#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""视频本地信号提取脚本（prompt-reverse-engineer 技能组件）。

做镜头切分（相邻帧颜色直方图差）、关键帧抽取（JPEG 写临时目录，路径进 JSON 供
Agent Read 后做多模态语义分析）、运镜估计（Farneback 光流）、逐秒亮度曲线。
退出码：0 成功 / 1 用法错误 / 2 输入不可读 / 3 URL 下载失败 / 4 解码失败
"""
import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile

import cv2
import numpy as np

TOOL = "analyze_video.py"
SCHEMA_VERSION = "1.0"

SHOT_THRESHOLD = 0.35  # 直方图相关性距离阈值，超过即判镜头切点
HIST_BINS = [8, 8, 4]  # HSV 分桶
MIN_SHOT_SECONDS = 0.4  # 小于该时长的镜头与前一镜头合并
MOTION_SILENT = 0.02    # 光流均值低于该值判静止
MOTION_STRONG = 0.15    # 高于该值判强烈运动


def load_bytes(args):
    source = args.input
    if source == "-":
        data = sys.stdin.buffer.read()
        if not data:
            print("错误：stdin 无输入", file=sys.stderr)
            sys.exit(2)
        return data, source, "stdin"
    if re.match(r"^https?://", source):
        try:
            import requests
        except ImportError:
            print("错误：URL 输入需要 requests 库", file=sys.stderr)
            sys.exit(3)
        try:
            resp = requests.get(source, timeout=args.timeout)
            resp.raise_for_status()
        except Exception as exc:
            print(f"错误：URL 下载失败：{exc}", file=sys.stderr)
            sys.exit(3)
        return resp.content, source, "url"
    try:
        with open(source, "rb") as fh:
            return fh.read(), source, "file"
    except OSError as exc:
        print(f"错误：文件不可读：{exc}", file=sys.stderr)
        sys.exit(2)


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


def analyze(video_path: str, data_size: int, max_seconds: float, stride: int,
            keyframes_dir: str):
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

    frame_idx = 0
    prev_hist = None
    prev_gray = None
    shot_frames = []  # 每个镜头的帧索引列表
    frame_infos = []  # (frame_idx, seconds, brightness)
    os.makedirs(keyframes_dir, exist_ok=True)  # 确定性目录（幂等：同输入同路径，内容覆盖写）
    sampled_gray_cache = {}

    while True:
        ok, frame = cap.read()
        if not ok or frame_idx >= frame_count:
            break
        if frame_idx % stride == 0:
            hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
            hist = hist_of(hsv)
            if prev_hist is not None:
                diff = cv2.compareHist(prev_hist, hist, cv2.HISTCMP_CORREL)
                distance = 1.0 - diff
                if distance > SHOT_THRESHOLD:
                    shot_frames.append([])  # 新镜头
            prev_hist = hist
            if not shot_frames:
                shot_frames.append([])
            shot_frames[-1].append(frame_idx)
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sampled_gray_cache[frame_idx] = gray
            frame_infos.append((frame_idx, frame_idx / fps, float(gray.mean())))
            prev_gray = gray
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

    shot_list = []
    for i, sf in enumerate(merged):
        start_s = round(sf[0] / fps, 3)
        end_s = round(sf[-1] / fps, 3)
        mid = sf[len(sf) // 2]
        mid_gray = sampled_gray_cache[mid]
        bgr = cv2.cvtColor(mid_gray, cv2.COLOR_GRAY2BGR)
        # 关键帧取中点帧彩色原图：需要重读（用 seek 回读保证颜色正确）
        key_path = os.path.join(keyframes_dir, f"shot_{i + 1:02d}_keyframe.jpg")
        cap2 = cv2.VideoCapture(video_path)
        cap2.set(cv2.CAP_PROP_POS_FRAMES, mid)
        ok2, frame2 = cap2.read()
        cap2.release()
        if not ok2:
            frame2 = cv2.cvtColor(mid_gray, cv2.COLOR_GRAY2BGR)
        cv2.imwrite(key_path, frame2, [cv2.IMWRITE_JPEG_QUALITY, 85])
        shot_hsv = cv2.cvtColor(frame2, cv2.COLOR_BGR2HSV)
        shot_hist = hist_of(shot_hsv)
        dom = np.unravel_index(int(np.argmax(shot_hist)), HIST_BINS)
        h_val, s_val, v_val = (d * 255 // (b - 1) for d, b in zip(dom, HIST_BINS))
        hsv_px = np.uint8([[[h_val, s_val, v_val]]])
        bgr_px = cv2.cvtColor(hsv_px, cv2.COLOR_HSV2BGR)[0][0]
        dom_hex = "#%02X%02X%02X" % (int(bgr_px[2]), int(bgr_px[1]), int(bgr_px[0]))
        # 运镜估计：用镜头首帧与尾帧
        first_gray = sampled_gray_cache[sf[0]]
        motion_level, motion_direction, zoom = estimate_motion(first_gray, mid_gray)
        if motion_level < MOTION_SILENT:
            shot_type = "静止"
        elif motion_level > MOTION_STRONG:
            shot_type = "强烈运动"
        else:
            shot_type = "镜头运动"
        shot_list.append({
            "index": i + 1,
            "start_s": start_s,
            "end_s": end_s,
            "duration_s": round(end_s - start_s, 3),
            "keyframe_path": os.path.abspath(key_path),
            "avg_brightness": rounded(mid_gray.mean()),
            "dominant_color_hex": dom_hex,
            "motion_level": rounded(motion_level),
            "motion_direction": motion_direction,
            "zoom": zoom,
            "shot_type_hint": shot_type,
        })

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
            "keyframes_dir": os.path.abspath(keyframes_dir),
        },
        "shots": {"shot_count": len(shot_list), "shot_list": shot_list},
        "brightness_curve": brightness_curve,
    }


def main():
    parser = argparse.ArgumentParser(description="视频本地信号提取（镜头切分/关键帧/运镜）")
    parser.add_argument("input", help="输入：文件路径 | '-'=stdin | http(s) URL")
    parser.add_argument("-o", "--output", help="结果写入 JSON 文件（默认仅 stdout）")
    parser.add_argument("--max-seconds", type=float, default=120.0,
                        help="最多分析的时长（秒），超长视频截断抽样")
    parser.add_argument("--stride", type=int, default=1, help="抽帧步长")
    parser.add_argument("--timeout", type=float, default=15.0, help="URL 下载超时秒数")
    args = parser.parse_args()

    data, source, kind = load_bytes(args)
    sha = hashlib.sha256(data).hexdigest()
    tmp_dir = os.path.join(tempfile.gettempdir(), f"pre_video_{sha[:8]}")
    os.makedirs(tmp_dir, exist_ok=True)
    video_path = os.path.join(tmp_dir, "input_video.bin")
    with open(video_path, "wb") as fh:
        fh.write(data)
    keyframes_dir = os.path.join(tempfile.gettempdir(), f"pre_keyframes_{sha[:8]}")

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "modality": "video",
        "input": {
            "source": source,
            "kind": kind,
            "sha256": sha,
            "size_bytes": len(data),
        },
        "local_features": analyze(video_path, len(data), args.max_seconds, args.stride,
                                   keyframes_dir),
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
