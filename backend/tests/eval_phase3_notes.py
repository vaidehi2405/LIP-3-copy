"""
Phase 3 Tests — Weekly Note Generation
"""

import pytest
import os
from unittest.mock import patch, MagicMock
import textstat
from textstat import textstat

from src.notes.validator import NoteValidator
from src.notes.generator import NoteGenerator

@pytest.fixture
def sample_themes():
    return {
        "review_window": {"start": "2026-04-15", "end": "2026-04-21"},
        "metadata": {"platforms_failed": []},
        "themes": [
            {
                "theme_name": "Login Failures",
                "original_idx": 0,
                "sentiment": "negative",
                "volume": 45,
                "representative_quote": {"quote": "App crashes trying to login every time."}
            },
            {
                "theme_name": "Slow KYC",
                "original_idx": 1,
                "sentiment": "negative",
                "volume": 30,
                "representative_quote": {"quote": "Taking days to verify my pan card."}
            },
            {
                "theme_name": "Good UI",
                "original_idx": 2,
                "sentiment": "positive",
                "volume": 20,
                "representative_quote": {"quote": "Very clean user interface."}
            }
        ]
    }

class TestNoteValidator:

    def test_word_count_check(self):
        text = "This is a short text."
        valid, count = NoteValidator.validate_word_count(text, max_words=10)
        assert valid
        assert count == 5
        
        long_text = "word " * 260
        valid, count = NoteValidator.validate_word_count(long_text, max_words=250)
        assert not valid
        assert count == 260

    def test_pii_regex_patterns(self):
        text = "Call me at +91 9999999999."
        safe, count = NoteValidator.check_pii(text)
        assert "+91 9999999999" not in safe
        assert count == 1

    def test_action_specificity_check(self):
        good_text = "## Suggested Actions\n1. **Login Screen**: Fix crash.\n2. **KYC Flow**: Speed up.\n3. **Dashboard**: Update UI."
        assert NoteValidator.check_actions_specificity(good_text)
        
        bad_text = "## Suggested Actions\n1. Fix the core app crash.\n2. Optimize backend.\n3. Ask for feedback."
        assert not NoteValidator.check_actions_specificity(bad_text)

    def test_quote_verification(self):
        themes = [{"representative_quote": {"quote": "App crashes trying to login."}}]
        text = "> \"App crashes trying to login.\""
        _, replacements = NoteValidator.verify_quotes(text, themes)
        assert replacements == 0
        
        hallucinated_text = "> \"This quote is totally fake.\""
        _, replacements = NoteValidator.verify_quotes(hallucinated_text, themes)
        assert replacements == 1

class TestNoteGenerator:

    @patch("src.notes.generator.Groq")
    @patch.dict(os.environ, {"GROQ_API_KEY": "test_key"})
    def test_generator_output(self, mock_groq, sample_themes):
        # Mock LLM return value
        mock_response = MagicMock()
        mock_response.choices[0].message.content = (
            "# Weekly App Review Pulse\n"
            "**95 reviews analyzed**...\n\n"
            "## Top Themes This Week\n"
            "### 1. Login Failures (45 mentions, negative)\n"
            "> \"App crashes trying to login every time.\"\n\n"
            "### 2. Slow KYC (30 mentions, negative)\n"
            "> \"Taking days to verify my pan card.\"\n\n"
            "### 3. Good UI (20 mentions, positive)\n"
            "> \"Very clean user interface.\"\n\n"
            "## Suggested Actions\n"
            "1. **Login Screen**: Add fallbacks.\n"
            "2. **KYC Upload**: Add real-time status.\n"
            "3. **Dashboard**: Highlight features."
        )
        
        # We need to mock chat.completions.create mapping
        mock_client_instance = mock_groq.return_value
        mock_client_instance.chat.completions.create.return_value = mock_response

        generator = NoteGenerator()
        result = generator.process_themes(sample_themes)
        
        assert result["metadata"]["word_count"] < 250
        assert result["metadata"]["themes_included"] == 3
        assert result["metadata"]["pii_caught_in_note"] == 0
        assert "html" in result
        assert "<div style=" in result["html"]
        
        # Quality metric: Readability Grade (TC-3.2 / Quality goal)
        grade = textstat.flesch_kincaid_grade(result["markdown"])
        # Simple mock text will obviously have low grade.
        assert grade <= 10.0

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
