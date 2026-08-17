---
name: prompt-reverse-engineer
description: "多模态 Prompt 逆向工程技能。当用户提供一段文本、一张图片或一个视频，并要求逆向/复刻/拆解其创作逻辑、还原为可复用 Prompt 时激活。触发词（中英双语）：逆向 prompt、反向生成、复刻这个文案/风格/图片/视频、把这段文字/这张图/这个视频变成 prompt、拆解文案/镜头/分镜、prompt 优化；prompt reverse engineering、reverse engineer this text/image/video、recreate this style as a prompt。输出适配 Midjourney / Stable Diffusion / GPT-4·Claude / Sora·Runway 多模型格式，附百分制质量评分。"
---

# Prompt 逆向工程多模态生成 Skill

把任何优秀作品（文本/图片/视频）→ 逆向拆解 → 还原为可复用、可修改的专业 Prompt。

## 1. 触发条件

用户提供了具体内容（粘贴的文本、图片、视频文件路径或 URL），并表达「逆向 / 复刻 / 拆解 / 变成 prompt / 优化 prompt」意图时执行本技能。用户提供**剧本 / 小说 / 文章等叙事文本**并要求「生成对应场景的图片/视频提示词 / 把故事变成画面 / 逐场景出图」时，按第 2 节叙事文本分支执行。纯闲聊或与内容逆向无关的任务不激活。

## 2. 核心工作流（六步，严格按序）

**叙事文本分支**：若输入为剧本/小说/文章且用户要求场景化生成，改走：`analyze_scenes.py` 获取场景切分信号 → Agent 通读全文提炼全局基调（summary/characters）并逐场景完成七段与分镜语义分析（契约见 `references/prompt_framework.md` 2.5 节，写入 story JSON）→ `prompt_compiler.py scenes` 编译（每场景图片默认 MJ/SD + 视频默认 Sora）→ 逐场景评分 → 按第 4 节场景化格式输出。安全过滤与降级规则与常规流程一致。

1. **识别**：判定输入模态（text / image / video）与来源（本地路径 / URL / 直接粘贴）。粘贴的文本写入技能目录外的临时文件；URL 可直接交给脚本下载；检查输入可读，失败按第 5 节处理。
2. **分析**：运行 `scripts/` 下对应脚本获取 `local_features` 确定性信号（脚本用法见第 6 节）。**图像/视频必须 Read 关键帧或原图**，用多模态能力完成语义分析（主体/风格/结构等）。
3. **推理**：按 `references/prompt_framework.md` 第二节的规范字段表，把语义结论整理为 `semantic_analysis` 对象写入 JSON 文件（示例：`tools/fixtures/semantic_*.json`，字段名必须与契约一致）。
4. **编译**：运行 `prompt_compiler.py all --analysis <json> --models <目标> --dims <评分json>`。用户未指定模型时用默认值（MJ + GPT-4 双版本）。
5. **评分**：按 `references/prompt_framework.md` 第三节 rubric 逐维给 0-100 分（评分 JSON 格式：`[{"key": "维度key", "score": 分数, "note": "一句话依据"}]`）。采纳 1-2 条优化建议，若低分维度源于语义字段缺失，**回第 3 步补全后重编一轮**。
6. **输出**：按第 4 节格式组织最终答复。

## 3. 各模态分析要点

- **文本**：角色定位（作者身份/专业领域/人设/受众）+ 写作风格（语言特点/情绪倾向/表达方式/关键词习惯）+ 结构逻辑（开头/展开/组织/结尾）+ 约束规则（字数/格式/禁止内容）。脚本信号可辅助：标题层级、列表/加粗密度、emoji 与感叹号频次、Top 关键词。
- **图像**：按七段结构分析——核心主体（身份/外形/特征，先写）→ 动作与状态 → 场景（地点/环境/时间/氛围）→ 艺术风格 → 光影色调（光影+色彩）→ 镜头构图（视角/景别/构图方式）→ 画质与质感（摄影参数+质量词）。脚本信号：主色/亮度/饱和度/色温、构图网格、清晰度。术语库与负向三类/格式规范见 `references/image_rules.md`。
- **视频**：脚本镜头切分 + **逐关键帧多模态分析** → 故事结构（起承转合）+ 分镜表（景别/运镜/时长/画面内容/台词）+ 人物 + 环境氛围 + 灯光。镜头语言见 `references/video_rules.md`。
- **叙事文本（场景化）**：全局基调先行（题材/风格/角色表）→ 场景切分（**时间/地点/人物关系任一变化即新场景**；剧本按场次标记、散文按叙事块，信号来自 `analyze_scenes.py`）→ 每场景独立提炼图片七段（`references/image_rules.md`）与视频分镜（`references/video_rules.md`），风格沿用全局基调保持全篇一致。

## 4. 输出格式规范

最终答复固定四部分（方便用户逐块复制）：

1. **分析摘要**：模态、来源、特征要点 3-8 条（引用脚本数据与关键帧观察）。
2. **Prompt 列表**：每个目标模型一条——小标题 `模型名 / 用途` + 代码块包裹完整 Prompt（MJ 用 `/imagine` 原样可粘贴；GPT/Claude 用 System+User 结构；SD 正负分离）。未指定模型时输出 Midjourney + GPT-4 两版本。
3. **评分报告**：六维表格（维度/权重/得分）+ 总分与等级 + 1-2 条优化建议。
4. **使用提示**：说明哪些占位需替换、如何微调（如换风格词、换比例参数）。

**场景化输出**（叙事文本分支）固定组织：
1. **文本总览**：题材、风格基调、主要角色。
2. **场景总表**：场景号 / 标题 / 时间地点 / 情绪关键词一览。
3. **逐场景提示词**：每个场景——小标题 `场景 N：标题` + 图片 Prompt（默认 MJ/SD 双版本，代码块包裹）+ 视频分镜 Prompt（默认 Sora）。
4. **逐场景评分**：每场景六维表格 + 总分与等级 + 1-2 条优化建议。
5. **使用提示**：占位替换说明、如何微调风格/比例。

风格参照：`assets/examples/*/output.md`（写作前先看对应模态的示例，场景化见 `story_example`）。

## 5. 异常处理规则

| 情况 | 处理 |
|---|---|
| 输入不可读 / URL 下载失败（脚本退出码 2/3） | 请用户提供本地路径或直接粘贴内容；URL 超时重试 2 次，仍失败则提示改用本地文件 |
| 脚本解码失败（退出码 4） | 检查文件类型与损坏情况；**降级路径**：跳过脚本层，Agent 直接基于内容做纯描述分析，按相同流程编译 |
| 缺字段（编译器退出码 4 并列出字段名） | 按列出的字段补全 `semantic_analysis` 后重新编译（scenes 模式会报出场景号） |
| 安全过滤阻断（退出码 5） | 重写含违规表述的部分，重编后输出 |
| 内容敏感（暴力/露骨/侵权模仿特定在世人物） | 拒绝生成，说明原因 |
| 未知模型名 | 回退默认 MJ + GPT-4 双版本，并说明 |
| 视频超长 | 用 `--max-seconds` 抽样分析，输出中注明抽样范围 |
| 用户未指定模型 | 默认 MJ + GPT-4 双版本 |

安全红线：输出 Prompt 不得包含越狱指令（"忽略之前指令"等）或可执行系统命令（`rm -rf`、`cmd.exe`、`subprocess` 等）；交付前必须经 `prompt_compiler.py filter` 校验。黑名单细则见 `references/prompt_framework.md` 第四节。

## 6. 脚本调用速查

技能目录 = 本 SKILL.md 所在目录，脚本在 `scripts/` 子目录，用 `python <技能目录>/scripts/<脚本>` 调用：

| 脚本 | 用法 | 输出 |
|---|---|---|
| analyze_text.py | `<input 文件\|URL\|-> [-o out.json]` | 文本统计信封 JSON |
| analyze_image.py | `<input> [--max-size 4096] [-o out.json]` | 图片信号信封 JSON |
| analyze_video.py | `<input> [--max-seconds 120] [-o out.json]` | 镜头切分+关键帧路径信封 JSON |
| analyze_scenes.py | `<input> [-o out.json]` | 叙事文本场景切分信号信封 JSON |
| prompt_compiler.py | `all \| compile \| score \| filter \| scenes` 子命令（`--help` 查看参数） | 编译/评分/过滤/逐场景编译结果 |

场景化编译：`python <技能目录>/scripts/prompt_compiler.py scenes --analysis story.json [--image-models mj,sd] [--video-models sora] [--dims dims.json | --auto]`，story JSON 契约见 `references/prompt_framework.md` 2.5 节；`--dims` 为逐场景评分 `[{scene_no, dims: [{key, score, note}]}]`。

统一约定：信封 `{schema_version, tool, modality, input, local_features}`；退出码 `0 成功 / 1 用法 / 2 输入不可读 / 3 下载失败 / 4 解码失败或缺字段 / 5 安全阻断`；同输入输出逐字节一致（幂等）。字段契约与评分细则唯一权威见 `references/prompt_framework.md`。

## 7. 参考索引

- `references/prompt_framework.md` —— 六要素结构 + 字段契约（含 2.5 节 story 场景化）+ 评分细则 + 安全规则 + 建议库 + 扩展指南（**必读**）
- `references/image_rules.md` —— 摄影参数/构图/光影/色彩/风格词库 + 七段结构与负向三类
- `references/video_rules.md` —— 景别/运镜/叙事/分镜规范
- `references/model_mappings.md` —— 四模型格式映射表 + 场景化默认模型
- `assets/templates/*.json` —— 机器渲染模板（新增模型=新增模板文件，自动注册）
- `assets/examples/<模态>_example/output.md` —— 三模态金标输出样例；`story_example` 为剧本→逐场景提示词金标
- `tools/fixtures/semantic_*.json` —— semantic_analysis 字段填写范例（semantic_story.json 为场景化范例）
