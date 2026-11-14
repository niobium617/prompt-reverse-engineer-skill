# 开发记录

> 记录每个阶段的改动、验证输出与回滚方式。方案见 [`2026-11-14-项目改进方案.md`](2026-11-14-项目改进方案.md)。

## 2026-11-14 阶段 0：视频分析资源治理

### 摘要

`analyze_video.py` 改为两遍顺序解码，移除全量帧缓存与逐镜头重开；新增 `--workdir`，本地输入零拷贝，stdin/URL 副本分析后删除；`--max-bytes` 对本地与 stdin 生效。`verify.py` 新增资源治理断言。

### 背景（基线）

- 旧实现 `sampled_gray_cache[frame_idx] = gray` 会缓存所有抽样帧灰度；120s / 30fps / 1080p 约 GB 级内存。
- 每个镜头 `cv2.VideoCapture(video_path)` 重开并 seek。
- 视频副本与关键帧写入 `tempfile.gettempdir()`，副本不清理。
- 本地文件整体读入内存后写副本，无大小上限。
- 基线断言：24/24 PASS。

### 变更清单

| 文件 | 旧 | 新 |
|---|---|---|
| `scripts/analyze_video.py` | 单遍解码 + 全量灰度缓存 + 逐镜头重开 | 两遍顺序解码；只保留首帧灰度/中点帧；无 per-shot 重开 |
| 同上 | 本地文件 `read()` 全量入内存后写临时副本 | 本地文件直接读；`getsize` 先校验 `--max-bytes`；流式计算 sha256 |
| 同上 | stdin/URL 副本常驻系统临时目录 | 副本写入 `--workdir`，`finally` 删除 |
| 同上 | 关键帧写 `gettempdir()/pre_keyframes_<sha8>` | 关键帧写 `<workdir>/video_<sha8>/keyframes/`，重复运行前清理旧文件 |
| 同上 | `--max-bytes` 仅 URL | 本地 / stdin / URL 均生效，超限退出 3 |
| `tools/verify.py` | 24 项 | 新增"单元层/视频资源治理"，25 项 |
| `README.md` | 24 项断言；"仅关键帧写系统临时目录" | 25 项；`--workdir` 说明；退出码 3 含超限 |
| `.gitignore` | 无 `.tmp/` | 忽略 `.tmp/` |

### 生效方式

无需安装步骤：脚本随技能目录使用。工作目录默认仓库 `.tmp/`；安装态回退系统临时目录。可用 `--workdir` 或环境变量 `APS_WORKDIR` 指定。

### 验证（真实输出）

```
[PASS] 单元层/analyze_video — shots=3 关键帧可读 幂等 OK
[PASS] 单元层/视频资源治理 — workdir 生效 / 临时副本清理 / 超限退出 3
...
通过 25 / 25
全部通过 ✔
```

补充验证：

- 与旧版输出逐字段对比（去掉 `keyframes_dir` / `keyframe_path`）：`equal True`。
- 本地输入两次运行输出 sha256 一致。
- stdin 模式 `input.bin` 在分析后不存在；关键帧存在。
- `--max-bytes 1000` 本地与 stdin 均退出 3，提示包含"上限"。
- 私网 URL 仍退出 3。

### 回滚

对上述文件执行 `git revert`。输出契约未变，无数据迁移。

### 脱敏

本文不含密钥、账号、绝对用户路径（除仓库内相对路径）。

## 2026-11-14 阶段 1：GPT Image 扁平契约与五任务模式

### 摘要

`gpt_image.json` 从「prompt / params / edit」扩展为五种任务模式（文生图 / 复刻 / 编辑 / 参考生成 / 融合），`semantic_analysis` 增加 12 个扁平视觉字段；编译器新增 `task_type` 映射与 `--kind` 显式选择、嵌套对象/类型/参考图编号校验、声明任务后的必填校验。`verify.py` 新增五任务模式断言，26/26 PASS。

### 背景（基线）

- 前一版本 `gpt_image/edit` 由 `target_style` 门控，只能表达「风格迁移式编辑」，无法表达复刻、参考生成、多图融合。
- 旧契约无位置/尺度/空间/材质/保留约束字段，编辑类需求只能塞进 `style` 或自由文本。
- `format_field` 对 dict 值走 `str()`，嵌套对象会被原样写进 Prompt（Python 表示泄漏）。
- 基线断言：25/25 PASS；基线输出快照 `.tmp/stage1_baseline/{text,image,video}.json`。

### 变更清单

| 文件 | 旧 | 新 |
|---|---|---|
| `assets/templates/gpt_image.json` | prompt / params / edit（`target_style` 门控） | prompt / params / recreate / edit / reference_guided / compose；`edit` 由 `modification_scope` 门控；新增 `clean_empty_label_lines: true` |
| `scripts/prompt_compiler.py` | `KNOWN_FIELDS` 28 字段；kind_requires 仅 known 字段 | +12 扁平字段；`TASK_KINDS` / `TASK_REQUIRED` / `resolve_kind` / `validate_semantic` / `validate_task_contract` / `join_values`；`kind_requires` 允许 optional/default 字段；`clean_rendered(text, drop_empty_label_lines)` |
| `tools/fixtures/semantic_gpt_image.json` | 无 | 五模式全字段范例（task_type=image_composition，参考图 图1/图2） |
| `tools/verify.py` | 25 项 | 新增「模板层/GPT Image 五任务模式」，26 项 |
| `references/prompt_framework.md` | 2.3 节 13 字段 | 新增 2.3.1（五用途映射与必填）与 2.3.2（12 扩展字段、参考图编号、扁平约束） |
| `references/model_mappings.md` | 注册表 3 用途；3.4 节单一时序 | 注册表 6 用途；3.4 节五种模式模板文本 + 门控/清理说明 |
| `SKILL.md` / `README.md` | 无 `--kind`、退出码 4 仅「缺字段」 | 增加 `task_type` / `--kind` 说明；退出码 4 列表补嵌套对象/类型/编号冲突/冲突；断言数 25→26 |
| `platform-adapters/doubao/*` | — | 由 `verify.py` 安装冒烟重新生成 |

### 生效方式

无需安装：脚本与模板随技能目录使用。图片任务在 `semantic_analysis` 写 `task_type`（`text_to_image` / `image_recreation` / `image_editing` / `reference_guided` / `image_composition`），或编译时用 `--kind prompt|recreate|edit|reference_guided|compose` 显式指定。两者冲突退出 4；显式 `--kind` 且无模型支持退出 1。不写 `task_type` / `--kind` 时行为与旧版一致。

### 验证（真实输出）

```
[PASS] 模板层/GPT Image 五任务模式 — 五用途互斥；编辑顺序 Change→Scope→Preserve→Do not change；参考图逐行；task_type 五种映射；6 类契约错误退出 4；冲突退出 4；无模型支持退出 1
...
通过 26 / 26
全部通过 ✔
```

补充验证：

- 基线对比（`semantic_text/image/video` 全模型编译）：text 与 video 全部逐字节一致；image 仅 `gpt_image/edit` 不再渲染（门控由 `target_style` 改为 `modification_scope`，属设计变更），`gpt_image/prompt` 与基线逐字节一致。
- `--kind` 五用途各返回单一 Prompt（不含 `params`）；`all --kind compose` 输出规格书 + 评分 82.5/B。
- 六类契约错误实测消息：`spatial 是对象（dict）`、`reference_images[1] 缺少「图N」编号`、`reference_images 编号重复：图1`、`task_type 必须是 …`、`task_type=image_editing 缺少必填字段：modification_scope`、`task_type=image_composition 对应用途 compose，与 --kind recreate 冲突`。
- `--models mj --kind compose` → 退出码 1，提示「没有模型支持用途 compose」。
- 场景级 `task_type` 同样生效：story 场景 1 声明 `text_to_image` 后 `gpt_image` 只渲染 `prompt`（不再出 `params`），场景 2 未声明保持原样；场景声明 `image_editing` 缺字段 → 退出码 4 且报「场景 1（雨夜街头相遇）：…缺少必填字段」。

### 偏差

- `clean_empty_label_lines` 定为模板级开关而非全局行为：全局「整行连换行删除」会改变 deepseek / gpt4_claude 视频分镜输出（原 `分镜脚本：` 空标签行会保留一个空行），违反「旧 10 个模板输出逐字节不变」。默认路径保持旧清理逻辑。
- `last_verified` 保持 `2026-11-05`，本次未重新核验 OpenAI 官方文档，不更新日期以免伪造核验记录。

### 回滚

`git revert` 上述文件；旧 `semantic_analysis`（无新字段、无 task_type）行为不变，无数据迁移。若只需回滚清理行为，把 `gpt_image.json` 的 `clean_empty_label_lines` 删除即可。

### 脱敏

本文不含密钥、账号、绝对用户路径（除仓库内相对路径）。

## 2026-11-14 阶段 2：一致性与 CI

### 摘要

新增 `VERSION`（2.1.0）作为版本单一源并对齐 codex 清单；`install.py` 动态扫描脚本清单、Python 3.10 无 `tomllib` 时降级告警并继续；新增 `tools/gen_examples.py`，四模态示例改由 fixtures 确定性生成；`verify.py` 从 26 项扩到 38 项（含 copy 模式安装、3.10 降级、一致性检查）；CI 改为全分支推送 + Windows 安装冒烟。`verify.py` 38/38 PASS。

### 背景（基线）

- 基线断言：26/26 PASS；`.github/workflows/verify.yml` 仅 `push: [main]`，单 ubuntu 作业。
- `install.py` 豆包文案写死「4 个 Python 分析脚本」，实际 6 个。
- `install.py` 直接 `import tomllib`（3.11+），CI 的 3.10 作业遇 codex 安装会失败。
- 无 `VERSION`；codex `plugin.json` 版本停在 `2.0.0`，最新 tag 仍是 `v1.4.0`。
- 四模态 `assets/examples/*/output.md` 为手写，建议条数 3 条与契约「1–2 条」不符，且随模板改动漂移。
- `verify.py` 安装层在非 Windows 直接跳过，CI 对安装逻辑零覆盖。

### 变更清单

| 文件 | 旧 | 新 |
|---|---|---|
| `VERSION` | 无 | 新增，内容 `2.1.0`（版本单一源） |
| `platform-adapters/codex/.../plugin.json` | `2.0.0` | `2.1.0`，与 `VERSION` 对齐 |
| `tools/gen_examples.py` | 无 | 新增：从 `tools/fixtures/semantic_*.json` 调用编译器生成四模态 `output.md`；`--check` 逐字节校验 |
| `assets/examples/*/output.md` | 手写（含元信息卡/摘要，建议 3 条） | 由生成器确定性输出（编译器 `--format md` 正文 + 标题/来源注记，建议数随评分器） |
| `tools/install.py` | 豆包文案写死「4 个 Python 分析脚本」及 4 个文件名 | 扫描 `scripts/*.py` 动态生成数量与清单（当前 6 个） |
| 同上 | 无 `tomllib` → `[ERROR]` 并跳过安装 | `[WARN]` 提示降级后继续追加标记块，退出 0 |
| `scripts/prompt_compiler.py` | 重复评分维度静默接受；场景号重复/跳号不校验 | 重复维度（全局与逐场景）退出 4；`scene_no` 必须为 1..N 连续整数，否则退出 4 |
| `tools/verify.py` | 26 项；无 `--filter` | 38 项（新增 12 项见下）；`--filter SUBSTR` 供分平台冒烟；`stderr` 同步 UTF-8 |
| `.github/workflows/verify.yml` | `push: [main]`，单 ubuntu 作业 | `push: ["**"]` + PR；新增 `windows-latest` 作业跑 `--filter 安装层` |
| `README.md` | 26 项断言；目录树无 `VERSION`/`gen_examples.py` | 38 项断言；目录树与验证表补一致性/安装降级条目 |
| `platform-adapters/doubao/*` | 与技能本体不同步（zip 未含阶段 1 最新文档） | 重新生成（zip 383035 → 381051 字节） |

新增 12 项断言：

1. 一致性/VERSION 与清单（`VERSION` ↔ `plugin.json.version`）
2. 一致性/Codex 清单文案（十模型描述 + DeepSeek 关键词）
3. 一致性/豆包脚本清单（文案数量/文件名 ↔ `scripts/*.py`）
4. 一致性/豆包产物可复现（两次生成哈希一致）
5. 一致性/依赖声明（README 无 `requests`，第三方导入均已声明）
6. 一致性/README 断言数（README 写的数字 ↔ 实际 checks 数）
7. 一致性/示例可复现（`gen_examples.py --check`）
8. 安装层/copy 模式冒烟（安装/幂等/`--force`，全平台）
9. 安装层/Python 3.10 降级（模拟无 `tomllib`，`[WARN]` + 退出 0 + 标记块写入）
10. 负向层/重复评分维度（退出 4）
11. 负向层/场景编号（重复/跳号均退出 4）
12. 模板层/十模型全量渲染（10 个模板在对应模态均输出非空 Prompt）

### 生效方式

- 新增/修改模板或 fixtures 后运行 `python tools/gen_examples.py` 重新生成示例，再 `python tools/install.py --platform doubao` 同步豆包产物。
- 版本发布前只需改 `VERSION`，`verify.py` 会检查 codex 清单是否同步。
- CI：ubuntu 3.10/3.12 跑全部 38 项；windows 3.12 跑 `--filter 安装层` 3 项。

### 验证（真实输出）

```
[PASS] 安装层/copy 模式冒烟 — copy 模式安装/幂等/--force 覆盖通过（Linux/Windows 通用）
[PASS] 安装层/Python 3.10 降级 — 模拟 Python 3.10（无 tomllib）降级告警并继续，退出 0
[PASS] 一致性/VERSION 与清单 — VERSION=2.1.0 与 codex plugin.json 一致
[PASS] 一致性/豆包脚本清单 — 6 个脚本清单与 scripts/*.py 一致
[PASS] 一致性/豆包产物可复现 — 豆包三产物两次生成哈希一致（固定时间戳可复现）
[PASS] 一致性/依赖声明 — README 依赖声明与 scripts 导入一致（无 requests）
[PASS] 一致性/README 断言数 — README 断言数 38 与实际一致
[PASS] 一致性/示例可复现 — 四模态 output.md 与 gen_examples.py 生成结果逐字节一致

== 验证汇总 ==
通过 38 / 38
全部通过 ✔
```

补充验证：

- `python tools/verify.py --filter 安装层` → 3/3 PASS。Windows 未实机验证，交由 CI `windows-latest` 作业覆盖。
- 重复评分维度实测提示「评分维度重复：theme_clarity」；场景号实测提示「场景 scene_no 重复：1」「场景 scene_no 必须从 1 连续编号，当前：1, 3」。
- 示例生成器两次运行输出逐字节一致（换行归一化为 LF，避免 Windows CRLF 漂移）。

### 偏差

- 示例 `output.md` 原含手写的元信息卡/分析摘要，现改为编译器确定性输出；分析摘要属 Agent 语义产物，无法由脚本复现，为消除漂移按方案 P1-3 舍弃。
- `last_updated`（codex config.toml 固定时间戳）仍为常量，未按阶段 2 清单外计划 P1-9 改为从 `VERSION` 派生。
- 未新增方案 §5.4 中的「未知字段警告」与「旧模板输出快照」：前者需区分场景对象自带字段，易误报；后者与示例逐字节断言职责重叠。

### 回滚

`git revert` 本阶段提交即可。`VERSION` 为新增文件，删除不影响运行；示例回滚后回到手写版本，`gen_examples --check` 断言需同步删除。无数据迁移。

### 脱敏

本文不含密钥、账号、绝对用户路径（除仓库内相对路径）。

## 2026-11-14 阶段 3：参考图、置信度与审查清单

### 摘要

落实方案 §5.3.6–§5.3.9：参考图角色从自由文本改为八值枚举并逐项校验；`uncertainty` 要求 `observed/inferred/unknown` 标签，模板禁止引用；GPT Image 输出末尾新增六项审查清单（不参与总分）。文档补齐角色/置信度细则与空间、材质、编辑约束术语。

### 背景（基线）

- 阶段 2 结束：`python tools/verify.py` → 38/38。
- 基线问题：`reference_images` 仅校验「图N」编号，角色靠自由文本，多图易串用；`uncertainty` 无格式约束，`unknown` 项可能被写进正文；GPT Image 只有六维评分，缺结构性自检；`image_rules.md` 无空间/材质/编辑约束术语。

### 变更清单

| 文件 | 旧值 | 新值 |
|---|---|---|
| `prompt_compiler.py` | 参考图只校验编号 | 增加 `REFERENCE_ROLES` 八枚举：缺角色、一条多角色 → 退出码 4 |
| `prompt_compiler.py` | `uncertainty` 无校验 | 每项须以 `observed:`/`inferred:`/`unknown:` 开头，否则退出码 4 |
| `prompt_compiler.py` | 模板可引用任意已声明字段 | `{uncertainty}` 占位符 → `validate-templates` 退出码 4 |
| `prompt_compiler.py` | 无审查清单 | `build_review_checklist()` 六项；`all`/`compile` 的 JSON 输出 `review_checklist`，Markdown 末尾渲染；unknown 泄漏写入 `warnings` + 「审查提示」 |
| `prompt_framework.md` | 2.3.2 仅一行说明 | 新增 2.3.3 角色枚举/写法/冲突规则、2.3.4 置信度三档、3.1 审查清单口径 |
| `image_rules.md` | 无空间/材质/编辑约束术语 | 新增第十一节（空间九宫格/景深/遮挡/材质/编辑三类约束）与第十二节（角色对照表） |
| `SKILL.md` | 未提参考图角色/审查清单 | 图像要点补角色与置信度；输出格式补审查清单；退出码补角色/标签/模板引用 |
| `semantic_gpt_image.json` | 参考图无角色；uncertainty 无标签 | 两张图改为 `identity_reference` / `style_reference` 完整写法；uncertainty 改为 `unknown:`/`inferred:` |
| `verify.py` | 38 项断言 | 44 项：参考图角色、uncertainty 标签、审查清单、模板引用禁令、泄漏提示、角色文档一致性 |
| `platform-adapters/doubao/*` | 阶段 2 文档 | 重新生成（instruction/SKILL/references/zip） |
| `README.md` | 38 项断言 | 44 项断言与验证表同步 |

新增 6 项断言：

1. 负向层/参考图角色（缺角色、一条多角色、编号重复 → 4）
2. 负向层/uncertainty 标签（缺标签 → 4；三档合法标签放行）
3. 模板层/GPT Image 审查清单（六项齐全、总分不变、非 GPT Image 不输出、Markdown 置于评分后）
4. 模板层/uncertainty 不入正文（`validate-templates` 拒绝 `{uncertainty}`）
5. 一致性/参考图角色文档（8 个角色在两份 references 中齐全）
6. 一致性/uncertainty 泄漏提示（unknown 进正文 → `warnings` + 清单待复核 + Markdown 提示）

### 生效方式

- 图像分析时 `reference_images` 每项写成 `图N：<角色枚举>；提取：…；保留：…；禁止迁移：…；优先级：…`。
- 不可确认信息写进 `uncertainty`，以 `observed:` / `inferred:` / `unknown:` 开头；`unknown` 只进说明。
- 目标含 GPT Image 时，`all --format md` 末尾自动附加审查清单；JSON 消费方读 `review_checklist`。
- 改参考文档后运行 `python tools/install.py --platform doubao` 同步豆包包。

### 验证（真实输出）

```
[PASS] 负向层/参考图角色 — 缺角色/一条多角色/编号重复 均退出码 4 并指明原因
[PASS] 负向层/uncertainty 标签 — 缺标签退出码 4；observed/inferred/unknown 三档均放行
[PASS] 模板层/GPT Image 五任务模式 — 五用途互斥；编辑顺序 Change→Scope→Preserve→Do not change；参考图逐行；task_type 五种映射；6 类契约错误退出 4；冲突退出 4；无模型支持退出 1
[PASS] 模板层/GPT Image 审查清单 — 六项审查清单齐全；总分仍等于六维加权和；非 GPT Image 不输出；Markdown 置于评分之后
[PASS] 模板层/uncertainty 不入正文 — validate-templates 拒绝 {uncertainty} 占位符（退出码 4）
[PASS] 一致性/参考图角色文档 — 8 个参考图角色在两份 references 中齐全，SKILL.md 已引用
[PASS] 一致性/uncertainty 泄漏提示 — unknown 进正文 → warnings + 审查清单待复核 + Markdown 审查提示

== 验证汇总 ==
通过 44 / 44
全部通过 ✔
```

补充验证：

- `all --analysis tools/fixtures/semantic_gpt_image.json --models gpt_image --auto --format md` 末尾输出「## 审查清单（不参与总分）」，6 项全部「通过」，总分仍为 82.5（B）。
- 同一 fixture 走 `mj` 时 JSON 无 `review_checklist`，确认清单只作用于 GPT Image。
- 手工构造 `uncertainty=["广告牌文字"]` → `错误：semantic_analysis：uncertainty[1] 必须以置信度标签开头…`，退出码 4。
- 手工构造 `reference_images=["图1：人物姿态参考"]` → 退出码 4 并列出八枚举。

### 偏差

- 角色只校验「枚举词 + 单角色 + 编号」，`提取/保留/禁止迁移/优先级` 作为必写格式写进文档但未机器校验：自由文本措辞差异大，硬校验误报率高。
- 审查清单是确定性结构启发式，不是语义判断；六项均自动给结论，暂未使用「人工确认」状态。
- 清单仅对 `gpt_image` 模型输出（按方案命名），未扩展到其他图像模型。
- `uncertainty` 泄漏只提示不阻断，符合方案「仅提示」的约定；真正禁止依赖模板占位符禁令。
- `image_rules.md` 新增内容追加为第十一/十二节，未重排既有章节，避免破坏文内「第八节」「第十节」引用。

### 回滚

`git revert` 本阶段提交即可。回滚后需重新生成豆包包与示例（`python tools/install.py --platform doubao`、`python tools/gen_examples.py`），并删除 `verify.py` 中新增 6 项断言、恢复 README 断言数为 38。无数据迁移。

### 脱敏

本文不含密钥、账号、绝对用户路径（除仓库内相对路径）。
