from posthog.test.base import BaseTest

from django.utils import timezone

from products.mcp_registry.backend.models import MCPMeasuredStats, MCPRankingRun, MCPRegistryServer
from products.mcp_registry.backend.ranking import compute_ranking_run, latest_completed_run


def _measured_server(error_rate_pct: float = 5.0, calls: int = 50_000) -> MCPRegistryServer:
    server = MCPRegistryServer.objects.create(display_name="Measured", is_measured=True)
    MCPMeasuredStats.objects.create(
        server=server,
        team_id=1,
        server_name="Measured",
        window_days=30,
        calls=calls,
        errors=int(calls * error_rate_pct / 100),
        error_rate_pct=error_rate_pct,
        intent_coverage_pct=90.0,
        link_method="exact_name",
        computed_at=timezone.now(),
    )
    return server


class TestRanking(BaseTest):
    def test_measured_signal_flips_ordering_only_in_the_measured_arm(self) -> None:
        measured = _measured_server()
        unmeasured = MCPRegistryServer.objects.create(
            display_name="Well documented", repository_url="https://github.com/example/mcp"
        )

        v1 = {score.server_id: score.score for score in compute_ranking_run("v1_metadata_prior").scores.all()}
        v2 = {score.server_id: score.score for score in compute_ranking_run("v2_measured_trust").scores.all()}

        # The control arm can't see usage, so the repo-backed server wins on metadata prior.
        assert v1[unmeasured.id] > v1[measured.id]
        assert v2[measured.id] > v2[unmeasured.id]

    def test_higher_error_rate_lowers_measured_trust(self) -> None:
        reliable = _measured_server(error_rate_pct=2.0)
        unreliable_server = MCPRegistryServer.objects.create(display_name="Flaky", is_measured=True)
        MCPMeasuredStats.objects.create(
            server=unreliable_server,
            team_id=2,
            server_name="Flaky",
            window_days=30,
            calls=50_000,
            errors=15_000,
            error_rate_pct=30.0,
            link_method="standalone",
            computed_at=timezone.now(),
        )

        scores = {score.server_id: score.score for score in compute_ranking_run("v2_measured_trust").scores.all()}

        assert scores[reliable.id] > scores[unreliable_server.id]

    def test_run_persists_scores_with_components(self) -> None:
        server = _measured_server()

        run = compute_ranking_run("v2_measured_trust")

        assert run.status == "completed"
        assert run.server_count == 1
        assert run.computed_at is not None
        score = run.scores.get(server=server)
        assert score.components["measured"] is True
        assert 0 < score.score <= 1

    def test_unknown_version_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            compute_ranking_run("v99_does_not_exist")

    def test_latest_completed_run_skips_failed_and_running(self) -> None:
        completed = compute_ranking_run("v1_metadata_prior")
        MCPRankingRun.objects.create(version="v1_metadata_prior", status="failed")
        MCPRankingRun.objects.create(version="v1_metadata_prior", status="running")

        assert latest_completed_run("v1_metadata_prior") == completed
        assert latest_completed_run("v2_measured_trust") is None
