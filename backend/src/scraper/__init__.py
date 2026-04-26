"""
Phase 1 — Review Scraping Module

Collects public app reviews from Apple App Store (iTunes RSS) and
Google Play Store, normalizes them into a unified schema, and outputs
deduplicated JSONL files.
"""

from .apple_scraper import AppleRSSScraper
from .google_scraper import GooglePlayScraper
from .normalizer import ReviewNormalizer
from .orchestrator import ScraperOrchestrator
from .rate_limiter import RateLimiter

__all__ = [
    "AppleRSSScraper",
    "GooglePlayScraper",
    "ReviewNormalizer",
    "ScraperOrchestrator",
    "RateLimiter",
]
