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
