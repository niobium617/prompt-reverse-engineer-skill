# DeepSeek Harness 适配说明

技能唯一事实源是 `../../prompt-reverse-engineer-skill/`。本目录只存放 DeepSeek Harness 平台的外壳说明，**不维护内容副本**——安装时由 `tools/install.py` 物化联接（junction）指向技能本体。

## 什么是 DeepSeek Harness

[DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness)（`deepseek-ai/DeepSeek-Harness`）是 DeepSeek 官方的 Agent 框架（npm 包前缀 `@deepseek-ai/dsh-*`，核心插件体系基于 Cordis）。它通过文件系统扫描加载 Agent Skill，格式与 Claude Code 的 `SKILL.md` 目录 bundle 一致，本技能无需改写即可直接使用。

## 模型与能力（DeepSeek V4.1 Flash）

本技能在 Harness 上运行时，语义分析由**宿主模型**完成，因此宿主模型能力直接决定可用模态与降级路径。当前主力模型为 **DeepSeek V4.1 Flash**（2026-09-10 发布）：

| 项 | 值 | 对本技能的影响 |
|---|---|---|
| API 模型名 | `deepseek-flash` | 旧名 `deepseek-v4-flash`、`deepseek-v4-flash-vision-exp` 已下线但**暂时路由**到 V4.1 Flash，无需改配置 |
| 上下文 / 最大输出 | 1M token / 384K | 长剧本可整篇通读；视频 `--max-seconds` 可提高到 600（SKILL.md 第 5 节「宿主能力自适配」） |
| 视觉输入 | ✅ **唯一支持视觉的模型**（**原生**：视觉整合进主力模型本体，非 8 月 `vision-exp` 的「外挂视觉编码器」式） | 图片模态可直接喂原图；**视频输入未在 API 文档中声明**，视频模态仍走 `analyze_video.py` 抽关键帧 → 逐帧喂图 |
| 思考模式 | 默认开启，`low` / `high` / `max` 三档 | 输出 DeepSeek 版 Prompt 时按 `references/model_mappings.md` 第六节选档 |
| API 格式 | `https://api.deepseek.com`（OpenAI）/ `.../anthropic`（Anthropic） | 两种格式均可承载本技能 |

### 视觉输入规格（图像模态）

官方文档：[图像理解](https://api-docs.deepseek.com/guides/vision)。

| 项 | 规格 |
|---|---|
| 传图方式 | ① base64 data URL 内联；② 公开 `http(s)` 链接；③ Files API `file_id` 引用 |
| 支持格式 | JPEG / PNG / GIF / WebP（按**文件实际内容**判断，不看扩展名） |
| 位置限制 | **只能放在 `user` 消息**——放 system / assistant 返回 400 |
| 模型限制 | 非视觉模型收到图片 → 400 `This model does not support image` |
| 数量 / 尺寸 | 单请求 ≤600 张；单边 ≤8192px（**≥15 张时降到 4096px**） |
| `detail` 档位 | `low`（缩到 512×512，更快更省）/ `high` = `original` / `auto`（当前等价 `original`） |
| Token 计费 | 进模型前自动缩放——<384×384 总像素的放大，更大的缩到约 800×800 等价；**每张图上限 384 tokens**（2000×2000 与 5000×5000 等价） |
| 其他端点 | Anthropic 端点用 `image` + `source` 块；Responses API 用 `input_image` |

**对本技能的含义**：`analyze_image.py` 的 `--max-size 4096` 默认值与「≥15 张图降至 4096px」这一上限一致，无需调整；图片交给模型后会被压到约 800×800 等价、每张 ≤384 tokens，因此**视频模态多喂关键帧的代价很低**——600 帧满额也仅约 23 万 tokens，1M 上下文绰绰有余。

**跨模型降级**：若 Harness 侧配置的是不支持视觉的模型（如 V4 Pro），图片/视频模态按 SKILL.md 第 5 节「原生视觉」能力轴降级——请用户补充文字描述，**不得编造画面细节**；文本模态与脚本层不受影响。

> **V4 Pro 下线**：自 2026-09-14 12:00（北京时间）起，`deepseek-v4-pro` 请求将全部路由到 V4.1 Flash 并按 Flash 计费，直至 V4.1 Pro 上线。

## Skill 发现路径（filesystem provider 按 rank 扫描）

| Rank | 来源 | 路径 |
|---|---|---|
| 100 | 项目级 dsh | `<projectRoot>/.dsh/skills` |
| 200 | 项目级互操作 | `<projectRoot>/.agents/skills` |
| 300 | 自定义 | `Config.customSkillDirs` |
| 400 | 用户级 dsh | `$DSH_HOME/skills`（默认 `~/.dsh/skills`） |
| 500 | 用户级互操作 | `$DSH_AGENTS_HOME/skills`（默认 `~/.agents/skills`） |

项目根 = 最近的含 `.git` 的祖先目录；无 `.git` 时回退当前 cwd。安装脚本默认装到 **rank 400（`~/.dsh/skills`）**，即用户级全局可用。

## 格式要求（本技能已满足，无需改动）

- skill 为单层目录 bundle `<name>/SKILL.md`，或平铺 Markdown `<name>.md`；**刻意不支持嵌套的 `**/SKILL.md` 发现**。
- Frontmatter 用 YAML 解析：必填 `name`（**必须 kebab-case**）与 `description`；可选 `whenToUse`、`metadata`、`disable-model-invocation`、`user-invocable`。
- bundle 资源目录：`references` / `scripts` / `assets` 下文件的变更不会触发目录失效（正文编辑实时生效）。
- 本技能 `SKILL.md` 头为 `name: prompt-reverse-engineer` + 单行双引号 `description`，与 `scripts/`、`references/`、`assets/` 组成标准 bundle，开箱即用。

## 安装

```bash
# 一键安装到全部已检测到的 Agent（含 DeepSeek Harness，缺失的自动跳过）
python tools/install.py

# 只装 DeepSeek Harness
python tools/install.py --platform deepseek
```

- 默认 junction 模式：`~/.dsh/skills/prompt-reverse-engineer` 是指向仓库内技能本体的联接点（C 盘只放联接点，更新仓库即生效）。
- 可用 `--mode copy --force` 改为物理复制；`--dry-run` 先预览。

## 手动安装备选（不用 install.py 时）

把 `prompt-reverse-engineer-skill/` 整个目录复制（或建 junction）到以下任一位置并重命名为 `prompt-reverse-engineer`：

- 用户级：`~/.dsh/skills/prompt-reverse-engineer`（或 `~/.agents/skills/prompt-reverse-engineer`）
- 项目级：`<项目>/.dsh/skills/prompt-reverse-engineer`（仅该项目内可用）

## 使用

在 DeepSeek Harness 会话中通过 `/prompt-reverse-engineer` 斜杠命令显式调用，或让模型按 `SKILL.md` 的 description 自动触发。`references`/`scripts`/`assets` 资源由 harness 按 bundle 基底指引提供给模型，`scripts/` 中的 Python 分析脚本可在宿主环境直接运行（依赖见技能 SKILL.md 第 6 节）。
