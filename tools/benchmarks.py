#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""基准用例执行器（离线、确定性，只验证结构层）。

目录：
  benchmarks/<suite>/<case>.json     用例定义（输入 / 结构层断言 / 语义层金标）
  benchmarks/<suite>/gold.md         语义层金标与评分锚点
  benchmarks/README.md              用法与两层分离说明
  benchmarks/rubric.md              语义层评分 rubric

分层：
  - 结构层：本脚本执行，校验退出码、模型/用途集合、必要子串、计数与 JSON 路径，
           结果可重复，不依赖网络或模型调用；
  - 语义层：不自动评分，由 Agent/人工按 rubric.md 与每例 gold.md 打分，
           避免把「像不像」伪装成确定性断言。

用法：
  python tools/benchmarks.py --list
  python tools/benchmarks.py --check
  python tools/benchmarks.py --suite image --check
  python tools/benchmarks.py --check --schema-only

退出码：0 全部通过；1 有用例失败或契约不合法；2 参数错误。
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SKILL = REPO / "prompt-reverse-engineer-skill"
SCRIPTS = SKILL / "scripts"
BENCH = REPO / "benchmarks"
FIXTURES = REPO / "tools" / "fixtures"
SUITES = ("image", "video", "workflow", "platform")
ALLOWED_SCRIPTS = {"prompt_compiler.py", "analyze_workflow.py"}
ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{2,63}$")
STEP_RE = re.compile(r"\{([a-z0-9-]+)\}")
ABS_PATH_RE = re.compile(r"(?:[A-Za-z]:[\\/]|/home/|/Users/|\\\\[^\\]+\\[^\\]+)")
PYTHON = sys.executable or "python"


class CaseError(Exception):
    pass


def load_json(path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise CaseError(f"不可读：{path.name}：{exc}")
    except json.JSONDecodeError as exc:
        raise CaseError(f"不是合法 JSON：{path.name}：{exc}")


def suite_cases(suite):
    directory = BENCH / suite
    if not directory.is_dir():
        return []
    return [(suite, path) for path in sorted(directory.glob("*.json"))]


def all_cases(selected):
    cases = []
    for suite in SUITES:
        if selected != "all" and selected != suite:
            continue
        cases.extend(suite_cases(suite))
    return cases


def rel(path):
    return path.resolve().relative_to(REPO.resolve()).as_posix()


def validate_case(suite, path):
    case = load_json(path)
    text = path.read_text(encoding="utf-8")
    if ABS_PATH_RE.search(text):
        raise CaseError("用例文件含绝对路径")
    required = ("id", "suite", "title", "input", "structural", "semantic")
    for key in required:
        if key not in case:
            raise CaseError(f"缺少字段 {key}")
    if not isinstance(case["id"], str) or not ID_RE.match(case["id"]):
        raise CaseError("id 必须是小写 kebab-case")
    if case["suite"] != suite:
        raise CaseError(f"suite 必须与目录一致（{suite}）")
    if not isinstance(case["title"], str) or not case["title"].strip():
        raise CaseError("title 不能为空")

    inp = case["input"]
    if not isinstance(inp, dict):
        raise CaseError("input 必须是对象")
    fixture = inp.get("fixture")
    if not isinstance(fixture, str) or not fixture.strip():
        raise CaseError("input.fixture 不能为空")
    if not (REPO / fixture).is_file():
        raise CaseError(f"fixture 不存在：{fixture}")
    steps = inp.get("steps")
    if not isinstance(steps, list) or not steps:
        raise CaseError("input.steps 必须是非空数组")
    for index, step in enumerate(steps):
        if not isinstance(step, dict):
            raise CaseError(f"input.steps[{index}] 必须是对象")
        script = step.get("script")
        if script not in ALLOWED_SCRIPTS:
            raise CaseError(f"input.steps[{index}].script 不在白名单：{script}")
        if not isinstance(step.get("args"), list) or not all(
                isinstance(arg, str) for arg in step["args"]):
            raise CaseError(f"input.steps[{index}].args 必须是字符串数组")
        if not isinstance(step.get("exit_code"), int):
            raise CaseError(f"input.steps[{index}].exit_code 必须是整数")
        save = step.get("save")
        if save is not None and (not isinstance(save, str)
                                 or not ID_RE.match(save)):
            raise CaseError(f"input.steps[{index}].save 必须是小写 kebab-case")
    if "save" not in steps[-1] and steps[-1]["exit_code"] != 0:
        raise CaseError("最后一步退出码非 0 时必须包含 save")

    structural = case["structural"]
    if not isinstance(structural, dict) or not structural:
        raise CaseError("structural 必须是非空对象")
    known = {"models", "kinds", "prompt_count", "text_contains",
             "text_forbidden", "shots", "json_equals", "json_lengths"}
    unknown = sorted(set(structural) - known)
    if unknown:
        raise CaseError(f"structural 含未知键：{', '.join(unknown)}")

    semantic = case["semantic"]
    if not isinstance(semantic, dict):
        raise CaseError("semantic 必须是对象")
    gold = semantic.get("gold")
    if not isinstance(gold, str) or not gold.strip():
        raise CaseError("semantic.gold 不能为空")
    if not (path.parent / gold).is_file():
        raise CaseError(f"语义层金标不存在：{gold}")
    criteria = semantic.get("criteria")
    if not isinstance(criteria, list) or len(criteria) < 3 or not all(
            isinstance(item, str) and item.strip() for item in criteria):
        raise CaseError("semantic.criteria 至少 3 条非空字符串")
    max_score = semantic.get("max_score")
    if not isinstance(max_score, int) or max_score <= 0:
        raise CaseError("semantic.max_score 必须是正整数")
    return case


def build_args(args, variables):
    built = []
    for arg in args:
        def replace(match):
            name = match.group(1)
            if name not in variables:
                raise CaseError(f"未定义的变量：{{{name}}}")
            return variables[name]
        built.append(STEP_RE.sub(replace, arg))
    return built


def run_steps(case, workdir):
    fixture = str((REPO / case["input"]["fixture"]).resolve())
    variables = {"fixture": fixture}
    output = b""
    for index, step in enumerate(case["input"]["steps"]):
        script = SCRIPTS / step["script"]
        args = build_args(step["args"], variables)
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        env["PYTHONHASHSEED"] = "0"
        try:
            proc = subprocess.run(
                [PYTHON, str(script)] + args,
                cwd=str(REPO), env=env, capture_output=True, timeout=120,
            )
        except subprocess.TimeoutExpired:
            raise CaseError(f"步骤 {index + 1} 超过 120 秒未结束")
        if proc.returncode != step["exit_code"]:
            raise CaseError(
                f"步骤 {index + 1} 退出码 {proc.returncode}，"
                f"期望 {step['exit_code']}：{proc.stderr.decode('utf-8', 'replace')[:300]}")
        output = proc.stdout
        save = step.get("save")
        if save:
            target = workdir / f"{save}.json"
            target.write_bytes(output)
            variables[save] = str(target)
    if not output.strip():
        raise CaseError("最后一步没有输出")
    try:
        return json.loads(output.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CaseError(f"最后一步输出不是合法 JSON：{exc}")


def get_path(doc, path):
    current = doc
    for part in path.split("."):
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                raise CaseError(f"路径不存在：{path}")
        elif isinstance(current, dict):
            if part not in current:
                raise CaseError(f"路径不存在：{path}")
            current = current[part]
        else:
            raise CaseError(f"路径不可继续：{path}")
    return current


def prompt_map(doc):
    return {(p["model"], p["kind"]): p for p in doc.get("prompts") or []}


def assert_structural(case, doc):
    s = case["structural"]
    if "models" in s:
        expected = sorted(s["models"])
        actual = sorted(doc.get("models") or [])
        if actual != expected:
            raise CaseError(f"模型集合 {actual} != {expected}")
    if "kinds" in s:
        actual = prompt_map(doc)
        for model, kinds in s["kinds"].items():
            present = sorted(kind for m, kind in actual if m == model)
            if present != sorted(kinds):
                raise CaseError(f"{model} 用途 {present} != {sorted(kinds)}")
    if "prompt_count" in s:
        count = len(doc.get("prompts") or [])
        if count != s["prompt_count"]:
            raise CaseError(f"prompt 数 {count} != {s['prompt_count']}")
    texts = [str(p.get("text", "")) for p in doc.get("prompts") or []]
    if "text_contains" in s:
        mapping = prompt_map(doc)
        for key, needles in s["text_contains"].items():
            model, _, kind = key.partition("/")
            prompt = mapping.get((model, kind))
            if not prompt:
                raise CaseError(f"缺少 Prompt：{key}")
            for needle in needles:
                if needle not in prompt["text"]:
                    raise CaseError(f"{key} 缺少子串：{needle}")
    for needle in s.get("text_forbidden") or []:
        for text in texts:
            if needle in text:
                raise CaseError(f"Prompt 出现禁止子串：{needle}")
    if "shots" in s:
        spec = s["shots"]
        shots = doc.get("shots") or []
        if "count" in spec and len(shots) != spec["count"]:
            raise CaseError(f"镜头数 {len(shots)} != {spec['count']}")
        if "models" in spec:
            actual = sorted(doc.get("models") or [])
            if actual != sorted(spec["models"]):
                raise CaseError(f"镜头模型 {actual} != {sorted(spec['models'])}")
        if "prompts_per_shot" in spec:
            for shot in shots:
                count = len(shot.get("prompts") or [])
                if count != spec["prompts_per_shot"]:
                    raise CaseError(
                        f"镜头 {shot.get('card', {}).get('shot_no')} "
                        f"Prompt 数 {count} != {spec['prompts_per_shot']}")
        if "checklist_min" in spec:
            count = len(doc.get("review_checklist") or [])
            if count < spec["checklist_min"]:
                raise CaseError(f"审查清单 {count} < {spec['checklist_min']}")
        if "skipped" in spec:
            skipped = doc.get("skipped") or []
            if len(skipped) != spec["skipped"]:
                raise CaseError(f"跳过模型 {len(skipped)} != {spec['skipped']}")
    for path, expected in (s.get("json_equals") or {}).items():
        actual = get_path(doc, path)
        if actual != expected:
            raise CaseError(f"{path} = {actual!r} != {expected!r}")
    for path, expected in (s.get("json_lengths") or {}).items():
        actual = get_path(doc, path)
        if not isinstance(actual, (list, dict)):
            raise CaseError(f"{path} 不是可计数对象")
        if len(actual) != expected:
            raise CaseError(f"{path} 长度 {len(actual)} != {expected}")


def describe(case):
    semantic = case["semantic"]
    return (f"{case['id']} [{case['suite']}] {case['title']} | "
            f"gold={semantic['gold']} 语义满分={semantic['max_score']}")


def main():
    parser = argparse.ArgumentParser(description="离线基准：结构层自动校验，语义层人工评分")
    parser.add_argument("--suite", choices=SUITES + ("all",), default="all",
                        help="选择用例集（默认 all）")
    parser.add_argument("--check", action="store_true",
                        help="校验用例契约并执行结构层断言")
    parser.add_argument("--schema-only", action="store_true",
                        help="只校验用例契约，不执行脚本")
    parser.add_argument("--list", action="store_true", help="列出用例")
    args = parser.parse_args()
    if not (args.check or args.schema_only or args.list):
        parser.error("请指定 --check、--schema-only 或 --list")

    cases = all_cases(args.suite)
    if not cases:
        print(f"错误：用例集 {args.suite} 为空", file=sys.stderr)
        return 2
    loaded = []
    failures = []
    for suite, path in cases:
        try:
            loaded.append(validate_case(suite, path))
        except CaseError as exc:
            failures.append(f"{rel(path)}：{exc}")
    if failures:
        for item in failures:
            print(f"[FAIL] {item}", file=sys.stderr)
        return 1
    if args.list:
        for case in loaded:
            print(describe(case))
        return 0
    if args.schema_only:
        print(f"用例契约通过：{len(loaded)} 例（"
              + " / ".join(f"{suite} {sum(1 for item in loaded if item['suite'] == suite)}"
                           for suite in SUITES
                           if any(item['suite'] == suite for item in loaded))
              + "）")
        return 0

    tmp_root = REPO / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="aps-bench-", dir=str(tmp_root)))
    passed = 0
    try:
        for case in loaded:
            try:
                doc = run_steps(case, workdir)
                assert_structural(case, doc)
            except (CaseError, KeyError) as exc:
                failures.append(f"{case['id']}：{exc}")
                print(f"[FAIL] {case['id']}：{exc}", file=sys.stderr)
                continue
            passed += 1
            print(f"[PASS] {case['id']}（结构层）")
            semantic = case["semantic"]
            print(f"[MANUAL] {case['semantic']['gold']}："
                  f"{len(semantic['criteria'])} 条语义标准，"
                  f"满分 {semantic['max_score']}，按 benchmarks/rubric.md 评分")
    finally:
        shutil.rmtree(str(workdir), ignore_errors=True)

    print(f"\n结构层通过 {passed} / {len(loaded)}；语义层需人工/Agent 评分")
    if failures:
        print("失败：", file=sys.stderr)
        for item in failures:
            print(f"  - {item}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
    sys.exit(main())
