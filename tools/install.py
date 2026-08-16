#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""prompt-reverse-engineer 一键安装脚本（纯 stdlib，无依赖）。

功能：
  - claude / cursor：在 ~/.claude/skills / ~/.cursor/skills 下建立 junction（默认）
    或复制（--mode copy），指向技能本体 prompt-reverse-engineer-skill/
  - codex：物化 platform-adapters/codex 插件内 skills junction，并向 ~/.codex/config.toml
    追加本地 marketplace 注册块（幂等，标记注释包裹）
  - doubao：确定性生成扁平化指令文本 platform-adapters/doubao/doubao_instruction.md
    （豆包不支持目录安装，需在「设置→技能中心→新建Skill」粘贴该文件内容）

幂等性：junction 同源 → SKIP；异源 → 重建；config.toml 标记块已存在 → SKIP。
退出码：0 成功（含全部优雅跳过）；2 参数错误。

用法示例：
  python tools/install.py                      # 全部平台，junction 模式
  python tools/install.py --platform claude,cursor
  python tools/install.py --mode copy --force
  python tools/install.py --dry-run            # 只打印不执行
  python tools/install.py --target-root D:\\test --platform all   # 冒烟测试（不触碰真实配置）
"""
import argparse
import os
import shutil
import subprocess
import sys
from pathlib import Path

MARKER_BEGIN = "# >>> prompt-reverse-engineer >>>"
MARKER_END = "# <<< prompt-reverse-engineer <<<"

SKILL_NAME = "prompt-reverse-engineer"
REPO_ROOT = Path(__file__).resolve().parent.parent
SKILL_SRC = REPO_ROOT / "prompt-reverse-engineer-skill"
ADAPTER_ROOT = REPO_ROOT / "platform-adapters"
CODEX_MARKET = ADAPTER_ROOT / "codex"
CODEX_PLUGIN = CODEX_MARKET / "prompt-reverse-engineer"
DOUBAO_DIR = ADAPTER_ROOT / "doubao"
DOUBAO_FILE = DOUBAO_DIR / "doubao_instruction.md"

# 生成豆包指令时用到的源文件
DOUBAO_SOURCES = [
    SKILL_SRC / "SKILL.md",
    SKILL_SRC / "references" / "prompt_framework.md",
    SKILL_SRC / "references" / "image_rules.md",
    SKILL_SRC / "references" / "video_rules.md",
    SKILL_SRC / "references" / "model_mappings.md",
]


def home() -> Path:
    return Path(os.path.expanduser("~"))


def agent_roots(target_root):
    """各平台的安装根目录。--target-root 时全部重定向到该目录下（冒烟测试用）。"""
    if target_root:
        base = Path(target_root)
        return {
            "claude": base / ".claude",
            "cursor": base / ".cursor",
            "codex": base / ".codex",
        }
    return {"claude": home() / ".claude", "cursor": home() / ".cursor",
            "codex": home() / ".codex"}


def is_junction(path: Path) -> bool:
    try:
        st = os.lstat(str(path))
    except OSError:
        return False
    return bool(st.st_file_attributes & 0x400) if hasattr(st, "st_file_attributes") else False


def junction_target(path: Path):
    """读取 junction 的目标路径（fsutil 解析 reparse point 中 printName）。"""
    try:
        out = subprocess.run(
            ["cmd", "/c", "dir", str(path)], capture_output=True, text=True, timeout=30
        ).stdout
        for line in out.splitlines():
            if "<JUNCTION>" in line and "[" in line:
                target = line.split("[")[1].split("]")[0]
                return Path(target)
    except Exception:
        pass
    return None


def make_junction(link: Path, source: Path, dry_run: bool, actions: list):
    if dry_run:
        actions.append(("junction", str(link), "-> " + str(source)))
        return True
    result = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(link), str(source)],
        capture_output=True, text=True, timeout=60,
    )
    return result.returncode == 0


def install_dir_platform(platform, mode, target_root, dry_run, force, actions):
    """claude / cursor：把技能目录装进 <root>/skills/prompt-reverse-engineer"""
    root = agent_roots(target_root)[platform]
    skills_dir = root / "skills"
    dest = skills_dir / SKILL_NAME
    if not root.exists():
        actions.append(("skip", platform, f"{root} 不存在（未安装该 Agent）"))
        return
    if mode == "junction":
        if is_junction(dest):
            target = junction_target(dest)
            if target and Path(target).resolve() == SKILL_SRC.resolve():
                actions.append(("skip", platform, f"{dest} 已指向同源，跳过"))
                return
            actions.append(("rebuild", platform, f"{dest} 指向异源，重建 junction"))
            if not dry_run:
                try:
                    os.rmdir(str(dest))
                except OSError as exc:
                    actions.append(("error", platform, f"移除旧 junction 失败：{exc}"))
                    return
            make_junction(dest, SKILL_SRC, dry_run, actions)
            actions.append(("ok", platform, f"junction {dest} -> {SKILL_SRC}"))
        elif dest.exists():
            actions.append(("skip", platform, f"{dest} 已存在（非 junction，不动它；--force 不适用）"))
        else:
            if not skills_dir.exists():
                if not dry_run:
                    skills_dir.mkdir(parents=True, exist_ok=True)
                actions.append(("mkdir", platform, str(skills_dir)))
            if make_junction(dest, SKILL_SRC, dry_run, actions):
                actions.append(("ok", platform, f"junction {dest} -> {SKILL_SRC}"))
            else:
                actions.append(("error", platform, "junction 创建失败，请改用 --mode copy"))
    else:  # copy
        if dest.exists():
            if force:
                actions.append(("rebuild", platform, f"强制覆盖 {dest}"))
                if not dry_run:
                    shutil.rmtree(str(dest))
            else:
                actions.append(("skip", platform, f"{dest} 已存在，跳过（--force 可覆盖）"))
                return
        if not dry_run:
            shutil.copytree(str(SKILL_SRC), str(dest))
        actions.append(("ok", platform, f"copytree {SKILL_SRC} -> {dest}"))


def install_codex(mode, target_root, dry_run, force, actions):
    """codex：物化插件内 skills junction + config.toml 注册 marketplace。"""
    root = agent_roots(target_root)["codex"]
    plugin_skills = CODEX_PLUGIN / "skills"
    # 1) 物化 skills（junction 指向技能本体；copy 模式则复制）
    if mode == "junction":
        if is_junction(plugin_skills):
            target = junction_target(plugin_skills)
            if target and Path(target).resolve() == SKILL_SRC.resolve():
                actions.append(("skip", "codex", f"{plugin_skills} 已指向同源，跳过"))
            else:
                actions.append(("rebuild", "codex", "skills junction 指向异源，重建"))
                if not dry_run:
                    os.rmdir(str(plugin_skills))
                make_junction(plugin_skills, SKILL_SRC, dry_run, actions)
                actions.append(("ok", "codex", f"junction {plugin_skills} -> {SKILL_SRC}"))
        elif plugin_skills.exists():
            if not dry_run and not any(plugin_skills.iterdir()):
                os.rmdir(str(plugin_skills))  # 空目录（如上次失败的残留），移除后建 junction
                if make_junction(plugin_skills, SKILL_SRC, dry_run, actions):
                    actions.append(("ok", "codex", f"junction {plugin_skills} -> {SKILL_SRC}"))
            else:
                actions.append(("skip", "codex", f"{plugin_skills} 已存在（非 junction）"))
        else:
            # 注意：junction 目标路径本身不能预先创建，mklink 直接建链接
            if make_junction(plugin_skills, SKILL_SRC, dry_run, actions):
                actions.append(("ok", "codex", f"junction {plugin_skills} -> {SKILL_SRC}"))
            else:
                actions.append(("error", "codex", "junction 创建失败，请改用 --mode copy"))
    else:
        if plugin_skills.exists():
            if force:
                if not dry_run:
                    shutil.rmtree(str(plugin_skills))
            else:
                actions.append(("skip", "codex", f"{plugin_skills} 已存在，跳过"))
                return
        if not dry_run:
            shutil.copytree(str(SKILL_SRC), str(plugin_skills))
        actions.append(("ok", "codex", f"copytree {SKILL_SRC} -> {plugin_skills}"))

    # 2) config.toml 注册
    config_path = root / "config.toml"
    if not config_path.exists():
        actions.append(("skip", "codex", f"{config_path} 不存在（未安装 Codex），仅物化插件目录"))
        return
    text = config_path.read_text(encoding="utf-8")
    if MARKER_BEGIN in text:
        actions.append(("skip", "codex", "config.toml 已含注册块，跳过"))
        return
    import tomllib
    try:
        tomllib.loads(text)
    except Exception as exc:
        actions.append(("error", "codex", f"config.toml 解析失败，不修改：{exc}"))
        return
    block = (
        f"\n{MARKER_BEGIN}\n"
        "[marketplaces.aps-local]\n"
        'last_updated = "2026-08-15T00:00:00Z"\n'
        "source_type = \"local\"\n"
        f"source = '''{CODEX_MARKET}'''\n\n"
        '[plugins."prompt-reverse-engineer@aps-local"]\n'
        "enabled = true\n"
        f"{MARKER_END}\n"
    )
    if dry_run:
        actions.append(("ok", "codex", f"将向 {config_path} 追加注册块（dry-run 未写入）"))
    else:
        with open(config_path, "a", encoding="utf-8") as fh:
            fh.write(block)
        actions.append(("ok", "codex", f"已向 {config_path} 追加注册块"))


def build_doubao_body():
    """把 SKILL.md + references 扁平化为单一中文指令正文（确定性）。"""
    lines = [
        "# Prompt 逆向工程专家（豆包技能）",
        "",
        "你是多模态 Prompt 逆向工程专家。用户提供文本、图片或视频后，你深度拆解其"
        "创作逻辑（主体、风格、结构、参数），反向生成可复用的专业 Prompt，适配输出"
        "Midjourney / Stable Diffusion / GPT-4 / Sora 等模型格式，并给出百分制质量评分。",
        "",
        "## 附带的脚本",
        "本技能包附带 scripts/ 目录（4 个 Python 分析脚本：analyze_text.py、"
        "analyze_image.py、analyze_video.py、prompt_compiler.py）。若运行环境支持执行"
        "本地 Python（依赖：Python 3.10+ 与 opencv-python/pillow/numpy，用法见下文"
        "「脚本调用速查」），优先运行脚本获取量化信号；若环境不支持执行脚本，则跳过"
        "脚本层，直接按「异常处理规则」中的降级路径做纯语义分析，流程与输出格式不变。",
        "",
        "## 触发条件",
        "用户提供具体内容并表达「逆向 / 复刻 / 拆解 / 变成 prompt / 优化 prompt」意图时执行。",
        "",
    ]
    for path in DOUBAO_SOURCES:
        text = path.read_text(encoding="utf-8")
        # 去掉 SKILL.md 的 frontmatter
        if text.startswith("---"):
            parts = text.split("---", 2)
            text = parts[2] if len(parts) > 2 else text
        lines.append(f"<!-- 来源：{path.relative_to(SKILL_SRC)} -->")
        lines.append("")
        for raw in text.splitlines():
            line = raw.rstrip()
            if not line.strip():
                lines.append("")
                continue
            if line.startswith("#"):
                level = len(line) - len(line.lstrip("#"))
                line = "#" * min(level + 1, 6) + line.lstrip("#")
            lines.append(line)
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def build_doubao_instruction(dry_run, actions):
    """生成豆包双产物：粘贴版指令文本 + 可上传技能包 SKILL.md（含 YAML 头）。"""
    if dry_run:
        actions.append(("ok", "doubao", f"将生成 {DOUBAO_FILE} 与技能包 SKILL.md（dry-run 未写入）"))
        return
    body = build_doubao_body()
    DOUBAO_DIR.mkdir(parents=True, exist_ok=True)
    DOUBAO_FILE.write_text(body, encoding="utf-8")
    # 豆包上传版：SKILL.md 必须含 YAML 格式的 name + description（豆包上传校验要求）
    pkg_dir = DOUBAO_DIR / "prompt-reverse-engineer"
    pkg_dir.mkdir(parents=True, exist_ok=True)
    frontmatter = (
        "---\n"
        "name: prompt-reverse-engineer\n"
        "description: \"多模态 Prompt 逆向工程技能。当用户提供文本、图片或视频并要求"
        "逆向/复刻/拆解其创作逻辑、还原为可复用 Prompt 时激活。触发词：逆向 prompt、"
        "反向生成、复刻这个文案/风格/图片/视频、拆解文案/镜头/分镜；prompt reverse "
        "engineering、recreate this style as a prompt。输出适配 Midjourney / Stable "
        "Diffusion / GPT-4 / Sora 多模型格式，附百分制质量评分。\"\n"
        "---\n"
    )
    (pkg_dir / "SKILL.md").write_text(frontmatter + "\n" + body, encoding="utf-8")
    # 完全体：同步技能本体的 scripts / references / assets（模板是编译器运行时依赖）
    for sub in ("scripts", "references", "assets"):
        dest = pkg_dir / sub
        if dest.exists():
            shutil.rmtree(str(dest))
        shutil.copytree(str(SKILL_SRC / sub), str(dest),
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    # 打包 zip（豆包上传用）：固定时间戳保证可复现
    import zipfile
    zip_path = DOUBAO_DIR / "prompt-reverse-engineer.zip"
    with zipfile.ZipFile(str(zip_path), "w") as zf:
        entries = sorted(
            p.relative_to(pkg_dir).as_posix() for p in pkg_dir.rglob("*") if p.is_file()
        )
        for rel in entries:
            info = zipfile.ZipInfo(f"prompt-reverse-engineer/{rel}",
                                   date_time=(2026, 8, 15, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            zf.writestr(info, (pkg_dir / rel).read_bytes())
    actions.append(("ok", "doubao",
                    f"已生成 {DOUBAO_FILE}、{pkg_dir / 'SKILL.md'}（完整技能包）与 {zip_path}"
                    f"（豆包上传 zip 或文件夹均可）"))


def main():
    parser = argparse.ArgumentParser(description="prompt-reverse-engineer 安装脚本")
    parser.add_argument("--platform", default="all",
                        help="claude,cursor,codex,doubao 逗号分隔，或 all（默认）")
    parser.add_argument("--mode", default="junction", choices=["junction", "copy"],
                        help="junction（默认，C 盘只放联接点，实体在 F 盘）/ copy（物理复制）")
    parser.add_argument("--dry-run", action="store_true", help="只打印动作不执行")
    parser.add_argument("--force", action="store_true", help="copy 模式强制覆盖已存在目录")
    parser.add_argument("--target-root", default=None,
                        help="把安装根目录重定向到指定目录（冒烟测试，不触碰真实配置）")
    args = parser.parse_args()

    platforms = (["claude", "cursor", "codex", "doubao"]
                 if args.platform == "all"
                 else [p.strip() for p in args.platform.split(",") if p.strip()])
    unknown = [p for p in platforms if p not in ("claude", "cursor", "codex", "doubao")]
    if unknown:
        print(f"错误：未知平台：{', '.join(unknown)}", file=sys.stderr)
        sys.exit(2)

    actions = []
    for platform in platforms:
        if platform in ("claude", "cursor"):
            install_dir_platform(platform, args.mode, args.target_root,
                                 args.dry_run, args.force, actions)
        elif platform == "codex":
            install_codex(args.mode, args.target_root, args.dry_run, args.force, actions)
        elif platform == "doubao":
            build_doubao_instruction(args.dry_run, actions)

    print("== 安装汇总 ==")
    for kind, name, detail in actions:
        tag = {"ok": "[OK]", "skip": "[SKIP]", "mkdir": "[MKDIR]", "junction": "[LINK]",
               "rebuild": "[REBUILD]", "error": "[ERROR]"}.get(kind, "[?]")
        print(f"{tag} {name}: {detail}")
    errors = [a for a in actions if a[0] == "error"]
    if args.dry_run:
        print("（dry-run 模式，未执行任何写操作）")
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
