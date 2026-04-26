"""
Apple App Store Scraper — iTunes RSS Feed

Scrapes public reviews from the Apple App Store using the iTunes RSS feed.
The feed provides structured JSON data without requiring authentication.

Feed URL format:
    https://itunes.apple.com/{country}/rss/customerreviews/id={app_id}/sortBy=mostRecent/json

Limitations:
    - Apple RSS feed returns a maximum of ~500 reviews
    - Feed only includes relatively recent reviews
    - Pagination via page parameter: page=1, page=2, etc. (up to 10 pages of 50)
"""

import requests
import structlog
from datetime import datetime, timezone
from typing import Optional
from .rate_limiter import RateLimiter, RateLimitError

logger = structlog.get_logger(__name__)

# Maximum pages Apple RSS supports (50 reviews per page, max 10 pages)
MAX_RSS_PAGES = 10
REVIEWS_PER_PAGE = 50


class AppleRSSScraper:
    """
    Scrapes reviews from the Apple App Store iTunes RSS feed.

    The feed returns JSON with review entries including author, rating,
    title, body, and version information.
    """

    def __init__(
        self,
        app_id: str,
        country: str = "us",
        rss_limit: int = 500,
        rate_limiter: Optional[RateLimiter] = None,
        request_timeout: int = 30,
    ):
        self.app_id = app_id
        self.country = country
        self.rss_limit = rss_limit
        self.rate_limiter = rate_limiter or RateLimiter()
        self.request_timeout = request_timeout

    def _build_feed_url(self, page: int) -> str:
        """Build the iTunes RSS feed URL for a given page."""
        return (
            f"https://itunes.apple.com/{self.country}/rss/"
            f"customerreviews/page={page}/id={self.app_id}/"
            f"sortBy=mostRecent/json"
        )

    def _parse_entry(self, entry: dict) -> Optional[dict]:
        """
        Parse a single RSS feed entry into a raw review dict.

        Uses defensive key access (.get()) to handle schema changes gracefully.
        Returns None if the entry is missing critical data (body).
        """
        try:
            # Extract author name (will be hashed later by normalizer)
            author_data = entry.get("author", {})
            author_name = author_data.get("name", {}).get("label", "")

            # Extract review body — skip if missing
            body = entry.get("content", {}).get("label", "")
            if not body or not body.strip():
                logger.warning(
                    "apple_entry_missing_body",
                    review_id=entry.get("id", {}).get("label", "unknown"),
                )
                return None

            # Extract rating — defensive parsing
            rating_str = entry.get("im:rating", {}).get("label", "0")
            try:
                rating = int(rating_str)
                # Clamp to 1-5 range
                rating = max(1, min(5, rating))
            except (ValueError, TypeError):
                logger.warning("apple_invalid_rating", raw_rating=rating_str)
                rating = 3  # Default to neutral if unparseable

            # Extract date
            date_str = entry.get("updated", {}).get("label", "")

            # Extract review ID
            review_id = entry.get("id", {}).get("label", "")

            # Extract title
            title = entry.get("title", {}).get("label", "")

            # Extract app version
            app_version = entry.get("im:version", {}).get("label", None)

            return {
                "review_id": f"apple_{review_id}" if review_id else None,
                "platform": "apple",
                "author_name_raw": author_name,
                "rating": rating,
                "title": title if title else None,
                "body": body.strip(),
                "date": date_str,
                "app_version": app_version,
            }

        except Exception as e:
            logger.error(
                "apple_entry_parse_error",
                error=str(e),
                error_type=type(e).__name__,
            )
            return None

    def _fetch_page(self, page: int) -> list[dict]:
        """
        Fetch a single page of reviews from the RSS feed.

        Returns a list of raw review dicts, or empty list on failure.
        """
        url = self._build_feed_url(page)
        logger.info("apple_fetch_page", page=page, url=url)

        try:
            response = self.rate_limiter.execute(
                lambda: requests.get(url, timeout=self.request_timeout)
            )

            if response.status_code != 200:
                logger.warning(
                    "apple_non_200_response",
                    status_code=response.status_code,
                    page=page,
                )
                return []

            data = response.json()

            # Navigate the RSS JSON structure
            feed = data.get("feed", {})
            entries = feed.get("entry", [])

            # If entries is a single dict (only 1 review), wrap in list
            if isinstance(entries, dict):
                entries = [entries]

            # Filter out the app metadata entry (first entry is often the app itself)
            review_entries = []
            for entry in entries:
                # App metadata entries have im:name but no im:rating
                if "im:rating" in entry:
                    review_entries.append(entry)

            reviews = []
            for entry in review_entries:
                parsed = self._parse_entry(entry)
                if parsed and parsed.get("review_id"):
                    reviews.append(parsed)

            logger.info(
                "apple_page_parsed",
                page=page,
                entries_found=len(entries),
                reviews_parsed=len(reviews),
            )
            return reviews

        except RateLimitError as e:
            logger.error(
                "apple_rate_limit_exhausted",
                page=page,
                error=str(e),
            )
            return []

        except requests.exceptions.Timeout:
            logger.error("apple_request_timeout", page=page, timeout=self.request_timeout)
            return []

        except requests.exceptions.RequestException as e:
            logger.error(
                "apple_request_error",
                page=page,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []

        except (ValueError, KeyError) as e:
            logger.error(
                "apple_parse_error",
                page=page,
                error=str(e),
                error_type=type(e).__name__,
            )
            return []

    def scrape(self) -> dict:
        """
        Scrape all available reviews from the iTunes RSS feed.

        Paginates through up to MAX_RSS_PAGES pages, collecting reviews
        until the limit is reached or pages are exhausted.

        Returns:
            dict with keys:
                - reviews: list of raw review dicts
                - metadata: scrape metadata (counts, errors, timings)
        """
        all_reviews = []
        pages_fetched = 0
        pages_failed = 0
        started_at = datetime.now(timezone.utc)

        max_pages = min(
            MAX_RSS_PAGES,
            (self.rss_limit + REVIEWS_PER_PAGE - 1) // REVIEWS_PER_PAGE,
        )

        logger.info(
            "apple_scrape_start",
            app_id=self.app_id,
            country=self.country,
            max_pages=max_pages,
            rss_limit=self.rss_limit,
        )

        for page in range(1, max_pages + 1):
            reviews = self._fetch_page(page)

            if reviews:
                all_reviews.extend(reviews)
                pages_fetched += 1
            else:
                # Empty page could mean we've exhausted available reviews
                if page == 1:
                    pages_failed += 1
                    logger.warning("apple_first_page_empty", app_id=self.app_id)
                else:
                    # Later pages empty = no more reviews
                    logger.info("apple_pagination_exhausted", last_page=page - 1)
                    break

            # Check if we've hit our limit
            if len(all_reviews) >= self.rss_limit:
                all_reviews = all_reviews[: self.rss_limit]
                logger.info(
                    "apple_limit_reached",
                    limit=self.rss_limit,
                    total_fetched=len(all_reviews),
                )
                break

        finished_at = datetime.now(timezone.utc)
        duration = (finished_at - started_at).total_seconds()

        metadata = {
            "platform": "apple",
            "app_id": self.app_id,
            "country": self.country,
            "reviews_collected": len(all_reviews),
            "pages_fetched": pages_fetched,
            "pages_failed": pages_failed,
            "partial": pages_failed > 0,
            "duration_seconds": round(duration, 2),
            "scraped_at": finished_at.isoformat(),
            "rate_limiter_stats": self.rate_limiter.stats,
        }

        if not all_reviews:
            metadata["warning"] = "No reviews found"
            logger.warning("apple_no_reviews", metadata=metadata)
        else:
            logger.info("apple_scrape_complete", metadata=metadata)

        return {"reviews": all_reviews, "metadata": metadata}
