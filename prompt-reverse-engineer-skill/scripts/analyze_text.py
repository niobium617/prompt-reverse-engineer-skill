#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""文本确定性统计脚本（prompt-reverse-engineer 技能组件）。

只做本地可计算的规则统计，无语义判断。输出统一 JSON 信封供 Agent 消费。
退出码：0 成功 / 1 用法错误 / 2 输入不可读 / 3 URL 下载失败 / 4 解码失败
幂等约定：同输入两次运行输出逐字节一致（不写时间戳、不用随机数、键排序输出）。
"""
import argparse
import hashlib
import json
import re
import sys
from collections import Counter

TOOL = "analyze_text.py"
SCHEMA_VERSION = "1.0"

CJK_RE = re.compile(r"[一-鿿]")
LATIN_RE = re.compile(r"[A-Za-z]")
SENTENCE_SPLIT_RE = re.compile(r"[。！？!?；;\n]+")
WORD_RE = re.compile(r"[A-Za-z0-9]+|[一-鿿]{2}")
QUOTE_RE = re.compile(r"[“”‘’\"']")
EMOJI_RE = re.compile(
    "[\U0001F000-\U0001FAFF☀-➿⬀-⯿️]"
)
UNIT_RE = re.compile(r"\d+\s*(%|％|字|词|words|个|条|秒|分钟|元|块)")
CN_FILLERS = ["很", "非常", "真的", "其实", "然后", "就是", "特别", "超级"]
EN_FILLERS = ["really", "very", "actually", "just", "so", "totally"]

CN_STOPWORDS = {
    "的", "了", "是", "在", "和", "有", "我", "你", "他", "她", "它", "我们", "你们", "他们",
    "这", "那", "一个", "一种", "这个", "那个", "与", "及", "或", "而", "但", "就", "都",
    "也", "不", "没", "着", "过", "上", "下", "中", "里", "对", "从", "为", "以", "把",
    "被", "让", "到", "说", "要", "会", "能", "可以", "因为", "所以", "如果", "虽然",
    "但是", "还是", "就是", "这样", "那样", "什么", "怎么", "为什么", "自己", "们",
}
EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "of", "with",
    "is", "are", "was", "were", "be", "been", "it", "this", "that", "these", "those",
    "i", "you", "he", "she", "we", "they", "as", "by", "from", "not", "so", "if",
    "your", "my", "our", "their", "his", "her", "will", "can", "do", "does",
}


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


def tokenize(text: str):
    """中文取二字词、英文取小写词，用于关键词统计。"""
    tokens = []
    for run in re.findall(r"[一-鿿]+|[A-Za-z0-9]+", text):
        if re.match(r"^[一-鿿]", run):
            for i in range(len(run) - 1):
                tokens.append(run[i:i + 2])
        else:
            tokens.append(run.lower())
    return tokens


def top_keywords(text: str, n=10):
    tokens = [t for t in tokenize(text) if t not in CN_STOPWORDS and t not in EN_STOPWORDS]
    counts = Counter(tokens)
    first_seen = {}
    for i, tok in enumerate(tokens):
        first_seen.setdefault(tok, i)
    # 先按次数降序、再按首次出现位置升序，保证确定性
    ranked = sorted(counts.items(), key=lambda kv: (-kv[1], first_seen[kv[0]]))
    return [{"word": w, "count": c} for w, c in ranked[:n]]


def analyze(text: str):
    total_chars = len(text)
    no_space = len(re.sub(r"\s", "", text))
    sentences = [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
    latin_words = len(re.findall(r"[A-Za-z0-9]+", text))
    cjk_chars = len(CJK_RE.findall(text))
    total_words = latin_words + cjk_chars
    avg_sentence_len = round(
        (sum(len(s) for s in sentences) / len(sentences)) if sentences else 0, 2
    )
    long_sentences = sum(1 for s in sentences if len(s) > 40)
    long_ratio = round(long_sentences / len(sentences), 4) if sentences else 0.0

    headings = Counter()
    for line in text.splitlines():
        m = re.match(r"^(#{1,6})\s", line)
        if m:
            headings[m.group(1)] += 1
    lines = text.splitlines()
    bullet_count = len([l for l in lines if re.match(r"^\s*[-*+]\s+", l)])
    ordered_count = len([l for l in lines if re.match(r"^\s*\d+[.、)]\s*", l)])
    code_fence_count = len(re.findall(r"^```", text, flags=re.M)) // 2
    table_count = len([l for l in lines if l.strip().startswith("|")])
    intro_candidate = paragraphs[0][:80] if paragraphs else ""
    conclusion_candidate = paragraphs[-1][:80] if len(paragraphs) > 1 else ""

    quoted_chars = len(QUOTE_RE.findall(text)) * 2
    dialogue_ratio = round(quoted_chars / total_chars, 4) if total_chars else 0.0

    exclamation_count = text.count("!") + text.count("！")
    question_count = text.count("?") + text.count("？")
    emoji_count = len(EMOJI_RE.findall(text))
    number_count = len(re.findall(r"\d+(?:\.\d+)?", text))
    punct_count = len(re.findall(r"[，。！？、；：,.!?;:…—]", text))
    punctuation_density = round(punct_count / total_chars, 4) if total_chars else 0.0
    latin_letters = len(LATIN_RE.findall(text))
    upper_letters = len(re.findall(r"[A-Z]", text))
    capitalization_ratio = (
        round(upper_letters / latin_letters, 4) if latin_letters else 0.0
    )

    filler_hits = {w: text.count(w) for w in CN_FILLERS + EN_FILLERS if text.count(w) > 0}
    filler_words = dict(sorted(filler_hits.items(), key=lambda kv: -kv[1]))

    unit_mentions = len(UNIT_RE.findall(text))
    bold_count = len(re.findall(r"\*\*[^*]+\*\*", text))
    numeric_rules = len(
        re.findall(r"\d+\s*(?:字|词|words|以内|以上|左右|%-100%|％-100％)", text)
    )

    cjk_ratio = cjk_chars / max(total_chars, 1)
    latin_ratio = latin_letters / max(total_chars, 1)
    if cjk_ratio > 0.5:
        language = "CJK"
    elif latin_ratio > 0.5:
        language = "Latin"
    else:
        language = "Mixed"

    if avg_sentence_len < 20:
        readability = "简"
    elif avg_sentence_len <= 40:
        readability = "中"
    else:
        readability = "繁"

    return {
        "stats": {
            "total_chars": total_chars,
            "total_chars_no_space": no_space,
            "total_words": total_words,
            "sentence_count": len(sentences),
            "paragraph_count": len(paragraphs),
            "avg_sentence_length": avg_sentence_len,
            "long_sentence_ratio": long_ratio,
        },
        "structure": {
            "heading_levels": dict(sorted(headings.items())),
            "has_list": bullet_count > 0 or ordered_count > 0,
            "bullet_count": bullet_count,
            "ordered_list_count": ordered_count,
            "code_fence_count": code_fence_count,
            "table_count": table_count,
            "intro_candidate": intro_candidate,
            "conclusion_candidate": conclusion_candidate,
            "dialogue_ratio": dialogue_ratio,
        },
        "style_signals": {
            "exclamation_count": exclamation_count,
            "question_count": question_count,
            "emoji_count": emoji_count,
            "number_count": number_count,
            "punctuation_density": punctuation_density,
            "capitalization_ratio": capitalization_ratio,
            "top_keywords": top_keywords(text),
            "filler_words": filler_words,
        },
        "constraints_hints": {
            "unit_mentions": unit_mentions,
            "bold_count": bold_count,
            "explicit_numeric_rules": numeric_rules,
        },
        "language": language,
        "readability_estimate": readability,
    }


def main():
    parser = argparse.ArgumentParser(description="文本确定性统计分析")
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
        "modality": "text",
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
