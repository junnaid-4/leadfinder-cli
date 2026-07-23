"""Tests for the Places API client."""

from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from lead_finder.places_client import (
    PLACES_API_URL,
    PlacesAPIInvalidRequestError,
    PlacesAPIKeyError,
    PlacesAPIResponseError,
    PlacesAPITemporaryError,
    PlacesClient,
)

API_KEY = "test_api_key_123"


@pytest.fixture
def client() -> PlacesClient:
    return PlacesClient(API_KEY)


@pytest.mark.asyncio
async def test_search_text_success(client: PlacesClient) -> None:
    """1. Successful single-page search."""
    with respx.mock:
        route = respx.post(PLACES_API_URL).mock(
            return_value=httpx.Response(
                200, json={"places": [{"id": "ChIJN1t_tDeuEmsRUsoyG83frY4"}]}
            )
        )

        response = await client.search_text("electricians in manchester")

        assert "places" in response
        assert len(response["places"]) == 1
        assert response["places"][0]["id"] == "ChIJN1t_tDeuEmsRUsoyG83frY4"

        request = route.calls.last.request
        assert request.headers["X-Goog-Api-Key"] == API_KEY
        assert "X-Goog-FieldMask" in request.headers


@pytest.mark.asyncio
async def test_search_text_pagination(client: PlacesClient) -> None:
    """2. Pagination parameter handling with correct JSON parsing."""
    with respx.mock:
        route = respx.post(PLACES_API_URL).mock(
            return_value=httpx.Response(200, json={"places": []})
        )

        await client.search_text("electricians", page_token="token_abc123")

        request = route.calls.last.request
        body: dict[str, Any] = json.loads(request.content.decode("utf-8"))
        assert body.get("pageToken") == "token_abc123"


@pytest.mark.asyncio
async def test_empty_api_result(client: PlacesClient) -> None:
    """29. Empty API result."""
    with respx.mock:
        respx.post(PLACES_API_URL).mock(return_value=httpx.Response(200, json={}))
        response = await client.search_text("nowhere")
        assert response == {}


@pytest.mark.asyncio
async def test_malformed_json_response(client: PlacesClient) -> None:
    """30. Malformed JSON."""
    with respx.mock:
        respx.post(PLACES_API_URL).mock(return_value=httpx.Response(200, content=b"{malformed"))
        with pytest.raises(PlacesAPIResponseError) as exc_info:
            await client.search_text("bad json")
        assert "Malformed JSON response" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, json.JSONDecodeError)


@pytest.mark.asyncio
async def test_invalid_json_structure(client: PlacesClient) -> None:
    """JSON value that is not an object."""
    with respx.mock:
        respx.post(PLACES_API_URL).mock(return_value=httpx.Response(200, json=["not", "a", "dict"]))
        with pytest.raises(PlacesAPIResponseError) as exc_info:
            await client.search_text("bad structure")
        assert "Response JSON is not a dictionary" in str(exc_info.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500, 502, 503, 504])
async def test_retry_on_temporary_errors(client: PlacesClient, status_code: int) -> None:
    """15, 16, 17, 18, 19. Retry on 429, 500, 502, 503, 504."""
    with respx.mock:
        route = respx.post(PLACES_API_URL).mock(
            side_effect=[
                httpx.Response(status_code, json={"error": "Temp error"}),
                httpx.Response(status_code, json={"error": "Temp error"}),
                httpx.Response(200, json={"places": [{"id": "123"}]}),
            ]
        )

        response = await client.search_text("plumbers")

        assert route.call_count == 3
        assert response["places"][0]["id"] == "123"


@pytest.mark.asyncio
async def test_retry_exhaustion(client: PlacesClient) -> None:
    """20. Retry exhaustion."""
    with respx.mock:
        route = respx.post(PLACES_API_URL).mock(
            return_value=httpx.Response(503, json={"error": "Service Unavailable"})
        )

        with pytest.raises(PlacesAPITemporaryError) as exc_info:
            await client.search_text("roofers")

        assert route.call_count == 3
        assert "temporarily unavailable" in str(exc_info.value)
        assert "3 attempts" in str(exc_info.value)
        assert isinstance(exc_info.value.__cause__, httpx.HTTPStatusError)
        assert API_KEY not in str(exc_info.value)


@pytest.mark.asyncio
async def test_no_retry_on_invalid_key(client: PlacesClient) -> None:
    """22, 23. No retry on 401/403."""
    for status_code in (401, 403):
        with respx.mock:
            route = respx.post(PLACES_API_URL).mock(
                return_value=httpx.Response(status_code, json={"error": "API Key Invalid"})
            )

            with pytest.raises(PlacesAPIKeyError) as exc_info:
                await client.search_text("builders")

            assert route.call_count == 1
            # Ensure API key is NOT leaked in the exception message
            assert API_KEY not in str(exc_info.value)


@pytest.mark.asyncio
async def test_no_retry_on_invalid_request(client: PlacesClient) -> None:
    """21. No retry on 400."""
    with respx.mock:
        route = respx.post(PLACES_API_URL).mock(
            return_value=httpx.Response(400, json={"error": "Invalid Argument"})
        )

        with pytest.raises(PlacesAPIInvalidRequestError):
            await client.search_text("cleaners")

        assert route.call_count == 1
