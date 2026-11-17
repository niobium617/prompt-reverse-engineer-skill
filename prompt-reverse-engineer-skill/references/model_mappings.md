# 模型格式映射（model_mappings.md）

本文件是 `assets/templates/*.json` 的人读说明与选型依据。机器渲染**以模板 JSON 为准**；本文件与模板冲突时，先改模板再同步本文件。各模型 `last_verified` 以模板 JSON 为准（Muse Image、Seedance 2.5 为 **2026-11-15**；即梦 5.0、Kling 4.0、Hailuo 3、Vidu Q3 为 **2026-11-18**；其余多数为 **2026-11-05**）。

## 1. 默认输出与模型选择

| 场景 | 默认模型 | 说明 |
|---|---|---|
| 文本逆向 | `midjourney` 不适用 → 实际输出 `gpt4_claude` 一种 | 文本模型建议 1-2 个目标即可，默认 GPT-5.5/Claude 5.5 |
| 图像逆向 | `midjourney`（V8.2） | 需要负面词或本地部署时加 `sd` |
| 视频逆向 | `sora2` | 需要镜头先行/短时长时加 `runway` 或 `veo3` |
| 视频首尾帧 / 参考素材 / 编辑 / 延长 | `seedance`（2.5） | 其余视频模型无对应能力或仅部分支持 |
| 叙事场景化 | 图片 `mj,sd` + 视频 `sora`（解析为 `sora2`） | 可用 `--image-models` / `--video-models` 覆盖 |
| 实拍镜头反推 | 视频 `sora,runway,veo,seedance`；图片 `midjourney,stable_diffusion,flux2,gpt_image,muse_image,nano_banana` | `shots` 按 `modality` 自动取默认；`--models` 可缩小子集 |

`--models` 接受模型 ID 或别名（逗号分隔），`default` 为 `midjourney,gpt4_claude`，`all` 为全部已注册模型。**模型版本升级只改模板 JSON 与本节表格，不改编译器代码。**

## 2. 模型注册表

| 模型 ID | 展示名 | 版本 | 模态 | 渲染用途（kind） | 关键别名 |
|---|---|---|---|---:|---|
| `midjourney` | Midjourney V8.2 | 8.2 | image | positive / negative / style_transfer | `mj` |
| `stable_diffusion` | Stable Diffusion 3.5 | 3.5 | image | positive / negative / params / style_transfer | `sd`, `sd3.5` |
| `flux2` | FLUX.2 [pro] | 2 | image | positive / params / style_transfer | `flux`, `flux2` |
| `gpt_image` | GPT Image 2.5 | 2.5 | image | prompt / params / recreate / edit / reference_guided / compose | `gpt-image`, `dalle` |
| `muse_image` | Muse Image 1.0 | 1.0 | image | prompt / recreate / edit / reference_guided / compose / anchored_composition / conversational_refinement / text_layout | `muse`, `muse-image`, `muse-image-1.0`, `meta-muse` |
| `nano_banana` | Nano Banana Pro | 3 | image | prompt / params / edit | `nano-banana`, `nb` |
| `jimeng` | 即梦 5.0（Seedream 5.0） | 5.0 | image | prompt / recreate / edit / reference_guided / compose / params | `即梦`, `seedream`, `seedream-5`, `seedream-5.0`, `doubao-seedream` |
| `gpt4_claude` | GPT-5.5 / Claude 5.5 | 5.5 | text / image / video | replicate / optimize（文本）；replicate（图/视频）；storyboard（视频） | `gpt4`, `gpt-5.5`, `claude-5.5` |
| `deepseek` | DeepSeek V4.1 Flash 1017 | 4.1 | text / image / video | replicate / optimize；image replicate；video storyboard | `ds`, `deepseek-flash`, `deepseek-1017` |
| `seedance` | Seedance 2.5 | 2.5 | video | storyboard / image_to_video / first_last_frame / reference_to_video / video_edit / video_extend / params | `seedance-2.5`, `seedance25`, `doubao-seedance`, `doubao-seedance-2.5` |
| `sora2` | Sora 2 | 2 | video | storyboard / replicate / params | `sora`, `sora-2` |
| `runway` | Runway Gen-4.5 | 4.5 | video | storyboard / replicate / params | `runway`, `gen-4.5` |
| `veo3` | Veo 3.1 | 3.1 | video | storyboard / negative / params | `veo`, `veo-3.1` |
| `kling` | Kling 4.0 | 4.0 | video | storyboard / image_to_video / first_last_frame / reference_to_video / params | `kling-4`, `kling-4.0`, `可灵` |
| `hailuo` | Hailuo 3（MiniMax H3） | 3 | video | storyboard / image_to_video / first_last_frame / reference_to_video / params | `hailuo-3`, `minimax`, `minimax-h3`, `海螺` |
| `vidu` | Vidu Q3 | Q3 | video | storyboard / image_to_video / first_last_frame / reference_to_video / params | `vidu-q3`, `viduq3`, `vidu-q3-pro`, `生数` |

`kind_requires` 控制条件渲染：`negative` 仅在 `negative_words` 非空时输出，`style_transfer` / `edit` 仅在 `target_style` 非空时输出。避免产出空负向块或空改写指令。门控字段可以是任意 `optional_fields` / `default_params` 中的字段（如 GPT Image 的 `reference_images`），为数组时按「存在非空项」判定。可选字段缺省时默认只清空标签文字并保留空行；模板声明 `"clean_empty_label_lines": true` 后整行连同换行删除（GPT Image 规格书式排版使用）。

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

五种任务模式各对应一个用途（kind），编译时按 `task_type` / `--kind` 只渲染其中一个（映射见 `prompt_framework.md` 2.3.1 节）：

```text
prompt（文生图）
Create an image with the following specification.
Subject: ... Position: ... Scale: ... Spatial layout: ... Scene: ...
Shot: ... Camera angle: ... Style: ... Lighting: ... Color: ...
Composition: ... Camera: ... Material: ... Quality: ... Text in image: ...
References: ... Constraints: render all text exactly as written; no extra text, logos, or watermarks. {negative_words}

recreate（按参考图复刻）
Recreate the referenced image as faithfully as possible.
Subject / Position / Scale / Spatial layout / Shot / Camera angle / Lighting / Color / Material / Style
Preserve: ... Avoid: ... Do not invent details that are not visible in the reference; do not restyle the image.

edit（单点编辑）
Edit the provided image.
Change: ... Modification scope: ...
Preserve unchanged: ... Do not change: ...
Keep all other content, composition, lighting, color and existing text exactly as is.

reference_guided（参考图定角色生成新图）
Create an image using the provided references.
Reference roles:（每张参考图一行，图N：角色说明）
Subject / Spatial layout / Style / Lighting / Color / Composition / Material
Constraints: use each reference only for its assigned role; do not transfer unlisted attributes. {negative_words}

compose（多参考图融合）
Compose a new image from the provided references.
Element sources:（每张参考图一行）
Placement / Scale / Spatial layout / Style / Lighting / Color / Composition
Constraints: match perspective, light direction, color temperature and material across all elements; do not simply collage the references.
```

- 结构化「规格书」优于长串关键词；`Text in image` 只放需要精确渲染的原文，要求逐字复现。
- `edit` 一次只改一件事：`Change` 写修改目标（`target_style`），`Modification scope` 限定范围，`Preserve unchanged` / `Do not change` 分别写保留项与禁改项；`edit` 仅在提供 `modification_scope` 时渲染。
- `recreate` 复刻参考图，`reference_guided` 让每张参考图只承担指定角色，`compose` 把多个参考元素合成同一画面（要求透视/光向/色温/材质一致，而不是拼贴）。
- `reference_images` 每项格式为「图N：角色说明」，编号必须唯一且连续可辨；缺编号或重复 → 退出码 4。参考图逐行渲染，一行一张。
- 本模板启用 `clean_empty_label_lines`：可选字段缺失时整行删除，避免规格书留下孤立空行（默认模板只清空标签、保留空行，以维持既有输出）。
- 常用画幅共 10 种；模板默认 `16:9`，需要方形/竖版时改 `aspect_ratio`。

### 3.5 Muse Image 1.0

**独立模板**：`assets/templates/muse_image.json`，规则文件 `references/muse_image_rules.md`。与 GPT Image 只共享扁平 `semantic_analysis` 字段与参考图角色枚举，不共用模板；Muse 更新不影响 GPT Image 编译策略。

八种用途（前五种与通用任务同名，后三种为 Muse 扩展）：

```text
prompt（文生图）
Create a new image from the following brief.
Task: ... Main subject: ... Position and scale: ... Spatial relationships: ...
Scene: ... Composition and camera: ... Visual style: ... Text in image: ... Avoid: ...

recreate（高保真复刻）
Task: high-fidelity recreation ... 主体/位置/空间关系/场景/构图/光影/材质
Preserve exactly: ... Avoid changing: ...
do not invent details / do not restyle / keep original proportions and spatial relationships

edit（局部编辑）
Requested changes: ... Modification scope: ...
Preserve unchanged: ... Do not change: ...
apply only the requested change; keep identity, pose, framing, lighting and text unchanged

reference_guided（参考图定角色）
Reference roles — each image is used only as described:
图1：identity_reference；用途：…；保留：…；禁止迁移：…
Reference usage / Allowed feature transfer / Forbidden feature transfer
Constraints: use each reference only for its assigned role ...

compose（多图融合）
Element sources — each reference contributes only what is described:
（逐图角色与用途）
Constraints: integrate into one coherent scene; match perspective/light/color temperature; do not collage

anchored_composition（系列一致性）
Anchor set — reuse these references exactly as described:
资产1：character_reference；参考图：图1；保留：…
Preserve across the series: ... Do not change: ...
Constraints: reuse same anchors for identity, clothing, environment and style

conversational_refinement（多轮修改）
Current iteration state — continue from this result without resetting earlier decisions:
第1轮：… / 本轮：…
Requested change for this round: ... Modification scope: ...
Preserve from previous rounds: ... Do not change: ...

text_layout（海报/信息图表）
Text content: ... Layout: ...
Main subject / Scene / Visual style / Composition
Constraints: render every character exactly; preserve hierarchy, alignment, text areas and reading order
```

- **自然语言完整句优先**，先 P0 任务目标，再 P1 主体/构图/空间关系，最后 P2 视觉表现与 P3 辅助项；不堆砌互不关联的形容词。
- `spatial_relationships` 每项以十类关系之一开头（position / direction / distance / interaction / occlusion / containment / alignment / scale / depth / attachment）；多主体、复刻、融合、Anchor 系列必写，单主体可省。
- `reference_images` 沿用八角色枚举；Muse 的 `subject_reference` 人物映射 `identity_reference`、非人物映射 `object_reference`。`reference_usage` / `feature_transfer` / `feature_exclusion` 压制多图属性串扰。
- 系列一致性用 `anchor_set`（每项「资产N：…」）+ `preserve_constraints`；多轮修改用 `iteration_context`（每项一轮）+ 本轮 `target_changes` / `modification_scope`。
- 编辑与多轮必须同时给目标、保留、禁止、范围四项；缺 `modification_scope` 不渲染 edit。
- **无独立 negative 参数**：`negative_words` 渲染为自然语言 `Avoid:`，不是扩散模型的负向词字段。
- **API 参数不进 Prompt**：`size` / `n` / `output_format` / `previous_response_id` / `reasoning_strength` / 搜索与代码开关属于 Meta Model API，模板只输出可复制的自然语言指令。
- 已知限制：生成非确定、文字轮次间可能变化、多图融合会重排布局、系列一致性需固定参考资产、工具调用不等于 Prompt 参数。详见 `muse_image_rules.md` §10–11。

### 3.6 Nano Banana Pro（Gemini 3 Pro Image）

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

### 3.7 即梦 5.0（Seedream 5.0，字节跳动）

```text
主体：...
行为与环境：...
位置：...
主体比例：...
空间关系：...
构图：...
景别：...
机位：...
材质：...
光影：...
色彩：...
风格：...
画面文字（逐字准确，不增删）：...
参考：...
避免：...
```

- 组织顺序：先写主体与行为，再写环境、材质、光影、构图，最后落到风格；画面里有什么必须写到可复现的粒度。
- 画面文字单独一行，要求逐字准确、不增删；海报/招牌原文放 `text_content`，不要指望模型自动补字。
- 支持文生图、图生图复刻、编辑、多参考图与多图融合：`recreate` 锁定主体/构图/透视/光线，`edit` 只改指定项，`reference_guided` / `compose` 按图分配角色并写清允许迁移与禁止迁移。
- 参数（`model_id` / `resolution` / `aspect_ratio` / `watermark`）只进 `params` 块。公开资料对 API 模型 ID 与分辨率档位存在版本差异，**以控制台为准**；不确定项见 `references/jimeng_sources.md` 的「待人工确认」。

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

### 5.4 Seedance 2.5（字节跳动 / 火山方舟）

```text
基于参考素材生成一段 {duration} 秒、画幅 {aspect_ratio} 的{style}视频。

{story}

{storyboard}

参考素材：
{video_references}

使用策略：{reference_usage}
禁止迁移：{feature_exclusion}

镜头语言：{camera}
光影：{lighting}
色彩：{color}
环境氛围：{atmosphere}
声音：{audio}
旁白：{narration}
避免：{negative_words}
```

- **六种任务模式**（`kind`）：`storyboard`（文生视频）/ `image_to_video`（首帧）/ `first_last_frame`（首尾帧）/ `reference_to_video`（全模态参考）/ `video_edit`（编辑）/ `video_extend`（延长）。`task_type` 映射：`text_to_video`→`storyboard`、`image_to_video`、`first_last_frame`、`reference_to_video`、`video_editing`→`video_edit`、`video_extension`→`video_extend`。
- **互斥场景**：首帧、首尾帧、全模态参考三者只能选一；全模态参考下再用 `video_edit` / `video_extend` 表达编辑与延长。编辑需同时具备 `source_video` + `target_changes` + `modification_scope` + `preserve_constraints` + `forbidden_changes`；延长需 `source_video` + `extension_plan`。
- **素材角色**：`video_references` 每行 `素材N：reference_image|reference_video|reference_audio；用途；保留；禁止迁移`；编号从 1 连续，缺角色、多角色、跳号均退出 4。
- **参数边界**：`resolution`（480p/720p/1080p）/ `ratio` / `duration` / `generate_audio` / `watermark` / `draft` / `model_id` 只进 `params` 块。2.5 默认 720p、`duration` 为 -1（自动），范围内 4–30 秒；首帧/首尾帧/编辑/延长仅支持 `adaptive` 画幅。
- **声音**：`generate_audio` 默认开启，必须写 `audio` 设计；对白放双引号内；不需要声音时在 `params` 关闭并说明。
- Seedance 模板与 Sora / Runway / Veo **相互独立**，共享视频分镜与 `video_references` 底层契约；模型更新只改 `seedance.json` 与 `seedance_rules.md`。
- `negative_words` 在正文以「避免：」呈现；**API 是否生效取决于接入面**，与 Veo 一致需在交付说明中提示。

### 5.5 Kling 4.0（快手可灵）

```text
【素材职责】本片为文生视频，无需外部素材。
【整体设定】：...
【主体与动作】：...
【镜头语言】：...
【环境】：...
【光影】：...
【色彩】：...
【视觉风格】：...
【分段事件】：
...
【声音】：...
【画外音】：...
【对白】：...
【参考】：...
【避免】：...
```

- 官方建议按「素材职责 / 整体设定 / 主体与动作 / 镜头 / 环境光影 / 分段事件 / 声音」组织；模板用中文标签分节，空标签整行删除。
- 四种任务：`storyboard`（文生视频）/ `image_to_video`（图1 首帧）/ `first_last_frame`（图1 首帧 + 图2 尾帧）/ `reference_to_video`（多图参考，写「使用策略 / 禁止迁移」）。
- 官方不主张堆叠负向词，只渲染用户明确给出的 `negative_words`；`parameters` 只放 `model_id / duration / resolution / aspect_ratio / generate_audio`。
- 公开资料常见单段 3–30 秒、720p/1080p；模板默认 10 秒 / 1080p / 16:9 / 声音开。实际档位以控制台为准，见 `references/kling_sources.md` 的「待人工确认」。
- 提供 `shot_style`，可在实拍反推时显式点名输出；**不计入默认镜头反推模型集合**。

### 5.6 Hailuo 3（MiniMax H3）

```text
integrated_multimodal_description:
整体设定：...
主体与动作：...
分段事件：
...
镜头语言：...
环境氛围：...
光影：...
色彩：...
视觉风格：...
画外音：...
对白：...
参考：...
避免：...
overall_soundscape: ...
non_diegetic_music: 无额外配乐
```

- 固定以 `integrated_multimodal_description:` 开头；多镜头用 `[Shot N]` 标记，`shots` 反推时每个镜头自带 `[Shot N]` 前缀。
- 声音拆两段：`overall_soundscape`（环境声/动作声）与 `non_diegetic_music`。本 Skill 没有独立配乐字段，后者固定写「无额外配乐」，用户给的音乐描述写入 `audio`。
- 任务覆盖 `storyboard` / `image_to_video` / `first_last_frame` / `reference_to_video`；参数只进 `params` 块。
- 公开资料常见 4–15 秒、768P/1080P；模板默认 10 秒 / 1080P / 16:9 / 声音开。实际档位以控制台为准，见 `references/hailuo_sources.md` 的「待人工确认」。
- 提供 `shot_style`，可在实拍反推时显式点名输出；**不计入默认镜头反推模型集合**。

### 5.7 Vidu Q3（生数科技）

```text
主体：...
动作与情节：...
场景：...
分段事件：
...
镜头语言：...
光影：...
色彩：...
风格：...
参考主体：...
声音：...
对白：...
画外音：...
避免：...
```

- 以「主体 + 动作 + 场景 + 镜头语言 + 光影色彩 + 氛围」的短段落描述为主；模板按中文标签分节。
- 参考主体在官方写法中用 `[@名称]` 指代；本 Skill 由 `reference_note` / `video_references` 承载名称与用途，不保证平台端自动解析。
- 任务覆盖 `storyboard` / `image_to_video` / `first_last_frame` / `reference_to_video`；参数只进 `params` 块（`model_id` 默认 `viduq3-pro`）。
- 公开资料常见 1–16 秒、540p/720p/1080p，声音默认开启；模板默认 8 秒 / 1080p / 16:9。实际档位以控制台为准，见 `references/vidu_sources.md` 的「待人工确认」。
- 提供 `shot_style`，可在实拍反推时显式点名输出；**不计入默认镜头反推模型集合**。

## 6. 场景化默认模型

| 输出 | 默认 | 可选 |
|---|---|---|
| 每场景图片 | `mj`（V8.2）+ `sd`（3.5） | `flux2`、`gpt_image`、`muse_image`、`nano_banana` |
| 多主体/多图融合/系列一致 | `muse_image`（1.0） | `gpt_image`、`nano_banana` |
| 每场景视频 | `sora`（Sora 2） | `runway`、`veo3`、`seedance`、`kling`、`hailuo`、`vidu` |
| 首尾帧/参考素材重构/视频编辑与延长 | `seedance`（2.5） | `sora`（延长）、`veo3`（参考图） |

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
| Muse Image 1.0 | 无独立参数；`negative_words` 渲染为 `Avoid:` 自然语言 | 无（API 参数不进 Prompt） | 16:9 |
| Nano Banana Pro | 弱支持（改写为正向约束） | `params` 块 | 2K / 16:9 |
| 即梦 5.0（Seedream 5.0） | 弱支持（正文「避免：」自然语言） | `params` 块 | 2K / 16:9 / 水印关 |
| GPT-5.5 / Claude 5.5 | 不适用 | 无 | — |
| DeepSeek V4.1 Flash | 不适用 | 首行模型/思考档 | `deepseek-flash` / high |
| Seedance 2.5 | 弱支持（正文「避免：」，API 视接入面） | `params` 块 | 720p / 5s / adaptive / 声音开 / 水印关 |
| Sora 2 | 不适用（用正向描述替代） | `params` 块 | 12s / 16:9 / 1280x720 |
| Runway Gen-4.5 | 不适用 | `params` 块 | 10s / 16:9 / 1280x720 |
| Veo 3.1 | 视接入面而定 | `params` 块 | 8s / 16:9 / 1080p |
| Kling 4.0 | 官方不主推负向（只渲染显式 `negative_words`） | `params` 块 | 10s / 16:9 / 1080p / 声音开 |
| Hailuo 3（MiniMax H3） | 同上（正文「避免：」自然语言） | `params` 块 | 10s / 16:9 / 1080P / 声音开 |
| Vidu Q3 | 同上（正文「避免：」自然语言） | `params` 块 | 8s / 16:9 / 1080p / 声音开 |

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
3. 可选字段放 `optional_fields`，条件渲染放 `kind_requires`，默认参数放 `default_params`；规格书式排版可加 `"clean_empty_label_lines": true` 删除空标签整行。
4. 运行 `python tools/verify.py`，模板元数据、别名冲突、渲染清理会被自动检查。
5. 同步更新本文件第 2 节注册表；不要改编译器代码。
