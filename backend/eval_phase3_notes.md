# Phase 3 Evaluation — Weekly Note Generation

## Evaluation Criteria

### 1. Functional Correctness

| Test Case | Description | Expected Outcome | Priority |
|---|---|---|---|
| TC-3.1 | Note contains exactly 3 themes | Three `###` theme sections present | P0 |
| TC-3.2 | Word count ≤ 250 | `len(note.split()) <= 250` | P0 |
| TC-3.3 | One verbatim quote per theme | Quotes match Phase 2 `representative_quotes` | P0 |
| TC-3.4 | Exactly 3 action ideas | Three numbered actions in "Suggested Actions" | P0 |
| TC-3.5 | Actions reference specific features | Each action bold-names a screen, flow, or feature | P0 |
| TC-3.6 | No PII in output | Regex scan passes for emails, phones, IDs | P0 |
| TC-3.7 | Themes ranked by volume | Theme 1 has highest `volume`, Theme 3 lowest | P1 |
| TC-3.8 | Markdown format correct | Valid markdown; renders correctly in email and viewer | P1 |
| TC-3.9 | HTML version generated | HTML output matches markdown content | P1 |
| TC-3.10 | Plain text fallback generated | Text version strips formatting but preserves content | P2 |

### 2. Quality Metrics

| Metric | Target | Measurement Method |
|---|---|---|
| Readability score | Flesch-Kincaid Grade ≤ 10 | `textstat` library |
| Scan time | < 2 minutes for average reader | Estimated from word count (250 words ≈ 1 min) |
| Action specificity | 100% reference a named feature | Manual review |
| Quote accuracy | 100% verbatim from input | Exact string match |
| Formatting consistency | Matches template on every run | Regex pattern matching |

---

## Edge Cases

### EC-3.1 — Only 1–2 Themes Available From Phase 2
- **Scenario**: Phase 2 produced only 1 or 2 themes (because of very few reviews or homogeneous content)
- **Expected Behavior**:
  - Note adapts to available themes (1 or 2 instead of 3)
  - Section header adjusts: "Top Theme This Week" (singular) or "Top 2 Themes This Week"
  - Action ideas still total 3 — remaining actions are forward-looking suggestions even if only 1 theme exists
  - Word count likely well under 250 — this is acceptable
  - No padding with filler content
- **Validation**: Feed Phase 3 with 1-theme input; verify valid note structure, no crash, and word count compliance

### EC-3.2 — All Themes Are Positive (No Complaints)
- **Scenario**: Phase 2 produced 5 themes, all with `sentiment: "positive"`
- **Expected Behavior**:
  - Note tone shifts from "things to fix" to "what's working well"
  - Action ideas pivot to: growth amplification, feature expansion, marketing leverage
  - E.g., "**Onboarding flow**: Highlight the streamlined signup in Play Store screenshots to improve conversion"
  - Note explicitly states: "No major pain points detected this week"
  - Word count still ≤ 250
- **Validation**: Feed all-positive theme set; verify tone is growth-oriented, not artificially negative

### EC-3.3 — LLM Generates Note Exceeding 250 Words
- **Scenario**: First LLM attempt produces 310 words
- **Expected Behavior**:
  - Validator detects word count violation
  - Re-prompts LLM with explicit instruction: "Previous output was {310} words. Rewrite to be under 250 words. Cut description length, not themes or actions."
  - Maximum 2 re-prompts
  - If still over after 2 retries: post-process by truncating action descriptions to single sentences
  - Final output guaranteed ≤ 250 words
- **Validation**: Use a prompt variant that consistently produces >250 words; verify re-prompt triggers and final compliance

### EC-3.4 — LLM Generates Generic Action Ideas
- **Scenario**: Actions say "Improve the user experience" or "Fix the bugs" instead of naming specific features
- **Expected Behavior**:
  - Validator checks each action for a bolded feature/screen reference
  - If action lacks a specific reference → re-prompt with examples:
    > "BAD: 'Improve the payment experience.' GOOD: '**UPI Payment Screen**: Add retry button with clearer error messages for timeout failures.'"
  - Feature names should come from the themes (e.g., if theme is about "KYC document upload", action should mention "KYC Upload Screen")
- **Validation**: Mock LLM returning vague actions; verify validator rejects and re-prompts

### EC-3.5 — Quotes Contain Residual PII
- **Scenario**: Despite Phase 2 PII scrubbing, a quote still contains a phone number or email
- **Expected Behavior**:
  - Phase 3 runs its own PII regex scan on the final note output
  - Any detected PII replaced with `[REDACTED]`
  - If more than 2 PII hits in one note → flag for manual review and log WARNING
  - PII count recorded in metadata: `"pii_caught_in_note": 1`
- **Validation**: Inject a quote with `"call me at 9876543210"` into Phase 3 input; verify it's redacted in output

### EC-3.6 — Theme Volume Tie (Two Themes Have Same Count)
- **Scenario**: Theme A has 35 mentions, Theme B has 35 mentions, Theme C has 20 mentions
- **Expected Behavior**:
  - Tie-breaking rule: prefer theme with lower average rating (more urgent negative signal)
  - If still tied: prefer theme that appeared first in Phase 2 output (stable sort)
  - Ranking order is deterministic and reproducible
- **Validation**: Feed themes with identical volumes; verify consistent ranking across multiple runs

### EC-3.7 — Extremely Short Reviews Yield Uninformative Quotes
- **Scenario**: Best available quote for a theme is just "Bad. Fix it." (2 words)
- **Expected Behavior**:
  - Quote is still used if it's the most representative
  - Note generator selects the longest substantive quote (> 10 words) as primary choice
  - If no quote > 10 words exists for a theme, use the best available and note in metadata: `"short_quotes": ["theme_001"]`
  - Never fabricate a longer version of a real quote
- **Validation**: Feed themes where all quotes are under 10 words; verify shortest quote used, no fabrication

### EC-3.8 — Markdown Rendering Issues in Email Clients
- **Scenario**: Gmail strips markdown formatting; Outlook renders `###` as plain text
- **Expected Behavior**:
  - HTML version is generated from markdown using a converter (`markdown` library)
  - HTML version uses inline CSS (no external stylesheets) for maximum email client compatibility
  - Plain text version provided as MIME multipart fallback
  - HTML tested against common email client rendering (Gmail, Outlook, Apple Mail)
- **Validation**: Convert note to HTML; verify inline styles applied and no external CSS references

### EC-3.9 — Week With Mixed Platform Data (Apple Only or Google Only)
- **Scenario**: Phase 1 only scraped Apple reviews (Google was unavailable)
- **Expected Behavior**:
  - Note header adjusts: "**{total_reviews} reviews analyzed** from App Store (Play Store unavailable this week)"
  - Themes and actions are still generated from available data
  - No false claims about Play Store data
  - Metadata: `"platforms": ["apple"], "google_unavailable": true`
- **Validation**: Feed single-platform theme data; verify note header reflects actual data source

### EC-3.10 — Unicode and Special Characters in Quotes
- **Scenario**: Quote contains emojis (🔥❌💀), non-Latin characters, curly quotes, or special symbols
- **Expected Behavior**:
  - Unicode characters preserved as-is in markdown and HTML output
  - Emojis render correctly in email (UTF-8 encoding enforced)
  - Curly quotes (`"` `"`) not converted to straight quotes (preserves original)
  - Special characters properly HTML-escaped in HTML version
- **Validation**: Inject quotes with emojis, Hindi text, and curly quotes; verify correct rendering in markdown and HTML

---

## Evaluation Script Outline

```python
# tests/eval_phase3_notes.py

import pytest
from src.notes.generator import NoteGenerator
from src.notes.validator import NoteValidator

class TestNoteGeneration:
    def test_three_themes_present(self, standard_themes_5):
        """TC-3.1: Note contains exactly 3 theme sections."""
        pass
    
    def test_word_count_limit(self, standard_themes_5):
        """TC-3.2: Output ≤ 250 words."""
        pass
    
    def test_verbatim_quotes(self, standard_themes_5):
        """TC-3.3: Quotes match Phase 2 representative_quotes exactly."""
        pass
    
    def test_three_actions(self, standard_themes_5):
        """TC-3.4: Exactly 3 action items present."""
        pass
    
    def test_actions_reference_features(self, standard_themes_5):
        """TC-3.5: Each action names a specific screen/feature."""
        pass
    
    def test_no_pii(self, standard_themes_5):
        """TC-3.6: No PII in final output."""
        pass
    
    def test_volume_ranking(self, standard_themes_5):
        """TC-3.7: Themes ordered by descending volume."""
        pass
    
    def test_markdown_validity(self, standard_themes_5):
        """TC-3.8: Output is valid markdown."""
        pass
    
    def test_html_generation(self, standard_themes_5):
        """TC-3.9: HTML version generated correctly."""
        pass

class TestEdgeCases:
    def test_single_theme(self, single_theme):
        """EC-3.1: Note works with only 1 theme."""
        pass
    
    def test_two_themes(self, two_themes):
        """EC-3.1: Note works with only 2 themes."""
        pass
    
    def test_all_positive_themes(self, positive_themes):
        """EC-3.2: Positive-only themes → growth-oriented actions."""
        pass
    
    def test_word_count_retry(self, long_themes):
        """EC-3.3: Word count violation triggers re-prompt."""
        pass
    
    def test_generic_action_rejection(self):
        """EC-3.4: Vague actions rejected and re-prompted."""
        pass
    
    def test_residual_pii(self, themes_with_pii_quotes):
        """EC-3.5: PII in quotes caught at Phase 3."""
        pass
    
    def test_volume_tie_breaking(self, tied_volume_themes):
        """EC-3.6: Deterministic ranking on volume ties."""
        pass
    
    def test_short_quotes(self, themes_with_short_quotes):
        """EC-3.7: Short quotes handled; no fabrication."""
        pass
    
    def test_html_email_compatibility(self, standard_themes_5):
        """EC-3.8: HTML uses inline CSS, no external refs."""
        pass
    
    def test_single_platform_note(self, apple_only_themes):
        """EC-3.9: Note header reflects single-platform data."""
        pass
    
    def test_unicode_in_quotes(self, themes_with_unicode_quotes):
        """EC-3.10: Emojis and special chars preserved."""
        pass

class TestNoteValidator:
    def test_word_count_check(self):
        """Validator correctly counts words."""
        pass
    
    def test_pii_regex_patterns(self):
        """Validator catches emails, phones, IDs."""
        pass
    
    def test_theme_count_check(self):
        """Validator ensures 1-3 themes in output."""
        pass
    
    def test_action_specificity_check(self):
        """Validator ensures bolded feature references."""
        pass
    
    def test_quote_verification(self):
        """Validator cross-checks quotes against input."""
        pass
```
