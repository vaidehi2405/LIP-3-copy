"""
Note Templates for Phase 3
Contains LLM prompts and markdown formatting structures.
"""

NOTE_SYSTEM_PROMPT = """You are a product analyst writing a weekly review summary for a product team.

Given these themes (ranked by volume from highest to lowest):
{top_themes_json}

Write a summary note focusing on actionable product insights.
Follow these STRICT rules:
1. Include exactly {theme_count} theme(s). Each must have a simple bolded title, the mention count, sentiment, and the EXACT verbatim user quote provided.
2. Under "Suggested Actions", include exactly 3 numbered action ideas. Each action MUST start with a bolded specific screen, feature, or product flow (e.g., "**KYC Flow**: ..."). Do not use generic advice like "improve the experience."
3. If all themes are positive, focus the 3 actions on growth, marketing leverage, or feature expansion.
4. Total word count MUST be under 250 words.
5. Do not include personal identifiers or filler paragraphs.

Output the note as markdown only, following this exact structure (no backticks or preamble):

# Weekly App Review Pulse
{header_summary}

## Top Themes This Week

### 1. [Theme Name] ([volume] mentions, [sentiment])
> "[verbatim_quote]"

(Repeat for other themes...)

## Suggested Actions
1. **[Specific Feature/Screen]**: [Actionable advice]
2. **[Specific Feature/Screen]**: [Actionable advice]
3. **[Specific Feature/Screen]**: [Actionable advice]

---
_Auto-generated on {timestamp}. Covers reviews from {start_date} to {end_date}._
"""

NOTE_REPROMPT_OVER_LENGTH = """Your previous response violated the word count constraint. It was {word_count} words.
You MUST rewrite the note to be UNDER 250 words. Cut down the descriptions and action lengths, but keep the 3 actions and the verbatim quotes intact.
"""

NOTE_REPROMPT_VAGUE_ACTIONS = """Your previous response contained generic actions that did not specify a product feature or screen in bold at the start.
Rewrite the "Suggested Actions" section so that EVERY action starts with a bolded feature/screen.
Example of BAD: "1. Improve the payment experience to reduce timeout errors."
Example of GOOD: "1. **UPI Payment Screen**: Add retry button with clearer error messages for timeout failures."
"""

def generate_header_summary(themes: list, platforms: list) -> str:
    """Generate the dynamic header line based on themes and platforms."""
    total_reviews = sum(t.get("volume", 0) for t in themes)
    
    plat_str = ""
    if "apple" in platforms and "google" in platforms:
        plat_str = "App Store and Play Store"
    elif "apple" in platforms:
        plat_str = "App Store (Play Store unavailable this week)"
    elif "google" in platforms:
        plat_str = "Play Store (App Store unavailable this week)"
    else:
        plat_str = "multiple sources"
        
    all_positive = all(t.get("sentiment") == "positive" for t in themes) if themes else False
    
    msg = f"**{total_reviews} reviews analyzed** from {plat_str}."
    if all_positive:
        msg += " No major pain points detected this week — user sentiment is highly positive."
        
    return msg
