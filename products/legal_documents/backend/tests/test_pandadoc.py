import hmac
import hashlib

from unittest.mock import MagicMock

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
                recipients=[pandadoc.PandaDocRecipient(email="a@b.c", role=pandadoc.PandaDocRole.CLIENT)],
            )

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_create_document_posts_expected_payload(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 201
        fake_response.content = b'{"id": "doc_123", "status": "document.uploaded", "name": "PostHog BAA"}'
        fake_response.json.return_value = {"id": "doc_123", "status": "document.uploaded", "name": "PostHog BAA"}
        session = MagicMock()
        session.post.return_value = fake_response

        client = pandadoc.PandaDocClient(session=session)
        result = client.create_document_from_template(
            template_id="tpl",
            name="PostHog BAA",
            recipients=[pandadoc.PandaDocRecipient(email="ada@acme.example", role=pandadoc.PandaDocRole.CLIENT)],
            tokens={"Client.Company": "Acme, Inc.", "Client.StreetAddress": "1 Analytics Way"},
            metadata={"legal_document_id": "lid-1"},
            sender_email="privacy@posthog.com",
        )

        session.post.assert_called_once()
        args, kwargs = session.post.call_args
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
        self.assertEqual(body["sender"], {"email": "privacy@posthog.com"})
        self.assertEqual(result.id, "doc_123")

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_create_document_omits_sender_when_not_provided(self) -> None:
        # When `sender_email` is None we leave the field off so PandaDoc falls
        # back to the API key's owning user.
        fake_response = MagicMock()
        fake_response.status_code = 201
        fake_response.content = b'{"id": "doc_123", "status": "document.uploaded", "name": "doc"}'
        fake_response.json.return_value = {"id": "doc_123", "status": "document.uploaded", "name": "doc"}
        session = MagicMock()
        session.post.return_value = fake_response

        pandadoc.PandaDocClient(session=session).create_document_from_template(
            template_id="tpl",
            name="doc",
            recipients=[pandadoc.PandaDocRecipient(email="ada@acme.example", role=pandadoc.PandaDocRole.CLIENT)],
        )

        body = session.post.call_args.kwargs["json"]
        self.assertNotIn("sender", body)

    @override_settings(PANDADOC_API_KEY="key", PANDADOC_API_BASE_URL="https://api.pandadoc.com")
    def test_stream_document_yields_raw_binary_stream(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 200
        fake_response.raw = MagicMock()
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        session = MagicMock()
        session.get.return_value = fake_response

        client = pandadoc.PandaDocClient(session=session)
        with client.stream_document(document_id="doc_123") as stream:
            self.assertIs(stream, fake_response.raw)

        session.get.assert_called_once()
        args, kwargs = session.get.call_args
        self.assertEqual(args[0], "https://api.pandadoc.com/public/v1/documents/doc_123/download")
        self.assertEqual(kwargs["headers"]["Authorization"], "API-Key key")
        self.assertTrue(kwargs["stream"])
        # Split (connect, read) timeout so slow PDF streams don't trip the
        # blanket 30s ceiling used for control-plane calls.
        self.assertEqual(kwargs["timeout"], pandadoc.DOWNLOAD_TIMEOUT_SECONDS)
        # Transparent decompression so gzip'd responses look like raw bytes.
        self.assertTrue(fake_response.raw.decode_content)

    @override_settings(PANDADOC_API_KEY="key")
    def test_stream_document_non_2xx_raises(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 404
        fake_response.text = "not found"
        fake_response.__enter__ = MagicMock(return_value=fake_response)
        fake_response.__exit__ = MagicMock(return_value=False)
        session = MagicMock()
        session.get.return_value = fake_response

        client = pandadoc.PandaDocClient(session=session)
        with self.assertRaises(pandadoc.PandaDocError):
            with client.stream_document(document_id="doc_123"):
                pass

    @override_settings(PANDADOC_API_KEY="key")
    def test_non_2xx_response_raises(self) -> None:
        fake_response = MagicMock()
        fake_response.status_code = 500
        fake_response.text = "boom"
        session = MagicMock()
        session.post.return_value = fake_response

        client = pandadoc.PandaDocClient(session=session)
        with self.assertRaises(pandadoc.PandaDocError):
            client.send_document(document_id="doc_123", subject="s", message="m")

    def test_build_session_mounts_retry_adapter(self) -> None:
        # The mounted HTTPAdapter carries the urllib3 Retry policy that lets
        # transient ProxyError / RemoteDisconnected and 5xx replies recover
        # without the caller seeing a PandaDocError on the first blip.
        session = pandadoc._build_session()
        adapter = session.get_adapter("https://api.pandadoc.com/")
        retry = adapter.max_retries
        self.assertEqual(retry.total, pandadoc._RETRY_TOTAL)
        self.assertEqual(retry.connect, pandadoc._RETRY_TOTAL)
        self.assertEqual(retry.read, pandadoc._RETRY_TOTAL)
        self.assertEqual(set(retry.status_forcelist or set()), set(pandadoc._RETRY_STATUS_FORCELIST))
        self.assertEqual(set(retry.allowed_methods or set()), set(pandadoc._RETRY_ALLOWED_METHODS))
        self.assertFalse(retry.raise_on_status)

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
