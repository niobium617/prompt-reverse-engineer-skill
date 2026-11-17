# 发布检查表

> 单一版本源：根目录 [`VERSION`](../VERSION)。`platform-adapters/codex/prompt-reverse-engineer/.codex-plugin/plugin.json`
> 的 `version` 必须与之一致（`verify.py` 已断言），README 的模型数、断言数同样由断言兜底。

## 1. 发布前（全部在特性分支完成）

- [ ] `VERSION` 递增（语义化版本；当前值见 `VERSION`）
- [ ] `plugin.json` 的 `version` 同步
- [ ] `python tools/verify.py` 全绿（当前 73 项，无网络、无 API）
- [ ] `python tools/benchmarks.py --check` 结构层 10 / 10 通过，语义层输出 `[MANUAL]`（当前 10 例）
- [ ] `python tools/benchmarks.py --suite image --check` 单套件可独立执行
- [ ] `python tools/gen_examples.py --check` 四模态 + Muse / Seedance / 镜头反推示例逐字节一致
- [ ] `python tools/gen_registry.py --check` 三份注册表逐字节一致（模型 16 / 平台 3）
- [ ] `python tools/install.py --platform doubao` 重新生成豆包三产物（含 `platforms/`），`git diff` 仅出现预期变更
- [ ] README 的断言数与 `verify.py` 实际条数一致（`一致性/README 断言数` 断言）
- [ ] README 的模型清单、仓库描述均为十六模型（含 Muse Image、Seedance、即梦、Kling / Hailuo / Vidu 独立模板）
- [ ] `creative-platforms/` 三平台五件套齐全，`verified` 平台均有已读官方来源（`平台层/五件套与能力声明` 断言）
- [ ] Muse 模板与 GPT Image 模板保持相互独立（`muse_image.json` 不并入 `gpt_image.json`）
- [ ] Seedance 模板与 Sora / Runway / Veo 模板保持相互独立（`seedance.json` 不并入其他视频模板）
- [ ] `docs/DEVLOG.md` 补发布条目（摘要/变更/验证/回滚/脱敏）
- [ ] 走分支 + PR，CI 全绿后 squash 合入 `main`

## 2. 打 tag 与 Release

```bash
# 网络可用时：annotated tag（推荐，tag 对象带发布说明）
git checkout main && git pull
git tag -a vX.Y.Z -m "vX.Y.Z: <一句话摘要>"
git push origin vX.Y.Z

# git 协议不可达时（本机曾出现）：由 GitHub API 建 tag + Release
gh release create vX.Y.Z --target main \
  --title "vX.Y.Z" --notes-file docs/<YYYY-MM-DD>-vX.Y.Z-发布说明.md
```

- [ ] tag 指向 `main` 的发布提交
- [ ] Release notes 含：新增能力、破坏性变更（无则写“无”）、验证方式、升级步骤
- [ ] 更新 GitHub 仓库描述（十六模型、五平台）
- [ ] 发布后核对：`gh release view vX.Y.Z`、`gh api repos/<owner>/<repo> --jq .description`

## 3. 发布后

- [ ] `tasks/todo.md` 对应阶段全部勾选
- [ ] 下一个版本的改进项移入新的方案文档，不覆盖本文
- [ ] 若发布过程有偏差（人工介入、网络绕行），在 `docs/DEVLOG.md` 记录

## 历史版本

| 版本 | 日期 | 要点 |
|---|---|---|
| v3.1.0 | 2026-11-18 | 阶段丁：新增 Kling 4.0 / Hailuo 3 / Vidu Q3 / 即梦 5.0（Seedream 5.0）四个独立模板（零代码注册）与官方资料索引；`benchmarks/` 10 例（图像 3 / 视频 3 / 工作流 2 / 平台 2），结构层自动断言与语义层 rubric 分离；`tools/benchmarks.py` 支持 `--suite image --check`；73 项断言 |
| v3.0.0 | 2026-11-17 | 阶段丙：ComfyUI API/UI JSON 只读解析（`analyze_workflow.py`）；`prompt_compiler.py workflow` 跨平台兼容报告（compatible/degraded/incompatible + 手工步骤）；IR 扩展 workflow 结构/悬空连线/成环校验；三平台 `category_aliases`；固定 `importable_output: false`（不生成/不导入/不导出工作流、无 L4）；69 项断言 |
| v2.6.0 | 2026-11-17 | `creative-platforms/` 首批三平台（ComfyUI L2 / Runway L1 / LibTV L1）五件套；来源闸门（`official` + 已读 `verified`）；注册表纳入 3 平台；安装物化 `platforms/`（junction/copy/豆包包）；修复 junction 目标读取；junction 安全清理（不跟随删除实体）；65 项断言 |
| v2.5.0 | 2026-11-17 | IR 1.0 契约与 `ir validate`；确定性注册表（模型 12 / 平台 0）；L1–L4 能力声明；62 项断言 |
| v2.4.1 | 2026-11-16 | 镜头反推覆盖六个图片模型：MJ / SD 3.5 / FLUX.2 / GPT Image / Muse Image / Nano Banana 各加单帧 `shot_style`，`shots` 按模态选默认模型（视频四款 / 图片六款），单图反推每次出六份独立 Prompt；58 项断言 |
| v2.4.0 | 2026-11-15 | 新增实拍图片/视频逐镜反推：脚本镜头信号（EXIF/景深/黑边/首中末关键帧/运镜轴）、12 维镜头卡规则、`shots` 逐镜 × 四视频模型渲染与逐镜评分、镜头审查清单；镜头反推示例；57 项断言 |
| v2.3.0 | 2026-11-15 | 新增 Seedance 2.5：独立视频模板与规则（六任务模式/首帧首尾帧全模态参考互斥/素材角色/参数边界）、Seedance 六项审查清单、官方资料索引；四模态 + Seedance 示例；53 项断言 |
| v2.2.0 | 2026-11-15 | 新增 Muse Image 1.0：独立模板与规则（八用途/十类空间关系/参考迁移边界/Anchor/多轮/文字版式）、Muse 六项审查清单、官方资料索引；四模态 + Muse 示例；49 项断言 |
| v2.1.0 | 2026-11-14 | 阶段 0–3：资源治理、GPT Image 五任务、一致性与 CI（45 项断言）、参考图角色/置信度/审查清单；修复非 Windows 安装与豆包产物行尾归一化 |
