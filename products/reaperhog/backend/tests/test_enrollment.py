from datetime import UTC, datetime, timedelta

from posthog.test.base import BaseTest, ClickhouseTestMixin, _create_event, flush_persons_and_events

from products.reaperhog.backend.logic.enrollment import FlagEnrollment, load_flag_enrollment


class TestLoadFlagEnrollment(ClickhouseTestMixin, BaseTest):
    def test_counts_evaluations_and_enabled_users_per_flag(self) -> None:
        evaluations: list[tuple[str, str, object]] = [
            ("beta", "u1", True),
            ("beta", "u1", True),
            ("beta", "u2", False),
            ("beta", "u3", "test"),
            ("beta", "u4", "false"),
            ("dark", "u1", False),
        ]
        for flag, distinct_id, response in evaluations:
            _create_event(
                team=self.team,
                event="$feature_flag_called",
                distinct_id=distinct_id,
                properties={"$feature_flag": flag, "$feature_flag_response": response},
            )
        _create_event(
            team=self.team, event="$feature_flag_called", distinct_id="u5", properties={"$feature_flag": "dark"}
        )
        _create_event(
            team=self.team,
            event="$feature_flag_called",
            distinct_id="u6",
            timestamp=datetime.now(UTC) - timedelta(days=91),
            properties={"$feature_flag": "beta", "$feature_flag_response": True},
        )
        _create_event(team=self.team, event="$pageview", distinct_id="u7", properties={"$feature_flag": "beta"})
        flush_persons_and_events()

        counts = load_flag_enrollment(self.team.id)

        assert counts == {
            "beta": FlagEnrollment(evaluations=5, users=4, enabled_evaluations=3, enabled_users=2),
            "dark": FlagEnrollment(evaluations=2, users=2, enabled_evaluations=0, enabled_users=0),
        }
