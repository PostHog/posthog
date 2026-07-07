import json
import time
import uuid
import base64
import asyncio
from collections.abc import AsyncGenerator, Iterator
from datetime import timedelta
from typing import Any, ClassVar, cast
from urllib.parse import quote

from unittest.mock import ANY, AsyncMock, MagicMock, patch

from django.conf import settings
from django.db import connection
from django.http import StreamingHttpResponse
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.utils import timezone as django_timezone

import jwt
import requests
from parameterized import parameterized
from rest_framework import status
from rest_framework.test import APIClient

from posthog.models import Integration, Organization, OrganizationMembership, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.user_integration import UserIntegration
from posthog.models.utils import generate_random_token_personal
from posthog.storage import object_storage

from products.tasks.backend.facade import api as tasks_facade
from products.tasks.backend.logic.services.code_usage_gate import (
    CodeUsageStatus,
    _gateway_usage_url,
    get_posthog_code_usage,
)
from products.tasks.backend.logic.services.connection_token import (
    get_sandbox_jwt_public_key,
    reset_sandbox_jwt_key_cache,
)
from products.tasks.backend.logic.services.staged_artifacts import (
    RUN_ARTIFACT_TTL_DAYS,
    build_task_artifact_entry,
    cache_task_staged_artifact,
    get_task_staged_artifacts,
)
from products.tasks.backend.logic.stream.redis_stream import (
    TaskRunRedisStream,
    TaskRunStreamEntryOrKeepalive,
    get_task_run_stream_key,
)
from products.tasks.backend.models import (
    CodeInvite,
    CodeInviteRedemption,
    SandboxEnvironment,
    Task,
    TaskAutomation,
    TaskRun,
)
from products.tasks.backend.presentation.serializers import (
    TASK_RUN_ARTIFACT_MAX_SIZE_BYTES,
    TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES,
)
from products.tasks.backend.temporal.process_task.utils import get_cached_github_user_token


def _grant_user_github_access(user: User, *, refresh_ttl_seconds: int = 15897600) -> UserIntegration:
    now = int(time.time())
    return UserIntegration.objects.create(
        user=user,
        kind="github",
        integration_id="12345",
        config={
            "installation_id": "12345",
            "expires_in": 3600,
            "refreshed_at": now,
            "repository_selection": "selected",
            "account": {"type": "User", "name": "octocat"},
            "github_user": {"login": "octocat", "id": 99},
            "user_token_refreshed_at": now,
            "user_access_token_expires_at": now + 28800,
            "user_refresh_token_expires_at": now + refresh_ttl_seconds,
        },
        sensitive_config={
            "access_token": "ghs_install",
            "user_access_token": "gho_access",
            "user_refresh_token": "ghr_refresh",
        },
    )


# Test RSA private key for JWT tests (RS256)
TEST_RSA_PRIVATE_KEY = """-----BEGIN PRIVATE KEY-----
MIIEvQIBADANBgkqhkiG9w0BAQEFAASCBKcwggSjAgEAAoIBAQDqh94SYMFsvG4C
Co9BSGjtPr2/OxzuNGr41O4+AMkDQRd9pKO49DhTA4VzwnOvrH8y4eI9N8OQne7B
wpdoouSn4DoDAS/b3SUfij/RoFUSyZiTQoWz0H6o2Vuufiz0Hf+BzlZEVnhSQ1ru
vqSf+4l8cWgeMXaFXgdD5kQ8GjvR5uqKxvO2Env1hMJRKeOOEGgCep/0c6SkMUTX
SeC+VjypVg9+8yPxtIpOQ7XKv+7e/PA0ilqehRQh4fo9BAWjUW1+HnbtsjJAjjfv
ngzIjpajuQVyMi7G79v8OvijhLMJjJBh3TdbVIfi+RkVj/H94UUfKWRfJA0eLykA
VvTiFf0nAgMBAAECggEABkLBQWFW2IXBNAm/IEGEF408uH2l/I/mqSTaBUq1EwKq
U17RRg8y77hg2CHBP9fNf3i7NuIltNcaeA6vRwpOK1MXiVv/QJHLO2fP41Mx4jIC
gi/c7NtsfiprQaG5pnykhP0SnXlndd65bzUkpOasmWdXnbK5VL8ZV40uliInJafE
1Eo9qSYCJxHmivU/4AbiBgygOAo1QIiuuUHcx0YGknLrBaMQETuvWJGE3lxVQ30/
EuRyA3r6BwN2T0z47PZBzvCpg/C1KeoYuKSMwMyEXfl+a8NclqdROkVaenmZpvVH
0lAvFDuPrBSDmU4XJbKCEfwfHjRkiWAFaTrKntGQtQKBgQD/ILoK4U9DkJoKTYvY
9lX7dg6wNO8jGLHNufU8tHhU+QnBMH3hBXrAtIKQ1sGs+D5rq/O7o0Balmct9vwb
CQZ1EpPfa83Thsv6Skd7lWK0JF7g2vVk8kT4nY/eqkgZUWgkfdMp+OMg2drYiIE8
u+sRPTCdq4Tv5miRg0OToX2H/QKBgQDrVR2GXm6ZUyFbCy8A0kttXP1YyXqDVq7p
L4kqyUq43hmbjzIRM4YDN3EvgZvVf6eub6L/3HfKvWD/OvEhHovTvHb9jkwZ3FO+
YQllB/ccAWJs/Dw5jLAsX9O+eIe4lfwROib3vYLnDTAmrXD5VL35R5F0MsdRoxk5
lTCq1sYI8wKBgGA9ZjDIgXAJUjJkwkZb1l9/T1clALiKjjf+2AXIRkQ3lXhs5G9H
8+BRt5cPjAvFsTZIrS6xDIufhNiP/NXt96OeGG4FaqVKihOmhYSW+57cwXWs4zjr
Mx1dwnHKZlw2m0R4unlwy60OwUFBbQ8ODER6gqZXl1Qv5G5Px+Qe3Q25AoGAUl+s
wgfz9r9egZvcjBEQTeuq0pVTyP1ipET7YnqrKSK1G/p3sAW09xNFDzfy8DyK2UhC
agUl+VVoym47UTh8AVWK4R4aDUNOHOmifDbZjHf/l96CxjI0yJOSbq2J9FarsOwG
D9nKJE49eIxlayD6jnM6us27bxwEDF/odSRQlXkCgYEAxn9l/5kewWkeEA0Afe1c
Uf+mepHBLw1Pbg5GJYIZPC6e5+wRNvtFjM5J6h5LVhyb7AjKeLBTeohoBKEfUyUO
rl/ql9qDIh5lJFn3uNh7+r7tmG21Zl2pyh+O8GljjZ25mYhdiwl0uqzVZaINe2Wa
vbMnD1ZQKgL8LHgb02cbTsc=
-----END PRIVATE KEY-----"""


class BaseTaskAPITest(TestCase):
    organization: ClassVar[Organization]
    team: ClassVar[Team]
    user: ClassVar[User]
    feature_flag_patcher: MagicMock
    mock_feature_flag: MagicMock
    client: APIClient

    @classmethod
    def setUpTestData(cls):
        cls.organization = Organization.objects.create(name="Test Org")
        cls.team = Team.objects.create(organization=cls.organization, name="Test Team")
        cls.user = User.objects.create_user(email="test@example.com", first_name="Test", password="password")
        cls.organization.members.add(cls.user)
        OrganizationMembership.objects.filter(user=cls.user, organization=cls.organization).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def setUp(self):
        self.client = APIClient()
        self.client.force_authenticate(self.user)

        # Enable tasks feature flag by default
        self.set_tasks_feature_flag(True)

    def tearDown(self):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()
        super().tearDown()

    def set_tasks_feature_flag(self, enabled=True):
        if hasattr(self, "feature_flag_patcher"):
            self.feature_flag_patcher.stop()

        self.feature_flag_patcher = patch("posthoganalytics.feature_enabled")  # type: ignore[assignment]
        self.mock_feature_flag = self.feature_flag_patcher.start()

        def check_flag(flag_name, *_args, **_kwargs):
            if flag_name == "tasks":
                return enabled
            return False

        self.mock_feature_flag.side_effect = check_flag

    def create_task(self, title="Test Task", created_by: User | None = None):
        return Task.objects.create(
            team=self.team,
            created_by=created_by or self.user,
            title=title,
            description="Test Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def create_organization_user(self, email_prefix: str = "other") -> User:
        user = User.objects.create_user(
            email=f"{email_prefix}-{uuid.uuid4()}@example.com",
            first_name="Other",
            password="password",
        )
        self.organization.members.add(user)
        return user

    def create_automation(
        self,
        name="Daily PRs",
        prompt="Check my GitHub PRs",
        repository="posthog/posthog",
        team=None,
        user=None,
    ):
        task = Task.objects.create(
            team=team or self.team,
            created_by=user or self.user,
            title=name,
            description=prompt,
            origin_product=Task.OriginProduct.AUTOMATION,
            repository=repository,
        )
        return TaskAutomation.objects.create(
            task=task,
            cron_expression="0 9 * * *",
            timezone="Europe/London",
            enabled=True,
        )


class TestTaskCreatorScoping(BaseTaskAPITest):
    def _create_legacy_task(self, title: str = "Legacy") -> Task:
        return Task.objects.create(
            team=self.team,
            created_by=None,
            title=title,
            description="Legacy unowned",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

    def test_list_excludes_other_user_tasks_but_includes_legacy_unowned(self):
        other_user = self.create_organization_user("victim")
        self.create_task("Mine", created_by=self.user)
        self.create_task("Theirs", created_by=other_user)
        self._create_legacy_task("Legacy")

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        titles = sorted(task["title"] for task in response.json()["results"])
        self.assertEqual(titles, ["Legacy", "Mine"])

    def test_retrieve_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_legacy_unowned_task_is_visible(self):
        task = self._create_legacy_task()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_retrieve_signal_report_task_owned_by_another_user_is_visible(self):
        # Signals-generated tasks are team-scoped artifacts; the pipeline picks
        # a system user as `created_by` purely to mint an OAuth token. Any team
        # member must be able to retrieve them by ID.
        other_user = self.create_organization_user("signal-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signal Report Task",
            description="Generated by signals",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            internal=True,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(task.id))

    def test_list_signal_report_tasks_hidden_by_default(self):
        # Signal-report tasks are always created with internal=True, so the
        # default list still hides them. The retrieve-by-ID path (and the
        # `?internal=true` / `?internal=all` filters) is how they're surfaced.
        other_user = self.create_organization_user("signal-owner")
        signal_task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signal Report Task",
            description="Generated by signals",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            internal=True,
        )
        mine = self.create_task("Mine", created_by=self.user)

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(mine.id), ids)
        self.assertNotIn(str(signal_task.id), ids)

    def test_list_signals_scout_tasks_owned_by_another_user(self):
        # Signals scout task runs are team-scoped, but created under the user
        # resolved from the team's GitHub integration so the sandbox can mint
        # OAuth tokens. They should still show in the shared Tasks list.
        other_user = self.create_organization_user("scout-owner")
        scout_task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signals Scout Task",
            description="Generated by Signals scout",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        mine = self.create_task("Mine", created_by=self.user)

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(mine.id), ids)
        self.assertIn(str(scout_task.id), ids)

    def test_list_onboarding_tasks_owned_by_another_user(self):
        # Onboarding tasks are the shared getting-started task: team-scoped, so they show
        # in everyone's Tasks list regardless of which user the task was created under.
        other_user = self.create_organization_user("onboarding-owner")
        onboarding_task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Onboarding Task",
            description="Getting started",
            origin_product=Task.OriginProduct.ONBOARDING,
        )
        mine = self.create_task("Mine", created_by=self.user)

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {t["id"] for t in response.json()["results"]}
        self.assertIn(str(mine.id), ids)
        self.assertIn(str(onboarding_task.id), ids)

    def test_retrieve_signals_scout_task_owned_by_another_user_is_visible(self):
        other_user = self.create_organization_user("scout-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signals Scout Task",
            description="Generated by Signals scout",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(task.id))

    def test_retrieve_hogdesk_task_owned_by_another_user_is_visible(self):
        # HogDesk Code threads are pinned to a support ticket via a shared ticket
        # tag; any agent opening the ticket must be able to load the same task.
        other_user = self.create_organization_user("hogdesk-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="HogDesk Task",
            description="Started from a support ticket",
            origin_product=Task.OriginProduct.HOGDESK,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(task.id))

    def test_list_runs_hogdesk_task_owned_by_another_user_succeeds(self):
        other_user = self.create_organization_user("hogdesk-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="HogDesk Task",
            description="Started from a support ticket",
            origin_product=Task.OriginProduct.HOGDESK,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in response.json()["results"]}
        self.assertEqual(ids, {str(run.id)})

    def test_retrieve_other_user_non_signal_internal_task_returns_404(self):
        # Non-signal internal tasks created by another user remain private.
        other_user = self.create_organization_user("victim")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Their internal",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=True,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_runs_signal_report_task_owned_by_another_user_succeeds(self):
        other_user = self.create_organization_user("signal-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signal Report Task",
            description="Generated by signals",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            internal=True,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in response.json()["results"]}
        self.assertEqual(ids, {str(run.id)})

    def test_list_runs_signals_scout_task_owned_by_another_user_succeeds(self):
        other_user = self.create_organization_user("scout-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signals Scout Task",
            description="Generated by Signals scout",
            origin_product=Task.OriginProduct.SIGNALS_SCOUT,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {r["id"] for r in response.json()["results"]}
        self.assertEqual(ids, {str(run.id)})

    def test_retrieve_run_signal_report_task_owned_by_another_user_succeeds(self):
        other_user = self.create_organization_user("signal-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signal Report Task",
            description="Generated by signals",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            internal=True,
        )
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(run.id))

    def test_retrieve_signal_report_automation_owned_by_another_user_succeeds(self):
        # TaskAutomationViewSet filters with task_run_visibility_q (task FK traversal).
        other_user = self.create_organization_user("signal-owner")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Signal Report Task",
            description="Generated by signals",
            origin_product=Task.OriginProduct.SIGNAL_REPORT,
            internal=True,
        )
        automation = TaskAutomation.objects.create(
            task=task,
            cron_expression="0 9 * * *",
            timezone="Europe/London",
            enabled=True,
        )

        response = self.client.get(f"/api/projects/@current/task_automations/{automation.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(automation.id))

    def test_retrieve_other_user_internal_non_signal_automation_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Their internal",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=True,
        )
        automation = TaskAutomation.objects.create(
            task=task,
            cron_expression="0 9 * * *",
            timezone="Europe/London",
            enabled=True,
        )

        response = self.client.get(f"/api/projects/@current/task_automations/{automation.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_repositories_excludes_other_user_repos(self):
        other_user = self.create_organization_user("victim")
        mine = self.create_task("Mine", created_by=self.user)
        mine.repository = "me/repo"
        mine.save(update_fields=["repository"])
        theirs = self.create_task("Theirs", created_by=other_user)
        theirs.repository = "victim/secret"
        theirs.save(update_fields=["repository"])

        response = self.client.get("/api/projects/@current/tasks/repositories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repositories"], ["me/repo"])

    def test_summaries_excludes_other_user_tasks(self):
        other_user = self.create_organization_user("victim")
        mine = self.create_task("Mine", created_by=self.user)
        theirs = self.create_task("Theirs", created_by=other_user)

        response = self.client.post(
            "/api/projects/@current/tasks/summaries/",
            {"ids": [str(mine.id), str(theirs.id)]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = sorted(item["id"] for item in response.json()["results"])
        self.assertEqual(ids, [str(mine.id)])

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_other_user_task_returns_404(self, mock_workflow):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(TaskRun.objects.filter(task=task).exists())
        mock_workflow.assert_not_called()

    def test_update_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user, title="Original")

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"title": "Hijacked"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        task.refresh_from_db()
        self.assertEqual(task.title, "Original")

    def test_delete_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        task.refresh_from_db()
        self.assertFalse(task.deleted)

    def test_staged_artifacts_prepare_upload_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/prepare_upload/",
            {"artifacts": [{"name": "x.txt", "type": "user_attachment", "size": 1}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_runs_for_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_run_for_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {"environment": "cloud"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)
        self.assertFalse(TaskRun.objects.filter(task=task).exists())

    def test_command_on_other_user_run_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/command/",
            {"jsonrpc": "2.0", "method": "user_message", "params": {"content": "leak secrets"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_set_output_on_other_user_run_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/",
            {"output": {"pr_url": "https://example.com/hijack"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_connection_token_on_other_user_run_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=other_user)
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_run_automation_for_other_user_task_returns_404(self):
        other_user = self.create_organization_user("victim")
        task = Task.objects.create(
            team=self.team,
            created_by=other_user,
            title="Their automation task",
            description="prompt",
            origin_product=Task.OriginProduct.AUTOMATION,
            repository="victim/repo",
        )
        automation = TaskAutomation.objects.create(
            task=task,
            cron_expression="0 9 * * *",
            timezone="Europe/London",
            enabled=True,
        )

        response = self.client.post(f"/api/projects/@current/task_automations/{automation.id}/run/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


@override_settings(CLOUD_DEPLOYMENT="US")
class TestTaskVisibilityInternalDebugTeamBypass(BaseTaskAPITest):
    """When the gate (`_is_internal_debug_team`) fires, PostHog employees can
    read any teammate's task/run by ID — but the bypass is deliberately narrow:
    only the `retrieve` action on TaskViewSet and read-only actions on
    TaskRunViewSet. List views, write actions, and other teams remain
    creator-scoped. The unaffected cases live in `TestTaskCreatorScoping`
    above; the deployment-region requirement is covered by
    `TestTaskVisibilityInternalDebugRegionGate`."""

    def setUp(self):
        super().setUp()
        # Production checks `team_id == 2 AND CLOUD_DEPLOYMENT == "US"`; tests
        # can't easily force the row id, so substitute the test team's id and
        # keep the deployment-region clause intact so off-US tests still flip.
        self._bypass_patch = patch(
            "products.tasks.backend.presentation.views.api._is_internal_debug_team",
            side_effect=lambda team_id: team_id == self.team.id and settings.CLOUD_DEPLOYMENT == "US",
        )
        self._bypass_patch.start()

    def tearDown(self):
        self._bypass_patch.stop()
        super().tearDown()

    def test_retrieve_other_user_task_succeeds(self):
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(task.id))

    def test_retrieve_other_user_task_without_ph_debug_still_404s(self):
        # The whole point of the param-gated bypass — even on the internal team
        # in US-prod, default behavior matches every other team.
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_still_excludes_other_user_tasks(self):
        # The bypass is scoped to `retrieve` — list still filters by creator even
        # with `?ph_debug=true`.
        other_user = self.create_organization_user("teammate")
        mine = self.create_task("Mine", created_by=self.user)
        theirs = self.create_task("Theirs", created_by=other_user)

        response = self.client.get("/api/projects/@current/tasks/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.json()["results"]}
        assert str(mine.id) in ids
        assert str(theirs.id) not in ids

    def test_repositories_still_excludes_other_user_repos(self):
        other_user = self.create_organization_user("teammate")
        theirs = self.create_task("Theirs", created_by=other_user)
        theirs.repository = "team/repo"
        theirs.save(update_fields=["repository"])

        response = self.client.get("/api/projects/@current/tasks/repositories/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repositories"], [])

    def test_list_runs_for_other_user_task_succeeds(self):
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        ids = {item["id"] for item in response.json()["results"]}
        self.assertEqual(ids, {str(run.id)})

    def test_list_runs_for_other_user_task_without_ph_debug_still_404s(self):
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_retrieve_other_user_run_succeeds(self):
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["id"], str(run.id))

    def test_connection_token_on_other_user_run_still_404s_with_ph_debug(self):
        # connection_token is a GET but mints a write-capable sandbox JWT — the
        # read-only debug bypass must NOT expose it for another user's run.
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/?ph_debug=true"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_write_action_on_other_user_task_still_returns_404(self, _mock_workflow):
        # POST /tasks/<id>/run/ is a write — bypass must NOT fire even when the
        # `?ph_debug=true` opt-in is set; that param is read-only.
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_create_run_on_other_user_task_still_returns_404(self):
        # POST /tasks/<id>/runs/ is a write — bypass must NOT fire even with the
        # opt-in.
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/?ph_debug=true",
            {"environment": "cloud"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestTaskVisibilityInternalDebugRegionGate(BaseTaskAPITest):
    """The internal-debug bypass keys on team-id 2 — but that's only meaningful in
    the US-prod DB. On EU prod, self-hosted, and dev, team-id 2 belongs to some
    unrelated organization. The gate must require `CLOUD_DEPLOYMENT == "US"` to
    avoid silently granting cross-creator visibility there."""

    def setUp(self):
        super().setUp()
        # Same shape as `TestTaskVisibilityInternalDebugTeamBypass.setUp` — the
        # `team.id` match would pass on its own, leaving `CLOUD_DEPLOYMENT` as
        # the only thing each test varies.
        self._bypass_patch = patch(
            "products.tasks.backend.presentation.views.api._is_internal_debug_team",
            side_effect=lambda team_id: team_id == self.team.id and settings.CLOUD_DEPLOYMENT == "US",
        )
        self._bypass_patch.start()

    def tearDown(self):
        self._bypass_patch.stop()
        super().tearDown()

    @parameterized.expand(
        [
            ("eu_prod", "EU"),
            ("self_hosted_or_dev", None),
        ]
    )
    def test_retrieve_other_user_task_still_blocked_off_us(self, _name: str, deployment: str | None) -> None:
        # Sending the FE opt-in must NOT unlock the bypass off-US: the deployment
        # guard fires before the param is even considered.
        other_user = self.create_organization_user("teammate")
        task = self.create_task(created_by=other_user)

        with override_settings(CLOUD_DEPLOYMENT=deployment):
            response = self.client.get(f"/api/projects/@current/tasks/{task.id}/?ph_debug=true")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            ("eu_prod", "EU"),
            ("self_hosted_or_dev", None),
        ]
    )
    def test_slack_thread_context_403_off_us(self, _name: str, deployment: str | None) -> None:
        with override_settings(CLOUD_DEPLOYMENT=deployment):
            response = self.client.get(
                f"/api/projects/{self.team.id}/tasks/slack_thread_context/"
                "?url=https%3A%2F%2Fposthog.slack.com%2Farchives%2FC0%2Fp1779956938619299"
            )
        self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN)


class TestTaskAPI(BaseTaskAPITest):
    def test_list_tasks(self):
        self.create_task("Task 1")
        self.create_task("Task 2")

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        task_titles = [t["title"] for t in data["results"]]
        self.assertIn("Task 1", task_titles)
        self.assertIn("Task 2", task_titles)

    def test_list_tasks_includes_latest_run(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        # Create runs for task1
        TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        run1_latest = TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        # Task2 has no runs

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)

        # Find task1 and task2 in results
        task1_data = next((t for t in data["results"] if t["id"] == str(task1.id)), None)
        task2_data = next((t for t in data["results"] if t["id"] == str(task2.id)), None)

        self.assertIsNotNone(task1_data)
        self.assertIsNotNone(task2_data)
        assert task1_data is not None  # Type narrowing
        assert task2_data is not None  # Type narrowing

        # task1 should have latest_run populated
        self.assertIn("latest_run", task1_data)
        self.assertIsNotNone(task1_data["latest_run"])
        self.assertEqual(task1_data["latest_run"]["id"], str(run1_latest.id))
        self.assertEqual(task1_data["latest_run"]["status"], "in_progress")

        # task2 should have latest_run as None
        self.assertIn("latest_run", task2_data)
        self.assertIsNone(task2_data["latest_run"])

    def test_list_tasks_latest_run_no_per_task_query(self):
        url = "/api/projects/@current/tasks/"
        task1 = self.create_task("Task 1")
        TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        # Warm the request first so one-time auth/access-control queries don't skew the count.
        self.client.get(url)
        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        baseline = len(ctx.captured_queries)

        # Add a second task with multiple runs; the query count must stay constant.
        task2 = self.create_task("Task 2")
        TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.COMPLETED)

        with self.assertNumQueries(baseline):
            response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_list_tasks_latest_run_fetches_only_one_run_per_task(self):
        task = self.create_task("Run-heavy task")
        for _ in range(5):
            TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        latest_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/api/projects/@current/tasks/?limit=1")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"][0]["latest_run"]["id"], str(latest_run.id))

        task_run_sql = "\n".join(query["sql"] for query in ctx.captured_queries)
        self.assertIn('FROM "posthog_task_run"', task_run_sql)
        self.assertIn('LIMIT 1) AS "_latest_run_id"', task_run_sql)
        self.assertNotIn("DISTINCT ON", task_run_sql)

    def test_latest_run_tiebreaks_by_id(self):
        task = self.create_task("Tie-break task")
        created_at = django_timezone.now()
        older_run_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
        latest_run_id = uuid.UUID("00000000-0000-0000-0000-000000000002")
        TaskRun.objects.create(
            id=older_run_id,
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            created_at=created_at,
        )
        TaskRun.objects.create(
            id=latest_run_id,
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            created_at=created_at,
        )

        list_response = self.client.get("/api/projects/@current/tasks/?limit=1")
        detail_response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.json()["results"][0]["latest_run"]["id"], str(latest_run_id))
        self.assertEqual(detail_response.json()["latest_run"]["id"], str(latest_run_id))

    def test_latest_run_ignores_mismatched_run_team(self):
        task = self.create_task("Team-scoped latest run")
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        valid_run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)
        TaskRun.objects.create(task=task, team=other_team, status=TaskRun.Status.IN_PROGRESS)

        list_response = self.client.get("/api/projects/@current/tasks/?limit=1")
        detail_response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")

        self.assertEqual(list_response.status_code, status.HTTP_200_OK)
        self.assertEqual(detail_response.status_code, status.HTTP_200_OK)
        self.assertEqual(list_response.json()["results"][0]["latest_run"]["id"], str(valid_run.id))
        self.assertEqual(detail_response.json()["latest_run"]["id"], str(valid_run.id))

    def test_list_tasks_stage_filter_uses_exists_without_distinct(self):
        matching_task = self.create_task("Matching stage")
        other_task = self.create_task("Other stage")
        TaskRun.objects.create(task=matching_task, team=self.team, stage="building")
        TaskRun.objects.create(task=matching_task, team=self.team, stage="building")
        TaskRun.objects.create(task=other_task, team=self.team, stage="planning")

        response = self.client.get("/api/projects/@current/tasks/?stage=building&limit=1")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 1)
        self.assertEqual(response.json()["results"][0]["id"], str(matching_task.id))

        query_sql = str(
            tasks_facade._list_tasks_queryset(
                self.team.id,
                self.user.id,
                filters={"stage": "building"},
            ).query
        ).upper()
        self.assertIn("EXISTS", query_sql)
        self.assertNotIn("SELECT DISTINCT", query_sql)

    def test_list_tasks_count_matches_queryset(self):
        for i in range(4):
            self.create_task(f"Task {i}")

        with CaptureQueriesContext(connection) as ctx:
            response = self.client.get("/api/projects/@current/tasks/?limit=2")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["count"], 4)
        self.assertEqual(len(response.json()["results"]), 2)
        self.assertIsNotNone(response.json()["next"])
        self.assertTrue(any("COUNT(" in query["sql"].upper() for query in ctx.captured_queries))

    @patch.object(object_storage, "get_presigned_url", return_value="https://signed.example/log")
    def test_list_tasks_per_row_work_bounded_to_page(self, mock_presign):
        page_size = 50
        for i in range(page_size + 5):
            task = self.create_task(f"Task {i}")
            TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/?limit={page_size}")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), page_size)
        self.assertLessEqual(mock_presign.call_count, page_size)

    def test_retrieve_task(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["title"], "Test Task")
        self.assertEqual(data["description"], "Test Description")

    def test_retrieve_task_with_latest_run(self):
        task = self.create_task("Test Task")

        _run1 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
        )

        run2 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("latest_run", data)
        self.assertIsNotNone(data["latest_run"])
        self.assertEqual(data["latest_run"]["id"], str(run2.id))
        self.assertEqual(data["latest_run"]["status"], "in_progress")

    def test_retrieve_task_without_runs(self):
        task = self.create_task("Test Task")

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("latest_run", data)
        self.assertIsNone(data["latest_run"])

    def test_create_task(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "origin_product": "user_created",
                "repository": "posthog/posthog",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

        data = response.json()
        self.assertEqual(data["title"], "New Task")
        self.assertEqual(data["description"], "New Description")
        self.assertEqual(data["repository"], "posthog/posthog")

    def test_create_task_accepts_null_runtime_fields(self):
        # The Code app's cloud-task flows (e.g. Discuss) send the write-only
        # runtime hints as explicit `null` when nothing is selected. `default=None`
        # alone rejects an explicit null ("This field may not be null."), so these
        # fields carry allow_null=True. Regression for that 400.
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "repository": "posthog/posthog",
                "runtime_adapter": None,
                "model": None,
                "reasoning_effort": None,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)

    def test_create_task_defaults_origin_product(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "repository": "posthog/posthog",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["origin_product"], Task.OriginProduct.USER_CREATED)

        task = Task.objects.get(id=data["id"])
        self.assertEqual(task.origin_product, Task.OriginProduct.USER_CREATED)

    def test_create_task_with_hogdesk_origin_product(self):
        # HogDesk creates Code tasks from a support ticket's Code chat with this
        # origin. Ensure the value round-trips through the API — the serializer
        # validates origin_product against OriginProduct.choices and 400s an
        # unknown value, so this is the regression that guards the enum addition.
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "origin_product": "hogdesk",
                "repository": "posthog/posthog",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["origin_product"], Task.OriginProduct.HOGDESK)

        task = Task.objects.get(id=data["id"])
        self.assertEqual(task.origin_product, Task.OriginProduct.HOGDESK)

    def test_create_task_with_github_user_integration(self):
        user_integration = _grant_user_github_access(self.user)

        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "origin_product": "user_created",
                "repository": "posthog/posthog",
                "github_user_integration": str(user_integration.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["github_user_integration"], str(user_integration.id))

        task = Task.objects.get(id=data["id"])
        self.assertEqual(task.github_user_integration_id, user_integration.id)

    def test_create_and_run_slack_task_uses_user_github_integration(self):
        user_integration = _grant_user_github_access(self.user)
        user_integration.repository_cache = [{"id": 1, "name": "posthog", "full_name": "posthog/posthog"}]
        user_integration.repository_cache_updated_at = django_timezone.now()
        user_integration.save(update_fields=["repository_cache", "repository_cache_updated_at"])
        Integration.objects.create(team=self.team, kind="github", integration_id="12345", config={})

        task = Task.create_and_run(
            team=self.team,
            title="Slack task",
            description="Created from Slack",
            origin_product=Task.OriginProduct.SLACK,
            user_id=self.user.id,
            repository="posthog/posthog",
            create_pr=True,
            mode="interactive",
            start_workflow=False,
        )

        self.assertEqual(task.origin_product, Task.OriginProduct.SLACK)
        self.assertEqual(task.github_user_integration_id, user_integration.id)
        assert task.latest_run is not None
        self.assertEqual(task.latest_run.state["pr_authorship_mode"], "user")

    def test_create_task_rejects_github_user_integration_for_other_user(self):
        other_user = self.create_organization_user()
        user_integration = _grant_user_github_access(other_user)

        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "New Task",
                "description": "New Description",
                "origin_product": "user_created",
                "repository": "posthog/posthog",
                "github_user_integration": str(user_integration.id),
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["attr"], "github_user_integration")

    def test_create_task_with_signal_report_same_team(self):
        from products.signals.backend.models import SignalReport, SignalReportTask
        from products.signals.backend.task_run_artefacts import TASK_RUN_TYPE_IMPLEMENTATION, signals_task_ids

        report = SignalReport.objects.create(team=self.team)
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "Signal Task",
                "description": "From a signal report",
                "origin_product": "signal_report",
                "signal_report": str(report.id),
                # Legacy field old clients still send — accepted and ignored.
                "signal_report_task_relationship": "implementation",
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["signal_report"], str(report.id))
        # A manual "start implementation" records the implementation task_run artefact (the
        # task↔report association and work-log entry) and writes the legacy SignalReportTask gate
        # row that blocks the auto-start pipeline from double-starting.
        self.assertEqual(signals_task_ids(report_id=str(report.id), type=TASK_RUN_TYPE_IMPLEMENTATION), [data["id"]])
        self.assertTrue(
            SignalReportTask.objects.filter(
                report=report, task_id=data["id"], relationship=TASK_RUN_TYPE_IMPLEMENTATION
            ).exists()
        )

    def test_create_task_with_signal_report_different_team_rejected(self):
        from products.signals.backend.models import SignalReport

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        report = SignalReport.objects.create(team=other_team)
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {
                "title": "Cross-team Task",
                "description": "Should be rejected",
                "origin_product": "signal_report",
                "signal_report": str(report.id),
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_patch_cannot_change_origin_product(self):
        task = self.create_task("Mine")
        self.assertEqual(task.origin_product, Task.OriginProduct.USER_CREATED)
        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"origin_product": "signal_report"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertEqual(task.origin_product, Task.OriginProduct.USER_CREATED)

    def test_patch_cannot_change_signal_report(self):
        from products.signals.backend.models import SignalReport

        report = SignalReport.objects.create(team=self.team)
        task = self.create_task("Mine")
        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"signal_report": str(report.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        self.assertIsNone(task.signal_report_id)

    def test_update_task(self):
        task = self.create_task("Original Task")

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"title": "Updated Task"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["title"], "Updated Task")

    def test_delete_task(self):
        task = self.create_task("Task to Delete")

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        task.refresh_from_db()
        self.assertTrue(task.deleted)
        self.assertIsNotNone(task.deleted_at)

    @parameterized.expand(
        [
            # (archived_param, expected_titles)
            ("default_excludes_archived", None, {"Active"}),
            ("archived_true_returns_only_archived", "true", {"Archived"}),
            ("archived_all_returns_both", "all", {"Active", "Archived"}),
            ("archived_false_returns_only_active", "false", {"Active"}),
        ]
    )
    def test_list_tasks_archived_filter(self, _name, archived_param, expected_titles):
        active_task = self.create_task("Active")
        archived_task = self.create_task("Archived")
        archived_task.archived = True
        archived_task.archived_at = django_timezone.now()
        archived_task.save(update_fields=["archived", "archived_at"])

        url = "/api/projects/@current/tasks/"
        if archived_param is not None:
            url = f"{url}?archived={archived_param}"
        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        results = response.json()["results"]
        titles = {task["title"] for task in results}
        self.assertEqual(titles, expected_titles)
        # The expected set drives which task UUIDs we expect to come back.
        expected_ids: set[str] = set()
        if "Active" in expected_titles:
            expected_ids.add(str(active_task.id))
        if "Archived" in expected_titles:
            expected_ids.add(str(archived_task.id))
        self.assertEqual({task["id"] for task in results}, expected_ids)

    def test_list_tasks_rejects_invalid_archived_value(self):
        self.create_task("Active")

        response = self.client.get("/api/projects/@current/tasks/?archived=foo")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_retrieve_archived_task_still_works(self):
        task = self.create_task("Archived")
        task.archived = True
        task.archived_at = django_timezone.now()
        task.save(update_fields=["archived", "archived_at"])

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["archived"])
        self.assertIsNotNone(data["archived_at"])

    def test_patch_archived_true_stamps_archived_at(self):
        task = self.create_task("Mine")
        self.assertFalse(task.archived)
        self.assertIsNone(task.archived_at)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"archived": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertTrue(data["archived"])
        self.assertIsNotNone(data["archived_at"])

        task.refresh_from_db()
        self.assertTrue(task.archived)
        self.assertIsNotNone(task.archived_at)

    def test_patch_archived_false_clears_archived_at(self):
        task = self.create_task("Mine")
        task.archived = True
        task.archived_at = django_timezone.now()
        task.save(update_fields=["archived", "archived_at"])

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"archived": False},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertFalse(data["archived"])
        self.assertIsNone(data["archived_at"])

        task.refresh_from_db()
        self.assertFalse(task.archived)
        self.assertIsNone(task.archived_at)

    def test_patch_archived_idempotent_preserves_archived_at(self):
        task = self.create_task("Mine")
        original_archived_at = django_timezone.now() - timedelta(days=1)
        task.archived = True
        task.archived_at = original_archived_at
        task.save(update_fields=["archived", "archived_at"])

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/",
            {"archived": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task.refresh_from_db()
        self.assertTrue(task.archived)
        # archived_at should not be re-stamped because the value did not transition.
        self.assertEqual(task.archived_at, original_archived_at)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_triggers_workflow(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()

        self.assertEqual(data["id"], str(task.id))
        self.assertIn("latest_run", data)
        self.assertIsNotNone(data["latest_run"])

        latest_run = data["latest_run"]
        run_id = latest_run["id"]

        mock_workflow.assert_called_once_with(
            task_id=str(task.id),
            run_id=run_id,
            team_id=task.team.id,
            user_id=self.user.id,
            posthog_mcp_scopes="full",
        )

        self.assertEqual(latest_run["task"], str(task.id))
        self.assertEqual(latest_run["status"], "queued")
        self.assertEqual(latest_run["environment"], "cloud")

    @parameterized.expand(
        [
            ("run_source_omitted", None, "full"),
            ("manual", {"run_source": "manual"}, "full"),
            # signal_report implementation runs log their work as report artefacts (task:write tools).
            ("signal_report", {"run_source": "signal_report"}, "full"),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_resolves_mcp_scope_from_run_source(self, _name, payload, expected_scope, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            payload,
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(mock_workflow.call_args.kwargs["posthog_mcp_scopes"], expected_scope)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_persists_sandbox_environment_id(self, mock_workflow):
        task = self.create_task(created_by=self.user)
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=self.user,
            name="Restricted env",
            network_access_level=SandboxEnvironment.NetworkAccessLevel.CUSTOM,
            allowed_domains=["example.com"],
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"sandbox_environment_id": str(sandbox_environment.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run_id = response.json()["latest_run"]["id"]
        task_run = TaskRun.objects.get(id=run_id)
        self.assertEqual(task_run.state["sandbox_environment_id"], str(sandbox_environment.id))
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("run_endpoint", "run", {"sandbox_environment_id": "{sandbox_environment_id}"}),
            (
                "create_run_endpoint",
                "runs",
                {"environment": "cloud", "sandbox_environment_id": "{sandbox_environment_id}"},
            ),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoints_reject_other_users_private_sandbox_environment(
        self, _name, endpoint, payload_template, mock_workflow
    ):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=self.user)
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=other_user,
            name="Victim's private env",
            private=True,
            environment_variables={"SECRET_KEY": "secret_value"},
        )
        payload = {
            key: str(sandbox_environment.id) if value == "{sandbox_environment_id}" else value
            for key, value in payload_template.items()
        }

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/{endpoint}/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid sandbox_environment_id")
        self.assertFalse(TaskRun.objects.filter(task=task).exists())
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_drops_inaccessible_inherited_sandbox_environment_id(self, mock_workflow):
        other_user = self.create_organization_user("victim")
        task = self.create_task(created_by=self.user)
        sandbox_environment = SandboxEnvironment.objects.create(
            team=self.team,
            created_by=other_user,
            name="Victim's private env",
            private=True,
            environment_variables={"SECRET_KEY": "secret_value"},
        )
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={"sandbox_environment_id": str(sandbox_environment.id)},
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"resume_from_run_id": str(previous_run.id)},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        self.assertEqual(run.state["resume_from_run_id"], str(previous_run.id))
        self.assertNotIn("sandbox_environment_id", run.state)
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_persists_pending_user_message(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"pending_user_message": "Read the attached file first"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run_id = response.json()["latest_run"]["id"]
        task_run = TaskRun.objects.get(id=run_id)
        self.assertEqual(
            task_run.state["pending_user_message"],
            "Read the attached file first",
        )
        mock_workflow.assert_called_once()

    @patch("posthog.storage.object_storage.copy")
    @patch("posthog.storage.object_storage.tag")
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_attaches_staged_artifacts(self, mock_workflow, mock_tag, mock_copy):
        task = self.create_task()
        staged_artifact = build_task_artifact_entry(
            artifact_id="artifact-123",
            name="spec.pdf",
            artifact_type="user_attachment",
            source="user_attachment",
            size=4096,
            content_type="application/pdf",
            storage_path=f"tasks/artifacts/team_{self.team.id}/task_{task.id}/staged/artifact-123/spec.pdf",
        )
        cache_task_staged_artifact(task, staged_artifact)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "pending_user_message": "Read the file first",
                "pending_user_artifact_ids": ["artifact-123"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run_id = response.json()["latest_run"]["id"]
        task_run = TaskRun.objects.get(id=run_id)
        self.assertEqual(task_run.state["pending_user_message"], "Read the file first")
        self.assertEqual(task_run.state["pending_user_artifact_ids"], ["artifact-123"])
        self.assertEqual(len(task_run.artifacts), 1)
        artifact = task_run.artifacts[0]
        self.assertEqual(artifact["id"], "artifact-123")
        self.assertEqual(artifact["name"], "spec.pdf")
        self.assertEqual(artifact["type"], "user_attachment")
        self.assertEqual(artifact["source"], "user_attachment")
        self.assertEqual(artifact["storage_path"], staged_artifact["storage_path"])
        mock_copy.assert_not_called()
        mock_tag.assert_called_once_with(
            staged_artifact["storage_path"],
            {
                "ttl_days": RUN_ARTIFACT_TTL_DAYS,
                "team_id": str(self.team.id),
            },
        )
        remaining_staged_artifacts, missing_artifact_ids = get_task_staged_artifacts(task, ["artifact-123"])
        self.assertEqual(remaining_staged_artifacts, [])
        self.assertEqual(missing_artifact_ids, ["artifact-123"])
        mock_workflow.assert_called_once()

    @patch("posthog.storage.object_storage.copy")
    @patch("posthog.storage.object_storage.tag")
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_ignores_copy_failures_for_staged_artifacts(self, mock_workflow, mock_tag, mock_copy):
        mock_copy.side_effect = AssertionError("copy should not be called")
        task = self.create_task()
        staged_artifact = build_task_artifact_entry(
            artifact_id="artifact-123",
            name="spec.pdf",
            artifact_type="user_attachment",
            source="user_attachment",
            size=4096,
            content_type="application/pdf",
            storage_path=f"tasks/artifacts/team_{self.team.id}/task_{task.id}/staged/artifact-123/spec.pdf",
        )
        cache_task_staged_artifact(task, staged_artifact)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "pending_user_message": "Read the file first",
                "pending_user_artifact_ids": ["artifact-123"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(TaskRun.objects.filter(task=task).count(), 1)
        task_run = TaskRun.objects.get(task=task)
        self.assertEqual(task_run.artifacts, [staged_artifact])
        remaining_staged_artifacts, missing_artifact_ids = get_task_staged_artifacts(task, ["artifact-123"])
        self.assertEqual(remaining_staged_artifacts, [])
        self.assertEqual(missing_artifact_ids, ["artifact-123"])
        mock_copy.assert_not_called()
        mock_tag.assert_called_once_with(
            staged_artifact["storage_path"],
            {
                "ttl_days": RUN_ARTIFACT_TTL_DAYS,
                "team_id": str(self.team.id),
            },
        )
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_run_endpoint_creates_cloud_run_without_triggering_workflow(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {
                "environment": "cloud",
                "mode": "interactive",
                "branch": "release/direct-upload",
                "runtime_adapter": "codex",
                "model": "gpt-5.4",
                "reasoning_effort": "high",
                "initial_permission_mode": "auto",
                "run_source": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task_run = TaskRun.objects.get(id=response.json()["id"])
        self.assertEqual(task_run.environment, TaskRun.Environment.CLOUD)
        self.assertEqual(task_run.status, TaskRun.Status.QUEUED)
        self.assertEqual(task_run.branch, "release/direct-upload")
        self.assertEqual(task_run.state["mode"], "interactive")
        self.assertEqual(task_run.state["pr_base_branch"], "release/direct-upload")
        self.assertEqual(task_run.state["runtime_adapter"], "codex")
        self.assertEqual(task_run.state["provider"], "openai")
        self.assertEqual(task_run.state["model"], "gpt-5.4")
        self.assertEqual(task_run.state["reasoning_effort"], "high")
        self.assertEqual(task_run.state["initial_permission_mode"], "auto")
        self.assertEqual(task_run.state["run_source"], "manual")
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_run_endpoint_caches_user_github_token(self, mock_workflow):
        integration = Integration.objects.create(team=self.team, kind="github", config={"access_token": "token"})
        task = Task.objects.create(
            team=self.team,
            created_by=self.user,
            title="GitHub task",
            description="Ship it",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
            github_integration=integration,
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {
                "environment": "cloud",
                "pr_authorship_mode": "user",
                "github_user_token": "ghu_test_token",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task_run = TaskRun.objects.get(id=response.json()["id"])
        self.assertEqual(get_cached_github_user_token(str(task_run.id)), "ghu_test_token")
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_run_endpoint_rejects_user_authorship_without_github_identity_when_no_repo(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {
                "environment": "cloud",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "github_authorization_required")
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_run_endpoint_persists_user_integration_when_no_repo(self, mock_workflow):
        task = self.create_task(created_by=self.user)
        user_integration = _grant_user_github_access(self.user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {
                "environment": "cloud",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task.refresh_from_db()
        self.assertEqual(task.github_user_integration_id, user_integration.id)
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_create_run_endpoint_falls_back_to_team_integration_when_no_user_integration(self, mock_workflow):
        integration = Integration.objects.create(team=self.team, kind="github", config={"access_token": "token"})
        task = self.create_task(created_by=self.user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {
                "environment": "cloud",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        task.refresh_from_db()
        task_run = TaskRun.objects.get(id=response.json()["id"])
        self.assertEqual(task.github_integration_id, integration.id)
        self.assertIsNone(task.github_user_integration_id)
        self.assertEqual(task_run.state["pr_authorship_mode"], "bot")
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_start_run_endpoint_triggers_workflow_for_existing_cloud_run(self, mock_workflow):
        task = self.create_task()
        task_run = task.create_run(environment=TaskRun.Environment.CLOUD)
        task_run.artifacts = [
            build_task_artifact_entry(
                artifact_id="artifact-123",
                name="spec.pdf",
                artifact_type="user_attachment",
                source="user_attachment",
                size=4096,
                content_type="application/pdf",
                storage_path=f"tasks/artifacts/team_{self.team.id}/task_{task.id}/run_{task_run.id}/artifact-123_spec.pdf",
            )
        ]
        task_run.save(update_fields=["artifacts", "updated_at"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{task_run.id}/start/",
            {
                "pending_user_message": "Read the file first",
                "pending_user_artifact_ids": ["artifact-123"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task_run.refresh_from_db()
        self.assertEqual(task_run.state["pending_user_message"], "Read the file first")
        self.assertEqual(task_run.state["pending_user_artifact_ids"], ["artifact-123"])
        mock_workflow.assert_called_once_with(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=task.team.id,
            user_id=self.user.id,
            posthog_mcp_scopes="full",
        )

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_start_run_endpoint_rejects_missing_run_artifacts(self, mock_workflow):
        task = self.create_task()
        task_run = task.create_run(environment=TaskRun.Environment.CLOUD)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{task_run.id}/start/",
            {"pending_user_artifact_ids": ["artifact-123"]},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "detail": "Some pending_user_artifact_ids are invalid for this run",
                "missing_artifact_ids": ["artifact-123"],
            },
        )
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_start_run_endpoint_rejects_non_startable_status(self, mock_workflow):
        task = self.create_task()
        task_run = task.create_run(environment=TaskRun.Environment.CLOUD)
        task_run.status = TaskRun.Status.COMPLETED
        task_run.save(update_fields=["status", "updated_at"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{task_run.id}/start/",
            {"pending_user_message": "Retry this"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {"error": "Only queued or not_started cloud runs can be started (current status: completed)"},
        )
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_start_run_endpoint_rolls_back_pending_state_when_workflow_trigger_fails(self, mock_workflow):
        mock_workflow.side_effect = RuntimeError("workflow start failed")
        task = self.create_task()
        task_run = task.create_run(environment=TaskRun.Environment.CLOUD)
        task_run.state = {"existing_key": "keep-me"}
        task_run.artifacts = [
            build_task_artifact_entry(
                artifact_id="artifact-123",
                name="spec.pdf",
                artifact_type="user_attachment",
                source="user_attachment",
                size=4096,
                content_type="application/pdf",
                storage_path=f"tasks/artifacts/team_{self.team.id}/task_{task.id}/run_{task_run.id}/artifact-123_spec.pdf",
            )
        ]
        task_run.save(update_fields=["state", "artifacts", "updated_at"])

        self.client.raise_request_exception = False
        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{task_run.id}/start/",
            {
                "pending_user_message": "Read the file first",
                "pending_user_artifact_ids": ["artifact-123"],
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_500_INTERNAL_SERVER_ERROR)
        task_run.refresh_from_db()
        self.assertEqual(task_run.state, {"existing_key": "keep-me"})
        mock_workflow.assert_called_once_with(
            task_id=str(task.id),
            run_id=str(task_run.id),
            team_id=task.team.id,
            user_id=self.user.id,
            posthog_mcp_scopes="full",
        )

    @parameterized.expand(
        [
            ("default",),
            ("acceptEdits",),
            ("plan",),
            ("bypassPermissions",),
            ("auto",),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_persists_initial_permission_mode(self, mode, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"initial_permission_mode": mode, "runtime_adapter": "claude", "model": "claude-sonnet-4-6"},
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["initial_permission_mode"] == mode
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_omits_initial_permission_mode_when_not_set(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/run/")

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert "initial_permission_mode" not in (task_run.state or {})
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_invalid_initial_permission_mode(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"initial_permission_mode": "invalid_mode"},
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_combines_pending_user_message_and_initial_permission_mode(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "pending_user_message": "Start with this",
                "initial_permission_mode": "plan",
                "runtime_adapter": "claude",
                "model": "claude-sonnet-4-6",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["pending_user_message"] == "Start with this"
        assert task_run.state["initial_permission_mode"] == "plan"
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_persists_pr_authorship_metadata(self, mock_workflow):
        task = self.create_task()
        task.repository = "posthog/posthog"
        task.created_by = self.user
        task.save(update_fields=["repository", "created_by"])
        user_integration = _grant_user_github_access(self.user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "branch": "main",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["pr_authorship_mode"] == "user"
        assert task_run.state["run_source"] == "manual"
        assert task_run.state["pr_base_branch"] == "main"
        assert task_run.state["github_credential_source"] == "server_integration"
        task.refresh_from_db()
        assert task.github_user_integration_id == user_integration.id
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_caches_github_user_token_backcompat(self, mock_workflow):
        """Backward-compat: callers that ship ``github_user_token`` have it cached per-run."""
        task = self.create_task()
        task.repository = "posthog/posthog"
        task.save(update_fields=["repository"])
        github_user_token = "ghu_test_token"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "branch": "main",
                "pr_authorship_mode": "user",
                "run_source": "manual",
                "github_user_token": github_user_token,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert get_cached_github_user_token(str(task_run.id)) == github_user_token
        assert task_run.state["github_credential_source"] == "caller_token"
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_accepts_token_even_without_linked_identity(self, mock_workflow):
        """A caller-supplied token satisfies the preflight on its own (no identity required)."""
        task = self.create_task()
        task.repository = "posthog/posthog"
        task.save(update_fields=["repository"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
                "github_user_token": "ghu_manual_token",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("gpt_5_3_low", "gpt-5.3-codex", "low"),
            ("gpt_5_3_medium", "gpt-5.3-codex", "medium"),
            ("gpt_5_3_high", "gpt-5.3-codex", "high"),
            ("gpt_5_5_xhigh", "gpt-5.5", "xhigh"),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_persists_runtime_metadata(self, _case_name, model, reasoning_effort, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "runtime_adapter": "codex",
                "model": model,
                "reasoning_effort": reasoning_effort,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest_run = response.json()["latest_run"]
        task_run = TaskRun.objects.get(id=latest_run["id"])
        assert task_run.state["runtime_adapter"] == "codex"
        assert task_run.state["provider"] == "openai"
        assert task_run.state["model"] == model
        assert task_run.state["reasoning_effort"] == reasoning_effort
        assert latest_run["runtime_adapter"] == "codex"
        assert latest_run["provider"] == "openai"
        assert latest_run["model"] == model
        assert latest_run["reasoning_effort"] == reasoning_effort
        mock_workflow.assert_called_once()

    @parameterized.expand([("auto",), ("read-only",), ("full-access",)])
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_preserves_codex_initial_permission_mode(self, initial_permission_mode, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "runtime_adapter": "codex",
                "model": "gpt-5.4",
                "initial_permission_mode": initial_permission_mode,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["initial_permission_mode"] == initial_permission_mode
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            (
                "claude_rejects_codex_mode",
                "claude",
                "claude-opus-4-6",
                "full-access",
                "Invalid choice 'full-access' for runtime_adapter 'claude'. Supported values: 'default', 'acceptEdits', 'plan', 'bypassPermissions', 'auto'.",
            ),
            (
                "codex_rejects_claude_mode",
                "codex",
                "gpt-5.4",
                "plan",
                "Invalid choice 'plan' for runtime_adapter 'codex'. Supported values: 'auto', 'read-only', 'full-access'.",
            ),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_mismatched_permission_mode(
        self,
        _case_name,
        runtime_adapter,
        model,
        initial_permission_mode,
        expected_detail,
        mock_workflow,
    ):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "runtime_adapter": runtime_adapter,
                "model": model,
                "initial_permission_mode": initial_permission_mode,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": expected_detail,
            "attr": "initial_permission_mode",
        }
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_user_authorship_without_github_identity(self, mock_workflow):
        task = self.create_task()
        task.repository = "posthog/posthog"
        task.save(update_fields=["repository"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "github_authorization_required"
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_user_authorship_when_refresh_token_expired(self, mock_workflow):
        task = self.create_task()
        task.repository = "posthog/posthog"
        task.created_by = self.user
        task.save(update_fields=["repository", "created_by"])
        integration = _grant_user_github_access(self.user)
        integration.config["user_refresh_token_expires_at"] = int(time.time()) - 1
        integration.save(update_fields=["config"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "github_authorization_required"
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_non_creator_with_404(self, mock_workflow: MagicMock) -> None:
        # Cross-user run attempts are blocked at the queryset level: a teammate
        # cannot see (let alone run) someone else's task. The previous
        # `github_authorization_required` 400 path is now unreachable for
        # non-creators and is superseded by this 404.
        task = self.create_task(created_by=self.user)
        task.repository = "posthog/posthog"
        task.save(update_fields=["repository"])
        _grant_user_github_access(self.user)
        requester = self.create_organization_user()
        self.client.force_authenticate(requester)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_404_NOT_FOUND
        assert not TaskRun.objects.filter(task=task).exists()
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_user_authorship_when_access_token_missing(self, mock_workflow: MagicMock) -> None:
        task = self.create_task(created_by=self.user)
        task.repository = "posthog/posthog"
        task.save(update_fields=["repository"])
        integration = _grant_user_github_access(self.user)
        sensitive_config = dict(integration.sensitive_config)
        sensitive_config.pop("user_access_token")
        integration.sensitive_config = sensitive_config
        integration.save(update_fields=["sensitive_config"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "github_authorization_required"
        mock_workflow.assert_not_called()

    @parameterized.expand(
        [
            ("missing_runtime_adapter", {"model": "gpt-5.3-codex"}, "runtime_adapter"),
            ("missing_model", {"runtime_adapter": "codex"}, "model"),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_incomplete_runtime_selection(self, _case_name, payload, expected_attr, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            payload,
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": "This field is required when selecting a cloud runtime.",
            "attr": expected_attr,
        }
        mock_workflow.assert_not_called()

    @parameterized.expand(
        [
            ("gpt_5_4_xhigh", "gpt-5.4", "xhigh", "low, medium, high"),
            ("gpt_5_4_max", "gpt-5.4", "max", "low, medium, high"),
            ("gpt_5_5_max", "gpt-5.5", "max", "low, medium, high, xhigh"),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_unsupported_codex_reasoning_effort(
        self, _case_name, model, reasoning_effort, supported_values, mock_workflow
    ):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "codex",
                "model": model,
                "reasoning_effort": reasoning_effort,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                f"Reasoning effort '{reasoning_effort}' is not supported for runtime_adapter 'codex' "
                f"and model '{model}'. Supported values: {supported_values}."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.presentation.serializers.posthoganalytics.capture")
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_unsupported_claude_reasoning_effort(self, mock_workflow, mock_capture):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "claude",
                "model": "claude-sonnet-4-5",
                "reasoning_effort": "high",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                "Reasoning effort 'high' is not supported for runtime_adapter 'claude' "
                "and model 'claude-sonnet-4-5'. Supported values: none."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

        # The rejection used to be visible only in the client's 400 response; it must also
        # be captured server-side so recurring bad model/effort combos are queryable.
        # assert_any_call because create_task() itself fires a "task_created" capture.
        mock_capture.assert_any_call(
            distinct_id=str(self.user.distinct_id),
            event="task run reasoning effort rejected",
            properties={
                "runtime_adapter": "claude",
                "model": "claude-sonnet-4-5",
                "reasoning_effort": "high",
                "error": (
                    "Reasoning effort 'high' is not supported for runtime_adapter 'claude' "
                    "and model 'claude-sonnet-4-5'. Supported values: none."
                ),
            },
            groups=ANY,
        )

    @parameterized.expand(
        [
            ("low",),
            ("medium",),
            ("high",),
            ("xhigh",),
            ("max",),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_accepts_fable_reasoning_effort(self, reasoning_effort, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "claude",
                "model": "claude-fable-5",
                "reasoning_effort": reasoning_effort,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest_run = response.json()["latest_run"]
        task_run = TaskRun.objects.get(id=latest_run["id"])
        assert task_run.state["model"] == "claude-fable-5"
        assert task_run.state["reasoning_effort"] == reasoning_effort
        mock_workflow.assert_called_once()

    @parameterized.expand(
        [
            ("low",),
            ("medium",),
            ("high",),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_accepts_claude_sonnet_5_reasoning_effort(self, reasoning_effort, mock_workflow):
        # claude-sonnet-5 was missing from the supported-model map, so every reasoning_effort
        # (including these valid ones) was rejected with "Supported values: none."
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "claude",
                "model": "claude-sonnet-5",
                "reasoning_effort": reasoning_effort,
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest_run = response.json()["latest_run"]
        task_run = TaskRun.objects.get(id=latest_run["id"])
        assert task_run.state["model"] == "claude-sonnet-5"
        assert task_run.state["reasoning_effort"] == reasoning_effort
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.presentation.serializers.posthoganalytics.capture")
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_unsupported_claude_sonnet_5_reasoning_effort(self, mock_workflow, mock_capture):
        # claude-sonnet-5 supports low/medium/high (unlike claude-sonnet-4-5, which supports
        # none) - this pins the "Supported values: <non-empty list>" message and confirms the
        # rejection capture also fires for a model that has some supported efforts.
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "claude",
                "model": "claude-sonnet-5",
                "reasoning_effort": "xhigh",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                "Reasoning effort 'xhigh' is not supported for runtime_adapter 'claude' "
                "and model 'claude-sonnet-5'. Supported values: low, medium, high."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

        # assert_any_call because create_task() itself fires a "task_created" capture.
        mock_capture.assert_any_call(
            distinct_id=str(self.user.distinct_id),
            event="task run reasoning effort rejected",
            properties={
                "runtime_adapter": "claude",
                "model": "claude-sonnet-5",
                "reasoning_effort": "xhigh",
                "error": (
                    "Reasoning effort 'xhigh' is not supported for runtime_adapter 'claude' "
                    "and model 'claude-sonnet-5'. Supported values: low, medium, high."
                ),
            },
            groups=ANY,
        )

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_derives_provider_from_runtime_adapter(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "runtime_adapter": "codex",
                "model": "gpt-5.3-codex",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        latest_run = response.json()["latest_run"]
        task_run = TaskRun.objects.get(id=latest_run["id"])
        assert task_run.state["provider"] == "openai"
        assert latest_run["provider"] == "openai"
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_rejects_user_authorship_without_github_identity_when_no_repo(self, mock_workflow):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json()["code"] == "github_authorization_required"
        mock_workflow.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_persists_user_integration_when_no_repo(self, mock_workflow):
        task = self.create_task(created_by=self.user)
        user_integration = _grant_user_github_access(self.user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task.refresh_from_db()
        assert task.github_user_integration_id == user_integration.id
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_falls_back_to_team_integration_when_no_user_integration(self, mock_workflow):
        integration = Integration.objects.create(team=self.team, kind="github", config={"access_token": "token"})
        task = self.create_task(created_by=self.user)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "pr_authorship_mode": "user",
                "run_source": "manual",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task.refresh_from_db()
        task_run = task.latest_run
        assert task_run is not None
        assert task.github_integration_id == integration.id
        assert task.github_user_integration_id is None
        assert task_run.state["pr_authorship_mode"] == "bot"
        mock_workflow.assert_called_once()

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_resume_carries_forward_pr_authorship_metadata(self, mock_workflow):
        task = self.create_task()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={
                "pr_authorship_mode": "bot",
                "run_source": "signal_report",
                "signal_report_id": "report-123",
                "pr_base_branch": "main",
                "runtime_adapter": "codex",
                "model": "gpt-5.3-codex",
                "reasoning_effort": "medium",
                "snapshot_external_id": "snap-1",
            },
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "resume_from_run_id": str(previous_run.id),
                "pending_user_message": "Please continue",
                "github_user_token": "ghu_resume_token",
            },
            format="json",
        )

        assert response.status_code == status.HTTP_200_OK
        task_run = TaskRun.objects.get(id=response.json()["latest_run"]["id"])
        assert task_run.state["pr_authorship_mode"] == "bot"
        assert task_run.state["run_source"] == "signal_report"
        assert task_run.state["signal_report_id"] == "report-123"
        assert task_run.state["snapshot_external_id"] == "snap-1"
        assert task_run.state["pr_base_branch"] == "main"
        assert task_run.state["runtime_adapter"] == "codex"
        assert task_run.state["provider"] == "openai"
        assert task_run.state["model"] == "gpt-5.3-codex"
        assert task_run.state["reasoning_effort"] == "medium"
        # Token passed on a BOT resume must not be cached — only USER mode runs use it.
        assert get_cached_github_user_token(str(task_run.id)) is None

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_endpoint_resume_rejects_inherited_invalid_reasoning_effort(self, mock_workflow):
        task = self.create_task()
        previous_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            state={
                "runtime_adapter": "codex",
                "model": "gpt-5.4",
                "reasoning_effort": "max",
            },
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {
                "mode": "interactive",
                "resume_from_run_id": str(previous_run.id),
            },
            format="json",
        )

        assert response.status_code == status.HTTP_400_BAD_REQUEST
        assert response.json() == {
            "type": "validation_error",
            "code": "invalid_input",
            "detail": (
                "Reasoning effort 'max' is not supported for runtime_adapter 'codex' "
                "and model 'gpt-5.4'. Supported values: low, medium, high."
            ),
            "attr": "reasoning_effort",
        }
        mock_workflow.assert_not_called()

    def test_run_endpoint_rejects_invalid_sandbox_environment_id(self):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"sandbox_environment_id": "550e8400-e29b-41d4-a716-446655440000"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["detail"], "Invalid sandbox_environment_id")

    @parameterized.expand(
        [
            # (filter_param, filter_value, task_repos, expected_task_indices)
            ("repository", "posthog/posthog", ["posthog/posthog", "posthog/posthog-js", "other/posthog"], [0]),
            ("repository", "posthog", ["posthog/posthog", "posthog/posthog-js", "other/posthog"], [0, 2]),
            ("repository", "posthog-js", ["posthog/posthog", "posthog/posthog-js", "other/posthog-js"], [1, 2]),
            ("organization", "posthog", ["posthog/posthog", "posthog/posthog-js", "other/posthog"], [0, 1]),
            ("organization", "other", ["posthog/posthog", "other/repo1", "other/repo2"], [1, 2]),
            # Case insensitive tests
            ("repository", "PostHog/PostHog", ["posthog/posthog", "posthog/posthog-js"], [0]),
            ("repository", "PostHog", ["posthog/posthog", "other/posthog"], [0, 1]),
            ("organization", "PostHog", ["posthog/posthog", "posthog/posthog-js", "other/repo"], [0, 1]),
        ]
    )
    def test_filter_by_repository_and_organization(self, filter_param, filter_value, task_repos, expected_indices):
        tasks = []
        for i, repo in enumerate(task_repos):
            task = Task.objects.create(
                team=self.team,
                title=f"Task {i}",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                repository=repo,
            )
            tasks.append(task)

        response = self.client.get(f"/api/projects/@current/tasks/?{filter_param}={filter_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        expected_task_ids = [str(tasks[i].id) for i in expected_indices]

        self.assertEqual(len(task_ids), len(expected_task_ids))
        for expected_id in expected_task_ids:
            self.assertIn(expected_id, task_ids)

    def test_delete_task_soft_deletes(self):
        task = self.create_task("Task to delete")

        response = self.client.delete(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)

        task.refresh_from_db()
        self.assertTrue(task.deleted)
        self.assertIsNotNone(task.deleted_at)

    def test_deleted_tasks_not_in_list(self):
        task1 = self.create_task("Active Task")
        task2 = self.create_task("Deleted Task")
        task2.soft_delete()

        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(task1.id))

    def test_deleted_task_not_retrievable(self):
        task = self.create_task("Deleted Task")
        task.soft_delete()

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @parameterized.expand(
        [
            # Tasks are creator-scoped: a user can only ever see their own tasks
            # plus legacy tasks without a creator. The `created_by` filter narrows
            # within that visible set; it cannot widen it to other users' tasks.
            ("self_user", "self", [0]),
            ("other_user", "other", []),
            ("no_filter", None, [0, 2]),
        ]
    )
    def test_filter_by_created_by(self, _name, filter_user, expected_indices):
        other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(other_user)

        users = {"self": self.user, "other": other_user, None: None}

        tasks = [
            Task.objects.create(
                team=self.team,
                title="My Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=self.user,
            ),
            Task.objects.create(
                team=self.team,
                title="Other Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=other_user,
            ),
            Task.objects.create(
                team=self.team,
                title="No Creator Task",
                description="Description",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=None,
            ),
        ]

        url = "/api/projects/@current/tasks/"
        if filter_user is not None:
            user = users[filter_user]
            assert user is not None
            url += f"?created_by={user.id}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        expected_task_ids = [str(tasks[i].id) for i in expected_indices]

        self.assertEqual(len(task_ids), len(expected_task_ids))
        for expected_id in expected_task_ids:
            self.assertIn(expected_id, task_ids)

    @parameterized.expand(
        [
            # (name, search_value, expected_task_indices)
            ("matches_title_substring", "login", [0]),
            ("matches_title_case_insensitive", "LOGIN", [0]),
            ("matches_description_substring", "regression", [1]),
            ("matches_both_title_and_description", "bug", [1, 2]),
            ("matches_task_number", "2", [2]),
            ("matches_slug_style_input", "TSK-1", [1]),
            ("no_match_returns_empty", "zzzzz", []),
            ("whitespace_is_trimmed", "   login   ", [0]),
            ("empty_string_is_ignored", "", [0, 1, 2]),
        ]
    )
    def test_filter_by_search(self, _name, search_value, expected_indices):
        tasks = []
        # Pin task_number explicitly so the "matches_task_number" and "matches_slug_style_input"
        # cases don't silently break if anything in setup were to bump the per-team counter.
        titles_descriptions_and_numbers = [
            ("Fix login flow", "Users cannot sign in on mobile", 0),
            ("Ship new feature", "Roll out regression-proof bug fix", 1),
            ("Cleanup", "Addresses a latent bug in the parser", 2),
        ]
        for title, description, task_number in titles_descriptions_and_numbers:
            tasks.append(
                Task.objects.create(
                    team=self.team,
                    title=title,
                    description=description,
                    origin_product=Task.OriginProduct.USER_CREATED,
                    created_by=self.user,
                    task_number=task_number,
                )
            )

        url = "/api/projects/@current/tasks/"
        if search_value is not None:
            url += f"?search={quote(search_value)}"

        response = self.client.get(url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = {t["id"] for t in data["results"]}
        expected_task_ids = {str(tasks[i].id) for i in expected_indices}
        self.assertEqual(task_ids, expected_task_ids)

    @parameterized.expand(
        [
            # (name, status_value, expected_task_indices)
            ("in_progress_latest_only", TaskRun.Status.IN_PROGRESS, [0]),
            ("completed_latest_only", TaskRun.Status.COMPLETED, [1]),
            ("failed_matches_nothing_here", TaskRun.Status.FAILED, []),
            ("queued_matches_task_with_single_queued_run", TaskRun.Status.QUEUED, [2]),
        ]
    )
    def test_filter_by_status(self, _name, status_value, expected_indices):
        # Explicit timestamps avoid flaky ordering when two runs share the same
        # default `created_at=now()` microsecond on fast machines.
        base_time = django_timezone.now()

        # Task 0: earlier completed run, newer in_progress run — latest = in_progress
        task_in_progress = self.create_task("Task 0")
        TaskRun.objects.create(
            task=task_in_progress,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            created_at=base_time,
        )
        TaskRun.objects.create(
            task=task_in_progress,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            created_at=base_time + timedelta(seconds=1),
        )

        # Task 1: single completed run — latest = completed
        task_completed = self.create_task("Task 1")
        TaskRun.objects.create(task=task_completed, team=self.team, status=TaskRun.Status.COMPLETED)

        # Task 2: single queued run — latest = queued
        task_queued = self.create_task("Task 2")
        TaskRun.objects.create(task=task_queued, team=self.team, status=TaskRun.Status.QUEUED)

        # Task 3: no runs — should never match any status filter
        self.create_task("Task 3")

        tasks = [task_in_progress, task_completed, task_queued]

        response = self.client.get(f"/api/projects/@current/tasks/?status={status_value}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = {t["id"] for t in data["results"]}
        expected_task_ids = {str(tasks[i].id) for i in expected_indices}
        self.assertEqual(task_ids, expected_task_ids)

    def test_filter_by_status_rejects_unknown_value(self):
        response = self.client.get("/api/projects/@current/tasks/?status=not_a_real_status")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_filter_by_status_uses_latest_run_not_any_run(self):
        """A task whose latest run is in_progress must not match status=completed, even if an older run completed."""
        base_time = django_timezone.now()

        task = self.create_task("Task with mixed runs")
        TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED, created_at=base_time)
        TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            created_at=base_time + timedelta(seconds=1),
        )

        response = self.client.get(f"/api/projects/@current/tasks/?status={TaskRun.Status.COMPLETED}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["results"], [])

    def test_filter_combines_search_and_status(self):
        matching = self.create_task("Payments bug")
        TaskRun.objects.create(task=matching, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        wrong_status = self.create_task("Payments crash")
        TaskRun.objects.create(task=wrong_status, team=self.team, status=TaskRun.Status.COMPLETED)

        wrong_search = self.create_task("Other issue")
        TaskRun.objects.create(task=wrong_search, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/?search=payments&status={TaskRun.Status.IN_PROGRESS}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual([t["id"] for t in data["results"]], [str(matching.id)])

    def test_filter_combines_all_filters(self):
        other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(other_user)

        matching = Task.objects.create(
            team=self.team,
            title="Fix login flow",
            description="Payments login regression",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
            created_by=self.user,
        )
        TaskRun.objects.create(task=matching, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        # Same content but wrong repository.
        Task.objects.create(
            team=self.team,
            title="Fix login flow elsewhere",
            description="Payments login regression",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="other/repo",
            created_by=self.user,
        )

        # Same repo and content but wrong creator.
        Task.objects.create(
            team=self.team,
            title="Fix login flow",
            description="Payments login regression",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
            created_by=other_user,
        )

        # Same creator/repo/content but wrong latest run status.
        wrong_status = Task.objects.create(
            team=self.team,
            title="Fix login flow",
            description="Payments login regression",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
            created_by=self.user,
        )
        TaskRun.objects.create(task=wrong_status, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.get(
            "/api/projects/@current/tasks/"
            f"?search=login&repository=posthog/posthog&created_by={self.user.id}"
            f"&status={TaskRun.Status.IN_PROGRESS}"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual([t["id"] for t in data["results"]], [str(matching.id)])

    def test_filters_survive_large_result_sets(self):
        """Regression test: filters must apply at the DB level, not after pagination truncates the page."""
        other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(other_user)

        # The task we care about — created first, so it ends up older than the noise below
        # and would fall outside a naive "top N by created_at" slice.
        needle = Task.objects.create(
            team=self.team,
            title="Needle task",
            description="Find me",
            origin_product=Task.OriginProduct.USER_CREATED,
            created_by=self.user,
        )

        # Pile of newer tasks created by someone else to push the needle below the default page.
        bulk = [
            Task(
                team=self.team,
                title=f"Noise {i}",
                description="...",
                origin_product=Task.OriginProduct.USER_CREATED,
                created_by=other_user,
            )
            for i in range(150)
        ]
        for task in bulk:
            task.save()

        response = self.client.get(f"/api/projects/@current/tasks/?created_by={self.user.id}")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()

        returned_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(needle.id), returned_ids)


class TestTaskRepositoriesAction(BaseTaskAPITest):
    def test_returns_distinct_sorted_repositories(self):
        Task.objects.create(
            team=self.team,
            title="T1",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog-js",
        )
        Task.objects.create(
            team=self.team,
            title="T2",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
        )
        # Duplicate of an existing repo should be collapsed.
        Task.objects.create(
            team=self.team,
            title="T3",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
        )
        # Null and empty repositories should be excluded.
        Task.objects.create(
            team=self.team,
            title="T4",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository=None,
        )

        response = self.client.get("/api/projects/@current/tasks/repositories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        self.assertEqual(
            response.json(),
            {"repositories": ["posthog/posthog", "posthog/posthog-js"]},
        )

    def test_excludes_soft_deleted_tasks(self):
        active = Task.objects.create(
            team=self.team,
            title="Active",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/posthog",
        )
        deleted = Task.objects.create(
            team=self.team,
            title="Deleted",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="gone/repo",
        )
        deleted.soft_delete()

        response = self.client.get("/api/projects/@current/tasks/repositories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repositories"], [active.repository])

    def test_excludes_internal_tasks(self):
        Task.objects.create(
            team=self.team,
            title="Public",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/public",
        )
        Task.objects.create(
            team=self.team,
            title="Internal",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/internal",
            internal=True,
        )

        response = self.client.get("/api/projects/@current/tasks/repositories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repositories"], ["posthog/public"])

    def test_scoped_to_team(self):
        Task.objects.create(
            team=self.team,
            title="Mine",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/mine",
        )

        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        Task.objects.create(
            team=other_team,
            title="Not mine",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            repository="posthog/not-mine",
        )

        response = self.client.get("/api/projects/@current/tasks/repositories/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repositories"], ["posthog/mine"])


class TestTaskInternalFilterAPI(BaseTaskAPITest):
    def setUp(self):
        super().setUp()
        self.external_task = self.create_task("External Task")
        self.internal_task = Task.objects.create(
            team=self.team,
            title="Internal Task",
            description="Internal Description",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=True,
        )

    def test_list_excludes_internal_tasks_by_default(self):
        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(self.external_task.id), task_ids)
        self.assertNotIn(str(self.internal_task.id), task_ids)

    def test_list_internal_true_shows_only_internal_tasks(self):
        # `internal=true` narrows to only-internal tasks for any team member — it's a visibility toggle,
        # not a staff/DEBUG gate (task visibility is the real access boundary).
        self.assertFalse(self.user.is_staff)
        with self.settings(DEBUG=False):
            response = self.client.get("/api/projects/@current/tasks/?internal=true")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        self.assertNotIn(str(self.external_task.id), task_ids)
        self.assertIn(str(self.internal_task.id), task_ids)

    def test_list_internal_false_excludes_internal_tasks(self):
        response = self.client.get("/api/projects/@current/tasks/?internal=false")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        task_ids = [t["id"] for t in data["results"]]
        self.assertIn(str(self.external_task.id), task_ids)
        self.assertNotIn(str(self.internal_task.id), task_ids)

    def test_list_internal_all_includes_both_for_non_staff(self):
        # `internal=all` surfaces internal tasks to any team member without a staff/DEBUG requirement —
        # the internal flag is a default-visibility toggle, not an access gate (task visibility is).
        self.assertFalse(self.user.is_staff)
        with self.settings(DEBUG=False):
            response = self.client.get("/api/projects/@current/tasks/?internal=all")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task_ids = [t["id"] for t in response.json()["results"]]
        self.assertIn(str(self.external_task.id), task_ids)
        self.assertIn(str(self.internal_task.id), task_ids)

    def test_internal_field_in_response(self):
        response = self.client.get(f"/api/projects/@current/tasks/{self.external_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["internal"])

    def test_retrieve_internal_task_by_id(self):
        response = self.client.get(f"/api/projects/@current/tasks/{self.internal_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["internal"])

    def test_internal_field_is_settable_on_create(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {"title": "Internal Task via API", "description": "Created as internal", "internal": True},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertTrue(response.json()["internal"])

    def test_internal_field_defaults_to_false_on_create(self):
        response = self.client.post(
            "/api/projects/@current/tasks/",
            {"title": "Normal Task", "description": "No internal flag"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["internal"])


class TestTaskSummariesAPI(BaseTaskAPITest):
    SUMMARIES_URL = "/api/projects/@current/tasks/summaries/"
    SUMMARY_FIELDS = {"id", "title", "repository", "created_at", "updated_at", "latest_run"}

    def post_summaries(self, ids):
        return self.client.post(self.SUMMARIES_URL, {"ids": ids}, format="json")

    def assertReturnsTaskIds(self, response, expected_ids):
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(
            sorted(t["id"] for t in response.json()["results"]),
            sorted(str(i) for i in expected_ids),
        )

    def test_summaries_returns_only_requested_ids_scoped_to_team(self):
        task_a = self.create_task("Task A")
        task_b = self.create_task("Task B")
        self.create_task("Task C")
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        other_task = Task.objects.create(
            team=other_team, title="Other", description="", origin_product=Task.OriginProduct.USER_CREATED
        )

        response = self.post_summaries([str(task_a.id), str(task_b.id), str(other_task.id), str(uuid.uuid4())])

        self.assertReturnsTaskIds(response, [task_a.id, task_b.id])

    def test_summaries_returns_internal_tasks_when_requested_by_id(self):
        internal_task = Task.objects.create(
            team=self.team,
            title="Internal",
            description="",
            origin_product=Task.OriginProduct.USER_CREATED,
            internal=True,
        )

        response = self.post_summaries([str(internal_task.id)])

        self.assertReturnsTaskIds(response, [internal_task.id])

    def test_summaries_latest_run_ignores_mismatched_run_team(self):
        task = self.create_task("Team-scoped summary run")
        other_team = Team.objects.create(organization=self.organization, name="Other Team")
        valid_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            environment=TaskRun.Environment.LOCAL,
        )
        TaskRun.objects.create(
            task=task,
            team=other_team,
            status=TaskRun.Status.IN_PROGRESS,
            environment=TaskRun.Environment.CLOUD,
        )

        response = self.post_summaries([str(task.id)])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        [payload] = response.json()["results"]
        self.assertEqual(
            payload["latest_run"],
            {"status": valid_run.status, "environment": valid_run.environment},
        )

    @parameterized.expand(
        [
            ("with_run", True),
            ("no_runs", False),
        ]
    )
    def test_summaries_response_shape(self, _name, with_run):
        task = self.create_task("Task")
        run = (
            TaskRun.objects.create(
                team=self.team,
                task=task,
                status=TaskRun.Status.IN_PROGRESS,
                environment=TaskRun.Environment.LOCAL,
            )
            if with_run
            else None
        )

        response = self.post_summaries([str(task.id)])

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        [payload] = response.json()["results"]
        self.assertEqual(set(payload.keys()), self.SUMMARY_FIELDS)
        expected_run = {"status": run.status, "environment": run.environment} if run else None
        self.assertEqual(payload["latest_run"], expected_run)

    def test_summaries_paginates_large_id_sets(self):
        tasks = [self.create_task(f"Task {i}") for i in range(3)]
        ids = [str(t.id) for t in tasks]

        response = self.client.post(f"{self.SUMMARIES_URL}?limit=2", {"ids": ids}, format="json")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["count"], 3)
        self.assertEqual(len(payload["results"]), 2)
        self.assertIsNotNone(payload["next"])

        # Follow `next` cursor; combined results should equal the full set without duplicates.
        next_url = payload["next"]
        next_path = next_url[next_url.index("/api/") :]
        response2 = self.client.post(next_path, {"ids": ids}, format="json")
        self.assertEqual(response2.status_code, status.HTTP_200_OK)
        payload2 = response2.json()
        self.assertEqual(len(payload2["results"]), 1)
        self.assertIsNone(payload2["next"])

        seen_ids = [r["id"] for r in payload["results"]] + [r["id"] for r in payload2["results"]]
        self.assertEqual(sorted(seen_ids), sorted(ids))
        self.assertEqual(len(set(seen_ids)), 3)

    @parameterized.expand(
        [
            ("empty", lambda: []),
            ("invalid_uuid", lambda: ["not-a-uuid"]),
        ]
    )
    def test_summaries_rejects_invalid_payload(self, _name, ids_factory):
        response = self.post_summaries(ids_factory())
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestTaskAutomationAPI(BaseTaskAPITest):
    @patch("products.tasks.backend.automation_service.sync_automation_schedule")
    def test_create_automation(self, mock_sync_schedule):
        response = self.client.post(
            "/api/projects/@current/task_automations/",
            {
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "Europe/London",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        payload = response.json()
        self.assertEqual(payload["name"], "Daily PRs")
        self.assertEqual(payload["repository"], "posthog/posthog")
        self.assertEqual(payload["cron_expression"], "0 9 * * *")
        self.assertEqual(payload["timezone"], "Europe/London")
        self.assertTrue(payload["enabled"])

        automation = TaskAutomation.objects.get(id=payload["id"])
        self.assertEqual(automation.task.title, "Daily PRs")
        self.assertEqual(automation.task.description, "Check my GitHub PRs")
        self.assertEqual(automation.task.repository, "posthog/posthog")
        self.assertEqual(automation.cron_expression, "0 9 * * *")
        mock_sync_schedule.assert_called_once_with(automation)

    def test_list_automations(self):
        automation = self.create_automation()

        response = self.client.get("/api/projects/@current/task_automations/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(len(payload["results"]), 1)
        self.assertEqual(payload["results"][0]["id"], str(automation.id))
        self.assertEqual(payload["results"][0]["cron_expression"], "0 9 * * *")

    def test_create_automation_rejects_invalid_timezone(self):
        response = self.client.post(
            "/api/projects/@current/task_automations/",
            {
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "UTC+99",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "'UTC+99' is not a valid IANA timezone.",
                "attr": "timezone",
            },
        )

    def test_create_automation_rejects_invalid_cron_expression(self):
        response = self.client.post(
            "/api/projects/@current/task_automations/",
            {
                "name": "Daily PRs",
                "prompt": "Check my GitHub PRs",
                "repository": "posthog/posthog",
                "cron_expression": "not a cron",
                "timezone": "Europe/London",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            response.json(),
            {
                "type": "validation_error",
                "code": "invalid_input",
                "detail": "Only standard 5-field cron expressions are supported "
                "(minute hour day month weekday). Example: '0 9 * * 1-5'.",
                "attr": "cron_expression",
            },
        )

    @patch("products.tasks.backend.facade.api._sync_automation_schedule")
    def test_create_automation_rolls_back_task_when_automation_create_fails(self, mock_sync_schedule):
        with patch(
            "products.tasks.backend.facade.api.TaskAutomation.objects.create",
            side_effect=RuntimeError("automation create failed"),
        ):
            with self.assertRaises(RuntimeError):
                tasks_facade.create_task_automation(
                    self.team.id,
                    self.user.id,
                    name="Daily PRs",
                    prompt="Check my GitHub PRs",
                    repository="posthog/posthog",
                    cron_expression="0 9 * * *",
                    timezone="Europe/London",
                )

        self.assertFalse(
            Task.objects.filter(
                team=self.team,
                title="Daily PRs",
                origin_product=Task.OriginProduct.AUTOMATION,
            ).exists()
        )

    @patch("products.tasks.backend.automation_service.sync_automation_schedule")
    def test_update_automation(self, mock_sync_schedule):
        automation = self.create_automation()

        response = self.client.patch(
            f"/api/projects/@current/task_automations/{automation.id}/",
            {
                "name": "Updated PR check",
                "cron_expression": "30 14 * * *",
                "enabled": False,
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        payload = response.json()
        self.assertEqual(payload["name"], "Updated PR check")
        self.assertEqual(payload["cron_expression"], "30 14 * * *")
        self.assertFalse(payload["enabled"])

        automation.refresh_from_db()
        automation.task.refresh_from_db()
        self.assertEqual(automation.task.title, "Updated PR check")
        self.assertEqual(automation.cron_expression, "30 14 * * *")
        self.assertFalse(automation.enabled)
        mock_sync_schedule.assert_called_once_with(automation)

    @patch("products.tasks.backend.facade.api._sync_automation_schedule")
    def test_update_automation_rolls_back_automation_when_task_update_fails(self, mock_sync_schedule):
        automation = self.create_automation()

        with patch.object(Task, "save", side_effect=RuntimeError("task update failed")):
            with self.assertRaises(RuntimeError):
                tasks_facade.update_task_automation(
                    automation.id,
                    self.team.id,
                    self.user.id,
                    name="Updated PR check",
                    cron_expression="30 14 * * *",
                )

        automation.refresh_from_db()
        automation.task.refresh_from_db()
        self.assertEqual(automation.cron_expression, "0 9 * * *")
        self.assertEqual(automation.task.title, "Daily PRs")

    @patch("products.tasks.backend.automation_service.delete_automation_schedule")
    def test_delete_automation(self, mock_delete_schedule):
        automation = self.create_automation()

        response = self.client.delete(f"/api/projects/@current/task_automations/{automation.id}/")

        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        mock_delete_schedule.assert_called_once()
        self.assertFalse(TaskAutomation.objects.filter(id=automation.id).exists())

    @patch("products.tasks.backend.automation_service.run_task_automation")
    def test_run(self, mock_run_task_automation):
        automation = self.create_automation()

        response = self.client.post(f"/api/projects/@current/task_automations/{automation.id}/run/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_run_task_automation.assert_called_once_with(str(automation.id))


class TestTaskRunAPI(BaseTaskAPITest):
    def test_list_runs_with_malformed_task_id_returns_404(self):
        # A non-UUID task id in the URL must 404, not 500 through the UUIDField filter.
        response = self.client.get("/api/projects/@current/tasks/not-a-uuid/runs/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    def test_update_run_status_publishes_stream_state_event(self, mock_signal, mock_publish_stream_state_event):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        mock_publish_stream_state_event.assert_called_once()

    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    def test_patch_cannot_mutate_protected_credential_state_keys(self, _mock_publish):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={
                "github_credential_source": "caller_token",
                "pr_authorship_mode": "user",
                "sandbox_id": "sb-real",
                "sandbox_cpu_cores": 2,
                "sandbox_memory_gb": 8,
                "sandbox_ttl_seconds": 1800,
                "inactivity_timeout_seconds": 600,
                "use_modal_directory_resume_snapshots": True,
                "snapshot_external_id": "im-real",
                "snapshot_kind": "directory",
                "snapshot_mount_path": "/tmp",
            },
        )

        # A caller cannot escalate to the creator's integration, flip authorship, repoint the
        # credential-propagation target at a sandbox they control, inflate the run's compute /
        # lifetime to provision an oversized, long-lived sandbox, or turn the run into a wizard run
        # (which would mint a write-scoped wizard token into the sandbox), change rollout
        # decisions, or change Modal resume snapshot metadata. Non-protected keys still merge.
        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {
                "state": {
                    "github_credential_source": "server_integration",
                    "pr_authorship_mode": "bot",
                    "sandbox_id": "sb-attacker",
                    "sandbox_cpu_cores": 128,
                    "sandbox_memory_gb": 512,
                    "sandbox_ttl_seconds": 86400,
                    "inactivity_timeout_seconds": 86400,
                    "wizard_config": {},
                    "use_modal_directory_resume_snapshots": False,
                    "snapshot_external_id": "im-attacker",
                    "snapshot_kind": "directory",
                    "snapshot_mount_path": "/tmp/workspace",
                    "scratch": "ok",
                }
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        assert run.state["github_credential_source"] == "caller_token"
        assert run.state["pr_authorship_mode"] == "user"
        assert run.state["sandbox_id"] == "sb-real"
        assert run.state["sandbox_cpu_cores"] == 2
        assert run.state["sandbox_memory_gb"] == 8
        assert run.state["sandbox_ttl_seconds"] == 1800
        assert run.state["inactivity_timeout_seconds"] == 600
        assert "wizard_config" not in run.state  # caller cannot mark a run as a wizard run
        assert run.state["use_modal_directory_resume_snapshots"] is True
        assert run.state["snapshot_external_id"] == "im-real"
        assert run.state["snapshot_kind"] == "directory"
        assert run.state["snapshot_mount_path"] == "/tmp"
        assert run.state["scratch"] == "ok"  # non-protected keys still merge

        # Nor can a caller remove a protected key to force a fallback or unguarded path.
        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {
                "state": {},
                "state_remove_keys": [
                    "github_credential_source",
                    "sandbox_id",
                    "use_modal_directory_resume_snapshots",
                    "snapshot_external_id",
                    "snapshot_kind",
                    "snapshot_mount_path",
                    "scratch",
                ],
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        assert run.state["github_credential_source"] == "caller_token"  # protected key survives removal
        assert run.state["sandbox_id"] == "sb-real"  # protected key survives removal
        assert run.state["use_modal_directory_resume_snapshots"] is True  # protected key survives removal
        assert run.state["snapshot_external_id"] == "im-real"  # protected key survives removal
        assert run.state["snapshot_kind"] == "directory"  # protected key survives removal
        assert run.state["snapshot_mount_path"] == "/tmp"  # protected key survives removal
        assert "scratch" not in run.state  # non-protected key removed

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    def test_update_run_status_to_completed_signals_workflow(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        call_args = mock_signal.call_args
        self.assertEqual(call_args[0][1], "completed")
        self.assertIsNone(call_args[0][2])

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.COMPLETED)
        self.assertIsNotNone(run.completed_at)

    @patch("products.tasks.backend.temporal.client.resume_task_in_cloud_workflow")
    def test_resume_in_cloud_rejects_user_authorship_without_github_identity_when_no_repo(self, mock_resume):
        task = self.create_task(created_by=self.user)
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            environment=TaskRun.Environment.LOCAL,
            status=TaskRun.Status.COMPLETED,
            state={"pr_authorship_mode": "user"},
        )

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/resume_in_cloud/")

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["code"], "github_authorization_required")
        run.refresh_from_db()
        self.assertEqual(run.environment, TaskRun.Environment.LOCAL)
        self.assertEqual(run.status, TaskRun.Status.COMPLETED)
        mock_resume.assert_not_called()

    @patch("products.tasks.backend.temporal.client.resume_task_in_cloud_workflow")
    def test_resume_in_cloud_persists_user_integration_when_no_repo(self, mock_resume):
        task = self.create_task(created_by=self.user)
        user_integration = _grant_user_github_access(self.user)
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            environment=TaskRun.Environment.LOCAL,
            status=TaskRun.Status.COMPLETED,
            state={"pr_authorship_mode": "user"},
        )

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/resume_in_cloud/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(task.github_user_integration_id, user_integration.id)
        self.assertEqual(run.environment, TaskRun.Environment.CLOUD)
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        mock_resume.assert_called_once_with(str(run.id), run.workflow_id)

    @patch("products.tasks.backend.temporal.client.resume_task_in_cloud_workflow")
    def test_resume_in_cloud_falls_back_to_team_integration_when_no_user_integration(self, mock_resume):
        integration = Integration.objects.create(team=self.team, kind="github", config={"access_token": "token"})
        task = self.create_task(created_by=self.user)
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            environment=TaskRun.Environment.LOCAL,
            status=TaskRun.Status.COMPLETED,
            state={"pr_authorship_mode": "user"},
        )

        response = self.client.post(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/resume_in_cloud/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task.refresh_from_db()
        run.refresh_from_db()
        self.assertEqual(task.github_integration_id, integration.id)
        self.assertIsNone(task.github_user_integration_id)
        self.assertEqual(run.state["pr_authorship_mode"], "bot")
        self.assertEqual(run.environment, TaskRun.Environment.CLOUD)
        self.assertEqual(run.status, TaskRun.Status.QUEUED)
        mock_resume.assert_called_once_with(str(run.id), run.workflow_id)

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    def test_update_run_status_to_failed_signals_workflow_with_error(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "failed", "error_message": "Something went wrong"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        call_args = mock_signal.call_args
        self.assertEqual(call_args[0][1], "failed")
        self.assertEqual(call_args[0][2], "Something went wrong")

        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.FAILED)
        self.assertEqual(run.error_message, "Something went wrong")

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    def test_update_run_status_to_cancelled_signals_workflow(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "cancelled"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_called_once()
        call_args = mock_signal.call_args
        self.assertEqual(call_args[0][1], "cancelled")

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    @patch("products.tasks.backend.push_dispatcher.notify_task_run_cancelled")
    def test_update_run_status_to_cancelled_triggers_push(self, mock_notify, _mock_signal):
        """Cancellation only flows through the API PATCH path — mark_completed / mark_failed
        cover the other terminal transitions. A regression that removes this hook would go
        undetected without an integration test here."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "cancelled"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_notify.assert_called_once()
        self.assertEqual(str(mock_notify.call_args.args[0].id), str(run.id))

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    @patch("products.tasks.backend.push_dispatcher.notify_task_run_cancelled")
    def test_update_run_status_to_non_cancelled_terminal_does_not_trigger_cancel_push(self, mock_notify, _mock_signal):
        """Sanity check: a PATCH to completed/failed must NOT fire the cancelled push."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_notify.assert_not_called()

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    def test_update_run_non_terminal_status_does_not_signal(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "in_progress"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_not_called()

    @patch("products.tasks.backend.facade.api.signal_workflow_completion")
    def test_update_run_same_terminal_status_does_not_signal(self, mock_signal):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"status": "completed"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_signal.assert_not_called()

    def test_list_runs_for_task(self):
        task = self.create_task()

        run1 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
        )

        run2 = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
        )

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 2)
        run_ids = [r["id"] for r in data["results"]]
        self.assertIn(str(run1.id), run_ids)
        self.assertIn(str(run2.id), run_ids)

    def test_retrieve_specific_run(self):
        task = self.create_task()

        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        # Add some logs to S3
        run.append_log([{"type": "info", "message": "Test log output"}])

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(data["id"], str(run.id))
        self.assertEqual(data["status"], "in_progress")
        # Verify log_url is returned (S3 presigned URL)
        self.assertIn("log_url", data)
        self.assertIsNotNone(data["log_url"])
        self.assertTrue(data["log_url"].startswith("http"))

    def test_list_runs_only_returns_task_runs(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        run1 = TaskRun.objects.create(task=task1, team=self.team, status=TaskRun.Status.QUEUED)
        _run2 = TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.get(f"/api/projects/@current/tasks/{task1.id}/runs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data["results"]), 1)
        self.assertEqual(data["results"][0]["id"], str(run1.id))

    def test_retrieve_run_from_different_task_fails(self):
        task1 = self.create_task("Task 1")
        task2 = self.create_task("Task 2")

        run2 = TaskRun.objects.create(task=task2, team=self.team, status=TaskRun.Status.QUEUED)

        response = self.client.get(f"/api/projects/@current/tasks/{task1.id}/runs/{run2.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_append_log_entries(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {
                "entries": [
                    {"type": "info", "message": "Starting task"},
                    {"type": "progress", "message": "Step 1 complete"},
                ]
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        run.refresh_from_db()

        # Verify logs are stored in S3
        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        # Parse newline-delimited JSON
        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 2)
        self.assertEqual(log_entries[0]["type"], "info")
        self.assertEqual(log_entries[0]["message"], "Starting task")
        self.assertEqual(log_entries[1]["type"], "progress")
        self.assertEqual(log_entries[1]["message"], "Step 1 complete")

    @patch("products.tasks.backend.temporal.process_task.activities.post_slack_update.post_slack_update")
    def test_set_output_with_pr_url_posts_slack_update_when_mapping_exists(self, mock_post_slack_update):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/1"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_post_slack_update.assert_called_once()
        input_arg = mock_post_slack_update.call_args[0][0]
        self.assertEqual(input_arg.run_id, str(run.id))
        self.assertEqual(input_arg.slack_thread_context["integration_id"], integration.pk)
        self.assertEqual(input_arg.slack_thread_context["channel"], "C123")
        self.assertEqual(input_arg.slack_thread_context["thread_ts"], "1234.5678")

    @patch("products.tasks.backend.models.TaskRun.publish_stream_state_event")
    def test_set_output_publishes_stream_state_event(self, mock_publish_stream_state_event):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/set_output/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/1"}},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_publish_stream_state_event.assert_called_once()

    @patch("products.tasks.backend.temporal.process_task.activities.post_slack_update.post_slack_update")
    def test_partial_update_with_pr_url_posts_slack_update_when_mapping_exists(self, mock_post_slack_update):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})

        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/2"}, "status": "in_progress"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_post_slack_update.assert_called_once()
        input_arg = mock_post_slack_update.call_args[0][0]
        self.assertEqual(input_arg.run_id, str(run.id))
        self.assertEqual(input_arg.slack_thread_context["integration_id"], integration.pk)

    def test_partial_update_merges_output_dict(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            output={"head_branch": "posthog-code/update-readme"},
        )

        response = self.client.patch(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
            {"output": {"pr_url": "https://github.com/org/repo/pull/2"}},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(
            run.output,
            {
                "head_branch": "posthog-code/update-readme",
                "pr_url": "https://github.com/org/repo/pull/2",
            },
        )

    def test_partial_update_does_not_restore_stale_state(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={
                "mode": "interactive",
                "pending_user_message": "read the attachment",
                "pending_user_artifact_ids": ["artifact-123"],
            },
        )
        stale_run = TaskRun.objects.get(id=run.id)

        TaskRun.update_state_atomic(
            run.id,
            updates={"sandbox_id": "sandbox-123"},
            remove_keys=["pending_user_message", "pending_user_artifact_ids"],
        )

        with patch("products.tasks.backend.presentation.views.api.TaskRunViewSet.get_object", return_value=stale_run):
            response = self.client.patch(
                f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
                {"stage": "executing"},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(run.stage, "executing")
        self.assertEqual(run.state["mode"], "interactive")
        self.assertEqual(run.state["sandbox_id"], "sandbox-123")
        self.assertNotIn("pending_user_message", run.state)
        self.assertNotIn("pending_user_artifact_ids", run.state)

    def test_partial_update_state_remove_keys_is_atomic(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={
                "mode": "interactive",
                "pending_user_message": "read the attachment",
                "pending_user_artifact_ids": ["artifact-123"],
            },
        )
        stale_run = TaskRun.objects.get(id=run.id)

        TaskRun.update_state_atomic(
            run.id,
            updates={"sandbox_id": "sandbox-123"},
        )

        with patch("products.tasks.backend.presentation.views.api.TaskRunViewSet.get_object", return_value=stale_run):
            response = self.client.patch(
                f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/",
                {"state_remove_keys": ["pending_user_message", "pending_user_artifact_ids"]},
                format="json",
            )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        run.refresh_from_db()
        self.assertEqual(run.state["mode"], "interactive")
        self.assertEqual(run.state["sandbox_id"], "sandbox-123")
        self.assertNotIn("pending_user_message", run.state)
        self.assertNotIn("pending_user_artifact_ids", run.state)

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_enqueues_slack_relay_workflow(self, mock_execute_relay):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        mock_execute_relay.return_value = "relay-1"

        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )
        mock_execute_relay.return_value = "relay-1"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "Which license should I use?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "accepted", "relay_id": "relay-1"})
        mock_execute_relay.assert_called_once_with(
            run_id=str(run.id),
            text="Which license should I use?",
            delete_progress=True,
        )

    @parameterized.expand(
        [
            (
                "prefers_last_non_empty_text_part",
                {
                    "text": "I'll pull DAU.\n\nHere's your answer.",
                    "text_parts": ["I'll pull DAU.", "Here's your answer."],
                },
                "Here's your answer.",
            ),
            (
                "falls_back_to_text_when_parts_only_blank",
                {"text": "actual message", "text_parts": ["", "   "]},
                "actual message",
            ),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_text_selection(self, _name, payload, expected_posted_text, mock_execute_relay):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        mock_execute_relay.return_value = "relay-selected"

        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_execute_relay.assert_called_once_with(
            run_id=str(run.id),
            text=expected_posted_text,
            delete_progress=True,
        )

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_skips_when_no_slack_mapping(self, mock_execute_relay):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "Which license should I use?"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "skipped"})
        mock_execute_relay.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_skips_for_terminal_run(self, mock_execute_relay):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "Done"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json(), {"status": "skipped"})
        mock_execute_relay.assert_not_called()

    @patch("products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow")
    def test_relay_message_rejects_blank_text(self, mock_execute_relay):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "   "},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        mock_execute_relay.assert_not_called()

    @patch(
        "products.tasks.backend.temporal.client.execute_posthog_code_agent_relay_workflow",
        side_effect=Exception("temporal down"),
    )
    def test_relay_message_returns_503_on_enqueue_failure(self, mock_execute_relay):
        from posthog.models.integration import Integration

        from products.slack_app.backend.models import SlackThreadTaskMapping

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        integration = Integration.objects.create(team=self.team, kind="slack", integration_id="T_SLACK", config={})
        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C123",
            thread_ts="1234.5678",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U123",
        )

        SlackThreadTaskMapping.objects.create(
            team=self.team,
            integration=integration,
            slack_workspace_id="T_SLACK",
            channel="C456",
            thread_ts="5678.1234",
            task=task,
            task_run=run,
            mentioning_slack_user_id="U456",
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/relay_message/",
            {"text": "hello"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_503_SERVICE_UNAVAILABLE)
        self.assertIn("error", response.json())

    def test_append_log_to_existing_entries(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        # Add first batch
        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "info", "message": "Initial entry"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        # Add second batch
        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "success", "message": "Task completed"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        run.refresh_from_db()

        # All logs should be stored in S3
        assert run.log_url is not None
        log_content = object_storage.read(run.log_url)
        assert log_content is not None

        # Parse newline-delimited JSON
        log_entries = [json.loads(line) for line in log_content.strip().split("\n")]
        self.assertEqual(len(log_entries), 2)
        self.assertEqual(log_entries[0]["message"], "Initial entry")
        self.assertEqual(log_entries[1]["message"], "Task completed")

    def test_append_log_empty_entries_fails(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": []},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.models.TaskRun.heartbeat_workflow")
    def test_append_log_calls_heartbeat_workflow(self, mock_heartbeat):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/append_log/",
            {"entries": [{"type": "info", "message": "hello"}]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        mock_heartbeat.assert_called_once_with(agent_active=True)

    @patch("posthog.storage.object_storage.write")
    @patch("posthog.storage.object_storage.tag")
    def test_upload_artifacts(self, mock_tag, mock_write):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        payload = {
            "artifacts": [
                {
                    "name": "plan.md",
                    "type": "plan",
                    "content": "# Plan",
                    "content_type": "text/markdown",
                }
            ]
        }

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_write.assert_called_once()
        mock_tag.assert_called_once()

        run.refresh_from_db()
        self.assertEqual(len(run.artifacts), 1)
        artifact = run.artifacts[0]
        self.assertIn("id", artifact)
        self.assertEqual(artifact["name"], "plan.md")
        self.assertEqual(artifact["type"], "plan")
        self.assertEqual(artifact["source"], "")
        self.assertIn("storage_path", artifact)
        self.assertIn(f"tasks/artifacts/team_{self.team.id}/task_{task.id}/run_{run.id}/", artifact["storage_path"])

    @patch("posthog.storage.object_storage.write")
    @patch("posthog.storage.object_storage.tag")
    def test_upload_artifacts_accepts_base64_content(self, mock_tag, mock_write):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        binary_content = b"\x00\xffbinary"

        payload = {
            "artifacts": [
                {
                    "name": "bundle.zip",
                    "type": "user_attachment",
                    "source": "user_attachment",
                    "content": base64.b64encode(binary_content).decode("ascii"),
                    "content_encoding": "base64",
                    "content_type": "application/zip",
                }
            ]
        }

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_write.assert_called_once()
        write_call = mock_write.call_args
        self.assertEqual(write_call.args[1], binary_content)
        self.assertEqual(write_call.args[2], {"ContentType": "application/zip"})
        mock_tag.assert_called_once()

        run.refresh_from_db()
        artifact = run.artifacts[0]
        self.assertEqual(artifact["name"], "bundle.zip")
        self.assertEqual(artifact["type"], "user_attachment")
        self.assertEqual(artifact["source"], "user_attachment")
        self.assertEqual(artifact["size"], len(binary_content))

    @patch("posthog.storage.object_storage.write")
    @patch("posthog.storage.object_storage.tag")
    def test_upload_artifacts_preserves_skill_bundle_metadata(self, mock_tag, mock_write):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        binary_content = b"skill zip"
        metadata = {
            "skill_name": "local-skill",
            "skill_source": "user",
            "content_sha256": "a" * 64,
            "bundle_format": "zip",
            "schema_version": 1,
        }

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {
                "artifacts": [
                    {
                        "name": "local-skill.zip",
                        "type": "skill_bundle",
                        "source": "posthog_code_skill",
                        "content": base64.b64encode(binary_content).decode("ascii"),
                        "content_encoding": "base64",
                        "content_type": "application/zip",
                        "metadata": metadata,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_write.assert_called_once()
        mock_tag.assert_called_once()

        run.refresh_from_db()
        artifact = run.artifacts[0]
        self.assertEqual(artifact["type"], "skill_bundle")
        self.assertEqual(artifact["metadata"], metadata)

    def test_upload_artifacts_rejects_skill_bundle_without_metadata(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {
                "artifacts": [
                    {
                        "name": "local-skill.zip",
                        "type": "skill_bundle",
                        "source": "posthog_code_skill",
                        "content": "c2tpbGw=",
                        "content_encoding": "base64",
                        "content_type": "application/zip",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("metadata", json.dumps(response.json()))

    def test_upload_artifacts_rejects_invalid_base64_content(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {
                "artifacts": [
                    {
                        "name": "broken.bin",
                        "type": "user_attachment",
                        "content": "%%%not-base64%%%",
                        "content_encoding": "base64",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_upload_artifacts_rejects_oversized_pdf_content(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        oversized_pdf = b"a" * (TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES + 1)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {
                "artifacts": [
                    {
                        "name": "large.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "content": base64.b64encode(oversized_pdf).decode("ascii"),
                        "content_encoding": "base64",
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("10MB attachment limit for PDFs", json.dumps(response.json()))

    def test_upload_artifacts_requires_items(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/",
            {"artifacts": []},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("posthog.storage.object_storage.get_presigned_post")
    def test_prepare_artifact_uploads(self, mock_get_presigned_post):
        mock_get_presigned_post.return_value = {
            "url": "https://example-bucket.s3.amazonaws.com",
            "fields": {"key": "placeholder", "policy": "policy", "x-amz-signature": "sig"},
        }
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "size": 4096,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(len(data["artifacts"]), 1)
        prepared = data["artifacts"][0]
        self.assertIn("id", prepared)
        self.assertEqual(prepared["name"], "spec.pdf")
        self.assertEqual(prepared["type"], "user_attachment")
        self.assertEqual(prepared["source"], "user_attachment")
        self.assertEqual(prepared["size"], 4096)
        self.assertEqual(prepared["content_type"], "application/pdf")
        self.assertIn(f"tasks/artifacts/team_{self.team.id}/task_{task.id}/run_{run.id}/", prepared["storage_path"])
        self.assertEqual(prepared["presigned_post"]["url"], "https://example-bucket.s3.amazonaws.com")
        self.assertIn("expires_in", prepared)

        self.assertEqual(mock_get_presigned_post.call_args.args[0], prepared["storage_path"])
        get_presigned_post_kwargs = mock_get_presigned_post.call_args.kwargs
        self.assertEqual(get_presigned_post_kwargs["expiration"], 3600)
        self.assertEqual(get_presigned_post_kwargs["conditions"], [["content-length-range", 0, 4096 + 65536]])

    @patch("posthog.storage.object_storage.get_presigned_post")
    def test_prepare_artifact_uploads_preserves_skill_bundle_metadata(self, mock_get_presigned_post):
        mock_get_presigned_post.return_value = {
            "url": "https://example-bucket.s3.amazonaws.com",
            "fields": {"key": "placeholder", "policy": "policy", "x-amz-signature": "sig"},
        }
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        metadata = {
            "skill_name": "local-skill",
            "skill_source": "repo",
            "content_sha256": "b" * 64,
            "bundle_format": "zip",
            "schema_version": 1,
        }

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "local-skill.zip",
                        "type": "skill_bundle",
                        "source": "posthog_code_skill",
                        "size": 4096,
                        "content_type": "application/zip",
                        "metadata": metadata,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prepared = response.json()["artifacts"][0]
        self.assertEqual(prepared["type"], "skill_bundle")
        self.assertEqual(prepared["metadata"], metadata)

    def test_prepare_artifact_uploads_rejects_oversized_size(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "huge.bin",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "size": TASK_RUN_ARTIFACT_MAX_SIZE_BYTES + 1,
                        "content_type": "application/octet-stream",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_prepare_artifact_uploads_rejects_oversized_pdf_size(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "large.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "size": TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES + 1,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("10MB attachment limit for PDFs", json.dumps(response.json()))

    def test_prepare_staged_artifact_uploads_rejects_oversized_size(self):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "huge.bin",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "size": TASK_RUN_ARTIFACT_MAX_SIZE_BYTES + 1,
                        "content_type": "application/octet-stream",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_prepare_staged_artifact_uploads_rejects_oversized_pdf_size(self):
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "large.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "size": TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES + 1,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("10MB attachment limit for PDFs", json.dumps(response.json()))

    @patch("posthog.storage.object_storage.get_presigned_post")
    def test_prepare_staged_artifact_uploads(self, mock_get_presigned_post):
        mock_get_presigned_post.return_value = {
            "url": "https://example-bucket.s3.amazonaws.com",
            "fields": {"key": "placeholder", "policy": "policy", "x-amz-signature": "sig"},
        }
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/prepare_upload/",
            {
                "artifacts": [
                    {
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "size": 4096,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        prepared = response.json()["artifacts"][0]
        self.assertEqual(prepared["name"], "spec.pdf")
        self.assertEqual(prepared["type"], "user_attachment")
        self.assertEqual(prepared["source"], "user_attachment")
        self.assertNotIn("metadata", prepared)
        self.assertIn(f"tasks/artifacts/team_{self.team.id}/task_{task.id}/staged/", prepared["storage_path"])
        self.assertEqual(mock_get_presigned_post.call_args.args[0], prepared["storage_path"])

    @patch("posthog.storage.object_storage.head_object")
    @patch("posthog.storage.object_storage.tag")
    def test_finalize_staged_artifact_uploads(self, mock_tag, mock_head_object):
        mock_head_object.return_value = {"ContentLength": 4096, "ContentType": "application/pdf"}
        task = self.create_task()
        artifact_id = uuid.uuid4().hex
        storage_path = f"tasks/artifacts/team_{self.team.id}/task_{task.id}/staged/{artifact_id}/spec.pdf"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": storage_path,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_head_object.assert_called_once_with(storage_path)
        mock_tag.assert_called_once()
        finalized_artifact = response.json()["artifacts"][0]
        self.assertEqual(finalized_artifact["id"], artifact_id)
        cached_artifacts, missing_artifact_ids = get_task_staged_artifacts(task, [artifact_id])
        self.assertEqual(missing_artifact_ids, [])
        self.assertEqual(cached_artifacts, [finalized_artifact])

    @patch("posthog.storage.object_storage.head_object")
    def test_finalize_staged_artifact_uploads_rejects_invalid_storage_path(self, mock_head_object):
        task = self.create_task()
        artifact_id = uuid.uuid4().hex

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": f"tasks/artifacts/team_{self.team.id}/task_other/staged/{artifact_id}/spec.pdf",
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Artifact storage path is invalid for this task")
        mock_head_object.assert_not_called()

    @patch("posthog.storage.object_storage.head_object")
    @patch("posthog.storage.object_storage.tag")
    def test_finalize_staged_artifact_uploads_is_atomic_for_partial_failures(self, mock_tag, mock_head_object):
        mock_head_object.side_effect = [
            {"ContentLength": 4096, "ContentType": "application/pdf"},
            None,
        ]
        task = self.create_task()
        artifact_id_1 = uuid.uuid4().hex
        artifact_id_2 = uuid.uuid4().hex

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/staged_artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id_1,
                        "name": "one.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": (
                            f"tasks/artifacts/team_{self.team.id}/task_{task.id}/staged/{artifact_id_1}/one.pdf"
                        ),
                        "content_type": "application/pdf",
                    },
                    {
                        "id": artifact_id_2,
                        "name": "two.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": (
                            f"tasks/artifacts/team_{self.team.id}/task_{task.id}/staged/{artifact_id_2}/two.pdf"
                        ),
                        "content_type": "application/pdf",
                    },
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        cached_artifacts, missing_artifact_ids = get_task_staged_artifacts(task, [artifact_id_1, artifact_id_2])
        self.assertEqual(cached_artifacts, [])
        self.assertEqual(sorted(missing_artifact_ids), sorted([artifact_id_1, artifact_id_2]))
        mock_tag.assert_not_called()

    @patch("posthog.storage.object_storage.head_object")
    @patch("posthog.storage.object_storage.tag")
    def test_finalize_artifact_uploads(self, mock_tag, mock_head_object):
        mock_head_object.return_value = {"ContentLength": 4096, "ContentType": "application/pdf"}
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        artifact_id = uuid.uuid4().hex
        storage_path = f"{run.get_artifact_s3_prefix()}/{artifact_id[:8]}_spec.pdf"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": storage_path,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_head_object.assert_called_once_with(storage_path)
        mock_tag.assert_called_once()

        run.refresh_from_db()
        self.assertEqual(len(run.artifacts), 1)
        artifact = run.artifacts[0]
        self.assertEqual(artifact["id"], artifact_id)
        self.assertEqual(artifact["name"], "spec.pdf")
        self.assertEqual(artifact["type"], "user_attachment")
        self.assertEqual(artifact["source"], "user_attachment")
        self.assertEqual(artifact["size"], 4096)
        self.assertEqual(artifact["content_type"], "application/pdf")
        self.assertEqual(artifact["storage_path"], storage_path)

    @patch("posthog.storage.object_storage.head_object")
    def test_finalize_artifact_uploads_rejects_invalid_storage_path(self, mock_head_object):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        artifact_id = uuid.uuid4().hex

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": f"{run.get_artifact_s3_prefix()}/wrong-prefix_spec.pdf",
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Artifact storage path is invalid for this run")
        mock_head_object.assert_not_called()

    @patch("posthog.storage.object_storage.head_object")
    @patch("products.tasks.backend.logic.services.staged_artifacts.tag_task_artifact")
    def test_finalize_artifact_uploads_returns_only_newly_finalized(self, mock_tag, mock_head_object):
        mock_head_object.return_value = {"ContentLength": 4096, "ContentType": "application/pdf"}
        task = self.create_task()
        existing_artifact_id = uuid.uuid4().hex
        existing_storage_path = (
            f"tasks/artifacts/team_{self.team.id}/task_{task.id}/runs/run/{existing_artifact_id[:8]}_previous.pdf"
        )
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[
                {
                    "id": existing_artifact_id,
                    "name": "previous.pdf",
                    "type": "user_attachment",
                    "storage_path": existing_storage_path,
                }
            ],
        )
        new_artifact_id = uuid.uuid4().hex
        new_storage_path = f"{run.get_artifact_s3_prefix()}/{new_artifact_id[:8]}_new.pdf"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": new_artifact_id,
                        "name": "new.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": new_storage_path,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        returned_ids = [artifact["id"] for artifact in response.json()["artifacts"]]
        self.assertEqual(returned_ids, [new_artifact_id])

        run.refresh_from_db()
        stored_ids = [artifact["id"] for artifact in run.artifacts]
        self.assertEqual(sorted(stored_ids), sorted([existing_artifact_id, new_artifact_id]))

    @patch("posthog.storage.object_storage.head_object")
    @patch("products.tasks.backend.logic.services.staged_artifacts.tag_task_artifact")
    def test_finalize_artifact_uploads_is_idempotent_for_existing_entry(self, mock_tag, mock_head_object):
        task = self.create_task()
        artifact_id = uuid.uuid4().hex
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        storage_path = f"{run.get_artifact_s3_prefix()}/{artifact_id[:8]}_spec.pdf"
        run.artifacts = [
            {
                "id": artifact_id,
                "name": "spec.pdf",
                "type": "user_attachment",
                "source": "user_attachment",
                "size": 4096,
                "content_type": "application/pdf",
                "storage_path": storage_path,
                "uploaded_at": django_timezone.now().isoformat(),
            }
        ]
        run.save(update_fields=["artifacts", "updated_at"])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "spec.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": storage_path,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["artifacts"], run.artifacts)
        mock_head_object.assert_not_called()
        mock_tag.assert_not_called()

    @patch("posthog.storage.object_storage.head_object")
    def test_finalize_artifact_uploads_rejects_missing_object(self, mock_head_object):
        mock_head_object.return_value = None
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        artifact_id = uuid.uuid4().hex
        storage_path = f"{run.get_artifact_s3_prefix()}/{artifact_id[:8]}_missing.pdf"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "missing.pdf",
                        "type": "user_attachment",
                        "storage_path": storage_path,
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Artifact upload not found in object storage")

    @patch("posthog.storage.object_storage.head_object")
    def test_finalize_artifact_uploads_rejects_oversized_pdf(self, mock_head_object):
        mock_head_object.return_value = {
            "ContentLength": TASK_RUN_PDF_ARTIFACT_MAX_SIZE_BYTES + 1,
            "ContentType": "application/pdf",
        }
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        artifact_id = uuid.uuid4().hex
        storage_path = f"{run.get_artifact_s3_prefix()}/{artifact_id[:8]}_large.pdf"

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id,
                        "name": "large.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": storage_path,
                        "content_type": "application/pdf",
                    }
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("10MB attachment limit for PDFs", response.json()["error"])

    @patch("posthog.storage.object_storage.head_object")
    @patch("products.tasks.backend.logic.services.staged_artifacts.tag_task_artifact")
    def test_finalize_artifact_uploads_is_atomic_for_partial_failures(self, mock_tag, mock_head_object):
        mock_head_object.side_effect = [
            {"ContentLength": 4096, "ContentType": "application/pdf"},
            None,
        ]
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, artifacts=[])
        artifact_id_1 = uuid.uuid4().hex
        artifact_id_2 = uuid.uuid4().hex

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/finalize_upload/",
            {
                "artifacts": [
                    {
                        "id": artifact_id_1,
                        "name": "one.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": f"{run.get_artifact_s3_prefix()}/{artifact_id_1[:8]}_one.pdf",
                        "content_type": "application/pdf",
                    },
                    {
                        "id": artifact_id_2,
                        "name": "two.pdf",
                        "type": "user_attachment",
                        "source": "user_attachment",
                        "storage_path": f"{run.get_artifact_s3_prefix()}/{artifact_id_2[:8]}_two.pdf",
                        "content_type": "application/pdf",
                    },
                ]
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        run.refresh_from_db()
        self.assertEqual(run.artifacts, [])
        mock_tag.assert_not_called()

    @patch("posthog.storage.object_storage.get_presigned_url")
    def test_presign_artifact_url(self, mock_presign):
        mock_presign.return_value = "https://example.com/artifact?sig=123"
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[
                {
                    "name": "plan.md",
                    "type": "plan",
                    "storage_path": "tasks/artifacts/team_1/task_2/run_3/plan.md",
                }
            ],
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/presign/",
            {"storage_path": "tasks/artifacts/team_1/task_2/run_3/plan.md"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["url"], "https://example.com/artifact?sig=123")
        self.assertIn("expires_in", response.json())

    def test_presign_artifact_not_found(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, artifacts=[])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/presign/",
            {"storage_path": "unknown"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("posthog.storage.object_storage.read_bytes")
    def test_download_artifact_content(self, mock_read_bytes):
        mock_read_bytes.return_value = b"artifact bytes"
        task = self.create_task()
        storage_path = "tasks/artifacts/team_1/task_2/run_3/plan.md"
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[
                {
                    "id": uuid.uuid4().hex,
                    "name": "plan.md",
                    "type": "plan",
                    "content_type": "text/markdown",
                    "storage_path": storage_path,
                }
            ],
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/download/",
            {"storage_path": storage_path},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"artifact bytes")
        self.assertEqual(response["Content-Type"], "text/markdown")
        self.assertIn('attachment; filename="plan.md"', response["Content-Disposition"])
        mock_read_bytes.assert_called_once_with(storage_path, missing_ok=True)

    def test_download_artifact_not_found(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS, artifacts=[])

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/download/",
            {"storage_path": "unknown"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("posthog.storage.object_storage.read_bytes")
    def test_download_artifact_missing_content(self, mock_read_bytes):
        mock_read_bytes.return_value = None
        task = self.create_task()
        storage_path = "tasks/artifacts/team_1/task_2/run_3/missing.md"
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[
                {
                    "id": uuid.uuid4().hex,
                    "name": "missing.md",
                    "type": "plan",
                    "storage_path": storage_path,
                }
            ],
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/artifacts/download/",
            {"storage_path": storage_path},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    @patch("posthog.storage.object_storage.read_bytes")
    def test_download_artifact_walks_resume_chain(self, mock_read_bytes):
        """A resumed run can download an artifact owned by the run it was forked from.

        Cloud→cloud resume creates a new TaskRun with state.resume_from_run_id pointing
        to the prior run; the prior run owns the git checkpoint pack/index artifacts.
        """
        mock_read_bytes.return_value = b"prior run pack bytes"
        task = self.create_task()
        prior_storage_path = "tasks/artifacts/team_1/task_x/run_prior/abc_pack.pack"

        prior_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.COMPLETED,
            artifacts=[
                {
                    "id": uuid.uuid4().hex,
                    "name": "checkpoint.pack",
                    "type": "artifact",
                    "content_type": "application/x-git-packed-objects",
                    "storage_path": prior_storage_path,
                }
            ],
        )
        new_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[],
            state={"resume_from_run_id": str(prior_run.id)},
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{new_run.id}/artifacts/download/",
            {"storage_path": prior_storage_path},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content, b"prior run pack bytes")
        mock_read_bytes.assert_called_once_with(prior_storage_path, missing_ok=True)

    def test_find_artifact_in_resume_chain_direct_hit(self):
        """Finds artifact on the run itself without walking the chain."""

        task = self.create_task()
        storage_path = "tasks/artifacts/team_1/task_x/run_a/artifact.pack"
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            artifacts=[{"id": "a", "name": "artifact.pack", "storage_path": storage_path}],
        )

        artifact = run.find_artifact_in_resume_chain(storage_path)
        self.assertIsNotNone(artifact)
        self.assertEqual(artifact["storage_path"], storage_path)  # type: ignore

    def test_find_artifact_in_resume_chain_miss(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, artifacts=[])
        self.assertIsNone(run.find_artifact_in_resume_chain("tasks/missing.pack"))

    def test_find_artifact_in_resume_chain_walks_one_hop(self):
        task = self.create_task()
        storage_path = "tasks/artifacts/team_1/task_x/run_prior/artifact.pack"
        prior_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[{"id": "a", "name": "artifact.pack", "storage_path": storage_path}],
        )
        new_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[],
            state={"resume_from_run_id": str(prior_run.id)},
        )

        artifact = new_run.find_artifact_in_resume_chain(storage_path)
        self.assertIsNotNone(artifact)

    def test_find_artifact_in_resume_chain_walks_multiple_hops(self):
        """Resumed-from-resumed-from chain still resolves."""

        task = self.create_task()
        storage_path = "tasks/artifacts/team_1/task_x/run_root/artifact.pack"
        root_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[{"id": "a", "name": "artifact.pack", "storage_path": storage_path}],
        )
        middle_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[],
            state={"resume_from_run_id": str(root_run.id)},
        )
        new_run = TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[],
            state={"resume_from_run_id": str(middle_run.id)},
        )

        artifact = new_run.find_artifact_in_resume_chain(storage_path)
        self.assertIsNotNone(artifact)

    def test_find_artifact_in_resume_chain_handles_cycle(self):
        """A self-referencing or circular resume chain doesn't loop forever."""

        task = self.create_task()
        run_a = TaskRun.objects.create(task=task, team=self.team, artifacts=[])
        run_b = TaskRun.objects.create(
            task=task,
            team=self.team,
            artifacts=[],
            state={"resume_from_run_id": str(run_a.id)},
        )
        # Patch run_a to point back at run_b — circular.
        run_a.state = {"resume_from_run_id": str(run_b.id)}
        run_a.save(update_fields=["state"])

        result = run_b.find_artifact_in_resume_chain("tasks/missing.pack")
        self.assertIsNone(result)

    def test_find_artifact_in_resume_chain_does_not_cross_tasks(self):
        """Resume chain lookup is scoped to the same task — sibling tasks are invisible."""

        task_a = self.create_task(title="A")
        task_b = self.create_task(title="B")
        storage_path = "tasks/artifacts/team_1/task_a/run/artifact.pack"

        prior_run_on_a = TaskRun.objects.create(
            task=task_a,
            team=self.team,
            artifacts=[{"id": "a", "name": "artifact.pack", "storage_path": storage_path}],
        )
        # Run on task B references a run from task A — should not resolve.
        run_on_b = TaskRun.objects.create(
            task=task_b,
            team=self.team,
            artifacts=[],
            state={"resume_from_run_id": str(prior_run_on_a.id)},
        )

        self.assertIsNone(run_on_b.find_artifact_in_resume_chain(storage_path))

    def test_walk_resume_chain_single_run(self):
        """A run with no resume_from_run_id resolves to a 1-element chain."""

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team)

        chain = run.get_resume_chain()
        self.assertEqual([r.id for r in chain], [run.id])

    def test_walk_resume_chain_multi_hop_ordered_oldest_first(self):
        """Chain returns oldest-ancestor → ... → parent → this in order."""

        task = self.create_task()
        root = TaskRun.objects.create(task=task, team=self.team)
        middle = TaskRun.objects.create(task=task, team=self.team, state={"resume_from_run_id": str(root.id)})
        leaf = TaskRun.objects.create(task=task, team=self.team, state={"resume_from_run_id": str(middle.id)})

        chain = leaf.get_resume_chain()
        self.assertEqual([r.id for r in chain], [root.id, middle.id, leaf.id])

    def test_walk_resume_chain_handles_cycle(self):
        """A circular `resume_from_run_id` chain doesn't loop forever."""

        task = self.create_task()
        run_a = TaskRun.objects.create(task=task, team=self.team)
        run_b = TaskRun.objects.create(task=task, team=self.team, state={"resume_from_run_id": str(run_a.id)})
        run_a.state = {"resume_from_run_id": str(run_b.id)}
        run_a.save(update_fields=["state"])

        chain = run_b.get_resume_chain()
        self.assertEqual({r.id for r in chain}, {run_a.id, run_b.id})

    def test_walk_resume_chain_respects_max_depth(self):
        task = self.create_task()
        prior: TaskRun | None = None
        runs: list[TaskRun] = []
        for _ in range(5):
            current = TaskRun.objects.create(
                task=task,
                team=self.team,
                state={"resume_from_run_id": str(prior.id)} if prior else {},
            )
            runs.append(current)
            prior = current

        chain = runs[-1].get_resume_chain(max_depth=2)
        # max_depth=2 means we walk at most 2 hops back from the leaf, so the
        # chain should contain exactly 3 entries (leaf + 2 ancestors).
        self.assertEqual(len(chain), 3)

    def test_walk_resume_chain_does_not_cross_tasks(self):
        task_a = self.create_task(title="A")
        task_b = self.create_task(title="B")

        run_on_a = TaskRun.objects.create(task=task_a, team=self.team)
        run_on_b = TaskRun.objects.create(task=task_b, team=self.team, state={"resume_from_run_id": str(run_on_a.id)})

        chain = run_on_b.get_resume_chain()
        # Walker is scoped via `task_run.task.runs.filter(...)` so a stale
        # cross-task `resume_from_run_id` is silently dropped.
        self.assertEqual([r.id for r in chain], [run_on_b.id])

    @parameterized.expand(
        [
            (
                "chained_returns_ancestors_first",
                True,  # has_ancestor
                {"a": '{"notification":{"method":"_posthog/git_checkpoint","params":{"checkpointId":"ckpt-A"}}}\n'},
                '{"notification":{"method":"session/update","params":{"update":{"sessionUpdate":"agent_message"}}}}\n',
                [
                    '{"notification":{"method":"_posthog/git_checkpoint","params":{"checkpointId":"ckpt-A"}}}',
                    '{"notification":{"method":"session/update","params":{"update":{"sessionUpdate":"agent_message"}}}}',
                ],
            ),
            (
                "unchained_returns_only_own_log",
                False,
                {},
                '{"hello":"world"}\n',
                ['{"hello":"world"}'],
            ),
            (
                "skips_missing_ancestor_logs",
                True,
                {"a": None},
                '{"only":"b"}\n',
                ['{"only":"b"}'],
            ),
        ]
    )
    @patch("posthog.storage.object_storage.read")
    def test_logs_endpoint_walks_resume_chain(
        self,
        _name: str,
        has_ancestor: bool,
        ancestor_logs: dict[str, str | None],
        own_log: str,
        expected_lines: list[str],
        mock_read,
    ):
        task = self.create_task()
        ancestor = TaskRun.objects.create(task=task, team=self.team) if has_ancestor else None
        target_state = {"resume_from_run_id": str(ancestor.id)} if ancestor else {}
        target = TaskRun.objects.create(task=task, team=self.team, state=target_state)

        def fake_read(path: str, missing_ok: bool = False) -> str | None:
            if ancestor and path == ancestor.log_url:
                return ancestor_logs.get("a")
            if path == target.log_url:
                return own_log
            return None

        mock_read.side_effect = fake_read

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{target.id}/logs/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.content.decode("utf-8").splitlines(), expected_lines)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_returns_jwt(self):
        reset_sandbox_jwt_key_cache()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("token", data)

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            data["token"],
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        self.assertEqual(decoded["run_id"], str(run.id))
        self.assertEqual(decoded["task_id"], str(task.id))
        self.assertEqual(decoded["team_id"], self.team.id)
        self.assertEqual(decoded["user_id"], self.user.id)
        self.assertIn("exp", decoded)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_has_correct_expiry(self):
        reset_sandbox_jwt_key_cache()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            response.json()["token"],
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        now = time.time()
        expected_expiry = now + (24 * 60 * 60)
        self.assertAlmostEqual(decoded["exp"], expected_expiry, delta=60)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    def test_connection_token_includes_distinct_id(self):
        reset_sandbox_jwt_key_cache()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/connection_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            response.json()["token"],
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        self.assertIn("distinct_id", decoded)
        self.assertEqual(decoded["distinct_id"], self.user.distinct_id)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @override_settings(SANDBOX_JWT_PUBLIC_KEY=None)
    def test_stream_token_returns_run_scoped_jwt(self):
        reset_sandbox_jwt_key_cache()

        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream_token/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertIn("token", data)
        # No proxy URL configured for this environment, so clients read from Django directly.
        self.assertIsNone(data["stream_base_url"])

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            data["token"],
            public_key,
            audience="posthog:stream_read",
            algorithms=["RS256"],
        )

        self.assertEqual(decoded["run_id"], str(run.id))
        self.assertEqual(decoded["task_id"], str(task.id))
        self.assertEqual(decoded["team_id"], self.team.id)
        self.assertNotIn("user_id", decoded)
        self.assertIn("exp", decoded)

    def test_stream_token_returns_proxy_url_when_configured_and_flag_enabled(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        with (
            self.settings(TASKS_AGENT_PROXY_PUBLIC_URL="https://agent-proxy.example.com", DEBUG=False),
            patch("products.tasks.backend.facade.api.posthoganalytics.feature_enabled", return_value=True),
        ):
            response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream_token/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["stream_base_url"], "https://agent-proxy.example.com")

    def test_stream_token_omits_proxy_url_when_flag_disabled(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        # Disable only the stream-via-proxy flag; leave other flags at their real values so the
        # request's own access checks still pass.
        def flag_enabled(key, *args, **kwargs):
            return key != "tasks-stream-via-proxy"

        with (
            self.settings(TASKS_AGENT_PROXY_PUBLIC_URL="https://agent-proxy.example.com", DEBUG=False),
            patch(
                "products.tasks.backend.facade.api.posthoganalytics.feature_enabled",
                side_effect=flag_enabled,
            ),
        ):
            response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream_token/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["stream_base_url"])

    def test_stream_token_returns_proxy_url_in_debug_without_flag(self):
        # Local dev (DEBUG) disables the analytics SDK, so the URL setting alone opts in.
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        with self.settings(TASKS_AGENT_PROXY_PUBLIC_URL="http://localhost:8003", DEBUG=True):
            response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream_token/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["stream_base_url"], "http://localhost:8003")

    def test_stream_token_omits_proxy_url_when_flag_evaluation_fails(self):
        # A flag-service outage must fall back to reading from Django, not break token issuance.
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        def flag_enabled(key, *args, **kwargs):
            if key == "tasks-stream-via-proxy":
                raise RuntimeError("flag service unavailable")
            return True

        with (
            self.settings(TASKS_AGENT_PROXY_PUBLIC_URL="https://agent-proxy.example.com", DEBUG=False),
            patch(
                "products.tasks.backend.facade.api.posthoganalytics.feature_enabled",
                side_effect=flag_enabled,
            ),
        ):
            response = self.client.get(f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream_token/")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIsNone(response.json()["stream_base_url"])

    def test_connection_token_cannot_access_other_team_run(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_task = Task.objects.create(
            team=other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_run = TaskRun.objects.create(task=other_task, team=other_team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(
            f"/api/projects/@current/tasks/{other_task.id}/runs/{other_run.id}/connection_token/"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_stream_token_cannot_access_other_team_run(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_task = Task.objects.create(
            team=other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_run = TaskRun.objects.create(task=other_task, team=other_team, status=TaskRun.Status.IN_PROGRESS)

        response = self.client.get(f"/api/projects/@current/tasks/{other_task.id}/runs/{other_run.id}/stream_token/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)


class TestTaskRunSessionLogsAPI(BaseTaskAPITest):
    """Tests for the GET .../session_logs/ endpoint that returns filtered log entries."""

    def _make_session_update_entry(self, session_update_type: str, timestamp: str, **extra) -> dict:
        """Build a log entry with session/update notification."""
        return {
            "type": "notification",
            "timestamp": timestamp,
            "notification": {
                "jsonrpc": "2.0",
                "method": "session/update",
                "params": {
                    "update": {
                        "sessionUpdate": session_update_type,
                        **extra,
                    }
                },
            },
        }

    def _make_posthog_entry(self, method: str, timestamp: str, **params) -> dict:
        """Build a log entry with a _posthog/* notification."""
        return {
            "type": "notification",
            "timestamp": timestamp,
            "notification": {
                "jsonrpc": "2.0",
                "method": method,
                "params": params,
            },
        }

    def _seed_log(self, task, run, entries: list[dict]):
        """Write entries directly to S3 as JSONL (bypasses append_log filtering)."""
        content = "\n".join(json.dumps(e) for e in entries)
        object_storage.write(run.log_url, content.encode("utf-8"))

    def _events_url(self, task, run):
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/session_logs/"

    def test_session_logs_returns_all_entries_unfiltered(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T00:00:03Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertEqual(response["X-Total-Count"], "3")
        self.assertEqual(response["X-Filtered-Count"], "3")

    def test_session_logs_empty_log(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)
        # No log written to S3

        response = self.client.get(self._events_url(task, run))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 0)
        self.assertEqual(response["X-Total-Count"], "0")
        self.assertEqual(response["X-Filtered-Count"], "0")

    def test_session_logs_walks_resume_chain(self):
        task = self.create_task()
        ancestor = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.COMPLETED)
        resumed = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"resume_from_run_id": str(ancestor.id)},
        )

        self._seed_log(
            task,
            ancestor,
            [
                self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
                self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            ],
        )
        self._seed_log(
            task,
            resumed,
            [self._make_session_update_entry("agent_message", "2026-01-01T00:00:03Z")],
        )

        response = self.client.get(self._events_url(task, resumed))
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(
            [e["notification"]["params"]["update"]["sessionUpdate"] for e in data],
            ["user_message", "agent_message", "agent_message"],
        )
        self.assertEqual(
            [e["timestamp"] for e in data],
            ["2026-01-01T00:00:01Z", "2026-01-01T00:00:02Z", "2026-01-01T00:00:03Z"],
        )
        self.assertEqual(response["X-Total-Count"], "3")

    def test_session_logs_filter_by_event_types(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T00:00:03Z"),
            self._make_session_update_entry("tool_result", "2026-01-01T00:00:04Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:05Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?event_types=tool_call,tool_result")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(response["X-Total-Count"], "5")
        self.assertEqual(response["X-Filtered-Count"], "2")
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["tool_call", "tool_result"])

    def test_session_logs_filter_by_exclude_types(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T00:00:03Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?exclude_types=agent_message")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(response["X-Filtered-Count"], "2")
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["user_message", "tool_call"])

    def test_session_logs_filter_by_after_timestamp(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T10:00:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:05:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:10:00Z"),
            self._make_session_update_entry("tool_result", "2026-01-01T10:15:00Z"),
        ]
        self._seed_log(task, run, entries)

        # After the second entry — should return only the last two
        response = self.client.get(self._events_url(task, run) + "?after=2026-01-01T10:05:00Z")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(response["X-Total-Count"], "4")
        self.assertEqual(response["X-Filtered-Count"], "2")
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["tool_call", "tool_result"])

    def test_session_logs_filter_after_handles_z_and_offset_formats(self):
        """Timestamps with Z suffix and +00:00 suffix should compare correctly."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T10:00:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:00:00.500Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:00:01Z"),
        ]
        self._seed_log(task, run, entries)

        # Use +00:00 format for the after param — should still match Z-format timestamps
        response = self.client.get(self._events_url(task, run) + "?after=2026-01-01T10:00:00%2B00:00")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        types = [e["notification"]["params"]["update"]["sessionUpdate"] for e in data]
        self.assertEqual(types, ["agent_message", "tool_call"])

    def test_session_logs_limit(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [self._make_session_update_entry("user_message", f"2026-01-01T00:00:{i:02d}Z") for i in range(10)]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?limit=3")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 3)
        self.assertEqual(response["X-Total-Count"], "10")
        self.assertEqual(response["X-Filtered-Count"], "10")
        self.assertEqual(response["X-Matching-Count"], "10")
        self.assertEqual(response["X-Has-More"], "true")

    def test_session_logs_caps_page_size_by_bytes(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:00Z", text="x" * 400),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:01Z", text="x" * 400),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:02Z", text="x" * 5000),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:03Z", text="x" * 400),
        ]
        self._seed_log(task, run, entries)

        with patch("products.tasks.backend.presentation.views.api.SESSION_LOG_PAGE_MAX_BYTES", 600):
            collected: list = []
            offset = 0
            pages = 0
            oversized_returned_alone = False
            while True:
                response = self.client.get(self._events_url(task, run) + f"?limit=100&offset={offset}")
                self.assertEqual(response.status_code, status.HTTP_200_OK)
                page = response.json()
                self.assertGreaterEqual(len(page), 1)
                if any(len(json.dumps(e)) > 600 for e in page):
                    self.assertEqual(len(page), 1)
                    oversized_returned_alone = True
                collected.extend(page)
                offset += len(page)
                pages += 1
                if response["X-Has-More"] != "true":
                    break

        self.assertGreater(pages, 1)
        self.assertTrue(oversized_returned_alone)
        self.assertEqual(response["X-Total-Count"], "4")
        self.assertEqual(
            [e["timestamp"] for e in collected],
            [f"2026-01-01T00:00:0{i}Z" for i in range(4)],
        )

    def test_session_logs_offset(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [self._make_session_update_entry("user_message", f"2026-01-01T00:00:{i:02d}Z") for i in range(6)]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run) + "?limit=2&offset=2")
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["timestamp"], "2026-01-01T00:00:02Z")
        self.assertEqual(data[1]["timestamp"], "2026-01-01T00:00:03Z")
        self.assertEqual(response["X-Total-Count"], "6")
        self.assertEqual(response["X-Filtered-Count"], "6")
        self.assertEqual(response["X-Matching-Count"], "6")
        self.assertEqual(response["X-Has-More"], "true")

    def test_session_logs_combined_filters(self):
        """Test after + event_types + limit together."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T10:00:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:01:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:02:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:03:00Z"),
            self._make_session_update_entry("agent_message", "2026-01-01T10:04:00Z"),
            self._make_session_update_entry("tool_call", "2026-01-01T10:05:00Z"),
        ]
        self._seed_log(task, run, entries)

        # After 10:01, only tool_call, limit 1
        response = self.client.get(
            self._events_url(task, run) + "?after=2026-01-01T10:01:00Z&event_types=tool_call&limit=1"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["timestamp"], "2026-01-01T10:03:00Z")

    def test_session_logs_posthog_method_filtering(self):
        """_posthog/* events should be filterable by their method name."""
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [
            self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z"),
            self._make_posthog_entry("_posthog/sdk_session", "2026-01-01T00:00:02Z", sessionId="s1"),
            self._make_posthog_entry("_posthog/session/resume", "2026-01-01T00:00:03Z", sessionId="s1"),
            self._make_session_update_entry("agent_message", "2026-01-01T00:00:04Z"),
        ]
        self._seed_log(task, run, entries)

        response = self.client.get(
            self._events_url(task, run) + "?event_types=_posthog/sdk_session,_posthog/session/resume"
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        data = response.json()
        self.assertEqual(len(data), 2)
        methods = [e["notification"]["method"] for e in data]
        self.assertEqual(methods, ["_posthog/sdk_session", "_posthog/session/resume"])

    def test_session_logs_server_timing_header(self):
        task = self.create_task()
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.IN_PROGRESS)

        entries = [self._make_session_update_entry("user_message", "2026-01-01T00:00:01Z")]
        self._seed_log(task, run, entries)

        response = self.client.get(self._events_url(task, run))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("Server-Timing", response)
        self.assertIn("s3_read", response["Server-Timing"])
        self.assertIn("filter", response["Server-Timing"])


class TestTaskRunStreamAPI(BaseTaskAPITest):
    def _stream_url(self, task: Task, run: TaskRun, suffix: str = "") -> str:
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream/{suffix}"

    def _mark_stream_complete(self, run: TaskRun) -> None:
        async def _mark() -> None:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(run.id)))
            await redis_stream.mark_complete()

        asyncio.run(_mark())

    def _read_stream_ids(self, run: TaskRun) -> list[str]:
        async def _read() -> list[str]:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(run.id)))
            messages = await redis_stream._redis_client.xrange(get_task_run_stream_key(str(run.id)))
            return [msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id for msg_id, _ in messages]

        return asyncio.run(_read())

    def _collect_sse_events(self, response) -> list[dict]:
        content = b"".join(response.streaming_content).decode("utf-8")
        events: list[dict] = []
        for block in [part.strip() for part in content.split("\n\n") if part.strip()]:
            event_name = None
            event_id = None
            data = None
            for line in block.splitlines():
                if line.startswith("event: "):
                    event_name = line[7:]
                elif line.startswith("id: "):
                    event_id = line[4:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            events.append({"event": event_name, "id": event_id, "data": data})
        return events

    def test_stream_replays_events_with_ids(self):
        task = self.create_task()
        run = task.create_run()
        run.emit_console_event("info", "hello")
        self._mark_stream_complete(run)

        response = self.client.get(self._stream_url(task, run), headers={"accept": "text/event-stream"})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = self._collect_sse_events(response)
        self.assertGreaterEqual(len(events), 2)
        self.assertEqual(events[0]["data"]["type"], "task_run_state")
        self.assertIsNotNone(events[0]["id"])
        self.assertEqual(events[1]["data"]["notification"]["method"], "_posthog/console")

    def test_stream_resumes_from_last_event_id(self):
        task = self.create_task()
        run = task.create_run()
        run.emit_console_event("info", "first")
        run.emit_sandbox_output("stdout", "stderr", 0)
        stream_ids = self._read_stream_ids(run)
        self._mark_stream_complete(run)

        response = self.client.get(self._stream_url(task, run), headers={"last-event-id": stream_ids[1]})

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        events = self._collect_sse_events(response)
        data_events = [event for event in events if event["event"] != "stream-end"]
        self.assertEqual(len(data_events), 1)
        self.assertEqual(data_events[0]["data"]["notification"]["method"], "_posthog/sandbox_output")
        self.assertEqual(events[-1]["event"], "stream-end")

    def test_stream_start_latest_only_yields_new_events(self):
        task = self.create_task()
        run = task.create_run()  # publishes a task_run_state event the latest cursor must skip

        new_event = {
            "type": "notification",
            "timestamp": "2026-01-01T00:00:01Z",
            "notification": {
                "jsonrpc": "2.0",
                "method": "_posthog/console",
                "params": {"sessionId": str(run.id), "level": "info", "message": "late hello"},
            },
        }

        # Append the new event the instant the handler captures the latest cursor, on the
        # handler's own event loop. A background thread would mutate the shared in-memory
        # fakeredis concurrently with the reader, which is racy and flakes in CI.
        real_get_latest = TaskRunRedisStream.get_latest_stream_id

        async def get_latest_then_publish(redis_stream: TaskRunRedisStream) -> str | None:
            latest_id = await real_get_latest(redis_stream)
            await redis_stream.write_event(new_event)
            await redis_stream.mark_complete()
            return latest_id

        with patch.object(TaskRunRedisStream, "get_latest_stream_id", get_latest_then_publish):
            response = self.client.get(self._stream_url(task, run) + "?start=latest")
            events = self._collect_sse_events(response)

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data_events = [event for event in events if event["event"] not in ("stream-end", "keepalive")]
        self.assertGreaterEqual(len(data_events), 1)
        self.assertTrue(
            all(event["data"]["notification"]["method"] == "_posthog/console" for event in data_events), data_events
        )
        self.assertEqual(data_events[-1]["data"]["notification"]["params"]["message"], "late hello")
        self.assertEqual(events[-1]["event"], "stream-end")


class TestTaskRunRedisStreamKeepalive(TestCase):
    def test_read_stream_entries_yields_keepalive_sentinel_when_idle(self):
        class StubRedis:
            def __init__(self):
                self.calls = 0

            async def xread(self, *_args, **_kwargs):
                self.calls += 1
                if self.calls == 1:
                    return []
                return [
                    [
                        b"task-run-stream:test",
                        [
                            (
                                b"1-0",
                                {b"data": json.dumps({"type": "STREAM_STATUS", "status": "complete"}).encode("utf-8")},
                            )
                        ],
                    ]
                ]

        async def collect_items() -> list[object]:
            redis_stream = TaskRunRedisStream("task-run-stream:test")
            redis_stream._redis_client = StubRedis()
            items: list[object] = []
            # Force the idle branch immediately so the test does not wait on wall-clock time.
            async for item in redis_stream.read_stream_entries(keepalive_interval_seconds=0):
                items.append(item)
            return items

        self.assertEqual(asyncio.run(collect_items()), [None])


class TestTaskRunStreamKeepaliveAPI(BaseTaskAPITest):
    def _stream_url(self, task: Task, run: TaskRun) -> str:
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream/"

    def test_stream_emits_keepalive_while_waiting_for_stream_creation(self):
        task = self.create_task()
        run = task.create_run()

        async def fake_read_stream_entries(self, *args, **kwargs):
            yield (
                "1-0",
                {
                    "type": "notification",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "notification": {
                        "jsonrpc": "2.0",
                        "method": "_posthog/console",
                        "params": {
                            "sessionId": str(run.id),
                            "level": "info",
                            "message": "after stream creation",
                        },
                    },
                },
            )

        with (
            patch.object(TaskRunRedisStream, "exists", new=AsyncMock(side_effect=[False, True])),
            patch.object(TaskRunRedisStream, "read_stream_entries", new=fake_read_stream_entries),
            patch("products.tasks.backend.presentation.views.api.TASK_RUN_STREAM_KEEPALIVE_INTERVAL_SECONDS", 0),
        ):
            response = cast(
                StreamingHttpResponse,
                self.client.get(self._stream_url(task, run), HTTP_ACCEPT="text/event-stream"),
            )
            content = b"".join(cast(Iterator[bytes], response.streaming_content)).decode("utf-8")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("event: keepalive", content)
        self.assertIn("after stream creation", content)
        self.assertLess(content.index("event: keepalive"), content.index("after stream creation"))

    def test_stream_emits_keepalive_comments_while_idle(self):
        task = self.create_task()
        run = task.create_run()

        async def fake_read_stream_entries(self, *args, **kwargs):
            yield None
            yield (
                "1-0",
                {
                    "type": "notification",
                    "timestamp": "2026-01-01T00:00:01Z",
                    "notification": {
                        "jsonrpc": "2.0",
                        "method": "_posthog/console",
                        "params": {
                            "sessionId": str(run.id),
                            "level": "info",
                            "message": "after idle gap",
                        },
                    },
                },
            )

        with (
            patch.object(TaskRunRedisStream, "wait_for_stream", new=AsyncMock(return_value=True)),
            patch.object(TaskRunRedisStream, "read_stream_entries", new=fake_read_stream_entries),
        ):
            response = cast(
                StreamingHttpResponse,
                self.client.get(self._stream_url(task, run), headers={"accept": "text/event-stream"}),
            )
            content = b"".join(cast(Iterator[bytes], response.streaming_content)).decode("utf-8")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("event: keepalive", content)
        self.assertIn('"type": "keepalive"', content)
        self.assertIn("after idle gap", content)


class TestTaskRunStreamConnectionCapAPI(BaseTaskAPITest):
    def _stream_url(self, task: Task, run: TaskRun) -> str:
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/stream/"

    def _mark_stream_complete(self, run: TaskRun) -> None:
        async def _mark() -> None:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(run.id)))
            await redis_stream.mark_complete()

        asyncio.run(_mark())

    def _read_stream_ids(self, run: TaskRun) -> list[str]:
        async def _read() -> list[str]:
            redis_stream = TaskRunRedisStream(get_task_run_stream_key(str(run.id)))
            messages = await redis_stream._redis_client.xrange(get_task_run_stream_key(str(run.id)))
            return [msg_id.decode("utf-8") if isinstance(msg_id, bytes) else msg_id for msg_id, _ in messages]

        return asyncio.run(_read())

    def _collect_sse_events(self, response: StreamingHttpResponse) -> list[dict]:
        content = b"".join(cast(Iterator[bytes], response.streaming_content)).decode("utf-8")
        events: list[dict] = []
        for block in [part.strip() for part in content.split("\n\n") if part.strip()]:
            event_name = None
            event_id = None
            data = None
            for line in block.splitlines():
                if line.startswith("event: "):
                    event_name = line[7:]
                elif line.startswith("id: "):
                    event_id = line[4:]
                elif line.startswith("data: "):
                    data = json.loads(line[6:])
            events.append({"event": event_name, "id": event_id, "data": data})
        return events

    @parameterized.expand(
        [
            ("after_real_event", False, "before cap"),
            ("on_keepalive_only_iteration", True, "event: keepalive"),
        ]
    )
    def test_stream_rotates_cleanly_when_connection_cap_elapses(
        self, _name: str, idle_first: bool, expected_marker: str
    ) -> None:
        task = self.create_task()
        run = task.create_run()

        def _console_event(message: str) -> dict:
            return {
                "type": "notification",
                "timestamp": "2026-01-01T00:00:01Z",
                "notification": {
                    "jsonrpc": "2.0",
                    "method": "_posthog/console",
                    "params": {"sessionId": str(run.id), "level": "info", "message": message},
                },
            }

        async def fake_read_stream_entries(
            self: TaskRunRedisStream, *args: Any, **kwargs: Any
        ) -> AsyncGenerator[TaskRunStreamEntryOrKeepalive]:
            if idle_first:
                yield None
            else:
                yield ("1-0", _console_event("before cap"))
            yield ("2-0", _console_event("after cap"))

        observe_closed = MagicMock()
        with (
            patch.object(TaskRunRedisStream, "read_stream_entries", new=fake_read_stream_entries),
            # A cap of 0 trips the elapsed check on the first yield, so the test
            # exercises the rotation path without sleeping through real time. The
            # keepalive case proves the check runs on idle yields too: if it only
            # ran after real events, an idle stream would never rotate.
            patch("products.tasks.backend.presentation.views.api.TASK_RUN_STREAM_CONNECTION_MAX_SECONDS", 0),
            patch("products.tasks.backend.presentation.views.api.observe_stream_connection_closed", observe_closed),
        ):
            response = cast(
                StreamingHttpResponse,
                self.client.get(self._stream_url(task, run), headers={"accept": "text/event-stream"}),
            )
            content = b"".join(cast(Iterator[bytes], response.streaming_content)).decode("utf-8")

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        # Whatever was already delivered is kept; the stream then signals rotation
        # (so clients can tell it apart from run completion) and ends without an
        # error event, letting the client resume from its Last-Event-ID cursor.
        self.assertIn(expected_marker, content)
        self.assertNotIn("after cap", content)
        self.assertNotIn("event: error", content)
        self.assertTrue(content.endswith('event: end\ndata: {"type": "rotated"}\n\n'))
        observe_closed.assert_called_once()
        self.assertEqual(observe_closed.call_args.args[1], "rotated")

    def test_stream_resumes_after_rotation_without_gap_or_duplicate(self) -> None:
        task = self.create_task()
        run = task.create_run()
        run.emit_console_event("info", "first message")
        run.emit_console_event("info", "second message")
        stream_ids = self._read_stream_ids(run)

        # A cap of 0 rotates the first connection after its first yield, leaving
        # the two console events for the resumed connection to pick up.
        with patch("products.tasks.backend.presentation.views.api.TASK_RUN_STREAM_CONNECTION_MAX_SECONDS", 0):
            first_response = cast(
                StreamingHttpResponse,
                self.client.get(self._stream_url(task, run), headers={"accept": "text/event-stream"}),
            )
            first_events = self._collect_sse_events(first_response)

        self.assertEqual(first_response.status_code, status.HTTP_200_OK)
        # The rotation marker is the last thing on the wire and carries no id, so
        # it can't poison the client's resume cursor.
        self.assertEqual(first_events[-1], {"event": "end", "id": None, "data": {"type": "rotated"}})
        first_data_events = first_events[:-1]
        self.assertEqual([event["id"] for event in first_data_events], [stream_ids[0]])
        # stream_ids[0] is the task_run_state event create_run publishes — the
        # console events are deliberately left for the resumed connection.
        self.assertEqual(first_data_events[0]["data"]["type"], "task_run_state")

        self._mark_stream_complete(run)

        second_response = cast(
            StreamingHttpResponse,
            self.client.get(
                self._stream_url(task, run),
                headers={"accept": "text/event-stream", "last-event-id": first_data_events[0]["id"]},
            ),
        )

        self.assertEqual(second_response.status_code, status.HTTP_200_OK)
        second_events = self._collect_sse_events(second_response)
        # The run was marked complete, so the resumed connection ends with the in-band
        # completion sentinel (id-less, so it can't poison the resume cursor) rather than
        # a bare EOF or a rotation marker.
        self.assertEqual(second_events[-1]["event"], "stream-end")
        second_data_events = [event for event in second_events if event["event"] != "stream-end"]
        # Resuming from the rotated connection's last id delivers the remaining
        # events exactly once — no gap, no duplicate.
        self.assertEqual([event["id"] for event in second_data_events], stream_ids[1:])
        self.assertEqual(
            [event["data"]["notification"]["params"]["message"] for event in second_data_events],
            ["first message", "second message"],
        )


class TestTasksAPIPermissions(BaseTaskAPITest):
    def setUp(self):
        super().setUp()
        # Create another team/org for cross-team tests
        self.other_org = Organization.objects.create(name="Other Org")
        self.other_team = Team.objects.create(organization=self.other_org, name="Other Team")
        self.other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.other_org.members.add(self.other_user)
        OrganizationMembership.objects.filter(user=self.other_user, organization=self.other_org).update(
            level=OrganizationMembership.Level.ADMIN
        )

    def test_check_access_flag_on_no_redemption(self):
        self.set_tasks_feature_flag(True)

        response = self.client.get("/api/code/invites/check-access/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["has_access"])

    def test_check_access_flag_off_no_redemption(self):
        self.set_tasks_feature_flag(False)

        response = self.client.get("/api/code/invites/check-access/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertFalse(response.json()["has_access"])

    def test_check_access_flag_off_with_redemption(self):
        self.set_tasks_feature_flag(False)
        invite = CodeInvite.objects.create(code="ACCESSCODE", max_redemptions=0, is_active=True)
        CodeInviteRedemption.objects.create(invite_code=invite, user=self.user)

        response = self.client.get("/api/code/invites/check-access/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["has_access"])

    def test_authentication_required(self):
        task = self.create_task()
        automation = self.create_automation(name="Daily PRs", prompt="Check my PRs")

        self.client.force_authenticate(None)

        endpoints = [
            ("/api/projects/@current/tasks/", "GET"),
            (f"/api/projects/@current/tasks/{task.id}/", "GET"),
            ("/api/projects/@current/task_automations/", "GET"),
            (f"/api/projects/@current/task_automations/{automation.id}/", "GET"),
            (f"/api/projects/@current/task_automations/{automation.id}/run/", "POST"),
        ]

        for url, method in endpoints:
            response = getattr(self.client, method.lower())(url)
            self.assertEqual(response.status_code, status.HTTP_403_FORBIDDEN, f"Failed for {method} {url}")

    def test_cross_team_task_access_forbidden(self):
        # Create task in other team
        other_task = Task.objects.create(
            team=self.other_team,
            title="Other Team Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )

        # Try to access other team's task
        response = self.client.get(f"/api/projects/@current/tasks/{other_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to update other team's task
        response = self.client.patch(
            f"/api/projects/@current/tasks/{other_task.id}/", {"title": "Hacked Title"}, format="json"
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        # Try to delete other team's task
        response = self.client.delete(f"/api/projects/@current/tasks/{other_task.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_cross_team_automation_access_forbidden(self):
        other_automation = self.create_automation(
            name="Other Team Automation",
            prompt="Description",
            team=self.other_team,
            user=self.other_user,
        )

        response = self.client.get(f"/api/projects/@current/task_automations/{other_automation.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.patch(
            f"/api/projects/@current/task_automations/{other_automation.id}/",
            {"name": "Hacked Automation"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

        response = self.client.delete(f"/api/projects/@current/task_automations/{other_automation.id}/")
        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_list_endpoints_only_return_team_resources(self):
        # Create resources in both teams

        my_task = self.create_task("My Task")
        my_automation = self.create_automation(name="My automation", prompt="Mine")

        other_task = Task.objects.create(
            team=self.other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_automation = self.create_automation(
            name="Other automation",
            prompt="Other",
            team=self.other_team,
            user=self.other_user,
        )

        # List tasks should only return my team's tasks
        response = self.client.get("/api/projects/@current/tasks/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        task_ids = [t["id"] for t in response.json()["results"]]
        self.assertIn(str(my_task.id), task_ids)
        self.assertNotIn(str(other_task.id), task_ids)

        response = self.client.get("/api/projects/@current/task_automations/")
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        automation_ids = [a["id"] for a in response.json()["results"]]
        self.assertIn(str(my_automation.id), automation_ids)
        self.assertNotIn(str(other_automation.id), automation_ids)

    @parameterized.expand(
        [
            ("task:read", "GET", "/api/projects/@current/tasks/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("task:read", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/connection_token/", False),
            ("task:read", "GET", "/api/projects/@current/task_automations/", True),
            ("task:read", "GET", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:read", "POST", "/api/projects/@current/tasks/", False),
            ("task:read", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", False),
            ("task:read", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", False),
            ("task:read", "POST", "/api/projects/@current/task_automations/", False),
            ("task:write", "GET", "/api/projects/@current/tasks/", True),
            ("task:write", "POST", "/api/projects/@current/tasks/", True),
            ("task:write", "PATCH", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "DELETE", f"/api/projects/@current/tasks/{{task_id}}/", True),
            ("task:write", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("task:write", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/connection_token/", True),
            ("task:write", "POST", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/start/", True),
            ("task:write", "GET", "/api/projects/@current/task_automations/", True),
            ("task:write", "GET", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:write", "POST", "/api/projects/@current/task_automations/", True),
            ("task:write", "PATCH", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:write", "DELETE", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("task:write", "POST", "/api/projects/@current/task_automations/{automation_id}/run/", True),
            ("other_scope:read", "GET", "/api/projects/@current/tasks/", False),
            ("other_scope:write", "POST", "/api/projects/@current/tasks/", False),
            ("*", "GET", "/api/projects/@current/tasks/", True),
            ("*", "POST", "/api/projects/@current/tasks/", True),
            ("*", "POST", f"/api/projects/@current/tasks/{{task_id}}/run/", True),
            ("*", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/", True),
            ("*", "GET", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/", True),
            ("*", "POST", f"/api/projects/@current/tasks/{{task_id}}/runs/{{run_id}}/start/", True),
            ("*", "GET", "/api/projects/@current/task_automations/", True),
            ("*", "GET", "/api/projects/@current/task_automations/{automation_id}/", True),
            ("*", "POST", "/api/projects/@current/task_automations/", True),
            ("*", "POST", "/api/projects/@current/task_automations/{automation_id}/run/", True),
        ]
    )
    def test_scoped_api_key_permissions(self, scope, method, url_template, should_have_access):
        task = self.create_task()
        automation = self.create_automation(name="Scoped automation", prompt="Check my PRs")
        run = TaskRun.objects.create(task=task, team=self.team, status=TaskRun.Status.QUEUED)

        api_key_value = generate_random_token_personal()

        PersonalAPIKey.objects.create(
            user=self.user,
            label=f"Test API Key - {scope}",
            secure_value=hash_key_value(api_key_value),
            scopes=[scope],
        )

        url = url_template.format(task_id=task.id, run_id=run.id, automation_id=automation.id)

        self.client.force_authenticate(None)

        data = {}
        if method == "POST" and url == "/api/projects/@current/tasks/":
            data = {
                "title": "New Task",
                "description": "Description",
                "origin_product": Task.OriginProduct.USER_CREATED,
            }
        elif method == "POST" and url == "/api/projects/@current/task_automations/":
            data = {
                "name": "New Automation",
                "prompt": "Check my PRs",
                "repository": "posthog/posthog",
                "cron_expression": "0 9 * * *",
                "timezone": "Europe/London",
            }
        elif method == "PATCH" and "/task_automations/" in url:
            data = {"name": "Updated Automation"}
        elif method == "PATCH" and "/tasks/" in url:
            data = {"title": "Updated Task"}

        if method == "GET":
            response = self.client.get(url, headers={"authorization": f"Bearer {api_key_value}"})
        elif method == "POST":
            response = self.client.post(url, data, format="json", headers={"authorization": f"Bearer {api_key_value}"})
        elif method == "PATCH":
            response = self.client.patch(url, data, format="json", headers={"authorization": f"Bearer {api_key_value}"})
        elif method == "DELETE":
            response = self.client.delete(url, headers={"authorization": f"Bearer {api_key_value}"})
        else:
            self.fail(f"Unsupported method: {method}")

        if should_have_access:
            self.assertNotEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected access but got 403 for {scope} on {method} {url}",
            )
        else:
            self.assertEqual(
                response.status_code,
                status.HTTP_403_FORBIDDEN,
                f"Expected 403 but got {response.status_code} for {scope} on {method} {url}",
            )


class TestTaskRepositoryReadinessAPI(BaseTaskAPITest):
    @patch("products.tasks.backend.facade.api.compute_repository_readiness")
    def test_repository_readiness_endpoint(self, mock_compute):
        mock_compute.return_value = {
            "repository": "posthog/posthog",
            "classification": "backend_service",
            "excluded": False,
            "coreSuggestions": {
                "state": "ready",
                "estimated": True,
                "reason": "ok",
                "evidence": {},
            },
            "replayInsights": {
                "state": "not_applicable",
                "estimated": True,
                "reason": "n/a",
                "evidence": {},
            },
            "errorInsights": {
                "state": "ready",
                "estimated": True,
                "reason": "ok",
                "evidence": {},
            },
            "overall": "ready",
            "evidenceTaskCount": 1,
            "windowDays": 7,
            "generatedAt": "2026-01-01T00:00:00+00:00",
            "cacheAgeSeconds": 0,
        }

        response = self.client.get(
            "/api/projects/@current/tasks/repository_readiness/",
            {
                "repository": "posthog/posthog",
                "window_days": "7",
                "refresh": "false",
            },
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(response.json()["repository"], "posthog/posthog")
        mock_compute.assert_called_once()

    def test_repository_readiness_requires_repository(self):
        response = self.client.get("/api/projects/@current/tasks/repository_readiness/")
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)


class TestTaskRunCommandAPI(BaseTaskAPITest):
    def _command_url(self, task, run):
        return f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/command/"

    def _make_user_message(self, content="Hello agent", request_id="req-1"):
        return {
            "jsonrpc": "2.0",
            "method": "user_message",
            "params": {"content": content},
            "id": request_id,
        }

    def _make_cancel(self, request_id="req-cancel"):
        return {"jsonrpc": "2.0", "method": "cancel", "id": request_id}

    def _create_run_with_sandbox(self, task, sandbox_url="http://localhost:9999", connect_token=None):
        state = {"sandbox_url": sandbox_url, "mode": "interactive"}
        if connect_token:
            state["sandbox_connect_token"] = connect_token
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state=state,
        )

    def _mock_agent_response(self, mock_post, body, status_code=200):
        mock_resp = MagicMock()
        mock_resp.status_code = status_code
        mock_resp.ok = 200 <= status_code < 300
        mock_resp.json.return_value = body
        mock_resp.text = json.dumps(body) if isinstance(body, dict) else str(body)
        mock_post.return_value = mock_resp

    @patch("products.tasks.backend.temporal.client.signal_task_followup_message")
    def test_command_signals_user_message(self, mock_signal_followup):
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        data = response.json()
        self.assertEqual(data["jsonrpc"], "2.0")
        self.assertTrue(data["result"]["queued"])

        mock_signal_followup.assert_called_once_with(run.workflow_id, "Hello agent", [])

    @patch("products.tasks.backend.temporal.client.signal_task_followup_message")
    def test_command_signals_user_message_without_active_sandbox(self, mock_signal_followup):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.QUEUED,
            state={},
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["result"]["queued"])
        mock_signal_followup.assert_called_once_with(run.workflow_id, "Hello agent", [])

    @patch("products.tasks.backend.temporal.client.signal_task_followup_message")
    def test_command_signals_user_message_artifact_ids(self, mock_signal_followup):
        task = self.create_task()
        run = self._create_run_with_sandbox(task)
        artifact = {
            "id": "artifact-123",
            "name": "spec.pdf",
            "type": "user_attachment",
            "source": "user_attachment",
            "size": 4096,
            "content_type": "application/pdf",
            "storage_path": f"{run.get_artifact_s3_prefix()}/artifact-123_spec.pdf",
            "uploaded_at": "2026-04-16T12:00:00Z",
        }
        run.artifacts = [artifact]
        run.save(update_fields=["artifacts", "updated_at"])

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "user_message",
                "params": {"content": "See attached", "artifact_ids": ["artifact-123"]},
                "id": "req-attachments",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["result"]["queued"])
        mock_signal_followup.assert_called_once_with(run.workflow_id, "See attached", ["artifact-123"])

    @patch("products.tasks.backend.temporal.client.signal_task_followup_message")
    def test_command_returns_502_when_user_message_signal_fails(self, mock_signal_followup):
        mock_signal_followup.side_effect = RuntimeError("temporal unavailable")
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(response.json()["error"], "Failed to queue user message for task run")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_rejects_unknown_artifact_ids(self, mock_post):
        reset_sandbox_jwt_key_cache()
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "user_message",
                "params": {"artifact_ids": ["missing-artifact"]},
                "id": "req-missing-attachment",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(response.json()["error"], "Some artifact_ids are invalid for this run")
        self.assertEqual(response.json()["missing_artifact_ids"], ["missing-artifact"])
        mock_post.assert_not_called()

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_proxies_cancel(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(
            mock_post,
            {
                "jsonrpc": "2.0",
                "id": "req-2",
                "result": {"cancelled": True},
            },
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": "req-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["result"]["cancelled"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_proxies_close(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(
            mock_post,
            {
                "jsonrpc": "2.0",
                "id": "req-3",
                "result": {"closed": True},
            },
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "close", "id": "req-3"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertTrue(response.json()["result"]["closed"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_proxies_permission_response(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(
            mock_post,
            {"jsonrpc": "2.0", "id": "req-4", "result": {"acknowledged": True}},
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "permission_response",
                "params": {"requestId": "perm-1", "optionId": "allow"},
                "id": "req-4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["method"], "permission_response")
        self.assertEqual(call_kwargs["json"]["params"]["requestId"], "perm-1")
        self.assertEqual(call_kwargs["json"]["params"]["optionId"], "allow")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_proxies_set_config_option(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(
            mock_post,
            {"jsonrpc": "2.0", "id": "req-5", "result": {"updated": True}},
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "set_config_option",
                "params": {"configId": "mode", "value": "plan"},
                "id": "req-5",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["method"], "set_config_option")
        self.assertEqual(call_kwargs["json"]["params"]["configId"], "mode")
        self.assertEqual(call_kwargs["json"]["params"]["value"], "plan")

    def _create_posthog_ai_task(self, created_by: User | None = None):
        return Task.objects.create(
            team=self.team,
            created_by=created_by or self.user,
            title="Max session",
            description="Max session",
            origin_product=Task.OriginProduct.POSTHOG_AI,
        )

    def _capture_calls_for_event(self, mock_capture, event):
        return [call for call in mock_capture.call_args_list if call.kwargs.get("event") == event]

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_emits_permission_responded_telemetry_for_posthog_ai(self, mock_post, mock_capture):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": "req-4", "result": {"acknowledged": True}})
        task = self._create_posthog_ai_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "permission_response",
                "params": {"requestId": "perm-1", "optionId": "allow"},
                "id": "req-4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        calls = self._capture_calls_for_event(mock_capture, "permission_responded")
        self.assertEqual(len(calls), 1)
        props = calls[0].kwargs["properties"]
        self.assertEqual(props["origin_product"], Task.OriginProduct.POSTHOG_AI)
        self.assertEqual(props["run_id"], str(run.id))
        self.assertEqual(props["request_id"], "perm-1")
        self.assertEqual(props["option_id"], "allow")
        self.assertTrue(props["success"])
        self.assertEqual(props["surface"], "relay")
        self.assertIsNone(props["conversation_id"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_emits_task_run_cancelled_telemetry_for_posthog_ai(self, mock_post, mock_capture):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": "req-2", "result": {"cancelled": True}})
        task = self._create_posthog_ai_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": "req-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        calls = self._capture_calls_for_event(mock_capture, "task_run_cancelled")
        self.assertEqual(len(calls), 1)
        props = calls[0].kwargs["properties"]
        self.assertEqual(props["origin_product"], Task.OriginProduct.POSTHOG_AI)
        self.assertEqual(props["cancel_source"], "user")
        self.assertEqual(props["surface"], "relay")
        self.assertIsNone(props["conversation_id"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_no_control_verb_telemetry_for_non_posthog_ai(self, mock_post, mock_capture):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": "req-2", "result": {"cancelled": True}})
        # USER_CREATED task (e.g. PostHog Code) — the generic relay must not emit PostHog AI funnels.
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": "req-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(self._capture_calls_for_event(mock_capture, "task_run_cancelled"), [])
        self.assertEqual(self._capture_calls_for_event(mock_capture, "permission_responded"), [])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_permission_telemetry_marks_forward_failure(self, mock_post, mock_capture):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"error": "agent rejected"}, status_code=502)
        task = self._create_posthog_ai_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "permission_response",
                "params": {"requestId": "perm-1", "optionId": "allow"},
                "id": "req-4",
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        calls = self._capture_calls_for_event(mock_capture, "permission_responded")
        self.assertEqual(len(calls), 1)
        self.assertFalse(calls[0].kwargs["properties"]["success"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.models.posthoganalytics.capture")
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_cancel_failure_emits_no_telemetry(self, mock_post, mock_capture):
        # The conversation layer recorded a cancel only when it actually reached the agent;
        # the relay mirrors that — a failed forward records nothing.
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"error": "agent rejected"}, status_code=502)
        task = self._create_posthog_ai_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": "req-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertEqual(self._capture_calls_for_event(mock_capture, "task_run_cancelled"), [])

    def test_command_denied_for_other_users_posthog_ai_run(self):
        # Auth equivalence for the relay cutover: a same-team user who did not create the PostHog AI
        # task cannot command its run (404 via task_visibility_q), matching the conversation layer's
        # `conversation.user == request.user` check. Removing the conversation-layer check is safe.
        other_user = self.create_organization_user("victim")
        task = self._create_posthog_ai_task(created_by=other_user)
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": "req-2"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_command_fails_without_sandbox_url(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
            state={},
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No active sandbox", response.json()["error"])

    @parameterized.expand(
        [
            ("missing_jsonrpc", {"method": "user_message", "params": {"content": "hi"}}),
            ("invalid_jsonrpc", {"jsonrpc": "1.0", "method": "user_message", "params": {"content": "hi"}}),
            ("unknown_method", {"jsonrpc": "2.0", "method": "unknown_method", "params": {}}),
            ("user_message_empty_content", {"jsonrpc": "2.0", "method": "user_message", "params": {"content": ""}}),
            ("user_message_missing_content", {"jsonrpc": "2.0", "method": "user_message", "params": {}}),
            (
                "permission_response_missing_requestId",
                {"jsonrpc": "2.0", "method": "permission_response", "params": {"optionId": "allow"}},
            ),
            (
                "permission_response_missing_optionId",
                {"jsonrpc": "2.0", "method": "permission_response", "params": {"requestId": "req-1"}},
            ),
            (
                "permission_response_empty_params",
                {"jsonrpc": "2.0", "method": "permission_response", "params": {}},
            ),
            (
                "set_config_option_missing_configId",
                {"jsonrpc": "2.0", "method": "set_config_option", "params": {"value": "plan"}},
            ),
            (
                "set_config_option_missing_value",
                {"jsonrpc": "2.0", "method": "set_config_option", "params": {"configId": "mode"}},
            ),
            (
                "set_config_option_empty_params",
                {"jsonrpc": "2.0", "method": "set_config_option", "params": {}},
            ),
        ]
    )
    def test_command_rejects_invalid_payloads(self, _name, payload):
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            payload,
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_passes_modal_connect_token_as_query_param(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(
            task,
            sandbox_url="https://sandbox.modal.run",
            connect_token="modal-token-abc123",
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["params"]["_modal_connect_token"], "modal-token-abc123")
        self.assertNotIn("_modal_connect_token", call_kwargs["headers"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_no_query_params_for_docker(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url="http://localhost:47821")

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["params"], {})

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_returns_502_on_connection_error(self, mock_post):
        reset_sandbox_jwt_key_cache()
        mock_post.side_effect = __import__("requests").ConnectionError("Connection refused")

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("not reachable", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_returns_504_on_timeout(self, mock_post):
        reset_sandbox_jwt_key_cache()
        mock_post.side_effect = __import__("requests").Timeout("Request timed out")

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_504_GATEWAY_TIMEOUT)
        self.assertIn("timed out", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_forwards_agent_server_auth_error(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(
            mock_post,
            {"error": "Missing authorization header"},
            status_code=401,
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("Missing authorization header", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_forwards_agent_server_no_session_error(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(
            mock_post,
            {"error": "No active session for this run"},
            status_code=400,
        )

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertIn("No active session", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_sends_jwt_with_correct_claims(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        call_kwargs = mock_post.call_args[1]
        auth_header = call_kwargs["headers"]["Authorization"]
        token = auth_header.replace("Bearer ", "")

        public_key = get_sandbox_jwt_public_key()
        decoded = jwt.decode(
            token,
            public_key,
            audience="posthog:sandbox_connection",
            algorithms=["RS256"],
        )

        self.assertEqual(decoded["run_id"], str(run.id))
        self.assertEqual(decoded["task_id"], str(task.id))
        self.assertEqual(decoded["team_id"], self.team.id)
        self.assertEqual(decoded["user_id"], self.user.id)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_posts_to_correct_url(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url="http://localhost:47821")

        self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "http://localhost:47821/command")

    def test_command_cannot_access_other_team_run(self):
        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        other_task = Task.objects.create(
            team=other_team,
            title="Other Task",
            description="Description",
            origin_product=Task.OriginProduct.USER_CREATED,
        )
        other_run = TaskRun.objects.create(
            task=other_task,
            team=other_team,
            status=TaskRun.Status.IN_PROGRESS,
            state={"sandbox_url": "http://localhost:9999"},
        )

        response = self.client.post(
            self._command_url(other_task, other_run),
            self._make_user_message(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_404_NOT_FOUND)

    def test_command_rejects_posthog_prefixed_methods(self):
        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {
                "jsonrpc": "2.0",
                "method": "_posthog/user_message",
                "params": {"content": "Hello via posthog prefix"},
            },
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_with_trailing_slash_sandbox_url(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url="http://localhost:47821/")

        self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        call_args = mock_post.call_args
        self.assertEqual(call_args[0][0], "http://localhost:47821/command")

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_accepts_numeric_id(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": 42, "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": 42},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["id"], 42)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_uses_600s_timeout(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["timeout"], 600)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_omits_params_for_cancel(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {"cancelled": True}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel"},
            format="json",
        )

        call_kwargs = mock_post.call_args[1]
        self.assertNotIn("params", call_kwargs["json"])

    @parameterized.expand(
        [
            ("aws_metadata", "http://169.254.169.254/latest/meta-data/"),
            ("internal_service", "http://internal-api.company.com:8080"),
            ("file_scheme", "file:///etc/passwd"),
            ("ftp", "ftp://evil.com/file"),
            ("http_arbitrary", "http://evil.com/command"),
            ("https_arbitrary", "https://evil.com/command"),
            ("http_with_at_sign", "http://localhost@evil.com/"),
            ("cloud_metadata_gcp", "http://metadata.google.internal/"),
        ]
    )
    def test_command_blocks_ssrf_urls(self, _name, malicious_url):
        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url=malicious_url)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("Invalid sandbox URL", response.json()["error"])

    @parameterized.expand(
        [
            ("docker_localhost", "http://localhost:47821"),
            ("docker_127", "http://127.0.0.1:47821"),
            ("modal_run", "https://sb-abc123.modal.run"),
            ("modal_run_subdomain", "https://test-sandbox-xyz.modal.run"),
            ("modal_host", "https://sb-abc123.w.modal.host"),
            (
                "modal_host_connect_token",
                "https://a-ta-01kjnh54bc9wwbh7ydrk4yqq1d-b778iwq0t2a33tyjqdu6eyfjn.w.modal.host",
            ),
        ]
    )
    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_allows_valid_sandbox_urls(self, _name, valid_url, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task, sandbox_url=valid_url)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)

    def test_command_with_empty_state(self):
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            status=TaskRun.Status.IN_PROGRESS,
        )

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertIn("No active sandbox", response.json()["error"])

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_accepts_id_zero(self, mock_post):
        reset_sandbox_jwt_key_cache()
        self._mock_agent_response(mock_post, {"jsonrpc": "2.0", "id": 0, "result": {}})

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            {"jsonrpc": "2.0", "method": "cancel", "id": 0},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        call_kwargs = mock_post.call_args[1]
        self.assertEqual(call_kwargs["json"]["id"], 0)

    @override_settings(SANDBOX_JWT_PRIVATE_KEY=TEST_RSA_PRIVATE_KEY)
    @patch("products.tasks.backend.presentation.views.api.http_requests.post")
    def test_command_generic_error_does_not_leak_details(self, mock_post):
        reset_sandbox_jwt_key_cache()
        mock_post.side_effect = RuntimeError("internal DNS resolve failed for secret-host.internal:8080")

        task = self.create_task()
        run = self._create_run_with_sandbox(task)

        response = self.client.post(
            self._command_url(task, run),
            self._make_cancel(),
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_502_BAD_GATEWAY)
        self.assertNotIn("secret-host", response.json()["error"])
        self.assertNotIn("DNS", response.json()["error"])
        self.assertEqual(response.json()["error"], "Failed to send command to agent server")


class TestSandboxEnvironmentAPI(BaseTaskAPITest):
    base_url = "/api/projects/@current/sandbox_environments/"

    def detail_url(self, env_id):
        return f"{self.base_url}{env_id}/"

    def test_create_environment(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "My Sandbox",
                "network_access_level": "custom",
                "allowed_domains": ["api.example.com"],
                "include_default_domains": True,
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertEqual(data["name"], "My Sandbox")
        self.assertEqual(data["network_access_level"], "custom")
        self.assertIn("api.example.com", data["allowed_domains"])
        self.assertIn("api.example.com", data["effective_domains"])
        self.assertIn("github.com", data["effective_domains"])

    def test_create_environment_sets_created_by(self):
        response = self.client.post(
            self.base_url,
            {"name": "Test Env", "network_access_level": "full"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        env = SandboxEnvironment.objects.get(id=response.json()["id"])
        self.assertEqual(env.created_by, self.user)
        self.assertEqual(env.team, self.team)

    def test_list_environments(self):
        SandboxEnvironment.objects.create(team=self.team, name="Env 1", created_by=self.user)
        SandboxEnvironment.objects.create(team=self.team, name="Env 2", created_by=self.user)

        response = self.client.get(self.base_url)
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertEqual(len(response.json()["results"]), 2)

    def test_retrieve_environment_includes_effective_domains(self):
        env = SandboxEnvironment.objects.create(
            team=self.team,
            name="Detail Env",
            network_access_level="trusted",
            created_by=self.user,
        )
        response = self.client.get(self.detail_url(env.id))
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        self.assertIn("effective_domains", response.json())

    def test_update_environment(self):
        env = SandboxEnvironment.objects.create(team=self.team, name="Old Name", created_by=self.user)
        response = self.client.patch(
            self.detail_url(env.id),
            {"name": "New Name", "network_access_level": "custom", "allowed_domains": ["new.example.com"]},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)
        env.refresh_from_db()
        self.assertEqual(env.name, "New Name")
        self.assertEqual(env.allowed_domains, ["new.example.com"])

    def test_delete_environment(self):
        env = SandboxEnvironment.objects.create(team=self.team, name="To Delete", created_by=self.user)
        response = self.client.delete(self.detail_url(env.id))
        self.assertEqual(response.status_code, status.HTTP_204_NO_CONTENT)
        self.assertFalse(SandboxEnvironment.objects.filter(id=env.id).exists())

    def test_private_environment_only_visible_to_creator(self):
        other_user = User.objects.create_user(email="other@example.com", first_name="Other", password="password")
        self.organization.members.add(other_user)

        SandboxEnvironment.objects.create(team=self.team, name="Private", private=True, created_by=other_user)
        SandboxEnvironment.objects.create(team=self.team, name="My Private", private=True, created_by=self.user)

        response = self.client.get(self.base_url)
        names = [e["name"] for e in response.json()["results"]]
        self.assertIn("My Private", names)
        self.assertNotIn("Private", names)

    def test_public_environment_visible_to_all(self):
        other_user = User.objects.create_user(email="other2@example.com", first_name="Other2", password="password")
        self.organization.members.add(other_user)

        SandboxEnvironment.objects.create(team=self.team, name="Public Env", private=False, created_by=other_user)

        response = self.client.get(self.base_url)
        names = [e["name"] for e in response.json()["results"]]
        self.assertIn("Public Env", names)

    def test_full_access_returns_empty_effective_domains(self):
        response = self.client.post(
            self.base_url,
            {"name": "Full", "network_access_level": "full"},
            format="json",
        )
        self.assertEqual(response.json()["effective_domains"], [])

    def test_trusted_returns_default_domains(self):
        from products.tasks.backend.constants import DEFAULT_TRUSTED_DOMAINS

        response = self.client.post(
            self.base_url,
            {"name": "Trusted", "network_access_level": "trusted"},
            format="json",
        )
        self.assertEqual(response.json()["effective_domains"], DEFAULT_TRUSTED_DOMAINS)

    def test_custom_without_defaults_returns_only_custom(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Custom Only",
                "network_access_level": "custom",
                "allowed_domains": ["only-this.com"],
                "include_default_domains": False,
            },
            format="json",
        )
        self.assertEqual(response.json()["effective_domains"], ["only-this.com"])

    def test_invalid_env_var_key_rejected(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Bad Env Vars",
                "network_access_level": "full",
                "environment_variables": {"123invalid": "value"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("NODE_OPTIONS",),
            ("LD_PRELOAD",),
            ("LD_LIBRARY_PATH",),
            ("DYLD_INSERT_LIBRARIES",),
            ("BASH_ENV",),
            ("GIT_SSH_COMMAND",),
            ("GIT_CONFIG_KEY_0",),
            ("GIT_CONFIG_VALUE_0",),
        ]
    )
    def test_blocked_process_control_env_var_key_rejected(self, key):
        response = self.client.post(
            self.base_url,
            {
                "name": "Dangerous Env Vars",
                "network_access_level": "full",
                "environment_variables": {key: "value"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @parameterized.expand(
        [
            ("GITHUB_TOKEN",),
            ("POSTHOG_PERSONAL_API_KEY",),
            ("JWT_PUBLIC_KEY",),
        ]
    )
    def test_reserved_env_var_key_rejected(self, key):
        response = self.client.post(
            self.base_url,
            {
                "name": "Reserved Env Vars",
                "network_access_level": "full",
                "environment_variables": {key: "value"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    def test_environment_variables_never_returned(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Secret Env",
                "network_access_level": "full",
                "environment_variables": {"SECRET_KEY": "supersecret"},
            },
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        data = response.json()
        self.assertNotIn("environment_variables", data)
        self.assertTrue(data["has_environment_variables"])

        detail = self.client.get(self.detail_url(data["id"])).json()
        self.assertNotIn("environment_variables", detail)
        self.assertTrue(detail["has_environment_variables"])

        list_data = self.client.get(self.base_url).json()
        for env in list_data["results"]:
            self.assertNotIn("environment_variables", env)

    def test_has_environment_variables_false_when_empty(self):
        response = self.client.post(
            self.base_url,
            {"name": "No Vars", "network_access_level": "full"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        self.assertFalse(response.json()["has_environment_variables"])

    def test_custom_with_defaults_merges_without_duplicates(self):
        response = self.client.post(
            self.base_url,
            {
                "name": "Dedup Test",
                "network_access_level": "custom",
                "allowed_domains": ["github.com", "custom.io"],
                "include_default_domains": True,
            },
            format="json",
        )
        effective = response.json()["effective_domains"]
        self.assertEqual(effective.count("github.com"), 1)
        self.assertIn("custom.io", effective)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_stores_sandbox_environment_id_in_state(self, mock_workflow):
        task = self.create_task()
        task.created_by = self.user
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        env = SandboxEnvironment.objects.create(
            team=self.team, name="Test Env", network_access_level="trusted", created_by=self.user
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background", "sandbox_environment_id": str(env.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task_run = TaskRun.objects.filter(task=task).latest("created_at")
        self.assertEqual(task_run.state.get("sandbox_environment_id"), str(env.id))

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_rejects_invalid_sandbox_environment_id(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background", "sandbox_environment_id": str(uuid.uuid4())},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_rejects_other_team_sandbox_environment(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        other_org = Organization.objects.create(name="Other Org")
        other_team = Team.objects.create(organization=other_org, name="Other Team")
        env = SandboxEnvironment.objects.create(
            team=other_team, name="Other Team Env", network_access_level="full", created_by=self.user
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background", "sandbox_environment_id": str(env.id)},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_400_BAD_REQUEST)

    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    def test_run_task_without_sandbox_environment_backward_compatible(self, mock_workflow):
        task = self.create_task()
        task.repository = "org/repo"
        task.github_integration = Integration.objects.create(team=self.team, kind="github")
        task.save()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background"},
            format="json",
        )
        self.assertEqual(response.status_code, status.HTTP_200_OK)

        task_run = TaskRun.objects.filter(task=task).latest("created_at")
        self.assertNotIn("sandbox_environment_id", task_run.state)


class TestCloudUsageGate(BaseTaskAPITest):
    OVER_LIMIT: ClassVar[CodeUsageStatus] = CodeUsageStatus(
        is_rate_limited=True,
        limit_type="burst",
        reset_at="2026-06-09T00:00:00Z",
        is_pro=False,
    )

    def _cloud_run(self, task, status_value=TaskRun.Status.QUEUED):
        return TaskRun.objects.create(
            task=task,
            team=self.team,
            environment=TaskRun.Environment.CLOUD,
            status=status_value,
        )

    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_run_over_limit_returns_429_and_creates_no_run(self, mock_gate):
        mock_gate.return_value = self.OVER_LIMIT
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "usage_limit_exceeded")
        self.assertEqual(response.json()["limit_type"], "burst")
        self.assertFalse(TaskRun.objects.filter(task=task).exists())

    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_create_cloud_run_over_limit_returns_429_and_creates_no_run(self, mock_gate):
        mock_gate.return_value = self.OVER_LIMIT
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {"environment": "cloud"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "usage_limit_exceeded")
        self.assertFalse(TaskRun.objects.filter(task=task).exists())

    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_create_local_run_is_not_gated(self, mock_gate):
        mock_gate.return_value = self.OVER_LIMIT
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/",
            {"environment": "local"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_201_CREATED)
        mock_gate.assert_not_called()
        self.assertTrue(TaskRun.objects.filter(task=task).exists())

    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_start_over_limit_returns_429(self, mock_gate):
        mock_gate.return_value = self.OVER_LIMIT
        task = self.create_task()
        run = self._cloud_run(task)

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/start/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "usage_limit_exceeded")
        run.refresh_from_db()
        self.assertEqual(run.status, TaskRun.Status.QUEUED)

    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_resume_in_cloud_over_limit_returns_429(self, mock_gate):
        mock_gate.return_value = self.OVER_LIMIT
        task = self.create_task()
        run = TaskRun.objects.create(
            task=task,
            team=self.team,
            environment=TaskRun.Environment.LOCAL,
            status=TaskRun.Status.COMPLETED,
        )

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/runs/{run.id}/resume_in_cloud/",
            {},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_429_TOO_MANY_REQUESTS)
        self.assertEqual(response.json()["code"], "usage_limit_exceeded")

    @parameterized.expand(
        [
            ("fail_open", None),
            ("under_limit", CodeUsageStatus(is_rate_limited=False, limit_type=None, reset_at=None, is_pro=False)),
        ]
    )
    @patch("products.tasks.backend.temporal.client.execute_task_processing_workflow")
    @patch("products.tasks.backend.logic.services.code_usage_gate.get_posthog_code_usage")
    def test_run_proceeds_when_not_blocked(self, _name, gate_return, mock_gate, mock_workflow):
        mock_gate.return_value = gate_return
        task = self.create_task()

        response = self.client.post(
            f"/api/projects/@current/tasks/{task.id}/run/",
            {"mode": "background"},
            format="json",
        )

        self.assertEqual(response.status_code, status.HTTP_200_OK)
        mock_gate.assert_called_once()
        self.assertTrue(TaskRun.objects.filter(task=task).exists())
        mock_workflow.assert_called_once()


class TestGetPosthogCodeUsage(TestCase):
    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("products.tasks.backend.logic.services.code_usage_gate.requests.get")
    @patch("products.tasks.backend.logic.services.code_usage_gate.create_oauth_access_token_for_user")
    def test_parses_rate_limited_usage(self, mock_token, mock_get):
        mock_token.return_value = "tok"
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "is_rate_limited": True,
                "burst": {"exceeded": True, "reset_at": "2026-06-09T00:00:00Z"},
                "sustained": {"exceeded": False, "reset_at": "2026-07-01T00:00:00Z"},
                "is_pro": True,
            },
        )

        usage = get_posthog_code_usage(MagicMock(), 1)

        assert usage is not None
        self.assertTrue(usage.is_rate_limited)
        self.assertEqual(usage.limit_type, "burst")
        self.assertEqual(usage.reset_at, "2026-06-09T00:00:00Z")
        self.assertTrue(usage.is_pro)
        self.assertEqual(mock_get.call_args.args[0], "https://gateway.us.posthog.com/v1/usage/posthog_code")

    @override_settings(DEBUG=True, CLOUD_DEPLOYMENT=None)
    def test_local_uses_localhost_gateway(self):
        self.assertEqual(_gateway_usage_url(), "http://localhost:3308/v1/usage/posthog_code")

    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("products.tasks.backend.logic.services.code_usage_gate.OAuthAccessToken")
    @patch("products.tasks.backend.logic.services.code_usage_gate.requests.get")
    @patch("products.tasks.backend.logic.services.code_usage_gate.create_oauth_access_token_for_user")
    def test_token_cleanup_error_does_not_break_fail_open(self, mock_token, mock_get, mock_oauth_model):
        mock_token.return_value = "tok"
        mock_get.return_value = MagicMock(
            status_code=200,
            json=lambda: {
                "is_rate_limited": True,
                "burst": {"exceeded": True, "reset_at": "2026-06-09T00:00:00Z"},
                "sustained": {"exceeded": False, "reset_at": "2026-07-01T00:00:00Z"},
                "is_pro": False,
            },
        )
        mock_oauth_model.objects.filter.return_value.delete.side_effect = Exception("db down")

        usage = get_posthog_code_usage(MagicMock(), 1)

        assert usage is not None
        self.assertTrue(usage.is_rate_limited)

    @parameterized.expand(
        [
            ("non_200", 500, None),
            ("network_error", None, None),
        ]
    )
    @override_settings(CLOUD_DEPLOYMENT="US")
    @patch("products.tasks.backend.logic.services.code_usage_gate.requests.get")
    @patch("products.tasks.backend.logic.services.code_usage_gate.create_oauth_access_token_for_user")
    def test_fails_open_on_gateway_error(self, _name, status_code, _unused, mock_token, mock_get):
        mock_token.return_value = "tok"
        if status_code is None:
            mock_get.side_effect = requests.RequestException("boom")
        else:
            mock_get.return_value = MagicMock(status_code=status_code)

        self.assertIsNone(get_posthog_code_usage(MagicMock(), 1))

    @override_settings(DEBUG=False, CLOUD_DEPLOYMENT="DEV")
    @patch("products.tasks.backend.logic.services.code_usage_gate.create_oauth_access_token_for_user")
    def test_fails_open_when_no_gateway_url(self, mock_token):
        self.assertIsNone(get_posthog_code_usage(MagicMock(), 1))
        mock_token.assert_not_called()
