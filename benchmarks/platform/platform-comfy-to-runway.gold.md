# 金标：ComfyUI API → Runway 兼容报告

## 输入

`tools/fixtures/workflow_api.json` 经 `analyze_workflow.py` 解析为 IR，再由 `prompt_compiler.py workflow --target runway` 生成兼容报告。目标平台为 Runway Workflows（L1，映射已验证）。

## 结构层金标（自动校验）

- `source_format = comfyui_api`，`target = runway`，`platform.id = runway`，`platform.status = verified`。
- 节点条目 11；兼容计数 `compatible = 1`、`degraded = 7`、`incompatible = 3`；总体 `incompatible`。
- 文件迁移状态 `degraded`，`importable_output = false`。
- 人工步骤 10 条；依赖 3 条；边界 4 条；问题 0 条。

## 语义层金标（人工 / Agent 评分）

### 必须命中

1. **逐节点结论**：Checkpoint / LoRA / ControlNet / KSampler / 文本编码 / 解码 / 保存等节点分别给出 compatible、degraded 或 incompatible，计数与条目一致。
2. **迁移边界**：明确「不生成、不导入、不导出可执行工作流」，只输出迁移报告与人工重建步骤。
3. **可执行步骤**：至少覆盖新建项目、上传 `input.png`、按目标语法重写正负提示词、配置模型与采样参数、确认输出节点。
4. **置信度**：平台能力来自映射与公开资料，未公开参数标注待人工确认。
5. **不夸大**：不声称 Runway 可直接导入 ComfyUI 工作流，不把网页端能力等同于开放 API。

### 允许的合理改写

- 人工步骤顺序可调整，但上传素材、重写提示词、配置模型、确认输出四类不得缺失。
- 平台名称可用中文，ID 必须保持 `runway`。

### 不允许

- 声称 `importable_output = true` 或生成可导入文件。
- 把 11 个节点全部标为 compatible。
- 编造 Runway 的具体 API 参数或端点。
- 忽略 ControlNet / LoRA 等 Runway 不支持或需替代的节点。

## 评分锚点（0–2 / 维）

| 维度 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| 事实与推断分离 | 编造平台参数 | 部分标注 | 能力置信度清楚 |
| 需求覆盖 | 缺逐节点结论 | 缺一到两类 | 11 节点 + 计数齐全 |
| 平台语法 | 直接给可导入文件 | 建议笼统 | 人工步骤可执行 |
| 一致性与可执行 | 计数与条目矛盾 | 局部不一致 | 计数自洽 |
| 安全与边界 | 声称可直接运行 | 边界模糊 | 明确不生成/不导入 |
