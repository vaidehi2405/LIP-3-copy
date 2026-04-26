# Phase 1 Evaluation — Review Scraping

## Evaluation Criteria

### 1. Functional Correctness

| Test Case | Description | Expected Outcome | Priority |
|---|---|---|---|
| TC-1.1 | Scrape Apple App Store reviews via RSS feed | Returns valid JSON with review objects | P0 |
| TC-1.2 | Scrape Google Play reviews via public endpoint | Returns parsed review objects | P0 |
| TC-1.3 | Reviews normalized to unified schema | All fields present: `review_id`, `platform`, `rating`, `body`, `date` | P0 |
| TC-1.4 | Date filtering: only 8–12 week window | No reviews older than 12 weeks or newer than current date | P0 |
| TC-1.5 | Deduplication by `review_id` | Re-running scraper produces no duplicate entries | P0 |
| TC-1.6 | PII hashing of author names | Author names stored as SHA-256 hashes, never raw | P0 |
| TC-1.7 | Language detection tag applied | Each review has a valid ISO 639-1 `language` field | P1 |
| TC-1.8 | JSONL output format correct | Each line is valid JSON; file is append-friendly | P1 |

### 2. Performance Metrics

| Metric | Target | Measurement Method |
|---|---|---|
| Scrape completion time (500 reviews) | < 5 minutes | Wall-clock timer |
| Memory usage | < 200 MB peak | `tracemalloc` profiling |
| Network requests | Minimized via pagination | Request counter per run |

### 3. Reliability

| Test Case | Description | Expected Outcome |
|---|---|---|
| TC-1.R1 | Rate limiting enforcement | Requests stay within configured `requests_per_minute` |
| TC-1.R2 | Retry on transient failure | Up to 3 retries with exponential backoff |
| TC-1.R3 | Timeout handling | 30s timeout per request; graceful failure after retries |
| TC-1.R4 | Partial platform failure | If Apple fails, Google data still collected (and vice versa) |

---

## Edge Cases

### EC-1.1 — Zero Reviews Returned
- **Scenario**: App has no reviews in the 8–12 week window (e.g., brand new app or very niche app).
- **Expected Behavior**: 
  - Scraper completes successfully with empty dataset
  - Returns `{"reviews": [], "metadata": {"count": 0, "warning": "No reviews found in window"}}`
  - Pipeline continues to Phase 2 which handles empty input gracefully
  - No error is raised; a warning is logged
- **Validation**: Mock RSS feed returning empty `<entry>` list; verify pipeline doesn't crash

### EC-1.2 — Extremely High Volume (>1000 Reviews/Week)
- **Scenario**: Viral app with thousands of reviews per week
- **Expected Behavior**:
  - Pagination handles full volume
  - Reviews capped at configurable limit (`rss_limit: 500`) to prevent runaway resource usage
  - Metadata records total available vs. collected count
- **Validation**: Mock paginated endpoint with 2000+ entries; verify cap is enforced and metadata is accurate

### EC-1.3 — Non-English Reviews
- **Scenario**: Reviews in Hindi, Spanish, Arabic, mixed-script text, or emoji-heavy reviews
- **Expected Behavior**:
  - Review is scraped and stored (not filtered out)
  - `language` field set via `langdetect` (e.g., `"hi"`, `"es"`, `"ar"`)
  - Reviews tagged as non-English are flagged for Phase 2 to decide handling
  - Emoji-only reviews get `language: "und"` (undetermined)
- **Validation**: Inject reviews in 5+ languages + emoji-only; verify correct language detection and no crashes on unusual Unicode

### EC-1.4 — RSS Feed Structure Changes
- **Scenario**: Apple changes the RSS feed XML/JSON schema (field renamed, nested differently, new fields added)
- **Expected Behavior**:
  - Parser uses defensive key access (`.get()` with defaults)
  - Schema mismatch logged as WARNING with the specific field that failed
  - Partial data extracted where possible (e.g., missing `title` is acceptable, missing `body` skips that review)
- **Validation**: Feed fixture with missing/renamed fields; verify graceful degradation

### EC-1.5 — Google Play Anti-Scraping Response
- **Scenario**: Google returns CAPTCHA page, 429 status, or blocks the request
- **Expected Behavior**:
  - Rate limiter detects 429/503 and backs off (exponential with jitter)
  - After 3 retries, marks Google as `"unavailable"` for this run
  - Pipeline continues with Apple-only data
  - Metadata: `{"google_status": "unavailable", "error": "HTTP 429 after 3 retries"}`
- **Validation**: Mock Google endpoint returning 429; verify retry count and fallback

### EC-1.6 — Duplicate Reviews Across Runs
- **Scenario**: Weekly run on Monday collects reviews; manual re-run on Wednesday overlaps
- **Expected Behavior**:
  - Deduplication by `review_id` prevents same review appearing twice
  - Newer scraped version does NOT overwrite older one (first-seen wins)
  - Dedup count logged: `"duplicates_skipped": 34`
- **Validation**: Run scraper twice with overlapping date windows; verify no duplicate `review_id` in output

### EC-1.7 — Malformed Individual Reviews
- **Scenario**: Review with null body, rating outside 1–5, invalid date format, or HTML injection in review text
- **Expected Behavior**:
  - Null body → skip review, log warning
  - Rating outside 1–5 → clamp to 1–5 range, log warning
  - Invalid date → use `scraped_at` as fallback date
  - HTML in body → strip tags, keep plain text
- **Validation**: Inject deliberately malformed review objects; verify each is handled per rule

### EC-1.8 — Network Timeout Mid-Pagination
- **Scenario**: Page 1 of 5 succeeds, page 3 times out
- **Expected Behavior**:
  - Reviews from pages 1–2 are retained
  - Page 3 retried up to 3 times
  - If all retries fail, return partial data (pages 1–2)
  - Metadata: `{"pages_fetched": 2, "pages_failed": 1, "partial": true}`
- **Validation**: Mock paginated endpoint where page 3 always times out; verify partial data returned

### EC-1.9 — Rate Limiting Across Both Platforms Simultaneously
- **Scenario**: Both Apple and Google hit rate limits in the same run
- **Expected Behavior**:
  - Each platform has independent rate limiter
  - Both back off independently
  - If both exhaust retries, run completes with empty review set
  - Error status logged for both platforms
- **Validation**: Both mocked endpoints return 429; verify independent retry logs

### EC-1.10 — Very Old Reviews Only
- **Scenario**: All reviews are older than 12 weeks (app abandoned or review drought)
- **Expected Behavior**:
  - Date filter removes all reviews
  - Returns empty dataset (same as EC-1.1)
  - Metadata indicates: `"all_reviews_outside_window": true`
- **Validation**: Mock feed with reviews dated 6 months ago; verify empty output with correct metadata

---

## Evaluation Script Outline

```python
# tests/eval_phase1_scraping.py

import pytest
from unittest.mock import patch, MagicMock
from src.scraper.apple_scraper import AppleRSSScraper
from src.scraper.google_scraper import GooglePlayScraper
from src.scraper.normalizer import ReviewNormalizer

class TestAppleScraper:
    def test_successful_scrape(self, apple_rss_fixture):
        """TC-1.1: Valid RSS feed returns normalized reviews."""
        pass
    
    def test_empty_feed(self, empty_rss_fixture):
        """EC-1.1: Empty feed returns empty list with warning metadata."""
        pass
    
    def test_malformed_entries(self, malformed_rss_fixture):
        """EC-1.4 / EC-1.7: Graceful handling of schema changes and bad data."""
        pass
    
    def test_rate_limit_retry(self, rate_limited_fixture):
        """TC-1.R1 / TC-1.R2: Exponential backoff on 429 responses."""
        pass
    
    def test_timeout_handling(self, timeout_fixture):
        """TC-1.R3: 30s timeout with retry."""
        pass

class TestGooglePlayScraper:
    def test_successful_scrape(self, google_play_fixture):
        """TC-1.2: Valid Google Play page returns parsed reviews."""
        pass
    
    def test_captcha_blocking(self, captcha_fixture):
        """EC-1.5: CAPTCHA/429 triggers retry then graceful failure."""
        pass
    
    def test_pagination_timeout(self, partial_pagination_fixture):
        """EC-1.8: Partial data returned on mid-pagination failure."""
        pass

class TestNormalizer:
    def test_unified_schema(self, raw_reviews_fixture):
        """TC-1.3: All reviews conform to normalized schema."""
        pass
    
    def test_deduplication(self, duplicate_reviews_fixture):
        """TC-1.5 / EC-1.6: Duplicate review_ids removed."""
        pass
    
    def test_pii_hashing(self, reviews_with_authors):
        """TC-1.6: Author names hashed to SHA-256."""
        pass
    
    def test_language_detection(self, multilingual_reviews):
        """TC-1.7 / EC-1.3: Correct language tags for diverse inputs."""
        pass
    
    def test_date_filtering(self, old_and_new_reviews):
        """TC-1.4 / EC-1.10: Only 8-12 week window retained."""
        pass
    
    def test_html_stripping(self, html_injected_reviews):
        """EC-1.7: HTML tags stripped from review body."""
        pass

class TestPartialFailure:
    def test_apple_fails_google_succeeds(self):
        """TC-1.R4: Pipeline continues with Google-only data."""
        pass
    
    def test_both_platforms_rate_limited(self):
        """EC-1.9: Both rate limited, empty result with error metadata."""
        pass
```
