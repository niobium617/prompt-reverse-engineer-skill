#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Prompt 编译/评分/安全过滤（prompt-reverse-engineer 技能组件）。

子命令：
  compile  将 semantic_analysis 按模型模板渲染为 Prompt（缺字段→退出码 4 并列出）
  score    六维加权评分（Agent 给分 --dims 或启发式 --auto）
  filter   安全过滤（命中黑名单→退出码 5 阻断，--sanitize 则替换后放行）
  all      compile + filter + score 串联
  scenes   叙事文本逐场景编译（image + video）
  shots    实拍镜头反推：逐镜头卡 → 各模型独立 Prompt（shot_style 模板）
  validate-templates  校验模板元数据/占位符/用途契约（全部错误一次列出）

任务模式：semantic_analysis.task_type（八枚举：前五通用 + 后三 Muse 扩展）经
TASK_KINDS 映射到用途（kind）；compile/all 也可用 --kind 显式选择。
两者同时给出且不一致→退出码 4；只给 task_type 时，模板若有该用途则只渲染该用途，
无该用途的模型保持原有全部渲染。
不传 task_type / --kind 时行为与旧版一致（渲染模板内全部适用用途）。

规则权威来源：references/prompt_framework.md（字段契约、评分细则、安全规则）。
注意：本文件 DIMENSIONS/SUGGESTIONS 与 prompt_framework.md 第三、五节镜像，
修改必须两处同步。新增模型=在 assets/templates/ 新增 *.json 模板，零代码改动。
退出码：0 成功 / 1 用法错误(含未知模型/无模型支持该用途) / 2 输入不可读 /
        4 契约错误(缺字段/坏评分/嵌套对象/类型不符/编号冲突) / 5 安全阻断
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

# --- 实拍镜头反推的逐镜头建议（shots 子命令专用，替换通用建议库） ---
SHOT_SUGGESTIONS = {
    "theme_clarity": "主体动作写清「谁做了什么」，一镜只保留一个可见事件",
    "scene_completeness": "补齐环境、光影、色彩三项，避免只写人物动作",
    "style_fit": "把整体风格写进每个镜头，保证跨镜统一",
    "structure_clarity": "景别、机位、运镜三项齐全，运镜不超过两个轴",
    "param_reasonableness": "按镜头实际时长填写 duration_s，并写明转场方式",
    "adaptability": "在 continuity_notes 写清跨镜一致项，便于换模型复用",
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
    # GPT Image 扁平视觉契约（prompt_framework.md 2.3 节）
    "subject_position", "subject_scale", "shot_type", "camera_angle",
    "spatial", "material", "preserve_constraints", "forbidden_changes",
    "modification_scope", "reference_images", "task_type", "uncertainty",
    # Muse Image 扩展字段（references/muse_image_rules.md）
    "spatial_relationships", "target_changes", "reference_usage",
    "feature_transfer", "feature_exclusion", "anchor_set",
    "iteration_context", "text_layout",
    # Seedance 视频扩展字段（references/seedance_rules.md）
    "first_frame", "last_frame", "source_video", "extension_plan",
    "video_references",
}

# 任务模式 → 用途（kind）；与 prompt_framework.md 2.3 节、
# model_mappings.md GPT Image / Muse Image 一节镜像。
# 前五种为通用图像任务；后三种为 Muse Image 扩展，其他模型没有对应 kind。
TASK_KINDS = {
    "text_to_image": "prompt",
    "image_recreation": "recreate",
    "image_editing": "edit",
    "reference_guided": "reference_guided",
    "image_composition": "compose",
    "anchored_composition": "anchored_composition",
    "conversational_refinement": "conversational_refinement",
    "text_layout": "text_layout",
    # 视频任务：Seedance 2.5 独立模式（references/seedance_rules.md）
    "text_to_video": "storyboard",
    "image_to_video": "image_to_video",
    "first_last_frame": "first_last_frame",
    "reference_to_video": "reference_to_video",
    "video_editing": "video_edit",
    "video_extension": "video_extend",
}
# 声明 task_type 后强制检查的必填字段（不声明时不校验，保持旧行为）
TASK_REQUIRED = {
    "text_to_image": [],
    "image_recreation": ["subject_position", "spatial"],
    "image_editing": ["modification_scope", "preserve_constraints", "forbidden_changes"],
    "reference_guided": ["reference_images", "spatial"],
    "image_composition": ["reference_images", "spatial"],
    "anchored_composition": ["reference_images", "anchor_set", "preserve_constraints"],
    "conversational_refinement": ["iteration_context", "preserve_constraints"],
    "text_layout": ["text_content", "text_layout"],
    # 视频任务
    "text_to_video": ["story"],
    "image_to_video": ["first_frame", "story"],
    "first_last_frame": ["first_frame", "last_frame", "story"],
    "reference_to_video": ["video_references", "story"],
    "video_editing": ["source_video", "target_changes", "preserve_constraints",
                      "forbidden_changes", "modification_scope"],
    "video_extension": ["source_video", "extension_plan"],
}
NEW_STRING_FIELDS = ("subject_position", "subject_scale", "shot_type",
                     "camera_angle", "spatial", "material", "text_layout",
                     "first_frame", "last_frame", "source_video",
                     "extension_plan")
NEW_LIST_FIELDS = ("preserve_constraints", "forbidden_changes",
                   "modification_scope", "reference_images", "uncertainty",
                   "spatial_relationships", "target_changes", "reference_usage",
                   "feature_transfer", "feature_exclusion", "anchor_set",
                   "iteration_context", "video_references")
# 列表字段的连接方式：逐条资产/轮次/素材每项一行，其余按语言选择分隔符
LIST_JOINERS = {"reference_images": "\n", "anchor_set": "\n",
                "iteration_context": "\n", "video_references": "\n"}
REF_ID_RE = re.compile(r"图\s*(\d+)")
# 参考图角色枚举（prompt_framework.md 2.3.3 / image_rules.md 第十一节）
REFERENCE_ROLES = (
    "edit_target", "identity_reference", "pose_reference",
    "clothing_reference", "style_reference", "composition_reference",
    "background_reference", "object_reference",
)
REFERENCE_ROLE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(REFERENCE_ROLES) + r")(?![A-Za-z0-9_])")
# Seedance 视频素材角色（references/seedance_rules.md 第六节）
# 官方 role 另有 first_frame / last_frame；本 Skill 用顶层 first_frame /
# last_frame 字段表达，不放进 video_references，避免同一信息两处维护。
VIDEO_REFERENCE_ROLES = ("reference_image", "reference_video", "reference_audio")
VIDEO_REFERENCE_ROLE_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(VIDEO_REFERENCE_ROLES) +
    r")(?![A-Za-z0-9_])")
VIDEO_REF_ID_RE = re.compile(r"素材\s*(\d+)")
# uncertainty 每项必须以置信度标签开头：observed / inferred / unknown
UNCERTAINTY_TAG_RE = re.compile(r"^(observed|inferred|unknown)\s*[:：]\s*\S", re.I)
UNCERTAINTY_ITEM_RE = re.compile(r"^(observed|inferred|unknown)\s*[:：]\s*(.+)$",
                                 re.I | re.S)
MODALITY_NAMES = {"text", "image", "video"}
KIND_RE = re.compile(r"^[a-z][a-z0-9_]*$")

# --- 实拍镜头反推契约（与 prompt_framework.md 2.6 节、shot_reverse_rules.md 镜像） ---
SHOT_SIZES = ("大远景", "远景", "全景", "中景", "近景", "特写", "大特写")
CAMERA_ANGLES = ("平拍", "仰拍", "俯拍", "低机位", "过肩", "第一人称", "鸟瞰", "斜角")
CAMERA_MOVE_TERMS = ("固定", "推", "拉", "摇", "移", "跟", "升降", "环绕",
                     "手持", "变焦", "希区柯克变焦", "甩镜", "旋转")
CAMERA_MOVE_SPLIT_RE = re.compile(r"\s*[+＋/／、]\s*")
SHOT_REQUIRED = ("shot_size", "camera_angle", "camera_move", "duration_s",
                 "subject_action", "environment", "lighting", "color",
                 "anchors", "sound", "continuity")
SHOT_STRING_FIELDS = ("shot_size", "camera_angle", "camera_move",
                      "subject_action", "environment", "lighting", "color",
                      "sound", "continuity", "lens", "focus", "transition",
                      "first_frame", "shot_note")
SHOT_LIST_FIELDS = ("anchors", "evidence")
PROGRAM_REQUIRED = ("style", "aspect_ratio", "total_duration")
PROGRAM_STRING_FIELDS = PROGRAM_REQUIRED + (
    "color_script", "sound_plan", "continuity_notes", "negative_words",
    "summary", "source_note")
SHOT_STYLE_KEYS = ("shot", "shot_prefix", "shot_suffix")
# 未指定 --models 时按模态选默认：视频四模型 / 图片六模型（均需模板含 shot_style）
VIDEO_SHOT_MODELS = "sora,runway,veo,seedance"
IMAGE_SHOT_MODELS = ("midjourney,stable_diffusion,flux2,"
                     "gpt_image,muse_image,nano_banana")
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


def _has_value(semantic, field):
    value = semantic.get(field)
    if isinstance(value, list):
        return any(str(item).strip() for item in value)
    return bool(str(value or "").strip())


def validate_semantic(semantic, where="semantic_analysis"):
    """按扁平契约校验新增视觉字段：嵌套对象、类型、task_type 枚举、参考图编号。"""
    def err(message):
        die(f"{where}：{message}", 4)

    if not isinstance(semantic, dict):
        err("必须是对象")
    for key, value in semantic.items():
        if isinstance(value, dict):
            err(f"{key} 是对象（dict）；契约要求扁平字段，请改为字符串或字符串数组")
    for key in NEW_STRING_FIELDS:
        if key in semantic and not isinstance(semantic[key], str):
            err(f"{key} 必须是字符串")
    for key in NEW_LIST_FIELDS:
        if key in semantic and not (
                isinstance(semantic[key], list)
                and all(isinstance(item, str) for item in semantic[key])):
            err(f"{key} 必须是字符串数组")
    task = semantic.get("task_type")
    if task is not None and task not in TASK_KINDS:
        err(f"task_type 必须是 {'/'.join(TASK_KINDS)} 之一，当前：{task!r}")
    refs = semantic.get("reference_images")
    if refs:
        numbers = []
        for index, item in enumerate(refs, 1):
            match = REF_ID_RE.search(item)
            if not match:
                err(f"reference_images[{index}] 缺少「图N」编号：{item}")
            numbers.append(int(match.group(1)))
            roles = REFERENCE_ROLE_RE.findall(item)
            if not roles:
                err(f"reference_images[{index}] 缺少角色枚举（"
                    f"{'/'.join(REFERENCE_ROLES)}）：{item}")
            if len(set(roles)) > 1:
                err(f"reference_images[{index}] 声明了多个角色"
                    f"（{', '.join(roles)}）；每张图只定一个角色")
        duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
        if duplicated:
            err("reference_images 编号重复："
                + ", ".join(f"图{n}" for n in duplicated))
    video_refs = semantic.get("video_references")
    if video_refs:
        numbers = []
        for index, item in enumerate(video_refs, 1):
            match = VIDEO_REF_ID_RE.search(item)
            if not match:
                err(f"video_references[{index}] 缺少「素材N」编号：{item}")
            numbers.append(int(match.group(1)))
            roles = VIDEO_REFERENCE_ROLE_RE.findall(item)
            if not roles:
                err(f"video_references[{index}] 缺少角色枚举（"
                    f"{'/'.join(VIDEO_REFERENCE_ROLES)}）：{item}")
            if len(set(roles)) > 1:
                err(f"video_references[{index}] 声明了多个角色"
                    f"（{', '.join(roles)}）；每个素材只定一个角色")
        duplicated = sorted({n for n in numbers if numbers.count(n) > 1})
        if duplicated:
            err("video_references 编号重复："
                + ", ".join(f"素材{n}" for n in duplicated))
    # 官方将首帧、首尾帧、全模态参考定义为互斥场景（seedance_rules.md §4）
    if task in ("image_to_video", "first_last_frame") and video_refs:
        err(f"task_type={task} 与 video_references 互斥；"
            "首帧/首尾帧任务请用 first_frame / last_frame 字段")
    if task == "reference_to_video" and (
            _has_value(semantic, "first_frame") or _has_value(semantic, "last_frame")):
        err("task_type=reference_to_video 不应使用 first_frame / last_frame；"
            "严格首尾帧请改用 first_last_frame")
    for index, item in enumerate(semantic.get("uncertainty") or [], 1):
        if not UNCERTAINTY_TAG_RE.match(str(item).strip()):
            err(f"uncertainty[{index}] 必须以置信度标签开头"
                f"（observed: / inferred: / unknown:）：{item}")


def validate_task_contract(semantic, where="semantic_analysis"):
    """声明 task_type 时检查该任务必填字段，缺失即退出码 4（不声明则不校验）。"""
    task = semantic.get("task_type")
    if not task:
        return
    missing = [f for f in TASK_REQUIRED[task] if not _has_value(semantic, f)]
    if missing:
        die(f"{where}：task_type={task} 缺少必填字段：{', '.join(missing)}", 4)


def resolve_kind(semantic, cli_kind, where="semantic_analysis"):
    """返回 (kind, strict)。

    strict=True 表示 --kind 显式指定：没有模型支持该用途时退出码 1。
    只给 task_type 时是该任务的建议用途，不支持的模型保持原有全部渲染。
    """
    task = semantic.get("task_type")
    if not task:
        return cli_kind, bool(cli_kind)
    mapped = TASK_KINDS[task]
    if cli_kind and cli_kind != mapped:
        die(f"{where}：task_type={task} 对应用途 {mapped}，与 --kind {cli_kind} 冲突", 4)
    return cli_kind or mapped, bool(cli_kind)


def load_analysis(path):
    data = load_json(path, "分析文件")
    if "semantic_analysis" not in data:
        die("分析文件缺少 semantic_analysis 字段（字段规范见 prompt_framework.md）", 4)
    if "modality" not in data or data["modality"] not in ("text", "image", "video", "story"):
        die("分析文件缺少有效 modality 字段（text/image/video/story）", 4)
    validate_semantic(data["semantic_analysis"])
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
            placeholders = set(FIELD_RE.findall(tmpl))
            unknown = sorted(placeholders - allowed_fields)
            if unknown:
                err(f"modalities.{modality}.{kind} 引用了未知占位符：{', '.join(unknown)}")
            if "uncertainty" in placeholders:
                err(f"modalities.{modality}.{kind} 不得引用 {{uncertainty}}："
                    "不确定项只进说明，不进 Prompt 正文")

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
            # 允许门控 default_params / optional_fields 中的字段（如 reference_images）
            unknown = sorted(set(fields) - allowed_fields)
            if unknown:
                err(f"kind_requires.{kind} 引用了未知字段：{', '.join(unknown)}")

    # 实拍镜头反推：shot_style 逐镜头模板（prompt_framework.md 2.6 节）
    shot_style = t.get("shot_style")
    if shot_style is not None:
        if not isinstance(shot_style, dict) or not shot_style:
            err("shot_style 必须是非空对象")
        else:
            if not ({"image", "video"} & set(modalities)):
                err("shot_style 只适用于含 image 或 video 模态的模板")
            allowed_shot = (allowed_fields
                            | set(SHOT_STRING_FIELDS) | set(SHOT_LIST_FIELDS)
                            | {"shot_no", "duration_s"}
                            | set(PROGRAM_STRING_FIELDS) | {"suggestions"})
            if not isinstance(shot_style.get("shot"), str) or not shot_style["shot"].strip():
                err("shot_style.shot 必须是非空字符串")
            for key, value in shot_style.items():
                if key not in SHOT_STYLE_KEYS:
                    err(f"shot_style 含未知键：{key}（可用：{', '.join(SHOT_STYLE_KEYS)}）")
                    continue
                if not isinstance(value, str):
                    err(f"shot_style.{key} 必须是字符串")
                    continue
                leftover = re.sub(r"\{\w+\}", "", value)
                if "{" in leftover or "}" in leftover:
                    err(f"shot_style.{key} 含未闭合的大括号")
                placeholders = set(FIELD_RE.findall(value))
                unknown = sorted(placeholders - allowed_shot)
                if unknown:
                    err(f"shot_style.{key} 引用了未知占位符：{', '.join(unknown)}")
                if "uncertainty" in placeholders:
                    err(f"shot_style.{key} 不得引用 {{uncertainty}}："
                        "不确定项只进说明，不进 Prompt 正文")
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
def join_values(field, items):
    """列表字段连接：reference_images 每项一行；其余按语言选分隔符。"""
    items = [str(v).strip() for v in items if str(v).strip()]
    joiner = LIST_JOINERS.get(field)
    if joiner:
        return joiner.join(items)
    if items and all(item.isascii() for item in items):
        return ", ".join(items)
    return "、".join(items)


def format_field(field, value):
    """把 semantic 字段值规范为模板可渲染的字符串。

    - 字符串：原样（去首尾空白）
    - 字符串列表：按字段选择分隔符（见 join_values）
    - 分镜对象数组（storyboard）：按 video_rules.md 分镜规范渲染为逐行文本
    - 嵌套对象：拒绝（模板只支持单层 {field} 占位，dict 会被 str() 成 repr）
    """
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        raise ValueError(
            f"字段 {field} 的值是对象（dict）；契约要求扁平字段，请改为字符串或字符串数组")
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
        return join_values(field, value)
    return str(value)


def clean_rendered(text, drop_empty_label_lines=False):
    """清理可选字段留空造成的空标签、重复标点与多余空行（确定性处理）。

    drop_empty_label_lines 由模板的 clean_empty_label_lines 开关控制：
    默认只清空标签文字（保留空行，存量模板输出逐字节不变）；
    开启后整行连同换行一起删除，避免规格书式模板留下孤立空行。
    """
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # 只匹配「整行仅有标签 + 标点」的情况，必须锚定行尾，
    # 否则会误删「标签：内容」这类有内容行的标签部分
    label_only = r"(?m)^[ \t]*[^\n:：]{1,24}[:：][ \t]*[.。；;，,、]?[ \t]*"
    if drop_empty_label_lines:
        text = re.sub(label_only + r"(?:\n|\Z)", "", text)
    else:
        text = re.sub(label_only + r"$", "", text)
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
    """返回 (status, payload)。status: ok / missing / skip / invalid

    kind_requires 用于「只有提供某字段才渲染该用途」的场景，
    例如没有 target_style 时不输出 style_transfer / edit。
    invalid 表示字段值无法渲染（如嵌套对象），payload 为错误消息。
    """
    section = template.get("modalities", {}).get(modality, {})
    if kind not in section:
        return "skip", None
    for required in template.get("kind_requires", {}).get(kind, []):
        if not _has_value(semantic, required):
            return "skip", None
    template_str = section[kind]
    fields = sorted(FIELD_RE.findall(template_str))
    optional = set(template.get("optional_fields", []))
    context, missing = {}, []
    for field in fields:
        try:
            rendered = format_field(field, semantic[field]) if field in semantic else ""
        except ValueError as exc:
            return "invalid", str(exc)
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
    return "ok", clean_rendered(
        text, drop_empty_label_lines=bool(template.get("clean_empty_label_lines"))
    )


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


def compile_prompts(registry, models, modality, semantic, kind=None, strict=False):
    """按模型列表渲染某模态，返回 (prompts, skipped, missing_all, invalid_all)。

    kind 为 None 时渲染模板内全部用途（旧行为）；指定时只渲染该用途：
    strict=True（--kind 显式指定）下不支持的模型进 skipped，全部不支持由调用方退出码 1；
    strict=False（仅由 task_type 推导）下不支持的模型维持全部渲染。
    """
    prompts, skipped, missing_all, invalid_all = [], [], [], []
    for model in models:
        template = registry[model]
        section = template.get("modalities", {})
        if modality not in section:
            skipped.append({"model": model, "reason": f"模板不支持 {modality} 模态"})
            continue
        kinds = list(section[modality])
        if kind:
            if kind in kinds:
                kinds = [kind]
            elif strict:
                skipped.append({"model": model, "reason": f"模板不支持用途 {kind}"})
                continue
        for each in kinds:
            status, payload = render_one(template, each, modality, semantic)
            if status == "ok":
                prompts.append(prompt_record(template, model, each, payload))
            elif status == "missing":
                missing_all.append((model, each, payload))
            elif status == "invalid":
                invalid_all.append((model, each, payload))
    return prompts, skipped, missing_all, invalid_all


def report_compile_errors(invalid_all, missing_all, where=""):
    """优先报契约错误（无法渲染的值），再报缺失字段；均退出码 4。"""
    prefix = f"{where}：" if where else ""
    if invalid_all:
        model, kind, message = invalid_all[0]
        die(f"{prefix}{model}/{kind} 契约错误：{message}", 4)
    if missing_all:
        for model, kind, fields in missing_all:
            die(f"{prefix}{model}/{kind} 缺失字段：{', '.join(fields)}"
                f"（补全 semantic_analysis 后重试）", 4)


REVIEW_STATUS = {"pass": "通过", "warn": "待复核", "manual": "人工确认"}


def _uncertainty_leaks(semantic, texts):
    """返回 (标签, 内容) 列表：uncertainty 项原文出现在编译结果正文中。"""
    leaks = []
    for item in semantic.get("uncertainty") or []:
        match = UNCERTAINTY_ITEM_RE.match(str(item).strip())
        if not match:
            continue
        detail = match.group(2).strip()
        if len(detail) < 4:
            continue
        if any(detail in text for text in texts):
            leaks.append((match.group(1).lower(), detail))
    return leaks


def uncertainty_warnings(semantic, texts):
    """unknown 项泄漏进正文时的提示（不改变退出码）。"""
    return [f"uncertainty 的 unknown 项疑似进入正文：{detail}"
            for tag, detail in _uncertainty_leaks(semantic, texts) if tag == "unknown"]


def build_review_checklist(semantic, prompts):
    """GPT Image 输出末尾的六项审查清单（不参与总分）。

    只做确定性结构检查：能自动判断的给 pass/warn，其余标 manual 交人工确认。
    """
    texts = [p["text"] for p in prompts]
    task = semantic.get("task_type")
    items = []

    def add(key, item, status, detail):
        items.append({"key": key, "item": item, "status": status, "detail": detail})

    # 1. 核心视觉信息
    required = TASK_REQUIRED.get(task, []) if task else []
    missing = [f for f in required if not _has_value(semantic, f)]
    if missing:
        add("core_info", "核心视觉信息是否遗漏", "warn",
            "缺少必填字段：" + "、".join(missing))
    elif not _has_value(semantic, "subject"):
        add("core_info", "核心视觉信息是否遗漏", "warn", "缺少 subject（画面主体）")
    else:
        add("core_info", "核心视觉信息是否遗漏", "pass", "必填视觉字段齐全")

    # 2. 重复描述（完全相同的字段/列表项）
    candidates = []
    for field in ("preserve_constraints", "forbidden_changes",
                  "modification_scope", "reference_images"):
        candidates.extend(str(v) for v in semantic.get(field) or [])
    for field in ("subject", "scene", "style", "lighting", "color",
                  "composition", "spatial", "material"):
        value = str(semantic.get(field) or "").strip()
        if value:
            candidates.append(value)
    normalized = [re.sub(r"[\s，,。.;；：:、]+", "", c).lower() for c in candidates]
    duplicated = sorted({c for c in normalized if len(c) >= 4 and normalized.count(c) > 1})
    if duplicated:
        add("duplicate", "是否有重复描述", "warn",
            "重复内容：" + "、".join(duplicated[:3]))
    else:
        add("duplicate", "是否有重复描述", "pass", "未发现完全相同字段/条目")

    # 3. 冲突指令（景别、机位互斥）
    def hit(field, needles):
        value = str(semantic.get(field) or "").lower()
        return any(n.lower() in value for n in needles)

    conflicts = []
    if hit("shot_type", ("特写", "close-up", "closeup")) and \
            hit("shot_type", ("远景", "全景", "wide shot", "long shot")):
        conflicts.append("shot_type 同时给了特写与远景")
    if hit("camera_angle", ("仰拍", "低角度", "low angle")) and \
            hit("camera_angle", ("俯拍", "高角度", "high angle", "鸟瞰")):
        conflicts.append("camera_angle 同时给了仰拍与俯拍")
    add("conflict", "是否有冲突指令", "warn" if conflicts else "pass",
        "；".join(conflicts) or "未发现互斥景别/机位")

    # 4. 把推测当事实
    leaks = _uncertainty_leaks(semantic, texts)
    if leaks:
        add("inference", "是否把推测当事实", "warn",
            "uncertainty 项出现在正文：" + "、".join(f"{detail}（{tag}）"
                                              for tag, detail in leaks[:3]))
    else:
        add("inference", "是否把推测当事实", "pass",
            "未发现 uncertainty 项进入正文")

    # 5. 参考图角色
    refs = semantic.get("reference_images") or []
    if not refs:
        add("reference_role", "参考图角色是否混淆", "pass", "无参考图")
    else:
        roles = []
        for item in refs:
            found = REFERENCE_ROLE_RE.findall(item)
            if found:
                roles.append(found[0])
        shared = sorted({r for r in roles if roles.count(r) > 1})
        if shared:
            add("reference_role", "参考图角色是否混淆", "warn",
                "多张图共用角色：" + "、".join(shared) + "；请在条目中写明优先级")
        else:
            add("reference_role", "参考图角色是否混淆", "pass",
                f"{len(refs)} 张参考图角色互不重复")

    # 6. 保留约束
    preserve_ok = _has_value(semantic, "preserve_constraints")
    forbidden_ok = _has_value(semantic, "forbidden_changes")
    if task == "image_editing" and not (preserve_ok and forbidden_ok):
        add("preserve", "是否缺少保留约束", "warn",
            "编辑任务需同时写明 preserve_constraints 与 forbidden_changes")
    elif task == "image_recreation" and not (preserve_ok or forbidden_ok):
        add("preserve", "是否缺少保留约束", "warn",
            "复刻任务建议写明保留项或禁止变化项")
    else:
        add("preserve", "是否缺少保留约束", "pass", "保留/禁止项已覆盖或非必需")
    return items


def build_muse_review_checklist(semantic, prompts):
    """Muse Image 输出末尾的六项审查清单（不参与总分）。

    与 GPT Image 的 review_checklist 分离：Muse 侧重空间关系、参考图迁移边界、
    Anchor / 多轮状态继承与文字版式。只做确定性结构检查。
    """
    task = semantic.get("task_type")
    items = []

    def add(key, item, status, detail):
        items.append({"key": key, "item": item, "status": status, "detail": detail})

    # 1. 核心信息：必填字段 + 使用 subject 的任务是否有主体
    required = TASK_REQUIRED.get(task, []) if task else []
    missing = [f for f in required if not _has_value(semantic, f)]
    subject_tasks = {"text_to_image", "image_recreation", "reference_guided",
                     "image_composition", "anchored_composition", "text_layout"}
    if missing:
        add("core_info", "任务目标与主体是否齐全", "warn",
            "缺少必填字段：" + "、".join(missing))
    elif task in subject_tasks and not _has_value(semantic, "subject"):
        add("core_info", "任务目标与主体是否齐全", "warn", "缺少 subject（画面主体）")
    else:
        add("core_info", "任务目标与主体是否齐全", "pass", "任务必填字段与主体齐全")

    # 2. 空间关系：多主体任务是否有逐条关系
    spatial_tasks = {"image_recreation", "reference_guided",
                     "image_composition", "anchored_composition"}
    if _has_value(semantic, "spatial_relationships"):
        add("spatial_relationships", "空间关系是否逐条明确", "pass",
            "已提供 spatial_relationships")
    elif task in spatial_tasks:
        detail = "仅有整体 spatial，建议逐条列出位置/朝向/遮挡/比例" \
            if _has_value(semantic, "spatial") else "多主体任务缺少空间关系描述"
        add("spatial_relationships", "空间关系是否逐条明确", "warn", detail)
    else:
        add("spatial_relationships", "空间关系是否逐条明确", "pass",
            "非多主体任务，可省略")

    # 3. 参考图角色与迁移边界
    refs = semantic.get("reference_images") or []
    if not refs:
        add("reference_roles", "参考图角色与迁移边界是否清楚", "pass", "无参考图")
    else:
        roles = [REFERENCE_ROLE_RE.findall(item)[0]
                 for item in refs if REFERENCE_ROLE_RE.findall(item)]
        shared = sorted({r for r in roles if roles.count(r) > 1})
        lacks_exclusion = [
            f"图{index}" for index, item in enumerate(refs, 1)
            if not re.search(r"禁止迁移|forbidden", str(item), re.I)
        ]
        if shared:
            add("reference_roles", "参考图角色与迁移边界是否清楚", "warn",
                "多张图共用角色：" + "、".join(shared) + "；请写明主次或差异")
        elif lacks_exclusion:
            add("reference_roles", "参考图角色与迁移边界是否清楚", "warn",
                "未写明禁止迁移：" + "、".join(lacks_exclusion))
        elif not _has_value(semantic, "reference_usage") and \
                not _has_value(semantic, "feature_exclusion"):
            add("reference_roles", "参考图角色与迁移边界是否清楚", "warn",
                "缺少 reference_usage / feature_exclusion，属性串扰风险较高")
        else:
            add("reference_roles", "参考图角色与迁移边界是否清楚", "pass",
                f"{len(refs)} 张参考图角色与迁移边界已写明")

    # 4. 编辑边界
    if task in ("image_editing", "conversational_refinement"):
        needed = ("target_changes", "preserve_constraints",
                  "forbidden_changes", "modification_scope")
        absent = [f for f in needed if not _has_value(semantic, f)]
        if absent:
            add("edit_boundary", "修改目标与保留边界是否完整", "warn",
                "缺少：" + "、".join(absent))
        else:
            add("edit_boundary", "修改目标与保留边界是否完整", "pass",
                "修改、保留、禁止与范围四项齐全")
    else:
        add("edit_boundary", "修改目标与保留边界是否完整", "pass", "非编辑任务")

    # 5. 连续一致性：Anchor 资产或多轮状态
    if task == "anchored_composition":
        anchors = semantic.get("anchor_set") or []
        malformed = [str(i) for i, a in enumerate(anchors, 1)
                     if not re.match(r"^\s*资产\s*\d+", str(a))]
        if not _has_value(semantic, "anchor_set"):
            add("continuity", "系列/多轮一致性能否继承", "warn", "缺少 anchor_set")
        elif malformed:
            add("continuity", "系列/多轮一致性能否继承", "warn",
                "anchor_set 建议以「资产N：」开头：" + "、".join(malformed))
        elif not _has_value(semantic, "preserve_constraints"):
            add("continuity", "系列/多轮一致性能否继承", "warn",
                "缺少 preserve_constraints，系列一致性无法约束")
        else:
            add("continuity", "系列/多轮一致性能否继承", "pass",
                f"{len(anchors)} 项锚定资产已声明")
    elif task == "conversational_refinement":
        if not _has_value(semantic, "iteration_context"):
            add("continuity", "系列/多轮一致性能否继承", "warn", "缺少 iteration_context")
        elif not _has_value(semantic, "preserve_constraints"):
            add("continuity", "系列/多轮一致性能否继承", "warn",
                "缺少 preserve_constraints，前轮已确认特征可能丢失")
        else:
            add("continuity", "系列/多轮一致性能否继承", "pass",
                "多轮状态与保留项已声明")
    else:
        add("continuity", "系列/多轮一致性能否继承", "pass", "非系列/多轮任务")

    # 6. 文字与版式
    if _has_value(semantic, "text_content"):
        if _has_value(semantic, "text_layout"):
            add("text_layout", "文字内容与版式层级是否明确", "pass",
                "文字与版式均已提供")
        else:
            add("text_layout", "文字内容与版式层级是否明确", "warn",
                "含画内文字但缺少 text_layout（字体/层级/对齐/阅读顺序）")
    elif task == "text_layout":
        add("text_layout", "文字内容与版式层级是否明确", "warn",
            "text_layout 任务缺少 text_content")
    else:
        add("text_layout", "文字内容与版式层级是否明确", "pass", "无画内文字")
    return items


def build_seedance_review_checklist(semantic, prompts):
    """Seedance 输出末尾的六项审查清单（不参与总分）。

    与 GPT / Muse 清单分离：Seedance 侧重任务场景互斥、时间结构、素材角色、
    声音设计与 API 参数边界。只做确定性结构检查。
    """
    task = semantic.get("task_type")
    items = []

    def add(key, item, status, detail):
        items.append({"key": key, "item": item, "status": status, "detail": detail})

    def text(field):
        return str(semantic.get(field) or "").strip()

    video_refs = semantic.get("video_references") or []
    generation_modes = {"text_to_video", "image_to_video",
                        "first_last_frame", "reference_to_video"}

    # 1. 核心信息
    required = TASK_REQUIRED.get(task, []) if task else []
    missing = [f for f in required if not _has_value(semantic, f)]
    if not task:
        add("core_info", "任务模式与必填信息是否齐全", "warn",
            "未声明 task_type，无法确定 Seedance 任务场景")
    elif missing:
        add("core_info", "任务模式与必填信息是否齐全", "warn",
            "缺少必填字段：" + "、".join(missing))
    else:
        add("core_info", "任务模式与必填信息是否齐全", "pass",
            "任务模式与必填字段齐全")

    # 2. 场景互斥（官方：首帧 / 首尾帧 / 全模态参考三选一）
    if task == "image_to_video" and _has_value(semantic, "last_frame"):
        add("task_mode", "任务场景是否互斥且输入合法", "warn",
            "首帧模式同时给了 last_frame；严格首尾帧请改用 first_last_frame")
    elif task == "text_to_video" and (
            video_refs or _has_value(semantic, "first_frame") or
            _has_value(semantic, "last_frame")):
        add("task_mode", "任务场景是否互斥且输入合法", "warn",
            "文生视频不应附带参考素材；请改用图生视频或全模态参考")
    elif task == "reference_to_video" and not video_refs:
        add("task_mode", "任务场景是否互斥且输入合法", "warn",
            "全模态参考任务缺少 video_references")
    elif task == "video_editing" and not text("source_video"):
        add("task_mode", "任务场景是否互斥且输入合法", "warn",
            "视频编辑任务缺少 source_video")
    elif task == "video_extension" and not (
            text("source_video") and text("extension_plan")):
        add("task_mode", "任务场景是否互斥且输入合法", "warn",
            "视频延长任务需要 source_video 与 extension_plan")
    elif not task:
        add("task_mode", "任务场景是否互斥且输入合法", "warn",
            "未声明 task_type，互斥关系无法自动校验")
    else:
        add("task_mode", "任务场景是否互斥且输入合法", "pass",
            "任务场景与输入组合合法")

    # 3. 时间结构：2.5 时长 [4, 30] 或 -1；生成类任务应有分镜
    raw = text("duration")
    duration_bad = False
    if re.fullmatch(r"-?\d+", raw):
        value = int(raw)
        duration_bad = value != -1 and not 4 <= value <= 30
    if task in generation_modes and not _has_value(semantic, "storyboard"):
        add("temporal_structure", "时间结构与镜头节奏是否明确", "warn",
            "缺少 storyboard；多镜头叙事建议逐镜头写景别、运镜与时长")
    elif duration_bad:
        add("temporal_structure", "时间结构与镜头节奏是否明确", "warn",
            f"duration={raw} 超出 Seedance 2.5 范围（4–30 秒，-1 为智能选择）")
    else:
        add("temporal_structure", "时间结构与镜头节奏是否明确", "pass",
            "时长与分镜结构可用")

    # 4. 素材角色与迁移边界
    if task == "reference_to_video":
        if not video_refs:
            add("reference_roles", "素材角色与迁移边界是否清楚", "warn",
                "缺少 video_references")
        else:
            lacks_usage = [f"素材{i}" for i, item in enumerate(video_refs, 1)
                           if "用途" not in str(item)]
            lacks_forbid = [f"素材{i}" for i, item in enumerate(video_refs, 1)
                            if not re.search(r"禁止迁移|forbidden", str(item), re.I)]
            if lacks_usage or lacks_forbid:
                add("reference_roles", "素材角色与迁移边界是否清楚", "warn",
                    "未写明用途/禁止迁移：" + "、".join(lacks_usage + lacks_forbid))
            else:
                add("reference_roles", "素材角色与迁移边界是否清楚", "pass",
                    f"{len(video_refs)} 个素材角色与迁移边界已写明")
    elif task in ("image_to_video", "first_last_frame"):
        if task == "first_last_frame" and not (
                text("first_frame") and text("last_frame")):
            add("reference_roles", "素材角色与迁移边界是否清楚", "warn",
                "首尾帧任务缺少 first_frame 或 last_frame")
        elif task == "image_to_video" and not text("first_frame"):
            add("reference_roles", "素材角色与迁移边界是否清楚", "warn",
                "首帧任务缺少 first_frame")
        else:
            add("reference_roles", "素材角色与迁移边界是否清楚", "pass",
                "首帧/尾帧角色已明确")
    else:
        add("reference_roles", "素材角色与迁移边界是否清楚", "pass",
            "非参考素材任务")

    # 5. 声音与对白：generate_audio 默认 true
    if task == "video_editing":
        add("audio_dialogue", "声音与对白是否已设计", "pass",
            "编辑任务的音频随源视频处理")
    elif _has_value(semantic, "audio") or _has_value(semantic, "dialogue") or \
            _has_value(semantic, "narration"):
        add("audio_dialogue", "声音与对白是否已设计", "pass",
            "已提供声音/对白/旁白设计")
    else:
        add("audio_dialogue", "声音与对白是否已设计", "warn",
            "generate_audio 默认 true；建议补 audio、dialogue 或 narration")

    # 6. API 参数边界：参数只进 params 块，不混入 Prompt 正文
    body = "\n".join(p["text"] for p in prompts if p["kind"] != "params")
    leaks = []
    if re.search(r"--(?:rs|rt|dur|seed|cf|wm)\b", body):
        leaks.append("--参数后缀")
    for key in ("resolution", "watermark", "generate_audio", "draft"):
        if re.search(rf"(?m)^\s*{key}\s*[:：]", body):
            leaks.append(key)
        if _has_value(semantic, key):
            leaks.append(f"semantic.{key}")
    if leaks:
        add("params_boundary", "API 参数是否留在 params 块", "warn",
            "参数混入正文或语义字段：" + "、".join(sorted(set(leaks))))
    else:
        add("params_boundary", "API 参数是否留在 params 块", "pass",
            "参数未混入 Prompt 正文")
    return items


def review_markdown(items, title="## 审查清单（不参与总分）"):
    lines = ["", title, "", "| 检查项 | 结论 | 说明 |", "|---|---|---|"]
    for item in items:
        detail = item["detail"].replace("|", "\\|")
        lines.append(f"| {item['item']} | {REVIEW_STATUS[item['status']]} | {detail} |")
    return lines


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
    validate_task_contract(semantic)
    kind, strict = resolve_kind(semantic, args.kind)

    prompts, skipped, missing_all, invalid_all = compile_prompts(
        registry, models, modality, semantic, kind=kind, strict=strict)
    report_compile_errors(invalid_all, missing_all)
    if strict and kind and not prompts:
        die(f"没有模型支持用途 {kind}（可用用途见模板 modalities）", 1)

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "compile",
        "modality": modality,
        "models": models,
        "prompts": prompts,
        "skipped": skipped,
    }
    if any(p["model"] == "gpt_image" for p in prompts):
        result["review_checklist"] = build_review_checklist(semantic, prompts)
    if any(p["model"] == "muse_image" for p in prompts):
        result["muse_review_checklist"] = build_muse_review_checklist(semantic, prompts)
    if any(p["model"] == "seedance" for p in prompts):
        result["seedance_review_checklist"] = build_seedance_review_checklist(semantic, prompts)
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
        if key in seen:
            die(f"评分维度重复：{key}", 4)
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
    validate_task_contract(semantic)
    kind, strict = resolve_kind(semantic, args.kind)

    prompts, skipped, missing_all, invalid_all = compile_prompts(
        registry, models, modality, semantic, kind=kind, strict=strict)
    report_compile_errors(invalid_all, missing_all)
    if strict and kind and not prompts:
        die(f"没有模型支持用途 {kind}（可用用途见模板 modalities）", 1)

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
    warnings = uncertainty_warnings(semantic, [p["text"] for p in prompts])
    if warnings:
        result["warnings"] = warnings
    if any(p["model"] == "gpt_image" for p in prompts):
        result["review_checklist"] = build_review_checklist(semantic, prompts)
    if any(p["model"] == "muse_image" for p in prompts):
        result["muse_review_checklist"] = build_muse_review_checklist(semantic, prompts)
    if any(p["model"] == "seedance" for p in prompts):
        result["seedance_review_checklist"] = build_seedance_review_checklist(semantic, prompts)
    if args.format == "json":
        emit(result, args.output)
    else:
        emit_text(result, args.output)
    if blocked and not args.sanitize:
        print("安全过滤阻断：生成结果命中黑名单，请重写后重试", file=sys.stderr)
        sys.exit(5)


def report_markdown(report, header="## 评分报告"):
    """纯文本输出用的评分表（与 score_report.json 的表格列保持一致）。"""
    lines = [header, "", "| 维度 | 权重 | 得分 | 依据 |", "|---|---:|---:|---|"]
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
    if result.get("review_checklist"):
        lines += review_markdown(result["review_checklist"])
    if result.get("muse_review_checklist"):
        lines += review_markdown(result["muse_review_checklist"],
                                 "## Muse Image 审查清单（不参与总分）")
    if result.get("seedance_review_checklist"):
        lines += review_markdown(result["seedance_review_checklist"],
                                 "## Seedance 审查清单（不参与总分）")
    if result.get("warnings"):
        lines += ["", "## 审查提示", ""] + [f"- {w}" for w in result["warnings"]]
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
    # scene_no 必须是 1..N 的连续整数：重复或跳号会让场景评分表对不上号
    scene_numbers = []
    for scene in scenes:
        no = scene.get("scene_no") if isinstance(scene, dict) else None
        if not isinstance(no, int):
            die("场景缺少整数 scene_no 字段：" +
                json.dumps(scene, ensure_ascii=False)[:120], 4)
        scene_numbers.append(no)
    duplicates = sorted({n for n in scene_numbers if scene_numbers.count(n) > 1})
    if duplicates:
        die(f"场景 scene_no 重复：{', '.join(str(n) for n in duplicates)}", 4)
    if scene_numbers != list(range(1, len(scene_numbers) + 1)):
        die("场景 scene_no 必须从 1 连续编号，当前：" +
            ", ".join(str(n) for n in scene_numbers), 4)

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
                if key in seen:
                    die(f"场景 {scene_no} 评分维度重复：{key}", 4)
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
        where = f"场景 {scene_no}（{title}）"
        validate_semantic(scene, where)
        # 场景若声明 task_type，按同一契约校验必填字段并只渲染该用途
        validate_task_contract(scene, where)
        scene_kind, _ = resolve_kind(scene, None, where)
        image_prompts, _, image_missing, image_invalid = compile_prompts(
            registry, image_models, "image", scene, kind=scene_kind)
        video_prompts, _, video_missing, video_invalid = compile_prompts(
            registry, video_models, "video", scene, kind=scene_kind)
        prompts = image_prompts + video_prompts
        report_compile_errors(image_invalid + video_invalid,
                              image_missing + video_missing,
                              where=f"场景 {scene_no}（{title}）")

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
# shots（实拍镜头反推）
# ---------------------------------------------------------------------------
def parse_camera_moves(value):
    """拆分复合运镜，返回 (tokens, invalid)。「推+摇」记两个轴。"""
    tokens = [t for t in CAMERA_MOVE_SPLIT_RE.split(str(value or "").strip()) if t]
    return tokens, [t for t in tokens if t not in CAMERA_MOVE_TERMS]


def validate_shots(semantic, modality, where="semantic_analysis"):
    """校验镜头卡契约（prompt_framework.md 2.6 节），返回 shots 列表。

    结构错误一律退出码 4：编号不连续、枚举非法、运镜超过两轴、
    镜头时长非正数、锚点/证据格式不符、镜头字段写成 unknown。
    """
    def err(message):
        die(f"{where}：{message}", 4)

    shots = semantic.get("shots")
    if not isinstance(shots, list) or not shots:
        err("缺少非空 shots 数组（字段规范见 prompt_framework.md 2.6 节）")
    if modality == "image" and len(shots) != 1:
        err(f"图片模态只反推单帧，shots 必须恰好 1 项，当前 {len(shots)} 项")
    for field in ("style", "aspect_ratio"):
        if not _has_value(semantic, field):
            err(f"缺少镜头组必填字段：{field}（style / aspect_ratio）")
    total = semantic.get("total_duration")
    if modality == "video" and not _has_value(semantic, "total_duration"):
        err("视频模态缺少 total_duration（镜头时长之和，单位为秒）")
    if _has_value(semantic, "total_duration"):
        try:
            total_value = float(total)
        except (TypeError, ValueError):
            err(f"total_duration 必须是秒数，当前：{total!r}")
        if total_value <= 0:
            err(f"total_duration 必须大于 0，当前：{total!r}")
        durations = [card.get("duration_s") for card in shots
                     if isinstance(card, dict)]
        numeric = all(isinstance(d, (int, float)) and not isinstance(d, bool)
                      for d in durations)
        shot_total = sum(float(d) for d in durations) if numeric else total_value
        if abs(shot_total - total_value) > 0.5:
            err(f"各镜头 duration_s 之和为 {shot_total:g} 秒，"
                f"与 total_duration {total_value:g} 秒不一致（容差 0.5 秒）")

    numbers = []
    for index, card in enumerate(shots, 1):
        label = f"shots[{index}]"
        if not isinstance(card, dict):
            err(f"{label} 必须是对象")
        for key, value in card.items():
            if isinstance(value, dict):
                err(f"{label}.{key} 是对象（dict）；镜头卡要求扁平字段")
        no = card.get("shot_no")
        if not isinstance(no, int) or isinstance(no, bool):
            err(f"{label} 缺少整数 shot_no 字段")
        numbers.append(no)
        for field in SHOT_STRING_FIELDS:
            if field in card and not isinstance(card[field], str):
                err(f"镜头 {no}：{field} 必须是字符串")
        for field in SHOT_LIST_FIELDS:
            if field in card and not (
                    isinstance(card[field], list)
                    and all(isinstance(item, str) for item in card[field])):
                err(f"镜头 {no}：{field} 必须是字符串数组")
        missing = [f for f in SHOT_REQUIRED if not _has_value(card, f)]
        if missing:
            err(f"镜头 {no} 缺少必填字段：{', '.join(missing)}")
        if card.get("shot_size") not in SHOT_SIZES:
            err(f"镜头 {no}：shot_size 必须是 {'/'.join(SHOT_SIZES)} 之一，"
                f"当前：{card.get('shot_size')!r}")
        if card.get("camera_angle") not in CAMERA_ANGLES:
            err(f"镜头 {no}：camera_angle 必须是 {'/'.join(CAMERA_ANGLES)} 之一，"
                f"当前：{card.get('camera_angle')!r}")
        tokens, invalid = parse_camera_moves(card.get("camera_move"))
        if invalid:
            err(f"镜头 {no}：camera_move 含未知运镜 {', '.join(invalid)}"
                f"（可用：{'/'.join(CAMERA_MOVE_TERMS)}，复合用 + 连接）")
        if "固定" in tokens and len(tokens) > 1:
            err(f"镜头 {no}：固定机位不能与其他运镜组合：{card.get('camera_move')}")
        if len(tokens) > 2:
            err(f"镜头 {no}：运镜最多两个轴，当前 {len(tokens)} 个"
                f"（{card.get('camera_move')}）")
        duration = card.get("duration_s")
        if isinstance(duration, bool) or not isinstance(duration, (int, float)):
            err(f"镜头 {no}：duration_s 必须是秒数")
        if duration <= 0:
            err(f"镜头 {no}：duration_s 必须大于 0")
        anchors = card.get("anchors") or []
        if len(anchors) > 5:
            err(f"镜头 {no}：anchors 最多 5 项，当前 {len(anchors)} 项")
        for i, item in enumerate(card.get("evidence") or [], 1):
            if not UNCERTAINTY_TAG_RE.match(str(item).strip()):
                err(f"镜头 {no}：evidence[{i}] 必须以置信度标签开头"
                    f"（observed: / inferred: / unknown:）：{item}")
        for field in ("lens", "focus"):
            value = str(card.get(field) or "")
            if re.search(r"unknown|未知", value, re.I):
                err(f"镜头 {no}：{field} 无法从画面确认时请省略该字段，"
                    "不要写「未知/unknown」进 Prompt")

    duplicates = sorted({n for n in numbers if numbers.count(n) > 1})
    if duplicates:
        err(f"镜头 shot_no 重复：{', '.join(str(n) for n in duplicates)}")
    if numbers != list(range(1, len(numbers) + 1)):
        err("镜头 shot_no 必须从 1 连续编号，当前：" +
            ", ".join(str(n) for n in numbers))
    return shots


def shot_storyboard(shots):
    """分镜总表（模型无关的确定性摘要）。"""
    rows = []
    for card in shots:
        rows.append({
            "shot_no": card["shot_no"],
            "shot_size": card["shot_size"],
            "camera_angle": card["camera_angle"],
            "camera_move": card["camera_move"],
            "duration_s": card["duration_s"],
            "action": card["subject_action"],
            "transition": str(card.get("transition") or ""),
        })
    return rows


def render_shot_part(template_str, template, card, program):
    """渲染 shot_style 的单段模板：镜头卡优先，其次镜头组字段与模板默认值。"""
    if not isinstance(template_str, str) or not template_str.strip():
        return ""
    defaults = template.get("default_params", {})
    context = {}
    for field in sorted(set(FIELD_RE.findall(template_str))):
        if field in card and _has_value(card, field):
            value = card[field]
        elif field in program and _has_value(program, field):
            value = program[field]
        elif field in defaults:
            value = defaults[field]
        else:
            value = ""
        context[field] = format_field(field, value) if value != "" else ""
    return clean_rendered(template_str.format(**context), drop_empty_label_lines=True)


def render_shot_prompt(template, card, program):
    """按模板的 shot_style 渲染单镜头 Prompt；无该配置返回 None。"""
    style = template.get("shot_style")
    if not isinstance(style, dict) or not str(style.get("shot", "")).strip():
        return None
    parts = [render_shot_part(style.get(key, ""), template, card, program)
             for key in ("shot_prefix", "shot", "shot_suffix")]
    text = "\n\n".join(part for part in parts if part.strip())
    return text or None


def heuristic_shot_scores(program, card):
    """逐镜头启发式近似评分，仅供离线验证；真实使用请由 Agent 用 --dims 给分。"""
    def present(value):
        return bool(str(value or "").strip())

    anchors = card.get("anchors") or []
    scores = {}
    s = 60 + (15 if len(str(card.get("subject_action", ""))) > 10 else 0)
    s += 10 if present(card.get("environment")) else 0
    s += 10 if anchors else 0
    scores["theme_clarity"] = min(s, 100)

    s = 60
    s += 15 if present(card.get("environment")) else 0
    s += 10 if present(card.get("lighting")) else 0
    s += 10 if present(card.get("color")) else 0
    scores["scene_completeness"] = min(s, 100)

    s = 60
    s += 20 if present(program.get("style")) else 0
    s += 10 if present(card.get("lighting")) else 0
    s += 10 if present(program.get("color_script")) else 0
    scores["style_fit"] = min(s, 100)

    s = 60
    s += 20 if present(card.get("camera_move")) and present(card.get("camera_angle")) else 0
    s += 10 if present(card.get("continuity")) else 0
    scores["structure_clarity"] = min(s, 100)

    s = 60
    s += 20 if card.get("duration_s") else 0
    s += 10 if present(card.get("transition")) else 0
    s += 10 if present(program.get("negative_words")) else 0
    scores["param_reasonableness"] = min(s, 100)

    s = 60
    s += 20 if present(program.get("continuity_notes")) else 0
    s += 10 if present(program.get("sound_plan")) else 0
    scores["adaptability"] = min(s, 100)
    return scores


def build_shot_review_checklist(semantic, shots, texts):
    """实拍镜头反推的六项审查清单（不参与总分）。"""
    items = []

    def add(key, item, status, detail):
        items.append({"key": key, "item": item, "status": status, "detail": detail})

    missing = []
    for card in shots:
        missing += [f"镜头{card['shot_no']}.{field}" for field in SHOT_REQUIRED
                    if not _has_value(card, field)]
    if missing:
        add("shot_contract", "镜头卡必填项是否齐全", "warn",
            "缺少字段：" + "、".join(missing))
    else:
        add("shot_contract", "镜头卡必填项是否齐全", "pass",
            f"{len(shots)} 个镜头卡必填项齐全")

    over = [f"镜头{card['shot_no']}（{card['camera_move']}）" for card in shots
            if len(parse_camera_moves(card["camera_move"])[0]) > 2]
    if over:
        add("motion_axes", "运镜轴数是否不超过两个", "warn",
            "运镜超过两轴：" + "、".join(over))
    else:
        add("motion_axes", "运镜轴数是否不超过两个", "pass",
            "每个镜头运镜均不超过两个轴")

    connectors = ("然后", "接着", "随后", "之后", "再")
    multi = [f"镜头{card['shot_no']}" for card in shots
             if sum(str(card.get("subject_action", "")).count(word)
                    for word in connectors) >= 2]
    if multi:
        add("one_event", "是否一镜只讲一个可见事件", "warn",
            "同一镜头出现多个连续动作：" + "、".join(multi))
    else:
        add("one_event", "是否一镜只讲一个可见事件", "pass",
            "镜头动作未被拆成多段事件")

    bad_anchors = [f"镜头{card['shot_no']}（{len(card.get('anchors') or [])} 个）"
                   for card in shots
                   if not 3 <= len(card.get("anchors") or []) <= 5]
    if bad_anchors:
        add("anchors", "视觉锚点是否 3–5 个且靠前", "warn",
            "锚点数量不在 3–5：" + "、".join(bad_anchors))
    else:
        add("anchors", "视觉锚点是否 3–5 个且靠前", "pass",
            "每个镜头 3–5 个视觉锚点")

    unbacked = [f"镜头{card['shot_no']}" for card in shots
                if (str(card.get("lens") or "").strip()
                    or str(card.get("focus") or "").strip())
                and not (card.get("evidence") or [])]
    leaks = [detail for tag, detail in _uncertainty_leaks(semantic, texts)
             if tag == "unknown"]
    if unbacked or leaks:
        detail = []
        if unbacked:
            detail.append("镜头焦段/焦点缺少 evidence 标签：" + "、".join(unbacked))
        if leaks:
            detail.append("unknown 项疑似进入正文：" + "、".join(leaks))
        add("lens_evidence", "镜头参数是否有画面证据", "warn", "；".join(detail))
    else:
        add("lens_evidence", "镜头参数是否有画面证据", "pass",
            "焦段/焦点均有证据标签或已省略")

    weak = [f"镜头{card['shot_no']}" for card in shots
            if not str(card.get("sound") or "").strip()
            or not str(card.get("continuity") or "").strip()]
    if weak:
        add("continuity_sound", "声音与跨镜衔接是否写明", "warn",
            "缺少声音或衔接：" + "、".join(weak))
    else:
        add("continuity_sound", "声音与跨镜衔接是否写明", "pass",
            "声音与衔接逐镜写明")
    return items


def load_shot_dims(path, shot_numbers):
    """解析逐镜头评分：[{shot_no, dims: [{key, score, note}]}]。"""
    data = load_json(path, "评分文件")
    if not isinstance(data, list):
        die("评分文件必须是数组：[{shot_no, dims: [...]}]", 4)
    known = {k for k, _, _ in DIMENSIONS}
    dims_map, notes_map, seen_shots = {}, {}, set()
    for item in data:
        if not isinstance(item, dict):
            die("评分文件每项必须是对象", 4)
        shot_no = item.get("shot_no")
        if not isinstance(shot_no, int) or isinstance(shot_no, bool):
            die("评分文件每项必须含整数 shot_no，发现：" +
                json.dumps(item, ensure_ascii=False)[:120], 4)
        if shot_no in seen_shots:
            die(f"评分文件 shot_no 重复：{shot_no}", 4)
        if shot_no not in shot_numbers:
            die(f"评分文件 shot_no={shot_no} 不在镜头列表中", 4)
        entries, seen = [], set()
        for dim in item.get("dims", []):
            key = dim.get("key")
            if key not in known:
                die(f"未知评分维度：{key}", 4)
            if key in seen:
                die(f"镜头 {shot_no} 评分维度重复：{key}", 4)
            score = dim.get("score")
            if not isinstance(score, (int, float)) or not 0 <= score <= 100:
                die(f"维度 {key} 得分须为 0-100 的数字", 4)
            entries.append((key, str(dim.get("note", "")).strip(), score))
            seen.add(key)
        missing = [k for k, _, _ in DIMENSIONS if k not in seen]
        if missing:
            die(f"镜头 {shot_no} 评分缺少维度：{', '.join(missing)}", 4)
        dims_map[shot_no] = [(k, n, w, s) for k, _, s in entries
                             for kk, n, w in DIMENSIONS if kk == k]
        notes_map[shot_no] = {k: note for k, note, _ in entries}
        seen_shots.add(shot_no)
    missing_shots = [n for n in shot_numbers if n not in dims_map]
    if missing_shots:
        die("评分文件缺少镜头：" + ", ".join(str(n) for n in missing_shots), 4)
    return dims_map, notes_map


def cmd_shots(args):
    """实拍镜头反推：镜头卡 → 分镜表 + 各视频模型逐镜头 Prompt。"""
    analysis = load_analysis(args.analysis)
    modality = analysis["modality"]
    if modality not in ("image", "video"):
        die("shots 子命令要求 analysis 的 modality 为 image 或 video", 1)
    semantic = analysis["semantic_analysis"]
    shots = validate_shots(semantic, modality)
    shot_numbers = [card["shot_no"] for card in shots]

    registry = load_registry(args.template_dir)
    if not registry:
        die(f"模板目录 {args.template_dir} 下未发现模型模板", 4)
    if args.models is None:
        args.models = (VIDEO_SHOT_MODELS if modality == "video"
                       else IMAGE_SHOT_MODELS)
    models, unknown = resolve_models(args.models, registry)
    if unknown:
        die(f"未知模型：{', '.join(unknown)}（可用：{', '.join(sorted(registry))}）", 1)
    if not models:
        die("未解析到任何模型", 1)
    capable = [m for m in models
               if isinstance(registry[m].get("shot_style"), dict)
               and str(registry[m]["shot_style"].get("shot", "")).strip()]
    if not capable:
        die("给定的模型都没有 shot_style 逐镜头模板（模板需含 shot_style 段）", 1)

    if args.dims and args.auto:
        die("--dims 与 --auto 只能二选一", 1)
    if args.dims:
        shot_dims, notes_map = load_shot_dims(args.dims, shot_numbers)
    elif args.auto:
        shot_dims, notes_map = {}, {}
        for card in shots:
            scores = heuristic_shot_scores(semantic, card)
            shot_dims[card["shot_no"]] = [
                (k, n, w, scores[k]) for k, n, w in DIMENSIONS]
            notes_map[card["shot_no"]] = {
                k: "自动近似：依据镜头卡字段完整度" for k, _, _ in DIMENSIONS}
    else:
        shot_dims, notes_map = {}, {}

    program = {key: semantic[key] for key in PROGRAM_STRING_FIELDS
               if _has_value(semantic, key)}
    if not _has_value(program, "total_duration"):
        # 图片模态不要求 total_duration：按拟生成片段时长补齐
        total = sum(float(card["duration_s"]) for card in shots)
        program["total_duration"] = int(total) if total.is_integer() else total
    skipped = [
        {"model": model,
         "reason": "模板缺少 shot_style 逐镜头模板"}
        for model in models if model not in capable
    ]

    out_shots, all_texts, blocked_any = [], [], False
    for card in shots:
        prompts = []
        for model in capable:
            template = registry[model]
            text = render_shot_prompt(template, card, program)
            if not text:
                continue
            prompts.append({
                "model": model,
                "display_name": template.get("display_name", model),
                "version": str(template.get("version", "")),
                "shot_no": card["shot_no"],
                "kind": "shot",
                "text": text,
                "template_id": template["template_id"],
                "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
            })
        matches, injection_flags, sanitized = [], [], []
        for prompt in prompts:
            source = f"{prompt['model']}/镜头{prompt['shot_no']}"
            injection_flags.extend(
                dict(flag, prompt=source) for flag in scan_injection(prompt["text"]))
            hit, clean = scan_text(prompt["text"])
            matches.extend(hit)
            sanitized.append(dict(prompt, text=clean))
        all_texts.extend(p["text"] for p in sanitized)
        if matches:
            blocked_any = True
        record = {
            "shot_no": card["shot_no"],
            "card": card,
            "prompts": sanitized,
            "filter": {"blocked": len(matches) > 0, "matches": matches,
                       "injection_flags": injection_flags},
        }
        if card["shot_no"] in shot_dims:
            report = build_report(
                shot_dims[card["shot_no"]], bool(args.auto),
                notes_map.get(card["shot_no"]))
            weakest = sorted(report["dimensions"],
                             key=lambda d: (d["score"], d["key"]))[:2]
            report["suggestions"] = [SHOT_SUGGESTIONS[d["key"]]
                                     for d in weakest
                                     if SHOT_SUGGESTIONS.get(d["key"])]
            record["score_report"] = report
        out_shots.append(record)

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "shots",
        "modality": modality,
        "models": models,
        "program": program,
        "storyboard": shot_storyboard(shots),
        "shots": out_shots,
        "skipped": skipped,
        "review_checklist": build_shot_review_checklist(
            semantic, shots, all_texts),
    }
    warnings = uncertainty_warnings(semantic, all_texts)
    if warnings:
        result["warnings"] = warnings
    if args.format == "json":
        emit(result, args.output)
    else:
        emit_shots_text(result, args.output)
    if blocked_any and not args.sanitize:
        print("安全过滤阻断：生成结果命中黑名单，请重写后重试", file=sys.stderr)
        sys.exit(5)


def emit_shots_text(result, output):
    program = result.get("program", {})
    shots = result.get("shots", [])
    models = result.get("models", [])

    def cell(value):
        return str(value if value not in (None, "") else "—").replace("|", "\\|")

    lines = [
        "# 实拍镜头反推 Prompt 编译结果",
        "",
        f"- 来源模态：`{result.get('modality')}`",
        f"- 画幅：{cell(program.get('aspect_ratio'))}",
        f"- 总时长：{cell(program.get('total_duration'))} 秒",
        f"- 目标模型：{', '.join(f'`{m}`' for m in models) or '—'}",
        "",
        "## 分镜总表",
        "",
        "| 镜头 | 景别 | 机位 | 运镜 | 时长(s) | 画面动作 | 转场 |",
        "|---:|---|---|---|---:|---|---|",
    ]
    for row in result.get("storyboard", []):
        lines.append(
            f"| {row['shot_no']} | {cell(row['shot_size'])} | {cell(row['camera_angle'])} "
            f"| {cell(row['camera_move'])} | {cell(row['duration_s'])} "
            f"| {cell(row['action'])} | {cell(row['transition'])} |")
    lines.append("")

    for shot in shots:
        card = shot.get("card", {})
        lines += [f"## 镜头 {shot['shot_no']} · {card.get('shot_size', '')} · "
                  f"{card.get('camera_angle', '')} · {card.get('camera_move', '')}", ""]
        for field, label in (("subject_action", "画面动作"), ("environment", "环境"),
                             ("lighting", "光影"), ("color", "色彩"),
                             ("sound", "声音"), ("continuity", "衔接")):
            lines.append(f"- {label}：{cell(card.get(field))}")
        anchors = card.get("anchors") or []
        lines.append(f"- 视觉锚点：{cell('、'.join(anchors))}")
        tokens, _ = parse_camera_moves(card.get("camera_move"))
        lines.append(f"- 运镜轴数：{len(tokens)}"
                     + (f"（{'、'.join(tokens)}）" if tokens else ""))
        for field, label in (("lens", "镜头（焦段）"), ("focus", "焦点"),
                             ("first_frame", "首帧提示"), ("transition", "转场")):
            if str(card.get(field) or "").strip():
                lines.append(f"- {label}：{cell(card.get(field))}")
        evidence = card.get("evidence") or []
        if evidence:
            lines.append(f"- 置信度：{'；'.join(evidence)}")
        lines.append("")
        for prompt in shot.get("prompts", []):
            title = prompt.get("display_name") or prompt["model"]
            if prompt.get("version"):
                title += f"（v{prompt['version']}）"
            lines += [f"### {title} · 镜头 {shot['shot_no']}", "",
                      "```text", prompt["text"], "```", ""]
        report = shot.get("score_report")
        if report:
            lines += report_markdown(report, header=f"### 镜头 {shot['shot_no']} 评分")
            lines.append("")

    checklist = result.get("review_checklist")
    if checklist:
        lines += review_markdown(checklist, "## 镜头审查清单（不参与总分）")
    if result.get("warnings"):
        lines += ["", "## 审查提示", ""] + [f"- {w}" for w in result["warnings"]]

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
    p_compile.add_argument("--kind",
                           help="只渲染指定用途（如 recreate/edit/reference_guided/compose）；"
                                "与 task_type 冲突或没有模型支持时退出码 4/1")
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
    p_all.add_argument("--kind",
                       help="只渲染指定用途（同 compile --kind）")
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

    p_shots = sub.add_parser(
        "shots", help="实拍镜头反推：逐镜头卡 → 各模型独立 Prompt")
    p_shots.add_argument("--analysis", required=True,
                         help="image/video 分析 JSON（semantic_analysis.shots[]）")
    p_shots.add_argument("--models",
                         help="目标模型列表（逗号分隔/别名，需模板含 shot_style；"
                              "默认视频四模型，图片六模型）")
    p_shots.add_argument("--dims",
                         help="逐镜头评分 JSON：[{shot_no, dims: [{key, score, note}]}]")
    p_shots.add_argument("--auto", action="store_true",
                         help="启发式逐镜头近似评分（仅离线验证）")
    p_shots.add_argument("--sanitize", action="store_true")
    p_shots.add_argument("--format", default="json",
                         choices=["json", "text", "md", "markdown"],
                         help="json 或 markdown/text（分镜表 + 镜头卡 + 评分表）")
    p_shots.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_shots.add_argument("-o", "--output")

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
    elif args.command == "shots":
        cmd_shots(args)
    elif args.command == "validate-templates":
        cmd_validate_templates(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
