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
from parameterized import parameterized

from posthog.csp_middleware import CSPMiddleware
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


@override_settings(TASKS_REDIS_URL="", CACHES={"default": {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}})
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
