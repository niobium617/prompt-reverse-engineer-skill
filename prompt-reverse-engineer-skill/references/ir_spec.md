# IR v1 契约（统一中间表示）

> 版本：`1.0` ｜ 实施阶段：甲 · 契约层；丙 · 工作流只读解析（2026-11-17）
> 权威性：本文件是 IR 字段、模块视图、校验规则与置信度语义的**唯一权威**。
> 实现：`scripts/analyze_workflow.py`、`scripts/prompt_compiler.py ir validate`；注册表：`tools/gen_registry.py`。
> 相邻契约：`prompt_framework.md` 第二节（`semantic_analysis` 扁平字段表）。

## 一、定位与边界

IR（Intermediate Representation）是**分析信封上的模块视图**，用于把散落在 `semantic_analysis`、`local_features` 与脚本参数里的信息按创作对象归类，便于跨平台映射与工作流衔接。

- **不是新输入格式**：旧分析 JSON 不写任何 IR 字段时，行为与 2.4.x 完全一致。
- **不嵌套进 `semantic_analysis`**：该对象仍只允许扁平字符串/字符串数组；IR 字段放在信封顶层。
- **不是 Prompt**：Prompt 是编译输出层，IR 只描述分析结论，不含渲染后的提示词。
- **不含时间戳/随机数**：同一输入两次校验输出一致。
- **不承诺执行**：IR 不包含 API 调用、工作流生成或任何 L4 自动化语义。

## 二、版本与兼容

| 规则 | 行为 |
|---|---|
| 省略 `ir_version` | 按 `1.0` 处理，旧 JSON 直接通过 |
| `ir_version` = `"1.0"` | 通过 |
| 其他值（如 `"2.0"`、数字、空串） | 契约错误，退出码 4 |
| 未知顶层键 | 忽略（前向兼容）；IR 已知字段类型错误仍退出 4 |

IR 版本升级须同时更新本文件、`prompt_compiler.py` 的 `IR_VERSION`、校验断言与 `config/*.json` 重新生成；不按小版本静默改变既有字段含义。

## 三、十一模块

IR 用 11 个模块描述一次创作。只有 `Project`、`Assets`、`Workflow` 需要新增顶层字段；其余模块是现有字段的**聚合视图**，由 Agent 按本表理解，不强制写入新键。

| # | 模块 | 数据来源 | v1 处理 |
|---|---|---|---|
| 1 | **Project** | 元信息卡、CLI 参数 | 新增可选顶层 `project`：`name/type/goal/output_spec` |
| 2 | **Subject** | 图像 `subject`；视频 `character`；文本 `role/domain/audience` | 保留原字段，IR 视图聚合 |
| 3 | **Scene** | `scene`、`atmosphere`、`story`、`storyboard` | 由现有字段派生，不新增必填 |
| 4 | **Visual** | `style/lighting/color/composition/photo_params/quality_words/material` | 聚合，不迁移 |
| 5 | **Shot** | `composition` 的视角/景别 + `storyboard[].shot_size/camera_move/duration_s` | 由 `storyboard` 派生 |
| 6 | **Prompt** | 编译器输出 | **输出层**，不进入 IR 输入 |
| 7 | **Reference** | `reference_images`、`video_references`、`reference_note`、`first_frame/last_frame/source_video` | 聚合，编号规则不变 |
| 8 | **Model** | `assets/templates/*.json` 元数据 | `config/model_registry.json` 生成 |
| 9 | **Parameters** | `default_params` + `params` 块 + `aspect_ratio/duration` | 聚合视图 |
| 10 | **Workflow** | 无（v1 起） | 新增可选顶层 `workflow`；无则视为 `null` |
| 11 | **Assets** | 分析脚本返回的输入路径 | 新增可选顶层 `assets[]` |

> `semantic_analysis` 是 Subject/Scene/Visual/Shot/Reference/Parameters 的主要载体；IR 不复制这些字段，只定义跨模块的归类方式与新增字段。

## 四、新增字段契约

### 4.1 `project`（可选，对象）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `name` | string | 否 | 项目/作品名称；只写中性名称，不写用户绝对路径 |
| `type` | string | 否 | 项目类型，如 `image / video / story / workflow / mixed` |
| `goal` | string | 否 | 本次创作目标，如「复刻雨夜霓虹街头氛围」 |
| `output_spec` | string | 否 | 输出规格的自然语言说明，如「9:16 竖版 10 秒，三镜」 |

允许附加字符串键；非字符串值 → 退出码 4。

### 4.2 `assets`（可选，数组）

每个条目是一份输入或参考资产：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `path` | string | 否 | **只记文件名**，不得含 `/`、`\`、`:` 或绝对路径 |
| `kind` | string | **是** | `image / video / audio / text / workflow / other` |
| `role` | string | 否 | 资产角色，如 `edit_target / style_reference / first_frame`；枚举仍以 `prompt_framework.md` 为准 |
| `sha256` | string | **是** | 64 位小写十六进制内容摘要 |
| `relation` | string | 否 | 资产间关系，如 `derived_from`、`paired_with` |

缺 `kind` 或 `sha256`、摘要格式非法、`path` 含目录分隔符 → 退出码 4。不得写入绝对用户路径。

### 4.3 `workflow`（可选，对象或 `null`）

v1 只接受 ComfyUI 只读解析产物（3.0.0 起由 `analyze_workflow.py` 生成）。字段：

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `nodes` | array | **是**（`workflow` 非空时） | 节点列表，不得为空；每项为对象，含 `id`、`class_type`，可选 `category` |
| `links` | array | 否 | 连线列表；每项含非空字符串 `from` / `to`，可选 `to_input`、`from_output`、`to_slot`、`link_id` |
| `format` | string | 否 | 仅 `comfyui_api / comfyui_ui`；其他值 → 退出码 4（不猜测未知格式） |
| `version` | string | 否 | ComfyUI UI JSON 版本（如 `"0.4"` / `"1.0"`） |
| `models` | array | 否 | 模型清单；元素为字符串，或含字符串 `name` 的对象（`node` / `role` 可选） |
| `assets` | array | 否 | 工作流内引用的素材；对象含字符串 `name`，`kind` 属于资产枚举，`node` 可选 |
| `parameters` | array | 否 | 采样/尺寸等参数；对象含有效 `node` 与对象 `values` |
| `custom_nodes` | array | 否 | 自定义节点清单；字符串或含非空 `class_type` 的对象（`category` / `nodes` 可选） |
| `deps` | object | 否 | 依赖汇总；值均为字符串数组（`custom_node_types` / `model_files` / `input_assets`） |
| `stats` | object | 否 | 计数汇总（节点/连线/模型/素材/自定义节点/未知节点/类别分布） |
| `issues` | array | 否 | 解析问题清单（字符串数组）；unknown 只警告，不阻断 |

`workflow` 非空但 `nodes` 缺失/为空/不是数组、节点缺 `id/class_type`、节点 ID 重复、连线端点不在节点集合内、连线成环、`parameters[].node` 无效 → 退出码 4。v1 不生成、不导入、不导出工作流文件。

工作流模块的置信度写在**顶层** `confidence.workflow`（格式见 4.4），不塞进 `workflow` 对象；`analyze_workflow.py` 输出同时带 `modality: "workflow"` 与 `ir_version: "1.0"`。

#### 4.3.1 工作流分析与兼容报告（阶段丙）

```bash
python prompt-reverse-engineer-skill/scripts/analyze_workflow.py workflow.json -o wf.json
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py workflow \
  --report wf.json --target runway --format md
```

- 只接受 ComfyUI **API JSON**（`{node_id: {class_type, inputs}}`）与 **UI JSON**（`{nodes, links}`）；不解析 `.blend/.psd/.prproj/.aep` 或剪映工程等闭源文件。
- `analyze_workflow.py` 只读解析：输出 `workflow` 模块与 `assets[]`（源文件摘要、仅文件名）、未知节点警告；悬空连线/成环/结构非法 → 退出码 4。
- `prompt_compiler.py workflow` 输出 `compatible / degraded / incompatible` 逐节点结论、文件迁移结论与手工重建步骤；`--format json` 可机读。
- 节点先按统一类别直接匹配 `workflow_mapping.json` 的 `nodes[].unified`，再查 `category_aliases` 的一对多别名（如 `sampler → image_model/video_model`，按图片/视频模态优先）；映射不到不猜。
- 报告固定 `importable_output: false`：不生成、不导入、不导出可导入工作流，不调用平台 API（无 L4）。
- 平台资料按 `--platforms-dir` → 安装态 `platforms/` → 仓库 `creative-platforms/` 查找；未知目标退出码 1，资料缺失或 `draft` 时整体保守降级。

### 4.4 `confidence`（可选，对象）

按模块记录结论的置信度：

```json
{
  "confidence": {
    "subject": {"status": "observed", "basis": "关键帧与 EXIF 均可确认"},
    "visual": {"status": "inferred", "basis": "由成片色调与布光推断"},
    "shot": {"status": "unknown", "basis": "无原始工作流文件"}
  }
}
```

- 键必须是第三节 11 个模块名的小写形式：`project / subject / scene / visual / shot / prompt / reference / model / parameters / workflow / assets`。
- `status` 只能是 `observed / inferred / unknown`。
- `basis` 必须是非空字符串，写依据而非结论。
- `unknown` 项**不得进入任何 Prompt 正文**；模块级 `unknown` 与 `semantic_analysis.uncertainty` 冲突时，取更保守的一方。

## 五、校验规则与退出码

`python prompt-reverse-engineer-skill/scripts/prompt_compiler.py ir validate --analysis <json>`

| 检查 | 失败行为 |
|---|---|
| 文件不可读 / 非 JSON | 退出码 2 / 4（与现有脚本一致） |
| `ir_version` 非 `"1.0"` | 退出码 4，报字段与当前值 |
| `workflow` 非空但 `nodes` 缺失/为空/非数组，或节点缺 `id/class_type`、节点 ID 重复 | 退出码 4，报索引 |
| `workflow.links` 端点不存在、`from_output/to_slot` 非负整数、连线成环 | 退出码 4，报端点或环 |
| `workflow.parameters[].node` 无效，或 `values` 不是对象 | 退出码 4，报索引 |
| `assets` 条目缺 `kind` 或 `sha256` | 退出码 4，报索引 |
| `assets[].path` 含目录分隔符或盘符 | 退出码 4 |
| `confidence` 键不在 11 模块内，或 `status/basis` 非法 | 退出码 4 |
| 任一 IR 字段嵌套深度 > 5（根对象按第 1 层计） | 退出码 4 |
| `semantic_analysis` 存在但违反扁平契约 | 退出码 4（复用现有校验） |
| 旧 JSON 无 IR 字段 | 直接通过，退出码 0 |

`workflow` 命令另有退出码：未知目标平台 → 1；报告不可读 → 2；报告非 JSON / 结构非法 / 不是工作流 → 4。

成功输出确定性 JSON：

```json
{
  "schema_version": "1.0",
  "tool": "prompt_compiler.py",
  "command": "ir validate",
  "ir_version": "1.0",
  "valid": true,
  "modules": ["project", "subject", "scene", "visual", "shot", "prompt",
              "reference", "model", "parameters", "workflow", "assets"],
  "errors": []
}
```

## 六、置信度语义

| 标签 | 含义 | 允许位置 |
|---|---|---|
| `observed` | 脚本信号或画面可直接确认 | IR `confidence`、`uncertainty` |
| `inferred` | 由证据推断，需保留「约 / 疑似」等措辞 | IR `confidence`、`uncertainty` |
| `unknown` | 无法确认 | 只进 IR `confidence` / `uncertainty` 元数据，**不进 Prompt 正文** |

`uncertainty` 仍是 `semantic_analysis` 内的逐项依据（每项必须以标签开头）；IR `confidence` 是模块级汇总。两者不互相替代：前者进分析过程，后者用于平台映射、工作流报告与人工复核。

## 七、最小合法示例

```json
{
  "schema_version": "1.0",
  "tool": "agent",
  "modality": "image",
  "ir_version": "1.0",
  "project": {
    "name": "霓虹街头复刻",
    "type": "image",
    "goal": "复刻雨夜霓虹氛围",
    "output_spec": "16:9 单图，电影感"
  },
  "assets": [
    {
      "path": "input.png",
      "kind": "image",
      "role": "style_reference",
      "sha256": "0000000000000000000000000000000000000000000000000000000000000000",
      "relation": "source"
    }
  ],
  "workflow": null,
  "confidence": {
    "subject": {"status": "observed", "basis": "原图可直接观察"},
    "visual": {"status": "inferred", "basis": "由色彩与布光推断"}
  },
  "semantic_analysis": {
    "subject": "撑透明伞的行人，黑色风衣，回眸",
    "scene": "雨夜霓虹街头",
    "composition": "低角度仰拍，中景",
    "lighting": "霓虹侧光，高对比",
    "color": "深蓝紫主色，霓虹橙青点缀"
  }
}
```

## 八、明确不做

1. 不要求 Agent 为 11 个模块逐项填写 JSON；模块是理解框架，不是必填清单。
2. 不生成可导入工作流，不调用生成 API，不要求密钥。
3. 不把 IR 写进模板占位符；模板仍只读取 `semantic_analysis` 的扁平字段。
4. 不在 IR 中保存用户绝对路径、账号或密钥。
5. 不为 IR 增加第二套评分引擎；评分仍按 `prompt_framework.md` 第三节。

## 九、变更控制

- 新增/修改字段：先改本文件，再改校验实现，最后补 `tools/verify.py` 断言与 `config/*.json`。
- 删除字段：至少保留一个版本的兼容读取，并在 `docs/DEVLOG.md` 写明迁移方式。
- 任何改动导致旧 fixtures 或旧模板输出不再逐字节一致，视为破坏性变更，须升级 `ir_version` 主版本。
