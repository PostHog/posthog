from __future__ import annotations

import json
import secrets
import threading
from collections.abc import Callable
from datetime import timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import uuid4

from pydantic import JsonValue

from .faults import Fault, FaultName
from .replay import Replay, ResponseStep

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.harness.temporal_env import TemporalWorkerThread


class Attempt:
    def __init__(self, provider: str, output: Path) -> None:
        if provider not in {"claude", "codex"}:
            raise ValueError("Unknown runtime")
        self.id = uuid4().hex
        self.emails = (f"ai-e2e-{self.id}@example.com", f"ai-e2e-connected-{self.id}@example.com")
        self.provider = provider
        self.model = "claude-sonnet-4-6" if provider == "claude" else "gpt-5.5"
        self.output = output / self.id
        self.output.mkdir(parents=True)
        self.timeline: list[dict[str, JsonValue]] = []
        names: tuple[FaultName, ...] = ("registration", "worker", "approval")
        self.faults = {name: Fault(name, self.timeline) for name in names}
        self.errors: list[str] = []
        self.replay: Replay | None = None
        self.task_id: str | None = None
        self.run_id: str | None = None
        self.workflow_id: str | None = None
        self.run_created = threading.Event()
        self.workflow_registered = threading.Event()
        self.signal_not_found = threading.Event()
        self.signal_accepted = threading.Event()
        self.worker_ready = threading.Event()
        self.threads: list[threading.Thread] = []
        self.cleanup_callbacks: list[Callable[[], None]] = []
        self.worker: TemporalWorkerThread | None = None
        self.title_requests = 0
        self.sdk_titles: list[str] = []
        self.tool_executions = 0

    def seed(self) -> None:
        from django.db import transaction
        from django.utils import timezone

        from posthog.models import (
            Integration,
            OAuthAccessToken,
            OAuthApplication,
            Organization,
            OrganizationMembership,
            Team,
            User,
        )
        from posthog.models.utils import generate_random_oauth_access_token
        from posthog.temporal.oauth import POSTHOG_AI_APP_CLIENT_ID_DEV

        from products.product_analytics.backend.models.insight import Insight
        from products.tasks.backend.models import UserTasksConfig

        with transaction.atomic():
            self.organization = Organization.objects.create(
                name=f"AI E2E {self.id}", is_ai_data_processing_approved=True
            )
            self.password = secrets.token_urlsafe(24)
            self.user = User.objects.create_and_join(
                self.organization,
                self.emails[0],
                self.password,
                "Synthetic tester",
                OrganizationMembership.Level.OWNER,
            )
            self.team = Team.objects.create(
                organization=self.organization, name="Synthetic workspace", completed_snippet_onboarding=True
            )
            self.user.current_organization = self.organization
            self.user.current_team = self.team
            self.user.is_email_verified = True
            self.user.credentials_reviewed_at = timezone.now()
            self.user.save()
            UserTasksConfig.objects.for_team(self.team.id).create(
                team_id=self.team.id,
                user=self.user,
                ai_run_preferences={
                    "runtime_adapter": self.provider,
                    "model": self.model,
                    "reasoning_effort": "medium",
                },
            )
            application, _ = OAuthApplication.objects.get_or_create(
                client_id=POSTHOG_AI_APP_CLIENT_ID_DEV,
                defaults={
                    "name": "Synthetic AI E2E agent",
                    "client_type": OAuthApplication.CLIENT_PUBLIC,
                    "authorization_grant_type": OAuthApplication.GRANT_AUTHORIZATION_CODE,
                    "algorithm": "RS256",
                    "redirect_uris": "https://example.com/callback",
                    "organization": self.organization,
                    "user": self.user,
                },
            )
            self.connected_team = Team.objects.create(
                organization=self.organization, name="Synthetic connected project", completed_snippet_onboarding=True
            )
            self.connected_user = User.objects.create_and_join(
                self.organization,
                self.emails[1],
                secrets.token_urlsafe(24),
                "Synthetic connection owner",
                OrganizationMembership.Level.OWNER,
            )
            self.connected_user.current_organization = self.organization
            self.connected_user.current_team = self.connected_team
            self.connected_user.is_email_verified = True
            self.connected_user.credentials_reviewed_at = timezone.now()
            self.connected_user.save()
            scopes = ["user:read", "project:read", "organization:read", "insight:read", "insight:write"]
            token = generate_random_oauth_access_token(None)
            OAuthAccessToken.objects.create(
                token=token,
                application=application,
                user=self.connected_user,
                expires=timezone.now() + timedelta(hours=1),
                scope=" ".join(scopes),
                scoped_teams=[self.connected_team.id],
                scoped_organizations=[str(self.organization.id)],
            )
            self.connection = Integration.objects.create(
                team=self.team,
                created_by=self.user,
                kind="posthog",
                config={"region": "DEV", "granted_scopes": scopes},
                sensitive_config={"access_token": token},
            )
            self.insight = Insight.objects.create(
                team=self.connected_team, created_by=self.connected_user, name="Synthetic original insight"
            )

    def public(self) -> dict[str, JsonValue]:
        return {
            "id": self.id,
            "provider": self.provider,
            "model": self.model,
            "team_id": self.team.id,
            "email": self.user.email,
            "password": self.password,
            "insight_id": self.insight.id,
            "connection_id": str(self.connection.id),
            "resource_team_id": self.connected_team.id,
            "task_id": self.task_id,
            "run_id": self.run_id,
        }

    def configure(self, steps: list[ResponseStep]) -> None:
        if self.replay is not None or self.task_id is not None:
            raise ValueError("Attempt already configured")
        self.replay = Replay(steps)

    def background(self, fn: Callable[[], None]) -> None:
        def run() -> None:
            from django.db import connections

            try:
                fn()
            except Exception as error:
                self.errors.append(f"{type(error).__name__}: {error}")
            finally:
                connections.close_all()

        thread = threading.Thread(target=run, daemon=True)
        self.threads.append(thread)
        thread.start()

    def start(self) -> None:
        if self.replay is None:
            raise ValueError("Configure responses before starting")

        def start_worker() -> None:
            from products.posthog_ai.eval_harness.harness.temporal_env import TemporalWorkerThread

            fault = self.faults["worker"]
            if generation := fault.reach():
                fault.wait_for_release(generation)
            self.worker = TemporalWorkerThread(max_concurrent_workflow_tasks=2, max_concurrent_activities=4)
            self.worker.start()
            self.worker_ready.set()

        def start_run() -> None:
            from products.tasks.backend.facade.api import create_task
            from products.tasks.backend.facade.warm import warm_task_run

            task = create_task(
                self.team.id,
                self.user.id,
                validated_data={
                    "title": "",
                    "description": f"Synthetic conversation {self.id}",
                    "origin_product": "posthog_ai",
                },
            )
            self.task_id = str(task.id)
            warm_task_run(
                task.id,
                self.team.id,
                self.user.id,
                extra_state={
                    "runtime_adapter": self.provider,
                    "model": self.model,
                    "reasoning_effort": "medium",
                    "initial_permission_mode": "auto",
                },
            )

        self.background(start_worker)
        self.background(start_run)
        if not self.run_created.wait(60):
            raise TimeoutError(f"Run was not created: {self.errors}")

    def snapshot(self) -> dict[str, JsonValue]:
        return {
            "id": self.id,
            "team_id": self.team.id,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "timeline": self.timeline,
            "errors": self.errors,
            "consumed": self.replay.consumed if self.replay else [],
            "replay_errors": self.replay.errors if self.replay else [],
            "title_requests": self.title_requests,
            "sdk_titles": self.sdk_titles,
            "tool_executions": self.tool_executions,
        }

    def verify(self) -> None:
        if self.errors:
            raise AssertionError(self.errors)
        if self.title_requests != 1:
            raise AssertionError(f"Expected one Django title request, got {self.title_requests}")
        if self.replay is None:
            raise AssertionError("No response sequence")
        self.replay.verify()
        for fault in self.faults.values():
            fault.verify()

    def capture(self) -> None:
        import subprocess

        from products.tasks.backend.models import TaskRun

        (self.output / "timeline.json").write_text(json.dumps(self.snapshot(), indent=2))
        if self.task_id:
            containers = subprocess.run(
                ["docker", "ps", "-aq", "--filter", f"name=task-sandbox-{self.task_id}-"],
                capture_output=True,
                text=True,
                check=True,
            )
            for container in containers.stdout.split():
                logs = subprocess.run(["docker", "logs", container], capture_output=True, text=True)
                (self.output / f"agent-{container}.log").write_text(logs.stdout + logs.stderr)
                server_log = subprocess.run(
                    ["docker", "exec", container, "cat", "/tmp/agent-server.log"], capture_output=True, text=True
                )
                (self.output / f"agent-server-{container}.log").write_text(server_log.stdout + server_log.stderr)
                subprocess.run(
                    [
                        "docker",
                        "cp",
                        f"{container}:/root/.claude/debug",
                        str(self.output / f"claude-debug-{container}"),
                    ],
                    capture_output=True,
                )
            for run in TaskRun.objects.filter(task_id=self.task_id, team_id=self.team.id):
                from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
                from products.tasks.backend.redis import get_tasks_stream_redis_sync

                entries = get_tasks_stream_redis_sync(False).xrange(get_task_run_stream_key(str(run.id)))
                (self.output / f"redis-{run.id}.json").write_text(
                    json.dumps([(key.decode(), json.loads(value[b"data"])) for key, value in entries], indent=2)
                )
                (self.output / f"run-{run.id}.json").write_text(
                    json.dumps({"status": run.status, "error": run.error_message})
                )
                from products.tasks.backend.facade.api import read_task_run_logs

                (self.output / f"stream-{run.id}.jsonl").write_text(
                    read_task_run_logs(str(run.id), self.task_id, self.team.id) or ""
                )

    def cleanup(self) -> None:

        from asgiref.sync import async_to_sync
        from temporalio.service import RPCError, RPCStatusCode

        from posthog.session.models import Session
        from posthog.storage import object_storage
        from posthog.temporal.common.client import async_connect

        from products.posthog_ai.eval_harness.harness.providers import cleanup_case_containers
        from products.tasks.backend.logic.stream.redis_stream import get_task_run_stream_key
        from products.tasks.backend.models import TaskRun
        from products.tasks.backend.redis import get_tasks_stream_redis_sync

        for fault in self.faults.values():
            fault.release()
        for thread in self.threads:
            thread.join(timeout=95)
            if thread.is_alive():
                raise RuntimeError("Attempt thread survived barrier release")
        if self.run_id:
            run = TaskRun.objects.filter(id=self.run_id, team_id=self.team.id).first()
            if run and not run.is_terminal:
                run.mark_failed("AI E2E attempt cleanup")
        if self.workflow_id:
            workflow_id = self.workflow_id

            async def terminate() -> None:
                client = await async_connect()
                try:
                    await client.get_workflow_handle(workflow_id).terminate(reason="AI E2E attempt cleanup")
                except RPCError as error:
                    if error.status != RPCStatusCode.NOT_FOUND:
                        raise

            async_to_sync(terminate)()
        if self.worker:
            self.worker.stop()
        if self.task_id:
            cleanup_case_containers(self.task_id)
        for callback in reversed(self.cleanup_callbacks):
            callback()
        for run in TaskRun.objects.filter(task_id__in=[self.task_id] if self.task_id else [], team_id=self.team.id):
            for prefix in (run.get_task_s3_prefix() + "/", run.get_artifact_s3_prefix() + "/"):
                keys = object_storage.list_objects(prefix) or []
                if keys:
                    object_storage.delete_objects(keys)
            redis = get_tasks_stream_redis_sync()
            stream_key = get_task_run_stream_key(str(run.id))
            keys = [stream_key, *redis.scan_iter(match=f"{stream_key}:*")]
            redis.delete(*keys)
        self.organization.delete()
        Session.objects.filter(user_id=self.user.id).delete()
        self.user.delete()
        self.connected_user.delete()
