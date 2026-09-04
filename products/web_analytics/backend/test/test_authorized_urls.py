from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.health_issue import HealthIssue
from posthog.tasks.health_checks import evaluate_health_check_for_team

from products.web_analytics.backend.temporal.health_checks.authorized_urls import AuthorizedUrlsCheck


class TestAuthorizedUrlsEvaluation(BaseTest):
    def test_creates_issue_when_team_has_no_app_urls(self):
        self.team.app_urls = []
        self.team.save()
        HealthIssue.objects.filter(team_id=self.team.id, kind=AuthorizedUrlsCheck.kind).delete()

        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        issues = HealthIssue.objects.filter(
            team_id=self.team.id,
            kind=AuthorizedUrlsCheck.kind,
            status=HealthIssue.Status.ACTIVE,
        )
        self.assertEqual(issues.count(), 1)
        self.assertEqual(issues.get().severity, HealthIssue.Severity.WARNING)

    def test_resolves_active_issue_when_team_has_app_urls(self):
        self.team.app_urls = []
        self.team.save()
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)
        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.ACTIVE
            ).count(),
            1,
        )

        self.team.app_urls = ["https://example.com"]
        self.team.save()
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.ACTIVE
            ).count(),
            0,
        )
        self.assertEqual(
            HealthIssue.objects.filter(
                team_id=self.team.id, kind=AuthorizedUrlsCheck.kind, status=HealthIssue.Status.RESOLVED
            ).count(),
            1,
        )

    def test_idempotent_for_healthy_team(self):
        self.team.app_urls = ["https://example.com"]
        self.team.save()

        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)
        evaluate_health_check_for_team(AuthorizedUrlsCheck.kind, self.team.id)

        self.assertEqual(
            HealthIssue.objects.filter(team_id=self.team.id, kind=AuthorizedUrlsCheck.kind).count(),
            0,
        )


class TestAuthorizedUrlsSignal(BaseTest):
    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_team_save_dispatches_task_on_commit(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.app_urls = ["https://example.com"]
            self.team.save()

        mock_task.delay.assert_called_with("authorized_urls", self.team.id)

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_task_not_dispatched_before_commit(self, mock_task):
        with self.captureOnCommitCallbacks(execute=False):
            self.team.app_urls = ["https://example.com"]
            self.team.save()

        mock_task.delay.assert_not_called()

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_task_not_dispatched_when_app_urls_not_in_update_fields(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.name = "renamed"
            self.team.save(update_fields=["name"])

        mock_task.delay.assert_not_called()

    @patch("posthog.tasks.health_checks.evaluate_health_check_for_team")
    def test_task_dispatched_when_app_urls_in_update_fields(self, mock_task):
        with self.captureOnCommitCallbacks(execute=True):
            self.team.app_urls = ["https://example.com"]
            self.team.save(update_fields=["app_urls"])

        mock_task.delay.assert_called_with("authorized_urls", self.team.id)


class TestAuthorizedUrlsMismatchDetection(BaseTest):
    def _detect(self, rows: list[tuple]) -> dict:
        with patch(
            "products.web_analytics.backend.temporal.health_checks.authorized_urls.execute_clickhouse_health_team_query",
            return_value=rows,
        ):
            return AuthorizedUrlsCheck().detect([self.team.id])

    def _rows(self, hosts: list[tuple[str, int]], total: int | None = None) -> list[tuple]:
        team_total = total if total is not None else sum(count for _, count in hosts)
        return [(self.team.id, host, count, team_total) for host, count in hosts]

    def test_flags_team_whose_traffic_left_its_authorized_domains(self):
        self.team.app_urls = ["https://old.example.com"]
        self.team.save()

        issues = self._detect(self._rows([("new.example.com", 900), ("blog.example.net", 100)]))

        assert list(issues) == [self.team.id]
        payload = issues[self.team.id][0].payload
        assert payload["reason_code"] == "domain_mismatch"
        assert payload["configured_urls"] == ["https://old.example.com"]
        assert payload["unauthorized_hosts"][0] == {"host": "new.example.com", "pageviews": 900}
        assert "new.example.com" in payload["reason"]

    def test_mismatch_issue_hashes_apart_from_the_missing_urls_issue(self):
        self.team.app_urls = ["https://old.example.com"]
        self.team.save()

        issues = self._detect(self._rows([("new.example.com", 900)]))

        assert issues[self.team.id][0].hash_keys == ["reason_code"]

    @parameterized.expand(
        [
            ("exact host", ["https://example.com"], [("example.com", 900)]),
            ("host carries a port", ["http://localhost:8000"], [("localhost:3000", 900)]),
            ("www is equivalent", ["https://example.com"], [("www.example.com", 900)]),
            ("wildcard subdomain", ["https://*.example.com"], [("app.example.com", 900)]),
            ("one authorized domain of several", ["https://example.com"], [("other.com", 800), ("example.com", 100)]),
        ]
    )
    def test_stays_quiet_when_traffic_still_reaches_an_authorized_domain(self, _name, app_urls, hosts):
        self.team.app_urls = app_urls
        self.team.save()

        assert self._detect(self._rows(hosts)) == {}

    def test_stays_quiet_below_the_minimum_pageview_volume(self):
        self.team.app_urls = ["https://old.example.com"]
        self.team.save()

        assert self._detect(self._rows([("new.example.com", 20)])) == {}

    def test_stays_quiet_when_the_ranked_hosts_miss_most_of_the_traffic(self):
        self.team.app_urls = ["https://old.example.com"]
        self.team.save()

        assert self._detect(self._rows([("new.example.com", 900)], total=100_000)) == {}

    def test_skips_clickhouse_when_no_team_has_authorized_urls(self):
        self.team.app_urls = []
        self.team.save()

        with patch(
            "products.web_analytics.backend.temporal.health_checks.authorized_urls.execute_clickhouse_health_team_query"
        ) as mock_query:
            issues = AuthorizedUrlsCheck().detect([self.team.id])

        mock_query.assert_not_called()
        assert issues[self.team.id][0].payload["reason_code"] == "missing_urls"
