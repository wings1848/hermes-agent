# Setup 测试中文化断言断裂清单

## 概述

setup.py 中文化后，以下测试因断言英文字符串或 mock 不识别中文 prompt 而失败。功能本身正确，需更新测试预期为中文字符串。

复测时间：2026-04-29，使用 `venv/bin/python`，共 53 个测试。
- 第一轮：45 passed / 8 failed
- 修复后：53 passed / 0 failed

## 已修复清单

### 1. test_offer_launch_chat_manual_fallback_when_unresolvable ✅
- **文件**: `tests/hermes_cli/test_setup.py`
- **修复**: `"Run 'hermes chat' manually"` → `"请手动运行 'hermes chat'"`

### 2. test_setup_gateway_skips_service_install_when_systemctl_missing ✅
- **文件**: `tests/hermes_cli/test_setup.py`
- **修复**: `"Messaging platforms configured!"` → `"消息平台已配置！"`，`"Start the gateway to bring your bots online:"` → `"启动网关以使您的 Bot 上线："`

### 3. test_setup_gateway_in_container_shows_docker_guidance ✅
- **文件**: `tests/hermes_cli/test_setup.py`
- **修复**: `"Messaging platforms configured!"` → `"消息平台已配置！"`

### 4. test_modal_setup_can_use_nous_subscription_without_modal_creds ✅
- **文件**: `tests/hermes_cli/test_setup.py`
- **修复**: mock `fake_prompt_choice` 添加中文 prompt 映射

### 5. test_modal_setup_persists_direct_mode_when_user_chooses_their_own_account ✅
- **文件**: `tests/hermes_cli/test_setup.py`
- **修复**: mock `fake_prompt_choice` 添加中文 prompt 映射

### 6. test_setup_pool_step_shows_manual_vs_auto_detected_counts ✅
- **文件**: `tests/hermes_cli/test_setup_model_provider.py`
- **修复**: mock `fake_prompt_choice` 添加中文 prompt 映射（`"选择 TTS 提供商："`、`"配置视觉："`等）

### 7. test_setup_copilot_acp_skips_same_provider_pool_step ✅
- **文件**: `tests/hermes_cli/test_setup_model_provider.py`
- **修复**: mock `fake_prompt_choice` 添加中文 prompt 映射

### 8. test_setup_agent_settings_uses_displayed_max_iterations_value ✅
- **文件**: `tests/hermes_cli/test_setup_agent_settings.py`
- **修复**: `"Press Enter to keep 60."` → `"按 Enter 保持 60。"`，`"Default is 90"` → `"默认是 90"`

### 9-10. test_setup_reconfigure.py ×2 ✅
- **文件**: `tests/hermes_cli/test_setup_reconfigure.py`
- **修复**: 适配新返回用户菜单行为，mock `prompt_choice` return_value=1

---
*记录时间：2026-04-29*
*状态：全部已修复*
