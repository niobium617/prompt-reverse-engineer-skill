# 发布检查表

> 单一版本源：根目录 [`VERSION`](../VERSION)。`platform-adapters/codex/prompt-reverse-engineer/.codex-plugin/plugin.json`
> 的 `version` 必须与之一致（`verify.py` 已断言），README 的模型数、断言数同样由断言兜底。

## 1. 发布前（全部在特性分支完成）

- [ ] `VERSION` 递增（语义化版本；当前值见 `VERSION`）
- [ ] `plugin.json` 的 `version` 同步
- [ ] `python tools/verify.py` 全绿（当前 45 项，无网络、无 API）
- [ ] `python tools/gen_examples.py --check` 四模态示例逐字节一致
- [ ] `python tools/install.py --platform doubao` 重新生成豆包三产物，`git diff` 仅出现预期变更
- [ ] README 的断言数与 `verify.py` 实际条数一致（`一致性/README 断言数` 断言）
- [ ] README 的模型清单、仓库描述均为十模型
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
- [ ] 更新 GitHub 仓库描述（十模型、五平台）
- [ ] 发布后核对：`gh release view vX.Y.Z`、`gh api repos/<owner>/<repo> --jq .description`

## 3. 发布后

- [ ] `tasks/todo.md` 对应阶段全部勾选
- [ ] 下一个版本的改进项移入新的方案文档，不覆盖本文
- [ ] 若发布过程有偏差（人工介入、网络绕行），在 `docs/DEVLOG.md` 记录

## 历史版本

| 版本 | 日期 | 要点 |
|---|---|---|
| v2.1.0 | 2026-11-14 | 阶段 0–3：资源治理、GPT Image 五任务、一致性与 CI（45 项断言）、参考图角色/置信度/审查清单；修复非 Windows 安装与豆包产物行尾归一化 |
