# 基准用例（benchmarks/）

离线、确定性、可重复的回归基准，覆盖图片逆向、视频逆向、工作流解析与跨平台迁移。共 10 例：图片 3、视频 3、工作流 2、平台迁移 2。

## 两层分离

| 层 | 执行者 | 内容 | 是否自动 |
| --- | --- | --- | --- |
| 结构层 | `tools/benchmarks.py` | 退出码、模型/用途集合、必要子串、计数、JSON 路径 | 是 |
| 语义层 | Agent / 人工按 `rubric.md` 与每例 `gold.md` | 事实与推断分离、需求覆盖、平台语法、一致性、安全边界 | 否 |

结构层只回答「输出是否具备约定的形状与关键事实」，不回答「写得好不好」。语义层不接入自动评分，避免把主观判断伪装成确定性断言，也避免基准变成第二个评分引擎。

## 目录

```text
benchmarks/
  README.md
  rubric.md
  image/
    image-text-to-image.json / .gold.md
    image-multi-reference-compose.json / .gold.md
    image-shot-reverse.json / .gold.md
  video/
    video-storyboard-six-models.json / .gold.md
    video-reference-to-video.json / .gold.md
    video-shot-reverse.json / .gold.md
  workflow/
    workflow-api-parse.json / .gold.md
    workflow-ui-parse.json / .gold.md
  platform/
    platform-comfy-to-runway.json / .gold.md
    platform-comfy-to-libtv.json / .gold.md
```

## 运行

```bash
python tools/benchmarks.py --list
python tools/benchmarks.py --schema-only
python tools/benchmarks.py --check
python tools/benchmarks.py --suite image --check
python tools/verify.py --filter 基准
```

- `--list`：列出用例、金标文件与语义满分。
- `--schema-only`：只校验用例契约，不执行脚本。
- `--check`：校验契约并执行结构层断言；语义层打印 `[MANUAL]` 提示，不计分。
- `--suite`：只跑某一套；默认 `all`。

退出码：`0` 全部通过；`1` 契约不合法或结构层失败；`2` 参数错误。

## 用例契约

下列示例把结构层可用键集中展示；实际用例只取所需键，不要求全部出现。

```json
{
  "id": "image-text-to-image",
  "suite": "image",
  "title": "图片逆向：文生图反推 MJ / GPT Image 提示词",
  "input": {
    "fixture": "tools/fixtures/semantic_image.json",
    "steps": [
      {
        "script": "prompt_compiler.py",
        "args": ["compile", "--analysis", "{fixture}", "--models", "midjourney,gpt_image"],
        "exit_code": 0
      }
    ]
  },
  "structural": {
    "models": ["midjourney", "gpt_image"],
    "kinds": {"midjourney": ["positive", "negative"], "gpt_image": ["prompt", "params"]},
    "prompt_count": 5,
    "text_contains": {"midjourney/positive": ["APS 2077"]},
    "text_forbidden": ["{", "}", "uncertainty"],
    "shots": {"count": 3, "models": ["sora2"], "prompts_per_shot": 4, "checklist_min": 6},
    "json_equals": {"workflow.format": "comfyui_api"},
    "json_lengths": {"workflow.nodes": 11}
  },
  "semantic": {
    "gold": "image-text-to-image.gold.md",
    "criteria": ["..."],
    "max_score": 10
  }
}
```

约束：

- `id` 为小写 kebab-case，必须与所在目录的 `suite` 一致。
- `input.fixture` 必须存在；步骤脚本只允许 `prompt_compiler.py`、`analyze_workflow.py`。
- 步骤可用 `{fixture}` 引用输入文件；`save` 会把该步 stdout 存为 JSON，供后续步骤以 `{save名}` 引用。
- 用例 JSON 不得包含绝对路径。
- 每例必须有 `gold.md` 与至少 3 条语义标准。
- `structural` 不允许未知键。

## 新增用例

1. 在对应 suite 目录放输入 fixture（优先复用 `tools/fixtures/`）。
2. 新建 `<id>.json`，写清输入、结构层断言与语义标准。
3. 新建 `<id>.gold.md`：输入、结构层金标、必须命中、允许改写、不允许、评分锚点。
4. 运行 `python tools/benchmarks.py --suite <suite> --check`。
5. 在 `tools/verify.py` 的基准检查中登记用例数量与关键断言。

## 边界

- 不调用模型、不联网、不需要 API Key。
- 不执行 ComfyUI 工作流，不生成可导入工作流。
- 结构层不校验文风、不校验「是否像官方模板」；这些属于语义层。
- 语义层结果不写入自动断言，只按 `rubric.md` 记录人工评分。
- 基准失败不等于模型不可用，只说明输出契约或关键事实发生变化。
