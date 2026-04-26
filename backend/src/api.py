from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# Enable CORS for the React dashboard
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

THEMES_DIR = Path("data/themes")
NOTES_DIR = Path("output/notes")


def _latest_theme_files() -> list[Path]:
    if not THEMES_DIR.exists():
        return []
    return sorted(THEMES_DIR.glob("*.json"))


def _safe_read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def _safe_percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "N/A"
    return f"{round((numerator / denominator) * 100)}%"


def _pct_delta(current: int, previous: int) -> tuple[str, str]:
    """Return human-readable % change and trend type.

    trendType values used by dashboard: up | down | neutral
    """
    if previous <= 0:
        return "New", "neutral"

    delta = ((current - previous) / previous) * 100
    if abs(delta) < 0.1:
        return "0%", "neutral"

    sign = "+" if delta > 0 else ""
    trend = f"{sign}{delta:.1f}%"
    return trend, ("up" if delta > 0 else "down")


def _parse_actions(note_path: Path) -> list[dict[str, Any]]:
    if not note_path.exists():
        return []

    actions: list[dict[str, Any]] = []
    with note_path.open("r", encoding="utf-8") as f:
        lines = f.readlines()

    in_actions = False
    for line in lines:
        stripped = line.strip()
        if stripped == "## Suggested Actions":
            in_actions = True
            continue
        if in_actions and stripped.startswith("## "):
            break

        if not in_actions:
            continue

        # Format: 1. **Feature**: Description
        match = re.match(r"^(\d+)\.\s+\*\*(.+?)\*\*:\s*(.+)$", stripped)
        if not match:
            continue

        _, feature, description = match.groups()
        lowered = description.lower()
        priority = "high" if any(k in lowered for k in ["fix", "crash", "error", "failure"]) else "medium"

        actions.append(
            {
                "id": len(actions) + 1,
                "priority": priority,
                "title": feature,
                "description": description,
                "category": "Engineering" if priority == "high" else "Product",
            }
        )

    return actions


def _format_date_range(theme_data: dict[str, Any]) -> str:
    window = theme_data.get("review_window", {})
    start = str(window.get("start", ""))[:10]
    end = str(window.get("end", ""))[:10]
    if start and end:
        return f"{start} - {end}"
    return "Date range unavailable"


def _dashboard_payload(current_file: Path, previous_file: Path | None) -> dict[str, Any]:
    theme_data = _safe_read_json(current_file)
    previous_data = _safe_read_json(previous_file) if previous_file else {}

    current_themes = theme_data.get("themes", [])
    previous_themes = previous_data.get("themes", [])

    total_reviews = int(theme_data.get("total_reviews_analyzed", 0))
    prev_reviews = int(previous_data.get("total_reviews_analyzed", 0)) if previous_data else 0

    total_mentions = sum(int(t.get("volume", 0)) for t in current_themes)
    positive_mentions = sum(int(t.get("volume", 0)) for t in current_themes if t.get("sentiment") == "positive")

    current_negative_issues = sum(1 for t in current_themes if t.get("sentiment") == "negative")
    prev_negative_issues = sum(1 for t in previous_themes if t.get("sentiment") == "negative")

    reviews_trend, reviews_trend_type = _pct_delta(total_reviews, prev_reviews)
    issues_trend, issues_trend_type = _pct_delta(current_negative_issues, prev_negative_issues)

    # Build action list from weekly note output if present.
    week_key = current_file.stem
    note_path = NOTES_DIR / week_key / "weekly_note.md"
    actions = _parse_actions(note_path)

    if not actions and current_themes:
        # Fallback suggested actions (derived from actual themes, no static/dummy card).
        for idx, theme in enumerate(current_themes[:3], start=1):
            actions.append(
                {
                    "id": idx,
                    "priority": "high" if theme.get("sentiment") == "negative" else "medium",
                    "title": theme.get("theme_name", "Theme follow-up"),
                    "description": f"Review {theme.get('volume', 0)} mentions for '{theme.get('theme_name', 'this theme')}' and prioritize next sprint tasks.",
                    "category": "Product",
                }
            )

    themes = []
    for idx, t in enumerate(current_themes, start=1):
        review_ids = t.get("review_ids", [])
        apple_count = sum(1 for rid in review_ids if str(rid).startswith("apple"))
        google_count = sum(1 for rid in review_ids if str(rid).startswith("google"))
        platforms = []
        if apple_count > 0:
            platforms.append("apple")
        if google_count > 0:
            platforms.append("google")

        themes.append(
            {
                "id": idx,
                "name": t.get("theme_name", "Unnamed theme"),
                "sentiment": t.get("sentiment", "neutral"),
                "mentions": int(t.get("volume", 0)),
                "confidence": t.get("confidence", "N/A"),
                "platforms": platforms,
                "platform_counts": {"apple": apple_count, "google": google_count},
                "quote": t.get("representative_quote", {}).get("quote", "No representative quote available."),
            }
        )

    top_negative = max(
        (t for t in themes if t["sentiment"] == "negative"),
        key=lambda x: x["mentions"],
        default=None,
    )

    alert = None
    if top_negative and top_negative["mentions"] > 0:
        alert = {
            "message": f"Action required: '{top_negative['name']}' has {top_negative['mentions']} negative mentions this week.",
            "cta": "Review Theme",
        }

    return {
        "weekKey": week_key,
        "dateRange": _format_date_range(theme_data),
        "alert": alert,
        "metrics": [
            {
                "label": "Reviews Analyzed",
                "value": str(total_reviews),
                "trend": reviews_trend,
                "trendType": reviews_trend_type,
                "context": "vs previous week",
            },
            {
                "label": "Themes Identified",
                "value": str(len(current_themes)),
                "trend": "Current week",
                "trendType": "neutral",
                "context": "LLM extracted themes",
            },
            {
                "label": "Positive Sentiment",
                "value": _safe_percent(positive_mentions, total_mentions),
                "trend": "Based on mention volume",
                "trendType": "neutral",
                "context": f"{positive_mentions}/{total_mentions} mentions",
            },
            {
                "label": "Critical Issues Detected",
                "value": str(current_negative_issues),
                "trend": issues_trend,
                "trendType": issues_trend_type,
                "context": "Negative sentiment themes",
            },
        ],
        "themes": themes,
        "actions": actions,
    }


@app.get("/api/latest")
async def get_latest_data():
    files = _latest_theme_files()
    if not files:
        raise HTTPException(
            status_code=404,
            detail="No theme data found. Run the pipeline (Phase 2+) to generate data/themes/<week>.json first.",
        )

    current_file = files[-1]
    previous_file = files[-2] if len(files) > 1 else None
    return _dashboard_payload(current_file, previous_file)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8000)
