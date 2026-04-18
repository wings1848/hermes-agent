
import httpx
import pytest
import ipaddress
from typing import Any
from gateway.platforms import telegram_network as tnet
from gateway.config import GatewayConfig, Platform, PlatformConfig, _apply_env_overrides

# Reuse FakeTransport from existing tests logic
class FakeTransport(httpx.AsyncBaseTransport):
    def __init__(self, calls, behavior):
        self.calls = calls
        self.behavior = behavior
        self.closed = False

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(
            {
                "url_host": request.url.host,
                "host_header": request.headers.get("host"),
                "sni_hostname": request.extensions.get("sni_hostname"),
            }
        )
        action = self.behavior.get(request.url.host, "ok")
        if action == "timeout":
            raise httpx.ConnectTimeout("timed out")
        if action == "connect_error":
            raise httpx.ConnectError("connect error")
        return httpx.Response(200, request=request, text="ok")

    async def aclose(self) -> None:
        self.closed = True

def _fake_transport_factory(calls, behavior):
    def factory(**kwargs):
        return FakeTransport(calls, behavior)
    return factory

def _telegram_request():
    return httpx.Request("GET", "https://api.telegram.org/botTOKEN/getMe")

class TestTelegramCustomDomains:
    def test_rewrite_request_for_custom_domain(self):
        request = _telegram_request()
        # Mock an SNI extension that might be present
        request.extensions["sni_hostname"] = "api.telegram.org"
        
        rewritten = tnet._rewrite_request_for_custom_domain(request, "tgapi.example.com")
        
        assert rewritten.url.host == "tgapi.example.com"
        # Host header should be updated
        assert rewritten.headers.get("host") == "tgapi.example.com"
        # SNI should be removed so httpx uses the new domain
        assert "sni_hostname" not in rewritten.extensions

    @pytest.mark.asyncio
    async def test_custom_domain_priority_and_stickiness(self, monkeypatch):
        calls = []
        behavior = {
            "api.telegram.org": "timeout",
            "tgapi.example.com": "ok",
            "149.154.167.220": "ok"
        }
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(
            fallback_ips=["149.154.167.220"],
            custom_domains=["tgapi.example.com"]
        )
        
        # 1. First request: Should try custom domain before primary and IP
        resp = await transport.handle_async_request(_telegram_request())
        assert resp.status_code == 200
        assert transport._sticky_endpoint == "tgapi.example.com"
        
        assert calls[0]["url_host"] == "tgapi.example.com"
        assert len(calls) == 1

        # 2. Second request: Should use sticky custom domain directly
        calls.clear()
        await transport.handle_async_request(_telegram_request())
        assert calls[0]["url_host"] == "tgapi.example.com"
        assert len(calls) == 1

    @pytest.mark.asyncio
    async def test_fallback_chain_full(self, monkeypatch):
        calls = []
        # Custom fails -> Primary fails -> IP works
        behavior = {
            "tgapi.example.com": "timeout",
            "api.telegram.org": "timeout",
            "149.154.167.220": "ok"
        }
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(
            fallback_ips=["149.154.167.220"],
            custom_domains=["tgapi.example.com"]
        )
        
        resp = await transport.handle_async_request(_telegram_request())
        assert resp.status_code == 200
        assert transport._sticky_endpoint == "149.154.167.220"
        
        assert [c["url_host"] for c in calls] == [
            "tgapi.example.com",
            "api.telegram.org",
            "149.154.167.220"
        ]

    @pytest.mark.asyncio
    async def test_primary_becomes_sticky(self, monkeypatch):
        calls = []
        # Custom fails -> Primary works
        behavior = {
            "tgapi.example.com": "timeout",
            "api.telegram.org": "ok"
        }
        monkeypatch.setattr(tnet.httpx, "AsyncHTTPTransport", _fake_transport_factory(calls, behavior))

        transport = tnet.TelegramFallbackTransport(
            fallback_ips=["149.154.167.220"],
            custom_domains=["tgapi.example.com"]
        )
        
        resp = await transport.handle_async_request(_telegram_request())
        assert resp.status_code == 200
        assert transport._sticky_endpoint is None # None represents primary
        
        assert [c["url_host"] for c in calls] == [
            "tgapi.example.com",
            "api.telegram.org"
        ]
        
        # Next request should try primary first
        calls.clear()
        await transport.handle_async_request(_telegram_request())
        assert calls[0]["url_host"] == "api.telegram.org"
        assert len(calls) == 1

    def test_config_parsing_env(self, monkeypatch):
        monkeypatch.setenv("HERMES_TELEGRAM_CUSTOM_DOMAINS", "domain1.com, domain2.org")
        config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True)})
        _apply_env_overrides(config)
        
        domains = config.platforms[Platform.TELEGRAM].extra.get("telegram_custom_domains")
        assert domains == ["domain1.com", "domain2.org"]

    def test_config_parsing_env_legacy(self, monkeypatch):
        monkeypatch.delenv("HERMES_TELEGRAM_CUSTOM_DOMAINS", raising=False)
        monkeypatch.setenv("TELEGRAM_CUSTOM_DOMAINS", "legacy.com")
        config = GatewayConfig(platforms={Platform.TELEGRAM: PlatformConfig(enabled=True)})
        _apply_env_overrides(config)
        
        domains = config.platforms[Platform.TELEGRAM].extra.get("telegram_custom_domains")
        assert domains == ["legacy.com"]
