"""
Scraper Orchestrator

Coordinates Apple and Google scrapers, merges results through the normalizer,
and writes output to JSONL files. Handles partial platform failures gracefully.
"""

import json
import os
import structlog
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import yaml

from .apple_scraper import AppleRSSScraper
from .google_scraper import GooglePlayScraper
from .normalizer import ReviewNormalizer
from .rate_limiter import RateLimiter

logger = structlog.get_logger(__name__)


class ScraperOrchestrator:
    """
    Orchestrates the full Phase 1 scraping pipeline:
        1. Scrape Apple App Store reviews
        2. Scrape Google Play Store reviews
        3. Merge and normalize all reviews
        4. Output deduplicated JSONL

    Handles partial failures: if one platform fails, proceeds with the other.
    """

    def __init__(self, config: dict):
        """
        Initialize the orchestrator with pipeline configuration.

        Args:
            config: Scraper configuration dict (from pipeline_config.yaml).
                    Expected keys: apple, google, lookback_weeks,
                    min_lookback_weeks, rate_limit, request_timeout_seconds
        """
        self.config = config

        # Rate limiter shared config (separate instances per scraper)
        rate_limit_config = config.get("rate_limit", {})
        self.rpm = rate_limit_config.get("requests_per_minute", 10)
        self.retry_max = rate_limit_config.get("retry_max", 3)
        self.retry_backoff = rate_limit_config.get("retry_backoff_seconds", 5)
        self.request_timeout = config.get("request_timeout_seconds", 30)

        # Date window
        self.lookback_weeks = config.get("lookback_weeks", 12)
        self.min_lookback_weeks = config.get("min_lookback_weeks", 8)

    def _create_apple_scraper(self) -> Optional[AppleRSSScraper]:
        """Create and configure the Apple scraper."""
        apple_config = self.config.get("apple", {})
        app_id = apple_config.get("app_id")

        if not app_id:
            logger.warning("apple_scraper_disabled", reason="No app_id configured")
            return None

        return AppleRSSScraper(
            app_id=app_id,
            country=apple_config.get("country", "us"),
            rss_limit=apple_config.get("rss_limit", 500),
            rate_limiter=RateLimiter(
                requests_per_minute=self.rpm,
                retry_max=self.retry_max,
                retry_backoff_seconds=self.retry_backoff,
            ),
            request_timeout=self.request_timeout,
        )

    def _create_google_scraper(self) -> Optional[GooglePlayScraper]:
        """Create and configure the Google Play scraper."""
        google_config = self.config.get("google", {})
        app_id = google_config.get("app_id")

        if not app_id:
            logger.warning("google_scraper_disabled", reason="No app_id configured")
            return None

        try:
            return GooglePlayScraper(
                app_id=app_id,
                language=google_config.get("language", "en"),
                count=google_config.get("count", 500),
                rate_limiter=RateLimiter(
                    requests_per_minute=self.rpm,
                    retry_max=self.retry_max,
                    retry_backoff_seconds=self.retry_backoff,
                ),
            )
        except ImportError as e:
            logger.error("google_scraper_import_error", error=str(e))
            return None

    @staticmethod
    def _save_jsonl(reviews: list[dict], filepath: str) -> None:
        """
        Save normalized reviews to a JSONL file (one review per line).

        Creates parent directories if they don't exist.
        """
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            for review in reviews:
                f.write(json.dumps(review, ensure_ascii=False) + "\n")

        logger.info("reviews_saved", filepath=str(path), count=len(reviews))

    @staticmethod
    def _save_metadata(metadata: dict, filepath: str) -> None:
        """Save scrape metadata to a JSON file."""
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)

        with open(path, "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        logger.info("metadata_saved", filepath=str(path))

    @staticmethod
    def _load_existing_review_ids(filepath: str) -> set:
        """
        Load existing review IDs from a JSONL file for deduplication
        across runs.
        """
        path = Path(filepath)
        if not path.exists():
            return set()

        ids = set()
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line:
                        review = json.loads(line)
                        ids.add(review.get("review_id"))
        except Exception as e:
            logger.warning("load_existing_ids_error", error=str(e))

        return ids

    def run(self, output_dir: str = "data/raw", week_key: Optional[str] = None) -> dict:
        """
        Execute the full Phase 1 scraping pipeline.

        Args:
            output_dir: Directory to write output files.
            week_key: Week identifier (e.g., "2026-W17"). Auto-generated if None.

        Returns:
            dict with keys:
                - reviews: list of normalized review dicts
                - metadata: combined scrape metadata
                - filepath: path to the output JSONL file
        """
        if week_key is None:
            week_key = datetime.now(timezone.utc).strftime("%Y-W%W")

        started_at = datetime.now(timezone.utc)
        logger.info("scraper_orchestrator_start", week_key=week_key)

        # Initialize results containers
        all_raw_reviews = []
        platform_metadata = {}
        platforms_available = []
        platforms_failed = []

        # --- Scrape Apple ---
        apple_scraper = self._create_apple_scraper()
        if apple_scraper:
            try:
                logger.info("scraping_apple_start")
                apple_result = apple_scraper.scrape()
                all_raw_reviews.extend(apple_result["reviews"])
                platform_metadata["apple"] = apple_result["metadata"]
                platforms_available.append("apple")
                logger.info(
                    "scraping_apple_complete",
                    reviews=len(apple_result["reviews"]),
                )
            except Exception as e:
                logger.error(
                    "scraping_apple_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                platform_metadata["apple"] = {
                    "status": "failed",
                    "error": str(e),
                }
                platforms_failed.append("apple")
        else:
            platform_metadata["apple"] = {"status": "disabled"}

        # --- Scrape Google ---
        google_scraper = self._create_google_scraper()
        if google_scraper:
            try:
                logger.info("scraping_google_start")
                google_result = google_scraper.scrape()
                all_raw_reviews.extend(google_result["reviews"])
                platform_metadata["google"] = google_result["metadata"]
                platforms_available.append("google")
                logger.info(
                    "scraping_google_complete",
                    reviews=len(google_result["reviews"]),
                )
            except Exception as e:
                logger.error(
                    "scraping_google_failed",
                    error=str(e),
                    error_type=type(e).__name__,
                )
                platform_metadata["google"] = {
                    "status": "failed",
                    "error": str(e),
                }
                platforms_failed.append("google")
        else:
            platform_metadata["google"] = {"status": "disabled"}

        # --- Normalize ---
        normalizer = ReviewNormalizer(
            lookback_weeks=self.lookback_weeks,
            min_lookback_weeks=self.min_lookback_weeks,
        )

        logger.info(
            "normalizing_reviews",
            total_raw=len(all_raw_reviews),
        )
        norm_result = normalizer.normalize_batch(all_raw_reviews)
        normalized_reviews = norm_result["reviews"]
        norm_stats = norm_result["stats"]

        # --- Dedup against existing data ---
        output_filepath = os.path.join(output_dir, f"{week_key}.jsonl")
        existing_ids = self._load_existing_review_ids(output_filepath)
        if existing_ids:
            before_dedup = len(normalized_reviews)
            normalized_reviews = [
                r for r in normalized_reviews if r["review_id"] not in existing_ids
            ]
            cross_run_dedup = before_dedup - len(normalized_reviews)
            logger.info(
                "cross_run_dedup",
                existing_ids=len(existing_ids),
                new_reviews=len(normalized_reviews),
                duplicates_removed=cross_run_dedup,
            )
            norm_stats["cross_run_duplicates_skipped"] = cross_run_dedup

        # --- Save output ---
        self._save_jsonl(normalized_reviews, output_filepath)

        metadata_filepath = os.path.join(output_dir, f"{week_key}_metadata.json")
        finished_at = datetime.now(timezone.utc)

        combined_metadata = {
            "week_key": week_key,
            "pipeline_phase": "phase_1_scraping",
            "started_at": started_at.isoformat(),
            "finished_at": finished_at.isoformat(),
            "duration_seconds": round(
                (finished_at - started_at).total_seconds(), 2
            ),
            "platforms_available": platforms_available,
            "platforms_failed": platforms_failed,
            "total_raw_reviews": len(all_raw_reviews),
            "total_normalized_reviews": len(normalized_reviews),
            "normalization_stats": norm_stats,
            "platform_metadata": platform_metadata,
            "output_file": output_filepath,
        }

        # Add warnings
        warnings = []
        if not normalized_reviews:
            warnings.append("No reviews found in window")
        if platforms_failed:
            warnings.append(
                f"Platforms failed: {', '.join(platforms_failed)}"
            )
        if norm_stats.get("all_reviews_outside_window"):
            warnings.append("All reviews were outside the date window")

        if warnings:
            combined_metadata["warnings"] = warnings

        self._save_metadata(combined_metadata, metadata_filepath)

        logger.info(
            "scraper_orchestrator_complete",
            week_key=week_key,
            total_reviews=len(normalized_reviews),
            platforms=platforms_available,
            warnings=warnings if warnings else None,
        )

        return {
            "reviews": normalized_reviews,
            "metadata": combined_metadata,
            "filepath": output_filepath,
        }


def load_config(config_path: str = "config/pipeline_config.yaml") -> dict:
    """Load pipeline configuration from YAML file."""
    with open(config_path, "r") as f:
        config = yaml.safe_load(f)
    return config.get("scraper", {})


def run_phase1(
    config_path: str = "config/pipeline_config.yaml",
    output_dir: str = "data/raw",
    week_key: Optional[str] = None,
) -> dict:
    """
    Convenience function to run Phase 1 from the command line or orchestrator.

    Args:
        config_path: Path to pipeline_config.yaml
        output_dir: Output directory for JSONL files
        week_key: Week identifier (auto-generated if None)

    Returns:
        Phase 1 result dict
    """
    config = load_config(config_path)
    orchestrator = ScraperOrchestrator(config)
    return orchestrator.run(output_dir=output_dir, week_key=week_key)


if __name__ == "__main__":
    # Configure structured logging
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )

    result = run_phase1()
    print(f"\n{'='*60}")
    print(f"Phase 1 Complete")
    print(f"Reviews collected: {len(result['reviews'])}")
    print(f"Output file: {result['filepath']}")
    if result["metadata"].get("warnings"):
        print(f"Warnings: {result['metadata']['warnings']}")
    print(f"{'='*60}")
