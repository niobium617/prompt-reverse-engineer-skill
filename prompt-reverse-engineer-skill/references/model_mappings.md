# 模型格式映射（model_mappings.md）

本文件是 `assets/templates/*.json` 的人读说明与选型依据。机器渲染**以模板 JSON 为准**；本文件与模板冲突时，先改模板再同步本文件。所有条目的 `last_verified` 为 **2026-11-05**。

## 1. 默认输出与模型选择

| 场景 | 默认模型 | 说明 |
|---|---|---|
| 文本逆向 | `midjourney` 不适用 → 实际输出 `gpt4_claude` 一种 | 文本模型建议 1-2 个目标即可，默认 GPT-5.5/Claude 5.5 |
| 图像逆向 | `midjourney`（V8.2） | 需要负面词或本地部署时加 `sd` |
| 视频逆向 | `sora2` | 需要镜头先行/短时长时加 `runway` 或 `veo3` |
| 叙事场景化 | 图片 `mj,sd` + 视频 `sora`（解析为 `sora2`） | 可用 `--image-models` / `--video-models` 覆盖 |

`--models` 接受模型 ID 或别名（逗号分隔），`default` 为 `midjourney,gpt4_claude`，`all` 为全部已注册模型。**模型版本升级只改模板 JSON 与本节表格，不改编译器代码。**

## 2. 模型注册表

| 模型 ID | 展示名 | 版本 | 模态 | 渲染用途（kind） | 关键别名 |
|---|---|---|---|---:|---|
| `midjourney` | Midjourney V8.2 | 8.2 | image | positive / negative / style_transfer | `mj` |
| `stable_diffusion` | Stable Diffusion 3.5 | 3.5 | image | positive / negative / params / style_transfer | `sd`, `sd3.5` |
| `flux2` | FLUX.2 [pro] | 2 | image | positive / params / style_transfer | `flux`, `flux2` |
| `gpt_image` | GPT Image 2.5 | 2.5 | image | prompt / params / edit | `gpt-image`, `dalle` |
| `nano_banana` | Nano Banana Pro | 3 | image | prompt / params / edit | `nano-banana`, `nb` |
| `gpt4_claude` | GPT-5.5 / Claude 5.5 | 5.5 | text / image / video | replicate / optimize（文本）；replicate（图/视频）；storyboard（视频） | `gpt4`, `gpt-5.5`, `claude-5.5` |
| `deepseek` | DeepSeek V4.1 Flash 1017 | 4.1 | text / image / video | replicate / optimize；image replicate；video storyboard | `ds`, `deepseek-flash`, `deepseek-1017` |
| `sora2` | Sora 2 | 2 | video | storyboard / replicate / params | `sora`, `sora-2` |
| `runway` | Runway Gen-4.5 | 4.5 | video | storyboard / replicate / params | `runway`, `gen-4.5` |
| `veo3` | Veo 3.1 | 3.1 | video | storyboard / negative / params | `veo`, `veo-3.1` |

`kind_requires` 控制条件渲染：`negative` 仅在 `negative_words` 非空时输出，`style_transfer` / `edit` 仅在 `target_style` 非空时输出。避免产出空负向块或空改写指令。

## 3. 图像模型

### 3.1 Midjourney V8.2

```text
/imagine prompt: {subject}, {scene}, {style}, {lighting}, {color}, {composition}, {photo_params}, {quality_words}, 文字「{text_content}」 --ar {aspect_ratio} --v 8.2
```

- V8.2 自 **2026-07-24** 起为默认版本；`--v 8.2` 可省略但建议显式写出，保证可复现。
- 负向不单独成句：`--no {negative_words}`，模板的 `negative` 用途输出整段可粘贴 Prompt（正向 + `--no`）。
- 角色/服装一致性改用 **Edit Model**（最多 4 张参考图）；V7 的 `--cref` / `--oref` 不适用于 V8，不要再生成。
- 常用参数：`--ar`、`--v`、`--style`、`--no`。`text_content` 用「」包裹，提示模型渲染指定文字。

### 3.2 Stable Diffusion 3.5

```text
Positive: {七段结构}
Negative: {negative_words}
Steps: 28, CFG scale: 4.5, Sampler: DPM++ 2M, Scheduler: Karras, Seed: -1, Size: {width}x{height}
```

- 正负严格分离，`params` 单独一块，便于粘贴到 WebUI / ComfyUI。
- 默认 Steps 28、CFG 4.5、DPM++ 2M + Karras；SD 3.5 对过高 CFG 更敏感，不建议回到 7-9。
- 标签堆叠仍有效，但优先「主体 → 场景 → 风格 → 光影 → 构图 → 画质」的可读顺序。

### 3.3 FLUX.2 [pro]

```text
{subject}. {scene}. {style}. {lighting}. {color}. {composition}. {photo_params}. {quality_words}. 文字「{text_content}」. {reference_note}
Guidance: 4.5, Steps: 28, Aspect ratio: 16:9
```

- **不支持 negative prompt**：模板无 negative 用途；原本的负向内容应改写为正向约束（如「干净背景，无文字」）。
- 偏好自然语言长句与完整描述，标签堆叠收益低；复杂构图建议用参考图，并在 `reference_note` 写明每张图的角色（人物/风格/构图）。
- `Guidance` 4.5 左右起步，画面过散再上调；`style_transfer` 用 `target_style` 替换 `style` 段。

### 3.4 GPT Image 2.5

```text
Create an image with the following specification.

Subject: ...
Scene: ...
Style: ...
Lighting: ...
Color: ...
Composition: ...
Camera: ...
Quality: ...
Text in image: ...
References: ...
Constraints: render all text exactly as written; no extra text, logos, or watermarks. {negative_words}
```

- 结构化「规格书」优于长串关键词；`Text in image` 只放需要精确渲染的原文，要求逐字复现。
- 支持多轮编辑：`edit` 用途一次只改一件事（`target_style`），并显式要求保留主体身份、构图、光影与已有文字。
- 常用画幅共 10 种；模板默认 `16:9`，需要方形/竖版时改 `aspect_ratio`。

### 3.5 Nano Banana Pro（Gemini 3 Pro Image）

```text
Create an image with the following specification.

Subject: ...
Location: ...
Style: ...
Lighting: ...
Color: ...
Composition: ...
Camera: ...
Quality: ...
Text in image: ...
References: ...
```

- 官方推荐顺序：主体 + 动作 → 地点 → 构图 → 风格；本模板在此基础上保留光影/色彩/画质标签。
- 分辨率 1K / 2K / 4K，模板默认 2K；API 侧最多可带 14 张参考图，`reference_note` 写清每张图的用途。
- 文字渲染能力强，需要海报/招牌文字时把原文放进 `Text in image`。
- 编辑用途：`Using the provided reference image(s), apply only this change: ...`，同样一次只改一项。

## 4. 文本模型

### 4.1 GPT-5.5 / Claude 5.5（共用模板 `gpt4_claude`）

```text
[System]
## 角色
你是{role}。
专业领域：{domain}
目标受众：{audience}
## 任务
{task}
## 背景与要求
写作风格：{style}
结构要求：{structure}
## 限制
{constraints}
## 输出格式
{output_format}

[User]
请基于以上设定生成一篇同类内容。
主题：[此处填写主题]
```

- 用 Markdown 一级/二级标题分隔六要素，模型对分节结构的遵循度明显高于纯段落拼接。
- GPT-5.5 上下文约 1.05M、输出上限 128K，推理档位 none/low/medium/high/xhigh；复杂逆向可要求先在内部推理再落笔。
- Claude 5.5 上下文 1M、输出上限 128K；**非默认 temperature/top_p/top_k 会被拒绝**，不要生成带采样参数的调用代码。
- `optimize` 用途用于「把用户的粗糙描述改写成六要素 Prompt」，输出「优化后 Prompt + 1-2 句修改说明」。

## 5. 视频模型

### 5.1 Sora 2

```text
创作一支 {duration} 秒的短视频，画幅 {aspect_ratio}。

{story}

{storyboard}

摄影：{camera}
灯光：{lighting}
色彩：{color}
氛围：{atmosphere}
声音：{audio}
旁白：{narration}
参考：{reference_note}
```

- 支持 4 / 8 / 12 / 16 / 20 秒；模板默认 12 秒。`sora-2-pro` 支持 1080p，模板默认 1280x720。
- 提示词以自然语言散文为主，先讲清「谁在什么环境做什么」，再补镜头与声音设计。
- 支持角色复用（Characters API）与视频延长；跨镜头一致性写进 `character` / `reference_note`。
- 支持 16:9 与 9:16 双画幅，`params` 块给出 `model / duration / size / aspect_ratio`。

### 5.2 Runway Gen-4.5

```text
镜头风格：{camera}
人物：{character}

{story}

{storyboard}

环境：{atmosphere}
灯光：{lighting}
色彩：{color}
视觉风格：{style}
声音：{audio}
```

- 时长 2–10 秒，输出 720p / 24–25fps；模板默认 10 秒、1280x720。
- 镜头语言先行：把运镜/景别放在最前，模型对「镜头怎么动」的响应比环境描述更直接。
- 单次生成时长有限，长叙事请拆成多段并在 `reference_note` 固定人物与场景。

### 5.3 Veo 3.1

```text
电影摄影：{camera}
主体：{character}
动作与故事：{story}

{storyboard}

背景：{atmosphere}
风格：{style}
灯光：{lighting}
色彩：{color}
音频：{audio}
旁白：{narration}
参考：{reference_note}
```

- 五段式：电影摄影 → 主体 → 动作 → 背景 → 风格氛围；分镜表插在动作之后。
- 时长 4 / 6 / 8 秒；1080p 与 4K 可用，高分辨率通常需 8 秒；模板默认 8 秒、1080p。
- 最多 3 张参考图；支持原生对白与音效，`audio` / `narration` 会直接影响生成的声音层。
- `negative` 用途输出固定负向句；**负向提示词是否生效取决于接入面**（API / 产品界面不同），交付时需说明。

## 6. 场景化默认模型

| 输出 | 默认 | 可选 |
|---|---|---|
| 每场景图片 | `mj`（V8.2）+ `sd`（3.5） | `flux2`、`gpt_image`、`nano_banana` |
| 每场景视频 | `sora`（Sora 2） | `runway`、`veo3` |

```bash
python scripts/prompt_compiler.py scenes --analysis story.json \
  --image-models mj,sd --video-models sora --dims dims.json --format md
```

跨场景一致性优先用参考图/Edit Model 固定人物造型；`semantic_analysis.characters` 写全角色表，各场景 `character` 只写本场出场人物。

## 7. 负向支持与参数速查

| 模型 | 负向支持 | 参数入口 | 默认值 |
|---|---|---|---|
| Midjourney V8.2 | 支持（`--no`） | 命令行参数 | `--ar 16:9 --v 8.2` |
| Stable Diffusion 3.5 | 支持（独立 negative） | `params` 块 | Steps 28 / CFG 4.5 / DPM++ 2M / Karras / 1024x576 |
| FLUX.2 [pro] | **不支持** | `params` 块 | Guidance 4.5 / Steps 28 |
| GPT Image 2.5 | 弱支持（写进 Constraints） | `params` 块 | quality high / 16:9 |
| Nano Banana Pro | 弱支持（改写为正向约束） | `params` 块 | 2K / 16:9 |
| GPT-5.5 / Claude 5.5 | 不适用 | 无 | — |
| DeepSeek V4.1 Flash | 不适用 | 首行模型/思考档 | `deepseek-flash` / high |
| Sora 2 | 不适用（用正向描述替代） | `params` 块 | 12s / 16:9 / 1280x720 |
| Runway Gen-4.5 | 不适用 | `params` 块 | 10s / 16:9 / 1280x720 |
| Veo 3.1 | 视接入面而定 | `params` 块 | 8s / 16:9 / 1080p |

## 8. DeepSeek 目标模型

- 别名：`deepseek` / `ds` / `deepseek-flash` / `deepseek-v4` / `deepseek-v4-flash` / `deepseek-v4.1-flash` / `deepseek-v4.1-flash-1017` / `deepseek-1017`。
- 当前快照：`V4.1-Flash-1017`；模型 ID `deepseek-flash`；1M 上下文 / 384K 输出，原生视觉输入。
- 思考档：`low` / `high` / `max`，模板默认 `high`。`default_params` 注入，无需写进 `semantic_analysis`。
- 自 2026-09-14 起，`deepseek-v4-pro` 请求在 V4.1 Pro 上线前按 Flash 费率路由到 V4.1 Flash；旧模型名继续兼容路由。逆向结果里若用户点名 V4 Pro，需说明当前实际路由。
- 模板特征：首行 `[模型] {model_id}（{snapshot}），思考档 {thinking_effort}`；六要素分节后附独立 `## 推理要求`；视觉分析要求「有参考图先读图核对，无图不得虚构」。
- **不计入默认模型集合**，仅在用户点名或显式 `--models deepseek` 时输出。

## 9. 版本迁移注记

| 旧产物 | 现状 | 迁移做法 |
|---|---|---|
| `--v 6` / `--v 7` | V8.2 为默认 | 改 `--v 8.2`；删除 `--cref` / `--oref`，改用 Edit Model |
| `--sref` / `--oref` 组合 | V8 语义已变 | 把参考图用途写进 `reference_note`，用产品侧 Edit Model |
| `sora_runway.json` | 已拆为 `sora2.json` + `runway.json` | 旧模板名不再注册；用 `sora2` / `runway` |
| SD 3.5 默认 Steps 30 / CFG 7 | 偏保守 | 改 Steps 28 / CFG 4.5 |
| GPT-4 文案 Prompt | 模型已升级 | 标题改为 GPT-5.5 / Claude 5.5，六要素不变 |
| DeepSeek `deepseek-v4-flash` | 兼容路由到 V4.1 Flash | 报告里标明实际快照 1017 |

## 10. 扩展新模型

1. 在 `assets/templates/` 新增 `<model>.json`，至少包含 `model` / `display_name` / `vendor` / `version` / `last_verified` / `alias` / `default_params` / `modalities`。
2. `alias` 不得与其他模型冲突（编译器检测到冲突会退出码 4）。
3. 可选字段放 `optional_fields`，条件渲染放 `kind_requires`，默认参数放 `default_params`。
4. 运行 `python tools/verify.py`，模板元数据、别名冲突、渲染清理会被自动检查。
5. 同步更新本文件第 2 节注册表；不要改编译器代码。
