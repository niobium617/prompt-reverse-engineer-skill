#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频本地信号提取脚本（prompt-reverse-engineer 技能组件）。

做镜头切分（相邻帧颜色直方图差）、关键帧抽取（每镜首/中/末三帧 JPEG 写工作目录，
路径进 JSON 供 Agent Read 后做多模态语义分析）、运镜估计（Farneback 光流）、
逐秒亮度曲线，以及实拍镜头反推用的确定性提示（景别/机位/运镜轴/色彩/黑边）。

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


def color_block(frame):
    """单帧色彩统计：主色（4bit 固定分桶，幂等）、亮度、饱和度、色温。"""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
    small = cv2.resize(frame, (64, 64), interpolation=cv2.INTER_AREA)
    bins = {}
    for row in small.reshape(-1, 3):
        key = (int(row[0]) >> 4, int(row[1]) >> 4, int(row[2]) >> 4)
        bins[key] = bins.get(key, 0) + 1
    total_px = small.shape[0] * small.shape[1]
    ranked = sorted(bins.items(), key=lambda kv: (-kv[1], kv[0]))
    dominant_colors = []
    for (br, bg, bb), cnt in ranked[:3]:
        rep = ((br << 4) | 8, (bg << 4) | 8, (bb << 4) | 8)
        dominant_colors.append({
            "hex": "#%02X%02X%02X" % (rep[2], rep[1], rep[0]),
            "ratio": round(cnt / total_px, 4),
        })
    b_mean = float(frame[:, :, 0].mean())
    r_mean = float(frame[:, :, 2].mean())
    if b_mean - r_mean > 12:
        temperature = "冷"
    elif r_mean - b_mean > 12:
        temperature = "暖"
    else:
        temperature = "中性"
    saturation_mean = rounded(hsv[:, :, 1].mean())
    return {
        "dominant_hex": dominant_color_hex(hsv),
        "dominant_colors": dominant_colors,
        "brightness_mean": rounded(gray.mean()),
        "saturation_mean": saturation_mean,
        "color_temperature_hint": temperature,
        "is_grayscale": bool(saturation_mean < 5.0),
    }


def detect_letterbox(gray):
    """检测画幅黑边/白边（只在首帧运行一次）。"""
    h, w = gray.shape

    def bar_count(means, stds, limit):
        count = 0
        for mean, std in zip(means, stds):
            if std < 2.5 and (mean <= 20 or mean >= 235):
                count += 1
            else:
                break
        return min(count, limit)

    row_means, row_stds = gray.mean(axis=1), gray.std(axis=1)
    col_means, col_stds = gray.mean(axis=0), gray.std(axis=0)
    top = bar_count(row_means, row_stds, int(h * 0.3))
    bottom = bar_count(row_means[::-1], row_stds[::-1], int(h * 0.3))
    left = bar_count(col_means, col_stds, int(w * 0.3))
    right = bar_count(col_means[::-1], col_stds[::-1], int(w * 0.3))
    detected = any((top, bottom, left, right))
    return {
        "detected": bool(detected),
        "top_px": int(top), "bottom_px": int(bottom),
        "left_px": int(left), "right_px": int(right),
    }


_FACE_CASCADE = None


def face_hints(frame):
    """人脸检测 → 景别/机位提示（Haar，静默降级）。"""
    global _FACE_CASCADE
    try:
        if _FACE_CASCADE is None:
            _FACE_CASCADE = cv2.CascadeClassifier(
                cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
        h, w = gray.shape
        small = cv2.resize(gray, (256, max(int(256 * h / w), 1)))
        found = _FACE_CASCADE.detectMultiScale(small, 1.1, 4)
    except Exception:
        found = []
    if len(found) == 0:
        return {
            "face_count": 0,
            "shot_size": {"hint": None, "basis": "none", "confidence": "low"},
            "camera_angle": {"hint": None, "basis": "none", "confidence": "low"},
        }
    boxes = [[fx / small.shape[1], fy / small.shape[0],
              fw / small.shape[1], fh / small.shape[0]] for fx, fy, fw, fh in found]
    height = max(box[3] for box in boxes)
    if height >= 0.5:
        size_hint = "特写"
    elif height >= 0.3:
        size_hint = "近景"
    elif height >= 0.15:
        size_hint = "中景"
    else:
        size_hint = "全景（人物偏小，环境为主）"
    center_y = float(np.mean([box[1] + box[3] / 2 for box in boxes]))
    if center_y < 0.38:
        angle_hint = "疑似仰拍/低机位（人脸偏画面上方）"
    elif center_y > 0.62:
        angle_hint = "疑似俯拍/高机位（人脸偏画面下方）"
    else:
        angle_hint = "平拍（人脸居中）"
    return {
        "face_count": int(len(found)),
        "shot_size": {"hint": size_hint, "basis": "face_box_height",
                      "confidence": "medium" if height >= 0.15 else "low"},
        "camera_angle": {"hint": angle_hint, "basis": "face_vertical_position",
                         "confidence": "low"},
    }


def motion_hint(level, direction, zoom):
    """光流 → 运镜轴与提示。轴代号：Z=推拉 / X=水平 / Y=垂直。"""
    if level < MOTION_SILENT:
        return {"axes": [], "hint": "固定", "confidence": "medium",
                "basis": "optical_flow"}
    axes, moves = [], []
    if zoom == "推近":
        axes.append("Z")
        moves.append("推")
    elif zoom == "拉远":
        axes.append("Z")
        moves.append("拉")
    if direction in ("左移", "右移"):
        axes.append("X")
        if not moves:
            moves.append("摇")
    elif direction in ("上移", "下移"):
        axes.append("Y")
        if not moves:
            moves.append("升降")
    if not moves:
        # 光流有量但无方向：强运动按手持晃动处理，弱运动仍视为固定
        moves.append("手持" if level > MOTION_STRONG else "固定")
    return {
        "axes": axes[:2],
        "hint": "+".join(moves[:2]),
        "confidence": "medium" if len(axes) <= 1 else "low",
        "basis": "optical_flow（无法区分摇镜与移镜，需人工确认）",
    }


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

    # 只登记需要的帧：每镜首帧（运镜基准）、中点帧（关键帧）、末帧（运镜终点）
    wanted = {}
    for i, sf in enumerate(merged):
        for idx, tag in ((sf[0], "first"), (sf[len(sf) // 2], "mid"),
                         (sf[-1], "last")):
            wanted.setdefault(idx, set()).add((i, tag))

    records = {}
    first_gray = {}
    frame_paths = {}
    mid_stats = {}
    mid_hints = {}
    letterbox = None
    last_frame = None
    last_gray = None

    def frame_path(i, tag):
        name = "keyframe" if tag == "mid" else tag
        return os.path.abspath(os.path.join(
            keyframes_dir, f"shot_{i + 1:02d}_{name}.jpg"))

    def record_shot(i, frame, gray, base_gray):
        sf = merged[i]
        start_s = round(sf[0] / fps, 3)
        end_s = round(sf[-1] / fps, 3)
        stats = mid_stats.get(i) or color_block(frame)
        hints = mid_hints.get(i) or face_hints(frame)
        paths = frame_paths.get(i, {})
        key_path = paths.get("mid") or frame_path(i, "mid")
        motion_level, motion_direction, zoom = estimate_motion(base_gray, gray)
        if motion_level < MOTION_SILENT:
            shot_type = "静止"
        elif motion_level > MOTION_STRONG:
            shot_type = "强烈运动"
        else:
            shot_type = "镜头运动"
        move = motion_hint(motion_level, motion_direction, zoom)
        records[i] = {
            "index": i + 1,
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": round(end_s - start_s, 3),
            "keyframe_path": key_path,
            "first_frame_path": paths.get("first") or key_path,
            "last_frame_path": paths.get("last") or key_path,
            "avg_brightness": stats["brightness_mean"],
            "dominant_color_hex": stats["dominant_hex"],
            "color": stats,
            "face_count": hints["face_count"],
            "shot_size_hint": hints["shot_size"],
            "camera_angle_hint": hints["camera_angle"],
            "motion_level": rounded(motion_level),
            "motion_direction": motion_direction,
            "zoom": zoom,
            "motion_axes": move["axes"],
            "camera_move_hint": move,
            "shot_type_hint": shot_type,
            "letterbox": letterbox or {"detected": False, "top_px": 0,
                                       "bottom_px": 0, "left_px": 0,
                                       "right_px": 0},
        }

    # 第二遍：顺序解码到目标帧，写首/中/末关键帧，末帧处收口运镜估计
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
                if letterbox is None:
                    letterbox = detect_letterbox(gray)
                for i, tag in sorted(wanted[frame_idx]):
                    path = frame_path(i, tag)
                    cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
                    frame_paths.setdefault(i, {})[tag] = path
                    if tag == "first":
                        first_gray[i] = gray
                    elif tag == "mid":
                        mid_stats[i] = color_block(frame)
                        mid_hints[i] = face_hints(frame)
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
            "letterbox": letterbox or {"detected": False, "top_px": 0,
                                       "bottom_px": 0, "left_px": 0,
                                       "right_px": 0},
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
