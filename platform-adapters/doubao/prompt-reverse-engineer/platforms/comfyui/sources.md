# ComfyUI 官方来源与核验记录

> 核验日期：2026-11-17 ｜ 状态：`verified`（至少 1 条官方来源已实际读取）
> 访问方式：直接读取官方文档页面。仅登记公开文档，不包含社区教程、论坛或第三方节点仓库的未核实内容。

## 1. 已实际读取并核验

| 资料 | URL | 核验内容 | 结论 |
|---|---|---|---|
| Workflow JSON（v1.0 Latest + 0.4） | <https://docs.comfy.org/specs/workflow_json> | 工作流保存格式由 `version` / `nodes` / `links` / `groups` 等字段构成；当前版 1.0，保留 0.4 | 已验证 |
| Workflow API Format | <https://docs.comfy.org/development/api-development/workflow-api-format> | Save 格式与 API 格式不同；API 格式以节点 ID 为键，含 `class_type` / `inputs`；API 省略位置、颜色、分组等 UI 元数据；`File → Export Workflow (API)`；示例含 `KSampler` / `VAEDecode` / `CheckpointLoaderSimple` / `SaveImage` | 已验证 |

## 2. 官方索引收录、本次未逐页读取正文

以下 URL 来自 ComfyUI 官方文档索引（`https://docs.comfy.org/llms.txt` 与开发者索引），本次**没有逐页读取正文**，因此相关细节在 `capability_map.json` 中标 `verified: false`，在回答中按「未验证」处理：

| 资料 | URL | 用途 | 状态 |
|---|---|---|---|
| Workflow JSON 0.4 | <https://docs.comfy.org/specs/workflow_json_0.4> | 旧版工作流字段 | 未核验 |
| Node Definition JSON | <https://docs.comfy.org/specs/nodedef_json> | 节点定义字段 | 未核验 |
| Node Definition JSON 1.0 | <https://docs.comfy.org/specs/nodedef_json_1_0> | 节点定义 1.0 | 未核验 |
| Workflow Metadata in Output Files | <https://docs.comfy.org/development/api-development/workflow-metadata> | 输出文件内嵌工作流与 API prompt | 未核验 |
| Custom Nodes 总览 | <https://docs.comfy.org/custom-nodes/overview> | 自定义节点架构与分类 | 未核验 |
| 安装自定义节点 | <https://docs.comfy.org/installation/install_custom_node> | 节点包安装方式 | 未核验 |
| 官方首图教程 | <https://docs.comfy.org/get_started/first_generation> | 文生图工作流示例 | 未核验 |

> 上表只用于「官方文档确实存在该主题」的定位，不构成参数、节点名或版本的确定性依据。

## 3. 明确标为 unknown 的事项

| 事项 | 当前状态 | 原因 |
|---|---|---|
| 具体版本号与发布节奏 | `unknown` | 官方工作流格式有版本，但应用/前端版本未统一锁定 |
| 内置节点完整清单与端口 | `unknown` | 随版本变化；应以本机 `/object_info` 为准 |
| 自定义节点兼容矩阵 | `unknown` | 第三方节点不由官方统一维护 |
| 云端 API 细节 | `unknown` | 本次只核验了工作流格式与 API 格式，未核验云端鉴权/配额/端点 |
| 视频/音频/3D 工作流细节 | `unknown` | 本阶段只做骨架，未逐类核验 |
| 工作流 JSON 的完整 schema 约束 | `unknown` | 未逐条读取 JSON Schema 字段约束 |

## 4. 未采用的来源

- 社区教程、博客、论坛帖：未作为确定性依据；若引用，必须在回答中明确标「未验证」。
- 第三方节点仓库：只作为用户工作流的依赖线索，不代表官方能力。
- 闭源工程文件与截图：不解析、不推断内部节点结构。

## 5. 维护约定

1. 新增官方来源时，先在本文件登记「读了什么、结论是什么」，再改 `capability_map.json`。
2. 官方页面 404/改版/重定向时，把条目移到「未采用」或更新 URL，不能继续引用失效链接。
3. 每次更新同步 `version_verified`，并运行 `python tools/verify.py --filter 平台`。
