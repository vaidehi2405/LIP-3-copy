"""
Theme Extractor Module
Handles querying the Groq LLaMA models, batching logic, rate limit handling,
and overarching coordination of Phase 2 logic.
"""

import json
import os
import time
import structlog
from datetime import datetime, timezone
import yaml
from groq import Groq, APIError, RateLimitError

from .prompts import THEME_DISCOVERY_SYSTEM_PROMPT, THEME_CONSOLIDATION_SYSTEM_PROMPT
from .pii_scrubber import PIIScrubber
from .validator import ThemeValidator

logger = structlog.get_logger(__name__)

class ThemeExtractor:
    """
    Coordinates Phase 2 Theme Extraction.
    Calls Groq LLM API.
    """

    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        # Load configuration
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            
        self.llm_config = config.get("llm", {})
        self.model = self.llm_config.get("model", "llama-3.1-70b-versatile")
        self.max_retries = self.llm_config.get("max_retries", 3)
        
        # Initialize Groq client
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            logger.error("groq_api_key_invalid", msg="LLM API authentication failed. Check your API key.")
            raise ValueError("LLM API authentication failed. Check your API key.")
            
        self.client = Groq(api_key=api_key)

    def _truncate_review(self, text: str, max_words: int = 500) -> str:
        """Truncate overly long reviews."""
        if not text:
            return ""
        words = text.split()
        if len(words) > max_words:
            return " ".join(words[:max_words]) + "... [TRUNCATED]"
        return text

    def _prepare_reviews(self, reviews: list[dict]) -> tuple[list[dict], dict]:
        """PII Scrubbing, truncating, grouping."""
        stats = {
            "reviews_truncated": 0,
            "non_english_skipped": 0,
            "total_reviews_analyzed": 0
        }

        prepared_reviews = []
        for r in reviews:
            # Skip non-English if configured, but default architecture handles them or translates them in prompt
            # But we record it
            if r.get("language") != "en" and r.get("language") != "unknown":
                stats["non_english_skipped"] += 1
            
            body = r.get("body", "")
            if len(body.split()) > 500:
                r["body"] = self._truncate_review(body)
                stats["reviews_truncated"] += 1

            prepared_reviews.append(r)

        # Do PII scrubbing
        safe_reviews, pii_stats = PIIScrubber.scrub_reviews(prepared_reviews)
        stats["pii_redactions"] = sum(pii_stats.values())
        stats["total_reviews_analyzed"] = len(safe_reviews)

        return safe_reviews, pii_stats, stats

    def _call_llm_json(self, system_prompt: str, user_content: str) -> dict:
        """
        Calls Groq API to return JSON format.
        Implements exponential backoff on retry.
        """
        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_content}
                    ],
                    response_format={"type": "json_object"},
                    max_tokens=4000,
                    temperature=0.1
                )
                
                content = response.choices[0].message.content
                return json.loads(content)
                
            except RateLimitError as e:
                wait_time = 2 ** attempt
                logger.warning("groq_rate_limit", attempt=attempt, wait=wait_time, error=str(e))
                if attempt == self.max_retries:
                    raise
                time.sleep(wait_time)
            except json.JSONDecodeError as e:
                logger.warning("groq_json_decode_error", attempt=attempt, error=str(e))
                if attempt == self.max_retries:
                    raise
                time.sleep(1)
            except Exception as e:
                logger.error("groq_api_error", attempt=attempt, error=str(e))
                if attempt == self.max_retries:
                    raise
                time.sleep(2)
        
        return {"themes": []}

    def _run_batch(self, batch_reviews: list[dict]) -> dict:
        """Runs the theme discovery prompt on a single batch."""
        # Format reviews compactly for prompt
        lines = []
        for r in batch_reviews:
            r_id = r.get("review_id", "unknown")
            rating = r.get("rating", "N/A")
            body_text = r.get("body", "")
            lines.append(f"[{r_id}] Rating: {rating} | Review: {body_text}")
        
        user_content = "\n".join(lines)
        return self._call_llm_json(THEME_DISCOVERY_SYSTEM_PROMPT, user_content)

    def extract_themes(self, raw_reviews: list[dict]) -> dict:
        """
        Main orchestration logic.
        1. Prepares reviews (PII, truncate).
        2. Batches (max 50 reviews/batch).
        3. Calls Groq.
        4. Validates & Merges.
        5. Formats output.
        """
        started_at = datetime.now(timezone.utc)
        safe_reviews, pii_stats, extract_stats = self._prepare_reviews(raw_reviews)
        
        if not safe_reviews:
            logger.warning("no_reviews_for_extraction")
            return {"themes": [], "warning": "No actionable reviews found"}

        # Edge Case 2.1: Very Few Reviews
        if len(safe_reviews) < 5:
            extract_stats["low_review_count_warning"] = True

        # Edge case: Sample > 500 reviews
        if len(safe_reviews) > 500:
            safe_reviews = safe_reviews[:500]
            extract_stats["capped_at_500"] = True
            
        all_review_dict = {r["review_id"]: r for r in safe_reviews}
            
        # Strategy: Batches of 50
        batch_size = 50
        batches = [safe_reviews[i:i + batch_size] for i in range(0, len(safe_reviews), batch_size)]
        extract_stats["batches_used"] = len(batches)
        
        logger.info("theme_extraction_start", total_reviews=len(safe_reviews), num_batches=len(batches))
        
        all_batch_themes = []
        for idx, batch in enumerate(batches):
            logger.info("processing_batch", batch=idx+1, total=len(batches))
            try:
                batch_result = self._run_batch(batch)
                batch_themes = batch_result.get("themes", [])
                all_batch_themes.extend(batch_themes)
            except Exception as e:
                logger.error("batch_failed", batch=idx+1, error=str(e))
                # Continue other batches if one fails
        
        # Consolidation if multiple batches
        if len(batches) > 1 and all_batch_themes:
            logger.info("consolidating_themes", num_intermediate_themes=len(all_batch_themes))
            intermediate_str = json.dumps({"themes": all_batch_themes}, indent=2)
            try:
                final_result = self._call_llm_json(THEME_CONSOLIDATION_SYSTEM_PROMPT, intermediate_str)
                final_themes = final_result.get("themes", [])
            except Exception as e:
                logger.error("consolidation_failed", error=str(e))
                final_themes = all_batch_themes # Fallback to unmerged
        else:
            final_themes = all_batch_themes

        # Post-process: Validation, specific overlapping, max 5, etc.
        validated_themes, val_stats = ThemeValidator.validate_and_merge(final_themes, safe_reviews)
        
        # Add stats
        extract_stats["quotes_corrected"] = val_stats.get("quotes_corrected", 0)
        
        # Check EC-2.3, EC-2.9 etc if all positive or negative (Just rely on LLM for now)
        # Verify themes empty issue
        if not validated_themes:
            return {"themes": [], "warning": "No actionable reviews found"}

        finished_at = datetime.now(timezone.utc)
        
        # Window calculation
        dates = [datetime.fromisoformat(r["date"]) for r in valid_dates(safe_reviews) if r.get("date")]
        
        return {
            "run_date": finished_at.isoformat(),
            "review_window": {
                "start": min(dates).isoformat() if dates else "",
                "end": max(dates).isoformat() if dates else ""
            },
            "total_reviews_analyzed": extract_stats["total_reviews_analyzed"],
            "themes": validated_themes,
            "metadata": {
                "llm_provider": "groq",
                "llm_model": self.model,
                "batches_used": extract_stats["batches_used"],
                "pii_redactions": extract_stats["pii_redactions"],
                "quotes_corrected": extract_stats["quotes_corrected"],
                "non_english_skipped": extract_stats["non_english_skipped"],
                "duration_seconds": round((finished_at - started_at).total_seconds(), 2)
            }
        }

def valid_dates(reviews):
    return [r for r in reviews if r.get("date")]
