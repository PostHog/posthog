from collections.abc import Mapping

from products.workflows.backend.models.hog_flow.hog_flow import HogFlow
from products.workflows.backend.services.hog_flow_secrets import strip_content_secrets

# The content of a workflow: everything the draft cycle stages and publish promotes, and nothing
# else. Metadata (name, description) and lifecycle (status) always apply to the live row. The draft
# blob is a full snapshot of these fields so publish is a plain copy, not a merge.
DRAFT_CONTENT_FIELDS = (
    "actions",
    "edges",
    "trigger",
    "trigger_masking",
    "conversion",
    "exit_condition",
    "email_sending_rate_limit",
    "abort_action",
    "variables",
)


def deep_merge(target: dict, patch: dict) -> dict:
    """Recursively merge `patch` into `target`. A null leaf deletes the key; a dict merges into a
    dict; anything else replaces. Lets a caller change config.inputs.subject without resending the
    rest of config."""
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            deep_merge(target[key], value)
        else:
            target[key] = value
    return target


def snapshot_content(values: Mapping[str, object]) -> dict:
    """A workflow's content fields in the API shape, without secrets."""
    snapshot = {field: values.get(field) for field in DRAFT_CONTENT_FIELDS}
    # The model's legacy default for actions/edges is `{}`, but the API shape is a list — normalize
    # so re-validation of a snapshot (draft publish, revision restore) doesn't choke on a
    # never-edited column.
    for field in ("actions", "edges"):
        if not snapshot[field]:
            snapshot[field] = []
    # Defensively strip secrets: a legacy row written before encryption shipped still has plaintext
    # secret inputs in `actions`, and this snapshot feeds revision content — which must never carry
    # secrets. New rows are already stripped, so this is a no-op for them. Every create takes a
    # snapshot inside its transaction, so the cache resolves each template once instead of once per
    # action.
    return strip_content_secrets(snapshot, template_cache={})


def snapshot_flow_content(flow: HogFlow) -> dict:
    return snapshot_content({field: getattr(flow, field) for field in DRAFT_CONTENT_FIELDS})
