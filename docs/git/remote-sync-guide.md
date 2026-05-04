# Git跨远程仓库同步管理与冲突解决方案

本文档总结了 `hermes-agent` 项目在跨仓库同步及解决大规模冲突时的实战经验，旨在为 AI 和开发者提供可复用的操作标准。

> 最近实战：2026-04-29，本地 8 个提交领先，上游 679 个提交落后，成功合并为零冲突回归。

## 1. 核心远程仓库配置

建议长期保留双远程配置，避免频繁 `set-url`：
- `origin`: `git@github.com:wings1848/hermes-agent.git` (个人 Fork)
- `upstream`: `git@github.com:NousResearch/hermes-agent.git` (官方上游)

**配置命令**:
```bash
git remote add upstream git@github.com:NousResearch/hermes-agent.git
```

**SSH 连接问题**：如果 `upstream` SSH 拉取超时（可能因 SSH key 无该组织权限），可改用 HTTPS：
```bash
git remote set-url upstream https://github.com/NousResearch/hermes-agent.git
```

## 2. 深度同步与冲突解决流程

### 步骤 A：获取上游更新并识别差异
```bash
git fetch upstream
git status -sb           # 检查 Ahead (本地领先) 和 Behind (本地落后) 的数量
git log --oneline upstream/main..main          # 列出本地独有提交
git diff --stat $(git merge-base main upstream/main)..main  # 本地改动范围
```

### 步骤 B：选择对齐策略

| 策略 | 适用场景 | 优点 | 缺点 |
|------|----------|------|------|
| **Squash → Rebase**（推荐） | 本地有多个碎片提交，上游大幅领先 | 冲突少，历史干净 | 丢失细粒度提交记录 |
| **直接 Rebase** | 本地提交少且独立 | 保留完整历史 | 每个提交都需过冲突 |
| **Merge** | 多人协作 | 单次冲突解决 | 非线性历史，冲突量大时难追踪 |

#### 推荐流程：Squash + Rebase + Lockfile 后处理

```bash
# 1. 备份当前状态
git branch backup/main-$(date +%Y%m%d)

# 2. 创建临时分支，压缩所有本地提交为一个
git checkout -b temp-squash main
git reset --soft $(git merge-base main upstream/main)
git commit -m "squash: <描述所有本地改动>"

# 3. 变基到上游最新
git rebase upstream/main

# 4. 解决冲突（见步骤 C）

# 5. lockfile 不要手动合并！直接重置为上游版本
git checkout HEAD -- uv.lock    # 或 package-lock.json / Cargo.lock 等

# 6. 应用到 main 分支
git checkout main
git reset --hard temp-squash
git branch -d temp-squash

# 7. 推送
git push origin main --force-with-lease
```

**为何 Squash 后再 Rebase？**
- 直接 rebase N 个提交 = N 轮冲突解决。Squash 为 1 个 = 1 轮。
- 交互式 rebase（`git rebase -i`）在 merge-base 很旧时，连第一个提交都可能冲突，不如 soft reset + 重新提交干净。

### 步骤 C：冲突分析与集成

#### C1. 冲突分类

| 类型 | 特征 | 处理原则 |
|------|------|----------|
| **修改/删除**（modify/delete） | 本地删除但上游修改了同一文件 | 确认本地意图后决定保留或删除 |
| **内容冲突**（content） | 双方修改了同一文件不同区域 | 合并双方改动 |
| **Lockfile 冲突** | `uv.lock`、`package-lock.json` 等 | **放弃本地版本**，使用上游版本 |

#### C2. 集成决策原则

1. **识别官方意图**：分析官方新增/修改的作用，不要盲目保留一方。
2. **逻辑集成**：将个人功能合入官方新框架，而非覆盖。
   - *案例*：官方引入 `proxy_targets` 实现 `NO_PROXY` 自动绕过 → 将 `custom_domains` 加入 `proxy_targets` 列表。
3. **上游结构 + 本地内容**：上游新增的命令/字段保留，但描述文字使用个人翻译版本。
   - *案例*：上游新增 `redraw`、`curator`、`indicator`、`footer` 命令 → 保留命令定义，描述中文化。
4. **个人交互设计优先**：如果个人版本有更丰富的用户体验（如互动菜单），保留个人版本。
   - *案例*：个人版有 `prompt_choice` 互动菜单，上游是简单的 fall-through → 保留菜单。

**代码风格适配**：上游使用 `cfg_get()` 辅助函数而本地使用 `dict.get().get()` → 统一使用 `cfg_get()`。

**大文件差异**：如 `hermes_cli/setup.py`（~3400 行），冲突块多达 6 个。先解决简单的 `cfg_get` 差异，再逐一处理内容冲突（Slack 配置、返回用户菜单等）。

### 步骤 D：测试验证

推送前按模块分批跑测试，优先覆盖改动文件：

```bash
source venv/bin/activate   # 使用项目 venv

# 按改动模块优先级分批
python -m pytest tests/hermes_cli/test_commands.py -v
python -m pytest tests/hermes_cli/test_setup*.py -v
python -m pytest tests/gateway/test_telegram*.py -v
```

**预期断裂**：中文化（i18n）会导致测试断言失败（期望英文，输出中文），属于已知的非回归问题，记录到文档待后续统一修复。

### 步骤 E：推送

```bash
git push origin main --force-with-lease
```
*注：使用 `--force-with-lease` 而非 `-f`，防止意外覆盖他人在远程的提交。*

## 3. 常用检查清单

- [ ] **检查点 1**: `git log upstream/main..main` 查看本地独有提交是否完整。
- [ ] **检查点 2**: 若官方修改了底层网络/传输类（如 `TelegramFallbackTransport`），检查调用点是否增加了新参数。
- [ ] **检查点 3**: 确保未跟踪的敏感文件（`.env`）或临时文档未被意外合入。
- [ ] **检查点 4**: `uv.lock` / `package-lock.json` 是否使用上游版本（而非本地旧版本）。
- [ ] **检查点 5**: 中文化改动是否导致相关测试断言需要更新。
- [ ] **检查点 6**: 推送前已创建 `backup/main-*` 分支作为回滚点。

## 4. 已知陷阱

- **交互式 rebase 在旧 merge-base 上不可靠**：当 merge-base 很旧（几百个提交前），即使第一个本地提交也可能无法 cleanly apply。方案：先 `reset --soft` + 重新提交，再 rebase。
- **不要手动合并 lockfile**：二进制/自动生成的锁文件冲突无法合理解决，始终重置为上游版本，再按需重新生成。
- **测试 venv 问题**：系统 python 可能缺少依赖（如 `prompt_toolkit`），始终使用项目 `.venv` 或 `venv` 中的 python。
- **SSH 超时不一定是网络问题**：可能是 SSH key 对该组织仓库无权限，尝试 HTTPS。

---
*最近更新时间：2026年4月29日*
