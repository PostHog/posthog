import json
from datetime import timedelta

import pytest
from posthog.test.base import BaseTest
from unittest.mock import patch

from django.utils import timezone

import numpy as np
import xgboost as xgb
from botocore.exceptions import ClientError

from products.signals.backend.models import SignalReport, SignalReportScore
from products.signals.backend.ranking.features import FEATURE_NAMES, FEATURE_SCHEMA_VERSION, feature_vector
from products.signals.backend.ranking.judgments import Judgment
from products.signals.backend.ranking.model_store import (
    ModelContractError,
    RankingModel,
    champion_object_key,
    load_champion,
    model_object_key,
)
from products.signals.backend.ranking.scorer import report_feature_row, score_reports
from products.signals.backend.ranking.sweep import reports_due_for_scoring, score_inbox_reports


def _booster(feature_names: list[str] | None = None) -> bytes:
    names = feature_names or list(FEATURE_NAMES)
    rng = np.random.default_rng(0)
    x = rng.random((200, len(names)))
    y = (x[:, 0] > 0.5).astype(int)
    model = xgb.XGBClassifier(n_estimators=5, max_depth=2)
    model.fit(x, y)
    booster = model.get_booster()
    booster.feature_names = names
    return bytes(booster.save_raw("ubj"))


class FakeS3:
    """Just enough of the boto3 S3 client for load_champion."""

    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects

    def get_object(self, Bucket: str, Key: str):  # noqa: N803
        if Key not in self.objects:
            raise ClientError({"Error": {"Code": "NoSuchKey"}}, "GetObject")
        return {"Body": _Body(self.objects[Key])}


class _Body:
    def __init__(self, data: bytes) -> None:
        self.data = data

    def read(self) -> bytes:
        return self.data


PREFIX = "inbox_ranking"


def _champion_objects(*, schema_version: int = FEATURE_SCHEMA_VERSION, feature_names=None, booster_names=None):
    metadata = {
        "model_version": "2026-08-19",
        "feature_schema_version": schema_version,
        "feature_names": list(feature_names or FEATURE_NAMES),
        "heads": [
            {"head": "open", "file": "open.ubj", "readable": True, "holdout_auc": 0.7},
            {"head": "action", "file": "action.ubj", "readable": False, "holdout_auc": 0.5},
        ],
    }
    return {
        champion_object_key(PREFIX): json.dumps(metadata).encode(),
        model_object_key(PREFIX, "2026-08-19", "open.ubj"): _booster(booster_names),
    }


@pytest.mark.parametrize(
    "objects,expected_error",
    [
        (_champion_objects(schema_version=FEATURE_SCHEMA_VERSION + 1), "feature_schema_version"),
        (_champion_objects(feature_names=[*FEATURE_NAMES, "extra"]), "feature_names differ"),
        (_champion_objects(booster_names=[f"f{i}" for i in range(len(FEATURE_NAMES))]), "booster feature_names"),
    ],
)
def test_load_champion_refuses_a_model_outside_the_feature_contract(objects, expected_error):
    with patch("products.signals.backend.ranking.model_store.settings") as settings:
        settings.INBOX_RANKING_DATASET_S3_BUCKET = "bucket"
        settings.INBOX_RANKING_DATASET_S3_PREFIX = PREFIX
        with pytest.raises(ModelContractError, match=expected_error):
            load_champion(FakeS3(objects))


def test_load_champion_serves_only_readable_heads_and_none_without_a_pointer():
    with patch("products.signals.backend.ranking.model_store.settings") as settings:
        settings.INBOX_RANKING_DATASET_S3_BUCKET = "bucket"
        settings.INBOX_RANKING_DATASET_S3_PREFIX = PREFIX
        assert load_champion(FakeS3({})) is None
        model = load_champion(FakeS3(_champion_objects()))
    assert model is not None
    assert model.model_version == "2026-08-19"
    assert set(model.boosters) == {"open"}


class TestScoringSweep(BaseTest):
    def _report(self, **kwargs) -> SignalReport:
        defaults = {
            "team": self.team,
            "status": SignalReport.Status.READY,
            "title": "Test report",
            "summary": "Test summary",
            "signal_count": 3,
            "total_weight": 2.0,
            "promoted_at": timezone.now() - timedelta(hours=2),
        }
        return SignalReport.objects.create(**{**defaults, **kwargs})

    def _model(self) -> RankingModel:
        booster = xgb.Booster()
        booster.load_model(bytearray(_booster()))
        return RankingModel(
            model_version="2026-08-19",
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            boosters={"open": booster},
            metadata={},
        )

    def _score(self, report: SignalReport, scored_at) -> SignalReportScore:
        return SignalReportScore.all_teams.create(
            team=self.team,
            report=report,
            model_version="2026-08-19",
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            features={},
            scores={"open": 0.5},
            scored_at=scored_at,
        )

    def test_report_feature_row_matches_the_snapshot_columns(self):
        now = timezone.now()
        report = self._report(created_at=now - timedelta(hours=5))
        report.created_at = now - timedelta(hours=5)
        row = report_feature_row(report, Judgment(priority="P1", actionability="not_actionable"), now)
        assert row["signal_count"] == 3 and row["title_chars"] == len("Test report")
        assert row["priority"] == "P1"
        assert row["age_hours"] == pytest.approx(5.0, abs=1e-3)
        assert len(feature_vector(row)) == len(FEATURE_NAMES)

    def test_score_reports_returns_a_probability_per_readable_head(self):
        report = self._report()
        scored = score_reports(self._model(), [report], {}, timezone.now())
        assert len(scored) == 1
        assert set(scored[0].scores) == {"open"} and 0.0 <= scored[0].scores["open"] <= 1.0
        assert scored[0].features["priority_known"] == 0.0 and scored[0].features["signal_count"] == 3.0

    def test_reports_due_for_scoring(self):
        never_scored = self._report()
        fresh = self._report()
        changed = self._report()
        stale = self._report()
        resolved = self._report(status=SignalReport.Status.RESOLVED)
        potential = self._report(status=SignalReport.Status.POTENTIAL, promoted_at=None)
        # Scores land after every report's creation-time updated_at.
        now = timezone.now()
        self._score(fresh, now)
        self._score(changed, now)
        SignalReport.objects.filter(id=changed.id).update(updated_at=now + timedelta(seconds=1))
        SignalReport.objects.filter(id=stale.id).update(updated_at=now - timedelta(hours=72))
        self._score(stale, now - timedelta(hours=48))

        due = {report.id for report in reports_due_for_scoring(now + timedelta(seconds=2), 100)}
        assert due == {never_scored.id, changed.id, stale.id}
        assert fresh.id not in due and resolved.id not in due and potential.id not in due

    def test_score_inbox_reports_is_a_no_op_unless_enabled(self):
        self._report()
        with self.settings(SIGNALS_RANKING_SCORING_ENABLED=False):
            result = score_inbox_reports()
        assert result.skipped_reason == "disabled" and SignalReportScore.all_teams.count() == 0

    def test_score_inbox_reports_appends_one_row_per_due_report(self):
        report = self._report()
        with (
            self.settings(SIGNALS_RANKING_SCORING_ENABLED=True),
            patch("products.signals.backend.ranking.sweep.load_champion", return_value=self._model()),
        ):
            first = score_inbox_reports()
            second = score_inbox_reports()
        assert first.scored == 1 and first.model_version == "2026-08-19"
        # Unchanged and freshly scored: the second tick has nothing to do and appends nothing.
        assert second.scored == 0
        rows = list(SignalReportScore.objects.filter(team=self.team, report=report))
        assert len(rows) == 1
        assert set(rows[0].scores) == {"open"} and rows[0].features["signal_count"] == 3.0
        assert rows[0].feature_schema_version == FEATURE_SCHEMA_VERSION
