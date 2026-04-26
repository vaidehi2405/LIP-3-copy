# Phase 4 Evaluation — Email Delivery

## Evaluation Criteria

### 1. Functional Correctness

| Test Case | Description | Expected Outcome | Priority |
|---|---|---|---|
| TC-4.1 | Email sent via SMTP | Email received by recipient with correct subject and body | P0 |
| TC-4.2 | Duplicate prevention (same week) | Second run for same `week_key` does NOT send email | P0 |
| TC-4.3 | Dry-run mode | Email composed but NOT sent; saved to `output/dry_run/` | P0 |
| TC-4.4 | Run ledger updated | Ledger records `run_id`, `week_key`, `status`, `recipients` | P0 |
| TC-4.5 | Multipart email (HTML + text) | Email contains both HTML and plain text MIME parts | P1 |
| TC-4.6 | Credentials from env vars | SMTP config read from `.env`; nothing hardcoded | P0 |
| TC-4.7 | TLS/SSL encryption | Connection uses STARTTLS or SSL | P1 |
| TC-4.8 | Subject line format | Subject: "Weekly App Review Pulse — {week_date_range}" | P2 |
| TC-4.9 | CC recipients supported | `EMAIL_CC` env var adds CC recipients | P2 |

### 2. Reliability Metrics

| Metric | Target | Measurement Method |
|---|---|---|
| Delivery success rate | 100% on valid SMTP config | Log analysis |
| Ledger consistency | Every run recorded, no orphaned entries | Ledger audit script |
| Dry-run fidelity | Dry-run output identical to sent version | Diff comparison |
| Idempotency | Re-runs never send duplicates | Ledger + inbox check |

---

## Edge Cases

### EC-4.1 — SMTP Credentials Missing or Invalid
- **Scenario**: `SMTP_USER` or `SMTP_PASSWORD` is empty, unset, or wrong
- **Expected Behavior**:
  - Pipeline detects missing credentials BEFORE attempting connection
  - Clear error: `"Email delivery failed: SMTP_PASSWORD not set in environment"`
  - For wrong credentials: SMTP auth failure caught → error logged with `"SMTP auth error: 535 Authentication failed"`
  - Ledger records: `"status": "failed", "error": "SMTP auth failure"`
  - Note is still saved to disk (Phases 1–3 output preserved)
- **Validation**: Unset `SMTP_PASSWORD`; verify error message and ledger entry; confirm note file exists

### EC-4.2 — SMTP Server Unreachable
- **Scenario**: Network down, DNS failure, or SMTP server at `smtp.gmail.com:587` not responding
- **Expected Behavior**:
  - Connection timeout after 30 seconds
  - Retry up to 2 times with 10-second backoff
  - After final failure: log error, record in ledger as `"status": "failed"`
  - Note preserved on disk
  - NOT marked as `"sent"` — meaning next run will retry email delivery
- **Validation**: Set `SMTP_HOST` to unreachable host; verify timeout, retry, and ledger status

### EC-4.3 — Duplicate Send Prevention (Re-Run Same Week)
- **Scenario**: Pipeline runs Monday at 9 AM and sends successfully. User manually triggers re-run Wednesday.
- **Expected Behavior**:
  - `should_send("2026-W17", ledger)` returns `False`
  - Log message: `"Week 2026-W17 already sent. Skipping email delivery."`
  - No email sent
  - Phases 1–3 CAN re-run (scrape fresh data, regenerate themes/notes) — only email is skipped
  - Ledger NOT updated (no new entry for a skip)
- **Validation**: Run pipeline twice for same week; verify only 1 email sent; ledger has exactly 1 `"sent"` entry

### EC-4.4 — Dry-Run Mode Fidelity
- **Scenario**: `DRY_RUN=true` in environment
- **Expected Behavior**:
  - Full pipeline executes (Phases 1–3)
  - Email is composed (subject, HTML body, plain text)
  - Email is NOT sent via SMTP
  - Full email output saved to `output/dry_run/{week_key}/email_draft.html` and `.txt`
  - Console prints: subject line + first 500 chars of body
  - Ledger records: `"status": "dry_run"`
  - Dry-run does NOT block subsequent real sends for the same week
- **Validation**: Set `DRY_RUN=true`; verify no SMTP connection attempted; file saved; ledger status correct; re-run with `DRY_RUN=false` sends email

### EC-4.5 — Recipient Email Address Invalid
- **Scenario**: `EMAIL_TO=not-an-email` or `EMAIL_TO=` (empty)
- **Expected Behavior**:
  - Validation before SMTP connection: regex check on email format
  - Empty → error: `"No recipients configured. Set EMAIL_TO in environment."`
  - Invalid format → error: `"Invalid email address: 'not-an-email'"`
  - Pipeline halts at Phase 4; Phases 1–3 output preserved
  - Ledger records failure
- **Validation**: Set invalid `EMAIL_TO`; verify error before SMTP connection attempt

### EC-4.6 — Very Large Email Body
- **Scenario**: Note generation somehow produces a larger-than-expected HTML body (e.g., HTML conversion bloat)
- **Expected Behavior**:
  - HTML body size checked before sending
  - If > 100KB → log warning, but still attempt send (most SMTP servers accept up to 10MB)
  - If > 5MB → error, do not send, save to disk only
  - Most realistic case: 250-word note → ~2KB HTML, well within limits
- **Validation**: Generate artificially inflated HTML (inject large base64 image); verify size check and handling

### EC-4.7 — Ledger File Corrupted or Missing
- **Scenario**: `run_ledger.json` is deleted, empty, or contains invalid JSON
- **Expected Behavior**:
  - Missing file → create new empty ledger: `{"runs": []}`
  - Empty file → same as missing: initialize fresh
  - Invalid JSON → backup corrupted file as `run_ledger.json.corrupted.{timestamp}`, create new
  - Log WARNING: `"Ledger file corrupted. Starting fresh. Backup saved."`
  - Pipeline continues with fresh ledger (may re-send for previously sent weeks — acceptable trade-off vs. blocking)
- **Validation**: Delete/corrupt ledger file; verify fresh ledger created, backup saved, pipeline continues

### EC-4.8 — Concurrent Pipeline Runs
- **Scenario**: Two instances of the pipeline start simultaneously (e.g., cron overlap, manual + scheduled)
- **Expected Behavior**:
  - File-based lock: pipeline acquires `pipeline.lock` at start
  - If lock exists and is < 1 hour old → second instance exits: `"Another pipeline run is in progress. Exiting."`
  - If lock exists and is > 1 hour old → assume stale lock, override with warning
  - Lock released at pipeline completion (or on crash via `atexit` handler)
  - Prevents duplicate emails from concurrent runs
- **Validation**: Start two instances simultaneously; verify only one proceeds, other exits cleanly

### EC-4.9 — Email With Special Characters in Subject
- **Scenario**: Week range contains characters that need encoding (e.g., em-dashes, non-ASCII)
- **Expected Behavior**:
  - Subject line properly encoded using RFC 2047 (MIME encoded-word)
  - Subject: `"Weekly App Review Pulse — Apr 15–21, 2026"` (em-dash and en-dash)
  - Python `email.header.Header` handles encoding automatically
  - Subject renders correctly in Gmail, Outlook, Apple Mail
- **Validation**: Generate subject with em-dash and non-ASCII chars; verify correct MIME header encoding

### EC-4.10 — Pipeline Crash Between Note Generation and Email Send
- **Scenario**: Phase 3 completes, note saved to disk, but pipeline crashes before Phase 4 starts
- **Expected Behavior**:
  - Note is preserved in `output/notes/{week_key}/`
  - Ledger has NO entry for this week (email never attempted)
  - On next run: `should_send()` returns `True` (no `"sent"` record)
  - Pipeline can re-run Phase 4 only (if note file exists) or full pipeline
  - Idempotency ensures no data corruption from partial run
- **Validation**: Kill pipeline after Phase 3; verify note exists, no ledger entry; re-run sends email successfully

### EC-4.11 — Multiple Recipients (TO + CC)
- **Scenario**: `EMAIL_TO=team@example.com,pm@example.com` and `EMAIL_CC=vp@example.com`
- **Expected Behavior**:
  - Multiple TO recipients: comma-separated, each receives the email
  - CC recipients added to email headers
  - All recipients recorded in ledger: `"recipients": ["team@example.com", "pm@example.com"], "cc": ["vp@example.com"]`
  - If one recipient bounces, email is still considered "sent" (bounce handling is out of scope)
- **Validation**: Set multiple TO and CC; verify all appear in email headers and ledger

### EC-4.12 — Gmail-Specific SMTP Quirks
- **Scenario**: Using Gmail SMTP with app-specific password; Gmail rate limits or requires OAuth2
- **Expected Behavior**:
  - Support both app-specific passwords (basic auth) and OAuth2 (if configured)
  - Gmail's sending rate limit: 500 emails/day — not a concern for weekly pipeline
  - If Gmail rejects due to "less secure app" policy → error message guides user to create app-specific password
  - Log: `"Gmail requires an app-specific password. See https://support.google.com/accounts/answer/185833"`
- **Validation**: Test with Gmail SMTP; verify connection and auth workflow

---

## Evaluation Script Outline

```python
# tests/eval_phase4_email.py

import pytest
import json
import os
from unittest.mock import patch, MagicMock
from src.email.sender import SMTPSender
from src.email.drafter import EmailDrafter
from src.email.ledger import RunLedger

class TestEmailSending:
    def test_successful_send(self, sample_note, smtp_mock):
        """TC-4.1: Email sent with correct subject and body."""
        pass
    
    def test_multipart_mime(self, sample_note, smtp_mock):
        """TC-4.5: Email has HTML and plain text parts."""
        pass
    
    def test_tls_encryption(self, smtp_mock):
        """TC-4.7: STARTTLS called before auth."""
        pass
    
    def test_subject_format(self, sample_note):
        """TC-4.8: Subject matches expected format."""
        pass
    
    def test_cc_recipients(self, sample_note, smtp_mock):
        """TC-4.9: CC recipients included in headers."""
        pass

class TestDuplicatePrevention:
    def test_skip_already_sent(self, ledger_with_sent_week):
        """TC-4.2: Same week_key → no email sent."""
        pass
    
    def test_allow_new_week(self, ledger_with_sent_week):
        """New week_key → email sent."""
        pass
    
    def test_dry_run_doesnt_block(self, ledger_with_dry_run):
        """EC-4.4: dry_run status doesn't prevent real send."""
        pass
    
    def test_failed_doesnt_block(self, ledger_with_failed):
        """Failed status doesn't prevent retry send."""
        pass

class TestDryRun:
    def test_no_smtp_connection(self, sample_note):
        """EC-4.4: SMTP.connect() never called in dry-run."""
        pass
    
    def test_file_saved(self, sample_note, tmp_path):
        """EC-4.4: Draft saved to dry_run directory."""
        pass
    
    def test_ledger_status(self, sample_note):
        """EC-4.4: Ledger records status as 'dry_run'."""
        pass

class TestEdgeCases:
    def test_missing_credentials(self):
        """EC-4.1: Missing SMTP_PASSWORD → clear error."""
        pass
    
    def test_invalid_credentials(self, smtp_auth_fail_mock):
        """EC-4.1: Wrong password → auth error logged."""
        pass
    
    def test_server_unreachable(self, smtp_timeout_mock):
        """EC-4.2: Unreachable host → retry and fail gracefully."""
        pass
    
    def test_invalid_recipient(self):
        """EC-4.5: Invalid email format caught before SMTP."""
        pass
    
    def test_empty_recipient(self):
        """EC-4.5: Empty EMAIL_TO → clear error."""
        pass
    
    def test_corrupted_ledger(self, corrupted_ledger_file):
        """EC-4.7: Corrupted ledger → backup and reinitialize."""
        pass
    
    def test_missing_ledger(self, tmp_path):
        """EC-4.7: Missing ledger → create fresh."""
        pass
    
    def test_concurrent_runs(self):
        """EC-4.8: File lock prevents dual execution."""
        pass
    
    def test_special_chars_subject(self):
        """EC-4.9: Em-dash and non-ASCII in subject encoded correctly."""
        pass
    
    def test_crash_recovery(self, note_on_disk_no_ledger):
        """EC-4.10: Pipeline crash → note preserved, re-run works."""
        pass
    
    def test_multiple_recipients(self, smtp_mock):
        """EC-4.11: Multiple TO + CC all included."""
        pass

class TestRunLedger:
    def test_record_sent(self):
        """Successful send recorded with all fields."""
        pass
    
    def test_record_failed(self):
        """Failed send recorded with error message."""
        pass
    
    def test_record_dry_run(self):
        """Dry run recorded with correct status."""
        pass
    
    def test_should_send_logic(self):
        """should_send() returns False only for 'sent' status."""
        pass
    
    def test_ledger_persistence(self, tmp_path):
        """Ledger survives process restart (file-based)."""
        pass
    
    def test_ledger_concurrent_write(self):
        """File locking prevents write corruption."""
        pass
```
