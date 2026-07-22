import uuid

from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase

from parameterized import parameterized

from products.tasks.backend.models import TaskSession
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


class TestTaskSessionStorage(SimpleTestCase):
    @patch("products.tasks.backend.models.object_storage.tag")
    @patch("products.tasks.backend.storage.object_storage.write")
    @patch("products.tasks.backend.storage.object_storage.read")
    def test_new_session_object_is_attributed_without_expiry(
        self,
        mock_read: MagicMock,
        mock_write: MagicMock,
        mock_tag: MagicMock,
    ) -> None:
        organization_id = uuid.uuid4()
        task_id = uuid.uuid4()
        task_session = TaskSession(
            id=uuid.uuid4(),
            organization_id=organization_id,
            task_id=task_id,
            object_storage_key="sessions/example.jsonl",
        )
        mock_read.return_value = None

        task_session.append_entries([{"type": "session"}])

        mock_write.assert_called_once_with("sessions/example.jsonl", '{"type": "session"}')
        mock_tag.assert_called_once_with(
            "sessions/example.jsonl",
            {
                "data_class": "task_session",
                "organization_id": str(organization_id),
                "task_id": str(task_id),
            },
        )
