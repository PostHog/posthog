import base64
from datetime import timedelta

import time_machine
from posthog.test.base import BaseTest
from unittest.mock import Mock, patch

from django.contrib.sessions.backends.signed_cookies import SessionStore
from django.core.exceptions import PermissionDenied
from django.http import HttpResponse
from django.test import RequestFactory, SimpleTestCase, override_settings
from django.utils import timezone

import requests
import fakeredis
import requests_mock
from parameterized import parameterized

from posthog.csp_middleware import CSPMiddleware
from posthog.egress.github.transport import GitHubEgressBudgetExhausted
from posthog.egress.limiter.policies import Priority
from posthog.models import User

from products.tasks.backend.logic.services.infrastructure_status import InfrastructureStatus, SourceSnapshot
from products.tasks.backend.models import SandboxCustomImage
from products.tasks.backend.presentation.views.infrastructure_admin import infrastructure_admin
from products.tasks.backend.redis import get_tasks_cache


class TestInfrastructureAdminPermissions(SimpleTestCase):
    @parameterized.expand([(False, True, False), (True, False, False), (True, True, True)])
    def test_denies_non_staff_inactive_and_impersonated_users(
        self, staff: bool, active: bool, impersonated: bool
    ) -> None:
        request = RequestFactory().get("/admin/tasks/task/infrastructure/", {"source": "custom"})
        request.user = User(is_staff=staff, is_active=active)
        request.session = SessionStore()
        if impersonated:
            request.session["loginas_from_user"] = "original-user"
        with self.assertRaises(PermissionDenied):
            infrastructure_admin(request)


@override_settings(
    TASKS_REDIS_URL="",
    GITHUB_APP_CLIENT_ID="",
    GITHUB_APP_PRIVATE_KEY="",
    CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}},
)
class TestInfrastructureSourceCache(SimpleTestCase):
    def setUp(self) -> None:
        get_tasks_cache().clear()
        self.redis = fakeredis.FakeRedis()
        redis_client = patch(
            "products.tasks.backend.logic.services.infrastructure_status.get_tasks_stream_redis_sync",
            return_value=self.redis,
        )
        redis_client.start()
        self.addCleanup(redis_client.stop)

    def test_expired_refresh_does_not_publish_or_release_the_next_owners_lock(self) -> None:
        cache = get_tasks_cache()
        key = "tasks:infrastructure-admin:v1:package"
        successor = self.redis.lock(f"{key}:lock", timeout=90, blocking=False)
        newer = SourceSnapshot(status="ok", observed_at=timezone.now(), data={"version": "2.0.0"})

        def response(*args: object, **kwargs: object) -> Mock:
            self.redis.pexpire(f"{key}:lock", 0)
            self.assertTrue(successor.acquire())
            cache.set(key, newer.model_dump_json())
            return Mock(json=lambda: {"version": "1.0.0"})

        collector = InfrastructureStatus()
        with patch("requests.get", side_effect=response):
            result = collector.read("package", collector.package)
        self.assertEqual(result.status, "refreshing")
        self.assertTrue(successor.owned())
        self.assertEqual(collector.read("package", collector.package), newer)

    @parameterized.expand(
        [("completed", "skipped"), ("completed", "failure"), ("queued", None), ("completed", "success")]
    )
    def test_workflow_success_does_not_hide_build_job_results(self, status: str, conclusion: str | None) -> None:
        responses = [
            Mock(json=lambda: {"content": base64.b64encode(b"ARG AGENT_VERSION=1.0.0").decode()}),
            Mock(json=lambda: {"workflow_runs": [{"id": 1, "status": "completed", "conclusion": "success"}]}),
            Mock(
                json=lambda: {
                    "jobs": [
                        {
                            "name": "Determine if sandbox image needs to be built",
                            "status": "completed",
                            "conclusion": "success",
                        },
                        {
                            "name": "Build and push Tasks Sandbox container image",
                            "status": status,
                            "conclusion": conclusion,
                            "steps": [
                                {
                                    "name": "Promote the smoked base image to :master",
                                    "status": "completed",
                                    "conclusion": "skipped",
                                }
                            ],
                        },
                        {
                            "name": "Build and push the derived sandbox images",
                            "status": status,
                            "conclusion": conclusion,
                        },
                    ]
                }
            ),
        ]
        collector = InfrastructureStatus()
        with patch("products.tasks.backend.logic.services.infrastructure_status.github_request", side_effect=responses):
            result = collector.read("release", collector.release).model_dump(mode="json")
        self.assertEqual(result["status"], "ok")
        self.assertEqual(
            result["data"]["runs"][0]["build_jobs"],
            [
                {"name": "Base images", "status": status, "conclusion": conclusion, "promotion": "skipped"},
                {"name": "Derived images", "status": status, "conclusion": conclusion, "promotion": None},
            ],
        )

    @parameterized.expand(
        [
            ("pin", "http"),
            ("runs", "http"),
            ("jobs_first", "http"),
            ("jobs_middle", "http"),
            ("jobs_last", "http"),
            ("pin", "budget"),
            ("jobs_middle", "budget"),
        ]
    )
    def test_github_failure_reports_safe_error_and_preserves_available_evidence(
        self, failed_read: str, failure_kind: str
    ) -> None:
        response = requests.Response()
        response.status_code = 401
        failure = (
            GitHubEgressBudgetExhausted("private upstream response", scope="example-installation")
            if failure_kind == "budget"
            else requests.HTTPError("private upstream response", response=response)
        )
        diagnostic = "shared request budget" if failure_kind == "budget" else "HTTP 401"
        jobs = [
            {"name": "Build and push Tasks Sandbox container image", "status": "completed", "conclusion": "success"}
        ]
        reads: list[Mock | Exception] = [
            Mock(json=lambda: {"content": base64.b64encode(b"ARG AGENT_VERSION=1.0.0").decode()}),
            Mock(
                json=lambda: {
                    "workflow_runs": [{"id": i, "html_url": f"https://example.com/runs/{i}"} for i in range(1, 4)]
                }
            ),
            *[Mock(json=lambda: {"jobs": jobs}) for _ in range(3)],
        ]
        reads[["pin", "runs", "jobs_first", "jobs_middle", "jobs_last"].index(failed_read)] = failure
        collector = InfrastructureStatus()
        with patch("products.tasks.backend.logic.services.infrastructure_status.github_request", side_effect=reads):
            result = collector.read("release", collector.release).model_dump(mode="json")
        if failed_read == "pin":
            self.assertEqual(result["status"], "error")
            self.assertIsNone(result["data"])
            self.assertIn(diagnostic, result["error"])
        else:
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["pin"], "1.0.0")
            self.assertIn(diagnostic, result["data"]["runs_error"])
            if failed_read == "runs":
                self.assertEqual(result["data"]["runs"], [])
            else:
                self.assertEqual([run["id"] for run in result["data"]["runs"]], [1, 2, 3])
                failed_id = ["jobs_first", "jobs_middle", "jobs_last"].index(failed_read) + 1
                for run in result["data"]["runs"]:
                    self.assertEqual(run["html_url"], f"https://example.com/runs/{run['id']}")
                    if run["id"] == failed_id:
                        self.assertEqual(run["build_jobs"], [])
                        self.assertIn(diagnostic, run["build_jobs_error"])
                    else:
                        self.assertEqual(run["build_jobs"][0]["conclusion"], "success")
                        self.assertIsNone(run["build_jobs_error"])
        self.assertNotIn("private upstream response", str(result))
        self.assertNotIn("example-installation", str(result))

    def test_workflow_list_failures_retain_history_without_refreshing_its_timestamp(self) -> None:
        with (
            time_machine.travel("2026-01-01T12:00:00Z", tick=False) as clock,
            patch("products.tasks.backend.logic.services.infrastructure_status.github_request") as request,
        ):
            request.side_effect = [
                Mock(json=lambda: {"content": base64.b64encode(b"ARG AGENT_VERSION=1.0.0").decode()}),
                Mock(json=lambda: {"workflow_runs": [{"id": 1, "html_url": "https://example.com/runs/1"}]}),
                Mock(json=lambda: {"jobs": []}),
            ]
            collector = InfrastructureStatus()
            original = collector.read("release", collector.release).model_dump(mode="json")
            for _ in range(2):
                clock.shift(timedelta(minutes=2))
                request.side_effect = [
                    Mock(json=lambda: {"content": base64.b64encode(b"ARG AGENT_VERSION=1.1.0").decode()}),
                    requests.Timeout(),
                ]
                retained = collector.read("release", collector.release).model_dump(mode="json")
                self.assertEqual(retained["status"], "ok")
                self.assertEqual(retained["data"]["pin"], "1.1.0")
                self.assertEqual(retained["data"]["runs"], original["data"]["runs"])
                self.assertEqual(retained["data"]["runs_observed_at"], original["data"]["runs_observed_at"])
                self.assertTrue(retained["data"]["runs_stale"])
                self.assertIn("timed out", retained["data"]["runs_error"])
                self.assertNotEqual(retained["observed_at"], original["observed_at"])

    def test_failed_refresh_preserves_evidence_without_claiming_freshness(self) -> None:
        collector = InfrastructureStatus()
        now = timezone.now()
        with (
            time_machine.travel(now, tick=False),
            patch("requests.get", return_value=Mock(json=lambda: {"version": "1.0.0"})),
        ):
            first = collector.read("package", collector.package)
            self.assertEqual(first.status, "ok")
        with (
            time_machine.travel(now + timedelta(minutes=2), tick=False),
            patch("requests.get", side_effect=requests.Timeout),
        ):
            stale = collector.read("package", collector.package)
            self.assertEqual(stale.status, "error")
            self.assertEqual(stale.data, first.data)
            self.assertEqual(stale.observed_at, first.observed_at)
            self.assertIn("timed out", stale.error or "")

    def test_partial_registry_publication_is_not_healthy(self) -> None:
        responses = [
            Mock(json=lambda: {"token": "test-token"}),
            Mock(headers={"Docker-Content-Digest": "sha256:test"}, json=lambda: {"manifests": []}),
        ]
        collector = InfrastructureStatus()
        with patch("requests.get", side_effect=responses):
            result = collector.read("vm", lambda: collector.registry("vm"))
        self.assertEqual(result.status, "error")
        self.assertIsNone(result.data)

    @parameterized.expand([("success", 200, 201), ("installation_rejected", 401, 201), ("token_rejected", 200, 403)])
    @override_settings(
        GITHUB_APP_CLIENT_ID="example-app",
        GITHUB_APP_PRIVATE_KEY="example-private-key",
        GITHUB_TOKEN="example-rejected-shared-token",
    )
    def test_release_uses_repository_scoped_app_reads(
        self, _name: str, installation_status: int, token_status: int
    ) -> None:
        with (
            requests_mock.Mocker() as http,
            patch("posthog.models.github_integration_base.jwt.encode", return_value="example-app-jwt"),
            patch("posthog.egress.github.transport.consume_github_installation_sync", return_value=True) as budget,
        ):
            http.get(
                "https://api.github.com/repos/PostHog/posthog/installation",
                request_headers={"Authorization": "Bearer example-app-jwt"},
                json={"id": 12345},
                status_code=installation_status,
            )
            mint = http.post(
                "https://api.github.com/app/installations/12345/access_tokens",
                request_headers={"Authorization": "Bearer example-app-jwt"},
                json={"token": "example-read-only-token"},
                status_code=token_status,
            )
            headers = {"Authorization": "Bearer example-read-only-token"}
            pin = http.get(
                "https://api.github.com/repos/PostHog/posthog/contents/products/tasks/backend/sandbox/images/Dockerfile.sandbox-base?ref=master",
                request_headers=headers,
                json={"content": base64.b64encode(b"ARG AGENT_VERSION=1.0.0").decode()},
            )
            http.get(
                "https://api.github.com/repos/PostHog/posthog/actions/workflows/cd-sandbox-base-image.yml/runs?branch=master&event=push&per_page=5",
                request_headers=headers,
                json={"workflow_runs": [{"id": 1}]},
            )
            http.get(
                "https://api.github.com/repos/PostHog/posthog/actions/runs/1/jobs?per_page=100",
                request_headers=headers,
                json={"jobs": []},
            )
            collector = InfrastructureStatus()
            result = collector.read("release", collector.release).model_dump(mode="json")

        if installation_status != 200 or token_status != 201:
            self.assertEqual(result["status"], "error")
            self.assertIsNone(result["data"])
            self.assertIn(
                f"HTTP {installation_status if installation_status != 200 else token_status}", result["error"]
            )
            self.assertFalse(pin.called)
        else:
            self.assertEqual(result["status"], "ok")
            self.assertEqual(result["data"]["pin"], "1.0.0")
            self.assertIsNone(result["data"]["runs_error"])
            self.assertEqual(mint.call_count, 1)
            self.assertEqual(
                mint.last_request.json(),
                {"repositories": ["posthog"], "permissions": {"contents": "read", "actions": "read"}},
            )
            self.assertEqual(budget.call_count, 3)
            for call in budget.call_args_list:
                self.assertEqual(call.args, ("12345",))
                self.assertEqual(call.kwargs["priority"], Priority.NORMAL)
        self.assertNotIn("example-read-only-token", str(result))
        self.assertNotIn("example-app-jwt", str(result))


@override_settings(TASKS_REDIS_URL="", CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
class TestInfrastructureInventory(BaseTest):
    def test_staff_inventory_contains_lineage_without_private_build_content(self) -> None:
        get_tasks_cache().clear()
        self.user.is_staff = True
        self.user.save()
        self.client.force_login(self.user)
        image = SandboxCustomImage.objects.for_team(self.team.id).create(
            team=self.team,
            name="Private test image",
            spec={"packages": ["example-package"]},
            status="ready",
            version=3,
            modal_image_name="test-image:v3",
            base_image_reference="ghcr.io/posthog/posthog-sandbox-vm@sha256:old",
            base_image_refresh_reference=None,
            error="private build failure detail",
            build_log="private build output",
        )
        SandboxCustomImage.objects.for_team(self.team.id).create(team=self.team, name="Archived", status="archived")
        response = self.client.get("/admin/tasks/task/infrastructure/", {"source": "custom"})
        self.assertEqual(response.status_code, 200)
        rows = response.json()["data"]["images"]
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["id"], str(image.id))
        self.assertEqual(rows[0]["base_image_reference"], image.base_image_reference)
        self.assertTrue(rows[0]["has_error"])
        self.assertTrue(rows[0]["has_published_image"])
        for private_value in (
            "Private test image",
            "private build failure detail",
            "private build output",
            "example-package",
        ):
            self.assertNotIn(private_value, response.content.decode())
        self.assertIn("no-cache", response["Cache-Control"])
        self.assertEqual(self.client.post("/admin/tasks/task/infrastructure/", {"source": "custom"}).status_code, 405)


@override_settings(ADMIN_PORTAL_ENABLED=True, JS_URL="https://assets.example.com", DEBUG=False)
class TestInfrastructureAdminCSP(SimpleTestCase):
    @parameterized.expand([("/admin/tasks/task/infrastructure/", True), ("/admin/", False)])
    def test_bundle_origin_is_limited_to_infrastructure_page(self, path: str, allowed: bool) -> None:
        request = RequestFactory().get(path)
        response = CSPMiddleware(lambda _: HttpResponse("page"))(request)
        directives = dict(part.split(" ", 1) for part in response["Content-Security-Policy"].split("; "))
        self.assertEqual("https://assets.example.com" in directives["script-src"], allowed)
        self.assertEqual("https://assets.example.com" in directives["style-src"], allowed)
        self.assertEqual(directives["frame-ancestors"], "'none'")
