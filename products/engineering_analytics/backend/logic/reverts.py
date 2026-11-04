"""Reverts: telling a pull request that undoes another apart from ordinary work, defined once.

GitHub records no link between a revert and the change it undoes, so the only signal in the
warehouse is the title. Two shapes name a revert:

- GitHub's revert button: ``Revert "<original title>"``.
- A conventional-commit title: ``revert: <subject>`` or ``revert(<scope>): <subject>``, with an
  optional breaking-change ``!`` before the colon, the form a repository that lints pull request
  titles produces.

Both patterns are anchored at the start of the title, so a title that merely mentions a revert
does not count. The pattern stays backslash-free so it survives embedding in a HogQL string
literal unescaped.
"""

_REVERT_TITLE_PATTERN = '(?i)^revert( "|([(][^()]*[)])?!?: )'


def revert_title_expr(title_column: str) -> str:
    """HogQL: whether ``title_column`` names a revert. ``ifNull`` keeps a NULL title from poisoning
    a ``countIf`` the way a NULL inside ``match`` would."""
    return f"match(ifNull({title_column}, ''), '{_REVERT_TITLE_PATTERN}')"
