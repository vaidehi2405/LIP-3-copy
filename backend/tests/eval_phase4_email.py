"""
Phase 4 Tests — Delivery Client & Ledger
"""

import pytest
import os
import json
from unittest.mock import patch, MagicMock
from src.email.rest_client import DeliveryClient
from src.email.ledger import RunLedger

@pytest.fixture
def temp_ledger(tmp_path):
    ledger_file = tmp_path / "run_ledger.json"
    return RunLedger(str(ledger_file))

class TestDeliveryClient:
    
    @patch("src.email.rest_client.requests.post")
    def test_create_draft_success(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        client = DeliveryClient(dry_run=False)
        result = client.create_email_draft("team@example.com", "Test Subject", "<html>Test</html>")
        
        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["to"] == "team@example.com"
        assert kwargs["json"]["subject"] == "Test Subject"
        assert kwargs["json"]["body"] == "<html>Test</html>"

    @patch("src.email.rest_client.requests.post")
    def test_append_doc_success(self, mock_post):
        mock_post.return_value.raise_for_status.return_value = None
        client = DeliveryClient(dry_run=False)
        result = client.append_to_doc("doc_123", "# Heading")
        
        assert result is True
        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        assert kwargs["json"]["doc_id"] == "doc_123"
        assert kwargs["json"]["content"] == "# Heading"

    def test_dry_run_mode(self):
        client = DeliveryClient(dry_run=True)
        # Should return True immediately without HTTP requests
        assert client.create_email_draft("team@example.com", "Test", "Body") is True

    @patch("src.email.rest_client.requests.post")
    def test_http_failure(self, mock_post):
        import requests
        mock_post.side_effect = requests.RequestException("Network error")
        client = DeliveryClient(dry_run=False)
        assert client.create_email_draft("team@example.com", "Test", "Body") is False

class TestRunLedger:

    def test_record_and_should_send(self, temp_ledger):
        # Initially should send
        assert temp_ledger.should_send("2026-W01") is True
        
        # Record a successful run
        temp_ledger.record_run("2026-W01", "sent")
        
        # Now should not send
        assert temp_ledger.should_send("2026-W01") is False

    def test_record_dry_run_allows_real_send(self, temp_ledger):
        # Record dry run
        temp_ledger.record_run("2026-W02", "dry_run")
        
        # Should still allow sending normally since dry_run != sent
        assert temp_ledger.should_send("2026-W02") is True

    def test_corrupt_ledger_handling(self, tmp_path):
        ledger_path = tmp_path / "corrupted_ledger.json"
        
        # Create an invalid JSON file
        with open(ledger_path, "w") as f:
            f.write("{ invalid json")
            
        ledger = RunLedger(str(ledger_path))
        
        # It should recreate the ledger safely
        assert ledger.should_send("2026-W01") is True
        ledger.record_run("2026-W01", "sent")
        
        # The file should now contain a valid json with 1 run
        with open(ledger_path, "r") as f:
            data = json.load(f)
            assert len(data["runs"]) == 1

if __name__ == "__main__":
    pytest.main([__file__, "-v"])
