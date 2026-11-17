# 金标：ComfyUI API → LibTV 兼容报告

## 输入

同一份 `tools/fixtures/workflow_api.json`，目标平台换为 LibTV（L1，映射已验证）。本用例检验迁移结论是否随目标能力变化，而不是复用 Runway 文案。

## 结构层金标（自动校验）

- `source_format = comfyui_api`，`target = libtv`，`platform.id = libtv`，`platform.status = verified`。
- 节点条目 11；`compatible = 1`、`degraded = 7`、`incompatible = 3`；总体 `incompatible`。
- 文件迁移状态 `degraded`，`importable_output = false`。
- 人工步骤 10 条；依赖 3 条；边界 4 条；问题 0 条。

## 语义层金标（人工 / Agent 评分）

### 必须命中

1. **目标导向**：步骤与术语面向 LibTV，不能出现「在 Runway 中新建项目」等串台文案。
2. **逐节点结论**：11 个节点均有结论；ControlNet、LoRA 等按 LibTV 能力标注降级或不兼容。
3. **计数自洽**：1 + 7 + 3 = 11，与条目数一致。
4. **可执行人工步骤**：新建项目、上传素材、重写提示词、配置模型与采样、确认输出。
5. **边界与置信度**：不生成可导入文件，不调用 API；未公开能力标注待人工确认。

### 允许的合理改写

- LibTV 的功能名可用中文描述，平台 ID 必须保持 `libtv`。
- 人工步骤可合并，但四类关键动作不得缺失。

### 不允许

- 复用 Runway 专属步骤或参数。
- 声称 LibTV 可直接导入 ComfyUI 工作流。
- 把 `degraded` 写成 `compatible`。
- 编造 LibTV 的 API 端点或参数。

## 评分锚点（0–2 / 维）

| 维度 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| 事实与推断分离 | 编造平台能力 | 部分标注 | 证据与置信度清楚 |
| 需求覆盖 | 缺逐节点结论 | 缺一到两类 | 11 节点 + 计数齐全 |
| 平台语法 | Runway 文案串台 | 建议笼统 | LibTV 步骤可执行 |
| 一致性与可执行 | 计数矛盾 | 局部不一致 | 计数自洽 |
| 安全与边界 | 声称可导入/运行 | 边界模糊 | 明确不生成/不调用 |
