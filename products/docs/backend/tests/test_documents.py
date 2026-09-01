from django.test import SimpleTestCase

from parameterized import parameterized

from products.docs.backend.logic.documents import plain_text


class TestPlainText(SimpleTestCase):
    @parameterized.expand(
        [
            ("empty document", None, ""),
            (
                "one paragraph",
                {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "Hello"}]}]},
                "Hello",
            ),
            (
                "marks inside a paragraph stay on one line",
                {
                    "type": "doc",
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [
                                {"type": "text", "text": "Ship "},
                                {"type": "text", "text": "today", "marks": [{"type": "bold"}]},
                            ],
                        }
                    ],
                },
                "Ship today",
            ),
            (
                "blocks are separate lines",
                {
                    "type": "doc",
                    "content": [
                        {"type": "heading", "attrs": {"level": 2}, "content": [{"type": "text", "text": "Notes"}]},
                        {"type": "paragraph", "content": [{"type": "text", "text": "From the call"}]},
                    ],
                },
                "Notes\nFrom the call",
            ),
            (
                "reference blocks with no text drop out",
                {
                    "type": "doc",
                    "content": [
                        {"type": "objectBlock", "attrs": {"kind": "insight", "objectId": "abc"}},
                        {"type": "paragraph", "content": [{"type": "text", "text": "Signups"}]},
                    ],
                },
                "Signups",
            ),
        ]
    )
    def test_flattens_prosemirror_content(self, _name: str, content, expected: str) -> None:
        assert plain_text(content) == expected
