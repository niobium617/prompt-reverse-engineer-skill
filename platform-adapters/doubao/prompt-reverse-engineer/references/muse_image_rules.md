# Muse Image 1.0 编译规则

> 适用模型：Meta Superintelligence Labs `muse-image-1.0`（本 Skill 内模型键 `muse_image`）。
> 独立规则文件：不与其他模型共用模板。可共用 `semantic_analysis` 扁平契约与 `reference_images` 角色枚举，但本文件的编译策略、优先级与审查项只服务 Muse Image。
> 最后核对：2026-11-15。

## 0. 资料边界（先读）

本文件把内容分成两类，写作与校验时不得混用：

| 类别 | 内容 | 依据 |
| --- | --- | --- |
| 官方事实 | 模型标识、六项能力、多轮编辑、参考图输入、Anchor Composition 工作流、API 参数、已知限制 | Meta 官方发布与 Model API / Cookbook 文档 |
| 本 Skill 设计 | 八维分析、十类空间关系、六段式编译、P0–P3 优先级、扁平字段、评分与审查清单 | 针对本仓库现有契约的设计建议，非 Meta 官方 Prompt 规范 |

Muse Image 没有官方规定的“标准 Prompt 格式”。本 Skill 输出的是**自然语言完整句为主、结构关系显式化**的指令，不把内部 JSON 直接发给模型。

同名区分：Google Research 2023 年的 “Muse” 是文本到图像的研究模型，与本文件讨论的 Meta Muse Image 不是同一模型，资料不得互引。

## 1. 与 GPT Image 的分工

| 维度 | GPT Image 2.5 | Muse Image 1.0 |
| --- | --- | --- |
| 模板文件 | `assets/templates/gpt_image.json` | `assets/templates/muse_image.json` |
| 规则文件 | `image_rules.md` + `prompt_framework.md` | 本文件 |
| 任务用途 | 五种（prompt / recreate / edit / reference_guided / compose） | 八种（前五种 + anchored / conversational / text_layout） |
| 指令组织 | 规格表式短句，字段标签清晰 | 自然语言完整句，先目标后关系 |
| 参考图 | 角色 + 编号 | 角色 + 编号 + 使用方式 + 允许/禁止迁移 |
| 系列一致性 | 参考图约束 | Anchor Set 固定资产 |
| 多轮修改 | 通用编辑 | `iteration_context` 显式继承前轮 |
| 负面词 | 支持自然语言禁止项 | 无独立 negative 字段，用 “Avoid:” 自然语言表达 |
| API 参数 | 尺寸/质量等 | size/n/reasoning_strength/搜索与代码开关，**不写入 Prompt 正文** |

原则：**统一分析、差异化生成**。修改 Muse 模板时不得改动 GPT Image 模板；反之亦然。两者的共享层只有扁平 `semantic_analysis` 字段名和参考图角色枚举。

## 2. 八维视觉分析

逆向图片时按以下八维提取，最终落到扁平字段：

| 维度 | 提取内容 | 主要字段 |
| --- | --- | --- |
| 主体 | 类别、数量、外观、姿态、动作、朝向、位置、比例、识别特征 | `subject`、`subject_position`、`subject_scale` |
| 构图 | 景别、视角、占比、画幅、视觉焦点、留白、对称、构图方式 | `composition`、`shot_type`、`camera_angle` |
| 空间关系 | 位置、朝向、距离、交互、遮挡、包含、对齐、比例、景深、附着 | `spatial`、`spatial_relationships` |
| 光影 | 主光、补光、轮廓光、方向、强度、阴影、反射、环境光、色温 | `lighting` |
| 色彩 | 主色、辅色、强调色、色温、饱和度、明暗对比、色彩分布 | `color` |
| 材质 | 类型、纹理、粗糙度、反射、透明度、表面状态、磨损 | `material` |
| 风格 | 艺术风格、渲染方式、写实度、线条、细节密度、色彩语言、氛围 | `style` |
| 文字与布局 | 文字内容、位置、字体、字号层级、对齐、文本区、图文关系、信息层级 | `text_content`、`text_layout` |

多主体图片必须逐个主体描述，不能合并成“两个不同服装的人物”。主体属性不得串扰。

## 3. 空间关系（Muse 重点）

`spatial_relationships` 是字符串数组，每项一条可验证的关系，建议以关系类型开头。十类：

| 类型 | 说明 | 示例 |
| --- | --- | --- |
| position | 位置 | `position：机器人位于画面中央偏左` |
| direction | 朝向 | `direction：人物面向右侧的汽车` |
| distance | 距离 | `distance：前景人物与背景建筑相距约一个街区` |
| interaction | 交互 | `interaction：右手握住剑柄` |
| occlusion | 遮挡 | `occlusion：桌角遮住人物左腿` |
| containment | 包含 | `containment：钥匙在玻璃瓶内` |
| alignment | 对齐 | `alignment：三块招牌沿水平线对齐` |
| scale | 尺寸比例 | `scale：人物高度约为门框的三分之二` |
| depth | 景深 | `depth：人物清晰，远处建筑轻微虚化` |
| attachment | 附着 | `attachment：徽章固定在左胸位置` |

单主体、无交互的图片可以为空；多主体、多参考图融合、复刻、Anchor 系列应尽量给出。`spatial` 保留一句整体空间概览，`spatial_relationships` 放逐条关系，二者不要重复。

## 4. 任务模式与编译

`task_type` 与前五种用途和 GPT Image 共用枚举，后三种为 Muse 扩展：

| task_type | 渲染 kind | 用途 | 额外必填 |
| --- | --- | --- | --- |
| `text_to_image` | prompt | 文生图 | — |
| `image_recreation` | recreate | 高保真复刻 | `subject_position` |
| `image_editing` | edit | 指定修改 | `modification_scope` |
| `reference_guided` | reference_guided | 单图/少图角色引导 | `reference_images` |
| `image_composition` | compose | 多图融合 | `reference_images` |
| `anchored_composition` | anchored_composition | 系列一致性 | `reference_images`、`anchor_set`、`preserve_constraints` |
| `conversational_refinement` | conversational_refinement | 多轮局部修改 | `iteration_context` |
| `text_layout` | text_layout | 海报/信息图表 | `text_content`、`text_layout` |

行为：
- 只给 `task_type`、不指定 `--kind` 时，非 strict 模式渲染该模型全部 kind；Muse 自身会按 `task_type` 选 kind 时优先对应项。
- 显式 `--kind` 且模型无该 kind → 退出 1。
- `task_type` 与 `--kind` 映射不一致 → 退出 4。

### 4.1 六段式内部结构

编译时按固定顺序组织，最终不必保留六个标题：

1. Task：生成 / 复刻 / 编辑 / 融合 / 系列 / 多轮 / 文字版式。
2. Main Subjects：主体及关键特征、数量、朝向。
3. Composition & Relationships：位置、动作、距离、遮挡、透视。
4. Visual Style：光影、色彩、材质、风格、氛围。
5. References：每张参考图的角色与使用方式。
6. Constraints：保留项、禁止项、修改边界、最终要求。

### 4.2 P0–P3 优先级

| 级别 | 内容 | 冲突时 |
| --- | --- | --- |
| P0 | 任务目标、最终输出 | 最高，不得被风格词覆盖 |
| P1 | 主体、构图、空间关系、数量、动作 | 高于 P2/P3 |
| P2 | 光影、色彩、材质、风格、细节 | 让位于 P0/P1 |
| P3 | 背景装饰、次要元素、纹理、氛围 | 可舍弃 |

自然语言完整句优先，不堆砌互不关联的形容词。复杂多主体、多参考图、信息图表可用结构化短句，但发送给模型前仍应保持可读的自然语言，不把分析用 JSON 直接当 Prompt。

## 5. 编辑任务四件事

编辑与多轮修改建议同时给出：

- `target_changes`：本轮要改什么（数组）。
- `preserve_constraints`：必须保留什么（数组）。
- `forbidden_changes`：禁止改什么（数组）。
- `modification_scope`：允许改动的地理/结构范围（字符串数组），例如 `["仅替换服装区域，不改动头部、手部与背景"]`。

顺序：先目标，再保留，最后边界。硬性门槛是编辑任务的 `modification_scope` 与多轮任务的 `iteration_context`（`kind_requires` 校验失败即退出 4）；其余项缺失不阻断渲染，但会在 Muse 审查清单里标为「待复核」。

## 6. 参考图角色契约

共用八角色枚举，不新增第九种：

`edit_target`、`identity_reference`、`pose_reference`、`clothing_reference`、`style_reference`、`composition_reference`、`background_reference`、`object_reference`。

Muse 资料中的 `subject_reference` 按内容映射：
- 人物主体 → `identity_reference`
- 非人物主体/道具 → `object_reference`

每项格式固定：`图N：<role>；用途：…；保留：…；禁止迁移：…`
- 必须以 `图N：` 开头，N 为正整数。
- 每项只能出现一个角色；编号不得重复；角色不得重复（除非任务确实需要同角色多图，此时用不同编号并说明差异）。
- 违规 → 退出 4。

`reference_usage`、`feature_transfer`、`feature_exclusion` 与 `reference_images` 配合：
- `reference_usage`：整体使用策略，例如“图1 只取面部与发型，图2 只取建筑结构与环境光”。
- `feature_transfer`：允许迁移的特征。
- `feature_exclusion`：禁止迁移的特征，用于压制属性串扰（如“人物参考图不得带入原背景与光照”）。

模板保留标签行 `Reference roles — each image is used only as described:`，即使内容为空也不会被清理；但 `kind_requires` 会先阻止空参考图进入渲染。

## 7. Anchor Composition

适用：连续漫画、分镜、人物系列海报、产品系列图、同角色不同姿势、同场景不同镜头。

`anchor_set` 为字符串数组，每项一个固定资产，建议格式：

```
资产1：character_reference；参考图：图1；保留：人物身份、面部、发型、体型
资产2：environment_reference；参考图：图2；保留：建筑结构、空间布局、环境光方向
资产3：style_reference；参考图：图3；保留：画风、线条、色彩语言
```

规则：
- 每次生成继续使用同一组参考图，不重新描述并重生成资产。
- 人物与环境分别建参考资产。
- 新图只改变未列入 `preserve_constraints` 的部分。
- `anchor_set` 每项按换行渲染，便于模型逐项读取。

## 8. Conversational Refinement

`iteration_context` 为字符串数组，记录本轮开始前的状态，建议每项一轮：

```
第1轮：已生成雨夜机甲机器人；已确认冷蓝主光、湿金属反射、低机位
第2轮：背景已改为废弃工厂；人物外观与姿态保持不变
本轮：只增强眼部蓝光与雨水反射，不改构图、装甲结构、人物位置
```

规则：
- 继承前轮已确认的视觉约束，不复述无关内容。
- 只描述本轮修改，`target_changes` 与 `modification_scope` 必须给。
- 已确认的主体特征不得无故改变。
- 若修改波及整体构图，应在 `modification_scope` 说明“允许重整构图”，而不是偷偷重写全部描述。

## 9. 评分与审查

### 9.1 Prompt 质量评分（六维，合计 100）

| 维度 | 权重 | 评价内容 |
| --- | --- | --- |
| 主体描述 | 20 | 外观、动作、数量 |
| 空间关系 | 20 | 位置、距离、遮挡、透视 |
| 构图布局 | 15 | 画面组织与视觉层级 |
| 视觉表现 | 15 | 光影、色彩、材质 |
| 参考图管理 | 15 | 角色与迁移边界 |
| 指令约束 | 15 | 修改边界与保留条件 |

该评分评价**逆向分析与 Prompt 质量**，不代表实际出图质量。真实效果需另测：主体相似度、空间关系准确度、构图还原度、多图融合一致性、文字准确度、修改范围准确度、系列角色一致性。

### 9.2 Muse 审查清单（输出末尾，不参与总分）

编译 `muse_image` 时附带六项：

1. 核心信息：任务目标、主体、必填字段是否齐全。
2. 空间关系：多主体任务是否逐条给出位置/朝向/遮挡等关系。
3. 参考图角色：编号、角色、使用方式、禁止迁移是否完整。
4. 编辑边界：修改目标、保留项、禁止项、范围是否齐全。
5. 连续一致性：Anchor 资产或多轮状态是否显式继承。
6. 文字版式：有画内文字时是否给出版式与层级。

清单只提示，不改变分数、不影响退出码。

## 10. 已知限制

- **非确定性**：相同 Prompt 不保证同一张图；不能凭一次结果判定 Prompt 对错。
- **文字不稳**：可生成可读文字，但轮次间可能变化；海报/图表应缩短文字、核对数字与标点、生成后检查。
- **多图融合会重排布局**：不保证像素级复制；要求精确保留构图时，必须显式写主体位置、比例、相对关系与不可变部分。
- **参考一致性有限**：重复描述不等于完全一致；优先固定人物/场景参考图并在系列中复用。
- **工具调用不是 Prompt 参数**：搜索、代码、自我优化由模型自行决定；不得虚构控制参数，也不要求用户在普通 Prompt 中写内部推理步骤。

## 11. API 与 Prompt 的边界

Meta Model API 参数（仅 API 层，禁止写入 Prompt 正文）：

`model`、`prompt`、`image`、`size`、`n`、`output_format`、`previous_response_id`、`reasoning_strength`、`enable_image_search`、`enable_web_search`、`enable_shell`。

- `size` 主要控制宽高比，不保证精确像素尺寸。
- `reasoning_strength` 取 `high` / `low`。
- 多轮连续编辑与参考图输入走 Responses API；Prompt 内只写视觉意图，不写 `previous_response_id` 等字段名。
- 本 Skill 当前只输出可复制的自然语言 Prompt；若未来增加 API 适配，应另建参数模板，不复用本文件。

## 12. 专项 Benchmark（建议）

36 组，A/B 对照：A 用通用图片模板，B 用本文件规则；同模型版本、同输入、同生成条件，人工盲评 + 图像指标。

| 类型 | 数量 | 目标 |
| --- | --- | --- |
| 单主体复刻 | 6 | 主体与风格还原 |
| 多主体空间关系 | 6 | 数量、位置、动作 |
| 局部编辑 | 6 | 边界与保留约束 |
| 多图参考融合 | 6 | 角色与特征迁移 |
| 系列图片 | 6 | Anchor 一致性 |
| 海报与信息图表 | 6 | 文字与布局 |

重点观察：复杂空间关系是否改善、多图属性串扰是否减少、系列一致性是否提高、编辑非目标区域是否更稳、文字版式是否更准。

## 13. 字段速查

| 字段 | 类型 | 用于 |
| --- | --- | --- |
| `subject` | string | 主体描述 |
| `subject_position` / `subject_scale` | string | 位置、占比 |
| `spatial` | string | 整体空间概览 |
| `spatial_relationships` | string[] | 十类逐条关系 |
| `composition` / `shot_type` / `camera_angle` | string | 构图与机位 |
| `style` / `lighting` / `color` / `material` | string | 视觉表现 |
| `text_content` | string | 画内文字原文 |
| `text_layout` | string | 字体、层级、对齐、文本区、阅读顺序 |
| `negative_words` | string | 自然语言禁止项（非独立 negative 参数） |
| `reference_images` | string[] | `图N：role；用途；保留；禁止迁移` |
| `reference_usage` | string[] | 参考图整体使用策略 |
| `feature_transfer` | string[] | 允许迁移 |
| `feature_exclusion` | string[] | 禁止迁移 |
| `target_changes` | string[] | 编辑目标 |
| `target_style` | string | 目标样式补充 |
| `preserve_constraints` | string[] | 保留项 |
| `forbidden_changes` | string[] | 禁止项 |
| `modification_scope` | string[] | 修改范围 |
| `anchor_set` | string[] | Anchor 资产表 |
| `iteration_context` | string[] | 多轮状态 |
| `uncertainty` | string[] | `observed:` / `inferred:` / `unknown:`；`unknown` 不进正文 |

## 14. 参考来源

- Meta：Introducing Muse Image and Muse Video — 模型定位、Agentic 生图、搜索与代码辅助。
- Meta Model API：Image Generation with Muse Image — 调用、连续编辑、参考图、参数。
- Meta：Build with Muse Image — 生成、编辑、多图融合、Anchor Composition。
- Meta Muse Image Cookbook — 开发示例。
- Google Research：Muse 2023 — 仅用于区分同名研究模型。

官方能力与 API 行为以 Meta 资料为准；八维分析、任务模式、字段契约、评分与审查清单是本 Skill 的设计，不是 Meta 官方 Prompt 规范。
