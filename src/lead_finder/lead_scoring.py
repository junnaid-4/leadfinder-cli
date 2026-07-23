"""Transparent lead priority scoring (Stage 4)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import LeadScoringConfig
    from .website_checker import WebsiteCheckResult

SCORING_VERSION = "v1"


class LeadPriority(StrEnum):
    VERY_HIGH = "very_high"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    VERY_LOW = "very_low"


@dataclass(frozen=True)
class ScoreComponent:
    rule: str
    points: int
    explanation: str


@dataclass(frozen=True)
class LeadScoreResult:
    business_id: int
    raw_score: int
    final_score: int
    priority: LeadPriority
    components: tuple[ScoreComponent, ...]
    scored_at: datetime


@dataclass(frozen=True)
class BusinessScoringInput:
    business_id: int
    place_id: str | None
    name: str | None
    phone: str | None
    address: str | None
    rating: float | None
    review_count: int | None
    business_status: str | None


def calculate_lead_score(
    business: BusinessScoringInput,
    latest_website_check: WebsiteCheckResult | None,
    config: LeadScoringConfig,
) -> LeadScoreResult:
    """Calculate an objective, bounded lead score."""
    components = []
    raw_score = 0

    weights = config.weights

    # Website check
    if not latest_website_check:
        components.append(
            ScoreComponent(
                rule="website_not_checked",
                points=0,
                explanation="Website not checked",
            )
        )
    else:
        status_val = latest_website_check.status.value

        if status_val == "no_website":
            components.append(ScoreComponent("no_website", weights.no_website, "No website"))
        elif status_val == "unreachable":
            components.append(
                ScoreComponent("unreachable", weights.unreachable, "Website unreachable")
            )
        elif status_val == "dns_error":
            components.append(ScoreComponent("dns_error", weights.dns_error, "DNS error"))
        elif status_val == "ssl_error":
            components.append(ScoreComponent("ssl_error", weights.ssl_error, "SSL error"))
        elif status_val == "redirect_loop":
            components.append(
                ScoreComponent("redirect_loop", weights.redirect_loop, "Redirect loop")
            )
        elif status_val == "timeout":
            components.append(ScoreComponent("timeout", weights.timeout, "Website timeout"))
        elif status_val == "http_error":
            http_status = latest_website_check.http_status or 0
            if 500 <= http_status <= 599:
                components.append(ScoreComponent("http_5xx", weights.http_5xx, "HTTP 5xx error"))
            elif 400 <= http_status <= 499:
                components.append(ScoreComponent("http_4xx", weights.http_4xx, "HTTP 4xx error"))
            else:
                components.append(
                    ScoreComponent("unknown_error", weights.unknown_error, "Unknown error")
                )
        elif status_val == "blocked":
            components.append(ScoreComponent("blocked", weights.blocked, "Website blocked"))
        elif status_val == "invalid_url":
            components.append(
                ScoreComponent("invalid_url", weights.invalid_url, "Invalid website URL")
            )
        elif status_val == "unknown_error":
            components.append(
                ScoreComponent("unknown_error", weights.unknown_error, "Unknown error")
            )
        elif status_val == "working":
            pass  # 0 points
        else:
            components.append(
                ScoreComponent("unknown_error", weights.unknown_error, "Unknown error")
            )

    # Phone number
    if business.phone:
        components.append(
            ScoreComponent("phone_present", weights.phone_present, "Phone number present")
        )
    else:
        components.append(
            ScoreComponent("phone_missing", weights.phone_missing, "Phone number missing")
        )

    # Rating
    if business.rating is not None:
        if business.rating >= 4.0:
            components.append(
                ScoreComponent("rating_high", weights.rating_high, "Rating at least 4.0")
            )
        elif 3.0 <= business.rating < 4.0:
            components.append(
                ScoreComponent(
                    "rating_medium", weights.rating_medium, "Rating from 3.0 to below 4.0"
                )
            )

    # Reviews
    if business.review_count is not None:
        if business.review_count >= 100:
            components.append(
                ScoreComponent("reviews_high", weights.reviews_high, "100 or more reviews")
            )
        elif 20 <= business.review_count < 100:
            components.append(
                ScoreComponent("reviews_medium", weights.reviews_medium, "20-99 reviews")
            )
        elif 5 <= business.review_count < 20:
            components.append(ScoreComponent("reviews_low", weights.reviews_low, "5-19 reviews"))

    # Data Quality
    if business.address:
        components.append(
            ScoreComponent("address_present", weights.address_present, "Address present")
        )

    if not business.name or not business.name.strip():
        components.append(
            ScoreComponent("missing_name", weights.missing_name, "Business name missing")
        )

    # Business state
    if business.business_status:
        normalized_status = business.business_status.upper()
        if normalized_status == "CLOSED_TEMPORARILY":
            components.append(
                ScoreComponent(
                    "temporarily_closed", weights.temporarily_closed, "Temporarily closed penalty"
                )
            )

    # Aggregate
    for c in components:
        raw_score += c.points

    # Override for permanently closed
    is_permanently_closed = False
    if business.business_status and business.business_status.upper() == "CLOSED_PERMANENTLY":
        is_permanently_closed = True

    if is_permanently_closed:
        raw_score = 0
        components.append(ScoreComponent("permanently_closed", 0, "Business is permanently closed"))
        final_score = 0
    else:
        final_score = max(0, min(100, raw_score))

    # Priority
    if final_score >= config.thresholds.very_high:
        priority = LeadPriority.VERY_HIGH
    elif final_score >= config.thresholds.high:
        priority = LeadPriority.HIGH
    elif final_score >= config.thresholds.medium:
        priority = LeadPriority.MEDIUM
    elif final_score >= config.thresholds.low:
        priority = LeadPriority.LOW
    else:
        priority = LeadPriority.VERY_LOW

    return LeadScoreResult(
        business_id=business.business_id,
        raw_score=raw_score,
        final_score=final_score,
        priority=priority,
        components=tuple(components),
        scored_at=datetime.now(UTC),
    )
