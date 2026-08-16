#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""图片本地信号提取脚本（prompt-reverse-engineer 技能组件）。

只做可计算信号：尺寸/EXIF/主色（固定 4bit 分桶，非 k-means，保证幂等）/构图/质量/人脸。
语义判断（这是什么主体、什么风格）由 Agent 多模态本体完成。
退出码：0 成功 / 1 用法错误 / 2 输入不可读 / 3 URL 下载失败 / 4 解码失败
"""
import argparse
import hashlib
import io
import json
import math
import re
import sys

import cv2
import numpy as np
from PIL import Image

TOOL = "analyze_image.py"
SCHEMA_VERSION = "1.0"

HUE_NAMES = [
    (0, 30, "红"), (30, 60, "橙"), (60, 90, "黄"), (90, 150, "绿"),
    (150, 180, "青"), (180, 250, "蓝"), (250, 290, "紫"), (290, 330, "品红"),
    (330, 360, "红"),
]


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


def extract_exif(data: bytes):
    exif = {}
    try:
        img = Image.open(io.BytesIO(data))
        info = img.getexif()
        mapping = {
            271: "camera_make",
            272: "camera_model",
            37386: "focal_length_35mm",
            33437: "aperture_fnumber",
            37377: "shutter_speed",
            34855: "iso",
            306: "datetime",
            274: "orientation",
        }
        for tag_id, name in mapping.items():
            if tag_id in info:
                value = info[tag_id]
                exif[name] = str(value)
    except Exception:
        pass
    return exif


def analyze_bgr(bgr: np.ndarray, data_size: int, pil_format: str):
    h, w = bgr.shape[:2]
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    hsv = cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)

    # --- 主色：降采样 64x64 + 每通道 4bit 固定分桶（幂等） ---
    small = cv2.resize(bgr, (64, 64), interpolation=cv2.INTER_AREA)
    bins = {}
    for row in small.reshape(-1, 3):
        key = (int(row[0]) >> 4, int(row[1]) >> 4, int(row[2]) >> 4)
        bins[key] = bins.get(key, 0) + 1
    total_px = small.shape[0] * small.shape[1]
    ranked = sorted(bins.items(), key=lambda kv: (-kv[1], kv[0]))
    dominant_colors = []
    for (br, bg, bb), cnt in ranked[:8]:
        rep = ((br << 4) | 8, (bg << 4) | 8, (bb << 4) | 8)  # 桶中点代表色
        dominant_colors.append({
            "hex": "#%02X%02X%02X" % (rep[2], rep[1], rep[0]),  # RGB 顺序
            "rgb": [int(rep[2]), int(rep[1]), int(rep[0])],
            "ratio": round(cnt / total_px, 4),
        })

    # --- 亮度 / 对比度 / 饱和度 / 色温 / 灰阶 ---
    brightness_mean = rounded(gray.mean())
    brightness_std = rounded(gray.std())
    contrast = rounded(float(gray.max() - gray.min()) / 255.0 * 100.0, 2)
    sat = hsv[:, :, 1]
    saturation_mean = rounded(sat.mean())
    is_grayscale = bool(saturation_mean < 5.0)
    b_mean, r_mean = float(bgr[:, :, 0].mean()), float(bgr[:, :, 2].mean())
    if b_mean - r_mean > 12:
        temperature = "冷"
    elif r_mean - b_mean > 12:
        temperature = "暖"
    else:
        temperature = "中性"
    hue_hist = np.zeros(12, dtype=np.int64)
    mask = (hsv[:, :, 1] > 40) & (hsv[:, :, 2] > 40)
    hue_vals = (hsv[:, :, 0][mask] // 15).astype(np.int64)
    for hv in hue_vals:
        hue_hist[min(int(hv), 11)] += 1
    hue_index = int(np.argmax(hue_hist)) * 15
    dominant_hue_name = "未知"
    for lo, hi, name in HUE_NAMES:
        if lo <= hue_index < hi:
            dominant_hue_name = name
            break

    # --- 构图 ---
    grid = cv2.resize(gray, (3, 3), interpolation=cv2.INTER_AREA).astype(np.float64)
    grid_luminance = [[rounded(v) for v in row] for row in grid]
    center_weight = rounded(grid[1, 1] / max(gray.mean(), 1.0), 4)
    canny = cv2.Canny(gray, 100, 200)
    edge_density = rounded(canny.mean() / 255.0, 4)
    sobel_x = cv2.Sobel(gray, cv2.CV_32F, 1, 0, ksize=3)
    sobel_y = cv2.Sobel(gray, cv2.CV_32F, 0, 1, ksize=3)
    mag = cv2.magnitude(sobel_x, sobel_y)
    hi_mask = (mag > 60).astype(np.uint8)
    n_labels, labels, stats, _ = cv2.connectedComponentsWithStats(hi_mask, 8)
    if n_labels > 1:
        largest = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
        x, y, bw, bh = stats[largest][:4]
        subject_center = [rounded((x + bw / 2) / w, 4), rounded((y + bh / 2) / h, 4)]
    else:
        subject_center = [0.5, 0.5]

    # --- 质量 ---
    laplacian_var = rounded(cv2.Laplacian(gray, cv2.CV_64F).var(), 2)
    overexposed = rounded(float((gray >= 250).mean()) * 100.0, 2)
    underexposed = rounded(float((gray <= 5).mean()) * 100.0, 2)

    # --- 人脸（Haar，静默降级） ---
    face_count = 0
    face_boxes = []
    try:
        cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        )
        small_gray = cv2.resize(gray, (256, max(int(256 * h / w), 1)))
        found = cascade.detectMultiScale(small_gray, 1.1, 4)
        face_count = int(len(found))
        for (fx, fy, fw, fh) in found:
            face_boxes.append([
                rounded(fx / small_gray.shape[1], 4),
                rounded(fy / small_gray.shape[0], 4),
                rounded(fw / small_gray.shape[1], 4),
                rounded(fh / small_gray.shape[0], 4),
            ])
    except Exception:
        pass

    return {
        "meta": {
            "width": int(w),
            "height": int(h),
            "aspect_ratio": aspect_ratio_str(w, h),
            "format": pil_format or "unknown",
            "file_size": int(data_size),
        },
        "color": {
            "dominant_colors": dominant_colors,
            "brightness_mean": brightness_mean,
            "brightness_std": brightness_std,
            "contrast": contrast,
            "saturation_mean": saturation_mean,
            "color_temperature_hint": temperature,
            "is_grayscale": is_grayscale,
            "dominant_hue_name": dominant_hue_name,
        },
        "composition": {
            "grid_luminance_3x3": grid_luminance,
            "center_weight": center_weight,
            "edge_density": edge_density,
            "subject_bbox_center": subject_center,
        },
        "quality": {
            "laplacian_variance": laplacian_var,
            "overexposed_ratio": overexposed,
            "underexposed_ratio": underexposed,
        },
        "faces": {"face_count": face_count, "face_boxes": face_boxes},
    }


def main():
    parser = argparse.ArgumentParser(description="图片本地信号提取")
    parser.add_argument("input", help="输入：文件路径 | '-'=stdin | http(s) URL")
    parser.add_argument("-o", "--output", help="结果写入 JSON 文件（默认仅 stdout）")
    parser.add_argument("--max-size", type=int, default=4096,
                        help="处理前降采样的最大边长（默认 4096）")
    parser.add_argument("--timeout", type=float, default=15.0, help="URL 下载超时秒数")
    args = parser.parse_args()

    data, source, kind = load_bytes(args)
    bgr = None
    pil_format = "unknown"
    try:
        pil = Image.open(io.BytesIO(data))
        pil_format = pil.format or "unknown"
        rgb = pil.convert("RGB")
        bgr = cv2.cvtColor(np.array(rgb), cv2.COLOR_RGB2BGR)
    except Exception:
        arr = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if arr is not None:
            bgr = arr
    if bgr is None:
        print("错误：无法解码为图片", file=sys.stderr)
        sys.exit(4)

    h, w = bgr.shape[:2]
    max_dim = max(h, w)
    if max_dim > args.max_size:
        scale = args.max_size / max_dim
        bgr = cv2.resize(
            bgr, (max(int(w * scale), 1), max(int(h * scale), 1)),
            interpolation=cv2.INTER_AREA,
        )

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "modality": "image",
        "input": {
            "source": source,
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        },
        "local_features": analyze_bgr(bgr, len(data), pil_format),
    }
    envelope["local_features"]["meta"]["exif"] = extract_exif(data)
    out = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
