import copy
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from functools import partial
from typing import Any, Literal

from posthog.models.activity_logging.activity_log import Change, Detail, Trigger, changes_between, log_activity
from posthog.models.signals import model_activity_signal, mutable_receiver

from products.feature_flags.backend.facade.activity import config_change_context, is_v1_config, json_equal
from products.feature_flags.backend.models.feature_flag import FeatureFlag

# Lives here, not in api/feature_flag.py, so it can wire at AppConfig.ready() without dragging that
# viewset (which pulls scipy via the dashboard -> error-tracking query runners cross-import) onto the
# django.setup() path. Flags are mutated outside web requests (cohort recalculation, scheduled
# changes), so the audit log must connect in every process.


@contextmanager
def complete_feature_flag_activity(flag: FeatureFlag) -> Iterator[None]:
    # The tag mixin persists relations after save(); finish the same audit entry after those writes.
    callbacks: list[Callable[[], None]] = []
    flag.__dict__["_activity_log_callbacks"] = callbacks
    flag.__dict__["_activity_before_tags"] = sorted(flag.tagged_items.values_list("tag__name", flat=True))
    try:
        yield
        delattr(flag, "_activity_log_callbacks")
        for callback in callbacks:
            callback()
    finally:
        flag.__dict__.pop("_activity_log_callbacks", None)
        flag.__dict__.pop("_activity_before_tags", None)


@mutable_receiver(model_activity_signal, sender=FeatureFlag)
def handle_feature_flag_change(
    sender: type[FeatureFlag],
    scope: Literal["FeatureFlag"],
    before_update: FeatureFlag | None,
    after_update: FeatureFlag,
    activity: str,
    was_impersonated: bool = False,
    **kwargs: Any,
) -> None:
    callbacks = getattr(after_update, "_activity_log_callbacks", None)
    if callbacks is not None:
        callbacks.append(
            partial(
                handle_feature_flag_change,
                sender,
                scope,
                before_update,
                after_update,
                activity,
                was_impersonated=was_impersonated,
                **kwargs,
            )
        )
        return

    # Extract scheduled change context if present
    scheduled_change_context = getattr(after_update, "_scheduled_change_context", {})
    scheduled_change_id = scheduled_change_context.get("scheduled_change_id")
    is_scheduled_change = scheduled_change_id is not None

    # A caller that rewrites the flag as a side effect of another action (for example the
    # experiment exposure freeze) sets _activity_trigger on the instance before the gated
    # write, so the log entry can say what drove the rewrite instead of reading as a
    # manual edit. An explicit caller trigger wins over the derived scheduled-change one.
    trigger = getattr(after_update, "_activity_trigger", None)
    if is_scheduled_change and trigger is None:
        trigger = Trigger(
            job_type="scheduled_change",
            job_id=str(scheduled_change_id),
            payload={"scheduled_change_id": scheduled_change_id},
        )

    changes = changes_between(scope, previous=before_update, current=after_update)
    before_filters = before_update.filters if before_update is not None else None
    after_filters = after_update.filters
    context = None
    if not is_v1_config(before_filters) or not is_v1_config(after_filters):
        # Django's empty-value comparison loses null/empty distinctions in opaque JSON.
        changes = [change for change in changes if change.field not in ("filters", "name")]
        if before_update is None or not json_equal(before_filters, after_filters):
            changes.append(
                Change(
                    type="FeatureFlag",
                    field="filters",
                    action="changed" if before_update is not None else "created",
                    before=copy.deepcopy(before_filters),
                    after=copy.deepcopy(after_filters),
                )
            )
        if before_update is not None and before_update.name != after_update.name:
            changes.append(
                Change(
                    type="FeatureFlag",
                    field="name",
                    action="changed",
                    before=before_update.name,
                    after=after_update.name,
                )
            )
        before_tags = getattr(after_update, "_activity_before_tags", None)
        if before_tags is not None:
            after_tags = sorted(after_update.tagged_items.values_list("tag__name", flat=True))
            if before_tags != after_tags:
                changes.append(
                    Change(type="FeatureFlag", field="tags", action="changed", before=before_tags, after=after_tags)
                )
        context = config_change_context(before_filters, after_filters)
    resolved_activity = activity
    deleted_change = next((change for change in changes if change.field == "deleted"), None)
    if deleted_change:
        if bool(deleted_change.after):
            resolved_activity = "deleted"
        elif bool(deleted_change.before):
            resolved_activity = "restored"

    log_activity(
        organization_id=after_update.team.organization_id,
        team_id=after_update.team_id,
        user=after_update.last_modified_by,
        was_impersonated=was_impersonated,
        item_id=after_update.id,
        scope=scope,
        activity=resolved_activity,
        detail=Detail(
            changes=changes,
            name=after_update.key,
            trigger=trigger,
            context=context,
        ),
    )
