#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""从 tools/fixtures 重新生成四模态示例 output.md（确定性、离线、无 API）。

示例是技能的对外展示，手写副本必然与模板/编译器漂移；本脚本用金标语义
analysis JSON 直接跑编译器，输出即示例，`verify.py` 断言两者逐字节一致。

用法：
  python tools/gen_examples.py           # 重新生成四个 output.md
  python tools/gen_examples.py --check   # 只校验（逐字节），不一致退出 1
退出码：0 成功/一致；1 生成失败或存在差异。
"""
import argparse
import subprocess
import sys
from pathlib import Path

PYTHON = sys.executable
REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "prompt-reverse-engineer-skill"
COMPILER = SKILL / "scripts" / "prompt_compiler.py"
FIXTURES = REPO / "tools" / "fixtures"
EXAMPLES = SKILL / "assets" / "examples"

# 示例目录 → 生成参数。所有命令都带 --auto（启发式评分），保证无人工给分也能复现。
JOBS = [
    {
        "dir": "text_example",
        "fixture": "semantic_text.json",
        "title": "文本模态（GPT-5.5 / Claude 5.5）",
        "command": ["all"],
    },
    {
        "dir": "image_example",
        "fixture": "semantic_image.json",
        "title": "图片模态（默认图片模型）",
        "command": ["all"],
    },
    {
        "dir": "video_example",
        "fixture": "semantic_video.json",
        "title": "视频模态（默认视频模型分镜）",
        "command": ["all"],
    },
    {
        "dir": "story_example",
        "fixture": "semantic_story.json",
        "title": "叙事文本逐场景（剧本 → 图片 + 视频提示词）",
        "command": ["scenes"],
    },
]

HEADER = (
    "# 示例输出：{title}\n"
    "\n"
    "> 本文件由 `python tools/gen_examples.py` 从 "
    "`tools/fixtures/{fixture}` 生成，请勿手工编辑。\n"
    "\n"
)


def render(job):
    """调用编译器生成示例正文（CRLF 归一化为 LF，保证跨平台逐字节一致）。"""
    cmd = [PYTHON, str(COMPILER), *job["command"],
           "--analysis", str(FIXTURES / job["fixture"]), "--auto", "--format", "md"]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0:
        detail = proc.stderr.decode("utf-8", errors="replace")[:400]
        raise SystemExit(f"生成 {job['dir']} 失败（退出码 {proc.returncode}）：{detail}")
    body = proc.stdout.decode("utf-8").replace("\r\n", "\n").strip("\n")
    # 编译器正文自带一级标题；降为二级，让示例文件只有一个 H1
    if body.startswith("# "):
        body = "## " + body[2:]
    header = HEADER.format(title=job["title"], fixture=job["fixture"])
    return header + body + "\n"


def main():
    parser = argparse.ArgumentParser(description="重新生成四模态示例 output.md")
    parser.add_argument("--check", action="store_true",
                        help="只校验仓库示例与生成结果是否逐字节一致")
    args = parser.parse_args()

    failed = 0
    for job in JOBS:
        target = EXAMPLES / job["dir"] / "output.md"
        expected = render(job)
        if args.check:
            actual = target.read_text(encoding="utf-8") if target.exists() else None
            if actual == expected:
                print(f"[PASS] {job['dir']}/output.md 与生成结果一致")
            else:
                failed += 1
                print(f"[DIFF] {job['dir']}/output.md 已漂移，"
                      "请运行 python tools/gen_examples.py")
        else:
            target.write_text(expected, encoding="utf-8", newline="\n")
            print(f"[OK] 已生成 {target.relative_to(REPO)}")
    if failed:
        sys.exit(1)


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
