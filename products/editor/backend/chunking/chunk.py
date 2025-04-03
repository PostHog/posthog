from typing import TypedDict

import tiktoken
from langchain.text_splitter import RecursiveCharacterTextSplitter
from tree_sitter import Node as SyntaxNode, Parser

from .parser import ProgrammingLanguage, get_parser_language


def get_token_count(content: str):
    encoding = tiktoken.get_encoding("o200k_base")
    return len(encoding.encode(content))


class TreeWalker:
    CAPTURE_NODES = {
        "class_definition",
        "class_declaration",
        "impl_item",
        "function_definition",
        "function_declaration",
        "function_item",
        "method_declaration",
        "method_definition",
    }

    def __init__(self, lang: ProgrammingLanguage, source_code: str, lookup_lines: set[int]):
        self.source_code = source_code.encode()
        self.root = Parser(get_parser_language(lang)).parse(self.source_code).root_node
        self.context: dict[int, str] = {}
        self.visited: set[SyntaxNode] = set()
        self.path: list[tuple[int, SyntaxNode]] = []
        self.lookup_lines = lookup_lines
        self.output: dict[int, str] = {}

    def traverse(self):
        def dfs(node: SyntaxNode):
            if node in self.visited:
                return
            self.visited.add(node)

            pop_path = False
            if node.type in self.CAPTURE_NODES:
                self.path.append((node.start_point.row, node))
                pop_path = True

            if node.start_point.row in self.lookup_lines:
                self.output[node.start_point.row] = self._format_path(self.path, node.start_point.row)

            for child in node.children:
                dfs(child)

            if pop_path:
                self.path.pop()

        dfs(self.root)

        return self.output

    def _format_path(self, path: list[tuple[int, SyntaxNode]], chunk_position: int) -> str:
        if not path:
            return ""

        prev_line: int | None = None
        output: list[str] = []

        for line, node in path:
            decl = self._extract_declaration_header(node)
            if not decl:
                continue

            if prev_line is not None and line - prev_line > 1:
                output[-1] += " ..."

            output.append(decl)
            prev_line = line

        if chunk_position - prev_line > 1:
            output[-1] += " ..."

        return "\n\n".join(output)

    def _extract_declaration_header(self, node: SyntaxNode) -> str | None:
        """Extract declaration header for functions, methods, or classes"""

        # Map of node types to their body node types
        body_type_map = {
            "function_declaration": ["block", "statement_block"],
            "function_definition": ["block", "statement_block"],
            "method_declaration": ["block", "statement_block"],
            "method_definition": ["block", "statement_block"],
            "function_item": ["block", "statement_block"],
            "class_declaration": ["class_body", "block", "declaration_list"],
            "class_definition": ["class_body", "block", "declaration_list"],
            "impl_item": ["block", "declaration_list"],  # Rust impl blocks
        }

        if node.type not in body_type_map:
            return None

        # Find the body node
        body_node = None
        for child in node.children:
            if child.type in body_type_map[node.type]:
                body_node = child
                break

        if body_node:
            # Extract text from declaration start to body start
            header = self.source_code[node.start_byte : body_node.start_byte].decode()
            return node.start_point.column * " " + header

        return None


class Chunk(TypedDict):
    line_start: int
    line_end: int
    context: str
    content: str


def chunk_code(lang: ProgrammingLanguage, content: str, chunk_size: int = 300, chunk_overlap: float = 0.2):
    token_count = get_token_count(content)
    if token_count < chunk_size:
        return content

    chunker = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=round(chunk_size * chunk_overlap),
        length_function=get_token_count,
        separators=["\n\n", "\n"],
    )
    chunks = chunker.split_text(content)
    chunks_with_positions: list[Chunk] = []
    capture_context_for: set[int] = set()

    for chunk in chunks:
        pos = content.find(chunk)
        line_number = content[:pos].count("\n") + 1
        chunks_with_positions.append(
            {
                "line_start": line_number,
                "line_end": line_number + chunk.count("\n"),
                "context": "",
                "content": chunk,
            }
        )
        capture_context_for.add(line_number)

    context = TreeWalker(lang, content, capture_context_for).traverse()

    for chunk in chunks_with_positions:
        chunk["context"] = context[chunk["line_start"]]

    return chunks_with_positions
