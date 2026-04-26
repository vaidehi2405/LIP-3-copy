"""
Review Normalizer

Transforms raw reviews from different platforms into a unified schema,
applies PII hashing, date filtering, deduplication, language detection,
and HTML stripping.
"""

import hashlib
import re
import structlog
from datetime import datetime, timezone, timedelta
from typing import Optional
from html import unescape

logger = structlog.get_logger(__name__)

# Lazy import langdetect — it's slow to initialize
_langdetect_loaded = False


def _ensure_langdetect():
    """Lazy-load langdetect to avoid startup penalty."""
    global _langdetect_loaded
    if not _langdetect_loaded:
        try:
            import langdetect
            # Make detection deterministic
            langdetect.DetectorFactory.seed = 0
            _langdetect_loaded = True
        except ImportError:
            logger.warning("langdetect_not_installed", fallback="und")


# Regex pattern to strip HTML tags
HTML_TAG_RE = re.compile(r"<[^>]+>")

# Regex patterns for detecting common date formats
ISO_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


class ReviewNormalizer:
    """
    Normalizes raw reviews from Apple and Google into a unified schema.

    Responsibilities:
        - Unified schema mapping
        - PII hashing (author names → SHA-256)
        - Date parsing and filtering (8–12 week window)
        - Deduplication by review_id
        - Language detection
        - HTML tag stripping
    """

    def __init__(
        self,
        lookback_weeks: int = 12,
        min_lookback_weeks: int = 8,
    ):
        self.lookback_weeks = lookback_weeks
        self.min_lookback_weeks = min_lookback_weeks

        # Calculate date window with a small buffer for processing time
        now = datetime.now(timezone.utc)
        self.window_end = now + timedelta(minutes=5)  # Small buffer for clock drift
        self.window_start = now - timedelta(weeks=lookback_weeks)

    @staticmethod
    def _hash_author(author_name: str) -> str:
        """
        Hash author name to SHA-256 for PII compliance.
        Never store raw usernames.
        """
        if not author_name:
            return hashlib.sha256(b"anonymous").hexdigest()
        return hashlib.sha256(author_name.encode("utf-8")).hexdigest()

    @staticmethod
    def _strip_html(text: str) -> str:
        """
        Remove HTML tags from text and unescape HTML entities.
        Preserves plain text content.
        """
        if not text:
            return ""
        # Unescape HTML entities first (&amp; → &, etc.)
        text = unescape(text)
        # Strip HTML tags
        text = HTML_TAG_RE.sub("", text)
        # Normalize whitespace
        text = " ".join(text.split())
        return text.strip()

    @staticmethod
    def _detect_language(text: str) -> str:
        """
        Detect the language of review text.

        Returns ISO 639-1 code (e.g., 'en', 'hi', 'es').
        Returns 'und' (undetermined) if detection fails or text is too short.
        """
        _ensure_langdetect()

        if not text or len(text.strip()) < 3:
            return "und"

        # Check for emoji-only content
        # Remove all emoji and whitespace; if nothing left, return "und"
        text_no_emoji = re.sub(
            r"[\U00010000-\U0010ffff\u2600-\u27BF\u2300-\u23FF\uFE0F]",
            "",
            text,
        )
        if not text_no_emoji.strip():
            return "und"

        try:
            import langdetect
            return langdetect.detect(text)
        except Exception:
            return "und"

    def _parse_date(self, date_str: str) -> Optional[datetime]:
        """
        Parse a date string into a datetime object.

        Handles multiple formats:
            - ISO 8601: 2026-04-15T10:30:00+00:00
            - Apple RSS: 2026-04-15T10:30:00-07:00
            - Simple date: 2026-04-15
            - Datetime objects passed as strings
        """
        if not date_str:
            return None

        # If it's already a datetime string in ISO format
        try:
            dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            pass

        # Try simple date format
        match = ISO_DATE_RE.search(str(date_str))
        if match:
            try:
                dt = datetime.strptime(match.group(), "%Y-%m-%d")
                return dt.replace(tzinfo=timezone.utc)
            except ValueError:
                pass

        logger.warning("unparseable_date", raw_date=date_str)
        return None

    def _is_in_window(self, dt: Optional[datetime]) -> bool:
        """Check if a datetime falls within the lookback window."""
        if dt is None:
            # If we can't parse the date, include it with a warning
            return True
        return self.window_start <= dt <= self.window_end

    def normalize_review(self, raw_review: dict) -> Optional[dict]:
        """
        Normalize a single raw review into the unified schema.

        Args:
            raw_review: Dict from Apple or Google scraper.

        Returns:
            Normalized review dict, or None if review should be skipped.
        """
        # Skip if no review_id
        review_id = raw_review.get("review_id")
        if not review_id:
            logger.warning("review_missing_id", platform=raw_review.get("platform"))
            return None

        # Extract and clean body
        body = raw_review.get("body", "")
        body = self._strip_html(body)
        if not body:
            logger.warning("review_empty_body", review_id=review_id)
            return None

        # Parse and filter by date
        date_str = raw_review.get("date", "")
        parsed_date = self._parse_date(date_str)

        if not self._is_in_window(parsed_date):
            logger.debug(
                "review_outside_window",
                review_id=review_id,
                date=date_str,
            )
            return None

        # Hash author name for PII compliance
        author_hash = self._hash_author(raw_review.get("author_name_raw", ""))

        # Detect language
        language = self._detect_language(body)

        # Build normalized review
        now = datetime.now(timezone.utc)

        # Clean title
        title = raw_review.get("title")
        if title:
            title = self._strip_html(title)
            if not title:
                title = None

        # Normalize rating — clamp to 1-5
        rating = raw_review.get("rating", 3)
        try:
            rating = int(rating)
            rating = max(1, min(5, rating))
        except (ValueError, TypeError):
            rating = 3

        return {
            "review_id": review_id,
            "platform": raw_review.get("platform", "unknown"),
            "author_anonymous_hash": author_hash,
            "rating": rating,
            "title": title,
            "body": body,
            "date": parsed_date.isoformat() if parsed_date else now.isoformat(),
            "language": language,
            "app_version": raw_review.get("app_version"),
            "scraped_at": now.isoformat(),
        }

    def normalize_batch(self, raw_reviews: list[dict]) -> dict:
        """
        Normalize a batch of raw reviews, applying deduplication
        and date filtering.

        Args:
            raw_reviews: List of raw review dicts from scrapers.

        Returns:
            dict with keys:
                - reviews: list of normalized review dicts (deduplicated)
                - stats: normalization statistics
        """
        seen_ids = set()
        normalized = []
        skipped_duplicate = 0
        skipped_no_body = 0
        skipped_outside_window = 0
        skipped_parse_error = 0
        total_input = len(raw_reviews)

        logger.info("normalize_batch_start", total_input=total_input)

        for raw in raw_reviews:
            # Deduplication
            review_id = raw.get("review_id")
            if review_id in seen_ids:
                skipped_duplicate += 1
                continue
            if review_id:
                seen_ids.add(review_id)

            # Normalize
            result = self.normalize_review(raw)
            if result is None:
                # Determine skip reason for stats
                body = raw.get("body", "")
                if not body or not body.strip():
                    skipped_no_body += 1
                else:
                    date_str = raw.get("date", "")
                    parsed = self._parse_date(date_str)
                    if parsed and not self._is_in_window(parsed):
                        skipped_outside_window += 1
                    else:
                        skipped_parse_error += 1
                continue

            normalized.append(result)

        # Detect language distribution
        lang_counts = {}
        for r in normalized:
            lang = r["language"]
            lang_counts[lang] = lang_counts.get(lang, 0) + 1

        stats = {
            "total_input": total_input,
            "total_normalized": len(normalized),
            "duplicates_skipped": skipped_duplicate,
            "no_body_skipped": skipped_no_body,
            "outside_window_skipped": skipped_outside_window,
            "parse_errors": skipped_parse_error,
            "language_distribution": lang_counts,
            "all_reviews_outside_window": (
                len(normalized) == 0 and skipped_outside_window > 0
            ),
        }

        logger.info("normalize_batch_complete", stats=stats)

        return {"reviews": normalized, "stats": stats}
