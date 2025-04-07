from posthog.test.base import BaseTest
from products.editor.backend.chunking import chunk_text

from .util import load_fixture


class TestTextChunking(BaseTest):
    def test_chunk_text(self):
        with load_fixture("md.txt") as content:
            chunks = chunk_text("markdown", content)
            self.assertEqual(len(chunks), 2)
            self.assertFalse(chunks[0].context)
            self.assertFalse(chunks[1].context)
