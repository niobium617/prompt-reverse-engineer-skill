# 金标：ComfyUI UI 格式与未知节点处理

## 输入

`tools/fixtures/workflow_ui.json`：10 个节点、10 条连线的 UI 格式工作流，含 `ImageResizeKJ` 与未知 `MysteryNodeXP` 两个自定义节点，1 条问题记录。

## 结构层金标（自动校验）

- 格式 `comfyui_ui`；节点 10、连线 10、模型 1、自定义节点 2、问题 1、素材 1。
- 未知节点计数 1；`confidence.workflow.status = observed`，`confidence.model.status = inferred`。

## 语义层金标（人工 / Agent 评分）

### 必须命中

1. **UI 结构解析**：节点来自 `nodes`，连线来自 `links` 的 `origin_id` / `target_id` 或等价字段；widgets_values 位置映射正确。
2. **自定义节点清单**：`ImageResizeKJ` 归为 upscale，`MysteryNodeXP` 归为 unknown；两者均进入 `custom_nodes` 与 deps。
3. **未知节点不阻断**：`MysteryNodeXP` 记录为 issue，继续解析其余节点，不抛异常、不丢节点。
4. **模型只按加载节点推断**：`base.safetensors` 来自 CheckpointLoaderSimple，不声称本机存在。
5. **只读边界**：不执行、不保存、不导出可导入工作流。

### 允许的合理改写

- issue 文案可不同，只要说明「未识别节点类型、已记入依赖、不阻断」。
- 分类名可用中文或英文，节点 ID 与类型必须一致。

### 不允许

- 把未知节点当作已支持节点并猜测其输出。
- 因单个未知节点导致整体解析失败。
- 把 UI 格式误判为 API 格式。
- 生成或修改工作流文件。

## 评分锚点（0–2 / 维）

| 维度 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| 事实与推断分离 | 猜测未知节点行为 | 部分标注 | 未知即 unknown |
| 需求覆盖 | 漏自定义节点或 issue | 缺一到两项 | 节点/连线/依赖/问题齐全 |
| 平台语法 | UI/API 混淆 | 基本正确 | UI 格式解析正确 |
| 一致性与可执行 | 解析中断 | 局部丢失 | 非阻断、全量解析 |
| 安全与边界 | 执行/导出工作流 | 边界模糊 | 只读、无 L4 |
