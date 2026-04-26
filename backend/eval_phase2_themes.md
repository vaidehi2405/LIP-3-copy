# Phase 2 Evaluation — Theme Extraction (LLM)

## Evaluation Criteria

### 1. Functional Correctness

| Test Case | Description | Expected Outcome | Priority |
|---|---|---|---|
| TC-2.1 | LLM groups reviews into ≤5 themes | Output contains 1–5 theme objects | P0 |
| TC-2.2 | Themes are feature-specific, not vague | No themes like "good", "bad", "general complaints" | P0 |
| TC-2.3 | Each theme has valid `review_ids` mapping | All `review_ids` exist in input dataset | P0 |
| TC-2.4 | Representative quote selected per theme | Quote is verbatim from an actual review | P0 |
| TC-2.5 | PII scrubbed from all output fields | No emails, phones, usernames, or device IDs in output | P0 |
| TC-2.6 | Theme output matches expected JSON schema | All required fields present and correctly typed | P0 |
| TC-2.7 | Sentiment correctly classified | Each theme has sentiment: `negative`, `positive`, or `mixed` | P1 |
| TC-2.8 | Volume counts are accurate | `volume` matches actual count of `review_ids` per theme | P1 |

### 2. Quality Metrics

| Metric | Target | Measurement Method |
|---|---|---|
| Theme specificity score | ≥ 4/5 on rubric | Manual review by evaluator OR LLM-as-judge |
| Theme distinctness | No two themes overlap > 20% in review_ids | Set intersection check |
| Quote representativeness | Quote matches theme sentiment | Manual spot-check |
| Action alignment | Themes map to identifiable product features | Manual review |
| Hallucination rate | 0 fabricated quotes | Cross-reference quotes against input reviews |

### 3. LLM Robustness

| Test Case | Description | Expected Outcome |
|---|---|---|
| TC-2.L1 | LLM returns malformed JSON | Parser retries with repair prompt; max 2 retries |
| TC-2.L2 | LLM returns >5 themes | Post-processor merges least significant themes to cap at 5 |
| TC-2.L3 | LLM returns vague theme names | Specificity validator rejects and re-prompts |
| TC-2.L4 | LLM API rate limit hit | Exponential backoff, max 3 retries per batch |
| TC-2.L5 | LLM API down entirely | Pipeline logs error and exits gracefully; no partial output saved |

---

## Edge Cases

### EC-2.1 — Very Few Reviews (< 5)
- **Scenario**: Only 2–4 reviews available after scraping (new app, niche market, or quiet week)
- **Expected Behavior**:
  - LLM still attempts theme extraction
  - May produce only 1–2 themes (fewer than usual)
  - If all reviews are on the same topic, output is 1 theme
  - Note in metadata: `"low_review_count_warning": true`
  - Phase 3 adapts to fewer themes (generates 1–2 theme note instead of 3)
- **Validation**: Feed 3 reviews (2 about payments, 1 about login); verify 1–2 themes produced, no crash

### EC-2.2 — All Reviews Are Positive
- **Scenario**: 100% 4–5 star reviews with no complaints
- **Expected Behavior**:
  - Themes reflect positive aspects (e.g., "Smooth onboarding experience", "Fast payment processing")
  - Sentiment for all themes set to `"positive"`
  - Action ideas pivot to enhancement/growth suggestions rather than fixes
  - Note explicitly signals: "No major negative patterns detected this week"
- **Validation**: Feed 50 reviews all rated 4–5 stars with positive text; verify themes are still specific and not just "app is great"

### EC-2.3 — All Reviews Are Negative With Same Complaint
- **Scenario**: 100 reviews all complaining about the same bug (e.g., "app crashes on login")
- **Expected Behavior**:
  - Single dominant theme extracted (e.g., "Login crash on Android 14")
  - Remaining themes (if any) are secondary patterns
  - Volume count for dominant theme ≈ 100
  - System does NOT artificially split one issue into multiple themes
- **Validation**: Feed 100 nearly identical complaints; verify 1 dominant theme, not 5 artificial splits

### EC-2.4 — Non-English Reviews Mixed In
- **Scenario**: 30% of reviews are in Hindi, Spanish, or other non-English languages
- **Expected Behavior**:
  - Option A (default): Non-English reviews are included; LLM processes multilingual input (GPT-4 handles this well)
  - Option B (configurable): Non-English reviews filtered out pre-LLM; count recorded in metadata as `"non_english_skipped": 45`
  - Theme names always in English regardless of input language
  - Quotes from non-English reviews translated to English with `[translated]` tag
- **Validation**: Mix 50 English + 20 Hindi + 10 Spanish reviews; verify themes are coherent and in English

### EC-2.5 — Reviews With Heavy PII
- **Scenario**: Users include their email, phone number, Aadhaar number, or username in review text
- **Expected Behavior**:
  - PII regex scrubber runs BEFORE sending to LLM
  - Patterns caught: `email@domain.com` → `[REDACTED_EMAIL]`, phone numbers → `[REDACTED_PHONE]`, 12-digit numbers → `[REDACTED_ID]`
  - LLM never sees raw PII
  - Output quotes also re-checked for PII (defense-in-depth)
  - PII occurrence count logged: `"pii_redactions": 7`
- **Validation**: Inject reviews with emails, phone numbers, and Aadhaar-like numbers; verify none appear in output

### EC-2.6 — LLM Returns Hallucinated Quotes
- **Scenario**: LLM fabricates a quote that doesn't exist in any input review
- **Expected Behavior**:
  - Quote validator cross-references every output quote against the input review corpus
  - Fuzzy match threshold: 85% similarity (handles minor LLM paraphrasing)
  - If quote < 85% match → replace with the actual closest-matching review
  - Metadata flags: `"quotes_corrected": 1`
- **Validation**: Intentionally use a prompt that encourages fabrication; verify validator catches and replaces

### EC-2.7 — Contradictory Reviews on Same Feature
- **Scenario**: 50 reviews love the new UI redesign, 50 reviews hate it
- **Expected Behavior**:
  - LLM creates a single theme with `sentiment: "mixed"` OR two separate themes (positive + negative)
  - If consolidated: theme description mentions the split (e.g., "UI redesign: divisive reception — praised for modern look, criticized for navigation changes")
  - Volume reflects total mentions across both sentiments
- **Validation**: Feed 50 positive + 50 negative reviews about same feature; verify coherent theme representation

### EC-2.8 — Token Limit Exceeded (Large Batch)
- **Scenario**: 500 reviews × average 100 words = 50,000 tokens (exceeds single-call context window for some models)
- **Expected Behavior**:
  - Batching strategy kicks in: split into batches of ~50 reviews each
  - Each batch produces intermediate themes
  - Consolidation call merges batch themes into final ≤5
  - Metadata records: `"batches_used": 10, "tokens_consumed": 45000`
- **Validation**: Feed 500 synthetic reviews; verify batching occurs and final output ≤5 themes

### EC-2.9 — Reviews Are Spam / Irrelevant
- **Scenario**: Reviews contain promotional spam, competitor mentions, or completely off-topic content
- **Expected Behavior**:
  - LLM is instructed to ignore spam/promotional content in the prompt
  - Spam reviews don't form their own theme
  - If >50% of reviews are spam, metadata flags: `"high_spam_ratio": true`
  - Remaining legitimate reviews are themed normally
  - If ALL reviews are spam, output: `{"themes": [], "warning": "No actionable reviews found"}`
- **Validation**: Mix 70% spam + 30% legitimate reviews; verify themes only cover legitimate content

### EC-2.10 — LLM Returns Overlapping Themes
- **Scenario**: LLM returns themes like "Payment failures" and "UPI payment not working" which are essentially the same
- **Expected Behavior**:
  - Theme validator checks pairwise overlap of `review_ids`
  - If overlap > 20%, merge the two themes
  - Keep the more specific theme name (e.g., "UPI payment not working" over "Payment failures")
  - Combined `review_ids` list is deduplicated
  - Volume recalculated after merge
- **Validation**: Craft prompt that produces overlapping themes; verify merger logic triggers

### EC-2.11 — LLM API Key Invalid / Expired
- **Scenario**: OpenAI/Gemini API key is expired, invalid, or missing
- **Expected Behavior**:
  - Clear error message: "LLM API authentication failed. Check your API key."
  - Pipeline halts at Phase 2 (no point continuing without themes)
  - No partial theme file written
  - Ledger records: `"status": "failed", "error": "LLM auth failure"`
- **Validation**: Set invalid API key; verify error message and clean exit

### EC-2.12 — Single Very Long Review (>5000 words)
- **Scenario**: One user writes a 5000-word essay review
- **Expected Behavior**:
  - Review truncated to first 500 words before LLM processing
  - Truncation logged: `"reviews_truncated": 1`
  - Original full text preserved in raw data store
  - Truncation doesn't break theme extraction for other reviews
- **Validation**: Inject one 5000-word review among 49 normal ones; verify truncation and correct theme output

---

## Evaluation Script Outline

```python
# tests/eval_phase2_themes.py

import pytest
from unittest.mock import patch, MagicMock
from src.themes.extractor import ThemeExtractor
from src.themes.validator import ThemeValidator
from src.themes.pii_scrubber import PIIScrubber

class TestThemeExtraction:
    def test_basic_extraction(self, sample_reviews_50):
        """TC-2.1: Reviews grouped into ≤5 themes."""
        pass
    
    def test_theme_specificity(self, sample_reviews_50):
        """TC-2.2: No vague themes like 'general issues'."""
        pass
    
    def test_review_id_mapping(self, sample_reviews_50):
        """TC-2.3: All review_ids in output exist in input."""
        pass
    
    def test_quote_verbatim(self, sample_reviews_50):
        """TC-2.4: Quotes match actual reviews (no hallucination)."""
        pass
    
    def test_schema_compliance(self, sample_reviews_50):
        """TC-2.6: Output matches expected JSON schema."""
        pass

class TestEdgeCases:
    def test_few_reviews(self, sample_reviews_3):
        """EC-2.1: Only 3 reviews still produces valid themes."""
        pass
    
    def test_all_positive(self, positive_reviews_50):
        """EC-2.2: All positive reviews produce positive themes."""
        pass
    
    def test_single_complaint(self, same_complaint_100):
        """EC-2.3: 100 identical complaints → 1 dominant theme."""
        pass
    
    def test_multilingual(self, multilingual_reviews):
        """EC-2.4: Mixed-language reviews produce English themes."""
        pass
    
    def test_pii_scrubbing(self, reviews_with_pii):
        """EC-2.5: PII removed before LLM, verified after."""
        pass
    
    def test_hallucinated_quotes(self):
        """EC-2.6: Fabricated quotes detected and replaced."""
        pass
    
    def test_contradictory_reviews(self, split_sentiment_reviews):
        """EC-2.7: Mixed sentiment handled as 'mixed' or split themes."""
        pass
    
    def test_large_batch_tokenization(self, sample_reviews_500):
        """EC-2.8: Batching triggers for >50 reviews."""
        pass
    
    def test_spam_reviews(self, spam_heavy_reviews):
        """EC-2.9: Spam reviews excluded from themes."""
        pass
    
    def test_overlapping_themes(self):
        """EC-2.10: Overlapping themes merged by validator."""
        pass
    
    def test_api_key_failure(self):
        """EC-2.11: Invalid API key → clean error and exit."""
        pass
    
    def test_long_review_truncation(self, one_long_review):
        """EC-2.12: 5000-word review truncated to 500 words."""
        pass

class TestPIIScrubber:
    def test_email_redaction(self):
        """Emails replaced with [REDACTED_EMAIL]."""
        pass
    
    def test_phone_redaction(self):
        """Phone numbers replaced with [REDACTED_PHONE]."""
        pass
    
    def test_id_number_redaction(self):
        """12-digit ID numbers replaced with [REDACTED_ID]."""
        pass
    
    def test_username_redaction(self):
        """@username patterns replaced with [REDACTED_USER]."""
        pass

class TestThemeValidator:
    def test_max_five_themes(self):
        """TC-2.1: Validator rejects >5 themes."""
        pass
    
    def test_specificity_scoring(self):
        """TC-2.2: Vague theme names scored low and re-prompted."""
        pass
    
    def test_overlap_detection(self):
        """EC-2.10: >20% review_id overlap triggers merge."""
        pass
    
    def test_volume_accuracy(self):
        """TC-2.8: Volume matches review_id count."""
        pass
```
