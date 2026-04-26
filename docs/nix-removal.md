---
name: Nix 移除变更记录
lang: zh-CN
created_at: 2026年04月26日 17时25分
creator: opencode
---

# Nix 移除变更记录

## 概述

移除项目中所有 Nix/NixOS/uv2nix 相关的构建基础设施、CI/CD、文档和代码引用。项目不再支持 Nix 安装方式，Managed 模式仅保留 Homebrew。

## 删除的文件（共 14 个）

### Nix 构建系统（11 个文件）

| 文件 | 说明 |
|------|------|
| `flake.nix` | Nix flake 入口 |
| `flake.lock` | Nix flake 锁定文件 |
| `nix/packages.nix` | Python 包依赖定义 |
| `nix/python.nix` | Python 解释器配置 |
| `nix/tui.nix` | TUI 前端构建 |
| `nix/web.nix` | Web Dashboard 构建 |
| `nix/lib.nix` | 工具函数 |
| `nix/devShell.nix` | 开发 shell 环境 |
| `nix/checks.nix` | Nix 构建检查 |
| `nix/nixosModules.nix` | NixOS 模块定义 |
| `nix/configMergeScript.nix` | 配置合并脚本 |

### CI/CD（4 个文件/目录）

| 文件 | 说明 |
|------|------|
| `.github/workflows/nix.yml` | Nix CI 流水线 |
| `.github/workflows/nix-lockfile-check.yml` | lockfile 格式检查 |
| `.github/workflows/nix-lockfile-fix.yml` | lockfile 自动修复 |
| `.github/actions/nix-setup/` | Nix 环境 setup Action |

### 文档（1 个文件）

| 文件 | 说明 |
|------|------|
| `website/docs/getting-started/nix-setup.md` | Nix 安装指南 |

### 测试（1 个文件）

| 文件 | 说明 |
|------|------|
| `tests/hermes_cli/test_container_aware_cli.py` | 容器感知 CLI 路由测试 |

## 修改的文件（共 12 个）

### `hermes_cli/config.py` — 核心配置模块

| 变更 | 详细 |
|------|------|
| 移除 `get_container_exec_info()` | 容器感知 CLI 路由函数 |
| 移除 `_MANAGED_SYSTEM_NAMES` 中的 `nix`/`nixos` | managed 系统名列表 |
| `get_managed_system()` | 不再返回 `"NixOS"` |
| `is_managed()` docstring | 移除 NixOS 特定描述 |
| `get_managed_update_command()` | 移除 NixOS case（返回 `"nix profile update"` 的分支）|
| `format_managed_message()` | 移除 NixOS 分支 |
| `_secure_dir()` docstring | "NixOS module" → "package manager" |
| `_secure_file()` docstring | "NixOS activation script" → "package manager" |
| `_ensure_hermes_home_managed()` 错误消息 | "Run 'sudo nixos-rebuild switch' first" → "Reinstall with your package manager" |
| section header 注释 | "Managed mode (NixOS declarative config)" → "Managed mode" |
| `ensure_hermes_home()` docstring | "In managed mode (NixOS)" → "In managed mode" |

### `hermes_cli/main.py` — CLI 入口模块

| 变更 | 详细 |
|------|------|
| 移除 container 路由块 | `parse_args()` 调用前的容器重定向逻辑 |
| 移除 NixOS sudo 配置提示 | 提示用户配置 `sudo` 权限的 4 行块 |
| 移除 `_exec_in_container()` 函数 | 约 90 行的容器进程替换函数 |
| 移除 `_probe_container()` 辅助函数 | `subprocess.run` 包装器 |
| 注释更新 | "Rootful containers (NixOS systemd service)" → "Other container runtimes" |

### `hermes_cli/gateway.py`

| 变更 | 详细 |
|------|------|
| 错误消息 | "managed by NixOS" → "managed mode"（2 处）|

### `hermes_logging.py`

| 变更 | 详细 |
|------|------|
| docstring | "In managed mode (NixOS)" → "In managed mode" |

### `.envrc`

| 变更 | 详细 |
|------|------|
| 移除 `watch_file flake.nix` 和 `watch_file flake.lock` | direnv 不再监控 Nix 文件 |
| 移除 `use flake` | 不再使用 Nix flake 设置环境 |

### `pyproject.toml`

| 变更 | 详细 |
|------|------|
| 注释 | "Nix-managed Python" → "managed Python" |

### `gateway/run.py`

| 变更 | 详细 |
|------|------|
| 注释 | "NixOS and other non-standard systems" → "non-standard systems" |

### `hermes_cli/tips.py`

| 变更 | 详细 |
|------|------|
| 移除 tipline | "Container mode: place .container-mode in HERMES_HOME and the host CLI auto-execs into the container." |

### `website/docs/getting-started/installation.md`

| 变更 | 详细 |
|------|------|
| 移除 Nix 用户提示框 | 关于 Nix 用户的安装提示 |

### `website/docs/getting-started/updating.md`

| 变更 | 详细 |
|------|------|
| 移除 Nix 更新章节 | 整个 "Updating with Nix" 段落 |

### `website/sidebars.ts`

| 变更 | 详细 |
|------|------|
| 移除导航项 | `nix-setup` 从 Getting Started 侧边栏移除 |

### `skills/productivity/google-workspace/scripts/_hermes_home.py`

| 变更 | 详细 |
|------|------|
| docstring | "nix env, CI" → "managed env, CI" |

### `hermes_cli/tips.py`

| 变更 | 详细 |
|------|------|
| 移除 tipline | 第 299 行关于 `.container-mode` 的 tip |

## 保留的内容

- `docs/release_docs/RELEASE_v*.md` — 历史发布日志保持不变（v0.5.0 提到 Nix 贡献）
- Homebrew managed 模式功能完好无损
- `get_container_exec_info` 的导入也被一并移除
