"""
Global Pipeline Orchestrator.
Coordinates Phase 1 (Scrape) -> Phase 2 (Themes) -> Phase 3 (Notes) -> Phase 4 (Delivery).
"""

import os
import json
import yaml
import structlog
from datetime import datetime, timezone
from pathlib import Path

from src.scraper.orchestrator import ScraperOrchestrator
from src.themes.extractor import ThemeExtractor
from src.notes.generator import NoteGenerator
from src.delivery.rest_client import DeliveryClient
from src.delivery.ledger import RunLedger

logger = structlog.get_logger(__name__)

class PipelineOrchestrator:
    def __init__(self, config_path: str = "config/pipeline_config.yaml"):
        with open(config_path, "r") as f:
            self.config = yaml.safe_load(f)
            
        self.week_key = datetime.now(timezone.utc).strftime("%Y-W%W")
        
        # Delivery Config
        email_config = self.config.get("email", {})
        self.dry_run = email_config.get("dry_run", True)
        self.to_address = email_config.get("to_address")
        self.doc_id = email_config.get("doc_id")

        self.ledger = RunLedger()
        self.delivery_client = DeliveryClient(dry_run=self.dry_run)

    def run_full_pipeline(self):
        """Execute all 4 pipeline phases sequentially."""
        logger.info("pipeline_started", week_key=self.week_key, dry_run=self.dry_run)
        
        # Check idempotency first (if not dry run)
        if not self.dry_run and not self.ledger.should_send(self.week_key):
            logger.info("pipeline_skip", reason="Already sent this week", week_key=self.week_key)
            return

        # ==========================================
        # Phase 1: Data Scraping
        # ==========================================
        logger.info("phase_1_started")
        scraper = ScraperOrchestrator(self.config.get("scraper", {}))
        scrape_result = scraper.run(output_dir="data/raw", week_key=self.week_key)
        reviews = scrape_result.get("reviews", [])
        
        if not reviews:
            logger.warning("pipeline_abort", reason="No reviews scraped")
            self.ledger.record_run(self.week_key, "failed", "No reviews scraped")
            return

        # ==========================================
        # Phase 2: Theme Extraction
        # ==========================================
        logger.info("phase_2_started", raw_reviews_count=len(reviews))
        theme_extractor = ThemeExtractor(config_path="config/pipeline_config.yaml")
        themes_data = theme_extractor.extract_themes(reviews)
        
        # Inject metadata from phase 1
        themes_data["metadata"] = scrape_result.get("metadata", {})
        
        # Save themes explicitly
        themes_dir = Path("data/themes")
        themes_dir.mkdir(parents=True, exist_ok=True)
        themes_filepath = themes_dir / f"{self.week_key}.json"
        with open(themes_filepath, "w", encoding="utf-8") as f:
            json.dump(themes_data, f, indent=2, ensure_ascii=False)

        if not themes_data.get("themes"):
            logger.warning("pipeline_abort", reason="No themes generated")
            self.ledger.record_run(self.week_key, "failed", "No themes generated")
            return

        # ==========================================
        # Phase 3: Note Generation
        # ==========================================
        logger.info("phase_3_started", themes_count=len(themes_data["themes"]))
        note_generator = NoteGenerator(config_path="config/pipeline_config.yaml")
        note_data = note_generator.process_themes(themes_data)
        
        if not note_data:
            logger.warning("pipeline_abort", reason="Note generator failed")
            self.ledger.record_run(self.week_key, "failed", "Note generation failed")
            return

        # Save note outputs
        output_dir = Path("output/notes") / self.week_key
        if self.dry_run:
            output_dir = Path("output/dry_run") / self.week_key
            
        output_dir.mkdir(parents=True, exist_ok=True)
        
        md_path = output_dir / "weekly_note.md"
        with open(md_path, "w", encoding="utf-8") as f:
            f.write(note_data["markdown"])
            
        html_path = output_dir / "weekly_note.html"
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(note_data["html"])
            
        txt_path = output_dir / "weekly_note_beautiful.txt"
        with open(txt_path, "w", encoding="utf-8") as f:
            f.write(note_data["plain_text"])

        # ==========================================
        # Phase 4: Delivery
        # ==========================================
        logger.info("phase_4_started")
        
        # Generate the precise Subject Title
        subject_title = "Weekly App Review Pulse"
        
        # Create Email Draft
        if self.to_address:
            draft_success = self.delivery_client.create_email_draft(
                to_email=self.to_address,
                subject=subject_title,
                html_body=note_data["formatted_html"]
            )
            if not draft_success:
                logger.error("draft_creation_failed")
                
        # Append to Google Doc
        if self.doc_id:
            doc_success = self.delivery_client.append_to_doc(
                doc_id=self.doc_id,
                markdown_content=note_data["formatted_html"]
            )
            if not doc_success:
                logger.error("doc_append_failed")

        # Record LEDGER
        final_status = "dry_run" if self.dry_run else "sent"
        
        self.ledger.record_run(
            week_key=self.week_key, 
            status=final_status,
            meta={
                "reviews_analyzed": len(reviews),
                "word_count": note_data["metadata"]["word_count"],
                "pii_caught": note_data["metadata"]["pii_caught_in_note"]
            }
        )
        
        logger.info("pipeline_complete", week_key=self.week_key, status=final_status)

if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    
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

    orchestrator = PipelineOrchestrator()
    orchestrator.run_full_pipeline()
