# TELEGRAM_CUSTOM_DOMAINS 环境变量命名不一致

## 问题描述

`gateway/config.py` 中 `_apply_env_overrides()` 读取的环境变量名为 `TELEGRAM_CUSTOM_DOMAINS`（无 `HERMES_` 前缀），
但测试 `tests/gateway/test_telegram_custom_domains.py::TestTelegramCustomDomains::test_config_parsing_env`
设置的是 `HERMES_TELEGRAM_CUSTOM_DOMAINS`（带前缀），导致 env var 未被读取，`custom_domains` 返回 `None`。

## 复现方法

```bash
cd /home/wings/BrainWorkshop/Code_Project/hermes-agent
source venv/bin/activate
python -m pytest tests/gateway/test_telegram_custom_domains.py::TestTelegramCustomDomains::test_config_parsing_env -v --tb=long
```

## 根因

| 位置 | 使用的变量名 |
|------|-------------|
| 代码 (`gateway/config.py:906`) | `TELEGRAM_CUSTOM_DOMAINS` |
| 测试 (`test_telegram_custom_domains.py:142`) | `HERMES_TELEGRAM_CUSTOM_DOMAINS` |

## 上下文：同文件内其他 env var 的命名约定

`_apply_env_overrides()` 中所有 Telegram 相关 env var **均无 `HERMES_` 前缀**：

| Env Var | 用途 |
|---------|------|
| `TELEGRAM_BOT_TOKEN` | Bot Token |
| `TELEGRAM_REPLY_TO_MODE` | 回复模式 |
| `TELEGRAM_FALLBACK_IPS` | 备用 IP |
| `TELEGRAM_CUSTOM_DOMAINS` | 自定义域名 |
| `TELEGRAM_HOME_CHANNEL` | Home 频道 |

## 处理方案（待定）

- **方案 A**：测试中去掉 `HERMES_` 前缀，与代码保持一致（最小改动）
- **方案 B**：代码中同时支持两个变量名，`HERMES_` 版本优先（完整方案，符合 Hermes 命名惯例）

## 相关文件

- `gateway/config.py` — `_apply_env_overrides()` 函数
- `tests/gateway/test_telegram_custom_domains.py` — 相关测试

---
*记录日期：2026-04-29*
