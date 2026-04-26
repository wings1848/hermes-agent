"""
Interactive setup wizard for Hermes Agent.

Modular wizard with independently-runnable sections:
  1. Model & Provider — choose your AI provider and model
  2. Terminal Backend — where your agent runs commands
  3. Agent Settings — iterations, compression, session reset
  4. Messaging Platforms — connect Telegram, Discord, etc.
  5. Tools — configure TTS, web search, image generation, etc.

Config files are stored in ~/.hermes/ for easy access.
"""

import importlib.util
import logging
import os
import shutil
import sys
import copy
from pathlib import Path
from typing import Optional, Dict, Any

from hermes_cli.nous_subscription import get_nous_subscription_features
from tools.tool_backend_helpers import managed_nous_tools_enabled
from utils import base_url_hostname
from hermes_constants import get_optional_skills_dir

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.resolve()

_DOCS_BASE = "https://hermes-agent.nousresearch.com/docs"


def _model_config_dict(config: Dict[str, Any]) -> Dict[str, Any]:
    current_model = config.get("model")
    if isinstance(current_model, dict):
        return dict(current_model)
    if isinstance(current_model, str) and current_model.strip():
        return {"default": current_model.strip()}
    return {}


def _get_credential_pool_strategies(config: Dict[str, Any]) -> Dict[str, str]:
    strategies = config.get("credential_pool_strategies")
    return dict(strategies) if isinstance(strategies, dict) else {}


def _set_credential_pool_strategy(config: Dict[str, Any], provider: str, strategy: str) -> None:
    if not provider:
        return
    strategies = _get_credential_pool_strategies(config)
    strategies[provider] = strategy
    config["credential_pool_strategies"] = strategies


def _supports_same_provider_pool_setup(provider: str) -> bool:
    if not provider or provider == "custom":
        return False
    if provider == "openrouter":
        return True
    from hermes_cli.auth import PROVIDER_REGISTRY

    pconfig = PROVIDER_REGISTRY.get(provider)
    if not pconfig:
        return False
    return pconfig.auth_type in {"api_key", "oauth_device_code"}


# Default model lists per provider — used as fallback when the live
# /models endpoint can't be reached.
_DEFAULT_PROVIDER_MODELS = {
    "copilot-acp": [
        "copilot-acp",
    ],
    "copilot": [
        "gpt-5.4",
        "gpt-5.4-mini",
        "gpt-5-mini",
        "gpt-5.3-codex",
        "gpt-5.2-codex",
        "gpt-4.1",
        "gpt-4o",
        "gpt-4o-mini",
        "claude-opus-4.6",
        "claude-sonnet-4.6",
        "claude-sonnet-4.5",
        "claude-haiku-4.5",
        "gemini-2.5-pro",
        "grok-code-fast-1",
    ],
    "gemini": [
        "gemini-3.1-pro-preview", "gemini-3-pro-preview",
        "gemini-3-flash-preview", "gemini-3.1-flash-lite-preview",
    ],
    "zai": ["glm-5.1", "glm-5", "glm-4.7", "glm-4.5", "glm-4.5-flash"],
    "kimi-coding": ["kimi-k2.6", "kimi-k2.5", "kimi-k2-thinking", "kimi-k2-turbo-preview"],
    "kimi-coding-cn": ["kimi-k2.6", "kimi-k2.5", "kimi-k2-thinking", "kimi-k2-turbo-preview"],
    "stepfun": ["step-3.5-flash", "step-3.5-flash-2603"],
    "arcee": ["trinity-large-thinking", "trinity-large-preview", "trinity-mini"],
    "minimax": ["MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M2.1", "MiniMax-M2"],
    "minimax-cn": ["MiniMax-M2.7", "MiniMax-M2.5", "MiniMax-M2.1", "MiniMax-M2"],
    "ai-gateway": ["anthropic/claude-opus-4.6", "anthropic/claude-sonnet-4.6", "openai/gpt-5", "google/gemini-3-flash"],
    "kilocode": ["anthropic/claude-opus-4.6", "anthropic/claude-sonnet-4.6", "openai/gpt-5.4", "google/gemini-3-pro-preview", "google/gemini-3-flash-preview"],
    "opencode-zen": ["gpt-5.4", "gpt-5.3-codex", "claude-sonnet-4-6", "gemini-3-flash", "glm-5", "kimi-k2.5", "minimax-m2.7"],
    "opencode-go": ["kimi-k2.6", "kimi-k2.5", "glm-5.1", "glm-5", "mimo-v2.5-pro", "mimo-v2.5", "mimo-v2-pro", "mimo-v2-omni", "minimax-m2.7", "minimax-m2.5", "qwen3.6-plus", "qwen3.5-plus"],
    "huggingface": [
        "Qwen/Qwen3.5-397B-A17B", "Qwen/Qwen3-235B-A22B-Thinking-2507",
        "Qwen/Qwen3-Coder-480B-A35B-Instruct", "deepseek-ai/DeepSeek-R1-0528",
        "deepseek-ai/DeepSeek-V3.2", "moonshotai/Kimi-K2.5",
    ],
}


def _current_reasoning_effort(config: Dict[str, Any]) -> str:
    agent_cfg = config.get("agent")
    if isinstance(agent_cfg, dict):
        return str(agent_cfg.get("reasoning_effort") or "").strip().lower()
    return ""


def _set_reasoning_effort(config: Dict[str, Any], effort: str) -> None:
    agent_cfg = config.get("agent")
    if not isinstance(agent_cfg, dict):
        agent_cfg = {}
        config["agent"] = agent_cfg
    agent_cfg["reasoning_effort"] = effort




# Import config helpers
from hermes_cli.config import (
    DEFAULT_CONFIG,
    get_hermes_home,
    get_config_path,
    get_env_path,
    load_config,
    save_config,
    save_env_value,
    get_env_value,
    ensure_hermes_home,
)
# display_hermes_home imported lazily at call sites (stale-module safety during hermes update)

from hermes_cli.colors import Colors, color


def print_header(title: str):
    """Print a section header."""
    print()
    print(color(f"◆ {title}", Colors.CYAN, Colors.BOLD))


from hermes_cli.cli_output import (  # noqa: E402
    print_error,
    print_info,
    print_success,
    print_warning,
)


def is_interactive_stdin() -> bool:
    """Return True when stdin looks like a usable interactive TTY."""
    stdin = getattr(sys, "stdin", None)
    if stdin is None:
        return False
    try:
        return bool(stdin.isatty())
    except Exception:
        return False


def print_noninteractive_setup_guidance(reason: str | None = None) -> None:
    """Print guidance for headless/non-interactive setup flows."""
    print()
    print(color("⚕ Hermes Setup — Non-interactive mode", Colors.CYAN, Colors.BOLD))
    print()
    if reason:
        print_info(reason)
    print_info("此处无法使用交互式向导。")
    print()
    print_info("请通过环境变量或配置命令来配置 Hermes：")
    print_info("  hermes config set model.provider custom")
    print_info("  hermes config set model.base_url http://localhost:8080/v1")
    print_info("  hermes config set model.default your-model-name")
    print()
    print_info("或在环境中设置 OPENROUTER_API_KEY / OPENAI_API_KEY。")
    print_info("在交互式终端中运行 'hermes setup' 可使用完整向导。")
    print()


def prompt(question: str, default: str = None, password: bool = False) -> str:
    """Prompt for input with optional default."""
    if default:
        display = f"{question} [{default}]: "
    else:
        display = f"{question}: "

    try:
        if password:
            import getpass

            value = getpass.getpass(color(display, Colors.YELLOW))
        else:
            value = input(color(display, Colors.YELLOW))

        return value.strip() or default or ""
    except (KeyboardInterrupt, EOFError):
        print()
        sys.exit(1)


def _curses_prompt_choice(question: str, choices: list, default: int = 0, description: str | None = None) -> int:
    """Single-select menu using curses. Delegates to curses_radiolist."""
    from hermes_cli.curses_ui import curses_radiolist
    return curses_radiolist(question, choices, selected=default, cancel_returns=-1, description=description)



def prompt_choice(question: str, choices: list, default: int = 0, description: str | None = None) -> int:
    """Prompt for a choice from a list with arrow key navigation.

    Escape keeps the current default (skips the question).
    Ctrl+C exits the wizard.
    """
    idx = _curses_prompt_choice(question, choices, default, description=description)
    if idx >= 0:
        if idx == default:
            print_info("  已跳过（保持当前）")
            print()
            return default
        print()
        return idx

    print(color(question, Colors.YELLOW))
    for i, choice in enumerate(choices):
        marker = "●" if i == default else "○"
        if i == default:
            print(color(f"  {marker} {choice}", Colors.GREEN))
        else:
            print(f"  {marker} {choice}")

    print_info(f"  回车使用默认值 ({default + 1})  Ctrl+C 退出")

    while True:
        try:
            value = input(
                color(f"  Select [1-{len(choices)}] ({default + 1}): ", Colors.DIM)
            )
            if not value:
                return default
            idx = int(value) - 1
            if 0 <= idx < len(choices):
                return idx
            print_error(f"Please enter a number between 1 and {len(choices)}")
        except ValueError:
            print_error("Please enter a number")
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt for yes/no. Ctrl+C exits, empty input returns default."""
    default_str = "Y/n" if default else "y/N"

    while True:
        try:
            value = (
                input(color(f"{question} [{default_str}]: ", Colors.YELLOW))
                .strip()
                .lower()
            )
        except (KeyboardInterrupt, EOFError):
            print()
            sys.exit(1)

        if not value:
            return default
        if value in ("y", "yes"):
            return True
        if value in ("n", "no"):
            return False
        print_error("Please enter 'y' or 'n'")


def prompt_checklist(title: str, items: list, pre_selected: list = None) -> list:
    """
    Display a multi-select checklist and return the indices of selected items.

    Each item in `items` is a display string. `pre_selected` is a list of
    indices that should be checked by default. A "Continue →" option is
    appended at the end — the user toggles items with Space and confirms
    with Enter on "Continue →".

    Falls back to a numbered toggle interface when simple_term_menu is
    unavailable.

    Returns:
        List of selected indices (not including the Continue option).
    """
    if pre_selected is None:
        pre_selected = []

    from hermes_cli.curses_ui import curses_checklist

    chosen = curses_checklist(
        title,
        items,
        set(pre_selected),
        cancel_returns=set(pre_selected),
    )
    return sorted(chosen)


def _prompt_api_key(var: dict):
    """Display a nicely formatted API key input screen for a single env var."""
    tools = var.get("tools", [])
    tools_str = ", ".join(tools[:3])
    if len(tools) > 3:
        tools_str += f", +{len(tools) - 3} more"

    print()
    print(color(f"  ─── {var.get('description', var['name'])} ───", Colors.CYAN))
    print()
    if tools_str:
        print_info(f"  启用: {tools_str}")
    if var.get("url"):
        print_info(f"  获取密钥: {var['url']}")
    print()

    if var.get("password"):
        value = prompt(f"  {var.get('prompt', var['name'])}", password=True)
    else:
        value = prompt(f"  {var.get('prompt', var['name'])}")

    if value:
        save_env_value(var["name"], value)
        print_success("  ✓ 已保存")
    else:
        print_warning("  已跳过（稍后通过 'hermes setup' 配置）")


def _print_setup_summary(config: dict, hermes_home):
    """Print the setup completion summary."""
    # Tool availability summary
    print()
    print_header("Tool Availability Summary")

    tool_status = []
    subscription_features = get_nous_subscription_features(config)

    # Vision — use the same runtime resolver as the actual vision tools
    try:
        from agent.auxiliary_client import get_available_vision_backends

        _vision_backends = get_available_vision_backends()
    except Exception:
        _vision_backends = []

    if _vision_backends:
        tool_status.append(("Vision (image analysis)", True, None))
    else:
        tool_status.append(("Vision (image analysis)", False, "run 'hermes setup' to configure"))

    # Mixture of Agents — requires OpenRouter specifically (calls multiple models)
    if get_env_value("OPENROUTER_API_KEY"):
        tool_status.append(("Mixture of Agents", True, None))
    else:
        tool_status.append(("Mixture of Agents", False, "OPENROUTER_API_KEY"))

    # Web tools (Exa, Parallel, Firecrawl, or Tavily)
    if subscription_features.web.managed_by_nous:
        tool_status.append(("Web Search & Extract (Nous subscription)", True, None))
    elif subscription_features.web.available:
        label = "Web Search & Extract"
        if subscription_features.web.current_provider:
            label = f"Web Search & Extract ({subscription_features.web.current_provider})"
        tool_status.append((label, True, None))
    else:
        tool_status.append(("Web Search & Extract", False, "EXA_API_KEY, PARALLEL_API_KEY, FIRECRAWL_API_KEY/FIRECRAWL_API_URL, or TAVILY_API_KEY"))

    # Browser tools (local Chromium, Camofox, Browserbase, Browser Use, or Firecrawl)
    browser_provider = subscription_features.browser.current_provider
    if subscription_features.browser.managed_by_nous:
        tool_status.append(("Browser Automation (Nous Browser Use)", True, None))
    elif subscription_features.browser.available:
        label = "Browser Automation"
        if browser_provider:
            label = f"Browser Automation ({browser_provider})"
        tool_status.append((label, True, None))
    else:
        missing_browser_hint = "npm install -g agent-browser, set CAMOFOX_URL, or configure Browser Use or Browserbase"
        if browser_provider == "Browserbase":
            missing_browser_hint = (
                "npm install -g agent-browser and set "
                "BROWSERBASE_API_KEY/BROWSERBASE_PROJECT_ID"
            )
        elif browser_provider == "Browser Use":
            missing_browser_hint = (
                "npm install -g agent-browser and set BROWSER_USE_API_KEY"
            )
        elif browser_provider == "Camofox":
            missing_browser_hint = "CAMOFOX_URL"
        elif browser_provider == "Local browser":
            missing_browser_hint = "npm install -g agent-browser"
        tool_status.append(
            ("Browser Automation", False, missing_browser_hint)
        )

    # Image generation — FAL (direct or via Nous), or any plugin-registered
    # provider (OpenAI, etc.)
    if subscription_features.image_gen.managed_by_nous:
        tool_status.append(("Image Generation (Nous subscription)", True, None))
    elif subscription_features.image_gen.available:
        tool_status.append(("Image Generation", True, None))
    else:
        # Fall back to probing plugin-registered providers so OpenAI-only
        # setups don't show as "missing FAL_KEY".
        _img_backend = None
        try:
            from agent.image_gen_registry import list_providers
            from hermes_cli.plugins import _ensure_plugins_discovered

            _ensure_plugins_discovered()
            for _p in list_providers():
                if _p.name == "fal":
                    continue
                try:
                    if _p.is_available():
                        _img_backend = _p.display_name
                        break
                except Exception:
                    continue
        except Exception:
            pass
        if _img_backend:
            tool_status.append((f"Image Generation ({_img_backend})", True, None))
        else:
            tool_status.append(("Image Generation", False, "FAL_KEY or OPENAI_API_KEY"))

    # TTS — show configured provider
    tts_provider = config.get("tts", {}).get("provider", "edge")
    if subscription_features.tts.managed_by_nous:
        tool_status.append(("Text-to-Speech (OpenAI via Nous subscription)", True, None))
    elif tts_provider == "elevenlabs" and get_env_value("ELEVENLABS_API_KEY"):
        tool_status.append(("Text-to-Speech (ElevenLabs)", True, None))
    elif tts_provider == "openai" and (
        get_env_value("VOICE_TOOLS_OPENAI_KEY") or get_env_value("OPENAI_API_KEY")
    ):
        tool_status.append(("Text-to-Speech (OpenAI)", True, None))
    elif tts_provider == "minimax" and get_env_value("MINIMAX_API_KEY"):
        tool_status.append(("Text-to-Speech (MiniMax)", True, None))
    elif tts_provider == "mistral" and get_env_value("MISTRAL_API_KEY"):
        tool_status.append(("Text-to-Speech (Mistral Voxtral)", True, None))
    elif tts_provider == "gemini" and (get_env_value("GEMINI_API_KEY") or get_env_value("GOOGLE_API_KEY")):
        tool_status.append(("Text-to-Speech (Google Gemini)", True, None))
    elif tts_provider == "neutts":
        try:
            neutts_ok = importlib.util.find_spec("neutts") is not None
        except Exception:
            neutts_ok = False
        if neutts_ok:
            tool_status.append(("Text-to-Speech (NeuTTS local)", True, None))
        else:
            tool_status.append(("Text-to-Speech (NeuTTS — not installed)", False, "run 'hermes setup tts'"))
    elif tts_provider == "kittentts":
        try:
            import importlib.util
            kittentts_ok = importlib.util.find_spec("kittentts") is not None
        except Exception:
            kittentts_ok = False
        if kittentts_ok:
            tool_status.append(("Text-to-Speech (KittenTTS local)", True, None))
        else:
            tool_status.append(("Text-to-Speech (KittenTTS — not installed)", False, "run 'hermes setup tts'"))
    else:
        tool_status.append(("Text-to-Speech (Edge TTS)", True, None))

    if subscription_features.modal.managed_by_nous:
        tool_status.append(("Modal Execution (Nous subscription)", True, None))
    elif config.get("terminal", {}).get("backend") == "modal":
        if subscription_features.modal.direct_override:
            tool_status.append(("Modal Execution (direct Modal)", True, None))
        else:
            tool_status.append(("Modal Execution", False, "run 'hermes setup terminal'"))
    elif managed_nous_tools_enabled() and subscription_features.nous_auth_present:
        tool_status.append(("Modal Execution (optional via Nous subscription)", True, None))

    # Tinker + WandB (RL training)
    if get_env_value("TINKER_API_KEY") and get_env_value("WANDB_API_KEY"):
        tool_status.append(("RL Training (Tinker)", True, None))
    elif get_env_value("TINKER_API_KEY"):
        tool_status.append(("RL Training (Tinker)", False, "WANDB_API_KEY"))
    else:
        tool_status.append(("RL Training (Tinker)", False, "TINKER_API_KEY"))

    # Home Assistant
    if get_env_value("HASS_TOKEN"):
        tool_status.append(("Smart Home (Home Assistant)", True, None))

    # Spotify (OAuth via hermes auth spotify — check auth.json, not env vars)
    try:
        from hermes_cli.auth import get_provider_auth_state
        _spotify_state = get_provider_auth_state("spotify") or {}
        if _spotify_state.get("access_token") or _spotify_state.get("refresh_token"):
            tool_status.append(("Spotify (PKCE OAuth)", True, None))
    except Exception:
        pass

    # Skills Hub
    if get_env_value("GITHUB_TOKEN"):
        tool_status.append(("Skills Hub (GitHub)", True, None))
    else:
        tool_status.append(("Skills Hub (GitHub)", False, "GITHUB_TOKEN"))

    # Terminal (always available if system deps met)
    tool_status.append(("Terminal/Commands", True, None))

    # Task planning (always available, in-memory)
    tool_status.append(("Task Planning (todo)", True, None))

    # Skills (always available -- bundled skills + user-created skills)
    tool_status.append(("Skills (view, create, edit)", True, None))

    # Print status
    available_count = sum(1 for _, avail, _ in tool_status if avail)
    total_count = len(tool_status)

    print_info(f"可用工具类别: {available_count}/{total_count}")
    print()

    for name, available, missing_var in tool_status:
        if available:
            print(f"   {color('✓', Colors.GREEN)} {name}")
        else:
            print(
                f"   {color('✗', Colors.RED)} {name} {color(f'(missing {missing_var})', Colors.DIM)}"
            )

    print()

    disabled_tools = [(name, var) for name, avail, var in tool_status if not avail]
    if disabled_tools:
        print_warning(
            "部分工具未启用。运行 'hermes setup tools' 进行配置，"
        )
        from hermes_constants import display_hermes_home as _dhh
        print_warning(f"或直接编辑 {_dhh()}/.env 添加缺失的 API 密钥。")
        print()

    # Done banner
    print()
    print(
        color(
            "┌─────────────────────────────────────────────────────────┐", Colors.GREEN
        )
    )
    print(
        color(
            "│              ✓ Setup Complete!                          │", Colors.GREEN
        )
    )
    print(
        color(
            "└─────────────────────────────────────────────────────────┘", Colors.GREEN
        )
    )
    print()

    # Show file locations prominently
    from hermes_constants import display_hermes_home as _dhh
    print(color(f"📁 所有文件位于 {_dhh()}/：", Colors.CYAN, Colors.BOLD))
    print()
    print(f"   {color('Settings:', Colors.YELLOW)}  {get_config_path()}")
    print(f"   {color('API Keys:', Colors.YELLOW)}  {get_env_path()}")
    print(
        f"   {color('Data:', Colors.YELLOW)}      {hermes_home}/cron/, sessions/, logs/"
    )
    print()

    print(color("─" * 60, Colors.DIM))
    print()
    print(color("📝 编辑配置：", Colors.CYAN, Colors.BOLD))
    print()
    print(f"   {color('hermes setup', Colors.GREEN)}          重新运行完整向导")
    print(f"   {color('hermes setup model', Colors.GREEN)}    更改模型/提供商")
    print(f"   {color('hermes setup terminal', Colors.GREEN)} 更改终端后端")
    print(f"   {color('hermes setup gateway', Colors.GREEN)}  配置消息平台")
    print(f"   {color('hermes setup tools', Colors.GREEN)}    配置工具提供商")
    print()
    print(f"   {color('hermes config', Colors.GREEN)}         查看当前设置")
    print(
        f"   {color('hermes config edit', Colors.GREEN)}    在编辑器中打开配置"
    )
    print(f"   {color('hermes config set <key> <value>', Colors.GREEN)}")
    print("                          设置特定值")
    print()
    print("   或直接编辑文件：")
    print(f"   {color(f'nano {get_config_path()}', Colors.DIM)}")
    print(f"   {color(f'nano {get_env_path()}', Colors.DIM)}")
    print()

    print(color("─" * 60, Colors.DIM))
    print()
    print(color("🚀 准备就绪！", Colors.CYAN, Colors.BOLD))
    print()
    print(f"   {color('hermes', Colors.GREEN)}              开始聊天")
    print(f"   {color('hermes gateway', Colors.GREEN)}      启动消息网关")
    print(f"   {color('hermes doctor', Colors.GREEN)}       检查问题")
    print()


def _prompt_container_resources(config: dict):
    """Prompt for container resource settings (Docker, Singularity, Modal, Daytona)."""
    terminal = config.setdefault("terminal", {})

    print()
    print_info("容器资源设置：")

    # Persistence
    current_persist = terminal.get("container_persistent", True)
    persist_label = "yes" if current_persist else "no"
    print_info("  持久化文件系统可在会话之间保留文件。")
    print_info("  设为 'no' 可使用每次重置的临时沙箱。")
    persist_str = prompt(
        "  Persist filesystem across sessions? (yes/no)", persist_label
    )
    terminal["container_persistent"] = persist_str.lower() in ("yes", "true", "y", "1")

    # CPU
    current_cpu = terminal.get("container_cpu", 1)
    cpu_str = prompt("  CPU cores", str(current_cpu))
    try:
        terminal["container_cpu"] = float(cpu_str)
    except ValueError:
        pass

    # Memory
    current_mem = terminal.get("container_memory", 5120)
    mem_str = prompt("  Memory in MB (5120 = 5GB)", str(current_mem))
    try:
        terminal["container_memory"] = int(mem_str)
    except ValueError:
        pass

    # Disk
    current_disk = terminal.get("container_disk", 51200)
    disk_str = prompt("  Disk in MB (51200 = 50GB)", str(current_disk))
    try:
        terminal["container_disk"] = int(disk_str)
    except ValueError:
        pass


# Tool categories and provider config are now in tools_config.py (shared
# between `hermes tools` and `hermes setup tools`).


# =============================================================================
# Section 1: Model & Provider Configuration
# =============================================================================



def setup_model_provider(config: dict, *, quick: bool = False):
    """Configure the inference provider and default model.

    Delegates to ``cmd_model()`` (the same flow used by ``hermes model``)
    for provider selection, credential prompting, and model picking.
    This ensures a single code path for all provider setup — any new
    provider added to ``hermes model`` is automatically available here.

    When *quick* is True, skips credential rotation, vision, and TTS
    configuration — used by the streamlined first-time quick setup.
    """
    from hermes_cli.config import load_config, save_config

    print_header("推理提供商")
    print_info("选择如何连接到您的主要聊天模型。")
    print_info(f"   指南: {_DOCS_BASE}/integrations/providers")
    print()

    # Delegate to the shared hermes model flow — handles provider picker,
    # credential prompting, model selection, and config persistence.
    from hermes_cli.main import select_provider_and_model
    try:
        select_provider_and_model()
    except (SystemExit, KeyboardInterrupt):
        print()
        print_info("提供商设置已跳过。")
    except Exception as exc:
        logger.debug("select_provider_and_model error during setup: %s", exc)
        print_warning(f"提供商设置遇到错误: {exc}")
        print_info("之后可随时通过 hermes model 重试。")

    # Re-sync the wizard's config dict from what cmd_model saved to disk.
    # This is critical: cmd_model writes to disk via its own load/save cycle,
    # and the wizard's final save_config(config) must not overwrite those
    # changes with stale values (#4172).
    _refreshed = load_config()
    config["model"] = _refreshed.get("model", config.get("model"))
    if "custom_providers" in _refreshed:
        config["custom_providers"] = _refreshed["custom_providers"]
    else:
        config.pop("custom_providers", None)

    # Derive the selected provider for downstream steps (vision setup).
    selected_provider = None
    _m = config.get("model")
    if isinstance(_m, dict):
        selected_provider = _m.get("provider")

    nous_subscription_selected = selected_provider == "nous"

    # ── Same-provider fallback & rotation setup (full setup only) ──
    if not quick and _supports_same_provider_pool_setup(selected_provider):
        try:
            from types import SimpleNamespace
            from agent.credential_pool import load_pool
            from hermes_cli.auth_commands import auth_add_command

            pool = load_pool(selected_provider)
            entries = pool.entries()
            entry_count = len(entries)
            manual_count = sum(1 for entry in entries if str(getattr(entry, "source", "")).startswith("manual"))
            auto_count = entry_count - manual_count
            print()
            print_header("同提供商故障切换与轮换")
            print_info(
                "Hermes 可为同一提供商保存多个凭证，并在某个凭证"
            )
            print_info(
                "耗尽或触发限流时自动轮换。这样可以保持主提供商"
            )
            print_info(
                "的连接，同时减少配额问题的中断影响。"
            )
            print()
            if auto_count > 0:
                print_info(
                    f"当前 {selected_provider} 的凭证池: {entry_count} "
                    f"({manual_count} 手动, {auto_count} 从环境/共享认证自动检测)"
                )
            else:
                print_info(f"当前 {selected_provider} 的凭证池: {entry_count}")

            while prompt_yes_no("Add another credential for same-provider fallback?", False):
                auth_add_command(
                    SimpleNamespace(
                        provider=selected_provider,
                        auth_type="",
                        label=None,
                        api_key=None,
                        portal_url=None,
                        inference_url=None,
                        client_id=None,
                        scope=None,
                        no_browser=False,
                        timeout=15.0,
                        insecure=False,
                        ca_bundle=None,
                        min_key_ttl_seconds=5 * 60,
                    )
                )
                pool = load_pool(selected_provider)
                entry_count = len(pool.entries())
                print_info(f"提供商凭证池现在有 {entry_count} 个凭证。")

            if entry_count > 1:
                strategy_labels = [
                    "优先填充/粘性 — 持续使用首个可用凭证直至耗尽",
                    "轮询 — 每次选择后轮换到下一个可用凭证",
                    "随机 — 每次随机选择一个可用凭证",
                ]
                current_strategy = _get_credential_pool_strategies(config).get(selected_provider, "fill_first")
                default_strategy_idx = {
                    "fill_first": 0,
                    "round_robin": 1,
                    "random": 2,
                }.get(current_strategy, 0)
                strategy_idx = prompt_choice(
                    "Select same-provider rotation strategy:",
                    strategy_labels,
                    default_strategy_idx,
                )
                strategy_value = ["fill_first", "round_robin", "random"][strategy_idx]
                _set_credential_pool_strategy(config, selected_provider, strategy_value)
                print_success(f"Saved {selected_provider} rotation strategy: {strategy_value}")
        except Exception as exc:
            logger.debug("Could not configure same-provider fallback in setup: %s", exc)

    # ── Vision & Image Analysis Setup (full setup only) ──
    if quick:
        _vision_needs_setup = False
    else:
        try:
            from agent.auxiliary_client import get_available_vision_backends
            _vision_backends = set(get_available_vision_backends())
        except Exception:
            _vision_backends = set()

        _vision_needs_setup = not bool(_vision_backends)

        if selected_provider in _vision_backends:
            _vision_needs_setup = False

    if _vision_needs_setup:
        _prov_names = {
            "nous-api": "Nous Portal API key",
            "copilot": "GitHub Copilot",
            "copilot-acp": "GitHub Copilot ACP",
            "zai": "Z.AI / GLM",
            "kimi-coding": "Kimi / Moonshot",
            "kimi-coding-cn": "Kimi / Moonshot (China)",
            "stepfun": "StepFun Step Plan",
            "minimax": "MiniMax",
            "minimax-cn": "MiniMax CN",
            "anthropic": "Anthropic",
            "ai-gateway": "Vercel AI Gateway",
            "custom": "your custom endpoint",
        }
        _prov_display = _prov_names.get(selected_provider, selected_provider or "your provider")

        print()
        print_header("视觉与图像分析（可选）")
        print_info(f"视觉功能使用独立的多模态后端。{_prov_display}")
        print_info("目前不提供 Hermes 可自动使用的视觉后端，")
        print_info("请现在选择一个后端，或跳过稍后配置。")
        print()

        _vision_choices = [
            "OpenRouter — 使用 Gemini（免费: openrouter.ai/keys）",
            "兼容 OpenAI 的端点 — base URL、API key 和视觉模型",
            "暂时跳过",
        ]
        _vision_idx = prompt_choice("Configure vision:", _vision_choices, 2)

        if _vision_idx == 0:  # OpenRouter
            _or_key = prompt("  OpenRouter API key", password=True).strip()
            if _or_key:
                save_env_value("OPENROUTER_API_KEY", _or_key)
                print_success("OpenRouter 密钥已保存 — 视觉将使用 Gemini")
            else:
                print_info("已跳过 — 视觉功能将不可用")
        elif _vision_idx == 1:  # OpenAI-compatible endpoint
            _base_url = prompt("  Base URL (blank for OpenAI)").strip() or "https://api.openai.com/v1"
            _api_key_label = "  API key"
            _is_native_openai = base_url_hostname(_base_url) == "api.openai.com"
            if _is_native_openai:
                _api_key_label = "  OpenAI API key"
            _oai_key = prompt(_api_key_label, password=True).strip()
            if _oai_key:
                save_env_value("OPENAI_API_KEY", _oai_key)
                # Save vision base URL to config (not .env — only secrets go there)
                _vaux = config.setdefault("auxiliary", {}).setdefault("vision", {})
                _vaux["base_url"] = _base_url
                if _is_native_openai:
                    _oai_vision_models = ["gpt-4o", "gpt-4o-mini", "gpt-4.1", "gpt-4.1-mini", "gpt-4.1-nano"]
                    _vm_choices = _oai_vision_models + ["使用默认 (gpt-4o-mini)"]
                    _vm_idx = prompt_choice("选择视觉模型:", _vm_choices, 0)
                    _selected_vision_model = (
                        _oai_vision_models[_vm_idx]
                        if _vm_idx < len(_oai_vision_models)
                        else "gpt-4o-mini"
                    )
                else:
                    _selected_vision_model = prompt("  视觉模型（留空使用主/自定义默认值）").strip()
                save_env_value("AUXILIARY_VISION_MODEL", _selected_vision_model)
                print_success(
                    f"视觉已配置: {_base_url}"
                    + (f" ({_selected_vision_model})" if _selected_vision_model else "")
                )
            else:
                print_info("已跳过 — 视觉功能将不可用")
        else:
            print_info("已跳过 — 稍后通过 'hermes setup' 或配置 AUXILIARY_VISION_* 设置添加")


    # Tool Gateway prompt is already shown by _model_flow_nous() above.
    save_config(config)

    if not quick and selected_provider != "nous":
        _setup_tts_provider(config)


# =============================================================================
# Section 1b: TTS Provider Configuration
# =============================================================================


def _check_espeak_ng() -> bool:
    """Check if espeak-ng is installed."""
    return shutil.which("espeak-ng") is not None or shutil.which("espeak") is not None


def _install_neutts_deps() -> bool:
    """Install NeuTTS dependencies with user approval. Returns True on success."""
    import subprocess
    import sys

    # Check espeak-ng
    if not _check_espeak_ng():
        print()
        print_warning("NeuTTS 需要 espeak-ng 进行音素生成。")
        if sys.platform == "darwin":
            print_info("通过以下命令安装: brew install espeak-ng")
        elif sys.platform == "win32":
            print_info("通过以下命令安装: choco install espeak-ng")
        else:
            print_info("通过以下命令安装: sudo apt install espeak-ng")
        print()
        if prompt_yes_no("立即安装 espeak-ng？", True):
            try:
                if sys.platform == "darwin":
                    subprocess.run(["brew", "install", "espeak-ng"], check=True)
                elif sys.platform == "win32":
                    subprocess.run(["choco", "install", "espeak-ng", "-y"], check=True)
                else:
                    subprocess.run(["sudo", "apt", "install", "-y", "espeak-ng"], check=True)
                print_success("espeak-ng 已安装")
            except (subprocess.CalledProcessError, FileNotFoundError) as e:
                print_warning(f"无法自动安装 espeak-ng: {e}")
                print_info("请手动安装后重新运行设置。")
                return False
        else:
            print_warning("NeuTTS 需要 espeak-ng。使用前请手动安装。")

    # Install neutts Python package
    print()
    print_info("正在安装 neutts Python 包...")
    print_info("首次使用时还会下载 TTS 模型（约 300MB）。")
    print()
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", "neutts[all]", "--quiet"],
            check=True, timeout=300,
        )
        print_success("neutts 安装成功")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print_error(f"neutts 安装失败: {e}")
        print_info("手动尝试: python -m pip install -U neutts[all]")
        return False


def _install_kittentts_deps() -> bool:
    """Install KittenTTS dependencies with user approval. Returns True on success."""
    import subprocess
    import sys

    wheel_url = (
        "https://github.com/KittenML/KittenTTS/releases/download/"
        "0.8.1/kittentts-0.8.1-py3-none-any.whl"
    )
    print()
    print_info("正在安装 kittentts Python 包（首次使用下载约 25-80MB 模型）...")
    print()
    try:
        subprocess.run(
            [sys.executable, "-m", "pip", "install", "-U", wheel_url, "soundfile", "--quiet"],
            check=True, timeout=300,
        )
        print_success("kittentts 安装成功")
        return True
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as e:
        print_error(f"kittentts 安装失败: {e}")
        print_info(f"手动尝试: python -m pip install -U '{wheel_url}' soundfile")
        return False


def _setup_tts_provider(config: dict):
    """Interactive TTS provider selection with install flow for NeuTTS."""
    tts_config = config.get("tts", {})
    current_provider = tts_config.get("provider", "edge")
    subscription_features = get_nous_subscription_features(config)

    provider_labels = {
        "edge": "Edge TTS",
        "elevenlabs": "ElevenLabs",
        "openai": "OpenAI TTS",
        "xai": "xAI TTS",
        "minimax": "MiniMax TTS",
        "mistral": "Mistral Voxtral TTS",
        "gemini": "Google Gemini TTS",
        "neutts": "NeuTTS",
        "kittentts": "KittenTTS",
    }
    current_label = provider_labels.get(current_provider, current_provider)

    print()
    print_header("文本转语音提供商（可选）")
    print_info(f"当前: {current_label}")
    print()

    choices = []
    providers = []
    if managed_nous_tools_enabled() and subscription_features.nous_auth_present:
        choices.append("Nous 订阅（托管 OpenAI TTS，计入订阅费用）")
        providers.append("nous-openai")
    choices.extend(
        [
            "Edge TTS（免费，云端，无需设置）",
            "ElevenLabs（高级质量，需要 API 密钥）",
            "OpenAI TTS（良好质量，需要 API 密钥）",
            "xAI TTS（Grok 语音，需要 API 密钥）",
            "MiniMax TTS（高质量，支持语音克隆，需要 API 密钥）",
            "Mistral Voxtral TTS（多语言，原生 Opus，需要 API 密钥）",
            "Google Gemini TTS（30 种预设语音，提示可控，需要 API 密钥）",
            "NeuTTS（本地设备，免费，约 300MB 模型下载）",
            "KittenTTS（本地设备，免费，轻量约 25-80MB ONNX）",
        ]
    )
    providers.extend(["edge", "elevenlabs", "openai", "xai", "minimax", "mistral", "gemini", "neutts", "kittentts"])
    choices.append(f"保持当前 ({current_label})")
    keep_current_idx = len(choices) - 1
    idx = prompt_choice("选择 TTS 提供商:", choices, keep_current_idx)

    if idx == keep_current_idx:
        return

    selected = providers[idx]
    selected_via_nous = selected == "nous-openai"
    if selected == "nous-openai":
        selected = "openai"
        print_info("OpenAI TTS 将通过托管的 Nous 网关使用，费用计入您的订阅。")
        if get_env_value("VOICE_TOOLS_OPENAI_KEY") or get_env_value("OPENAI_API_KEY"):
            print_warning(
                "直接配置的 OpenAI 凭证仍然存在，在从 ~/.hermes/.env 中移除之前可能优先使用。"
            )

    if selected == "neutts":
        # Check if already installed
        try:
            already_installed = importlib.util.find_spec("neutts") is not None
        except Exception:
            already_installed = False

        if already_installed:
            print_success("NeuTTS 已安装")
        else:
            print()
            print_info("NeuTTS 需要：")
            print_info("  • Python 包: neutts（约 50MB 安装 + 首次使用约 300MB 模型）")
            print_info("  • 系统包: espeak-ng（音素生成器）")
            print()
            if prompt_yes_no("立即安装 NeuTTS 依赖？", True):
                if not _install_neutts_deps():
                    print_warning("NeuTTS 安装不完整，回退到 Edge TTS。")
                    selected = "edge"
            else:
                print_info("跳过安装。手动安装后设置 tts.provider 为 'neutts'。")
                selected = "edge"

    elif selected == "elevenlabs":
        existing = get_env_value("ELEVENLABS_API_KEY")
        if not existing:
            print()
            api_key = prompt("ElevenLabs API 密钥", password=True)
            if api_key:
                save_env_value("ELEVENLABS_API_KEY", api_key)
                print_success("ElevenLabs API 密钥已保存")
            else:
                print_warning("未提供 API 密钥，回退到 Edge TTS。")
                selected = "edge"

    elif selected == "openai" and not selected_via_nous:
        existing = get_env_value("VOICE_TOOLS_OPENAI_KEY") or get_env_value("OPENAI_API_KEY")
        if not existing:
            print()
            api_key = prompt("用于 TTS 的 OpenAI API 密钥", password=True)
            if api_key:
                save_env_value("VOICE_TOOLS_OPENAI_KEY", api_key)
                print_success("OpenAI TTS API 密钥已保存")
            else:
                print_warning("未提供 API 密钥，回退到 Edge TTS。")
                selected = "edge"

    elif selected == "xai":
        existing = get_env_value("XAI_API_KEY")
        if not existing:
            print()
            api_key = prompt("用于 TTS 的 xAI API 密钥", password=True)
            if api_key:
                save_env_value("XAI_API_KEY", api_key)
                print_success("xAI TTS API 密钥已保存")
            else:
                from hermes_constants import display_hermes_home as _dhh
                print_warning(
                    "未提供 xAI API 密钥用于 TTS。通过 "
                    f"hermes setup model 或 {_dhh()}/.env 配置 XAI_API_KEY "
                    "以使用 xAI TTS。回退到 Edge TTS。"
                )
                selected = "edge"

    elif selected == "minimax":
        existing = get_env_value("MINIMAX_API_KEY")
        if not existing:
            print()
            api_key = prompt("用于 TTS 的 MiniMax API 密钥", password=True)
            if api_key:
                save_env_value("MINIMAX_API_KEY", api_key)
                print_success("MiniMax TTS API 密钥已保存")
            else:
                print_warning("未提供 API 密钥，回退到 Edge TTS。")
                selected = "edge"

    elif selected == "mistral":
        existing = get_env_value("MISTRAL_API_KEY")
        if not existing:
            print()
            api_key = prompt("用于 TTS 的 Mistral API 密钥", password=True)
            if api_key:
                save_env_value("MISTRAL_API_KEY", api_key)
                print_success("Mistral TTS API 密钥已保存")
            else:
                print_warning("未提供 API 密钥，回退到 Edge TTS。")
                selected = "edge"

    elif selected == "gemini":
        existing = get_env_value("GEMINI_API_KEY") or get_env_value("GOOGLE_API_KEY")
        if not existing:
            print()
            print_info("在 https://aistudio.google.com/app/apikey 获取免费 API 密钥")
            api_key = prompt("用于 TTS 的 Gemini API 密钥", password=True)
            if api_key:
                save_env_value("GEMINI_API_KEY", api_key)
                print_success("Gemini TTS API 密钥已保存")
            else:
                print_warning("未提供 API 密钥，回退到 Edge TTS。")
                selected = "edge"

    elif selected == "kittentts":
        # Check if already installed
        try:
            import importlib.util
            already_installed = importlib.util.find_spec("kittentts") is not None
        except Exception:
            already_installed = False

        if already_installed:
            print_success("KittenTTS 已安装")
        else:
            print()
            print_info("KittenTTS 轻量（约 25-80MB，纯 CPU，无需 API 密钥）。")
            print_info("语音: Jasper, Bella, Luna, Bruno, Rosie, Hugo, Kiki, Leo")
            print()
            if prompt_yes_no("立即安装 KittenTTS？", True):
                if not _install_kittentts_deps():
                    print_warning("KittenTTS 安装不完整，回退到 Edge TTS。")
                    selected = "edge"
            else:
                print_info("跳过安装。手动安装后设置 tts.provider 为 'kittentts'。")
                selected = "edge"

    # Save the selection
    if "tts" not in config:
        config["tts"] = {}
    config["tts"]["provider"] = selected
    save_config(config)
    print_success(f"TTS provider set to: {provider_labels.get(selected, selected)}")


def setup_tts(config: dict):
    """Standalone TTS setup (for 'hermes setup tts')."""
    _setup_tts_provider(config)


# =============================================================================
# Section 2: Terminal Backend Configuration
# =============================================================================


def setup_terminal_backend(config: dict):
    """Configure the terminal execution backend."""
    import platform as _platform
    print_header("终端后端")
    print_info("选择 Hermes 运行 shell 命令和代码的位置。")
    print_info("这会影响工具执行、文件访问和隔离性。")
    print_info(f"   指南: {_DOCS_BASE}/developer-guide/environments")
    print()

    current_backend = config.get("terminal", {}).get("backend", "local")
    is_linux = _platform.system() == "Linux"

    # Build backend choices with descriptions
    terminal_choices = [
        "Local - 直接在本机运行（默认）",
        "Docker - 隔离容器，可配置资源",
        "Modal - 无服务器云端沙箱",
        "SSH - 在远程机器上运行",
        "Daytona - 持久化云端开发环境",
    ]
    idx_to_backend = {0: "local", 1: "docker", 2: "modal", 3: "ssh", 4: "daytona"}
    backend_to_idx = {"local": 0, "docker": 1, "modal": 2, "ssh": 3, "daytona": 4}

    next_idx = 5
    if is_linux:
        terminal_choices.append("Singularity/Apptainer - 适用于 HPC 的容器")
        idx_to_backend[next_idx] = "singularity"
        backend_to_idx["singularity"] = next_idx
        next_idx += 1

    # Add keep current option
    keep_current_idx = next_idx
    terminal_choices.append(f"Keep current ({current_backend})")
    idx_to_backend[keep_current_idx] = current_backend

    terminal_idx = prompt_choice(
        "选择终端后端:", terminal_choices, keep_current_idx
    )

    selected_backend = idx_to_backend.get(terminal_idx)

    if terminal_idx == keep_current_idx:
        print_info(f"保持当前后端: {current_backend}")
        return

    config.setdefault("terminal", {})["backend"] = selected_backend

    if selected_backend == "local":
        print_success("终端后端: Local")
        print_info("命令直接在本机上运行。")

        # CWD for messaging
        print()
        print_info("消息会话的工作目录：")
        print_info("  通过 Telegram/Discord 使用 Hermes 时，这是代理启动的目录。")
        print_info(
            "  CLI 模式始终在当前目录启动。"
        )
        current_cwd = config.get("terminal", {}).get("cwd", "")
        cwd = prompt("  消息工作目录", current_cwd or str(Path.home()))
        if cwd:
            config["terminal"]["cwd"] = cwd

        # Sudo support
        print()
        existing_sudo = get_env_value("SUDO_PASSWORD")
        if existing_sudo:
            print_info("Sudo 密码: 已配置")
        else:
            if prompt_yes_no(
                "启用 sudo 支持？（存储密码用于 apt install 等操作）", False
            ):
                sudo_pass = prompt("  Sudo 密码", password=True)
                if sudo_pass:
                    save_env_value("SUDO_PASSWORD", sudo_pass)
                    print_success("Sudo 密码已保存")

    elif selected_backend == "docker":
        print_success("终端后端: Docker")

        # Check if Docker is available
        docker_bin = shutil.which("docker")
        if not docker_bin:
            print_warning("PATH 中未找到 Docker！")
            print_info("安装 Docker: https://docs.docker.com/get-docker/")
        else:
            print_info(f"已找到 Docker: {docker_bin}")

        # Docker image
        current_image = config.get("terminal", {}).get(
            "docker_image", "nikolaik/python-nodejs:python3.11-nodejs20"
        )
        image = prompt("  Docker 镜像", current_image)
        config["terminal"]["docker_image"] = image
        save_env_value("TERMINAL_DOCKER_IMAGE", image)

        _prompt_container_resources(config)

    elif selected_backend == "singularity":
        print_success("终端后端: Singularity/Apptainer")

        # Check if singularity/apptainer is available
        sing_bin = shutil.which("apptainer") or shutil.which("singularity")
        if not sing_bin:
            print_warning("PATH 中未找到 Singularity/Apptainer！")
            print_info(
                "安装: https://apptainer.org/docs/admin/main/installation.html"
            )
        else:
            print_info(f"已找到: {sing_bin}")

        current_image = config.get("terminal", {}).get(
            "singularity_image", "docker://nikolaik/python-nodejs:python3.11-nodejs20"
        )
        image = prompt("  Container image", current_image)
        config["terminal"]["singularity_image"] = image
        save_env_value("TERMINAL_SINGULARITY_IMAGE", image)

        _prompt_container_resources(config)

    elif selected_backend == "modal":
        print_success("终端后端: Modal")
        print_info("无服务器云端沙箱。每个会话有独立的容器。")
        from tools.managed_tool_gateway import is_managed_tool_gateway_ready
        from tools.tool_backend_helpers import normalize_modal_mode

        managed_modal_available = bool(
            managed_nous_tools_enabled()
            and
            get_nous_subscription_features(config).nous_auth_present
            and is_managed_tool_gateway_ready("modal")
        )
        modal_mode = normalize_modal_mode(config.get("terminal", {}).get("modal_mode"))
        use_managed_modal = False
        if managed_modal_available:
            modal_choices = [
                "使用我的 Nous 订阅",
                "使用我自己的 Modal 账户",
            ]
            if modal_mode == "managed":
                default_modal_idx = 0
            elif modal_mode == "direct":
                default_modal_idx = 1
            else:
                default_modal_idx = 1 if get_env_value("MODAL_TOKEN_ID") else 0
            modal_mode_idx = prompt_choice(
                "选择 Modal 执行的计费方式：",
                modal_choices,
                default_modal_idx,
            )
            use_managed_modal = modal_mode_idx == 0

        if use_managed_modal:
            config["terminal"]["modal_mode"] = "managed"
            print_info("Modal 执行将通过托管的 Nous 网关使用，费用计入您的订阅。")
            if get_env_value("MODAL_TOKEN_ID") or get_env_value("MODAL_TOKEN_SECRET"):
                print_info(
                    "直接的 Modal 凭证仍然存在，但此后端已锁定为托管模式。"
                )
        else:
            config["terminal"]["modal_mode"] = "direct"
            print_info("需要 Modal 账户: https://modal.com")

            # Check if modal SDK is installed
            try:
                __import__("modal")
            except ImportError:
                print_info("正在安装 modal SDK...")
                import subprocess

                uv_bin = shutil.which("uv")
                if uv_bin:
                    result = subprocess.run(
                        [
                            uv_bin,
                            "pip",
                            "install",
                            "--python",
                            sys.executable,
                            "modal",
                        ],
                        capture_output=True,
                        text=True,
                    )
                else:
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install", "modal"],
                        capture_output=True,
                        text=True,
                    )
                if result.returncode == 0:
                    print_success("modal SDK 已安装")
                else:
                    print_warning("安装失败 — 手动运行: pip install modal")

            # Modal token
            print()
            print_info("Modal 认证：")
            print_info("  在 https://modal.com/settings 获取您的 token")
            existing_token = get_env_value("MODAL_TOKEN_ID")
            if existing_token:
                print_info("  Modal token: 已配置")
                if prompt_yes_no("  更新 Modal 凭证？", False):
                    token_id = prompt("    Modal Token ID", password=True)
                    token_secret = prompt("    Modal Token Secret", password=True)
                    if token_id:
                        save_env_value("MODAL_TOKEN_ID", token_id)
                    if token_secret:
                        save_env_value("MODAL_TOKEN_SECRET", token_secret)
            else:
                token_id = prompt("    Modal Token ID", password=True)
                token_secret = prompt("    Modal Token Secret", password=True)
                if token_id:
                    save_env_value("MODAL_TOKEN_ID", token_id)
                if token_secret:
                    save_env_value("MODAL_TOKEN_SECRET", token_secret)

        _prompt_container_resources(config)

    elif selected_backend == "daytona":
        print_success("终端后端: Daytona")
        print_info("持久化云端开发环境。")
        print_info("每个会话获得专用的沙箱，文件系统持久化。")
        print_info("注册: https://daytona.io")

        # Check if daytona SDK is installed
        try:
            __import__("daytona")
        except ImportError:
            print_info("正在安装 daytona SDK...")
            import subprocess

            uv_bin = shutil.which("uv")
            if uv_bin:
                result = subprocess.run(
                    [uv_bin, "pip", "install", "--python", sys.executable, "daytona"],
                    capture_output=True,
                    text=True,
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", "daytona"],
                    capture_output=True,
                    text=True,
                )
            if result.returncode == 0:
                print_success("daytona SDK 已安装")
            else:
                print_warning("安装失败 — 手动运行: pip install daytona")
                if result.stderr:
                    print_info(f"  错误: {result.stderr.strip().splitlines()[-1]}")

        # Daytona API key
        print()
        existing_key = get_env_value("DAYTONA_API_KEY")
        if existing_key:
            print_info("  Daytona API 密钥: 已配置")
            if prompt_yes_no("  更新 API 密钥？", False):
                api_key = prompt("    Daytona API 密钥", password=True)
                if api_key:
                    save_env_value("DAYTONA_API_KEY", api_key)
                    print_success("    已更新")
        else:
            api_key = prompt("    Daytona API 密钥", password=True)
            if api_key:
                save_env_value("DAYTONA_API_KEY", api_key)
                print_success("    已配置")

        # Daytona image
        current_image = config.get("terminal", {}).get(
            "daytona_image", "nikolaik/python-nodejs:python3.11-nodejs20"
        )
        image = prompt("  Sandbox image", current_image)
        config["terminal"]["daytona_image"] = image
        save_env_value("TERMINAL_DAYTONA_IMAGE", image)

        _prompt_container_resources(config)

    elif selected_backend == "ssh":
        print_success("终端后端: SSH")
        print_info("通过 SSH 在远程机器上运行命令。")

        # SSH host
        current_host = get_env_value("TERMINAL_SSH_HOST") or ""
        host = prompt("  SSH host (hostname or IP)", current_host)
        if host:
            save_env_value("TERMINAL_SSH_HOST", host)

        # SSH user
        current_user = get_env_value("TERMINAL_SSH_USER") or ""
        user = prompt("  SSH user", current_user or os.getenv("USER", ""))
        if user:
            save_env_value("TERMINAL_SSH_USER", user)

        # SSH port
        current_port = get_env_value("TERMINAL_SSH_PORT") or "22"
        port = prompt("  SSH port", current_port)
        if port and port != "22":
            save_env_value("TERMINAL_SSH_PORT", port)

        # SSH key
        current_key = get_env_value("TERMINAL_SSH_KEY") or ""
        default_key = str(Path.home() / ".ssh" / "id_rsa")
        ssh_key = prompt("  SSH private key path", current_key or default_key)
        if ssh_key:
            save_env_value("TERMINAL_SSH_KEY", ssh_key)

        # Test connection
        if host and prompt_yes_no("  测试 SSH 连接？", True):
            print_info("  正在测试连接...")
            import subprocess

            ssh_cmd = ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5"]
            if ssh_key:
                ssh_cmd.extend(["-i", ssh_key])
            if port and port != "22":
                ssh_cmd.extend(["-p", port])
            ssh_cmd.append(f"{user}@{host}" if user else host)
            ssh_cmd.append("echo ok")
            result = subprocess.run(ssh_cmd, capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                print_success("  SSH 连接成功！")
            else:
                print_warning(f"  SSH 连接失败: {result.stderr.strip()}")
                print_info("  请检查您的 SSH 密钥和主机设置。")

    # Sync terminal backend to .env so terminal_tool picks it up directly.
    # config.yaml is the source of truth, but terminal_tool reads TERMINAL_ENV.
    save_env_value("TERMINAL_ENV", selected_backend)
    if selected_backend == "modal":
        save_env_value("TERMINAL_MODAL_MODE", config["terminal"].get("modal_mode", "auto"))
    save_config(config)
    print()
    print_success(f"终端后端已设置为: {selected_backend}")


# =============================================================================
# Section 3: Agent Settings
# =============================================================================


def _apply_default_agent_settings(config: dict):
    """Apply recommended defaults for all agent settings without prompting."""
    config.setdefault("agent", {})["max_turns"] = 90
    save_env_value("HERMES_MAX_ITERATIONS", "90")

    config.setdefault("display", {})["tool_progress"] = "all"

    config.setdefault("compression", {})["enabled"] = True
    config["compression"]["threshold"] = 0.50

    config.setdefault("session_reset", {}).update({
        "mode": "both",
        "idle_minutes": 1440,
        "at_hour": 4,
    })

    save_config(config)
    print_success("已应用推荐的默认设置：")
    print_info("  最大迭代次数: 90")
    print_info("  工具进度显示: all")
    print_info("  压缩阈值: 0.50")
    print_info("  会话重置: 不活跃（1440 分钟） + 每天（4:00）")
    print_info("  之后可运行 `hermes setup agent` 自定义。")


def setup_agent_settings(config: dict):
    """Configure agent behavior: iterations, progress display, compression, session reset."""

    print_header("代理设置")
    print_info(f"   指南: {_DOCS_BASE}/user-guide/configuration")
    print()

    # ── Max Iterations ──
    current_max = get_env_value("HERMES_MAX_ITERATIONS") or str(
        config.get("agent", {}).get("max_turns", 90)
    )
    print_info("每次对话的最大工具调用迭代次数。")
    print_info("数值越高 = 可处理更复杂的任务，但消耗更多 tokens。")
    print_info(
        f"按 Enter 保持 {current_max}。大多数任务使用 90，自由探索使用 150+。"
    )

    max_iter_str = prompt("最大迭代次数", current_max)
    try:
        max_iter = int(max_iter_str)
        if max_iter > 0:
            save_env_value("HERMES_MAX_ITERATIONS", str(max_iter))
            config.setdefault("agent", {})["max_turns"] = max_iter
            config.pop("max_turns", None)
            print_success(f"最大迭代次数已设置为 {max_iter}")
    except ValueError:
        print_warning("无效数字，保持当前值")

    # ── Tool Progress Display ──
    print_info("")
    print_info("工具进度显示")
    print_info("控制工具活动信息的显示量（CLI 和消息平台）。")
    print_info("  off     — 静默，仅显示最终回复")
    print_info("  new     — 仅在工具切换时显示名称（减少干扰）")
    print_info("  all     — 显示每次工具调用及简短预览")
    print_info("  verbose — 完整参数、结果和调试日志")

    current_mode = config.get("display", {}).get("tool_progress", "all")
    mode = prompt("工具进度模式", current_mode)
    if mode.lower() in ("off", "new", "all", "verbose"):
        if "display" not in config:
            config["display"] = {}
        config["display"]["tool_progress"] = mode.lower()
        save_config(config)
        print_success(f"工具进度模式已设置为: {mode.lower()}")
    else:
        print_warning(f"未知模式 '{mode}'，保持 '{current_mode}'")

    # ── Context Compression ──
    print_header("上下文压缩")
    print_info("当上下文过长时自动总结旧消息。")
    print_info(
        "阈值越高 = 越晚压缩（使用更多上下文）。越低 = 越早压缩。"
    )

    config.setdefault("compression", {})["enabled"] = True

    current_threshold = config.get("compression", {}).get("threshold", 0.50)
    threshold_str = prompt("压缩阈值 (0.5-0.95)", str(current_threshold))
    try:
        threshold = float(threshold_str)
        if 0.5 <= threshold <= 0.95:
            config["compression"]["threshold"] = threshold
    except ValueError:
        pass

    print_success(
        f"上下文压缩阈值已设置为 {config['compression'].get('threshold', 0.50)}"
    )

    # ── Session Reset Policy ──
    print_header("会话重置策略")
    print_info(
        "消息会话（Telegram、Discord 等）会随时间累积上下文。"
    )
    print_info(
        "每条消息都会加入对话历史，意味着 API 成本不断增加。"
    )
    print_info("")
    print_info(
        "为管理此问题，会话可以在不活跃一段时间后"
    )
    print_info(
        "或在每天的固定时间自动重置。重置时，代理会先将重要"
    )
    print_info(
        "内容保存到持久化记忆中 — 但对话上下文会被清除。"
    )
    print_info("")
    print_info("您也可以随时在聊天中键入 /reset 手动重置。")
    print_info("")

    reset_choices = [
        "不活跃 + 每日重置（推荐 — 以先到者为准）",
        "仅不活跃（N 分钟无消息后重置）",
        "仅每日（每天固定时间重置）",
        "永不自动重置（上下文保留到 /reset 或上下文压缩）",
        "保持当前设置",
    ]

    current_policy = config.get("session_reset", {})
    current_mode = current_policy.get("mode", "both")
    current_idle = current_policy.get("idle_minutes", 1440)
    current_hour = current_policy.get("at_hour", 4)

    default_reset = {"both": 0, "idle": 1, "daily": 2, "none": 3}.get(current_mode, 0)

    reset_idx = prompt_choice("会话重置模式:", reset_choices, default_reset)

    config.setdefault("session_reset", {})

    if reset_idx == 0:  # Both
        config["session_reset"]["mode"] = "both"
        idle_str = prompt("  不活跃超时（分钟）", str(current_idle))
        try:
            idle_val = int(idle_str)
            if idle_val > 0:
                config["session_reset"]["idle_minutes"] = idle_val
        except ValueError:
            pass
        hour_str = prompt("  每日重置小时 (0-23, 本地时间)", str(current_hour))
        try:
            hour_val = int(hour_str)
            if 0 <= hour_val <= 23:
                config["session_reset"]["at_hour"] = hour_val
        except ValueError:
            pass
        print_success(
            f"会话将在 {config['session_reset'].get('idle_minutes', 1440)} 分钟不活跃后或每天 {config['session_reset'].get('at_hour', 4)}:00 重置"
        )
    elif reset_idx == 1:  # Idle only
        config["session_reset"]["mode"] = "idle"
        idle_str = prompt("  不活跃超时（分钟）", str(current_idle))
        try:
            idle_val = int(idle_str)
            if idle_val > 0:
                config["session_reset"]["idle_minutes"] = idle_val
        except ValueError:
            pass
        print_success(
            f"会话将在 {config['session_reset'].get('idle_minutes', 1440)} 分钟不活跃后重置"
        )
    elif reset_idx == 2:  # Daily only
        config["session_reset"]["mode"] = "daily"
        hour_str = prompt("  每日重置小时 (0-23, 本地时间)", str(current_hour))
        try:
            hour_val = int(hour_str)
            if 0 <= hour_val <= 23:
                config["session_reset"]["at_hour"] = hour_val
        except ValueError:
            pass
        print_success(
            f"会话将在每天 {config['session_reset'].get('at_hour', 4)}:00 重置"
        )
    elif reset_idx == 3:  # None
        config["session_reset"]["mode"] = "none"
        print_info(
            "会话永不自动重置。上下文仅通过压缩管理。"
        )
        print_warning(
            "长对话成本会增加。需要时请手动使用 /reset。"
        )
    # else: keep current (idx == 4)

    save_config(config)


# =============================================================================
# Section 4: Messaging Platforms (Gateway)
# =============================================================================


def _setup_telegram():
    """Configure Telegram bot credentials and allowlist."""
    print_header("Telegram")
    existing = get_env_value("TELEGRAM_BOT_TOKEN")
    if existing:
        print_info("Telegram: 已配置")
        if not prompt_yes_no("重新配置 Telegram？", False):
            # Check missing allowlist on existing config
            if not get_env_value("TELEGRAM_ALLOWED_USERS"):
                print_info("⚠️  Telegram 没有用户白名单 — 任何人都可以使用您的 Bot！")
                if prompt_yes_no("现在添加允许的用户？", True):
                    print_info("   查找您的 Telegram 用户 ID: 给 @userinfobot 发消息")
                    allowed_users = prompt("允许的用户 ID（逗号分隔）")
                    if allowed_users:
                        save_env_value("TELEGRAM_ALLOWED_USERS", allowed_users.replace(" ", ""))
                        print_success("Telegram 白名单已配置")
            return

    print_info("通过 Telegram 上的 @BotFather 创建一个 Bot")
    import re

    while True:
        token = prompt("Telegram Bot Token", password=True)
        if not token:
            return
        if not re.match(r"^\d+:[A-Za-z0-9_-]{30,}$", token):
            print_error(
                "Invalid token format. Expected: <numeric_id>:<alphanumeric_hash> "
                "(e.g., 123456789:ABCdefGHI-jklMNOpqrSTUvwxYZ)"
            )
            continue
        break
    save_env_value("TELEGRAM_BOT_TOKEN", token)
    print_success("Telegram Token 已保存")

    print()
    print_info("🔒 安全：限制谁可以使用您的 Bot")
    print_info("   查找您的 Telegram 用户 ID：")
    print_info("   1. 在 Telegram 上给 @userinfobot 发消息")
    print_info("   2. 它会回复您的数字 ID（例如 123456789）")
    print()
    allowed_users = prompt(
        "允许的用户 ID（逗号分隔，留空表示开放访问）"
    )
    if allowed_users:
        save_env_value("TELEGRAM_ALLOWED_USERS", allowed_users.replace(" ", ""))
        print_success("Telegram 白名单已配置 - 仅列出的用户可使用 Bot")
    else:
        print_info("⚠️ 未设置白名单 - 任何找到您 Bot 的人都可以使用！")

    print()
    print_info("📬 主频道：Hermes 在此投递 cron 任务结果、")
    print_info("   跨平台消息和通知。")
    print_info("   对于 Telegram DM，这就是您的用户 ID（与上面相同）。")

    first_user_id = allowed_users.split(",")[0].strip() if allowed_users else ""
    if first_user_id:
        if prompt_yes_no(f"使用您的用户 ID ({first_user_id}) 作为主频道？", True):
            save_env_value("TELEGRAM_HOME_CHANNEL", first_user_id)
            print_success(f"Telegram 主频道已设置为 {first_user_id}")
        else:
            home_channel = prompt("主频道 ID（留空稍后在 Telegram 中用 /set-home 设置）")
            if home_channel:
                save_env_value("TELEGRAM_HOME_CHANNEL", home_channel)
    else:
        print_info("   您也可以在 Telegram 聊天中输入 /set-home 稍后设置。")
        home_channel = prompt("主频道 ID（留空稍后设置）")
        if home_channel:
            save_env_value("TELEGRAM_HOME_CHANNEL", home_channel)


def _setup_discord():
    """Configure Discord bot credentials and allowlist."""
    print_header("Discord")
    existing = get_env_value("DISCORD_BOT_TOKEN")
    if existing:
        print_info("Discord: 已配置")
        if not prompt_yes_no("重新配置 Discord？", False):
            if not get_env_value("DISCORD_ALLOWED_USERS"):
                print_info("⚠️  Discord 没有用户白名单 — 任何人都可以使用您的 Bot！")
                if prompt_yes_no("现在添加允许的用户？", True):
                    print_info("   查找 Discord ID：启用开发者模式，右键点击名称 → 复制 ID")
                    allowed_users = prompt("允许的用户 ID（逗号分隔）")
                    if allowed_users:
                        cleaned_ids = _clean_discord_user_ids(allowed_users)
                        save_env_value("DISCORD_ALLOWED_USERS", ",".join(cleaned_ids))
                        print_success("Discord 白名单已配置")
            return

    print_info("在 https://discord.com/developers/applications 创建一个 Bot")
    token = prompt("Discord Bot Token", password=True)
    if not token:
        return
    save_env_value("DISCORD_BOT_TOKEN", token)
    print_success("Discord Token 已保存")

    print()
    print_info("🔒 安全：限制谁可以使用您的 Bot")
    print_info("   查找您的 Discord 用户 ID：")
    print_info("   1. 在 Discord 设置中启用开发者模式")
    print_info("   2. 右键点击您的名称 → 复制 ID")
    print()
    print_info("   您也可以使用 Discord 用户名（在网关启动时解析）。")
    print()
    allowed_users = prompt(
        "允许的用户 ID 或用户名（逗号分隔，留空表示开放访问）"
    )
    if allowed_users:
        cleaned_ids = _clean_discord_user_ids(allowed_users)
        save_env_value("DISCORD_ALLOWED_USERS", ",".join(cleaned_ids))
        print_success("Discord 白名单已配置")
    else:
        print_info("⚠️ 未设置白名单 - 任何与 Bot 在同一服务器的用户都可以使用！")

    print()
    print_info("📬 主频道：Hermes 在此投递 cron 任务结果、")
    print_info("   跨平台消息和通知。")
    print_info("   获取频道 ID：右键点击频道 → 复制频道 ID")
    print_info("   （需要 Discord 设置中启用开发者模式）")
    print_info("   您也可以在 Discord 频道中输入 /set-home 稍后设置。")
    home_channel = prompt("主频道 ID（留空稍后用 /set-home 设置）")
    if home_channel:
        save_env_value("DISCORD_HOME_CHANNEL", home_channel)


def _clean_discord_user_ids(raw: str) -> list:
    """Strip common Discord mention prefixes from a comma-separated ID string."""
    cleaned = []
    for uid in raw.replace(" ", "").split(","):
        uid = uid.strip()
        if uid.startswith("<@") and uid.endswith(">"):
            uid = uid.lstrip("<@!").rstrip(">")
        if uid.lower().startswith("user:"):
            uid = uid[5:]
        if uid:
            cleaned.append(uid)
    return cleaned


def _setup_slack():
    """Configure Slack bot credentials."""
    print_header("Slack")
    existing = get_env_value("SLACK_BOT_TOKEN")
    if existing:
        print_info("Slack: 已配置")
        if not prompt_yes_no("重新配置 Slack？", False):
            return

    print_info("创建 Slack 应用的步骤：")
    print_info("   1. 访问 https://api.slack.com/apps → 创建新应用（从头开始）")
    print_info("   2. 启用 Socket 模式: Settings → Socket Mode → 启用")
    print_info("      • 创建应用级别的 Token，作用域为 'connections:write'")
    print_info("   3. 添加 Bot Token 作用域: Features → OAuth & Permissions")
    print_info("      必需的作用域: chat:write, app_mentions:read,")
    print_info("      channels:history, channels:read, im:history,")
    print_info("      im:read, im:write, users:read, files:read, files:write")
    print_info("      私有频道可选: groups:history")
    print_info("   4. 订阅事件: Features → Event Subscriptions → 启用")
    print_info("      必需事件: message.im, message.channels, app_mention")
    print_info("      私有频道可选: message.groups")
    print_warning("   ⚠ 没有 message.channels，Bot 仅能在 DM 中工作，")
    print_warning("     不能在公共频道中工作。")
    print_info("   5. 安装到工作区: Settings → Install App")
    print_info("   6. 任何作用域或事件更改后重新安装应用")
    print_info("   7. 安装后，邀请 Bot 到频道: /invite @YourBot")
    print()
    print_info("   完整指南: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/slack/")
    print()
    bot_token = prompt("Slack Bot Token (xoxb-...)", password=True)
    if not bot_token:
        return
    save_env_value("SLACK_BOT_TOKEN", bot_token)
    app_token = prompt("Slack App Token (xapp-...)", password=True)
    if app_token:
        save_env_value("SLACK_APP_TOKEN", app_token)
    print_success("Slack tokens 已保存")

    print()
    print_info("🔒 安全：限制谁可以使用您的 Bot")
    print_info("   查找成员 ID：点击用户名 → 查看完整资料 → ⋮ → 复制成员 ID")
    print()
    allowed_users = prompt(
        "允许的用户 ID（逗号分隔，留空表示默认拒绝所有人，配对用户除外）"
    )
    if allowed_users:
        save_env_value("SLACK_ALLOWED_USERS", allowed_users.replace(" ", ""))
        print_success("Slack 白名单已配置")
    else:
        print_warning("⚠️ 未设置 Slack 白名单 - 默认拒绝未配对的用户。")
        print_info("   仅当您有意开放工作区访问时，才设置 SLACK_ALLOW_ALL_USERS=true 或 GATEWAY_ALLOW_ALL_USERS=true。")


def _setup_matrix():
    """Configure Matrix credentials."""
    print_header("Matrix")
    existing = get_env_value("MATRIX_ACCESS_TOKEN") or get_env_value("MATRIX_PASSWORD")
    if existing:
        print_info("Matrix: 已配置")
        if not prompt_yes_no("重新配置 Matrix？", False):
            return

    print_info("可与任何 Matrix 服务端配合使用（Synapse, Conduit, Dendrite 或 matrix.org）。")
    print_info("   1. 在您的服务端上创建一个 Bot 用户，或使用您自己的账户")
    print_info("   2. 从 Element 获取 access token，或提供用户 ID + 密码")
    print()
    homeserver = prompt("Homeserver URL（例如 https://matrix.example.org）")
    if homeserver:
        save_env_value("MATRIX_HOMESERVER", homeserver.rstrip("/"))

    print()
    print_info("认证：提供 access token（推荐），或用户 ID + 密码。")
    token = prompt("Access token（留空使用密码登录）", password=True)
    if token:
        save_env_value("MATRIX_ACCESS_TOKEN", token)
        user_id = prompt("用户 ID (@bot:server — 可选，将自动检测)")
        if user_id:
            save_env_value("MATRIX_USER_ID", user_id)
        print_success("Matrix access token 已保存")
    else:
        user_id = prompt("用户 ID (@bot:server)")
        if user_id:
            save_env_value("MATRIX_USER_ID", user_id)
        password = prompt("密码", password=True)
        if password:
            save_env_value("MATRIX_PASSWORD", password)
            print_success("Matrix 凭证已保存")

    if token or get_env_value("MATRIX_PASSWORD"):
        print()
        want_e2ee = prompt_yes_no("启用端到端加密（E2EE）？", False)
        if want_e2ee:
            save_env_value("MATRIX_ENCRYPTION", "true")
            print_success("E2EE 已启用")

        matrix_pkg = "mautrix[encryption]" if want_e2ee else "mautrix"
        try:
            __import__("mautrix")
        except ImportError:
            print_info(f"正在安装 {matrix_pkg}...")
            import subprocess
            uv_bin = shutil.which("uv")
            if uv_bin:
                result = subprocess.run(
                    [uv_bin, "pip", "install", "--python", sys.executable, matrix_pkg],
                    capture_output=True, text=True,
                )
            else:
                result = subprocess.run(
                    [sys.executable, "-m", "pip", "install", matrix_pkg],
                    capture_output=True, text=True,
                )
            if result.returncode == 0:
                print_success(f"{matrix_pkg} 已安装")
            else:
                print_warning(f"安装失败 — 手动运行: pip install '{matrix_pkg}'")
                if result.stderr:
                    print_info(f"  错误: {result.stderr.strip().splitlines()[-1]}")

        print()
        print_info("🔒 安全：限制谁可以使用您的 Bot")
        print_info("   Matrix 用户 ID 格式为 @username:server")
        print()
        allowed_users = prompt("允许的用户 ID（逗号分隔，留空表示开放访问）")
        if allowed_users:
            save_env_value("MATRIX_ALLOWED_USERS", allowed_users.replace(" ", ""))
            print_success("Matrix 白名单已配置")
        else:
            print_info("⚠️ 未设置白名单 - 任何能给 Bot 发消息的人都可以使用！")

        print()
        print_info("📬 主房间：Hermes 在此投递 cron 任务结果和通知。")
        print_info("   房间 ID 格式为 !abc123:server（在 Element 房间设置中显示）")
        print_info("   您也可以在 Matrix 房间中输入 /set-home 稍后设置。")
        home_room = prompt("主房间 ID（留空稍后用 /set-home 设置）")
        if home_room:
            save_env_value("MATRIX_HOME_ROOM", home_room)


def _setup_mattermost():
    """Configure Mattermost bot credentials."""
    print_header("Mattermost")
    existing = get_env_value("MATTERMOST_TOKEN")
    if existing:
        print_info("Mattermost: 已配置")
        if not prompt_yes_no("重新配置 Mattermost？", False):
            return

    print_info("可与任何自托管的 Mattermost 实例配合使用。")
    print_info("   1. 在 Mattermost 中: 集成 → Bot 账户 → 添加 Bot 账户")
    print_info("   2. 复制 Bot token")
    print()
    mm_url = prompt("Mattermost 服务器 URL（例如 https://mm.example.com）")
    if mm_url:
        save_env_value("MATTERMOST_URL", mm_url.rstrip("/"))
    token = prompt("Bot Token", password=True)
    if not token:
        return
    save_env_value("MATTERMOST_TOKEN", token)
    print_success("Mattermost Token 已保存")

    print()
    print_info("🔒 安全：限制谁可以使用您的 Bot")
    print_info("   查找用户 ID：点击您的头像 → 个人资料")
    print_info("   或使用 API: GET /api/v4/users/me")
    print()
    allowed_users = prompt("允许的用户 ID（逗号分隔，留空表示开放访问）")
    if allowed_users:
        save_env_value("MATTERMOST_ALLOWED_USERS", allowed_users.replace(" ", ""))
        print_success("Mattermost 白名单已配置")
    else:
        print_info("⚠️ 未设置白名单 - 任何能给 Bot 发消息的人都可以使用！")

    print()
    print_info("📬 主频道：Hermes 在此投递 cron 任务结果和通知。")
    print_info("   获取频道 ID：点击频道名称 → 查看信息 → 复制 ID")
    print_info("   您也可以在 Mattermost 频道中输入 /set-home 稍后设置。")
    home_channel = prompt("主频道 ID（留空稍后用 /set-home 设置）")
    if home_channel:
        save_env_value("MATTERMOST_HOME_CHANNEL", home_channel)


def _setup_whatsapp():
    """Configure WhatsApp bridge."""
    print_header("WhatsApp")
    existing = get_env_value("WHATSAPP_ENABLED")
    if existing:
        print_info("WhatsApp: 已启用")
        return

    print_info("WhatsApp 通过内置桥接（Baileys）连接。")
    print_info("需要 Node.js。运行 'hermes whatsapp' 进行引导式设置。")
    print()
    if prompt_yes_no("现在启用 WhatsApp？", True):
        save_env_value("WHATSAPP_ENABLED", "true")
        print_success("WhatsApp 已启用")
        print_info("运行 'hermes whatsapp' 选择您的模式（独立 Bot 号码")
        print_info("或个人自聊）并通过 QR 码配对。")


def _setup_weixin():
    """Configure Weixin (personal WeChat) via iLink Bot API QR login."""
    from hermes_cli.gateway import _setup_weixin as _gateway_setup_weixin
    _gateway_setup_weixin()


def _setup_signal():
    """Configure Signal via gateway setup."""
    from hermes_cli.gateway import _setup_signal as _gateway_setup_signal
    _gateway_setup_signal()


def _setup_email():
    """Configure Email via gateway setup."""
    from hermes_cli.gateway import _setup_email as _gateway_setup_email
    _gateway_setup_email()


def _setup_sms():
    """Configure SMS (Twilio) via gateway setup."""
    from hermes_cli.gateway import _setup_sms as _gateway_setup_sms
    _gateway_setup_sms()


def _setup_dingtalk():
    """Configure DingTalk via gateway setup."""
    from hermes_cli.gateway import _setup_dingtalk as _gateway_setup_dingtalk
    _gateway_setup_dingtalk()


def _setup_feishu():
    """Configure Feishu / Lark via gateway setup."""
    from hermes_cli.gateway import _setup_feishu as _gateway_setup_feishu
    _gateway_setup_feishu()


def _setup_wecom():
    """Configure WeCom (Enterprise WeChat) via gateway setup."""
    from hermes_cli.gateway import _setup_wecom as _gateway_setup_wecom
    _gateway_setup_wecom()


def _setup_wecom_callback():
    """Configure WeCom Callback (self-built app) via gateway setup."""
    from hermes_cli.gateway import _setup_wecom_callback as _gw_setup
    _gw_setup()




def _setup_bluebubbles():
    """Configure BlueBubbles iMessage gateway."""
    print_header("BlueBubbles (iMessage)")
    existing = get_env_value("BLUEBUBBLES_SERVER_URL")
    if existing:
        print_info("BlueBubbles: 已配置")
        if not prompt_yes_no("重新配置 BlueBubbles？", False):
            return

    print_info("通过 BlueBubbles 将 Hermes 连接到 iMessage — 一个免费的、开源的")
    print_info("macOS 服务器，将 iMessage 桥接到任何设备。")
    print_info("   需要运行 BlueBubbles Server v1.0.0+ 的 Mac")
    print_info("   下载: https://bluebubbles.app/")
    print()
    print_info("在 BlueBubbles Server → 设置 → API 中，记下您的 Server URL 和密码。")
    print()

    server_url = prompt("BlueBubbles 服务器 URL（例如 http://192.168.1.10:1234）")
    if not server_url:
        print_warning("需要提供 Server URL — 跳过 BlueBubbles 设置")
        return
    save_env_value("BLUEBUBBLES_SERVER_URL", server_url.rstrip("/"))

    password = prompt("BlueBubbles 服务器密码", password=True)
    if not password:
        print_warning("需要提供密码 — 跳过 BlueBubbles 设置")
        return
    save_env_value("BLUEBUBBLES_PASSWORD", password)
    print_success("BlueBubbles 凭证已保存")

    print()
    print_info("🔒 安全：限制谁可以给您的 Bot 发消息")
    print_info("   使用 iMessage 地址：邮箱 (user@icloud.com) 或电话 (+15551234567)")
    print()
    allowed_users = prompt("允许的 iMessage 地址（逗号分隔，留空表示开放访问）")
    if allowed_users:
        save_env_value("BLUEBUBBLES_ALLOWED_USERS", allowed_users.replace(" ", ""))
        print_success("BlueBubbles 白名单已配置")
    else:
        print_info("⚠️ 未设置白名单 — 任何能给您的 iMessage 发消息的人都可以使用 Bot！")

    print()
    print_info("📬 主频道：用于 cron 任务投递和通知的电话或邮箱。")
    print_info("   您也可以在 iMessage 聊天中使用 /set-home 稍后设置。")
    home_channel = prompt("主频道地址（留空稍后设置）")
    if home_channel:
        save_env_value("BLUEBUBBLES_HOME_CHANNEL", home_channel)

    print()
    print_info("高级设置（默认值适用于大多数情况）：")
    if prompt_yes_no("配置 webhook 监听器设置？", False):
        webhook_port = prompt("Webhook 监听端口（默认: 8645）")
        if webhook_port:
            try:
                save_env_value("BLUEBUBBLES_WEBHOOK_PORT", str(int(webhook_port)))
                print_success(f"Webhook 端口已设置为 {webhook_port}")
            except ValueError:
                print_warning("无效端口号，使用默认值 8645")

    print()
    print_info("需要 BlueBubbles Private API 辅助模块来支持输入指示器、")
    print_info("已读回执和 Tapback 反应。基础消息功能无需此模块也可使用。")
    print_info("   安装: https://docs.bluebubbles.app/helper-bundle/installation")


def _setup_qqbot():
    """Configure QQ Bot (Official API v2) via gateway setup."""
    from hermes_cli.gateway import _setup_qqbot as _gateway_setup_qqbot
    _gateway_setup_qqbot()


def _setup_webhooks():
    """Configure webhook integration."""
    print_header("Webhooks")
    existing = get_env_value("WEBHOOK_ENABLED")
    if existing:
        print_info("Webhooks: 已配置")
        if not prompt_yes_no("重新配置 webhooks？", False):
            return

    print()
    print_warning("⚠  Webhook 和 SMS 平台需要将网关端口暴露到")
    print_warning("   互联网。为保障安全，请在沙箱环境中运行网关")
    print_warning("   （Docker、VM 等）以限制提示注入的破坏范围。")
    print()
    print_info("   完整指南: https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/")
    print()

    port = prompt("Webhook 端口（默认 8644）")
    if port:
        try:
            save_env_value("WEBHOOK_PORT", str(int(port)))
            print_success(f"Webhook 端口已设置为 {port}")
        except ValueError:
            print_warning("无效端口号，使用默认值 8644")

    secret = prompt("全局 HMAC 密钥（所有路由共享）", password=True)
    if secret:
        save_env_value("WEBHOOK_SECRET", secret)
        print_success("Webhook 密钥已保存")
    else:
        print_warning("未设置密钥 — 您必须在 config.yaml 中为每个路由配置独立密钥")

    save_env_value("WEBHOOK_ENABLED", "true")
    print()
    print_success("Webhooks 已启用！后续步骤：")
    from hermes_constants import display_hermes_home as _dhh
    print_info(f"   1. 在 {_dhh()}/config.yaml 中定义 webhook 路由")
    print_info("   2. 将您的服务（GitHub、GitLab 等）指向：")
    print_info("      http://your-server:8644/webhooks/<route-name>")
    print()
    print_info("   路由配置指南：")
    print_info("   https://hermes-agent.nousresearch.com/docs/user-guide/messaging/webhooks/#configuring-routes")
    print()
    print_info("   在编辑器中打开配置：hermes config edit")


# Platform registry for the gateway checklist
_GATEWAY_PLATFORMS = [
    ("Telegram", "TELEGRAM_BOT_TOKEN", _setup_telegram),
    ("Discord", "DISCORD_BOT_TOKEN", _setup_discord),
    ("Slack", "SLACK_BOT_TOKEN", _setup_slack),
    ("Signal", "SIGNAL_HTTP_URL", _setup_signal),
    ("Email", "EMAIL_ADDRESS", _setup_email),
    ("SMS (Twilio)", "TWILIO_ACCOUNT_SID", _setup_sms),
    ("Matrix", "MATRIX_ACCESS_TOKEN", _setup_matrix),
    ("Mattermost", "MATTERMOST_TOKEN", _setup_mattermost),
    ("WhatsApp", "WHATSAPP_ENABLED", _setup_whatsapp),
    ("DingTalk", "DINGTALK_CLIENT_ID", _setup_dingtalk),
    ("Feishu / Lark", "FEISHU_APP_ID", _setup_feishu),
    ("WeCom (Enterprise WeChat)", "WECOM_BOT_ID", _setup_wecom),
    ("WeCom Callback (Self-Built App)", "WECOM_CALLBACK_CORP_ID", _setup_wecom_callback),
    ("Weixin (WeChat)", "WEIXIN_ACCOUNT_ID", _setup_weixin),
    ("BlueBubbles (iMessage)", "BLUEBUBBLES_SERVER_URL", _setup_bluebubbles),
    ("QQ Bot", "QQ_APP_ID", _setup_qqbot),
    ("Webhooks (GitHub, GitLab, etc.)", "WEBHOOK_ENABLED", _setup_webhooks),
]


def setup_gateway(config: dict):
    """Configure messaging platform integrations."""
    print_header("消息平台")
    print_info("连接到消息平台，从任何地方与 Hermes 聊天。")
    print_info("按空格键切换，按回车确认。")
    print()

    # Build checklist items, pre-selecting already-configured platforms
    items = []
    pre_selected = []
    for i, (name, env_var, _func) in enumerate(_GATEWAY_PLATFORMS):
        # Matrix has two possible env vars
        is_configured = bool(get_env_value(env_var))
        if name == "Matrix" and not is_configured:
            is_configured = bool(get_env_value("MATRIX_PASSWORD"))
        label = f"{name}  (已配置)" if is_configured else name
        items.append(label)
        if is_configured:
            pre_selected.append(i)

    selected = prompt_checklist("选择要配置的平台:", items, pre_selected)

    if not selected:
        print_info("未选择任何平台。稍后运行 'hermes setup gateway' 进行配置。")
        return

    for idx in selected:
        name, _env_var, setup_func = _GATEWAY_PLATFORMS[idx]
        setup_func()

    # ── Gateway Service Setup ──
    any_messaging = (
        get_env_value("TELEGRAM_BOT_TOKEN")
        or get_env_value("DISCORD_BOT_TOKEN")
        or get_env_value("SLACK_BOT_TOKEN")
        or get_env_value("SIGNAL_HTTP_URL")
        or get_env_value("EMAIL_ADDRESS")
        or get_env_value("TWILIO_ACCOUNT_SID")
        or get_env_value("MATTERMOST_TOKEN")
        or get_env_value("MATRIX_ACCESS_TOKEN")
        or get_env_value("MATRIX_PASSWORD")
        or get_env_value("WHATSAPP_ENABLED")
        or get_env_value("DINGTALK_CLIENT_ID")
        or get_env_value("FEISHU_APP_ID")
        or get_env_value("WECOM_BOT_ID")
        or get_env_value("WEIXIN_ACCOUNT_ID")
        or get_env_value("BLUEBUBBLES_SERVER_URL")
        or get_env_value("QQ_APP_ID")
        or get_env_value("WEBHOOK_ENABLED")
    )
    if any_messaging:
        print()
        print_info("━" * 50)
        print_success("消息平台已配置！")

        # Check if any home channels are missing
        missing_home = []
        if get_env_value("TELEGRAM_BOT_TOKEN") and not get_env_value(
            "TELEGRAM_HOME_CHANNEL"
        ):
            missing_home.append("Telegram")
        if get_env_value("DISCORD_BOT_TOKEN") and not get_env_value(
            "DISCORD_HOME_CHANNEL"
        ):
            missing_home.append("Discord")
        if get_env_value("SLACK_BOT_TOKEN") and not get_env_value("SLACK_HOME_CHANNEL"):
            missing_home.append("Slack")
        if get_env_value("BLUEBUBBLES_SERVER_URL") and not get_env_value("BLUEBUBBLES_HOME_CHANNEL"):
            missing_home.append("BlueBubbles")
        if get_env_value("QQ_APP_ID") and not (
            get_env_value("QQBOT_HOME_CHANNEL") or get_env_value("QQ_HOME_CHANNEL")
        ):
            missing_home.append("QQBot")

        if missing_home:
            print()
            print_warning(f"未设置主频道: {', '.join(missing_home)}")
            print_info("   没有主频道，cron 任务和跨平台")
            print_info("   消息无法投递到这些平台。")
            print_info("   稍后在聊天中使用 /set-home 设置，或：")
            for plat in missing_home:
                print_info(
                    f"     hermes config set {plat.upper()}_HOME_CHANNEL <channel_id>"
                )

        # Offer to install the gateway as a system service
        import platform as _platform

        _is_linux = _platform.system() == "Linux"
        _is_macos = _platform.system() == "Darwin"

        from hermes_cli.gateway import (
            _is_service_installed,
            _is_service_running,
            supports_systemd_services,
            has_conflicting_systemd_units,
            has_legacy_hermes_units,
            install_linux_gateway_from_setup,
            print_systemd_scope_conflict_warning,
            print_legacy_unit_warning,
            systemd_start,
            systemd_restart,
            launchd_install,
            launchd_start,
            launchd_restart,
            UserSystemdUnavailableError,
        )

        service_installed = _is_service_installed()
        service_running = _is_service_running()
        supports_systemd = supports_systemd_services()
        supports_service_manager = supports_systemd or _is_macos

        print()
        if supports_systemd and has_conflicting_systemd_units():
            print_systemd_scope_conflict_warning()
            print()

        if supports_systemd and has_legacy_hermes_units():
            print_legacy_unit_warning()
            print()

        if service_running:
            if prompt_yes_no("  重启网关以应用更改？", True):
                try:
                    if supports_systemd:
                        systemd_restart()
                    elif _is_macos:
                        launchd_restart()
                except UserSystemdUnavailableError as e:
                    print_error("  重启失败 — 用户 systemd 不可达：")
                    for line in str(e).splitlines():
                        print(f"  {line}")
                except Exception as e:
                    print_error(f"  重启失败: {e}")
        elif service_installed:
            if prompt_yes_no("  启动网关服务？", True):
                try:
                    if supports_systemd:
                        systemd_start()
                    elif _is_macos:
                        launchd_start()
                except UserSystemdUnavailableError as e:
                    print_error("  启动失败 — 用户 systemd 不可达：")
                    for line in str(e).splitlines():
                        print(f"  {line}")
                except Exception as e:
                    print_error(f"  启动失败: {e}")
        elif supports_service_manager:
            svc_name = "systemd" if supports_systemd else "launchd"
            if prompt_yes_no(
                f"  将网关安装为 {svc_name} 服务？（后台运行，开机自启）",
                True,
            ):
                try:
                    installed_scope = None
                    did_install = False
                    if supports_systemd:
                        installed_scope, did_install = install_linux_gateway_from_setup(force=False)
                    else:
                        launchd_install(force=False)
                        did_install = True
                    print()
                    if did_install and prompt_yes_no("  现在启动服务？", True):
                        try:
                            if supports_systemd:
                                systemd_start(system=installed_scope == "system")
                            elif _is_macos:
                                launchd_start()
                        except UserSystemdUnavailableError as e:
                            print_error("  启动失败 — 用户 systemd 不可达：")
                            for line in str(e).splitlines():
                                print(f"  {line}")
                        except Exception as e:
                            print_error(f"  启动失败: {e}")
                except Exception as e:
                    print_error(f"  安装失败: {e}")
                    print_info("  您可以手动尝试: hermes gateway install")
            else:
                print_info("  您可以稍后安装: hermes gateway install")
                if supports_systemd:
                    print_info("  或作为开机自启服务: sudo hermes gateway install --system")
                print_info("  或在前台运行:  hermes gateway")
        else:
            from hermes_constants import is_container
            if is_container():
                print_info("启动网关以使您的 Bot 上线：")
                print_info("   hermes gateway run          # 作为容器主进程运行")
                print_info("")
                print_info("如需自动重启，请使用 Docker 重启策略：")
                print_info("   docker run --restart unless-stopped ...")
                print_info("   docker restart <container>  # 手动重启")
            else:
                print_info("启动网关以使您的 Bot 上线：")
                print_info("   hermes gateway              # 在前台运行")

        print_info("━" * 50)


# =============================================================================
# Section 5: Tool Configuration (delegates to unified tools_config.py)
# =============================================================================


def setup_tools(config: dict, first_install: bool = False):
    """Configure tools — delegates to the unified tools_command() in tools_config.py.

    Both `hermes setup tools` and `hermes tools` use the same flow:
    platform selection → toolset toggles → provider/API key configuration.

    Args:
        first_install: When True, uses the simplified first-install flow
            (no platform menu, prompts for all unconfigured API keys).
    """
    from hermes_cli.tools_config import tools_command

    tools_command(first_install=first_install, config=config)


# =============================================================================
# Post-Migration Section Skip Logic
# =============================================================================


def _model_section_has_credentials(config: dict) -> bool:
    """Return True when any known inference provider has usable credentials.

    Sources of truth:
      * ``PROVIDER_REGISTRY`` in ``hermes_cli.auth`` — lists every supported
        provider along with its ``api_key_env_vars``.
      * ``active_provider`` in the auth store — covers OAuth device-code /
        external-OAuth providers (Nous, Codex, Qwen, Gemini CLI, ...).
      * The legacy OpenRouter aggregator env vars, which route generic
        ``OPENAI_API_KEY`` / ``OPENROUTER_API_KEY`` values through OpenRouter.
    """
    try:
        from hermes_cli.auth import get_active_provider
        if get_active_provider():
            return True
    except Exception:
        pass

    try:
        from hermes_cli.auth import PROVIDER_REGISTRY
    except Exception:
        PROVIDER_REGISTRY = {}  # type: ignore[assignment]

    def _has_key(pconfig) -> bool:
        for env_var in pconfig.api_key_env_vars:
            # CLAUDE_CODE_OAUTH_TOKEN is set by Claude Code itself, not by
            # the user — mirrors is_provider_explicitly_configured in auth.py.
            if env_var == "CLAUDE_CODE_OAUTH_TOKEN":
                continue
            if get_env_value(env_var):
                return True
        return False

    # Prefer the provider declared in config.yaml, avoids false positives
    # from stray env vars (GH_TOKEN, etc.) when the user has already picked
    # a different provider.
    model_cfg = config.get("model") if isinstance(config, dict) else None
    if isinstance(model_cfg, dict):
        provider_id = (model_cfg.get("provider") or "").strip().lower()
        if provider_id in PROVIDER_REGISTRY:
            if _has_key(PROVIDER_REGISTRY[provider_id]):
                return True
        if provider_id == "openrouter":
            for env_var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
                if get_env_value(env_var):
                    return True

    # OpenRouter aggregator fallback (no provider declared in config).
    for env_var in ("OPENROUTER_API_KEY", "OPENAI_API_KEY"):
        if get_env_value(env_var):
            return True

    for pid, pconfig in PROVIDER_REGISTRY.items():
        # Skip copilot in auto-detect: GH_TOKEN / GITHUB_TOKEN are
        # commonly set for git tooling.  Mirrors resolve_provider in auth.py.
        if pid == "copilot":
            continue
        if _has_key(pconfig):
            return True
    return False


def _gateway_platform_short_label(label: str) -> str:
    """Strip trailing parenthetical qualifiers from a gateway platform label."""
    base = label.split("(", 1)[0].strip()
    return base or label


def _get_section_config_summary(config: dict, section_key: str) -> Optional[str]:
    """Return a short summary if a setup section is already configured, else None.

    Used after OpenClaw migration to detect which sections can be skipped.
    ``get_env_value`` is the module-level import from hermes_cli.config
    so that test patches on ``setup_mod.get_env_value`` take effect.
    """
    if section_key == "model":
        if not _model_section_has_credentials(config):
            return None
        model = config.get("model")
        if isinstance(model, str) and model.strip():
            return model.strip()
        if isinstance(model, dict):
            return str(model.get("default") or model.get("model") or "configured")
        return "configured"

    elif section_key == "terminal":
        backend = config.get("terminal", {}).get("backend", "local")
        return f"backend: {backend}"

    elif section_key == "agent":
        max_turns = config.get("agent", {}).get("max_turns", 90)
        return f"max turns: {max_turns}"

    elif section_key == "gateway":
        platforms = [
            _gateway_platform_short_label(label)
            for label, env_var, _ in _GATEWAY_PLATFORMS
            if get_env_value(env_var)
        ]
        if platforms:
            return ", ".join(platforms)
        return None  # No platforms configured — section must run

    elif section_key == "tools":
        tools = []
        if get_env_value("ELEVENLABS_API_KEY"):
            tools.append("TTS/ElevenLabs")
        if get_env_value("BROWSERBASE_API_KEY"):
            tools.append("Browser")
        if get_env_value("FIRECRAWL_API_KEY"):
            tools.append("Firecrawl")
        if tools:
            return ", ".join(tools)
        return None

    return None


def _skip_configured_section(
    config: dict, section_key: str, label: str
) -> bool:
    """Show an already-configured section summary and offer to skip.

    Returns True if the user chose to skip, False if the section should run.
    """
    summary = _get_section_config_summary(config, section_key)
    if not summary:
        return False
    print()
    print_success(f"  {label}: {summary}")
    return not prompt_yes_no(f"  Reconfigure {label.lower()}?", default=False)


# =============================================================================
# OpenClaw Migration
# =============================================================================


_OPENCLAW_SCRIPT = (
    get_optional_skills_dir(PROJECT_ROOT / "optional-skills")
    / "migration"
    / "openclaw-migration"
    / "scripts"
    / "openclaw_to_hermes.py"
)


def _load_openclaw_migration_module():
    """Load the openclaw_to_hermes migration script as a module.

    Returns the loaded module, or None if the script can't be loaded.
    """
    if not _OPENCLAW_SCRIPT.exists():
        return None

    spec = importlib.util.spec_from_file_location(
        "openclaw_to_hermes", _OPENCLAW_SCRIPT
    )
    if spec is None or spec.loader is None:
        return None

    mod = importlib.util.module_from_spec(spec)
    # Register in sys.modules so @dataclass can resolve the module
    # (Python 3.11+ requires this for dynamically loaded modules)
    import sys as _sys
    _sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    except Exception:
        _sys.modules.pop(spec.name, None)
        raise
    return mod


# Item kinds that represent high-impact changes warranting explicit warnings.
# Gateway tokens/channels can hijack messaging platforms from the old agent.
# Config values may have different semantics between OpenClaw and Hermes.
# Instruction/context files (.md) can contain incompatible setup procedures.
_HIGH_IMPACT_KIND_KEYWORDS = {
    "gateway": "⚠ Gateway/messaging — this will configure Hermes to use your OpenClaw messaging channels",
    "telegram": "⚠ Telegram — this will point Hermes at your OpenClaw Telegram bot",
    "slack": "⚠ Slack — this will point Hermes at your OpenClaw Slack workspace",
    "discord": "⚠ Discord — this will point Hermes at your OpenClaw Discord bot",
    "whatsapp": "⚠ WhatsApp — this will point Hermes at your OpenClaw WhatsApp connection",
    "config": "⚠ Config values — OpenClaw settings may not map 1:1 to Hermes equivalents",
    "soul": "⚠ Instruction file — may contain OpenClaw-specific setup/restart procedures",
    "memory": "⚠ Memory/context file — may reference OpenClaw-specific infrastructure",
    "context": "⚠ Context file — may contain OpenClaw-specific instructions",
}


def _print_migration_preview(report: dict):
    """Print a detailed dry-run preview of what migration would do.

    Groups items by category and adds explicit warnings for high-impact
    changes like gateway token takeover and config value differences.
    """
    items = report.get("items", [])
    if not items:
        print_info("没有需要迁移的内容。")
        return

    migrated_items = [i for i in items if i.get("status") == "migrated"]
    conflict_items = [i for i in items if i.get("status") == "conflict"]
    skipped_items = [i for i in items if i.get("status") == "skipped"]

    warnings_shown = set()

    if migrated_items:
        print(color("  将导入:", Colors.GREEN))
        for item in migrated_items:
            kind = item.get("kind", "unknown")
            dest = item.get("destination", "")
            if dest:
                dest_short = str(dest).replace(str(Path.home()), "~")
                print(f"      {kind:<22s} → {dest_short}")
            else:
                print(f"      {kind}")

            # Check for high-impact items and collect warnings
            kind_lower = kind.lower()
            dest_lower = str(dest).lower()
            for keyword, warning in _HIGH_IMPACT_KIND_KEYWORDS.items():
                if keyword in kind_lower or keyword in dest_lower:
                    warnings_shown.add(warning)
        print()

    if conflict_items:
        print(color("  将覆盖（与现有 Hermes 配置冲突）:", Colors.YELLOW))
        for item in conflict_items:
            kind = item.get("kind", "unknown")
            reason = item.get("reason", "already exists")
            print(f"      {kind:<22s}  {reason}")
        print()

    if skipped_items:
        print(color("  将跳过:", Colors.DIM))
        for item in skipped_items:
            kind = item.get("kind", "unknown")
            reason = item.get("reason", "")
            print(f"      {kind:<22s}  {reason}")
        print()

    # Print collected warnings
    if warnings_shown:
        print(color("  ── Warnings ──", Colors.YELLOW))
        for warning in sorted(warnings_shown):
            print(color(f"    {warning}", Colors.YELLOW))
        print()
        print(color("  Note: OpenClaw config values may have different semantics in Hermes.", Colors.YELLOW))
        print(color("  For example, OpenClaw's tool_call_execution: \"auto\" ≠ Hermes's yolo mode.", Colors.YELLOW))
        print(color("  Instruction files (.md) from OpenClaw may contain incompatible procedures.", Colors.YELLOW))
        print()


def _offer_openclaw_migration(hermes_home: Path) -> bool:
    """Detect ~/.openclaw and offer to migrate during first-time setup.

    Runs a dry-run first to show the user exactly what would be imported,
    overwritten, or taken over. Only executes after explicit confirmation.

    Returns True if migration ran successfully, False otherwise.
    """
    openclaw_dir = Path.home() / ".openclaw"
    if not openclaw_dir.is_dir():
        return False

    if not _OPENCLAW_SCRIPT.exists():
        return False

    print()
    print_header("检测到 OpenClaw 安装")
    print_info(f"在 {openclaw_dir} 找到 OpenClaw 数据")
    print_info("Hermes 可以预览将要导入的内容，然后才进行更改。")
    print()

    if not prompt_yes_no("是否想查看可以导入的内容？", default=True):
        print_info(
            "跳过迁移。之后可运行: hermes claw migrate --dry-run"
        )
        return False

    # Ensure config.yaml exists before migration tries to read it
    config_path = get_config_path()
    if not config_path.exists():
        save_config(load_config())

    # Load the migration module
    try:
        mod = _load_openclaw_migration_module()
        if mod is None:
            print_warning("Could not load migration script.")
            return False
    except Exception as e:
        print_warning(f"无法加载迁移脚本: {e}")
        logger.debug("OpenClaw migration module load error", exc_info=True)
        return False

    # ── Phase 1: Dry-run preview ──
    try:
        selected = mod.resolve_selected_options(None, None, preset="full")
        dry_migrator = mod.Migrator(
            source_root=openclaw_dir.resolve(),
            target_root=hermes_home.resolve(),
            execute=False,  # dry-run — no files modified
            workspace_target=None,
            overwrite=True,  # show everything including conflicts
            migrate_secrets=True,
            output_dir=None,
            selected_options=selected,
            preset_name="full",
        )
        preview_report = dry_migrator.migrate()
    except Exception as e:
        print_warning(f"迁移预览失败: {e}")
        logger.debug("OpenClaw migration preview error", exc_info=True)
        return False

    # Display the full preview
    preview_summary = preview_report.get("summary", {})
    preview_count = preview_summary.get("migrated", 0)

    if preview_count == 0:
        print()
        print_info("没有需要从 OpenClaw 导入的内容。")
        return False

    print()
    print_header(f"迁移预览 — 将导入 {preview_count} 项")
    print_info("尚未进行任何更改。请查看以下列表：")
    print()
    _print_migration_preview(preview_report)

    # ── Phase 2: Confirm and execute ──
    if not prompt_yes_no("继续迁移？", default=False):
        print_info(
            "迁移已取消。之后可运行: hermes claw migrate"
        )
        print_info(
            "使用 --dry-run 再次预览，或 --preset minimal 进行轻量导入。"
        )
        return False

    # Execute the migration — overwrite=False so existing Hermes configs are
    # preserved. The user saw the preview; conflicts are skipped by default.
    try:
        migrator = mod.Migrator(
            source_root=openclaw_dir.resolve(),
            target_root=hermes_home.resolve(),
            execute=True,
            workspace_target=None,
            overwrite=False,  # preserve existing Hermes config
            migrate_secrets=True,
            output_dir=None,
            selected_options=selected,
            preset_name="full",
        )
        report = migrator.migrate()
    except Exception as e:
        print_warning(f"迁移失败: {e}")
        logger.debug("OpenClaw migration error", exc_info=True)
        return False

    # Print final summary
    summary = report.get("summary", {})
    migrated = summary.get("migrated", 0)
    skipped = summary.get("skipped", 0)
    conflicts = summary.get("conflict", 0)
    errors = summary.get("error", 0)

    print()
    if migrated:
        print_success(f"从 OpenClaw 导入了 {migrated} 项。")
    if conflicts:
        print_info(f"跳过了 {conflicts} 项（在 Hermes 中已存在，使用 hermes claw migrate --overwrite 强制覆盖）。")
    if skipped:
        print_info(f"跳过了 {skipped} 项（未找到或未更改）。")
    if errors:
        print_warning(f"{errors} 项出现错误 — 请检查迁移报告。")

    output_dir = report.get("output_dir")
    if output_dir:
        print_info(f"完整报告已保存到: {output_dir}")

    print_success("迁移完成！继续设置...")
    return True


# =============================================================================
# Main Wizard Orchestrator
# =============================================================================

SETUP_SECTIONS = [
    ("model", "Model & Provider", setup_model_provider),
    ("tts", "Text-to-Speech", setup_tts),
    ("terminal", "Terminal Backend", setup_terminal_backend),
    ("gateway", "Messaging Platforms (Gateway)", setup_gateway),
    ("tools", "Tools", setup_tools),
    ("agent", "Agent Settings", setup_agent_settings),
]

# The returning-user menu intentionally omits standalone TTS because model setup
# already includes TTS selection and tools setup covers the rest of the provider
# configuration. Keep this list in the same order as the visible menu entries.
RETURNING_USER_MENU_SECTION_KEYS = [
    "model",
    "terminal",
    "gateway",
    "tools",
    "agent",
]


def run_setup_wizard(args):
    """Run the interactive setup wizard.

    Supports full, quick, and section-specific setup:
      hermes setup           — full or quick (auto-detected)
      hermes setup model     — just model/provider
      hermes setup tts       — just text-to-speech
      hermes setup terminal  — just terminal backend
      hermes setup gateway   — just messaging platforms
      hermes setup tools     — just tool configuration
      hermes setup agent     — just agent settings
    """
    from hermes_cli.config import is_managed, managed_error
    if is_managed():
        managed_error("run setup wizard")
        return
    ensure_hermes_home()

    reset_requested = bool(getattr(args, "reset", False))
    if reset_requested:
        save_config(copy.deepcopy(DEFAULT_CONFIG))
        print_success("Configuration reset to defaults.")

    config = load_config()
    hermes_home = get_hermes_home()

    # Detect non-interactive environments (headless SSH, Docker, CI/CD)
    non_interactive = getattr(args, 'non_interactive', False)
    if not non_interactive and not is_interactive_stdin():
        non_interactive = True

    if non_interactive:
        print_noninteractive_setup_guidance(
            "Running in a non-interactive environment (no TTY detected)."
        )
        return

    # Check if a specific section was requested
    section = getattr(args, "section", None)
    if section:
        for key, label, func in SETUP_SECTIONS:
            if key == section:
                print()
                print(
                    color(
                        "┌─────────────────────────────────────────────────────────┐",
                        Colors.MAGENTA,
                    )
                )
                print(color(f"│     ⚕ Hermes Setup — {label:<34s} │", Colors.MAGENTA))
                print(
                    color(
                        "└─────────────────────────────────────────────────────────┘",
                        Colors.MAGENTA,
                    )
                )
                func(config)
                save_config(config)
                print()
                print_success(f"{label} configuration complete!")
                return

        print_error(f"未知的设置部分: {section}")
        print_info(f"可用部分: {', '.join(k for k, _, _ in SETUP_SECTIONS)}")
        return

    # Check if this is an existing installation with a provider configured
    from hermes_cli.auth import get_active_provider

    active_provider = get_active_provider()
    is_existing = (
        bool(get_env_value("OPENROUTER_API_KEY"))
        or bool(get_env_value("OPENAI_BASE_URL"))
        or active_provider is not None
    )

    print()
    print(
        color(
            "┌─────────────────────────────────────────────────────────┐",
            Colors.MAGENTA,
        )
    )
    print(
        color(
            "│             ⚕ Hermes Agent Setup Wizard                │", Colors.MAGENTA
        )
    )
    print(
        color(
            "├─────────────────────────────────────────────────────────┤",
            Colors.MAGENTA,
        )
    )
    print(
        color(
            "│  让我们配置您的 Hermes Agent 安装。                    │", Colors.MAGENTA
        )
    )
    print(
        color(
            "│  随时按 Ctrl+C 退出。                                  │", Colors.MAGENTA
        )
    )
    print(
        color(
            "└─────────────────────────────────────────────────────────┘",
            Colors.MAGENTA,
        )
    )

    migration_ran = False

    if is_existing:
        # ── Returning User Menu ──
        print()
        print_header("欢迎回来！")
        print_success("您已经配置过 Hermes。")
        print()

        menu_choices = [
            "快速设置 - 仅配置缺失项",
            "完整设置 - 重新配置所有内容",
            "模型与提供商",
            "终端后端",
            "消息平台（网关）",
            "工具",
            "代理设置",
            "退出",
        ]
        choice = prompt_choice("您想做什么？", menu_choices, 0)

        if choice == 0:
            # Quick setup
            _run_quick_setup(config, hermes_home)
            return
        elif choice == 1:
            # Full setup — fall through to run all sections
            pass
        elif choice == 7:
            print_info("正在退出。准备就绪时运行 'hermes setup'。")
            return
        elif 2 <= choice <= 6:
            # Individual section — map by key, not by position.
            # SETUP_SECTIONS includes TTS but the returning-user menu skips it,
            # so positional indexing (choice - 2) would dispatch the wrong section.
            section_key = RETURNING_USER_MENU_SECTION_KEYS[choice - 2]
            section = next((s for s in SETUP_SECTIONS if s[0] == section_key), None)
            if section:
                _, label, func = section
                func(config)
                save_config(config)
                _print_setup_summary(config, hermes_home)
            return
    else:
        # ── First-Time Setup ──
        print()

        # Offer OpenClaw migration before configuration begins
        migration_ran = _offer_openclaw_migration(hermes_home)
        if migration_ran:
            config = load_config()

        setup_mode = prompt_choice("您想如何设置 Hermes？", [
            "快速设置 — 提供商、模型和消息（推荐）",
            "完整设置 — 配置所有内容",
        ], 0)

        if setup_mode == 0:
            _run_first_time_quick_setup(config, hermes_home, is_existing)
            return

    # ── Full Setup — run all sections ──
    print_header("配置位置")
    print_info(f"配置文件:  {get_config_path()}")
    print_info(f"密钥文件: {get_env_path()}")
    print_info(f"数据文件夹:  {hermes_home}")
    print_info(f"安装目录:  {PROJECT_ROOT}")
    print()
    print_info("您可以直接编辑这些文件，或使用 'hermes config edit'")

    if migration_ran:
        print()
        print_info("设置已从 OpenClaw 导入。")
        print_info("以下各节将显示导入的内容 — 按 Enter 保持现状，")
        print_info("或根据需要选择重新配置。")

    # Section 1: Model & Provider
    if not (migration_ran and _skip_configured_section(config, "model", "Model & Provider")):
        setup_model_provider(config)

    # Section 2: Terminal Backend
    if not (migration_ran and _skip_configured_section(config, "terminal", "Terminal Backend")):
        setup_terminal_backend(config)

    # Section 3: Agent Settings
    if not (migration_ran and _skip_configured_section(config, "agent", "Agent Settings")):
        setup_agent_settings(config)

    # Section 4: Messaging Platforms
    if not (migration_ran and _skip_configured_section(config, "gateway", "Messaging Platforms")):
        setup_gateway(config)

    # Section 5: Tools
    if not (migration_ran and _skip_configured_section(config, "tools", "Tools")):
        setup_tools(config, first_install=not is_existing)

    # Save and show summary
    save_config(config)
    _print_setup_summary(config, hermes_home)

    _offer_launch_chat()


def _resolve_hermes_chat_argv() -> Optional[list[str]]:
    """Resolve argv for launching ``hermes chat`` in a fresh process."""
    hermes_bin = shutil.which("hermes")
    if hermes_bin:
        return [hermes_bin, "chat"]

    try:
        if importlib.util.find_spec("hermes_cli") is not None:
            return [sys.executable, "-m", "hermes_cli.main", "chat"]
    except Exception:
        pass

    return None


def _offer_launch_chat():
    """Prompt the user to jump straight into chat after setup."""
    print()
    if not prompt_yes_no("立即启动 hermes chat？", True):
        return

    chat_argv = _resolve_hermes_chat_argv()
    if not chat_argv:
        print_info("无法自动重新启动 Hermes。请手动运行 'hermes chat'。")
        return

    os.execvp(chat_argv[0], chat_argv)


def _run_first_time_quick_setup(config: dict, hermes_home, is_existing: bool):
    """Streamlined first-time setup: provider + model only.

    Applies sensible defaults for TTS (Edge), terminal (local), agent
    settings, and tools — the user can customize later via
    ``hermes setup <section>``.
    """
    # Step 1: Model & Provider (essential — skips rotation/vision/TTS)
    setup_model_provider(config, quick=True)

    # Step 2: Apply defaults for everything else
    _apply_default_agent_settings(config)
    config.setdefault("terminal", {}).setdefault("backend", "local")

    save_config(config)

    # Step 3: Offer messaging gateway setup
    print()
    gateway_choice = prompt_choice(
        "连接消息平台？（Telegram、Discord 等）",
        [
            "立即设置消息平台（推荐）",
            "跳过 — 稍后用 'hermes setup gateway' 设置",
        ],
        0,
    )

    if gateway_choice == 0:
        setup_gateway(config)
        save_config(config)

    print()
    print_success("设置完成！您已准备就绪。")
    print()
    print_info("  配置所有设置:    hermes setup")
    if gateway_choice != 0:
        print_info("  连接 Telegram/Discord:  hermes setup gateway")
    print()

    _print_setup_summary(config, hermes_home)

    _offer_launch_chat()


def _run_quick_setup(config: dict, hermes_home):
    """Quick setup — only configure items that are missing."""
    from hermes_cli.config import (
        get_missing_env_vars,
        get_missing_config_fields,
        check_config_version,
    )

    print()
    print_header("快速设置 — 仅缺失项")

    # Check what's missing
    missing_required = [
        v for v in get_missing_env_vars(required_only=False) if v.get("is_required")
    ]
    missing_optional = [
        v for v in get_missing_env_vars(required_only=False) if not v.get("is_required")
    ]
    missing_config = get_missing_config_fields()
    current_ver, latest_ver = check_config_version()

    has_anything_missing = (
        missing_required
        or missing_optional
        or missing_config
        or current_ver < latest_ver
    )

    if not has_anything_missing:
        print_success("一切已配置！无需操作。")
        print()
        print_info("运行 'hermes setup' 并选择 '完整设置' 重新配置，")
        print_info("或从菜单中选择特定部分。")
        return

    # Handle missing required env vars
    if missing_required:
        print()
        print_info(f"缺少 {len(missing_required)} 个必需设置：")
        for var in missing_required:
            print(f"     • {var['name']}")
        print()

        for var in missing_required:
            print()
            print(color(f"  {var['name']}", Colors.CYAN))
            print_info(f"  {var.get('description', '')}")
            if var.get("url"):
                print_info(f"  获取密钥: {var['url']}")

            if var.get("password"):
                value = prompt(f"  {var.get('prompt', var['name'])}", password=True)
            else:
                value = prompt(f"  {var.get('prompt', var['name'])}")

            if value:
                save_env_value(var["name"], value)
                print_success(f"  已保存 {var['name']}")
            else:
                print_warning(f"  已跳过 {var['name']}")

    # Split missing optional vars by category
    missing_tools = [v for v in missing_optional if v.get("category") == "tool"]
    missing_messaging = [
        v
        for v in missing_optional
        if v.get("category") == "messaging" and not v.get("advanced")
    ]

    # ── Tool API keys (checklist) ──
    if missing_tools:
        print()
        print_header("工具 API 密钥")

        checklist_labels = []
        for var in missing_tools:
            tools = var.get("tools", [])
            tools_str = f" → {', '.join(tools[:2])}" if tools else ""
            checklist_labels.append(f"{var.get('description', var['name'])}{tools_str}")

        selected_indices = prompt_checklist(
            "您想配置哪些工具？",
            checklist_labels,
        )

        for idx in selected_indices:
            var = missing_tools[idx]
            _prompt_api_key(var)

    # ── Messaging platforms (checklist then prompt for selected) ──
    if missing_messaging:
        print()
        print_header("消息平台")
        print_info("将 Hermes 连接到消息应用，从任何地方聊天。")
        print_info("之后可通过 'hermes setup gateway' 配置。")

        # Group by platform (preserving order)
        platform_order = []
        platforms = {}
        for var in missing_messaging:
            name = var["name"]
            if "TELEGRAM" in name:
                plat = "Telegram"
            elif "DISCORD" in name:
                plat = "Discord"
            elif "SLACK" in name:
                plat = "Slack"
            else:
                continue
            if plat not in platforms:
                platform_order.append(plat)
            platforms.setdefault(plat, []).append(var)

        platform_labels = [
            {
                "Telegram": "📱 Telegram",
                "Discord": "💬 Discord",
                "Slack": "💼 Slack",
            }.get(p, p)
            for p in platform_order
        ]

        selected_indices = prompt_checklist(
            "您想设置哪些平台？",
            platform_labels,
        )

        for idx in selected_indices:
            plat = platform_order[idx]
            vars_list = platforms[plat]
            emoji = {"Telegram": "📱", "Discord": "💬", "Slack": "💼"}.get(plat, "")
            print()
            print(color(f"  ─── {emoji} {plat} ───", Colors.CYAN))
            print()
            for var in vars_list:
                print_info(f"  {var.get('description', '')}")
                if var.get("url"):
                    print_info(f"  {var['url']}")
                if var.get("password"):
                    value = prompt(f"  {var.get('prompt', var['name'])}", password=True)
                else:
                    value = prompt(f"  {var.get('prompt', var['name'])}")
                if value:
                    save_env_value(var["name"], value)
                    print_success("  ✓ 已保存")
                else:
                    print_warning("  已跳过")
                print()

    # Handle missing config fields
    if missing_config:
        print()
        print_info(
            f"正在添加 {len(missing_config)} 个新配置选项（使用默认值）..."
        )
        for field in missing_config:
            print_success(f"  已添加 {field['key']} = {field['default']}")

        # Update config version
        config["_config_version"] = latest_ver
        save_config(config)

    # Jump to summary
    _print_setup_summary(config, hermes_home)
