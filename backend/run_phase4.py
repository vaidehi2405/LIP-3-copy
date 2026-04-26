"""Quick test: run Phase 4 delivery only, using the note already on disk."""
import json, yaml, structlog
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from src.delivery.rest_client import DeliveryClient
from src.delivery.ledger import RunLedger

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

with open("config/pipeline_config.yaml") as f:
    config = yaml.safe_load(f)

email_cfg = config["email"]
week_key = "2026-W16"

# Load existing note
md_path = Path("output/notes") / week_key / "weekly_note.md"
html_path = Path("output/notes") / week_key / "weekly_note.html"

if not md_path.exists() or not html_path.exists():
    print(f"ERROR: Note files not found at {md_path}. Run Phase 3 first.")
    exit(1)

md_content = md_path.read_text(encoding="utf-8")
html_content = html_path.read_text(encoding="utf-8")

from src.notes.generator import NoteGenerator
requested_html = NoteGenerator._apply_output_formatting(md_content)

print(f"Loaded note: {len(md_content)} chars (md), {len(requested_html)} chars (html)")
print(f"Sending to: {email_cfg['to_address']}")
print(f"Doc ID: {email_cfg['doc_id']}")
print(f"Dry run: {email_cfg['dry_run']}")
print()

client = DeliveryClient(dry_run=email_cfg["dry_run"])

# 1. Create email draft
print(">>> Creating email draft...")
draft_ok = client.create_email_draft(
    to_email=email_cfg["to_address"],
    subject="Weekly App Review Pulse — Week 16, 2026",
    html_body=requested_html
)
print(f"Draft result: {'SUCCESS' if draft_ok else 'FAILED'}")

# 2. Append to Google Doc
print("\n>>> Appending to Google Doc...")
doc_ok = client.append_to_doc(
    doc_id=email_cfg["doc_id"],
    markdown_content=requested_html
)
print(f"Doc append result: {'SUCCESS' if doc_ok else 'FAILED'}")
