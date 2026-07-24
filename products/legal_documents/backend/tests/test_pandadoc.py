import hmac
import hashlib

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from parameterized import parameterized

from products.legal_documents.backend.logic import pandadoc


class TestPandaDocClient(TestCase):
    @override_settings(PANDADOC_API_KEY="", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_missing_api_key_raises_not_configured(self) -> None:
        client = pandadoc.PandaDocClient()
        with self.assertRaises(pandadoc.PandaDocNotConfigured):
            client.create_document_from_template(
                template_id="tpl",
                name="doc",
                recipients=[pandadoc.PandaDocRecipient(email="a@b.c", role=pandadoc.PandaDocRole.CLIENT)],
            )

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_create_document_posts_expected_payload(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 201
        fake_response.content = b'{"id": "doc_123", "status": "document.uploaded", "name": "PostHog BAA"}'
        fake_response.json.return_value = {"id": "doc_123", "status": "document.uploaded", "name": "PostHog BAA"}

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.post", return_value=fake_response
        ) as mock_post:
            client = pandadoc.PandaDocClient()
            result = client.create_document_from_template(
                template_id="tpl",
                name="PostHog BAA",
                recipients=[pandadoc.PandaDocRecipient(email="ada@acme.example", role=pandadoc.PandaDocRole.CLIENT)],
                tokens={"Client.Company": "Acme, Inc.", "Client.StreetAddress": "1 Analytics Way"},
                metadata={"legal_document_id": "lid-1"},
                owner_email="privacy@posthog.com",
            )

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents")
        self.assertEqual(kwargs["headers"]["Authorization"], "API-Key key")
        body = kwargs["json"]
        self.assertEqual(body["template_uuid"], "tpl")
        self.assertEqual(body["name"], "PostHog BAA")
        self.assertEqual(body["recipients"], [{"email": "ada@acme.example", "role": "Client"}])
        self.assertEqual(
            body["tokens"],
            [
                {"name": "Client.Company", "value": "Acme, Inc."},
                {"name": "Client.StreetAddress", "value": "1 Analytics Way"},
            ],
        )
        self.assertEqual(body["metadata"], {"legal_document_id": "lid-1"})
        self.assertEqual(body["owner"], {"email": "privacy@posthog.com"})
        self.assertNotIn("sender", body)
        self.assertEqual(result.id, "doc_123")

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_create_document_omits_owner_when_not_provided(self) -> None:
        # When `owner_email` is None we leave the field off so PandaDoc falls
        # back to the API key's owning user.
        fake_response = MagicMock()
        fake_response.status_code = 201
        fake_response.content = b'{"id": "doc_123", "status": "document.uploaded", "name": "doc"}'
        fake_response.json.return_value = {"id": "doc_123", "status": "document.uploaded", "name": "doc"}

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.post", return_value=fake_response
        ) as mock_post:
            pandadoc.PandaDocClient().create_document_from_template(
                template_id="tpl",
                name="doc",
                recipients=[pandadoc.PandaDocRecipient(email="ada@acme.example", role=pandadoc.PandaDocRole.CLIENT)],
            )

        body = mock_post.call_args.kwargs["json"]
        self.assertNotIn("owner", body)
        self.assertNotIn("sender", body)

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_stream_document_yields_raw_binary_stream(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.raw = MagicMock()
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.get", return_value=fake_response
        ) as mock_get:
            client = pandadoc.PandaDocClient()
            with client.stream_document(document_id="doc_123") as stream:
                self.assertIs(stream, fake_response.raw)

        mock_get.assert_called_once()
        args, kwargs = mock_get.call_args
        self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents/doc_123/download")
        self.assertEqual(kwargs["headers"]["Authorization"], "API-Key key")
        self.assertTrue(kwargs["stream"])
        # Transparent decompression so gzip'd responses look like raw bytes.
        self.assertTrue(fake_response.raw.decode_content)

    @override_settings(PANDADOC_API_KEY="key")
    def test_stream_document_non_2xx_raises(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 404
        fake_response.text = "not found"
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)

        with patch("products.legal_documents.backend.logic.pandadoc.requests.get", return_value=fake_response):
            client = pandadoc.PandaDocClient()
            with self.assertRaises(pandadoc.PandaDocError):
                with client.stream_document(document_id="doc_123"):
                    pass

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_send_document_includes_sender_when_provided(self) -> None:
        # PandaDoc only honors the configured sender identity if `sender` is on
        # the /send call — `owner` at create time controls workspace ownership
        # inside PandaDoc, not the email "From" name. Without `sender` on /send,
        # recipients see the API key owner.
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b""

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.post", return_value=fake_response
        ) as mock_post:
            pandadoc.PandaDocClient().send_document(
                document_id="doc_123",
                subject="s",
                message="m",
                sender_email="privacy@posthog.com",
            )

        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents/doc_123/send")
        self.assertEqual(kwargs["json"]["sender"], {"email": "privacy@posthog.com"})

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_send_document_omits_sender_when_not_provided(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.content = b""

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.post", return_value=fake_response
        ) as mock_post:
            pandadoc.PandaDocClient().send_document(document_id="doc_123", subject="s", message="m")

        self.assertNotIn("sender", mock_post.call_args.kwargs["json"])

    @override_settings(PANDADOC_API_KEY="key")
    def test_non_2xx_response_raises(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 500
        fake_response.text = "boom"

        with patch("products.legal_documents.backend.logic.pandadoc.requests.post", return_value=fake_response):
            client = pandadoc.PandaDocClient()
            with self.assertRaises(pandadoc.PandaDocError):
                client.send_document(document_id="doc_123", subject="s", message="m")

    def test_verify_webhook_signature_accepts_valid_hmac(self) -> None:
        secret = "shhh"
        body = b'{"event": "document_state_changed"}'
        signature = hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
        self.assertTrue(pandadoc.verify_webhook_signature(secret=secret, body=body, signature=signature))

    def test_verify_webhook_signature_rejects_bad_hmac(self) -> None:
        self.assertFalse(pandadoc.verify_webhook_signature(secret="shhh", body=b"{}", signature="0" * 64))

    def test_verify_webhook_signature_rejects_empty_inputs(self) -> None:
        self.assertFalse(pandadoc.verify_webhook_signature(secret="", body=b"{}", signature="abc"))
        self.assertFalse(pandadoc.verify_webhook_signature(secret="k", body=b"{}", signature=""))

    def test_serialize_recipient_emits_flat_email_and_role_for_each_role(self) -> None:
        # Both the Client signer and the PostHog CC serialize to the same
        # minimal shape; tokens carry all template content.
        client = pandadoc.PandaDocRecipient(email="ada@acme.example", role=pandadoc.PandaDocRole.CLIENT)
        self.assertEqual(pandadoc._serialize_recipient(client), {"email": "ada@acme.example", "role": "Client"})
        posthog = pandadoc.PandaDocRecipient(email="privacy@posthog.com", role=pandadoc.PandaDocRole.POSTHOG)
        self.assertEqual(pandadoc._serialize_recipient(posthog), {"email": "privacy@posthog.com", "role": "PostHog"})

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_void_document_patches_status_endpoint_with_voided_code(self) -> None:
        # Voided is PandaDoc's "no longer signable" status. We hit the status
        # endpoint with the numeric code (11) rather than deleting the doc so
        # PandaDoc retains the audit record of the cancelled signing process.
        fake_response = MagicMock()
        fake_response.status_code = 204

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.patch", return_value=fake_response
        ) as mock_patch:
            pandadoc.PandaDocClient().void_document(document_id="doc_123")

        mock_patch.assert_called_once()
        args, kwargs = mock_patch.call_args
        self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents/doc_123/status")
        self.assertEqual(kwargs["headers"]["Authorization"], "API-Key key")
        self.assertEqual(kwargs["json"], {"status": 11, "notify_recipients": True})

    @override_settings(PANDADOC_API_KEY="key")
    def test_void_document_can_opt_out_of_recipient_notification(self) -> None:
        # The caller may want to suppress the "your document was cancelled"
        # email — e.g., the recipient is wrong and we don't want them to even
        # know the original existed.
        fake_response = MagicMock()
        fake_response.status_code = 204

        with patch(
            "products.legal_documents.backend.logic.pandadoc.requests.patch", return_value=fake_response
        ) as mock_patch:
            pandadoc.PandaDocClient().void_document(document_id="doc_123", notify_recipients=False)

        self.assertEqual(mock_patch.call_args.kwargs["json"]["notify_recipients"], False)

    @parameterized.expand(
        [
            # 404 = envelope already gone on PandaDoc's side; that's the state
            # we wanted, so the helper treats it as success.
            ("404_not_found_treated_as_success", 404, {"type": "not_found"}, False),
            # 403 permissions_error = the API key's user can't void this
            # envelope (owner mismatch, or a terminal state we don't own).
            # Nothing to do for a delete, so treat it as a no-op success.
            ("403_permissions_error_treated_as_success", 403, {"type": "permissions_error"}, False),
            # A generic 403 (bad/expired key, WAF block) is a real problem and
            # must still surface rather than being silently swallowed.
            ("403_generic_raises", 403, {"type": "authentication_error"}, True),
            # 423 = PandaDoc has the document locked for editing; surface to
            # the caller so it can decide whether to retry or log + move on.
            ("423_locked_raises", 423, {"type": "locked"}, True),
        ]
    )
    @override_settings(PANDADOC_API_KEY="key")
    def test_void_document_status_handling(
        self, _name: str, status_code: int, body: dict[str, str], should_raise: bool
    ) -> None:
        fake_response = MagicMock()
        fake_response.status_code = status_code
        fake_response.text = str(body)
        fake_response.json.return_value = body

        with patch("products.legal_documents.backend.logic.pandadoc.requests.patch", return_value=fake_response):
            if should_raise:
                with self.assertRaises(pandadoc.PandaDocError):
                    pandadoc.PandaDocClient().void_document(document_id="doc_123")
            else:
                pandadoc.PandaDocClient().void_document(document_id="doc_123")
