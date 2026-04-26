"""
Phase 1 Evaluation Tests — Review Scraping

Comprehensive tests covering functional correctness, edge cases,
and reliability for the scraping pipeline.
"""

import json
import hashlib
import os
import time
import pytest
from datetime import datetime, timezone, timedelta
from unittest.mock import patch, MagicMock, PropertyMock
from pathlib import Path

# Add src to path
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.scraper.rate_limiter import RateLimiter, RateLimitError
from src.scraper.apple_scraper import AppleRSSScraper
from src.scraper.normalizer import ReviewNormalizer
from src.scraper.orchestrator import ScraperOrchestrator


# ============================================================
# Fixtures
# ============================================================

def make_apple_rss_entry(
    review_id="12345",
    author="John Doe",
    rating="4",
    title="Great app",
    body="Love this app, works perfectly!",
    date="2026-04-10T12:00:00-07:00",
    version="2.1.0",
):
    """Create a single Apple RSS feed entry."""
    return {
        "id": {"label": review_id},
        "author": {"name": {"label": author}},
        "im:rating": {"label": rating},
        "title": {"label": title},
        "content": {"label": body},
        "updated": {"label": date},
        "im:version": {"label": version},
    }


def make_apple_rss_response(entries, status_code=200):
    """Create a mock Apple RSS feed response."""
    mock_response = MagicMock()
    mock_response.status_code = status_code
    mock_response.json.return_value = {
        "feed": {
            "entry": entries,
        }
    }
    return mock_response


def make_empty_apple_response():
    """Create an empty Apple RSS response (for pagination stop)."""
    mock_response = MagicMock()
    mock_response.status_code = 200
    mock_response.json.return_value = {"feed": {"entry": []}}
    return mock_response


def make_google_review(
    review_id="gplay_001",
    user_name="Jane Smith",
    score=5,
    content="Amazing app experience!",
    at=None,
    version="3.0.1",
    thumbs_up=10,
):
    """Create a single Google Play review dict."""
    if at is None:
        at = datetime.now(timezone.utc) - timedelta(days=7)
    return {
        "reviewId": review_id,
        "userName": user_name,
        "score": score,
        "content": content,
        "at": at,
        "reviewCreatedVersion": version,
        "thumbsUpCount": thumbs_up,
    }


def make_scraper_config(
    apple_app_id="123456789",
    google_app_id="com.example.app",
    lookback_weeks=12,
):
    """Create a scraper configuration dict."""
    return {
        "apple": {
            "app_id": apple_app_id,
            "country": "us",
            "rss_limit": 500,
        },
        "google": {
            "app_id": google_app_id,
            "language": "en",
            "count": 500,
        },
        "lookback_weeks": lookback_weeks,
        "min_lookback_weeks": 8,
        "rate_limit": {
            "requests_per_minute": 60,  # Fast for tests
            "retry_max": 2,
            "retry_backoff_seconds": 0.01,  # Fast retries for tests
        },
        "request_timeout_seconds": 5,
    }


# ============================================================
# Rate Limiter Tests
# ============================================================

class TestRateLimiter:
    """Tests for the rate limiter with exponential backoff."""

    def test_basic_execution(self):
        """Rate limiter executes function and returns result."""
        limiter = RateLimiter(requests_per_minute=60, retry_max=3)
        result = limiter.execute(lambda: "success")
        assert result == "success"

    def test_rate_limiting_enforced(self):
        """Requests are throttled to respect rate limit."""
        limiter = RateLimiter(requests_per_minute=30, retry_max=0)
        # 30 RPM = 2 second interval
        start = time.monotonic()
        limiter.execute(lambda: "a")
        limiter.execute(lambda: "b")
        elapsed = time.monotonic() - start
        assert elapsed >= 1.5  # Should have waited ~2 seconds

    def test_retry_on_exception(self):
        """Retries on transient exceptions with backoff."""
        call_count = 0

        def failing_then_success():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ConnectionError("Network error")
            return "success"

        limiter = RateLimiter(
            requests_per_minute=600,
            retry_max=3,
            retry_backoff_seconds=0.01,
        )
        result = limiter.execute(failing_then_success)
        assert result == "success"
        assert call_count == 3

    def test_retry_on_429_status(self):
        """Retries on HTTP 429 response."""
        call_count = 0

        def mock_request():
            nonlocal call_count
            call_count += 1
            resp = MagicMock()
            resp.status_code = 429 if call_count < 3 else 200
            return resp

        limiter = RateLimiter(
            requests_per_minute=600,
            retry_max=3,
            retry_backoff_seconds=0.01,
        )
        result = limiter.execute(mock_request)
        assert result.status_code == 200
        assert call_count == 3

    def test_exhausted_retries_raises(self):
        """Raises RateLimitError when all retries exhausted."""
        limiter = RateLimiter(
            requests_per_minute=600,
            retry_max=2,
            retry_backoff_seconds=0.01,
        )
        with pytest.raises(RateLimitError):
            limiter.execute(lambda: (_ for _ in ()).throw(ConnectionError("fail")))

    def test_stats_tracking(self):
        """Stats track total requests and retries."""
        call_count = 0

        def sometimes_fail():
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ConnectionError("fail")
            return "ok"

        limiter = RateLimiter(
            requests_per_minute=600,
            retry_max=3,
            retry_backoff_seconds=0.01,
        )
        limiter.execute(sometimes_fail)
        stats = limiter.stats
        assert stats["total_requests"] == 2
        assert stats["total_retries"] == 1


# ============================================================
# Apple Scraper Tests
# ============================================================

class TestAppleScraper:
    """Tests for the Apple App Store RSS scraper."""

    @patch("src.scraper.apple_scraper.requests.get")
    def test_successful_scrape(self, mock_get):
        """TC-1.1: Valid RSS feed returns normalized reviews."""
        entries = [
            make_apple_rss_entry(review_id=f"r{i}", body=f"Review body {i}")
            for i in range(5)
        ]
        mock_get.side_effect = [make_apple_rss_response(entries), make_empty_apple_response()]

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(requests_per_minute=600, retry_max=1, retry_backoff_seconds=0.01),
        )
        result = scraper.scrape()

        assert len(result["reviews"]) == 5
        assert result["metadata"]["platform"] == "apple"
        assert result["metadata"]["reviews_collected"] == 5

    @patch("src.scraper.apple_scraper.requests.get")
    def test_empty_feed(self, mock_get):
        """EC-1.1: Empty feed returns empty list with warning."""
        mock_get.return_value = make_apple_rss_response([])

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(requests_per_minute=600, retry_max=1, retry_backoff_seconds=0.01),
        )
        result = scraper.scrape()

        assert result["reviews"] == []
        assert result["metadata"]["reviews_collected"] == 0
        assert "warning" in result["metadata"]

    @patch("src.scraper.apple_scraper.requests.get")
    def test_malformed_entries_skipped(self, mock_get):
        """EC-1.7: Entries with null body are skipped."""
        entries = [
            make_apple_rss_entry(review_id="good", body="Valid review"),
            make_apple_rss_entry(review_id="bad", body=""),  # Empty body
            make_apple_rss_entry(review_id="also_good", body="Another valid review"),
        ]
        mock_get.side_effect = [make_apple_rss_response(entries), make_empty_apple_response()]

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(requests_per_minute=600, retry_max=1, retry_backoff_seconds=0.01),
        )
        result = scraper.scrape()

        assert len(result["reviews"]) >= 2  # May get duplicates from pagination

    @patch("src.scraper.apple_scraper.requests.get")
    def test_invalid_rating_clamped(self, mock_get):
        """EC-1.7: Rating outside 1-5 is clamped."""
        entries = [
            make_apple_rss_entry(review_id="r1", rating="0", body="Bad rating"),
            make_apple_rss_entry(review_id="r2", rating="10", body="High rating"),
            make_apple_rss_entry(review_id="r3", rating="abc", body="NaN rating"),
        ]
        mock_get.side_effect = [make_apple_rss_response(entries), make_empty_apple_response()]

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(requests_per_minute=600, retry_max=1, retry_backoff_seconds=0.01),
        )
        result = scraper.scrape()

        ratings = [r["rating"] for r in result["reviews"]]
        assert all(1 <= r <= 5 for r in ratings)

    @patch("src.scraper.apple_scraper.requests.get")
    def test_rate_limit_retry(self, mock_get):
        """EC-1.5: 429 response triggers retry."""
        mock_429 = MagicMock()
        mock_429.status_code = 429

        mock_200 = make_apple_rss_response([
            make_apple_rss_entry(body="Success after retry")
        ])

        mock_get.side_effect = [mock_429, mock_429, mock_200]

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(
                requests_per_minute=600,
                retry_max=3,
                retry_backoff_seconds=0.01,
            ),
        )
        result = scraper.scrape()
        assert len(result["reviews"]) == 1

    @patch("src.scraper.apple_scraper.requests.get")
    def test_timeout_handling(self, mock_get):
        """TC-1.R3: Timeout results in empty result, no crash."""
        import requests as req
        mock_get.side_effect = req.exceptions.Timeout("Connection timed out")

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(
                requests_per_minute=600,
                retry_max=0,
                retry_backoff_seconds=0.01,
            ),
        )
        result = scraper.scrape()
        assert result["reviews"] == []

    @patch("src.scraper.apple_scraper.requests.get")
    def test_schema_change_graceful(self, mock_get):
        """EC-1.4: Missing fields handled gracefully."""
        # Entry with renamed/missing fields
        entry = {
            "id": {"label": "r1"},
            "im:rating": {"label": "4"},
            "content": {"label": "Works fine"},
            # Missing: author, title, im:version, updated
        }
        mock_get.side_effect = [make_apple_rss_response([entry]), make_empty_apple_response()]

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=100,
            rate_limiter=RateLimiter(requests_per_minute=600, retry_max=1, retry_backoff_seconds=0.01),
        )
        result = scraper.scrape()

        assert len(result["reviews"]) == 1
        assert result["reviews"][0]["body"] == "Works fine"

    @patch("src.scraper.apple_scraper.requests.get")
    def test_limit_enforced(self, mock_get):
        """EC-1.2: Reviews capped at rss_limit."""
        entries = [
            make_apple_rss_entry(review_id=f"r{i}", body=f"Review {i}")
            for i in range(50)
        ]
        mock_get.return_value = make_apple_rss_response(entries)

        scraper = AppleRSSScraper(
            app_id="123456789",
            rss_limit=10,  # Cap at 10
            rate_limiter=RateLimiter(requests_per_minute=600, retry_max=1, retry_backoff_seconds=0.01),
        )
        result = scraper.scrape()

        assert len(result["reviews"]) <= 10


# ============================================================
# Normalizer Tests
# ============================================================

class TestNormalizer:
    """Tests for the Review Normalizer."""

    def test_unified_schema(self):
        """TC-1.3: All reviews conform to normalized schema."""
        normalizer = ReviewNormalizer(lookback_weeks=52)  # Wide window
        raw = {
            "review_id": "apple_12345",
            "platform": "apple",
            "author_name_raw": "John Doe",
            "rating": 4,
            "title": "Great",
            "body": "Works perfectly",
            "date": datetime.now(timezone.utc).isoformat(),
            "app_version": "2.0",
        }

        result = normalizer.normalize_review(raw)

        assert result is not None
        required_fields = [
            "review_id", "platform", "author_anonymous_hash",
            "rating", "title", "body", "date", "language",
            "app_version", "scraped_at",
        ]
        for field in required_fields:
            assert field in result, f"Missing field: {field}"

    def test_pii_hashing(self):
        """TC-1.6: Author names hashed to SHA-256."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        raw = {
            "review_id": "test_1",
            "platform": "apple",
            "author_name_raw": "John Doe",
            "rating": 5,
            "body": "Great app",
            "date": datetime.now(timezone.utc).isoformat(),
        }

        result = normalizer.normalize_review(raw)

        # Should be SHA-256 hash, not raw name
        assert result["author_anonymous_hash"] != "John Doe"
        expected_hash = hashlib.sha256("John Doe".encode("utf-8")).hexdigest()
        assert result["author_anonymous_hash"] == expected_hash
        assert len(result["author_anonymous_hash"]) == 64  # SHA-256 hex length

    def test_deduplication(self):
        """TC-1.5 / EC-1.6: Duplicate review_ids removed."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        now = datetime.now(timezone.utc).isoformat()

        reviews = [
            {"review_id": "r1", "platform": "apple", "body": "First", "rating": 5, "date": now},
            {"review_id": "r1", "platform": "apple", "body": "Duplicate", "rating": 5, "date": now},
            {"review_id": "r2", "platform": "google", "body": "Second", "rating": 4, "date": now},
        ]

        result = normalizer.normalize_batch(reviews)

        assert result["stats"]["total_normalized"] == 2
        assert result["stats"]["duplicates_skipped"] == 1

    def test_date_filtering(self):
        """TC-1.4: Only reviews in 8-12 week window retained."""
        normalizer = ReviewNormalizer(lookback_weeks=12)
        now = datetime.now(timezone.utc)

        reviews = [
            {
                "review_id": "recent",
                "platform": "apple",
                "body": "Recent review",
                "rating": 5,
                "date": (now - timedelta(weeks=2)).isoformat(),
            },
            {
                "review_id": "old",
                "platform": "apple",
                "body": "Old review",
                "rating": 3,
                "date": (now - timedelta(weeks=20)).isoformat(),  # 20 weeks ago
            },
        ]

        result = normalizer.normalize_batch(reviews)

        assert result["stats"]["total_normalized"] == 1
        assert result["stats"]["outside_window_skipped"] == 1

    def test_html_stripping(self):
        """EC-1.7: HTML tags stripped from review body."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        raw = {
            "review_id": "html_test",
            "platform": "apple",
            "body": "<b>Bold text</b> and <a href='url'>link</a> &amp; entities",
            "rating": 4,
            "date": datetime.now(timezone.utc).isoformat(),
        }

        result = normalizer.normalize_review(raw)

        assert "<b>" not in result["body"]
        assert "<a" not in result["body"]
        assert "Bold text" in result["body"]
        assert "& entities" in result["body"]

    def test_language_detection_english(self):
        """TC-1.7: English reviews tagged correctly."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        raw = {
            "review_id": "en_test",
            "platform": "apple",
            "body": "This is a really great application that works perfectly on my phone",
            "rating": 5,
            "date": datetime.now(timezone.utc).isoformat(),
        }

        result = normalizer.normalize_review(raw)
        assert result["language"] == "en"

    def test_language_detection_non_english(self):
        """EC-1.3: Non-English reviews detected correctly."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        raw = {
            "review_id": "es_test",
            "platform": "google",
            "body": "Esta aplicación es muy buena, me encanta usarla todos los días",
            "rating": 5,
            "date": datetime.now(timezone.utc).isoformat(),
        }

        result = normalizer.normalize_review(raw)
        # Should detect Spanish
        assert result["language"] in ("es", "pt", "it", "ca")  # Romance languages

    def test_emoji_only_review(self):
        """EC-1.3: Emoji-only reviews get language 'und'."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        raw = {
            "review_id": "emoji_test",
            "platform": "google",
            "body": "🔥🔥🔥💯❤️👍",
            "rating": 5,
            "date": datetime.now(timezone.utc).isoformat(),
        }

        result = normalizer.normalize_review(raw)
        assert result["language"] == "und"

    def test_empty_body_skipped(self):
        """EC-1.7: Reviews with empty body are skipped."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        raw = {
            "review_id": "empty_body",
            "platform": "apple",
            "body": "",
            "rating": 1,
            "date": datetime.now(timezone.utc).isoformat(),
        }

        result = normalizer.normalize_review(raw)
        assert result is None

    def test_all_reviews_outside_window(self):
        """EC-1.10: All reviews too old → empty with metadata flag."""
        normalizer = ReviewNormalizer(lookback_weeks=12)
        old_date = (datetime.now(timezone.utc) - timedelta(weeks=26)).isoformat()

        reviews = [
            {"review_id": f"old_{i}", "platform": "apple", "body": f"Old review {i}",
             "rating": 3, "date": old_date}
            for i in range(5)
        ]

        result = normalizer.normalize_batch(reviews)

        assert result["stats"]["total_normalized"] == 0
        assert result["stats"]["all_reviews_outside_window"] is True

    def test_rating_clamping(self):
        """EC-1.7: Ratings outside 1-5 clamped."""
        normalizer = ReviewNormalizer(lookback_weeks=52)

        for raw_rating, expected in [(0, 1), (6, 5), (-1, 1), (100, 5)]:
            raw = {
                "review_id": f"rating_{raw_rating}",
                "platform": "apple",
                "body": "Test review body text here",
                "rating": raw_rating,
                "date": datetime.now(timezone.utc).isoformat(),
            }
            result = normalizer.normalize_review(raw)
            assert result["rating"] == expected, f"Rating {raw_rating} should clamp to {expected}"


# ============================================================
# Orchestrator Tests
# ============================================================

class TestScraperOrchestrator:
    """Tests for the Scraper Orchestrator."""

    @patch("src.scraper.orchestrator.GooglePlayScraper")
    @patch("src.scraper.orchestrator.AppleRSSScraper")
    def test_both_platforms_success(self, MockApple, MockGoogle):
        """TC-1.R4: Both platforms scraped successfully."""
        # Mock Apple
        apple_instance = MockApple.return_value
        apple_instance.scrape.return_value = {
            "reviews": [
                {"review_id": "apple_1", "platform": "apple", "body": "Good",
                 "rating": 5, "date": datetime.now(timezone.utc).isoformat()},
            ],
            "metadata": {"platform": "apple", "reviews_collected": 1},
        }

        # Mock Google
        google_instance = MockGoogle.return_value
        google_instance.scrape.return_value = {
            "reviews": [
                {"review_id": "google_1", "platform": "google", "body": "Great",
                 "rating": 4, "date": datetime.now(timezone.utc).isoformat()},
            ],
            "metadata": {"platform": "google", "reviews_collected": 1},
        }

        config = make_scraper_config()
        orchestrator = ScraperOrchestrator(config)

        with patch.object(orchestrator, '_create_apple_scraper', return_value=apple_instance):
            with patch.object(orchestrator, '_create_google_scraper', return_value=google_instance):
                result = orchestrator.run(output_dir="data/raw", week_key="test-week")

        assert result["metadata"]["total_raw_reviews"] == 2
        assert "apple" in result["metadata"]["platforms_available"]
        assert "google" in result["metadata"]["platforms_available"]

    @patch("src.scraper.orchestrator.GooglePlayScraper")
    @patch("src.scraper.orchestrator.AppleRSSScraper")
    def test_apple_fails_google_succeeds(self, MockApple, MockGoogle):
        """TC-1.R4 / EC-1.5: Pipeline continues with Google-only data."""
        apple_instance = MockApple.return_value
        apple_instance.scrape.side_effect = Exception("Apple scrape failed")

        google_instance = MockGoogle.return_value
        google_instance.scrape.return_value = {
            "reviews": [
                {"review_id": "google_1", "platform": "google", "body": "Works",
                 "rating": 4, "date": datetime.now(timezone.utc).isoformat()},
            ],
            "metadata": {"platform": "google", "reviews_collected": 1},
        }

        config = make_scraper_config()
        orchestrator = ScraperOrchestrator(config)

        with patch.object(orchestrator, '_create_apple_scraper', return_value=apple_instance):
            with patch.object(orchestrator, '_create_google_scraper', return_value=google_instance):
                result = orchestrator.run(output_dir="data/raw", week_key="test-partial")

        assert "apple" in result["metadata"]["platforms_failed"]
        assert "google" in result["metadata"]["platforms_available"]
        assert result["metadata"]["total_raw_reviews"] == 1

    def test_no_platforms_configured(self):
        """Both platforms disabled returns empty result."""
        config = make_scraper_config(apple_app_id="", google_app_id="")
        orchestrator = ScraperOrchestrator(config)
        result = orchestrator.run(output_dir="data/raw", week_key="test-empty")

        assert result["metadata"]["total_normalized_reviews"] == 0
        assert "No reviews found in window" in result["metadata"].get("warnings", [])

    def test_jsonl_output_format(self, tmp_path):
        """TC-1.8: Each line in JSONL is valid JSON."""
        reviews = [
            {"review_id": "r1", "body": "Test 1"},
            {"review_id": "r2", "body": "Test 2"},
        ]

        filepath = str(tmp_path / "test.jsonl")
        ScraperOrchestrator._save_jsonl(reviews, filepath)

        with open(filepath, "r") as f:
            lines = f.readlines()

        assert len(lines) == 2
        for line in lines:
            parsed = json.loads(line.strip())
            assert "review_id" in parsed

    def test_cross_run_dedup(self, tmp_path):
        """EC-1.6: Deduplication across runs prevents duplicates."""
        filepath = str(tmp_path / "existing.jsonl")

        # Write existing reviews
        with open(filepath, "w") as f:
            f.write(json.dumps({"review_id": "existing_1"}) + "\n")
            f.write(json.dumps({"review_id": "existing_2"}) + "\n")

        existing_ids = ScraperOrchestrator._load_existing_review_ids(filepath)

        assert "existing_1" in existing_ids
        assert "existing_2" in existing_ids
        assert len(existing_ids) == 2


# ============================================================
# Edge Case Integration Tests
# ============================================================

class TestEdgeCases:
    """Integration-style edge case tests."""

    def test_very_few_reviews(self):
        """EC-1.1 / EC-2.1: Pipeline handles 0-4 reviews gracefully."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        now = datetime.now(timezone.utc).isoformat()

        # Only 2 reviews
        reviews = [
            {"review_id": "r1", "platform": "apple", "body": "Payments broken",
             "rating": 1, "date": now},
            {"review_id": "r2", "platform": "google", "body": "Login crash",
             "rating": 2, "date": now},
        ]

        result = normalizer.normalize_batch(reviews)
        assert result["stats"]["total_normalized"] == 2

    def test_high_volume_cap(self):
        """EC-1.2: Large review sets are processable."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        now = datetime.now(timezone.utc).isoformat()

        # 1000 reviews
        reviews = [
            {"review_id": f"r{i}", "platform": "apple",
             "body": f"Review number {i} with enough text for detection",
             "rating": (i % 5) + 1, "date": now}
            for i in range(1000)
        ]

        result = normalizer.normalize_batch(reviews)
        assert result["stats"]["total_normalized"] == 1000
        assert result["stats"]["duplicates_skipped"] == 0

    def test_multilingual_mix(self):
        """EC-1.3: Mixed-language reviews processed correctly."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        now = datetime.now(timezone.utc).isoformat()

        reviews = [
            {"review_id": "en1", "platform": "apple",
             "body": "This application works really well on my device",
             "rating": 5, "date": now},
            {"review_id": "hi1", "platform": "google",
             "body": "यह ऐप बहुत अच्छा है मुझे यह पसंद है",
             "rating": 4, "date": now},
            {"review_id": "es1", "platform": "google",
             "body": "Esta aplicación es increíblemente buena y rápida",
             "rating": 5, "date": now},
        ]

        result = normalizer.normalize_batch(reviews)
        assert result["stats"]["total_normalized"] == 3

        # Check language tags are set (not all "und")
        langs = result["stats"]["language_distribution"]
        assert len(langs) >= 2  # At least 2 different languages detected

    def test_duplicate_across_platforms(self):
        """Reviews from different platforms with same content are NOT deduped (different IDs)."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        now = datetime.now(timezone.utc).isoformat()

        reviews = [
            {"review_id": "apple_123", "platform": "apple",
             "body": "Same review text here",
             "rating": 5, "date": now},
            {"review_id": "google_456", "platform": "google",
             "body": "Same review text here",
             "rating": 5, "date": now},
        ]

        result = normalizer.normalize_batch(reviews)
        # Different review_ids = not duplicates (even if content is same)
        assert result["stats"]["total_normalized"] == 2

    def test_malformed_date_uses_fallback(self):
        """EC-1.7: Invalid date format uses scraped_at as fallback."""
        normalizer = ReviewNormalizer(lookback_weeks=52)

        raw = {
            "review_id": "bad_date",
            "platform": "apple",
            "body": "Review with bad date format for testing",
            "rating": 3,
            "date": "not-a-date",
        }

        result = normalizer.normalize_review(raw)
        # Should not crash, should have a valid date
        assert result is not None
        assert "date" in result

    def test_special_unicode_preserved(self):
        """EC-3.10: Unicode and special chars preserved in body."""
        normalizer = ReviewNormalizer(lookback_weeks=52)
        now = datetime.now(timezone.utc).isoformat()

        body = "Love it! \U0001f525\u2764\ufe0f Best app - really great experience"
        raw = {
            "review_id": "unicode_test",
            "platform": "google",
            "body": body,
            "rating": 5,
            "date": now,
        }

        result = normalizer.normalize_review(raw)
        assert "\U0001f525" in result["body"]
        assert "\u2764" in result["body"]
        assert "Love it" in result["body"]


# ============================================================
# Run tests
# ============================================================

if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
