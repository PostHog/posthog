from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.storage import append_jsonl_object


class TestAppendJsonlObject(SimpleTestCase):
    @parameterized.expand(
        [
            ("", True, '{"type": "session"}'),
            ('{"type": "session"}', False, '{"type": "session"}\n{"type": "message"}'),
        ]
    )
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_appends_complete_json_lines(
        self,
        existing_content: str,
        expected_is_new: bool,
        expected_content: str,
        mock_read: MagicMock,
        mock_write: MagicMock,
    ) -> None:
        mock_read.return_value = existing_content

        is_new = append_jsonl_object("sessions/example.jsonl", [{"type": "session" if expected_is_new else "message"}])

        self.assertEqual(is_new, expected_is_new)
        mock_write.assert_called_once_with("sessions/example.jsonl", expected_content)
