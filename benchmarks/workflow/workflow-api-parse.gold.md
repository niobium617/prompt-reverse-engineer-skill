# 金标：ComfyUI API 格式只读解析

## 输入

`tools/fixtures/workflow_api.json`：11 个节点、15 条连线的 API 格式工作流，含 checkpoint、LoRA、ControlNet、LoadImage、KSampler、VAEDecode、SaveImage。

## 结构层金标（自动校验）

- IR 版本 `1.0`，模态 `workflow`，项目类型 `comfyui_workflow`，格式 `comfyui_api`。
- 节点 11、连线 15、模型 3、自定义节点 0、问题 0、素材 1、未知节点 0。
- `confidence.workflow.status = observed`；`confidence.model.status = inferred`。

## 语义层金标（人工 / Agent 评分）

### 必须命中

1. **计数正确**：节点与连线来自文件本身；三个模型分别为 checkpoint、LoRA、ControlNet；一个输入图片素材。
2. **只读边界**：不执行采样、不推断未连线节点的输出、不渲染预览图。
3. **模型置信度**：模型名来自加载节点参数，标注「本机可用性需人工确认」，不写成已安装。
4. **参数来源**：KSampler 的 steps / cfg / sampler / scheduler / seed 来自节点输入或 widgets_values，未做连线求值。
5. **依赖与素材**：`input.png` 进入 assets 与 deps.input_assets；模型文件进入 deps.model_files。

### 允许的合理改写

- 节点分类名称可不同（如 `sampler` / `采样器`），计数与 ID 必须一致。
- 问题列表为空时可不输出该键，但结构层要求存在空数组时以实际为准。

### 不允许

- 声称工作流已成功运行或输出图片。
- 把推断的模型可用性写成 observed。
- 把自定义节点或未知节点静默丢弃。
- 生成可导入的 ComfyUI 工作流文件。

## 评分锚点（0–2 / 维）

| 维度 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| 事实与推断分离 | 模型可用性当事实 | 部分标注 | observed/inferred 清楚 |
| 需求覆盖 | 缺计数或依赖 | 缺一到两项 | 五类统计齐全 |
| 平台语法 | 结构误读 | 基本正确 | API 格式解析正确 |
| 一致性与可执行 | 执行/生成工作流 | 边界模糊 | 只读、不改文件 |
| 安全与边界 | 解析闭源文件 | 边界模糊 | 仅公开 JSON、无 L4 |
