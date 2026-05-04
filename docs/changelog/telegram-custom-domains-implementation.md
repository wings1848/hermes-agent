# Telegram增加自定义BotAPI域名实施报告

## 1. 目标概述
为 Telegram 渠道实现自定义 API 域名支持，旨在解决特定网络环境下 `api.telegram.org` 无法访问的问题。该方案集成了“粘性路由（Sticky Routing）”机制与“多级回退（Multi-tier Fallback）”策略。

## 2. 核心设计

### 2.1 优先级逻辑 (Fallback Chain)
请求按以下顺序尝试，直到成功为止：
1.  **Sticky Endpoint**：优先使用上次请求成功的端点（域名或 IP）。
2.  **Custom Domains**：依次尝试环境变量 `HERMES_TELEGRAM_CUSTOM_DOMAINS` 中配置的域名列表。
3.  **Primary Host**：尝试默认的 `api.telegram.org`。
4.  **IP Fallback**：尝试通过 DoH 发现或硬编码种子列表获取的 Telegram 官方 IP（SNI 保持为 `api.telegram.org`）。

### 2.2 粘性机制 (Sticky Mechanism)
- **实现方式**：在 `TelegramFallbackTransport` 中引入 `_sticky_endpoint` 变量（内存级）。
- **状态区分**：使用 `_NOT_SET` 哨兵值区分“从未请求成功”与“Primary 路径成功（None）”两种状态，确保 Primary 路径成功后也能获得最高优先级。
- **并发安全**：使用 `asyncio.Lock()` 确保在多并发请求下更新 Sticky 状态的线程安全。

### 2.3 请求重写逻辑
- **自定义域名**：修改 URL Host 的同时，同步更新 HTTP `Host` 头部并移除 `sni_hostname` 扩展，允许 `httpx` 根据新域名自动生成正确的 TLS SNI。
- **IP 回退**：修改 URL Host 为 IP，但保持 `Host` 头部和 `sni_hostname` 为 `api.telegram.org`，以通过 Telegram 的边缘服务器验证。

## 3. 代码变更说明

### 3.1 传输层 (`gateway/platforms/telegram_network.py`)
- 重构 `TelegramFallbackTransport`，支持 `custom_domains` 参数。
- 实现 `_rewrite_request_for_custom_domain` 函数。
- 优化 `handle_async_request` 重试循环，增加对 IP Sticky 行为的兼容逻辑，确保现有测试不被破坏。

### 3.2 配置层 (`gateway/config.py`)
- 在 `_apply_env_overrides` 中增加对 `HERMES_TELEGRAM_CUSTOM_DOMAINS` 和 `TELEGRAM_CUSTOM_DOMAINS` 的解析。
- 支持以逗号分隔的多个域名输入。

### 3.3 适配器层 (`gateway/platforms/telegram.py`)
- 在 `connect` 方法中提取配置并实例化具备自定义域名能力的 `TelegramFallbackTransport`。

### 3.4 测试验证 (`tests/gateway/test_telegram_custom_domains.py`)
- 编写了完整的单元测试，验证了：
    - 重写函数对 `Host` 和 `SNI` 的处理。
    - 完整的优先级回退链路。
    - Sticky 机制在域名和 IP 场景下的生效情况。
    - 环境变量的解析正确性。

## 4. 使用说明

### 环境变量
```bash
# 设置一个或多个自定义域名（逗号分隔）
export HERMES_TELEGRAM_CUSTOM_DOMAINS="tgapi.example.com,proxy.another.io"
```

### 配置文件 (config.yaml)
```yaml
platforms:
  telegram:
    extra:
      telegram_custom_domains:
        - tgapi.example.com
        - proxy.another.io
```

## 5. 兼容性保证
- **向后兼容**：保留了原有的 `_sticky_ip` 属性（通过 `@property` 映射），确保旧有监控或测试代码不会报错。
- **IP Fallback 保留**：当自定义域名和 Primary 域名均失效时，系统仍会自动触发原有的 DoH IP 发现机制。
