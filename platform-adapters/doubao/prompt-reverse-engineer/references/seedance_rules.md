# Seedance 2.5 编译规则

> 适用模型：字节跳动 / 火山方舟（Ark）Doubao Seedance 2.5 系列（本 Skill 内模型键 `seedance`）。
> 独立规则文件：不与其他视频模型共用模板。可共用扁平 `semantic_analysis` 契约，但任务模式、素材角色、参数边界与审查项只服务 Seedance。
> 最后核对：2026-11-15。

## 0. 资料边界（先读）

| 类别 | 内容 | 依据 |
| --- | --- | --- |
| 官方事实 | 模型系列与场景、输入素材角色与数量、resolution/ratio/duration 等参数、时长与格式限制、互斥场景、提示词语言与字数建议、真人人脸限制 | 火山方舟《视频生成 API》官方文档 |
| 本 Skill 设计 | 视频逆向维度、六种任务模式、字段契约、六段式编译、P0–P3、六维评分、Seedance 审查清单 | 针对本仓库现有契约的设计建议，非字节官方 Prompt 规范 |

Seedance 没有官方规定的“标准 Prompt 格式”。本 Skill 输出**可直接粘贴的自然语言分镜指令**，不把内部 JSON 直接发给模型；`resolution`、`ratio`、`duration` 等 API 参数只以键值形式放 `params` 块，不写参数键值或后缀进正文；正文可以用自然语言交代时长与画幅意图。

## 1. 与其他视频模型的分工

| 维度 | Sora 2 / Runway / Veo 3 | Seedance 2.5 |
| --- | --- | --- |
| 模板文件 | `assets/templates/sora2.json` 等 | `assets/templates/seedance.json` |
| 规则文件 | `video_rules.md` 对应小节 | 本文件 |
| 任务组织 | 单段视频描述 + 参考图 | 六种模式，按官方四类场景 + 编辑/延长拆分 |
| 素材角色 | `参考图N` | `素材N` + `reference_image` / `reference_video` / `reference_audio` |
| 首尾帧 | 非统一契约 | 独立字段 `first_frame` / `last_frame`，与全模态参考互斥 |
| 音频 | 部分模型原生音频 | `generate_audio` 默认 `true`，声音写进正文，开关进 params |
| 时长 | 各模型固定档位 | 2.5 为 4–30 秒或 `-1` 智能选择 |

原则：**统一分析、差异化生成**。修改 Seedance 模板不得改动其他视频模板；共享层只有扁平 `semantic_analysis` 字段名与不确定性标签。

## 2. 视频逆向分析维度

| 维度 | 提取内容 | 主要字段 |
| --- | --- | --- |
| 叙事 | 一句话故事、起因、动作、结果、情绪走向 | `story` |
| 时间结构 | 镜头数、每镜起止、节奏、转场、总时长 | `storyboard`、`duration` |
| 主体 | 人物/物体外观、数量、动作、朝向、状态变化 | `character`、`story` |
| 镜头语言 | 景别、机位、运镜、焦点、构图 | `camera`、`shot_type`、`camera_angle` |
| 光影与色彩 | 主光、时段、色温、对比、色调 | `lighting`、`color` |
| 环境氛围 | 地点、天气、空间、声音环境 | `atmosphere` |
| 风格 | 写实/动画/广告/电影感、质感、参考流派 | `style` |
| 声音 | 对白、旁白、音效、音乐、静音设计 | `audio`、`dialogue`、`narration` |
| 素材 | 首帧、尾帧、参考图/视频/音频及用途 | `first_frame`、`last_frame`、`video_references` |
| 约束 | 禁止项、保留项、修改边界 | `negative_words`、`preserve_constraints`、`forbidden_changes` |

## 3. 素材角色契约

官方在 `content` 数组中用 `role` 标记素材用途，本 Skill 映射为扁平字段：

| 官方 role | 本 Skill 字段 | 说明 |
| --- | --- | --- |
| `first_frame` | `first_frame`（字符串） | 首帧图，图生视频 / 首尾帧 |
| `last_frame` | `last_frame`（字符串） | 尾帧图，仅首尾帧 |
| `reference_image` | `video_references` | 参考图 |
| `reference_video` | `video_references` | 参考视频 |
| `reference_audio` | `video_references` | 参考音频 |

`video_references` 每项格式固定：

```
素材1：reference_image；用途：锁定主角面部与服装；保留：发型、红色外套；禁止迁移：原图背景与光线
素材2：reference_video；用途：参考运镜节奏；保留：推镜速度；禁止迁移：原片人物与场景
素材3：reference_audio；用途：参考环境声；保留：雨声密度；禁止迁移：原片对白
```

- 必须以 `素材N：` 开头，N 为正整数，不得重复。
- 每项只能出现一个角色枚举；出现多个 → 退出 4。
- 缺少编号或角色 → 退出 4。
- `reference_usage` 写整体策略，`feature_exclusion` 写全局禁止迁移；两者与逐项说明互补，不重复。

## 4. 任务模式与编译

官方定义三类互斥输入场景：图生视频-首帧、图生视频-首尾帧、全模态参考生视频（含参考/编辑/延长子任务），另有文生视频。本 Skill 拆成六种：

| task_type | 渲染 kind | 对应官方场景 | 额外必填 |
| --- | --- | --- | --- |
| `text_to_video` | `storyboard` | 文生视频 | `story` |
| `image_to_video` | `image_to_video` | 图生视频-首帧 | `first_frame`、`story` |
| `first_last_frame` | `first_last_frame` | 图生视频-首尾帧 | `first_frame`、`last_frame`、`story` |
| `reference_to_video` | `reference_to_video` | 全模态参考生视频（reference） | `video_references`、`story` |
| `video_editing` | `video_edit` | 全模态参考生视频（edit） | `source_video`、`target_changes`、`preserve_constraints`、`forbidden_changes`、`modification_scope` |
| `video_extension` | `video_extend` | 全模态参考生视频（extend） | `source_video`、`extension_plan` |

行为：
- 只给 `task_type`、不指定 `--kind` 时，非 strict 模式渲染该模型全部 kind；显式 `--kind` 走对应模式。
- `task_type` 与 `--kind` 映射不一致 → 退出 4。
- `image_to_video` / `first_last_frame` 同时给 `video_references` → 退出 4（官方互斥）。
- `reference_to_video` 同时给 `first_frame` / `last_frame` → 退出 4；严格首尾帧请改用 `first_last_frame`。
- 全模态参考可通过提示词把某张参考图指定为首帧/尾帧，但官方建议：需要严格一致时仍走首尾帧场景。

### 4.1 六段式内部结构

1. Task：生成 / 首帧 / 首尾帧 / 参考 / 编辑 / 延长。
2. Subject & Story：主体、动作、事件、结果。
3. Temporal Structure：逐镜头景别、运镜、动作、时长、转场。
4. Visual Style：光影、色彩、环境、风格。
5. References：每个素材的角色、用途、保留与禁止迁移。
6. Audio & Constraints：对白、旁白、音效、音乐、禁止项、保留项。

### 4.2 P0–P3 优先级

| 级别 | 内容 | 冲突时 |
| --- | --- | --- |
| P0 | 任务目标、主体动作、素材角色、输出时长 | 最高 |
| P1 | 分镜顺序、镜头语言、关键转场 | 高于 P2/P3 |
| P2 | 光影、色彩、风格、环境细节 | 让位于 P0/P1 |
| P3 | 次要装饰、背景细节、氛围修饰 | 可舍弃 |

## 5. 分镜写法

多镜头任务必须逐镜头写，建议每镜一行：

```
镜头1（0–2秒）：中景，固定机位，雨夜街头，主角撑伞站立，雨水沿伞骨滴落。
镜头2（2–5秒）：推镜至近景，主角抬头看向霓虹招牌，眼神由疲惫转为惊讶。
```

规则：
- 镜头数量与总时长匹配：2.5 秒级镜头通常 2–3 秒，5 秒视频不宜塞入 6 个以上镜头。
- 每镜只写一个主要动作，避免“同时、一边……一边……”堆叠。
- 明确转场（硬切、叠化、甩镜），不写“自然过渡”这类空话。
- 单镜头任务也建议写清起始状态与结束状态。

## 6. 首帧与首尾帧

- `first_frame`：写“以图1为首帧”，并描述首帧之后的动作与镜头变化；不要重复描述首帧图里已经可见的静态细节。
- `last_frame`：写“以图2为尾帧”，并描述如何从首帧过渡到尾帧；官方说明两图宽高比不一致时以首帧为主，尾图自动居中裁剪。
- 2.5 的首帧/首尾帧任务 `ratio` 只能为 `adaptive`，输出跟随首帧图。
- 首帧图建议只出现一个明确主体；多主体或含文字的首帧容易在运动中失真。

## 7. 视频编辑与延长

编辑任务四件事与图片编辑同构：

- `source_video`：待编辑视频（用 `素材N：reference_video` 描述）。
- `target_changes`：本轮要改什么。
- `modification_scope`：允许改动的范围（时间区间、画面区域、对象）。
- `preserve_constraints` / `forbidden_changes`：必须保留 / 禁止改动。

官方限制（2.5，`omni_reference_task_type=edit`）：
- `content` 至少一个 `reference_video`。
- 待编辑视频时长 4–30 秒。
- `ratio` 只能 `adaptive`；`duration` 只能 `-1`。
- 平台按提示词意图选定待编辑视频，输出宽高比与时长跟随源视频。

延长任务（`extend`）：
- 至少一个 `reference_video`，`ratio` 只能 `adaptive`。
- `extension_plan` 写明向前还是向后延长、延长多久、新增内容如何衔接。
- 不写“继续播放”这类空指令，要写新增事件与镜头。

## 8. 声音与对白

- `generate_audio` 默认 `true`：不写声音设计，模型也会自动配人声、音效与音乐，容易与意图不符。
- 对白建议放双引号内，官方明确这样有助于音频生成，例如：男人说：“你先走，我马上到。”
- 一句对白控制在一句话内；多人对话标明说话人。
- 需要静音时显式写“全程无对白、无音乐，仅保留雨声”。
- 参考音频写入 `video_references`，用途写“参考音色/节奏/环境声”，并写禁止迁移项。

## 9. API 参数边界

以下参数只以 `params` 键值块输出，禁止写成 `key=value` 指令或 `--rs/--rt/--dur` 后缀；正文可用自然语言交代「多长、什么画幅」作为创作意图（如「一段 10 秒、画幅 16:9 的片子」），但不得伪装成 API 参数：

`model`、`resolution`、`ratio`、`duration`、`frames`、`generate_audio`、`watermark`、`output_format`、`seed`、`camera_fixed`、`return_last_frame`、`draft`、`service_tier`、`callback_url`、`execution_expires_after`。

官方支持在提示词后追加弱校验后缀 `--rs`（分辨率）、`--rt`（宽高比）、`--dur`（时长）、`--seed`、`--cf`（固定摄像头）、`--wm`（水印）。本 Skill 不采用后缀写法：参数集中放在 `params` 块，避免与正文混杂、便于程序校验。

### 9.1 Seedance 2.5 关键取值

| 参数 | 取值 | 备注 |
| --- | --- | --- |
| `resolution` | `480p` / `720p` / `1080p` | 默认 `720p`；`draft=true` 时只能 480p |
| `ratio` | `16:9` / `4:3` / `1:1` / `3:4` / `9:16` / `21:9` / `adaptive` | 首帧/首尾帧/编辑/延长只能 `adaptive` |
| `duration` | 4–30 或 `-1` | 默认 `-1`；编辑任务只能 `-1` |
| `generate_audio` | `true` / `false` | 默认 `true` |
| `watermark` | `true` / `false` | 默认 `false` |
| `output_format` | `mp4` / `mov` | 默认 `mp4`；2.5 支持 |
| `draft` | `true` / `false` | 仅 2.5；样片 480p，任务 ID 有效期 14 天 |
| `frames` | 29–289，满足 `25+4n` | 仅 1.0 pro / pro fast；优先于 duration |
| `seed` / `camera_fixed` / `service_tier` | — | 仅 1.0 系列 |

## 10. 评分与审查

### 10.1 Prompt 质量评分（六维，合计 100）

| 维度 | 权重 | 评价内容 |
| --- | --- | --- |
| 任务与叙事 | 20 | 目标、主体、事件是否明确 |
| 时间结构 | 20 | 分镜、节奏、转场、时长 |
| 镜头语言 | 15 | 景别、机位、运镜 |
| 视觉表现 | 15 | 光影、色彩、风格、氛围 |
| 素材管理 | 15 | 首尾帧/参考素材角色与迁移边界 |
| 声音与约束 | 15 | 对白、音效、禁止项、保留项 |

该评分评价**逆向分析与 Prompt 质量**，不代表实际生成质量。真实效果需另测：主体一致性、动作自然度、镜头稳定性、首尾帧贴合度、参考迁移准确度、音画同步、编辑范围准确度。

### 10.2 Seedance 审查清单（输出末尾，不参与总分）

编译 `seedance` 时附带六项：

1. 核心信息：任务模式与必填字段是否齐全。
2. 任务场景：首帧 / 首尾帧 / 全模态参考是否互斥且输入合法。
3. 时间结构：分镜与 duration 是否匹配（2.5 为 4–30 秒或 -1）。
4. 素材角色：编号、角色、用途、禁止迁移是否完整。
5. 声音与对白：`generate_audio` 默认开启时是否写了声音设计。
6. 参数边界：API 参数是否只出现在 `params` 块。

清单只提示，不改变分数、不影响退出码。

## 11. 已知限制

- **非确定性**：相同 Prompt 与 seed 也不保证完全一致；seed 仅 1.0 系列支持。
- **参考一致性有限**：参考素材是引导而非像素复制；跨镜头人物一致性需固定参考图并重复关键特征。
- **真人人脸限制**：2.5 / 2.0 系列不支持直接上传含真人人脸的参考图/视频；仅可使用本账号近 30 天内由 Seedance 生成的含人脸视频做二次创作。
- **互斥场景**：首帧、首尾帧、全模态参考不可混用；混用会异步报错。
- **编辑任务约束**：时长 4–30 秒、比例 `adaptive`、`duration=-1`，不满足会报错。
- **提示词长度**：中文建议 ≤500 字，英文建议 ≤1000 词；超出易丢细节。
- **语言**：中英文全系列支持；2.5 另支持西/印尼/葡/日/马来/泰/阿/越/韩，2.0 另支持西/印尼/葡/日。

## 12. 官方 API 参数（仅 API 层）

| 参数 | 类型 | 说明 |
| --- | --- | --- |
| `model` | string | 模型 ID，例如 `doubao-seedance-2-5-260628` |
| `content` | array | 文本、图片、视频、音频、样片任务 |
| `resolution` | string | 480p / 720p / 1080p |
| `ratio` | string | 宽高比或 adaptive |
| `duration` | integer | 4–30 或 -1 |
| `frames` | integer | 仅 1.0 系列 |
| `generate_audio` | boolean | 默认 true |
| `watermark` | boolean | 默认 false |
| `output_format` | string | mp4 / mov，2.5 支持 |
| `seed` | integer | 仅 1.0 系列 |
| `camera_fixed` | boolean | 仅 1.0 系列，参考图场景不支持 |
| `return_last_frame` | boolean | 返回尾帧，便于接续生成 |
| `draft` | boolean | 2.5 样片模式 |
| `service_tier` | string | 仅 1.0 系列 |
| `callback_url` | string | 异步回调 |
| `execution_expires_after` | integer | 任务超时 |

## 13. 字段速查

| 字段 | 类型 | 用于 |
| --- | --- | --- |
| `story` | string | 一句话故事与主体动作 |
| `storyboard` | string | 逐镜头分镜 |
| `character` | string | 人物/主体外观与状态 |
| `camera` | string | 景别、机位、运镜 |
| `lighting` / `color` / `atmosphere` / `style` | string | 视觉表现 |
| `audio` / `dialogue` / `narration` | string | 音效、对白、旁白 |
| `first_frame` / `last_frame` | string | 首帧 / 尾帧描述 |
| `source_video` | string | 待编辑/待延长视频 |
| `video_references` | string[] | `素材N：role；用途；保留；禁止迁移` |
| `reference_usage` | string | 参考素材整体策略 |
| `feature_exclusion` | string | 全局禁止迁移 |
| `target_changes` / `preserve_constraints` / `forbidden_changes` | string[] | 编辑目标与边界 |
| `modification_scope` | string[] | 修改范围 |
| `extension_plan` | string | 延长方案 |
| `negative_words` | string | 禁止项 |
| `uncertainty` | string[] | `observed:` / `inferred:` / `unknown:`；`unknown` 不进正文 |

## 14. 参考来源

- 火山方舟《视频生成 API》— 模型系列、任务场景、content 素材角色、参数表、限制。
- 火山方舟 Seedance 2.5 样片模式 — draft 参数与任务 ID 有效期。
- 火山方舟《图片裁剪规则》— 宽高比不一致时的居中裁剪。

官方能力与 API 行为以火山方舟文档为准；六种任务模式、字段契约、六段式编译、评分与审查清单是本 Skill 的设计，不是字节官方 Prompt 规范。
