# Telegram 命令注册实现方案

本文档详细说明 Hermes 仓库中 Telegram 渠道的命令注册实现机制。

## 核心架构概述

Telegram 命令注册采用**中心化注册表 (Central Registry)** 模式，所有平台的命令定义统一存储在 `hermes_cli/commands.py` 中，然后根据各平台特性导出适配的格式。

```
┌─────────────────────────────────────────────────────────────┐
│           hermes_cli/commands.py (命令定义中心)              │
│  ┌─────────────────────────────────────────────────────┐   │
│  │ COMMAND_REGISTRY: list[CommandDef]                    │   │
│  │  - Core commands (Session, Configuration, etc.)      │   │
│  │  - Plugin commands                                  │   │
│  │  - Skill commands                                   │   │
│  └─────────────────────────────────────────────────────┘   │
│                          │                                  │
│           ┌──────────────┼──────────────┐                   │
│           ▼              ▼              ▼                     │
│  telegram_menu_commands()  discord_xxx()  slack_subcommand_map()
```

## 1. 命令定义中心 (hermes_cli/commands.py)

### 1.1 CommandDef 数据类

```python
@dataclass(frozen=True)
class CommandDef:
    name: str                          # 规范名称: "background"
    description: str                   # 人类可读描述
    category: str                     # 分类: "Session", "Configuration" 等
    aliases: tuple[str, ...] = ()      # 别名: ("bg",)
    args_hint: str = ""                # 参数占位符: "<prompt>", "[name]"
    subcommands: tuple[str, ...] = () # 可Tab补全的子命令
    cli_only: bool = False            # 仅 CLI 可用
    gateway_only: bool = False          # 仅 Gateway/消息平台可用
    gateway_config_gate: str | None = None  # 配置门控
```

### 1.2 命令注册表示例

```python
COMMAND_REGISTRY: list[CommandDef] = [
    # Session 分类
    CommandDef("new", "开启新会话", "Session",
             aliases=("reset",)),
    CommandDef("clear", "清屏并开始新会话", "Session",
             cli_only=True),
    CommandDef("background", "在后台运行提示词任务", "Session",
             aliases=("bg",), args_hint="<prompt>"),
    
    # Configuration 分类
    CommandDef("model", "切换当前会话的模型", "Configuration",
             args_hint="[model] [--provider name] [--global]"),
    CommandDef("verbose", "循环切换工具进度显示模式", "Configuration",
             cli_only=True,
             gateway_config_gate="display.tool_progress_command"),
    
    # Gateway 专用
    CommandDef("help", "显示可用命令", "Info"),
    CommandDef("commands", "浏览所有命令和技能", "Info",
             gateway_only=True, args_hint="[page]"),
]
```

### 1.3 命令解析与查找

```python
_COMMAND_LOOKUP: dict[str, CommandDef] = _build_command_lookup()

def resolve_command(name: str) -> CommandDef | None:
    """解析命令名或别名到 CommandDef"""
    return _COMMAND_LOOKUP.get(name.lower().lstrip("/"))
```

## 2. Telegram 专用命令函数

### 2.1 telegram_bot_commands()

生成 Telegram Bot API `setMyCommands` 所需的命令列表。

```python
def telegram_bot_commands() -> list[tuple[str, str]]:
    """返回 (命令名, 描述) 对，用于 Telegram setMyCommands"""
    overrides = _resolve_config_gates()
    result: list[tuple[str, str]] = []
    for cmd in COMMAND_REGISTRY:
        if not _is_gateway_available(cmd, overrides):
            continue
        tg_name = _sanitize_telegram_name(cmd.name)
        if tg_name:
            result.append((tg_name, cmd.description))
    # 包含插件命令
    for name, description, _args_hint in _iter_plugin_command_entries():
        tg_name = _sanitize_telegram_name(name)
        if tg_name:
            result.append((tg_name, description))
    return result
```

### 2.2 telegram_menu_commands() - 菜单命令生成

返回 Telegram 菜单命令列表，限制为 100 条（Bot API 上限）。

```python
def telegram_menu_commands(max_commands: int = 100) -> tuple[list[tuple[str, str]], int]:
    """返回 Telegram 菜单命令，限制为 Bot API 上限
    
    优先级:
      1. Core CommandDef commands (始终包含)
      2. Plugin slash commands (优先于 skills)
      3. Built-in skill commands (填充剩余槽位)
    
    返回:
      (menu_commands, hidden_count) - hidden_count 是因上限被隐藏的 skill 数量
    """
    core_commands = list(telegram_bot_commands())
    reserved_names = {n for n, _ in core_commands}
    all_commands = list(core_commands)
    
    remaining_slots = max(0, max_commands - len(all_commands))
    entries, hidden_count = _collect_gateway_skill_entries(
        platform="telegram",
        max_slots=remaining_slots,
        reserved_names=reserved_names,
        desc_limit=40,  # Telegram 描述上限
        sanitize_name=_sanitize_telegram_name,
    )
    
    all_commands.extend((n, d) for n, d, _k in entries)
    return all_commands[:max_commands], hidden_count
```

### 2.3 命令名规范化

Telegram 要求命令名：1-32 字符、仅小写 a-z、0-9、下划线。

```python
# 正则: 移除所有非 a-z0-9_ 的字符
_TG_INVALID_CHARS = re.compile(r"[^a-z0-9_]")
_TG_MULTI_UNDERSCORE = re.compile(r"_{2,}")

def _sanitize_telegram_name(raw: str) -> str:
    """转换为有效的 Telegram 命令名"""
    name = raw.lower().replace("-", "_")
    name = _TG_INVALID_CHARS.sub("", name)
    name = _TG_MULTI_UNDERSCORE.sub("_", name)
    return name.strip("_")
```

### 2.4 命令名长度限制处理

```python
def _clamp_command_names(
    entries: list[tuple[str, str]],
    reserved: set[str],
) -> list[tuple[str, str]]:
    """强制 32 字符限制并处理冲突
    
    超长名称截断至 32 字符，若冲突则添加数字后缀 (name0-name9)
    """
    used: set[str] = set(reserved)
    result: list[tuple[str, str]] = []
    
    for name, desc in entries:
        if len(name) > 32:
            candidate = name[:32]
            if candidate in used:
                prefix = name[:31]
                for digit in range(10):
                    candidate = f"{prefix}{digit}"
                    if candidate not in used:
                        break
                else:
                    continue  # 所有数字槽位用尽，跳过
            name = candidate
        if name in used:
            continue
        used.add(name)
        result.append((name, desc))
    
    return result
```

## 3. Skill/Plugin 命令收集

### 3.1 _collect_gateway_skill_entries()

从插件和 skill 收集命令条目，供各平台使用。

```python
def _collect_gateway_skill_entries(
    platform: str,
    max_slots: int,
    reserved_names: set[str],
    desc_limit: int = 100,
    sanitize_name: Callable[[str], str] | None = None,
) -> tuple[list[tuple[str, str, str]], int]:
    """收集平台可用的 plugin + skill 条目
    
    优先级:
      1. Plugin slash commands (不被裁剪)
      2. Built-in skill commands (达到上限时裁剪)
    
    过滤规则:
      - Hub 安装的 skill 排除
      - 平台禁用列表中的 skill 排除
    """
```

## 4. Telegram 平台适配器实现

### 4.1 命令注册调用 (gateway/platforms/telegram.py)

在 Telegram 连接时注册命令菜单：

```python
# 位置: TelegramPlatformAdapter.start() 方法中

async def start(self) -> bool:
    # ... 连接代码 ...
    
    # 注册 bot 命令，使 Telegram 在用户输入 / 时显示提示菜单
    # 列表来自中心 COMMAND_REGISTRY
    try:
        from telegram import BotCommand
        from hermes_cli.commands import telegram_menu_commands
        
        # Telegram 允许最多 100 条命令，存在未文档化的 payload 大小限制
        # Skill 描述在 telegram_menu_commands() 中截断至 40 字符以安全容纳 100 条命令
        menu_commands, hidden_count = telegram_menu_commands(max_commands=100)
        await self._bot.set_my_commands([
            BotCommand(name, desc) for name, desc in menu_commands
        ])
        
        if hidden_count:
            logger.info(
                "[%s] Telegram menu: %d commands registered, %d hidden "
                "(over 100 limit). Use /commands for full list.",
                self.name, len(menu_commands), hidden_count
            )
    except Exception as e:
        logger.warning(
            "[%s] Could not register Telegram command menu: %s",
            self.name, e, exc_info=True
        )
```

## 5. 注册流程时序图

```
Telegram Platform Start
         │
         ▼
┌─────────────────────┐
│  Initialize Bot     │
│  (python-telegram) │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│  Connect to       │
│  Telegram API    │
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ telegram_menu_     │◄────────────┐
│ commands(max=100) │             │
└─────────────────────┘             │
         │                           │
    ┌────┴────┐                     │
    ▼         ▼                     │
┌────────┐ ┌──────────┐            │
│ Core   │ │ Plugin   │            │
│ cmds   │ │ commands │            │
└────────┘ └──────────┘            │
    │                           ┌───┘
    ▼                           │
┌─────────────────────┐        │
│ _collect_gateway_   │        │
│ skill_entries()     │────────┘
│ (skills)            │      
└─────────────────────┘       
         │
         ▼
┌─────────────────────┐
│ _sanitize_telegram_ │◄─── 规范化命令名
│ name()             │     (小写、下划线)
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ _clamp_command_     │◄─── 32字符限制
│ names()            │     冲突处理
└─────────────────────┘
         │
         ▼
┌─────────────────────┐
│ bot.set_my_commands │◄─── Telegram API
│ ([BotCommand, ...]) │     注册菜单
└─────────────────────┘
         │
         ▼
    User sees /help /new /model ...
```

## 6. 关键配置门控

部分命令通过 `gateway_config_gate` 实现条件性可用：

```python
# 例如: verbose 命令仅在 display.tool_progress_command 配置为真时在 gateway 中可用
CommandDef("verbose", "循环切换工具进度显示模式", "Configuration",
          cli_only=True,
          gateway_config_gate="display.tool_progress_command")

def _resolve_config_gates() -> set[str]:
    """读取 config.yaml 解析配置门控"""
    # 遍历 gateway_config_gate 为真的命令，从配置中获取对应值
```

## 7. 添加新命令流程

1. 在 `COMMAND_REGISTRY` 中添加 `CommandDef` 条目
2. 若是 CLI 专用命令，设置 `cli_only=True`
3. 若是 Gateway 专用命令，设置 `gateway_only=True`
4. 需要配置门控时，设置 `gateway_config_gate="config.path"`
5. 命令自动出现在 Telegram 命令菜单中（重启 bot 后）

## 8. 文件位置汇总

| 文件 | 职责 |
|------|------|
| `hermes_cli/commands.py` | 命令定义中心、导出函数 |
| `gateway/platforms/telegram.py` | Telegram 平台适配器 |
| `gateway/platforms/discord.py` | Discord 平台适配器 (类似模式) |
| `agent/skill_commands.py` | Skill 命令定义 |
| `hermes_cli/plugins.py` | 插件命令注册 |

## 9. 核心设计原则

1. **单一来源**: `COMMAND_REGISTRY` 是所有命令的唯一真理
2. **平台适配**: 各平台通过专门的 `*_menu_commands()` 函数获取适配后的命令列表
3. **优先级机制**: Core commands > Plugin commands > Skills (裁剪时优先级相反)
4. **配置门控**: 通过 `gateway_config_gate` 实现条件性命令暴露
5. **名称规范化**: 各平台有自己的命名规则 (Telegram 最严格)