"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="stack",
        name="Stack",
        plural="stacks",
        description="Diffs and pushes of definitions managed in code, their bindings, and adopting or detaching entities.",
        group="Developer experience",
    ),
)
