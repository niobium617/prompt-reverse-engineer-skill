# 创作平台适配层（creative-platforms）

本目录回答「**这个效果在某个创作软件里怎么搭 / 怎么映射**」，例如 ComfyUI、Runway、LibTV。
它是**资料与映射规则**，不是安装外壳，也不含任何可执行工作流。

## 1. 与 `platform-adapters/` 的区别

两个目录名字相近，职责完全不同：

| 目录 | 回答的问题 | 内容 | 维护方式 |
|---|---|---|---|
| `platform-adapters/` | 「这个技能怎么装进某个 **Agent 宿主**？」 | Claude Code / Cursor / Codex / DeepSeek / 豆包的安装外壳、注册块、上传包 | `tools/install.py` 物化，**勿手改** |
| `creative-platforms/` | 「这个 Prompt / 分镜怎么落到某个 **创作软件**？」 | 平台规则、能力声明、Prompt 映射、节点映射、官方来源 | 人工维护 + `gen_registry.py` 生成注册表 |

一句话：**`platform-adapters` 管宿主，`creative-platforms` 管创作工具。**

## 2. 目录结构

```
creative-platforms/
├── README.md                     # 本文件：命名、状态、边界、维护流程
├── comfyui/
│   ├── platform_rules.md         # 平台工作方式、限制、使用规则、官方来源
│   ├── capability_map.json       # 机器可读能力声明（注册表来源）
│   ├── prompt_mapping.md         # 统一 Prompt → 平台 Prompt 的写法
│   ├── workflow_mapping.json     # 统一节点 → 平台节点/功能映射（v1 只登记已知项）
│   └── sources.md                # 官方资料索引与核验日期
├── runway/                       # 同上五件套
└── libtv/                        # 同上五件套
```

## 3. 首批平台与状态

| 平台 | ID | 状态 | 能力等级 | 说明 |
|---|---|---|---|---|
| ComfyUI | `comfyui` | `verified` | L2 | 官方 Workflow JSON / API 格式文档已核验；节点类名以本机 `/object_info` 为准 |
| Runway | `runway` | `verified` | L1 | 官方 Workflows 页面已核验；无公开的工作流文件格式，参数级映射需人工确认 |
| LibTV | `libtv` | `verified` | L1 | 官网、插件页、AI 视频落地页已核验；节点图/API 细节未公开，按人工流程降级 |

`status` 语义：

- `verified`：至少有 1 条**本次实际读取**的官方来源，方可进入 `config/platform_registry.json`。
- `draft`：来源不足或无法核验；**不进入注册表**，Agent 不得据此给确定性结论。当前无 draft 平台。

## 4. 能力等级（与 IR 1.0 一致）

| 等级 | 含义 | 本 Skill 是否提供 |
|---|---|---|
| L1 | Prompt 适配（把统一 Prompt 改写成目标平台写法） | 是 |
| L2 | 配置适配（参数、模型、素材选项映射） | 是（仅已核验项；未核验项标「需人工确认」） |
| L3 | 工作流适配（只读解析与兼容性报告） | 仅只读（3.0.0 起由 `analyze_workflow.py` / `prompt_compiler.py workflow` 提供）；**不生成、不导入、不导出**工作流文件 |
| L4 | 自动化执行（调用平台 API 跑生成） | **不做**。平台原生能力照实声明，`automation.supported_by_skill` 一律 `false` |

红线：

- 不把平台网页端功能等同于开放 API；
- 不把推断出的节点、模型、参数写成已知事实；
- 不输出可导入的工作流文件，不承诺「一键运行 / 保证运行」；
- 不读取闭源工程文件（`.blend` / `.prproj` / `.psd` / `.aep` 等）。

## 5. Agent 如何消费本目录

安装后，技能实例内应出现 `platforms/`（junction 或复制，见 `tools/install.py`）：

```
<技能目录>/platforms/<平台 ID>/{platform_rules.md,capability_map.json,prompt_mapping.md,workflow_mapping.json,sources.md}
```

回答平台类问题时的顺序：

1. 读 `platforms/<平台 ID>/platform_rules.md` 与 `capability_map.json`；
2. 用 `prompt_mapping.md` / `workflow_mapping.json` 做映射；
3. **每条结论标注**：`已验证`（官方文档直接支持）/ `未验证`（社区资料或推断）/ `需人工确认`（依赖本机安装、账号、版本）；
4. 输出固定含：映射结果、不兼容项、降级方案、置信度标记；
5. 读不到 `platforms/` 时，**只输出通用 Prompt**，并明确说明「未找到平台资料，以下不含平台节点/参数映射」。

## 6. 来源闸门与更新流程

1. 先读官方文档，更新 `sources.md`（标题、URL、核验日期、核验内容、未核验项）；
2. 再改 `capability_map.json`（`status`、`version_verified`、`features[].confidence`）；
3. 改 `prompt_mapping.md` / `workflow_mapping.json`；未知项保留在 `unmapped`，不要猜；
4. 运行 `python tools/gen_registry.py` 重新生成注册表（`--check` 必须通过）；
5. 运行 `python tools/verify.py --filter 平台` 校验 schema、来源闸门、安装物化与文档同步。

官方页面改版、模型下线或参数变更时，按同一流程更新，并在 `docs/DEVLOG.md` 记录。
