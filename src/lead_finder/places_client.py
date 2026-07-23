"""Client for Google Places API (New)."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

import httpx
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from lead_finder.logging_config import get_logger

logger = get_logger("places_client")

PLACES_API_URL = "https://places.googleapis.com/v1/places:searchText"

FIELD_MASK = (
    "places.id,places.displayName,places.primaryType,places.types,"
    "places.formattedAddress,places.nationalPhoneNumber,"
    "places.internationalPhoneNumber,places.googleMapsUri,"
    "places.websiteUri,places.rating,places.userRatingCount,"
    "places.businessStatus,places.regularOpeningHours,"
    "places.currentOpeningHours,nextPageToken"
)


class PlacesAPIError(Exception):
    """Base class for Places API exceptions."""


class PlacesAPIKeyError(PlacesAPIError):
    """Raised when the API key is missing or invalid (401/403)."""


class PlacesAPIQuotaError(PlacesAPIError):
    """Raised when the API quota is exceeded (429 with hard limit)."""


class PlacesAPIInvalidRequestError(PlacesAPIError):
    """Raised when the request is invalid (400)."""


class PlacesAPITemporaryError(PlacesAPIError):
    """Raised when temporary errors exhaust the retry limit."""


class PlacesAPIResponseError(PlacesAPIError):
    """Raised when Google Places returns malformed or structurally invalid data."""


def build_places_cache_key(
    *,
    query: str,
    location: str,
    field_mask: str,
    page_token: str | None,
    request_parameters: Mapping[str, object] | None = None,
) -> str:
    """Build a deterministic cache key for Places API requests."""
    parts = {
        "query": query,
        "location": location,
        "field_mask": field_mask,
        "page_token": page_token,
        "request_parameters": dict(request_parameters) if request_parameters else {},
    }
    canonical_json = json.dumps(parts, sort_keys=True)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def _is_temporary_error(exception: BaseException) -> bool:
    """Check if the exception is temporary and should be retried."""
    if isinstance(
        exception,
        (
            httpx.TimeoutException,
            httpx.ConnectError,
            httpx.ReadError,
            httpx.WriteError,
        ),
    ):
        return True
    if isinstance(exception, httpx.HTTPStatusError):
        # 429 can be rate limit (temporary) or quota (hard limit).
        # We retry 429 briefly. If it persists, it will eventually bubble up.
        return exception.response.status_code in {429, 500, 502, 503, 504}
    return False


class PlacesClient:
    """Client for interacting with Google Places API."""

    def __init__(self, api_key: str) -> None:
        if not api_key or api_key.strip() == "":
            raise ValueError("API key must be provided.")
        self._api_key = api_key
        self._client = httpx.AsyncClient(timeout=10.0)

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        await self._client.aclose()

    @retry(
        retry=retry_if_exception(_is_temporary_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        reraise=True,
    )
    async def _execute_request_with_retry(self, payload: dict[str, Any]) -> httpx.Response:
        """Execute request with backoff for temporary errors."""
        headers = {
            "X-Goog-Api-Key": self._api_key,
            "X-Goog-FieldMask": FIELD_MASK,
            "Content-Type": "application/json",
        }

        try:
            response = await self._client.post(
                PLACES_API_URL,
                json=payload,
                headers=headers,
            )
            response.raise_for_status()
            return response
        except httpx.HTTPStatusError as e:
            status = e.response.status_code
            if status == 400:
                raise PlacesAPIInvalidRequestError(f"Invalid request: {e.response.text}") from e
            if status in (401, 403):
                raise PlacesAPIKeyError("API Key or permission error") from e
            if _is_temporary_error(e):
                logger.warning("Temporary API error (HTTP %d). Retrying...", status)
                raise e
            raise PlacesAPIError(f"API request failed with HTTP {status}") from e
        except Exception as e:
            if _is_temporary_error(e):
                logger.warning("Network error (%s). Retrying...", type(e).__name__)
                raise e
            if isinstance(e, PlacesAPIError):
                raise
            raise PlacesAPIError("Unexpected request error") from e

    async def search_text(self, text_query: str, page_token: str | None = None) -> dict[str, Any]:
        """
        Search for places via text query.
        Returns the parsed JSON response.
        """
        payload: dict[str, Any] = {
            "textQuery": text_query,
        }
        if page_token:
            payload["pageToken"] = page_token

        try:
            response = await self._execute_request_with_retry(payload)
        except PlacesAPIError:
            raise
        except Exception as e:
            if _is_temporary_error(e):
                msg = "Google Places temporarily unavailable after 3 attempts"
                raise PlacesAPITemporaryError(msg) from e
            raise

        try:
            result = response.json()
        except Exception as e:
            raise PlacesAPIResponseError("Malformed JSON response") from e

        if not isinstance(result, dict):
            raise PlacesAPIResponseError("Response JSON is not a dictionary")
        return result
