# Prompt Reverse Engineer — 多模态 Prompt 逆向工程 Skill

> **把任何优秀作品 → 逆向拆解 → 还原为可复用的专业 Prompt**
>
> 支持 **Claude Code / Cursor / Codex / 豆包** 四大平台 · **文本 / 图片 / 视频** 三模态输入 · **Midjourney / Stable Diffusion / GPT-4·Claude / Sora·Runway** 多模型格式输出 · 附**百分制六维加权质量评分**

看到一篇爆款文案、一张惊艳的 AI 图片、一段电影感短视频，想知道「它是怎么被生成的」？把作品丢给本技能，它会自动拆解其主体、风格、结构与参数，反向还原出可复刻、可修改的专业 Prompt，并适配输出为各主流生成模型的格式。

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

---

## 一、核心能力

### 1.1 三种输入模态

| 输入 | 分析目标 | 输出内容 |
|---|---|---|
| **文本**（文章/文案/小说/脚本） | 角色定位、写作风格、结构逻辑、约束规则 | 复刻 Prompt + 优化模板 |
| **图像**（摄影/绘画/海报/产品图） | 主体、场景、构图、光影、色彩、摄影参数 | 正向 Prompt + Negative Prompt + 风格迁移 Prompt |
| **视频**（短视频/广告/电影片段） | 镜头序列、运镜方式、人物动作、环境氛围、叙事结构 | 视频生成 Prompt + 分镜脚本 |

### 1.2 四种目标模型格式

生成的 Prompt 自动适配目标模型语法：

- **Midjourney**：`/imagine prompt: ... --ar 16:9 --v 6` 格式，负向词用 `--no` 表达
- **Stable Diffusion**：Positive / Negative 严格分离，附 Steps、CFG、Sampler、Seed 参数行
- **GPT-4 / Claude**：System + User 消息结构，六要素完整映射
- **Sora / Runway**：自然语言分镜脚本，含景别/运镜/时长/画面内容

**未指定目标模型时，默认输出 Midjourney + GPT-4 双版本。**

### 1.3 质量评分

每个生成的 Prompt 附百分制评分，六维加权（权重见下表），评分后自动附 1-2 条优化建议：

| 维度 | 权重 | | 维度 | 权重 |
|---|---|---|---|---|
| 主题明确度 | 20% | | 结构清晰度 | 15% |
| 场景完整度 | 20% | | 参数合理性 | 15% |
| 风格契合度 | 20% | | 可调性/复用性 | 10% |

### 1.4 工作原理：双层分析

```
作品（文本/图片/视频）
   │
   ├── 脚本层（本地确定性信号）──→ 字数/句式统计 · 主色/构图/EXIF · 镜头切分/关键帧
   │        analyze_text.py / analyze_image.py / analyze_video.py
   │
   ├── Agent 多模态本体（语义分析）──→ 主体 · 风格 · 结构 · 叙事（按规则库六要素）
   │
   ├── 编译层 prompt_compiler.py ──→ 模板渲染成 4 种模型格式 + 六维评分 + 安全过滤
   │
   └── 输出：分析摘要 + Prompt 列表 + 评分报告 + 使用提示
```

**脚本只做「本地可计算」的事，语义判断归 Agent**——因此脚本不可用时（如豆包纯文本模式）技能仍可完整运行，仅缺少量化信号（降级路径已内置于 SKILL.md）。

---

## 二、快速开始

### 2.1 环境要求

| 依赖 | 用途 | 必需性 |
|---|---|---|
| Python 3.10+ | 运行分析/编译脚本 | 脚本模式必需 |
| opencv-python、pillow、numpy | 图片/视频信号提取 | 脚本模式必需 |
| requests | URL 输入自动下载 | URL 输入时必需 |

> 纯指令降级模式（豆包粘贴版）无任何依赖。安装依赖：`pip install opencv-python pillow numpy requests`

### 2.2 安装（四平台）

```bash
# 预览安装动作（不执行任何写操作）
python tools/install.py --dry-run

# 一键安装到全部已检测到的 Agent（缺失的自动跳过）
python tools/install.py
```

- **Claude Code** → 安装到 `~/.claude/skills/prompt-reverse-engineer`
- **Cursor** → 安装到 `~/.cursor/skills/prompt-reverse-engineer`
- **Codex** → 注册本地插件市场到 `~/.codex/config.toml`
- **豆包（桌面版）** → 直接上传 `platform-adapters/doubao/prompt-reverse-engineer.zip`（内含标准 SKILL.md + scripts + references + assets）

Windows 默认使用 **junction 联接**安装（技能目录只放联接点，实体留在仓库内，更新仓库即自动生效，无需管理员权限）；可用 `--mode copy` 切换为物理复制。各平台细节见 [`platform-adapters/README.md`](platform-adapters/README.md)。

### 2.3 30 秒上手

安装后在任意支持的 Agent 中说：

```
把这段文案逆向成 prompt：
「【爆款】声波电动牙刷，3 档模式只要 199！……」

分析这张图片生成 Midjourney prompt：D:\images\cyberpunk.png

拆解这个视频的分镜脚本，转成 Sora prompt：https://example.com/video.mp4
```

即得完整输出：分析摘要 → Prompt 列表（可直接粘贴使用）→ 评分报告 → 使用提示。

---

## 三、详细使用说明

### 3.1 触发方式

提供具体内容（粘贴文本 / 本地文件路径 / URL）并表达「逆向 / 复刻 / 拆解 / 变成 prompt / 优化 prompt」意图即触发。英文触发词：`prompt reverse engineering`、`reverse engineer this text/image/video`、`recreate this style as a prompt`。

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
> 技能：输出分析摘要 → GPT-4 复刻 Prompt（可直接把 `[此处填写主题]` 换成自己的主题复用）→ 评分报告

### 3.3 图片模式（摄影/绘画/海报/产品图）

**输入**：本地图片路径或图片 URL。

**分析维度**：主体（人物/物体/动作/外观/服饰）→ 场景（地点/环境/时间/氛围）→ 构图（视角/景别/构图方式）→ 光影（光源/明暗/氛围）→ 色彩（主色调/风格/饱和度）→ 摄影参数（镜头/焦距/景深），辅以脚本量化信号（主色、亮度、构图网格、清晰度）。

**输出**：MJ `/imagine` 正向 Prompt + `--no` 负向 + 风格迁移版 + GPT 描述版 + 评分。

**指定模型与风格**：
> 「分析这张图，出 MJ 和 SD 两个版本」
> 「把这张图的风格迁移成宫崎骏动画风」

### 3.4 视频模式（短视频/广告/电影片段）

**输入**：本地视频路径或 URL。

**分析流程**：脚本自动切分镜头并抽取关键帧 → Agent 逐关键帧做多模态分析 → 还原故事结构与分镜表（景别/运镜/时长/画面内容/台词）。

**输出**：Sora/Runway 自然语言分镜脚本 + 复刻 Prompt + GPT-4 分镜表 + 评分。

**超长视频**：自动截取前 120 秒抽样分析（`--max-seconds` 可调），输出注明抽样范围。

### 3.5 指定目标模型

| 说法 | 结果 |
|---|---|
| （不指定） | 默认 **Midjourney + GPT-4** 双版本 |
| 「也出 SD 版」/「转成 Sora」 | 追加对应模型 |
| 「全部模型」 | 四种格式全出 |
| 指定了未注册的模型名 | 回退默认双版本并说明 |

### 3.6 安全红线（自动执行）

- 输出 Prompt **强制**经安全过滤：越狱指令（"忽略之前指令"等）与可执行系统命令（`rm -rf`、`cmd.exe`、`subprocess` 等）命中即阻断，重写后才可输出
- 涉暴力、露骨、侵权模仿特定在世人物的内容拒绝生成
- 脚本不做任何网络上传；唯一网络行为是按用户要求下载用户提供的 URL

---

## 四、架构与设计

### 4.1 目录结构

```
├── prompt-reverse-engineer-skill/     # 技能本体（唯一事实源）
│   ├── SKILL.md                       # 核心定义：触发条件/六步工作流/输出规范/异常处理
│   ├── scripts/
│   │   ├── analyze_text.py            # 文本确定性统计
│   │   ├── analyze_image.py           # 图片信号提取（主色/构图/EXIF/人脸）
│   │   ├── analyze_video.py           # 视频镜头切分+关键帧+运镜估计（无需 ffmpeg）
│   │   └── prompt_compiler.py         # 编译/评分/安全过滤（compile|score|filter|all）
│   ├── references/                    # 规则知识库（Markdown，Agent 阅读）
│   │   ├── prompt_framework.md        # 六要素+字段契约+评分细则+安全规则（总纲）
│   │   ├── image_rules.md             # 摄影/绘画/光影/色彩术语库
│   │   ├── video_rules.md             # 电影镜头语言+分镜规范
│   │   └── model_mappings.md          # 四模型格式映射表
│   └── assets/
│       ├── templates/                 # 5 个 JSON 渲染模板（新模型=新文件，自动注册）
│       └── examples/                  # 三模态示例（输入媒体+金标输出）
├── platform-adapters/                 # 平台适配层（内容由 install.py 物化，勿手改）
│   ├── codex/…/.codex-plugin/plugin.json
│   └── doubao/                        # 豆包：上传 zip + 粘贴指令双产物
└── tools/
    ├── install.py                     # 一键安装（junction/copy，幂等，--dry-run）
    ├── verify.py                      # 离线端到端验证（13 项断言）
    └── fixtures/                      # 金标语义分析 JSON（契约测试/字段范例）
```

### 4.2 脚本通用约定

- **统一信封**：`{schema_version, tool, modality, input{source,kind,sha256,size_bytes}, local_features}`
- **统一退出码**：`0 成功 / 1 用法错误 / 2 输入不可读 / 3 下载失败 / 4 解码失败或缺字段 / 5 安全阻断`
- **确定性幂等**：同输入两次运行输出逐字节一致（固定分桶算法、无时间戳、无随机数、键排序）
- **无状态**：不写配置文件；仅视频关键帧写入系统临时目录（路径返回 JSON 供 Agent 读取）
- **输入统一**：本地路径 / `-`(stdin) / `http(s)://` URL 三种形式

### 4.3 数据契约（三层）

```
L1 脚本 → Agent：       local_features 量化信号（JSON 信封）
L2 Agent → 编译器：     semantic_analysis 语义字段（字段规范唯一权威：
                        references/prompt_framework.md 第二节）
L3 编译器 → Agent：     {prompts[], score_report{}, filter{}}
```

### 4.4 扩展设计

- **新增目标模型**：在 `assets/templates/` 新增一个 `*.json`（含 `model`/`alias`/`default_params`/`modalities` 字段），编译器自动注册发现，**零代码改动**
- **新增分析维度**：`references/prompt_framework.md` 加字段定义 → 模板占位符引用 → SKILL.md 补一行
- **新增评分维度**：`prompt_compiler.py` 的 `DIMENSIONS`（权重和须为 100）与 `prompt_framework.md` 第三、五节**两处同步修改**

---

## 五、离线验证

```bash
python tools/verify.py
```

13 项断言、全部离线、可重复执行：

| 层 | 覆盖 |
|---|---|
| 单元层 | 三脚本跑示例输入：退出码/信封/关键字段 + 幂等（两次运行逐字节一致） |
| 契约层 | 编译渲染（总分=加权和、建议 1-2 条）+ 越狱样例阻断（退出码 5）+ `--sanitize` 替换放行 |
| 负向层 | 缺字段（退出码 4 报字段名）/ 未知模型 / 坏文件 |
| 安装层 | junction 创建、重复运行幂等、config.toml 标记块仅一次（Windows） |
| 豆包兼容 | YAML frontmatter 校验 + zip 内文件齐全 + 包内编译器独立运行成功 |
| 三场景 | ① 营销文案→GPT Prompt（角色/风格/结构约束）② 赛博朋克图→MJ Prompt（`/imagine`+`--no`+风格迁移）③ 10 秒视频→分镜 Prompt（镜头数=分镜段落数） |

---

## 六、扩展指南

见 [四、架构与设计 → 4.4](#44-扩展设计)。典型操作：

1. **支持新模型（如 Flux）**：复制 `assets/templates/midjourney.json` 改名为 `flux.json`，改 `model`/`alias` 与模板字符串 → 立即生效
2. **补充风格词库**：直接编辑 `references/image_rules.md`（规则是 Markdown，无需改代码）

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

*技能规则与数据契约的权威来源是 `prompt-reverse-engineer-skill/references/`，请以该目录为准。*
