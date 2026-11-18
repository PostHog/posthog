"""GitHub records no link between a revert and the change it undoes, so the title is the only
signal. A revert is GitHub's ``Revert "<original title>"`` or a conventional-commit
``revert: <subject>`` / ``revert(<scope>): <subject>`` title.
"""

# The pattern has no backslash, so it can sit in a HogQL string literal unescaped.
_REVERT_TITLE_PATTERN = '(?i)^revert( "|([(][^()]*[)])?!?: )'


def revert_title_expr(title_column: str) -> str:
    """A HogQL boolean expression. It is false for a NULL title, so it is safe inside ``countIf``."""
    return f"match(ifNull({title_column}, ''), '{_REVERT_TITLE_PATTERN}')"
