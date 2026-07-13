import os
import re
import json
import uuid
import string
import secrets
from collections.abc import Callable, Iterable
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal, Optional

from django.db.models.signals import post_save
from django.dispatch import receiver

from pydantic import BaseModel

if TYPE_CHECKING:
    from products.slack_app.backend.slack_thread import SlackThreadContext
    from products.tasks.backend.logic.services.sandbox import SandboxResources

from django.conf import settings
from django.contrib.postgres.fields import ArrayField
from django.core.exceptions import ValidationError
from django.db import IntegrityError, models, transaction
from django.db.models.fields.json import KeyTransform
from django.utils import timezone as django_timezone

import structlog
import posthoganalytics

from posthog.event_usage import groups
from posthog.helpers.encrypted_fields import EncryptedJSONStringField
from posthog.models.file_system.constants import DEFAULT_SURFACE, DESKTOP_SURFACE
from posthog.models.file_system.file_system_mixin import FileSystemSyncMixin
from posthog.models.file_system.file_system_representation import FileSystemRepresentation
from posthog.models.integration import Integration
from posthog.models.scoping.root_mixin import TeamScopedRootMixin
from posthog.models.team.team import Team
from posthog.models.user import User
from posthog.models.utils import DeletedMetaFields, UUIDModel
from posthog.storage import object_storage
from posthog.temporal.oauth import PosthogMcpScopes

from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS
from products.tasks.backend.error_telemetry import truncate_error_message
from products.tasks.backend.logic.stream.redis_stream import publish_task_run_stream_event
from products.tasks.backend.metrics import observe_task_run_created, observe_task_run_dispatch_callback
from products.tasks.backend.redis import evaluate_dedicated_stream_flag, run_uses_dedicated_stream

logger = structlog.get_logger(__name__)

LogLevel = Literal["debug", "info", "warn", "error"]


def resolve_schema(schema: type[BaseModel] | dict) -> dict:
    if isinstance(schema, dict):
        return schema
    return schema.model_json_schema()


class Channel(TeamScopedRootMixin):
    """A shared feed of tasks (rendered as "#<name>" in PostHog Code). Every task is
    owned by the channel it was kicked off in. Each user gets one private "personal"
    channel ("#me") per team, provisioned lazily on first channel list."""

    class ChannelType(models.TextChoices):
        PUBLIC = "public", "Public"
        PERSONAL = "personal", "Personal"

    PERSONAL_CHANNEL_NAME = "me"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # db_constraint=False on the team/user FKs: posthog_team and posthog_user are written on
    # virtually every request, and adding an FK constraint takes a SHARE ROW EXCLUSIVE lock on
    # them that stalls deploys. Django still enforces the relation and on_delete at the app
    # level (see safe-django-migrations.md).
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+", db_constraint=False)
    name = models.CharField(max_length=128)
    channel_type = models.CharField(max_length=16, choices=ChannelType, default=ChannelType.PUBLIC)
    created_by = models.ForeignKey(
        "posthog.User", on_delete=models.SET_NULL, null=True, blank=True, related_name="+", db_constraint=False
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


SLACK_NOTIFIED_PR_URL_STATE_KEY = "slack_notified_pr_url"
PR_READY_EMAIL_QUEUED_AT_STATE_KEY = "pr_ready_email_queued_at"
PR_READY_EMAIL_SENT_AT_STATE_KEY = "pr_ready_email_sent_at"
PR_READY_EMAIL_PR_URL_STATE_KEY = "pr_ready_email_pr_url"


class Task(FileSystemSyncMixin, DeletedMetaFields, models.Model):
    class OriginProduct(models.TextChoices):
        ONBOARDING = "onboarding", "Onboarding"
        ERROR_TRACKING = "error_tracking", "Error Tracking"
        EVAL_CLUSTERS = "eval_clusters", "Eval Clusters"
        USER_CREATED = "user_created", "User Created"
        AUTOMATION = "automation", "Automation"
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
        IMAGE_BUILDER = "image_builder", "Image Builder"

    # nosemgrep: prefer-uuid7-django-pk -- TODO: migrate to uuid7 or clarify intent
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE)
    created_by = models.ForeignKey("posthog.User", on_delete=models.SET_NULL, null=True, blank=True, db_index=False)
    task_number = models.IntegerField(null=True, blank=True)
    title = models.CharField(max_length=255)
    title_manually_set = models.BooleanField(default=False)
    description = models.TextField()
    origin_product = models.CharField(max_length=20, choices=OriginProduct)

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
            "If true, the task is hidden from default list responses. Used by PostHog Code clients "
            "to share archive state across desktop and mobile."
        ),
    )
    archived_at = models.DateTimeField(null=True, blank=True)

    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    ci_prompt = models.TextField(
        blank=True,
        null=True,
        help_text="Custom prompt for CI fixes. If blank, a default prompt will be used.",
    )

    # Conversation-level state shared across the task's runs (each resume/follow-up
    # is a fresh TaskRun), e.g. which PRs have been announced to the Slack thread.
    state = models.JSONField(default=dict, null=True, blank=True)

    class Meta:
        db_table = "posthog_task"
        managed = True
        indexes = [
            models.Index(fields=["signal_report"], name="posthog_task_signal_report_idx"),
            models.Index(fields=["archived"], name="posthog_task_archived_idx"),
            models.Index(fields=["team", "-created_at", "-id"], name="posthog_task_team_created_idx"),
            models.Index(fields=["team", "created_by", "-created_at", "-id"], name="posthog_task_team_creator_idx"),
            models.Index(fields=["channel", "-created_at"], name="posthog_task_channel_feed_idx"),
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

    @classmethod
    def get_file_system_unfiled(cls, team: "Team", surface: str = DEFAULT_SURFACE) -> models.QuerySet["Task"]:
        # Tasks live only on the desktop surface, never the web app tree.
        if surface != DESKTOP_SURFACE:
            return cls.objects.none()
        base_qs = cls.objects.filter(team=team, deleted=False)
        return cls._filter_unfiled_queryset(base_qs, team, type="task", ref_field="id", surface=surface)

    def get_file_system_representation(self, folder: str | None = None) -> FileSystemRepresentation:
        # Tasks live only on the desktop surface, never the web app tree. They land in
        # Unfiled/Tasks/<title> on first save (via FileSystemSyncMixin) and stay there
        # unless filed into another folder — e.g. a canvas channel.
        return FileSystemRepresentation(
            base_folder=folder or self._get_assigned_folder("Unfiled/Tasks"),
            type="task",
            ref=str(self.id),
            name=self.title or "Untitled",
            href=f"/tasks/{self.id}",
            meta={
                "created_at": str(self.created_at),
                "created_by": self.created_by_id,
            },
            should_delete=bool(self.deleted),
            surface=DESKTOP_SURFACE,
        )

    def capture_event(self, event: str, properties: dict | None = None) -> None:
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
            }
            if properties:
                all_properties.update(properties)
            posthoganalytics.capture(
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

    def create_run(
        self,
        environment: Optional["TaskRun.Environment"] = None,
        mode: str = "background",
        extra_state: dict | None = None,
        branch: str | None = None,
    ) -> "TaskRun":
        state: dict = {"mode": mode}
        if extra_state:
            state.update({k: v for k, v in extra_state.items() if k != "mode"})
        # Pin the stream-routing decision once so every reader/writer agrees for this run's life.
        if "use_dedicated_stream" not in state:
            distinct_id = (self.created_by.distinct_id if self.created_by else None) or f"team_{self.team_id}"
            state["use_dedicated_stream"] = evaluate_dedicated_stream_flag(
                organization_id=str(self.team.organization_id),
                distinct_id=distinct_id,
            )
        is_resume = bool((extra_state or {}).get("resume_from_run_id"))
        has_pending = bool(
            (extra_state or {}).get("pending_user_message") or (extra_state or {}).get("pending_user_artifact_ids")
        )
        task_run = TaskRun.objects.create(
            task=self,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            **({"environment": environment} if environment else {}),
            state=state,
            branch=branch,
        )
        task_run.publish_stream_state_event()
        observe_task_run_created(task_run)
        self.capture_event(
            "task_run_created",
            {
                "run_id": str(task_run.id),
                "mode": mode,
                "environment": task_run.environment,
                "is_resume": is_resume,
                "has_pending_message": has_pending,
            },
        )
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

    def soft_delete(self):
        self.deleted = True
        self.deleted_at = django_timezone.now()
        self.save()
        self.capture_event(
            "task_deleted",
            {"duration_seconds": round((django_timezone.now() - self.created_at).total_seconds(), 1)},
        )

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
        repository: str | None = None,
        slack_thread_context: Optional["SlackThreadContext"] = None,
        slack_thread_url: str | None = None,
        branch: str | None = None,
        signal_report_id: str | None = None,
        ai_stage: str | None = None,
        sandbox_environment_id: str | None = None,
        internal: bool = False,
        output_schema: type[BaseModel] | dict | None = None,
        interaction_origin: str | None = None,
        runtime_adapter: str | None = None,
        model: str | None = None,
        reasoning_effort: str | None = None,
        initial_permission_mode: str | None = None,
        sandbox_resources: "SandboxResources | None" = None,
        sandbox_timeout_seconds: int | None = None,
        inactivity_timeout_seconds: int | None = None,
        wizard_config: dict | None = None,
        wizard_head_branch: str | None = None,
        pending_user_message: str | None = None,
        custom_image_builder_id: str | None = None,
        custom_image_id: str | None = None,
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

        github_integration = Integration.objects.filter(team=team, kind="github").first()
        github_user_integration = None
        task_stub = Task(
            team=team,
            origin_product=origin_product,
            created_by=created_by,
            repository=repository,
            github_integration=github_integration,
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

        task = Task.objects.create(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            created_by=created_by,
            github_integration=github_integration,
            github_user_integration=github_user_integration,
            repository=repository,
            internal=internal,
            json_schema=resolve_schema(output_schema) if output_schema else None,
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
        )
        return task

    @staticmethod
    def create_and_run(
        *,
        team: Team,
        title: str,
        description: str,
        origin_product: "Task.OriginProduct",
        user_id: int,  # Will be used to validate the tasks feature flag and create a personal api key for interacting with PostHog.
        repository: str | None = None,  # Format: "organization/repository", e.g. "posthog/posthog-js"
        create_pr: bool = True,
        mode: str = "background",
        slack_thread_context: Optional["SlackThreadContext"] = None,
        slack_thread_url: str | None = None,
        start_workflow: bool = True,
        posthog_mcp_scopes: PosthogMcpScopes = "full",
        branch: str | None = None,
        signal_report_id: str | None = None,
        sandbox_environment_id: str | None = None,
        internal: bool = False,
        output_schema: type[BaseModel] | dict | None = None,
        interaction_origin: str | None = None,
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
        pending_user_message: str | None = None,
        custom_image_builder_id: str | None = None,
        custom_image_id: str | None = None,
    ) -> "Task":
        from products.tasks.backend.temporal.client import _normalize_slack_context, execute_task_processing_workflow

        task, extra_state = Task._build_task(
            team=team,
            title=title,
            description=description,
            origin_product=origin_product,
            user_id=user_id,
            repository=repository,
            slack_thread_context=slack_thread_context,
            slack_thread_url=slack_thread_url,
            branch=branch,
            signal_report_id=signal_report_id,
            sandbox_environment_id=sandbox_environment_id,
            internal=internal,
            output_schema=output_schema,
            interaction_origin=interaction_origin,
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
            pending_user_message=pending_user_message,
            custom_image_builder_id=custom_image_builder_id,
            custom_image_id=custom_image_id,
        )

        run_extra_state = dict(extra_state or {})
        if start_workflow:
            # Persist everything the dispatch needs alongside the row, in the same INSERT, so a
            # reconciler can re-dispatch faithfully if the on_commit callback below is ever lost.
            run_extra_state["pending_dispatch"] = {
                "create_pr": create_pr,
                "posthog_mcp_scopes": posthog_mcp_scopes,
                "user_id": user_id,
                "slack_thread_context": _normalize_slack_context(slack_thread_context),
            }

        task_run = task.create_run(mode=mode, extra_state=run_extra_state or None, branch=branch)

        if start_workflow:
            # Defer the fire-and-forget workflow start until the creating transaction commits.
            # Otherwise, when create_and_run runs inside a transaction.atomic() block, the
            # workflow's first activity can read the TaskRun before its row is visible and fail.
            # on_commit runs the callback immediately in autocommit mode, so non-atomic callers
            # are unaffected. If the callback is lost (process recycled in the commit->callback
            # window, or an earlier on_commit hook raising), the run stays QUEUED — the periodic
            # reconciler re-dispatches it from the persisted pending_dispatch above.
            run_id = str(task_run.id)
            team_id = task.team.id
            task_id = str(task.id)

            observe_task_run_dispatch_callback(task_run, phase="scheduled")

            def _dispatch() -> None:
                observe_task_run_dispatch_callback(task_run, phase="fired")
                execute_task_processing_workflow(
                    task_id=task_id,
                    run_id=run_id,
                    team_id=team_id,
                    user_id=user_id,
                    create_pr=create_pr,
                    slack_thread_context=slack_thread_context,
                    posthog_mcp_scopes=posthog_mcp_scopes,
                )

            transaction.on_commit(_dispatch)

        return task


class TaskThreadMessage(TeamScopedRootMixin):
    """One human message in a task's thread — the side conversation channel members
    have around a task. Messages never reach the agent unless the task author
    forwards one (send_to_agent), which stamps the forwarded_* fields."""

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
        indexes = [models.Index(fields=["task", "created_at"], name="task_thread_msg_task_created")]

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


class TaskAutomationManager(models.Manager):
    def get_queryset(self):
        return (
            super()
            .get_queryset()
            .select_related(
                "task",
                "task__team",
                "task__created_by",
                "task__github_integration",
                "task__github_user_integration",
                "last_task_run",
                "last_task_run__task",
            )
        )


class TaskAutomationQuerySet(models.QuerySet):
    def with_task_context(self):
        return self.select_related(
            "task",
            "task__team",
            "task__created_by",
            "task__github_integration",
            "task__github_user_integration",
            "last_task_run",
            "last_task_run__task",
        )


class TaskAutomation(models.Model):
    class RunStatus(models.TextChoices):
        SUCCESS = "success", "Success"
        FAILED = "failed", "Failed"
        RUNNING = "running", "Running"

    # nosemgrep: prefer-uuid7-django-pk -- TODO: migrate to uuid7 or clarify intent
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    cron_expression = models.CharField(max_length=100)
    timezone = models.CharField(max_length=128, default="UTC")
    template_id = models.CharField(max_length=255, null=True, blank=True)
    enabled = models.BooleanField(default=True)
    task = models.OneToOneField(Task, on_delete=models.CASCADE, related_name="automation")
    last_task_run = models.ForeignKey("TaskRun", on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    last_error = models.TextField(null=True, blank=True)
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    objects = TaskAutomationManager()

    class Meta:
        db_table = "posthog_task_automation"
        ordering = ["task__title", "-created_at"]

    def __str__(self):
        return self.name

    @property
    def schedule_id(self) -> str:
        return f"task-automation-{self.id}"

    @property
    def team(self) -> Team:
        return self.task.team

    @property
    def team_id(self) -> int:
        return self.task.team_id

    @property
    def created_by(self) -> User | None:
        return self.task.created_by

    @property
    def created_by_id(self) -> int | None:
        return self.task.created_by_id

    @property
    def name(self) -> str:
        return self.task.title

    @property
    def prompt(self) -> str:
        return self.task.description

    @property
    def repository(self) -> str | None:
        return self.task.repository

    @property
    def github_integration(self) -> Integration | None:
        return self.task.github_integration

    @property
    def github_integration_id(self) -> int | None:
        return self.task.github_integration_id

    @property
    def last_run_at(self) -> datetime | None:
        return self.last_task_run.created_at if self.last_task_run else None

    @property
    def last_run_status(self) -> str | None:
        if self.last_task_run is None:
            return None
        if self.last_task_run.status == TaskRun.Status.COMPLETED:
            return self.RunStatus.SUCCESS
        if self.last_task_run.status in [TaskRun.Status.FAILED, TaskRun.Status.CANCELLED]:
            return self.RunStatus.FAILED
        return self.RunStatus.RUNNING


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

    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "posthog_task_run"
        ordering = ["-created_at"]
        indexes = [
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
        self.completed_at = None
        self.error_message = None

        state = self.state or {}
        prior_snapshot_external_id = state.get("snapshot_external_id")
        prior_snapshot_kind = state.get("snapshot_kind")
        prior_snapshot_mount_path = state.get("snapshot_mount_path")
        state["handoff_resumed"] = True
        state["mode"] = "interactive"
        state.pop("pending_user_message", None)
        state.pop("pending_user_message_ts", None)
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
            if updates:
                state.update(updates)

        return cls.mutate_state_atomic(run_id, _mutator)

    @staticmethod
    def get_workflow_id(task_id: str | uuid.UUID, run_id: str | uuid.UUID) -> str:
        """Get the Temporal workflow ID for a task run."""
        return f"task-processing-{task_id}-{run_id}"

    @property
    def workflow_id(self) -> str:
        """Get the Temporal workflow ID for this task run."""
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

        existing_content = object_storage.read(self.log_url, missing_ok=True) or ""
        is_new_file = not existing_content

        new_lines = "\n".join(json.dumps(entry) for entry in entries)
        content = existing_content + ("\n" if existing_content else "") + new_lines

        object_storage.write(self.log_url, content)

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

    def capture_event(self, event: str, properties: dict | None = None, event_uuid: str | None = None) -> None:
        try:
            distinct_id = (
                str(self.task.created_by.distinct_id)
                if self.task.created_by_id and self.task.created_by
                else str(self.team.uuid)
            )
            all_properties: dict = {
                "task_id": str(self.task_id),
                "run_id": str(self.id),
                "team_id": self.team_id,
                "repository": self.task.repository,
                "origin_product": self.task.origin_product,
                "title": self.task.title,
                "signal_report_id": str(self.task.signal_report_id) if self.task.signal_report_id else None,
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
    def is_terminal(self) -> bool:
        return self.status in {self.Status.COMPLETED, self.Status.FAILED, self.Status.CANCELLED}

    def delete(self, *args, **kwargs):
        raise Exception("Cannot delete TaskRun. Task runs are immutable records.")


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


class CodeInvite(UUIDModel):
    """Invite codes for PostHog Code access."""

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
    """Tracks each redemption of a PostHog Code invite."""

    invite_code = models.ForeignKey(CodeInvite, on_delete=models.CASCADE, related_name="redemptions")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE)
    organization = models.ForeignKey("posthog.Organization", on_delete=models.SET_NULL, null=True, blank=True)
    redeemed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "posthog_code_invite_redemption"
        unique_together = [("invite_code", "user")]

    def __str__(self):
        return f"{self.user} redeemed {self.invite_code}"


# How long a single beacon keeps a device "present" before the row is treated as stale.
# Clients beacon every ~30s; expiring after 60s gives them one missed POST of slack.
TASK_PRESENCE_TTL_SECONDS = 60


class TaskPresence(TeamScopedRootMixin):
    """Per-device 'this user is actively watching this task' beacon.

    Created/refreshed by the desktop and mobile PostHog Code clients while a
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


class CodeWorkflowConfig(TeamScopedRootMixin):
    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+")
    version = models.PositiveIntegerField(default=1)
    bindings = models.JSONField(default=dict, help_text="Situation id → ordered WorkflowAction list")
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_code_workflow_config"
        constraints = [
            models.UniqueConstraint(fields=["team", "user"], name="code_workflow_config_team_user_unique"),
        ]

    def __str__(self):
        return f"CodeWorkflowConfig(team={self.team_id}, user={self.user_id}, v{self.version})"


class CodePrSnapshot(TeamScopedRootMixin):
    class State(models.TextChoices):
        OPEN = "open", "Open"
        DRAFT = "draft", "Draft"
        MERGED = "merged", "Merged"
        CLOSED = "closed", "Closed"

    class CiStatus(models.TextChoices):
        PASSING = "passing", "Passing"
        FAILING = "failing", "Failing"
        PENDING = "pending", "Pending"
        NONE = "none", "None"

    class ReviewDecision(models.TextChoices):
        APPROVED = "approved", "Approved"
        CHANGES_REQUESTED = "changes_requested", "Changes requested"
        REVIEW_REQUIRED = "review_required", "Review required"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    github_integration = models.ForeignKey(
        "posthog.Integration", on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    pr_url = models.CharField(max_length=500)
    number = models.PositiveIntegerField()
    title = models.TextField(blank=True, default="")
    state = models.CharField(max_length=10, choices=State.choices)
    ci_status = models.CharField(max_length=10, choices=CiStatus.choices, default=CiStatus.NONE)
    review_decision = models.CharField(max_length=20, choices=ReviewDecision.choices, null=True, blank=True)
    unresolved_threads = models.PositiveIntegerField(default=0)
    mergeable = models.BooleanField(null=True, blank=True)
    author_login = models.CharField(max_length=255, null=True, blank=True)
    head_branch = models.CharField(
        max_length=255,
        null=True,
        blank=True,
        help_text="PR head (source) branch, used to group follow-up task runs under this PR's workstream",
    )
    requested_reviewer_logins = models.JSONField(default=list, help_text="GitHub logins requested as reviewers")
    pr_updated_at = models.DateTimeField(null=True, blank=True, help_text="PR's last-updated time on GitHub")
    fingerprint = models.CharField(max_length=64, blank=True, default="", help_text="Change-detection hash")
    fetched_at = models.DateTimeField(default=django_timezone.now, help_text="When this snapshot was last polled")
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_code_pr_snapshot"
        constraints = [
            models.UniqueConstraint(fields=["team", "pr_url"], name="code_pr_snapshot_team_url_unique"),
        ]

    def __str__(self):
        return f"CodePrSnapshot({self.pr_url} {self.state})"


class CodeWorkstream(TeamScopedRootMixin):
    class WorkstreamState(models.TextChoices):
        ATTENTION = "attention", "Needs attention"
        IN_PROGRESS = "in_progress", "In progress"

    # nosemgrep: prefer-uuid7-django-pk -- mirrors sibling task models in this app
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    team = models.ForeignKey("posthog.Team", on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey("posthog.User", on_delete=models.CASCADE, related_name="+")
    key = models.CharField(max_length=600, help_text="Grouping key: pr:<url> | branch:<repo>#<branch> | path:<path>")
    repo_name = models.CharField(max_length=255, null=True, blank=True)
    repo_full_path = models.CharField(max_length=512, null=True, blank=True)
    branch = models.CharField(max_length=255, null=True, blank=True)
    pr_url = models.CharField(max_length=500, null=True, blank=True)
    pr_snapshot = models.ForeignKey(CodePrSnapshot, on_delete=models.SET_NULL, null=True, blank=True, related_name="+")
    pr = models.JSONField(null=True, blank=True, help_text="Per-user-resolved PrSnapshot wire shape")
    situations = models.JSONField(default=list, help_text="List of situation ids this workstream is in")
    primary_situation = models.CharField(max_length=20, null=True, blank=True, help_text="Board column placement")
    state = models.CharField(max_length=20, choices=WorkstreamState.choices)
    tasks = models.JSONField(default=list, help_text="List of {id, title, status} for grouped tasks")
    last_activity_at = models.DateTimeField()
    generated_at = models.DateTimeField(default=django_timezone.now, help_text="When this row was last rebuilt")
    created_at = models.DateTimeField(default=django_timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = "posthog_code_workstream"
        ordering = ["-last_activity_at"]
        constraints = [
            models.UniqueConstraint(fields=["team", "user", "key"], name="code_workstream_team_user_key_unique"),
        ]
        indexes = [
            models.Index(fields=["team", "user", "state"], name="code_workstream_state_idx"),
        ]

    def __str__(self):
        return f"CodeWorkstream({self.key} {self.state})"


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
