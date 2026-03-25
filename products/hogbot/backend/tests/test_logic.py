import json
from datetime import UTC, datetime
from unittest.mock import patch

from django.test import SimpleTestCase, override_settings

from products.hogbot.backend import logic


class TestHogbotLogic(SimpleTestCase):
    @override_settings(OBJECT_STORAGE_HOGBOT_FOLDER="hogbot")
    def test_log_key_generation(self):
        self.assertEqual(logic.get_admin_log_key(17), "hogbot/logs/hogbot_17_admin.jsonl")
        self.assertEqual(logic.get_research_log_key(17, "sig-1"), "hogbot/logs/hogbot_17_sig-1.jsonl")

    @patch("products.hogbot.backend.logic.object_storage.read")
    def test_read_log_entries_filters_after_exclude_types_and_limit(self, mock_read):
        mock_read.return_value = "\n".join(
            [
                json.dumps(
                    {
                        "timestamp": "2026-03-25T09:59:00Z",
                        "notification": {"method": "_hogbot/status"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-25T10:00:00Z",
                        "notification": {"method": "_hogbot/console"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-25T10:01:00Z",
                        "notification": {"method": "_hogbot/result"},
                    }
                ),
                json.dumps(
                    {
                        "timestamp": "2026-03-25T10:02:00Z",
                        "notification": {"method": "_hogbot/error"},
                    }
                ),
            ]
        )

        entries, total_count = logic.read_log_entries(
            "hogbot/logs/test.jsonl",
            after=datetime(2026, 3, 25, 10, 0, 30, tzinfo=UTC),
            exclude_types={"_hogbot/error"},
            limit=1,
        )

        self.assertEqual(total_count, 4)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["notification"]["method"], "_hogbot/result")
