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

## 阶段 4：迭代与差异分析（可选）

- [ ] `SKILL.md` 增加生成结果回传与迭代工作流
- [ ] 评估 `diff` 子命令（复用 `local_features`）

## 阶段 5：发布

- [x] `VERSION` 递增，tag 与 release notes
- [x] 重新生成豆包 zip 与 Codex 清单
- [x] 更新仓库描述、README 模型数与断言数
