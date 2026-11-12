"""What each API scope object this product owns is for. See posthog/scope_docs.py."""

from posthog.scope_docs import ScopeDoc

SCOPE_DOCS = (
    ScopeDoc(
        object="task",
        name="Task",
        plural="tasks",
        description="Agent tasks and their runs, logs, artifacts, threads, channels, and sandbox environments.",
        group="AI & context management tools",
        docs_url="https://posthog.com/docs/tasks",
    ),
)
