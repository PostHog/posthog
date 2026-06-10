import json

from posthog.test.base import BaseTest
from unittest.mock import AsyncMock, MagicMock, patch

from asgiref.sync import async_to_sync
from parameterized import parameterized

from products.signals.backend.facade.api import (
    ANOMALY_DETECTION_SKILL,
    EVIDENCE_SOURCE_PRODUCT_QUERY_RUNS,
    AnomalyFinding,
    get_team_anomalies,
)


def _signal_row(skill_name=ANOMALY_DETECTION_SKILL, short_id="abc123", with_short_id=True):
    evidence = [
        {
            "source_product": EVIDENCE_SOURCE_PRODUCT_QUERY_RUNS,
            "summary": "spike",
            **({"entity_id": short_id} if with_short_id else {}),
        }
    ]
    metadata = {
        "source_product": "signals_scout",
        "source_type": "cross_source_issue",
        "weight": 0.86,
        "deleted": False,
        "extra": {
            "skill_name": skill_name,
            "skill_version": 1.0,
            "confidence": 0.9,
            "finding_id": "f1",
            "scout_run_id": "r1",
            "task_run_id": "t1",
            "evidence": evidence,
            "hypothesis": "Likely a deploy regression.",
            "severity": "P1",
            "time_range": {"date_from": "2026-06-01T00:00:00Z", "date_to": "2026-06-08T00:00:00Z"},
        },
    }
    return ("doc-1", "Signups dropped 60%.", json.dumps(metadata), "2026-06-07T00:00:00Z")


class TestGetTeamAnomalies(BaseTest):
    def setUp(self):
        super().setUp()
        self.organization.is_ai_data_processing_approved = True
        self.organization.save()

    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows", new_callable=AsyncMock)
    def test_parses_and_scopes_to_anomaly_scout(self, mock_rows):
        mock_rows.return_value = [_signal_row(), _signal_row(skill_name="signals-scout-logs")]
        out = async_to_sync(get_team_anomalies)(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert len(out) == 1
        a = out[0]
        assert isinstance(a, AnomalyFinding)
        assert a.insight_short_id == "abc123"
        assert a.weight == 0.86
        assert a.hypothesis == "Likely a deploy regression."
        assert a.severity == "P1"
        assert a.time_range == ("2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")

    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows", new_callable=AsyncMock)
    def test_short_id_none_when_no_query_runs_evidence(self, mock_rows):
        mock_rows.return_value = [_signal_row(with_short_id=False)]
        out = async_to_sync(get_team_anomalies)(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert len(out) == 1
        assert out[0].insight_short_id is None

    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows", new_callable=AsyncMock)
    def test_empty_when_ai_not_approved(self, mock_rows):
        self.organization.is_ai_data_processing_approved = False
        self.organization.save()
        mock_rows.return_value = [_signal_row()]
        out = async_to_sync(get_team_anomalies)(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert out == []

    @parameterized.expand(
        [
            ("bare_string", "date_from..date_to"),  # substring trap: must not match via `in` on a str
            ("null_bound", {"date_from": None, "date_to": "2026-06-08T00:00:00Z"}),
            ("missing_date_to", {"date_from": "2026-06-01T00:00:00Z"}),
        ]
    )
    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows", new_callable=AsyncMock)
    def test_malformed_time_range_degrades_to_none(self, _name, time_range, mock_rows):
        # time_range is LLM-authored: anything but a dict with both truthy bounds must degrade to None.
        metadata = {
            "source_product": "signals_scout",
            "source_type": "cross_source_issue",
            "weight": 0.5,
            "deleted": False,
            "extra": {"skill_name": ANOMALY_DETECTION_SKILL, "time_range": time_range, "evidence": []},
        }
        mock_rows.return_value = [("doc", "content", json.dumps(metadata), "2026-06-07T00:00:00Z")]
        out = async_to_sync(get_team_anomalies)(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert len(out) == 1
        assert out[0].time_range is None

    @patch("products.signals.backend.facade.api.fetch_team_anomaly_signal_rows", new_callable=AsyncMock)
    def test_malformed_row_is_skipped_not_fatal(self, mock_rows):
        mock_rows.return_value = [("bad", "content", "{not valid json", "2026-06-07T00:00:00Z"), _signal_row()]
        out = async_to_sync(get_team_anomalies)(self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z")
        assert len(out) == 1  # the malformed row is skipped, the valid one survives
        assert out[0].insight_short_id == "abc123"


class TestFetchTeamAnomalySignalRows(BaseTest):
    def test_query_uses_single_brace_placeholders(self):
        from products.signals.backend.temporal import signal_queries

        captured = {}

        async def _fake(**kwargs):
            captured.update(kwargs)
            return MagicMock(results=[])

        with patch.object(signal_queries, "execute_hogql_query_with_retry", side_effect=_fake):
            async_to_sync(signal_queries.fetch_team_anomaly_signal_rows)(
                self.team, "2026-06-01T00:00:00Z", "2026-06-08T00:00:00Z"
            )

        query = captured["query"]
        assert "{{" not in query and "}}" not in query, f"double braces leaked into query: {query}"
        for ph in ("{team_id}", "{date_from}", "{date_to}", "{model_name}", "{source_product}", "{source_type}"):
            assert ph in query, f"missing placeholder {ph} in query: {query}"
        # placeholders dict must carry every placeholder the query references
        assert set(captured["placeholders"].keys()) >= {
            "team_id",
            "date_from",
            "date_to",
            "model_name",
            "source_product",
            "source_type",
        }
