# 金标：镜头复用 → 延续模式（两镜，四模型）

## 输入

`tools/fixtures/semantic_shot_continuation.json`：6 秒雨夜街角两镜；`reuse_mode=continuation`，`continuation_from` 写明上一镜结束状态，第 1 镜 `start_state` 与之对齐，第 2 镜 `start_state` 承接第 1 镜 `end_state`；Delta 为空，Preserve 覆盖人物位置、伞与西装、霓虹位置。

## 结构层金标（自动校验）

- 复用计划模式为 `continuation`；`continuation_from` 原样输出。
- `manifest.changed` 长度为 0（未伪造改动）；保留 3、必须联动 2、无法保证 1。
- 镜头数 2；每镜 4 条 Prompt；审查清单 9 项，`continuity_state` 为 `pass`。
- 不得出现 `{`、`}`、`uncertainty`。

## 语义层金标（人工 / Agent 评分）

### 必须命中

1. **七项对齐**：`continuation_from` 与第 1 镜 `start_state` 在人物位置、身体朝向、视线方向、运动方向、服装与道具状态、场景布局、光线方向上一致。
2. **起止承接**：第 2 镜 `start_state`（身体前倾约 10 度、左脚承重、伞垂右手）与第 1 镜 `end_state` 一致，无跳变。
3. **Delta 克制**：延续不是修改，`prompt_delta` 留空；不得借延续之名新增剧情或换服装。
4. **审查口径**：`continuity_state` 只检查「是否都写明」，语义冲突由 Agent 提示；不得把自动检查说成语义已通过。
5. **平台语法**：四模型两镜各自独立可粘贴；延续说明不进入 Prompt 正文，需要时用首尾帧能力承接。

### 允许的合理改写

- Preserve 可增加「雨声连续」，但不得删掉人物位置、服装、光线三项。
- 镜头卡时间轴可分得更细，但起止状态必须保持等价。

### 不允许

- 第 2 镜重新建立人物或场景，导致与上一镜脱节。
- 把 `continuation_from` 写成一句抽象的「接着上一镜」。
- 未写第 1 镜 `start_state` 仍声明 `continuation`。
- Prompt 出现空标签、模板变量残留或 `unknown:` 内容。

## 评分锚点（0–2 / 维）

| 维度 | 0 | 1 | 2 |
| --- | --- | --- | --- |
| 七项对齐 | 多项冲突 | 缺 1–2 项 | 七项一致 |
| 起止承接 | 状态跳变 | 局部不一致 | 起止可逐项对上 |
| Delta 克制 | 伪造改动 | 夹带轻微新增 | 保持为空 |
| 审查口径 | 把检查当语义通过 | 口径含糊 | 检查与语义分离 |
| 平台语法 | 语法破坏 | 基本可用 | 四模型正确且独立可粘贴 |
