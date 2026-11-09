from typing import Any

from django.http import QueryDict
from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.exceptions import exception_handler

from products.messaging.backend.presentation.views.code_send_fields import (
    AttachmentSize,
    attachment_size,
    with_code_send_reason,
)
from products.messaging.backend.presentation.views.message_templates import SendEmailSerializer

ADDRESS_VERDICTS = [
    ("jane=tag@example.com", True),
    ("jane~tag@example.com", True),
    ("jane#tag@example.com", True),
    ("o'brien@example.com", True),
    ("a!b$c%d&e*f/g?h^i`j|k~l@example.com", True),
    ("jane@sub.example.co.uk", True),
    ("jane@bücher.example", False),
    ("jane@[192.0.2.1]", False),
    ('"jane doe"@example.com', False),
    ("jane@localhost", False),
    (".jane@example.com", False),
    ("jane.@example.com", False),
    ("jane..doe@example.com", False),
]


INVOICE = "a" * 64


def _attachment(**fields: Any) -> dict[str, str]:
    return {"sha256": INVOICE, "filename": "invoice.pdf", **fields}


def _code_send(fields: dict[str, Any]) -> SendEmailSerializer:
    return SendEmailSerializer(
        data={"to": "user@example.com", "template_key": "welcome", "subject": "Hi", "text": "Hi", **fields}
    )


def _refusal(fields: dict[str, Any]) -> dict[str, Any]:
    serializer = _code_send(fields)
    assert not serializer.is_valid()
    response = exception_handler(ValidationError(serializer.errors), {"request": RequestFactory().post("/")})
    assert response is not None
    return with_code_send_reason(response.data)


class TestCodeSendFieldRefusals(SimpleTestCase):
    @parameterized.expand(
        [
            ("cc_with_a_display_name", {"cc": "Jane <jane@example.com>"}, "cc__0", "invalid_request"),
            ("cc_with_two_addresses_in_one", {"cc": "jane@example.com, joe@example.com"}, "cc__0", "invalid_request"),
            (
                "executable",
                {"attachments": [_attachment(filename="setup.EXE")]},
                "attachments__0__filename",
                "blocked_file_type",
            ),
            (
                "registry_file",
                {"attachments": [_attachment(filename="settings.reg")]},
                "attachments__0__filename",
                "blocked_file_type",
            ),
            (
                "executable_with_a_trailing_dot",
                {"attachments": [_attachment(filename="setup.exe.")]},
                "attachments__0__filename",
                "blocked_file_type",
            ),
            (
                "filename_with_a_path",
                {"attachments": [_attachment(), _attachment(filename="../invoice.pdf")]},
                "attachments__1__filename",
                "unsafe_filename",
            ),
            (
                "filename_with_a_line_break",
                {"attachments": [_attachment(filename="invoice\r\n.pdf")]},
                "attachments__0__filename",
                "unsafe_filename",
            ),
            (
                "content_type_that_is_not_a_mime_type",
                {"attachments": [_attachment(content_type="pdf")]},
                "attachments__0__content_type",
                "not_mime_type",
            ),
            (
                "content_id_with_brackets",
                {"attachments": [_attachment(content_id="<logo>")]},
                "attachments__0__content_id",
                "unsafe_content_id",
            ),
            (
                "sha256_in_upper_case",
                {"attachments": [_attachment(sha256="A" * 64)]},
                "attachments__0__sha256",
                "invalid_request",
            ),
            (
                "attachment_without_a_sha256",
                {"attachments": [{"filename": "invoice.pdf"}]},
                "attachments__0__sha256",
                "invalid_request",
            ),
            (
                "attachment_with_inline_content",
                {"attachments": [_attachment(content="JVBERi0xLjQ=")]},
                "attachments__0__content",
                "invalid_request",
            ),
            ("attachment_that_is_not_an_object", {"attachments": ["invoice.pdf"]}, "attachments__0", "invalid_request"),
            (
                "attachment_with_a_camel_case_key",
                {"attachments": [_attachment(contentId="logo")]},
                "attachments__0__contentId",
                "invalid_request",
            ),
            (
                "attachment_with_an_empty_key",
                {"attachments": [_attachment(**{"": "", "contentId": "logo"})]},
                "attachments__0__",
                "invalid_request",
            ),
        ]
    )
    def test_refuses_an_extra_field_it_cannot_send(
        self, _name: str, fields: dict[str, Any], attr: str, code: str
    ) -> None:
        refused = _refusal(fields)

        assert (refused["type"], refused["code"], refused["attr"]) == ("invalid_request", code, attr)
        assert refused["why"] and refused["fix"]

    def test_points_a_file_sent_inline_to_the_upload_route(self) -> None:
        refused = _refusal({"attachments": [_attachment(content="JVBERi0xLjQ=")]})

        assert "messaging/attachments/uploads/" in refused["fix"]

    @parameterized.expand(
        [
            (
                "too_many_bcc",
                {"bcc": [f"user{i}@example.com" for i in range(11)]},
                "bcc",
                "invalid_request",
                "at most 10 addresses",
            ),
            (
                "too_many_attachments",
                {"attachments": [_attachment()] * 11},
                "attachments",
                "too_many_attachments",
                "at most 10 files",
            ),
            (
                "too_many_attachments_that_are_also_invalid",
                {"attachments": [{}] * 11},
                "attachments",
                "too_many_attachments",
                "at most 10 files",
            ),
            (
                "filename_too_long",
                {"attachments": [_attachment(filename="a" * 252 + ".pdf")]},
                "attachments__0__filename",
                "invalid_request",
                "255 characters",
            ),
            (
                "content_type_too_long",
                {"attachments": [_attachment(content_type=f"application/{'x' * 67}")]},
                "attachments__0__content_type",
                "invalid_request",
                "78 characters",
            ),
            (
                "content_id_too_long",
                {"attachments": [_attachment(content_id="x" * 79)]},
                "attachments__0__content_id",
                "invalid_request",
                "78 characters",
            ),
        ]
    )
    def test_explains_the_limit_a_refused_field_passed(
        self, _name: str, fields: dict[str, Any], attr: str, code: str, fix: str
    ) -> None:
        refused = _refusal(fields)

        assert (refused["code"], refused["attr"]) == (code, attr)
        assert fix in refused["fix"]

    @parameterized.expand(
        [
            ("one_address", {"cc": "copy@example.com"}),
            ("empty_lists", {"cc": [], "bcc": [], "attachments": []}),
            ("ten_addresses", {"bcc": [f"user{i}@example.com" for i in range(10)]}),
            ("ten_attachments", {"attachments": [_attachment()] * 10}),
        ]
    )
    def test_accepts_extra_fields_at_their_limits(self, _name: str, fields: dict[str, Any]) -> None:
        serializer = _code_send(fields)

        assert serializer.is_valid(), serializer.errors

    @parameterized.expand(
        [(field, address, accepted) for field in ("cc", "bcc") for address, accepted in ADDRESS_VERDICTS]
    )
    def test_takes_the_copy_addresses_the_pipeline_takes(self, field: str, address: str, accepted: bool) -> None:
        if accepted:
            serializer = _code_send({field: [address]})
            assert serializer.is_valid(), serializer.errors
            assert serializer.validated_data[field] == [address]
        else:
            assert _refusal({field: [address]})["attr"] == f"{field}__0"


class TestAttachmentSize(SimpleTestCase):
    @parameterized.expand(
        [
            ("no_attachments_field", {}, AttachmentSize(count=0, bytes=0)),
            ("null_attachments", {"attachments": None}, AttachmentSize(count=0, bytes=0)),
            ("empty_attachments", {"attachments": []}, AttachmentSize(count=0, bytes=0)),
            ("uploaded_files", {"attachments": [_attachment(), _attachment()]}, AttachmentSize(count=2, bytes=None)),
            ("a_file_that_is_not_an_object", {"attachments": ["invoice.pdf"]}, AttachmentSize(count=1, bytes=None)),
            ("attachments_that_are_not_a_list", {"attachments": "invoice.pdf"}, AttachmentSize(count=None, bytes=None)),
            ("a_body_that_is_not_an_object", ["invoice.pdf"], AttachmentSize(count=None, bytes=None)),
            (
                "a_form_body",
                QueryDict(f"attachments[0]filename=a.pdf&attachments[0]sha256={INVOICE}"),
                AttachmentSize(count=None, bytes=None),
            ),
        ]
    )
    def test_counts_the_files_and_leaves_their_bytes_to_the_pipeline(
        self, _name: str, body: Any, expected: AttachmentSize
    ) -> None:
        assert attachment_size(body) == expected
