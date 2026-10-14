"""Whether two versions of a TypeScript file differ only in comments, judged with tree-sitter.

Python's `ast` is the interpreter's own parser. tree-sitter is not the TypeScript compiler, so this
module compares the token stream, which fixes the program, and not tree-sitter's tree:

- Every token must match, and the text between two tokens must be byte-identical unless a comment
  sits there in either version.
- Where a comment sits, the two versions must agree on whether a line break separates the tokens.
  A block comment that holds a line break counts as one for automatic semicolon insertion, so
  `return /*\\n*/ x` returns `undefined`. tree-sitter parses it the same as `return /* */ x`.
- Any text between two tokens that is neither whitespace nor a comment makes the file `logic`,
  because the comparison never reads it.
- tree-sitter recovers from a syntax error instead of raising, so a tree with an error node is
  `logic`.

A comment that a tool reads is code, as in Python: a compiler, linter, security scanner, bundler,
test runner or coverage directive, a triple-slash reference, or a pure annotation that changes tree
shaking. A change to its text, to the token it precedes, or to the number of line breaks between it
and that token makes the file `logic`, because a next-line directive applies to one physical line.
"""

import re
from collections.abc import Iterator
from dataclasses import dataclass
from typing import Literal

import tree_sitter_typescript
from tree_sitter import Language, Node, Parser

_TYPESCRIPT_PARSER = Parser(Language(tree_sitter_typescript.language_typescript()))
_TSX_PARSER = Parser(Language(tree_sitter_typescript.language_tsx()))

_LINE_BREAK_RE = re.compile(rb"\r\n|[\n\r]|\xe2\x80[\xa8\xa9]")

_DIRECTIVE_COMMENT_RE = re.compile(
    rb"^///\s*<|^/\*!|@ts-|@jsx|@internal|@license|@preserve|[#@]__[A-Z_]+__|"
    rb"nosemgrep|nosec|trunk-ignore|stylelint|"
    rb"eslint|oxlint|biome-|prettier-ignore|dprint-ignore|istanbul|\bc8\b|\bv8\s+ignore|"
    rb"webpack|vite-ignore|@vite-|source(?:Mapping)?URL=|@(?:vitest|jest)-environment",
    re.IGNORECASE,
)


@dataclass(frozen=True, kw_only=True)
class _Token:
    kind: str
    text: bytes
    separator: bytes
    separator_has_comment: bool
    between_tokens: bool


@dataclass(frozen=True, kw_only=True)
class _DirectiveComment:
    text: bytes
    tokens_before: int
    inline: bool
    line_breaks_to_next_token: int


@dataclass(frozen=True, kw_only=True)
class _LexedSource:
    tokens: tuple[_Token, ...]
    directives: tuple[_DirectiveComment, ...]


def _leaves(root: Node) -> Iterator[Node]:
    stack = [root]
    while stack:
        node = stack.pop()
        if node.type == "comment" or node.child_count == 0:
            yield node
        else:
            stack.extend(reversed(node.children))


def _has_line_break(text: bytes) -> bool:
    return _LINE_BREAK_RE.search(text) is not None


def _lex(source: bytes, *, tsx: bool) -> _LexedSource | None:
    """The tokens and directive comments of `source`, or None when it cannot be compared safely."""
    tree = (_TSX_PARSER if tsx else _TYPESCRIPT_PARSER).parse(source)
    if tree.root_node.has_error:
        return None
    tokens: list[_Token] = []
    directives: list[_DirectiveComment] = []
    awaiting_next_token: list[tuple[bytes, int, bool, int]] = []
    separator_start = 0
    previous_end = 0
    separator_has_comment = False
    for leaf in [*_leaves(tree.root_node), None]:
        start = len(source) if leaf is None else leaf.start_byte
        if source[previous_end:start].strip():
            return None
        if leaf is not None and leaf.type == "comment":
            text = source[leaf.start_byte : leaf.end_byte]
            if _DIRECTIVE_COMMENT_RE.search(text):
                inline = bool(tokens) and not _has_line_break(source[separator_start:start])
                awaiting_next_token.append((text, len(tokens), inline, leaf.end_byte))
            separator_has_comment = True
            previous_end = leaf.end_byte
            continue
        directives.extend(
            _DirectiveComment(
                text=text,
                tokens_before=tokens_before,
                inline=inline,
                line_breaks_to_next_token=len(_LINE_BREAK_RE.findall(source[end:start])),
            )
            for text, tokens_before, inline, end in awaiting_next_token
        )
        awaiting_next_token.clear()
        tokens.append(
            _Token(
                kind="end" if leaf is None else leaf.type,
                text=b"" if leaf is None else source[leaf.start_byte : leaf.end_byte],
                separator=source[separator_start:start],
                separator_has_comment=separator_has_comment,
                between_tokens=bool(tokens) and leaf is not None,
            )
        )
        if leaf is not None:
            separator_start = previous_end = leaf.end_byte
        separator_has_comment = False
    return _LexedSource(tokens=tuple(tokens), directives=tuple(directives))


def _same_program(base: _Token, head: _Token) -> bool:
    if (base.kind, base.text) != (head.kind, head.text):
        return False
    if base.separator_has_comment or head.separator_has_comment:
        return not base.between_tokens or _has_line_break(base.separator) == _has_line_break(head.separator)
    return base.separator == head.separator


def typescript_change_shape(base: bytes, head: bytes, *, tsx: bool) -> Literal["comment", "logic"]:
    """`comment` when only comments changed, else `logic`."""
    base_lexed = _lex(base, tsx=tsx)
    head_lexed = _lex(head, tsx=tsx)
    if base_lexed is None or head_lexed is None:
        return "logic"
    if base_lexed.directives != head_lexed.directives or len(base_lexed.tokens) != len(head_lexed.tokens):
        return "logic"
    if all(_same_program(b, h) for b, h in zip(base_lexed.tokens, head_lexed.tokens)):
        return "comment"
    return "logic"
