# LibTV 官方来源与核验记录

> 核验日期：2026-11-17 ｜ 状态：`verified`（至少 1 条官方来源已实际读取）
> 仅登记公开官方页面。官方使用指南为飞书 wiki，自动化访问无法读取正文，未作为确定性依据。

## 1. 已实际读取并核验

| 资料 | URL | 核验内容 | 结论 |
|---|---|---|---|
| LibTV 官网首页 | <https://www.liblib.tv/> | LibTV 画布 / Agent（BETA）/ 3D-BOX；视频、图片、音频生成；剧本生成、智能剪辑；项目/资产/插件/创作导航；模型列表（Wan 3.0、Kling 4.0、SD2 Mini&Fast、SD 2.5 Flash、Seedream 5.5、Seedance 2.5） | 已验证 |
| AI 视频落地页 | <https://www.liblib.tv/ai-video/scene> | 一句话剧本、一万字剧本直出 80 集、6 大场景模板、导入剧本、原创与改编、TV Director、角色设定/核心看点/时代背景/目标受众、MiniMax H3、Kling 4.0 原生 4K | 已验证 |
| LibTV Plugin 插件页 | <https://www.liblib.tv/plugin> | Agent 自动化生成视频或图像；支持 OpenAI、Claude、Claude Code、OpenClaw、Hermes、CodeBuddy；安装命令（`codex plugin marketplace add ...`、`codex plugin add libtv@libtv`）；需 LibTV 账户授权 | 已验证 |

## 2. 已知存在但本次未读取正文

| 资料 | URL | 状态 | 原因 |
|---|---|---|---|
| LibTV 官方使用指南（飞书 wiki） | 官方页面链接 | 未核验 | 客户端渲染，自动化抓取正文为空；不据空白内容推断功能 |
| LibTV Agent / 3D-BOX 详情页 | 官网导航内链 | 未核验 | 仅见入口，未逐页读取能力与限制 |
| 定价、配额、商用授权条款 | 官网相关页面 | 未核验 | 未读取，不作承诺 |

## 3. 明确标为 unknown 的事项

| 事项 | 当前状态 | 原因 |
|---|---|---|
| 画布节点类型、连线格式、端口名 | `unknown` | 官方公开页面未说明 |
| 分镜字段名、可选值 | `unknown` | 只知「分镜」环节存在 |
| 项目/工作流文件导入导出 | `unknown` | 未公开格式；不假设存在 |
| 公开 REST API 与鉴权 | `unknown` | 未核验到公开 API 文档 |
| 插件调用链、配额、计费 | `unknown` | 插件页只讲安装与授权 |
| 各模型时长/画幅/分辨率限制 | `unknown` | 未逐模型读取文档 |
| 角色一致性的实现方式 | `unknown` | 只知有角色设定与资产 |

## 4. 未采用的来源

- 第三方教程、短视频、博客、公众号文章：未作为确定性依据。
- 落地页营销表述（如「直出 80 集」「爆款」）：只说明产品定位，不据此推断产能或质量。
- 飞书 wiki 的搜索摘要：只在定位主题时参考，不引用为事实。

## 5. 维护约定

1. 优先补齐官方使用指南与 Agent / 3D-BOX 的可访问正文；每条都写「读了什么」。
2. 若官方后续公开项目文件格式、REST API 或分镜字段，更新 `capability_map.json` 与 `workflow_mapping.json`，并复核能力等级是否仍为 L1。
3. 每次更新同步 `version_verified`，并运行 `python tools/verify.py --filter 平台`。
