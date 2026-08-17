#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""叙事文本场景切分信号脚本（prompt-reverse-engineer 技能组件）。

只做本地可计算的确定性信号，无语义判断：
  - detected_format：script（检测到剧本场次标记）/ prose（散文叙事）
  - scene_markers：剧本场次标记行（行号 + 文本 + 识别类型）
  - scene_candidates：散文按叙事块切出的候选段落（含时间/地点提示词命中）
最终场景划分（合并/细分/定名）由 Agent 语义完成，本脚本只提供信号。
输出统一 JSON 信封供 Agent 消费。
退出码：0 成功 / 1 用法错误 / 2 输入不可读 / 3 URL 下载失败 / 4 解码失败或空输入
幂等约定：同输入两次运行输出逐字节一致（不写时间戳、不用随机数、键排序输出）。
"""
import argparse
import hashlib
import json
import re
import sys

TOOL = "analyze_scenes.py"
SCHEMA_VERSION = "1.0"

QUOTE_RE = re.compile(r"[“”‘’\"']")

# ---- 剧本场次标记（行首） ----
SCENE_CN_RE = re.compile(
    r"^\s*(?:第?\s*[\d一二三四五六七八九十百零〇]+\s*场|场\s*[\d一二三四五六七八九十百零〇]+)"
)
SCENE_CN_ENV_RE = re.compile(r"^\s*(?:内景|外景|日|夜|黄昏|清晨|夜晚|白天)[\s·,，。.．:：]")
SCENE_EN_RE = re.compile(r"^\s*(?:INT\.?\s*/\s*EXT\.?|INT\.?|EXT\.?|SCENE\s+\d+)", re.IGNORECASE)

MIN_MARKERS_FOR_SCRIPT = 2  # 全文至少 2 个标记行才判定为剧本

# ---- 散文场景切换提示词（段落内命中） ----
TIME_HINT_WORDS = [
    "清晨", "早上", "上午", "中午", "下午", "傍晚", "黄昏", "夜晚", "深夜",
    "第二天", "翌日", "次日", "此刻", "这时", "此时", "忽然", "突然", "与此同时",
    "日复一日", "多年后", "几个月后",
]
PLACE_HINT_WORDS = [
    "街道", "房间", "办公室", "咖啡厅", "餐厅", "公园", "医院", "车站",
    "机场", "酒店", "海边", "楼顶", "天台", "走廊", "电梯", "地下室", "教室",
]
PLACE_ACTION_RE = re.compile(r"(?:回到|来到|走进|走出|离开|抵达|赶往|前往)[^。！？；\n]{0,12}")


def load_bytes(args) -> bytes:
    """统一输入装载：本地路径 / '-'=stdin / http(s) URL。"""
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
        except Exception as exc:  # 网络/超时/HTTP 错误统一归类
            print(f"错误：URL 下载失败：{exc}", file=sys.stderr)
            sys.exit(3)
        return resp.content, source, "url"
    path = source
    try:
        with open(path, "rb") as fh:
            return fh.read(), path, "file"
    except OSError as exc:
        print(f"错误：文件不可读：{exc}", file=sys.stderr)
        sys.exit(2)


def decode_text(data: bytes) -> str:
    for enc in ("utf-8", "gbk"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            continue
    return data.decode("utf-8", errors="replace")


def scene_marker_type(line: str):
    """返回 (type, matched) 或 None。"""
    for regex, typ in ((SCENE_CN_RE, "cn_scene"),
                       (SCENE_CN_ENV_RE, "cn_env"),
                       (SCENE_EN_RE, "en_scene")):
        m = regex.match(line)
        if m:
            return typ, m.group(0)
    return None


def collect_markers(text: str):
    markers = []
    for i, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        hit = scene_marker_type(line)
        if hit:
            typ, matched = hit
            markers.append({"line": i, "text": line[:80], "type": typ,
                            "matched": matched})
    return markers


def hints_in(text: str):
    times = [w for w in TIME_HINT_WORDS if w in text]
    places = [w for w in PLACE_HINT_WORDS if w in text]
    place_actions = list(dict.fromkeys(PLACE_ACTION_RE.findall(text)))
    return times[:6], places[:6], place_actions[:3]


def collect_candidates(text: str):
    """散文：按空行切叙事块，输出候选（含时间/地点提示）。"""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    candidates = []
    for idx, block in enumerate(blocks, 1):
        times, places, actions = hints_in(block)
        quoted = len(QUOTE_RE.findall(block)) * 2
        total = max(len(block), 1)
        candidates.append({
            "index": idx,
            "first_line": block[:80].replace("\n", " "),
            "char_count": len(block),
            "dialogue_ratio": round(quoted / total, 4),
            "time_hints": times,
            "place_hints": places,
            "place_actions": actions,
        })
    return candidates


def analyze(text: str):
    markers = collect_markers(text)
    detected = "script" if len(markers) >= MIN_MARKERS_FOR_SCRIPT else "prose"
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text) if b.strip()]
    quoted = len(QUOTE_RE.findall(text)) * 2
    stats = {
        "total_chars": len(text),
        "paragraph_count": len(blocks),
        "dialogue_ratio": round(quoted / max(len(text), 1), 4),
        "marker_count": len(markers),
    }
    features = {
        "detected_format": detected,
        "scene_markers": markers,
        "scene_candidates": collect_candidates(text) if detected == "prose" else [],
        "stats": stats,
    }
    return features


def main():
    parser = argparse.ArgumentParser(description="叙事文本场景切分信号")
    parser.add_argument("input", help="输入：文件路径 | '-'=stdin | http(s) URL")
    parser.add_argument("-o", "--output", help="结果写入 JSON 文件（默认仅 stdout）")
    parser.add_argument("--timeout", type=float, default=15.0, help="URL 下载超时秒数")
    args = parser.parse_args()

    data, source, kind = load_bytes(args)
    text = decode_text(data)
    if not text.strip():
        print("错误：输入为空文本", file=sys.stderr)
        sys.exit(4)

    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "modality": "story",
        "input": {
            "source": source,
            "kind": kind,
            "sha256": hashlib.sha256(data).hexdigest(),
            "size_bytes": len(data),
        },
        "local_features": analyze(text),
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
