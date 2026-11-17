#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ComfyUI 工作流只读解析（prompt-reverse-engineer 技能组件，阶段丙）。

只接受 ComfyUI 公开 JSON：
  - API 格式：{"<节点ID>": {"class_type": "...", "inputs": {...}}}
  - UI 格式：{"nodes": [...], "links": [...], ...}（version 0.4 / 1.0）
不解析 .blend / .psd / .prproj / .aep / 剪映工程等闭源项目文件，
不执行工作流，不生成、不导入、不导出任何可导入工作流。

输出 IR 1.0 信封（references/ir_spec.md）：
  topology / model files / input assets / parameters / custom-node deps / issues
  + 顶层 assets（源工作流 sha256）+ confidence。
未知节点类型只记 issue 与 stderr 警告，不阻断（退出码 0）。
悬空连线、重复 ID、连线成环、结构非法 → 退出码 4。
退出码：0 成功 / 1 用法错误 / 2 输入不可读 / 3 URL 下载失败 /
        4 解码失败、结构非法、悬空连线或成环
幂等约定：同输入两次运行输出逐字节一致（无时间戳、无随机数、键排序）。
"""
import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

from _net import DownloadError, fetch_url

TOOL = "analyze_workflow.py"
SCHEMA_VERSION = "1.0"
IR_VERSION = "1.0"
MAX_NODES = 5000
MAX_LINKS = 20000

# ComfyUI 官方内置/前端节点。不在此表但能识别的类名按自定义节点记入依赖。
CORE_CLASSES = {
    "CheckpointLoaderSimple", "CheckpointLoader", "UNETLoader",
    "UnetLoaderGGUF", "VAELoader", "CLIPLoader", "DualCLIPLoader",
    "CLIPTextEncode", "CLIPTextEncodeSDXL", "CLIPTextEncodeFlux",
    "T5TextEncode", "KSampler", "KSamplerAdvanced", "SamplerCustom",
    "SamplerCustomAdvanced", "EmptyLatentImage", "EmptySD3LatentImage",
    "EmptyLatentAudio", "VAEDecode", "VAEDecodeTiled", "VAEDecodeAudio",
    "SaveImage", "PreviewImage", "SaveAudio", "LoadImage", "LoadImageMask",
    "LoadAudio", "LoraLoader", "LoraLoaderModelOnly", "ControlNetLoader",
    "ControlNetApply", "ControlNetApplyAdvanced", "ImageScale", "ImageScaleBy",
    "ImageUpscaleWithModel", "UpscaleModelLoader", "ConditioningCombine",
    "ConditioningConcat", "ConditioningSetArea", "Reroute", "Note",
    "PrimitiveNode", "MarkdownNote",
}

CATEGORY_BY_CLASS = {
    "CLIPTextEncode": "text_prompt",
    "CLIPTextEncodeSDXL": "text_prompt",
    "CLIPTextEncodeFlux": "text_prompt",
    "T5TextEncode": "text_prompt",
    "CheckpointLoaderSimple": "model_loader",
    "CheckpointLoader": "model_loader",
    "UNETLoader": "model_loader",
    "UnetLoaderGGUF": "model_loader",
    "VAELoader": "model_loader",
    "CLIPLoader": "model_loader",
    "DualCLIPLoader": "model_loader",
    "UpscaleModelLoader": "model_loader",
    "LoraLoader": "lora",
    "LoraLoaderModelOnly": "lora",
    "ControlNetLoader": "controlnet",
    "ControlNetApply": "controlnet",
    "ControlNetApplyAdvanced": "controlnet",
    "LoadImage": "image_asset",
    "LoadImageMask": "image_asset",
    "VHS_LoadVideo": "video_asset",
    "LoadVideo": "video_asset",
    "LoadVideoUpload": "video_asset",
    "LoadAudio": "audio",
    "SaveAudio": "audio",
    "EmptyLatentImage": "resolution",
    "EmptySD3LatentImage": "resolution",
    "EmptyLatentAudio": "resolution",
    "KSampler": "sampler",
    "KSamplerAdvanced": "sampler",
    "SamplerCustom": "sampler",
    "SamplerCustomAdvanced": "sampler",
    "VAEDecode": "decode",
    "VAEDecodeTiled": "decode",
    "VAEDecodeAudio": "decode",
    "SaveImage": "image_output",
    "PreviewImage": "image_output",
    "VHS_VideoCombine": "video_output",
    "SaveVideo": "video_output",
    "SaveWEBM": "video_output",
    "SaveAnimatedWEBP": "video_output",
    "ImageScale": "upscale",
    "ImageScaleBy": "upscale",
    "ImageUpscaleWithModel": "upscale",
    "ImageResizeKJ": "upscale",
    "ConditioningCombine": "conditioning",
    "ConditioningConcat": "conditioning",
    "ConditioningSetArea": "conditioning",
    "Reroute": "ui_only",
    "Note": "ui_only",
    "PrimitiveNode": "ui_only",
    "MarkdownNote": "ui_only",
}

# API 输入键 → 模型角色。只从加载/增强类节点提取，sampler_name 等参数不算模型。
MODEL_INPUT_ROLES = {
    "ckpt_name": "checkpoint",
    "unet_name": "unet",
    "vae_name": "vae",
    "clip_name": "clip",
    "clip_name1": "clip",
    "clip_name2": "clip",
    "clip_name3": "clip",
    "lora_name": "lora",
    "control_net_name": "controlnet",
    "model_name": "upscale",
    "style_model_name": "lora",
}
MODEL_INPUT_CATEGORIES = ("model_loader", "lora", "controlnet", "upscale")

# UI widgets_values 位置 → 模型角色（只覆盖常见加载器）。
UI_MODEL_WIDGETS = {
    "CheckpointLoaderSimple": ((0, "ckpt_name", "checkpoint"),),
    "CheckpointLoader": ((1, "ckpt_name", "checkpoint"),),
    "UNETLoader": ((0, "unet_name", "unet"),),
    "UnetLoaderGGUF": ((0, "unet_name", "unet"),),
    "VAELoader": ((0, "vae_name", "vae"),),
    "CLIPLoader": ((0, "clip_name", "clip"),),
    "DualCLIPLoader": ((0, "clip_name1", "clip"), (1, "clip_name2", "clip")),
    "LoraLoader": ((0, "lora_name", "lora"),),
    "LoraLoaderModelOnly": ((0, "lora_name", "lora"),),
    "ControlNetLoader": ((0, "control_net_name", "controlnet"),),
    "DiffControlNetLoader": ((0, "control_net_name", "controlnet"),),
    "UpscaleModelLoader": ((0, "model_name", "upscale"),),
}

# 输入素材节点 → (widgets 位置, 素材类型)。
UI_ASSET_WIDGETS = {
    "LoadImage": (0, "image"),
    "LoadImageMask": (0, "image"),
    "LoadAudio": (0, "audio"),
    "VHS_LoadVideo": (0, "video"),
    "LoadVideo": (0, "video"),
    "LoadVideoUpload": (0, "video"),
}

PARAM_KEYS = ("seed", "noise_seed", "steps", "cfg", "sampler_name",
              "scheduler", "denoise", "start_at_step", "end_at_step",
              "width", "height", "batch_size", "filename_prefix")

# UI widgets_values 位置 → 参数名；None 表示该位置不是本脚本关心的参数。
UI_PARAM_WIDGETS = {
    "KSampler": ("seed", None, "steps", "cfg", "sampler_name", "scheduler",
                 "denoise"),
    "KSamplerAdvanced": (None, "noise_seed", None, "steps", "cfg",
                         "sampler_name", "scheduler", "start_at_step",
                         "end_at_step", None),
    "EmptyLatentImage": ("width", "height", "batch_size"),
    "EmptySD3LatentImage": ("width", "height", "batch_size"),
    "EmptyLatentAudio": ("width", "height", "batch_size"),
    "SaveImage": ("filename_prefix",),
}

NAME_SUFFIX_RE = re.compile(r"\s*\[(?:input|output|temp)\]\s*$", re.IGNORECASE)


def die(message, code=4):
    print(f"错误：{message}", file=sys.stderr)
    sys.exit(code)


def load_bytes(args):
    """统一输入装载：本地路径 / '-'=stdin / http(s) URL。"""
    source = args.input
    if source == "-":
        data = sys.stdin.buffer.read()
        if not data:
            die("stdin 无输入", 2)
        return data, source, "stdin"
    if re.match(r"^https?://", source):
        try:
            data = fetch_url(source, timeout=args.timeout,
                             max_bytes=args.max_bytes)
        except DownloadError as exc:
            die(f"URL 下载失败：{exc}", 3)
        return data, source, "url"
    try:
        with open(source, "rb") as fh:
            return fh.read(), source, "file"
    except OSError as exc:
        die(f"文件不可读：{exc}", 2)


def source_name(source, kind):
    """只保留文件名，避免把本机绝对路径写进 IR。"""
    if kind == "stdin":
        return "stdin"
    if kind == "url":
        tail = source.split("?", 1)[0].split("#", 1)[0].rstrip("/")
        return tail.rsplit("/", 1)[-1] or "workflow.json"
    return Path(source).name or "workflow.json"


def basename(value):
    """模型/素材名只保留文件名；统一分隔符并去掉 ComfyUI 的 [input] 标记。"""
    if not isinstance(value, str):
        return None
    text = value.strip().replace("\\", "/")
    if not text:
        return None
    name = text.rsplit("/", 1)[-1]
    name = NAME_SUFFIX_RE.sub("", name).strip()
    return name or None


def node_key(node_id):
    """数字节点优先按数值排序，其余按字符串；保证跨运行顺序稳定。"""
    text = str(node_id)
    if text.isdigit():
        return (0, int(text), "")
    return (1, 0, text)


def link_key(link):
    return (node_key(link.get("to", "")), str(link.get("to_input", "")),
            node_key(link.get("from", "")), int(link.get("from_output", 0)))


def detect_format(data):
    if not isinstance(data, dict) or not data:
        die("工作流为空或顶层不是对象", 4)
    if isinstance(data.get("nodes"), list) and isinstance(data.get("links"), list):
        return "comfyui_ui"
    if all(isinstance(value, dict) and isinstance(value.get("class_type"), str)
           and value.get("class_type").strip() for value in data.values()):
        return "comfyui_api"
    bad = sorted(str(key) for key, value in data.items()
                 if not (isinstance(value, dict)
                         and isinstance(value.get("class_type"), str)
                         and value.get("class_type").strip()))
    if bad:
        die("仅支持 ComfyUI API JSON（节点ID→{class_type,inputs}）或 "
            "UI JSON（nodes+links）；非法顶层键：" + ", ".join(bad[:5]), 4)
    die("仅支持 ComfyUI API JSON（节点ID→{class_type,inputs}）或 "
        "UI JSON（nodes+links）", 4)


def has_cycle(node_ids, edges):
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


def category_of(class_type):
    return CATEGORY_BY_CLASS.get(class_type, "unknown")


def parse_api(data):
    """解析 API 格式，返回 nodes/links/models/assets/params/issues。"""
    if len(data) > MAX_NODES:
        die(f"节点数 {len(data)} 超过上限 {MAX_NODES}", 4)
    nodes = {}
    for node_id, node in data.items():
        if not isinstance(node, dict):
            die(f"节点 {node_id} 必须是对象", 4)
        class_type = node.get("class_type")
        if not isinstance(class_type, str) or not class_type.strip():
            die(f"节点 {node_id} 缺少 class_type", 4)
        inputs = node.get("inputs", {})
        if not isinstance(inputs, dict):
            die(f"节点 {node_id} 的 inputs 必须是对象", 4)
        nodes[str(node_id)] = {
            "class_type": class_type.strip(),
            "inputs": inputs,
            "raw": node,
        }
    node_ids = set(nodes)
    links = []
    for node_id in sorted(nodes, key=node_key):
        inputs = nodes[node_id]["inputs"]
        for input_name in sorted(inputs, key=str):
            value = inputs[input_name]
            if not (isinstance(value, list) and len(value) == 2
                    and isinstance(value[0], str) and value[0].strip()
                    and isinstance(value[1], int)
                    and not isinstance(value[1], bool) and value[1] >= 0):
                continue
            source = value[0]
            if source not in node_ids:
                die(f"悬空连线：节点 {node_id} 的输入 {input_name} "
                    f"指向不存在的节点 {source}", 4)
            links.append({
                "from": source,
                "from_output": value[1],
                "to": node_id,
                "to_input": str(input_name),
            })
    if len(links) > MAX_LINKS:
        die(f"连线数 {len(links)} 超过上限 {MAX_LINKS}", 4)
    if has_cycle(list(nodes), [(link["from"], link["to"]) for link in links]):
        die("工作流连线存在环（循环依赖），无法按有向无环图解析", 4)

    issues = []
    for node_id in sorted(nodes, key=node_key):
        class_type = nodes[node_id]["class_type"]
        category = category_of(class_type)
        nodes[node_id]["category"] = category
        if category == "unknown":
            issues.append(f"未识别节点类型：{class_type}（节点 {node_id}）；"
                          "已按自定义节点记入依赖，不阻断解析")
    apply_negative_hint(nodes, links)

    models, assets, parameters = [], [], []
    for node_id in sorted(nodes, key=node_key):
        node = nodes[node_id]
        class_type = node["class_type"]
        if node["category"] in MODEL_INPUT_CATEGORIES:
            for input_name in MODEL_INPUT_ROLES:
                value = node["inputs"].get(input_name)
                name = basename(value)
                if name:
                    models.append({"node": node_id, "role": MODEL_INPUT_ROLES[input_name],
                                   "name": name})
        asset_kind = asset_kind_for(node["category"])
        if asset_kind:
            for input_name in ("image", "mask", "video", "audio", "file",
                               "path", "filename"):
                name = basename(node["inputs"].get(input_name))
                if name:
                    assets.append({"node": node_id, "kind": asset_kind,
                                   "name": name})
                    break
        values = {}
        for key in PARAM_KEYS:
            if key not in node["inputs"]:
                continue
            value = node["inputs"][key]
            if isinstance(value, (str, int, float, bool)):
                values[key] = clean_param(key, value)
        if values:
            parameters.append({"node": node_id, "class_type": class_type,
                               "values": values})
    return nodes, links, models, assets, parameters, issues


def parse_ui(data):
    """解析 UI 格式（version 0.4/1.0），验证节点/连线 ID 与槽位。"""
    version = data.get("version")
    issues = []
    if version is not None and str(version) not in ("0.4", "1.0"):
        die(f"不支持的 UI 工作流 version：{version!r}（仅支持 0.4 / 1.0）", 4)
    if version is None:
        issues.append("UI 工作流缺少 version 字段；按 0.4/1.0 结构解析")
    raw_nodes = data["nodes"]
    raw_links = data["links"]
    if not raw_nodes:
        die("UI 工作流 nodes 为空", 4)
    if len(raw_nodes) > MAX_NODES:
        die(f"节点数 {len(raw_nodes)} 超过上限 {MAX_NODES}", 4)
    if len(raw_links) > MAX_LINKS:
        die(f"连线数 {len(raw_links)} 超过上限 {MAX_LINKS}", 4)

    nodes = {}
    for index, node in enumerate(raw_nodes):
        if not isinstance(node, dict):
            die(f"UI nodes[{index}] 必须是对象", 4)
        if node.get("id") is None:
            die(f"UI nodes[{index}] 缺少 id", 4)
        class_type = node.get("type")
        if not isinstance(class_type, str) or not class_type.strip():
            die(f"UI nodes[{index}] 缺少 type", 4)
        node_id = str(node["id"])
        if node_id in nodes:
            die(f"UI 节点 ID 重复：{node_id}", 4)
        inputs = node.get("inputs") or []
        outputs = node.get("outputs") or []
        if not isinstance(inputs, list) or not isinstance(outputs, list):
            die(f"UI 节点 {node_id} 的 inputs/outputs 必须是数组", 4)
        nodes[node_id] = {
            "class_type": class_type.strip(),
            "raw": node,
            "inputs": inputs,
            "outputs": outputs,
        }

    links = []
    link_ids = set()
    for index, raw in enumerate(raw_links):
        if not isinstance(raw, list) or len(raw) < 5:
            die(f"UI links[{index}] 必须是至少 5 项的数组", 4)
        link_id, from_id, from_slot, to_id, to_slot = raw[:5]
        if not isinstance(link_id, int) or isinstance(link_id, bool):
            die(f"UI links[{index}] 的 link_id 必须是整数", 4)
        if link_id in link_ids:
            die(f"UI 连线 ID 重复：{link_id}", 4)
        link_ids.add(link_id)
        for slot_name, slot in (("from_slot", from_slot), ("to_slot", to_slot)):
            if not isinstance(slot, int) or isinstance(slot, bool) or slot < 0:
                die(f"UI links[{index}] 的 {slot_name} 必须是非负整数", 4)
        source, target = str(from_id), str(to_id)
        if source not in nodes:
            die(f"悬空连线：link {link_id} 的起点节点 {source} 不存在", 4)
        if target not in nodes:
            die(f"悬空连线：link {link_id} 的终点节点 {target} 不存在", 4)
        if from_slot >= len(nodes[source]["outputs"]):
            die(f"UI 连线 {link_id} 的起点槽位 {from_slot} 超出节点 "
                f"{source} 的输出数量 {len(nodes[source]['outputs'])}", 4)
        if to_slot >= len(nodes[target]["inputs"]):
            die(f"UI 连线 {link_id} 的终点槽位 {to_slot} 超出节点 "
                f"{target} 的输入数量 {len(nodes[target]['inputs'])}", 4)
        to_input = nodes[target]["inputs"][to_slot]
        input_name = to_input.get("name") if isinstance(to_input, dict) else None
        links.append({
            "from": source,
            "from_output": from_slot,
            "to": target,
            "to_input": str(input_name) if input_name is not None else "",
            "to_slot": to_slot,
            "link_id": link_id,
        })
    if has_cycle(list(nodes), [(link["from"], link["to"]) for link in links]):
        die("工作流连线存在环（循环依赖），无法按有向无环图解析", 4)
    for link in links:
        target_input = nodes[link["to"]]["inputs"][link["to_slot"]]
        if isinstance(target_input, dict) and target_input.get("link") is not None \
                and target_input.get("link") != link["link_id"]:
            issues.append(f"UI 连线 {link['link_id']} 与节点 {link['to']} "
                          f"输入槽位的 link 标记不一致；按连线数组为准")

    for index, node in enumerate(raw_nodes):
        node_id = str(node["id"])
        category = category_of(nodes[node_id]["class_type"])
        nodes[node_id]["category"] = category
        if category == "unknown":
            issues.append(f"未识别节点类型：{nodes[node_id]['class_type']}"
                          f"（节点 {node_id}）；已按自定义节点记入依赖，不阻断解析")
        for input_item in nodes[node_id]["inputs"]:
            if isinstance(input_item, dict) and input_item.get("link") is not None:
                if input_item["link"] not in link_ids:
                    die(f"悬空输入引用：节点 {node_id} 的输入 "
                        f"{input_item.get('name', '?')} 指向不存在的连线 "
                        f"{input_item['link']}", 4)
        for output_item in nodes[node_id]["outputs"]:
            if isinstance(output_item, dict):
                for link_id in output_item.get("links") or []:
                    if link_id not in link_ids:
                        die(f"悬空输出引用：节点 {node_id} 的输出 "
                            f"{output_item.get('name', '?')} 指向不存在的连线 "
                            f"{link_id}", 4)
    apply_negative_hint(nodes, links)

    models, assets, parameters = [], [], []
    for node_id in sorted(nodes, key=node_key):
        node = nodes[node_id]
        class_type = node["class_type"]
        widgets = node["raw"].get("widgets_values")
        linked = {item.get("name") for item in node["inputs"]
                  if isinstance(item, dict) and item.get("link") is not None}
        for position, input_name, role in UI_MODEL_WIDGETS.get(class_type, ()):
            value = widget_at(widgets, position, input_name)
            name = basename(value)
            if name:
                models.append({"node": node_id, "role": role, "name": name})
        asset_info = UI_ASSET_WIDGETS.get(class_type)
        if asset_info:
            position, kind = asset_info
            name = basename(widget_at(widgets, position, kind))
            if name:
                assets.append({"node": node_id, "kind": kind, "name": name})
        values = {}
        for position, key in enumerate(UI_PARAM_WIDGETS.get(class_type, ())):
            if key is None or key in linked:
                continue
            value = widget_at(widgets, position, key)
            if isinstance(value, (str, int, float, bool)):
                values[key] = clean_param(key, value)
        if values:
            parameters.append({"node": node_id, "class_type": class_type,
                               "values": values})
    return nodes, links, models, assets, parameters, issues, version


def widget_at(widgets, position, name=None):
    if isinstance(widgets, list):
        return widgets[position] if position < len(widgets) else None
    if isinstance(widgets, dict) and name:
        return widgets.get(name)
    return None


def clean_param(key, value):
    if key == "filename_prefix" and isinstance(value, str):
        return basename(value) or value.strip()
    if isinstance(value, str):
        return value.strip()
    return value


def asset_kind_for(category):
    return {
        "image_asset": "image",
        "video_asset": "video",
        "audio": "audio",
    }.get(category)


def apply_negative_hint(nodes, links):
    """文本编码节点接到采样器 negative 输入时改判为 negative_prompt。"""
    negative_targets = {(link["from"], link.get("to_input"))
                        for link in links if link.get("to_input") == "negative"}
    for node_id, node in nodes.items():
        if node["category"] == "text_prompt":
            if any(source == node_id for source, _ in negative_targets):
                node["category"] = "negative_prompt"


def build_workflow(nodes, links, models, assets, parameters, issues,
                   fmt, version):
    node_list = []
    for node_id in sorted(nodes, key=node_key):
        node_list.append({
            "id": node_id,
            "class_type": nodes[node_id]["class_type"],
            "category": nodes[node_id]["category"],
        })
    link_list = sorted(links, key=link_key)
    models = sorted(models, key=lambda item: (
        node_key(item["node"]), item["role"], item["name"]))
    assets = sorted(assets, key=lambda item: (
        node_key(item["node"]), item["kind"], item["name"]))
    parameters = sorted(parameters, key=lambda item: node_key(item["node"]))
    unknown = sorted({node["class_type"] for node in nodes.values()
                      if node["category"] == "unknown"})
    custom = sorted({node["class_type"] for node in nodes.values()
                     if node["class_type"] not in CORE_CLASSES})
    custom_nodes = []
    for class_type in custom:
        ids = sorted((node_id for node_id, node in nodes.items()
                      if node["class_type"] == class_type), key=node_key)
        custom_nodes.append({
            "class_type": class_type,
            "category": category_of(class_type),
            "nodes": ids,
        })
    category_counts = {}
    for node in nodes.values():
        category = node["category"]
        category_counts[category] = category_counts.get(category, 0) + 1
    workflow = {
        "format": fmt,
        "nodes": node_list,
        "links": link_list,
        "models": models,
        "assets": assets,
        "parameters": parameters,
        "custom_nodes": custom_nodes,
        "deps": {
            "custom_node_types": custom,
            "model_files": sorted({item["name"] for item in models}),
            "input_assets": sorted({item["name"] for item in assets}),
        },
        "stats": {
            "node_count": len(node_list),
            "link_count": len(link_list),
            "model_count": len(models),
            "asset_count": len(assets),
            "custom_node_count": len(custom),
            "unknown_node_count": len(unknown),
            "category_counts": category_counts,
        },
        "issues": sorted(issues),
    }
    if version is not None:
        workflow["version"] = str(version)
    return workflow


def main():
    parser = argparse.ArgumentParser(description="ComfyUI 工作流只读解析")
    parser.add_argument("input", help="输入：ComfyUI API/UI JSON 文件 | '-'=stdin | http(s) URL")
    parser.add_argument("-o", "--output", help="结果写入 JSON 文件（默认仅 stdout）")
    parser.add_argument("--timeout", type=float, default=15.0, help="URL 下载超时秒数")
    parser.add_argument("--max-bytes", type=int, default=32 * 1024 * 1024,
                        help="URL 下载大小上限（字节，默认 32 MiB；仅公网地址）")
    args = parser.parse_args()

    data_bytes, source, kind = load_bytes(args)
    try:
        text = data_bytes.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        die(f"JSON 必须是 UTF-8 编码：{exc}", 4)
    if not text.strip():
        die("输入为空", 4)
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        die(f"不是合法 JSON：{exc}", 4)

    fmt = detect_format(data)
    version = None
    if fmt == "comfyui_api":
        nodes, links, models, assets, parameters, issues = parse_api(data)
    else:
        nodes, links, models, assets, parameters, issues, version = parse_ui(data)
    if len(nodes) > MAX_NODES:
        die(f"节点数 {len(nodes)} 超过上限 {MAX_NODES}", 4)

    name = source_name(source, kind)
    workflow = build_workflow(nodes, links, models, assets, parameters,
                              issues, fmt, version)
    envelope = {
        "schema_version": SCHEMA_VERSION,
        "tool": TOOL,
        "modality": "workflow",
        "ir_version": IR_VERSION,
        "input": {
            "source": name,
            "kind": kind,
            "sha256": hashlib.sha256(data_bytes).hexdigest(),
            "size_bytes": len(data_bytes),
        },
        "project": {
            "name": Path(name).stem or "workflow",
            "type": "comfyui_workflow",
        },
        "assets": [{
            "path": name,
            "kind": "workflow",
            "role": "source_workflow",
            "sha256": hashlib.sha256(data_bytes).hexdigest(),
        }],
        "workflow": workflow,
        "confidence": {
            "workflow": {
                "status": "observed",
                "basis": "只读解析文件结构；节点与连线计数来自文件本身",
            },
            "assets": {
                "status": "observed",
                "basis": "从加载节点参数提取文件名；文件内容与可读性未校验",
            },
            "model": {
                "status": "inferred",
                "basis": "按加载节点参数名推断模型文件；本机可用性需人工确认",
            },
            "parameters": {
                "status": "observed",
                "basis": "读取节点输入或 widgets_values；未执行连线求值",
            },
        },
    }
    out = json.dumps(envelope, ensure_ascii=False, sort_keys=True)
    if args.output:
        try:
            with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
                fh.write(out + "\n")
        except OSError as exc:
            die(f"输出文件不可写：{exc}", 2)
    print(out)
    for issue in workflow["issues"]:
        print(f"警告：{issue}", file=sys.stderr)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
