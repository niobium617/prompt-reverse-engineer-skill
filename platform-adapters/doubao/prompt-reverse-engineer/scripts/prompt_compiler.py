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
  workflow 工作流跨平台兼容性报告（只读；不生成/不导入可导入工作流）
  ir validate  校验分析 JSON 是否符合 IR 1.0（references/ir_spec.md）
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

# --- IR v1 契约（references/ir_spec.md，甲阶段） ---
IR_VERSION = "1.0"
IR_MODULES = ("project", "subject", "scene", "visual", "shot", "prompt",
              "reference", "model", "parameters", "workflow", "assets")
IR_MAX_DEPTH = 5
IR_ASSET_KINDS = ("image", "video", "audio", "text", "workflow", "other")
IR_CONFIDENCE_STATUS = ("observed", "inferred", "unknown")
IR_WORKFLOW_FORMATS = ("comfyui_api", "comfyui_ui")
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PATH_SEP_RE = re.compile(r"[\\/:]")

# --- 工作流兼容性报告（阶段丙，只读） ---
PLATFORM_ID_RE = re.compile(r"^[a-z][a-z0-9_-]*$")
WORKFLOW_STATUS_RANK = {"compatible": 0, "degraded": 1, "incompatible": 2}
WORKFLOW_STATUS_LABEL = {
    "compatible": "可迁移",
    "degraded": "部分降级",
    "incompatible": "不可直接迁移",
}
WORKFLOW_SOURCE_FORMAT = {"comfyui_api": "api_json", "comfyui_ui": "ui_json"}

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


def ir_depth(value):
    """IR 嵌套深度：标量 0，容器为 1+子项最大深度（根对象按第 1 层计）。"""
    if isinstance(value, dict):
        return 1 + max((ir_depth(item) for item in value.values()), default=0)
    if isinstance(value, list):
        return 1 + max((ir_depth(item) for item in value), default=0)
    return 0


def ir_node_id(value):
    """节点 ID 统一为字符串；布尔/空值/其他类型返回 None。"""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return str(value)
    if isinstance(value, str) and value.strip():
        return value
    return None


def ir_has_cycle(node_ids, edges):
    """有向图环检测（迭代 DFS，避免深工作流触发递归上限）。"""
    adjacency = {node_id: [] for node_id in node_ids}
    for source, target in edges:
        if source in adjacency and target in adjacency:
            adjacency[source].append(target)
    state = {node_id: 0 for node_id in node_ids}
    for start in node_ids:
        if state[start]:
            continue
        state[start] = 1
        stack = [(start, iter(adjacency[start]))]
        while stack:
            current, iterator = stack[-1]
            try:
                nxt = next(iterator)
            except StopIteration:
                state[current] = 2
                stack.pop()
                continue
            if state[nxt] == 1:
                return True
            if state[nxt] == 0:
                state[nxt] = 1
                stack.append((nxt, iter(adjacency[nxt])))
    return False


def ir_errors(data):
    """按 references/ir_spec.md 校验 IR v1，返回错误列表（空列表=通过）。"""
    errors = []
    if not isinstance(data, dict):
        return ["分析文件顶层必须是对象"]

    version = data.get("ir_version", IR_VERSION)
    if version != IR_VERSION:
        errors.append(f'ir_version 必须是 "{IR_VERSION}"，当前：{version!r}')

    project = data.get("project")
    if project is not None:
        if not isinstance(project, dict):
            errors.append("project 必须是对象")
        else:
            for key, value in project.items():
                if not isinstance(value, str):
                    errors.append(f"project.{key} 必须是字符串")

    assets = data.get("assets")
    if assets is not None:
        if not isinstance(assets, list):
            errors.append("assets 必须是数组")
        else:
            for index, item in enumerate(assets):
                where = f"assets[{index}]"
                if not isinstance(item, dict):
                    errors.append(f"{where} 必须是对象")
                    continue
                kind = item.get("kind")
                if kind not in IR_ASSET_KINDS:
                    errors.append(f"{where}.kind 必须是 "
                                  f"{'/'.join(IR_ASSET_KINDS)} 之一，当前：{kind!r}")
                sha = item.get("sha256")
                if not isinstance(sha, str) or not SHA256_RE.match(sha):
                    errors.append(f"{where}.sha256 必须是 64 位小写十六进制摘要")
                path = item.get("path")
                if path is not None:
                    if not isinstance(path, str) or not path.strip():
                        errors.append(f"{where}.path 必须是非空字符串")
                    elif PATH_SEP_RE.search(path):
                        errors.append(f"{where}.path 只能是文件名"
                                      f"（不得含目录分隔符或盘符）：{path}")
                for key in ("role", "relation"):
                    if key in item and not isinstance(item[key], str):
                        errors.append(f"{where}.{key} 必须是字符串")

    workflow = data.get("workflow")
    if workflow is not None:
        if not isinstance(workflow, dict):
            errors.append("workflow 必须是对象或 null")
        else:
            node_ids = set()
            nodes = workflow.get("nodes")
            if not isinstance(nodes, list):
                errors.append("workflow.nodes 是必填数组")
            elif not nodes:
                errors.append("workflow.nodes 不能为空数组（工作流至少一个节点）")
            else:
                for index, node in enumerate(nodes):
                    if not isinstance(node, dict):
                        errors.append(f"workflow.nodes[{index}] 必须是对象")
                        continue
                    node_id = ir_node_id(node.get("id"))
                    if node_id is None:
                        errors.append(f"workflow.nodes[{index}].id 必须是非空字符串或整数")
                    elif node_id in node_ids:
                        errors.append(f"workflow.nodes[{index}].id 重复：{node_id}")
                    else:
                        node_ids.add(node_id)
                    class_type = node.get("class_type")
                    if not isinstance(class_type, str) or not class_type.strip():
                        errors.append(f"workflow.nodes[{index}] 缺少 class_type")
                    if "category" in node and not isinstance(node["category"], str):
                        errors.append(f"workflow.nodes[{index}].category 必须是字符串")
            for key in ("links", "models", "custom_nodes", "issues"):
                if key in workflow and not isinstance(workflow[key], list):
                    errors.append(f"workflow.{key} 必须是数组")
            fmt = workflow.get("format")
            if fmt is not None and fmt not in IR_WORKFLOW_FORMATS:
                errors.append(f"workflow.format 必须是 "
                              f"{'/'.join(IR_WORKFLOW_FORMATS)} 之一，当前：{fmt!r}")
            version = workflow.get("version")
            if version is not None and not isinstance(version, str):
                errors.append("workflow.version 必须是字符串（如 \"0.4\" / \"1.0\"）")

            links = workflow.get("links")
            edges = []
            if isinstance(links, list):
                for index, link in enumerate(links):
                    where = f"workflow.links[{index}]"
                    if not isinstance(link, dict):
                        errors.append(f"{where} 必须是对象")
                        continue
                    source = link.get("from")
                    target = link.get("to")
                    source_ok = isinstance(source, str) and bool(source.strip())
                    target_ok = isinstance(target, str) and bool(target.strip())
                    if not source_ok:
                        errors.append(f"{where}.from 必须是非空字符串")
                    elif node_ids and source not in node_ids:
                        errors.append(f"{where}.from 指向不存在的节点：{source}")
                    if not target_ok:
                        errors.append(f"{where}.to 必须是非空字符串")
                    elif node_ids and target not in node_ids:
                        errors.append(f"{where}.to 指向不存在的节点：{target}")
                    if source_ok and target_ok:
                        edges.append((source, target))
                    if "to_input" in link and not isinstance(link["to_input"], str):
                        errors.append(f"{where}.to_input 必须是字符串")
                    for key in ("from_output", "to_slot"):
                        if key in link and (not isinstance(link[key], int)
                                            or isinstance(link[key], bool)
                                            or link[key] < 0):
                            errors.append(f"{where}.{key} 必须是非负整数")
                if edges and ir_has_cycle(sorted(node_ids), edges):
                    errors.append("workflow.links 存在环（循环依赖），不符合 IR 工作流契约")

            for key in ("models", "custom_nodes", "issues"):
                items = workflow.get(key)
                if not isinstance(items, list):
                    continue
                for index, item in enumerate(items):
                    where = f"workflow.{key}[{index}]"
                    if key == "issues":
                        if not isinstance(item, str):
                            errors.append(f"{where} 必须是字符串")
                    elif key == "models":
                        if isinstance(item, str):
                            continue
                        if not isinstance(item, dict):
                            errors.append(f"{where} 必须是字符串或对象")
                        elif "name" in item and not isinstance(item["name"], str):
                            errors.append(f"{where}.name 必须是字符串")
                    else:
                        if isinstance(item, str):
                            continue
                        if not isinstance(item, dict):
                            errors.append(f"{where} 必须是字符串或对象")
                        elif not isinstance(item.get("class_type"), str) \
                                or not item["class_type"].strip():
                            errors.append(f"{where} 缺少 class_type")

            workflow_assets = workflow.get("assets")
            if workflow_assets is not None:
                if not isinstance(workflow_assets, list):
                    errors.append("workflow.assets 必须是数组")
                else:
                    for index, item in enumerate(workflow_assets):
                        where = f"workflow.assets[{index}]"
                        if not isinstance(item, dict):
                            errors.append(f"{where} 必须是对象")
                            continue
                        if not isinstance(item.get("name"), str) \
                                or not item["name"].strip():
                            errors.append(f"{where}.name 必须是非空字符串")
                        if "kind" in item and item["kind"] not in IR_ASSET_KINDS:
                            errors.append(f"{where}.kind 必须是 "
                                          f"{'/'.join(IR_ASSET_KINDS)} 之一，"
                                          f"当前：{item['kind']!r}")

            parameters = workflow.get("parameters")
            if parameters is not None:
                if not isinstance(parameters, list):
                    errors.append("workflow.parameters 必须是数组")
                else:
                    for index, item in enumerate(parameters):
                        where = f"workflow.parameters[{index}]"
                        if not isinstance(item, dict):
                            errors.append(f"{where} 必须是对象")
                            continue
                        if ir_node_id(item.get("node")) is None:
                            errors.append(f"{where}.node 必须是非空字符串或整数")
                        if not isinstance(item.get("values"), dict):
                            errors.append(f"{where}.values 必须是对象")

            deps = workflow.get("deps")
            if deps is not None:
                if not isinstance(deps, dict):
                    errors.append("workflow.deps 必须是对象")
                else:
                    for key, value in deps.items():
                        if not isinstance(value, list) or not all(
                                isinstance(entry, str) for entry in value):
                            errors.append(f"workflow.deps.{key} 必须是字符串数组")
            stats = workflow.get("stats")
            if stats is not None and not isinstance(stats, dict):
                errors.append("workflow.stats 必须是对象")

    confidence = data.get("confidence")
    if confidence is not None:
        if not isinstance(confidence, dict):
            errors.append("confidence 必须是对象")
        else:
            for module, entry in confidence.items():
                where = f"confidence.{module}"
                if module not in IR_MODULES:
                    errors.append(f"{where} 不是 IR 模块名"
                                  f"（允许：{'/'.join(IR_MODULES)}）")
                if not isinstance(entry, dict):
                    errors.append(f"{where} 必须是对象")
                    continue
                status = entry.get("status")
                if status not in IR_CONFIDENCE_STATUS:
                    errors.append(f"{where}.status 必须是 "
                                  f"{'/'.join(IR_CONFIDENCE_STATUS)} 之一，"
                                  f"当前：{status!r}")
                basis = entry.get("basis")
                if not isinstance(basis, str) or not basis.strip():
                    errors.append(f"{where}.basis 必须是非空字符串")
                if "evidence" in entry and not isinstance(entry["evidence"], (str, list)):
                    errors.append(f"{where}.evidence 必须是字符串或数组")

    for key in ("project", "assets", "workflow", "confidence"):
        if key in data:
            depth = ir_depth(data[key])
            if depth > IR_MAX_DEPTH:
                errors.append(f"{key} 嵌套深度 {depth} 超过上限 {IR_MAX_DEPTH}")
    return errors


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


def build_report(dim_entries, approximate, notes=None, suggestion_pool=None):
    total = round(sum(w * s for _, _, w, s in dim_entries) / 100.0, 1)
    grade = "A" if total >= 90 else "B" if total >= 75 else "C" if total >= 60 else "D"
    ranked = sorted(dim_entries, key=lambda e: (e[3], e[0]))
    suggestions = []
    for key, name, _, _ in ranked[:2]:
        pool = suggestion_pool or SUGGESTIONS
        if pool.get(key):
            suggestions.append(pool[key][0])
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
# optimize（已有 Prompt 诊断与优化）
# ---------------------------------------------------------------------------
TEXT_MODEL_IDS = ("gpt4_claude", "deepseek")
VIDEO_MODEL_IDS = ("seedance", "sora2", "runway", "veo3", "kling", "hailuo", "vidu")
IMAGE_MODEL_IDS = ("midjourney", "stable_diffusion", "flux2", "gpt_image",
                   "muse_image", "nano_banana", "jimeng")

# 只认语法特征与明确模型名；单独的「Midjourney 风格」不自动判定为 MJ 原稿。
MODEL_SIGNATURES = [
    ("deepseek", r"deepseek(?:[- ]v?4)?|\[模型\]"),
    ("gpt4_claude", r"\[system\]|##\s*角色|\bclaude\b|\bgpt-?5(?:\.5)?\b"),
    ("seedance", r"\bseedance\b"),
    ("sora2", r"\bsora(?:[- ]?2)?\b"),
    ("runway", r"\brunway\b|\bgen-4(?:\.5)?\b"),
    ("veo3", r"\bveo(?:[- ]?3(?:\.1)?)?\b"),
    ("kling", r"\bkling\b|可灵|【整体设定】"),
    ("hailuo", r"\bhailuo\b|海螺|integrated_multimodal_description"),
    ("vidu", r"\bvidu\b|\[@[^\]]+\]"),
    ("jimeng", r"即梦|seedream"),
    ("muse_image", r"\bmuse(?:\s*image)?\b"),
    ("gpt_image", r"gpt[- ]?image|dall-e|create an image with the following specification"),
    ("nano_banana", r"nano\s*banana"),
    ("flux2", r"\bflux(?:\.2)?\b"),
    ("stable_diffusion", r"stable diffusion|positive\s*:|negative prompt|cfg scale"),
    ("midjourney", r"/imagine\b|--ar\s+\d|--v\s+\d|--no\s+"),
]

VIDEO_SIGNALS = [
    r"分镜", r"运镜", r"镜头语言", r"\[shot\s*\d", r"镜头\s*\d+",
    r"storyboard", r"\d+\s*(?:秒|seconds?)\b", r"camera (?:move|movement|pan|tilt)",
]
IMAGE_SIGNALS = [
    r"/imagine", r"--ar\b", r"positive\s*:", r"negative prompt", r"主体",
    r"构图", r"光影", r"色调", r"画面", r"aspect ratio", r"背景",
    r"女孩|男孩|女子|男子|人物|角色", r"霓虹|赛博|街|城市|森林|海边|室内|室外",
    r"8k|4k|高清|超清|电影感|画质", r"广角|长焦|微距|俯拍|仰拍|特写",
    r"close-up|wide shot|medium shot", r"lighting", r"composition",
]
TEXT_SIGNALS = [
    r"\[system\]", r"##\s*角色", r"输出格式", r"受众", r"写一篇|写一段|撰写|起草",
    r"\brole\b|\byou are\b", r"\btask\b", r"constraints?", r"\baudience\b",
    r"小说|文章|文案|剧本|报告|邮件|总结|翻译|演讲稿|段落|字数|读者",
]
STRONG_TEXT_SIGNALS = r"小说|文章|文案|剧本|报告|邮件|总结|翻译|演讲稿|字数|段落|读者"
STRONG_VIDEO_SIGNALS = r"分镜|运镜|镜头语言|镜头\s*\d+|\[shot\s*\d+|\d+\s*(?:秒|seconds?)"

CONFLICT_PAIRS = [
    ("白天", "夜晚", "scene_completeness", "时间冲突"),
    ("晴天", "雨天", "scene_completeness", "天气冲突"),
    ("室内", "室外", "scene_completeness", "空间冲突"),
    ("写实", "卡通", "style_fit", "风格冲突"),
    ("冷色调", "暖色调", "style_fit", "色调冲突"),
    ("固定镜头", "环绕", "param_reasonableness", "运镜冲突"),
    ("特写", "远景", "param_reasonableness", "景别冲突"),
]
VAGUE_WORDS = (
    "好看的", "好看", "高级感", "氛围感", "有感觉", "很酷", "一些", "等等",
    "随便", "差不多", "漂亮", "震撼", "大片感", "whatever", "something",
    "nice", "beautiful", "amazing", "interesting",
)
SEVERITY_PENALTY = {"high": 12, "medium": 6, "low": 3}
SEVERITY_RANK = {"high": 0, "medium": 1, "low": 2}
SEVERITY_LABEL = {"high": "高", "medium": "中", "low": "低"}
PLACEHOLDER_RE = re.compile(
    r"\[(?!shot\b|镜头|图\d|素材\d|@|已过滤)[^\]\n]{1,24}\]"
    r"|\{[^}\n]{1,24}\}|<[^>\n]{1,24}>", re.I)
ASPECT_RATIO_RE = re.compile(r"\b\d{1,3}\s*[:：]\s*\d{1,3}\b")
DURATION_RE = re.compile(r"\d+\s*(?:秒|s\b|seconds?)", re.I)
PHOTO_PARAM_RE = re.compile(
    r"\b\d{2,3}\s*mm\b|\bf/\d(?:\.\d+)?\b|\biso\s*\d+|\b\d+\s*(?:mm|毫米)\b", re.I)


def _has_markers(text, markers):
    lower = text.lower()
    return any(marker.lower() in lower for marker in markers)


def _subject_signal(text):
    cleaned = re.sub(r"--[a-z]+(?:\s+[^\s,，;；]+)?", " ", text, flags=re.I)
    cleaned = re.sub(r"\[[^\]]*\]|\{[^}]*\}", " ", cleaned)
    cleaned = re.sub(r"[\s,，。.;；:：/\\|_\-]+", "", cleaned)
    return len(cleaned) >= 3


def _placeholder_signal(text):
    return bool(PLACEHOLDER_RE.search(text))


def _photo_params_signal(text):
    return bool(PHOTO_PARAM_RE.search(text)) or _has_markers(
        text, ("光圈", "快门", "景深", "焦段", "镜头参数", "aperture", "shutter",
               "depth of field", "bokeh", "lens"))


def _storyboard_signal(text):
    return bool(re.search(r"镜头\s*\d+|\[shot\s*\d+|shot\s*\d+|scene\s*\d+",
                          text, re.I)) or _has_markers(
        text, ("分镜", "storyboard", "镜头表", "分镜表"))


def _duration_signal(text):
    return bool(DURATION_RE.search(text)) or _has_markers(text, ("时长", "duration"))


def _aspect_ratio_signal(text):
    return bool(ASPECT_RATIO_RE.search(text)) or _has_markers(text, ("画幅", "aspect ratio"))


def _feat(fid, label, dimension, weight, markers=(), *, required=False,
          severity="low", fix="", detector=None):
    return {
        "id": fid, "label": label, "dimension": dimension, "weight": weight,
        "markers": tuple(markers), "required": required, "severity": severity,
        "fix": fix, "detector": detector,
    }


IMAGE_FEATURES = [
    _feat("subject", "主体", "theme_clarity", 5,
          required=True, severity="high",
          fix="首句写清主体（谁/什么）与至少 2 个可辨识特征",
          detector=_subject_signal),
    _feat("scene", "场景", "scene_completeness", 3,
          ("场景", "环境", "背景", "地点", "街头", "室内", "室外", "森林", "海边",
           "城市", "scene", "background", "environment", "setting", "location"),
          required=True, severity="high",
          fix="补时间 + 地点 + 氛围，如「雨夜霓虹街头，潮湿反光地面」"),
    _feat("composition", "构图", "structure_clarity", 3,
          ("构图", "景别", "视角", "特写", "近景", "中景", "远景", "全景", "仰拍",
           "俯拍", "平视", "三分法", "居中", "对称", "composition", "framing",
           "close-up", "wide shot", "medium shot", "camera angle", "rule of thirds"),
          required=True, severity="high",
          fix="补景别 + 机位 + 构图方式，如「低角度仰拍，全景，三分法」"),
    _feat("lighting", "光影", "scene_completeness", 2,
          ("光", "照明", "逆光", "侧光", "柔光", "硬光", "霓虹", "烛光", "光影",
           "轮廓光", "打光", "lighting", "backlit", "rim light", "neon",
           "soft light", "hard light", "golden hour"),
          required=True, severity="high",
          fix="补光源 + 方向 + 明暗，如「霓虹侧光与轮廓光，高对比夜色」"),
    _feat("color", "色彩", "scene_completeness", 2,
          ("色彩", "色调", "主色", "配色", "饱和度", "色温", "暖色", "冷色",
           "color", "palette", "saturation", "color temperature", "warm tone",
           "cool tone"),
          required=True, severity="high",
          fix="补主色 + 点缀色 + 饱和度，如「深蓝紫主色，霓虹橙点缀」"),
    _feat("style", "风格", "style_fit", 3,
          ("风格", "画风", "摄影", "电影感", "写实", "插画", "动漫", "油画",
           "水彩", "赛博朋克", "复古", "极简", "style", "cinematic",
           "photorealistic", "illustration", "anime", "painting", "vintage",
           "minimalist"),
          severity="medium", fix="补 1-2 个风格锚点词（见 image_rules.md 术语库）"),
    _feat("photo_params", "摄影参数", "param_reasonableness", 2,
          severity="medium", fix="补焦段/光圈/景深，如「24mm，f/2.8，深景深」",
          detector=_photo_params_signal),
    _feat("quality_words", "质量词", "style_fit", 1,
          ("8k", "4k", "高清", "超清", "细节", "电影级", "高画质", "杰作",
           "ultra detailed", "high resolution", "masterpiece", "best quality",
           "sharp focus"),
          fix="补 2-3 个质量词，如「ultra detailed, 8K, cinematic」"),
    _feat("negative_words", "负向词", "param_reasonableness", 2,
          ("--no", "negative prompt", "negative words", "反向词", "负面词",
           "负面提示", "避免", "不要出现", "禁止出现", "avoid", "no "),
          fix="补负向三类：质量缺陷 / 多余元素 / 解剖错误（见 image_rules.md）"),
    _feat("text_content", "画内文字", "theme_clarity", 1,
          ("画面文字", "招牌", "字幕", "标题文字", "text in image", "sign", "caption"),
          fix="有画内文字时逐字写明并加引号"),
    _feat("reference_note", "参考素材", "adaptability", 1,
          ("参考图", "参考素材", "图1", "图2", "reference image", "reference"),
          fix="有参考图时逐张写「图N：角色/用途」"),
    _feat("placeholder", "变量占位", "adaptability", 1,
          fix="把可变项写成 [变量]，便于复用", detector=_placeholder_signal),
]

TEXT_FEATURES = [
    _feat("role", "角色", "structure_clarity", 2,
          ("你是", "扮演", "角色是", "role", "act as", "you are"),
          required=True, severity="high",
          fix="补角色：身份 / 专业领域 / 人设"),
    _feat("task", "任务", "theme_clarity", 4,
          ("任务", "撰写", "写一篇", "写一段", "写", "生成", "创作", "起草",
           "分析", "翻译", "总结", "task", "write", "create", "generate",
           "draft", "compose"),
          required=True, severity="high",
          fix="首段直接写清要完成的任务与交付物"),
    _feat("context", "背景", "scene_completeness", 2,
          ("背景", "受众", "读者", "用户", "产品", "场景", "context", "background",
           "audience", "reader", "product"),
          severity="medium", fix="补背景：受众、使用场景、已有材料"),
    _feat("style", "风格", "style_fit", 2,
          ("风格", "语气", "语调", "文风", "style", "tone", "voice"),
          required=True, severity="high",
          fix="补写作风格与语气，如「专业克制，面向开发者」"),
    _feat("structure", "结构", "structure_clarity", 2,
          ("结构", "开头", "结尾", "分段", "步骤", "outline", "structure",
           "sections"),
          required=True, severity="high",
          fix="写清结构：开头 / 展开 / 结尾或分段顺序"),
    _feat("constraints", "约束", "param_reasonableness", 3,
          ("限制", "字数", "不超过", "不少于", "禁止", "避免", "constraint",
           "no more than", "within", "must not", "word count"),
          required=True, severity="high",
          fix="补硬约束：字数、格式、禁用词、必须包含项"),
    _feat("output_format", "输出格式", "structure_clarity", 1,
          ("输出格式", "格式", "output format", "format", "json", "markdown"),
          severity="medium", fix="补输出格式：Markdown / JSON / 表格 / 分段"),
    _feat("audience", "受众", "theme_clarity", 1,
          ("受众", "读者", "面向", "audience", "reader", "for beginners"),
          fix="补目标受众，避免内容泛化"),
    _feat("reference_note", "参考素材", "adaptability", 1,
          ("参考范文", "参考", "reference", "示例", "example"),
          fix="有参考范文时标明可借鉴与不可照搬的部分"),
    _feat("placeholder", "变量占位", "adaptability", 1,
          fix="把主题/对象写成 [变量]，便于复用", detector=_placeholder_signal),
]

VIDEO_FEATURES = [
    _feat("story", "故事", "theme_clarity", 4,
          ("故事", "情节", "叙事", "剧情", "起承转合", "story", "narrative", "plot"),
          required=True, severity="high",
          fix="补故事线：谁在什么处境下做了什么，结果如何"),
    _feat("character", "人物", "theme_clarity", 1,
          ("人物", "角色", "主角", "女子", "男子", "character", "protagonist"),
          severity="medium", fix="补人物外形、服装与动作状态"),
    _feat("storyboard", "分镜", "structure_clarity", 3,
          required=True, severity="high",
          fix="按镜头拆写：镜头N + 时长 + 景别 + 动作",
          detector=_storyboard_signal),
    _feat("camera", "运镜", "param_reasonableness", 2,
          ("运镜", "推镜", "拉镜", "摇镜", "移镜", "跟拍", "环绕", "升降",
           "固定镜头", "camera move", "pan", "tilt", "dolly", "tracking shot",
           "zoom", "orbit"),
          severity="medium", fix="补运镜方式，单镜不超过两个轴"),
    _feat("atmosphere", "氛围", "scene_completeness", 2,
          ("氛围", "气氛", "天气", "环境", "atmosphere", "mood", "weather",
           "environment"),
          severity="medium", fix="补环境与氛围：地点、天气、时间"),
    _feat("lighting", "光影", "scene_completeness", 2,
          ("光", "照明", "逆光", "侧光", "柔光", "硬光", "霓虹", "烛光", "光影",
           "轮廓光", "打光", "lighting", "backlit", "rim light", "neon",
           "soft light", "hard light", "golden hour"),
          severity="medium", fix="补光源方向与明暗关系"),
    _feat("color", "色彩", "scene_completeness", 1,
          ("色彩", "色调", "主色", "配色", "饱和度", "色温", "暖色", "冷色",
           "color", "palette", "saturation", "color temperature"),
          fix="补主色与色彩走向"),
    _feat("style", "风格", "style_fit", 3,
          ("风格", "画风", "电影感", "写实", "动画", "赛博朋克", "复古", "style",
           "cinematic", "photorealistic", "anime", "vintage"),
          severity="medium", fix="补整体风格锚点，保证跨镜统一"),
    _feat("audio", "声音", "structure_clarity", 1,
          ("声音", "音效", "配乐", "对白", "环境音", "旁白", "audio", "sound",
           "music", "dialogue", "voiceover"),
          fix="补声音设计：环境音 / 音效 / 对白 / 配乐"),
    _feat("duration", "时长", "param_reasonableness", 1,
          severity="medium", fix="写清总时长与逐镜时长",
          detector=_duration_signal),
    _feat("aspect_ratio", "画幅", "param_reasonableness", 1,
          severity="medium", fix="补画幅，如 16:9 / 9:16",
          detector=_aspect_ratio_signal),
    _feat("reference_note", "参考素材", "adaptability", 1,
          ("参考图", "参考视频", "参考素材", "图1", "素材1", "reference"),
          fix="有参考素材时逐项写「素材N：用途 / 保留 / 禁止迁移」"),
    _feat("placeholder", "变量占位", "adaptability", 1,
          fix="把可变项写成 [变量]，便于复用", detector=_placeholder_signal),
]

FEATURE_SPECS = {"text": TEXT_FEATURES, "image": IMAGE_FEATURES, "video": VIDEO_FEATURES}
AUDIT_SUGGESTIONS = {
    "image": {
        "theme_clarity": ["首句写清主体与 2 个可辨识特征", "删除画面中无法呈现的抽象修饰"],
        "scene_completeness": ["补时间、地点、氛围三要素", "补主色 + 点缀色 + 饱和度"],
        "style_fit": ["补 1-2 个风格锚点词（见 image_rules.md）", "删除与整体风格冲突的修饰"],
        "structure_clarity": ["按七段结构重排：主体→场景→风格→光影→色彩→构图→参数"],
        "param_reasonableness": ["补焦段/光圈/景深，并核对模型参数语法"],
        "adaptability": ["把主体、风格、画幅写成 [变量] 便于复用"],
    },
    "video": {
        "theme_clarity": ["第一句写清故事线与主角目标", "一镜只保留一个可见事件"],
        "scene_completeness": ["补环境、光影、色彩与氛围", "用具体地点替换泛化场景词"],
        "style_fit": ["补整体风格锚点，保证跨镜统一"],
        "structure_clarity": ["按镜头拆写：镜头N + 时长 + 景别 + 动作 + 运镜"],
        "param_reasonableness": ["补总时长、逐镜时长与画幅，单镜运镜不超过两轴"],
        "adaptability": ["把人物、场景、时长写成 [变量]，并写清跨镜一致项"],
    },
}
DEFAULT_OPTIMIZE_MODELS = {"text": "gpt4_claude", "image": "default", "video": "sora2"}
FEATURE_FIELDS = {
    "text": {
        "role": ("role",), "task": ("task",), "context": ("context", "audience"),
        "style": ("style",), "structure": ("structure",),
        "constraints": ("constraints",), "output_format": ("output_format",),
        "audience": ("audience",), "reference_note": ("reference_note",),
    },
    "image": {
        "subject": ("subject",), "scene": ("scene",), "composition": ("composition",),
        "lighting": ("lighting",), "color": ("color",), "style": ("style",),
        "photo_params": ("photo_params",), "quality_words": ("quality_words",),
        "negative_words": ("negative_words",), "text_content": ("text_content",),
        "reference_note": ("reference_note", "reference_images"),
    },
    "video": {
        "story": ("story",), "character": ("character",), "storyboard": ("storyboard",),
        "camera": ("camera",), "atmosphere": ("atmosphere",), "lighting": ("lighting",),
        "color": ("color",), "style": ("style",), "audio": ("audio", "narration", "dialogue"),
        "duration": ("duration",), "aspect_ratio": ("aspect_ratio",),
        "reference_note": ("reference_note", "video_references"),
    },
}


def _modality_scores(text):
    return {
        "video": sum(1 for p in VIDEO_SIGNALS if re.search(p, text, re.I)),
        "image": sum(1 for p in IMAGE_SIGNALS if re.search(p, text, re.I)),
        "text": sum(1 for p in TEXT_SIGNALS if re.search(p, text, re.I)),
    }


def detect_model(text):
    for model, pattern in MODEL_SIGNATURES:
        if re.search(pattern, text, re.I):
            return model
    return None


def model_modality(registry, model):
    """模型模板支持的唯一模态；多模态模板返回 None（交给内容信号判断）。"""
    if model not in registry:
        return None
    supported = [m for m in ("text", "image", "video")
                 if m in registry[model].get("modalities", {})]
    return supported[0] if len(supported) == 1 else None


def choose_modality(registry, model, text):
    scores = _modality_scores(text)
    if model in registry:
        supported = set(registry[model].get("modalities", {}))
    else:
        supported = {"text", "image", "video"}
    if not supported:
        supported = {"text"}
    # 强信号优先：带镜头编号/时长的是视频；带小说/文章/字数的是文本；
    # 其余按命中数排序，至少 2 个信号才判为视觉模态，避免把普通描述误判成图片。
    if "video" in supported and re.search(STRONG_VIDEO_SIGNALS, text, re.I):
        return "video"
    if "text" in supported and re.search(STRONG_TEXT_SIGNALS, text, re.I) and not \
            re.search(r"/imagine\b|--ar\s+\d|positive\s*:|negative prompt", text, re.I):
        return "text"
    ranked = sorted(scores.items(),
                    key=lambda item: (-item[1], ("video", "image", "text").index(item[0])))
    for modality, score in ranked:
        if modality in supported and (score >= 2 or len(supported) == 1):
            return modality
    for modality in ("text", "image", "video"):
        if modality in supported:
            return modality
    return "text"


def _detect_feature(text, spec):
    if spec["detector"]:
        return spec["detector"](text)
    return _has_markers(text, spec["markers"])


def _issue(issue_id, dimension, severity, title, evidence, fix):
    return {
        "id": issue_id, "dimension": dimension, "severity": severity,
        "title": title, "evidence": evidence, "fix": fix,
    }


def _missing_issues(features, specs):
    issues = []
    for spec in specs:
        if features.get(spec["id"]):
            continue
        severity = "high" if spec["required"] else spec["severity"]
        issues.append(_issue(
            f"missing_{spec['id']}", spec["dimension"], severity,
            f"缺少{spec['label']}",
            f"未检出「{spec['label']}」信号（关键词：{'、'.join(spec['markers'][:3]) or '长度不足'}）",
            spec["fix"],
        ))
    return issues


def _quality_issues(text, modality):
    issues = []
    lower = text.lower()
    vague = sorted({word for word in VAGUE_WORDS if word in lower})
    if vague:
        issues.append(_issue(
            "vague_wording", "theme_clarity", "medium" if len(vague) > 1 else "low",
            "存在模糊修饰词", "、".join(vague[:6]),
            "替换为可观察的具体名词/形容词，如「高级感」→「低饱和莫兰迪配色」",
        ))
    segments = [seg.strip().lower() for seg in re.split(r"[,，;；。\n]+", text)
                if len(seg.strip()) >= 4]
    duplicated = sorted({seg for seg in segments if segments.count(seg) >= 2})
    adjacent = re.findall(r"([一-鿿]{2,8})\1", text)
    if duplicated or adjacent:
        evidence = "、".join(duplicated[:3] + adjacent[:3]) or "相邻重复短语"
        issues.append(_issue(
            "duplicate_wording", "structure_clarity", "low",
            "存在重复表述", evidence, "删除重复词，合并为一次具体描述",
        ))
    if modality != "video":
        for index, (left, right, dimension, label) in enumerate(CONFLICT_PAIRS):
            if left in text and right in text:
                issues.append(_issue(
                    f"conflict_{index}", dimension, "medium", label,
                    f"同时出现「{left}」与「{right}」",
                    "确认是否为有意的时间/空间变化；单画面 Prompt 只保留一个方向",
                ))
    ratios = sorted({match.group(0).replace("：", ":")
                     for match in ASPECT_RATIO_RE.finditer(text)})
    if len(ratios) > 1:
        issues.append(_issue(
            "aspect_ratio_conflict", "param_reasonableness", "medium",
            "画幅声明冲突", "、".join(ratios),
            "一个 Prompt 只保留一个画幅；多画幅请拆成多条 Prompt",
        ))
    return issues


def _syntax_issues(model, text, modality):
    if not model:
        return []
    issues = []
    lower = text.lower()
    mj_flag = "/imagine" in lower or bool(re.search(r"--(?:ar|v|no)\b", lower))

    def add(severity, dimension, title, evidence, fix):
        issues.append(_issue("syntax_" + str(len(issues) + 1), dimension,
                             severity, title, evidence, fix))

    if model == "midjourney":
        match = re.search(r"--ar\s+(\S+)", text, re.I)
        if match and not re.fullmatch(r"\d{1,3}:\d{1,3}", match.group(1)):
            add("high", "param_reasonableness", "--ar 参数格式错误",
                f"--ar {match.group(1)}", "改为 --ar 16:9 这类「宽:高」格式")
        elif mj_flag and not re.search(r"--ar\s+\d{1,3}:\d{1,3}", text, re.I):
            add("medium", "param_reasonableness", "缺少 --ar 画幅",
                "未检出 --ar", "补 --ar 16:9 或 --ar 9:16，避免默认画幅")
        if "negative prompt" in lower:
            add("medium", "param_reasonableness", "负向写法不符合 MJ",
                "出现 Negative prompt:", "Midjourney 用 --no 列表，不用 Negative prompt:")
    elif model == "stable_diffusion":
        if mj_flag:
            add("high", "param_reasonableness", "混入 Midjourney 参数",
                "出现 /imagine 或 --ar/--v/--no", "SD 用 Positive/Negative 分段，参数另起一行")
        if not re.search(r"negative\s*(?:prompt)?\s*:", lower):
            add("medium", "param_reasonableness", "缺少 Negative Prompt",
                "未检出 Negative prompt:", "补 Negative prompt: 并列出三类负向词")
    elif model in ("flux2", "gpt_image", "muse_image", "nano_banana"):
        if mj_flag:
            add("medium", "param_reasonableness", "混入 Midjourney 参数",
                "出现 /imagine 或 --ar/--v/--no", "该模型用自然语言或分段标签，删除 MJ 参数")
    elif model in VIDEO_MODEL_IDS:
        if mj_flag:
            add("medium", "param_reasonableness", "混入图片模型参数",
                "出现 /imagine 或 --ar/--v/--no", "视频 Prompt 用自然语言分镜，参数放 params 块")
    elif model in TEXT_MODEL_IDS:
        if mj_flag:
            add("high", "param_reasonableness", "文本 Prompt 混入图片参数",
                "出现 /imagine 或 --ar/--v/--no", "删除图片参数，改用六要素与输出格式约束")
    if model == "hailuo" and modality == "video" and \
            "integrated_multimodal_description" not in lower:
        add("low", "structure_clarity", "未使用 Hailuo 四段结构",
            "缺少 integrated_multimodal_description:",
            "按官方四段结构重排：description / [Shot N] / soundscape / music")
    return issues


def _score_notes(features, specs):
    scores, present_weight, total_weight = {}, {}, {}
    for key, _, _ in DIMENSIONS:
        present_weight[key] = 0
        total_weight[key] = 0
    for spec in specs:
        dimension = spec["dimension"]
        total_weight[dimension] += spec["weight"]
        if features.get(spec["id"]):
            present_weight[dimension] += spec["weight"]
    for key, _, _ in DIMENSIONS:
        if key == "adaptability":
            scores[key] = 55 + (20 if features.get("placeholder") else 0) + \
                (10 if features.get("reference_note") else 0)
        elif total_weight[key]:
            scores[key] = 40 + 55.0 * present_weight[key] / total_weight[key]
        else:
            scores[key] = 55
    return scores


def audit_prompt(text, modality, model=None):
    """确定性体检：字段覆盖 + 问题清单 + 启发式评分。不做语义改写。"""
    specs = FEATURE_SPECS[modality]
    features = {spec["id"]: _detect_feature(text, spec) for spec in specs}
    issues = _missing_issues(features, specs)
    issues += _quality_issues(text, modality)
    issues += _syntax_issues(model, text, modality)
    scores = _score_notes(features, specs)
    for issue in issues:
        scores[issue["dimension"]] -= SEVERITY_PENALTY[issue["severity"]]
    scores = {key: max(0, min(100, round(value))) for key, value in scores.items()}
    notes = {}
    for key, name, _ in DIMENSIONS:
        present = [spec["label"] for spec in specs
                   if spec["dimension"] == key and features.get(spec["id"])]
        missing = [spec["label"] for spec in specs
                   if spec["dimension"] == key and not features.get(spec["id"])]
        parts = []
        if present:
            parts.append("已检出：" + "、".join(present))
        if missing:
            parts.append("缺少：" + "、".join(missing))
        if key == "adaptability":
            parts = [f"变量占位：{'有' if features.get('placeholder') else '无'}",
                     f"参考素材：{'有' if features.get('reference_note') else '无'}"]
        notes[key] = "；".join(parts)
    dim_entries = [(key, name, weight, scores[key]) for key, name, weight in DIMENSIONS]
    report = build_report(dim_entries, True, notes,
                          suggestion_pool=AUDIT_SUGGESTIONS.get(modality))
    issues.sort(key=lambda item: (SEVERITY_RANK[item["severity"]],
                                  item["dimension"], item["id"]))
    return {"features": features, "issues": issues, "score_report": report, "notes": notes}


def optimized_features(semantic, modality):
    """按 semantic_analysis 字段判断优化稿覆盖了哪些检查项。"""
    specs = FEATURE_SPECS[modality]
    fields = FEATURE_FIELDS[modality]
    result = {}
    all_text = []
    for value in semantic.values():
        if isinstance(value, str):
            all_text.append(value)
        elif isinstance(value, list):
            all_text.extend(str(item) for item in value if str(item).strip())
    for spec in specs:
        if spec["id"] == "placeholder":
            result[spec["id"]] = _placeholder_signal(" ".join(all_text))
            continue
        names = fields.get(spec["id"], ())
        result[spec["id"]] = any(_has_value(semantic, name) for name in names)
    return result


def feature_comparison(baseline, optimized, modality):
    return [{"id": spec["id"], "label": spec["label"],
             "baseline": bool(baseline.get(spec["id"])),
             "optimized": bool(optimized.get(spec["id"]))}
            for spec in FEATURE_SPECS[modality]]


def _comparison_report(baseline, optimized):
    by_key = {dim["key"]: dim for dim in baseline["dimensions"]}
    dimensions = []
    for dim in optimized["dimensions"]:
        before = by_key[dim["key"]]["score"]
        dimensions.append({
            "key": dim["key"], "name": dim["name"], "weight": dim["weight"],
            "baseline": before, "optimized": dim["score"],
            "delta": round(dim["score"] - before, 1),
        })
    return {
        "baseline_total": baseline["total"], "optimized_total": optimized["total"],
        "baseline_grade": baseline["grade"], "optimized_grade": optimized["grade"],
        "delta": round(optimized["total"] - baseline["total"], 1),
        "dimensions": dimensions,
    }


def _read_prompt(args):
    if args.prompt is not None:
        return args.prompt, "inline"
    if args.file:
        if args.file == "-":
            return sys.stdin.read(), "stdin"
        try:
            return Path(args.file).read_text(encoding="utf-8"), args.file
        except OSError as exc:
            die(f"文件不可读：{exc}", 2)
    if args.stdin:
        return sys.stdin.read(), "stdin"
    die("需要 --prompt、--file 或 --stdin", 1)


def cmd_optimize(args):
    text, source = _read_prompt(args)
    if not text.strip():
        die("待优化 Prompt 为空", 1)
    registry = load_registry(args.template_dir)
    if not registry:
        die(f"模板目录 {args.template_dir} 下未发现模型模板", 4)

    warnings = []
    model_hint, model_source = None, "none"
    if args.model:
        resolved, unknown = resolve_models(args.model, registry)
        if unknown:
            die(f"未知模型：{', '.join(unknown)}（可用：{', '.join(sorted(registry))}）", 1)
        if resolved:
            model_hint, model_source = resolved[0], "explicit"
    else:
        detected = detect_model(text)
        if detected:
            model_hint, model_source = detected, "detected"

    if args.modality == "auto":
        modality = choose_modality(registry, model_hint, text)
        modality_source = "model" if model_hint and model_modality(registry, model_hint) else "heuristic"
    else:
        modality = args.modality
        modality_source = "explicit"
    supported = set(registry[model_hint]["modalities"]) if model_hint else set()
    if model_hint and supported and modality not in supported:
        warnings.append(f"模型 {model_hint} 不支持 {modality} 模态，已忽略该模型线索")
        model_hint, model_source = None, "none"
        if modality_source == "model":
            modality_source = "heuristic"

    analysis = None
    if args.analysis:
        analysis = load_analysis(args.analysis)
        analysis_modality = analysis["modality"]
        if args.modality != "auto" and analysis_modality != modality:
            die(f"--analysis 的 modality={analysis_modality} 与 --modality {modality} 不一致", 4)
        if analysis_modality != modality:
            warnings.append(
                f"自动识别模态为 {modality}，analysis 声明 {analysis_modality}；以 analysis 为准")
            modality = analysis_modality
            modality_source = "analysis"
            if model_hint and supported and modality not in supported:
                warnings.append(f"模型 {model_hint} 不支持 {modality} 模态，已忽略该模型线索")
                model_hint, model_source = None, "none"

    matches, sanitized = scan_text(text)
    input_blocked = len(matches) > 0
    audit = audit_prompt(sanitized if (input_blocked and args.sanitize) else text,
                         modality, model_hint)
    if args.baseline_dims:
        dim_entries, notes = parse_dims(args.baseline_dims)
        audit["score_report"] = build_report(
            dim_entries, False, notes,
            suggestion_pool=AUDIT_SUGGESTIONS.get(modality))
        audit["notes"] = notes

    target_spec = args.models
    if target_spec is None:
        if model_hint and modality in registry[model_hint].get("modalities", {}):
            target_spec = model_hint
        else:
            target_spec = DEFAULT_OPTIMIZE_MODELS[modality]
    models, unknown = resolve_models(target_spec, registry)
    if unknown:
        die(f"未知模型：{', '.join(unknown)}（可用：{', '.join(sorted(registry))}）", 1)
    if not models:
        die("未解析到任何模型", 1)

    optimized = None
    comparison = None
    prompts, skipped = [], []
    all_matches, injection_flags = [], []
    blocked = input_blocked
    if analysis:
        semantic = analysis["semantic_analysis"]
        validate_task_contract(semantic)
        kind, strict = resolve_kind(semantic, args.kind)
        prompts, skipped, missing_all, invalid_all = compile_prompts(
            registry, models, modality, semantic, kind=kind, strict=strict)
        report_compile_errors(invalid_all, missing_all)
        if strict and kind and not prompts:
            die(f"没有模型支持用途 {kind}（可用用途见模板 modalities）", 1)
        if not prompts and skipped:
            reasons = "；".join(f"{item['model']}：{item['reason']}" for item in skipped[:3])
            die(f"目标模型均未渲染出 Prompt：{reasons}", 1)

        sanitized_prompts = []
        for prompt in prompts:
            source_name = f"{prompt['model']}/{prompt['kind']}"
            injection_flags.extend(
                dict(flag, prompt=source_name) for flag in scan_injection(prompt["text"]))
            prompt_matches, prompt_sanitized = scan_text(prompt["text"])
            all_matches.extend(prompt_matches)
            sanitized_prompts.append(dict(prompt, text=prompt_sanitized))
        prompts = sanitized_prompts
        blocked = blocked or bool(all_matches)

        optimized_report = None
        pool = AUDIT_SUGGESTIONS.get(modality)
        opt_features = optimized_features(semantic, modality)
        if args.dims:
            dim_entries, notes = parse_dims(args.dims)
            optimized_report = build_report(dim_entries, False, notes,
                                            suggestion_pool=pool)
        elif args.auto:
            # 与原稿同一套字段覆盖口径，避免两种启发式混算出假的升降。
            auto_scores = {key: round(value) for key, value in
                           _score_notes(opt_features, FEATURE_SPECS[modality]).items()}
            dim_entries = [(key, name, weight, auto_scores[key])
                           for key, name, weight in DIMENSIONS]
            optimized_report = build_report(dim_entries, True,
                                            suggestion_pool=pool)

        optimized = {
            "features": opt_features,
            "feature_compare": feature_comparison(audit["features"],
                                                  opt_features, modality),
            "score_report": optimized_report,
        }
        if optimized_report:
            comparison = _comparison_report(audit["score_report"], optimized_report)
        optimized["warnings"] = uncertainty_warnings(
            semantic, [prompt["text"] for prompt in prompts])

    result = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "subcommand": "optimize",
        "modality": modality,
        "modality_source": modality_source,
        "source_model": model_hint,
        "model_source": model_source,
        "input": {"source": source, "chars": len(text)},
        "filter": {
            "blocked": blocked,
            "input_blocked": input_blocked,
            "sanitized": bool(args.sanitize),
            "matches": matches + all_matches,
            "injection_flags": scan_injection(text) + injection_flags,
            "sanitized_text": sanitized,
        },
        "audit": audit,
        "target_models": models,
        "prompts": prompts,
        "skipped": skipped,
        "optimized": optimized,
        "comparison": comparison,
    }
    if warnings:
        result["warnings"] = warnings

    if args.format == "json":
        emit(result, args.output)
    else:
        emit_optimize_text(result, args.output)
    if blocked and not args.sanitize:
        print("安全过滤阻断：待优化 Prompt 或生成结果命中黑名单，请重写后重试",
              file=sys.stderr)
        sys.exit(5)


def emit_optimize_text(result, output):
    audit = result["audit"]
    report = audit["score_report"]
    lines = [
        "# Prompt 优化报告",
        "",
        "## 元信息卡",
        "",
        "| 项 | 值 |",
        "|---|---|",
        f"| 模态 | `{result['modality']}`（{result['modality_source']}） |",
        f"| 原稿模型 | `{result['source_model']}`（{result['model_source']}） |"
        if result["source_model"] else "| 原稿模型 | 未检出（可加 --model） |",
        f"| 目标模型 | {', '.join(f'`{m}`' for m in result['target_models']) or '—'} |",
        f"| 原稿长度 | {result['input']['chars']} 字符 |",
        f"| 安全过滤 | {'命中并已处理' if result['filter'].get('sanitized') else '命中并阻断' if result['filter']['blocked'] else '通过'} |",
        f"| 注入标记 | {injection_summary(result['filter']['injection_flags'])} |",
        "",
    ]
    if result.get("warnings"):
        lines += ["## 识别提示", ""] + [f"- {item}" for item in result["warnings"]] + [""]
    lines += report_markdown(report, "## 原稿评分（启发式）")
    lines += ["", "## 问题清单", ""]
    issues = audit["issues"]
    if issues:
        lines += ["| 严重度 | 维度 | 问题 | 证据 | 修法 |", "|---|---|---|---|---|"]
        names = {key: name for key, name, _ in DIMENSIONS}
        for issue in issues:
            evidence = issue["evidence"].replace("|", "\\|")
            fix = issue["fix"].replace("|", "\\|")
            lines.append(
                f"| {SEVERITY_LABEL[issue['severity']]} | {names[issue['dimension']]} "
                f"| {issue['title']} | {evidence} | {fix} |")
    else:
        lines.append("未发现结构性问题。")
    lines.append("")
    if result["optimized"]:
        compare = result["optimized"]["feature_compare"]
        lines += ["## 字段覆盖对比", "", "| 检查项 | 原稿 | 优化稿 |", "|---|---|:---:|"]
        for item in compare:
            lines.append(
                f"| {item['label']} | {'✓' if item['baseline'] else '—'} "
                f"| {'✓' if item['optimized'] else '—'} |")
        lines.append("")
        if result["prompts"]:
            lines += ["## 优化后 Prompt", ""]
            for prompt in result["prompts"]:
                title = prompt.get("display_name") or prompt["model"]
                if prompt.get("version"):
                    title += f"（v{prompt['version']}）"
                lines += [f"### {title} · {prompt['kind']}", "",
                          "```text", prompt["text"], "```", ""]
        if result["comparison"]:
            comp = result["comparison"]
            lines += ["## 评分对比", "",
                      "| 维度 | 权重 | 原稿 | 优化稿 | 变化 |",
                      "|---|---:|---:|---:|---:|"]
            for dim in comp["dimensions"]:
                sign = "+" if dim["delta"] > 0 else ""
                lines.append(
                    f"| {dim['name']} | {dim['weight']}% | {dim['baseline']} "
                    f"| {dim['optimized']} | {sign}{dim['delta']} |")
            sign = "+" if comp["delta"] > 0 else ""
            lines += ["", f"总分：{comp['baseline_total']} → {comp['optimized_total']}"
                          f"（{sign}{comp['delta']}），等级 {comp['baseline_grade']} → "
                          f"{comp['optimized_grade']}。", ""]
        if result["optimized"].get("warnings"):
            lines += ["## 待复核提示", ""]
            lines += [f"- {item}" for item in result["optimized"]["warnings"]]
            lines.append("")
    else:
        lines += ["## 下一步", "",
                  "按 `references/prompt_optimize_rules.md` 把原稿改写为"
                  " `semantic_analysis`，然后加 `--analysis <json> --auto` 重跑本命令，"
                  "即可得到优化后 Prompt 与评分对比。", ""]
    lines += ["## 使用提示", ""]
    if report.get("approximate"):
        lines.append("- 原稿评分为启发式近似值，仅供定位缺口；最终分请用 `--baseline-dims` 人工给分。")
    if result["filter"]["blocked"] and not result["filter"].get("sanitized_text"):
        lines.append("- 原稿命中安全黑名单，已阻断；重写违规表述后再优化。")
    lines.append("- 改写只补结构、不编造原稿没有的事实；不确定项按 `uncertainty` 标 `unknown:`，不进正文。")
    if result["source_model"]:
        lines.append(f"- 已按 `{result['source_model']}` 语法体检；换模型时参数写法要同步替换。")
    text = "\n".join(lines) + "\n"
    if output:
        with open(output, "w", encoding="utf-8") as fh:
            fh.write(text)
    else:
        print(text, end="")


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
def cmd_ir(args):
    """IR v1 契约校验：只在传入 IR 字段时生效，旧 JSON 直接通过。"""
    data = load_json(args.analysis, "分析文件")
    if not isinstance(data, dict):
        die("分析文件顶层必须是对象", 4)
    semantic = data.get("semantic_analysis")
    if semantic is not None:
        validate_semantic(semantic)
    modality = data.get("modality")
    if modality is not None and modality not in (
            "text", "image", "video", "story", "workflow"):
        die("分析文件 modality 必须是 text/image/video/story/workflow 之一", 4)

    errors = ir_errors(data)
    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "command": "ir validate",
        "ir_version": IR_VERSION,
        "valid": not errors,
        "modules": list(IR_MODULES),
        "errors": errors,
    }
    emit(report, args.output)
    if errors:
        print(f"IR 校验失败：{len(errors)} 项错误", file=sys.stderr)
        sys.exit(4)


def workflow_wf_node_key(node_id):
    text = str(node_id)
    if text.isdigit():
        return (0, int(text), "")
    return (1, 0, text)


def workflow_platforms_dir(override):
    """定位平台资料：显式参数 > 安装态 platforms/ > 仓库 creative-platforms/。"""
    if override:
        path = Path(override).expanduser().resolve()
        if not path.is_dir():
            die(f"平台资料目录不存在：{override}", 2)
        return path
    skill_root = Path(__file__).resolve().parent.parent
    installed = skill_root / "platforms"
    if installed.is_dir():
        return installed
    repo = skill_root.parent / "creative-platforms"
    if repo.is_dir():
        return repo
    return None


def load_workflow_platform(pid, base):
    """读取目标平台 capability_map/workflow_mapping；缺失时返回降级所需信息。"""
    warnings = []
    if base is None:
        return None, None, ["未找到平台资料目录（platforms/ 或 creative-platforms/）；"
                            "兼容性结论按保守降级处理"]
    folder = base / pid
    if not folder.is_dir():
        die(f"未知目标平台：{pid}（{base} 下无该平台资料）", 1)
    cap_path = folder / "capability_map.json"
    map_path = folder / "workflow_mapping.json"
    cap = mapping = None
    if cap_path.is_file():
        cap = load_json(cap_path, f"平台能力声明 {pid}")
        if not isinstance(cap, dict):
            die(f"平台能力声明 {pid} 顶层必须是对象", 4)
        if cap.get("platform") != pid:
            warnings.append(f"capability_map.json 的 platform 字段与目录名 {pid} 不一致")
    else:
        warnings.append(f"缺少 {pid}/capability_map.json；只给保守降级结论")
    if map_path.is_file():
        mapping = load_json(map_path, f"工作流映射 {pid}")
        if not isinstance(mapping, dict):
            die(f"工作流映射 {pid} 顶层必须是对象", 4)
        if mapping.get("platform") != pid:
            warnings.append(f"workflow_mapping.json 的 platform 字段与目录名 {pid} 不一致")
    else:
        warnings.append(f"缺少 {pid}/workflow_mapping.json；不输出确定性节点映射")
    return cap, mapping, warnings


def load_workflow_report(path):
    """读取 analyze_workflow.py 输出（或 IR JSON），校验后返回归一化节点。"""
    data = load_json(path, "工作流报告")
    if not isinstance(data, dict):
        die("工作流报告顶层必须是对象", 4)
    errors = ir_errors(data)
    if errors:
        die("工作流报告不符合 IR 1.0：" + "；".join(errors[:5]), 4)
    workflow = data.get("workflow")
    if not isinstance(workflow, dict):
        die("工作流报告缺少 workflow 对象（请先用 analyze_workflow.py 解析）", 4)
    fmt = workflow.get("format")
    if fmt not in IR_WORKFLOW_FORMATS:
        die("工作流报告 workflow.format 必须是 "
            f"{'/'.join(IR_WORKFLOW_FORMATS)} 之一", 4)
    nodes = []
    for index, node in enumerate(workflow["nodes"]):
        if not isinstance(node, dict):
            die(f"workflow.nodes[{index}] 必须是对象", 4)
        node_id = ir_node_id(node.get("id"))
        class_type = node.get("class_type")
        if node_id is None or not isinstance(class_type, str) or not class_type.strip():
            die(f"workflow.nodes[{index}] 缺少有效 id/class_type", 4)
        category = node.get("category")
        if not isinstance(category, str) or not category.strip():
            category = "unknown"
        nodes.append({"id": node_id, "class_type": class_type.strip(),
                      "category": category, "custom": False})
    if not nodes:
        die("workflow.nodes 不能为空", 4)
    return data, workflow, nodes


def workflow_custom_types(workflow):
    custom = set()
    for item in workflow.get("custom_nodes") or []:
        if isinstance(item, str):
            custom.add(item)
        elif isinstance(item, dict) and isinstance(item.get("class_type"), str):
            custom.add(item["class_type"])
    deps = workflow.get("deps")
    if isinstance(deps, dict):
        for item in deps.get("custom_node_types") or []:
            if isinstance(item, str):
                custom.add(item)
    return custom


def workflow_custom_nodes(workflow):
    raw = workflow.get("custom_nodes") or []
    grouped = {}
    for item in raw:
        if isinstance(item, str):
            class_type, category, nodes = item, "unknown", []
        elif isinstance(item, dict):
            class_type = item.get("class_type")
            if not isinstance(class_type, str):
                continue
            category = item.get("category") if isinstance(item.get("category"), str) else "unknown"
            nodes = [str(node) for node in item.get("nodes") or []
                     if isinstance(node, (str, int)) and not isinstance(node, bool)]
        else:
            continue
        entry = grouped.setdefault(class_type, {"class_type": class_type,
                                                "category": category,
                                                "nodes": set()})
        entry["nodes"].update(nodes)
    result = []
    for class_type in sorted(grouped):
        entry = grouped[class_type]
        result.append({
            "class_type": class_type,
            "category": entry["category"],
            "nodes": sorted(entry["nodes"], key=workflow_wf_node_key),
        })
    return result


def workflow_modality(nodes):
    categories = {node["category"] for node in nodes}
    if categories & {"video_output", "video_asset"}:
        return "video"
    if categories & {"image_output", "image_asset"}:
        return "image"
    return "unknown"


def workflow_mapping_entry(category, mapping, modality):
    """按统一类别查目标映射；支持 category_aliases 的一对多别名。"""
    entries = {}
    for item in mapping.get("nodes") or []:
        if isinstance(item, dict) and isinstance(item.get("unified"), str):
            entries[item["unified"]] = item
    if category in entries:
        return category, entries[category]
    aliases = mapping.get("category_aliases") or {}
    keys = aliases.get(category) if isinstance(aliases, dict) else None
    if not isinstance(keys, list):
        return None, None
    preferred = {"image": "image_model", "video": "video_model"}.get(modality)
    ordered = ([preferred] if preferred in keys else []) + [
        key for key in keys if key != preferred]
    for key in ordered:
        if isinstance(key, str) and key in entries:
            return key, entries[key]
    return None, None


def workflow_item_status(category, target, modality, mapping, custom,
                         usable, availability):
    """返回 (status, reason, mapping_key, confidence)。"""
    mapped_key = entry = None
    if usable and mapping is not None:
        mapped_key, entry = workflow_mapping_entry(category, mapping, modality)
    confidence = "unverified"
    if isinstance(entry, dict) and entry.get("confidence") in (
            "verified", "manual", "unverified"):
        confidence = entry["confidence"]
    if not usable:
        return "degraded", availability, mapped_key, confidence
    if target == "comfyui":
        if category == "unknown":
            return ("degraded", "本机未识别该节点类型；需在 ComfyUI 节点定义"
                    "（object_info）中确认", mapped_key, "manual")
        if custom:
            return ("degraded", "自定义节点可运行但需安装对应节点包与模型；"
                    "版本与端口需人工确认", mapped_key, "manual")
        return ("compatible", "同一平台，内置节点原生可用；具体端口以本机定义为准",
                mapped_key, "manual")
    if category == "unknown":
        if target == "runway":
            return ("incompatible", "目标平台不支持任意自定义节点；需人工重建该步骤",
                    mapped_key, "unverified")
        return ("degraded", "节点语义未公开；需人工重建该步骤",
                mapped_key, "unverified")
    if category in ("lora", "controlnet"):
        return ("incompatible", "目标平台未提供等价 LoRA/ControlNet 节点；"
                "需改用内置风格、参考图或首帧近似", mapped_key, confidence)
    if category in ("text_prompt", "negative_prompt"):
        return ("degraded", "文本可迁移，但语法与长度限制需重写；"
                "不直接粘贴 ComfyUI 权重语法", mapped_key, confidence)
    if category in ("image_asset", "video_asset"):
        if isinstance(entry, dict) and entry.get("status") in ("mapped", "partial") \
                and entry.get("confidence") == "verified":
            return ("compatible", "可作为输入素材上传；具体接入方式需人工确认",
                    mapped_key, confidence)
        return ("degraded", "素材可人工上传；目标平台接入方式未完全验证",
                mapped_key, "unverified")
    if category in ("model_loader", "sampler", "decode", "resolution"):
        return ("degraded", "由目标平台内部媒体模型处理；参数不可完全等价迁移",
                mapped_key, confidence)
    if category == "upscale":
        return ("degraded", "目标平台未公开等价放大节点；改用平台内置放大或后期",
                mapped_key, "unverified")
    if category == "conditioning":
        return ("degraded", "条件组合由目标平台内部处理；无法逐端口迁移",
                mapped_key, "unverified")
    if category == "audio":
        return ("degraded", "音频链路需人工重建；参数与接口未核验",
                mapped_key, confidence)
    if category in ("image_output", "video_output"):
        return ("degraded", "输出由目标平台重新生成；文件名与格式不保留",
                mapped_key, confidence)
    if category in ("reroute", "ui_only"):
        return ("degraded", "UI 辅助节点，迁移时忽略", mapped_key, "manual")
    return ("degraded", "未定义映射；需人工确认该步骤", mapped_key, "unverified")


def workflow_file_transfer(target, source_format, cap, usable, availability):
    if not usable:
        return {"status": "degraded", "reason": availability,
                "importable_output": False, "source_format": source_format,
                "target_formats": []}
    target_formats = cap.get("workflow_formats") or []
    source_platform_format = WORKFLOW_SOURCE_FORMAT[source_format]
    import_flag = (cap.get("import_export") or {}).get("import")
    if source_platform_format in target_formats:
        status = "compatible"
        reason = "目标平台声明支持对应工作流格式；导入方式需人工确认；本报告不生成文件"
    elif import_flag is False:
        status = "incompatible"
        reason = "目标平台声明不支持工作流导入；只能人工重建"
    else:
        status = "degraded"
        reason = "目标平台未公开/未验证该格式导入；需人工重建；本报告不生成可导入文件"
    return {"status": status, "reason": reason, "importable_output": False,
            "source_format": source_format, "target_formats": target_formats}


def workflow_node_ids(ids):
    ordered = sorted({str(node) for node in ids}, key=workflow_wf_node_key)
    return "、".join(ordered)


def workflow_manual_steps(target, display, items, workflow, usable):
    steps = []
    if not usable:
        steps.append("目标平台资料不可用或未过来源闸门；以下仅为保守建议，"
                     "需人工确认后再迁移。")
    by_category = {}
    for item in items:
        by_category.setdefault(item["category"], []).append(item["node"])
    custom_nodes = workflow_custom_nodes(workflow)
    if target == "comfyui":
        steps.append("原文件属于 ComfyUI 工作流，可在原环境继续使用；"
                     "本报告不生成新文件。")
        if custom_nodes:
            names = "、".join(entry["class_type"] for entry in custom_nodes)
            steps.append(f"安装并确认自定义节点：{names}；版本与端口以本机为准。")
        unknown = [item for item in items if item["category"] == "unknown"]
        if unknown:
            steps.append("在本机 object_info 中确认未知节点："
                         + "、".join(f"{item['class_type']}（节点 {item['node']}）"
                                    for item in unknown) + "。")
        steps.append("节点类名与端口以本机节点定义（object_info）为准；"
                     "采样参数需在界面复核。")
        return steps
    steps.append(f"在 {display} 中新建工作流/项目，按下面顺序手工重建。")
    if by_category.get("text_prompt") or by_category.get("negative_prompt"):
        parts = []
        if by_category.get("text_prompt"):
            parts.append(f"正向文本（节点 {workflow_node_ids(by_category['text_prompt'])}）")
        if by_category.get("negative_prompt"):
            parts.append(f"负向约束（节点 {workflow_node_ids(by_category['negative_prompt'])}）")
        steps.append("重建" + "、".join(parts) + "：按目标平台语法重写，"
                     "不要直接粘贴 ComfyUI 权重语法。")
    deps = workflow.get("deps") if isinstance(workflow.get("deps"), dict) else {}
    asset_names = deps.get("input_assets") or []
    if by_category.get("image_asset") or by_category.get("video_asset") or asset_names:
        names = "、".join(asset_names) if asset_names else "原输入素材"
        steps.append(f"上传输入素材：{names}；确认目标平台的尺寸/时长限制。")
    if by_category.get("model_loader"):
        steps.append(f"用目标平台媒体模型节点替换加载器（节点 "
                     f"{workflow_node_ids(by_category['model_loader'])}）；"
                     "不按文件名替换模型，选择账号内可用模型。")
    model_files = deps.get("model_files") or []
    if model_files:
        steps.append("模型文件：" + "、".join(model_files)
                     + "；只能在目标平台账号内选等价模型，不按文件名自动替换。")
    if by_category.get("lora"):
        steps.append(f"移除 LoRA（节点 {workflow_node_ids(by_category['lora'])}）；"
                     "改用内置风格或参考图近似，权重无法等价迁移。")
    if by_category.get("controlnet"):
        steps.append(f"移除 ControlNet（节点 {workflow_node_ids(by_category['controlnet'])}）；"
                     "改用参考图、首帧或文字结构约束近似。")
    if by_category.get("sampler") or by_category.get("decode") or by_category.get("resolution"):
        ids = (by_category.get("sampler", []) + by_category.get("decode", [])
               + by_category.get("resolution", []))
        steps.append(f"在目标平台参数面板复核步数/CFG/种子/分辨率（节点 "
                     f"{workflow_node_ids(ids)}）；不可控项按平台默认值执行。")
    if by_category.get("upscale"):
        steps.append(f"放大/尺寸节点（节点 {workflow_node_ids(by_category['upscale'])}）"
                     "改用目标平台内置放大或后期。")
    if by_category.get("audio"):
        steps.append(f"音频链路（节点 {workflow_node_ids(by_category['audio'])}）"
                     "需人工重建；参数未核验。")
    if by_category.get("image_output") or by_category.get("video_output"):
        ids = (by_category.get("image_output", []) + by_category.get("video_output", []))
        steps.append(f"输出节点（节点 {workflow_node_ids(ids)}）不迁移；"
                     "在目标平台重新选择输出格式并保存。")
    if by_category.get("reroute") or by_category.get("ui_only"):
        ids = by_category.get("reroute", []) + by_category.get("ui_only", [])
        steps.append(f"忽略 UI 辅助节点（节点 {workflow_node_ids(ids)}）。")
    unknown = [item for item in items if item["category"] == "unknown"]
    if unknown:
        steps.append("人工确认未知节点的作用："
                     + "、".join(f"{item['class_type']}（节点 {item['node']}）"
                                for item in unknown)
                     + "；无法确认时按缺失处理，不臆测参数。")
    if custom_nodes:
        names = "、".join(entry["class_type"] for entry in custom_nodes)
        steps.append(f"以下自定义节点需确认目标平台等价能力：{names}。")
    steps.append("完成后在目标平台内手动保存；本 Skill 不生成、不导入、"
                 "不导出工作流文件。")
    return steps


def workflow_md_cell(text):
    return str(text).replace("|", "\\|").replace("\n", " ").strip()


def workflow_report_markdown(report):
    overall = report["overall"]
    lines = [
        "# 工作流跨平台兼容报告",
        "",
        f"- 目标平台：`{report['target']}`（{report['platform']['display_name']}）",
        f"- 源格式：`{report['source_format']}`",
        f"- 总体结论：**{WORKFLOW_STATUS_LABEL[overall]}（{overall}）**",
        "- 节点统计：compatible {compatible} / degraded {degraded} / "
        "incompatible {incompatible}".format(**report["counts"]),
        f"- 文件迁移：**{WORKFLOW_STATUS_LABEL[report['file_transfer']['status']]}"
        f"（{report['file_transfer']['status']}）** — "
        f"{workflow_md_cell(report['file_transfer']['reason'])}",
        "- 可导入产物：不生成（`importable_output=false`）",
        "",
        "## 节点兼容性",
        "",
        "| 节点 | 类型 | 统一类别 | 结论 | 映射 | 依据 |",
        "| --- | --- | --- | --- | --- | --- |",
    ]
    for item in report["items"]:
        lines.append("| {node} | {class_type} | {category} | {status} | {mapping} | {reason} |".format(
            node=workflow_md_cell(item["node"]),
            class_type=workflow_md_cell(item["class_type"]),
            category=workflow_md_cell(item["category"]),
            status=item["status"],
            mapping=workflow_md_cell("、".join(item["mapping"]) or "—"),
            reason=workflow_md_cell(item["reason"]),
        ))
    lines += ["", "## 手工重建步骤", ""]
    lines += [f"{index}. {step}" for index, step in enumerate(report["manual_steps"], 1)]
    deps = report["deps"]
    lines += ["", "## 依赖", ""]
    custom = "、".join(
        f"{entry['class_type']}（{entry['category']}；节点 "
        f"{workflow_node_ids(entry['nodes'])}）" for entry in deps["custom_nodes"])
    lines.append(f"- 自定义节点：{custom or '无'}")
    lines.append(f"- 模型文件：{'、'.join(deps['model_files']) or '无'}")
    lines.append(f"- 输入素材：{'、'.join(deps['input_assets']) or '无'}")
    lines += ["", "## 问题", ""]
    lines += [f"- {issue}" for issue in report["issues"]] or ["- 无"]
    lines += ["", "## 边界", ""]
    lines += [f"- {item}" for item in report["boundary"]]
    return "\n".join(lines) + "\n"


def emit_workflow_text(report, output):
    text = workflow_report_markdown(report)
    if output:
        with open(output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    else:
        print(text, end="")


def cmd_workflow(args):
    """只读工作流兼容性报告：不生成、不导入、不导出任何工作流文件。"""
    target = args.target.strip()
    if not PLATFORM_ID_RE.match(target):
        die(f"目标平台 ID 非法：{args.target!r}（小写字母开头，仅含 a-z0-9_-）", 1)
    data, workflow, nodes = load_workflow_report(args.report)
    base = workflow_platforms_dir(args.platforms_dir)
    cap, mapping, warnings = load_workflow_platform(target, base)
    draft = isinstance(cap, dict) and cap.get("status") == "draft"
    usable = cap is not None and mapping is not None and not draft
    if draft:
        availability = "平台资料未过来源闸门（draft）；只给保守降级结论"
    elif cap is None or mapping is None:
        availability = "平台资料缺失；只给保守降级结论"
    else:
        availability = "平台资料不可用；只给保守降级结论"

    custom_types = workflow_custom_types(workflow)
    for node in nodes:
        node["custom"] = node["class_type"] in custom_types
    modality = workflow_modality(nodes)
    items = []
    for node in sorted(nodes, key=lambda item: workflow_wf_node_key(item["id"])):
        status, reason, mapped_key, confidence = workflow_item_status(
            node["category"], target, modality, mapping, node["custom"],
            usable, availability)
        items.append({
            "node": node["id"],
            "class_type": node["class_type"],
            "category": node["category"],
            "custom": node["custom"],
            "status": status,
            "reason": reason,
            "mapping": [mapped_key] if mapped_key else [],
            "confidence": confidence,
        })
    file_transfer = workflow_file_transfer(
        target, workflow["format"], cap, usable, availability)
    statuses = [item["status"] for item in items] + [file_transfer["status"]]
    overall = max(statuses, key=lambda value: WORKFLOW_STATUS_RANK[value])
    counts = {status: sum(1 for item in items if item["status"] == status)
              for status in ("compatible", "degraded", "incompatible")}

    display = cap.get("display_name") if isinstance(cap, dict) else target
    deps_raw = workflow.get("deps") if isinstance(workflow.get("deps"), dict) else {}
    model_files = deps_raw.get("model_files") or []
    if not model_files:
        model_files = sorted({item.get("name") for item in workflow.get("models") or []
                              if isinstance(item, dict) and isinstance(item.get("name"), str)})
    input_assets = deps_raw.get("input_assets") or []
    if not input_assets:
        input_assets = sorted({item.get("name") for item in workflow.get("assets") or []
                               if isinstance(item, dict) and isinstance(item.get("name"), str)})
    report_issues = [str(item) for item in workflow.get("issues") or []]
    for warning in warnings:
        if warning not in report_issues:
            report_issues.append(warning)
    if draft and "平台资料为 draft：不用于确定性结论，只作人工参考" not in report_issues:
        report_issues.append("平台资料为 draft：不用于确定性结论，只作人工参考")
    if not usable and base is not None and cap is not None \
            and mapping is None and "缺少 workflow_mapping.json；不输出确定性节点映射" not in report_issues:
        report_issues.append("缺少 workflow_mapping.json；不输出确定性节点映射")

    report = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "command": "workflow",
        "target": target,
        "source_format": workflow["format"],
        "modality": modality,
        "platform": {
            "id": target,
            "display_name": display,
            "status": cap.get("status") if isinstance(cap, dict) else "missing",
            "capability_level": cap.get("capability_level") if isinstance(cap, dict) else "unknown",
            "loaded": usable,
            "draft": draft,
            "mapping_loaded": mapping is not None,
            "target_formats": cap.get("workflow_formats") if isinstance(cap, dict) else [],
        },
        "overall": overall,
        "counts": counts,
        "file_transfer": file_transfer,
        "items": items,
        "deps": {
            "custom_nodes": workflow_custom_nodes(workflow),
            "model_files": sorted(set(model_files)),
            "input_assets": sorted(set(input_assets)),
        },
        "manual_steps": workflow_manual_steps(target, display, items, workflow, usable),
        "issues": report_issues,
        "boundary": [
            "只读解析 ComfyUI 公开 API/UI JSON；不解析闭源工程文件。",
            "不执行工作流，不生成、不导入、不导出可导入工作流，不调用平台 API（无 L4）。",
            "兼容结论基于 creative-platforms 映射与置信度；未公开参数一律需人工确认。",
            "unknown 结论不进入 Prompt 正文。",
        ],
    }
    if args.format in ("md", "markdown", "text"):
        emit_workflow_text(report, args.output)
    else:
        emit(report, args.output)


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

    p_optimize = sub.add_parser(
        "optimize", help="已有 Prompt 诊断：字段体检 + 问题清单 + 可选重编对比")
    p_optimize.add_argument("--prompt", help="待优化 Prompt 文本")
    p_optimize.add_argument("--file", help="待优化 Prompt 文件（- 表示 stdin）")
    p_optimize.add_argument("--stdin", action="store_true", help="从 stdin 读取")
    p_optimize.add_argument("--modality", default="auto",
                            choices=["auto", "text", "image", "video"],
                            help="原稿模态（默认自动识别）")
    p_optimize.add_argument("--model", help="原稿模型线索（ID 或别名，如 mj/sora）")
    p_optimize.add_argument("--models",
                            help="优化稿目标模型（默认沿用检出模型，否则 default）")
    p_optimize.add_argument("--analysis",
                            help="优化稿 semantic_analysis JSON（提供后编译并对比）")
    p_optimize.add_argument("--kind", help="优化稿用途（同 compile --kind）")
    p_optimize.add_argument("--baseline-dims",
                            help="原稿人工评分 JSON：[{key, score, note}]（替代启发式）")
    p_optimize.add_argument("--dims", help="优化稿人工评分 JSON：[{key, score, note}]")
    p_optimize.add_argument("--auto", action="store_true",
                            help="优化稿启发式近似评分（仅离线验证）")
    p_optimize.add_argument("--sanitize", action="store_true",
                            help="命中黑名单时替换为 [已过滤] 并放行（默认退出码 5）")
    p_optimize.add_argument("--format", default="md",
                            choices=["json", "text", "md", "markdown"],
                            help="json 或 markdown/text（诊断表 + 问题清单 + 对比）")
    p_optimize.add_argument("--template-dir", default=str(DEFAULT_TEMPLATE_DIR))
    p_optimize.add_argument("-o", "--output")

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

    p_workflow = sub.add_parser(
        "workflow", help="工作流跨平台兼容性报告（只读，不生成可导入文件）")
    p_workflow.add_argument("--report", required=True,
                            help="analyze_workflow.py 输出（含 workflow.nodes/format）")
    p_workflow.add_argument("--target", required=True,
                            help="目标平台 ID（如 comfyui/runway/libtv）")
    p_workflow.add_argument("--platforms-dir",
                            help="平台资料目录（默认安装态 platforms/，仓库用 creative-platforms/）")
    p_workflow.add_argument("--format", default="md",
                            choices=["json", "text", "md", "markdown"],
                            help="md/text 输出兼容性表格，json 输出结构化报告")
    p_workflow.add_argument("-o", "--output")

    p_ir = sub.add_parser("ir", help="IR v1 契约校验（references/ir_spec.md）")
    ir_sub = p_ir.add_subparsers(dest="ir_command", required=True)
    p_ir_validate = ir_sub.add_parser("validate", help="校验分析 JSON 是否符合 IR 1.0")
    p_ir_validate.add_argument("--analysis", required=True,
                               help="分析 JSON（可含 semantic_analysis；旧 JSON 无 IR 字段直接通过）")
    p_ir_validate.add_argument("-o", "--output")

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
    elif args.command == "optimize":
        cmd_optimize(args)
    elif args.command == "all":
        cmd_all(args)
    elif args.command == "scenes":
        cmd_scenes(args)
    elif args.command == "shots":
        cmd_shots(args)
    elif args.command == "workflow":
        cmd_workflow(args)
    elif args.command == "ir":
        cmd_ir(args)
    elif args.command == "validate-templates":
        cmd_validate_templates(args)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
