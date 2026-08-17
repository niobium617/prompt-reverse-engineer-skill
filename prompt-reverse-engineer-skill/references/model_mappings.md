# 模型格式映射表

> 六要素语义字段 → 各目标模型 Prompt 格式的映射规范。机器渲染模板见 `assets/templates/*.json`（占位符即 `prompt_framework.md` 的字段名），本文件供 Agent 理解与人工撰写时参考。

## 一、默认输出规则

- 用户**未指定目标模型**时，默认输出 **Midjourney + GPT-4/Claude 两个版本**。
- 用户指定多个模型时（如"转成 MJ 和 SD"），全部输出。
- 用户指定了未注册的模型名 → 回退默认双版本，并在输出中说明。

## 二、模型注册表（template 文件对应关系）

| 模型 | alias | 模板文件 | 主要场景 |
|---|---|---|---|
| Midjourney | mj, midjourney | midjourney.json | 图像生成 |
| Stable Diffusion | sd, stable_diffusion | stable_diffusion.json | 图像生成 |
| GPT-4 / Claude | gpt4, claude, gpt | gpt4_claude.json | 文本/通用 |
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

## 六、Sora / Runway 格式（自然语言分镜脚本）

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

## 七、扩展位

新增模型 = 在 `assets/templates/` 新增一个 `*.json` 模板（含 `model`/`alias`/`default_params`/`modalities` 字段，占位符用 `prompt_framework.md` 字段名），`prompt_compiler.py` 自动注册发现；并在本文件第二节补一行映射。
