from datetime import UTC, datetime

from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from products.signals.backend.models import SignalTeamConfig
from products.signals.backend.repo_availability import note_repo_selection_ask_raised, repo_ask_holds_promotion

REPO_AVAILABILITY_MODULE = "products.signals.backend.repo_availability"
ASKED_AT = datetime(2026, 9, 15, 5, 0, tzinfo=UTC)


class TestRepoAvailability(BaseTest):
    def setUp(self) -> None:
        super().setUp()
        # A SignalTeamConfig is auto-created for every team via register_team_extension_signal.
        self.config = SignalTeamConfig.objects.get(team=self.team)

    def _set_asked_at(self, asked_at: datetime | None) -> None:
        self.config.repo_selection_ask_raised_at = asked_at
        self.config.save(update_fields=["repo_selection_ask_raised_at"])

    def _patch_source(self, resolves: bool):
        return patch(
            f"{REPO_AVAILABILITY_MODULE}.resolve_team_github_integration",
            return_value=object() if resolves else None,
        )

    @parameterized.expand(
        [
            # Nothing asked yet: the report has to get through, because it is what raises the ask.
            ("first report on a repo-less team", False, None, False),
            # The ask is already open, so every later report would repeat the same question.
            ("later report on a repo-less team", False, ASKED_AT, True),
            # A source resolves, so selection has candidates and the report is a normal one.
            ("repository connected", True, None, False),
        ]
    )
    def test_promotion_is_held_only_once_the_ask_is_open(self, _name, resolves, asked_at, expected_held):
        self._set_asked_at(asked_at)
        with self._patch_source(resolves):
            assert repo_ask_holds_promotion(self.team) is expected_held

    def test_unasked_team_never_resolves_a_source(self):
        # Every signal in the fleet runs this gate, so a team with no open ask must pay only the
        # single indexed stamp read: there is nothing to hold and nothing to clear.
        with patch(f"{REPO_AVAILABILITY_MODULE}.resolve_team_github_integration") as resolve:
            with self.assertNumQueries(1):
                assert repo_ask_holds_promotion(self.team) is False
        resolve.assert_not_called()

    def test_reconnecting_a_source_clears_the_ask(self):
        # Without the clear, a team that connects a repository stays held for good: the stamp would
        # keep holding promotions that selection could now answer.
        self._set_asked_at(ASKED_AT)
        with self._patch_source(True):
            assert repo_ask_holds_promotion(self.team) is False
        self.config.refresh_from_db()
        assert self.config.repo_selection_ask_raised_at is None

    def test_gate_fails_open_when_the_source_lookup_raises(self):
        self._set_asked_at(ASKED_AT)
        with patch(
            f"{REPO_AVAILABILITY_MODULE}.resolve_team_github_integration",
            side_effect=RuntimeError("github unavailable"),
        ):
            assert repo_ask_holds_promotion(self.team) is False

    @parameterized.expand(
        [
            ("standing exit", "repo_selection_required", False, True),
            # The split telemetry names which exit ran; both stay the same ask.
            ("named standing exit", "repo_selection_required_no_integration", False, True),
            # The agent researched this report and asked about it, so the team's other reports must
            # keep running even if its integration lapsed in the meantime.
            ("agent asked about this report", "agent_requested", False, False),
            ("no reason recorded", None, False, False),
            # Selection has candidates, so this null repository was a decision about the report.
            ("source resolves", "repo_selection_required", True, False),
        ]
    )
    def test_only_the_standing_repo_selection_exit_records_an_ask(
        self, _name, pending_reason, source_resolves, expected_stamped
    ):
        with self._patch_source(source_resolves):
            note_repo_selection_ask_raised(self.team.id, pending_reason=pending_reason)
        self.config.refresh_from_db()
        assert (self.config.repo_selection_ask_raised_at is not None) is expected_stamped
