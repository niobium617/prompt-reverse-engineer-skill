# 平台适配层说明

技能唯一事实源是 `../prompt-reverse-engineer-skill/`。本目录只存放各 Agent 平台的「外壳」，安装时由 `tools/install.py` 物化联接（junction）或复制，**不手工维护内容副本**。

## 各平台映射关系

| 平台 | 安装位置 | 方式 |
|---|---|---|
| Claude Code | `~/.claude/skills/prompt-reverse-engineer` | junction → 技能本体（install.py） |
| Cursor | `~/.cursor/skills/prompt-reverse-engineer` | junction → 技能本体（install.py） |
| Codex | `~/.codex/config.toml` 注册本地 marketplace，指向本目录 `codex/` | `codex/prompt-reverse-engineer/skills/` 由 install.py 物化 junction → 技能本体 |
| DeepSeek Harness | `~/.dsh/skills/prompt-reverse-engineer` | junction → 技能本体（install.py）；格式与 Claude Code 的 `SKILL.md` bundle 兼容，无需改写，细节见 [deepseek/README.md](deepseek/README.md) |
| 豆包（桌面版） | 上传技能包 / 粘贴指令 | ① **上传**（推荐）：把 `doubao/prompt-reverse-engineer/` 文件夹打包为 zip 上传——内含标准 `SKILL.md`（YAML 头含 name + description，豆包上传校验要求）；② **粘贴**：把 `doubao/doubao_instruction.md` 内容粘贴进「技能中心→新建Skill」指令框 |

## codex 子目录结构

```
codex/                                # marketplace root（config.toml 的 source 指向这里）
└── prompt-reverse-engineer/          # 插件目录
    ├── .codex-plugin/plugin.json     # 插件元数据（skills 字段指向 ./skills/）
    └── skills/                       # install.py 物化：junction → 技能本体
```

注册块由 install.py 追加到 `~/.codex/config.toml`：

```toml
# >>> prompt-reverse-engineer >>>
[marketplaces.aps-local]
last_updated = "2026-08-15T00:00:00Z"
source_type = "local"
source = '''<本仓库路径>/platform-adapters/codex'''

[plugins."prompt-reverse-engineer@aps-local"]
enabled = true
# <<< prompt-reverse-engineer <<<
```

> 注册块由 `tools/install.py` 自动写入真实绝对路径，无需手工修改。

## 手动安装备选（不用 install.py 时）

- Claude Code / Cursor / DeepSeek Harness：复制（或建 junction）整个 `prompt-reverse-engineer-skill/` 到各自 skills 目录并重命名为 `prompt-reverse-engineer`（DeepSeek Harness 为 `~/.dsh/skills/prompt-reverse-engineer`，见 [deepseek/README.md](deepseek/README.md)）。
- Codex：手动创建上述目录结构 + 手工追加 config.toml 注册块。
- 豆包：上传 `doubao/prompt-reverse-engineer/` 文件夹打包的 zip（技能包内含带 YAML 头的 SKILL.md）；或把 `doubao/doubao_instruction.md` 内容粘贴进「技能中心 → 新建 Skill」的指令框。
