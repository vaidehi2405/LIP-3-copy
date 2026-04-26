"""
Theme Validator
Validates extracted themes from the LLM, resolves overlaps, validates quotes,
and flags issues requiring a retry.
"""

import structlog
from typing import List, Dict, Set, Tuple
from difflib import SequenceMatcher

logger = structlog.get_logger(__name__)

# List of vague words we want to penalize
VAGUE_WORDS = {"good", "bad", "general", "issue", "problem", "complaint", "app", "experience", "nice", "great", "worst", "bug"}


class ThemeValidator:
    """Consolidates and validates LLM extracted themes."""

    @classmethod
    def validate_and_merge(cls, themes: List[Dict], all_reviews: List[Dict]) -> Tuple[List[Dict], Dict]:
        """
        Main entry point for validation.
        1. Checks specificity
        2. Merges overlapping themes
        3. Validates quotes against actual reviews
        4. Truncates to max 5 themes

        Returns tuple of (Valid Themes, validation statistics).
        """
        stats = {
            "vague_themes_dropped": 0,
            "themes_merged": 0,
            "quotes_corrected": 0,
            "hallucinated_quotes_dropped": 0
        }

        if not themes:
            return [], stats

        # 1. Filter vague themes
        valid_themes = []
        for t in themes:
            if cls._score_specificity(t.get("theme_name", "")) >= 1.0:
                valid_themes.append(t)
            else:
                logger.warning("vague_theme_dropped", theme_name=t.get("theme_name"))
                stats["vague_themes_dropped"] += 1

        # 2. Merge overlapping themes (>20% overlap in review IDs)
        valid_themes = cls._merge_overlapping(valid_themes, overlap_threshold=0.20, stats=stats)

        # 3. Validate quotes
        input_review_dict = {r["review_id"]: r for r in all_reviews}
        for t in valid_themes:
            cls._validate_quote(t, input_review_dict, stats)

        # Sort by volume desc
        valid_themes.sort(key=lambda x: x.get("volume", 0), reverse=True)

        # 4. Cap at 5 themes (EC-2.1)
        if len(valid_themes) > 5:
            valid_themes = valid_themes[:5]

        return valid_themes, stats

    @staticmethod
    def _score_specificity(theme_name: str) -> float:
        """
        Calculates a basic specificity score.
        Returns 0.0 (too vague) to 5.0 (highly specific).
        For our boolean check, we just want it to be >= 1.0 to pass.
        """
        if not theme_name:
            return 0.0
        
        words = set(theme_name.lower().split())
        if not words:
            return 0.0
            
        vague_overlap = words.intersection(VAGUE_WORDS)
        
        # If the theme name is just "bad experience"
        if len(words) <= 2 and len(vague_overlap) == len(words):
            return 0.0 # Rejected
            
        # Specific names should have more words and fewer generic terms
        score = len(words) - (len(vague_overlap) * 1.5)
        return max(0.0, score)

    @classmethod
    def _merge_overlapping(cls, themes: List[Dict], overlap_threshold: float, stats: Dict) -> List[Dict]:
        """
        Merge themes that share more than `overlap_threshold` proportion of review_ids.
        """
        # We need a stable output list
        if not themes:
            return []

        merged_themes = []
        skip_indices = set()

        for i, t1 in enumerate(themes):
            if i in skip_indices:
                continue

            current_merged = t1
            for j in range(i + 1, len(themes)):
                if j in skip_indices:
                    continue
                
                t2 = themes[j]
                
                # Check overlap
                set1 = set(current_merged.get("review_ids", []))
                set2 = set(t2.get("review_ids", []))
                
                if not set1 or not set2:
                    continue

                intersection = len(set1.intersection(set2))
                min_len = min(len(set1), len(set2))
                
                if min_len > 0 and (intersection / min_len) > overlap_threshold:
                    # Merge them
                    skip_indices.add(j)
                    stats["themes_merged"] += 1
                    
                    # Keep more specific name
                    name1 = current_merged.get("theme_name", "")
                    name2 = t2.get("theme_name", "")
                    
                    chosen_name = name1 if len(name1) >= len(name2) else name2
                    
                    combined_ids = list(set1.union(set2))
                    
                    # Just keep current_merged quote for simplicity in merge
                    current_merged = {
                        "theme_name": chosen_name,
                        "description": current_merged.get("description", t2.get("description", "")),
                        "review_ids": combined_ids,
                        "sentiment": current_merged.get("sentiment", t2.get("sentiment")),
                        "volume": len(combined_ids),
                        "representative_quote": current_merged.get("representative_quote") or t2.get("representative_quote")
                    }

            merged_themes.append(current_merged)

        return merged_themes

    @staticmethod
    def _validate_quote(theme: Dict, all_reviews: Dict[str, Dict], stats: Dict):
        """
        Ensure the representative quote actually matches the source review text.
        Applies fuzzy match (if > 85% match, consider valid).
        If invalid or hallucinated, try to find a legitimate matching quote from the review_ids array.
        """
        quote_obj = theme.get("representative_quote")
        if not quote_obj:
            return

        review_id = quote_obj.get("review_id")
        llm_quote_text = quote_obj.get("quote", "")

        # Target valid review
        source_review = all_reviews.get(review_id)
        
        is_valid = False
        if source_review:
            actual_body = source_review.get("body", "")
            if llm_quote_text in actual_body:
                is_valid = True
            else:
                # Fuzzy matching (85% similarity)
                similarity = SequenceMatcher(None, llm_quote_text, actual_body).ratio()
                if similarity >= 0.85:
                    is_valid = True
                    # Correct it to the authentic text portion
                    # For simplicity, we just keep the quote as long as it's >85% since finding exact substring is hard
                    # But ideally we replace with a correct phrase

        if not is_valid:
            stats["quotes_corrected"] += 1
            logger.warning("hallucinated_quote_detected", theme=theme.get("theme_name"), review_id=review_id)
            
            # Fallback: try to select a quote from any of the review IDs
            fallback_found = False
            for rid in theme.get("review_ids", []):
                fallback_review = all_reviews.get(rid)
                if fallback_review and fallback_review.get("body"):
                    theme["representative_quote"] = {
                        "review_id": rid,
                        "quote": fallback_review["body"][:200] + "..." if len(fallback_review["body"]) > 200 else fallback_review["body"],
                        "rating": fallback_review.get("rating", 3)
                    }
                    fallback_found = True
                    break
            
            if not fallback_found:
                # Discard quote entirely if we can't find one
                stats["hallucinated_quotes_dropped"] += 1
                theme.pop("representative_quote", None)
