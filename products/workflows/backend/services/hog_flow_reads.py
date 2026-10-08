"""Reading workflows for the API: one workflow behind the reader's object access check, or a filtered,
searched and access-filtered page of them. Each workflow is a contract with its secret inputs masked."""

import re
from collections.abc import Mapping
from typing import TYPE_CHECKING, Final, Optional, cast
from uuid import UUID

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Count, F, OuterRef, Q, QuerySet, Subquery, Value
from django.db.models.expressions import RawSQL
from django.db.models.functions import Coalesce

from django_filters import BooleanFilter, FilterSet

from products.workflows.backend.facade.contracts import (
    Workflow,
    WorkflowAccessDenied,
    WorkflowArchived,
    WorkflowEditState,
    WorkflowListFilterError,
    WorkflowListFiltersInvalid,
    WorkflowListQuery,
    WorkflowNotFound,
    WorkflowPage,
    WorkflowRef,
)
from products.workflows.backend.facade.enums import HogFlowScheduleStatus, WorkflowProposalStatus
from products.workflows.backend.models.hog_flow.hog_flow import MESSAGING_ACTION_TYPES, HogFlow
from products.workflows.backend.models.hog_flow_schedule import HogFlowSchedule
from products.workflows.backend.models.workflow_proposal import WorkflowProposal
from products.workflows.backend.services.batch_jobs import hog_flow_ids_with_broadcast_status
from products.workflows.backend.services.hog_flow_schedules import list_schedules_oldest_first
from products.workflows.backend.services.hog_flow_secrets import TemplateCache, mask_workflow_fields
from products.workflows.backend.services.publish_impact import build_publish_impact

if TYPE_CHECKING:
    from products.access_control.backend.facade.user_access_control import AccessControlLevel, UserAccessControl


def get_workflow(
    *,
    team_id: int,
    workflow_id: UUID | str,
    user_access_control: "UserAccessControl | None",
    required_level: str | None,
) -> Workflow:
    """The team's workflow, or WorkflowNotFound, or WorkflowAccessDenied when the reader's level for
    it is below `required_level`. Pass None for both access arguments to skip the check, as a
    service credential does."""
    flow = _checked_flow(team_id, workflow_id, user_access_control, required_level, created_by=True)
    return _to_workflow(flow, user_access_control, template_cache={}, with_schedules=True)


def get_workflow_ref(
    *,
    team_id: int,
    workflow_id: UUID | str,
    user_access_control: "UserAccessControl | None",
    required_level: str | None,
) -> WorkflowRef:
    """The same lookup and access check as get_workflow, for an action that only needs the workflow's
    identity and dispatch settings."""
    flow = _checked_flow(team_id, workflow_id, user_access_control, required_level, created_by=False)
    trigger = flow.trigger if isinstance(flow.trigger, dict) else {}
    return WorkflowRef(
        id=flow.id,
        team_id=flow.team_id,
        name=flow.name,
        status=flow.status,
        version=flow.version,
        trigger_type=trigger.get("type"),
        trigger_filters=trigger.get("filters") or {},
        variables=flow.variables,
    )


def get_workflow_edit_state(
    *,
    team_id: int,
    workflow_id: UUID | str,
    user_access_control: "UserAccessControl | None",
    required_level: str | None,
) -> WorkflowEditState:
    """The same lookup and access check as get_workflow, for an edit the serializer validates against
    the stored workflow."""
    flow = _checked_flow(team_id, workflow_id, user_access_control, required_level, created_by=True)
    return to_edit_state(flow)


def get_team_workflow_edit_state(
    *, team_id: int, workflow_id: UUID | str, user_access_control: "UserAccessControl", required_level: str
) -> WorkflowEditState:
    """The team's workflow for an edit made outside a request, read once for the archived and access checks.
    An archived workflow raises WorkflowArchived before the access check, so every caller gets the same answer."""
    try:
        flow = HogFlow.objects.select_related("created_by").get(team_id=team_id, pk=workflow_id)
    except (HogFlow.DoesNotExist, ValidationError, ValueError):
        raise WorkflowNotFound()
    if flow.status == HogFlow.State.ARCHIVED:
        raise WorkflowArchived()
    if not user_access_control.check_access_level_for_object(
        flow, required_level=cast("AccessControlLevel", required_level)
    ):
        raise WorkflowAccessDenied(required_level)
    return to_edit_state(flow)


def to_edit_state(flow: HogFlow) -> WorkflowEditState:
    return WorkflowEditState(
        id=flow.id,
        team_id=flow.team_id,
        name=flow.name,
        status=flow.status,
        version=flow.version,
        origin_product=flow.origin_product,
        created_by=flow.created_by,
        updated_at=flow.updated_at,
        trigger=flow.trigger,
        trigger_masking=flow.trigger_masking,
        conversion=flow.conversion,
        exit_condition=flow.exit_condition,
        email_sending_rate_limit=flow.email_sending_rate_limit,
        edges=flow.edges,
        actions=flow.actions,
        abort_action=flow.abort_action,
        variables=flow.variables,
        draft=flow.draft,
        draft_updated_at=flow.draft_updated_at,
        encrypted_inputs=flow.encrypted_inputs,
        draft_encrypted_inputs=flow.draft_encrypted_inputs,
    )


def workflow_from_fields(*, fields: Mapping[str, object], user_access_control: "UserAccessControl | None") -> Workflow:
    """The workflow a write left behind, built from the field values the write returned rather than
    read again, so a write another request commits afterwards does not show in this response."""
    return _to_workflow(HogFlow(**fields), user_access_control, template_cache={}, with_schedules=True)


def workflow_publish_impact(
    *, team_id: int, hog_flow_id: UUID, by_action_counts: Optional[dict], position_unknown: Optional[int]
) -> dict:
    """What publishing the staged draft does to the runs in flight."""
    flow = HogFlow.objects.get(team_id=team_id, pk=hog_flow_id)
    draft = flow.draft or {}
    schedule_overrides = {
        str(schedule_id): variables or {}
        for schedule_id, variables in HogFlowSchedule.objects.filter(hog_flow_id=flow.id)
        .exclude(status=HogFlowScheduleStatus.COMPLETED)
        .values_list("id", "variables")
    }
    return build_publish_impact(
        live_actions=flow.actions or [],
        live_edges=flow.edges or [],
        live_variables=flow.variables or [],
        draft_actions=draft.get("actions") or [],
        draft_variables=draft.get("variables") or [],
        existing_redirects=flow.action_redirects,
        by_action_counts=by_action_counts,
        position_unknown=position_unknown,
        schedule_overrides=schedule_overrides,
    )


def _checked_flow(
    team_id: int,
    workflow_id: UUID | str,
    user_access_control: "UserAccessControl | None",
    required_level: str | None,
    *,
    created_by: bool,
) -> HogFlow:
    queryset = HogFlow.objects.select_related("created_by") if created_by else HogFlow.objects.all()
    try:
        flow = queryset.get(team_id=team_id, pk=workflow_id)
    except (HogFlow.DoesNotExist, ValidationError, ValueError):
        # ValidationError and ValueError fire when the id is not a parseable UUID.
        raise WorkflowNotFound()
    # The same check AccessControlPermission.has_object_permission runs on a model viewset's object.
    if (
        user_access_control is not None
        and required_level is not None
        and not user_access_control.check_access_level_for_object(
            flow, required_level=cast("AccessControlLevel", required_level)
        )
    ):
        raise WorkflowAccessDenied(required_level)
    return flow


# The query parameters the field filter set reads. The view passes these through as they arrived.
WORKFLOW_FIELD_FILTER_PARAMS: Final[tuple[str, ...]] = (
    "id",
    "created_at",
    "updated_at",
    "status",
    "origin_product",
    "optimization_enabled",
)


def list_workflows(
    *,
    team_id: int,
    query: WorkflowListQuery,
    user_access_control: "UserAccessControl | None",
    include_all_if_admin: bool,
    offset: int,
    limit: int,
) -> WorkflowPage:
    """One page of the team's workflows that match `query` and that the reader may see. Pass None
    for `user_access_control` to skip the access filter, as a service credential does. Raises
    WorkflowListFiltersInvalid when a field filter does not parse."""
    queryset = _list_queryset(team_id, query, user_access_control, include_all_if_admin)
    count = queryset.count()
    # The same bounds LimitOffsetPagination applies to a queryset.
    flows = [] if count == 0 or offset > count else list(queryset[offset : offset + limit])
    if user_access_control is not None and flows:
        user_access_control.preload_object_access_controls(cast("list[models.Model]", flows))
    template_cache: TemplateCache = {}
    return WorkflowPage(
        count=count,
        results=[_to_workflow(flow, user_access_control, template_cache, with_schedules=False) for flow in flows],
    )


def _list_queryset(
    team_id: int,
    query: WorkflowListQuery,
    user_access_control: "UserAccessControl | None",
    include_all_if_admin: bool,
) -> QuerySet:
    queryset = HogFlow.objects.filter(team_id=team_id).select_related("created_by")

    pending = (
        WorkflowProposal.objects.filter(hog_flow=OuterRef("pk"), status=WorkflowProposalStatus.SUGGESTED)
        .order_by()
        .values("hog_flow")
        .annotate(count=Count("id"))
        .values("count")
    )
    queryset = queryset.annotate(
        pending_suggestions=Coalesce(Subquery(pending), 0),
        suggestions_enabled=Coalesce(F("optimization__enabled"), Value(False)),
    )
    # A suggestion waits on a person, so the page that shows them sorts it above recency. Every
    # other reader of this list — the MCP tool, any other surface — keeps recency, or a stale
    # workflow with one suggestion would push a fresh one off their first page.
    # `id` breaks ties so LIMIT/OFFSET paging stays stable: rows sharing an updated_at can
    # otherwise repeat on one page and never appear on another.
    if query.suggestions_first:
        queryset = queryset.order_by("-pending_suggestions", "-updated_at", "-id")
    else:
        queryset = queryset.order_by("-updated_at", "-id")

    if query.created_by_uuid is not None:
        queryset = queryset.filter(created_by__uuid=query.created_by_uuid)

    if query.types:
        queryset = queryset.filter(workflow_type_q(set(query.types)))

    if query.broadcast_eligible:
        queryset = annotate_broadcast_shape(queryset).filter(
            Q(origin_product=HogFlow.OriginProduct.BROADCASTS)
            | Q(
                origin_product__isnull=True,
                _has_batch_trigger=True,
                _email_step_count=1,
                _has_other_step=False,
            )
        )

    if query.broadcast_statuses:
        queryset = queryset.filter(
            id__in=hog_flow_ids_with_broadcast_status(team_id=team_id, statuses=query.broadcast_statuses)
        )

    # `?type=loop` and `?type=broadcast` return the same rows, but Desktop's Loops list sends
    # this param and ships on its own release cadence, so installed builds keep sending it.
    if query.origin_product:
        queryset = queryset.filter(origin_product=query.origin_product)

    if query.trigger:
        queryset = queryset.filter(trigger__contains=query.trigger)

    if user_access_control is not None:
        queryset = user_access_control.filter_queryset_by_access_level(
            queryset, include_all_if_admin=include_all_if_admin
        )

    filterset = _WorkflowFilterSet(data=query.field_filters, queryset=queryset)
    if not filterset.is_valid():
        # Format each message and keep each code the way DjangoFilterBackend does, so that this 400 body
        # matches the body of every other filtered list endpoint.
        raise WorkflowListFiltersInvalid(
            {
                name: [
                    WorkflowListFilterError(message=str(error.message % (error.params or ())), code=error.code)
                    for error in errors
                ]
                for name, errors in filterset.errors.as_data().items()
            }
        )
    queryset = filterset.qs

    # Search runs after the field filters so the tier decision below sees the same rows the response
    # will: a name match that the `status` filter then drops must not stop the step search from running.
    if not query.search:
        return queryset
    # Escape regex metacharacters, then let spaces match any run of space/dash/underscore
    # so "welcome email" also matches "welcome-email" — same approach as feature flag search.
    regex_pattern = re.escape(query.search).replace(r"\ ", r"[\s\-_]*")

    # Name and description are small columns, while the step search has to read every workflow's `actions`
    # JSON (tens of KB per email step). Only fall through to the step content when nothing matched by
    # name, so the common search stays cheap and a subject line or body text, which rarely appears in a
    # workflow name, is still found.
    by_name = Q(name__iregex=regex_pattern) | Q(description__iregex=regex_pattern)
    if queryset.filter(by_name).exists():
        return queryset.filter(by_name)
    return queryset.filter(Q(_action_content_matches(regex_pattern)))


def _to_workflow(
    flow: HogFlow,
    user_access_control: "UserAccessControl | None",
    template_cache: TemplateCache,
    *,
    with_schedules: bool,
) -> Workflow:
    masked: dict[str, object] = {"actions": flow.actions, "trigger": flow.trigger, "draft": flow.draft}
    mask_workflow_fields(
        masked,
        live_actions=flow.actions,
        live_trigger=flow.trigger,
        encrypted_inputs=flow.encrypted_inputs,
        draft_encrypted_inputs=flow.draft_encrypted_inputs,
        template_cache=template_cache,
    )
    access_level: Optional[str] = (
        user_access_control.get_user_access_level(flow) if user_access_control is not None else None
    )
    return Workflow(
        id=flow.id,
        team_id=flow.team_id,
        name=flow.name,
        description=flow.description,
        version=flow.version,
        status=flow.status,
        origin_product=flow.origin_product,
        created_at=flow.created_at,
        created_by=flow.created_by,
        updated_at=flow.updated_at,
        trigger=masked["trigger"],
        trigger_masking=flow.trigger_masking,
        conversion=flow.conversion,
        exit_condition=flow.exit_condition,
        email_sending_rate_limit=flow.email_sending_rate_limit,
        edges=flow.edges,
        actions=cast("list[dict] | dict", masked["actions"]),
        abort_action=flow.abort_action,
        variables=flow.variables,
        billable_action_types=flow.billable_action_types,
        schedules=tuple(list_schedules_oldest_first(team_id=flow.team_id, hog_flow_id=flow.id))
        if with_schedules
        else (),
        draft=cast("dict | None", masked["draft"]),
        draft_updated_at=flow.draft_updated_at,
        action_redirects=flow.action_redirects,
        email_sending_paused_at=flow.email_sending_paused_at,
        email_sending_paused_reason=flow.email_sending_paused_reason,
        email_sending_paused_by=flow.email_sending_paused_by,
        email_sending_resumed_at=flow.email_sending_resumed_at,
        user_access_level=access_level,
        pending_suggestions=getattr(flow, "pending_suggestions", None),
        suggestions_enabled=getattr(flow, "suggestions_enabled", None),
    )


# A workflow's type is what owns it, else what it does. `loop` and `broadcast` name the surfaces that
# have their own page, and the behavioural values exclude them: a flow those surfaces own is tagged
# by surface in the UI (see WorkflowTypeTag), so returning it under `messaging` would contradict the
# tag on the row. Accepting several lets a list say which surfaces it covers, which is how the
# workflows page asks for everything except the ones that moved out.
WORKFLOW_TYPES: Final[tuple[str, ...]] = ("messaging", "automation", "loop", "broadcast")
OWNED_WORKFLOW_TYPES: Final[dict[str, str]] = {
    "loop": HogFlow.OriginProduct.LOOPS,
    "broadcast": HogFlow.OriginProduct.BROADCASTS,
}


def workflow_type_q(requested: set[str]) -> Q:
    owned = Q(origin_product__in=[OWNED_WORKFLOW_TYPES[t] for t in requested if t in OWNED_WORKFLOW_TYPES])
    behavioural = requested - set(OWNED_WORKFLOW_TYPES)
    if not behavioural:
        return owned

    messaging = Q()
    for action_type in MESSAGING_ACTION_TYPES:
        messaging |= Q(actions__contains=[{"type": action_type}])
    unowned = ~Q(origin_product__in=list(OWNED_WORKFLOW_TYPES.values()))
    if behavioural == {"messaging", "automation"}:
        return owned | unowned
    return owned | (unowned & (messaging if behavioural == {"messaging"} else ~messaging))


BROADCAST_TRIGGER_TYPE = "batch"
BROADCAST_ALLOWED_ACTION_TYPES = frozenset({"trigger", "function_email", "exit"})


def _json_path(path: str) -> models.Func:
    # A jsonpath bind parameter. Postgres types a plain parameter as text and the jsonb_path_*
    # functions take jsonpath, so the cast has to be spelled out.
    return models.Func(models.Value(path), template="%(expressions)s::jsonpath", output_field=models.TextField())


def _jsonb_path_exists(path: str) -> models.Func:
    return models.Func(
        models.F("actions"),
        _json_path(path),
        function="jsonb_path_exists",
        output_field=models.BooleanField(),
    )


def annotate_broadcast_shape(queryset: QuerySet) -> QuerySet:
    # Whether a workflow has the shape the broadcasts UI renders: a batch trigger and one email step,
    # evaluated in Postgres so a list can filter on the graph without loading every row's actions.
    # The trigger comes from the trigger action, where mask_trigger_config reads it: the `trigger`
    # column is a legacy copy and rows exist where the two disagree. jsonpath runs in lax mode, so a
    # row whose `actions` is not an array yields no matches rather than an error.
    other_step = " && ".join(f'@.type != "{action_type}"' for action_type in sorted(BROADCAST_ALLOWED_ACTION_TYPES))
    return queryset.annotate(
        _has_batch_trigger=_jsonb_path_exists(
            f'$[*] ? (@.type == "trigger" && @.config.type == "{BROADCAST_TRIGGER_TYPE}")'
        ),
        _email_step_count=models.Func(
            models.Func(
                models.F("actions"),
                _json_path('$[*] ? (@.type == "function_email")'),
                function="jsonb_path_query_array",
                output_field=models.JSONField(),
            ),
            function="jsonb_array_length",
            output_field=models.IntegerField(),
        ),
        _has_other_step=_jsonb_path_exists(f"$[*] ? ({other_step})"),
    )


BROADCAST_STATUSES = ("draft", "scheduled", "sending", "sent", "failed", "archived")


class _WorkflowFilterSet(FilterSet):
    # A producer's work list, so an agent need not read every workflow to find the few it may look at.
    optimization_enabled = BooleanFilter(
        method="filter_optimization_enabled",
        label="Only workflows someone turned suggestions on for.",
    )

    class Meta:
        model = HogFlow
        # `created_by` is filtered by uuid in _list_queryset (the list UI's member picker keys on
        # uuid, not pk), so it's deliberately not an exact-match field here.
        fields = ["id", "created_at", "updated_at", "status", "origin_product"]

    def filter_optimization_enabled(self, queryset, name: str, value: bool):
        # Off keeps its row, so "on" is a row still enabled. Archived workflows drop out: nothing runs there.
        if not value:
            return queryset.exclude(optimization__enabled=True)
        return queryset.filter(optimization__enabled=True, status=HogFlow.State.ACTIVE)


# The email body as a person reads it: the editor's plain-text export when it exists, otherwise the HTML
# with style and script blocks and tags removed, so CSS, script and markup never match a search term.
# The block patterns start with a non-greedy quantifier because Postgres gives a whole regex the
# greediness of its first quantifier. The tag pattern skips over quoted attribute values, so a '>' inside
# one (a liquid comparison, say) does not end the tag early and leak the rest of the attribute into the
# searchable text. Mirrored by emailBodyText in the frontend's workflowSearchMatches.ts.
_EMAIL_BODY_TEXT_SQL = (
    "COALESCE(NULLIF(action #>> '{config,inputs,email,value,text}', ''), "
    "regexp_replace(regexp_replace(regexp_replace(action #>> '{config,inputs,email,value,html}', "
    "'<style[^>]*?>.*?</style>', ' ', 'gi'), '<script[^>]*?>.*?</script>', ' ', 'gi'), "
    "'<[^>\"'']*((\"[^\"]*\"|''[^'']*'')[^>\"'']*)*>', ' ', 'g'))"
)

# What a person remembers about a message they received or authored.
_ACTION_SEARCH_TEXT_SQL = (
    "action ->> 'name'",
    "action #>> '{config,inputs,email,value,subject}'",
    "action #>> '{config,inputs,email,value,preheader}'",
    _EMAIL_BODY_TEXT_SQL,
)


def _action_content_matches(regex_pattern: str) -> RawSQL:
    """A predicate that is true when a step in the live actions or the pending draft matches the search."""
    table = HogFlow._meta.db_table
    step_matches = " OR ".join(f"{text} ~* %s" for text in _ACTION_SEARCH_TEXT_SQL)
    clauses = []
    for source in (f'"{table}"."actions"', f'"{table}"."draft" -> \'actions\''):
        # `actions` defaults to {} on a workflow that never got a graph, and jsonb_array_elements raises on
        # anything but an array, so guard the source rather than let one such row fail the whole list.
        clauses.append(
            "EXISTS (SELECT 1 FROM jsonb_array_elements("
            f"CASE WHEN jsonb_typeof({source}) = 'array' THEN {source} ELSE '[]'::jsonb END"
            f") AS action WHERE {step_matches})"
        )
    params = [regex_pattern] * (len(clauses) * len(_ACTION_SEARCH_TEXT_SQL))
    # nosemgrep: python.django.security.audit.raw-query.avoid-raw-sql (the search term is bound via params; only constant SQL and the table name from _meta are interpolated)
    return RawSQL(" OR ".join(clauses), params, output_field=models.BooleanField())
