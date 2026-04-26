"""
Google Play Store Scraper

Scrapes public reviews from the Google Play Store using the
`google-play-scraper` Python library. This library handles the
underlying web requests and pagination.

No API key or authentication required — uses public endpoints only.
"""

import structlog
from datetime import datetime, timezone
from typing import Optional

try:
    from google_play_scraper import Sort, reviews as gplay_reviews
    from google_play_scraper.exceptions import NotFoundError

    GPLAY_AVAILABLE = True
except ImportError:
    GPLAY_AVAILABLE = False

from .rate_limiter import RateLimiter, RateLimitError

logger = structlog.get_logger(__name__)

# Google Play scraper returns reviews in batches of this size
DEFAULT_BATCH_SIZE = 100


class GooglePlayScraper:
    """
    Scrapes reviews from the Google Play Store using the
    google-play-scraper library.

    The library handles pagination via continuation tokens internally.
    We wrap it with rate limiting and error handling.
    """

    def __init__(
        self,
        app_id: str,
        language: str = "en",
        country: str = "us",
        count: int = 500,
        rate_limiter: Optional[RateLimiter] = None,
    ):
        if not GPLAY_AVAILABLE:
            raise ImportError(
                "google-play-scraper is required but not installed. "
                "Run: pip install google-play-scraper"
            )

        self.app_id = app_id
        self.language = language
        self.country = country
        self.count = count
        self.rate_limiter = rate_limiter or RateLimiter()

    def _parse_review(self, review: dict) -> Optional[dict]:
        """
        Parse a single review from google-play-scraper format to our raw format.

        Uses defensive access to handle library version changes.
        Returns None if review has no body text.
        """
        try:
            body = review.get("content", "")
            if not body or not body.strip():
                logger.warning(
                    "google_review_missing_body",
                    review_id=review.get("reviewId", "unknown"),
                )
                return None

            # Extract rating — clamp to 1-5
            rating = review.get("score", 3)
            try:
                rating = int(rating)
                rating = max(1, min(5, rating))
            except (ValueError, TypeError):
                logger.warning("google_invalid_rating", raw_rating=rating)
                rating = 3

            # Extract date — google-play-scraper returns datetime objects
            review_date = review.get("at", None)
            if isinstance(review_date, datetime):
                date_str = review_date.isoformat()
            elif review_date:
                date_str = str(review_date)
            else:
                date_str = datetime.now(timezone.utc).isoformat()

            # Extract author name (for PII hashing in normalizer)
            author_name = review.get("userName", "")

            # Extract review ID
            review_id = review.get("reviewId", "")

            # Extract app version
            app_version = review.get("reviewCreatedVersion", None)

            # Extract thumbs up count (useful metadata)
            thumbs_up = review.get("thumbsUpCount", 0)

            return {
                "review_id": f"google_{review_id}" if review_id else None,
                "platform": "google",
                "author_name_raw": author_name,
                "rating": rating,
                "title": None,  # Google Play reviews don't have separate titles
                "body": body.strip(),
                "date": date_str,
                "app_version": app_version,
                "thumbs_up": thumbs_up,
            }

        except Exception as e:
            logger.error(
                "google_review_parse_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    def _fetch_batch(
        self, continuation_token: Optional[str] = None
    ) -> tuple[list[dict], Optional[str]]:
        """
        Fetch a batch of reviews from Google Play.

        Args:
            continuation_token: Token from previous batch for pagination.

        Returns:
            Tuple of (raw_reviews_list, next_continuation_token)
            Token is None when no more pages are available.
        """
        try:

            def _do_fetch():
                result, token = gplay_reviews(
                    self.app_id,
                    lang=self.language,
                    country=self.country,
                    sort=Sort.NEWEST,
                    count=min(DEFAULT_BATCH_SIZE, self.count),
                    continuation_token=continuation_token,
                )
                return result, token

            result, next_token = self.rate_limiter.execute(
                lambda: _do_fetch()
            )

            return result, next_token

        except RateLimitError as e:
            logger.error("google_rate_limit_exhausted", error=str(e))
            return [], None

        except NotFoundError:
            logger.error("google_app_not_found", app_id=self.app_id)
            return [], None

        except Exception as e:
            logger.error(
                "google_fetch_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return [], None

    def scrape(self) -> dict:
        """
        Scrape reviews from Google Play Store.

        Paginates through batches using continuation tokens until
        the requested count is reached or no more reviews are available.

        Returns:
            dict with keys:
                - reviews: list of raw review dicts
                - metadata: scrape metadata
        """
        all_reviews = []
        continuation_token = None
        batches_fetched = 0
        batches_failed = 0
        started_at = datetime.now(timezone.utc)

        logger.info(
            "google_scrape_start",
            app_id=self.app_id,
            language=self.language,
            target_count=self.count,
        )

        while len(all_reviews) < self.count:
            logger.info(
                "google_fetch_batch",
                batch=batches_fetched + 1,
                reviews_so_far=len(all_reviews),
            )

            raw_batch, next_token = self._fetch_batch(continuation_token)

            if not raw_batch:
                if batches_fetched == 0:
                    batches_failed += 1
                    logger.warning(
                        "google_first_batch_empty", app_id=self.app_id
                    )
                else:
                    logger.info(
                        "google_pagination_exhausted",
                        total_batches=batches_fetched,
                    )
                break

            # Parse each review
            parsed_count = 0
            for raw_review in raw_batch:
                parsed = self._parse_review(raw_review)
                if parsed and parsed.get("review_id"):
                    all_reviews.append(parsed)
                    parsed_count += 1

            batches_fetched += 1
            logger.info(
                "google_batch_parsed",
                batch=batches_fetched,
                raw_count=len(raw_batch),
                parsed_count=parsed_count,
            )

            # Check if we should continue
            if not next_token:
                logger.info("google_no_more_pages", total_batches=batches_fetched)
                break

            continuation_token = next_token

        # Trim to limit
        if len(all_reviews) > self.count:
            all_reviews = all_reviews[: self.count]

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        metadata = {
            "platform": "google",
            "app_id": self.app_id,
            "language": self.language,
            "reviews_collected": len(all_reviews),
            "batches_fetched": batches_fetched,
            "batches_failed": batches_failed,
            "partial": batches_failed > 0,
            "duration_seconds": round(duration, 2),
            "scraped_at": finished_at.isoformat(),
            "rate_limiter_stats": self.rate_limiter.stats,
        }

        if not all_reviews:
            metadata["warning"] = "No reviews found"
            logger.warning("google_no_reviews", metadata=metadata)
        else:
            logger.info("google_scrape_complete", metadata=metadata)

        return {"reviews": all_reviews, "metadata": metadata}
