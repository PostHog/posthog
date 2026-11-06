from django.test import SimpleTestCase

from parameterized import parameterized

from products.messaging.backend.services.content_hash import email_content_hash


class TestEmailContentHash(SimpleTestCase):
    @parameterized.expand(
        [
            (
                "fields_absent",
                {"subject": "Welcome, {{ variables.first_name }}", "html": "<p>Hi {{ variables.first_name }}</p>"},
                "v1:f74cd913f3aa2e5667a588f2865634e56693df77793ca594d18e9b5f89e3d2e6",
            ),
            (
                "non_ascii",
                {"subject": "Grüße", "preheader": "Vorschau", "html": "<p>ä</p>", "text": "ä"},
                "v1:75cf6fc3189ca26f60da672d29a1d4c89c7db3dd458df3a550a34a4d2a92c149",
            ),
            (
                "windows_line_endings",
                {
                    "subject": "Welcome, {{ variables.first_name }}",
                    "html": "<p>Hi {{ variables.first_name }}</p>",
                    "text": "\r\n\r",
                },
                "v1:8112876ee1b2dd7327f571b04b546ed057bfff5a904d9f0ae507b6a449ab6453",
            ),
        ]
    )
    def test_matches_the_spec_test_vectors(self, _name: str, email: dict, expected: str) -> None:
        assert email_content_hash(email) == expected
