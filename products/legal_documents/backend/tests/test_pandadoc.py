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

    @staticmethod
    def _status_response(document_status: str) -> MagicMock:
        response = MagicMock()
        response.status_code = 200
        response.content = b'{"status": "..."}'
        response.json.return_value = {"id": "doc_123", "status": document_status}
        return response

    @parameterized.expand(
        [
            # Only envelopes actually emailed to a signer carry a live signing
            # link, and PandaDoc only permits voiding from these two states.
            ("sent_is_voided", "document.sent", True),
            ("viewed_is_voided", "document.viewed", True),
            # Never dispatched: still processing, ready-but-unsent (the stranded
            # webhook case), or errored. Nothing to void — must be a no-op so
            # the row stays deletable instead of wedging.
            ("uploaded_is_noop", "document.uploaded", False),
            ("draft_is_noop", "document.draft", False),
            ("error_is_noop", "document.error", False),
            # Already terminal — a second void would 4xx and re-wedge the row.
            ("completed_is_noop", "document.completed", False),
            ("already_voided_is_noop", "document.voided", False),
        ]
    )
    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_void_document_only_voids_sent_or_viewed_envelopes(
        self, _name: str, document_status: str, should_void: bool
    ) -> None:
        # Voided is PandaDoc's "no longer signable" status (numeric code 11 on
        # the status endpoint) — a status transition rather than a delete so
        # PandaDoc retains the audit record of the cancelled signing process.
        patch_response = MagicMock()
        patch_response.status_code = 204

        with (
            patch(
                "products.legal_documents.backend.logic.pandadoc.requests.get",
                return_value=self._status_response(document_status),
            ),
            patch(
                "products.legal_documents.backend.logic.pandadoc.requests.patch", return_value=patch_response
            ) as mock_patch,
        ):
            pandadoc.PandaDocClient().void_document(document_id="doc_123")

        if should_void:
            mock_patch.assert_called_once()
            args, kwargs = mock_patch.call_args
            self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents/doc_123/status")
            self.assertEqual(kwargs["headers"]["Authorization"], "API-Key key")
            self.assertEqual(kwargs["json"], {"status": 11, "notify_recipients": True})
        else:
            mock_patch.assert_not_called()

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_void_document_noop_when_envelope_already_gone(self) -> None:
        # A 404 from the status lookup means the envelope no longer exists on
        # PandaDoc's side — the state we wanted — so we skip the void entirely.
        get_response = MagicMock()
        get_response.status_code = 404
        get_response.text = "not found"

        with (
            patch("products.legal_documents.backend.logic.pandadoc.requests.get", return_value=get_response),
            patch("products.legal_documents.backend.logic.pandadoc.requests.patch") as mock_patch,
        ):
            pandadoc.PandaDocClient().void_document(document_id="doc_123")

        mock_patch.assert_not_called()

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_void_document_can_opt_out_of_recipient_notification(self) -> None:
        # The caller may want to suppress the "your document was cancelled"
        # email — e.g., the recipient is wrong and we don't want them to even
        # know the original existed.
        patch_response = MagicMock()
        patch_response.status_code = 204

        with (
            patch(
                "products.legal_documents.backend.logic.pandadoc.requests.get",
                return_value=self._status_response("document.sent"),
            ),
            patch(
                "products.legal_documents.backend.logic.pandadoc.requests.patch", return_value=patch_response
            ) as mock_patch,
        ):
            pandadoc.PandaDocClient().void_document(document_id="doc_123", notify_recipients=False)

        self.assertEqual(mock_patch.call_args.kwargs["json"]["notify_recipients"], False)

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_void_document_raises_when_void_of_live_envelope_fails(self) -> None:
        # A sent envelope PandaDoc refuses to void (e.g. 423 locked for editing)
        # must surface so the caller doesn't delete a row whose signing link is
        # still completable.
        patch_response = MagicMock()
        patch_response.status_code = 423
        patch_response.text = "Document is locked for editing"

        with (
            patch(
                "products.legal_documents.backend.logic.pandadoc.requests.get",
                return_value=self._status_response("document.sent"),
            ),
            patch("products.legal_documents.backend.logic.pandadoc.requests.patch", return_value=patch_response),
        ):
            with self.assertRaises(pandadoc.PandaDocError):
                pandadoc.PandaDocClient().void_document(document_id="doc_123")
