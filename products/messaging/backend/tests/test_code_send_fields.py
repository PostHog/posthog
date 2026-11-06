import base64
from typing import Any

from django.test import RequestFactory, SimpleTestCase

from parameterized import parameterized
from rest_framework.exceptions import ValidationError

from posthog.exceptions import exception_handler

from products.messaging.backend.presentation.views.code_send_fields import with_code_send_reason
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


def _attachment(**fields: Any) -> dict[str, str]:
    return {"filename": "invoice.pdf", "content": "JVBERi0xLjQ=", **fields}


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
            ("cc_with_a_display_name", {"cc": "Jane <jane@example.com>"}, "cc__0"),
            ("cc_with_two_addresses_in_one", {"cc": "jane@example.com, joe@example.com"}, "cc__0"),
            (
                "content_that_is_not_base64",
                {"attachments": [_attachment(content="not base64!")]},
                "attachments__0__content",
            ),
            ("empty_content", {"attachments": [_attachment(content="")]}, "attachments__0__content"),
            ("executable", {"attachments": [_attachment(filename="setup.EXE")]}, "attachments__0__filename"),
            ("registry_file", {"attachments": [_attachment(filename="settings.reg")]}, "attachments__0__filename"),
            (
                "executable_with_a_trailing_dot",
                {"attachments": [_attachment(filename="setup.exe.")]},
                "attachments__0__filename",
            ),
            (
                "filename_with_a_path",
                {"attachments": [_attachment(), _attachment(filename="../invoice.pdf")]},
                "attachments__1__filename",
            ),
            (
                "filename_with_a_line_break",
                {"attachments": [_attachment(filename="invoice\r\n.pdf")]},
                "attachments__0__filename",
            ),
            (
                "content_type_that_is_not_a_mime_type",
                {"attachments": [_attachment(content_type="pdf")]},
                "attachments__0__content_type",
            ),
            (
                "content_id_with_brackets",
                {"attachments": [_attachment(content_id="<logo>")]},
                "attachments__0__content_id",
            ),
            ("attachment_that_is_not_an_object", {"attachments": ["invoice.pdf"]}, "attachments__0"),
            (
                "attachment_with_a_camel_case_key",
                {"attachments": [_attachment(contentId="logo")]},
                "attachments__0__contentId",
            ),
            (
                "attachment_with_an_empty_key",
                {"attachments": [_attachment(**{"": "", "contentId": "logo"})]},
                "attachments__0__",
            ),
            (
                "attachments_too_large",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 300_000).decode())] * 2},
                "attachments",
            ),
        ]
    )
    def test_refuses_an_extra_field_it_cannot_send(self, _name: str, fields: dict[str, Any], attr: str) -> None:
        refused = _refusal(fields)

        assert (refused["type"], refused["code"], refused["attr"]) == ("invalid_request", "invalid_request", attr)
        assert refused["why"] and refused["fix"]

    @parameterized.expand(
        [
            ("too_many_bcc", {"bcc": [f"user{i}@example.com" for i in range(11)]}, "bcc", "at most 10 addresses"),
            ("too_many_attachments", {"attachments": [_attachment()] * 11}, "attachments", "at most 10 files"),
            (
                "filename_too_long",
                {"attachments": [_attachment(filename="a" * 252 + ".pdf")]},
                "attachments__0__filename",
                "255 characters",
            ),
            (
                "content_type_too_long",
                {"attachments": [_attachment(content_type=f"application/{'x' * 67}")]},
                "attachments__0__content_type",
                "78 characters",
            ),
            (
                "content_id_too_long",
                {"attachments": [_attachment(content_id="x" * 79)]},
                "attachments__0__content_id",
                "78 characters",
            ),
        ]
    )
    def test_explains_the_limit_a_refused_field_passed(
        self, _name: str, fields: dict[str, Any], attr: str, fix: str
    ) -> None:
        refused = _refusal(fields)

        assert (refused["code"], refused["attr"]) == ("invalid_request", attr)
        assert fix in refused["fix"]

    @parameterized.expand(
        [
            ("one_address", {"cc": "copy@example.com"}),
            ("empty_lists", {"cc": [], "bcc": [], "attachments": []}),
            ("ten_addresses", {"bcc": [f"user{i}@example.com" for i in range(10)]}),
            (
                "attachments_at_the_size_limit",
                {"attachments": [_attachment(content=base64.b64encode(b"x" * 262_144).decode())] * 2},
            ),
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
