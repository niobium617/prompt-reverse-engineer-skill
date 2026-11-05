#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 编译/评分/安全过滤（prompt-reverse-engineer 技能组件）。

子命令：
  compile  将 semantic_analysis 按模型模板渲染为 Prompt（缺字段→退出码 4 并列出）
  score    六维加权评分（Agent 给分 --dims 或启发式 --auto）
  filter   安全过滤（命中黑名单→退出码 5 阻断，--sanitize 则替换后放行）
  all      compile + filter + score 串联
  scenes   叙事文本逐场景编译（image + video）
  validate-templates  校验模板元数据/占位符/用途契约（全部错误一次列出）

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
import unicodedata
from datetime import date
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

# --- 提示注入标记（仅报告，不阻断；语义见 prompt_framework.md 第四节） ---
INJECTION_PATTERNS = [
    {"id": "inj_instruction_override",
     "pattern": r"(ignore|disregard|forget)\s+(all\s+)?(the\s+)?(previous|prior|above)\s+"
                r"(instructions|prompts|rules|messages)"},
    {"id": "inj_role_override",
     "pattern": r"\b(you\s+are\s+now|from\s+now\s+on\s+you|act\s+as\s+if)\b"},
    {"id": "inj_system_prompt",
     "pattern": r"\b(system\s+prompt|developer\s+mode|jailbreak)\b"},
    {"id": "inj_chat_template",
     "pattern": r"(<\|im_start\|>|<\|im_end\|>|<<SYS>>|\[/?INST\]|###\s*(system|instruction)\s*:)"},
    {"id": "inj_override_cn",
     "pattern": r"(忽略|无视|忘记)(之前|此前|以上|前面)?(的)?(所有|全部)?(指令|提示词?|规则|设定)"},
    {"id": "inj_role_cn",
     "pattern": r"(你现在是|从现在开始你|扮演一个没有限制|开发者模式)"},
    {"id": "inj_reveal_cn",
     "pattern": r"(输出|打印|展示|重复)(你的|其)?(系统)?(提示词|指令)"},
]
COMPILED_INJECTION = [
    (item["id"], re.compile(item["pattern"], re.IGNORECASE)) for item in INJECTION_PATTERNS
]

ZERO_WIDTH_CHARS = frozenset("​‌‍‎‏⁠﻿­᠎")
# 常见西里尔/希腊同形字 → ASCII（NFKC 不处理这类跨文字同形）
HOMOGLYPHS = str.maketrans({
    "а": "a", "в": "b", "е": "e", "к": "k", "м": "m", "н": "h", "о": "o",
    "р": "p", "с": "c", "т": "t", "у": "y", "х": "x", "і": "i", "ј": "j",
    "ѕ": "s", "ԁ": "d", "ӏ": "l",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O",
    "Р": "P", "С": "C", "Т": "T", "У": "Y", "Х": "X", "І": "I", "Ј": "J",
    "Ѕ": "S", "Ԁ": "D", "Ӏ": "I",
    "ο": "o", "α": "a", "ε": "e", "ι": "i", "κ": "k", "ν": "v",
    "ρ": "p", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K",
    "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y", "Χ": "X",
})
# 模板可引用的语义字段（与 prompt_framework.md 第二、三节字段契约对应）
KNOWN_FIELDS = {
    "role", "domain", "audience", "task", "style", "structure", "constraints",
    "output_format", "subject", "scene", "lighting", "color", "composition",
    "photo_params", "quality_words", "negative_words", "target_style",
    "text_content", "reference_note", "story", "storyboard", "character",
    "camera", "atmosphere", "audio", "narration", "dialogue", "duration",
    "aspect_ratio",
}
MODALITY_NAMES = {"text", "image", "video"}
KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TEMPLATE_META = ("model", "display_name", "vendor", "version",
                 "last_verified", "alias", "default_params", "modalities")

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


def template_errors(filename, t):
    """校验单个模型模板的元数据、占位符与用途契约，返回错误消息列表。"""
    errors = []

    def err(message):
        errors.append(f"模板 {filename}：{message}")

    for key in ("display_name", "vendor", "version"):
        value = t.get(key)
        if not isinstance(value, str) or not value.strip():
            err(f"{key} 必须是非空字符串")
    last_verified = t.get("last_verified")
    if not isinstance(last_verified, str) or not DATE_RE.match(last_verified):
        err("last_verified 必须是 YYYY-MM-DD 日期")
    else:
        try:
            date.fromisoformat(last_verified)
        except ValueError:
            err(f"last_verified 不是有效日期：{last_verified}")

    alias = t.get("alias")
    if not isinstance(alias, list) or not all(
            isinstance(a, str) and a.strip() for a in alias):
        err("alias 必须是非空字符串数组")
        alias = []
    elif len(set(alias)) != len(alias):
        err("alias 含重复项")

    defaults = t.get("default_params")
    if not isinstance(defaults, dict):
        err("default_params 必须是对象")
        defaults = {}
    else:
        for key, value in defaults.items():
            if not isinstance(key, str) or not key.strip():
                err("default_params 的键必须是非空字符串")
            if isinstance(value, (dict, list)) or value is None:
                err(f"default_params.{key} 必须是标量（字符串/数字/布尔）")

    optional = t.get("optional_fields", [])
    if not isinstance(optional, list) or not all(
            isinstance(f, str) and f.strip() for f in optional):
        err("optional_fields 必须是字符串数组")
        optional = []

    modalities = t.get("modalities")
    if not isinstance(modalities, dict) or not modalities:
        err("modalities 必须是非空对象")
        return errors

    kinds_all = set()
    allowed_fields = KNOWN_FIELDS | set(defaults) | set(optional)
    for modality, kinds in modalities.items():
        if modality not in MODALITY_NAMES:
            err(f"未知模态：{modality}（可用：{', '.join(sorted(MODALITY_NAMES))}）")
            continue
        if not isinstance(kinds, dict) or not kinds:
            err(f"modalities.{modality} 必须是非空对象")
            continue
        for kind, tmpl in kinds.items():
            if not KIND_RE.match(kind):
                err(f"用途名 {modality}.{kind} 须为小写字母/数字/下划线")
            if not isinstance(tmpl, str) or not tmpl.strip():
                err(f"modalities.{modality}.{kind} 必须是非空字符串")
                continue
            kinds_all.add(kind)
            leftover = re.sub(r"\{\w+\}", "", tmpl)
            if "{" in leftover or "}" in leftover:
                err(f"modalities.{modality}.{kind} 含未闭合的大括号")
            unknown = sorted(set(FIELD_RE.findall(tmpl)) - allowed_fields)
            if unknown:
                err(f"modalities.{modality}.{kind} 引用了未知占位符：{', '.join(unknown)}")

    requires = t.get("kind_requires", {})
    if not isinstance(requires, dict):
        err("kind_requires 必须是对象")
    else:
        for kind, fields in requires.items():
            if kind not in kinds_all:
                err(f"kind_requires.{kind} 没有对应用途模板")
            if not isinstance(fields, list) or not all(
                    isinstance(f, str) and f.strip() for f in fields):
                err(f"kind_requires.{kind} 必须是字符串数组")
                continue
            unknown = sorted(set(fields) - KNOWN_FIELDS)
            if unknown:
                err(f"kind_requires.{kind} 引用了未知字段：{', '.join(unknown)}")
    return errors


def scan_templates(template_dir):
    """加载模板目录并收集全部错误，返回 (registry, errors, skipped)。

    errors 为 [(退出码, 消息)]；score_report.json 等无 model 的文件进 skipped。
    """
    registry, alias_owner, errors, skipped = {}, {}, [], []
    for p in sorted(Path(template_dir).glob("*.json")):
        try:
            t = json.loads(p.read_text(encoding="utf-8"))
        except OSError as exc:
            errors.append((2, f"模板不可读：{p.name}：{exc}"))
            continue
        except json.JSONDecodeError as exc:
            errors.append((4, f"模板不是合法 JSON：{p.name}：{exc}"))
            continue
        if not isinstance(t, dict) or "model" not in t:
            skipped.append(p.name)  # score_report.json 等非模型模板
            continue
        model = t["model"]
        problems = template_errors(p.name, t)
        if not isinstance(model, str) or not model.strip():
            problems.insert(0, f"模板 {p.name} 的 model 必须是非空字符串")
        if problems:
            errors.extend((4, message) for message in problems)
            continue
        if model in registry:
            errors.append(
                (4, f"模板 model 重复：{model}（{registry[model]['file']} 与 {p.name}）"))
            continue
        conflict = False
        for name in [model] + [str(a) for a in t["alias"]]:
            if name in alias_owner and alias_owner[name] != model:
                errors.append(
                    (4, f"模板别名冲突：{name} 同时被 {alias_owner[name]} 与 {model} 使用"))
                conflict = True
            alias_owner.setdefault(name, model)
        if conflict:
            continue
        registry[model] = dict(t, template_id=p.stem, file=p.name)
    return registry, errors, skipped


def load_registry(template_dir):
    """加载并校验模板目录；任一模板不合契约即退出（首个错误决定退出码）。"""
    registry, errors, _ = scan_templates(template_dir)
    if errors:
        code, message = errors[0]
        die(message, code)
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
                    str(item[k]).strip() for k in ("shot_size", "camera_move")
                    if str(item.get(k, "")).strip()
                )
                duration = item.get("duration_s")
                if duration:
                    body += f"，{duration}秒" if body else f"{duration}秒"
                action = str(item.get("action", "")).strip()
                if body and action:
                    line = f"镜头{no}：{body}。{action}"
                elif action:
                    line = f"镜头{no}：{action}"
                else:
                    line = f"镜头{no}：{body}"
                dialogue = str(item.get("dialogue", "")).strip()
                if dialogue:
                    line += f"（台词：{dialogue}）"
                lines.append(line)
            return "\n".join(lines)
        return "、".join(str(v).strip() for v in value if str(v).strip())
    return str(value)


def clean_rendered(text):
    """清理可选字段留空造成的空标签、重复标点与多余空行（确定性处理）。"""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 整行只有「标签：」或「Label: .」时删除（仅删空值行，不碰有内容的行）
    text = re.sub(
        r"(?m)^[ \t]*[^\n:：]{1,24}[:：][ \t]*[.。；;，,、]?[ \t]*$",
        "", text,
    )
    # 空文字槽位：文字「」以及其前的逗号
    text = re.sub(r"[，,]\s*文字「\s*」", "", text)
    text = re.sub(r"(?m)^[ \t]*文字「\s*」[ \t]*$", "", text)
    # 重复逗号（中英文）折叠为一个英文逗号；逗号后统一一个空格
    text = re.sub(r"([,，])\s*(?:[,，]\s*)+", ", ", text)
    text = re.sub(r"[,，]\s+--", " --", text)
    text = re.sub(r"^\s*[,，]\s*", "", text)
    # 自然语言模板（FLUX.2）空字段造成的连续句号
    text = re.sub(r"(?:\.\s*){2,}", ". ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    lines = [line.rstrip() for line in text.splitlines()]
    return "\n".join(lines).strip()


def render_one(template, kind, modality, semantic):
    """返回 (status, payload)。status: ok / missing / skip

    kind_requires 用于「只有提供某字段才渲染该用途」的场景，
    例如没有 target_style 时不输出 style_transfer / edit。
    """
    section = template.get("modalities", {}).get(modality, {})
    if kind not in section:
        return "skip", None
    for required in template.get("kind_requires", {}).get(kind, []):
        if not str(semantic.get(required, "")).strip():
            return "skip", None
    template_str = section[kind]
    fields = sorted(FIELD_RE.findall(template_str))
    optional = set(template.get("optional_fields", []))
    context, missing = {}, []
    for field in fields:
        rendered = format_field(field, semantic[field]) if field in semantic else ""
        if rendered:
            context[field] = rendered
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


def prompt_record(template, model, kind, text):
    """统一的 Prompt 记录结构（含模型展示名与版本，便于前端/文档消费）。"""
    return {
        "model": model,
        "display_name": template.get("display_name", model),
        "version": str(template.get("version", "")),
        "kind": kind,
        "text": text,
        "template_id": template["template_id"],
        "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }


def compile_prompts(registry, models, modality, semantic):
    """按模型列表渲染某模态，返回 (prompts, skipped, missing_all)。"""
    prompts, skipped, missing_all = [], [], []
    for model in models:
        template = registry[model]
        if modality not in template.get("modalities", {}):
            skipped.append({"model": model, "reason": f"模板不支持 {modality} 模态"})
            continue
        for kind in template["modalities"][modality]:
            status, payload = render_one(template, kind, modality, semantic)
            if status == "ok":
                prompts.append(prompt_record(template, model, kind, payload))
            elif status == "missing":
                missing_all.append((model, kind, payload))
    return prompts, skipped, missing_all


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

    prompts, skipped, missing_all = compile_prompts(registry, models, modality, semantic)
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


def build_report(dim_entries, approximate, notes=None):
    total = round(sum(w * s for _, _, w, s in dim_entries) / 100.0, 1)
    grade = "A" if total >= 90 else "B" if total >= 75 else "C" if total >= 60 else "D"
    ranked = sorted(dim_entries, key=lambda e: (e[3], e[0]))
    suggestions = []
    for key, name, _, _ in ranked[:2]:
        if SUGGESTIONS.get(key):
            suggestions.append(SUGGESTIONS[key][0])
    notes = notes or {}
    dimensions = [{"key": k, "name": n, "weight": w, "score": s,
                   "note": str(notes.get(k, "")).strip()}
                  for k, n, w, s in dim_entries]
    return {
        "total": total,
        "grade": grade,
        "approximate": approximate,
        "dimensions": dimensions,
        "suggestions": suggestions,
    }


def parse_dims(path):
    """解析 Agent 给分文件：[{key, score, note}] → (dim_entries, notes)。"""
    dims_data = load_json(path, "评分文件")
    known = {k for k, _, _ in DIMENSIONS}
    entries, seen = [], set()
    for item in dims_data:
        key = item.get("key")
        if key not in known:
            die(f"未知评分维度：{key}", 4)
        score = item.get("score")
        if not isinstance(score, (int, float)) or not 0 <= score <= 100:
            die(f"维度 {key} 得分须为 0-100 的数字", 4)
        entries.append((key, str(item.get("note", "")).strip(), score))
        seen.add(key)
    missing = [k for k, _, _ in DIMENSIONS if k not in seen]
    if missing:
        die(f"评分文件缺少维度：{', '.join(missing)}", 4)
    dim_entries = [(k, n, w, s) for k, _, s in entries
                   for kk, n, w in DIMENSIONS if kk == k]
    notes = {k: note for k, note, _ in entries}
    return dim_entries, notes


def render_report_text(report, layout_path):
    """按 score_report.json 布局渲染 Markdown 评分报告（失败返回 None）。"""
    try:
        layout = json.loads(Path(layout_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    lines = [layout.get("header", "## 评分报告"), ""]
    if layout.get("table_header") and layout.get("table_row"):
        lines.append(layout["table_header"])
        for dim in report["dimensions"]:
            note = (dim.get("note") or "—").replace("|", "\\|")
            lines.append(layout["table_row"].format(
                name=dim["name"], weight=dim["weight"],
                score=dim["score"], note=note,
            ))
        lines.append("")
    else:
        for dim in report["dimensions"]:
            lines.append(layout.get("dimension_line", "- {name}（权重 {weight}%）：{score} 分").format(
                name=dim["name"], weight=dim["weight"], score=dim["score"],
                note=dim.get("note") or "—",
            ))
    lines.append(layout.get("total_line", "总分：{total} / 100（等级 {grade}）").format(
        total=report["total"], grade=report["grade"]))
    if report.get("approximate") and layout.get("approximate_note"):
        lines.append(layout["approximate_note"])
    suggestions = report.get("suggestions", [])
    if suggestions:
        lines.append("")
        for i, sug in enumerate(suggestions, 1):
            lines.append(layout.get("suggestion_line", "优化建议 {i}：{suggestion}").format(
                i=i, suggestion=sug))
    return "\n".join(lines)


def cmd_score(args):
    semantic = None
    if args.analysis:
        semantic = load_analysis(args.analysis)["semantic_analysis"]
    if args.dims:
        dim_entries, notes = parse_dims(args.dims)
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

    report = build_report(dim_entries, approximate, notes)
    report_text = render_report_text(
        report, Path(args.template_dir) / "score_report.json")

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
def normalized_views(text):
    """生成两个归一化视图：compact（删零宽）与 space（零宽→空格）。

    NFKC 处理全角/兼容字符，HOMOGLYPHS 处理跨文字同形字。返回
    (compact, compact_map, space, space_map)，map[i] 为视图下标 i 对应的原文下标。
    两个视图互补：词内插零宽靠 compact，词间插零宽靠 space。
    """
    compact_chars, compact_map, space_chars, space_map = [], [], [], []
    for index, char in enumerate(text):
        for out in unicodedata.normalize("NFKC", char).translate(HOMOGLYPHS):
            if out in ZERO_WIDTH_CHARS:
                space_chars.append(" ")
                space_map.append(index)
                continue
            compact_chars.append(out)
            compact_map.append(index)
            space_chars.append(out)
            space_map.append(index)
    return "".join(compact_chars), compact_map, "".join(space_chars), space_map


def _view_hits(view, compiled):
    for pattern_id, pattern in compiled:
        for match in pattern.finditer(view):
            yield pattern_id, match.group(0), match.start(), match.end()


def collect_hits(text, compiled):
    """扫描原文 + 两个归一化视图，返回映射回原文区间且去重的命中。"""
    hits = [{"pattern_id": pid, "matched": matched, "start": start, "end": end}
            for pid, matched, start, end in _view_hits(text, compiled)]
    compact, compact_map, spaced, space_map = normalized_views(text)
    for view, index_map in ((compact, compact_map), (spaced, space_map)):
        for pid, matched, start, end in _view_hits(view, compiled):
            if end <= start:
                continue
            hits.append({
                "pattern_id": pid,
                "matched": matched,
                "start": index_map[start],
                "end": index_map[end - 1] + 1,
            })
    unique, seen = [], set()
    for hit in sorted(hits, key=lambda h: (h["start"], h["end"], h["pattern_id"])):
        key = (hit["pattern_id"], hit["start"], hit["end"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(hit)
    return unique


def public_hits(hits):
    return [{"pattern_id": h["pattern_id"], "matched": h["matched"],
             "pos": h["start"], "end": h["end"]} for h in hits]


def sanitize_by_spans(text, hits):
    """按原文区间合并替换为 [已过滤]，避免归一化视图与原文错位。"""
    spans = sorted({(h["start"], h["end"]) for h in hits if h["end"] > h["start"]})
    merged = []
    for start, end in spans:
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    out, cursor = [], 0
    for start, end in merged:
        out.append(text[cursor:start])
        out.append("[已过滤]")
        cursor = end
    out.append(text[cursor:])
    return "".join(out)


def scan_text(text):
    hits = collect_hits(text, COMPILED_BLACKLIST)
    return public_hits(hits), sanitize_by_spans(text, hits)


def scan_injection(text):
    """提示注入标记：仅提示，不阻断；供 filter/all/scenes 的 injection_flags 字段。"""
    return public_hits(collect_hits(text, COMPILED_INJECTION))


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
        "filter": {
            "blocked": blocked,
            "matches": matches,
            "injection_flags": scan_injection(text),
            "sanitized_text": sanitized,
        },
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

    prompts, skipped, missing_all = compile_prompts(registry, models, modality, semantic)
    if missing_all:
        for model, kind, fields in missing_all:
            die(f"{model}/{kind} 缺失字段：{', '.join(fields)}"
                f"（补全 semantic_analysis 后重试）", 4)

    all_matches, injection_flags = [], []
    sanitized_prompts = []
    for p in prompts:
        # 注入标记基于原始渲染文本，避免被黑名单替换后漏报
        source = f"{p['model']}/{p['kind']}"
        injection_flags.extend(
            dict(flag, prompt=source) for flag in scan_injection(p["text"]))
        matches, sanitized = scan_text(p["text"])
        all_matches.extend(matches)
        sanitized_prompts.append(dict(p, text=sanitized))
    prompts = sanitized_prompts  # --sanitize 时输出替换后的文本；默认阻断退出码 5
    blocked = len(all_matches) > 0

    # 评分
    if args.dims:
        dim_entries, notes = parse_dims(args.dims)
        approximate = False
    elif args.auto:
        auto_scores = heuristic_scores(semantic)
        dim_entries = [(k, n, w, auto_scores[k]) for k, n, w in DIMENSIONS]
        notes = {}
        approximate = True
    else:
        die("all 需要 --dims 或 --auto", 1)
    report = build_report(dim_entries, approximate, notes)

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "all",
        "modality": modality,
        "models": models,
        "prompts": prompts,
        "skipped": skipped,
        "filter": {"blocked": blocked, "matches": all_matches,
                   "injection_flags": injection_flags},
        "score_report": report,
    }
    if args.format == "json":
        emit(result, args.output)
    else:
        emit_text(result, args.output)
    if blocked and not args.sanitize:
        print("安全过滤阻断：生成结果命中黑名单，请重写后重试", file=sys.stderr)
        sys.exit(5)


def report_markdown(report):
    """纯文本输出用的评分表（与 score_report.json 的表格列保持一致）。"""
    lines = ["## 评分报告", "", "| 维度 | 权重 | 得分 | 依据 |", "|---|---:|---:|---|"]
    for dim in report.get("dimensions", []):
        note = (dim.get("note") or "—").replace("|", "\\|")
        lines.append(f"| {dim['name']} | {dim['weight']}% | {dim['score']} | {note} |")
    lines += ["", f"总分：{report['total']} / 100（等级 {report['grade']}）"]
    if report.get("approximate"):
        lines.append("（自动启发式近似评分，仅供参考）")
    for i, sug in enumerate(report.get("suggestions", []), 1):
        lines.append(f"优化建议 {i}：{sug}")
    return lines


def injection_summary(flags):
    """注入标记的一行摘要（仅提示，不影响放行）。"""
    if not flags:
        return "无"
    ids = sorted({flag["pattern_id"] for flag in flags})
    return f"{len(flags)} 处（{', '.join(ids)}）"


def emit_text(result, output):
    models = result.get("models", [])
    filter_result = result.get("filter", {})
    lines = [
        "# Prompt 编译结果",
        "",
        f"- 模态：`{result.get('modality')}`",
        f"- 目标模型：{', '.join(f'`{m}`' for m in models) or '—'}",
        f"- 安全过滤：{'命中并已处理' if filter_result.get('blocked') else '通过'}",
        f"- 注入标记：{injection_summary(filter_result.get('injection_flags', []))}",
        "",
        "## Prompt 列表",
        "",
    ]
    for p in result.get("prompts", []):
        title = p.get("display_name") or p["model"]
        if p.get("version"):
            title += f"（v{p['version']}）"
        lines += [f"### {title} · {p['kind']}", "", "```text", p["text"], "```", ""]
    r = result.get("score_report")
    if r:
        lines += report_markdown(r)
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
        image_prompts, _, image_missing = compile_prompts(
            registry, image_models, "image", scene)
        video_prompts, _, video_missing = compile_prompts(
            registry, video_models, "video", scene)
        prompts = image_prompts + video_prompts
        missing_all = image_missing + video_missing
        if missing_all:
            for model, kind, fields in missing_all:
                die(f"场景 {scene_no}（{title}）{model}/{kind} 缺失字段：{', '.join(fields)}"
                    f"（补全 semantic_analysis.scenes[{scene_no}] 后重试）", 4)

        matches, injection_flags, sanitized = [], [], []
        for p in prompts:
            source = f"{p['model']}/{p['kind']}"
            injection_flags.extend(
                dict(flag, prompt=source) for flag in scan_injection(p["text"]))
            m, s = scan_text(p["text"])
            matches.extend(m)
            sanitized.append(dict(p, text=s))
        if matches:
            blocked_any = True

        report = build_report(scene_dims[scene_no], bool(args.auto),
                              notes_map.get(scene_no))
        out_scenes.append({
            "scene_no": scene_no,
            "title": title,
            "prompts": sanitized,
            "filter": {"blocked": len(matches) > 0, "matches": matches,
                       "injection_flags": injection_flags},
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
    models = result.get("models", {})
    scenes = result.get("scenes", [])
    lines = [
        "# 叙事场景 Prompt 编译结果",
        "",
        f"- 图片模型：{', '.join(f'`{m}`' for m in models.get('image', [])) or '—'}",
        f"- 视频模型：{', '.join(f'`{m}`' for m in models.get('video', [])) or '—'}",
        "",
        "## 场景总览",
        "",
        "| 场景 | 标题 | 图片 Prompt | 视频 Prompt | 得分 | 等级 |",
        "|---:|---|---:|---:|---:|:---:|",
    ]
    for sc in scenes:
        image_n = sum(1 for p in sc.get("prompts", [])
                      if p["model"] in models.get("image", []))
        video_n = sum(1 for p in sc.get("prompts", [])
                      if p["model"] in models.get("video", []))
        r = sc.get("score_report", {})
        lines.append(
            f"| {sc['scene_no']} | {sc['title']} | {image_n} | {video_n} "
            f"| {r.get('total', '—')} | {r.get('grade', '—')} |")
    lines.append("")

    for sc in scenes:
        lines += [f"## 场景 {sc['scene_no']}：{sc['title']}", ""]
        lines.append(
            f"- 注入标记：{injection_summary(sc.get('filter', {}).get('injection_flags', []))}")
        lines.append("")
        for p in sc.get("prompts", []):
            title = p.get("display_name") or p["model"]
            if p.get("version"):
                title += f"（v{p['version']}）"
            lines += [f"### {title} · {p['kind']}", "", "```text", p["text"], "```", ""]
        r = sc.get("score_report")
        if r:
            lines += report_markdown(r)
            lines.append("")

    text = "\n".join(lines) + "\n"
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text, end="")


# ---------------------------------------------------------------------------
# validate-templates
# ---------------------------------------------------------------------------
def cmd_validate_templates(args):
    """一次性校验目录内全部模板，输出全部错误而非首个错误。"""
    registry, errors, skipped = scan_templates(args.template_dir)
    if not registry and not errors:
        errors = [(4, f"模板目录 {args.template_dir} 下未发现模型模板")]
    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "validate-templates",
        "valid": not errors,
        "model_count": len(registry),
        "models": sorted(registry),
        "skipped": skipped,
        "errors": [message for _, message in errors],
    }
    emit(result, args.output)
    if errors:
        print(f"模板校验失败：{len(errors)} 项错误", file=sys.stderr)
        sys.exit(2 if any(code == 2 for code, _ in errors) else 4)
    print(f"模板校验通过：{len(registry)} 个模型模板", file=sys.stderr)


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
    p_all.add_argument("--format", default="json",
                       choices=["json", "text", "md", "markdown"],
                       help="json 或 markdown/text（渲染排版后的 Prompt 卡片与评分表）")
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
    p_scenes.add_argument("--format", default="json",
                          choices=["json", "text", "md", "markdown"],
                          help="json 或 markdown/text（场景总览 + Prompt 卡片 + 评分表）")
    p_scenes.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_scenes.add_argument("-o", "--output")

    p_validate = sub.add_parser("validate-templates",
                                help="校验模板元数据/占位符/用途契约")
    p_validate.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_validate.add_argument("-o", "--output")

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
    elif args.command == "validate-templates":
        cmd_validate_templates(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
