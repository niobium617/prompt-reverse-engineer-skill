# Prompt Reverse Engineer — 多模态 Prompt 逆向工程 Skill

> **把任何优秀作品 → 逆向拆解 → 还原为可复用的专业 Prompt**
>
> 支持 **Claude Code / Cursor / Codex / DeepSeek Harness / 豆包** 五大平台 · **文本 / 图片 / 视频 / 剧本小说 / ComfyUI 工作流** 多模态输入 · **Midjourney V8.2 / Stable Diffusion 3.5 / FLUX.2 / GPT Image 2.5 / Muse Image 1.0 / 即梦 5.0 / Nano Banana Pro / GPT-5.5·Claude 5.5 / DeepSeek V4.1 Flash / Seedance 2.5 / Sora 2 / Runway Gen-4.5 / Veo 3.1 / Kling 4.0 / Hailuo 3 / Vidu Q3** 多模型格式输出 · 附**百分制六维加权质量评分**（剧本可逐场景生成图片/视频提示词，实拍素材可逐镜反推镜头 Prompt，ComfyUI 工作流可只读拆解并出跨平台兼容报告，已写好的 Prompt 可诊断、改写并给出前后评分对比）

看到一篇爆款文案、一张惊艳的 AI 图片、一段电影感短视频，想知道「它是怎么被生成的」？把作品丢给本技能，它会自动拆解其主体、风格、结构与参数，反向还原出可复刻、可修改的专业 Prompt，并适配输出为各主流生成模型的格式。手上已有写好的 Prompt 但效果不稳？同一套标准会先做确定性诊断（缺字段、模糊词、冲突、参数语法），再按原意改写并重编，给出字段覆盖与前后评分对比。

纯插件形态：无前端、无后端、无数据库、无 API key、无状态、幂等、零新增依赖（脚本仅用 Python 标准库 + opencv/pillow/numpy）。

---

## 目录

- [一、核心能力](#一核心能力)
- [二、快速开始](#二快速开始)
- [三、详细使用说明](#三详细使用说明)
- [四、架构与设计](#四架构与设计)
- [五、离线验证](#五离线验证)
- [六、扩展指南](#六扩展指南)
- [七、常见问题](#七常见问题)
- [八、许可证](#八许可证)
- [九、相关项目](#九相关项目)

---

## 一、核心能力

### 1.1 输入模态与输出目标

| 输入 | 分析目标 | 输出内容 |
|---|---|---|
| **文本**（文章/文案/小说/脚本） | 角色定位、写作风格、结构逻辑、约束规则 | 复刻 Prompt + 优化模板 |
| **图像**（摄影/绘画/海报/产品图） | 主体、场景、构图、光影、色彩、摄影参数 | 正向 Prompt + Negative Prompt + 风格迁移 Prompt |
| **视频**（短视频/广告/电影片段） | 镜头序列、运镜方式、人物动作、环境氛围、叙事结构 | 视频生成 Prompt + 分镜脚本 |
| **实拍图片/视频**（镜头反推） | 景别、机位、运镜轴、时长、光影、色彩、声音、跨镜一致性 | 逐镜镜头卡 + 分镜总表 + 各模型（视频四款 / 图片六款）独立 Prompt + 逐镜评分 |
| **剧本/小说/文章**（叙事文本→场景化） | 场景切分、全局基调、逐场景七段+分镜 | 每个场景的图片 Prompt（默认 MJ+SD）+ 视频 Prompt（默认 Sora）+ 逐场景评分 |
| **ComfyUI 工作流**（API/UI JSON，只读） | 节点/连线/模型/LoRA/ControlNet/自定义节点/参数/缺失依赖 | 逐节点 `compatible/degraded/incompatible` 兼容报告 + 手工重建步骤（**不生成可导入工作流**） |
| **已有 Prompt**（优化/诊断） | 模态与模型语法、字段覆盖、模糊/重复/冲突、参数写法、六维评分 | 问题清单（按严重度）+ 优化后 Prompt（各目标模型）+ 字段覆盖对比 + 前后评分对比 |

### 1.2 十六种目标模型格式

生成的 Prompt 自动适配目标模型语法（模板元数据含展示名、厂商、版本、核验日期）：

| 类别 | 模型 | 输出要点 |
|---|---|---|
| 图像 | **Midjourney V8.2** | `/imagine prompt: ... --ar 16:9 --v 8.2`；负向用 `--no`；角色一致性用 Edit Model |
| 图像 | **Stable Diffusion 3.5** | Positive / Negative 严格分离 + Steps 28 / CFG 4.5 / DPM++ 2M 参数行 |
| 图像 | **FLUX.2 [pro]** | 自然语言长句，**不支持 negative**，参考图标注角色 |
| 图像 | **GPT Image 2.5** | 结构化规格书（Subject/Scene/Style/…/Constraints），文字逐字复现；五种任务模式（文生图/复刻/编辑/参考生成/融合）分别出稿 |
| 图像 | **Muse Image 1.0** | 自然语言完整句；八种任务模式（前五种 + Anchor 系列 / 多轮修改 / 文字版式）；空间关系与参考图迁移边界独立成段；**模板与 GPT Image 完全独立** |
| 图像 | **即梦 5.0（Seedream 5.0）** | 主体→行为与环境→位置→构图→光影→色彩→风格逐行标签；编辑/参考/融合模式独立；参数只进 `params` 块 |
| 图像 | **Nano Banana Pro** | 分段标签 + 1K/2K/4K，最多 14 张参考图，文字渲染强 |
| 文本 | **GPT-5.5 / Claude 5.5** | Markdown 标题组织六要素，System + User 结构 |
| 文本 | **DeepSeek V4.1 Flash** | 首行模型快照 + 思考档（`low`/`high`/`max`）+ 独立「推理要求」段 |
| 视频 | **Seedance 2.5** | 自然语言分镜 + 六种任务模式（文生视频 / 首帧 / 首尾帧 / 全模态参考 / 编辑 / 延长）；素材角色显式标注、参数只进 `params` 块；**模板与其他视频模型完全独立** |
| 视频 | **Sora 2** | 4/8/12/16/20 秒；自然语言散文 + 分镜 + 声音设计；`sora-2-pro` 1080p |
| 视频 | **Runway Gen-4.5** | 2–10 秒 / 720p；镜头先行，再写故事与氛围 |
| 视频 | **Veo 3.1** | 4/6/8 秒；电影摄影→主体→动作→背景→风格五段式，原生对白/音效 |
| 视频 | **Kling 4.0** | 素材职责→整体设定→主体动作→镜头→环境光影→分段事件→声音；首帧/首尾帧/参考模式；参数只进 `params` |
| 视频 | **Hailuo 3（MiniMax H3）** | 官方四段结构 `integrated_multimodal_description` / `[Shot N]` / `overall_soundscape` / `non_diegetic_music`；无配乐时明确写「无额外配乐」 |
| 视频 | **Vidu Q3** | 主体→动作与情节→场景→镜头语言→光影色彩→声音；`[@名称]` 参考主体由 `reference_note` 承载 |

**未指定目标模型时，默认输出 Midjourney V8.2 + GPT-5.5/Claude 5.5 双版本**；其余模型按需追加（`--models` 接受模型 ID 或别名）。

四个默认视频模板（Seedance / Sora 2 / Runway / Veo 3.1）与六个默认图片模板（Midjourney / Stable Diffusion / FLUX.2 / GPT Image / Muse Image / Nano Banana）另含独立的 `shot_style` 渲染段：`prompt_compiler.py shots` 按镜头逐条渲染，每个镜头输出一份可直接粘贴的 Prompt，而不是整片一段。新增的 Kling / Hailuo / Vidu 也带 `shot_style`，可在 `--models` 中显式指定；视频素材未指定模型时仍默认出四款视频模型，单张图片默认出六款图片模型。

### 1.3 质量评分

每个生成的 Prompt 附百分制评分，六维加权（权重见下表），评分后自动附 1-2 条优化建议：

| 维度 | 权重 | | 维度 | 权重 |
|---|---|---|---|---|
| 主题明确度 | 20% | | 结构清晰度 | 15% |
| 场景完整度 | 20% | | 参数合理性 | 15% |
| 风格契合度 | 20% | | 可调性/复用性 | 10% |

### 1.4 工作原理：双层分析

```
作品（文本/图片/视频/剧本）
   │
   ├── 脚本层（本地确定性信号）──→ 字数/句式统计 · 主色/构图/EXIF/景深 · 镜头切分/首中末关键帧/变化曲线与变化帧/运镜轴 · 场景切分信号 · 工作流节点/连线/依赖
   │        analyze_text.py / analyze_image.py / analyze_video.py / analyze_scenes.py / analyze_workflow.py
   │
   ├── Agent 多模态本体（语义分析）──→ 主体 · 风格 · 结构 · 叙事 · 逐场景七段+分镜 · 逐镜镜头卡（按规则库）
   │
   ├── 编译层 prompt_compiler.py ──→ 模板渲染成 16 种模型格式 + 六维评分 + 安全过滤（scenes 逐场景编译、shots 逐镜编译、optimize 诊断/重编）
   │
   └── 输出：元信息卡 + 分析摘要 + Prompt 列表 + 评分表 + 使用提示
             （场景化：总览 + 场景总表 + 逐场景 Prompt + 逐场景评分）
             （镜头反推：分镜总表 + 逐镜 Prompt + 逐镜评分 + 镜头审查清单）
             （Prompt 优化：原稿评分 + 问题清单 + 优化后 Prompt + 字段对比 + 评分对比）
```

**脚本只做「本地可计算」的事，语义判断归 Agent**——因此脚本不可用时（如豆包纯文本模式）技能仍可完整运行，仅缺少量化信号（降级路径已内置于 SKILL.md）。

### 1.5 IR 1.0 与能力声明（2.5.0 起）

在 `semantic_analysis` 之上增加**可选**的 IR 1.0 模块视图，用于跨平台映射与工作流衔接；旧 JSON 不写 IR 字段时行为完全不变。

- **IR 字段**：`ir_version`（固定 `"1.0"`）、`project`（名称/类型/目标/输出规格）、`assets`（文件名/类型/角色/sha256/关系）、`workflow`（v1 仅 ComfyUI 只读解析产物）、`confidence`（11 模块级 `observed/inferred/unknown` + 依据）。
- **11 模块**：Project / Subject / Scene / Visual / Shot / Prompt / Reference / Model / Parameters / Workflow / Assets；其中只有 Project、Assets、Workflow 需要新增顶层字段，其余是现有字段的聚合视图。
- **校验**：`prompt_compiler.py ir validate --analysis <json>`，契约错误退出码 4；`unknown` 结论不得进入 Prompt 正文。契约唯一权威见 `references/ir_spec.md`。
- **工作流只读解析（3.0.0 起）**：`analyze_workflow.py workflow.json -o wf.json` 解析 ComfyUI API/UI JSON（节点/连线/模型/LoRA/ControlNet/自定义节点/参数/缺失依赖），悬空连线或成环退出码 4；`prompt_compiler.py workflow --report wf.json --target runway --format md` 输出跨平台兼容性报告与手工重建步骤。报告固定 `importable_output: false`，不生成、不导入、不导出工作流，不调用平台 API。
- **三注册表**（生成物，勿手改）：`config/model_registry.json`、`config/platform_registry.json`、`config/capability_registry.json`，由 `tools/gen_registry.py` 从模板与 `creative-platforms/*/capability_map.json` 确定性生成，`--check` 逐字节复现。
- **能力等级**：L1 Prompt 适配、L2 配置适配（本 Skill 提供）；L3 工作流适配仅只读解析；L4 自动化执行明确不做，注册表统一声明 `supported_by_skill: false`。
- **创作平台骨架**（2.6.0 起）：`creative-platforms/` 维护 ComfyUI / Runway / LibTV 三平台五件套（平台规则、能力声明、Prompt 映射、节点映射、官方来源）；只有通过来源闸门的 `verified` 平台进入 `platform_registry.json`，安装时物化到技能实例的 `platforms/`。说明见 [`creative-platforms/README.md`](creative-platforms/README.md)。

---

## 二、快速开始

### 2.1 环境要求

| 依赖 | 用途 | 必需性 |
|---|---|---|
| Python 3.10+ | 运行分析/编译脚本 | 脚本模式必需 |
| opencv-python、pillow、numpy | 图片/视频信号提取 | 脚本模式必需 |

> 纯指令降级模式（豆包粘贴版）无任何依赖。安装依赖：`pip install opencv-python pillow numpy`（URL 下载用标准库 `urllib`，无需额外包）

### 2.2 安装（五平台）

```bash
# 预览安装动作（不执行任何写操作）
python tools/install.py --dry-run

# 一键安装到全部已检测到的 Agent（缺失的自动跳过）
python tools/install.py
```

- **Claude Code** → 安装到 `~/.claude/skills/prompt-reverse-engineer`
- **Cursor** → 安装到 `~/.cursor/skills/prompt-reverse-engineer`
- **Codex** → 注册本地插件市场到 `~/.codex/config.toml`
- **DeepSeek Harness** → 安装到 `~/.dsh/skills/prompt-reverse-engineer`（格式与 Claude Code 的 SKILL.md bundle 兼容，无需改写；宿主模型 `deepseek-flash` = V4.1 Flash，1M 上下文 + 原生视觉输入）
- **豆包（桌面版）** → 直接上传 `platform-adapters/doubao/prompt-reverse-engineer.zip`（内含标准 SKILL.md + scripts + references + assets + platforms）

Windows 默认使用 **junction 联接**安装（技能目录只放联接点，实体留在仓库内，更新仓库即自动生效，无需管理员权限）；可用 `--mode copy` 切换为物理复制。

安装时会把 `creative-platforms/` 物化到技能实例的 `platforms/`：junction 模式在技能本体下建 `platforms -> creative-platforms` 子链接，copy 模式与豆包包物理复制该目录。源目录缺失或链接创建失败时只告警，安装态**降级为仅通用 Prompt**。各平台细节见 [`platform-adapters/README.md`](platform-adapters/README.md)。

### 2.3 30 秒上手

安装后在任意支持的 Agent 中说：

```
把这段文案逆向成 prompt：
「【爆款】声波电动牙刷，3 档模式只要 199！……」

分析这张图片生成 Midjourney prompt：D:\images\cyberpunk.png

拆解这个视频的分镜脚本，转成 Sora prompt：https://example.com/video.mp4

把这段实拍视频逐镜反推成提示词，Sora / Veo 各出一版：D:\videos\night_street.mp4

把这部短剧按场景生成图片和视频提示词：D:\scripts\rain_umbrella.txt

优化这段提示词，保留原意，补全构图、光影和摄影参数：赛博朋克城市夜景……
```

即得完整输出：元信息卡 → 分析摘要 → Prompt 列表（可直接粘贴使用）→ 评分表 → 使用提示。优化 Prompt 时输出改为：原稿评分 → 问题清单 → 优化后 Prompt → 字段覆盖对比 → 前后评分对比。

---

## 三、详细使用说明

### 3.1 触发方式

提供具体内容（粘贴文本 / 本地文件路径 / URL）并表达「逆向 / 复刻 / 拆解 / 变成 prompt」意图即触发；实拍图片/视频说「反推镜头 / 复刻这个运镜 / 拆成分镜」走镜头反推分支；直接给出**已写好的 Prompt** 并说「优化 / 改写 / 诊断 / 看看哪里不好」走 Prompt 优化分支（见 3.8）。英文触发词：`prompt reverse engineering`、`reverse engineer this text/image/video/shot`、`recreate this style as a prompt`、`recreate this camera move as a prompt`、`optimize/improve/diagnose this prompt`。

### 3.2 文本模式（文章/文案/小说/脚本）

**输入**：直接粘贴文本、给本地文件路径或 URL。

**分析维度**：
- **角色定位**：作者身份、专业领域、人设定位、目标受众
- **写作风格**：语言特点、情绪倾向、表达方式、关键词使用习惯
- **结构逻辑**：开头方式、内容展开、信息组织、结尾设计
- **约束规则**：字数限制、格式要求、禁止内容、输出规范

**输出**：复刻 Prompt（System 含角色/风格/结构/约束六要素，User 为变量占位）+ 优化模板 + 评分报告。

**示例对话**：
> 用户：「把这篇文章逆向成 prompt，输出 GPT 版本」
> 技能：输出分析摘要 → GPT-5.5/Claude 5.5 复刻 Prompt（可直接把 `[此处填写主题]` 换成自己的主题复用）→ 评分报告

### 3.3 图片模式（摄影/绘画/海报/产品图）

**输入**：本地图片路径或图片 URL。

**分析维度**：主体（人物/物体/动作/外观/服饰）→ 场景（地点/环境/时间/氛围）→ 构图（视角/景别/构图方式）→ 光影（光源/明暗/氛围）→ 色彩（主色调/风格/饱和度）→ 摄影参数（镜头/焦距/景深），辅以脚本量化信号（主色、亮度、构图网格、清晰度）。

**输出**：MJ V8.2 `/imagine` 正向 Prompt + `--no` 负向 + 风格迁移版 + GPT 描述版 + 评分；还可按需出 FLUX.2（无负向）、GPT Image 2.5、Nano Banana Pro 版本。

**指定模型与风格**：
> 「分析这张图，出 MJ 和 SD 两个版本」
> 「把这张图的风格迁移成宫崎骏动画风」
> 「再出一版 FLUX.2 和 Nano Banana，画面文字写 APS 2077」

**GPT Image 2.5 五种任务模式**：文生图 / 复刻参考图 / 编辑已有图 / 参考图各自定角色生成新图 / 多参考图融合。Agent 在 `semantic_analysis.task_type` 写入对应枚举（`text_to_image` / `image_recreation` / `image_editing` / `reference_guided` / `image_composition`），脚本只渲染该用途；也可在编译时显式指定：

```bash
# 编辑已有图（一次只改一件事）
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py compile   --analysis image.json --models gpt_image --kind edit
# 用两张参考图合成新画面
... --models gpt_image --kind compose
```

`--kind` 与 `task_type` 冲突退出 4；参考图用 `reference_images: ["图1：人物姿态", "图2：霓虹配色"]` 逐行标注角色，缺编号或编号重复退出 4。五种模式的模板与字段见 `references/model_mappings.md` 3.4 节、`references/prompt_framework.md` 2.3.1–2.3.2 节。

**Muse Image 1.0 八种任务模式**：通用五用途 + `anchored_composition`（系列一致性，资产锚点）/ `conversational_refinement`（多轮修改，保留轮次状态）/ `text_layout`（海报画内文字与版式）。Muse 用自然语言完整句、无独立 negative 参数，多主体空间关系逐条写入 `spatial_relationships`，参考图需写明「用途 / 保留 / 禁止迁移 / 优先级」。

```bash
# 用三张参考图 + 资产锚点生成系列首图
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py compile   --analysis muse.json --models muse_image --kind anchored_composition
# 在上一轮结果上做定向修改
... --models muse_image --kind conversational_refinement
```

Muse 模板（`assets/templates/muse_image.json`）与 GPT Image 模板**相互独立**，共用 `visual_analysis`、`reference_roles` 等底层契约；Muse 模型更新只改 Muse 文件，不影响 GPT Image 编译策略。八种模式与字段见 `references/muse_image_rules.md`、`references/model_mappings.md` 3.5 节。

### 3.4 视频模式（短视频/广告/电影片段）

**输入**：本地视频路径或 URL。

**分析流程**：脚本自动切分镜头并抽取关键帧 → Agent 逐关键帧做多模态分析 → 还原故事结构与分镜表（景别/运镜/时长/画面内容/台词）。

**输出**：Seedance 2.5 / Sora 2 / Runway Gen-4.5 / Veo 3.1 自然语言分镜脚本 + 复刻 Prompt + GPT 版分镜表 + 评分；含声音/对白设计的模型会额外输出 `audio` / `narration` 段。

**超长视频**：默认只取前 120 秒（`--max-seconds` 可调，**截断而非跨片抽样**），输出注明截取范围。

**Seedance 2.5 六种任务模式**：文生视频（`text_to_video`）/ 首帧（`image_to_video`）/ 首尾帧（`first_last_frame`）/ 全模态参考（`reference_to_video`）/ 视频编辑（`video_editing`）/ 视频延长（`video_extension`）。首帧、首尾帧、全模态参考三者**互斥**；参考素材逐行写 `素材N：reference_image|reference_video|reference_audio；用途；保留；禁止迁移`；`resolution` / `ratio` / `duration` 等只进 `params` 块，不写正文。

```bash
# 三张参考素材（图 + 视频 + 音频）生成新片
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py compile   --analysis video.json --models seedance --kind reference_to_video
# 在源视频上定向编辑
... --models seedance --kind video_edit
```

Seedance 模板（`assets/templates/seedance.json`）与 Sora / Runway / Veo 模板**相互独立**，共用视频分镜与 `video_references` 底层契约；Seedance 模型更新只改自己的文件。六种模式、素材角色、参数边界与审查清单见 `references/seedance_rules.md`、`references/model_mappings.md` 5.4 节。

**逐镜反推（实拍素材，`shots` 子命令）**：给了实拍视频/照片并要求「反推镜头提示词 / 复刻这个运镜 / 拆成分镜」时，走镜头反推分支。视频脚本额外输出首/中/末关键帧、逐抽样点变化曲线、镜头内变化峰值帧（边界保护 + `--max-keyframes` 整片上限）、运镜轴（Z 推拉 / X 水平摇移 / Y 升降 / R 旋转）、逐镜主色与黑边信号，图片脚本额外输出 EXIF 焦段/光圈/快门/ISO、景深与黑边推断；Agent 逐帧复核后按 `references/shot_reverse_rules.md` 填镜头卡（景别 / 机位 / 运镜 / 时长 / 画面动作 / 环境 / 光影 / 色彩 / 锚点 / 声音 / 衔接 / 转场 / 证据），再由编译器逐镜、逐模型独立渲染：

```bash
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py shots \
  --analysis shot.json --models sora,runway,veo,seedance --auto --format md

# 单张实拍图：不指定 --models 时默认六款图片模型全出
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py shots \
  --analysis shot_image.json --auto --format md
```

输出分镜总表 + 每镜镜头卡 + 每个模型的独立 Prompt + 逐镜六维评分 + 镜头审查清单。未指定模型时按模态取默认：视频素材出四款视频模型，单张图片出六款图片模型，可用 `--models mj,sd` 等自选；镜头卡字段错误（编号不连续/重复、枚举不符、时长 ≤ 0、运镜超两轴、锚点超 5 个、证据无置信度标签）退出 4 并报镜头号；指定模型都没有 `shot_style` 段时退出 1。声明 `reuse_mode`（`replicate`/`local_edit`/`variant`/`continuation`/`repair`）时额外输出四栏复用计划（已修改 / 保留 / 必须联动 / 无法保证），审查清单由 6 项扩为 9 项；模式必填缺失退出 4，Delta 与 Preserve 冲突仅警告并标 `reuse_conflict=warn`。示例见 `assets/examples/shot_reverse_example/output.md` 与 `assets/examples/shot_reuse_example/`，规则见 `references/shot_reverse_rules.md` 第五节。

### 3.5 叙事文本场景化模式（剧本/小说/文章）

**输入**：本地文本路径、URL 或直接粘贴的剧本/小说/文章，并表达「生成对应场景的图片/视频提示词」「把故事变成画面」「逐场景出图」意图。

**分析流程**：脚本 `analyze_scenes.py` 先做确定性场景切分信号（剧本按场次标记 `第X场`/`INT.`/`EXT.` 等；散文按叙事块+时间地点提示）→ Agent 通读全文提炼全局基调（题材/风格/角色表）→ 按「**时间/地点/人物关系任一变化即新场景**」定稿场景划分 → 每场景独立完成图片七段 + 视频分镜语义分析（契约见 `references/prompt_framework.md` 2.5 节）。

**输出**（每场景一份，逐场景评分）：元信息卡 → 文本总览 → 场景总表（场景/标题/Prompt 数/得分/等级）→ 逐场景图片 Prompt（默认 **MJ V8.2 + SD 3.5** 双版本）+ 视频分镜 Prompt（默认 **Sora 2**）→ 逐场景六维评分 → 使用提示。

**示例对话**：
> 用户：「把这本小说按场景拆成图片和视频提示词，图片出 MJ 和 SD 版」
> 技能：输出总览 → 场景总表 → 每场景 MJ/SD Prompt + Sora 2 分镜脚本 → 逐场景评分与优化建议

### 3.6 指定目标模型

| 说法 | 结果 |
|---|---|
| （不指定） | 默认 **Midjourney V8.2 + GPT-5.5/Claude 5.5** 双版本 |
| 「也出 SD 版」/「转成 Sora」/「出 Veo 版」 | 追加对应模型 |
| 「也出 FLUX.2 / GPT Image / Muse / Nano Banana」 | 追加对应图像模板 |
| 「复刻这张图」/「编辑这张图」/「用这两张参考图合成」 | GPT Image 或 Muse 对应 `recreate` / `edit` / `reference_guided`、`compose` 用途（见 3.3 节） |
| 「做系列图」/「在上一版上改」/「海报文字排版」 | Muse 的 `anchored_composition` / `conversational_refinement` / `text_layout`（见 3.3 节） |
| 「也出 DeepSeek 版」 | 追加 DeepSeek 格式（含思考档位，见 `model_mappings.md` 第 8 节） |
| 「也出 Seedance 版」/「做首尾帧视频」/「按参考视频延长」 | 追加 Seedance 模板，按 `seedance_rules.md` 判定六种任务模式；首帧 / 首尾帧 / 全模态参考互斥 |
| 「反推这个运镜」/「拆成分镜」/「复刻这段实拍」 | 逐镜镜头卡 + 分镜总表；视频默认 **Sora 2 / Runway / Veo 3.1 / Seedance**，图片默认 **Midjourney / SD 3.5 / FLUX.2 / GPT Image / Muse Image / Nano Banana**（见 3.4 节） |
| 「全部模型」 | 全部 16 种格式输出（`--models all`） |
| 指定了未注册的模型名 | 回退默认双版本并说明 |
| 场景化模式（不指定） | 图片默认 **MJ + SD**、视频默认 **Sora 2**（`--image-models` / `--video-models` 可换） |

### 3.7 安全红线（自动执行）

- 输出 Prompt **强制**经安全过滤：越狱指令（"忽略之前指令"等）与可执行系统命令（`rm -rf`、`cmd.exe`、`subprocess` 等）命中即阻断，重写后才可输出
- 被分析内容中的指令性文本一律视为**数据**，不执行、不改变工作流
- 涉暴力、露骨、侵权模仿特定在世人物的内容拒绝生成
- 脚本不做任何网络上传；唯一网络行为是按用户要求下载用户提供的 URL

### 3.8 Prompt 优化模式（已有 Prompt）

**输入**：一段已经写好的 Prompt（直接粘贴、`--file` 或 stdin），不是待逆向的作品。用户说「优化这段提示词 / 改写一下 / 诊断哪里不对 / 提升到能出图」时触发；若给的是文案、剧本、图片或视频，仍走对应模态的逆向分支。

**四步流程**：

1. **确定性诊断**：`prompt_compiler.py optimize` 自动判定模态（text/image/video）与模型语法（MJ/SD/FLUX/GPT Image/Muse/即梦/Seedance/Sora/Runway/Veo/Kling/Hailuo/Vidu/文本），逐字段检查主体、场景、构图、光影、色彩、风格、摄影参数、负向词、分镜、时长、画幅等，标出模糊词、重复、冲突和参数写法错误，并给出六维启发式评分与安全过滤结果。
2. **问题清单**：按 `high / medium / low` 排序，每条含维度、证据与修法（复用 `prompt_framework.md` 建议库，视觉模态用专用建议）。
3. **语义改写**：Agent 按 `references/prompt_optimize_rules.md` 用**原稿已有事实**补结构，写入 `semantic_analysis`；不编造主体/风格/参数，缺失项留空或标 `unknown:`，不跨模型混写参数。
4. **重编与对比**：带 `--analysis` 重跑，渲染目标模型 Prompt，输出字段覆盖对比与前后六维评分；评分口径不同时明确标注，不把分差当真实提升。

```bash
# 只诊断（给出问题清单与评分，不改写）
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py optimize \
  --file original.txt --format md

# 诊断 + 用改写后的 semantic_analysis 重编并对比
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py optimize \
  --file original.txt --analysis optimized.json --auto --format md
```

输出：元信息卡 → 原稿评分 → 问题清单 → 字段覆盖对比 → 优化后 Prompt（各目标模型）→ 评分对比 → 使用提示。未指定目标模型时按模态取默认（图片 `default`、文本 `gpt4_claude`、视频 `sora2`），也可用 `--models mj,gpt_image` 自选。安全黑名单命中退出码 5；`--sanitize` 仅用于诊断展示，不作为交付稿。示例见 `assets/examples/optimize_example/`（`input.md` 为原稿），规则见 `references/prompt_optimize_rules.md`。

---

## 四、架构与设计

### 4.1 目录结构

```
├── prompt-reverse-engineer-skill/     # 技能本体（唯一事实源）
│   ├── SKILL.md                       # 核心定义：触发条件/六步工作流/输出规范/异常处理
│   ├── platforms/                     # 安装时物化的平台资料（junction/copy，不入库）
│   ├── scripts/
│   │   ├── analyze_text.py            # 文本确定性统计
│   │   ├── analyze_image.py           # 图片信号提取（主色/构图/EXIF/景深/黑边/镜头信号）
│   │   ├── analyze_video.py           # 视频镜头切分+首中末关键帧+变化曲线/变化帧+运镜轴+逐镜色彩（无需 ffmpeg）
│   │   ├── analyze_scenes.py          # 叙事文本场景切分信号（剧本场次标记/散文候选块）
│   │   ├── analyze_workflow.py        # ComfyUI API/UI JSON 只读解析（节点/连线/依赖/问题）
│   │   ├── _net.py                    # 受限 URL 下载（仅公网/逐跳复检重定向/大小上限）
│   │   └── prompt_compiler.py         # 编译/评分/安全过滤/优化诊断（compile|score|filter|optimize|all|scenes|shots|workflow|validate-templates）
│   ├── references/                    # 规则知识库（Markdown，Agent 阅读）
│   │   ├── ir_spec.md                 # IR 1.0 契约（11 模块/新增字段/校验规则/置信度）
│   │   ├── prompt_framework.md        # 六要素+字段契约+评分细则+安全规则（总纲，含 2.5 story / 2.6 shots / 2.7 optimize 契约）
│   │   ├── prompt_optimize_rules.md   # Prompt 优化规则（模态/模型判定、问题严重度、改写原则、对比口径）
│   │   ├── image_rules.md             # 摄影/绘画/光影/色彩术语库（含七段结构）
│   │   ├── muse_image_rules.md        # Muse Image 独立编译规则（八维/十类空间/八模式/迁移边界）
│   │   ├── muse_image_sources.md      # Muse Image 官方资料索引与「官方能力 vs 本 Skill 设计」边界
│   │   ├── seedance_rules.md          # Seedance 2.5 独立编译规则（六模式/素材角色/参数边界/审查清单）
│   │   ├── seedance_sources.md        # Seedance 官方资料索引与「官方能力 vs 本 Skill 设计」边界
│   │   ├── video_rules.md             # 电影镜头语言+分镜规范
│   │   ├── shot_reverse_rules.md      # 实拍镜头反推规则（镜头卡 12 维/证据置信度/跨镜一致性/逐模型写法）
│   │   ├── kling_sources.md           # 可灵官方资料索引与「官方能力 vs 本 Skill 设计」边界
│   │   ├── hailuo_sources.md          # 海螺官方资料索引（四段结构/声音字段边界）
│   │   ├── vidu_sources.md            # Vidu 官方资料索引（[@名称]/参考主体边界）
│   │   ├── jimeng_sources.md          # 即梦/Seedream 官方资料索引与 Skill 侧快照声明
│   │   └── model_mappings.md          # 十六模型格式映射表（含 DeepSeek 思考档位与版本迁移）
│   └── assets/
│       ├── templates/                 # 17 个 JSON 模板（16 模型渲染 + 1 评分报告，新模型=新文件，自动注册）
│       └── examples/                  # 四模态示例（输入媒体+金标输出，含 story_example / muse_image_example / seedance_example / shot_reverse_example / optimize_example）
├── benchmarks/                        # 离线基准（13 例：图片3/视频3/镜头复用3/工作流2/平台2）
│   ├── README.md                      # 结构层自动校验 vs 语义层人工评分
│   ├── rubric.md                      # 语义层五维 0–2 分 rubric
│   └── image|video|workflow|platform/ # 每例 JSON + gold.md（输入/金标/rubric）
├── config/                            # 三份注册表（gen_registry.py 生成物，勿手改）
│   ├── model_registry.json            # 模型 ID/别名/模态/任务模式/能力等级/来源文档
│   ├── platform_registry.json         # 平台能力声明（仅来源核验通过的 verified 平台）
│   └── capability_registry.json       # 模型与平台的支持项/不支持项/降级方案/核验日期
├── creative-platforms/                # 创作软件适配层（资料与映射，非安装外壳）
│   ├── README.md                      # 与 platform-adapters 的区别、状态、来源闸门
│   ├── comfyui/                       # 五件套：rules / capability_map / prompt_mapping / workflow_mapping / sources
│   ├── runway/                        # 同上（L1，仅步骤级映射）
│   └── libtv/                         # 同上（L1，节点/API 未公开，人工流程降级）
├── platform-adapters/                 # Agent 宿主适配层（内容由 install.py 物化，勿手改）
│   ├── codex/…/.codex-plugin/plugin.json
│   ├── deepseek/README.md             # DeepSeek Harness 适配说明（~/.dsh/skills）
│   └── doubao/                        # 豆包：上传 zip + 粘贴指令双产物
├── docs/                              # 项目文档
│   ├── 2026-11-14-项目改进方案.md     # 工程与 GPT Image 专项改进方案
│   ├── 2026-11-15-跨平台工作流升级方案.md # IR / 平台适配 / 工作流升级（已确认）
│   ├── 2026-11-15-实拍镜头反推方案.md  # 镜头信号 / 镜头卡 / shots 逐镜渲染（已实施）
│   ├── 2026-11-18-v3.1.0-发布说明.md  # v3.1.0 发布说明（四模型 + 离线基准）
│   ├── 2026-11-19-镜头逆向复用升级方案.md # 复用计划 / 关键帧时间轴 / 变体延续（待评审）
│   ├── DEVLOG.md                      # 阶段开发记录（改动/验证/回滚）
│   └── RELEASE.md                     # 发布检查表（版本源/tag/Release）
├── tasks/
│   └── todo.md                        # 分阶段任务清单
├── VERSION                            # 版本单一源（codex plugin.json 与之对齐）
└── tools/
    ├── install.py                     # 一键安装（junction/copy，幂等，--dry-run）
    ├── gen_examples.py                # 从 fixtures 重新生成全部示例（四模态 + 专项 + Prompt 优化，确定性）
    ├── gen_registry.py                # 从模板与 creative-platforms 生成三份注册表（确定性，--check）
    ├── benchmarks.py                  # 基准执行器（结构层自动校验，语义层只标记人工）
    ├── verify.py                      # 离线端到端验证（83 项断言）
    └── fixtures/                      # 金标语义分析 JSON（契约测试/字段范例）
```

### 4.2 脚本通用约定

- **统一信封**：`{schema_version, tool, modality, input{source,kind,sha256,size_bytes}, local_features}`
- **统一退出码**：`0 成功 / 1 用法错误（含无模型支持指定用途） / 2 输入不可读 / 3 下载失败或超过体积上限 / 4 契约错误（解码失败、缺字段、嵌套对象、类型不符、参考图编号冲突、task_type 与 --kind 冲突） / 5 安全阻断`
- **确定性幂等**：同输入两次运行输出逐字节一致（固定分桶算法、无时间戳、无随机数、键排序）
- **无状态**：不写配置文件；视频关键帧写入 `--workdir`（默认仓库 `.tmp/`，安装态回退系统临时目录），路径返回 JSON 供 Agent 读取；stdin/URL 的视频副本分析后删除
- **输入统一**：本地路径 / `-`(stdin) / `http(s)://` URL 三种形式；URL 仅允许公网 http(s)，私网/回环/链路本地/含凭据地址直接拒绝（退出码 3），重定向逐跳复检，并有 `--max-bytes` 大小上限（文本/场景 32 MiB、图片 64 MiB、视频 512 MiB）

### 4.3 数据契约（三层）

```
L1 脚本 → Agent：       local_features 量化信号（JSON 信封）
L2 Agent → 编译器：     semantic_analysis 语义字段（字段规范唯一权威：
                        references/prompt_framework.md 第二节）
IR（可选信封视图）：    ir_version / project / assets / workflow / confidence
                        （唯一权威：references/ir_spec.md；ir validate 校验）
L3 编译器 → Agent：     {prompts[], score_report{}, filter{blocked, matches, injection_flags}}
```

### 4.4 扩展设计

- **新增目标模型**：在 `assets/templates/` 新增一个 `*.json`（含 `model`/`display_name`/`vendor`/`version`/`last_verified`/`alias`/`default_params`/`modalities`），编译器自动注册并检测别名冲突，**零代码改动**
- **模板自检**：`python scripts/prompt_compiler.py validate-templates` 一次列出全部问题（元数据缺失、日期非法、未知占位符、大括号未闭合、`kind_requires` 指向不存在的用途/字段）
- **新增模型后同步注册表**：`python tools/gen_registry.py` 重新生成 `config/*.json`；CI/验证用 `--check` 断言逐字节一致
- **修改 IR 契约**：先改 `references/ir_spec.md`，再改 `prompt_compiler.py` 的 `IR_*` 常量与校验，最后补 `verify.py` 断言；旧 JSON 无 IR 字段必须继续通过
- **新增分析维度**：`references/prompt_framework.md` 加字段定义 → 模板占位符引用 → SKILL.md 补一行
- **新增视频/图片模型的逐镜支持**：模板加 `shot_style` 段即可被 `shots` 子命令渲染，字段只用镜头卡契约（见 `references/shot_reverse_rules.md`）；无 `shot_style` 的模型在 shots 输出中自动跳过，全部指定模型都缺失时退出 1
- **新增评分维度**：`prompt_compiler.py` 的 `DIMENSIONS`（权重和须为 100）与 `prompt_framework.md` 第三、五节**两处同步修改**

---

## 五、离线验证

```bash
python tools/verify.py
python tools/verify.py --filter 基准
python tools/benchmarks.py --check
python tools/benchmarks.py --suite image --check
```

83 项断言、全部离线、可重复执行；基准结构层自动校验，语义层由 Agent/人工按 `benchmarks/rubric.md` 评分：

| 层 | 覆盖 |
|---|---|
| 单元层 | 四脚本跑示例输入：退出码/信封/关键字段 + 幂等（两次运行逐字节一致）；analyze_scenes 剧本→场次标记、散文→候选块+时间地点提示 |
| 契约层 | 编译渲染（总分=加权和、建议 1-2 条）+ 越狱样例阻断（退出码 5）+ `--sanitize` 替换放行；`ir validate` 旧 JSON 直接通过 + 合法 IR 通过 + 6 类 IR 错误（版本/缺 nodes/缺 sha256/绝对路径/置信度/嵌套深度）退出码 4 |
| 负向层 | 缺字段（退出码 4 报字段名）/ 未知模型 / 坏文件 / 重复评分维度 / 重复与跳号 scene_no / 参考图缺角色或多角色 / uncertainty 缺置信度标签 / 场景缺字段（报场景号）/ 场景黑名单；工作流悬空连线、成环、UI 断链、坏 JSON → 退出码 4；IR 重复节点 ID / 环 / 端点错误 → 退出码 4 |
| 工作流层 | ComfyUI API 样例 11 节点/15 连线/3 模型/1 素材，UI 样例 10/10/2 自定义+1 未知警告；输出幂等且仅文件名；`ir validate` 通过；comfyui 原生 11/11 兼容；runway / libtv 各 1 兼容 + 7 降级 + 3 不兼容，附 10 步手工重建；未知目标退出 1；报告无绝对路径且 `importable_output: false`；draft 平台不给 compatible |
| 安装层 | junction 创建与幂等、config.toml 标记块仅一次（Windows）；copy 模式安装/幂等/`--force`（全平台）；无 `tomllib` 的 Python 3.10 降级告警并退出 0 |
| 豆包兼容 | YAML frontmatter 校验 + zip 内文件齐全 + 包内编译器独立运行成功 |
| DeepSeek 模型 | 别名（`deepseek`/`ds`/`deepseek-flash`/`deepseek-1017`）解析一致 + 三模态渲染含模型名/思考档/推理段 + 不混入默认集合 |
| 模板层 | 16 个模型模板元数据齐全且在对应模态均渲染非空 Prompt；FLUX.2 无负向、GPT Image/Muse/Seedance/Nano Banana/Veo/Runway/Sora 结构正确；可灵/海螺/Vidu 标签与 params 正确、即梦 prompt/params 与中文标签正确、三者别名解析一致且不混入默认集合；Markdown 排版；模板别名冲突→退出码 4；GPT Image 六项审查清单齐全且不参与总分；Muse、Seedance 六项审查清单各自独立且不串用；模板引用 `{uncertainty}` 被拒 |
| 任务模式 | GPT Image 五用途、Muse 八用途、Seedance 六任务模式互斥渲染（`--kind` / `task_type` 映射）；编辑顺序 Change→Scope→Preserve→Do not change；参考图逐行带编号；Muse / Seedance 模板与其他模型独立（本模型用途齐全、无串用）；Anchor/多轮/文字版式结构正确；首帧 / 首尾帧 / 全模态参考互斥、`素材N` 角色与编号校验；嵌套对象/编号缺失重复/未知 task_type/冲突→退出码 4，无模型支持→退出码 1 |
| 镜头反推 | 图片脚本输出 EXIF/景深/黑边镜头信号且带置信度；视频脚本输出首/中/末关键帧、逐抽样点变化曲线、镜头内变化峰值帧（距边界不足一个抽样间隔不加密）与运镜轴、逐镜色彩及黑边；`shots` 三镜 × 四视频模型独立 Prompt、分镜表、逐镜评分与审查清单齐全；单张图片默认 × 六图片模型（MJ `/imagine` 参数行、SD 正负向、FLUX 无负向、GPT/Muse/Nano 规格书），EXIF 焦段与景别进全部 Prompt，单帧无视频时长句式；`--dims` 人工评分与 `--format md` 排版；10 类镜头卡错误（编号/枚举/时长/运镜轴/锚点/证据标签）→退出码 4，图片多镜→退出码 4，无 `shot_style`→退出码 1，黑名单→退出码 5 且 `--sanitize` 放行；声明 `reuse_mode` 时输出四栏复用计划、九项审查清单与镜头卡扩展字段，复用模式必填缺失→退出码 4，Delta/Preserve 冲突→警告不覆盖，未声明时旧输出逐字节不变 |
| 优化层 | 弱结构图片 Prompt → 模态/模型判定、缺失构图/摄影参数/模糊词诊断；视频镜头编号+时长 → 视频模态与 Sora 2 默认；`--analysis` 重编 → 字段覆盖与六维评分提升（C→A）；黑名单退出码 5、`--sanitize` 放行；两次运行逐字节一致 |
| 基准层 | 13 例基准契约合法（图片 3 / 视频 3 / 镜头复用 3 / 工作流 2 / 平台 2），每例含输入、结构层断言、`gold.md` 与至少 3 条语义标准；`benchmarks.py --check` 结构层 13/13 通过，语义层只标记人工评分不自动打分；图片套件 3 例与镜头复用套件 3 例单独通过 |
| 一致性 | `VERSION` 与 codex 清单版本一致；清单描述含十六模型与 DeepSeek/可灵/海螺/Vidu/即梦；豆包脚本文案与 `scripts/*.py` 同步；豆包三产物两次生成哈希一致；README 依赖声明与脚本导入一致；README 断言数与实际一致；四模态 + Muse / Seedance / 镜头反推 / Prompt 优化示例可由 `gen_examples.py` 逐字节复现；8 个参考图角色在 references 中齐全；unknown 项进正文会提示而不改变总分；三注册表可由 `gen_registry.py --check` 逐字节复现（16 模型、无绝对路径）；L3 仅只读 / L4 不支持、全部模型声明 L1 且不支持 L4、平台过来源闸门；IR 文档覆盖 11 模块且 SKILL/README 同步；工作流规范/能力声明/三平台别名表同步 |
| 平台层 | 三平台五件套齐全；`capability_map.json` schema、置信度标记、官方来源闸门（`official` + 已读 `verified`）通过；`workflow_mapping.json` 节点状态合法；无「可运行 / 保证运行」表述；注册表 3 平台均为 L1-L3 且 `supported_by_skill: false`；junction / copy / 豆包包均物化 `platforms/` 且幂等 |
| 安全加固 | 全角、词内/词间零宽、大小写西里尔同形字 5 类绕过仍阻断；纯注入措辞（`act as if`/`ignore all prior rules`）只进 `injection_flags` 不阻断；`validate-templates` 全量通过且 5 类坏模板均报错；私网/回环/凭据/非 http URL 被拒，四脚本退出码 3 |
| 四场景 | ① 营销文案→GPT Prompt（角色/风格/结构约束）② 赛博朋克图→MJ Prompt（`/imagine`+`--no`+风格迁移）③ 10 秒视频→分镜 Prompt（镜头数=分镜段落数）④ 剧本→逐场景 Prompt（每场景 MJ/SD/Sora 2 齐全 + 逐场景评分） |

---

## 六、扩展指南

见 [四、架构与设计 → 4.4](#44-扩展设计)。典型操作：

1. **支持新模型**：在 `assets/templates/` 新建 `*.json`，填 `model`/`display_name`/`vendor`/`version`/`last_verified`/`alias`/`default_params`/`modalities` 与模板字符串 → 立即生效；别名不得与既有模型冲突
2. **补充风格词库**：直接编辑 `references/image_rules.md`（规则是 Markdown，无需改代码）
3. **调排版**：`all` / `scenes` 加 `--format md` 输出 Prompt 卡片 + Markdown 评分表；`assets/templates/score_report.json` 控制表格列与行格式

---

## 七、常见问题

**Q1：豆包上传提示「SKILL.md 需包含 YAML 格式的技能名称和描述」？**
请上传 `platform-adapters/doubao/prompt-reverse-engineer.zip`（含标准 YAML 头）。仓库中的 `doubao_instruction.md` 是旧版粘贴用纯文本，不含 YAML 头，上传会报此错。

**Q2：豆包版和完整版的区别？**
豆包 zip 包与技能本体内容一致（SKILL.md + scripts + references + assets 全量打入），唯一区别是豆包版 SKILL.md 正文为自包含扁平版（规则全部内联），以便豆包只读单文件时也能完整运行。

**Q3：脚本跑不了怎么办？**
技能设计即「规则为主、脚本为辅」。脚本不可用时走内置降级路径：Agent 直接基于内容做纯语义分析，流程与输出格式不变，仅缺少量化信号与硬过滤。

**Q4：为什么视频分析不需要 ffmpeg？**
关键帧抽取与镜头切分用 OpenCV（`cv2.VideoCapture`）完成，不依赖 ffmpeg CLI。

**Q5：会消耗我的 API 吗？**
离线验证（`verify.py`）完全不消耗 API。正式使用时的语义分析由所在 Agent 的模型完成，属 Agent 正常调用。

---

## 八、许可证

[MIT License](LICENSE) © 2026 niobium617

---

## 九、相关项目

| 项目 | 说明 |
|------|------|
| [AI Prompt Hub](https://github.com/niobium617/ai-prompt-hub) | 集提示词库、AI 技能教程、在线工具、社区交流于一体的全栈学习项目（Vue 3 + NestJS + 微信小程序）。与本 Skill 理念同源——把好作品拆解为可复用的 Prompt；其提示词库与教程体系收录了本 Skill 的逆向分析方法论。 |

---

*技能规则与数据契约的权威来源是 `prompt-reverse-engineer-skill/references/`，请以该目录为准。*
