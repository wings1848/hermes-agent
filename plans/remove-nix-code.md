# Nix 相关代码移除方案

> 日期: 2026-04-30
>
> 目标: 彻底移除项目中所有 Nix/NixOS/uv2nix 相关的构建文件、代码注释和文档引用

---

## 范围清单

### 待删除文件（3 项）

| # | 文件 | 说明 |
|---|------|------|
| 1 | `packaging/nix/hermes-agent.nix` | Nix 构建定义（~170 行） |
| 2 | `packaging/nix/overlays.nix` | Nix overlay（外部 NixOS 配置入口） |
| 3 | `packaging/nix/` | 空目录（删除文件后清理） |

### 配置文件更新（1 项）

| # | 文件 | 改动 |
|---|------|------|
| 4 | `.gitignore` | 移除第 59 行 `.nix-stamps/` |

### 代码注释清理（2 项）

| # | 文件 | 当前内容 | 修改后 |
|---|------|----------|--------|
| 5 | `hermes_cli/main.py:916` | `# pre-built dist + node_modules (nix / full HERMES_TUI_DIR) skips npm.` | 移除 `nix /` |
| 6 | `pyproject.toml:83` | `# Sheets, Docs). Declared here so packagers (Nix, Homebrew) ship them with` | 移除 `Nix,` |

### 网站文档更新（2 个文件, 3 处）

| # | 文件 | 改动 |
|---|------|------|
| 7 | `website/docs/guides/build-a-hermes-plugin.md` | 删除 "Distribute for NixOS" 整个小节（~35 行），以及结尾的 Nix Setup 链接 |
| 8a | `website/docs/user-guide/features/plugins.md:102` | 删除插件来源表格中的 Nix 行 |
| 8b | `website/docs/user-guide/features/plugins.md:159-174` | 删除 "NixOS declarative plugins" 整个小节（~16 行） |

### 普通文档更新（1 项）

| # | 文件 | 改动 |
|---|------|------|
| 9 | `docs/git/remote-sync-guide.md:95-98` | 删除或更新 Nix 文件删除命令示例（该命令引用已不存在的文件路径） |

### 保留不变（历史记录）

| 文件 | 理由 |
|------|------|
| `docs/changelog/nix-removal.md` | 关于**上次** Nix 移除的变更记录——保留作为历史参考 |
| `docs/releases/RELEASE_v0.3.0.md` | 历史版本发布说明，保留原始内容 |
| `docs/releases/RELEASE_v0.5.0.md` | 同上 |
| `docs/releases/RELEASE_v0.8.0.md` | 同上 |
| `docs/releases/RELEASE_v0.9.0.md` | 同上 |

---

## 风险分析

| 方面 | 评估 |
|------|------|
| 核心功能影响 | ✅ 无影响。Nix 文件仅用于 NixOS 构建，不参与 Python 运行时逻辑 |
| 导入链影响 | ✅ 无影响。没有 Python import 引用这些文件 |
| CI/CD 影响 | ✅ 无影响。`.github/workflows/` 中没有 Nix 相关的 workflow |
| 用户可见影响 | ⚠️ 网站文档移除 NixOS 相关章节，NixOS 用户会失去参考（但代码已不再支持 Nix 构建） |
| 测试影响 | ✅ 无影响。没有测试依赖这些文件 |

---

## 预期变更统计

```
3 个文件被删除（.nix）
4 个文件被编辑（注释/文档）
0 个 Python import 受影响
0 个 CI 配置受影响
```

---

## 执行步骤

```bash
# 步骤 1：删除 .nix 文件
git rm packaging/nix/hermes-agent.nix packaging/nix/overlays.nix
rmdir packaging/nix          # 如果目录为空

# 步骤 2：更新 .gitignore
# 移除 .nix-stamps/ 行

# 步骤 3：更新代码注释
# hermes_cli/main.py: 移除 "nix /"
# pyproject.toml: 移除 "Nix,"

# 步骤 4：更新网站文档
# website/docs/guides/build-a-hermes-plugin.md: 删除 Distribute for NixOS 小节
# website/docs/user-guide/features/plugins.md: 删除 Nix 行 + NixOS 小节

# 步骤 5：更新普通文档
# docs/git/remote-sync-guide.md: 删除 Nix 文件删除命令示例

# 步骤 6：验证
scripts/run_tests.sh
```
