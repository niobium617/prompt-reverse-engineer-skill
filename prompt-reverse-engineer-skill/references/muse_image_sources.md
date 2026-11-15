# Muse Image 参考资料索引

> 用途：记录 Muse Image 适配所依据的官方与设计资料，避免与同名研究模型混淆。
> 核对日期：2026-11-15。
> 来源形式：以下为需求方提供的官方资料标题；项目内不固化可能失效的 URL，引用时按标题在 Meta 官方站点检索。

| 资料 | 覆盖内容 | 使用方式 |
| --- | --- | --- |
| Meta：Introducing Muse Image and Muse Video | 模型定位、六项能力、Agentic 生图、搜索与代码辅助 | 官方能力依据 |
| Meta Model API：Image Generation with Muse Image | 模型调用、连续编辑、参考图输入、API 参数与限制 | 官方 API 依据 |
| Meta：Build with Muse Image | 图片生成、编辑、多图融合、Anchor Composition 工作流 | 官方工作流依据 |
| Meta Muse Image Cookbook | 实际开发示例 | 官方示例参考 |
| Google Research：Muse 2023 | 另一款同名文本到图像研究模型 | **仅用于区分**，能力不得与本模型互引 |

## 边界

- 模型标识、能力、API 参数、多轮编辑、参考图输入、Anchor Composition、已知限制：以 Meta 官方资料为准。
- 八维视觉分析、十类空间关系、六段式编译、P0–P3 优先级、扁平字段、六维评分、Muse 审查清单、36 组 Benchmark：本 Skill 的设计建议，不是 Meta 官方 Prompt 格式。
- 官方没有规定“Muse 标准 Prompt 格式”。本 Skill 输出自然语言完整句为主的可复制指令，不把内部 JSON 直接发给模型。

## 维护

- 新增官方资料时更新本表与 `muse_image_rules.md` §0、§14。
- 模型能力变化时先改 `muse_image_rules.md` 与 `assets/templates/muse_image.json`，不要改 `gpt_image.json`。
- API 参数变化只影响本文档与规则文件 §11，不影响 Prompt 模板。
