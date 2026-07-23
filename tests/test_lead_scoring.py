import json

import pytest

from lead_finder.config import LeadScoringConfig
from lead_finder.lead_scoring import (
    BusinessScoringInput,
    LeadPriority,
    calculate_lead_score,
)
from lead_finder.website_checker import WebsiteCheckResult, WebsiteStatus


@pytest.fixture
def base_config():
    return LeadScoringConfig()


@pytest.fixture
def base_business():
    return BusinessScoringInput(
        business_id=1,
        place_id="place123",
        name="Test Business",
        phone=None,
        address=None,
        rating=None,
        review_count=None,
        business_status="OPERATIONAL",
    )


def test_no_website_score(base_config, base_business):
    # Requirement 1: No website
    wc = WebsiteCheckResult(
        business_id=1,
        original_url="http://test.com",
        normalized_url="https://test.com",
        final_url=None,
        status=WebsiteStatus.NO_WEBSITE,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(base_business, wc, base_config)
    assert any(c.rule == "no_website" and c.points == 40 for c in result.components)


def test_working_website_score(base_config, base_business):
    # Requirement 2: Working website
    wc = WebsiteCheckResult(
        business_id=1,
        original_url="http://test.com",
        normalized_url="https://test.com",
        final_url="https://test.com",
        status=WebsiteStatus.WORKING,
        http_status=200,
        redirect_count=0,
        response_time_ms=100,
        content_type="text/html",
    )
    result = calculate_lead_score(base_business, wc, base_config)
    # Working website adds 0 points.
    assert not any(c.rule == "working" for c in result.components)


@pytest.mark.parametrize(
    "status,rule,expected_points",
    [
        (WebsiteStatus.UNREACHABLE, "unreachable", 30),  # Req 3
        (WebsiteStatus.DNS_ERROR, "dns_error", 30),  # Req 4
        (WebsiteStatus.SSL_ERROR, "ssl_error", 25),  # Req 5
        (WebsiteStatus.TIMEOUT, "timeout", 20),  # Req 6
        (WebsiteStatus.REDIRECT_LOOP, "redirect_loop", 25),  # Req 7
        (WebsiteStatus.BLOCKED, "blocked", 5),  # Req 10
        (WebsiteStatus.INVALID_URL, "invalid_url", 20),  # Req 11
        (WebsiteStatus.UNKNOWN_ERROR, "unknown_error", 10),  # Req 12
    ],
)
def test_website_error_scores(base_config, base_business, status, rule, expected_points):
    wc = WebsiteCheckResult(
        business_id=1,
        original_url="http://test.com",
        normalized_url="https://test.com",
        final_url=None,
        status=status,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(base_business, wc, base_config)
    assert any(c.rule == rule and c.points == expected_points for c in result.components)


def test_http_404_score(base_config, base_business):
    # Requirement 8
    wc = WebsiteCheckResult(
        business_id=1,
        original_url="http://test.com",
        normalized_url="https://test.com",
        final_url=None,
        status=WebsiteStatus.HTTP_ERROR,
        http_status=404,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(base_business, wc, base_config)
    assert any(c.rule == "http_4xx" and c.points == 15 for c in result.components)


def test_http_500_score(base_config, base_business):
    # Requirement 9
    wc = WebsiteCheckResult(
        business_id=1,
        original_url="http://test.com",
        normalized_url="https://test.com",
        final_url=None,
        status=WebsiteStatus.HTTP_ERROR,
        http_status=500,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(base_business, wc, base_config)
    assert any(c.rule == "http_5xx" and c.points == 25 for c in result.components)


def test_phone_present(base_config):
    # Requirement 13
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    assert any(c.rule == "phone_present" and c.points == 10 for c in result.components)


def test_phone_missing(base_config):
    # Requirement 14
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone=None,
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    assert any(c.rule == "phone_missing" and c.points == -10 for c in result.components)


@pytest.mark.parametrize(
    "rating,rule,expected_points",
    [
        (4.5, "rating_high", 10),  # Req 15
        (4.0, "rating_high", 10),
        (3.5, "rating_medium", 5),  # Req 16
        (3.0, "rating_medium", 5),
        (2.9, None, 0),  # Req 17 (Low rating = 0)
        (None, None, 0),  # Req 18 (Missing rating = 0)
    ],
)
def test_rating_scores(base_config, rating, rule, expected_points):
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=rating,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    if rule:
        assert any(c.rule == rule and c.points == expected_points for c in result.components)
    else:
        assert not any(c.rule.startswith("rating_") for c in result.components)


@pytest.mark.parametrize(
    "reviews,rule,expected_points",
    [
        (100, "reviews_high", 15),  # Req 19
        (150, "reviews_high", 15),
        (20, "reviews_medium", 10),  # Req 20
        (99, "reviews_medium", 10),
        (5, "reviews_low", 5),  # Req 21
        (19, "reviews_low", 5),
        (4, None, 0),  # Req 22 (Low review count)
        (None, None, 0),  # Req 22 (Missing review count)
    ],
)
def test_review_count_scores(base_config, reviews, rule, expected_points):
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=None,
        review_count=reviews,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    if rule:
        assert any(c.rule == rule and c.points == expected_points for c in result.components)
    else:
        assert not any(c.rule.startswith("reviews_") for c in result.components)


def test_address_present(base_config):
    # Requirement 23
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address="123 Main St",
        rating=None,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    assert any(c.rule == "address_present" and c.points == 5 for c in result.components)


def test_missing_business_name_penalty(base_config):
    # Requirement 24
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="",
        phone="123",
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    assert any(c.rule == "missing_name" and c.points == -20 for c in result.components)


def test_score_capped_at_100(base_config):
    # Requirement 25
    wc = WebsiteCheckResult(
        business_id=1,
        original_url="http://test.com",
        normalized_url="https://test.com",
        final_url=None,
        status=WebsiteStatus.NO_WEBSITE,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    # Give it many positive attributes to push raw score > 100
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="Perfect",
        phone="123",
        address="123 St",
        rating=5.0,
        review_count=5000,
        business_status=None,
    )
    result = calculate_lead_score(b, wc, base_config)
    # Points: no_website(40)+phone(10)+rating(10)+reviews(15)+address(5) = 80
    assert result.raw_score > 70

    # Adjust config to guarantee raw_score > 100.
    config = LeadScoringConfig()
    config.weights.no_website = 100
    result = calculate_lead_score(b, wc, config)

    assert result.raw_score == 140
    assert result.final_score == 100


def test_score_floored_at_0(base_config):
    # Requirement 26
    # Missing name (-20), missing phone (-10), working website (0),
    # no rating (0), no address (0) = -30
    wc = WebsiteCheckResult(
        business_id=1,
        original_url=None,
        normalized_url=None,
        final_url=None,
        status=WebsiteStatus.WORKING,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="",
        phone=None,
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, wc, base_config)
    assert result.raw_score == -30
    assert result.final_score == 0


@pytest.mark.parametrize(
    "score,expected_priority",
    [
        (0, LeadPriority.VERY_LOW),  # Requirement 27: exact boundaries
        (19, LeadPriority.VERY_LOW),
        (20, LeadPriority.LOW),
        (39, LeadPriority.LOW),
        (40, LeadPriority.MEDIUM),
        (59, LeadPriority.MEDIUM),
        (60, LeadPriority.HIGH),
        (79, LeadPriority.HIGH),
        (80, LeadPriority.VERY_HIGH),
        (100, LeadPriority.VERY_HIGH),
    ],
)
def test_category_thresholds(score, expected_priority):
    # Requirement 27 & 4 boundaries
    # We will manipulate the config weights to output exact scores.
    config = LeadScoringConfig()
    config.weights.no_website = score
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="Name",
        phone=None,
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    # Provide a phone number to avoid the phone_missing penalty.
    # so let's set phone to none, and compensate
    config.weights.phone_missing = 0
    config.weights.phone_present = 0
    wc = WebsiteCheckResult(
        business_id=1,
        original_url=None,
        normalized_url=None,
        final_url=None,
        status=WebsiteStatus.NO_WEBSITE,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(b, wc, config)
    assert result.final_score == score
    assert result.priority == expected_priority


def test_configurable_weights_change_result():
    # Requirement 28
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    config = LeadScoringConfig()
    config.weights.phone_present = 50
    result1 = calculate_lead_score(b, None, config)

    config.weights.phone_present = 100
    result2 = calculate_lead_score(b, None, config)

    assert result1.final_score == 50
    assert result2.final_score == 100


def test_invalid_threshold_configuration_rejected():
    # Requirement 29
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        LeadScoringConfig(thresholds={"very_high": 50, "high": 60, "medium": 40, "low": 20})


def test_missing_website_check_neutral(base_config):
    # Requirement 31
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=None,
        review_count=None,
        business_status=None,
    )
    result = calculate_lead_score(b, None, base_config)
    website_comp = next(c for c in result.components if c.rule == "website_not_checked")
    assert website_comp.points == 0


def test_score_breakdown_contains_applied_rules(base_config):
    # Requirement 32
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address="123",
        rating=5.0,
        review_count=100,
        business_status=None,
    )
    wc = WebsiteCheckResult(
        business_id=1,
        original_url=None,
        normalized_url=None,
        final_url=None,
        status=WebsiteStatus.NO_WEBSITE,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(b, wc, base_config)

    rules_applied = [c.rule for c in result.components]
    assert "no_website" in rules_applied
    assert "phone_present" in rules_applied
    assert "rating_high" in rules_applied
    assert "reviews_high" in rules_applied
    assert "address_present" in rules_applied

    # Check serialization logic (similar to DB persistence)
    components_list = [
        {"rule": c.rule, "points": c.points, "explanation": c.explanation}
        for c in result.components
    ]
    json_data = json.dumps(components_list)
    parsed = json.loads(json_data)
    assert len(parsed) == 5
    assert parsed[0]["rule"] == "no_website"


def test_permanently_closed_business(base_config):
    # Requirement 40: Permanently closed
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=5.0,
        review_count=100,
        business_status="CLOSED_PERMANENTLY",
    )
    wc = WebsiteCheckResult(
        business_id=1,
        original_url=None,
        normalized_url=None,
        final_url=None,
        status=WebsiteStatus.NO_WEBSITE,
        http_status=None,
        redirect_count=0,
        response_time_ms=None,
        content_type=None,
    )
    result = calculate_lead_score(b, wc, base_config)
    assert result.final_score == 0
    assert result.raw_score == 0
    assert any(c.rule == "permanently_closed" for c in result.components)


def test_temporarily_closed_business(base_config):
    # Requirement 40 continued
    b = BusinessScoringInput(
        business_id=1,
        place_id="p1",
        name="N",
        phone="123",
        address=None,
        rating=None,
        review_count=None,
        business_status="CLOSED_TEMPORARILY",
    )
    result = calculate_lead_score(b, None, base_config)
    assert any(c.rule == "temporarily_closed" and c.points == -20 for c in result.components)
