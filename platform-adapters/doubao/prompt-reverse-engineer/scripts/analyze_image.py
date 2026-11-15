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

from _net import DownloadError, fetch_url

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
            data = fetch_url(source, timeout=args.timeout, max_bytes=args.max_bytes)
        except DownloadError as exc:
            print(f"错误：URL 下载失败：{exc}", file=sys.stderr)
            sys.exit(3)
        return data, source, "url"
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


def _num(value):
    """EXIF 数值统一转 float；解析失败返回 None。"""
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _fmt_num(value):
    """数值文本：整数不带小数点，其余保留两位。"""
    if value is None:
        return None
    if abs(value - round(value)) < 1e-6:
        return str(int(round(value)))
    return f"{value:.2f}".rstrip("0").rstrip(".")


def _exposure_str(seconds):
    """快门时间：≥1 秒写「2s」，其余写「1/125」。"""
    if seconds is None or seconds <= 0:
        return None
    if seconds >= 1:
        return f"{_fmt_num(seconds)}s"
    return f"1/{int(round(1 / seconds))}"


def focal_class(mm):
    """等效焦距粗略分级（只用于镜头语言提示）。"""
    if mm is None:
        return None
    if mm <= 18:
        return "超广角"
    if mm <= 35:
        return "广角"
    if mm <= 70:
        return "标准"
    if mm <= 135:
        return "中长焦"
    return "长焦"


def extract_exif(data: bytes):
    """读取 EXIF。lens 为结构化镜头参数；顶层键保持旧版兼容。

    注意：旧版把 37386（FocalLength，实际焦距）标成 focal_length_35mm，
    版本修正为 41989（FocalLengthIn35mmFilm，35mm 等效焦距），
    顶层同时保留 focal_length 与 focal_length_35mm 两个语义正确的键。
    """
    exif = {}
    lens = {}
    try:
        img = Image.open(io.BytesIO(data))
        info = img.getexif()

        def raw(tag_id):
            return info.get(tag_id)

        make, model = raw(271), raw(272)
        if make:
            exif["camera_make"] = str(make).strip()
            lens["camera_make"] = str(make).strip()
        if model:
            exif["camera_model"] = str(model).strip()
            lens["camera_model"] = str(model).strip()

        focal = _num(raw(37386))
        focal35 = _num(raw(41989))
        fnumber = _num(raw(33437))
        exposure = _num(raw(33434))
        shutter_apex = _num(raw(37377))
        lens_model = raw(42036)
        iso = raw(34855)

        if focal is not None:
            exif["focal_length"] = _fmt_num(focal)
            lens["focal_length_mm"] = _fmt_num(focal)
        if focal35 is not None:
            exif["focal_length_35mm"] = _fmt_num(focal35)
            lens["focal_length_35mm_eq"] = _fmt_num(focal35)
        if fnumber is not None:
            exif["aperture_fnumber"] = f"f/{_fmt_num(fnumber)}"
            lens["aperture_fnumber"] = f"f/{_fmt_num(fnumber)}"
        if exposure is not None:
            exif["exposure_time"] = _exposure_str(exposure)
            lens["exposure_time"] = _exposure_str(exposure)
        if shutter_apex is not None:
            # 37377 是 APEX 快门值，仅作兼容保留（换算请用 33434）
            exif["shutter_speed"] = _fmt_num(shutter_apex)
        if iso is not None:
            exif["iso"] = str(iso)
            lens["iso"] = str(iso)
        if lens_model:
            lens["lens_model"] = str(lens_model).strip()

        datetime_value, orientation = raw(306), raw(274)
        if datetime_value:
            exif["datetime"] = str(datetime_value)
        if orientation is not None:
            exif["orientation"] = str(orientation)
    except Exception:
        pass
    if lens:
        exif["lens"] = lens
    return exif


def detect_letterbox(bgr: np.ndarray):
    """检测黑边/白边信箱（letterbox / pillarbox）。"""
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    h, w = gray.shape

    def bar_count(means, stds):
        count = 0
        for mean, std in zip(means, stds):
            if std < 2.5 and (mean < 20 or mean > 235):
                count += 1
            else:
                break
        return count

    row_means = gray.mean(axis=1)
    row_stds = gray.std(axis=1)
    col_means = gray.mean(axis=0)
    col_stds = gray.std(axis=0)
    top = min(bar_count(row_means, row_stds), int(h * 0.3))
    bottom = min(bar_count(row_means[::-1], row_stds[::-1]), int(h * 0.3))
    left = min(bar_count(col_means, col_stds), int(w * 0.3))
    right = min(bar_count(col_means[::-1], col_stds[::-1]), int(w * 0.3))
    content_w = w - left - right
    content_h = h - top - bottom
    detected = any((top, bottom, left, right))
    return {
        "detected": bool(detected),
        "confidence": "high" if detected else "low",
        "top_px": int(top),
        "bottom_px": int(bottom),
        "left_px": int(left),
        "right_px": int(right),
        "content_aspect_ratio": aspect_ratio_str(content_w, content_h)
        if detected and content_w > 0 and content_h > 0 else None,
    }


def depth_of_field_hint(gray: np.ndarray):
    """中心与边缘的清晰度差异 → 景深提示（只是提示，不是测量）。"""
    h, w = gray.shape
    cy0, cy1 = int(h * 0.3), max(int(h * 0.7), 1)
    cx0, cx1 = int(w * 0.3), max(int(w * 0.7), 1)
    center = float(cv2.Laplacian(gray[cy0:cy1, cx0:cx1], cv2.CV_64F).var())
    band_h = max(int(h * 0.15), 1)
    band_w = max(int(w * 0.15), 1)
    crops = [
        gray[:band_h, :], gray[h - band_h:, :],
        gray[:, :band_w], gray[:, w - band_w:],
    ]
    border = float(np.mean(
        [cv2.Laplacian(crop, cv2.CV_64F).var() for crop in crops]))
    ratio = rounded(min(center / max(border, 1e-6), 999.0), 3)
    if ratio >= 3.0:
        hint = "浅景深（中心清晰、边缘虚化）"
    elif ratio <= 1.3:
        hint = "深景深（前后景都较清晰）"
    else:
        hint = "中等景深"
    return {"hint": hint, "confidence": "medium" if ratio >= 3.0 or ratio <= 1.3
            else "low", "center_laplacian": rounded(center, 2),
            "border_laplacian": rounded(border, 2), "ratio": ratio}


def shot_size_hint(face_boxes):
    """按人脸框高度占画面比例推断景别；没有人脸则不猜。"""
    if not face_boxes:
        return {"hint": None, "basis": "none", "confidence": "low"}
    height = max(box[3] for box in face_boxes)
    if height >= 0.5:
        hint = "特写"
    elif height >= 0.3:
        hint = "近景"
    elif height >= 0.15:
        hint = "中景"
    else:
        hint = "全景（人物偏小，环境为主）"
    return {"hint": hint, "basis": "face_box_height",
            "confidence": "medium" if height >= 0.15 else "low"}


def camera_angle_hint(face_boxes):
    """按人脸在画面中的纵向位置给出低置信机位提示。"""
    if not face_boxes:
        return {"hint": None, "basis": "none", "confidence": "low"}
    center_y = float(np.mean([box[1] + box[3] / 2 for box in face_boxes]))
    if center_y < 0.38:
        hint = "疑似仰拍/低机位（人脸偏画面上方）"
    elif center_y > 0.62:
        hint = "疑似俯拍/高机位（人脸偏画面下方）"
    else:
        hint = "平拍（人脸居中）"
    return {"hint": hint, "basis": "face_vertical_position", "confidence": "low"}


def key_light_hint(gray: np.ndarray):
    """画面四象限亮度 → 主光方向粗略提示。"""
    h, w = gray.shape
    mid_h, mid_w = h // 2, w // 2
    quads = {
        "左上": gray[:mid_h, :mid_w], "右上": gray[:mid_h, mid_w:],
        "左下": gray[mid_h:, :mid_w], "右下": gray[mid_h:, mid_w:],
    }
    means = {name: float(crop.mean()) for name, crop in quads.items()}
    bright = max(means, key=means.get)
    dark = min(means, key=means.get)
    if means[bright] - means[dark] < 12:
        return {"direction": "均匀光线（无明显主光方向）",
                "basis": "frame_quadrant_luminance", "confidence": "low"}
    return {"direction": f"{bright}偏亮，疑似主光来自{bright}",
            "basis": "frame_quadrant_luminance", "confidence": "low"}


def lens_hint(exif, dof):
    """镜头焦段提示：优先 EXIF，其次由景深推断（均标注依据）。"""
    lens = exif.get("lens") or {}
    focal35 = _num(lens.get("focal_length_35mm_eq"))
    focal = focal35 if focal35 is not None else _num(lens.get("focal_length_mm"))
    if focal is not None:
        return {"hint": focal_class(focal), "basis": "exif",
                "focal_mm": _fmt_num(focal),
                "confidence": "high" if focal35 is not None else "medium"}
    if dof["ratio"] >= 3.0:
        return {"hint": "疑似中长焦（浅景深）", "basis": "dof_inference",
                "focal_mm": None, "confidence": "low"}
    if dof["ratio"] <= 1.3:
        return {"hint": "疑似广角（深景深）", "basis": "dof_inference",
                "focal_mm": None, "confidence": "low"}
    return {"hint": None, "basis": "none", "focal_mm": None,
            "confidence": "low"}


def analyze_bgr(bgr: np.ndarray, data_size: int, pil_format: str, exif=None):
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

    # --- 实拍镜头反推提示（全部为近似信号，供 Agent 参考，不写入 Prompt 事实） ---
    dof = depth_of_field_hint(gray)
    hints = {
        "letterbox": detect_letterbox(bgr),
        "shot_size": shot_size_hint(face_boxes),
        "camera_angle": camera_angle_hint(face_boxes),
        "depth_of_field": dof,
        "lens": lens_hint(exif or {}, dof),
        "key_light": key_light_hint(gray),
    }
    hints["notes"] = [
        "景别/机位/焦段提示均来自确定性像素统计，只能作为初稿参考",
        "无法从画面确认的镜头参数请省略，不要编造光圈、快门、ISO",
    ]

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
        "shot_hints": hints,
    }


def main():
    parser = argparse.ArgumentParser(description="图片本地信号提取")
    parser.add_argument("input", help="输入：文件路径 | '-'=stdin | http(s) URL")
    parser.add_argument("-o", "--output", help="结果写入 JSON 文件（默认仅 stdout）")
    parser.add_argument("--max-size", type=int, default=4096,
                        help="处理前降采样的最大边长（默认 4096）")
    parser.add_argument("--timeout", type=float, default=15.0, help="URL 下载超时秒数")
    parser.add_argument("--max-bytes", type=int, default=64 * 1024 * 1024,
                        help="URL 下载大小上限（字节，默认 64 MiB；仅公网地址）")
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

    exif = extract_exif(data)
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
        "local_features": analyze_bgr(bgr, len(data), pil_format, exif),
    }
    envelope["local_features"]["meta"]["exif"] = exif
    out = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
