"""Core domain models and enumerations."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class LeadCategory(StrEnum):
    """Business lead classification values."""

    NO_WEBSITE = "NO_WEBSITE"
    BROKEN_WEBSITE = "BROKEN_WEBSITE"
    IMPORTANT_PAGE_BROKEN = "IMPORTANT_PAGE_BROKEN"
    WORKING_WEBSITE = "WORKING_WEBSITE"
    MANUAL_REVIEW = "MANUAL_REVIEW"
    UNCHECKED = "UNCHECKED"


class PriorityLevel(StrEnum):
    """Lead priority grouping based on score."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class SearchRunStatus(StrEnum):
    """Lifecycle status for a search run."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class BusinessRecord(BaseModel):
    """Business discovered via Google Places."""

    place_id: str
    business_name: str
    category: str | None = None
    additional_categories: list[str] = Field(default_factory=list)
    address: str | None = None
    city: str | None = None
    postal_code: str | None = None
    phone: str | None = None
    international_phone: str | None = None
    google_maps_url: str | None = None
    website_url: str | None = None
    rating: float | None = None
    review_count: int | None = None
    business_status: str | None = None
    opening_hours_status: str | None = None
    search_query: str | None = None
    search_location: str | None = None
    collected_at: datetime | None = None
    lead_category: LeadCategory = LeadCategory.UNCHECKED
    manual_review_required: bool = False


class WebsiteCheckRecord(BaseModel):
    """Result of checking a business website."""

    place_id: str
    original_url: str | None = None
    final_url: str | None = None
    initial_status_code: int | None = None
    final_status_code: int | None = None
    redirect_count: int = 0
    response_time_ms: int | None = None
    content_type: str | None = None
    check_attempts: int = 0
    issue_type: str | None = None
    issue_description: str | None = None
    important_broken_page: str | None = None
    checked_at: datetime | None = None
    lead_category: LeadCategory = LeadCategory.UNCHECKED


class SearchRunRecord(BaseModel):
    """Metadata for a pipeline execution."""

    id: int | None = None
    config_name: str
    search_location: str
    status: SearchRunStatus = SearchRunStatus.PENDING
    started_at: datetime | None = None
    finished_at: datetime | None = None
    businesses_discovered: int = 0
    duplicates_removed: int = 0
    api_requests_used: int = 0
    website_checks_completed: int = 0
    dry_run: bool = False


class CachedApiResponse(BaseModel):
    """Cached Google Places API response."""

    cache_key: str
    endpoint: str
    response_body: str
    created_at: datetime
    expires_at: datetime
