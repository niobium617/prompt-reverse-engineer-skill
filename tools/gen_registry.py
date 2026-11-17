#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从模板与 creative-platforms 生成三份注册表（确定性生成物，不手改）。

生成：
  config/model_registry.json        <- prompt-reverse-engineer-skill/assets/templates/*.json
  config/platform_registry.json     <- creative-platforms/*/capability_map.json（仅 verified）
  config/capability_registry.json   <- 上述两者汇总

约定：
  - 键排序、无时间戳、无绝对路径、LF 换行；同一输入逐字节一致；
  - 注册表只声明本 Skill 能做什么，不出现 L4 自动化或"保证运行"表述；
  - `--check` 只比对不写盘，用于 verify.py 的逐字节复现断言。

用法：
  python tools/gen_registry.py
  python tools/gen_registry.py --check

退出码：0 成功/一致；1 源文件错误或注册表漂移；2 参数或读写错误。
"""
import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "prompt-reverse-engineer-skill"
TEMPLATES = SKILL / "assets" / "templates"
REFERENCES = SKILL / "references"
PLATFORMS = REPO / "creative-platforms"
CONFIG = REPO / "config"

SCHEMA_VERSION = "1.0"
GENERATOR = "tools/gen_registry.py"
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CAPABILITY_LEVELS = {
    "L1": {
        "title": "Prompt 适配",
        "skill_support": "full",
        "scope": "生成目标平台提示词",
    },
    "L2": {
        "title": "配置适配",
        "skill_support": "full",
        "scope": "映射参数、参考素材与模型选项",
    },
    "L3": {
        "title": "工作流适配",
        "skill_support": "readonly_only",
        "scope": "可只读解析并输出报告；不生成、不导入、不导出工作流",
    },
    "L4": {
        "title": "自动化执行",
        "skill_support": "none",
        "scope": "平台原生能力照实声明，本 Skill 不调用生成 API",
    },
}


def fail(message, code=1):
    print(f"错误：{message}", file=sys.stderr)
    sys.exit(code)


def read_json(path, what):
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except OSError as exc:
        fail(f"{what}不可读：{exc}", 2)
    except json.JSONDecodeError as exc:
        fail(f"{what}不是合法 JSON：{exc}")


def rel(path):
    return path.relative_to(REPO).as_posix()


def load_models():
    if not TEMPLATES.is_dir():
        fail(f"模板目录不存在：{rel(TEMPLATES)}")
    models = []
    seen = set()
    for path in sorted(TEMPLATES.glob("*.json")):
        data = read_json(path, f"模板 {path.name}")
        if not isinstance(data, dict) or "model" not in data:
            continue  # score_report.json 等非模型模板
        model = data["model"]
        if not isinstance(model, str) or not model.strip():
            fail(f"模板 {path.name} 的 model 必须是非空字符串")
        if model in seen:
            fail(f"模型 ID 重复：{model}")
        seen.add(model)
        for key in ("display_name", "vendor", "version", "last_verified"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                fail(f"模板 {path.name} 缺少 {key}")
        if not DATE_RE.match(data["last_verified"]):
            fail(f"模板 {path.name} 的 last_verified 必须是 YYYY-MM-DD")
        aliases = data.get("alias") or []
        if not isinstance(aliases, list) or not all(isinstance(a, str) for a in aliases):
            fail(f"模板 {path.name} 的 alias 必须是字符串数组")
        params = data.get("default_params") or {}
        if not isinstance(params, dict):
            fail(f"模板 {path.name} 的 default_params 必须是对象")
        modalities = data.get("modalities") or {}
        if not isinstance(modalities, dict) or not modalities:
            fail(f"模板 {path.name} 的 modalities 必须是非空对象")
        task_modes = {}
        for modality in sorted(modalities):
            kinds = modalities[modality]
            if not isinstance(kinds, dict):
                fail(f"模板 {path.name} 的 modalities.{modality} 必须是对象")
            task_modes[modality] = sorted(kinds)
        source_docs = [rel(REFERENCES / "model_mappings.md")]
        sources = REFERENCES / f"{model}_sources.md"
        if sources.is_file():
            source_docs.append(rel(sources))
        level = "L2" if params else "L1"
        models.append({
            "id": model,
            "display_name": data["display_name"],
            "vendor": data["vendor"],
            "version": data["version"],
            "aliases": sorted(aliases),
            "modalities": sorted(modalities),
            "task_modes": task_modes,
            "capability_level": level,
            "capability_scope": ["L1_prompt"] + (["L2_config"] if level == "L2" else []),
            "default_params": params,
            "last_verified": data["last_verified"],
            "source_template": rel(path),
            "source_docs": source_docs,
        })
    if not models:
        fail("未发现任何模型模板")
    models.sort(key=lambda item: item["id"])
    return models


CONFIDENCE = {"verified", "unverified", "manual"}


def check_sources(platform, sources):
    """来源闸门：条目结构合法，且 verified 状态至少一条官方已读来源。"""
    if not isinstance(sources, list):
        fail(f"{platform} 的 sources 必须是数组")
    usable = 0
    for index, item in enumerate(sources):
        where = f"{platform} 的 sources[{index}]"
        if not isinstance(item, dict):
            fail(f"{where} 必须是对象")
        for key in ("title", "url"):
            if not isinstance(item.get(key), str) or not item[key].strip():
                fail(f"{where} 缺少 {key}")
        if not DATE_RE.match(str(item.get("accessed", ""))):
            fail(f"{where} 的 accessed 必须是 YYYY-MM-DD")
        if not isinstance(item.get("official"), bool):
            fail(f"{where} 的 official 必须是布尔值")
        if not isinstance(item.get("verified"), bool):
            fail(f"{where} 的 verified 必须是布尔值（是否已实际读取正文）")
        if item["official"] and item["verified"]:
            usable += 1
    return usable


def check_tagged_list(platform, key, items, required):
    if not isinstance(items, list):
        fail(f"{platform} 的 {key} 必须是数组")
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            fail(f"{platform} 的 {key}[{index}] 必须是对象")
        for field in required:
            if not isinstance(item.get(field), str) or not item[field].strip():
                fail(f"{platform} 的 {key}[{index}] 缺少 {field}")
        if item.get("confidence") not in CONFIDENCE:
            fail(f"{platform} 的 {key}[{index}] 的 confidence 必须是 "
                 f"verified/unverified/manual 之一")


def load_platforms():
    if not PLATFORMS.is_dir():
        return []
    platforms = []
    for path in sorted(PLATFORMS.glob("*/capability_map.json")):
        data = read_json(path, f"平台能力声明 {rel(path)}")
        if not isinstance(data, dict):
            fail(f"{rel(path)} 顶层必须是对象")
        platform = data.get("platform")
        if not isinstance(platform, str) or not platform.strip():
            fail(f"{rel(path)} 缺少 platform")
        if path.parent.name != platform:
            fail(f"{rel(path)} 的目录名必须与 platform 一致")
        for key in ("display_name", "version_verified"):
            if not isinstance(data.get(key), str) or not data[key].strip():
                fail(f"{platform} 缺少 {key}")
        if not DATE_RE.match(data["version_verified"]):
            fail(f"{platform} 的 version_verified 必须是 YYYY-MM-DD")
        status = data.get("status")
        if status not in ("verified", "draft"):
            fail(f"{platform} 的 status 必须是 verified 或 draft")
        if not isinstance(data.get("modalities"), list) or not data["modalities"]:
            fail(f"{platform} 的 modalities 必须是非空数组")
        if not isinstance(data.get("workflow_formats"), list):
            fail(f"{platform} 的 workflow_formats 必须是数组")
        for key in ("import_export", "api", "dependencies"):
            if not isinstance(data.get(key), dict):
                fail(f"{platform} 的 {key} 必须是对象")
        automation = data.get("automation") or {}
        if automation.get("supported_by_skill") is not False:
            fail(f"{platform} 的 automation.supported_by_skill 必须显式声明为 false（决策 D2）")
        level = data.get("capability_level")
        if level not in CAPABILITY_LEVELS:
            fail(f"{platform} 的 capability_level 必须是 L1/L2/L3/L4 之一")
        check_tagged_list(platform, "features", data.get("features") or [], ("name", "note"))
        check_tagged_list(platform, "models", data.get("models") or [], ("name", "note"))
        usable = check_sources(platform, data.get("sources") or [])
        if status == "verified" and usable < 1:
            fail(f"{platform} 标为 verified 但没有已实际读取的官方来源（来源闸门）")
        if status != "verified":
            continue  # draft 不进入注册表
        entry = dict(data)
        entry["source_path"] = rel(path)
        platforms.append(entry)
    platforms.sort(key=lambda item: item["platform"])
    return platforms


def build_registries(models, platforms):
    model_registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATOR,
        "models": models,
    }

    platform_registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATOR,
        "platforms": platforms,
    }

    capability_models = []
    for item in models:
        supported = list(item["capability_scope"])
        if item["capability_level"] == "L1":
            degrade = "无默认参数映射；只输出 Prompt，参数由用户按目标平台填写"
        else:
            degrade = "参数映射以模板 default_params 为准；平台未核验的参数需人工确认"
        capability_models.append({
            "id": item["id"],
            "capability_level": item["capability_level"],
            "supported": supported,
            "unsupported": ["L3_workflow_generation", "L4_automation"],
            "degrade": degrade,
            "last_verified": item["last_verified"],
        })

    capability_platforms = []
    for item in platforms:
        level = item["capability_level"]
        supported = ["L1_prompt"]
        if level in ("L2", "L3"):
            supported.append("L2_config")
        if level == "L3":
            supported.append("L3_workflow_readonly")
        capability_platforms.append({
            "id": item["platform"],
            "capability_level": level,
            "supported": supported,
            "unsupported": ["L3_workflow_generation", "L4_automation"],
            "degrade": item.get("degrade") or [],
            "last_verified": item.get("version_verified"),
        })

    capability_registry = {
        "schema_version": SCHEMA_VERSION,
        "generated_by": GENERATOR,
        "capability_levels": CAPABILITY_LEVELS,
        "models": capability_models,
        "platforms": capability_platforms,
    }

    return {
        CONFIG / "model_registry.json": model_registry,
        CONFIG / "platform_registry.json": platform_registry,
        CONFIG / "capability_registry.json": capability_registry,
    }


def dump(obj):
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, indent=2) + "\n"


def main():
    parser = argparse.ArgumentParser(description="生成/校验三份注册表（确定性）")
    parser.add_argument("--check", action="store_true",
                        help="只校验注册表能否由源文件逐字节复现，不写盘")
    args = parser.parse_args()

    models = load_models()
    platforms = load_platforms()
    payloads = {path: dump(obj) for path, obj in build_registries(models, platforms).items()}

    absolute = str(REPO.resolve())
    for path, text in payloads.items():
        if absolute in text:
            fail(f"{rel(path)} 含绝对路径，注册表不得写入本机路径")
        if "可运行" in text:
            fail(f"{rel(path)} 含「可运行」表述（不得承诺执行）")

    if args.check:
        drifted = []
        for path, text in payloads.items():
            if not path.is_file():
                drifted.append(f"{rel(path)} 缺失")
                continue
            current = path.read_text(encoding="utf-8")
            if current != text:
                drifted.append(f"{rel(path)} 与源文件不一致")
        if drifted:
            for item in drifted:
                print(f"漂移：{item}", file=sys.stderr)
            sys.exit(1)
        print(f"注册表一致：{len(payloads)} 份，"
              f"模型 {len(models)} / 平台 {len(platforms)}", file=sys.stderr)
        return

    CONFIG.mkdir(parents=True, exist_ok=True)
    for path, text in payloads.items():
        with open(path, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(text)
    print(f"已生成 {len(payloads)} 份注册表：模型 {len(models)} / 平台 {len(platforms)}",
          file=sys.stderr)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    main()
