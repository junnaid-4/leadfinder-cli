import httpx
import pytest
import respx

from lead_finder.config import WebsiteCheckConfig
from lead_finder.website_checker import WebsiteChecker, WebsiteStatus, normalize_url


def test_normalize_url():
    assert normalize_url("http://example.com") == "http://example.com"
    assert normalize_url("  https://test.com  ") == "https://test.com"
    assert normalize_url("example.com") == "https://example.com"
    assert normalize_url("example.com/path") == "https://example.com/path"
    assert normalize_url("ftp://example.com") is None
    assert normalize_url("javascript:alert(1)") is None
    assert normalize_url("data:text/plain,hello") is None
    assert normalize_url("") is None
    assert normalize_url(None) is None

@pytest.fixture
async def checker():
    config = WebsiteCheckConfig(
        concurrency=2,
        connect_timeout_seconds=1.0,
        read_timeout_seconds=1.0,
        max_redirects=3,
    )
    chk = WebsiteChecker(config)
    yield chk
    await chk.close()

@pytest.mark.asyncio
async def test_check_missing_website(checker):
    result = await checker.check_website(1, None)
    assert result.status == WebsiteStatus.NO_WEBSITE
    assert result.normalized_url is None

@pytest.mark.asyncio
@respx.mock
async def test_check_working(checker):
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"})
    )
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.WORKING
    assert result.http_status == 200
    assert result.content_type == "text/html"

@pytest.mark.asyncio
@respx.mock
async def test_check_redirect_followed(checker):
    respx.get("https://example.com").mock(
        return_value=httpx.Response(301, headers={"Location": "https://final.com/"})
    )
    respx.get("https://final.com/").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"})
    )

    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.WORKING
    assert str(result.final_url) == "https://final.com/"
    assert result.redirect_count == 1

@pytest.mark.asyncio
async def test_check_invalid_urls(checker):
    # Requirement 4 & 5: Malformed and unsupported schemes (no network request made)
    invalid_urls = [
        "ftp://example.com",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "file:///etc/passwd",
        "http://[::1",
    ]
    for url in invalid_urls:
        result = await checker.check_website(1, url)
        assert result.status == WebsiteStatus.INVALID_URL
        assert result.normalized_url is None

@pytest.mark.asyncio
@respx.mock
async def test_check_normalized_url(checker):
    # Requirement 6: URL without scheme
    respx.get("https://example.com").mock(
        return_value=httpx.Response(200, headers={"content-type": "text/html"})
    )
    result = await checker.check_website(1, "example.com")
    assert result.normalized_url == "https://example.com"
    assert result.status == WebsiteStatus.WORKING

@pytest.mark.asyncio
@respx.mock
async def test_check_404(checker):
    respx.get("https://example.com").mock(return_value=httpx.Response(404))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.HTTP_ERROR
    assert result.http_status == 404

@pytest.mark.asyncio
@respx.mock
async def test_check_500(checker):
    respx.get("https://example.com").mock(return_value=httpx.Response(500))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.HTTP_ERROR
    assert result.http_status == 500

@pytest.mark.asyncio
@respx.mock
async def test_check_blocked(checker):
    respx.get("https://example.com").mock(return_value=httpx.Response(403))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.BLOCKED
    assert result.http_status == 403

@pytest.mark.asyncio
@respx.mock
async def test_check_timeout(checker):
    respx.get("https://example.com").mock(side_effect=httpx.ConnectTimeout("Timeout"))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.TIMEOUT

@pytest.mark.asyncio
@respx.mock
async def test_check_dns_error(checker):
    respx.get("https://example.com").mock(side_effect=httpx.ConnectError("NameResolutionError"))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.DNS_ERROR

@pytest.mark.asyncio
@respx.mock
async def test_check_ssl_error(checker):
    respx.get("https://example.com").mock(
        side_effect=httpx.ConnectError("SSL certificate verify failed")
    )
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.SSL_ERROR

@pytest.mark.asyncio
@respx.mock
async def test_check_unreachable(checker):
    respx.get("https://example.com").mock(side_effect=httpx.ConnectError("Connection refused"))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.UNREACHABLE

@pytest.mark.asyncio
@respx.mock
async def test_check_redirect_loop(checker):
    respx.get("https://example.com").mock(side_effect=httpx.TooManyRedirects("Exceeded"))
    result = await checker.check_website(1, "https://example.com")
    assert result.status == WebsiteStatus.REDIRECT_LOOP

@pytest.mark.asyncio
async def test_concurrency_limit(checker):
    assert checker._semaphore._value == 2
