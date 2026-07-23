"""Website availability checking and objective classification."""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from enum import Enum
from urllib.parse import urlparse

import httpx

from lead_finder.config import WebsiteCheckConfig


class WebsiteStatus(str, Enum):  # noqa: UP042
    NO_WEBSITE = "no_website"
    WORKING = "working"
    UNREACHABLE = "unreachable"
    TIMEOUT = "timeout"
    DNS_ERROR = "dns_error"
    SSL_ERROR = "ssl_error"
    HTTP_ERROR = "http_error"
    REDIRECT_LOOP = "redirect_loop"
    INVALID_URL = "invalid_url"
    BLOCKED = "blocked"
    UNKNOWN_ERROR = "unknown_error"


@dataclass
class WebsiteCheckResult:
    business_id: int
    original_url: str | None
    normalized_url: str | None
    final_url: str | None
    status: WebsiteStatus
    http_status: int | None
    redirect_count: int
    response_time_ms: int | None
    content_type: str | None
    error_type: str | None
    error_message: str | None


def normalize_url(raw_url: str | None) -> str | None:
    """Safely normalize a URL, returning None if invalid or unsupported."""
    if not raw_url:
        return None

    url = raw_url.strip()
    if not url:
        return None

    if "://" not in url and "." in url.split("/")[0] and not url.startswith(
        ("http", "ftp", "javascript", "data")
    ):
        url = f"https://{url}"

    try:
        parsed = urlparse(url)
    except Exception:
        return None

    if parsed.scheme not in ("http", "https"):
        return None

    if not parsed.netloc:
        return None

    return url


class WebsiteChecker:
    """Checks website availability objectively without downloading large bodies."""

    def __init__(self, config: WebsiteCheckConfig) -> None:
        self.config = config
        self._semaphore = asyncio.Semaphore(config.concurrency)
        timeout = httpx.Timeout(
            connect=config.connect_timeout_seconds,
            read=config.read_timeout_seconds,
            write=config.connect_timeout_seconds,
            pool=config.connect_timeout_seconds,
        )
        self.client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=config.follow_redirects,
            max_redirects=config.max_redirects,
            headers={"User-Agent": "Mozilla/5.0 (compatible; LeadFinder/1.0)"},
        )

    async def close(self) -> None:
        """Close the HTTP client."""
        await self.client.aclose()

    async def check_website(
        self, business_id: int, raw_url: str | None
    ) -> WebsiteCheckResult:
        """Perform an objective check of a single website."""
        async with self._semaphore:
            return await self._check_website_internal(business_id, raw_url)

    async def _check_website_internal(
        self, business_id: int, raw_url: str | None
    ) -> WebsiteCheckResult:
        original_url = raw_url.strip() if raw_url else None
        if not original_url:
            return self._build_result(
                business_id, original_url, None, WebsiteStatus.NO_WEBSITE
            )

        normalized_url = normalize_url(original_url)
        if not normalized_url:
            return self._build_result(
                business_id, original_url, None, WebsiteStatus.INVALID_URL
            )

        start_time = time.monotonic()
        try:
            async with self.client.stream("GET", normalized_url) as response:
                response_time_ms = int((time.monotonic() - start_time) * 1000)
                final_url = str(response.url)
                http_status = response.status_code
                redirect_count = len(response.history)
                content_type = response.headers.get("content-type")

                status = WebsiteStatus.WORKING
                if 400 <= http_status < 600:
                    if http_status in (401, 403):
                        status = WebsiteStatus.BLOCKED
                    else:
                        status = WebsiteStatus.HTTP_ERROR

                return self._build_result(
                    business_id=business_id,
                    original_url=original_url,
                    normalized_url=normalized_url,
                    status=status,
                    final_url=final_url,
                    http_status=http_status,
                    redirect_count=redirect_count,
                    response_time_ms=response_time_ms,
                    content_type=content_type,
                )

        except httpx.TooManyRedirects:
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            return self._build_result(
                business_id,
                original_url,
                normalized_url,
                WebsiteStatus.REDIRECT_LOOP,
                redirect_count=self.config.max_redirects,
                response_time_ms=response_time_ms,
                error_type="TooManyRedirects",
                error_message="Exceeded maximum redirects",
            )
        except httpx.TimeoutException as e:
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            return self._build_result(
                business_id,
                original_url,
                normalized_url,
                WebsiteStatus.TIMEOUT,
                response_time_ms=response_time_ms,
                error_type=e.__class__.__name__,
                error_message=str(e),
            )
        except httpx.ConnectError as e:
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            err_str = str(e).lower()
            if "ssl" in err_str or "certificate" in err_str:
                status = WebsiteStatus.SSL_ERROR
            elif (
                "nodename nor servname provided" in err_str
                or "name or service not known" in err_str
                or "nameresolutionerror" in err_str
                or "getaddrinfo" in err_str
            ):
                status = WebsiteStatus.DNS_ERROR
            elif "connection refused" in err_str or "unreachable" in err_str:
                status = WebsiteStatus.UNREACHABLE
            else:
                status = WebsiteStatus.UNREACHABLE

            return self._build_result(
                business_id,
                original_url,
                normalized_url,
                status,
                response_time_ms=response_time_ms,
                error_type=e.__class__.__name__,
                error_message=str(e),
            )
        except Exception as e:
            response_time_ms = int((time.monotonic() - start_time) * 1000)
            return self._build_result(
                business_id,
                original_url,
                normalized_url,
                WebsiteStatus.UNKNOWN_ERROR,
                response_time_ms=response_time_ms,
                error_type=e.__class__.__name__,
                error_message=str(e),
            )

    def _build_result(
        self,
        business_id: int,
        original_url: str | None,
        normalized_url: str | None,
        status: WebsiteStatus,
        final_url: str | None = None,
        http_status: int | None = None,
        redirect_count: int = 0,
        response_time_ms: int | None = None,
        content_type: str | None = None,
        error_type: str | None = None,
        error_message: str | None = None,
    ) -> WebsiteCheckResult:
        return WebsiteCheckResult(
            business_id=business_id,
            original_url=original_url,
            normalized_url=normalized_url,
            final_url=final_url,
            status=status,
            http_status=http_status,
            redirect_count=redirect_count,
            response_time_ms=response_time_ms,
            content_type=content_type,
            error_type=error_type,
            error_message=error_message,
        )
