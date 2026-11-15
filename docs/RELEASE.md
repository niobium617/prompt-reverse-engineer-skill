# 发布检查表

> 单一版本源：根目录 [`VERSION`](../VERSION)。`platform-adapters/codex/prompt-reverse-engineer/.codex-plugin/plugin.json`
> 的 `version` 必须与之一致（`verify.py` 已断言），README 的模型数、断言数同样由断言兜底。

## 1. 发布前（全部在特性分支完成）

- [ ] `VERSION` 递增（语义化版本；当前值见 `VERSION`）
- [ ] `plugin.json` 的 `version` 同步
- [ ] `python tools/verify.py` 全绿（当前 58 项，无网络、无 API）
- [ ] `python tools/gen_examples.py --check` 四模态 + Muse / Seedance / 镜头反推示例逐字节一致
- [ ] `python tools/install.py --platform doubao` 重新生成豆包三产物，`git diff` 仅出现预期变更
- [ ] README 的断言数与 `verify.py` 实际条数一致（`一致性/README 断言数` 断言）
- [ ] README 的模型清单、仓库描述均为十二模型（含 Muse Image、Seedance 独立模板）
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
  --title "vX.Y.Z" --notes-file docs/release-notes-vX.Y.Z.md
```

- [ ] tag 指向 `main` 的发布提交
- [ ] Release notes 含：新增能力、破坏性变更（无则写“无”）、验证方式、升级步骤
- [ ] 更新 GitHub 仓库描述（十二模型、五平台）
- [ ] 发布后核对：`gh release view vX.Y.Z`、`gh api repos/<owner>/<repo> --jq .description`

## 3. 发布后

- [ ] `tasks/todo.md` 对应阶段全部勾选
- [ ] 下一个版本的改进项移入新的方案文档，不覆盖本文
- [ ] 若发布过程有偏差（人工介入、网络绕行），在 `docs/DEVLOG.md` 记录

## 历史版本

| 版本 | 日期 | 要点 |
|---|---|---|
| v2.4.1 | 2026-11-16 | 镜头反推覆盖六个图片模型：MJ / SD 3.5 / FLUX.2 / GPT Image / Muse Image / Nano Banana 各加单帧 `shot_style`，`shots` 按模态选默认模型（视频四款 / 图片六款），单图反推每次出六份独立 Prompt；58 项断言 |
| v2.4.0 | 2026-11-15 | 新增实拍图片/视频逐镜反推：脚本镜头信号（EXIF/景深/黑边/首中末关键帧/运镜轴）、12 维镜头卡规则、`shots` 逐镜 × 四视频模型渲染与逐镜评分、镜头审查清单；镜头反推示例；57 项断言 |
| v2.3.0 | 2026-11-15 | 新增 Seedance 2.5：独立视频模板与规则（六任务模式/首帧首尾帧全模态参考互斥/素材角色/参数边界）、Seedance 六项审查清单、官方资料索引；四模态 + Seedance 示例；53 项断言 |
| v2.2.0 | 2026-11-15 | 新增 Muse Image 1.0：独立模板与规则（八用途/十类空间关系/参考迁移边界/Anchor/多轮/文字版式）、Muse 六项审查清单、官方资料索引；四模态 + Muse 示例；49 项断言 |
| v2.1.0 | 2026-11-14 | 阶段 0–3：资源治理、GPT Image 五任务、一致性与 CI（45 项断言）、参考图角色/置信度/审查清单；修复非 Windows 安装与豆包产物行尾归一化 |
