from collections.abc import Sequence
from datetime import datetime

from django.db import transaction
from django.utils import timezone

from posthog.schema import AnyPropertyFilterDiscriminated

from posthog.hogql import ast
from posthog.hogql.parser import CacheOrigin, parse_expr

from posthog.api.capture import capture_internal
from posthog.models.team.team import Team
from posthog.models.user import User

from products.mcp_analytics.backend import custom_harnesses, logic
from products.mcp_analytics.backend.mcp_harness import HARNESS_TOKEN_SQL, custom_arms_sql, harness_label_sql
from products.mcp_analytics.backend.models import MCPAnalyticsSubmission

from . import contracts
from .constants import MCP_MISSING_CAPABILITY_EVENT
from .enums import SubmissionKind


def custom_harness_rules(team: Team) -> tuple[contracts.CustomHarnessRule, ...]:
    return custom_harnesses.custom_harness_rules(team)


def invalidate_custom_harness_rules(team: Team) -> None:
    custom_harnesses.invalidate_custom_harness_rules(team)


_VIRTUAL_FIELD_SQL = (
    f"if(startsWith(event, '$mcp_'), arrayMap(h -> {harness_label_sql('h')}, [{HARNESS_TOKEN_SQL}])[1], NULL)"
)


def mcp_harness_virtual_field_expr(custom_rules: Sequence[contracts.CustomHarnessRule] = ()) -> ast.Expr:
    # The fixed body is too long for the user parse cache, so only the short team rules parse as user input.
    expr = parse_expr(_VIRTUAL_FIELD_SQL, cache_origin=CacheOrigin.BUILTIN)
    if custom_rules:
        # nosemgrep: hogql-fstring-audit (the rule fields are escaped and character-restricted)
        rule_arms = parse_expr(f"multiIf({custom_arms_sql('h', custom_rules)}NULL)", cache_origin=CacheOrigin.USER)
        assert isinstance(rule_arms, ast.Call)
        _harness_label_call(expr).args[:0] = rule_arms.args[:-1]
    return expr


def _harness_label_call(virtual_field: ast.Expr) -> ast.Call:
    assert isinstance(virtual_field, ast.Call)
    label_access = virtual_field.args[1]
    assert isinstance(label_access, ast.ArrayAccess) and isinstance(label_access.array, ast.Call)
    label_lambda = label_access.array.args[0]
    assert isinstance(label_lambda, ast.Lambda) and isinstance(label_lambda.expr, ast.Call)
    return label_lambda.expr


def _to_submission(instance: MCPAnalyticsSubmission) -> contracts.Submission:
    return contracts.Submission(
        id=instance.id,
        kind=SubmissionKind(instance.kind),
        goal=instance.goal,
        summary=instance.summary,
        category=instance.category,
        blocked=instance.blocked,
        attempted_tool=instance.attempted_tool,
        mcp_client_name=instance.mcp_client_name,
        mcp_client_version=instance.mcp_client_version,
        mcp_protocol_version=instance.mcp_protocol_version,
        mcp_transport=instance.mcp_transport,
        mcp_session_id=instance.mcp_session_id,
        mcp_trace_id=instance.mcp_trace_id,
        created_at=instance.created_at,
        updated_at=instance.updated_at,
    )


def list_feedback_submissions(team: Team) -> list[contracts.Submission]:
    return [_to_submission(instance) for instance in logic.list_submissions(team, SubmissionKind.FEEDBACK)]


def list_missing_capability_submissions(team: Team) -> list[contracts.Submission]:
    return [_to_submission(instance) for instance in logic.list_submissions(team, SubmissionKind.MISSING_CAPABILITY)]


def create_feedback_submission(
    team: Team, created_by: User | None, submission: contracts.CreateFeedbackSubmission
) -> contracts.Submission:
    return _to_submission(logic.create_feedback_submission(team, created_by, submission))


def create_missing_capability_submission(
    team: Team, created_by: User | None, submission: contracts.CreateMissingCapabilitySubmission
) -> contracts.Submission:
    return _to_submission(logic.create_missing_capability_submission(team, created_by, submission))


def capture_missing_capability_event(team: Team, distinct_id: str, submission: contracts.Submission) -> None:
    properties: dict[str, object] = {
        "submission_id": str(submission.id),
        "kind": submission.kind,
        "attempted_tool_present": bool(submission.attempted_tool),
        "mcp_client_name_present": bool(submission.mcp_client_name),
        "mcp_session_id_present": bool(submission.mcp_session_id),
        "mcp_trace_id_present": bool(submission.mcp_trace_id),
        "$mcp_source": "posthog_mcp_analytics",
        "$mcp_tool_name": "mcp-missing-capability-report",
        "missing_capability_blocked": submission.blocked,
    }
    if submission.mcp_session_id:
        properties["$mcp_session_id"] = submission.mcp_session_id
    if submission.mcp_trace_id:
        properties["$mcp_trace_id"] = submission.mcp_trace_id

    capture_internal(
        token=team.api_token,
        event_name=MCP_MISSING_CAPABILITY_EVENT,
        event_source="mcp_analytics_missing_capability",
        distinct_id=distinct_id,
        properties=properties,
        event_uuid=str(submission.id),
        process_person_profile=False,
    )


def list_mcp_sessions(
    team: Team,
    limit: int,
    offset: int,
    search: str = "",
    order_by: str = "",
    date_from: str | None = None,
    date_to: str | None = None,
    has_errors: bool | None = None,
    properties: list[AnyPropertyFilterDiscriminated] | None = None,
    filter_test_accounts: bool = False,
    user: User | None = None,
) -> contracts.MCPSessionsPage:
    return logic.list_mcp_sessions(
        team,
        limit=limit,
        offset=offset,
        search=search,
        order_by=order_by,
        date_from=date_from,
        date_to=date_to,
        has_errors=has_errors,
        properties=properties,
        filter_test_accounts=filter_test_accounts,
        user=user,
    )


def list_mcp_tool_calls(
    team: Team,
    session_id: str,
    limit: int,
    offset: int,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    properties: list[AnyPropertyFilterDiscriminated] | None = None,
    filter_test_accounts: bool = False,
    user: User | None = None,
) -> contracts.MCPToolCallsPage:
    return logic.list_mcp_tool_calls(
        team,
        session_id=session_id,
        limit=limit,
        offset=offset,
        date_from=date_from,
        date_to=date_to,
        properties=properties,
        filter_test_accounts=filter_test_accounts,
        user=user,
    )


def generate_session_intent(team: Team, session_id: str, date_from: datetime | None = None) -> str:
    """Generate (or return the cached) intent summary for an MCP session.

    Shared entry point for the UI's on-demand button and any future caller
    (e.g. clustering). Persists the result to ``MCPSession.intent``. ``date_from``
    bounds the event scan to keep older sessions summarisable (same bound as
    ``list_mcp_tool_calls``).
    """
    return logic.generate_session_intent(team, session_id=session_id, date_from=date_from)


def generate_intent_digest(team: Team) -> contracts.IntentDigest:
    """Generate (or return the cached) project-level digest of what agents are trying to do.

    Powers the dashboard's activity tab: a one-sentence summary plus semantic themes. Cached
    both by intent corpus and by recency, so a quiet project regenerates only when its intents
    change and a busy one regenerates at a bounded rate.
    """
    return logic.generate_intent_digest(team)


def get_activity_overview(
    team: Team,
    properties: list[AnyPropertyFilterDiscriminated] | None = None,
    filter_test_accounts: bool = False,
    user: User | None = None,
    refresh: bool = False,
) -> contracts.ActivityOverview:
    """Compute the activity view's aggregates and recent-call feed in one pass.

    Bounded to the last 30 days. Cached by the filters and the caller's property restrictions:
    for 5 minutes without restrictions, for less than one poll interval with them.
    ``refresh`` skips a cached entry older than a few seconds and stores the fresh result in its place.

    ``properties`` and ``filter_test_accounts`` are the tabs' shared filters.
    """
    return logic.get_activity_overview(
        team, properties=properties, filter_test_accounts=filter_test_accounts, user=user, refresh=refresh
    )


def get_intent_cluster_snapshot(team: Team, tool: str | None = None) -> contracts.IntentClusterSnapshot:
    """The latest snapshot, optionally narrowed to one tool's slice of it."""
    return logic.get_intent_cluster_snapshot(team, tool=tool)


def trigger_intent_cluster_recompute(team: Team, user: User | None) -> None:
    """Kick off the intent cluster recompute Temporal workflow.

    Returns immediately. Use ``get_intent_cluster_snapshot`` to poll status —
    the workflow's compute activity writes the snapshot status (COMPUTING →
    IDLE/ERROR) as it runs.
    """
    import asyncio

    from django.conf import settings

    from temporalio.exceptions import WorkflowAlreadyStartedError

    from posthog.temporal.common.client import async_connect
    from posthog.temporal.mcp_analytics.intent_clustering.constants import (
        CHILD_WORKFLOW_ID_PREFIX,
        WORKFLOW_EXECUTION_TIMEOUT,
        WORKFLOW_NAME,
    )
    from posthog.temporal.mcp_analytics.intent_clustering.models import IntentClusteringWorkflowInputs

    from products.mcp_analytics.backend.models import MCPIntentClusterSnapshot

    # One run at a time per team: while a fresh run holds the snapshot in
    # COMPUTING, another dispatch would only stack a duplicate workflow on the
    # queue behind it. A run stuck past STALE_COMPUTING_THRESHOLD is presumed
    # dead (same rule as the sweep in get_intent_cluster_snapshot), so a
    # retry is allowed through. The row lock serialises concurrent triggers so
    # they can't all pass the freshness check before any of them claims the
    # snapshot; the Temporal dispatch stays outside the transaction.
    # Claiming COMPUTING before dispatching also means the 202 response and
    # any immediate poll see consistent state — the workflow's activity
    # re-asserts COMPUTING on pickup, and both writes are idempotent.
    with transaction.atomic():
        snapshot, created = MCPIntentClusterSnapshot.objects.select_for_update().get_or_create(
            team=team,
            defaults={
                "status": MCPIntentClusterSnapshot.Status.COMPUTING,
                "error_message": "",
                "last_computed_by": user,
            },
        )
        if not created:
            if (
                snapshot.status == MCPIntentClusterSnapshot.Status.COMPUTING
                and snapshot.updated_at >= timezone.now() - logic.STALE_COMPUTING_THRESHOLD
            ):
                return
            snapshot.status = MCPIntentClusterSnapshot.Status.COMPUTING
            snapshot.error_message = ""
            snapshot.last_computed_by = user
            snapshot.save(update_fields=["status", "error_message", "last_computed_by", "updated_at"])

    # Deterministic per team: Temporal refuses a second start while a run with
    # this id is live, so even a run that outlives STALE_COMPUTING_THRESHOLD
    # (which is shorter than the 20-minute execution timeout) can't be
    # overlapped by a retry — the id frees up once the previous run closes.
    workflow_id = f"{CHILD_WORKFLOW_ID_PREFIX}-{team.id}-adhoc"

    # Create + use the Temporal client inside one event loop. sync_connect()
    # would build the client in asgiref's managed loop and then asyncio.run()
    # would call start_workflow in a different loop; the temporalio Rust
    # bridge is currently loop-agnostic but the inconsistency is fragile.
    # Matches the cluster_mcp_intents management command pattern.
    async def _start() -> None:
        client = await async_connect()
        # execution_timeout bounds the whole run *including* queue wait: with
        # no worker polling the task queue, an unbounded workflow sits pending
        # forever and every recompute click stacks another one behind it.
        await client.start_workflow(
            WORKFLOW_NAME,
            IntentClusteringWorkflowInputs(team_id=team.id, user_id=user.id if user else None),
            id=workflow_id,
            task_queue=settings.MCPA_TASK_QUEUE,
            execution_timeout=WORKFLOW_EXECUTION_TIMEOUT,
        )

    try:
        asyncio.run(_start())
    except WorkflowAlreadyStartedError:
        # The previous run outlived the stale threshold but is genuinely still
        # running — leave the snapshot in COMPUTING; the live run flips the
        # status when it finishes.
        return
    except Exception:
        # Dispatch failed, so no activity will ever flip the status — revert
        # the optimistic COMPUTING write instead of leaving the snapshot stuck
        # until the stale-COMPUTING sweep in get_intent_cluster_snapshot.
        MCPIntentClusterSnapshot.objects.filter(team=team).update(
            status=MCPIntentClusterSnapshot.Status.ERROR,
            error_message="Failed to start the intent clustering workflow",
            updated_at=timezone.now(),
        )
        raise
