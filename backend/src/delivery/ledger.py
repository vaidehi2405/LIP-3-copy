"""
Run Ledger
Tracks pipeline runs to prevent duplicate email/doc delivery.
"""

import json
import os
import time
from pathlib import Path
from datetime import datetime, timezone
import structlog
import uuid

logger = structlog.get_logger(__name__)

class RunLedger:
    def __init__(self, filepath: str = "run_ledger.json"):
        self.filepath = Path(filepath)
        self._ensure_exists()

    def _ensure_exists(self):
        """Creates the ledger if it doesn't exist or is corrupted."""
        if not self.filepath.exists():
            self._write_empty()
        else:
            try:
                with open(self.filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "runs" not in data:
                        self._write_empty()
            except json.JSONDecodeError:
                logger.warning("corrupt_ledger_found", action="creating_backup")
                backup = f"{self.filepath}.corrupted.{int(time.time())}"
                os.rename(self.filepath, backup)
                self._write_empty()

    def _write_empty(self):
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump({"runs": []}, f, indent=2)

    def should_send(self, week_key: str) -> bool:
        """Returns True if this week_key has not been successfully 'sent'."""
        with open(self.filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
            for run in data.get("runs", []):
                if run.get("week_key") == week_key and run.get("status") in ("sent", "delivered"):
                    return False
        return True

    def record_run(self, week_key: str, status: str, error: str = None, meta: dict = None):
        """Records a completed (or failed) run snippet to the ledger."""
        run_record = {
            "run_id": str(uuid.uuid4()),
            "week_key": week_key,
            "run_date": datetime.now(timezone.utc).isoformat(),
            "status": status,
        }
        if error:
            run_record["error"] = error
        if meta:
            run_record.update(meta)

        # Simple file locking could be used here if concurrency is a real concern, 
        # but for a single scheduled Github Action, standard append is fine.
        data = {"runs": []}
        try:
            with open(self.filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            pass
            
        data["runs"].append(run_record)
        
        with open(self.filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            
        logger.info("ledger_updated", week_key=week_key, status=status)
