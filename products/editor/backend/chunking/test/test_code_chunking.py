from posthog.test.base import BaseTest
from products.editor.backend.chunking import ProgrammingLanguage, chunk_text

from .util import load_fixture


class TestCodeChunking(BaseTest):
    def test_jsx(self):
        with load_fixture("jsx.txt") as content:
            chunks = chunk_text(content, language=ProgrammingLanguage.JAVASCRIPT)
            self.assertEqual(len(chunks), 5)
            for chunk in chunks[1:4]:
                self.assertIn("function", chunk.context)

    def test_go(self):
        with load_fixture("go.txt") as content:
            chunks = chunk_text(content, language=ProgrammingLanguage.GO)
            self.assertEqual(len(chunks), 5)
            for chunk in chunks[1:4]:
                self.assertIn("func main", chunk.context)

    def test_rust(self):
        with load_fixture("rust.txt") as content:
            chunks = chunk_text(content, language=ProgrammingLanguage.RUST)
            self.assertEqual(len(chunks), 7)
            for chunk in chunks[2:]:
                self.assertIn("impl RawJSFrame", chunk.context)
            self.assertIn("fn resolve_impl", chunks[3].context)
            self.assertIn("fn source_url", chunks[5].context)
            self.assertIn("fn source_url", chunks[6].context)

    def test_typescript(self):
        with load_fixture("ts.txt") as content:
            chunks = chunk_text(content, language=ProgrammingLanguage.TYPESCRIPT)
            self.assertEqual(len(chunks), 5)
            self.assertFalse(chunks[0].context)
            self.assertFalse(chunks[1].context)
            self.assertIn("ConcurrencyControllerItem", chunks[2].context)
            self.assertFalse(chunks[3].context)
            self.assertIn("ConcurrencyController", chunks[4].context)

    def test_typescript_jsx(self):
        with load_fixture("jsx.txt") as content:
            chunks = chunk_text(content, language=ProgrammingLanguage.TSX)
            self.assertEqual(len(chunks), 5)
            for chunk in chunks[1:4]:
                self.assertIn("function", chunk.context)

    def test_python(self):
        with load_fixture("python.txt") as content:
            chunks = chunk_text(content, language=ProgrammingLanguage.PYTHON)
            self.assertEqual(len(chunks), 7)
            self.assertFalse(chunks[0].context)
            self.assertFalse(chunks[1].context)
            for chunk in chunks[2:5]:
                self.assertIn("class Action", chunk.context)
            self.assertFalse(chunks[6].context)
