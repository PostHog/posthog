"""GitHub records no link between a revert and the change it undoes, so the title is the only
signal. A revert is GitHub's ``Revert "<original title>"`` or a conventional-commit
``revert: <subject>`` / ``revert(<scope>): <subject>`` title.
"""

# The pattern has no backslash, so it can sit in a HogQL string literal unescaped.
_REVERT_TITLE_PATTERN = '(?i)^revert( "|([(][^()]*[)])?!?: )'


def revert_title_expr(title_column: str) -> str:
    """A HogQL boolean expression. It is false for a NULL title, so it is safe inside ``countIf``."""
    return f"match(ifNull({title_column}, ''), '{_REVERT_TITLE_PATTERN}')"


_REVERTED_REFERENCE_PATTERN = (
    "(?im)^[[:blank:]]*(?:this[[:blank:]]+)?reverts[[:blank:]]+(?:([a-z0-9_.-]+/[a-z0-9_.-]+))?#([0-9]+)"
)


def reverted_pr_number_expr(*, title_column: str, body_column: str, repo_full_name_column: str) -> str:
    body = f"ifNull({body_column}, '')"
    referenced_repo = f"regexpExtract({body}, '{_REVERTED_REFERENCE_PATTERN}', 1)"
    referenced_number = f"regexpExtract({body}, '{_REVERTED_REFERENCE_PATTERN}', 2)"
    names_this_repo = f"({referenced_repo} = '' OR lower({referenced_repo}) = lower({repo_full_name_column}))"
    return f"if({revert_title_expr(title_column)} AND {names_this_repo}, toInt({referenced_number}), NULL)"
