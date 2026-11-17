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

## 2026-11-14 修复：Linux CI 安装层断言失败（junction → symlink）

### 摘要

`install.py` 的 codex 安装路径在非 Windows 平台直接调用 `cmd /c mklink`，抛
`FileNotFoundError` 导致 GitHub Actions ubuntu 作业在「安装层/Python 3.10 降级」失败；
改为 POSIX 用 `os.symlink`、Windows 保持 junction。

### 背景（基线）

- 本地 Windows：`python tools/verify.py` → 44/44 通过。
- PR #6 / #7 首次 CI：ubuntu 3.10、3.12 两个作业均 FAIL，43/44，唯一失败项即上述断言；
  windows-latest 安装冒烟通过。

### 变更清单（旧值 → 新值）

| 位置 | 旧值 | 新值 |
|---|---|---|
| `make_junction` | 无条件 `cmd /c mklink /J` | `os.name == "nt"` 用 mklink；POSIX 用 `os.symlink`（已存在同源链接则跳过） |
| `is_junction` | 仅识别 Windows reparse point | POSIX 返回 `path.is_symlink()` |
| `junction_target` | 仅 `cmd /c dir` 解析 | POSIX 用 `os.readlink` |
| 链接删除（2 处） | `os.rmdir` | 新增 `remove_link`：符号链接 `unlink`，junction `rmdir` |

### 生效方式

随分支配送，无需额外操作；非 Windows 用户以 junction 模式安装时自动得到符号链接，
行为与 Windows 等价。

### 验证（真实输出）

修复后本地 Windows：

```text
== 验证汇总 ==
通过 44 / 44
全部通过 ✔
```

（阶段 2 分支同补丁：38 / 38 通过。）

GitHub Actions 修复后：

```text
4360839914 chore/stage2-consistency-ci completed success
4360843948 chore/stage2-consistency-ci completed success
4360801938 feat/stage3-reference-confidence-review completed success
4360796526 feat/stage3-reference-confidence-review completed success
```

### 偏差

- Windows 工作区 `core.autocrlf=true` 时，重新检出后的 `image_rules.md` 为 CRLF，
  重新生成的豆包 zip 会比提交版本多 17 字节；CI（LF 检出）与提交一致。未引入
  `.gitattributes` 强制换行，避免一次性重写全仓库行尾，留待发布阶段评估。

### 回滚

`git revert` 本修复提交；Windows 行为不变，POSIX 恢复为安装报错（不使用）。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-14 发布 v2.1.0

### 摘要

固化阶段 0–3 成果：豆包产物行尾归一化、发布检查表、README/CI 断言数同步，发布 `v2.1.0`。

### 背景（基线）

- 发布前：`VERSION` 2.1.0、`plugin.json` 2.1.0（阶段 2 已对齐）；`verify.py` 44/44。
- 已知偏差：Windows `core.autocrlf=true` 检出时，重新生成的豆包 zip 与提交版本不一致（差 17 字节及以上），阶段 3 记录为「留待发布阶段评估」。

### 变更清单（旧值 → 新值）

| 位置 | 旧值 | 新值 |
|---|---|---|
| `tools/install.py` | 直接 `read_text` / `copytree`，`write_text` 走平台默认换行 | 新增 `normalize_newlines` / `normalize_tree`，写入显式 `newline="\n"`，豆包产物恒为 LF |
| `tools/verify.py` | 44 项断言 | 45 项：新增 `一致性/豆包产物换行`（归一化函数 + 指令文本/zip 内文本无 CRLF） |
| `README.md` | 44 项断言（树与说明） | 45 项；目录树补 `docs/RELEASE.md` |
| `.github/workflows/verify.yml` | 步骤名 44 项 | 45 项 |
| `docs/RELEASE.md` | 不存在 | 发布检查表（版本源、tag/Release、发布后核对、历史版本） |
| 豆包 zip | 390614 字节（内部混有 CRLF） | 390286 字节（内部文本 LF） |

### 生效方式

随 `main` 发布；安装器与 CI 自动使用新逻辑。非 Windows 平台生成结果与 Windows 完全一致。

### 验证（真实输出）

```text
== 验证汇总 ==
通过 45 / 45
全部通过 ✔
```

```text
[PASS] text_example/output.md 与生成结果一致
[PASS] image_example/output.md 与生成结果一致
[PASS] video_example/output.md 与生成结果一致
[PASS] story_example/output.md 与生成结果一致
```

`python tools/install.py --platform doubao` 后 `git diff --name-only` 仅 5 个预期文件；
包内文本文件（`git ls-files --eol` 显示 `w/lf`）与 zip 内条目均无 CRLF。

### 偏差

- 仓库描述在阶段 0–1 已含十模型/五平台，本次只核对未改写。
- 发布当天 git 协议到 github.com 间歇不可达，tag/Release 若无法 `git push` 则改走 GitHub API（`gh release create --target main`）。

### 回滚

`git revert` 发布提交；`gh release delete v2.1.0 --yes` 并删除远端 tag；豆包产物恢复为归档 zip。
无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-15 Muse Image 1.0 独立适配（v2.2.0）

### 摘要

新增 Meta Muse Image 1.0 目标模型：独立模板与独立规则文件，支持八种任务模式（通用五用途 + Anchor 系列 / 多轮修改 / 文字版式）、十类空间关系、参考图迁移边界与 Muse 专项审查清单；升级至 `2.2.0`，断言 45 → 49。

### 背景（基线）

- 适配前：`VERSION` 2.1.0、11 个模板文件（10 模型 + 评分报告）、`verify.py` 45/45。
- 设计资料给出八维分析、六任务模式等建议，但明确「这些属于 Skill 设计，并非 Meta 官方 Prompt 格式」；同时要求 Muse 不与 GPT Image 共用 JSON 模板。
- 编译器按 `assets/templates/*.json` 的 `model` 键自动注册，因此采用**单个扁平 `muse_image.json`**，而非设计稿中的嵌套 `muse_image/*.json`；仍满足「独立模板、互不影响」的约束，且零代码注册。

### 变更清单（旧值 → 新值）

| 位置 | 旧值 | 新值 |
|---|---|---|
| `assets/templates/muse_image.json` | 不存在 | 独立模板：8 用途、`kind_requires`、Muse 标签段；不含 `params` 用途 |
| `references/muse_image_rules.md` | 不存在 | 官方能力 vs 本 Skill 设计边界、八维分析、十类空间关系、八模式、参考图迁移边界、Anchor/多轮、评分与限制、API 边界 |
| `references/muse_image_sources.md` | 不存在 | 五个官方来源索引；注明 Google Research Muse 2023 仅用于同名区分，禁止交叉引用 |
| `scripts/prompt_compiler.py` | 5 用途；`KNOWN_FIELDS` 无 Muse 字段 | 8 用途；新增 `spatial_relationships`/`target_changes`/`reference_usage`/`feature_transfer`/`feature_exclusion`/`anchor_set`/`iteration_context`/`text_layout`；Muse 六项审查清单 |
| `assets/templates/gpt_image.json` | 5 用途 | **未改动**（`muse_template_independent` 断言兜底） |
| `tools/fixtures/semantic_muse_image.json` | 不存在 | 多参考图融合 + 10 条空间关系 + 迁移边界的字段范例 |
| `assets/examples/muse_image_example/output.md` | 不存在 | 由 `gen_examples.py` 确定性生成 |
| `tools/verify.py` | 45 项 | 49 项：Muse 独立模板 / 八任务模式 / 字段契约 / 审查清单 |
| `README.md` / `SKILL.md` / `model_mappings.md` / `prompt_framework.md` / `image_rules.md` | 十模型、45 项 | 十一模型、49 项；补 Muse 模式、空间关系与迁移边界说明 |
| `tools/install.py` | 豆包扁平指令不含 Muse 规则 | 纳入 `muse_image_rules.md`，豆包文案补 Muse Image 1.0 |
| `VERSION` / codex `plugin.json` | 2.1.0 | 2.2.0；description/longDescription 补 Muse，keywords 补 `muse` |

### 生效方式

随 `main` 发布。Muse 为**按需模型**（`--models muse_image`），不计入默认双版本；安装态与豆包包同步携带独立模板与规则。

### 验证（真实输出）

```text
[PASS] 模板层/Muse Image 独立模板 — Muse 八用途独立模板；无 params；GPT Image 五用途未被改动；两者 Prompt 文本不共用
[PASS] 模板层/Muse Image 八任务模式 — Muse 八用途互斥；编辑/Anchor/多轮/文字版式结构正确；参考图逐行；三个 Muse task_type 映射正确；冲突退出 4；GPT Image 不支持该用途退出 1
[PASS] 契约层/Muse Image 字段契约 — 编辑/Anchor/多轮/版式缺字段、空间关系类型、参考图角色、未知 task_type 均退出码 4 并指明原因
[PASS] 模板层/Muse Image 审查清单 — Muse 六项清单齐全；总分仍为六维加权和；非 Muse/GPT 不串用；缺空间关系与禁止迁移均标待复核；Markdown 置于评分之后
[PASS] 模板层/十一模型全量渲染 — 11 个模型模板均渲染出非空 Prompt（共 29 条）

== 验证汇总 ==
通过 49 / 49
全部通过 ✔
```

```text
$ python tools/gen_examples.py --check
[PASS] text_example/output.md 与生成结果一致
[PASS] image_example/output.md 与生成结果一致
[PASS] muse_image_example/output.md 与生成结果一致
[PASS] video_example/output.md 与生成结果一致
[PASS] story_example/output.md 与生成结果一致
```

### 偏差

- 设计稿建议 `assets/templates/image/muse_image/*.json` 多文件组织；编译器只自动注册扁平 `assets/templates/*.json`，故落为单文件 + 独立 `muse_image_rules.md`。模板与 GPT Image 仍完全独立，Muse 后续更新不影响 GPT Image 编译策略。
- Muse 资料中的 `subject_reference` 未新增第九种角色：人物映射 `identity_reference`，非人物/道具映射 `object_reference`。
- 三个 Muse 扩展 `task_type` 进入全局枚举，但仅 Muse 模板提供对应 kind；GPT Image 明确指定这些 `--kind` 时退出码 1。

### 回滚

`git revert` 本版本提交；`VERSION`/`plugin.json` 回到 2.1.0，删除 `muse_image*` 模板、规则、fixture 与示例，`prompt_compiler.py` 回退 5 用途与 45 项断言；豆包产物重新生成。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-15 Seedance 2.5 独立适配（v2.3.0）

### 摘要

新增字节跳动 Seedance 2.5 目标模型：独立视频模板与独立规则文件，支持六种任务模式（文生视频 / 首帧 / 首尾帧 / 全模态参考 / 视频编辑 / 视频延长）、素材角色契约、`params` 参数边界与 Seedance 专项审查清单；升级至 `2.3.0`，断言 49 → 53。

### 背景（基线）

- 适配前：`VERSION` 2.2.0、12 个模板文件（11 模型 + 评分报告）、`verify.py` 49/49。
- 官方（火山方舟）资料明确四种互斥场景：文生视频、首帧、首尾帧、全模态参考；编辑与延长属于全模态参考子任务。素材角色为 `first_frame` / `last_frame` / `reference_image` / `reference_video` / `reference_audio`。
- 按既有「模型独立编译」约定，不并入 Sora / Runway / Veo 模板：新建 `assets/templates/seedance.json` 与 `references/seedance_rules.md`，共用视频分镜与 `video_references` 底层契约。

### 变更清单（旧值 → 新值）

| 位置 | 旧值 | 新值 |
|---|---|---|
| `assets/templates/seedance.json` | 不存在 | 独立模板：7 用途（storyboard / image_to_video / first_last_frame / reference_to_video / video_edit / video_extend / params）、`kind_requires`、`clean_empty_label_lines` |
| `references/seedance_rules.md` | 不存在 | 资料边界、视频逆向维度、素材角色、六任务模式与互斥、分镜/首尾帧/编辑延长写法、声音、API 参数边界、评分与限制、官方 API 表、字段速查 |
| `references/seedance_sources.md` | 不存在 | 火山方舟官方文档索引与「官方能力 vs 本 Skill 设计」边界 |
| `scripts/prompt_compiler.py` | 5 个视频字段、无视频 task_type | 新增 `first_frame`/`last_frame`/`source_video`/`extension_plan`/`video_references`；6 个视频 `task_type` 映射；素材角色与互斥校验；Seedance 六项审查清单 |
| `assets/templates/sora2.json` / `runway.json` / `veo3.json` | 既有用途 | **未改动**（`seedance_template_independent` 断言兜底） |
| `tools/fixtures/semantic_seedance.json` | 不存在 | 三素材全模态参考（图/视频/音频）+ 3 镜头分镜 + 声音设计范例 |
| `assets/examples/seedance_example/output.md` | 不存在 | 由 `gen_examples.py` 确定性生成 |
| `tools/verify.py` | 49 项 | 53 项：Seedance 独立模板 / 六任务模式 / 字段契约 / 审查清单 |
| `README.md` / `SKILL.md` / `model_mappings.md` / `prompt_framework.md` / `video_rules.md` | 十一模型、49 项 | 十二模型、53 项；补 Seedance 六模式、素材角色与参数边界 |
| `tools/install.py` | 豆包扁平指令不含 Seedance 规则 | 纳入 `seedance_rules.md`，豆包文案补 Seedance 2.5 |
| `VERSION` / codex `plugin.json` | 2.2.0 | 2.3.0；description/longDescription 补 Seedance，keywords 补 `seedance` |
| `docs/RELEASE.md` / `tasks/todo.md` / `.github/workflows/verify.yml` | 49 项、十一模型 | 53 项、十二模型；新增阶段 3.6 |

### 生效方式

随 `main` 发布。Seedance 为**按需模型**（`--models seedance`），不计入默认双版本；安装态与豆包包同步携带独立模板与规则。

### 验证（真实输出）

```text
[PASS] 模板层/Seedance 独立模板 — Seedance 七用途独立模板；无图片用途；与 Sora/Runway/Veo 模板文本不共用
[PASS] 模板层/Seedance 六任务模式 — Seedance 六模式互斥；分镜/首帧/首尾帧/参考/编辑/延长结构正确；六个 task_type 映射正确；冲突退出 4；无模型支持退出 1
[PASS] 契约层/Seedance 字段契约 — 素材缺编号/角色/多角色/重复、首帧与参考互斥、编辑缺范围、字段类型、未知任务均退出码 4 并指明原因
[PASS] 模板层/Seedance 审查清单 — Seedance 六项清单齐全；总分仍为六维加权和；非 Seedance 不串用；缺分镜/声音/禁止迁移/参数越界均标待复核；Markdown 置于评分之后
[PASS] 模板层/十二模型全量渲染 — 12 个模型模板均渲染出非空 Prompt（共 30 条）

== 验证汇总 ==
通过 53 / 53
全部通过 ✔
```

```text
$ python tools/gen_examples.py --check
[PASS] text_example/output.md 与生成结果一致
[PASS] image_example/output.md 与生成结果一致
[PASS] muse_image_example/output.md 与生成结果一致
[PASS] video_example/output.md 与生成结果一致
[PASS] seedance_example/output.md 与生成结果一致
[PASS] story_example/output.md 与生成结果一致
```

### 偏差

- 官方素材角色含 `first_frame` / `last_frame`；本 Skill 用顶层 `first_frame` / `last_frame` 标量字段表达，`video_references` 只收 `reference_image` / `reference_video` / `reference_audio`，避免同一信息两处维护；互斥由编译器强制。
- 官方四种场景中的「编辑」「延长」在本 Skill 拆为独立 `video_edit` / `video_extend` 用途，仍归全模态参考任务，便于分别输出结构化字段。
- 参考素材上限（2.5：30 图 / 10 视频 / 10 音频）只写进规则文档，不在编译器做硬上限校验——接口接入面可能不同，交付时提示用户核对。

### 回滚

`git revert` 本版本提交；`VERSION`/`plugin.json` 回到 2.2.0，删除 `seedance*` 模板、规则、fixture 与示例，`prompt_compiler.py` 回退视频模式与 49 项断言；豆包产物重新生成。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-15 实拍图片/视频逐镜反推（v2.4.0）

### 摘要

新增「实拍镜头反推」分支：真实图片/实拍视频不再只还原整片风格，而是逐镜输出可直接粘贴的镜头 Prompt。脚本补齐确定性镜头信号（图片 EXIF/景深/黑边，视频首/中/末关键帧/运镜轴/逐镜色彩），新增 `references/shot_reverse_rules.md` 规则库与 `prompt_compiler.py shots` 子命令，按 Sora 2 / Runway / Veo 3.1 / Seedance 四个视频模板逐镜独立渲染；升级至 `2.4.0`，断言 53 → 57。

### 背景（基线）

- 适配前：`VERSION` 2.3.0、`verify.py` 53/53；视频模式只产出整片分镜脚本，图片模式只产出单帧 Prompt。
- 用户诉求：分析现实图片或视频，反推相关镜头提示词；粒度定为逐镜镜头卡 + 分镜总表；实现方式定为增强脚本 + 新增规则。
- 参考项目：`freestylefly/awesome-gpt-image-2`、`nidhinjs/prompt-master`、`wuyoscar/GPT-Image2-Skill`、`black-forest-labs/skills`、`Vieeeeeee/skills-gallery`、`MapleShaw/seedance2.0-prompt-skill`、`heloraai/Seedance2.0-Prompt-Optimizer-skill`、`happyhorse-prompt-studio`（Apache-2.0）、`ismoshushi/awesome-opus-video-skills`。仅借鉴「先固定可观测项、再写风格」「参数只进参数块」「逐镜独立可粘贴」等结构与工作流，未复制代码或整段文案。

### 变更清单（旧值 → 新值）

| 位置 | 旧值 | 新值 |
|---|---|---|
| `scripts/analyze_image.py` | 无镜头信号 | `shot_hints`：EXIF 焦段/35mm 等效/光圈/快门/ISO、景深推断、黑边、人脸；每项带 `confidence` |
| `scripts/analyze_video.py` | 每镜中点关键帧 | 每镜首/中/末关键帧、`motion_axes`（Z/X/Y/R）、`camera_move_hint`、逐镜主色、黑边、景别/机位提示 |
| `scripts/prompt_compiler.py` | 子命令 `compile|score|filter|all|scenes|validate-templates` | 新增 `shots`；`report_markdown` 支持自定义标题；每镜评分加自动近似依据 |
| `references/shot_reverse_rules.md` | 不存在 | 三条硬原则、两层工作流、镜头卡 12 维、证据与置信度、跨镜一致性、图片单帧反推、逐模型写法、自检清单、常见错误、来源边界 |
| `references/video_rules.md` | 分镜只讲整片 | 六节点明整片总览，逐镜工作指向 `shots` |
| `references/image_rules.md` | 无实拍参数说明 | 补 EXIF 优先、无 EXIF 用「约/疑似」、不编造数字 |
| `SKILL.md` | 三种输入模态 | 补「实拍镜头分支」、`shots` 用法、镜头审查清单与输出组织、退出码 1/4 特例 |
| `assets/templates/{sora2,runway,veo3,seedance}.json` | 无逐镜段 | 补 `shot_style` 渲染段（各模型独立） |
| `tools/fixtures/semantic_shot_reverse.json` | 不存在 | 10 秒 3 镜范本（远景推 / 中景过肩跟 / 特写仰拍固定） |
| `assets/examples/shot_reverse_example/output.md` | 不存在 | 由 `gen_examples.py` 确定性生成 |
| `tools/verify.py` | 53 项 | 57 项：图片镜头信号 / 视频镜头信号 / 逐镜渲染+评分 / 镜头卡契约与安全 |
| `README.md` / `tasks/todo.md` | 53 项、无镜头反推 | 57 项；补输入模态、`shots` 用法、目录树、验证表与扩展说明 |
| `VERSION` / codex `plugin.json` | 2.3.0 | 2.4.0；description/longDescription 补实拍逐镜反推，defaultPrompt 补一条 |

### 生效方式

随 `main` 发布。镜头反推为**按需分支**：仅在用户提供实拍素材并表达「反推镜头 / 复刻运镜 / 拆成分镜」时触发，不改变原有文本/图片/视频/剧本的默认输出。四个视频模板已含 `shot_style`，安装态与豆包包需重新生成后同步。

### 验证（真实输出）

```text
[PASS] 单元层/analyze_image 镜头信号 — EXIF 块 + 6 类 shot_hints（无 EXIF 时不猜焦段/景别）齐全
[PASS] 单元层/analyze_video 镜头信号 — 3 镜均含首/中/末关键帧、运镜轴、逐镜色彩、黑边与人脸提示
[PASS] 镜头反推/逐镜渲染+评分 — 3 镜 × 4 模型独立 Prompt；分镜表/评分/审查清单齐全；--dims 人工评分与 Markdown 排版通过
[PASS] 契约层/镜头卡字段与安全 — 编号/字段/枚举/运镜/时长/锚点/证据/焦段 10 类错误退出 4；图片多镜退出 4；无 shot_style 退出 1；黑名单退出 5 且 sanitize 放行
[PASS] 一致性/README 断言数 — README 断言数 57 与实际一致

== 验证汇总 ==
通过 57 / 57
全部通过 ✔
```

```text
$ python tools/gen_examples.py --check
[PASS] text_example/output.md 与生成结果一致
[PASS] image_example/output.md 与生成结果一致
[PASS] muse_image_example/output.md 与生成结果一致
[PASS] video_example/output.md 与生成结果一致
[PASS] seedance_example/output.md 与生成结果一致
[PASS] story_example/output.md 与生成结果一致
[PASS] shot_reverse_example/output.md 与生成结果一致
```

### 偏差

- 镜头卡字段 12 维为设计命名，与任何参考项目的字段名不一一对应；`evidence` 统一用 `observed:` / `inferred:` / `unknown:` 前缀。
- 运镜按设备无关的四个轴（Z 推拉 / X 水平摇移 / Y 升降 / R 旋转）编码，复合运镜用 `+` 连接且最多两轴；`固定` 不与其它轴组合。
- 图片反推严格单镜（`shots` 恰好 1 项），视频可多镜；`total_duration` 与逐镜时长之和允许 0.5 秒误差。
- `lens` / `focus` 无法从画面确认时必须省略，不写「unknown」；自动评分标注「自动近似：依据镜头卡字段完整度」，不冒充人工评审。

### 回滚

`git revert` 本版本提交；`VERSION`/`plugin.json` 回到 2.3.0，删除 `shot_reverse_rules.md`、`semantic_shot_reverse.json` 与 `shot_reverse_example/`，`prompt_compiler.py` 移除 `shots` 子命令与镜头校验，模板移除 `shot_style` 段，`verify.py` 回退 53 项；豆包产物重新生成。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-16 实拍镜头反推覆盖六个图片模型（v2.4.1）

### 摘要

v2.4.0 只让四个视频模型支持逐镜渲染，单张实拍图反推仍要人工换算成图片模型。v2.4.1 给 Midjourney / SD 3.5 / FLUX.2 / GPT Image / Muse Image / Nano Banana 六个图片模板各加单帧 `shot_style`，`shots` 未指定模型时按 `modality` 取默认集合，图片反推一次输出六份独立 Prompt；断言 57 → 58，版本升至 2.4.1。

### 背景（基线）

- 适配前：`VERSION` 2.4.0、`verify.py` 57/57；`shot_style` 仅存在于 `sora2/runway/veo3/seedance` 四个视频模板，图片模板无逐镜段。
- 用户诉求：真实图片反推也应直接产出各图片模型可粘贴的 Prompt，而非只给视频 Prompt 再手改。
- 参考项目：图片六款模板结构沿用既有 `image_rules.md` 与 v2.4.0 已记录的参考项目边界（仅借鉴「规格书分字段」「先固定可观测项再写风格」），未复制第三方代码或文案。

### 变更清单（旧值 → 新值）

| 位置 | 旧值 | 新值 |
|---|---|---|
| `scripts/prompt_compiler.py` | `shots` 默认固定四视频模型；图片模板禁止 `shot_style` | `VIDEO_SHOT_MODELS` / `IMAGE_SHOT_MODELS`；按 `modality` 选默认；图片模板允许 `shot_style` |
| `assets/templates/midjourney.json` | 无逐镜段 | `shot_style`：`/imagine prompt:` + 景别/机位/运镜/锚点/焦段 + `--ar/--v` |
| `assets/templates/stable_diffusion.json` | 无 | `shot_style`：`Positive:` 标签串 + `Negative:` + 采样参数 |
| `assets/templates/flux2.json` | 无 | `shot_style`：中文自然语言，保持无负向 |
| `assets/templates/gpt_image.json` | 无 | `shot_style`：分字段规格书 + 单帧约束 |
| `assets/templates/muse_image.json` | 无 | `shot_style`：完整中文句 + Lens/Focus/Avoid/画幅 |
| `assets/templates/nano_banana.json` | 无 | `shot_style`：分字段规格书 + Lens/Focus/Resolution |
| `tools/fixtures/semantic_shot_reverse_image.json` | 不存在 | 单张实拍图金标（特写/平拍/固定/3s、EXIF 85mm、f/1.8） |
| `tools/verify.py` | 57 项；无 shot_style 用例用 `--models mj` | 58 项：新增图片六模型渲染；用例改用文本模型 `deepseek` |
| `references/prompt_framework.md` 2.6 | 只列视频模型 | 补图片模型、模态默认集合、退出码 1 说明 |
| `references/shot_reverse_rules.md` 第七节 | 四款视频写法 | 补六款图片写法与单帧共用约束 |
| `references/image_rules.md` | 只讲 EXIF 参数 | 补一句：图片 `shots` 默认六款图片模型独立输出 |
| `references/model_mappings.md` 第 1 节 | 无镜头反推行 | 补「实拍镜头反推」默认模型行 |
| `SKILL.md` | 默认模型只写四视频 | 默认模型表、`shots` 用法改为按模态 |
| `README.md` / `tasks/todo.md` / `docs/RELEASE.md` / CI | 57 项、视频四模型 | 58 项；1.2/3.4/3.6/验证表与发布检查同步补图片六模型 |
| `VERSION` / codex `plugin.json` | 2.4.0 | 2.4.1；description 补图片六模型逐镜 |

### 生效方式

随 `main` 发布。安装态与豆包包需重新生成后同步。图片反推仍走同一 `shots` 子命令：`--analysis` 传图片镜头卡 JSON，不指定 `--models` 时输出六份独立 Prompt；显式指定任意图片模型子集也有效。

### 验证（真实输出）

```text
[PASS] 镜头反推/图片六模型渲染 — 单张实拍图 → 六图片模型独立 Prompt；默认图片模型、EXIF 焦段、正负向/规格书结构与审查清单通过
[PASS] 一致性/README 断言数 — README 断言数 58 与实际一致

== 验证汇总 ==
通过 58 / 58
全部通过 ✔
```

`python tools/gen_examples.py --check` 7 项全 PASS（模板新增 `shot_style` 不影响既有金标）。

### 偏差

- 图片模板不含时长/声音/衔接占位符，单帧 Prompt 不输出视频句式；`total_duration` 省略时编译器按 `duration_s` 补齐（默认 3 秒）。
- Muse 与 GPT Image 的图片 `shot_style` 各自独立，不共用文本；FLUX.2 继续禁用负向。
- 六个图片模板的 Prompt 语序按各模型既有 `image_rules.md` 偏好设计，不追求六款逐字对齐。

### 回滚

`git revert` 本版本提交；`VERSION`/`plugin.json` 回到 2.4.0，六个图片模板移除 `shot_style`，`prompt_compiler.py` 恢复固定四视频默认与图片模板禁用 `shot_style`，删除 `semantic_shot_reverse_image.json`，`verify.py` 回退 57 项并恢复 `--models mj` 用例；豆包产物重新生成。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-16 模板对齐九个参考项目的审计（v2.4.1 补充）

### 摘要

对照九个第三方提示词项目（图片五、视频四）逐模板审计 12 个模板与相关规则。按「只借原则、不抄文本」补三处缺口：FLUX.2 在无负向能力时的文字/水印约束替代句、Nano Banana 的约束行、Seedance 参数边界中「正文可写自然语言时长/画幅意图」的说明。其余原则已在此前版本落地，未覆盖项列为已知缺口。

### 背景（基线）

- 审计时点：v2.4.1，`python tools/verify.py` 58/58；12 个模板、7 份金标示例。
- 参考项目（仅作设计参考）：
  - 图片：freestylefly/awesome-gpt-image-2、nidhinjs/prompt-master、wuyoscar/GPT-Image2-Skill、black-forest-labs/skills、Vieeeeeee/skills-gallery。
  - 视频：MapleShaw/seedance2.0-prompt-skill、heloraai/Seedance2.0-Prompt-Optimizer-skill、happyhorse-prompt-studio、ismoshushi/awesome-opus-video-skills。
- 提炼的原则：结构化规格书 + 逐项约束；先可观察事实、后风格判断；编辑/重绘任务拆分；模型专属语法与参数边界；示例驱动；逐镜可粘贴；API 参数只进 `params`；证据标注。

### 变更清单

| 文件 | 旧值 | 新值 |
| --- | --- | --- |
| `assets/templates/flux2.json` | `positive` / `style_transfer` 无文字水印约束；约束句前直接跟 `{reference_note}` | 三种写法都含「不在画面中额外添加文字、水印或 logo。」；约束句移到 `{reference_note}` 之前，参考图为空时不留孤立标点 |
| `assets/templates/nano_banana.json` | `image.prompt` 无约束行；`image.edit` 只写保留项 | `image.prompt` 末尾增加 `Constraints: render any text exactly as written; do not add extra text, logos, or watermarks.`；`image.edit` 补同一约束；`shot_style.shot_suffix` 增加同一行 |
| `references/seedance_rules.md` §0、§9 | 「参数只进 params，不写指令或后缀」易被读成正文不得提时长/画幅 | 明确：键值与 `--rs/--rt/--dur` 后缀不进正文；正文可用自然语言交代时长与画幅意图；不得伪装成 API 参数 |
| `references/video_rules.md` §8 | 同上，表述含混 | 同步为「键值写进 params；正文可写自然语言意图」 |
| `tools/verify.py` | 模板契约未校验这两类约束 | `templates_contract` 增加 FLUX「不额外添加文字」与 Nano `Constraints` 行两条断言（总数仍 58） |

### 覆盖矩阵（原则 → 落点）

| 原则 | 已落地 | 缺口 |
| --- | --- | --- |
| 结构化规格书 + 逐项约束 | `gpt_image`、`muse_image`、`nano_banana` 分字段；Seedance 六段式；FLUX/Nano 约束句 | MJ/SD/FLUX 仍为自然语言长句，不强加字段标签（有意为之） |
| 先可观察、后风格 | 镜头卡 `subject_action` 在前；`image_rules.md` 七段结构；分镜按「主体→动作→场景」 | 部分视频模板的 `style` 占位符仍靠前，未逐模板重排 |
| 编辑/重绘拆分 | `gpt_image` recreate/edit；`muse_image` recreate/edit；`nano_banana` edit；Seedance `video_edit`/`video_extend` | MJ/SD/FLUX 仅有 `style_transfer`，无独立编辑模式 |
| 模型专属语法与参数边界 | MJ `--ar`、SD 正负向+采样参数、FLUX 无负向、Seedance `params` 块与后缀禁令 | —— |
| 示例驱动 | 7 份金标（文本/图片/Muse/视频/Seedance/剧本/镜头反推） | 未为 12 个模型逐一建示例 |
| 逐镜可粘贴 | `shots` 子命令覆盖视频四 + 图片六，每模型一段 | —— |
| API 参数不进正文 | 全部模板 `params` 独立；Seedance 规则补充 | —— |
| 证据标注 | 镜头卡 `observed:` / `inferred:` / `unknown:`，`unknown` 不入正文 | —— |

### 生效方式

随 `main` 发布，无需重装；豆包产物已重新生成（`python tools/install.py --platform doubao`）。

### 验证（真实输出）

```text
[PASS] 一致性/README 断言数 — README 断言数 58 与实际一致

== 验证汇总 ==
通过 58 / 58
全部通过 ✔
```

`python tools/gen_examples.py --check` 7 项全 PASS（金标未变）。FLUX.2 渲染修复后片段：

```text
... masterpiece. 文字「APS 2077」. 不在画面中额外添加文字、水印或 logo。参考图 1：人物姿态；参考图 2：霓虹配色
```

### 偏差

- 三个参考项目里的整段 Prompt 范本未复制；只采用结构原则，措辞按本仓库中文契约重写。
- 未为 12 个模型逐一补金标：四视频 + 六图片已有 `shots` 断言覆盖，新增逐模型示例会显著抬高维护成本，暂不做。
- `deepseek` / `gpt4_claude` 为纯文本模型，九个参考项目不含同类，未纳入对照。

### 回滚

`git revert` 本次提交；三条模板改动回到 v2.4.1 状态，`verify.py` 移除两条约束断言，两份规则文件的措辞恢复原文；重跑 `python tools/install.py --platform doubao`。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-17 跨平台升级甲阶段：IR 1.0 契约与三注册表（v2.5.0）

### 摘要

落地冻结方案《2026-11-15-跨平台工作流升级方案》甲阶段：新增可选的 IR 1.0 信封层（11 模块）与 `ir validate` 校验，新增确定性注册表生成器并产出三份 `config/*.json`，`verify.py` 增加 4 项断言（58 → 62）。旧分析 JSON 不写 IR 字段时行为与 v2.4.1 完全一致，模板渲染与 7 份金标示例逐字节未变。

### 背景（基线）

- 实施前：v2.4.1，`python tools/verify.py` 58/58；12 个模型模板、7 份金标示例；无 `config/` 目录、无 IR 契约。
- 方案冻结于 2026-11-15，甲阶段目标为「先定契约，再接平台」：IR 只做表达能力扩展，不做第二套评分或导入导出。
- 版本偏差：方案 §11 建议甲阶段发 2.4.0（按当时 2.3.0/53 项估算），实际基线已是 2.4.1/58，故本阶段发 **2.5.0**，避免与已发布版本撞号。

### 变更清单

| 文件 | 旧值 | 新值 |
| --- | --- | --- |
| `prompt-reverse-engineer-skill/references/ir_spec.md` | 不存在 | 新增：IR 1.0 唯一权威。11 模块表、`project/assets/workflow/confidence` 字段契约、资产 `kind` 与 sha256、路径只允许 basename、最大嵌套深度 5、校验规则与退出码 4、置信度 `observed/inferred/unknown` 语义、最小示例、非目标与变更控制 |
| `prompt-reverse-engineer-skill/scripts/prompt_compiler.py` | 仅 render/score/filter/scenes/shots | 新增 `IR_VERSION/IR_MODULES/IR_MAX_DEPTH/IR_ASSET_KINDS/IR_CONFIDENCE_STATUS/IR_WORKFLOW_FORMATS` 常量、`ir_depth()`、`ir_errors()` 与 `ir validate` 子命令；仅在字段存在时校验，`semantic_analysis` 仍为扁平契约 |
| `tools/gen_registry.py` | 不存在 | 新增：从模板与 `creative-platforms/*/capability_map.json` 确定性生成注册表；键排序、LF、无时间戳/绝对路径；`--check` 逐字节比对；L2 由 `default_params` 非空推导 |
| `config/model_registry.json` | 不存在 | 12 个模型（`gpt4_claude` 为 L1，其余 11 个 L2），含别名、模态、任务模式、默认参数、来源模板与来源文档 |
| `config/platform_registry.json` | 不存在 | 空列表（首批平台留待乙阶段），结构已定 |
| `config/capability_registry.json` | 不存在 | L1–L4 定义 + 12 模型能力声明；L3 统一 `readonly_only`，L4 统一 `none` |
| `tools/verify.py` | 58 项 | 62 项：IR 契约（旧 JSON 通过 + 合法 IR 通过 + 6 类错误退出 4）、注册表可复现（`--check`、12 模型、无绝对路径）、注册表能力声明（L3 只读/L4 不支持/来源闸门）、IR 文档契约（11 模块 + SKILL/README 同步） |
| `prompt-reverse-engineer-skill/SKILL.md` | 无 IR 说明 | 步骤 3/4、§5 错误处理、§6 脚本表与退出码、§7 参考索引补 IR 契约 |
| `README.md` | 无 IR/注册表章节 | 新增 §1.5；目录树补 `ir_spec.md`、`config/`、`gen_registry.py`；§4.3/4.4 补契约与维护规则；验证表与断言数 62 |
| `VERSION` / codex `plugin.json` | 2.4.1 | 2.5.0 |
| 豆包产物 | v2.4.1 包 | 重新生成：`doubao_instruction.md`、包内 SKILL 与 `prompt_compiler.py`、新增 `references/ir_spec.md`、zip |

### 生效方式

随 `main` 发布，无需重装；豆包产物已重新生成（`python tools/install.py --platform doubao`）。模型或平台清单变动后运行 `python tools/gen_registry.py`，CI/验证用 `--check`。

### 验证（真实输出）

```text
$ python tools/verify.py
[PASS] 一致性/README 断言数 — README 断言数 62 与实际一致
[PASS] 一致性/注册表可复现 — 3 份注册表与源文件逐字节一致；12 模型；无绝对路径
[PASS] 一致性/注册表能力声明 — L3 只读/L4 不支持；12 模型均声明 L1 且不支持 L4；平台过来源闸门
[PASS] 一致性/IR 文档契约 — ir_spec 覆盖 11 模块与校验规则；SKILL/README 已同步

== 验证汇总 ==
通过 62 / 62
全部通过 ✔
```

```text
$ python prompt-reverse-engineer-skill/scripts/prompt_compiler.py ir validate --analysis tools/fixtures/semantic_image.json
{"command": "ir validate", "errors": [], "ir_version": "1.0", "modules": ["project", "subject", "scene", "visual", "shot", "prompt", "reference", "model", "parameters", "workflow", "assets"], "schema_version": "1.0", "tool": "prompt_compiler.py", "valid": true}
退出码 0
```

```text
$ python tools/gen_registry.py --check
注册表一致：3 份，模型 12 / 平台 0
退出码 0
```

`python tools/gen_examples.py --check` 7 项全 PASS（四模态 + Muse/Seedance + 剧本 + 镜头反推输出未变）。IR 反例由 `verify.py` 覆盖：`ir_version` 非 1.0、非空 `workflow` 缺 `nodes`、资产缺 64 位 sha256、资产路径含 `C:/`、置信度状态非法、嵌套深度 > 5，均退出码 4 且报错含对应关键词。

### 偏差

- 版本号由方案建议的 2.4.0 改为 2.5.0（基线已 2.4.1）。
- 新增 4 项断言（方案允许 4–6），覆盖契约、可复现、能力声明、文档同步四个面，未再拆分。
- `platform_registry.json` 暂为空：乙阶段才引入首批三平台；生成器与来源闸门已就位，届时只加 `capability_map.json`，不改代码。
- L2 判定取模板 `default_params` 是否非空；`gpt4_claude` 为纯文本模型，按 L1 处理。

### 回滚

`git revert` 本次提交；删除 `config/` 三份注册表与 `tools/gen_registry.py`，移除 `ir_spec.md` 与 `prompt_compiler.py` 的 IR 常量/子命令，`verify.py` 删除 4 项断言并恢复 58，版本回到 2.4.1，重跑 `python tools/install.py --platform doubao`。旧分析 JSON 与模板未改，无数据迁移；已写 IR 字段的 JSON 在旧版会被当作未知顶层字段忽略。

### 脱敏

本文不含密钥与绝对用户路径。

## 2026-11-17 跨平台升级乙阶段：creative-platforms 三平台与安装物化（v2.6.0）

### 摘要

落地冻结方案乙阶段：新增根目录 `creative-platforms/`，为 ComfyUI / Runway / LibTV 建立五件套（平台规则、能力声明、Prompt 映射、节点映射、官方来源）；`gen_registry.py` 加严来源闸门并校验 schema，`platform_registry.json` 由空变为 3 个 `verified` 平台；`install.py` 把平台资料物化到技能实例的 `platforms/`（junction 子链接 / copy 复制 / 豆包包内物理复制），缺失或失败只告警并降级为通用 Prompt。`verify.py` 新增 3 项平台断言（62 → 65），全部离线通过。

### 背景（基线）

- 实施前：v2.5.0，`python tools/verify.py` 62/62；`config/platform_registry.json` 为空列表；仓库无 `creative-platforms/`，只有 Agent 宿主适配层 `platform-adapters/`。
- 方案 2026-11-15 冻结，乙阶段范围：三平台五件套、`capability_map.json` schema、来源闸门、安装物化；不做 L4、不解析闭源工程、不做工作流导入导出（丙阶段）。
- 版本偏差：方案按甲阶段可能发 2.4.0 估算乙为 2.5；实际甲已发 2.5.0，故乙发 **2.6.0**。

### 变更清单

| 文件/目录 | 旧值 | 新值 |
| --- | --- | --- |
| `creative-platforms/README.md` | 不存在 | 新增：与 `platform-adapters/` 的命名区分、目录树、状态表、L1–L4 边界、Agent 消费路径、来源闸门与更新流程 |
| `creative-platforms/comfyui/` | 不存在 | 五件套，L2：官方 Workflow JSON 1.0/0.4 与 API 格式已读；UI JSON / API JSON / Export Workflow (API) 已验证；节点类名标 `manual`；工作流解析标 `unverified`（留丙） |
| `creative-platforms/runway/` | 不存在 | 五件套，L1：Workflows 定义、Input/Media Model/LLM 节点类别、单端点、Recipes、计费已验证；工作流文件格式、节点参数、音频链标 unknown |
| `creative-platforms/libtv/` | 不存在 | 五件套，L1：画布 / Agent BETA / 3D-BOX、五类生成能力、6 大场景模板、TV Director、Plugin 安装方式已验证；节点结构、项目文件、公开 REST API 明确 unknown |
| `tools/gen_registry.py` | 仅要求 verified 有非空 sources | 新增 `check_sources` / `check_tagged_list`：来源条目必须含 title/url/accessed/official/verified；`verified` 至少 1 条 `official` 且 `verified`（已读正文）；`features`/`models` 的 `confidence` 限 `verified/unverified/manual`；校验目录名与 platform 一致、日期格式、`import_export`/`api`/`dependencies` 为对象 |
| `config/platform_registry.json` | 空列表 | 3 个平台，含能力等级、置信度条目、官方来源与 `source_path` |
| `config/capability_registry.json` | 仅模型 | 新增 3 平台能力声明（L2 含配置适配；L1 仅 Prompt），统一 `unsupported: L3_workflow_generation / L4_automation` |
| `tools/install.py` | 不处理平台资料 | 新增 `ensure_platform_link` / `copy_platforms`：junction 模式建 `SKILL_SRC/platforms -> creative-platforms`；copy 模式复制到实例 `platforms/`；豆包包始终复制；源缺失/创建失败记 `[WARN]` 并降级。修复 `junction_target`：`dir <junction>` 会跟随目标目录而取不到标记，改用 `os.readlink`（兼容 `\\?\` 前缀），失败再列父目录。新增 `clear_dir`：清理目标是 junction 时只删链接，避免 `shutil.rmtree` 跟随删除实体（`--force` 与豆包重新生成共用） |
| `.gitignore` | 无 | 新增 `prompt-reverse-engineer-skill/platforms`（安装物化链接不入库） |
| `tools/verify.py` | 62 项 | 65 项：`平台层/五件套与能力声明`、`平台层/注册表闸门`、`安装层/平台资料物化`（junction + copy + 豆包 zip 三路） |
| `prompt-reverse-engineer-skill/SKILL.md` | 无平台分支 | §1 补 ComfyUI/Runway/LibTV 自然语言触发；§4 补平台映射输出六项；§5 补 `platforms/` 不可读、要求自动执行、节点/字段未公开三行处理；§7 补 `platforms/<平台 ID>/` 索引 |
| `README.md` | 无平台章节 | §1.5 补创作平台骨架；§2.2 补安装物化与降级；目录树补 `creative-platforms/` 与 `platforms/`；验证表新增「平台层」；断言数 65 |
| `docs/RELEASE.md` | 58 项、历史止于 v2.4.1 | 65 项；发布前补注册表 `--check`、豆包包含 `platforms/`、五件套与来源闸门；历史补 v2.5.0 / v2.6.0 |
| `platform-adapters/README.md` | 仅宿主说明 | 开头补与 `creative-platforms/` 的职责区分与安装物化说明 |
| `VERSION` / codex `plugin.json` | 2.5.0 | 2.6.0；描述补三平台映射（只映射、不自动执行） |
| 豆包产物 | v2.5.0 包 | 重新生成：包内新增 `platforms/`（16 个条目），`SKILL.md` / `zip` 同步 |

### 生效方式

随 `main` 发布，无需重装；junction 安装（Windows 默认）会自动出现 `platforms/`，copy 模式与豆包包需重跑 `python tools/install.py`。平台资料变更后依次跑 `gen_registry.py` 与 `verify.py --filter 平台`。

### 验证（真实输出）

```text
$ python tools/verify.py --filter 平台
[PASS] 平台层/五件套与能力声明 — 三平台五件套齐全；schema/置信度/官方来源闸门通过
[PASS] 平台层/注册表闸门 — 3 平台过闸门进入注册表；L1-L3；均声明不支持生成/L4；无绝对路径
[PASS] 安装层/平台资料物化 — junction/copy/豆包包均物化 platforms/，三平台资料可读且幂等

== 验证汇总 ==
通过 3 / 3
全部通过 ✔
```

```text
$ python tools/verify.py
...
[PASS] 一致性/README 断言数 — README 断言数 65 与实际一致
[PASS] 一致性/注册表可复现 — 3 份注册表与源文件逐字节一致；12 模型；无绝对路径
[PASS] 一致性/注册表能力声明 — L3 只读/L4 不支持；12 模型均声明 L1 且不支持 L4；平台过来源闸门
[PASS] 平台层/五件套与能力声明 — 三平台五件套齐全；schema/置信度/官方来源闸门通过
[PASS] 平台层/注册表闸门 — 3 平台过闸门进入注册表；L1-L3；均声明不支持生成/L4；无绝对路径
[PASS] 安装层/平台资料物化 — junction/copy/豆包包均物化 platforms/，三平台资料可读且幂等

== 验证汇总 ==
通过 65 / 65
全部通过 ✔
```

```text
$ python tools/gen_registry.py --check
注册表一致：3 份，模型 12 / 平台 3
退出码 0
```

安装冒烟（临时根目录）实际输出：

```text
[OK] platforms: junction ...\prompt-reverse-engineer-skill\platforms -> ...\creative-platforms
[OK] claude: junction ...\.claude\skills\prompt-reverse-engineer -> ...\prompt-reverse-engineer-skill
[SKIP] platforms: ... 已指向 creative-platforms，跳过
[OK] claude: copytree ...\creative-platforms -> ...\skills\prompt-reverse-engineer\platforms
```

豆包包实测：zip 共 57 个条目，其中 `prompt-reverse-engineer/platforms/` 16 个条目（README + 三平台各五件套）。

### 偏差

- LibTV 判为 `verified`：官网首页、AI 视频落地页、插件页均已实际读取；但画布节点、项目文件格式、公开 REST API 官方未公开，`capability_map.json` 中逐项标 `unknown`，不据此推断。官方飞书使用指南客户端渲染、抓取为空，未作为依据。
- Runway 帮助中心自动化访问 403，未读取正文；只采用 `dev.runway.com/workflows` 与 `runwayml.com/workflows` 两个已读官方页面。
- ComfyUI 只完成 L2 与格式核验，工作流只读解析按方案留到丙阶段，`features` 中明确标 `unverified`。
- 修复了既有 `junction_target` 的缺陷（Windows 下 `dir <junction>` 跟随目标导致无法识别同源）；此前安装冒烟只断言链接存在与「出现过 SKIP」，未暴露该问题。修复后二次安装才真正逐项 SKIP。
- copy 模式的 codex 分支未单测：仓库内 `skills/` 是既有 junction，copy 模式按既有逻辑跳过；claude copy 分支已覆盖平台资料复制。

### 回滚

`git revert` 本次提交；删除 `creative-platforms/` 与 `config/` 三份注册表（回到 empty 需同时回滚 `gen_registry.py` 闸门改动），移除 `install.py` 的平台物化与 `junction_target` 修复，`verify.py` 删除 3 项并恢复 62，版本回到 2.5.0，重跑 `python tools/install.py --platform doubao`。已物化的 `prompt-reverse-engineer-skill/platforms` 链接需手动删除（`rmdir`，不跟随目标）。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径；验证输出中的安装路径以 `...` 省略。

## 2026-11-17 跨平台升级丙阶段：ComfyUI 工作流只读解析与兼容报告（v3.0.0）

### 摘要

落地冻结方案丙阶段「工作流最小闭环」：新增 `analyze_workflow.py`，只读解析 ComfyUI **API JSON** 与 **UI JSON**，输出 IR 兼容的 `workflow` 模块（节点、连线、模型、素材、参数、自定义节点依赖、问题、置信度）；`prompt_compiler.py` 新增 `workflow` 子命令，按目标平台输出 `compatible / degraded / incompatible` 逐节点结论、文件迁移结论与手工重建步骤，固定 `importable_output: false`；`ir validate` 扩展校验工作流载荷。`verify.py` 新增 4 项断言（65 → 69），全部离线通过。版本升至 **3.0.0**（新增输入模态，属能力级变更）。

### 背景（基线）

- 实施前：v2.6.0，`python tools/verify.py` 65/65；`creative-platforms/` 三平台五件套已就绪，但 ComfyUI 工作流只读解析标 `unverified`，无工作流脚本、无兼容性报告。
- 方案 2026-11-15 冻结，丙阶段范围：ComfyUI API/UI JSON 只读解析、工作流 IR 校验、跨平台兼容报告；不做 L4、不解析闭源工程、不生成/导入/导出可导入工作流。
- 验收基线：合法 JSON 可解析；悬空连线/成环退出码 4；未知节点只警告不阻断；输出逐字节幂等；不产出可导入工作流。

### 变更清单

| 文件/目录 | 旧值 | 新值 |
| --- | --- | --- |
| `prompt-reverse-engineer-skill/scripts/analyze_workflow.py` | 不存在 | 新增：只读解析 ComfyUI API JSON / UI JSON；输出 `schema_version/tool/modality/ir_version/input/project/assets/workflow/confidence`；节点上限 5000、连线上限 20000；悬空连线/成环/结构非法退出码 4；未知节点记入 `issues` 并警告，不阻断 |
| `tools/fixtures/workflow_api.json` | 不存在 | 新增中性样例：11 节点 / 15 连线；KSampler、Checkpoint、EmptyLatent、正负 CLIP、VAEDecode、SaveImage、LoRA、LoadImage、ControlNet 加载与应用 |
| `tools/fixtures/workflow_ui.json` | 不存在 | 新增中性样例：10 节点 / 10 连线，`version: 0.4`；含已知自定义节点 `ImageResizeKJ` 与未知节点 `MysteryNodeXP` |
| `prompt-reverse-engineer-skill/scripts/prompt_compiler.py` | 仅 `compile / score / ir validate` 等 | 新增 `workflow --report --target [--platforms-dir] [--format json|text|md] [-o]`；新增工作流 IR 校验（节点 ID 重复、端点不存在、连线成环、`parameters[].node` 无效、`from_output/to_slot` 非负整数均退出码 4）；未知目标退出码 1，报告不可读退出码 2 |
| `creative-platforms/{comfyui,runway,libtv}/workflow_mapping.json` | 仅 `nodes[].unified` 等 | 新增 `category_aliases`：`negative_prompt → text_prompt`；`model_loader/sampler/decode/resolution → image_model/video_model`（按模态优先）；Runway 输出类 → `output`；LibTV 输出类 → `image_asset / video_model / editing`；LoRA/ControlNet/放大/条件控制不设等价项 |
| `creative-platforms/comfyui/capability_map.json` | 工作流解析 `unverified` | 改为 `verified`，注明只读解析与兼容报告；降级项补「无效工作流退出码 4」「不生成/不导入/不导出可导入工作流，不调用平台 API」 |
| `creative-platforms/comfyui/platform_rules.md` | 声明「v1 不解析工作流文件」 | 改为自 3.0.0 起提供 L3 只读分析；补非法工作流与跨平台迁移的处理规则；安全边界保持不执行、不安装、不下载 |
| `creative-platforms/README.md` | L3 标为未提供 | L3 行改为 3.0.0 起由 `analyze_workflow.py` / `prompt_compiler.py workflow` 提供，仍不生成/导入/导出 |
| `prompt-reverse-engineer-skill/references/ir_spec.md` | 仅甲阶段 IR 契约 | §4.3 补全 `workflow` 字段表与校验规则；新增 §4.3.1 命令、格式边界、兼容报告、`category_aliases` 与平台资料查找顺序；退出码表补工作流项 |
| `prompt-reverse-engineer-skill/SKILL.md` | 无工作流分支 | 新增「工作流分支」触发与边界（拆解 ComfyUI 工作流、迁移到 Runway 要改什么、列出缺失自定义节点与模型）；脚本表补 `analyze_workflow.py`；退出码 4 补工作流结构错误 |
| `README.md` | 无工作流输入 | 输入表补 ComfyUI 工作流；架构与 §1.5 补只读解析与兼容报告；目录树补脚本与 fixtures；断言数 69 |
| `tools/verify.py` | 65 项 | 69 项：`工作流层/只读解析与 IR`、`负向层/工作流结构错误`、`工作流层/跨平台兼容报告`、`一致性/工作流文档与能力声明`；平台骨架校验 `category_aliases` 目标存在 |
| `docs/RELEASE.md` | 65 项、历史止于 v2.6.0 | 69 项；历史补 v3.0.0 |
| `tasks/todo.md` | 丙未开始 | 丙勾选：解析器、编译器、IR 校验、别名与能力、4 项断言/69 总数、文档与豆包 |
| `VERSION` / codex `plugin.json` | 2.6.0 | 3.0.0；描述补 ComfyUI API/UI 只读解析与兼容报告，不生成可导入工作流、不自动执行 |
| 豆包产物 | v2.6.0 包 | 重新生成：`scripts/` 增至 7 个（含 `analyze_workflow.py`），`SKILL.md`、`references/ir_spec.md`、`platforms/` 与 zip 同步 |

### 生效方式

随 `main` 发布，无需重装。CLI 直接可用：

```bash
python prompt-reverse-engineer-skill/scripts/analyze_workflow.py workflow.json -o wf.json
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py workflow --report wf.json --target runway --format md
python prompt-reverse-engineer-skill/scripts/prompt_compiler.py ir validate --analysis wf.json
```

平台资料按 `--platforms-dir` → 安装态 `platforms/` → 仓库 `creative-platforms/` 查找；缺失或 `draft` 时整体保守降级。

### 验证（真实输出）

工作流断言：

```text
$ python tools/verify.py --filter 工作流
[PASS] 工作流层/只读解析与 IR — API 11 节点/15 连线/3 模型；UI 10/10/2 自定义+1 未知警告；IR 通过；输出幂等；仅文件名
[PASS] 负向层/工作流结构错误 — 悬空连线/成环/UI 断链/坏 JSON 均退出码 4；IR 重复 ID/环/端点错误退出码 4
[PASS] 工作流层/跨平台兼容报告 — comfyui 原生 11/11；UI 2 降级；runway 3 不兼容 + 手工步骤；libtv 全降级；未知目标退出 1；幂等；无绝对路径；draft 保守
[PASS] 一致性/工作流文档与能力声明 — IR 规范/SKILL/README 同步；ComfyUI 能力已 verified；三平台别名表齐全

== 验证汇总 ==
通过 4 / 4
全部通过 ✔
```

解析实测（API 样例）：

```json
{
  "format": "comfyui_api",
  "nodes": 11,
  "links": 15,
  "models": 3,
  "assets": 1,
  "custom_nodes": 0,
  "stats": {
    "node_count": 11, "link_count": 15, "model_count": 3,
    "asset_count": 1, "custom_node_count": 0, "unknown_node_count": 0
  },
  "issues": [],
  "confidence": {
    "workflow": {"status": "observed", "basis": "只读解析文件结构；节点与连线计数来自文件本身"},
    "assets": {"status": "observed", "basis": "从加载节点参数提取文件名；文件内容与可读性未校验"},
    "model": {"status": "inferred", "basis": "按加载节点参数名推断模型文件；本机可用性需人工确认"},
    "parameters": {"status": "observed", "basis": "读取节点输入或 widgets_values；未执行连线求值"}
  }
}
```

解析实测（UI 样例）：

```json
{
  "format": "comfyui_ui",
  "version": "0.4",
  "nodes": 10,
  "links": 10,
  "custom_nodes": [
    {"class_type": "ImageResizeKJ", "category": "upscale", "nodes": ["7"]},
    {"class_type": "MysteryNodeXP", "category": "unknown", "nodes": ["10"]}
  ],
  "stats": {"custom_node_count": 2, "unknown_node_count": 1},
  "issues": ["未识别节点类型：MysteryNodeXP（节点 10）；已按自定义节点记入依赖，不阻断解析"]
}
```

兼容报告实测：

```text
API  → runway：总体 incompatible；compatible 1 / degraded 7 / incompatible 3
API  → comfyui：总体 compatible；11 / 0 / 0
UI   → comfyui：总体 degraded；8 / 2 / 0
UI   → runway：总体 incompatible；1 / 8 / 1
UI   → libtv：总体 degraded；1 / 9 / 0
未知目标 nosuch：退出码 1
```

Runway Markdown 报告首段实际输出：

```text
- 目标平台：`runway`（Runway Workflows）
- 源格式：`comfyui_api`
- 总体结论：**不可直接迁移（incompatible）**
- 节点统计：compatible 1 / degraded 7 / incompatible 3
- 文件迁移：**部分降级（degraded）** — 目标平台未公开/未验证该格式导入；需人工重建；本报告不生成可导入文件
- 可导入产物：不生成（`importable_output=false`）
```

全量回归：

```text
$ python tools/verify.py
通过 69 / 69
全部通过 ✔

$ python tools/gen_registry.py --check
注册表一致：3 份，模型 12 / 平台 3
退出码 0

$ python tools/gen_examples.py --check
[PASS] text_example/output.md 与生成结果一致
[PASS] image_example/output.md 与生成结果一致
[PASS] muse_image_example/output.md 与生成结果一致
[PASS] video_example/output.md 与生成结果一致
[PASS] seedance_example/output.md 与生成结果一致
[PASS] story_example/output.md 与生成结果一致
[PASS] shot_reverse_example/output.md 与生成结果一致
退出码 0
```

豆包产物重新生成后，脚本清单断言为 7 个脚本且与 `scripts/*.py` 一致；两次生成哈希一致（固定时间戳），产物为 LF。

### 偏差

- 统一类别到平台并非一对一：`sampler` 需按图片/视频落到 `image_model` 或 `video_model`，故在 `workflow_mapping.json` 增加一对多 `category_aliases`，而不是简单改名替换。
- LoRA/ControlNet 在 Runway 与 LibTV 无等价节点，报告判 `incompatible`；即使总体结论为「不可直接迁移」，仍逐节点给出可迁移项与手工重建步骤，不因整体失败而省略细节。
- API 样例含 LoRA/ControlNet，LibTV 结论为 incompatible 3；UI 样例不含这两类，LibTV 为 degraded 1/9/0。两者是样例差异，不是规则不一致。
- 未知节点只进入 `custom_nodes` 与 `issues`，按自定义依赖提示人工安装，不阻断解析；未知目标平台不是「降级」，而是用法错误（退出码 1）。
- 兼容报告只读：不调用 ComfyUI `/prompt`、不调用任何平台 API、不生成/导入/导出工作流文件；`importable_output` 固定 `false`。
- 仍只支持 ComfyUI API/UI JSON，不解析 `.blend/.psd/.prproj/.aep` 或剪映工程。

### 回滚

`git revert` 本次提交。若需单独回退丙阶段：删除 `analyze_workflow.py` 与两个 workflow fixtures；移除 `prompt_compiler.py` 的 `workflow` 子命令及工作流 IR 校验；恢复 `ir_spec.md`、三平台 `workflow_mapping.json`、ComfyUI `capability_map.json` / `platform_rules.md`、`creative-platforms/README.md`、`SKILL.md`、`README.md`、`RELEASE.md`；`verify.py` 删除 4 项并恢复 65；`VERSION` 与 codex 清单回到 2.6.0；重跑 `python tools/install.py --platform doubao`。无数据迁移。

### 脱敏

本文不含密钥与绝对用户路径；验证输出只使用仓库内中性 fixtures，路径以 `...` 省略。
