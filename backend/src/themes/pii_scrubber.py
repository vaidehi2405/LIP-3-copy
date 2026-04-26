"""
PII Scrubber
Implements defense-in-depth regex scrubbing to remove Personally Identifiable Information
from raw app reviews before they are sent to the LLM.
"""

import re
import structlog
from typing import Optional, Dict, Tuple

logger = structlog.get_logger(__name__)


class PIIScrubber:
    """
    Scrub PII (Emails, Phone numbers, Identifiers, Usernames) from text
    using regex patterns. Replaces matches with standard placeholders.
    """

    # Regex Patterns
    # Basic email pattern
    EMAIL_PATTERN = re.compile(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", re.IGNORECASE)
    
    # Phone numbers (Indian/US focus + international) - simplistic but catches most formatted + raw numbers
    # Watches for 10 digits or numbers with + and country codes.
    PHONE_PATTERN = re.compile(
        # Matches: +91 9999999999 | 999-999-9999 | 9999999999 | +1 999 999 9999
        r"(?:\+?\d{1,3}[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)",
        re.IGNORECASE
    )

    # Identifiers: 12-digit (like Aadhaar), 10-char alphanumeric (like PAN)
    ID_PATTERN = re.compile(
        r"\b(?:\d{4}[-\s]?\d{4}[-\s]?\d{4}|[A-Z]{5}[0-9]{4}[A-Z]{1})\b",
        re.IGNORECASE
    )

    # Social media-style Usernames / Handles starting with @
    # E.g. @john_doe
    USERNAME_PATTERN = re.compile(r"(?<!\w)@[A-Za-z0-9_.-]+", re.IGNORECASE)

    @classmethod
    def scrub_text(cls, text: str) -> Tuple[str, Dict[str, int]]:
        """
        Scrub a single text string of PII.

        Returns:
            Tuple[str, dict]: 
                - The scrubbed text
                - A dictionary of redaction counts (e.g. {'emails': 1, 'phones': 0})
        """
        if not text:
            return "", {"emails": 0, "phones": 0, "ids": 0, "usernames": 0}

        scrubbed = text
        stats = {"emails": 0, "phones": 0, "ids": 0, "usernames": 0}

        # Sub emails
        scrubbed, stats["emails"] = cls.EMAIL_PATTERN.subn("[REDACTED_EMAIL]", scrubbed)
        
        # Sub phone numbers
        scrubbed, stats["phones"] = cls.PHONE_PATTERN.subn("[REDACTED_PHONE]", scrubbed)
        
        # Sub Identifiers (Aadhaar / PAN)
        scrubbed, stats["ids"] = cls.ID_PATTERN.subn("[REDACTED_ID]", scrubbed)
        
        # Sub usernames
        scrubbed, stats["usernames"] = cls.USERNAME_PATTERN.subn("[REDACTED_USER]", scrubbed)

        total_redactions = sum(stats.values())
        if total_redactions > 0:
            logger.debug("pii_scrubbed", redactions=total_redactions, stats=stats)

        return scrubbed, stats

    @classmethod
    def scrub_reviews(cls, reviews: list[dict]) -> Tuple[list[dict], Dict[str, int]]:
        """
        Scrub a batch of reviews in-place (or creates new dicts to be safe).
        Targets the 'body' and 'title' fields.

        Returns:
            Tuple containing the scrubbed reviews and total redaction stats across the batch.
        """
        scrubbed_reviews = []
        total_stats = {"emails": 0, "phones": 0, "ids": 0, "usernames": 0}

        for review in reviews:
            scrub_review = review.copy()
            
            if scrub_review.get("body"):
                new_body, b_stats = cls.scrub_text(scrub_review["body"])
                scrub_review["body"] = new_body
                for k, v in b_stats.items():
                    total_stats[k] += v
                    
            if scrub_review.get("title"):
                new_title, t_stats = cls.scrub_text(scrub_review["title"])
                scrub_review["title"] = new_title
                for k, v in t_stats.items():
                    total_stats[k] += v

            scrubbed_reviews.append(scrub_review)

        # Log batch summary if any PII was found
        total_pii = sum(total_stats.values())
        if total_pii > 0:
            logger.info("batch_pii_scrubbed", total_pii_redacted=total_pii, stats=total_stats)

        return scrubbed_reviews, total_stats
