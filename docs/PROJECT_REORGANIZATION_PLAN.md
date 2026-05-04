# Hermes Agent 项目结构整理方案

> 创建日期: 2026-04-30
> 最后更新: 2026-04-30（阶段 1-4 已执行完成）
>
> 目标: 在不破坏核心功能的前提下，清理根目录混乱、统一目录命名规范、合并分散配置

---

## 执行状态总览

| 阶段 | 内容 | 风险 | 状态 | 完成日期 |
|------|------|------|------|----------|
| **阶段 1** | 📄 文档重组 | ✅ 安全 | ✅ **已完成** | 2026-04-30 |
| **阶段 2** | ⚙️ 配置示例合并 | ✅ 安全 | ✅ **已完成** | 2026-04-30 |
| **阶段 3** | 🐳 打包构建合并 | ✅ 安全 | ✅ **已完成** | 2026-04-30 |
| **阶段 4** | 🧹 清理冗余 | ✅ 安全 | ✅ **已完成** | 2026-04-30 |
| **阶段 5** | 🔧 工具子包重命名 | ⚠️ 中 | ⏸️ **暂缓** | — |
| **阶段 6** | 🏗️ 根 .py 归入包 | 🔴 高 | ⏸️ **远期目标** | — |

---

## 执行结果

### 根目录瘦身：移除了 12 个散落文件/目录

| 原位置 | 新位置 |
|--------|--------|
| `AGENTS.md` | `docs/dev/AGENTS.md` |
| `CONTRIBUTING.md` | `docs/dev/CONTRIBUTING.md` |
| `SECURITY.md` | `docs/dev/SECURITY.md` |
| `Dockerfile` / `.dockerignore` / `docker-compose.yml` | `docker/` |
| `cli-config.yaml.example` / `.env.example` | `examples/config/` |
| `datagen-config-examples/` (4 个文件) | `examples/datagen/` |
| `nix/` (2 个文件) | `packaging/nix/` |
| `constraints-termux.txt` | `packaging/constraints/termux.txt` |
| `setup-hermes.sh` | `scripts/setup-hermes.sh` |
| `assets/banner.png` | `docs/assets/banner.png` |
| `plans/` (1 个文件) | `docs/plans/` |

### 文档目录重构

`docs/` 从 11 个散落文件 → 分类整理后为：

```
docs/
├── assets/          banner.png
├── dev/             AGENTS.md, CONTRIBUTING.md, SECURITY.md
├── changelog/       nix-removal.md, telegram-custom-domains-implementation.md
├── issues/          setup-chinese-assertion-breakage.md, telegram-custom-domains-env-var-inconsistency.md
├── releases/        RELEASE_v0.2.0.md ~ RELEASE_v0.11.0.md (9 个)
├── guides/          hermes-already-has-routines.md
├── gateway/         telegram-command-registration.md, telegram-custom-botapi-domain.md
├── git/             remote-sync-guide.md
└── plans/           gemini-oauth-provider.md
```

所有中文文件名已重命名为英文。

### 配置文件更新

| 文件 | 改动内容 |
|------|----------|
| `.github/workflows/docker-publish.yml` | `Dockerfile` → `docker/Dockerfile`（3 处） |
| `README.md` | `setup-hermes.sh` → `scripts/setup-hermes.sh`；`assets/banner.png` → `docs/assets/banner.png` |
| `scripts/setup-hermes.sh` | 脚本 start 注释路径更新；`constraints-termux.txt` → `packaging/constraints/termux.txt` |
| `tests/hermes_cli/test_setup_hermes_script.py` | `setup-hermes.sh` → `scripts/setup-hermes.sh`；`constraints-termux.txt` → `packaging/constraints/termux.txt` |
| `.gitignore` | 清理重复条目、按类别分组、添加 `run_datagen_*.sh` 泛化模式 |

### 测试验证

| 测试 | 结果 |
|------|------|
| 核心模块 import 验证（hermes_constants/logging/state/time/model_tools/toolsets/run_agent） | ✅ 全部通过 |
| `test_setup_hermes_script.py` | ✅ 2 passed |
| `test_project_metadata.py` | ✅ 6 passed |
| `test_hermes_constants.py` | ✅ 全部通过 |
| `test_hermes_state.py` | ✅ 全部通过 |
| `test_toolsets.py` | ✅ 全部通过 |
| `test_hermes_logging.py` | ⚠️ 1 个预先存在的失败（非本次引入） |

---

## 现状分析

### 当前问题（执行后剩余）

| # | 问题 | 严重程度 | 解决状态 |
|---|------|----------|----------|
| 1 | **根目录 Python 文件过多** — 16 个 `.py` 文件散落 | 🔴 高 | ⏸️ 阶段 6 远期目标 |
| 5 | **`tools/environments/` 命名混淆** | 🟡 中 | ⏸️ 阶段 5 待执行 |
| — | **`.plans/` 幽灵目录**（dotfile，非本次 `plans/`） | 🟢 低 | ⏸️ 待确认用途 |
| — | **`temp_vision_images/` 空目录**（已在 .gitignore） | 🟢 低 | ✅ 已忽略 |

### 改动风险评估（参考）

| 改动类型 | 影响范围 | 风险 |
|----------|----------|------|
| 移动文档/非代码文件 | 仅文件路径变更 | ✅ 无风险 |
| 移动配置示例 | 仅文件路径变更 | ✅ 无风险 |
| 移动 Docker/Nix 文件 | 需更新 CI 引用路径 | ✅ 低风险 |
| 移动 `scripts` 文件 | 需更新用户文档 | ✅ 低风险 |
| 重命名 Python 包路径 | 影响数十个 import 语句 | ⚠️ 中风险 |
| 将根 .py 移入包结构 | 影响 pyproject.toml + 数百个 import | 🔴 高风险 |

---

## 整理方案（分阶段执行）

### 阶段 1: 文档重组（✅ 已完成 2026-04-30）

```
当前结构 → 目标结构
──────────────────────────────────────────────────────────
AGENTS.md                  →  docs/dev/AGENTS.md  ✅
CONTRIBUTING.md            →  docs/dev/CONTRIBUTING.md  ✅
SECURITY.md                →  docs/dev/SECURITY.md  ✅
README.md                  →  保留在根目录  ✅
docs/变更记录/             →  docs/changelog/  ✅
docs/问题记录/             →  docs/issues/  ✅
docs/release_docs/         →  docs/releases/  ✅
docs/远程仓库同步管理...md  →  docs/git/remote-sync-guide.md  ✅
docs/hermes-already-has... →  docs/guides/  ✅
docs/Telegram*.md          →  docs/gateway/  ✅
plans/                     →  docs/plans/  ✅
```

**操作清单：**
- [x] 创建 `docs/dev/`、`docs/changelog/`、`docs/issues/`、`docs/releases/`、`docs/guides/`、`docs/gateway/`、`docs/git/`、`docs/plans/` 子目录
- [x] 移动 `AGENTS.md` → `docs/dev/AGENTS.md`
- [x] 移动 `CONTRIBUTING.md` → `docs/dev/CONTRIBUTING.md`
- [x] 移动 `SECURITY.md` → `docs/dev/SECURITY.md`
- [x] 移动 `docs/变更记录/*` → `docs/changelog/`（重命名英文文件名）
- [x] 移动 `docs/问题记录/*` → `docs/issues/`
- [x] 移动 `docs/release_docs/*` → `docs/releases/`
- [x] 移动 `docs/远程仓库同步*.md` → `docs/git/`
- [x] 移动 `docs/hermes-already-has-routines.md` → `docs/guides/`
- [x] 移动 `docs/Telegram命令注册方案.md` → `docs/gateway/`
- [x] 移动 `docs/Telegram增加自定义BotAPI域名方案.md` → `docs/gateway/`
- [x] 移动 `plans/*` → `docs/plans/`
- [x] 删除空的 `plans/` 目录

---

### 阶段 2: 配置与示例合并（✅ 已完成 2026-04-30）

```
当前结构 → 目标结构
──────────────────────────────────────────────────────────
cli-config.yaml.example     →  examples/config/cli-config.yaml  ✅
.env.example                →  examples/config/env.example  ✅
datagen-config-examples/    →  examples/datagen/  ✅
  ├── example_browser_tasks.jsonl
  ├── run_browser_tasks.sh
  ├── trajectory_compression.yaml
  └── web_research.yaml
```

**操作清单：**
- [x] 创建 `examples/config/`、`examples/datagen/` 目录
- [x] 移动 `cli-config.yaml.example` → `examples/config/cli-config.yaml`
- [x] 移动 `.env.example` → `examples/config/env.example`
- [x] 移动 `datagen-config-examples/*` → `examples/datagen/`
- [x] 删除空的 `datagen-config-examples/` 目录

---

### 阶段 3: 打包与构建文件合并（✅ 已完成 2026-04-30）

```
当前结构 → 目标结构
──────────────────────────────────────────────────────────
Dockerfile                  →  docker/Dockerfile  ✅
.dockerignore               →  docker/.dockerignore  ✅
docker-compose.yml          →  docker/docker-compose.yml  ✅
docker/SOUL.md              →  docker/SOUL.md（保留不变）✅
nix/                        →  packaging/nix/  ✅
  ├── hermes-agent.nix
  └── overlays.nix
constraints-termux.txt      →  packaging/constraints/termux.txt  ✅
setup-hermes.sh             →  scripts/setup-hermes.sh  ✅
```

> **注意：** 本次执行中同时进行了以下依赖文件更新：
> - `.github/workflows/docker-publish.yml`：`Dockerfile` → `docker/Dockerfile`（3 处）
> - `scripts/setup-hermes.sh`：`constraints-termux.txt` → `packaging/constraints/termux.txt`
> - `tests/hermes_cli/test_setup_hermes_script.py`：路径同步更新
> - `README.md`：`setup-hermes.sh` → `scripts/setup-hermes.sh`

**操作清单：**
- [x] 移动 `Dockerfile` → `docker/Dockerfile`
- [x] 移动 `.dockerignore` → `docker/.dockerignore`
- [x] 移动 `docker-compose.yml` → `docker/docker-compose.yml`
- [x] 创建 `packaging/nix/` 目录，移动 `nix/*` 进去
- [x] 删除空的 `nix/` 目录
- [x] 创建 `packaging/constraints/` 目录，移动 `constraints-termux.txt` 进去
- [x] 移动 `setup-hermes.sh` → `scripts/setup-hermes.sh`
- [x] 更新 `README.md` 中的安装说明路径
- [x] 更新 CI 工作流 `docker-publish.yml` 中的 Dockerfile 路径
- [x] 更新 `scripts/setup-hermes.sh` 中的 constraints 文件路径
- [x] 更新测试文件 `test_setup_hermes_script.py` 中的文件路径

---

### 阶段 4: 清理冗余文件与目录（✅ 已完成 2026-04-30）

**操作清单：**
- [x] 将 `assets/banner.png` → `docs/assets/banner.png`（并更新 README.md 引用）
- [ ] ~~删除空的 `tinker-atropos/` 目录~~（保留，它是 git 子模块，定义在 `.gitmodules`）
- [x] 删除空的 `assets/` 目录（移动 banner.png 后）
- [x] 更新 `.gitignore`，添加更多已知临时目录模式

---

### 阶段 5: 工具类子包重命名（⚠️ 中等风险，涉及 import 更新）

**当前状态：⏸️ 暂缓执行**

**问题：** `tools/environments/` 是终端执行后端（local/docker/ssh/modal/daytona），根目录 `environments/` 是 RL 训练环境，命名易混淆。

```
tools/environments/          →  tools/execution_environments/
  ├── __init__.py
  ├── base.py
  ├── local.py
  ├── docker.py
  ├── ssh.py
  ├── modal.py
  ├── daytona.py
  ├── singularity.py
  └── file_sync.py
```

**涉及 import 更新的文件（共 7 个测试文件）：**
- `tests/tools/test_docker_environment.py`
- `tests/tools/test_docker_find.py`
- `tests/tools/test_modal_bulk_upload.py`
- `tests/tools/test_ssh_bulk_upload.py`
- `tests/tools/test_ssh_environment.py`
- `tests/tools/test_sync_back_backends.py`
- `tools/browser_providers/__init__.py`

**可选方案 B（更低风险）：** 不重命名目录，仅在 `tools/environments/` 中添加 README.md 说明与根 `environments/` 的区分。

---

### 阶段 6: 根目录 Python 源文件归入包结构（🔴 高风险，暂不建议）

> **不建议一次性执行**。根目录 16 个 `.py` 文件被 45+ 文件、数百个 import 语句引用。强制迁移会：
> - 需要同时更新 `pyproject.toml` 中的 `[project.scripts]` 入口点
> - 需要更新 `hermes` 启动脚本的引用路径
> - 需要修改 `run_agent.py` 中 `from run_agent import AIAgent` 的自引用模式
> - 大量测试文件需同步更新
>
> **建议**：将此作为长期重构目标，未来有计划地迁移核心模块。

---

## 验证清单

每个阶段完成后，执行以下验证：

```bash
# 1. 运行完整测试套件
scripts/run_tests.sh

# 2. 验证导入无错误
python -c "from hermes_cli.main import main; print('CLI OK')"
python -c "from run_agent import AIAgent; print('Agent OK')"

# 3. 检查是否有文件遗漏
git status
```

---

## 附录: 变更后根目录当前状态

```
hermes-agent/
├── hermes                  # 启动脚本
├── pyproject.toml           # 包配置
├── README.md                # 项目介绍
├── PROJECT_REORGANIZATION_PLAN.md  # 本文档
├── LICENSE                  # 许可证
├── .env                     # 环境变量（保留，未移动）
├── .envrc                   # direnv 配置
│
├── [16 个根 Python 文件]    # 🔴 保留（阶段 6 远期目标）
│   ├── run_agent.py
│   ├── cli.py
│   ├── hermes_constants.py
│   ├── hermes_logging.py
│   ├── hermes_state.py
│   ├── hermes_time.py
│   ├── model_tools.py
│   ├── toolsets.py
│   ├── toolset_distributions.py
│   ├── batch_runner.py
│   ├── trajectory_compressor.py
│   ├── mcp_serve.py
│   ├── mini_swe_runner.py
│   ├── rl_cli.py
│   ├── utils.py
│   └── package.json / package-lock.json / uv.lock
│
├── agent/                   # AIAgent 核心
├── hermes_cli/              # CLI 子系统
├── gateway/                 # 消息网关
├── tools/                   # 工具实现
├── tui_gateway/             # TUI 后端
├── ui-tui/                  # TUI 前端
├── web/                     # 网页仪表盘
├── website/                 # 文档站点
├── plugins/                 # 插件
├── skills/                  # 内置技能
├── optional-skills/         # 可选技能
├── cron/                    # 调度器
├── environments/            # RL 训练环境
├── acp_adapter/             # ACP 服务器
├── acp_registry/            # ACP 注册表
├── tests/                   # 测试
│
├── docs/                    # 📁 统一文档目录
│   ├── assets/              #    媒体资源
│   ├── dev/                 #    开发者文档
│   ├── changelog/           #    变更记录
│   ├── issues/              #    问题记录
│   ├── releases/            #    版本发布说明
│   ├── guides/              #    操作指南
│   ├── gateway/             #    网关文档
│   ├── git/                 #    Git 工作流文档
│   └── plans/               #    设计规划文档
│
├── examples/                # 📁 统一示例目录
│   ├── config/              #    配置示例
│   └── datagen/             #    数据生成示例
│
├── docker/                  # 📁 Docker 配置
│   ├── Dockerfile
│   ├── .dockerignore
│   ├── docker-compose.yml
│   └── SOUL.md
│
├── packaging/               # 📁 打包构建
│   ├── homebrew/            #    Homebrew 打包
│   ├── nix/                 #    Nix 打包
│   └── constraints/         #    平台约束
│
├── scripts/                 # 📁 辅助脚本
│   ├── setup-hermes.sh      #    安装脚本（从根目录移入）
│   ├── release.py
│   └── ...
│
├── tinker-atropos/          # Git 子模块（不可删除）
└── temp_vision_images/      # 临时目录（已在 .gitignore）
```
