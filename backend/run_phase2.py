import json
import os
import structlog
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from src.themes.extractor import ThemeExtractor

# Configure structured logging
structlog.configure(
    processors=[
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ],
    wrapper_class=structlog.stdlib.BoundLogger,
    context_class=dict,
    logger_factory=structlog.PrintLoggerFactory(),
)

def run_phase_2(input_filepath: str):
    print(f"Loading reviews from {input_filepath}...")
    reviews = []
    with open(input_filepath, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip():
                reviews.append(json.loads(line))
                
    print(f"Loaded {len(reviews)} reviews. Starting extraction...")
    extractor = ThemeExtractor()
    result = extractor.extract_themes(reviews)
    
    week_key = Path(input_filepath).stem
    out_dir = Path("data/themes")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{week_key}.json"
    
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, indent=2, ensure_ascii=False)
        
    print("\n" + "="*60)
    print("Phase 2 Complete")
    print(f"Themes extracted: {len(result.get('themes', []))}")
    print(f"Output saved to: {out_path}")
    print("="*60 + "\n")
    
    for idx, theme in enumerate(result.get('themes', [])):
        print(f"Theme {idx+1}: {theme.get('theme_name')} (Volume: {theme.get('volume')})")
        print(f"  Description: {theme.get('description')}")
        quote = theme.get('representative_quote', {}).get('quote', 'N/A')
        print(f"  Quote: \"{quote}\"")
        print()

if __name__ == "__main__":
    run_phase_2(r"data\raw\2026-W16.jsonl")
