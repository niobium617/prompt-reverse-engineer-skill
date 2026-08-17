# DeepSeek Harness 适配说明

技能唯一事实源是 `../../prompt-reverse-engineer-skill/`。本目录只存放 DeepSeek Harness 平台的外壳说明，**不维护内容副本**——安装时由 `tools/install.py` 物化联接（junction）指向技能本体。

## 什么是 DeepSeek Harness

[DeepSeek Harness](https://github.com/deepseek-ai/DeepSeek-Harness)（`deepseek-ai/DeepSeek-Harness`）是 DeepSeek 官方的 Agent 框架（npm 包前缀 `@deepseek-ai/dsh-*`，核心插件体系基于 Cordis）。它通过文件系统扫描加载 Agent Skill，格式与 Claude Code 的 `SKILL.md` 目录 bundle 一致，本技能无需改写即可直接使用。

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
