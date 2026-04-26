import json
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

from src.notes.generator import NoteGenerator

def run_phase_3(input_filepath: str):
    print(f"Loading themes from {input_filepath}...")
    with open(input_filepath, "r", encoding="utf-8") as f:
        themes_data = json.load(f)
                
    print(f"Loaded themes successfully. Generating note...")
    generator = NoteGenerator()
    result = generator.process_themes(themes_data)
    
    week_key = Path(input_filepath).stem
    out_dir = Path("output/notes") / week_key
    out_dir.mkdir(parents=True, exist_ok=True)
    
    md_path = out_dir / "weekly_note.md"
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(result["markdown"])
        
    html_path = out_dir / "weekly_note.html"
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(result["html"])
        
    print("\n" + "="*60)
    print("Phase 3 Complete")
    print(f"Word Count: {result['metadata']['word_count']}")
    print(f"Output saved to: {md_path} and .html")
    print("="*60 + "\n")
    print(result["markdown"])
    print("\n" + "="*60)

if __name__ == "__main__":
    run_phase_3(r"data\themes\2026-W16.json")
