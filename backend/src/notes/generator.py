"""
Note Generator
Generates the Weekly App Review Pulse summary using the Groq API.
Handles parsing themes, LLM prompt retries, Markdown drafting, and HTML compilation.
"""

import os
import json
import time
import re
import markdown
import structlog
from datetime import datetime, timezone
import yaml
from groq import Groq, RateLimitError

from .templates import (
    NOTE_SYSTEM_PROMPT,
    NOTE_REPROMPT_OVER_LENGTH,
    NOTE_REPROMPT_VAGUE_ACTIONS,
    generate_header_summary
)
from .validator import NoteValidator

logger = structlog.get_logger(__name__)

def markdown_to_arial_html(md_string: str) -> str:
    """Converts markdown into clean HTML preserving Arial font, using strictly valid B, U, and I tags."""
    import re
    # Convert bold first
    text = re.sub(r'\*\*(.*?)\*\*', r'<b>\1</b>', md_string)
    text = re.sub(r'__(.*?)__', r'<b>\1</b>', text)
    
    lines = text.split('\n')
    html_lines = []
    
    for line in lines:
        if line.startswith("# "):
            title = line[2:].upper().strip()
            html_lines.append(f"<b>{title}</b>")
            html_lines.append("=" * len(title))
        elif line.startswith("## "):
            subtitle = line[3:].upper().strip()
            html_lines.append(f"<br><br><b><u>{subtitle}</u></b><br>")
        elif line.startswith("### "):
            # Sub-headings without bold in screenshot
            html_lines.append(f"<br>{line[4:].strip()}")
        elif line.startswith("> "):
            # Quotes -> Italics
            html_lines.append(f"<i>{line[2:].strip()}</i>")
        elif line.startswith("---"):
            pass
        else:
            html_lines.append(line)
            
    return '<br>\n'.join(html_lines)

class NoteGenerator:
    """Uses Groq LLaMA to convert extracted themes into a weekly summary note."""

    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        with open(config_path, "r") as f:
            config = yaml.safe_load(f)
            
        self.llm_config = config.get("llm", {})
        self.model = self.llm_config.get("model", "llama-3.3-70b-versatile")
        self.max_retries = self.llm_config.get("max_retries", 3)
        self.platforms = ["apple", "google"] # We can read this from metadata dynamically
        
        # Initialize Groq client
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key or api_key == "your_groq_api_key_here":
            logger.error("groq_api_key_invalid")
            raise ValueError("LLM API authentication failed. Check your API key.")
            
        self.client = Groq(api_key=api_key)

    def _call_llm_text(self, system_prompt: str, user_messages: list, temperature: float = 0.3) -> str:
        """Call Groq and return a markdown string, handling backoff."""
        messages = [{"role": "system", "content": system_prompt}]
        messages.extend(user_messages)

        for attempt in range(1, self.max_retries + 1):
            try:
                response = self.client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    # response_format not used for text output
                    max_tokens=2000,
                    temperature=temperature
                )
                return response.choices[0].message.content
            except RateLimitError as e:
                wait_time = 2 ** attempt
                logger.warning("groq_rate_limit", attempt=attempt, wait=wait_time)
                if attempt == self.max_retries:
                    raise
                time.sleep(wait_time)
            except Exception as e:
                logger.error("groq_api_error", attempt=attempt, error=str(e))
                if attempt == self.max_retries:
                    raise
                time.sleep(2)
        return ""

    @staticmethod
    def _apply_output_formatting(md_string: str) -> str:
        """
        Bypasses plain-text constraints by mapping characters to Unicode Mathematical Sans-Serif glyphs.
        This provides a 'faux' rich text appearance (bold, italic, underline) without using HTML/Markdown tags.
        """
        def to_bold(text: str) -> str:
            res = []
            for c in text:
                if 'A' <= c <= 'Z': res.append(chr(ord(c) - ord('A') + 0x1D5D4))
                elif 'a' <= c <= 'z': res.append(chr(ord(c) - ord('a') + 0x1D5EE))
                elif '0' <= c <= '9': res.append(chr(ord(c) - ord('0') + 0x1D7CE))
                else: res.append(c)
            return "".join(res)

        def to_italic(text: str) -> str:
            res = []
            for c in text:
                if 'A' <= c <= 'Z': res.append(chr(ord(c) - ord('A') + 0x1D608))
                elif 'a' <= c <= 'z': res.append('\u210E' if c == 'h' else chr(ord(c) - ord('a') + 0x1D622))
                else: res.append(c)
            return "".join(res)

        def to_underline(text: str) -> str:
            return "".join(c + '\u0332' for c in text)

        lines = md_string.split('\n')
        rich_lines = []
        
        for line in lines:
            while '**' in line:
                parts = line.split('**', 2)
                if len(parts) >= 3:
                    line = parts[0] + to_bold(parts[1]) + parts[2]
                else:
                    line = line.replace('**', '') 
                    
            if line.startswith("# "): rich_lines.append(f"\n{to_bold(line[2:].strip())}\n")
            elif line.startswith("## "): rich_lines.append(f"\n{to_underline(line[3:].strip())}\n")
            elif line.startswith("### "): rich_lines.append(f"\n{to_underline(line[4:].strip())}")
            elif line.startswith("> "): rich_lines.append(f"\n    {to_italic(line[2:].strip('\"'))}")
            elif line.startswith("---"): rich_lines.append("-" * 40)
            else: rich_lines.append(line)
                
        # Collapse accidental triple blank lines
        import re
        output = '\n'.join(rich_lines).strip()
        output = re.sub(r"\n{3,}", "\n\n", output)
        return output

    def process_themes(self, themes_data: dict) -> dict:
        """
        Takes the output dict from Phase 2 and generates the Weekly Note.
        Returns a dict with 'markdown', 'html', 'metadata'.
        """
        started_at = datetime.now(timezone.utc)
        
        raw_themes = themes_data.get("themes", [])
        if not raw_themes:
            logger.warning("no_themes_for_note")
            return {}

        # Tie breaking & Ranking (EC-3.6)
        # Volume descending, then by original index to keep determinism
        for idx, t in enumerate(raw_themes):
            t["_original_idx"] = idx
            
        # Tie break on volume -> lower sentiment if we had a numerical score, 
        # but since it's just 'negative' we just rely on stable sort
        raw_themes.sort(key=lambda x: (x.get("volume", 0), -x.get("_original_idx", 0)), reverse=True)
        
        # Take top 3 max
        top_themes = raw_themes[:3]

        # Prepare header variables
        # Format the dates
        window = themes_data.get("review_window", {})
        start_date = "N/A"
        end_date = "N/A"
        if window.get("start"):
            start_date = datetime.fromisoformat(window["start"]).strftime("%b %d")
        if window.get("end"):
            end_date = datetime.fromisoformat(window["end"]).strftime("%b %d, %Y")
            
        # We need the platforms that succeeded, check if 'google_unavailable' in metadata
        platforms = self.platforms
        if themes_data.get("metadata", {}).get("platforms_failed") == ["google"]:
            platforms = ["apple"]
            
        header_summary = generate_header_summary(raw_themes, platforms)
        
        # Filter down the quotes if needed (EC-3.7 short quotes logic)
        for t in top_themes:
            # Not strictly implementing the "shortest substantive quote search" here since 
            # phase 2 handles extracting the single quote. Phase 3 just uses it.
            pass

        themes_json = json.dumps(top_themes, indent=2)
        
        system_prompt = NOTE_SYSTEM_PROMPT.format(
            top_themes_json=themes_json,
            theme_count=len(top_themes),
            header_summary=header_summary,
            timestamp=started_at.strftime("%Y-%m-%d %H:%M UTC"),
            start_date=start_date,
            end_date=end_date
        )

        user_messages = [
            {"role": "user", "content": "Please generate the weekly note."}
        ]

        logger.info("generating_note_start")
        generated_md = self._call_llm_text(system_prompt, user_messages)

        # ====== Validation & Retry Loop ======
        max_correction_loops = 2
        
        for loop in range(max_correction_loops):
            needs_retry = False
            
            # 1. Word Count (EC-3.3)
            is_valid_len, word_count = NoteValidator.validate_word_count(generated_md)
            if not is_valid_len:
                logger.warning("word_count_exceeded", count=word_count, loop=loop)
                user_messages.extend([
                    {"role": "assistant", "content": generated_md},
                    {"role": "user", "content": NOTE_REPROMPT_OVER_LENGTH.format(word_count=word_count)}
                ])
                needs_retry = True
            
            # 2. Specificity (EC-3.4)
            if not needs_retry and not NoteValidator.check_actions_specificity(generated_md):
                logger.warning("generic_actions_detected", loop=loop)
                user_messages.extend([
                    {"role": "assistant", "content": generated_md},
                    {"role": "user", "content": NOTE_REPROMPT_VAGUE_ACTIONS}
                ])
                needs_retry = True

            if needs_retry:
                generated_md = self._call_llm_text(system_prompt, user_messages, temperature=0.1)
            else:
                break

        # Emergency fix if STILL over word count
        is_valid_len, word_count = NoteValidator.validate_word_count(generated_md)
        if not is_valid_len:
            logger.info("force_truncating_actions")
            generated_md = NoteValidator.force_truncate_actions(generated_md)

        # ====== Final Post-Processing ======
        # Strip PII (EC-3.5)
        safe_md, pii_caught = NoteValidator.check_pii(generated_md)
        
        # Verify Quotes
        safe_md, quote_corrections = NoteValidator.verify_quotes(safe_md, top_themes)

        formatted_text = self._apply_output_formatting(safe_md)
        html_body = f"""<div style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">{safe_md}</div>"""

        finished_at = datetime.now(timezone.utc)
        
        return {
            "markdown": safe_md,
            "html": html_body,
            "plain_text": safe_md,
            "formatted_html": formatted_text,  # using the same key so we don't have to change orchestrator
            "metadata": {
                "word_count": len(safe_md.split()),
                "pii_caught_in_note": pii_caught,
                "quote_validation_replacements": quote_corrections,
                "themes_included": len(top_themes),
                "duration_seconds": round((finished_at - started_at).total_seconds(), 2)
            }
        }
