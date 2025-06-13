from langchain.text_splitter import RecursiveCharacterTextSplitter
from tree_sitter import Node as SyntaxNode, Parser

from ..llm.token_counter import get_token_count
from .parser import ProgrammingLanguage, get_parser_language
from .types import Chunk


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
        self.path: list[tuple[int, SyntaxNode]] = []
        self.lookup_lines = lookup_lines
        self.output: dict[int, str] = {}

    def traverse(self):
        def dfs(node: SyntaxNode):
            start_line_number = node.start_point.row
            end_line_number = node.end_point.row

            pop_path = False
            if node.type in self.CAPTURE_NODES:
                self.path.append((start_line_number, node))
                pop_path = True

            for child in node.children:
                dfs(child)

            if self.path:
                for lookup_line in self.lookup_lines:
                    if (
                        # The deepest win
                        lookup_line not in self.output
                        # Shouldn't capture the left boundary as the chunk starts there
                        and start_line_number < lookup_line
                        and lookup_line <= end_line_number
                    ):
                        self.output[lookup_line] = self._format_path(self.path, lookup_line)

            if pop_path:
                self.path.pop()

        dfs(self.root)

        return self.output

    def _format_path(self, path: list[tuple[int, SyntaxNode]], chunk_position: int) -> str:
        if not path:
            return ""

        prev_line: int | None = None
        output: list[str] = []

        def add_ellipsis():
            if prev_line is not None and chunk_position - prev_line > 1:
                output[-1] += " ..."

        for line, node in path:
            decl = self._extract_declaration_header(node)
            if not decl:
                continue

            add_ellipsis()

            output.append(decl)
            prev_line = line

        add_ellipsis()

        return "\n\n".join(output)

    def _extract_declaration_header(self, node: SyntaxNode) -> str | None:
        """Extract declaration header for functions, methods, or classes"""

        # Map of node types to their body node types
        body_type_map = {
            "function_declaration": ["block", "statement_block"],
            "function_definition": ["block", "statement_block", "compound_statement"],
            "method_declaration": ["block", "statement_block"],
            "method_definition": ["block", "statement_block"],
            "function_item": ["block", "statement_block"],
            "class_declaration": ["class_body", "block", "declaration_list"],
            "class_definition": ["class_body", "block", "declaration_list"],
            "impl_item": ["block", "declaration_list"],  # Rust impl blocks
        }

        def indent(header: str):
            return node.start_point.column * " " + header

        if node.type in body_type_map:
            body_node = None
            for child in node.children:
                if child.type in body_type_map[node.type]:
                    body_node = child
                    break

            if body_node:
                header = self.source_code[node.start_byte : body_node.start_byte].decode()
                return indent(header)

        return None


def chunk_code(lang: ProgrammingLanguage, content: str, chunk_size: int, chunk_overlap: float) -> list[Chunk]:
    chunker = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size,
        chunk_overlap=round(chunk_size * chunk_overlap),
        length_function=get_token_count,
        separators=["\n\n", "\n"],
    )
    chunks = chunker.split_text(content)
    chunks_with_positions: list[Chunk] = []
    capture_context_for: set[int] = set()

    # In case chunks are exactly the same, but their enclosing context is different.
    current_pos = 0

    for chunk in chunks:
        pos = content.find(chunk, current_pos)
        current_pos = pos + 1

        line_number = content[:pos].count("\n")
        line_end = line_number + chunk.count("\n")

        chunks_with_positions.append(
            Chunk(
                line_start=line_number,
                line_end=line_end,
                context="",
                content=chunk,
            )
        )
        capture_context_for.add(line_number)

    chunk_context = TreeWalker(lang, content, capture_context_for).traverse()

    for chunk in chunks_with_positions:
        if chunk.line_start in chunk_context:
            chunk.context = chunk_context[chunk.line_start]

    return chunks_with_positions
