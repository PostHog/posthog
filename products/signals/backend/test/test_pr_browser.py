from datetime import UTC, datetime, timedelta

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from django.core.cache import cache

from parameterized import parameterized

from posthog.models import Integration, User
from posthog.models.integration import GitHubIntegration

from products.signals.backend.models import SignalReport
from products.signals.backend.monitor_pr import monitor_key


class TestPRBrowser(APIBaseTest):
    def setUp(self):
        super().setUp()
        cache.clear()
        self.url = f"/api/projects/{self.team.id}/signals/pull_requests/"
        Integration.objects.create(
            team=self.team, kind="github", integration_id="123", config={"account": {"name": "example"}}
        )
        self.items = [self.item(number) for number in range(120, 0, -1)]
        for mocked in (
            patch.object(User, "get_github_login", return_value="example-author"),
            patch.object(
                GitHubIntegration, "list_all_cached_repositories", return_value=[{"full_name": "example/widget"}]
            ),
            patch.object(GitHubIntegration, "api_request", side_effect=self.search),
        ):
            mocked.start()
            self.addCleanup(mocked.stop)

    def item(self, number, repository="example/widget"):
        created_at = (datetime(2026, 1, 1, tzinfo=UTC) + timedelta(hours=number)).isoformat()
        return {
            "html_url": f"https://github.com/{repository}/pull/{number}",
            "title": f"Change {number}",
            "state": "open",
            "user": {"login": "example-author"},
            "created_at": created_at,
            "updated_at": created_at,
        }

    def search(self, method, path, **kwargs):
        params = kwargs["params"]
        assert "author:example-author" in params["q"]
        assert "user:example" in params["q"]
        assert params["sort"] == "created" and params["order"] == "desc"
        start = (params["page"] - 1) * 100
        return Mock(ok=True, json=lambda: {"items": self.items[start : start + 100], "total_count": len(self.items)})

    @parameterized.expand([("all",), ("monitored",), ("unmonitored",)])
    def test_filters_across_search_pages_and_only_returns_own_project_report(self, monitoring):
        self.items.insert(0, self.item(999, "example/unregistered"))
        pr_url = "https://github.com/example/widget/pull/5"
        own = SignalReport.objects.create(
            team=self.team,
            created_by=self.user,
            scout_idempotency_key=monitor_key(self.user.id, pr_url),
            status=SignalReport.Status.READY,
        )
        someone = User.objects.create_and_join(self.organization, email="someone@example.com", password="test")
        SignalReport.objects.create(
            team=self.team,
            created_by=someone,
            scout_idempotency_key=monitor_key(someone.id, "https://github.com/example/widget/pull/6"),
            status=SignalReport.Status.MONITORING,
        )
        response = self.client.get(self.url, {"monitoring": monitoring})
        self.assertEqual(response.status_code, 200, response.data)
        results = response.data["results"]
        cursor = response.data["next_cursor"]
        while cursor:
            response = self.client.get(self.url, {"monitoring": monitoring, "cursor": cursor})
            self.assertEqual(response.status_code, 200, response.data)
            results.extend(response.data["results"])
            cursor = response.data["next_cursor"]
        expected = [n for n in range(120, 0, -1) if monitoring == "all" or (n == 5) == (monitoring == "monitored")]
        self.assertEqual([pr["number"] for pr in results], expected)
        for pr in results:
            self.assertEqual(pr["report"], {"id": str(own.id), "status": "ready"} if pr["number"] == 5 else None)

    def test_cursor_cannot_be_reused_for_another_filter_or_tampered_with(self):
        with self.settings(SIGNALS_PR_BROWSER_CURSOR_SIGNING_KEYS=["old-cursor-test-key"]):
            cursor = self.client.get(self.url).data["next_cursor"]
            self.assertEqual(self.client.get(self.url, {"monitoring": "monitored", "cursor": cursor}).status_code, 400)
            self.assertEqual(self.client.get(self.url, {"cursor": cursor + "x"}).status_code, 400)
        with self.settings(SIGNALS_PR_BROWSER_CURSOR_SIGNING_KEYS=["new-cursor-test-key", "old-cursor-test-key"]):
            self.assertEqual(self.client.get(self.url, {"cursor": cursor}).status_code, 200)
        with self.settings(SIGNALS_PR_BROWSER_CURSOR_SIGNING_KEYS=["new-cursor-test-key"]):
            self.assertEqual(self.client.get(self.url, {"cursor": cursor}).status_code, 400)
        with self.settings(SIGNALS_PR_BROWSER_CURSOR_SIGNING_KEYS=[]):
            self.assertEqual(self.client.get(self.url).status_code, 400)

    @parameterized.expand([(True,), (False,)])
    def test_overview_uses_registered_repository_and_distinguishes_unavailable_checks(self, checks_available):
        pr = {
            "success": True,
            "title": "Improve checkout",
            "merged": False,
            "state": "open",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
        }
        with (
            patch.object(GitHubIntegration, "get_pull_request", return_value=pr),
            patch.object(
                GitHubIntegration,
                "get_pull_request_checks",
                return_value={"success": checks_available, "has_conflict": True, "checks": []},
            ),
        ):
            response = self.client.get(self.url + "overview/", {"pr_url": "https://github.com/example/widget/pull/1"})
            self.assertEqual(response.status_code, 200, response.data)
            self.assertEqual(response.data["checks_available"], checks_available)
            self.assertTrue(response.data["has_conflicts"])
            self.assertEqual(
                self.client.get(
                    self.url + "overview/", {"pr_url": "https://github.com/example/unregistered/pull/1"}
                ).status_code,
                400,
            )
