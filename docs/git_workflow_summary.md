# Git 远程仓库管理与冲突解决工作流 (SOP)

本文档总结了 `hermes-agent` 项目在跨仓库同步及解决大规模冲突时的实战经验，旨在为 AI 和开发者提供可复用的操作标准。

## 1. 核心远程仓库配置
建议长期保留双远程配置，避免频繁 `set-url`：
- `origin`: `git@github.com:wings1848/hermes-agent.git` (个人 Fork)
- `upstream`: `git@github.com:NousResearch/hermes-agent.git` (官方上游)

**配置命令**:
```bash
git remote add upstream git@github.com:NousResearch/hermes-agent.git
```

## 2. 深度同步与冲突解决流程

### 步骤 A：获取上游更新并识别差异
当本地分支落后且包含个人提交时，Git 会提示“分支偏离”（Diverged）。
```bash
git fetch upstream
git status # 检查 Ahead (本地领先) 和 Behind (本地落后) 的数量
```

### 步骤 B：选择对齐策略
- **Rebase (推荐)**: 保持历史线性，将个人提交置于官方最新提交之上。
  `git pull --rebase upstream main`
- **Merge**: 保留合并节点，适用于多人协作或希望明确记录合并点的场景。
  `git pull upstream main --no-rebase`

### 步骤 C：冲突分析与集成 (核心经验)
当发生冲突时，**切勿盲目保留一方**。
1. **识别官方意图**：分析官方新增变量的作用。
   - *案例*：官方引入 `proxy_targets` 是为了 `NO_PROXY` 自动绕过机制。
2. **逻辑集成**：将个人功能（如 `custom_domains`）合入官方新框架。
   - *做法*：将 `custom_domains` 加入到官方的 `proxy_targets` 列表中，确保代理绕过逻辑对自定义域名也生效。

### 步骤 D：完成合并与推送
经过 Rebase 或 Merge 修复冲突后，本地历史已改变。
1. **本地提交**: `git add . && git commit -m "Merge and resolve conflicts"`
2. **安全推送**: 
   `git push origin main --force-with-lease`
   *注：使用 --force-with-lease 而非 -f，防止意外覆盖他人在远程的提交。*

## 3. 常用检查清单 (AI 复用提示)
- [ ] **检查点 1**: 运行 `git log origin/main..main` 查看本地即将推送到个人仓库的独特提交。
- [ ] **检查点 2**: 若官方修改了底层网络/传输类（如 `TelegramFallbackTransport`），需检查所有调用点是否增加了新参数。
- [ ] **检查点 3**: 确保未跟踪的敏感文件（如 `.env`）或临时文档（如方案草稿）未被意外合入。

---
*最近更新时间：2026年4月25日*
