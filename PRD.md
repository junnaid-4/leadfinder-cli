# Product Requirements Document

## Local Business Website Lead Finder

**Version:** 1.0
**Project type:** Internal lead-generation tool
**Initial market:** Manchester, United Kingdom
**Initial niche:** Configurable, starting with one niche such as electricians
**Primary user:** Flozen AI internal sales team
**Development approach:** Python command-line application
**Status:** MVP specification

---

# 1. Product Summary

The Local Business Website Lead Finder is an internal Python tool that discovers local businesses through the Google Places API and identifies businesses that:

1. Do not have a website listed on Google Maps.
2. Have a website that is clearly unavailable or technically broken.
3. Optionally have an important page, such as Contact or Services, that returns a major error.

The tool will collect business information, test listed websites, classify leads and export the results into a CSV file for manual review and outreach.

The first version will focus only on objective and reliably detectable technical issues.

The tool will not attempt to judge whether a website is visually outdated, commercially weak or poorly designed.

---

# 2. Problem Statement

Flozen AI wants to sell affordable websites to small and medium-sized local businesses in the United Kingdom.

The proposed website price range is approximately:

* PKR 100,000 to PKR 150,000
* Or the equivalent agreed amount in GBP

Manually searching Google Maps for businesses, opening every profile, checking whether a website exists and testing each website takes too much time.

A semi-automated tool can reduce this work by:

* Finding businesses in a selected niche and location.
* Extracting their available contact information.
* Detecting businesses without websites.
* Detecting websites with major technical failures.
* Producing an organized lead list.
* Allowing the sales team to focus on high-potential leads.

---

# 3. Product Goal

Create a reliable internal tool that can produce a reviewed list of local businesses that may need a new website.

The tool should help answer:

* Which businesses have no website?
* Which businesses have a website that cannot be reached?
* Which websites return serious errors?
* Which businesses have enough credibility or activity to be worth contacting?
* What specific technical issue can be mentioned during outreach?

---

# 4. Non-Goals

The first version must not include:

* AI-based website design scoring.
* Subjective visual-quality analysis.
* Automatic claims that a website looks outdated.
* Full website crawling.
* Automatic email or WhatsApp outreach.
* CRM functionality.
* Login or user accounts.
* Public SaaS functionality.
* Payment processing.
* Lead purchasing.
* Social-media scraping.
* Google Maps HTML scraping.
* Browser automation for Google Maps.
* Proxy rotation.
* CAPTCHA bypassing.
* Automatic website generation.
* Automatic proposal generation.
* Automated contact-form submission.
* Lighthouse or PageSpeed integration.
* Screenshot-based AI analysis.
* SEO audits.
* Accessibility audits.
* Competitor comparisons.
* Revenue estimation.

These may be added later only after the lead-generation and sales process has been validated.

---

# 5. Target Users

## Primary user

Flozen AI team members responsible for:

* Market research.
* Lead generation.
* Sales outreach.
* Website-service sales.
* Niche validation.

## User skill level

The user may have basic Python and terminal knowledge but should not need to modify the source code for normal use.

---

# 6. Core Use Case

A team member wants to find electricians in Manchester that either:

* Have no website.
* Have an unreachable website.
* Have a website returning a serious server or page error.

The user runs a command such as:

```bash
python main.py \
  --query "electricians" \
  --location "Manchester, UK" \
  --max-results 200
```

The tool then:

1. Searches Google Places.
2. Collects matching businesses.
3. Deduplicates results using Google Place ID.
4. Checks whether each business has a website.
5. Tests websites that are present.
6. Classifies each business.
7. Exports the results into CSV files.

---

# 7. Lead Categories

## Group A: No Website

A business is classified as `NO_WEBSITE` when:

* Google Places returns no website field.
* The website field is null.
* The website field is empty.
* The website value is clearly invalid after normalization.

Example:

```text
Business: Manchester Power Solutions
Website: None
Lead category: NO_WEBSITE
Reason: No website listed on Google Maps
```

---

## Group B: Broken Website

A business is classified as `BROKEN_WEBSITE` only when the system detects a clear technical failure.

Accepted broken conditions include:

* DNS resolution failure.
* Connection failure.
* Repeated connection timeout.
* Redirect loop.
* Homepage returns HTTP 404.
* Homepage returns HTTP 410.
* Homepage returns HTTP 500–599.
* Invalid URL that cannot be corrected safely.
* Empty or unusable response after repeated attempts.
* Obvious suspended-hosting page.
* Obvious expired-domain placeholder.
* Obvious domain-for-sale page.

A website must not be marked broken merely because it returns:

* HTTP 301.
* HTTP 302.
* HTTP 307.
* HTTP 308.
* HTTP 401.
* HTTP 403.
* HTTP 429.
* Slow response.
* HTTP instead of HTTPS.
* An SSL warning caused only by the automated client.
* A bot-protection page.
* An unusual content-management system.
* Basic HTML.
* An unattractive design.

These cases should receive a separate status for manual review.

---

## Group C: Working Website

A website is classified as `WORKING_WEBSITE` when:

* The final page loads successfully.
* The final response is an acceptable HTML response.
* The website is not identified as an error, placeholder or suspended page.

These businesses should remain in the complete results file but should not appear in the main lead file unless an optional important-page check finds a clear error.

---

## Manual Review

A business should be classified as `MANUAL_REVIEW` when the tool cannot confidently decide.

Examples:

* HTTP 403.
* HTTP 429.
* CAPTCHA.
* Cloudflare challenge.
* Bot-blocking page.
* Intermittent timeout.
* SSL handshake error.
* Login page.
* Unexpected non-HTML content.
* Website only works in a browser.
* Domain redirects to a social-media page.
* Domain redirects to another unrelated company.
* Response contains conflicting indicators.

False positives are more damaging than missed leads. When uncertain, use `MANUAL_REVIEW`.

---

# 8. Optional Phase 1.5 Feature

The system may check a maximum of five important internal pages.

Relevant page keywords:

* contact
* contact-us
* services
* service
* quote
* request-a-quote
* booking
* book
* about
* about-us

The tool should:

1. Download the homepage HTML.
2. Extract same-domain internal links.
3. Select no more than five relevant links.
4. Send lightweight HTTP requests.
5. Flag only major errors.

An important page may be marked broken when it returns:

* 404.
* 410.
* 500–599.
* Redirect loop.
* Repeated timeout.

This feature must be configurable and disabled by default in the earliest prototype.

Example:

```text
Lead category: IMPORTANT_PAGE_BROKEN
Reason: Contact page returned HTTP 404
Broken URL: https://example.co.uk/contact
```

---

# 9. Business Data to Collect

For each business, collect the following fields when available:

* Google Place ID.
* Business name.
* Primary business category.
* Additional categories.
* Full address.
* Locality or city.
* Postal code.
* Phone number.
* International phone number.
* Google Maps URL.
* Website URL.
* Rating.
* Review count.
* Business status.
* Opening-hours status.
* Search query used.
* Search location used.
* Date collected.
* Date website checked.

Only request fields needed by the product.

Do not request unnecessary Google Places fields.

---

# 10. Output Fields

The main CSV should contain:

```text
place_id
business_name
category
address
city
postal_code
phone
international_phone
google_maps_url
website_url
rating
review_count
business_status
lead_category
issue_type
issue_description
initial_status_code
final_status_code
final_url
redirect_count
response_time_ms
content_type
check_attempts
important_broken_page
search_query
search_location
collected_at
checked_at
manual_review_required
```

---

# 11. Output Files

The application should generate:

## Complete results

```text
output/all_businesses.csv
```

Contains all discovered businesses.

## Qualified leads

```text
output/qualified_leads.csv
```

Contains:

* `NO_WEBSITE`
* `BROKEN_WEBSITE`
* `IMPORTANT_PAGE_BROKEN`

## Manual review

```text
output/manual_review.csv
```

Contains uncertain cases.

## Working websites

```text
output/working_websites.csv
```

Contains businesses whose websites passed the checks.

## Execution log

```text
logs/run_YYYYMMDD_HHMMSS.log
```

---

# 12. Lead Prioritization

The MVP may use a simple priority score.

The score must be transparent and deterministic.

Suggested scoring:

```text
No website                                  +50
Homepage DNS failure                        +50
Homepage 500–599                            +50
Homepage 404 or 410                         +45
Expired or suspended hosting page           +45
Repeated connection timeout                 +40
Redirect loop                               +40
Important Contact page broken               +30
Important Services page broken              +25
Rating of 4.0 or higher                     +10
At least 20 reviews                         +10
At least 50 reviews                         +10
At least 100 reviews                        +10
Public phone number available               +10
Business marked operational                 +5
```

Suggested priority groups:

```text
80 or more: HIGH
55–79: MEDIUM
Below 55: LOW
```

The system should never treat this score as proof that the business will buy.

It is only a sorting mechanism.

---

# 13. Google Places Search Strategy

The tool must not attempt to find every business in Manchester through one broad query.

Use niche-based searches.

Examples:

```text
electricians in Manchester
emergency electricians in Manchester
commercial electricians in Manchester
domestic electricians in Manchester
electrical contractors in Manchester
```

The tool should allow multiple search queries in a configuration file.

Example configuration:

```yaml
location: "Manchester, UK"

queries:
  - "electricians"
  - "emergency electricians"
  - "electrical contractors"

max_results_per_query: 100
```

The system must deduplicate businesses across all searches using Google Place ID.

---

# 14. Geographic Scope

The tool should support configurable geographic scope.

Initial options:

* Manchester city.
* Greater Manchester.
* Individual neighbourhoods or towns.

Examples:

* Manchester.
* Salford.
* Stockport.
* Trafford.
* Didsbury.
* Chorlton.
* Oldham.
* Rochdale.
* Bolton.
* Bury.

The first test should use one defined location rather than the whole Greater Manchester area.

---

# 15. Niche-Selection Guidelines

Before running a large search, score each niche using:

* Value of one new customer.
* Dependence on local Google search.
* Owner contactability.
* Number of existing competitors.
* Average business maturity.
* Likelihood of having an outdated or missing website.
* Ability to pay.
* Need for trust and credibility.
* Repeatability of a website template.
* Ease of demonstrating return on investment.

Promising initial niches may include:

* Electricians.
* Plumbers.
* Roofers.
* Heating engineers.
* Boiler installers.
* Builders.
* Landscaping businesses.
* Cleaning companies.
* Pest-control companies.
* Locksmiths.
* Garage-door installers.
* Small dental clinics.
* Physiotherapy clinics.

Do not select a niche only because many businesses lack websites.

A viable niche must also have:

* Enough revenue.
* Reachable decision-makers.
* A reason to value new customer enquiries.
* A clear website sales pitch.

---

# 16. Google API Cost-Control Requirements

The application must include safeguards against unnecessary API usage.

Required controls:

* Store every returned Place ID.
* Avoid querying the same Place ID repeatedly.
* Cache Google Places responses.
* Allow a maximum request count per run.
* Allow a maximum business-result count.
* Display an estimated request count before execution.
* Ask for explicit command-line confirmation before large runs.
* Use a minimal field mask.
* Support a dry-run mode.
* Stop cleanly when a configured limit is reached.
* Log every API request.
* Never retry billing-related or invalid-request errors indefinitely.
* Use exponential backoff only for temporary failures.
* Provide instructions for setting Google Cloud quotas.
* Never hardcode the API key.
* Read the API key from an environment variable.

Required environment variable:

```bash
GOOGLE_MAPS_API_KEY
```

The application must fail safely when this variable is missing.

---

# 17. Website-Checking Rules

## URL normalization

The system should:

1. Trim whitespace.
2. Add a scheme when missing.
3. Prefer the URL returned by Google.
4. Follow redirects.
5. Record the final destination.
6. Avoid modifying paths unnecessarily.
7. Avoid guessing alternative domains.

When no scheme exists:

1. Try `https://`.
2. If the HTTPS connection clearly fails, optionally try `http://`.
3. Record which version succeeded.

---

## HTTP client

Use:

* `httpx`
* Async mode
* Connection pooling
* Configurable concurrency
* Redirect following
* Timeouts
* Controlled retries
* Browser-like user agent

Suggested defaults:

```text
Connection timeout: 5 seconds
Read timeout: 10 seconds
Total attempts: 2
Maximum redirects: 10
Concurrency: 10
```

Do not use extremely high concurrency.

The tool must be respectful and lightweight.

---

## Status-code rules

### Normally working

```text
200–299
301
302
303
307
308
```

Redirects should be followed before classification.

### Broken

```text
404
410
500–599
```

### Manual review

```text
400
401
403
405
406
408
409
423
425
429
451
```

Other unusual codes should default to manual review.

---

## Content checks

A `200` response alone does not guarantee a working business website.

The tool may inspect page text for strong error indicators.

Examples:

```text
domain expired
domain for sale
account suspended
website suspended
hosting account suspended
site unavailable
this domain has expired
coming soon
default web site page
future home of
parked free
buy this domain
```

The phrase check must be conservative.

Do not classify a website as broken based on one vague phrase such as:

```text
coming soon
```

Use combinations of:

* Page title.
* Visible text.
* Domain-hosting indicators.
* Response structure.
* Redirect destination.

When uncertain, classify as `MANUAL_REVIEW`.

---

# 18. Robots, Ethics and Responsible Use

The tool should:

* Use official Google Places APIs.
* Avoid scraping Google Maps HTML.
* Avoid bypassing CAPTCHAs.
* Avoid bypassing bot protection.
* Avoid excessive crawling.
* Make only limited requests to business websites.
* Identify itself through a reasonable user-agent.
* Respect configured rate limits.
* Avoid collecting personal data not necessary for business outreach.
* Use publicly available business information.
* Keep a record of the source of each lead.
* Allow removal of businesses from the outreach list.
* Avoid misleading claims during outreach.

The tool should not claim:

* That a business is losing a specific amount of money.
* That a website is hacked.
* That the website violates laws.
* That Google is penalizing the business.
* That an issue definitely causes lost revenue.

Only state directly observed facts.

Good statement:

```text
Your contact page returned a 404 error when we checked it.
```

Bad statement:

```text
Your broken website is costing you thousands every month.
```

---

# 19. Manual Review Requirement

No business should be contacted solely based on automated classification.

Before outreach, a team member must:

1. Open the Google Maps profile.
2. Confirm the business is active.
3. Open the website manually.
4. Confirm the detected issue.
5. Check that the business is relevant.
6. Confirm that contact information is public.
7. Remove duplicates.
8. Select a personalized outreach angle.

The final lead list should contain only human-verified leads.

---

# 20. Functional Requirements

## FR-01: Configuration

The user must be able to configure:

* Location.
* Search queries.
* Maximum results.
* Output folder.
* Website-check concurrency.
* Timeout.
* Retry count.
* Important-page checking.
* Minimum review count.
* Minimum rating.
* API request limit.

---

## FR-02: Google Places collection

The system must:

* Search businesses by text query.
* Handle pagination.
* Respect API limits.
* Use field masks.
* Collect the required fields.
* Cache responses.
* Deduplicate by Place ID.

---

## FR-03: Website classification

The system must assign one of:

```text
NO_WEBSITE
BROKEN_WEBSITE
IMPORTANT_PAGE_BROKEN
WORKING_WEBSITE
MANUAL_REVIEW
UNCHECKED
```

---

## FR-04: Website testing

The system must record:

* Original URL.
* Final URL.
* Initial status.
* Final status.
* Redirect count.
* Response time.
* Content type.
* Error type.
* Number of attempts.
* Check timestamp.

---

## FR-05: CSV export

The system must:

* Export valid UTF-8 CSV.
* Preserve all required fields.
* Create separate category files.
* Sort qualified leads by priority score.
* Avoid duplicate Place IDs.
* Avoid duplicate normalized website domains where appropriate.

---

## FR-06: Logging

The system must log:

* Start and end time.
* Configuration.
* API calls.
* Businesses returned.
* Duplicate count.
* Website checks attempted.
* Classification totals.
* Failed requests.
* Retry attempts.
* Output paths.
* Fatal errors.

The API key must never appear in logs.

---

## FR-07: Resume and caching

The tool should support resuming interrupted runs.

It should not repeat:

* Completed Place lookups.
* Completed website checks that are still fresh.

Suggested cache duration:

```text
Places search results: 30 days
Website status checks: 7 days
```

---

## FR-08: Summary report

At the end of each run, print:

```text
Businesses discovered
Duplicates removed
No-website leads
Broken-website leads
Important-page failures
Manual-review cases
Working websites
API requests used
Website checks completed
Output file locations
```

---

# 21. Non-Functional Requirements

## Reliability

* One failed website must not stop the run.
* One failed Places query must not corrupt existing output.
* Partial results must be preserved.
* Errors must be understandable.

## Performance

The MVP should process approximately 200 websites within a reasonable local execution time using controlled concurrency.

The goal is reliability, not maximum speed.

## Maintainability

The code should:

* Use type hints.
* Use clear function names.
* Separate responsibilities into modules.
* Include docstrings where useful.
* Avoid giant files.
* Avoid unnecessary abstractions.
* Avoid premature microservices.
* Avoid a web framework in the MVP.

## Security

* API key stored in `.env`.
* `.env` included in `.gitignore`.
* No secrets committed.
* URLs treated as untrusted input.
* Prevent access to local or private network addresses.
* Limit response download size.
* Avoid executing downloaded scripts.
* Do not run arbitrary website code.

---

# 22. SSRF and Network-Safety Requirements

Because the tool requests external URLs, it must protect against Server-Side Request Forgery-style risks.

Reject URLs resolving to:

* `localhost`
* `127.0.0.0/8`
* Private IPv4 ranges
* Link-local addresses
* Multicast addresses
* Private IPv6 ranges
* Cloud metadata addresses
* Local network hostnames

Do not request:

```text
file://
ftp://
gopher://
data:
javascript:
```

Only allow:

```text
http://
https://
```

Limit maximum response size.

Suggested maximum:

```text
5 MB
```

---

# 23. Recommended Technology Stack

## Language

```text
Python 3.12+
```

## Core packages

```text
httpx
pydantic
pydantic-settings
python-dotenv
beautifulsoup4
tenacity
typer
rich
pandas
PyYAML
```

## Testing

```text
pytest
pytest-asyncio
respx
```

## Code quality

```text
ruff
mypy
```

## Storage

For the first version:

```text
SQLite
```

SQLite should store:

* Places.
* Search runs.
* Website checks.
* Cached results.

CSV remains the user-facing export format.

---

# 24. Recommended Project Structure

```text
local-business-lead-finder/
│
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── config.example.yaml
│
├── src/
│   └── lead_finder/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── database.py
│       ├── places_client.py
│       ├── website_checker.py
│       ├── url_utils.py
│       ├── page_classifier.py
│       ├── important_pages.py
│       ├── lead_scoring.py
│       ├── exporter.py
│       └── logging_config.py
│
├── tests/
│   ├── test_url_utils.py
│   ├── test_page_classifier.py
│   ├── test_lead_scoring.py
│   ├── test_website_checker.py
│   └── test_exporter.py
│
├── data/
├── output/
└── logs/
```

---

# 25. Suggested CLI Commands

## Validate configuration

```bash
python -m lead_finder.cli validate-config --config config.yaml
```

## Estimate run

```bash
python -m lead_finder.cli estimate --config config.yaml
```

## Collect places

```bash
python -m lead_finder.cli collect --config config.yaml
```

## Check websites

```bash
python -m lead_finder.cli check-websites --config config.yaml
```

## Export results

```bash
python -m lead_finder.cli export --config config.yaml
```

## Complete pipeline

```bash
python -m lead_finder.cli run --config config.yaml
```

## Dry run

```bash
python -m lead_finder.cli run --config config.yaml --dry-run
```

---

# 26. Example Configuration

```yaml
project:
  name: "Manchester Electrician Leads"

search:
  location: "Manchester, UK"
  queries:
    - "electricians"
    - "emergency electricians"
    - "electrical contractors"
  max_results_per_query: 50
  max_total_results: 150
  max_api_requests: 100

filters:
  operational_only: true
  minimum_rating: 0
  minimum_review_count: 0

website_check:
  enabled: true
  concurrency: 10
  connect_timeout_seconds: 5
  read_timeout_seconds: 10
  retries: 1
  follow_redirects: true
  max_redirects: 10
  max_response_size_mb: 5
  important_pages_enabled: false
  max_important_pages: 5

cache:
  places_ttl_days: 30
  website_check_ttl_days: 7

output:
  directory: "output"
  include_working_websites: true
```

---

# 27. Testing Requirements

The project must include unit tests for:

## URL normalization

Test:

* Missing scheme.
* HTTPS URL.
* HTTP URL.
* Trailing spaces.
* Invalid scheme.
* Localhost rejection.
* Private IP rejection.
* IPv6 private-address rejection.

## Status classification

Test:

* 200.
* 301 followed by 200.
* 404.
* 410.
* 500.
* 503.
* 403.
* 429.
* Redirect loop.
* Timeout.
* DNS error.

## Content classification

Test pages containing:

* Expired domain.
* Suspended hosting.
* Domain for sale.
* Normal business content.
* Vague “coming soon” message.
* Cloudflare challenge.

## Deduplication

Test:

* Duplicate Place ID.
* Same domain with different URL forms.
* Same business across multiple search queries.

## Export

Test:

* Correct headers.
* Correct categories.
* UTF-8 business names.
* Empty optional fields.
* No duplicate rows.

External APIs must be mocked during automated tests.

Tests must not call the live Google Places API.

---

# 28. Acceptance Criteria

The MVP is accepted when:

1. The user can provide a niche and location through configuration.
2. The tool retrieves businesses through the official Places API.
3. Businesses are deduplicated using Place ID.
4. Businesses without websites are correctly classified.
5. Listed websites are checked asynchronously.
6. Major homepage failures are classified correctly.
7. Uncertain cases are sent to manual review.
8. Results are exported to separate CSV files.
9. API usage is limited by configuration.
10. Results can be resumed from cache.
11. The API key is never committed or logged.
12. Tests cover core classification logic.
13. The README explains setup and usage.
14. A trial run of no more than 20 businesses succeeds.
15. No subjective website-design scoring exists in the MVP.

---

# 29. Development Phases

## Phase 0: Setup

Deliver:

* Project structure.
* Dependency management.
* Environment configuration.
* Logging.
* Basic CLI.
* SQLite setup.

## Phase 1: Google Places collection

Deliver:

* Places API integration.
* Field-mask configuration.
* Pagination.
* Deduplication.
* Caching.
* CSV export of collected businesses.

## Phase 2: Website checks

Deliver:

* URL normalization.
* Network-safety checks.
* Async HTTP checks.
* Redirect handling.
* Status classification.
* Retry handling.
* Response-time collection.

## Phase 3: Lead classification

Deliver:

* No-website classification.
* Broken-website classification.
* Manual-review classification.
* Conservative placeholder-page detection.
* Priority scoring.

## Phase 4: Export and reporting

Deliver:

* Separate CSV files.
* Run summary.
* Sorted qualified leads.
* Logs.
* Resume support.

## Phase 5: Optional important-page checks

Deliver only after the core pipeline is stable:

* Internal-link extraction.
* Relevant-page selection.
* Maximum five page checks.
* Broken important-page classification.

---

# 30. Initial Validation Plan

Run the tool in stages.

## Test 1

```text
Niche: Electricians
Location: Manchester
Maximum businesses: 20
```

Manually verify every result.

Record:

* Correct no-website classifications.
* Correct broken classifications.
* False positives.
* False negatives.
* API requests consumed.
* Average processing time.

## Test 2

Increase to:

```text
Maximum businesses: 50
```

Contact no businesses until the results are manually checked.

## Test 3

Generate approximately:

```text
100 verified leads
```

Begin outreach and record:

* Contact attempts.
* Replies.
* Positive replies.
* Meetings.
* Quotes sent.
* Deals closed.
* Most responsive lead category.

Only after this validation should the system be expanded.

---

# 31. Success Metrics

## Product metrics

* Percentage of businesses classified without errors.
* False-positive rate.
* Duplicate rate.
* API requests per unique business.
* Website checks completed successfully.
* Manual-review percentage.
* Cost per qualified lead.

## Sales metrics

* Verified leads generated.
* Contact rate.
* Reply rate.
* Positive reply rate.
* Meeting-booking rate.
* Proposal rate.
* Close rate.
* Revenue per niche.
* Revenue by lead category.

The most important metric is not the number of scraped businesses.

It is:

```text
Qualified and manually verified leads that convert into paying clients.
```

---

# 32. Future Enhancements

Only consider these after validating sales:

* Playwright browser checks.
* Mobile rendering tests.
* Screenshots.
* Lighthouse audits.
* Visual redesign scoring.
* Contact-form testing.
* CRM pipeline.
* Outreach templates.
* Automatic audit reports.
* AI-generated personalization.
* Competitor analysis.
* Multi-user dashboard.
* Cloud deployment.
* Scheduled lead refresh.
* Multiple cities.
* Multiple countries.

---

# 33. Final Scope Rule

The first version is complete when it reliably finds:

1. Businesses with no website.
2. Businesses with clearly broken websites.
3. Businesses requiring manual review.

Anything beyond this is secondary.

Do not build a complicated website-analysis platform before proving that Flozen AI can close customers from the basic lead list.

---

# Codex Master Prompt

You are building an internal Python application named **Local Business Website Lead Finder**.

Your task is to implement the application according to the attached PRD.

Do not overengineer the system.

The initial version must remain a local command-line application. Do not create a web dashboard, frontend, SaaS architecture, authentication system, Docker orchestration, microservices, browser automation or AI-based website scoring.

## Objective

Build a reliable Python pipeline that:

1. Searches for local businesses using the official Google Places API.
2. Supports configurable business queries and locations.
3. Deduplicates businesses using Google Place ID.
4. Separates businesses with no website.
5. Checks listed websites using asynchronous HTTP requests.
6. Flags only objectively broken websites.
7. Sends uncertain cases to manual review.
8. Stores results in SQLite.
9. Exports results to CSV.
10. Limits Google API usage and supports caching.

## Required technology

Use:

* Python 3.12+
* `httpx`
* `pydantic`
* `pydantic-settings`
* `python-dotenv`
* `beautifulsoup4`
* `tenacity`
* `typer`
* `rich`
* `pandas`
* `PyYAML`
* SQLite
* `pytest`
* `pytest-asyncio`
* `respx`
* `ruff`
* `mypy`

Use a modern `pyproject.toml`.

## Required project structure

Create:

```text
local-business-lead-finder/
│
├── README.md
├── pyproject.toml
├── .env.example
├── .gitignore
├── config.example.yaml
│
├── src/
│   └── lead_finder/
│       ├── __init__.py
│       ├── cli.py
│       ├── config.py
│       ├── models.py
│       ├── database.py
│       ├── places_client.py
│       ├── website_checker.py
│       ├── url_utils.py
│       ├── page_classifier.py
│       ├── important_pages.py
│       ├── lead_scoring.py
│       ├── exporter.py
│       └── logging_config.py
│
├── tests/
├── data/
├── output/
└── logs/
```

## Business classifications

Use exactly these classification values:

```text
NO_WEBSITE
BROKEN_WEBSITE
IMPORTANT_PAGE_BROKEN
WORKING_WEBSITE
MANUAL_REVIEW
UNCHECKED
```

## Classification rules

### NO_WEBSITE

Use when the Google Places website field is absent, null or empty.

### BROKEN_WEBSITE

Use only for objective failures such as:

* DNS failure.
* Connection failure after retries.
* Repeated timeout.
* Redirect loop.
* Homepage HTTP 404.
* Homepage HTTP 410.
* Homepage HTTP 500–599.
* Strong evidence of an expired domain.
* Strong evidence of suspended hosting.
* Strong evidence of a domain-for-sale placeholder.

### WORKING_WEBSITE

Use when the final website response is successful and there is no strong error-page evidence.

### MANUAL_REVIEW

Use for:

* HTTP 401.
* HTTP 403.
* HTTP 429.
* CAPTCHA.
* Cloudflare challenge.
* Bot blocking.
* SSL ambiguity.
* Unexpected non-HTML content.
* Intermittent failure.
* Conflicting evidence.
* Any uncertain classification.

Always prefer `MANUAL_REVIEW` over a potentially incorrect `BROKEN_WEBSITE` classification.

## HTTP requirements

Use asynchronous `httpx.AsyncClient`.

Default settings:

```text
Concurrency: 10
Connection timeout: 5 seconds
Read timeout: 10 seconds
Retries: 1
Maximum redirects: 10
Maximum response size: 5 MB
```

Follow redirects.

Use a reasonable browser-like user-agent.

Record:

* Original URL.
* Final URL.
* Initial status code.
* Final status code.
* Redirect count.
* Response time.
* Content type.
* Error category.
* Attempts.
* Check timestamp.

## URL safety

Only permit HTTP and HTTPS.

Reject requests to:

* localhost.
* Loopback IPs.
* Private IPs.
* Link-local IPs.
* Multicast IPs.
* Cloud metadata addresses.
* Private IPv6 addresses.

Protect against DNS rebinding where reasonably possible.

Do not support:

```text
file://
ftp://
gopher://
data:
javascript:
```

## Google API requirements

Use the official current Google Places API.

Read the API key only from:

```text
GOOGLE_MAPS_API_KEY
```

Never hardcode or log the API key.

Use a minimal configurable field mask.

Support:

* Text search.
* Pagination.
* Request limits.
* Result limits.
* Caching.
* Exponential backoff for temporary API errors.
* Clear handling of quota and authentication errors.
* Deduplication by Place ID.

Do not scrape Google Maps HTML.

## Database requirements

Use SQLite.

Create tables for:

* Search runs.
* Search queries.
* Businesses.
* Website checks.
* Cached API responses.

Use migrations only if they can be implemented simply. Do not add a heavy migration framework unless necessary.

Use unique constraints for Place ID.

## CLI requirements

Implement these commands:

```bash
lead-finder validate-config
lead-finder estimate
lead-finder collect
lead-finder check-websites
lead-finder export
lead-finder run
```

Support:

```bash
--config
--dry-run
--force-refresh
```

The estimate command should show:

* Number of queries.
* Configured result limits.
* Maximum API requests.
* Whether website checks are enabled.
* Whether important-page checks are enabled.

The run command should request terminal confirmation before a large run.

## Configuration

Support YAML configuration.

Create `config.example.yaml` containing:

* Project name.
* Location.
* Queries.
* Maximum results.
* API request limit.
* Website-check settings.
* Cache TTL.
* Output directory.
* Filters.
* Important-page configuration.

Validate the configuration using Pydantic.

Fail with a clear error message when configuration is invalid.

## CSV exports

Generate:

```text
output/all_businesses.csv
output/qualified_leads.csv
output/manual_review.csv
output/working_websites.csv
```

Use UTF-8.

Qualified leads must include:

```text
NO_WEBSITE
BROKEN_WEBSITE
IMPORTANT_PAGE_BROKEN
```

Sort qualified leads by priority score descending.

## Required CSV columns

Include:

```text
place_id
business_name
category
address
city
postal_code
phone
international_phone
google_maps_url
website_url
rating
review_count
business_status
lead_category
issue_type
issue_description
initial_status_code
final_status_code
final_url
redirect_count
response_time_ms
content_type
check_attempts
important_broken_page
priority_score
priority_level
search_query
search_location
collected_at
checked_at
manual_review_required
```

## Lead scoring

Implement transparent deterministic scoring.

Use the scoring rules from the PRD.

Keep the score logic isolated in `lead_scoring.py`.

Include unit tests for every scoring rule.

## Logging

Create file and console logging.

Log:

* Run configuration.
* Start and finish.
* Queries.
* API request count.
* Businesses collected.
* Duplicates removed.
* Website checks.
* Retries.
* Classification totals.
* Exports.
* Errors.

Never log secrets.

## Tests

Create unit tests for:

* URL normalization.
* Unsafe URL rejection.
* Private IP rejection.
* Status-code classification.
* Redirect handling.
* Timeout handling.
* DNS failure.
* Placeholder-page classification.
* Cloudflare/manual-review classification.
* Place-ID deduplication.
* CSV export.
* Lead scoring.
* Configuration validation.

Mock all external HTTP requests.

Tests must never use the live Google Places API.

Use `respx` for HTTPX mocking.

## README

The README must explain:

1. Project purpose.
2. Prerequisites.
3. Google Cloud setup.
4. How to enable Places API.
5. How to create `.env`.
6. How to configure a search.
7. How to run a 20-business pilot.
8. CLI commands.
9. Output files.
10. Classification meanings.
11. Cost-control precautions.
12. Manual-review requirement.
13. Limitations.
14. Ethical-use guidance.
15. How to run tests and linting.

## Development process

Work in stages.

### Stage 1

Create project structure, configuration, models, logging and database.

Run tests.

### Stage 2

Implement Places API collection, caching, limits and deduplication.

Run tests.

### Stage 3

Implement URL normalization, network safety and asynchronous website checking.

Run tests.

### Stage 4

Implement classification and scoring.

Run tests.

### Stage 5

Implement CSV export and CLI workflow.

Run tests.

### Stage 6

Perform a final code review.

Check:

* No hardcoded secrets.
* No Google Maps scraping.
* No subjective design scoring.
* No unnecessary browser automation.
* No uncontrolled concurrency.
* No infinite retries.
* No duplicate Place IDs.
* No misleading classifications.
* No tests that call live APIs.

## Execution instructions

Before writing code:

1. Read the complete PRD.
2. Summarize the implementation plan.
3. Identify any contradictions.
4. Choose the simplest maintainable architecture.
5. Do not add features outside the PRD.

After each stage:

1. Run tests.
2. Run Ruff.
3. Run MyPy.
4. Fix failures before continuing.
5. Briefly summarize completed work.

At the end:

1. Run the full test suite.
2. Run linting.
3. Run type checking.
4. Show the final project tree.
5. Provide exact setup commands.
6. Provide the command for a safe 20-business Manchester electrician pilot.
7. List any remaining limitations honestly.

Do not claim the tool is production-ready unless all acceptance criteria are satisfied.

---

# Recommended First Codex Task

Do not give Codex the entire build as one uncontrolled instruction initially.

Start with this:

```text
Read the attached PRD for the Local Business Website Lead Finder.

Implement only Stage 1:

- Create the Python 3.12 project structure.
- Create pyproject.toml.
- Add the required dependencies.
- Add configuration models using Pydantic.
- Add config.example.yaml.
- Add .env.example.
- Add logging configuration.
- Add SQLite database initialization.
- Add core data models.
- Add a Typer CLI with placeholder commands.
- Add unit tests for configuration validation and database initialization.
- Add Ruff, MyPy and Pytest configuration.

Do not implement Google Places API calls or website checking yet.

After implementation:

1. Run the tests.
2. Run Ruff.
3. Run MyPy.
4. Fix all errors.
5. Show the project tree.
6. Summarize design decisions.
```

---

# Second Codex Task

```text
Continue the Local Business Website Lead Finder project.

Implement only Stage 2 from the PRD:

- Google Places API text-search client.
- Minimal configurable field masks.
- Pagination.
- API request limits.
- Maximum result limits.
- Caching.
- Temporary-error retries.
- Authentication, quota and invalid-request error handling.
- Place-ID deduplication.
- SQLite persistence.
- A collect CLI command.
- Mocked unit tests using respx.

Do not implement website checking yet.

Never call the live API during tests.

After implementation:

1. Run the tests.
2. Run Ruff.
3. Run MyPy.
4. Fix every failure.
5. Explain how API usage is limited.
```

---

# Third Codex Task

```text
Continue the Local Business Website Lead Finder project.

Implement only Stage 3 from the PRD:

- URL normalization.
- HTTP/HTTPS-only enforcement.
- Private-network and localhost blocking.
- DNS and IP safety validation.
- Asynchronous HTTPX website checks.
- Connection and read timeouts.
- Controlled retries.
- Redirect following.
- Redirect-loop detection.
- Maximum response-size handling.
- Response timing.
- Content-type recording.
- Website-check persistence.
- A check-websites CLI command.
- Fully mocked tests.

Do not add Playwright, Selenium, Lighthouse or browser automation.

After implementation:

1. Run the tests.
2. Run Ruff.
3. Run MyPy.
4. Fix all failures.
5. Explain any network-safety limitations.
```

---

# Fourth Codex Task

```text
Continue the Local Business Website Lead Finder project.

Implement only Stage 4 from the PRD:

- NO_WEBSITE classification.
- BROKEN_WEBSITE classification.
- WORKING_WEBSITE classification.
- MANUAL_REVIEW classification.
- Conservative expired-domain and suspended-hosting detection.
- Cloudflare and bot-protection manual-review detection.
- Transparent lead scoring.
- Priority levels.
- Classification and scoring tests.

False positives are unacceptable.

When evidence is uncertain, classify the business as MANUAL_REVIEW.

Do not implement subjective website-quality analysis.

After implementation:

1. Run tests.
2. Run Ruff.
3. Run MyPy.
4. Show examples of each classification.
```

---

# Fifth Codex Task

```text
Continue the Local Business Website Lead Finder project.

Implement Stage 5 from the PRD:

- CSV exports.
- Complete run workflow.
- Run summary.
- Estimate command.
- Dry-run support.
- Force-refresh support.
- Output sorting.
- Resume support.
- README documentation.
- A safe example configuration for 20 electricians in Manchester.

Generate:

- all_businesses.csv
- qualified_leads.csv
- manual_review.csv
- working_websites.csv

After implementation:

1. Run the full test suite.
2. Run Ruff.
3. Run MyPy.
4. Fix all failures.
5. Show exact installation and execution commands.
6. Show the safe pilot command.
7. State all remaining limitations.
```

---

# Final Review Prompt for Codex

```text
Perform a ruthless final review of the Local Business Website Lead Finder against the PRD.

Inspect the entire repository.

Check for:

- Scope creep.
- Hardcoded secrets.
- Excessive Google API usage.
- Missing field masks.
- Missing pagination safeguards.
- Duplicate Place IDs.
- Incorrect status-code classification.
- False broken-website classifications.
- Unsafe URL requests.
- SSRF risks.
- Unlimited response downloads.
- Infinite retries.
- Excessive concurrency.
- Missing cache behavior.
- Weak error handling.
- Missing tests.
- Live API calls inside tests.
- Incorrect CSV fields.
- Poor documentation.
- Dead code.
- Unnecessary abstractions.
- Type errors.
- Lint errors.

Fix every issue you can safely fix without adding features outside the PRD.

Then:

1. Run the complete test suite.
2. Run Ruff.
3. Run MyPy.
4. Show the final project tree.
5. Summarize all fixes.
6. List unresolved limitations.
7. Confirm whether every acceptance criterion is satisfied.
8. Do not claim production readiness unless that is genuinely true.
```

