from django.test import SimpleTestCase

from parameterized import parameterized

from products.docs.backend.logic.markdown import from_markdown, to_markdown

NOTES = """# How we work here

Sessions are **cheap**. Open one per *question*, then `close` it.

- Prefer the smallest change.
- Land it, then [keep going](https://example.com).

1. First
2. Second

- [ ] Write it down
- [x] Read it back

> A quote worth keeping.

```python
print("hi")
```
"""


class TestDocMarkdown(SimpleTestCase):
    def test_markdown_survives_a_round_trip_through_a_doc(self):
        assert to_markdown(from_markdown(NOTES)) == NOTES

    @parameterized.expand(
        [
            (
                {
                    "type": "dataValue",
                    "attrs": {"query": "SELECT count() FROM events", "label": "events", "shortId": ""},
                },
                '<hogql label="events">SELECT count() FROM events</hogql>',
            ),
            (
                {"type": "dataValue", "attrs": {"query": "", "label": "Weekly signups", "shortId": "abc"}},
                '<insight id="abc">Weekly signups</insight>',
            ),
            ({"type": "dataRequest", "attrs": {"question": "signups this week"}}, "[signups this week]"),
            ({"type": "mention", "attrs": {"label": "Shy"}}, "@Shy"),
        ]
    )
    def test_inline_objects_compile_to_what_agents_read(self, node, expected):
        doc = {"type": "doc", "content": [{"type": "paragraph", "content": [{"type": "text", "text": "See "}, node]}]}
        assert to_markdown(doc) == f"See {expected}\n"

    def test_empty_markdown_is_one_empty_paragraph(self):
        assert from_markdown("") == {"type": "doc", "content": [{"type": "paragraph"}]}
