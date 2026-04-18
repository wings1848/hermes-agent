"""Telegram-specific network helpers.

Provides a hostname-preserving fallback transport for networks where
api.telegram.org resolves to an endpoint that is unreachable from the current
host. The transport keeps the logical request host and TLS SNI as
api.telegram.org while retrying the TCP connection against one or more fallback
IPv4 addresses.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import socket
from typing import Any, Iterable, Optional

import httpx

logger = logging.getLogger(__name__)

_TELEGRAM_API_HOST = "api.telegram.org"

# DNS-over-HTTPS providers used to discover Telegram API IPs that may differ
# from the (potentially unreachable) IP returned by the local system resolver.
_DOH_TIMEOUT = 4.0  # seconds — bounded so connect() isn't noticeably delayed

_DOH_PROVIDERS: list[dict] = [
    {
        "url": "https://dns.google/resolve",
        "params": {"name": _TELEGRAM_API_HOST, "type": "A"},
        "headers": {},
    },
    {
        "url": "https://cloudflare-dns.com/dns-query",
        "params": {"name": _TELEGRAM_API_HOST, "type": "A"},
        "headers": {"Accept": "application/dns-json"},
    },
]

# Last-resort IPs when DoH is also blocked.  These are stable Telegram Bot API
# endpoints in the 149.154.160.0/20 block (same seed used by OpenClaw).
_SEED_FALLBACK_IPS: list[str] = ["149.154.167.220"]


def _resolve_proxy_url() -> str | None:
    # Delegate to shared implementation (env vars + macOS system proxy detection)
    from gateway.platforms.base import resolve_proxy_url
    return resolve_proxy_url("TELEGRAM_PROXY")


_NOT_SET = object()

class TelegramFallbackTransport(httpx.AsyncBaseTransport):
    """Retry Telegram Bot API requests via custom domains and fallback IPs.

    Requests continue to target https://api.telegram.org/... logically, but
    are retried against a list of custom domains and then fallback IPs on
    failure. Supports "sticky" routing to the last successful endpoint.
    """

    def __init__(
        self,
        fallback_ips: Iterable[str],
        custom_domains: Optional[Iterable[str]] = None,
        **transport_kwargs,
    ):
        self._fallback_ips = [ip for ip in dict.fromkeys(_normalize_fallback_ips(fallback_ips))]
        self._custom_domains = [d.strip() for d in (custom_domains or []) if d.strip()]
        proxy_url = _resolve_proxy_url()
        if proxy_url and "proxy" not in transport_kwargs:
            transport_kwargs["proxy"] = proxy_url

        self._transport_kwargs = transport_kwargs
        self._primary = httpx.AsyncHTTPTransport(**transport_kwargs)
        self._domain_transports: dict[str, httpx.AsyncHTTPTransport] = {
            domain: httpx.AsyncHTTPTransport(**transport_kwargs)
            for domain in self._custom_domains
        }
        self._ip_transports = {
            ip: httpx.AsyncHTTPTransport(**transport_kwargs) for ip in self._fallback_ips
        }
        self._sticky_endpoint: Any = _NOT_SET  # domain string, IP string, or None (primary)
        self._sticky_lock = asyncio.Lock()

    @property
    def _sticky_ip(self) -> Optional[str]:
        """Backward compatibility for tests."""
        return self._sticky_endpoint if self._sticky_endpoint is not _NOT_SET else None

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        # Only apply fallback logic to Telegram API requests.
        # Primary is used for all other hosts.
        if request.url.host != _TELEGRAM_API_HOST:
            return await self._primary.handle_async_request(request)

        # Build attempt order: Sticky -> Custom Domains -> Primary -> IPs
        sticky = self._sticky_endpoint
        attempt_order: list[Optional[str]] = []

        is_sticky_ip = False
        if sticky and sticky is not _NOT_SET:
            try:
                ipaddress.ip_address(sticky)
                is_sticky_ip = True
            except ValueError:
                pass

        if is_sticky_ip:
            # Original behavior: If an IP is sticky, try it first, then other IPs.
            # We preserve this to pass existing tests and because if we are using
            # IP fallbacks, the DNS/Domain path is likely blocked.
            attempt_order.append(sticky)
            for ip in self._fallback_ips:
                if ip != sticky:
                    attempt_order.append(ip)
        else:
            # Domain-first priority: Sticky -> Custom Domains -> Primary -> IPs
            if sticky is not _NOT_SET:
                attempt_order.append(sticky)

            # Add custom domains (excluding sticky)
            for domain in self._custom_domains:
                if domain != sticky:
                    attempt_order.append(domain)

            # Add primary (None represents api.telegram.org)
            if None not in attempt_order:
                attempt_order.append(None)

            # Add IP fallbacks
            for ip in self._fallback_ips:
                if ip != sticky:
                    attempt_order.append(ip)

        last_error: Exception | None = None
        for endpoint in attempt_order:
            # endpoint is:
            # - None: Primary (api.telegram.org)
            # - string: Custom Domain or IP
            
            is_ip = False
            if endpoint:
                try:
                    ipaddress.ip_address(endpoint)
                    is_ip = True
                except ValueError:
                    pass

            if endpoint is None:
                candidate = request
                transport = self._primary
            elif is_ip:
                candidate = _rewrite_request_for_ip(request, endpoint)
                transport = self._ip_transports[endpoint]
            else:
                candidate = _rewrite_request_for_custom_domain(request, endpoint)
                # Ensure we have a transport for this domain (e.g. if added via env after init)
                if endpoint not in self._domain_transports:
                    self._domain_transports[endpoint] = httpx.AsyncHTTPTransport(**self._transport_kwargs)
                transport = self._domain_transports[endpoint]

            try:
                response = await transport.handle_async_request(candidate)
                # Successful request: update sticky endpoint
                if self._sticky_endpoint is _NOT_SET or self._sticky_endpoint != endpoint:
                    async with self._sticky_lock:
                        if self._sticky_endpoint is _NOT_SET or self._sticky_endpoint != endpoint:
                            self._sticky_endpoint = endpoint
                            desc = endpoint if endpoint else _TELEGRAM_API_HOST
                            logger.warning(
                                "[Telegram] Path successful; using sticky endpoint %s",
                                desc,
                            )
                return response
            except Exception as exc:
                last_error = exc
                if not _is_retryable_connect_error(exc):
                    raise
                
                desc = endpoint if endpoint else _TELEGRAM_API_HOST
                if endpoint == sticky:
                    logger.warning("[Telegram] Sticky endpoint %s failed; falling back", desc)
                else:
                    logger.warning("[Telegram] Attempt %s failed: %s", desc, exc)
                continue

        if last_error is None:
            raise RuntimeError("All Telegram endpoints exhausted but no error was recorded")
        raise last_error

    async def aclose(self) -> None:
        await self._primary.aclose()
        for transport in self._domain_transports.values():
            await transport.aclose()
        for transport in self._ip_transports.values():
            await transport.aclose()


def _rewrite_request_for_custom_domain(request: httpx.Request, domain: str) -> httpx.Request:
    """Rewrite request to use a custom domain.
    
    Unlike IP fallbacks, custom domains use their own hostname for TLS SNI
    and the HTTP Host header.
    """
    url = request.url.copy_with(host=domain)
    headers = request.headers.copy()
    # Explicitly update Host header
    headers["host"] = domain
    
    extensions = dict(request.extensions)
    extensions.pop("sni_hostname", None)
    
    return httpx.Request(
        method=request.method,
        url=url,
        headers=headers,
        stream=request.stream,
        extensions=extensions,
    )


def _normalize_fallback_ips(values: Iterable[str]) -> list[str]:
    normalized: list[str] = []
    for value in values:
        raw = str(value).strip()
        if not raw:
            continue
        try:
            addr = ipaddress.ip_address(raw)
        except ValueError:
            logger.warning("Ignoring invalid Telegram fallback IP: %r", raw)
            continue
        if addr.version != 4:
            logger.warning("Ignoring non-IPv4 Telegram fallback IP: %s", raw)
            continue
        if addr.is_private or addr.is_loopback or addr.is_link_local or addr.is_unspecified:
            logger.warning("Ignoring private/internal Telegram fallback IP: %s", raw)
            continue
        normalized.append(str(addr))
    return normalized


def parse_fallback_ip_env(value: str | None) -> list[str]:
    if not value:
        return []
    parts = [part.strip() for part in value.split(",")]
    return _normalize_fallback_ips(parts)


def _resolve_system_dns() -> set[str]:
    """Return the IPv4 addresses that the OS resolver gives for api.telegram.org."""
    try:
        results = socket.getaddrinfo(_TELEGRAM_API_HOST, 443, socket.AF_INET)
        return {addr[4][0] for addr in results}
    except Exception:
        return set()


async def _query_doh_provider(
    client: httpx.AsyncClient, provider: dict
) -> list[str]:
    """Query one DoH provider and return A-record IPs."""
    try:
        resp = await client.get(
            provider["url"], params=provider["params"], headers=provider["headers"]
        )
        resp.raise_for_status()
        data = resp.json()
        ips: list[str] = []
        for answer in data.get("Answer", []):
            if answer.get("type") != 1:  # A record
                continue
            raw = answer.get("data", "").strip()
            try:
                ipaddress.ip_address(raw)
                ips.append(raw)
            except ValueError:
                continue
        return ips
    except Exception as exc:
        logger.debug("DoH query to %s failed: %s", provider["url"], exc)
        return []


async def discover_fallback_ips() -> list[str]:
    """Auto-discover Telegram API IPs via DNS-over-HTTPS.

    Resolves api.telegram.org through Google and Cloudflare DoH, collects all
    unique IPs, and excludes the system-DNS-resolved IP (which is presumably
    unreachable on this network).  Falls back to a hardcoded seed list when DoH
    is also unavailable.
    """
    async with httpx.AsyncClient(timeout=httpx.Timeout(_DOH_TIMEOUT)) as client:
        doh_tasks = [_query_doh_provider(client, p) for p in _DOH_PROVIDERS]
        system_dns_task = asyncio.to_thread(_resolve_system_dns)
        results = await asyncio.gather(system_dns_task, *doh_tasks, return_exceptions=True)

    # results[0] = system DNS IPs (set), results[1:] = DoH IP lists
    system_ips: set[str] = results[0] if isinstance(results[0], set) else set()

    doh_ips: list[str] = []
    for r in results[1:]:
        if isinstance(r, list):
            doh_ips.extend(r)

    # Deduplicate preserving order, exclude system-DNS IPs
    seen: set[str] = set()
    candidates: list[str] = []
    for ip in doh_ips:
        if ip not in seen and ip not in system_ips:
            seen.add(ip)
            candidates.append(ip)

    # Validate through existing normalization
    validated = _normalize_fallback_ips(candidates)

    if validated:
        logger.debug("Discovered Telegram fallback IPs via DoH: %s", ", ".join(validated))
        return validated

    logger.info(
        "DoH discovery yielded no new IPs (system DNS: %s); using seed fallback IPs %s",
        ", ".join(system_ips) or "unknown",
        ", ".join(_SEED_FALLBACK_IPS),
    )
    return list(_SEED_FALLBACK_IPS)


def _rewrite_request_for_ip(request: httpx.Request, ip: str) -> httpx.Request:
    original_host = request.url.host or _TELEGRAM_API_HOST
    url = request.url.copy_with(host=ip)
    headers = request.headers.copy()
    headers["host"] = original_host
    extensions = dict(request.extensions)
    extensions["sni_hostname"] = original_host
    return httpx.Request(
        method=request.method,
        url=url,
        headers=headers,
        stream=request.stream,
        extensions=extensions,
    )


def _is_retryable_connect_error(exc: Exception) -> bool:
    return isinstance(exc, (httpx.ConnectTimeout, httpx.ConnectError))
