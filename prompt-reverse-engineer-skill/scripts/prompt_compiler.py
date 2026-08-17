#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 编译/评分/安全过滤（prompt-reverse-engineer 技能组件）。

子命令：
  compile  将 semantic_analysis 按模型模板渲染为 Prompt（缺字段→退出码 4 并列出）
  score    六维加权评分（Agent 给分 --dims 或启发式 --auto）
  filter   安全过滤（命中黑名单→退出码 5 阻断，--sanitize 则替换后放行）
  all      compile + filter + score 串联

规则权威来源：references/prompt_framework.md（字段契约、评分细则、安全规则）。
注意：本文件 DIMENSIONS/SUGGESTIONS 与 prompt_framework.md 第三、五节镜像，
修改必须两处同步。新增模型=在 assets/templates/ 新增 *.json 模板，零代码改动。
退出码：0 成功 / 1 用法错误(含未知模型) / 2 输入不可读 / 4 契约错误(缺字段/坏评分) / 5 安全阻断
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

TOOL = "prompt_compiler.py"
SCHEMA_VERSION = "1.0"
DEFAULT_MODELS = ["midjourney", "gpt4_claude"]

# --- 评分维度（与 prompt_framework.md 第三节镜像） ---
DIMENSIONS = [
    ("theme_clarity", "主题明确度", 20),
    ("scene_completeness", "场景完整度", 20),
    ("style_fit", "风格契合度", 20),
    ("structure_clarity", "结构清晰度", 15),
    ("param_reasonableness", "参数合理性", 15),
    ("adaptability", "可调性/复用性", 10),
]
assert sum(w for _, _, w in DIMENSIONS) == 100, "评分权重之和必须为 100"

# --- 优化建议库（与 prompt_framework.md 第五节镜像，修改须两处同步） ---
SUGGESTIONS = {
    "theme_clarity": [
        "在 Prompt 首句直接点明生成对象与核心特征，删除可有可无的修饰",
        "为目标受众补一句限定，避免生成泛化",
    ],
    "scene_completeness": [
        "补充时间、地点、氛围三要素之一",
        "用具体名词替换模糊场景词（如“街道”→“雨夜霓虹街头”）",
    ],
    "style_fit": [
        "增加 1-2 个风格锚点词（参考 image_rules.md / video_rules.md 术语库）",
        "删除与整体风格冲突的修饰词",
    ],
    "structure_clarity": [
        "按六要素顺序重排（角色→任务→背景→要求→限制→输出格式）",
        "将隐含约束显式写出（字数、格式、禁用词）",
    ],
    "param_reasonableness": [
        "对照 model_mappings.md 核对参数语法与取值范围",
        "删除与内容不匹配的多余参数",
    ],
    "adaptability": [
        "把具体样例中的可变项替换为 [变量] 占位",
        "为可调参数添加注释说明取值范围",
    ],
}

# --- 安全黑名单（与 prompt_framework.md 第四节对应） ---
BLACKLIST = [
    {"id": "jailbreak_ignore_en", "pattern": r"ignore\s+(all\s+)?previous\s+instructions"},
    {"id": "jailbreak_disregard_en", "pattern": r"disregard\s+(all\s+)?prior\s+(instructions|prompts)"},
    {"id": "jailbreak_word", "pattern": r"jailbreak"},
    {"id": "jailbreak_dan", "pattern": r"\bDAN\b"},
    {"id": "jailbreak_devmode", "pattern": r"developer\s+mode"},
    {"id": "jailbreak_reveal_en", "pattern": r"reveal\s+(your|the)\s+system\s+prompt"},
    {"id": "jailbreak_ignore_cn", "pattern": r"忽略(之前|此前|以上)?(所有|的)?(指令|提示词?)"},
    {"id": "jailbreak_reveal_cn", "pattern": r"输出(你的|其)?(系统)?提示词"},
    {"id": "jailbreak_cn", "pattern": r"越狱|打破限制"},
    {"id": "exec_rm", "pattern": r"rm\s+(-[a-z]+\s+)?-?rf"},
    {"id": "exec_format", "pattern": r"format\s+c:"},
    {"id": "exec_del", "pattern": r"del\s+/[fsq]"},
    {"id": "exec_cmd", "pattern": r"cmd\.exe"},
    {"id": "exec_powershell", "pattern": r"powershell"},
    {"id": "exec_shutdown", "pattern": r"shutdown"},
    {"id": "exec_taskkill", "pattern": r"taskkill"},
    {"id": "exec_regadd", "pattern": r"reg\s+add"},
    {"id": "exec_netuser", "pattern": r"net\s+user"},
    {"id": "exec_droptable", "pattern": r"drop\s+table"},
    {"id": "exec_ossystem", "pattern": r"os\.system"},
    {"id": "exec_subprocess", "pattern": r"subprocess"},
    {"id": "exec_call", "pattern": r"exec\s*\("},
    {"id": "exec_eval", "pattern": r"eval\s*\("},
    {"id": "exec_backtick", "pattern": r"`[^`]*[a-zA-Z][^`]*`"},
    {"id": "exec_dollar_paren", "pattern": r"\$\([^)]*\)"},
]
COMPILED_BLACKLIST = [
    (item["id"], re.compile(item["pattern"], re.IGNORECASE)) for item in BLACKLIST
]

DEFAULT_TEMPLATE_DIR = Path(__file__).resolve().parent.parent / "assets" / "templates"
FIELD_RE = re.compile(r"\{(\w+)\}")


# ---------------------------------------------------------------------------
# 公共工具
# ---------------------------------------------------------------------------
def die(message, code):
    print(f"错误：{message}", file=sys.stderr)
    sys.exit(code)


def load_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        die(f"{what}不可读：{exc}", 2)
    except json.JSONDecodeError as exc:
        die(f"{what}不是合法 JSON：{exc}", 4)


def load_analysis(path):
    data = load_json(path, "分析文件")
    if "semantic_analysis" not in data:
        die("分析文件缺少 semantic_analysis 字段（字段规范见 prompt_framework.md）", 4)
    if "modality" not in data or data["modality"] not in ("text", "image", "video", "story"):
        die("分析文件缺少有效 modality 字段（text/image/video/story）", 4)
    return data


def load_registry(template_dir):
    registry = {}
    for p in sorted(Path(template_dir).glob("*.json")):
        t = json.loads(p.read_text(encoding="utf-8"))
        if "model" not in t:  # 跳过 score_report.json 等非模型模板
            continue
        registry[t["model"]] = dict(t, template_id=p.stem, file=p.name)
    return registry


def resolve_models(spec, registry):
    if spec in ("default",):
        names = DEFAULT_MODELS
    elif spec == "all":
        names = list(registry.keys())
    else:
        names = [s.strip() for s in spec.split(",") if s.strip()]
    resolved, unknown = [], []
    for name in names:
        key = next((m for m, t in registry.items()
                    if m == name or name in t.get("alias", [])), None)
        if key:
            resolved.append(key)
        else:
            unknown.append(name)
    return resolved, unknown


# ---------------------------------------------------------------------------
# compile
# ---------------------------------------------------------------------------
def format_field(field, value):
    """把 semantic 字段值规范为模板可渲染的字符串。

    - 字符串：原样（去首尾空白）
    - 字符串列表：用顿号连接（如 negative_words）
    - 分镜对象数组（storyboard）：按 video_rules.md 分镜规范渲染为逐行文本
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, list):
        if value and isinstance(value[0], dict):
            lines = []
            for idx, item in enumerate(value, 1):
                no = str(item.get("shot_no", idx))
                body = "，".join(
                    str(item[k]) for k in ("shot_size", "camera_move")
                    if item.get(k)
                )
                duration = item.get("duration_s")
                if duration:
                    body += f"，{duration}秒" if body else f"{duration}秒"
                action = item.get("action")
                line = f"镜头{no}：{body}。{action}" if action else f"镜头{no}：{body}"
                if item.get("dialogue"):
                    line += f"（台词：{item['dialogue']}）"
                lines.append(line)
            return "\n".join(lines)
        return "、".join(str(v) for v in value)
    return str(value)


def clean_rendered(text):
    """清理可选字段留空造成的重复逗号/悬挂逗号（确定性处理）。"""
    text = re.sub(r"(,\s*){2,}", ", ", text)
    text = re.sub(r",\s+--", " --", text)
    text = re.sub(r"^\s*,\s*", "", text)
    return text


def render_one(template, kind, modality, semantic):
    """返回 (status, payload)。status: ok / missing / skip"""
    section = template.get("modalities", {}).get(modality, {})
    if kind not in section:
        return "skip", None
    template_str = section[kind]
    fields = sorted(FIELD_RE.findall(template_str))
    optional = set(template.get("optional_fields", []))
    context, missing = {}, []
    for field in fields:
        if field in semantic and format_field(field, semantic[field]):
            context[field] = format_field(field, semantic[field])
        elif field in template.get("default_params", {}):
            context[field] = str(template["default_params"][field])
        elif field in optional:
            context[field] = ""
        else:
            missing.append(field)
    if missing:
        return "missing", missing
    try:
        text = template_str.format(**context)
    except (KeyError, IndexError, ValueError):
        return "missing", sorted(set(fields) - set(context))
    return "ok", clean_rendered(text)


def cmd_compile(args):
    analysis = load_analysis(args.analysis)
    semantic = analysis["semantic_analysis"]
    modality = analysis["modality"]
    registry = load_registry(args.template_dir)
    if not registry:
        die(f"模板目录 {args.template_dir} 下未发现模型模板", 4)
    models, unknown = resolve_models(args.models, registry)
    if unknown:
        die(f"未知模型：{', '.join(unknown)}（可用：{', '.join(sorted(registry))}）", 1)
    if not models:
        die("未解析到任何模型", 1)

    prompts, skipped, missing_all = [], [], []
    for model in models:
        template = registry[model]
        for kind in template.get("modalities", {}).get(modality, {}):
            status, payload = render_one(template, kind, modality, semantic)
            if status == "ok":
                prompts.append({
                    "model": model,
                    "kind": kind,
                    "text": payload,
                    "template_id": template["template_id"],
                    "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                })
            elif status == "missing":
                missing_all.append((model, kind, payload))
        if modality not in template.get("modalities", {}):
            skipped.append({"model": model, "reason": f"模板不支持 {modality} 模态"})

    if missing_all:
        for model, kind, fields in missing_all:
            die(f"{model}/{kind} 缺失字段：{', '.join(fields)}"
                f"（补全 semantic_analysis 后重试）", 4)

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "compile",
        "modality": modality,
        "models": models,
        "prompts": prompts,
        "skipped": skipped,
    }
    emit(result, args.output)


# ---------------------------------------------------------------------------
# score
# ---------------------------------------------------------------------------
def heuristic_scores(semantic):
    """启发式近似评分，仅供离线验证；真实使用请由 Agent 用 --dims 给分。"""
    def present(*keys):
        return any(str(semantic.get(k, "")).strip() for k in keys)

    def length(*keys):
        return max((len(str(semantic.get(k, ""))) for k in keys), default=0)

    scores = {}
    s = 60
    s += 15 if length("subject", "task") > 10 else 0
    s += 10 if present("audience", "domain") else 0
    s += 10 if length("subject", "task") > 30 else 0
    scores["theme_clarity"] = min(s, 100)

    s = 60
    s += 15 if present("scene") else 0
    s += 10 if present("lighting") else 0
    s += 10 if present("atmosphere", "color") else 0
    scores["scene_completeness"] = min(s, 100)

    s = 60
    s += 20 if present("style") else 0
    s += 10 if present("quality_words") else 0
    scores["style_fit"] = min(s, 100)

    s = 60
    s += 20 if present("storyboard", "structure") else 0
    s += 10 if present("constraints") else 0
    scores["structure_clarity"] = min(s, 100)

    s = 60
    s += 20 if present("photo_params", "duration", "aspect_ratio") else 0
    s += 10 if present("negative_words") else 0
    scores["param_reasonableness"] = min(s, 100)

    s = 60
    s += 20 if present("suggestions") else 0
    s += 10 if present("audience") else 0
    scores["adaptability"] = min(s, 100)
    return scores


def build_report(dim_entries, approximate):
    total = round(sum(w * s for _, _, w, s in dim_entries) / 100.0, 1)
    grade = "A" if total >= 90 else "B" if total >= 75 else "C" if total >= 60 else "D"
    ranked = sorted(dim_entries, key=lambda e: (e[3], e[0]))
    suggestions = []
    for key, name, _, _ in ranked[:2]:
        if SUGGESTIONS.get(key):
            suggestions.append(SUGGESTIONS[key][0])
    dimensions = [{"key": k, "name": n, "weight": w, "score": s}
                  for k, n, w, s in dim_entries]
    return {
        "total": total,
        "grade": grade,
        "approximate": approximate,
        "dimensions": dimensions,
        "suggestions": suggestions,
    }


def cmd_score(args):
    semantic = None
    if args.analysis:
        semantic = load_analysis(args.analysis)["semantic_analysis"]
    if args.dims:
        dims_data = load_json(args.dims, "评分文件")
        known = {k for k, _, _ in DIMENSIONS}
        entries, missing = [], []
        seen = set()
        for item in dims_data:
            key = item.get("key")
            if key not in known:
                die(f"未知评分维度：{key}", 4)
            score = item.get("score")
            if not isinstance(score, (int, float)) or not 0 <= score <= 100:
                die(f"维度 {key} 得分须为 0-100 的数字", 4)
            entries.append((key, item.get("note", ""), score))
            seen.add(key)
        for key, name, weight in DIMENSIONS:
            if key not in seen:
                missing.append(key)
        if missing:
            die(f"评分文件缺少维度：{', '.join(missing)}", 4)
        dim_entries = [(k, name, w, s) for k, _, s in entries
                       for kk, name, w in DIMENSIONS if kk == k]
        notes = {k: note for k, note, _ in entries}
        approximate = False
    elif args.auto:
        if semantic is None:
            die("--auto 需要同时提供 --analysis", 1)
        auto_scores = heuristic_scores(semantic)
        dim_entries = [(k, n, w, auto_scores[k]) for k, n, w in DIMENSIONS]
        notes = {}
        approximate = True
    else:
        die("评分需要 --dims dims.json（Agent 给分）或 --auto（启发式，仅离线验证）", 1)

    report = build_report(dim_entries, approximate)

    # 用 score_report.json 渲染文本
    report_text = None
    template_path = Path(args.template_dir) / "score_report.json"
    try:
        layout = json.loads(template_path.read_text(encoding="utf-8"))
        lines = [layout.get("header", "## 评分报告")]
        for dim in report["dimensions"]:
            lines.append(layout["dimension_line"].format(
                name=dim["name"], weight=dim["weight"], score=dim["score"],
                note=notes.get(dim["key"], "—"),
            ) if "dimension_line" in layout else
                f"- {dim['name']}（权重 {dim['weight']}%）：{dim['score']} 分")
        lines.append(layout["total_line"].format(
            total=report["total"], grade=report["grade"]))
        for i, sug in enumerate(report["suggestions"], 1):
            lines.append(layout["suggestion_line"].format(i=i, suggestion=sug))
        if approximate and "approximate_note" in layout:
            lines.append(layout["approximate_note"])
        report_text = "\n".join(lines)
    except (OSError, KeyError, json.JSONDecodeError):
        report_text = None

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "score",
        "score_report": report,
        "report_text": report_text,
    }
    emit(result, args.output)


# ---------------------------------------------------------------------------
# filter
# ---------------------------------------------------------------------------
def scan_text(text):
    # 位置一律相对原始文本：先在原文收集全部命中，再统一替换
    matches = []
    for pid, pattern in COMPILED_BLACKLIST:
        for m in pattern.finditer(text):
            matches.append({"pattern_id": pid, "matched": m.group(0), "pos": m.start()})
    sanitized = text
    for _, pattern in COMPILED_BLACKLIST:
        sanitized = pattern.sub("[已过滤]", sanitized)
    return matches, sanitized


def cmd_filter(args):
    if args.prompt is not None:
        text = args.prompt
    elif args.file:
        try:
            text = Path(args.file).read_text(encoding="utf-8")
        except OSError as exc:
            die(f"文件不可读：{exc}", 2)
    else:
        die("需要 --prompt 或 --file", 1)
    matches, sanitized = scan_text(text)
    blocked = len(matches) > 0
    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "filter",
        "filter": {"blocked": blocked, "matches": matches, "sanitized_text": sanitized},
    }
    emit(result, args.output)
    if blocked and not args.sanitize:
        print("安全过滤阻断：Prompt 命中黑名单，已拒绝输出", file=sys.stderr)
        sys.exit(5)


# ---------------------------------------------------------------------------
# all
# ---------------------------------------------------------------------------
def cmd_all(args):
    analysis = load_analysis(args.analysis)
    semantic = analysis["semantic_analysis"]
    modality = analysis["modality"]
    registry = load_registry(args.template_dir)
    if not registry:
        die(f"模板目录 {args.template_dir} 下未发现模型模板", 4)
    models, unknown = resolve_models(args.models, registry)
    if unknown:
        die(f"未知模型：{', '.join(unknown)}（可用：{', '.join(sorted(registry))}）", 1)
    if not models:
        die("未解析到任何模型", 1)

    prompts, skipped, missing_all = [], [], []
    for model in models:
        template = registry[model]
        for kind in template.get("modalities", {}).get(modality, {}):
            status, payload = render_one(template, kind, modality, semantic)
            if status == "ok":
                prompts.append({
                    "model": model, "kind": kind, "text": payload,
                    "template_id": template["template_id"],
                    "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest(),
                })
            elif status == "missing":
                missing_all.append((model, kind, payload))
        if modality not in template.get("modalities", {}):
            skipped.append({"model": model, "reason": f"模板不支持 {modality} 模态"})

    if missing_all:
        for model, kind, fields in missing_all:
            die(f"{model}/{kind} 缺失字段：{', '.join(fields)}"
                f"（补全 semantic_analysis 后重试）", 4)

    all_matches = []
    sanitized_prompts = []
    for p in prompts:
        matches, sanitized = scan_text(p["text"])
        all_matches.extend(matches)
        sanitized_prompts.append(dict(p, text=sanitized))
    blocked = len(all_matches) > 0

    # 评分
    if args.dims:
        dims_data = load_json(args.dims, "评分文件")
        known = {k for k, _, _ in DIMENSIONS}
        entries, seen = [], set()
        for item in dims_data:
            key = item.get("key")
            if key not in known:
                die(f"未知评分维度：{key}", 4)
            score = item.get("score")
            if not isinstance(score, (int, float)) or not 0 <= score <= 100:
                die(f"维度 {key} 得分须为 0-100 的数字", 4)
            entries.append((key, item.get("note", ""), score))
            seen.add(key)
        missing = [k for k, _, _ in DIMENSIONS if k not in seen]
        if missing:
            die(f"评分文件缺少维度：{', '.join(missing)}", 4)
        dim_entries = [(k, n, w, s) for k, _, s in entries
                       for kk, n, w in DIMENSIONS if kk == k]
        approximate = False
    elif args.auto:
        auto_scores = heuristic_scores(semantic)
        dim_entries = [(k, n, w, auto_scores[k]) for k, n, w in DIMENSIONS]
        approximate = True
    else:
        die("all 需要 --dims 或 --auto", 1)
    report = build_report(dim_entries, approximate)

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "all",
        "modality": modality,
        "models": models,
        "prompts": prompts,
        "skipped": skipped,
        "filter": {"blocked": blocked, "matches": all_matches},
        "score_report": report,
    }
    if args.format == "json":
        emit(result, args.output)
    else:
        emit_text(result, args.output)
    if blocked and not args.sanitize:
        print("安全过滤阻断：生成结果命中黑名单，请重写后重试", file=sys.stderr)
        sys.exit(5)


def emit_text(result, output):
    lines = [f"# Prompt 编译结果（modality={result.get('modality')}）", ""]
    for p in result.get("prompts", []):
        lines.append(f"### {p['model']} / {p['kind']}")
        lines.append("```")
        lines.append(p["text"])
        lines.append("```")
        lines.append("")
    r = result.get("score_report", {})
    if r:
        lines.append("## 评分报告")
        for dim in r["dimensions"]:
            lines.append(f"- {dim['name']}（权重 {dim['weight']}%）：{dim['score']} 分")
        lines.append(f"总分：{r['total']} / 100（等级 {r['grade']}）")
        if r.get("approximate"):
            lines.append("（自动启发式近似评分，仅供参考）")
        for i, sug in enumerate(r.get("suggestions", []), 1):
            lines.append(f"优化建议 {i}：{sug}")
    text = "\n".join(lines) + "\n"
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text, end="")


def emit(result, output):
    out = json.dumps(result, ensure_ascii=False, sort_keys=True)
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(out + "\n")
    else:
        print(out)


# ---------------------------------------------------------------------------
# scenes
# ---------------------------------------------------------------------------
def cmd_scenes(args):
    """叙事文本（modality=story）逐场景编译：每场景渲染图片组（默认 mj,sd）
    + 视频组（默认 sora）+ 安全过滤 + 逐场景评分。"""
    analysis = load_analysis(args.analysis)
    if analysis["modality"] != "story":
        die("scenes 子命令要求 analysis 的 modality 为 story（叙事文本场景化）", 1)
    semantic = analysis.get("semantic_analysis", {})
    scenes = semantic.get("scenes")
    if not isinstance(scenes, list) or not scenes:
        die("story 分析缺少非空 scenes 数组（字段规范见 prompt_framework.md 2.5 节）", 4)

    registry = load_registry(args.template_dir)
    if not registry:
        die(f"模板目录 {args.template_dir} 下未发现模型模板", 4)
    image_models, image_unknown = resolve_models(args.image_models, registry)
    video_models, video_unknown = resolve_models(args.video_models, registry)
    unknown = sorted(set(image_unknown) | set(video_unknown))
    if unknown:
        die(f"未知模型：{', '.join(unknown)}（可用：{', '.join(sorted(registry))}）", 1)
    if not any("image" in registry[m].get("modalities", {}) for m in image_models):
        die("图片模型列表中无支持 image 模态的模板", 1)
    if not any("video" in registry[m].get("modalities", {}) for m in video_models):
        die("视频模型列表中无支持 video 模态的模板", 1)

    # ---- 逐场景评分数据 ----
    scene_dims, notes_map = {}, {}
    if args.dims:
        dims_data = load_json(args.dims, "评分文件")
        known = {k for k, _, _ in DIMENSIONS}
        for item in dims_data:
            scene_no = item.get("scene_no")
            if not isinstance(scene_no, int):
                die("评分文件每项必须含整数 scene_no，发现：" + json.dumps(item, ensure_ascii=False), 4)
            entries, seen = [], set()
            for d in item.get("dims", []):
                key = d.get("key")
                if key not in known:
                    die(f"未知评分维度：{key}", 4)
                score = d.get("score")
                if not isinstance(score, (int, float)) or not 0 <= score <= 100:
                    die(f"维度 {key} 得分须为 0-100 的数字", 4)
                entries.append((key, d.get("note", ""), score))
                seen.add(key)
            missing = [k for k, _, _ in DIMENSIONS if k not in seen]
            if missing:
                die(f"场景 {scene_no} 评分缺少维度：{', '.join(missing)}", 4)
            scene_dims[scene_no] = [(k, n, w, s) for k, _, s in entries
                                    for kk, n, w in DIMENSIONS if kk == k]
            notes_map[scene_no] = {k: note for k, note, _ in entries}
    elif args.auto:
        for scene in scenes:
            no = scene.get("scene_no")
            if not isinstance(no, int):
                die(f"场景缺少整数 scene_no 字段：{json.dumps(scene, ensure_ascii=False)[:120]}", 4)
            auto = heuristic_scores(scene)
            scene_dims[no] = [(k, n, w, auto[k]) for k, n, w in DIMENSIONS]
    else:
        die("scenes 需要 --dims（逐场景评分 JSON）或 --auto（启发式，仅离线验证）", 1)

    # ---- 逐场景编译 ----
    out_scenes, blocked_any = [], False
    for scene in scenes:
        scene_no = scene.get("scene_no")
        if not isinstance(scene_no, int):
            die("场景缺少整数 scene_no 字段", 4)
        if scene_no not in scene_dims:
            die(f"场景 {scene_no} 缺少评分条目", 4)
        title = scene.get("title") or f"场景 {scene_no}"
        prompts, missing_all = [], []
        for model in image_models:
            template = registry[model]
            for kind in template.get("modalities", {}).get("image", {}):
                status, payload = render_one(template, kind, "image", scene)
                if status == "ok":
                    prompts.append({"model": model, "kind": kind, "text": payload,
                                    "template_id": template["template_id"],
                                    "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()})
                elif status == "missing":
                    missing_all.append((model, kind, payload))
        for model in video_models:
            template = registry[model]
            for kind in template.get("modalities", {}).get("video", {}):
                status, payload = render_one(template, kind, "video", scene)
                if status == "ok":
                    prompts.append({"model": model, "kind": kind, "text": payload,
                                    "template_id": template["template_id"],
                                    "sha256": hashlib.sha256(payload.encode("utf-8")).hexdigest()})
                elif status == "missing":
                    missing_all.append((model, kind, payload))
        if missing_all:
            for model, kind, fields in missing_all:
                die(f"场景 {scene_no}（{title}）{model}/{kind} 缺失字段：{', '.join(fields)}"
                    f"（补全 semantic_analysis.scenes[{scene_no}] 后重试）", 4)

        matches, sanitized = [], []
        for p in prompts:
            m, s = scan_text(p["text"])
            matches.extend(m)
            sanitized.append(dict(p, text=s))
        if matches:
            blocked_any = True

        report = build_report(scene_dims[scene_no], bool(args.auto))
        out_scenes.append({
            "scene_no": scene_no,
            "title": title,
            "prompts": sanitized,
            "filter": {"blocked": len(matches) > 0, "matches": matches},
            "score_report": report,
        })

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "scenes",
        "modality": "story",
        "models": {"image": image_models, "video": video_models},
        "scenes": out_scenes,
    }
    if args.format == "json":
        emit(result, args.output)
    else:
        emit_scenes_text(result, args.output)
    if blocked_any and not args.sanitize:
        print("安全过滤阻断：生成结果命中黑名单，请重写后重试", file=sys.stderr)
        sys.exit(5)


def emit_scenes_text(result, output):
    lines = ["# 场景化 Prompt 编译结果（modality=story）", ""]
    for sc in result.get("scenes", []):
        lines.append(f"## 场景 {sc['scene_no']}：{sc['title']}")
        for p in sc.get("prompts", []):
            lines.append(f"### {p['model']} / {p['kind']}")
            lines.append("```")
            lines.append(p["text"])
            lines.append("```")
            lines.append("")
        r = sc.get("score_report", {})
        if r:
            lines.append("### 评分")
            for dim in r["dimensions"]:
                lines.append(f"- {dim['name']}（权重 {dim['weight']}%）：{dim['score']} 分")
            lines.append(f"总分：{r['total']} / 100（等级 {r['grade']}）")
            if r.get("approximate"):
                lines.append("（自动启发式近似评分，仅供参考）")
            for i, sug in enumerate(r.get("suggestions", []), 1):
                lines.append(f"优化建议 {i}：{sug}")
            lines.append("")
    text = "\n".join(lines) + "\n"
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text, end="")


# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Prompt 编译/评分/安全过滤")
    sub = parser.add_subparsers(dest="command", required=True)

    p_compile = sub.add_parser("compile", help="按模型模板渲染 Prompt")
    p_compile.add_argument("--analysis", required=True, help="分析 JSON（含 modality + semantic_analysis）")
    p_compile.add_argument("--models", default="default",
                           help="模型列表（逗号分隔/别名）或 default（MJ+GPT4）/all")
    p_compile.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_compile.add_argument("-o", "--output")

    p_score = sub.add_parser("score", help="六维加权评分")
    p_score.add_argument("--analysis", help="分析 JSON（--auto 启发式评分需要）")
    p_score.add_argument("--dims", help="Agent 评分 JSON：[{key, score, note}]")
    p_score.add_argument("--auto", action="store_true", help="启发式近似评分（仅离线验证）")
    p_score.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_score.add_argument("-o", "--output")

    p_filter = sub.add_parser("filter", help="安全过滤")
    p_filter.add_argument("--prompt", help="待检 Prompt 文本")
    p_filter.add_argument("--file", help="待检 Prompt 文件")
    p_filter.add_argument("--sanitize", action="store_true",
                          help="命中黑名单时替换为 [已过滤] 并放行（默认阻断退出码 5）")
    p_filter.add_argument("-o", "--output")

    p_all = sub.add_parser("all", help="compile + filter + score 串联")
    p_all.add_argument("--analysis", required=True)
    p_all.add_argument("--models", default="default")
    p_all.add_argument("--dims", help="Agent 评分 JSON：[{key, score, note}]")
    p_all.add_argument("--auto", action="store_true")
    p_all.add_argument("--sanitize", action="store_true")
    p_all.add_argument("--format", default="json", choices=["json", "text"])
    p_all.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_all.add_argument("-o", "--output")

    p_scenes = sub.add_parser("scenes", help="叙事文本逐场景编译（每场景 image+video 提示词）")
    p_scenes.add_argument("--analysis", required=True,
                          help="story 分析 JSON（modality=story，semantic_analysis.scenes[]）")
    p_scenes.add_argument("--image-models", default="mj,sd",
                          help="图片模型列表（逗号分隔/别名，默认 mj,sd）")
    p_scenes.add_argument("--video-models", default="sora",
                          help="视频模型列表（逗号分隔/别名，默认 sora）")
    p_scenes.add_argument("--dims",
                          help="逐场景评分 JSON：[{scene_no, dims: [{key, score, note}]}]")
    p_scenes.add_argument("--auto", action="store_true",
                          help="启发式逐场景近似评分（仅离线验证）")
    p_scenes.add_argument("--sanitize", action="store_true")
    p_scenes.add_argument("--format", default="json", choices=["json", "text"])
    p_scenes.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_scenes.add_argument("-o", "--output")

    args = parser.parse_args()
    if args.command == "compile":
        cmd_compile(args)
    elif args.command == "score":
        cmd_score(args)
    elif args.command == "filter":
        cmd_filter(args)
    elif args.command == "all":
        cmd_all(args)
    elif args.command == "scenes":
        cmd_scenes(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
