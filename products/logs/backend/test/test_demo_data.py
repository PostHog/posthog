import datetime as dt

from posthog.test.base import APIBaseTest, ClickhouseTestMixin

from posthog.clickhouse.client import sync_execute

from products.logs.backend.demo_data import _SERVICES, _SEVERITY_NUMBERS, generate_demo_logs


class TestGenerateDemoLogs(ClickhouseTestMixin, APIBaseTest):
    def test_returns_zero_when_days_past_is_zero(self):
        inserted = generate_demo_logs(self.team.id, now=dt.datetime.now(dt.UTC), days_past=0, seed="test")
        assert inserted == 0

    def test_inserts_rows_for_team(self):
        now = dt.datetime(2025, 6, 1, 12, 0, 0, tzinfo=dt.UTC)
        inserted = generate_demo_logs(
            self.team.id, now=now, days_past=1, seed="test", logs_per_minute=2, batch_size=200
        )
        assert inserted > 0

        rows = sync_execute(
            "SELECT count() FROM logs WHERE team_id = %(team_id)s",
            {"team_id": self.team.id},
        )
        assert rows[0][0] == inserted

    def test_isolates_by_team_id(self):
        now = dt.datetime(2025, 6, 1, 12, 0, 0, tzinfo=dt.UTC)
        generate_demo_logs(self.team.id, now=now, days_past=1, seed="test", logs_per_minute=1)
        other_team_count = sync_execute(
            "SELECT count() FROM logs WHERE team_id = %(team_id)s",
            {"team_id": self.team.id + 99999},
        )[0][0]
        assert other_team_count == 0

    def test_emits_known_services_and_severities(self):
        now = dt.datetime(2025, 6, 1, 12, 0, 0, tzinfo=dt.UTC)
        # Enough volume + a single deterministic seed so this is stable across runs.
        generate_demo_logs(self.team.id, now=now, days_past=1, seed="test", logs_per_minute=4)
        services = {
            row[0]
            for row in sync_execute(
                "SELECT DISTINCT service_name FROM logs WHERE team_id = %(team_id)s",
                {"team_id": self.team.id},
            )
        }
        expected_services = {service["name"] for service in _SERVICES}
        # At minimum all services should be representable; not strictly required to all show
        # in every run, but the seed is deterministic so this is stable.
        assert services.issubset(expected_services)
        assert services  # not empty

        severities = {
            row[0]
            for row in sync_execute(
                "SELECT DISTINCT severity_text FROM logs WHERE team_id = %(team_id)s",
                {"team_id": self.team.id},
            )
        }
        assert severities.issubset(set(_SEVERITY_NUMBERS.keys()))
        assert "info" in severities

    def test_is_deterministic_for_same_seed(self):
        now = dt.datetime(2025, 6, 1, 12, 0, 0, tzinfo=dt.UTC)
        a = generate_demo_logs(self.team.id, now=now, days_past=1, seed="seed-x", logs_per_minute=2)
        b = generate_demo_logs(self.team.id + 1, now=now, days_past=1, seed="seed-x", logs_per_minute=2)
        assert a == b
