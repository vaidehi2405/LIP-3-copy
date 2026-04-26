"""
Phase 2 Evaluation Tests — Theme Extraction (LLM)

Comprehensive tests covering functional correctness, edge cases,
and reliability for the theme extraction pipeline.
"""

import json
import pytest
from unittest.mock import patch, MagicMock

import os
import sys
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.themes.pii_scrubber import PIIScrubber
from src.themes.validator import ThemeValidator
from src.themes.extractor import ThemeExtractor

# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_reviews_50():
    return [
        {
            "review_id": f"r_{i}",
            "body": f"Review body {i}. Some complain about login issue.",
            "rating": 2,
            "date": "2026-04-10T12:00:00+00:00",
            "language": "en"
        }
        for i in range(50)
    ]

# ============================================================
# PII Scrubber Tests
# ============================================================

class TestPIIScrubber:
    def test_email_redaction(self):
        text = "Contact me at user.name@example.com for more info."
        scrubbed, stats = PIIScrubber.scrub_text(text)
        assert "user.name@example.com" not in scrubbed
        assert "[REDACTED_EMAIL]" in scrubbed
        assert stats["emails"] == 1

    def test_phone_redaction(self):
        text = "Call +91 9876543210 or 123-456-7890."
        scrubbed, stats = PIIScrubber.scrub_text(text)
        assert "+91 9876543210" not in scrubbed
        assert "123-456-7890" not in scrubbed
        assert "[REDACTED_PHONE]" in scrubbed
        assert stats["phones"] == 2

    def test_id_number_redaction(self):
        text = "My ID is 1234 5678 9012 and PAN ABCDE1234F."
        scrubbed, stats = PIIScrubber.scrub_text(text)
        assert "1234 5678 9012" not in scrubbed
        assert "ABCDE1234F" not in scrubbed
        assert "[REDACTED_ID]" in scrubbed
        assert stats["ids"] == 2

    def test_username_redaction(self):
        text = "Thanks @groww_support and @user123."
        scrubbed, stats = PIIScrubber.scrub_text(text)
        assert "@groww_support" not in scrubbed
        assert "[REDACTED_USER]" in scrubbed
        assert stats["usernames"] == 2

# ============================================================
# Theme Validator Tests
# ============================================================

class TestThemeValidator:
    def test_vague_theme_exclusion(self):
        all_reviews = []
        themes = [
            {"theme_name": "bad app", "review_ids": ["r1", "r2"]},
            {"theme_name": "KYC upload timeout", "review_ids": ["r3", "r4"]}
        ]
        valid_themes, stats = ThemeValidator.validate_and_merge(themes, all_reviews)
        assert len(valid_themes) == 1
        assert valid_themes[0]["theme_name"] == "KYC upload timeout"
        assert stats["vague_themes_dropped"] == 1

    def test_max_five_themes(self):
        all_reviews = []
        themes = [
            {"theme_name": f"Specific Feature {i}", "volume": 10-i, "review_ids": [f"r{i}"]}
            for i in range(10)
        ]
        valid_themes, stats = ThemeValidator.validate_and_merge(themes, all_reviews)
        assert len(valid_themes) == 5

    def test_overlap_detection(self):
        all_reviews = []
        themes = [
            {"theme_name": "Payment failure UPI", "review_ids": ["r1", "r2", "r3"]},
            {"theme_name": "UPI transaction timeout", "review_ids": ["r2", "r3", "r4"]}
        ]
        valid_themes, stats = ThemeValidator.validate_and_merge(themes, all_reviews)
        assert len(valid_themes) == 1
        assert stats["themes_merged"] == 1
        assert len(valid_themes[0]["review_ids"]) == 4

    def test_quote_validation_fuzzymatch(self):
        all_reviews = [
            {"review_id": "r1", "body": "I tried to upload my PAN card but the app crashed immediately."}
        ]
        themes = [
            {
                "theme_name": "PAN upload crash",
                "review_ids": ["r1"],
                "representative_quote": {
                    "review_id": "r1",
                    "quote": "tried to upload my PAN card but the app crashed" # Slightly paraphrased / substring
                }
            }
        ]
        valid_themes, stats = ThemeValidator.validate_and_merge(themes, all_reviews)
        assert len(valid_themes) == 1
        assert valid_themes[0]["representative_quote"] is not None
        assert stats["hallucinated_quotes_dropped"] == 0

    def test_quote_validation_hallucination_dropped(self):
        all_reviews = [
            {"review_id": "r1", "body": "App is good."}
        ]
        themes = [
            {
                "theme_name": "Login authentication failure during startup",
                "review_ids": ["r1"],
                "representative_quote": {
                    "review_id": "r1",
                    "quote": "The login is completely broken!" # Completely hallucinated
                }
            }
        ]
        valid_themes, stats = ThemeValidator.validate_and_merge(themes, all_reviews)
        assert stats["quotes_corrected"] == 1

# ============================================================
# Theme Extractor Tests
# ============================================================

class TestThemeExtraction:
    
    @patch("src.themes.extractor.Groq")
    @patch.dict(os.environ, {"GROQ_API_KEY": "test_key"})
    def test_truncation(self, mock_groq):
        extractor = ThemeExtractor()
        long_review = "word " * 600
        truncated = extractor._truncate_review(long_review)
        assert len(truncated.split()) == 501
        assert truncated.endswith("[TRUNCATED]")

    @patch("src.themes.extractor.Groq")
    @patch.dict(os.environ, {"GROQ_API_KEY": "test_key"})
    def test_pii_scrubbing_integration(self, mock_groq_class):
        extractor = ThemeExtractor()
        reviews = [
            {"review_id": "r1", "body": "My phone +91 9999999999"}
        ]
        safe_reviews, pii_stats, extract_stats = extractor._prepare_reviews(reviews)
        assert "9999999999" not in safe_reviews[0]["body"]
        assert extract_stats["pii_redactions"] == 1

    @patch.object(ThemeExtractor, "_call_llm_json")
    def test_basic_extraction(self, mock_call_llm_json, sample_reviews_50):
        mock_call_llm_json.return_value = {
            "themes": [
                {
                    "theme_name": "Login screen crash on Android",
                    "description": "App crashes during login",
                    "review_ids": ["r_1", "r_2"],
                    "sentiment": "negative",
                    "volume": 2,
                    "representative_quote": {
                        "review_id": "r_1",
                        "quote": "Review body 1. Some complain about login issue.",
                        "rating": 2
                    }
                }
            ]
        }
        
        # We need to set GROQ_API_KEY environment variable momentarily to init extractor if missing
        import os
        os.environ["GROQ_API_KEY"] = "test_key"
        
        extractor = ThemeExtractor()
        result = extractor.extract_themes(sample_reviews_50)
        
        assert "themes" in result
        assert len(result["themes"]) == 1
        assert result["themes"][0]["theme_name"] == "Login screen crash on Android"
        assert result["metadata"]["batches_used"] == 1

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
