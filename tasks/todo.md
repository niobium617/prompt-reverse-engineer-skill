# 任务清单

> 依据：[`docs/2026-11-14-项目改进方案.md`](../docs/2026-11-14-项目改进方案.md)。完成后勾选，并在 `docs/DEVLOG.md` 记录验证输出。

## 阶段 0：P0 资源治理

- [x] `analyze_video.py`：抽样帧不再全量缓存，只保留首帧灰度/中点帧
- [x] 删除每镜头重开 `VideoCapture`，改为两遍顺序解码
- [x] 新增 `--workdir`（默认项目 `.tmp/`，安装态回退系统临时目录），副本分析后清理
- [x] 本地/stdin/URL 统一 `--max-bytes`（默认 512 MiB），超限退出 3
- [x] `verify.py` 增加 workdir / 副本清理 / 体积超限断言
- [x] 现有 24 项 + 新增资源治理断言全部通过（25 项）

## 阶段 1：GPT Image 契约与模板

- [x] `prompt_framework.md` §2.3 增加 12 个扁平字段（2.3.1 五用途 / 2.3.2 扩展字段）
- [x] `gpt_image.json` 增加 `recreate` / `reference_guided` / `compose`，改造 `edit`
- [x] `prompt_compiler.py`：`KNOWN_FIELDS` 扩充，`kind_requires` 改用 `allowed_fields`
- [x] `compile --kind` 与 `task_type` 映射、冲突退出 4
- [x] `format_field` 拒绝 `dict` 值（退出 4）
- [x] 参考图编号、task_type 枚举、必填字段校验
- [x] `fixtures` 与四模态示例同步更新（新增 `semantic_gpt_image.json`）
- [x] 旧 10 个模板输出逐字节不变（基线对比：text/video 全一致，image 仅 `gpt_image/edit` 按设计不再渲染）

## 阶段 2：一致性与 CI

- [x] README 删除 `requests`，依赖表与临时目录描述修正
- [x] `install.py` 动态扫描脚本清单，删除"4 个"硬编码
- [x] `install.py` 在 Python 3.10 降级 `tomllib` 校验并继续
- [x] 新增根目录 `VERSION`，`plugin.json` 与之对齐
- [x] 新增 `tools/gen_examples.py`，verify 断言示例可复现
- [x] `verify.py` 新增 12–14 条断言
- [x] CI 改为全分支 push + PR，新增 Windows 安装冒烟
- [x] 断言数量同步到 README

## 阶段 3：参考图、置信度、评分清单

- [x] `reference_images` 角色枚举与编号规则写入文档
- [x] `uncertainty` 规则：`unknown` 不进正文
- [x] GPT Image 审查清单出现在输出末尾（不参与总分）
- [x] `image_rules.md` 补空间/材质/编辑约束术语

## 阶段 3.5：Muse Image 1.0 独立适配

- [x] 独立模板 `assets/templates/muse_image.json`（八用途，不与 GPT Image 共用）
- [x] 独立规则 `references/muse_image_rules.md` + 官方资料边界 `muse_image_sources.md`
- [x] 八维分析、十类空间关系、参考图迁移边界（用途/保留/禁止迁移/优先级）
- [x] Anchor 系列（`anchor_set`）、多轮修改（`iteration_context`）、文字版式（`text_layout`）
- [x] 编译器字段与三个扩展 `task_type`、`kind_requires`、Muse 六项审查清单（不参与总分）
- [x] `semantic_muse_image.json` + `muse_image_example` 金标输出
- [x] `verify.py` 新增 4 项（独立模板/八模式/字段契约/审查清单），共 49 项
- [x] README / VERSION / plugin.json / 豆包指令同步（2.2.0）

## 阶段 3.6：Seedance 2.5 独立适配

- [x] 独立模板 `assets/templates/seedance.json`（六任务模式，不与 Sora / Runway / Veo 共用）
- [x] 独立规则 `references/seedance_rules.md` + 官方资料边界 `seedance_sources.md`
- [x] 六任务模式：文生视频 / 首帧 / 首尾帧 / 全模态参考 / 编辑 / 延长，首帧·首尾帧·全模态参考互斥
- [x] 素材角色契约（`素材N：reference_image|reference_video|reference_audio；用途；保留；禁止迁移`）
- [x] 视频扩展字段（`first_frame`/`last_frame`/`source_video`/`extension_plan`/`video_references` 等）与 `params` 边界
- [x] 编译器 `TASK_KINDS`/`TASK_REQUIRED`/互斥校验、Seedance 六项审查清单（不参与总分）
- [x] `semantic_seedance.json` + `seedance_example` 金标输出
- [x] `verify.py` 新增 4 项（独立模板/六任务模式/字段契约/审查清单），共 53 项
- [x] README / VERSION / plugin.json / 豆包指令同步（2.3.0）

## 阶段 3.7：实拍图片/视频逐镜反推

- [x] `analyze_image.py` 输出 `shot_hints`（EXIF 焦段/光圈/快门/ISO、景深、黑边、人脸），每项带置信度
- [x] `analyze_video.py` 逐镜输出首/中/末关键帧、运镜轴、逐镜主色、黑边、景别/机位提示
- [x] 新规则 `references/shot_reverse_rules.md`：三条硬原则、镜头卡 12 维、证据标签、跨镜一致性、逐模型写法、自检清单
- [x] 编译器 `shots` 子命令：`--models` / `--dims` / `--auto` / `--format md`，逐镜渲染 + 逐镜评分 + 镜头审查清单
- [x] 镜头卡契约校验（编号/枚举/时长/运镜轴/锚点/证据/焦段），错误退出 4 并报镜头号
- [x] `semantic_shot_reverse.json` + `shot_reverse_example` 金标输出
- [x] `verify.py` 新增 4 项（图片镜头信号/视频镜头信号/逐镜渲染+评分/字段与安全），共 57 项
- [x] README / SKILL.md / video_rules.md / image_rules.md 同步；VERSION 与 plugin.json 升至 2.4.0

## 阶段 3.8：镜头反推覆盖六个图片模型

- [x] 六个图片模板补 `shot_style`：MJ `/imagine` + `--ar`、SD `Positive/Negative` + 采样参数、FLUX.2 无负向、GPT Image/Nano Banana 规格书、Muse 完整句
- [x] 编译器按 `modality` 选默认模型（视频四款 / 图片六款），图片模板允许 `shot_style`
- [x] `semantic_shot_reverse_image.json` 单图金标（EXIF 85mm / f/1.8 / 3s）
- [x] `verify.py` 新增 1 项（图片六模型渲染），共 58 项；无 `shot_style` 用例改用 `deepseek`
- [x] `prompt_framework.md` 2.6 / `shot_reverse_rules.md` 第七节 / `SKILL.md` / README 1.2、3.4、3.6、验证表同步
- [x] VERSION 与 plugin.json 升至 2.4.1；豆包产物重新生成

## 阶段 4：迭代与差异分析（可选）

- [ ] `SKILL.md` 增加生成结果回传与迭代工作流
- [ ] 评估 `diff` 子命令（复用 `local_features`）

## 阶段 5：发布

- [x] `VERSION` 递增，tag 与 release notes
- [x] 重新生成豆包 zip 与 Codex 清单
- [x] 更新仓库描述、README 模型数与断言数

## 跨平台工作流升级（已确认，自甲阶段开始）

> 方案：[`docs/2026-11-15-跨平台工作流升级方案.md`](../docs/2026-11-15-跨平台工作流升级方案.md)（2026-11-15 冻结）。实施时按文档 §0.1 开工检查单执行。

- [x] 甲：IR 契约、三注册表、置信度推广（v2.5.0）
  - [x] `references/ir_spec.md`：11 模块字段契约、校验规则、退出码 4、变更控制
  - [x] `prompt_compiler.py ir validate`：可选 IR 层，旧 JSON 无 IR 字段直接通过；版本/资产 sha256/绝对路径/nodes/置信度/深度 5 六类错误退出 4
  - [x] `tools/gen_registry.py`：三份注册表确定性生成，`--check` 逐字节比对；L2 由 `default_params` 是否非空推导（12 模型：1 个 L1、11 个 L2）
  - [x] `config/model_registry.json`、`platform_registry.json`、`capability_registry.json` 生成并入库
  - [x] `verify.py` 新增 4 项（IR 契约、注册表可复现、能力声明、IR 文档），共 62 项
  - [x] `SKILL.md` / README 1.5、4.3、4.4、验证表同步；VERSION 与 plugin.json 升至 2.5.0；豆包产物重新生成
- [x] 乙：`creative-platforms/` 首批三平台（ComfyUI / Runway / LibTV）（v2.6.0）
  - [x] 根目录 `creative-platforms/README.md`：与 `platform-adapters/` 的命名区分、状态表、L1-L4 边界、消费路径、来源闸门与更新流程
  - [x] ComfyUI 五件套（L2）：Workflow JSON 1.0/0.4 + API 格式官方规范已读；节点类名标「需人工确认」；不解析工作流（留到丙）
  - [x] Runway 五件套（L1）：Workflows 官方页已读；节点类别/单端点/Recipes 已验证，参数与文件格式标 unknown
  - [x] LibTV 五件套（L1）：官网/落地页/插件页已读；节点图、项目文件、公开 REST API 明确 unknown；Plugin 自动化不计入本 Skill
  - [x] 来源闸门：`verified` 需至少 1 条 `official: true` 且 `verified: true`（已实际读取）的来源；`draft` 不进注册表；`gen_registry.py` 校验 schema 与置信度枚举
  - [x] 安装物化：junction 模式建 `platforms -> creative-platforms` 子链接；copy 模式与豆包包复制到 `platforms/`；缺失/失败只告警并降级为通用 Prompt
  - [x] 修复 `junction_target`：改用 `os.readlink`（原 `dir <junction>` 会跟随目标，取不到标记）
  - [x] `verify.py` 新增 3 项（五件套/注册表闸门/安装物化），共 65 项
  - [x] SKILL.md / README / VERSION / plugin.json / 豆包产物同步（2.6.0）
- [x] 丙：ComfyUI 工作流只读解析与兼容性校验（v3.0.0）
  - [x] `scripts/analyze_workflow.py`：ComfyUI API/UI JSON 只读解析；悬空连线/成环/结构非法退出 4；未知节点只警告；输出 IR 1.0 信封（仅文件名、无绝对路径）
  - [x] `prompt_compiler.py workflow`：按目标平台输出 `compatible/degraded/incompatible`、文件迁移结论与手工重建步骤；未知目标退出 1；资料缺失/draft 保守降级
  - [x] `ir validate` 扩展 workflow 结构校验（节点/连线端点/成环/参数），旧 JSON 仍直接通过
  - [x] 三平台 `workflow_mapping.json` 增加 `category_aliases`；ComfyUI 能力声明将工作流解析标为 verified
  - [x] `verify.py` 新增 4 项（工作流解析/结构错误/兼容报告/文档与能力），共 69 项
  - [x] SKILL.md / README / ir_spec.md / RELEASE / VERSION / plugin.json / 豆包产物同步（3.0.0）
- [ ] 丁：可灵等模型模板 + `benchmarks/`
- [ ] 戊（可选）：WAV 音频信号、专业软件 L1 说明
