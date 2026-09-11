# 模型格式映射表

> 六要素语义字段 → 各目标模型 Prompt 格式的映射规范。机器渲染模板见 `assets/templates/*.json`（占位符即 `prompt_framework.md` 的字段名），本文件供 Agent 理解与人工撰写时参考。

## 一、默认输出规则

- 用户**未指定目标模型**时，默认输出 **Midjourney + GPT-4/Claude 两个版本**。
- 场景化模式（叙事文本 → 逐场景提示词，`prompt_compiler.py scenes`）：默认 **图片 = Midjourney + Stable Diffusion 双版本**、**视频 = Sora**，可用 `--image-models` / `--video-models` 指定其他组合。
- 用户指定多个模型时（如"转成 MJ 和 SD"），全部输出。
- 用户指定了未注册的模型名 → 回退默认版本，并在输出中说明。
- **DeepSeek 版为可选输出**（用户说"也出 DeepSeek 版" → `--models deepseek`），**不计入默认集合**；默认集合定义于 `prompt_compiler.py` 的 `DEFAULT_MODELS`。

## 二、模型注册表（template 文件对应关系）

| 模型 | alias | 模板文件 | 主要场景 |
|---|---|---|---|
| Midjourney | mj, midjourney | midjourney.json | 图像生成 |
| Stable Diffusion | sd, stable_diffusion | stable_diffusion.json | 图像生成 |
| GPT-4 / Claude | gpt4, claude, gpt | gpt4_claude.json | 文本/通用 |
| DeepSeek V4.1 Flash | ds, deepseek, deepseek-flash | deepseek.json | 文本/通用（含原生视觉输入） |
| Sora / Runway | sora, runway | sora_runway.json | 视频生成 |

## 三、Midjourney 格式

```
/imagine prompt: {subject}, {scene}, {style}, {lighting}, {color}, {composition}, {photo_params}, {quality_words} --ar {aspect_ratio} --v {version}
```

- 要素按 `image_rules.md` 第一节七段顺序排列，逗号分隔（主体+动作 → 场景 → 风格 → 光影色调 → 构图 → 画质质感）。
- 负向内容用 `--no {negative_words}` 参数表达（MJ 无独立 Negative 段），按第八节三类组织。
- 常用参数：`--ar`（比例，默认 16:9）、`--v`（版本）、`--stylize`（风格化 0-1000）、`--chaos`（随机性 0-100）、`--no`。
- MJ **不支持** `(词:权重)` 权重语法，突出要素用前置或 `--stylize`/`--chaos`（见 image_rules.md 第九节）。
- 风格迁移：替换 `{style}` 为目标风格词，其余段位不变：`/imagine prompt: {subject}, {scene}, {target_style}, {lighting}, {color}, {composition}, {photo_params}, {quality_words} --ar {aspect_ratio} --v {version}`。

## 四、Stable Diffusion 格式

```
Positive: {subject}, {scene}, {style}, {lighting}, {color}, {composition}, {photo_params}, {quality_words}
Negative: {negative_words}
Steps: 30, CFG scale: 7, Sampler: DPM++ 2M Karras, Seed: -1, Size: {width}x{height}
```

- Positive 与 Negative **严格分离**成两段；Positive 按第一节七段顺序，Negative 按第八节三类组织。
- 参数行：Steps / CFG / Sampler / Seed / Size / Model tag（如真实感模型 `photorealistic` 前缀）。
- 权重语法：SD 支持 `(关键词:权重数值)`（>1 增强、<1 减弱），见 image_rules.md 第九节。
- 风格迁移：替换 Positive 中的 `{style}` 为目标风格词，其余段位不变。

## 五、GPT-4 / Claude 格式（System + User 消息结构）

```
[System]
你是{role}。背景：{context 要素组合}。
任务：{task}。
要求：{style}；{structure}。
限制：{constraints}。
输出格式：{output_format}。

[User]
（用户提供的输入数据，如原文/图片描述/分镜素材）
```

- 文本模态直接按六要素映射为 System 消息，User 放原文本或主题输入。
- 视频模态可将 storyboard 渲染为 System 中的分镜表，User 放参考素材描述。
- 复刻用途（replicate）：System 描述"如何生成同类内容"；优化用途：System 描述"如何优化输入内容"。

## 六、DeepSeek 格式（System + User + 独立推理段）

```
[模型] {model_id}，思考档 {thinking_effort}
[System]
你是{role}。专业领域：{domain}。目标受众：{audience}。
任务：{task}。
写作风格：{style}。
结构要求：{structure}。
限制：{constraints}。
输出格式：{output_format}。
[推理要求]
先拆解原作的角色锚点、风格特征与结构骨架，列出必须复现的要素，再据此产出正文；推理过程无需展示，结论必须落在正文里。
[User]
请基于以上设定生成一篇同类内容，主题：[此处填写主题]
```

- 目标模型为 **DeepSeek V4.1 Flash**（API 模型名 `deepseek-flash`）。首行 `{model_id}` 与 `{thinking_effort}` 由模板 `default_params` 注入，**不占 `semantic_analysis` 字段**，与 `prompt_framework.md` 第二节字段表不冲突。
- **独立 `[推理要求]` 段**：与第五节 GPT-4/Claude 格式的**唯一结构差异**。DeepSeek V4.1 Flash 默认开启思考模式，把"先拆解什么、再产出什么"显式写出，可显著提升复刻一致性；非思考模式调用时该段退化为普通要求段，无需改写。
- **思考档位**（`low` / `high` / `max`，模板默认 `high`）：任务越复杂越往上调。

| 任务类型 | 建议档位 |
|---|---|
| 单条短文本复刻、简单优化 | low |
| 常规逆向分析（单模态文本/图片） | high（默认） |
| 长剧本场景化、多镜头分镜、逐场景评分 | max |

- **原生视觉输入**：`deepseek-flash` 支持图片输入（1M 上下文 / 384K 输出），模板图像模态已内置"附参考图则直读核对、无图则不得虚构画面细节"的指令。API 文档**未声明视频输入**，视频模态仍按 `video_rules.md` 抽关键帧后逐帧喂图。
- **API 双格式**：`https://api.deepseek.com`（OpenAI 格式）或 `https://api.deepseek.com/anthropic`（Anthropic 格式），本模板的 System/User 结构两者通用。
- **模型路由**：旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 已下线但暂时路由到 V4.1 Flash；`deepseek-v4-pro` 自 2026-09-14 12:00（北京时间）起同样路由到 V4.1 Flash 并按 Flash 计费。

## 七、Sora / Runway 格式（自然语言分镜脚本）

```
创作一支 {duration} 秒的{氛围/类型}短片，画幅 {aspect_ratio}。
故事：{story}
{逐镜头段落，按 video_rules.md 分镜规范}
镜头1：{shot_size}，{camera_move}，{duration_s}秒。{action}。{dialogue}
镜头2：……
整体氛围：{atmosphere}；灯光：{lighting}。
```

- 用自然语言段落而非表格；运镜术语用 `video_rules.md` 第三节英文模板。
- 每镜头一个段落，画面内容具体到动作与环境。

## 八、扩展位

新增模型 = 在 `assets/templates/` 新增一个 `*.json` 模板（含 `model`/`alias`/`default_params`/`modalities` 字段，占位符用 `prompt_framework.md` 字段名），`prompt_compiler.py` 自动注册发现；并在本文件第二节补一行映射。

模板若要引用**非语义字段**（模型名、调用参数等，不属于 `semantic_analysis`），写进 `default_params` 由编译器注入——范例见 `deepseek.json` 的 `model_id` 与 `thinking_effort`（渲染为 `[模型] deepseek-flash，思考档 high`）。此类占位符**不得**写进 `prompt_framework.md` 第二节字段表，否则会被误当成必填语义字段。
