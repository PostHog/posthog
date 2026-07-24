import dataclasses
from typing import Literal, Optional


class FanoutParentDependencyError(Exception):
    """A fan-out child can't be enabled because of its required parent; str() is the canonical
    user-facing message, shared by the schema-update serializer and the source-creation view."""


@dataclasses.dataclass(frozen=True)
class FanoutParentState:
    """Parent-schema facts the dependency rules need, normalized from either a model instance
    (schema update) or a creation-payload entry (source create)."""

    enabled: bool
    is_append: bool
    has_sync_type: bool


def resolve_fanout_parent_action(
    child_name: str,
    parent_name: str,
    parent: Optional[FanoutParentState],
    *,
    requires_sync_type: bool,
) -> Literal["ok", "enable"]:
    """Decide what to do about one required parent when enabling a fan-out child.

    Returns "ok" (parent already syncing) or "enable" (caller flips the parent on through its
    own mechanism). Raises FanoutParentDependencyError when the child can't be enabled:

    - parent missing from the source,
    - parent on append sync — its table accumulates duplicate rows and the streaming
      warehouse reader has no dedupe, so the child would fan out once per duplicate,
    - parent not configured — auto-enabling a schema without a sync type would create an
      invalid state, so the caller must set the parent up first.

    Keeping the rules and wording here is what stops the two call sites from drifting.
    """
    if parent is None:
        raise FanoutParentDependencyError(
            f"'{child_name}' syncs using the '{parent_name}' schema's data, "
            f"but this source has no '{parent_name}' schema."
        )
    if parent.is_append:
        raise FanoutParentDependencyError(
            f"'{child_name}' syncs using the '{parent_name}' schema's data, "
            f"so '{parent_name}' can't use append sync. "
            f"Switch '{parent_name}' to incremental or full refresh first."
        )
    if parent.enabled:
        return "ok"
    if requires_sync_type and not parent.has_sync_type:
        raise FanoutParentDependencyError(
            f"'{child_name}' syncs using the '{parent_name}' schema's data. Set up and enable '{parent_name}' first."
        )
    return "enable"
