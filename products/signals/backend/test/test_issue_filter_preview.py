import json
from datetime import timedelta
from uuid import uuid4

import time_machine
from posthog.test.base import ClickhouseTestMixin, NonAtomicAPIBaseTest
from unittest.mock import patch

from django.utils import timezone

from faker import Faker

from posthog.hogql.property_access_types import RestrictedProperty

from posthog.clickhouse.client import sync_execute
from posthog.models import User
from posthog.models.scoping import team_scope

from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.event_definitions.backend.facade.enums import PropertyDefinitionType
from products.signals.backend.issue_filter_preview import PreviewSignal, preview_issue_filters
from products.signals.backend.models import SignalReport, SignalReportArtefact, SignalReportPullRequest, SignalSpend
from products.signals.backend.signal_metadata import EMBEDDING_MODEL


class TestIssueFilterPreview(ClickhouseTestMixin, NonAtomicAPIBaseTest):
    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self):
        super().setUp()
        self.enterContext(team_scope(self.team.pk))
        self.url = f"/api/projects/{self.team.pk}/signals/source_configs/issue_filter_preview/"

    def test_invalid_filter_returns_status(self):
        response = self.client.post(self.url, {"issue_filters": {"properties": [{"type": "person"}]}}, format="json")
        assert response.status_code == 200, response.content
        assert response.json()["status"] == "invalid_expression"
        assert response.json()["results"] == []

    def test_empty_window_for_one_transition(self):
        response = self.client.post(self.url, {"issue_filters": {}, "source_type": "issue_spiking"}, format="json")
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == "ok"
        assert [row["source_type"] for row in body["results"]] == ["issue_spiking"]
        assert body["results"][0]["passing_count"] == body["results"][0]["excluded_count"] == 0

    def test_cache_expires_and_keeps_filters_and_transition_types_separate(self):
        now = timezone.now()
        signal = PreviewSignal(
            timestamp=now, signal_id=str(uuid4()), source_type="issue_spiking", issue_id=str(uuid4()), report_id=""
        )
        with (
            time_machine.travel(now, tick=False) as clock,
            patch("products.signals.backend.issue_filter_preview.recent_signals", return_value=[]) as history,
        ):
            initial = preview_issue_filters(self.team, self.user, {}, "issue_spiking")
            assert initial["status"] == "ok"
            assert initial["results"][0]["passing_count"] == 0
            history.return_value = [signal]
            assert (
                preview_issue_filters(self.team, self.user, {"properties": [], "bytecode": []}, "issue_spiking")
                == initial
            )

            all_types = preview_issue_filters(self.team, self.user, {})
            assert sum(row["passing_count"] for row in all_types["results"]) == 1
            candidate = {"properties": [{"key": "severity", "operator": "is_set"}]}
            filtered = preview_issue_filters(self.team, self.user, candidate, "issue_spiking")
            assert filtered["results"][0]["unavailable_count"] == 1
            teammate = User.objects.create_and_join(self.organization, "teammate@example.com", None)
            assert preview_issue_filters(self.team, teammate, {}, "issue_spiking")["results"][0]["passing_count"] == 1

            clock.shift(timedelta(seconds=61))
            refreshed = preview_issue_filters(self.team, self.user, {}, "issue_spiking")
            assert refreshed["results"][0]["passing_count"] == 1

    def test_permission_change_blocks_a_cached_filter(self):
        candidate = {"properties": [{"key": "severity", "operator": "is_set"}]}
        assert preview_issue_filters(self.team, self.user, candidate)["status"] == "ok"
        restricted = RestrictedProperty(name="severity", property_type=PropertyDefinitionType.EVENT)
        with patch(
            "products.signals.backend.issue_filter_preview.access.get_restricted_properties_with_group_type_index_for_team",
            return_value={restricted},
        ):
            denied = preview_issue_filters(self.team, self.user, candidate)
        assert denied["status"] == "access_denied"
        assert denied["results"] == []

    def test_failed_replay_can_be_retried_immediately(self):
        with patch("products.signals.backend.issue_filter_preview.recent_signals", side_effect=TimeoutError):
            assert preview_issue_filters(self.team, self.user, {}, "issue_reopened")["status"] == "query_failed"
        assert preview_issue_filters(self.team, self.user, {}, "issue_reopened")["status"] == "ok"

    def test_reports_follow_only_excluded_transitions(self):
        now = timezone.now()
        passing, excluded, shared, unavailable = [str(uuid4()) for _ in range(4)]
        included_report, excluded_report = [
            SignalReport.objects.create(team=self.team, triggering_signal_id=signal_id)
            for signal_id in (passing, excluded)
        ]
        for number, report in enumerate((included_report, excluded_report), start=1):
            pr = SignalReportPullRequest.objects.create(
                team=self.team, repository="example/app", number=number, state=SignalReportPullRequest.State.MERGED
            )
            SignalReportArtefact.objects.create(
                team=self.team, report=report, type=SignalReportArtefact.ArtefactType.PULL_REQUEST, pull_request=pr
            )
        amount = Faker().pydecimal(left_digits=2, right_digits=2, positive=True)
        for signal in (passing, excluded, shared):
            SignalSpend.objects.for_team(self.team.pk).create(
                team=self.team, signal_id=signal, kind=SignalSpend.Kind.AD_HOC, finalized_at=now, spend=amount
            )
        documents = []
        for signal, report, age in (
            (passing, included_report, 1),
            (excluded, excluded_report, 2),
            (shared, excluded_report, 3),
            (unavailable, included_report, 4),
            (str(uuid4()), included_report, 8),
        ):
            stamp = now - timedelta(days=age)
            metadata = {
                "source_product": "error_tracking",
                "source_type": "issue_created",
                "source_id": str(uuid4()),
                "report_id": str(report.id),
            }
            documents.append(
                (
                    self.team.pk,
                    "signals",
                    "signal",
                    "plain",
                    signal,
                    stamp,
                    stamp,
                    "",
                    json.dumps(metadata),
                    [0.0] * 1536,
                    stamp,
                    0,
                    0,
                )
            )
        sync_execute(
            f"""INSERT INTO distributed_posthog_document_embeddings_{EMBEDDING_MODEL.value.replace("-", "_")}
            (team_id,product,document_type,rendering,document_id,timestamp,inserted_at,content,metadata,embedding,_timestamp,_offset,_partition) VALUES""",
            documents,
        )
        with patch(
            "products.signals.backend.issue_filter_preview.alerts.replay_signal_filters",
            return_value={
                passing: (LifecycleFilterOutcome.MATCH, {"severity": "high"}),
                excluded: (LifecycleFilterOutcome.EXCLUDED_BY_FILTER, {"severity": "low"}),
                shared: (LifecycleFilterOutcome.EXCLUDED_BY_FILTER, {"severity": "medium"}),
            },
        ):
            response = self.client.post(
                self.url,
                {"issue_filters": {"properties": [{"key": "severity", "type": "event", "value": "high"}]}},
                format="json",
            )
        assert response.status_code == 200, response.content
        body = response.json()
        assert body["status"] == "ok", body
        created, reopened, spiking = body["results"]
        assert (created["passing_count"], created["excluded_count"], created["unavailable_count"]) == (1, 2, 1)
        assert [sample["field_values"]["severity"] for sample in created["excluded"]] == ["low", "medium"]
        assert created["excluded_reports"] == {
            "count": 1,
            "with_pr": 1,
            "with_merged_pr": 1,
            "spend_usd_cents": float(amount + amount),
        }
        assert reopened["excluded_count"] == spiking["excluded_count"] == 0
