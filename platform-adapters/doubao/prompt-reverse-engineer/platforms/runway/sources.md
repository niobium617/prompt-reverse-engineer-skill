# Runway 官方来源与核验记录

> 核验日期：2026-11-17 ｜ 状态：`verified`（至少 1 条官方来源已实际读取）
> 仅登记公开官方页面；帮助中心文章在自动化访问时被拦截，未读取正文，不作为确定性依据。

## 1. 已实际读取并核验

| 资料 | URL | 核验内容 | 结论 |
|---|---|---|---|
| Workflows 开发者页 | <https://dev.runway.com/workflows> | 工作流是可视化多步骤流水线；连接输入、模型、Prompt 与媒体操作；发布为一个 API 端点；编辑重发布端点不变；Input / Media Model / LLM 节点类别；Recipes；按模型与处理步骤计费；Gen-4.5 节点 | 已验证 |
| Workflows 产品页 | <https://runwayml.com/workflows> | Input Nodes（图片/视频/文本）；Media Model Nodes（输出图片/视频）；LLM Nodes（输出文本）；模型列表 Gen-4 / Gen-4 Turbo / Flash 2.5 / Veo 3.1 及「And more」；无代码搭建 | 已验证 |

## 2. 已知存在但本次未读取正文

| 资料 | URL | 状态 | 原因 |
|---|---|---|---|
| Runway Help Center：Workflows 入门/搭建类文章 | `https://help.runwayml.com/...` | 未核验 | 自动化访问返回 403；未获得可引用的具体文章 URL 与正文 |
| Runway API 文档 | 开发者页导航中的 Docs | 未核验 | 本次只核验 Workflows 产品页与开发者落地页，未逐页读取 API 鉴权/端点文档 |
| Recipes 详情 | 开发者页内链 | 未核验 | 只读取了列表与简介，未逐页读取步骤结构 |

## 3. 明确标为 unknown 的事项

| 事项 | 当前状态 | 原因 |
|---|---|---|
| 工作流文件格式（导入/导出） | `unknown` | 官方页面未公开；不假设存在 |
| 节点参数名、端口名、默认值 | `unknown` | 官方页面只讲节点类别与作用，未列参数 |
| 各模型时长/分辨率/画幅限制 | `unknown` | 未逐模型读取文档 |
| 音频节点 | `unknown` | Workflows 页面未展开 |
| API 鉴权、配额、价格 | `unknown` | 未读取 API 文档；不作承诺 |
| 账号可用模型清单 | `unknown` | 随账号、地区与上线状态变化 |

## 4. 未采用的来源

- 第三方教程、视频、博客：未作为确定性依据。
- 帮助中心搜索摘要：只在定位主题时参考，不引用为事实。
- 营销页中的效果演示：只说明产品定位，不据此推断节点参数或工作流结构。

## 5. 维护约定

1. 优先补充官方 Workflows 文档与帮助中心的可访问正文；每条都写「读了什么」。
2. 若官方后续公开工作流文件格式或节点参数，更新 `capability_map.json` 的 `workflow_formats` / `features` 与 `workflow_mapping.json`。
3. 每次更新同步 `version_verified`，并运行 `python tools/verify.py --filter 平台`。
