import hmac
import hashlib

from unittest.mock import MagicMock, patch

from django.test import TestCase, override_settings

from products.legal_documents.backend.logic import pandadoc


class TestPandaDocClient(TestCase):
    @override_settings(PANDADOC_API_KEY="", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_missing_api_key_raises_not_configured(self) -> None:
        client = pandadoc.PandaDocClient()
        with self.assertRaises(pandadoc.PandaDocNotConfigured):
            client.create_document_from_template(
                template_id="tpl",
                name="doc",
                recipients=[pandadoc.PandaDocRecipient(email="a@b.c")],
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
                recipients=[
                    pandadoc.PandaDocRecipient(
                        email="ada@acme.example",
                        company="Acme, Inc.",
                        street_address="1 Analytics Way",
                    )
                ],
                metadata={"legal_document_id": "lid-1"},
            )

        mock_post.assert_called_once()
        args, kwargs = mock_post.call_args
        self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents")
        self.assertEqual(kwargs["headers"]["Authorization"], "API-Key key")
        body = kwargs["json"]
        self.assertEqual(body["template_uuid"], "tpl")
        self.assertEqual(body["name"], "PostHog BAA")
        recipient = body["recipients"][0]
        self.assertEqual(recipient["email"], "ada@acme.example")
        self.assertEqual(recipient["role"], "Client")
        self.assertEqual(
            recipient["fields"],
            {"company": {"value": "Acme, Inc."}, "street_address": {"value": "1 Analytics Way"}},
        )
        self.assertNotIn("tokens", body)
        self.assertEqual(body["metadata"], {"legal_document_id": "lid-1"})
        self.assertEqual(result.id, "doc_123")

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

    def test_serialize_recipient_handles_posthog_sender_without_client_fields(self) -> None:
        # The PostHog sender recipient doesn't carry Client.* fields, so
        # _serialize_recipient must not blow up when it's passed — otherwise
        # every real submission 500s (tests don't catch this on their own
        # because submit_to_pandadoc short-circuits when template IDs are unset).
        sender = pandadoc.PandaDocSenderPostHog()
        payload = pandadoc._serialize_recipient(sender)
        self.assertEqual(payload, {"email": sender.email, "role": "PostHog"})
        self.assertNotIn("fields", payload)

    def test_serialize_recipient_serializes_client_fields(self) -> None:
        client = pandadoc.PandaDocRecipient(
            email="ada@acme.example", company="Acme, Inc.", street_address="1 Analytics Way"
        )
        payload = pandadoc._serialize_recipient(client)
        self.assertEqual(
            payload,
            {
                "email": "ada@acme.example",
                "role": "Client",
                "fields": {
                    "company": {"value": "Acme, Inc."},
                    "street_address": {"value": "1 Analytics Way"},
                },
            },
        )
