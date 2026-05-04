# Telegram增加自定义BotAPI域名方案

## 需求概述

为 Telegram 渠道增加自定义 Bot API 域名功能。当配置了自定义域名时，优先按顺序尝试使用配置的域名列表进行请求；若全部失败，则回退（Fallback）至默认的 `api.telegram.org` 及其原有的 IP Fallback 流程。

## 优先级与重试逻辑

```text
[启动请求]
     ↓
1. 尝试 Sticky Domain (若存在)
     ↓ 失败
2. 依次尝试配置的域名列表 (Custom Domains)
     ↓ 全部失败
3. 尝试默认 api.telegram.org (Primary)
     ↓ 失败
4. 尝试 IP Fallback (DoH 发现或 Seed IPs)
     ↓ 失败
[抛出最终错误]
```

## 配置方式

### 环境变量
支持多个域名，使用**逗号**分隔。
```bash
TELEGRAM_CUSTOM_DOMAINS="tgapi.072103.xyz"
```

### 配置文件 (config.yaml)
```yaml
platforms:
  telegram:
    extra:
      telegram_custom_domains:
        - tgapi.072103.xyz
        - another-proxy.io
```

## 核心机制说明

- **Domain 格式**：仅支持 Hostname 格式（如 `api.example.com`），默认强制使用 **HTTPS (Port 443)**。
- **Domain Sticky 机制**：
  - **内存级 Sticky**：一旦某个域名（自定义域名或原域名）请求成功，后续请求将优先使用该域名。
  - 状态仅保存在内存中，进程重启后重新按优先级探测。
- **请求头处理**：使用自定义域名请求时，HTTP `Host` 头部和 TLS SNI 应对应修改为该自定义域名（与 IP Fallback 模式保持 `Host: api.telegram.org` 的逻辑不同）。
- **接口覆盖**：自定义域名应同时应用于 API 接口（`api.telegram.org`）和文件接口（`api.telegram.org/file/`）。

## 注意事项

- **环境一致性**
- **兼容性**：必须完整保留现有的 `TelegramFallbackTransport` 功能（DoH 发现、种子 IP 列表、SNI 保持等）。
- **验证逻辑**：需增加域名合法性检查，防止注入非法字符。
- **依赖管理**：继续使用 `uv` 进行依赖管理。

## 测试要求

- **单元测试**：
  - 验证环境变量和 YAML 配置的解析优先级。
  - 模拟网络失败，验证从自定义域名到 Primary 再到 IP Fallback 的完整切换流程。
  - 验证 Sticky 机制在成功请求后的生效情况。
