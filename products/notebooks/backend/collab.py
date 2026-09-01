"""
prosemirror-collab step buffering for rich (v1) notebooks.

The buffering itself is the shared transport in `posthog/collab/steps.py`; this module
binds it to the notebook namespace.
"""

from posthog.collab.steps import (
    StepEntry as StepEntry,
    SubmitResult as SubmitResult,
    submit_steps as _submit_steps,
)

from products.notebooks.backend.collab_stream import NOTEBOOK_COLLAB_NAMESPACE


def submit_steps(
    team_id: int,
    notebook_id: str,
    client_id: str,
    steps_json: list[dict],
    last_seen_version: int,
    *,
    last_saved_version: int,
    user_id: int | None = None,
    user_name: str | None = None,
    cursor_head: int | None = None,
) -> SubmitResult:
    return _submit_steps(
        NOTEBOOK_COLLAB_NAMESPACE,
        team_id,
        notebook_id,
        client_id,
        steps_json,
        last_seen_version,
        last_saved_version=last_saved_version,
        user_id=user_id,
        user_name=user_name,
        cursor_head=cursor_head,
    )
