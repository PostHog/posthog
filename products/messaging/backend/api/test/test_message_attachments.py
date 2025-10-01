from posthog.test.base import APIBaseTest
from unittest.mock import MagicMock, patch

from django.core.files.uploadedfile import SimpleUploadedFile

from rest_framework import status

from products.messaging.backend.api.message_attachments import MAX_FILE_SIZE


class TestMessageAttachmentsAPI(APIBaseTest):
    @patch("products.messaging.backend.api.message_attachments.object_storage")
    def test_upload_success(self, mock_storage):
        mock_storage.write = MagicMock()
        test_file = SimpleUploadedFile(
            "test.svg", b'<svg viewBox="0 0 1 1"><path d="M0 0"/></svg>', content_type="image/svg+xml"
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_attachments/upload", {"file": test_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("file_url", response.json())
        mock_storage.write.assert_called_once()

        called_args = mock_storage.write.call_args[0]
        object_path_arg = called_args[0]
        file_arg = called_args[1]

        self.assertTrue(object_path_arg.startswith(f"{self.team.id}/"))
        self.assertEqual(file_arg, test_file)

        # Assert object_path ends with a UUID and .txt
        uuid_txt_pattern = r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\.txt$"
        self.assertRegex(object_path_arg, uuid_txt_pattern)

    @patch("products.messaging.backend.api.message_attachments.object_storage")
    def test_upload_file_too_large(self, mock_storage):
        test_file = SimpleUploadedFile(
            "big.svg", b'<svg viewBox="0 0 1 1">' + b"0" * (MAX_FILE_SIZE + 1) + b"</svg>", content_type="image/svg+xml"
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_attachments/upload", {"file": test_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("File too large", response.json())

    @patch("products.messaging.backend.api.messaging_attachments.object_storage")
    def test_upload_disallowed_extension(self, mock_storage):
        test_file = SimpleUploadedFile("test.exe", b"hello world", content_type="application/octet-stream")
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_attachments/upload/", {"file": test_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid file type", response.json())

    @patch("products.messaging.backend.api.message_attachments.object_storage")
    def test_upload_disallowed_mime_type(self, mock_storage):
        test_file = SimpleUploadedFile(
            "test.svg", b'<svg viewBox="0 0 1 1"><path d="M0 0"/></svg>', content_type="application/x-msdownload"
        )
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_attachments/upload/", {"file": test_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid MIME type", response.json())

    @patch("products.messaging.backend.api.message_attachments.object_storage")
    def test_upload_storage_exception(self, mock_storage):
        mock_storage.write.side_effect = Exception("Storage error!")
        test_file = SimpleUploadedFile("test.txt", b"hello world", content_type="text/plain")
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_attachments/upload/", {"file": test_file}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        self.assertIn("error", response.json())

    @patch("products.messaging.backend.api.message_attachments.object_storage")
    def test_upload_missing_file(self):
        response = self.client.post(
            f"/api/environments/{self.team.id}/messaging_attachments/upload/", {}, format="multipart"
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Missing file", response.json())
