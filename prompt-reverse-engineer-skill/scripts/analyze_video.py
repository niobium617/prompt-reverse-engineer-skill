#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频本地信号提取脚本（prompt-reverse-engineer 技能组件）。

做镜头切分（相邻帧颜色直方图差）、关键帧抽取（JPEG 写工作目录，路径进 JSON 供
Agent Read 后做多模态语义分析）、运镜估计（Farneback 光流）、逐秒亮度曲线。

资源约定：
  - 单次解码只保留当前帧与统计量，不缓存全部抽样帧；
  - 镜头切分与关键帧抽取分两遍顺序解码，避免逐镜头 seek/重开；
  - 本地文件直接交给 OpenCV 读取，不复制、不整文件入内存；
  - stdin / URL 先落盘到工作目录，分析结束后删除副本；
  - 关键帧是输出产物，保留在 <workdir>/video_<sha8>/keyframes/ 供 Agent 读取。

退出码：0 成功 / 1 用法错误 / 2 输入不可读 / 3 下载失败或超过体积上限 / 4 解码失败
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from pathlib import Path

import cv2
import numpy as np

from _net import DownloadError, fetch_url

TOOL = "analyze_video.py"
SCHEMA_VERSION = "1.0"

SHOT_THRESHOLD = 0.35  # 直方图相关性距离阈值，超过即判镜头切点
HIST_BINS = [8, 8, 4]  # HSV 分桶
MIN_SHOT_SECONDS = 0.4  # 小于该时长的镜头与前一镜头合并
MOTION_SILENT = 0.02    # 光流均值低于该值判静止
MOTION_STRONG = 0.15    # 高于该值判强烈运动
CHUNK = 64 * 1024


class InputTooLarge(Exception):
    """输入超过 --max-bytes 上限。"""


def default_workdir():
    """仓库内运行时用 <repo>/.tmp；安装态回退系统临时目录。"""
    env = os.environ.get("APS_WORKDIR")
    if env:
        return Path(env)
    repo = Path(__file__).resolve().parents[2]
    if (repo / ".git").exists() or (repo / "README.md").is_file():
        return repo / ".tmp"
    return Path(tempfile.gettempdir()) / "aps_video"


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_limited(stream, dest, max_bytes):
    """把流写入 dest，同时计算 sha256；超过上限抛 InputTooLarge。"""
    digest = hashlib.sha256()
    total = 0
    with open(dest, "wb") as out:
        while True:
            chunk = stream.read(CHUNK)
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise InputTooLarge(f"输入超过大小上限 {max_bytes} 字节")
            digest.update(chunk)
            out.write(chunk)
    return digest.hexdigest(), total


def prepare_input(args, base):
    """返回 (video_path, source, kind, sha256, size_bytes, temp_copy)。

    temp_copy 是本次运行创建的临时视频副本，分析结束后删除；本地文件为 None。
    """
    source = args.input
    if source == "-":
        incoming = tempfile.NamedTemporaryFile(
            dir=base, prefix="incoming_", suffix=".bin", delete=False)
        incoming.close()
        try:
            sha, size = copy_limited(sys.stdin.buffer, incoming.name, args.max_bytes)
        except InputTooLarge as exc:
            os.unlink(incoming.name)
            print(f"错误：{exc}", file=sys.stderr)
            sys.exit(3)
        except OSError as exc:
            os.unlink(incoming.name)
            print(f"错误：stdin 读取失败：{exc}", file=sys.stderr)
            sys.exit(2)
        if size == 0:
            os.unlink(incoming.name)
            print("错误：stdin 无输入", file=sys.stderr)
            sys.exit(2)
        return _settle_temp(incoming.name, base, sha, source, "stdin", size)

    if re.match(r"^https?://", source):
        try:
            data = fetch_url(source, timeout=args.timeout, max_bytes=args.max_bytes)
        except DownloadError as exc:
            print(f"错误：URL 下载失败：{exc}", file=sys.stderr)
            sys.exit(3)
        sha = hashlib.sha256(data).hexdigest()
        incoming = tempfile.NamedTemporaryFile(
            dir=base, prefix="incoming_", suffix=".bin", delete=False)
        with incoming:
            incoming.write(data)
        return _settle_temp(incoming.name, base, sha, source, "url", len(data))

    path = Path(source)
    try:
        size = path.stat().st_size
    except OSError as exc:
        print(f"错误：文件不可读：{exc}", file=sys.stderr)
        sys.exit(2)
    if size > args.max_bytes:
        print(f"错误：输入超过大小上限 {args.max_bytes} 字节（实际 {size}）",
              file=sys.stderr)
        sys.exit(3)
    try:
        sha = sha256_file(path)
    except OSError as exc:
        print(f"错误：文件不可读：{exc}", file=sys.stderr)
        sys.exit(2)
    return str(path), source, "file", sha, size, None


def _settle_temp(incoming_path, base, sha, source, kind, size):
    """把临时副本移到与本输入 sha 绑定的确定性目录，返回最终路径。"""
    run_dir = Path(base) / f"video_{sha[:8]}"
    run_dir.mkdir(parents=True, exist_ok=True)
    target = run_dir / "input.bin"
    os.replace(incoming_path, target)
    return str(target), source, kind, sha, size, target


def rounded(value, ndigits=4):
    return round(float(value), ndigits)


def aspect_ratio_str(w, h):
    g = math.gcd(int(w), int(h))
    return f"{int(w) // g}:{int(h) // g}"


def hist_of(hsv):
    hist = cv2.calcHist([hsv], [0, 1, 2], None, HIST_BINS,
                        [0, 180, 0, 256, 0, 256])
    cv2.normalize(hist, hist)
    return hist


def estimate_motion(prev_gray, curr_gray):
    """返回 (motion_level, direction, zoom)。降采样 256 宽，Farneback 光流。"""
    scale = 256.0 / prev_gray.shape[1]
    prev = cv2.resize(prev_gray, (256, int(prev_gray.shape[0] * scale)))
    curr = cv2.resize(curr_gray, (256, int(curr_gray.shape[0] * scale)))
    flow = cv2.calcOpticalFlowFarneback(
        prev, curr, None, 0.5, 3, 15, 3, 5, 1.2, 0
    )
    h, w = flow.shape[:2]
    fy, fx = np.mgrid[:h, :w]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    radial_x = (fx - cx) / max(cx, 1.0)
    radial_y = (fy - cy) / max(cy, 1.0)
    radial_norm = np.sqrt(radial_x ** 2 + radial_y ** 2)
    radial_norm[radial_norm < 1e-6] = 1e-6
    radial_x /= radial_norm
    radial_y /= radial_norm
    radial_comp = float((flow[:, :, 0] * radial_x + flow[:, :, 1] * radial_y).mean())
    tangential_comp = float((flow[:, :, 0] * (-radial_y) + flow[:, :, 1] * radial_x).mean())
    mag = float(np.sqrt(flow[:, :, 0] ** 2 + flow[:, :, 1] ** 2).mean())
    level = min(round(mag / 2.0, 4), 1.0)  # 归一化到 0-1（经验缩放）

    if level < MOTION_SILENT:
        direction, zoom = "无", "无"
    else:
        ax, ay = float(flow[:, :, 0].mean()), float(flow[:, :, 1].mean())
        if abs(ax) > abs(ay) * 1.5:
            direction = "右移" if ax > 0 else "左移"
        elif abs(ay) > abs(ax) * 1.5:
            direction = "下移" if ay > 0 else "上移"
        else:
            direction = "无"
        if abs(radial_comp) > abs(tangential_comp) * 1.5 and abs(radial_comp) > 0.05:
            zoom = "拉远" if radial_comp > 0 else "推近"
        else:
            zoom = "无"
    return level, direction, zoom


def dominant_color_hex(hsv):
    hist = hist_of(hsv)
    dom = np.unravel_index(int(np.argmax(hist)), HIST_BINS)
    h_val, s_val, v_val = (d * 255 // (b - 1) for d, b in zip(dom, HIST_BINS))
    hsv_px = np.uint8([[[h_val, s_val, v_val]]])
    bgr_px = cv2.cvtColor(hsv_px, cv2.COLOR_HSV2BGR)[0][0]
    return "#%02X%02X%02X" % (int(bgr_px[2]), int(bgr_px[1]), int(bgr_px[0]))


def analyze(video_path: str, data_size: int, max_seconds: float, stride: int,
            keyframes_dir: str):
    keyframes_dir = os.path.abspath(str(keyframes_dir))
    os.makedirs(keyframes_dir, exist_ok=True)
    # 同一输入重复运行时清掉上次的关键帧，避免 stride/时长变化留下多余文件
    for stale in Path(keyframes_dir).glob("shot_*.jpg"):
        stale.unlink()

    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("错误：无法解码为视频", file=sys.stderr)
        sys.exit(4)
    fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
    frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
    width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)
    height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)
    duration_s = frame_count / fps if fps > 0 else 0.0
    fourcc_int = int(cap.get(cv2.CAP_PROP_FOURCC))
    fourcc = "".join(chr((fourcc_int >> (8 * i)) & 0xFF) for i in range(4)).strip()
    truncated = False
    if duration_s > max_seconds:
        frame_count = int(max_seconds * fps)
        truncated = True

    # 第一遍：只算直方图差与亮度，不保留帧数据
    frame_idx = 0
    prev_hist = None
    shot_frames = []  # 每个镜头的帧索引列表
    frame_infos = []  # (frame_idx, seconds, brightness)
    while True:
        ok, frame = cap.read()
        if not ok or frame_idx >= frame_count:
            break
        if frame_idx % stride == 0:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = hist_of(hsv)
            if prev_hist is not None:
                distance = 1.0 - cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                if distance > SHOT_THRESHOLD:
                    shot_frames.append([])  # 新镜头
            prev_hist = hist
            if not shot_frames:
                shot_frames.append([])
            shot_frames[-1].append(frame_idx)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            frame_infos.append((frame_idx, frame_idx / fps, float(gray.mean())))
        frame_idx += 1
    cap.release()

    if not shot_frames:
        print("错误：视频无有效帧", file=sys.stderr)
        sys.exit(4)

    # 合并过短镜头（与前一镜头）
    merged = [shot_frames[0]]
    for sf in shot_frames[1:]:
        dur = (sf[-1] - sf[0]) / fps
        if dur < MIN_SHOT_SECONDS and merged:
            merged[-1].extend(sf)
        else:
            merged.append(sf)
    merged = [sf for sf in merged if sf]

    # 只登记需要取色的帧：每镜头首帧（运镜基准）与中点帧（关键帧）
    wanted = {}
    for i, sf in enumerate(merged):
        wanted.setdefault(sf[0], set()).add((i, "first"))
        wanted.setdefault(sf[len(sf) // 2], set()).add((i, "mid"))

    records = {}
    first_gray = {}
    last_frame = None
    last_gray = None

    def record_shot(i, frame, gray, base_gray):
        sf = merged[i]
        start_s = round(sf[0] / fps, 3)
        end_s = round(sf[-1] / fps, 3)
        key_path = os.path.join(keyframes_dir, f"shot_{i + 1:02d}_keyframe.jpg")
        cv2.imwrite(key_path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
        dom_hex = dominant_color_hex(cv2.cvtColor(frame, cv2.COLOR_BGR2HSV))
        motion_level, motion_direction, zoom = estimate_motion(base_gray, gray)
        if motion_level < MOTION_SILENT:
            shot_type = "静止"
        elif motion_level > MOTION_STRONG:
            shot_type = "强烈运动"
        else:
            shot_type = "镜头运动"
        records[i] = {
            "index": i + 1,
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": round(end_s - start_s, 3),
            "keyframe_path": os.path.abspath(key_path),
            "avg_brightness": rounded(gray.mean()),
            "dominant_color_hex": dom_hex,
            "motion_level": rounded(motion_level),
            "motion_direction": motion_direction,
            "zoom": zoom,
            "shot_type_hint": shot_type,
        }

    # 第二遍：顺序解码到目标帧，取首帧灰度与中点彩色帧
    cap = cv2.VideoCapture(video_path)
    if not cap.isOpened():
        print("错误：无法解码为视频", file=sys.stderr)
        sys.exit(4)
    frame_idx = 0
    try:
        while True:
            ok, frame = cap.read()
            if not ok or frame_idx >= frame_count:
                break
            if frame_idx % stride == 0 and frame_idx in wanted:
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                last_frame, last_gray = frame, gray
                for i, tag in sorted(wanted[frame_idx]):
                    if tag == "first":
                        first_gray[i] = gray
                    else:
                        record_shot(i, frame, gray, first_gray.pop(i, gray))
            frame_idx += 1
    finally:
        cap.release()

    # 解码异常导致漏帧时用最后一个成功帧兜底，保证输出结构完整
    for i in range(len(merged)):
        if i not in records:
            if last_frame is None:
                print("错误：视频无可解码帧", file=sys.stderr)
                sys.exit(4)
            record_shot(i, last_frame, last_gray, first_gray.pop(i, last_gray))

    shot_list = [records[i] for i in range(len(merged))]

    # 逐秒亮度曲线
    brightness_curve = []
    sec = 0
    bucket = []
    for _, seconds, brightness in frame_infos:
        while seconds >= sec + 1.0 and bucket:
            brightness_curve.append(rounded(sum(bucket) / len(bucket), 2))
            bucket = []
            sec += 1
        bucket.append(brightness)
    if bucket:
        brightness_curve.append(rounded(sum(bucket) / len(bucket), 2))

    return {
        "meta": {
            "duration_s": rounded(duration_s),
            "frame_count": int(frame_count),
            "fps": rounded(fps, 2),
            "width": int(width),
            "height": int(height),
            "aspect_ratio": aspect_ratio_str(width, height) if width and height else "?",
            "fourcc": fourcc or "unknown",
            "file_size": int(data_size),
            "truncated": truncated,
            "keyframes_dir": keyframes_dir,
        },
        "shots": {"shot_count": len(shot_list), "shot_list": shot_list},
        "brightness_curve": brightness_curve,
    }


def main():
    parser = argparse.ArgumentParser(description="视频本地信号提取（镜头切分/关键帧/运镜）")
    parser.add_argument("input", help="输入：文件路径 | '-'=stdin | http(s) URL")
    parser.add_argument("-o", "--output", help="结果写入 JSON 文件（默认仅 stdout）")
    parser.add_argument("--max-seconds", type=float, default=120.0,
                        help="最多分析的时长（秒）；超长视频只取前 N 秒，不做跨片抽样")
    parser.add_argument("--stride", type=int, default=1, help="抽帧步长")
    parser.add_argument("--timeout", type=float, default=15.0, help="URL 下载超时秒数")
    parser.add_argument("--max-bytes", type=int, default=512 * 1024 * 1024,
                        help="输入大小上限（字节，默认 512 MiB；本地/URL/stdin 均生效）")
    parser.add_argument("--workdir", default=None,
                        help="工作目录（默认仓库 .tmp/，安装态回退系统临时目录）；"
                             "关键帧写入 <workdir>/video_<sha8>/keyframes/")
    args = parser.parse_args()

    base = Path(args.workdir) if args.workdir else default_workdir()
    try:
        base.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        if args.workdir:
            print(f"错误：工作目录不可用：{exc}", file=sys.stderr)
            sys.exit(2)
        base = Path(tempfile.gettempdir()) / "aps_video"
        base.mkdir(parents=True, exist_ok=True)

    video_path, source, kind, sha, size, temp_copy = prepare_input(args, base)
    keyframes_dir = base / f"video_{sha[:8]}" / "keyframes"

    try:
        local_features = analyze(video_path, size, args.max_seconds, args.stride,
                                 str(keyframes_dir))
    finally:
        if temp_copy is not None:
            try:
                os.unlink(temp_copy)
            except OSError:
                pass

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "modality": "video",
        "input": {
            "source": source,
            "kind": kind,
            "sha256": sha,
            "size_bytes": size,
        },
        "local_features": local_features,
    }
    out = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
