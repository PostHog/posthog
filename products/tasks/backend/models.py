import os
import re
import json
import uuid
import string
import secrets
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional

from django.db.models.signals import post_delete, post_save, pre_delete
from django.dispatch import receiver
from django.utils.functional import Promise

from pydantic import BaseModel

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext
    from products.tasks.backend.logic.services.sandbox import SandboxResources

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.contrib.postgres.indexes import GinIndex, OpClass
from django.core.exceptions import ValidationError
from django.db import IntegrityError, connection, models, transaction
from django.db.models.fields.json import KeyTransform
from django.utils import timezone as django_timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.activity_logging.model_activity import ModelActivityMixin
from posthog.models.github_integration_base import INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY
from posthog.models.integration import ERROR_TOKEN_REFRESH_FAILED, Integration
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import DeletedMetaFields, UUIDModel
from posthog.storage import object_storage
from posthog.temporal.oauth import PosthogMcpScopes
from posthog.uuidt import uuid7

from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS
from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.logic.stream.redis_stream import publish_task_run_stream_event
from products.tasks.backend.metrics import observe_task_run_created, observe_task_run_dispatch_callback
from products.tasks.backend.redis import evaluate_dedicated_stream_flag, run_uses_dedicated_stream
from products.tasks.backend.storage import append_jsonl_object

logger = structlog.get_logger(__name__)


def execute_after_commit(callback: Callable[[], object]) -> None:
    """Run commit side effects immediately in tests, where TestCase never commits its wrapper transaction."""
    if settings.TEST:
        callback()
    else:
        transaction.on_commit(callback)


LogLevel = Literal["debug", "info", "warn", "error"]
MCPBuiltInAgentKey = Literal["support", "scout"]
MCP_BUILT_IN_AGENT_STATE_KEY = "mcp_builtin_agent_key"
MCP_CREDENTIAL_OWNER_STATE_KEY = "mcp_credential_owner_id"
MCP_GATEWAY_SERVER_ALLOWLIST_STATE_KEY = "mcp_gateway_server_ids"
TASK_OWNERSHIP_VERSION_STATE_KEY = "task_ownership_version"
MCP_BUILT_IN_AGENT_KEY_BY_ORIGIN: dict[str, MCPBuiltInAgentKey] = {
    "support_reply": "support",
    "signals_scout": "scout",
}


def resolve_schema(schema: type[BaseModel] | dict) -> dict:
    if isinstance(schema, dict):
        return schema
    return schema.model_json_schema()


def _task_ownership_version(state: dict | None) -> str | None:
    value = (state or {}).get(TASK_OWNERSHIP_VERSION_STATE_KEY)
    return value if isinstance(value, str) else None


def _has_pending_user_input(state: dict[str, Any]) -> bool:
    return bool(state.get("pending_user_message") or state.get("pending_user_artifact_ids"))


def stamp_pending_user_message_id(state: dict[str, Any], *, refresh: bool = False) -> None:
    if not _has_pending_user_input(state):
        return
    existing = state.get("pending_user_message_id")
    if not refresh and isinstance(existing, str) and existing:
        return
    state["pending_user_message_id"] = str(uuid.uuid4())


class TaskOwnershipChangedError(RuntimeError):
    pass


class Channel(TeamScopedRootMixin):
    """A shared feed of tasks (rendered as "#<name>" in PostHog Desktop). Every task is
    owned by the channel it was kicked off in. Each user gets one private "personal"
    channel ("#me") per team, and each team gets a public "general" channel, Slack-style.
    Listing creates neither; provisioning does. The general channel can't be renamed or
    deleted."""

    class ChannelType(models.TextChoices):
        PUBLIC = "public", "Public"
        PERSONAL = "personal", "Personal"

    class SystemRole(models.TextChoices):
        """Identifies a channel as one of the two system-provisioned spaces, independent
        of its (renameable) name and its (visibility-only) channel_type."""

        PERSONAL = "personal", "Personal"
        GENERAL = "general", "General"

    PERSONAL_CHANNEL_NAME = "me"
    # The label the personal channel is shown under, reserved so no other space can wear it.
    PERSONAL_CHANNEL_LABEL = "personal"
    GENERAL_CHANNEL_NAME = "general"

    @classmethod
    def visible_to_q(cls, user_id: int | None, *, relation: Literal["", "channel", "task__channel"] = "") -> models.Q:
        """The channel-visibility rule as a queryset filter: a personal channel is
        visible only to its creator. ``relation`` names the join to ``Channel`` when
        filtering another model's queryset (e.g. ``"channel"``); empty filters
        ``Channel`` rows directly."""
        prefix = {"": "", "channel": "channel__", "task__channel": "task__channel__"}[relation]
        visible_q = models.Q(**{f"{prefix}channel_type": cls.ChannelType.PUBLIC})
        if user_id is not None:
            visible_q |= models.Q(
                **{
                    f"{prefix}channel_type": cls.ChannelType.PERSONAL,
                    f"{prefix}created_by_id": user_id,
                }
            )
        return models.Q(**{f"{prefix}deleted": False}) & visible_q

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: posthog_team and posthog_user are written on
    # virtually every request, and adding an FK constraint takes a SHARE ROW EXCLUSIVE lock on
    # them that stalls deploys. Django still enforces the relation and on_delete at the app
    # level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    name = models.CharField(max_length=128)
    channel_type = models.CharField(max_length=16, choices=ChannelType, default=ChannelType.PUBLIC)
    # Null for ordinary channels. No dedicated unique constraint: provisioning still creates/adopts
    # the general channel by its fixed name, so task_channel_team_name_public_unique (team, name)
    # remains the race guard; task_channel_team_user_personal_unique guards the personal role likewise.
    system_role = models.CharField(max_length=16, null=True, blank=True, choices=SystemRole.choices)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    github_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        limit_choices_to={"kind": "github"},
    )
    repositories = ArrayField(
        models.CharField(max_length=255),
        default=list,
        db_default=[],
        blank=True,
        help_text="GitHub repositories inherited by new tasks in this channel",
    )
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_channel"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "name"],
                condition=models.Q(channel_type="public", deleted=False),
                name="task_channel_team_name_public_unique",
            ),
            models.UniqueConstraint(
                fields=["team", "created_by"],
                condition=models.Q(channel_type="personal", deleted=False),
                name="task_channel_team_user_personal_unique",
            ),
        ]

    def __str__(self):
        return f"#{self.name}"


@receiver(pre_delete, sender=Integration)
def clear_channel_repositories_on_github_integration_delete(
    sender: type[Integration], instance: Integration, **kwargs: Any
) -> None:
    if instance.kind != Integration.IntegrationKind.GITHUB:
        return

    Channel.objects.for_team(instance.team_id).filter(github_integration_id=instance.id).update(
        github_integration=None,
        repositories=[],
    )


SLACK_NOTIFIED_PR_URL_STATE_KEY = "slack_notified_pr_url"
PR_READY_EMAIL_QUEUED_AT_STATE_KEY = "pr_ready_email_queued_at"
PR_READY_EMAIL_SENT_AT_STATE_KEY = "pr_ready_email_sent_at"
PR_READY_EMAIL_PR_URL_STATE_KEY = "pr_ready_email_pr_url"


class TaskClientProvenance(models.TextChoices):
    POSTHOG_DESKTOP = "posthog_desktop", "PostHog Desktop"


def task_origin_product_choices() -> list[tuple[str, str | Promise]]:
    # Callable so growing the enum doesn't generate a no-op migration.
    return list(Task.OriginProduct.choices)


class Task(DeletedMetaFields, models.Model):
    class Runtime(models.TextChoices):
        ACP = "acp", "ACP"
        PI = "pi", "Pi"

    class OriginProduct(models.TextChoices):
        ONBOARDING = "onboarding", "Onboarding"
        ERROR_TRACKING = "error_tracking", "Error Tracking"
        EVAL_CLUSTERS = "eval_clusters", "Eval Clusters"
        USER_CREATED = "user_created", "User Created"
        SLACK = "slack", "Slack"
        SUPPORT_QUEUE = "support_queue", "Support Queue"
        SESSION_SUMMARIES = "session_summaries", "Session Summaries"
        POSTHOG_AI = "posthog_ai", "PostHog AI"
        EXPERIMENTS = "experiments", "Experiments"
        # Unlike the others (which indicate direct creation from that product, e.g. a "fix this error" button),
        # signal report tasks originate indirectly via signals from other products.
        SIGNAL_REPORT = "signal_report", "Signal Report"
        # Headless Signals scout — proactively explores a project and emits signals.
        SIGNALS_SCOUT = "signals_scout", "Signals Scout"
        # Conversations support reply pipeline — autonomous grounded draft replies.
        SUPPORT_REPLY = "support_reply", "Support Reply"
        # HogDesk — the internal support desk client. Tasks it creates from a
        # ticket's Code chat carry this origin (previously "support_queue", which
        # collided with the conversations support pipeline).
        HOGDESK = "hogdesk", "HogDesk"
        # ReviewHog PR reviewer — its sandbox steps (chunking/review/validation/dedup) spawn one task each.
        REVIEW_HOG = "review_hog", "ReviewHog"
        IMAGE_BUILDER = "image_builder", "Image Builder"
        # Loop firings: named, cloud-executed agent automations triggered by schedule,
        # GitHub event or API. See products/tasks/docs/LOOPS.md.
        LOOP = "loop", "Loop"
        # "Create fix task" on the MCP analytics tool-quality failure drill-down.
        MCP_ANALYTICS = "mcp_analytics", "MCP Analytics"
        # Inbox scout-chat kickoffs ("Suggest a scout", fleet overview, recent signals),
        # minted server-side by products/signals so the origin proves the run is entitled
        # through the generally-available Inbox rather than PostHog Desktop.
        SIGNALS_CHAT = "signals_chat", "Signals Chat"
        TASK_ANALYSIS = "task_analysis", "Task Analysis"
        # A workflow's "Create AI task" action. Unattended like LOOP; the run executes as
        # the workflow's creator.
        WORKFLOW = "workflow", "Workflow"

    # nosemgrep: prefer-uuid7-django-pk -- TODO: migrate to uuid7 or clarify intent
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False)
    task_number = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=255)
    title_manually_set = models.BooleanField(default=False)
    description = models.TextField()
    origin_product = models.CharField(max_length=20, choices=task_origin_product_choices)
    client_provenance = models.CharField(
        max_length=32,
        choices=TaskClientProvenance,
        null=True,
        blank=True,
        editable=False,
    )

    # Repository configuration
    github_integration = models.ForeignKey(
        "posthog.Integration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        limit_choices_to={"kind": "github"},
        help_text="GitHub integration for this task",
    )
    # Keep the selected personal installation as a preference for deterministic
    # authorship when a user has multiple GitHub installations. SET_NULL on
    # disconnect lets future runs fall back to resolving the user's current link.
    github_user_integration = models.ForeignKey(
        "posthog.UserIntegration",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        db_index=False,
        limit_choices_to={"kind": "github"},
        help_text="User-scoped GitHub integration used for user-authored task runs",
    )

    repository = models.CharField(
        max_length=255, null=True, blank=True
    )  # Format is organization/repo, for example posthog/posthog-js
    repositories = ArrayField(
        models.CharField(max_length=255),
        default=list,
        db_default=[],
        blank=True,
        help_text="GitHub repositories available to this task",
    )

    # Channel this task was kicked off in. Legacy tasks (and tasks from non-channel
    # surfaces) stay NULL. SET_NULL so deleting a channel never deletes its tasks.
    channel = models.ForeignKey(
        "tasks.Channel",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        db_index=False,
    )

    # Loop firing that spawned this task, if any. NULL for every non-loop task. SET_NULL
    # so deleting a loop never deletes its historical runs. db_index=False here: the index
    # is added CONCURRENTLY in a follow-up migration (see 0062), which is a separate DDL
    # statement Django can't emit as part of a plain AddField.
    loop = models.ForeignKey(
        "tasks.Loop",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tasks",
        db_index=False,
        db_constraint=True,
    )

    # Workflow (hog flow) whose action created this task, if any. Follows `loop` above; that
    # per-origin-column pattern is worth replacing with a generic (origin_product, origin_id)
    # pair before a fourth origin needs one. Plain UUID rather than an FK because hog flows
    # live in products.workflows, which tasks must not depend on.
    hog_flow_id = models.UUIDField(null=True, blank=True, db_index=False)

    # Caller-supplied idempotency key, unique per team when set, so a retried create (e.g. a
    # workflow engine redelivery) returns the existing task instead of making a second one.
    origin_key = models.CharField(max_length=128, null=True, blank=True)

    # DEPRECATED - do not use
    signal_report = models.ForeignKey(
        "signals.SignalReport",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="task",
        db_index=False,
    )

    json_schema = models.JSONField(
        default=None,
        null=True,
        blank=True,
        help_text="JSON schema for the task. This is used to validate the output of the task.",
    )

    internal = models.BooleanField(
        default=False,
        help_text="If true, this task is for internal use and should not be exposed to end users.",
    )

    archived = models.BooleanField(
        default=False,
        help_text=(
            "If true, the task is hidden from default list responses. Used by PostHog Desktop clients "
            "to share archive state across desktop and mobile."
        ),
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    # Distinct from `updated_at` (the row's last write): this moves when something happens
    # in the task, so a run can stream for hours without touching `updated_at` yet still sort
    # to the top. Nullable only for rows written outside the ORM; the Django default stamps
    # every other path.
    last_activity_at = models.DateTimeField(default=django_timezone.now, null=True, blank=True)
    ci_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="Custom prompt for CI fixes. If blank, a default prompt will be used.",
    )

    # Conversation-level state shared across the task's runs (each resume/follow-up
    # is a fresh TaskRun), e.g. which PRs have been announced to the Slack thread.
    state = models.JSONField(default=dict, null=True, blank=True)

    runtime = models.CharField(
        max_length=10,
        choices=Runtime,
        default=Runtime.ACP,
        db_default=Runtime.ACP,
        help_text="Agent protocol/harness driving this task's runs.",
    )

    class Meta:
        db_table = "posthog_task"
        managed = True
        indexes = [
            models.Index(fields=["signal_report"], name="posthog_task_signal_report_idx"),
            models.Index(fields=["archived"], name="posthog_task_archived_idx"),
            models.Index(fields=["team", "-created_at", "-id"], name="posthog_task_team_created_idx"),
            models.Index(fields=["team", "created_by", "-created_at", "-id"], name="posthog_task_team_creator_idx"),
            models.Index(fields=["channel", "-created_at"], name="posthog_task_channel_feed_idx"),
            models.Index(fields=["team", "-last_activity_at", "-id"], name="posthog_task_team_activity_idx"),
            models.Index(fields=["channel", "-last_activity_at"], name="posthog_task_chan_activity_idx"),
            models.Index(fields=["loop"], name="posthog_task_loop_idx"),
            models.Index(fields=["hog_flow_id", "-created_at"], name="posthog_task_hog_flow_idx"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["team", "origin_key"],
                condition=models.Q(origin_key__isnull=False),
                name="posthog_task_origin_key_uniq",
            ),
        ]

    def __str__(self):
        return self.title

    def save(self, *args, **kwargs):
        is_new = self._state.adding

        if self.repository:
            parts = self.repository.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValidationError({"repository": "Format for repository is organization/repo"})

            self.repository = self.repository.lower()

        if self.task_number is None:
            self._assign_task_number()

        super().save(*args, **kwargs)

        if is_new:
            self._track_task_created()

    @property
    def mcp_builtin_agent_key(self) -> MCPBuiltInAgentKey | None:
        expected_key = MCP_BUILT_IN_AGENT_KEY_BY_ORIGIN.get(self.origin_product)
        marker = (self.state or {}).get(MCP_BUILT_IN_AGENT_STATE_KEY)
        return expected_key if marker == expected_key else None

    @property
    def mcp_credential_owner_id(self) -> int | None:
        """The person whose MCP Store grants this run may mount.

        Only meaningful on a stamped built-in agent task, so it reads through
        `mcp_builtin_agent_key` — an unstamped or untrusted origin can never
        borrow someone's grants. None means the run belongs to nobody, which
        limits it to the team-scoped grants members have lent to agents.
        """
        if self.mcp_builtin_agent_key is None:
            return None
        owner_id = (self.state or {}).get(MCP_CREDENTIAL_OWNER_STATE_KEY)
        return owner_id if isinstance(owner_id, int) else None

    @property
    def mcp_gateway_server_allowlist(self) -> list[str] | None:
        """Gateway server ids the run may mount, gating every grant regardless of scope.

        None (no snapshot) leaves mount resolution unfiltered — every non-scout task, and
        pre-snapshot rows. Once a snapshot exists, a malformed value fails closed to an empty
        allowlist: a scout whose selection is unreadable must not fall back to mounting every
        reachable grant. Reads through `mcp_builtin_agent_key` like the owner id: only a
        stamped agent task carries one.
        """
        if self.mcp_builtin_agent_key is None:
            return None
        ids = (self.state or {}).get(MCP_GATEWAY_SERVER_ALLOWLIST_STATE_KEY)
        if ids is None:
            return None
        return [str(i) for i in ids] if isinstance(ids, list) else []

    def capture_event(
        self, event: str, properties: dict | None = None, capture_fn: Callable[..., None] | None = None
    ) -> None:
        # capture_fn lets Celery callers pass a ph_scoped_capture client — the module-level
        # posthoganalytics.capture silently drops events in workers (see posthog.ph_client).
        try:
            distinct_id = (
                str(self.created_by.distinct_id) if self.created_by_id and self.created_by else str(self.team.uuid)
            )
            all_properties = {
                "task_id": str(self.id),
                "team_id": self.team_id,
                "title": self.title,
                "description": self.description[:500] if self.description else "",
                "origin_product": self.origin_product,
                "repository": self.repository,
                "repositories": self.repositories or ([self.repository] if self.repository else []),
            }
            if properties:
                all_properties.update(properties)
            (capture_fn or posthoganalytics.capture)(
                distinct_id=distinct_id,
                event=event,
                properties=all_properties,
                groups=groups(team=self.team),
                send_feature_flags=True,
            )
        except Exception as e:
            logger.warning("task.capture_event_failed", analytics_event=event, error=str(e))

    def _track_task_created(self) -> None:
        self.capture_event(
            "task_created",
            {"has_json_schema": self.json_schema is not None},
        )

    @staticmethod
    def generate_team_prefix(team_name: str) -> str:
        clean_name = "".join(c for c in team_name if c.isalnum())
        uppercase_letters = [c for c in clean_name if c.isupper()]
        if len(uppercase_letters) >= 3:
            return "".join(uppercase_letters[:3])
        return clean_name[:3].upper() if clean_name else "TSK"

    @property
    def slug(self) -> str:
        if self.task_number is None:
            return ""
        prefix = self.generate_team_prefix(self.team.name)
        return f"{prefix}-{self.task_number}"

    @property
    def latest_run(self) -> Optional["TaskRun"]:
        runs = [run for run in self.runs.all() if run.team_id == self.team_id]
        if runs:
            return max(runs, key=lambda r: (r.created_at, r.id))
        return None

    def _assign_task_number(self) -> None:
        max_task_number = Task.objects.filter(team=self.team).aggregate(models.Max("task_number"))["task_number__max"]
        self.task_number = (max_task_number if max_task_number is not None else -1) + 1

    @property
    def ownership_version(self) -> str | None:
        return _task_ownership_version(self.state)

    def create_run(
        self,
        environment: Optional["TaskRun.Environment"] = None,
        mode: str = "background",
        extra_state: dict | None = None,
        branch: str | None = None,
    ) -> "TaskRun":
        expected_created_by_id = self.created_by_id
        expected_ownership_version = self.ownership_version
        dedicated_stream = (extra_state or {}).get("use_dedicated_stream")
        if dedicated_stream is None:
            distinct_id = (self.created_by.distinct_id if self.created_by else None) or f"team_{self.team_id}"
            dedicated_stream = evaluate_dedicated_stream_flag(
                organization_id=str(self.team.organization_id),
                distinct_id=distinct_id,
            )

        with transaction.atomic():
            task = (
                Task.objects.select_for_update(of=("self",))
                .select_related("created_by", "team")
                .get(id=self.id, team_id=self.team_id)
            )
            if task.created_by_id != expected_created_by_id or task.ownership_version != expected_ownership_version:
                raise TaskOwnershipChangedError("Task ownership changed before the run was created")

            state: dict = {} if task.runtime == Task.Runtime.PI else {"mode": mode}
            if extra_state:
                state.update({k: v for k, v in extra_state.items() if k != "mode"})
            state.setdefault("repositories", task.repositories or ([task.repository] if task.repository else []))
            # A workflow task's later runs must keep the connector allowlist selected by the workflow.
            if task.origin_product == Task.OriginProduct.WORKFLOW and "config_snapshot" not in state:
                previous = task.latest_run
                previous_snapshot = previous.state.get("config_snapshot") if previous else None
                if previous_snapshot:
                    state["config_snapshot"] = previous_snapshot
            if task.ownership_version is not None:
                state[TASK_OWNERSHIP_VERSION_STATE_KEY] = task.ownership_version

            resume_from_run_id = (extra_state or {}).get("resume_from_run_id")
            if resume_from_run_id is not None:
                resume_source = TaskRun.objects.filter(id=resume_from_run_id, task_id=task.id).only("state").first()
                if resume_source is None or not resume_source.matches_task_ownership(task):
                    raise TaskOwnershipChangedError("The resume source belongs to a previous task owner")

            # Pin the stream-routing decision once so every reader/writer agrees for this run's life.
            state.setdefault("use_dedicated_stream", dedicated_stream)
            is_resume = bool(resume_from_run_id)
            has_pending = _has_pending_user_input(extra_state or {})
            stamp_pending_user_message_id(state)
            task_run = TaskRun.objects.create(
                task=task,
                team=task.team,
                status=TaskRun.Status.QUEUED,
                queued_at=django_timezone.now(),
                **({"environment": environment} if environment else {}),
                state=state,
                branch=branch,
            )

            def emit_created_events() -> None:
                task_run.publish_stream_state_event()
                observe_task_run_created(task_run)
                task.capture_event(
                    "task_run_created",
                    {
                        "run_id": str(task_run.id),
                        "mode": mode,
                        "environment": task_run.environment,
                        # The bare `environment` property gets clobbered by the analytics client's
                        # deployment-environment super-property, so ship the run's local/cloud value
                        # under an unclobbered name too — as TaskRun.capture_event already does.
                        "run_environment": task_run.environment,
                        "is_resume": is_resume,
                        "has_pending_message": has_pending,
                        # Loop attribution: this event uses Task.capture_event (not TaskRun's),
                        # so carry it from the run state the same way TaskRun.capture_event does.
                        "loop_id": state.get("loop_id"),
                        "loop_trigger_id": state.get("loop_trigger_id"),
                    },
                )

            execute_after_commit(emit_created_events)
            return task_run

    @property
    def slack_notified_pr_url(self) -> str | None:
        """PR URL last announced to this task's Slack thread, if any."""
        return (self.state or {}).get(SLACK_NOTIFIED_PR_URL_STATE_KEY)

    def mark_slack_pr_notified(self, pr_url: str) -> None:
        """Record ``pr_url`` as the PR announced to the task's Slack thread. Row-locked
        merge so it doesn't clobber other keys in the shared state bag."""
        with transaction.atomic():
            task = Task.objects.select_for_update().only("id", "state").get(id=self.id)
            state = dict(task.state or {})
            state[SLACK_NOTIFIED_PR_URL_STATE_KEY] = pr_url
            task.state = state
            task.save(update_fields=["state", "updated_at"])
        self.state = state

    @property
    def pr_ready_email_sent_at(self) -> str | None:
        return (self.state or {}).get(PR_READY_EMAIL_SENT_AT_STATE_KEY)

    def mark_pr_ready_email_queued(self, pr_url: str, *, queued_at: datetime | None = None) -> bool:
        """Record that this task's PR-ready email task was queued, preserving other state keys."""
        with transaction.atomic():
            task = Task.objects.select_for_update().only("id", "state").get(id=self.id)
            state = dict(task.state or {})
            if state.get(PR_READY_EMAIL_QUEUED_AT_STATE_KEY) or state.get(PR_READY_EMAIL_SENT_AT_STATE_KEY):
                self.state = state
                return False
            state[PR_READY_EMAIL_QUEUED_AT_STATE_KEY] = (queued_at or django_timezone.now()).isoformat()
            state[PR_READY_EMAIL_PR_URL_STATE_KEY] = pr_url
            task.state = state
            task.save(update_fields=["state", "updated_at"])
        self.state = state
        return True

    def mark_pr_ready_email_sent(self, pr_url: str, *, sent_at: datetime | None = None) -> None:
        """Record confirmed PR-ready email delivery, preserving other state keys."""
        with transaction.atomic():
            task = Task.objects.select_for_update().only("id", "state").get(id=self.id)
            state = dict(task.state or {})
            state[PR_READY_EMAIL_SENT_AT_STATE_KEY] = (sent_at or django_timezone.now()).isoformat()
            state[PR_READY_EMAIL_PR_URL_STATE_KEY] = pr_url
            task.state = state
            task.save(update_fields=["state", "updated_at"])
        self.state = state

    def soft_delete(self, capture_fn: Callable[..., None] | None = None):
        self.deleted = True
        self.deleted_at = django_timezone.now()
        self.save()
        self.capture_event(
            "task_deleted",
            {"duration_seconds": round((django_timezone.now() - self.created_at).total_seconds(), 1)},
            capture_fn=capture_fn,
        )

    def soft_delete_if_unclaimed_prewarm(self, task_run: "TaskRun") -> bool:
        deleted_at = django_timezone.now()
        updated = Task.objects.filter(
            pk=self.pk,
            deleted=False,
            title="",
            description="",
            runs__id=task_run.id,
            runs__state__prewarmed=True,
            runs__state__await_user_message=True,
        ).update(deleted=True, deleted_at=deleted_at, updated_at=deleted_at)
        if not updated:
            return False
        self.deleted = True
        self.deleted_at = deleted_at
        self.updated_at = deleted_at
        self.capture_event(
            "task_deleted", {"duration_seconds": round((deleted_at - self.created_at).total_seconds(), 1)}
        )
        return True

    def delete(self, *args, **kwargs):
        raise Exception("Cannot hard delete Task. Use soft_delete() instead.")

    @staticmethod
    def _build_task(
        *,
        team: Team,
        title: str,
        description: str,
        origin_product: "Task.OriginProduct",
        user_id: int,
        title_manually_set: bool = False,
        repository: str | None = None,
        channel: Channel | None = None,
        slack_thread_context: Optional["SlackThreadContext"] = None,
        slack_thread_url: str | None = None,
        branch: str | None = None,
        signal_report_id: str | None = None,
        hog_flow_id: uuid.UUID | None = None,
        origin_key: str | None = None,
        ai_stage: str | None = None,
        sandbox_environment_id: str | None = None,
        internal: bool = False,
        output_schema: type[BaseModel] | dict | None = None,
        interaction_origin: str | None = None,
        runtime: str = "acp",
        runtime_adapter: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        initial_permission_mode: str | None = None,
        sandbox_resources: "SandboxResources | None" = None,
        sandbox_timeout_seconds: int | None = None,
        inactivity_timeout_seconds: int | None = None,
        wizard_config: dict | None = None,
        wizard_head_branch: str | None = None,
        self_driving_head_branch: str | None = None,
        pending_user_message: str | None = None,
        custom_image_builder_id: str | None = None,
        custom_image_id: str | None = None,
        mcp_builtin_agent_key: MCPBuiltInAgentKey | None = None,
        client_provenance: TaskClientProvenance | None = None,
        mcp_credential_owner_id: int | None = None,
        mcp_gateway_server_ids: list[str] | None = None,
    ) -> tuple["Task", dict[str, Any]]:
        """Create the Task row and assemble the initial run's `extra_state`.

        Shared by `create_and_run` (which then creates and dispatches the run) and
        `create_without_run` (which discards the run state). One path keeps the
        GitHub-integration resolution and authorship logic from drifting between them.
        """
        created_by = User.objects.get(id=user_id)

        from products.tasks.backend.logic.services.sandbox import is_public_sandbox_repo
        from products.tasks.backend.temporal.process_task.utils import (
            PrAuthorshipMode,
            RunSource,
            RuntimeAdapter,
            get_pr_authorship_mode,
            get_provider_for_runtime_adapter,
            resolve_user_github_integration_for_task,
            user_github_integration_is_usable,
        )

        github_integration = None
        if repository or origin_product not in (Task.OriginProduct.SIGNALS_CHAT, Task.OriginProduct.SIGNAL_REPORT):
            github_integration = (
                Integration.objects.filter(team=team, kind="github")
                .exclude(errors=ERROR_TOKEN_REFRESH_FAILED)
                .exclude(config__has_key=INSTALLATION_UNAVAILABLE_SINCE_CONFIG_KEY)
                .first()
            )
        github_user_integration = None
        task_stub = Task(
            team=team,
            origin_product=origin_product,
            client_provenance=client_provenance,
            created_by=created_by,
            repository=repository,
            github_integration=github_integration,
            runtime=runtime,
        )
        authorship_mode = get_pr_authorship_mode(
            task_stub,
            {"run_source": RunSource.SIGNAL_REPORT.value}
            if origin_product == Task.OriginProduct.SIGNAL_REPORT
            else None,
        )
        if authorship_mode == PrAuthorshipMode.USER:
            user_github_integration = resolve_user_github_integration_for_task(
                task_stub,
                repository=repository,
                allow_refresh=True,
            )
            if user_github_integration_is_usable(user_github_integration):
                github_user_integration = user_github_integration.integration if user_github_integration else None
        elif authorship_mode == PrAuthorshipMode.BOT and github_integration is None:
            # If BOT starts a task, provides a repo, but there's no team GitHub Integration,
            # then use the user_id BOT provided and get user's GitHub Integration instead
            user_github_integration = resolve_user_github_integration_for_task(
                task_stub,
                repository=repository,
                allow_refresh=True,
            )
            if user_github_integration is not None:
                github_user_integration = user_github_integration.integration

        if repository:
            if not github_integration and github_user_integration is None and not is_public_sandbox_repo(repository):
                raise ValueError(f"Team {team.id} does not have a GitHub integration")

        sandbox_env = None
        if sandbox_environment_id is not None:
            sandbox_env = SandboxEnvironment.get_accessible_for_task(
                environment_id=sandbox_environment_id,
                team_id=team.id,
                task_created_by_id=user_id,
            )
            if sandbox_env is None:
                raise ValueError(f"Invalid sandbox_environment_id: {sandbox_environment_id}")

        expected_agent_key = MCP_BUILT_IN_AGENT_KEY_BY_ORIGIN.get(origin_product)
        if mcp_builtin_agent_key is not None and mcp_builtin_agent_key != expected_agent_key:
            raise ValueError(f"Agent key {mcp_builtin_agent_key!r} does not match task origin {origin_product!r}")

        initial_state: dict[str, Any] = {}
        if mcp_builtin_agent_key:
            initial_state[MCP_BUILT_IN_AGENT_STATE_KEY] = mcp_builtin_agent_key
            # Only ever recorded alongside the agent marker: without one there is no agent
            # run to delegate to, and a stray owner id must not be able to ride on a task.
            if mcp_credential_owner_id is not None:
                initial_state[MCP_CREDENTIAL_OWNER_STATE_KEY] = mcp_credential_owner_id
            if mcp_gateway_server_ids is not None:
                initial_state[MCP_GATEWAY_SERVER_ALLOWLIST_STATE_KEY] = [str(i) for i in mcp_gateway_server_ids]

        task = Task.objects.create(
            team=team,
            title=title,
            title_manually_set=title_manually_set,
            description=description,
            origin_product=origin_product,
            client_provenance=client_provenance,
            created_by=created_by,
            github_integration=github_integration,
            github_user_integration=github_user_integration,
            repository=repository,
            channel=channel,
            internal=internal,
            runtime=runtime,
            json_schema=resolve_schema(output_schema) if output_schema else None,
            state=initial_state,
            hog_flow_id=hog_flow_id,
            origin_key=origin_key,
            **({"signal_report_id": signal_report_id} if signal_report_id else {}),
        )

        extra_state: dict[str, Any] = {}
        if slack_thread_url:
            extra_state["slack_thread_url"] = slack_thread_url
        if interaction_origin:
            extra_state["interaction_origin"] = interaction_origin
        elif slack_thread_context:
            extra_state["interaction_origin"] = "slack"
        if origin_product == Task.OriginProduct.SIGNAL_REPORT:
            extra_state["run_source"] = RunSource.SIGNAL_REPORT.value
            extra_state["pr_authorship_mode"] = PrAuthorshipMode.BOT.value
        elif origin_product in (Task.OriginProduct.USER_CREATED, Task.OriginProduct.SLACK):
            extra_state["pr_authorship_mode"] = (
                PrAuthorshipMode.USER.value if github_user_integration is not None else PrAuthorshipMode.BOT.value
            )

        if sandbox_env is not None:
            extra_state["sandbox_environment_id"] = str(sandbox_env.id)

        # Per-run custom base image (Modal VM runtime only); wins over the environment's image.
        if custom_image_id is not None:
            custom_image = SandboxCustomImage.get_accessible_for_task(
                image_id=custom_image_id, team_id=team.id, task_created_by_id=user_id
            )
            if custom_image is None or not custom_image.is_ready:
                raise ValueError(f"Invalid custom_image_id: {custom_image_id}")
            extra_state["custom_image_id"] = str(custom_image.id)

        if branch:
            extra_state["pr_base_branch"] = branch

        if model:
            extra_state["model"] = model

        # `runtime_adapter` selects the harness (claude | codex) and the agent server derives
        # the provider from it, so a pinned model must ship with its matching runtime. Codex runs
        # default permission mode to `auto` so a headless run doesn't stall on a prompt.
        if runtime_adapter:
            extra_state["runtime_adapter"] = runtime_adapter
            provider = get_provider_for_runtime_adapter(runtime_adapter)
            if provider is not None:
                extra_state["provider"] = provider.value
            if initial_permission_mode is None and runtime_adapter == RuntimeAdapter.CODEX.value:
                initial_permission_mode = "auto"
        if reasoning_effort:
            extra_state["reasoning_effort"] = reasoning_effort

        # Forwarded to the in-sandbox agent and lifted onto its $ai_generation traces as an
        # `ai_stage` property (see TaskProcessingContext / agent-server configureEnvironment).
        if ai_stage:
            extra_state["ai_stage"] = ai_stage

        if initial_permission_mode:
            extra_state["initial_permission_mode"] = initial_permission_mode

        # Optional per-task sandbox compute/timeout overrides. Read back into
        # SandboxConfig at provision time (see TaskProcessingContext); unset
        # fields keep the SandboxConfig defaults.
        if sandbox_resources is not None:
            if sandbox_resources.cpu_cores is not None:
                extra_state["sandbox_cpu_cores"] = sandbox_resources.cpu_cores
            if sandbox_resources.memory_gb is not None:
                extra_state["sandbox_memory_gb"] = sandbox_resources.memory_gb
        if sandbox_timeout_seconds is not None:
            extra_state["sandbox_ttl_seconds"] = sandbox_timeout_seconds

        # Optional per-task inactivity timeout override (seconds). Read back via
        # TaskProcessingContext.inactivity_timeout(); unset falls back to the
        # origin-aware default.
        if inactivity_timeout_seconds is not None:
            extra_state["inactivity_timeout_seconds"] = inactivity_timeout_seconds

        # Marks this as a cloud setup-wizard run: the workflow runs the wizard in the sandbox before
        # the agent (see run_wizard activity / TaskProcessingContext.wizard_config).
        if wizard_config is not None:
            extra_state["wizard_config"] = wizard_config
            # The agent-server self-delivers pending_user_message the moment it boots. With
            # overlap-clone-boot the server launches during provisioning, so that first turn
            # ("commit the wizard's changes, open a PR") runs before run_wizard has touched the
            # repo, finds nothing to commit, and consumes the prompt — the run then idles forever.
            # Wizard runs must boot the agent only after the wizard step.
            extra_state["overlap_clone_boot_enabled"] = False

        # Server-generated head branch the agent is instructed to push to, so the GitHub PR
        # webhook can bind the opened PR back to this run (webhooks.find_task_run). Kept out of
        # TaskRun.branch, which means "branch to check out at provisioning" — not "branch the
        # agent will create".
        if wizard_head_branch:
            extra_state["wizard_head_branch"] = wizard_head_branch

        # Same server-generated-branch pattern for signals implementation runs: the stamped value
        # is the only caller-unwritable end of the run->PR link, so the self-driving review
        # carve-out matches a PR's GitHub-attested head ref against it (find_signal_implementation_run)
        # instead of trusting the API-writable output.pr_url.
        if self_driving_head_branch:
            extra_state["self_driving_head_branch"] = self_driving_head_branch

        # The first message handed to the agent once its server is ready (forward_pending_user_message
        # reads it from run state). Without it a background run boots the agent idle — it never gets a
        # prompt and just sits there while relay_sandbox_events waits for events that never come.
        if pending_user_message:
            extra_state["pending_user_message"] = pending_user_message

        # Builder sessions must run on the exact VM base that custom images layer on.
        if custom_image_builder_id:
            extra_state["custom_image_builder_id"] = custom_image_builder_id
            extra_state["use_modal_vm_sandbox"] = True

        return task, extra_state

    @staticmethod
    def create_without_run(
        *,
        team: Team,
        title: str,
        description: str,
        origin_product: "Task.OriginProduct",
        user_id: int,
        repository: str | None = None,
        channel: Channel | None = None,
        slack_thread_context: Optional["SlackThreadContext"] = None,
        slack_thread_url: str | None = None,
        branch: str | None = None,
        signal_report_id: str | None = None,
        sandbox_environment_id: str | None = None,
        internal: bool = False,
        output_schema: type[BaseModel] | dict | None = None,
        interaction_origin: str | None = None,
        model: str | None = None,
        initial_permission_mode: str | None = None,
        mcp_builtin_agent_key: MCPBuiltInAgentKey | None = None,
        client_provenance: TaskClientProvenance | None = None,
        mcp_credential_owner_id: int | None = None,
        mcp_gateway_server_ids: list[str] | None = None,
    ) -> "Task":
        """Create the Task row without an initial run or workflow.

        For callers that own run creation themselves — e.g. the sandbox warm path
        (`products/tasks/backend/logic/services/warm.py`), which creates the first run with its
        own state. The run `extra_state` assembled by `_build_task` is discarded here.
        """
        task, _ = Task._build_task(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            user_id=user_id,
            repository=repository,
            channel=channel,
            slack_thread_context=slack_thread_context,
            slack_thread_url=slack_thread_url,
            branch=branch,
            signal_report_id=signal_report_id,
            sandbox_environment_id=sandbox_environment_id,
            internal=internal,
            output_schema=output_schema,
            interaction_origin=interaction_origin,
            model=model,
            initial_permission_mode=initial_permission_mode,
            mcp_builtin_agent_key=mcp_builtin_agent_key,
            client_provenance=client_provenance,
            mcp_credential_owner_id=mcp_credential_owner_id,
            mcp_gateway_server_ids=mcp_gateway_server_ids,
        )
        return task

    @staticmethod
    def create_and_run(
        *,
        team: Team,
        title: str,
        description: str,
        origin_product: "Task.OriginProduct",
        user_id: int,
        title_manually_set: bool = False,
        repository: str | None = None,  # Format: "organization/repository", e.g. "posthog/posthog-js"
        channel: Channel | None = None,
        create_pr: bool = True,
        mode: str = "background",
        slack_thread_context: Optional["SlackThreadContext"] = None,
        slack_thread_url: str | None = None,
        start_workflow: bool = True,
        posthog_mcp_scopes: PosthogMcpScopes = "full",
        branch: str | None = None,
        signal_report_id: str | None = None,
        hog_flow_id: uuid.UUID | None = None,
        origin_key: str | None = None,
        extra_run_state: dict[str, Any] | None = None,
        sandbox_environment_id: str | None = None,
        internal: bool = False,
        client_provenance: TaskClientProvenance | None = None,
        output_schema: type[BaseModel] | dict | None = None,
        interaction_origin: str | None = None,
        runtime: str = "acp",
        runtime_adapter: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        initial_permission_mode: str | None = None,
        sandbox_resources: "SandboxResources | None" = None,
        sandbox_timeout_seconds: int | None = None,
        inactivity_timeout_seconds: int | None = None,
        ai_stage: str | None = None,
        wizard_config: dict | None = None,
        wizard_head_branch: str | None = None,
        self_driving_head_branch: str | None = None,
        pending_user_message: str | None = None,
        workflow_id_prefix: str | None = None,
        custom_image_builder_id: str | None = None,
        custom_image_id: str | None = None,
        github_read_access: bool = False,
        mcp_builtin_agent_key: MCPBuiltInAgentKey | None = None,
        mcp_credential_owner_id: int | None = None,
        mcp_gateway_server_ids: list[str] | None = None,
    ) -> "Task":
        from products.tasks.backend.logic.services.workflow_dispatch import (
            WorkflowDispatchOptions,
            enqueue_or_start_workflow,
        )
        from products.tasks.backend.temporal.client import _normalize_slack_context

        task, extra_state = Task._build_task(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            user_id=user_id,
            title_manually_set=title_manually_set,
            repository=repository,
            channel=channel,
            slack_thread_context=slack_thread_context,
            slack_thread_url=slack_thread_url,
            branch=branch,
            signal_report_id=signal_report_id,
            hog_flow_id=hog_flow_id,
            origin_key=origin_key,
            sandbox_environment_id=sandbox_environment_id,
            internal=internal,
            client_provenance=client_provenance,
            output_schema=output_schema,
            interaction_origin=interaction_origin,
            runtime=runtime,
            runtime_adapter=runtime_adapter,
            model=model,
            reasoning_effort=reasoning_effort,
            initial_permission_mode=initial_permission_mode,
            sandbox_resources=sandbox_resources,
            sandbox_timeout_seconds=sandbox_timeout_seconds,
            inactivity_timeout_seconds=inactivity_timeout_seconds,
            ai_stage=ai_stage,
            wizard_config=wizard_config,
            wizard_head_branch=wizard_head_branch,
            self_driving_head_branch=self_driving_head_branch,
            pending_user_message=pending_user_message,
            custom_image_builder_id=custom_image_builder_id,
            custom_image_id=custom_image_id,
            mcp_builtin_agent_key=mcp_builtin_agent_key,
            mcp_credential_owner_id=mcp_credential_owner_id,
            mcp_gateway_server_ids=mcp_gateway_server_ids,
        )

        run_extra_state = dict(extra_state or {})
        # Caller-supplied run state (e.g. a workflow action's config_snapshot) wins over the
        # derived defaults, matching how loop fires assemble their run state by hand.
        if extra_run_state:
            run_extra_state.update(extra_run_state)
        if github_read_access:
            # Read by TaskProcessingContext.github_read_access: provisioning injects a read-only
            # GitHub token into the (repo-less) sandbox instead of the full credential path.
            run_extra_state["github_read_access"] = True
        # Persist everything the dispatch needs alongside the row, in the same INSERT, so a
        # reconciler can re-dispatch faithfully if the workflow start is ever lost.
        run_extra_state["pending_dispatch"] = {
            "create_pr": create_pr,
            "posthog_mcp_scopes": posthog_mcp_scopes,
            "user_id": user_id,
            "slack_thread_context": _normalize_slack_context(slack_thread_context),
            "workflow_id_prefix": workflow_id_prefix,
        }

        with transaction.atomic():
            task_run = task.create_run(mode=mode, extra_state=run_extra_state or None, branch=branch)

            if start_workflow:
                # Defer the fire-and-forget workflow start until the creating transaction commits.
                # Otherwise, when create_and_run runs inside a transaction.atomic() block, the
                # workflow's first activity can read the TaskRun before its row is visible and fail.
                # on_commit runs the callback immediately in autocommit mode, so non-atomic callers
                # are unaffected. If the callback is lost (process recycled in the commit->callback
                # window, or an earlier on_commit hook raising), the run stays QUEUED — the periodic
                # reconciler re-dispatches it from the persisted pending_dispatch above.
                execute_after_commit(lambda: observe_task_run_dispatch_callback(task_run, phase="scheduled"))
                enqueue_or_start_workflow(
                    task_run,
                    options=WorkflowDispatchOptions(
                        user_id=user_id,
                        create_pr=create_pr,
                        slack_thread_context=_normalize_slack_context(slack_thread_context),
                        posthog_mcp_scopes=posthog_mcp_scopes,
                        workflow_id_prefix=workflow_id_prefix,
                    ),
                )

        return task


class TaskSession(TeamScopedRootMixin, UUIDModel):
    organization = models.ForeignKey(
        "posthog.Organization",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
        db_index=False,
    )
    team = models.ForeignKey(
        "posthog.Team",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
        db_index=False,
    )
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="task_sessions", db_index=False)
    object_storage_key = models.CharField(max_length=512, null=True, blank=True, unique=True)
    content_sha256 = models.CharField(max_length=64, null=True, blank=True)
    size = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_session"
        indexes = [
            models.Index(fields=["organization", "-updated_at"], name="task_session_org_updated_idx"),
            models.Index(fields=["team", "-updated_at"], name="task_session_team_updated_idx"),
            models.Index(fields=["task", "-updated_at"], name="task_session_task_updated_idx"),
        ]

    @classmethod
    def create_for_task(cls, task: Task) -> "TaskSession":
        return cls.objects.unscoped().create(
            organization_id=task.team.organization_id,
            team_id=task.team_id,
            task=task,
        )

    def read_jsonl(self) -> str:
        if self.object_storage_key is None:
            return ""
        return object_storage.read(self.object_storage_key, missing_ok=True) or ""

    def tag_object(self) -> None:
        if self.object_storage_key is None:
            return
        try:
            object_storage.tag(
                self.object_storage_key,
                {
                    "data_class": "task_session",
                    "organization_id": str(self.organization_id),
                    "team_id": str(self.team_id),
                    "task_id": str(self.task_id),
                },
            )
        except Exception as error:
            logger.warning(
                "task_session.failed_to_tag_object",
                task_session_id=str(self.id),
                object_storage_key=self.object_storage_key,
                error=str(error),
            )


class TaskThreadMessage(TeamScopedRootMixin):
    """One message in a task's thread — the side conversation channel members have
    around a task. Human messages never reach the agent unless the task author
    forwards one (send_to_agent), which stamps the forwarded_* fields. Agent rows
    (``author_kind=AGENT``, no ``author``) are server-emitted announcements carrying
    a stable ``event`` key + ``payload`` — the same shape as ``ChannelFeedMessage`` —
    so clients can render them structurally and dedupe them against live
    session-derived views (e.g. ``turn_complete`` carries the run id)."""

    class AuthorKind(models.TextChoices):
        HUMAN = "human", "Human"
        SYSTEM = "system", "System"
        AGENT = "agent", "Agent"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: adding an FK constraint to those hot tables
    # locks them and stalls deploys; Django still enforces the relation and on_delete at the
    # app level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="thread_messages")
    author = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    author_kind = models.CharField(max_length=16, choices=AuthorKind, default=AuthorKind.HUMAN)
    # Stable event key + structured payload for non-human rows (empty for human
    # messages); `content` stays the rendered text so older clients degrade cleanly.
    event = models.CharField(max_length=64, blank=True, default="")
    payload = models.JSONField(default=dict, blank=True)
    content = models.TextField()
    forwarded_to_agent_at = models.DateTimeField(null=True, blank=True)
    forwarded_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    forwarded_run = models.ForeignKey(
        "tasks.TaskRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_index=False
    )
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_thread_message"
        indexes = [
            models.Index(fields=["task", "created_at"], name="task_thread_msg_task_created"),
        ]

    def __str__(self):
        return f"Thread message {self.id} on task {self.task_id}"


class TaskThreadMessageMention(TeamScopedRootMixin):
    """One @-mention of a user inside a thread message, indexed at write time so the
    mentions feed is a single indexed query instead of a client-side scan of every
    channel's threads. ``created_at`` is copied from the message so listing never
    joins for ordering."""

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: adding an FK constraint to those hot tables
    # locks them and stalls deploys; Django still enforces the relation and on_delete at the
    # app level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    message = models.ForeignKey(TaskThreadMessage, on_delete=models.CASCADE, related_name="mentions")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="+")
    mentioned_user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_thread_message_mention"
        constraints = [
            models.UniqueConstraint(fields=["message", "mentioned_user"], name="task_mention_message_user_unique")
        ]
        indexes = [models.Index(fields=["team", "mentioned_user", "created_at"], name="task_mention_team_user_created")]

    def __str__(self):
        return f"Mention of user {self.mentioned_user_id} in message {self.message_id}"


class TaskActivity(TeamScopedRootMixin):
    """One row per (user, task): the latest thing that happened on a task the user is
    involved in, plus whether they have seen it.

    Collapsing to one row per task is what makes "read" a property of the task rather
    than of a feed cursor, so opening the task from anywhere clears it. Rows are
    projected on write by ``products.tasks.backend.facade.api``.
    """

    class Kind(models.TextChoices):
        CREATED = "created", "Created"
        MENTION = "mention", "Mention"
        MESSAGE = "message", "Message"
        AWAITING_INPUT = "awaiting_input", "Awaiting input"
        COMPLETED = "completed", "Completed"

    # uuid7 rather than the uuid4 the sibling task models use: rows are insert-heavy and
    # read newest-first, so a time-ordered key keeps the index appends local and makes the
    # id a meaningful tiebreak when two rows share an activity_at.
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="+")
    message = models.ForeignKey(
        TaskThreadMessage, on_delete=models.SET_NULL, null=True, blank=True, related_name="activity_rows"
    )
    kind = models.CharField(max_length=32, choices=Kind)
    activity_at = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_task_activity"
        constraints = [models.UniqueConstraint(fields=["team", "user", "task"], name="task_activity_user_task_unique")]
        indexes = [
            models.Index(fields=["team", "user", "activity_at", "id"], name="task_activity_feed_idx"),
            models.Index(
                fields=["team", "user"], condition=models.Q(read_at__isnull=True), name="task_activity_unread_idx"
            ),
        ]

    @classmethod
    def record(
        cls,
        *,
        team_id: int,
        user_id: int,
        task_id: uuid.UUID | str,
        kind: str,
        activity_at: datetime,
        message_id: uuid.UUID | None = None,
        actor_id: int | None = None,
    ) -> None:
        """Record the latest activity on ``task_id`` for ``user_id``, newest-wins.

        A single upsert rather than read-modify-write: two messages landing on the same
        task concurrently would otherwise race and lose one. The ``WHERE`` on the conflict
        clause is what makes it newest-wins, so an out-of-order write (a retried Temporal
        activity, say) can't drag ``activity_at`` backwards.

        Activity the user caused themselves lands already-read — their own reply should
        never light up their own unread badge.
        """
        read_at = activity_at if actor_id is not None and actor_id == user_id else None
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {cls._meta.db_table}
                       (id, team_id, user_id, task_id, message_id, kind, activity_at, read_at)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (team_id, user_id, task_id) DO UPDATE
                   SET message_id = EXCLUDED.message_id,
                       kind = EXCLUDED.kind,
                       activity_at = EXCLUDED.activity_at,
                       read_at = CASE
                           WHEN {cls._meta.db_table}.activity_at = EXCLUDED.activity_at
                           THEN {cls._meta.db_table}.read_at
                           ELSE EXCLUDED.read_at
                       END
                 WHERE {cls._meta.db_table}.activity_at <= EXCLUDED.activity_at
                """,
                [uuid7(), team_id, user_id, task_id, message_id, kind, activity_at, read_at],
            )


class TaskCommentActivity(TeamScopedRootMixin):
    class Kind(models.TextChoices):
        MENTION = "mention", "Mention"
        THREAD_REPLY = "thread_reply", "Thread reply"
        OWNED_ITEM_COMMENT = "owned_item_comment", "Owned item comment"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="+")
    comment = models.ForeignKey(
        "posthog.Comment",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
        db_index=False,
    )
    root_comment = models.ForeignKey(
        "posthog.Comment",
        on_delete=models.CASCADE,
        related_name="+",
        db_constraint=False,
        db_index=False,
    )
    kind = models.CharField(max_length=32, choices=Kind)
    activity_at = models.DateTimeField()
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_task_comment_activity"
        constraints = [
            models.UniqueConstraint(
                fields=["team", "user", "comment"],
                name="task_comment_activity_unique",
            )
        ]
        indexes = [
            models.Index(fields=["team", "user", "activity_at", "id"], name="task_comment_activity_feed"),
            models.Index(
                fields=["team", "user"],
                condition=models.Q(read_at__isnull=True),
                name="task_comment_activity_unread",
            ),
        ]

    @classmethod
    def record_many(
        cls,
        *,
        team_id: int,
        task_id: uuid.UUID | str,
        comment_id: uuid.UUID,
        root_comment_id: uuid.UUID,
        activity_at: datetime,
        recipients: dict[int, str],
    ) -> None:
        if not recipients:
            return
        values = []
        params: list[Any] = []
        for user_id, kind in recipients.items():
            values.append("(%s, %s, %s, %s, %s, %s, %s, %s, NULL)")
            params.extend([uuid7(), team_id, user_id, task_id, comment_id, root_comment_id, kind, activity_at])
        with connection.cursor() as cursor:
            cursor.execute(
                f"""
                INSERT INTO {cls._meta.db_table}
                       (id, team_id, user_id, task_id, comment_id, root_comment_id, kind, activity_at, read_at)
                VALUES {", ".join(values)}
                ON CONFLICT (team_id, user_id, comment_id) DO UPDATE
                   SET task_id = EXCLUDED.task_id,
                       root_comment_id = EXCLUDED.root_comment_id,
                       kind = EXCLUDED.kind,
                       activity_at = EXCLUDED.activity_at,
                       read_at = CASE
                           WHEN {cls._meta.db_table}.activity_at <= EXCLUDED.activity_at
                                AND {cls._meta.db_table}.kind = EXCLUDED.kind
                           THEN {cls._meta.db_table}.read_at
                           ELSE NULL
                       END
                 WHERE {cls._meta.db_table}.activity_at <= EXCLUDED.activity_at
                """,
                params,
            )


class TaskPin(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="+")
    pinned_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_pin"
        constraints = [models.UniqueConstraint(fields=["user", "task"], name="task_pin_user_task_unique")]
        indexes = [models.Index(fields=["user", "-pinned_at"], name="task_pin_user_pinned_idx")]


def bump_task_activity(*, team_id: int, task_id: uuid.UUID | str, at: datetime) -> None:
    """Move a task's activity clock forward to ``at``, newest-wins.

    A guarded ``UPDATE`` rather than a ``save()``: it must not drag ``updated_at`` along
    (that field answers when the task row was last edited), and the ``WHERE`` is what keeps
    a retried Temporal activity or a slow writer from pulling the clock backwards.
    """
    Task.objects.filter(team_id=team_id, id=task_id).filter(
        models.Q(last_activity_at__isnull=True) | models.Q(last_activity_at__lt=at)
    ).update(last_activity_at=at)


@receiver(post_save, sender=TaskThreadMessage)
def bump_task_activity_on_thread_message(sender, instance: "TaskThreadMessage", created: bool, **kwargs) -> None:
    if created:
        bump_task_activity(team_id=instance.team_id, task_id=instance.task_id, at=instance.created_at)


@receiver(post_save, sender=Task)
def project_task_created_activity(sender, instance: Task, created: bool, **kwargs) -> None:
    """Seed the creator's activity row. A signal rather than a facade call because tasks are
    created from several paths (API, loops, the sandbox warm path) and every one of them
    should show up in its creator's feed."""
    if created and instance.created_by_id is not None:
        TaskActivity.record(
            team_id=instance.team_id,
            user_id=instance.created_by_id,
            task_id=instance.id,
            kind=TaskActivity.Kind.CREATED,
            activity_at=instance.created_at,
            actor_id=instance.created_by_id,
        )


class ChannelFeedMessage(TeamScopedRootMixin):
    """A durable, team-visible announcement in a channel's feed — rendered alongside
    task cards as a "PostHog agent" system row (e.g. "Adam created this context").
    The channel feed is otherwise a task list, so these give channel lifecycle events
    a home without shoe-horning them into tasks. ``author`` is the user whose action
    produced the row (for "Adam …"); ``author_kind`` says who authored it."""

    class AuthorKind(models.TextChoices):
        HUMAN = "human", "Human"
        SYSTEM = "system", "System"
        AGENT = "agent", "Agent"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: adding an FK constraint to those hot
    # tables locks them and stalls deploys; Django still enforces the relation and
    # on_delete at the app level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="feed_messages")
    author = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    author_kind = models.CharField(max_length=16, choices=AuthorKind, default=AuthorKind.SYSTEM)
    # A stable event key the client maps to copy (e.g. "context_created"), plus a
    # structured payload (e.g. {"context_name": "mobile"}) so rendering survives renames.
    event = models.CharField(max_length=64)
    payload = models.JSONField(default=dict, blank=True)
    # Optional freeform fallback when there is no structured event.
    content = models.TextField(blank=True, default="")
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_channel_feed_message"
        indexes = [models.Index(fields=["channel", "created_at"], name="task_channel_feed_msg_created")]

    def __str__(self):
        return f"Feed message {self.id} on channel {self.channel_id}"


class ChannelInstructions(TeamScopedRootMixin):
    """A versioned markdown instructions blob (CONTEXT.md) attached to a channel.

    Each edit publishes a new row (incrementing ``version``, flipping the previous
    ``is_latest`` off) so history is preserved and auditable. A channel with no
    rows simply has no instructions yet — readers present that as a blank
    version 0."""

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="instruction_versions")

    # The markdown instructions describing the channel's context.
    content = models.TextField()

    version = models.PositiveIntegerField(default=1)
    is_latest = models.BooleanField(default=True)
    deleted = models.BooleanField(default=False)

    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_channel_instructions"
        constraints = [
            models.UniqueConstraint(
                fields=["channel", "version"],
                condition=models.Q(deleted=False),
                name="unique_channel_instructions_version",
            ),
            models.UniqueConstraint(
                fields=["channel"],
                condition=models.Q(deleted=False, is_latest=True),
                name="unique_channel_instructions_latest",
            ),
        ]


class ChannelContextGeneration(TeamScopedRootMixin):
    """Tracks which Task is currently generating a channel's CONTEXT.md.

    Project-shared, per-channel marker so any user sees the in-progress state.
    ``task_id`` is a plain UUID (same app, but kept soft to match the canvas
    product's generation pointer). Cleared automatically when a new
    instructions version is published."""

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    channel = models.OneToOneField(Channel, on_delete=models.CASCADE, related_name="context_generation")

    task_id = models.UUIDField(null=True, blank=True)

    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_channel_context_generation"


class ChannelStar(TeamScopedRootMixin):
    """A user's star on a channel (the sidebar pin). Per-user, per-channel."""

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    channel = models.ForeignKey(Channel, on_delete=models.CASCADE, related_name="stars")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+", db_constraint=False)

    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_channel_star"
        constraints = [
            models.UniqueConstraint(fields=["channel", "user"], name="unique_channel_star_per_user"),
        ]


class Loop(ModelActivityMixin, TeamScopedRootMixin):
    """A named, cloud-executed agent automation: instructions plus model config,
    fired by schedule/GitHub/API triggers. Each firing spawns an internal Task
    that runs on the standard tasks pipeline as the loop's owner (created_by).
    See products/tasks/docs/LOOPS.md."""

    class Visibility(models.TextChoices):
        PERSONAL = "personal", "Personal"
        TEAM = "team", "Team"

    class OverlapPolicy(models.TextChoices):
        SKIP = "skip", "Skip"
        ALLOW = "allow", "Allow"
        CANCEL_PREVIOUS = "cancel_previous", "Cancel previous"

    activity_logging_on_delete = True

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: adding an FK constraint to those hot tables
    # locks them and stalls deploys; Django still enforces the relation and on_delete at the
    # app level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    # The original creator, immutable. `created_by` doubles as the current owner and is reassigned by
    # ownership takeover; `creator` is not, so it stays the authority for the destructive/visibility
    # operations (delete, un-share) that takeover must not confer on whoever grabbed the loop.
    creator = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    name = models.CharField(max_length=400)
    description = models.TextField(blank=True, default="")
    visibility = models.CharField(max_length=16, choices=Visibility, default=Visibility.PERSONAL)
    instructions = models.TextField()
    runtime_adapter = models.CharField(max_length=32)
    model = models.CharField(max_length=128, blank=True, default="")
    reasoning_effort = models.CharField(max_length=32, null=True, blank=True)
    repositories = models.JSONField(default=list, blank=True)
    sandbox_environment = models.ForeignKey(
        "tasks.SandboxEnvironment", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    enabled = models.BooleanField(default=True)
    overlap_policy = models.CharField(max_length=32, choices=OverlapPolicy, default=OverlapPolicy.SKIP)
    behaviors = models.JSONField(default=dict, blank=True)
    connectors = models.JSONField(default=dict, blank=True)
    notifications = models.JSONField(default=dict, blank=True)
    # Binding to a context (a "#channel" / desktop folder) this loop is attached to, or {} when
    # unattached. Shape: {folder_id, name, outputs: {post_to_feed, update_context, canvas_id}}.
    # Drives feed placement (each run's Task.channel) and the context.md / canvas publish contract
    # injected into every run's prompt. See products/tasks/docs/LOOPS.md.
    context_target = models.JSONField(default=dict, blank=True)
    # Skill bundles attached at save time: zipped local skills whose manifest entries (same shape
    # as TaskRun.artifacts entries, type "skill_bundle", bytes in object storage under
    # get_skill_bundle_s3_prefix()) are copied into every fired run so the sandbox installs them.
    skill_bundles = models.JSONField(default=list, blank=True)
    internal = models.BooleanField(
        default=False,
        help_text="If true, this loop is for internal use and should not be exposed to end users.",
    )
    # What created this loop: `user_created` for loops a person made in the UI/API, other values
    # mark loops created by a backend flow. Mirrors `Task.origin_product` (attribution, not
    # ownership; the loop is still team- and owner-scoped via `team`/`created_by`).
    origin_product = models.CharField(
        max_length=32,
        choices=task_origin_product_choices,
        default=Task.OriginProduct.USER_CREATED,
        help_text="Which product or flow created this loop.",
    )
    client_provenance = models.CharField(
        max_length=32,
        choices=TaskClientProvenance,
        null=True,
        blank=True,
        editable=False,
    )
    last_run_at = models.DateTimeField(null=True, blank=True)
    last_run_status = models.CharField(max_length=32, null=True, blank=True)
    last_error = models.TextField(null=True, blank=True)
    consecutive_failures = models.PositiveIntegerField(default=0)
    # Why a loop is currently paused when it wasn't the owner who paused it, so the UI can explain
    # it and a reactivation flow can clear it. Null for a normal owner pause. See loop_lifecycle.py.
    disabled_reason = models.CharField(max_length=64, null=True, blank=True)
    deleted = models.BooleanField(default=False)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_loop"

    def __str__(self):
        return self.name

    @staticmethod
    def skill_bundle_s3_prefix_for(team_id: int, loop_id: "uuid.UUID | str") -> str:
        """Base prefix for a loop's skill bundle objects in S3, computable from ids so
        seeding can validate snapshot paths without loading the row."""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/artifacts/team_{team_id}/loop_{loop_id}"

    def get_skill_bundle_s3_prefix(self) -> str:
        return Loop.skill_bundle_s3_prefix_for(self.team_id, self.id)

    def _get_before_update(self, **kwargs: Any) -> "Loop | None":
        # ModelActivityMixin's prior-state lookup goes through `objects` (the fail-closed
        # TeamScopedManager). Loop saves happen from webhook handlers and Temporal activities
        # with no ambient team scope, so route the lookup through `.unscoped()` to avoid a
        # TeamScopeError when logging the change (same pattern as SignalScoutConfig).
        if not self.pk:
            return None
        return type(self).objects.unscoped().filter(pk=self.pk).first()


class LoopTrigger(TeamScopedRootMixin):
    """One firing condition attached to a loop. Schedule triggers are backed by a
    Temporal Schedule whose identity hangs off this row's id, so trigger rows are
    updated in place, never delete-and-recreated."""

    class TriggerType(models.TextChoices):
        SCHEDULE = "schedule", "Schedule"
        GITHUB = "github", "GitHub"
        API = "api", "API"

    class ScheduleSyncStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        SYNCED = "synced", "Synced"
        FAILED = "failed", "Failed"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team FK: same hot-table rationale as Loop above.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    loop = models.ForeignKey(Loop, on_delete=models.CASCADE, related_name="triggers")
    type = models.CharField(max_length=16, choices=TriggerType)
    enabled = models.BooleanField(default=True)
    config = models.JSONField(default=dict)
    # Denormalized off `config` for `type=github` rows only (see `save()`), so webhook
    # fan-out matching hits an indexed column instead of scanning the JSON `config` blob.
    github_integration_id = models.BigIntegerField(null=True, blank=True)
    repository = models.CharField(max_length=512, null=True, blank=True)
    event_types = ArrayField(models.CharField(max_length=32), null=True, blank=True)
    schedule_sync_status = models.CharField(max_length=16, choices=ScheduleSyncStatus, null=True, blank=True)
    last_fired_at = models.DateTimeField(null=True, blank=True)
    # Set once a one-time (`run_at`) trigger has fired its single occurrence. Terminal: its spent
    # Temporal Schedule is torn down and no sync path re-arms it. See loop_service.complete_one_time_trigger.
    completed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_loop_trigger"
        indexes = [
            models.Index(fields=["github_integration_id", "repository"], name="task_loop_trigger_gh_repo_idx"),
        ]

    def __str__(self):
        return f"{self.type} trigger on loop {self.loop_id}"

    def save(self, *args, **kwargs):
        if self.type == self.TriggerType.GITHUB:
            config = self.config if isinstance(self.config, dict) else {}
            github_integration_id = config.get("github_integration_id")
            try:
                self.github_integration_id = int(github_integration_id) if github_integration_id is not None else None
            except (TypeError, ValueError):
                self.github_integration_id = None
            repository = config.get("repository")
            self.repository = repository.strip() if isinstance(repository, str) and repository.strip() else None
            events = config.get("events")
            self.event_types = (
                [event for event in events if isinstance(event, str)] if isinstance(events, list) else None
            )
        else:
            self.github_integration_id = None
            self.repository = None
            self.event_types = None
        super().save(*args, **kwargs)

    @property
    def schedule_id(self) -> str:
        return f"loop-trigger-{self.id}"


class LoopFire(TeamScopedRootMixin):
    """Per-fire dedup record, so schedule replays, webhook redeliveries, API retries and
    double-clicked manual runs never double-spawn a run. Trigger fires dedup on
    (loop_trigger, fire_key); manual "run now" fires have no trigger and dedup on
    (loop, fire_key). The fire key is the Temporal workflow id, the X-GitHub-Delivery GUID
    or the client idempotency key depending on path. The created run's ids and terminal
    reason are recorded so a dedup hit (a retry) returns the original outcome instead of a
    bare "deduped"."""

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team FK: same hot-table rationale as Loop above.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    # Always set. Direct FK (not just via loop_trigger) so manual fires have a dedup scope and so
    # the per-loop rate-cap and retention queries hit an index instead of joining through trigger.
    loop = models.ForeignKey(Loop, on_delete=models.CASCADE, related_name="fires", null=True, db_constraint=False)
    # Null for manual "run now" fires, which have no trigger.
    # SET_NULL, not CASCADE: replacing a trigger during an ordinary edit must not delete its LoopFire
    # rows. Those rows carry the per-loop/per-team rate-cap history (counted by `loop`, which survives),
    # so a CASCADE would let an owner reset their own cost caps just by editing triggers.
    loop_trigger = models.ForeignKey(
        LoopTrigger, on_delete=models.SET_NULL, related_name="fires", null=True, blank=True
    )
    fire_key = models.CharField(max_length=512)
    # Outcome of the fire, for returning to a retry that dedups against this row.
    outcome_reason = models.CharField(max_length=64, null=True, blank=True)
    outcome_task_id = models.UUIDField(null=True, blank=True)
    outcome_task_run_id = models.UUIDField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)

    class Meta:
        db_table = "posthog_task_loop_fire"
        constraints = [
            # Trigger fires: unique per (trigger, key). Partial so manual fires (null trigger)
            # don't all collide on a shared NULL.
            models.UniqueConstraint(
                fields=["loop_trigger", "fire_key"],
                name="task_loop_fire_trigger_key_unique",
                condition=models.Q(loop_trigger__isnull=False),
            ),
            # Manual fires: unique per (loop, key) when there's no trigger.
            models.UniqueConstraint(
                fields=["loop", "fire_key"],
                name="task_loop_fire_loop_key_unique",
                condition=models.Q(loop_trigger__isnull=True),
            ),
        ]
        indexes = [
            # Per-loop rate-cap window and retention pruning.
            models.Index(fields=["loop", "created_at"], name="task_loop_fire_loop_ct_idx"),
        ]

    def __str__(self):
        return f"Fire {self.fire_key} on loop {self.loop_id}"


class TaskRun(models.Model):
    class Status(models.TextChoices):
        NOT_STARTED = "not_started", "Not Started"
        QUEUED = "queued", "Queued"
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETED = "completed", "Completed"
        FAILED = "failed", "Failed"
        CANCELLED = "cancelled", "Cancelled"

    class Environment(models.TextChoices):
        LOCAL = "local", "Local"
        CLOUD = "cloud", "Cloud"

    # nosemgrep: prefer-uuid7-django-pk -- TODO: migrate to uuid7 or clarify intent
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="runs")
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    active_task_session = models.ForeignKey(
        TaskSession,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="active_runs",
    )

    branch = models.CharField(max_length=255, blank=True, null=True, help_text="Branch name for the run")

    environment = models.CharField(
        max_length=10,
        choices=Environment,
        default=Environment.CLOUD,
        help_text="Execution environment",
    )

    # Stage tracking
    stage = models.CharField(
        max_length=100,
        blank=True,
        null=True,
        help_text="Current stage for this run (e.g., 'research', 'plan', 'build')",
    )

    status = models.CharField(max_length=20, choices=Status, default=Status.NOT_STARTED)

    error_message = models.TextField(blank=True, null=True, help_text="Error message if execution failed")

    # This is a structured output of the run. This is used to store the PR URL, commit SHA, etc.
    output = models.JSONField(
        blank=True,
        null=True,
        help_text="Run output data (e.g., PR URL, commit SHA, etc.)",
    )

    # Artifact manifest describing files uploaded to S3 for this run.
    artifacts = models.JSONField(
        blank=True,
        default=list,
        help_text="List of artifacts uploaded to S3 for this run.",
    )

    # Store intermediate run state in this field. This is used to resume the run if it fails, or to provide context throughout the run.
    state = models.JSONField(
        default=dict,
        blank=True,
        help_text="Run state data for resuming or tracking execution state",
    )

    # Local url-based MCP servers imported from the creating client (PostHog Desktop),
    # merged into the sandbox agent server's --mcpServers at spawn. Encrypted because
    # header values carry credentials; never exposed through API responses.
    imported_mcp_servers = EncryptedJSONStringField(
        blank=True,
        null=True,
        default=None,
        help_text="Client-imported MCP server configs (type/name/url/headers) to make available in the sandbox",
    )

    relayed_mcp_servers = models.JSONField(
        blank=True,
        null=True,
        default=None,
        help_text="Names of desktop-only MCP servers the creating client relays into this run (docs/cloud-mcp-relay.md). Names only — configuration never crosses the wire.",
    )

    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    # When the run last entered QUEUED. `created_at` can't stand in for it because
    # `prepare_for_cloud_handoff` re-queues an existing run without resetting it, and
    # `updated_at` can't either because any unrelated write to a still-queued run would
    # move it. Null on rows queued before this field existed; readers fall back to
    # `created_at`, which is exact for a run that was only ever queued once.
    queued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_task_run"
        ordering = ["-created_at"]
        indexes = [
            GinIndex(
                OpClass(KeyTransform("verified_pr_urls", "state"), name="jsonb_path_ops"),
                name="task_run_verified_pr_urls_idx",
            ),
            GinIndex(
                OpClass(KeyTransform("head_branches", "output"), name="jsonb_path_ops"),
                name="task_run_head_branches_idx",
            ),
            models.Index(
                fields=["branch"],
                name="task_run_branch_idx",
                condition=models.Q(branch__isnull=False),
            ),
            # Partial functional index backing the per-PR-webhook lookup
            # `filter(output__pr_url=...)`. The equality lookup implies the key is
            # present, so the `IS NOT NULL` condition keeps the index off the many
            # runs without a PR URL (queued/in-progress/failed) while still serving
            # the query.
            models.Index(
                KeyTransform("pr_url", "output"),
                name="task_run_output_pr_url_idx",
                condition=models.Q(output__pr_url__isnull=False),
            ),
            # Same shape for the wizard-run webhook leg `filter(state__wizard_head_branch=...)`;
            # only wizard runs carry the key, so the index stays tiny.
            models.Index(
                KeyTransform("wizard_head_branch", "state"),
                name="task_run_wizard_branch_idx",
                condition=models.Q(state__wizard_head_branch__isnull=False),
            ),
            # Same shape again for the self-driving review carve-out lookup
            # `filter(state__self_driving_head_branch=...)`; only signals implementation runs
            # carry the key.
            models.Index(
                KeyTransform("self_driving_head_branch", "state"),
                name="task_run_sd_branch_idx",
                condition=models.Q(state__self_driving_head_branch__isnull=False),
            ),
            # Time-range scans over runs (default ordering, recent-runs lookups, and the
            # signals outcome-billing query that buckets PR runs into a period).
            models.Index(fields=["created_at"], name="task_run_created_at_idx"),
            models.Index(fields=["task", "-created_at", "-id"], name="task_run_task_created_idx"),
            models.Index(
                fields=["team", "stage", "task"],
                name="task_run_team_stage_task_idx",
                condition=models.Q(stage__isnull=False),
            ),
        ]

    def __str__(self):
        return f"Run for {self.task.title} - {self.get_status_display()}"

    @property
    def mode(self) -> str:
        """Get the execution mode from state. Defaults to 'background'."""
        return (self.state or {}).get("mode", "background")

    def get_sandbox_environment(self) -> Optional["SandboxEnvironment"]:
        """Resolve the SandboxEnvironment for this run, scoped to team and respecting privacy.

        Private environments are only accessible if the task creator matches the
        environment creator. If either created_by is null, private environments
        are not accessible.
        """
        env_id = (self.state or {}).get("sandbox_environment_id")
        if not env_id:
            return None
        return SandboxEnvironment.get_accessible_for_task(
            environment_id=env_id,
            team_id=self.team_id,
            task_created_by_id=self.task.created_by_id,
        )

    def prepare_for_cloud_handoff(self) -> None:
        """
        Restart this run in the cloud, resuming from its existing log/checkpoints.

        The `handoff_resumed` flag tells the workflow and sandbox provisioning
        to treat this as a resume of the same run (skip initial prompt, hydrate
        from the existing log) without overloading `resume_from_run_id`, which
        means "continue from a different run".
        """
        self.status = self.Status.QUEUED
        self.environment = self.Environment.CLOUD
        self.queued_at = django_timezone.now()
        self.completed_at = None
        self.error_message = None

        state = self.state or {}
        prior_snapshot_external_id = state.get("snapshot_external_id")
        prior_snapshot_kind = state.get("snapshot_kind")
        prior_snapshot_mount_path = state.get("snapshot_mount_path")
        state["handoff_resumed"] = True
        state["mode"] = "interactive"
        state.pop("pending_user_message", None)
        state.pop("pending_user_artifact_ids", None)
        state.pop("pending_user_message_id", None)
        state.pop("pending_user_message_ts", None)
        state.pop("sandbox_id", None)
        state.pop("sandbox_url", None)
        state.pop("sandbox_jwt_kid", None)
        state.pop("sandbox_connect_token", None)
        # Drop the provider stamp too: the handed-off run re-resolves its backend from
        # scratch, so a stale `hogland` must not survive to outrank the EU guard, the
        # Modal-only fallbacks, or the flag kill switch on the next context resolution.
        state.pop("sandbox_backend", None)
        self.state = state

        logger.info(
            "prepare_for_cloud_handoff",
            run_id=str(self.id),
            task_id=str(self.task_id),
            prior_snapshot_external_id=prior_snapshot_external_id,
            prior_snapshot_kind=prior_snapshot_kind,
            prior_snapshot_mount_path=prior_snapshot_mount_path,
        )

        self.save(
            update_fields=[
                "status",
                "environment",
                "queued_at",
                "completed_at",
                "error_message",
                "state",
                "updated_at",
            ]
        )
        self.publish_stream_state_event()

    @classmethod
    def mutate_state_atomic(
        cls,
        run_id: str | uuid.UUID,
        mutator: Callable[[dict[str, Any]], None],
    ) -> dict[str, Any]:
        """Apply a state mutation while holding a row lock on the task run.

        Task-run state is updated from several independent activities. Using a
        locked read avoids stale read-modify-write cycles that can resurrect
        keys another activity has already removed.
        """
        with transaction.atomic():
            locked_task_run = cls.objects.select_for_update().get(id=run_id)
            state = dict(locked_task_run.state or {})
            mutator(state)
            locked_task_run.state = state
            locked_task_run.save(update_fields=["state", "updated_at"])
            return state

    @classmethod
    def update_state_atomic(
        cls,
        run_id: str | uuid.UUID,
        *,
        updates: dict[str, Any] | None = None,
        remove_keys: Iterable[str] | None = None,
    ) -> dict[str, Any]:
        """Merge state updates against the latest persisted row state."""

        def _mutator(state: dict[str, Any]) -> None:
            for key in remove_keys or []:
                state.pop(key, None)
            if not updates:
                return
            state.update(updates)
            if "pending_user_message_id" in updates:
                return
            if "pending_user_message" in updates or "pending_user_artifact_ids" in updates:
                stamp_pending_user_message_id(state, refresh=True)

        return cls.mutate_state_atomic(run_id, _mutator)

    @classmethod
    def update_output_atomic(
        cls,
        run_id: str | uuid.UUID,
        *,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        """Merge output updates against the latest persisted row output.

        Output is written from several independent places (the agent server, the
        PR webhook backstop, the CI follow-up snapshot), so an unlocked
        read-modify-write could resurrect keys another writer already changed.
        Skips the save when nothing changes, so pollers don't churn ``updated_at``.
        """
        with transaction.atomic():
            locked_task_run = cls.objects.select_for_update().get(id=run_id)
            output = dict(locked_task_run.output or {})
            merged = {**output, **updates}
            if merged == output:
                return output
            locked_task_run.output = merged
            locked_task_run.save(update_fields=["output", "updated_at"])
            return merged

    @classmethod
    def clear_sandbox_connection_state_atomic(
        cls,
        run_id: str | uuid.UUID,
        sandbox_id: str,
    ) -> dict[str, Any]:
        def _mutator(state: dict[str, Any]) -> None:
            if state.get("sandbox_id") != sandbox_id:
                return

            for key in ("sandbox_id", "sandbox_url", "sandbox_connect_token", "sandbox_jwt_kid", "sandbox_backend"):
                state.pop(key, None)

        return cls.mutate_state_atomic(run_id, _mutator)

    @staticmethod
    def get_workflow_id(
        task_id: str | uuid.UUID, run_id: str | uuid.UUID, workflow_id_prefix: str | None = None
    ) -> str:
        """Get the Temporal workflow ID for a task run, optionally under a caller-supplied prefix."""
        if workflow_id_prefix:
            return f"{workflow_id_prefix}-{task_id}-{run_id}"
        return f"task-processing-{task_id}-{run_id}"

    @property
    def workflow_id(self) -> str:
        """The run's actual Temporal workflow ID.

        A prefixed dispatch persists the started ID in `state` (it isn't derivable from ids alone);
        the default ID stays derived.
        """
        persisted = self.state.get("workflow_id") if isinstance(self.state, dict) else None
        if persisted:
            return persisted
        return self.get_workflow_id(self.task_id, self.id)

    def heartbeat_workflow(self, agent_active: bool = False) -> None:
        if not agent_active:
            return

        from products.tasks.backend.redis import get_tasks_cache

        cache_key = f"tasks:task_run:heartbeat:{self.id}:active"
        if not get_tasks_cache().add(cache_key, True, timeout=60):
            return

        import asyncio

        from posthog.temporal.common.client import sync_connect

        from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

        try:
            client = sync_connect()
            handle = client.get_workflow_handle(self.workflow_id)
            asyncio.run(handle.signal(ProcessTaskWorkflow.heartbeat, arg=agent_active))
        except Exception as e:
            logger.warning("task_run.heartbeat_failed", task_run_id=str(self.id), error=str(e))

    def signal_client_activity(self) -> None:
        from products.tasks.backend.redis import get_tasks_cache

        cache_key = f"tasks:task_run:client_activity:{self.id}"
        if not get_tasks_cache().add(cache_key, True, timeout=60):
            return

        import asyncio

        from posthog.temporal.common.client import sync_connect

        from products.tasks.backend.temporal.process_task.workflow import ProcessTaskWorkflow

        try:
            client = sync_connect()
            handle = client.get_workflow_handle(self.workflow_id)
            asyncio.run(handle.signal(ProcessTaskWorkflow.client_activity))
        except Exception as e:
            logger.warning("task_run.client_activity_signal_failed", task_run_id=str(self.id), error=str(e))

    @property
    def log_url(self) -> str:
        """Generate the S3 path for this run's logs."""
        return f"{self.get_task_s3_prefix()}/run_{self.id}.jsonl"

    def get_task_s3_prefix(self) -> str:
        """Base prefix for task-scoped objects in S3."""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/logs/team_{self.team_id}/task_{self.task_id}"

    def get_artifact_s3_prefix(self) -> str:
        """Base prefix for storing artifacts in S3."""
        tasks_folder = settings.OBJECT_STORAGE_TASKS_FOLDER
        return f"{tasks_folder}/artifacts/team_{self.team_id}/task_{self.task_id}/run_{self.id}"

    def get_resume_chain(self, max_depth: int = 10) -> list["TaskRun"]:
        """Walk `state.resume_from_run_id` from this run upward.

        Returns runs ordered oldest-ancestor → ... → parent → this. Bounded
        depth and a seen-set guard against cycles. The walk is scoped to this
        task — a stale cross-task `resume_from_run_id` is silently dropped.

        Loads sibling runs in a single query and walks in-memory so chain depth
        doesn't translate to per-hop database round trips.
        """
        chain: list[TaskRun] = [self]
        if max_depth <= 0:
            return chain

        # Walking the chain only needs id/state/artifacts and the bits that
        # `log_url` derives from (team_id, task_id). Fetching the full row would
        # pull every column for every historical run on the task.
        siblings_qs = self.task.runs.only("id", "team_id", "task_id", "state", "artifacts")
        siblings_by_id: dict[str, TaskRun] = {str(run.id): run for run in siblings_qs}
        seen: set[str] = {str(self.id)}
        current: TaskRun | None = self
        depth = 0
        while current is not None and depth < max_depth:
            prior_id_raw = (current.state or {}).get("resume_from_run_id")
            if not prior_id_raw:
                break
            try:
                prior_id = str(uuid.UUID(str(prior_id_raw)))
            except (ValueError, TypeError):
                break
            if prior_id in seen:
                break
            seen.add(prior_id)
            current = siblings_by_id.get(prior_id)
            if current is None:
                break
            chain.append(current)
            depth += 1
        chain.reverse()
        return chain

    def find_artifact_in_resume_chain(self, storage_path: str) -> dict | None:
        """Find an artifact by storage_path on this run or any ancestor in the resume chain."""
        # Iterate newest-first since artifact is more likely to be on this run.
        for run in reversed(self.get_resume_chain()):
            for entry in run.artifacts or []:
                if entry.get("storage_path") == storage_path:
                    return entry
        return None

    @staticmethod
    def _is_agent_message_chunk(entry: dict) -> bool:
        """Check if an entry is an agent_message_chunk event."""
        notification = entry.get("notification", {})
        if not isinstance(notification, dict):
            return False
        if notification.get("method") != "session/update":
            return False
        params = notification.get("params", {})
        update = params.get("update", {}) if isinstance(params, dict) else {}
        return update.get("sessionUpdate") == "agent_message_chunk" if isinstance(update, dict) else False

    # Default S3 retention for a freshly-created run log. Live runs auto-expire after a month;
    # callers that must preserve a log indefinitely pass `ttl_days=None` so it is never tagged for
    # expiry — user history must not silently vanish after 30 days.
    DEFAULT_LOG_TTL_DAYS = 30

    def append_log(self, entries: list[dict], *, ttl_days: int | None = DEFAULT_LOG_TTL_DAYS):
        """Append log entries to S3 storage.

        `ttl_days` tags a newly-created log file for expiry; pass `None` to write a log that is
        never auto-expired. The tag is only applied on
        first write — re-tagging an existing log would not change a TTL already in flight.
        """
        entries = [e for e in entries if not self._is_agent_message_chunk(e)]
        if not entries:
            return

        is_new_file = append_jsonl_object(self.log_url, entries)

        self._mirror_logs_to_posthog_logs(entries)

        if is_new_file and ttl_days is not None:
            try:
                object_storage.tag(
                    self.log_url,
                    {
                        "ttl_days": str(ttl_days),
                        "team_id": str(self.team_id),
                    },
                )
            except Exception as e:
                logger.warning(
                    "task_run.failed_to_tag_logs",
                    task_run_id=str(self.id),
                    log_url=self.log_url,
                    error=str(e),
                )

    def _mirror_logs_to_posthog_logs(self, entries: list[dict]) -> None:
        """Mirror persisted entries into the PostHog Logs product via stdout (dogfooding).

        Fire-and-forget: mirroring failures must never break the run's log write.
        """
        from products.tasks.backend.feature_flags import agent_otel_telemetry_enabled_for_state
        from products.tasks.backend.logic.services.run_log_mirror import mirror_entries, mirroring_enabled

        if not settings.TASK_RUN_LOGS_MIRROR_ORIGIN_PRODUCTS:
            return

        # Per-run rollout decision (tasks-agent-run-otel-telemetry), stamped into run
        # state at dispatch; fail closed while the stamp is absent.
        if not agent_otel_telemetry_enabled_for_state(self.state if isinstance(self.state, dict) else None):
            return

        try:
            origin_product = self.task.origin_product
            if not mirroring_enabled(origin_product):
                return

            mirror_entries(
                entries,
                team_id=self.team_id,
                task_id=str(self.task_id),
                run_id=str(self.id),
                origin_product=origin_product,
            )
        except Exception as e:
            logger.warning(
                "task_run.mirror_logs_to_posthog_logs_failed",
                task_run_id=str(self.id),
                error=str(e),
            )

    def effective_rtk(self) -> bool | None:
        """rtk posture for analytics: the launch-persisted effective value, falling
        back to the user's explicit override for runs that never launched."""
        state = self.state if isinstance(self.state, dict) else {}
        rtk = state.get("rtk_effective", state.get("rtk_enabled"))
        return rtk if isinstance(rtk, bool) else None

    def _analytics_usage_properties(self) -> dict:
        """Token usage and rtk posture for analytics events.

        The agent-server merges cumulative usage into ``state.token_usage`` as turns
        settle.
        """
        props: dict = {}
        state = self.state if isinstance(self.state, dict) else {}
        usage = state.get("token_usage")
        if isinstance(usage, dict):
            for key in (
                "input_tokens",
                "output_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "thought_tokens",
                "total_tokens",
                "turns",
            ):
                value = usage.get(key)
                if isinstance(value, int | float) and not isinstance(value, bool):
                    props["usage_turns" if key == "turns" else key] = value
        rtk = self.effective_rtk()
        if rtk is not None:
            props["rtk_enabled"] = rtk
        return props

    def capture_event(
        self,
        event: str,
        properties: dict | None = None,
        event_uuid: str | None = None,
        distinct_id_override: str | None = None,
    ) -> bool:
        """Capture an analytics event for this run. Returns False when it never reached capture.

        The exception stays swallowed — no caller wants a failed analytics call to fail their
        work — but the outcome is reported so callers tracking event loss can count it.
        """
        try:
            # The override lets the PR webhook attribute pr_merged to the GitHub user who
            # actually merged, rather than the task's assigned user.
            distinct_id = distinct_id_override or (
                str(self.task.created_by.distinct_id)
                if self.task.created_by_id and self.task.created_by
                else str(self.team.uuid)
            )
            all_properties: dict = {
                "task_id": str(self.task_id),
                "run_id": str(self.id),
                "team_id": self.team_id,
                "repository": self.task.repository,
                "repositories": (self.state or {}).get("repositories")
                or self.task.repositories
                or ([self.task.repository] if self.task.repository else []),
                "origin_product": self.task.origin_product,
                "title": self.task.title,
                "signal_report_id": str(self.task.signal_report_id) if self.task.signal_report_id else None,
                "loop_id": (self.state or {}).get("loop_id"),
                "loop_trigger_id": (self.state or {}).get("loop_trigger_id"),
                "environment": self.environment,
                # The bare `environment` property gets clobbered by the analytics
                # client's deployment-region super-property, so ship the run's
                # local/cloud value under an unclobbered name too.
                "run_environment": self.environment,
                "mode": self.mode,
                **self._analytics_usage_properties(),
            }
            if properties:
                all_properties.update(properties)
            capture_kwargs: dict = {
                "distinct_id": distinct_id,
                "event": event,
                "properties": all_properties,
                "groups": groups(team=self.team),
                "send_feature_flags": True,
            }
            if event_uuid:
                capture_kwargs["uuid"] = event_uuid
            posthoganalytics.capture(**capture_kwargs)
        except Exception as e:
            logger.warning("task_run.capture_event_failed", analytics_event=event, error=str(e))
            return False
        return True

    def _duration_seconds(self) -> float:
        if self.completed_at and self.created_at:
            return round((self.completed_at - self.created_at).total_seconds(), 1)
        return 0.0

    def mark_completed(self, *, notify: bool = True, analytics_properties: dict | None = None) -> None:
        """Mark the progress as completed.

        ``notify=False`` skips the push notification — for janitor-style finalization of a run
        the user is no longer watching, where a "finished" ping long after the fact is noise.
        ``analytics_properties`` are merged into the ``task_run_completed`` capture so swept
        completions stay distinguishable from organic ones.
        """
        self.status = self.Status.COMPLETED
        self.completed_at = django_timezone.now()
        self.save(update_fields=["status", "completed_at"])
        self.publish_stream_state_event()
        self.capture_event(
            "task_run_completed",
            {"duration_seconds": self._duration_seconds(), **(analytics_properties or {})},
        )
        if not notify:
            return
        from products.tasks.backend.push_dispatcher import notify_task_run_completed

        notify_task_run_completed(self)

    def track_structured_result(self):
        """Track a structured result event with properties from the run output."""
        if not self.output:
            return

        try:
            self.capture_event("task_run_structured_result", {"result": self.output})
        except Exception as e:
            logger.warning(
                "task_run.track_structured_result_failed",
                task_run_id=str(self.id),
                error=str(e),
            )

    def mark_failed(self, error: str, error_type: str | None = None) -> None:
        """Mark the progress as failed with an error message."""
        self.status = self.Status.FAILED
        self.error_message = error
        self.completed_at = django_timezone.now()
        self.save(update_fields=["status", "error_message", "completed_at"])
        self.publish_stream_state_event()
        self.capture_event(
            "task_run_failed",
            {
                "error_message": truncate_error_message(error),
                "error_type": error_type or "unspecified",
                "duration_seconds": self._duration_seconds(),
            },
        )
        from products.tasks.backend.push_dispatcher import notify_task_run_failed

        notify_task_run_failed(self)

    def build_stream_state_event(self) -> dict[str, Any]:
        return {
            "type": "task_run_state",
            "run_id": str(self.id),
            "task_id": str(self.task_id),
            "status": self.status,
            "stage": self.stage,
            "output": self.output,
            "branch": self.branch,
            "error_message": self.error_message,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
        }

    def publish_stream_event(self, event: dict[str, Any]) -> None:
        publish_task_run_stream_event(str(self.id), event, run_uses_dedicated_stream(self.state))

    def publish_stream_state_event(self) -> None:
        self.publish_stream_event(self.build_stream_state_event())

    def emit_console_event(self, level: LogLevel, message: str) -> None:
        """Emit a console-style log event in ACP notification format."""
        event = {
            "type": "notification",
            "timestamp": django_timezone.now().isoformat(),
            "notification": {
                "jsonrpc": "2.0",
                "method": "_posthog/console",
                "params": {
                    "sessionId": str(self.id),
                    "level": level,
                    "message": message,
                },
            },
        }
        self.append_log([event])
        self.publish_stream_event(event)

    def emit_conversation_cleared(self) -> None:
        """Record a `/clear` that had no sandbox to run it.

        A live run clears through the agent, which swaps in a fresh agent session and
        emits this marker itself. A finished run has no sandbox, and booting one just to
        clear it would cost a whole run, so the marker is written straight to the log.
        Resume reads a chain's logs concatenated and rebuilds only the turns after the
        marker, so the next run continues the task with an empty conversation while its
        checkpoints, artifacts, and visible history stay intact.

        The `/clear` message is recorded ahead of the marker, matching the agent, so the
        transcript shows what the user typed and rehydration drops it with everything
        else on the pre-clear side. It carries the `importedUserPrompt` tag because the
        desktop client renders user turns from `session/prompt` requests and drops raw
        `user_message_chunk`s; the tag tells its log replay to promote the chunk into one.

        The marker carries no `sessionId`: there is no agent session behind it, and
        resume reads that field to decide which session to continue.

        A repeat call while the log already ends at the boundary appends nothing, so a
        double-submitted or retried clear doesn't stack duplicate markers.
        """
        if self._log_tail_is_conversation_cleared():
            return
        timestamp = django_timezone.now().isoformat()
        events = [
            {
                "type": "notification",
                "timestamp": timestamp,
                "notification": {
                    "jsonrpc": "2.0",
                    "method": "session/update",
                    "params": {
                        "sessionId": str(self.id),
                        "update": {
                            "sessionUpdate": "user_message_chunk",
                            "content": {"type": "text", "text": "/clear"},
                            "_meta": {"importedUserPrompt": True},
                        },
                    },
                },
            },
            {
                "type": "notification",
                "timestamp": timestamp,
                "notification": {
                    "jsonrpc": "2.0",
                    "method": "_posthog/conversation_cleared",
                    "params": {},
                },
            },
        ]
        self.append_log(events)
        for event in events:
            self.publish_stream_event(event)

    def _log_tail_is_conversation_cleared(self) -> bool:
        # Reads the whole object because S3 offers no cheap tail read; clears are rare
        # and the subsequent append re-reads it anyway.
        content = object_storage.read(self.log_url, missing_ok=True) or ""
        last_line = content.strip().rsplit("\n", 1)[-1]
        if not last_line:
            return False
        try:
            entry = json.loads(last_line)
        except json.JSONDecodeError:
            return False
        if not isinstance(entry, dict):
            return False
        notification = entry.get("notification")
        return isinstance(notification, dict) and notification.get("method") == "_posthog/conversation_cleared"

    def emit_progress_event(
        self,
        step: str,
        status: str,
        label: str,
        group: str,
        detail: Optional[str] = None,
    ) -> None:
        """Emit a structured progress notification in ACP format.

        Consumed by the desktop client as `_posthog/progress`. Events sharing a
        `group` coalesce into a single collapsible card on the client, so the
        backend decides grouping granularity by picking a phase id (e.g.
        `"setup"`, `"pr_create"`).
        """
        event = self.build_progress_event(step, status, label, group, detail)
        self.append_log([event])
        self.publish_stream_event(event)

    def build_progress_event(
        self,
        step: str,
        status: str,
        label: str,
        group: str,
        detail: Optional[str] = None,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "sessionId": str(self.id),
            "step": step,
            "status": status,
            "label": label,
            "group": group,
        }
        if detail is not None:
            params["detail"] = detail
        return {
            "type": "notification",
            "timestamp": django_timezone.now().isoformat(),
            "notification": {
                "jsonrpc": "2.0",
                "method": "_posthog/progress",
                "params": params,
            },
        }

    def emit_sandbox_output(self, stdout: str, stderr: str, exit_code: int) -> None:
        """Emit sandbox execution output as ACP notification."""
        event = {
            "type": "notification",
            "timestamp": django_timezone.now().isoformat(),
            "notification": {
                "jsonrpc": "2.0",
                "method": "_posthog/sandbox_output",
                "params": {
                    "sessionId": str(self.id),
                    "stdout": stdout,
                    "stderr": stderr,
                    "exitCode": exit_code,
                },
            },
        }
        self.append_log([event])
        self.publish_stream_event(event)

    @property
    def ownership_version(self) -> str | None:
        return _task_ownership_version(self.state)

    def matches_task_ownership(self, task: Task | None = None) -> bool:
        current_task = task or self.task
        return self.ownership_version == current_task.ownership_version

    @property
    def is_terminal(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.FAILED, self.Status.CANCELLED}

    def delete(self, *args, **kwargs):
        raise Exception("Cannot delete TaskRun. Task runs are immutable records.")


class TaskWorkflowDispatch(TeamScopedRootMixin):
    class Kind(models.TextChoices):
        CREATE = "create", "create"
        RESTART = "restart", "restart"

    class Status(models.TextChoices):
        PENDING = "pending", "pending"
        CLAIMED = "claimed", "claimed"
        ACCEPTED = "accepted", "accepted"
        DEAD = "dead", "dead"

    id = models.UUIDField(primary_key=True, default=uuid7, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, db_constraint=False, db_index=False)
    task_run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name="workflow_dispatches", db_index=False)
    workflow_id = models.CharField(max_length=512)
    dispatch_kind = models.CharField(max_length=16, choices=Kind.choices)
    payload = models.JSONField(default=dict)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    attempt_count = models.PositiveIntegerField(default=0)
    enqueued_at = models.DateTimeField(default=django_timezone.now)
    next_attempt_at = models.DateTimeField(default=django_timezone.now)
    claimed_by = models.CharField(max_length=128, blank=True, default="")
    lease_expires_at = models.DateTimeField(null=True, blank=True)
    accepted_at = models.DateTimeField(null=True, blank=True)
    last_error = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_taskworkflowdispatch"
        constraints = [
            models.UniqueConstraint(fields=["task_run", "dispatch_kind"], name="uniq_dispatch_per_run_kind"),
            models.CheckConstraint(
                name="accepted_at_iff_accepted",
                condition=models.Q(status="accepted", accepted_at__isnull=False)
                | (~models.Q(status="accepted") & models.Q(accepted_at__isnull=True)),
            ),
        ]
        indexes = [
            models.Index(fields=["next_attempt_at"], condition=models.Q(status="pending"), name="twd_pending_due"),
            models.Index(fields=["lease_expires_at"], condition=models.Q(status="claimed"), name="twd_claimed_lease"),
            models.Index(fields=["team", "created_at"], name="twd_team_created"),
        ]


class AgentPeerMessage(TeamScopedRootMixin):
    """One agent-to-agent message between two cloud task runs, relayed through the
    control plane (see logic/services/peer_messages.py). The row is both the audit
    record and the target run's queue-capacity unit: ``outcome`` advances
    accepted → signaled → delivered, with terminals rejected / target_finished /
    delivery_failed. Synchronous states are set by the send path;
    delivery states by the follow-up activity — a non-terminal row past the delivery
    window counts as expired for capacity, so a lost activity can't wedge the cap.
    ``content`` is the sender-authored body only; the delivered text wraps it in a
    server-composed envelope that is never persisted here."""

    class Outcome(models.TextChoices):
        ACCEPTED = "accepted", "Accepted"
        SIGNALED = "signaled", "Signaled"
        DELIVERED = "delivered", "Delivered"
        REJECTED = "rejected", "Rejected"
        TARGET_FINISHED = "target_finished", "Target finished"
        DELIVERY_FAILED = "delivery_failed", "Delivery failed"

    NON_TERMINAL_OUTCOMES = (Outcome.ACCEPTED, Outcome.SIGNALED)

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: adding an FK constraint to those hot tables
    # locks them and stalls deploys; Django still enforces the relation and on_delete at the
    # app level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    # db_index=False on the run FKs: the composite indexes below lead with these
    # columns, so their leftmost prefix already serves single-column lookups and the
    # CASCADE scans — separate auto indexes would be pure write amplification.
    sender_run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name="sent_peer_messages", db_index=False)
    target_run = models.ForeignKey(
        TaskRun, on_delete=models.CASCADE, related_name="received_peer_messages", db_index=False
    )
    # The sender task's creating user — attribution for rendering and per-user throttles.
    # Redundant under same-user visibility, load-bearing once visibility widens team-wide.
    sender_user = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    content = models.TextField()
    # Target-side artifact ids (post copy-on-send); sender-side ids are never delivered.
    artifact_ids = models.JSONField(default=list, blank=True)
    outcome = models.CharField(max_length=20, choices=Outcome, default=Outcome.ACCEPTED)
    # Phase a terminal row failed in (queue_cap, artifact_copy, signal, credential_refresh, ...).
    failure_phase = models.CharField(max_length=50, blank=True, default="")
    failure_detail = models.TextField(blank=True, default="")
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_agent_peer_message"
        indexes = [
            # Queue-cap query: non-terminal rows for a target within the delivery window.
            models.Index(fields=["target_run", "outcome", "created_at"], name="peer_msg_target_outcome_idx"),
            # Sender-side throttle windows.
            models.Index(fields=["sender_run", "created_at"], name="peer_msg_sender_created_idx"),
        ]

    def __str__(self):
        return f"Peer message {self.id}: run {self.sender_run_id} → run {self.target_run_id} ({self.outcome})"


class TaskArtifact(TeamScopedRootMixin, UUIDModel):
    class ArtifactType(models.TextChoices):
        SLACK_MESSAGE = "slack_message", "Slack message"
        SLACK_CANVAS = "slack_canvas", "Slack canvas"
        DOCUMENT = "document", "Document"
        SPREADSHEET = "spreadsheet", "Spreadsheet"
        DASHBOARD = "dashboard", "Dashboard"
        FILE = "file", "File"
        GITHUB_PR = "github_pr", "GitHub PR"

    class Adapter(models.TextChoices):
        SLACK_MESSAGE = "slack_message", "Slack message"
        SLACK_CANVAS = "slack_canvas", "Slack canvas"
        SLACK_FILE = "slack_file", "Slack file"
        DOCUMENT_CONNECTOR = "document_connector", "Document connector"
        GITHUB_PR = "github_pr", "GitHub PR"

    class Status(models.TextChoices):
        ACTIVE = "active", "Active"
        FAILED = "failed", "Failed"

    # App-level scoping is enforced by TeamScopedRootMixin; avoid locking the hot Team/User tables.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="living_artifacts")
    task_run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name="living_artifacts")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )
    name = models.CharField(max_length=255)
    artifact_type = models.CharField(max_length=32, choices=ArtifactType)
    adapter = models.CharField(max_length=32, choices=Adapter)
    status = models.CharField(max_length=16, choices=Status, default=Status.ACTIVE, db_default=Status.ACTIVE)
    location = models.JSONField(
        default=dict, db_default=models.Value("{}"), help_text="Adapter-specific location data."
    )
    metadata = models.JSONField(
        default=dict, db_default=models.Value("{}"), help_text="Adapter-specific artifact metadata."
    )
    versions = models.JSONField(
        default=list, db_default=models.Value("[]"), help_text="Chronological artifact versions."
    )
    current_version = models.PositiveIntegerField(default=1, db_default=1)
    # Slack delivery exchanges this for an anonymous image url that bypasses export access
    # checks, so it's a dedicated column the API never accepts from callers — only the chart
    # endpoint sets it, for an export it rendered itself. Plain id, not an FK: exports live in
    # another product and expire on their own TTL; delivery treats a dangling id as no link.
    export_asset_id = models.BigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_artifact"
        indexes = [
            models.Index(fields=["team", "task", "-updated_at"], name="task_artifact_team_task_idx"),
            models.Index(fields=["team", "task_run", "-updated_at"], name="task_artifact_team_run_idx"),
        ]

    def __str__(self):
        return f"{self.name} ({self.artifact_type})"


class TaskSearchDocument(TeamScopedRootMixin, UUIDModel):
    """Small, rebuildable search projection for Desktop's global command menu."""

    class Kind(models.TextChoices):
        TASK = "task", "Task"
        PULL_REQUEST = "pull_request", "Pull request"
        ARTIFACT = "artifact", "Artifact"
        CHANNEL = "channel", "Channel"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="+", null=True, blank=True)
    task_run = models.ForeignKey(TaskRun, on_delete=models.CASCADE, related_name="+", null=True, blank=True)
    channel = models.ForeignKey(Channel, on_delete=models.SET_NULL, related_name="+", null=True, blank=True)
    kind = models.CharField(max_length=32, choices=Kind)
    source_key = models.CharField(max_length=512)
    title = models.CharField(max_length=512)
    subtitle = models.CharField(max_length=512, blank=True, default="")
    search_text = models.TextField()
    exact_identifiers = ArrayField(models.CharField(max_length=512), default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_task_search_document"
        constraints = [
            models.UniqueConstraint(fields=["team", "kind", "source_key"], name="task_search_doc_source_unique")
        ]
        indexes = [
            models.Index(fields=["team", "kind"], name="task_search_doc_team_kind_idx"),
            GinIndex(fields=["exact_identifiers"], name="task_search_doc_exact_gin"),
            GinIndex(fields=["search_text"], name="task_search_doc_text_trgm", opclasses=["gin_trgm_ops"]),
        ]


class SandboxSession(TeamScopedRootMixin, UUIDModel):
    """Usage ledger for one cloud sandbox: when it ran, its resource shape, and which
    slice of its lifetime is attributable to a user.

    One row per sandbox, keyed on the provider sandbox id and upserted by the
    provisioning activity so activity retries stay idempotent. Rows record raw usage
    only — pricing/credit conversion happens downstream at aggregation time
    (see logic/services/sandbox_usage.py). Pre-warmed sandboxes stay unattributed
    (``user_attributed_at`` NULL, on PostHog's dime) until a user claims the run with
    their first message; the boundary timestamps are deliberately redundant so any
    future billable-window policy (wall-clock, active-plus-grace, ...) can be computed
    from the ledger without a backfill.
    """

    class EndedReason(models.TextChoices):
        CLEANUP = "cleanup", "Cleanup"
        REAPED = "reaped", "Reaped"

    # db_constraint=False on the team FK: adding an FK constraint to that hot table
    # locks it and stalls deploys; Django still enforces the relation and on_delete at
    # the app level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    task_run = models.ForeignKey("tasks.TaskRun", on_delete=models.CASCADE, related_name="sandbox_sessions")

    sandbox_id = models.CharField(max_length=255, unique=True, help_text="Provider sandbox id (e.g. Modal object id)")
    origin_product = models.CharField(
        max_length=20,
        choices=task_origin_product_choices,
        null=True,
        blank=True,
        help_text="Task origin at provision time, denormalized for per-origin aggregation",
    )
    client_provenance = models.CharField(
        max_length=32,
        choices=TaskClientProvenance,
        null=True,
        blank=True,
        editable=False,
    )
    prewarmed = models.BooleanField(default=False, help_text="Sandbox was provisioned ahead of any user demand")
    vm_runtime = models.BooleanField(
        default=False, help_text="Modal VM runtime rather than gVisor (billed differently)"
    )
    sandbox_backend = models.CharField(
        max_length=32,
        null=True,
        blank=True,
        help_text="Provider backend (e.g. hogland); NULL for Modal. Hogland's TTL is idle, not absolute",
    )

    # Resource shape at creation, already clamped by SandboxConfig. Limits are what the
    # sandbox may consume — raw usage metrics derive from these; the burstable request
    # floors are recorded for future pricing-policy work only (Modal bills max(request, actual)).
    cpu_cores = models.FloatField(help_text="CPU core limit")
    memory_gb = models.FloatField(help_text="Memory limit in GiB")
    ttl_seconds = models.IntegerField(help_text="Hard TTL after which the provider kills the sandbox")
    burstable = models.BooleanField(default=False)
    cpu_request_cores = models.FloatField(null=True, blank=True, help_text="Reserved CPU floor when burstable")
    memory_request_mb = models.IntegerField(null=True, blank=True, help_text="Reserved memory floor when burstable")

    created_at = models.DateTimeField(default=django_timezone.now, help_text="Sandbox provisioned")
    # Anchored at the Sandbox.create() boundary, not ledger-row insert time: the
    # provider's TTL clock starts there, before repo setup runs and the row is opened.
    ttl_expires_at = models.DateTimeField(help_text="Absolute provider kill deadline (creation boundary + TTL)")
    user_attributed_at = models.DateTimeField(
        null=True, blank=True, help_text="Start of the user-attributable window; NULL while (pre)warm and unclaimed"
    )
    last_user_activity_at = models.DateTimeField(
        null=True, blank=True, help_text="Most recent user message routed to this sandbox's run"
    )
    ended_at = models.DateTimeField(
        null=True, blank=True, help_text="Sandbox destroyed; NULL rows are clamped to ttl_expires_at"
    )
    ended_reason = models.CharField(max_length=20, choices=EndedReason, null=True, blank=True)
    provider_cpu_usage_attribution_usec = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Cumulative provider CPU time sampled when user attribution starts"
    )
    provider_billed_cpu_usage_attribution_usec = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Estimated billed CPU time sampled when user attribution starts"
    )
    provider_cpu_usage_attribution_measured_at = models.DateTimeField(
        null=True, blank=True, help_text="When provider CPU usage was sampled at user attribution"
    )
    provider_cpu_usage_usec = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Cumulative provider CPU time sampled immediately before sandbox cleanup"
    )
    provider_billed_cpu_usage_usec = models.PositiveBigIntegerField(
        null=True, blank=True, help_text="Estimated billed CPU time sampled immediately before sandbox cleanup"
    )
    provider_usage_measured_at = models.DateTimeField(
        null=True, blank=True, help_text="When provider resource usage was sampled"
    )

    class Meta:
        db_table = "posthog_task_sandbox_session"
        indexes = [
            # The usage report scans sessions overlapping the period instance-wide:
            # closed recently (ended_at > begin) or open and not yet past their TTL
            # (ended_at IS NULL AND ttl_expires_at > begin) — the partial index keeps
            # rows that never got a close stamp from being re-fetched forever.
            models.Index(fields=["ended_at"], name="sandbox_session_ended_at_idx"),
            models.Index(
                fields=["ttl_expires_at"],
                condition=models.Q(ended_at__isnull=True),
                name="sandbox_session_open_ttl_idx",
            ),
            # For per-team/per-origin re-aggregation once pricing decides which origins bill.
            models.Index(fields=["team", "user_attributed_at"], name="sandbox_session_team_attr_idx"),
        ]

    def __str__(self):
        return f"Sandbox session {self.sandbox_id} for run {self.task_run_id}"


class SandboxSnapshot(UUIDModel):
    """Tracks sandbox snapshots used for sandbox environments in tasks."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", "In Progress"
        COMPLETE = "complete", "Complete"
        ERROR = "error", "Error"

    integration = models.ForeignKey(
        Integration,
        on_delete=models.SET_NULL,
        related_name="snapshots",
        null=True,
        blank=True,
    )

    external_id = models.CharField(
        max_length=255,
        blank=True,
        help_text="Snapshot ID from external provider.",
        unique=True,
    )

    repos = ArrayField(
        models.CharField(max_length=255),
        default=list,
        help_text="List of repositories in format 'org/repo'",
    )

    metadata = models.JSONField(default=dict, blank=True, help_text="Additional metadata for the snapshot.")

    status = models.CharField(
        max_length=20,
        choices=Status,
        default=Status.IN_PROGRESS,
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_sandbox_snapshot"
        indexes = [
            models.Index(fields=["integration", "status", "-created_at"]),
        ]

    def __str__(self):
        repo_count = len(self.repos)
        return f"Snapshot {self.external_id} ({self.get_status_display()}, {repo_count} repos)"

    def is_complete(self) -> bool:
        return self.status == self.Status.COMPLETE

    def has_repo(self, repo: str) -> bool:
        repo_lower = repo.lower()
        return any(r.lower() == repo_lower for r in self.repos)

    def has_repos(self, repos: list[str]) -> bool:
        return all(self.has_repo(repo) for repo in repos)

    def update_status(self, status: Status):
        self.status = status
        self.save(update_fields=["status"])

    @classmethod
    def get_latest_snapshot_for_integration(cls, integration_id: int) -> Optional["SandboxSnapshot"]:
        return (
            cls.objects.filter(
                integration_id=integration_id,
                status=cls.Status.COMPLETE,
            )
            .order_by("-created_at")
            .first()
        )

    @classmethod
    def get_latest_snapshot_with_repos(
        cls, integration_id: int, required_repos: list[str]
    ) -> Optional["SandboxSnapshot"]:
        snapshots = cls.objects.filter(
            integration_id=integration_id,
            status=cls.Status.COMPLETE,
        ).order_by("-created_at")

        for snapshot in snapshots:
            if snapshot.has_repos(required_repos):
                return snapshot
        return None

    def delete(self, *args, **kwargs):
        if self.external_id:
            from products.tasks.backend.logic.services.sandbox import Sandbox

            if os.environ.get("MODAL_TOKEN_ID") and os.environ.get("MODAL_TOKEN_SECRET") and not settings.TEST:
                try:
                    # Modal-only: hogland runs never create SandboxSnapshot rows today. When
                    # hogland resume snapshots land, this needs a backend branch keyed on the
                    # snapshot's provider rather than the MODAL_TOKEN_* env gate above.
                    Sandbox.delete_snapshot(self.external_id)
                except Exception as e:
                    raise Exception(
                        f"Failed to delete external snapshot {self.external_id}: {str(e)}. "
                        f"The database record has not been deleted."
                    ) from e

        super().delete(*args, **kwargs)


class SandboxEnvironment(UUIDModel):
    """Configuration for sandbox execution environments including network access and secrets."""

    class NetworkAccessLevel(models.TextChoices):
        TRUSTED = "trusted", "Trusted"
        FULL = "full", "Full"
        CUSTOM = "custom", "Custom"

    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True)

    name = models.CharField(max_length=255)

    network_access_level = models.CharField(
        max_length=20,
        choices=NetworkAccessLevel,
        default=NetworkAccessLevel.FULL,  # NOTE: Default should be TRUSTED once we have an egress proxy in place
    )

    allowed_domains = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        help_text="List of allowed domains for custom network access",
    )

    include_default_domains = models.BooleanField(
        default=False,
        help_text="Whether to include default trusted domains (GitHub, npm, PyPI)",
    )

    repositories = ArrayField(
        models.CharField(max_length=255),
        default=list,
        blank=True,
        help_text="List of repositories this environment applies to (format: org/repo)",
    )

    environment_variables = EncryptedJSONStringField(
        default=dict,
        blank=True,
        null=True,
        help_text="Encrypted environment variables for sandbox execution",
    )

    custom_image = models.ForeignKey(
        "SandboxCustomImage",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="Custom base image for this environment's sandboxes (Modal VM runtime only)",
    )

    private = models.BooleanField(
        default=True,
        help_text="If true, only the creator can see this environment. Otherwise visible to whole team.",
    )

    internal = models.BooleanField(
        default=False,
        help_text="If true, this environment is for internal use (e.g. signals pipeline) and should not be exposed to end users.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_sandbox_environment"
        indexes = [
            models.Index(fields=["team", "created_by"]),
        ]

    def is_accessible_for_task_creator(self, task_created_by_id: int | None) -> bool:
        if not self.private:
            return True
        return task_created_by_id is not None and self.created_by_id == task_created_by_id

    @classmethod
    def get_accessible_for_task(
        cls,
        *,
        environment_id: str | uuid.UUID,
        team_id: int,
        task_created_by_id: int | None,
    ) -> Optional["SandboxEnvironment"]:
        try:
            environment = cls.objects.filter(id=environment_id, team_id=team_id).first()
        except (ValidationError, ValueError):
            return None
        if environment is None:
            return None
        if not environment.is_accessible_for_task_creator(task_created_by_id):
            return None
        return environment

    def __str__(self):
        return self.name

    @staticmethod
    def is_valid_env_var_key(key: str) -> bool:
        if not key:
            return False
        pattern = r"^[A-Za-z_][A-Za-z0-9_]*$"
        return bool(re.match(pattern, key))

    def get_effective_domains(self) -> list[str]:
        if self.network_access_level == self.NetworkAccessLevel.FULL:
            return []

        if self.network_access_level == self.NetworkAccessLevel.TRUSTED:
            return DEFAULT_TRUSTED_DOMAINS.copy()

        if self.network_access_level == self.NetworkAccessLevel.CUSTOM:
            domains = list(self.allowed_domains)
            if self.include_default_domains:
                for domain in DEFAULT_TRUSTED_DOMAINS:
                    if domain not in domains:
                        domains.append(domain)
            return domains

        return []


class SandboxCustomImage(TeamScopedRootMixin):
    """User-defined custom base image for cloud task sandboxes, layered on the VM sandbox base."""

    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        SCANNING = "scanning", "Scanning"
        SCAN_FAILED = "scan_failed", "Scan Failed"
        BUILDING = "building", "Building"
        BUILD_FAILED = "build_failed", "Build Failed"
        READY = "ready", "Ready"
        ARCHIVED = "archived", "Archived"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
    )

    name = models.CharField(max_length=255)
    description = models.TextField(blank=True, default="")
    repository = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Optional 'org/repo' the builder session clones to verify the image can bring up its dependencies.",
    )
    private = models.BooleanField(
        default=False,
        help_text="If true, only the creator can see and use this image. Otherwise visible to the whole team.",
    )

    spec = models.JSONField(default=dict, blank=True, help_text="Declarative image spec (see SandboxImageSpec schema).")
    status = models.CharField(max_length=20, choices=Status, default=Status.DRAFT)
    version = models.PositiveIntegerField(default=0, help_text="Incremented on each successful build.")
    modal_image_name = models.CharField(
        max_length=255,
        blank=True,
        default="",
        help_text="Published Modal named-image reference (name:tag) for the latest successful build.",
    )
    base_image_reference = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="Immutable VM base image reference used for the latest successful build.",
    )
    base_image_refresh_reference = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="VM base image reference most recently queued for an automatic refresh.",
    )
    scan_result = models.JSONField(default=dict, blank=True, help_text="Latest security scan verdict and findings.")
    error = models.TextField(blank=True, default="", help_text="Failure detail for scan_failed/build_failed states.")
    build_log = models.TextField(blank=True, default="", help_text="Sanitized tail of the latest Modal build output.")

    builder_task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
        help_text="The image-builder agent task whose conversation produced this image's spec.",
    )

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_sandbox_custom_image"
        indexes = [
            models.Index(fields=["team", "status", "-created_at"]),
        ]

    def __str__(self):
        return f"{self.name} ({self.get_status_display()})"

    @property
    def is_ready(self) -> bool:
        return self.status == self.Status.READY and bool(self.modal_image_name)

    def is_accessible_to_user(self, user_id: int | None) -> bool:
        if not self.private:
            return True
        return user_id is not None and self.created_by_id == user_id

    @classmethod
    def get_accessible_for_task(
        cls,
        *,
        image_id: str | uuid.UUID,
        team_id: int,
        task_created_by_id: int | None,
    ) -> Optional["SandboxCustomImage"]:
        try:
            image = cls.objects.for_team(team_id).filter(id=image_id).first()
        except (ValidationError, ValueError):
            return None
        if image is None or not image.is_accessible_to_user(task_created_by_id):
            return None
        return image

    def modal_publish_name(self) -> str:
        # One stable tag per image — Modal has no image-deletion API, so per-version tags would accumulate.
        return f"posthog-sandbox-custom-{self.team_id}-{self.id.hex}:latest"


class CodeInviteQuerySet(models.QuerySet["CodeInvite"]):
    def unexpired(self, at: datetime | None = None) -> "CodeInviteQuerySet":
        at = at or django_timezone.now()
        return self.filter(models.Q(expires_at__isnull=True) | models.Q(expires_at__gt=at))

    def expire(self, at: datetime | None = None) -> int:
        at = at or django_timezone.now()
        return self.unexpired(at).update(expires_at=at)


class CodeInvite(UUIDModel):
    """Invite codes for PostHog Desktop access."""

    objects = CodeInviteQuerySet.as_manager()

    code = models.CharField(max_length=50, unique=True, db_index=True, blank=True)
    max_redemptions = models.PositiveIntegerField(default=1, help_text="Maximum number of redemptions. 0 = unlimited.")
    redemption_count = models.PositiveIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    expires_at = models.DateTimeField(null=True, blank=True, help_text="Optional expiration date.")
    description = models.TextField(blank=True, help_text="Internal admin note.")
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="created_code_invites"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_code_invite"

    def __str__(self):
        return self.code

    def save(self, *args, **kwargs):
        if not self.code:
            alphabet = string.ascii_uppercase + string.digits
            for attempt in range(10):
                self.code = "".join(secrets.choice(alphabet) for _ in range(8))
                try:
                    with transaction.atomic():
                        return super().save(*args, **kwargs)
                except IntegrityError:
                    if attempt == 9:
                        raise
            return
        super().save(*args, **kwargs)

    @property
    def is_redeemable(self) -> bool:
        if not self.is_active:
            return False
        if self.expires_at and self.expires_at <= django_timezone.now():
            return False
        if self.max_redemptions > 0 and self.redemption_count >= self.max_redemptions:
            return False
        return True


class CodeInviteRedemption(UUIDModel):
    """Tracks each redemption of a PostHog Desktop invite."""

    invite_code = models.ForeignKey(CodeInvite, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    organization = models.ForeignKey("posthog.Organization", on_delete=models.SET_NULL, null=True, blank=True)
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_code_invite_redemption"
        unique_together = [("invite_code", "user")]

    def __str__(self):
        return f"{self.user} redeemed {self.invite_code}"


class DesktopBetaTermsAcceptance(models.Model):
    organization = models.OneToOneField(
        "posthog.Organization",
        on_delete=models.CASCADE,
        primary_key=True,
        db_constraint=False,
    )
    accepted_by_user_id = models.BigIntegerField()
    accepted_at = models.DateTimeField(auto_now_add=True)


# How long a single beacon keeps a device "present" before the row is treated as stale.
# Clients beacon every ~30s; expiring after 60s gives them one missed POST of slack.
TASK_PRESENCE_TTL_SECONDS = 60


class TaskPresence(TeamScopedRootMixin):
    """Per-device 'this user is actively watching this task' beacon.

    Created/refreshed by the desktop and mobile PostHog Desktop clients while a
    task screen is foregrounded. The push fanout consults this table to skip
    devices that are demonstrably already watching the task, so we don't fire
    phantom notifications at a phone while the user is mid-conversation with
    the agent on their laptop.

    Rows are ephemeral (expire after ``TASK_PRESENCE_TTL_SECONDS``). Cleanup is
    lazy: every push fanout filters on ``expires_at > now``, so stale rows are
    ignored automatically. We can layer a periodic sweep on top later if the
    row count ever becomes a problem; for now there's nothing to maintain.
    """

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # `related_name="+"` on every FK so Django doesn't add reverse accessors
    # (`user.task_presences`, etc.). Presence is always queried forward — by
    # (task, user) or by push_token id — and skipping the reverse manager
    # keeps frameworks that walk all reverse relations on related models
    # (notably the User activity-logger) from tripping on this model's
    # fail-closed manager when no team context is set.
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    task = models.ForeignKey(Task, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+")
    # Identifies the device that's watching. Push fanout joins on this FK to
    # decide which tokens to suppress, and CASCADE means unregistering the push
    # token automatically clears the presence too.
    push_token = models.ForeignKey(
        "posthog.UserPushToken",
        on_delete=models.CASCADE,
        related_name="+",
    )
    last_seen_at = models.DateTimeField(auto_now=True)
    expires_at = models.DateTimeField(db_index=True)

    class Meta:
        db_table = "posthog_task_presence"
        constraints = [
            models.UniqueConstraint(
                fields=["task", "push_token"],
                name="task_presence_task_push_token_unique",
            ),
        ]

    def __str__(self):
        return f"Presence: user {self.user_id} on task {self.task_id} via device {self.push_token_id}"


@receiver(post_delete, sender=TaskSession)
def delete_task_session_object(sender: type[TaskSession], instance: TaskSession, **kwargs: Any) -> None:
    if instance.object_storage_key is None:
        return
    object_storage_key = instance.object_storage_key
    task_session_id = str(instance.id)

    def delete_object() -> None:
        try:
            object_storage.delete(object_storage_key)
        except Exception as error:
            logger.warning(
                "task_session.failed_to_delete_object",
                task_session_id=task_session_id,
                object_storage_key=object_storage_key,
                error=str(error),
            )

    transaction.on_commit(delete_object)


# A write to one of these means the agent did something a reader would call activity. Writes to
# anything else a run carries (branch, model, its sandbox session) are bookkeeping, and bumping
# on them would float an idle session to the top with nothing new to read.
RUN_ACTIVITY_FIELDS = frozenset({"status", "stage", "output", "artifacts", "completed_at", "error_message"})


@receiver(post_save, sender=TaskRun)
def bump_task_activity_on_run(sender, instance: TaskRun, created: bool, update_fields=None, **kwargs) -> None:
    # A signal rather than calls at each transition because runs are written from the API, the
    # webhook handlers, the sandbox relay, and several Temporal activities, and one path forgetting
    # to bump would silently leave a live session reading as idle.
    if not created and update_fields is not None and not (RUN_ACTIVITY_FIELDS & set(update_fields)):
        return
    bump_task_activity(team_id=instance.team_id, task_id=instance.task_id, at=django_timezone.now())


@receiver(post_save, sender=TaskRun)
def track_task_run_completion(sender, instance: TaskRun, created: bool, **kwargs):
    try:
        if (
            not created
            and instance.status == TaskRun.Status.COMPLETED
            and instance.output
            and instance.task.json_schema
        ):
            instance.track_structured_result()
    except Exception as e:
        logger.warning(
            "task_run.track_task_run_completion_failed",
            task_run_id=str(instance.id),
            error=str(e),
        )
