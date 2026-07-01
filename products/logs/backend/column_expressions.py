import hashlib

from posthog.hogql import ast

# The wire descriptor's `source` selects the lowering strategy (source-driven):
# flat map lookup for attribute maps, JSON dig for the body string.
FLAT_MAP_SOURCES = ("attributes", "resource_attributes")
JSON_BODY_SOURCE = "body"


def path_to_expr(source: str, path: str) -> ast.Expr:
    """Lower a custom-column descriptor `(source, path)` into a HogQL AST expression.

    - `attributes` / `resource_attributes`: the whole `path` is a single map key
      (dots are part of the OTel key, never split) -> `attributes['http.url']`.
    - `body`: `path` is a dot-separated JSON path -> `JSONExtractString(body, 'user', 'id')`.

    `path` is always carried as a bound chain member / Constant, so it cannot escape
    the map-index or JSONExtract boundary as interpolated SQL.
    """
    if source in FLAT_MAP_SOURCES:
        return ast.Field(chain=[source, path])

    if source == JSON_BODY_SOURCE:
        keys = [ast.Constant(value=segment) for segment in path.split(".")]
        return ast.Call(name="JSONExtractString", args=[ast.Field(chain=[JSON_BODY_SOURCE]), *keys])

    raise ValueError(f"Unknown custom-column source: {source!r}")


def canonical_key(source: str, path: str) -> str:
    """Derive a stable `col_<hash>` alias from `(source, path)`.

    Independent of any client-generated uuid so identical column setups hash to the
    same query (and therefore the same query cache key). The null separator keeps
    e.g. `("ab", "c")` and `("a", "bc")` from colliding.
    """
    digest = hashlib.sha256(f"{source}\x00{path}".encode()).hexdigest()
    return f"col_{digest[:12]}"
