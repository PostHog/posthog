"""Scores inbox reports with every model the serving manifest names.

One pass loads the serving set, reads each report's current vector once per rendering the models
need, builds each model's matrix through its own `FeatureSet.build_matrix`, and produces one
validated `RankingScore` per report. `build_matrix` is the code the training dag fits and grades
with, so a served score is the value the dag would produce for the same model and vector.

Nothing is written until every report of the call is scored, so a failure part of the way through
a call writes nothing.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

import pandas as pd
import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ScopedCapture

from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.ranking.features import (
    EMBEDDING_COLUMN,
    EMBEDDING_INSERTED_AT_COLUMN,
    REPORT_EMBEDDINGS_EXTRA,
    TITLE_EMBEDDINGS_EXTRA,
    FeatureSet,
    ReportEmbeddingsFeatureSet,
)
from products.signals.backend.ranking.model_store import LoadedModel, ServingSet, load_serving_set
from products.signals.backend.ranking.serving_manifest import ServingManifestEntry
from products.signals.backend.ranking.sinks import persist_scores
from products.signals.backend.report_embedding_reader import ReportVector, latest_report_vectors
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE, EMBEDDING_RENDERING_TITLE_SUMMARY

logger = structlog.get_logger(__name__)

NO_VECTOR = "no_vector"

# The rendering each embedding side input is the vector of. The dataset dag snapshots the same
# renderings under the same keys, so a model reads the text it was fit on.
RENDERING_BY_EXTRA: Mapping[str, str] = {
    REPORT_EMBEDDINGS_EXTRA: EMBEDDING_RENDERING_TITLE_SUMMARY,
    TITLE_EMBEDDINGS_EXTRA: EMBEDDING_RENDERING_TITLE,
}

# A model that did not load has no feature contract this pass could read.
UNKNOWN_FEATURE_SCHEMA_VERSION = 0

# Left off the copied metadata: an embedding set names 1536 columns, and `feature_set` with
# `feature_schema_version` already identify them.
_METADATA_FIELDS_NOT_COPIED = frozenset({"feature_names"})


class ScoringError(Exception):
    """The pass cannot produce a served score for any report."""


@frozen
class ReportScoringOutcome:
    report_id: str
    # None when the report could not be scored this pass.
    score: RankingScore | None
    # Why the report has no score, e.g. "no_vector". None when scored.
    reason: str | None


@frozen
class _ModelScores:
    """One model's pass over the call's reports: probabilities per report it could score, or the
    reason it scored none."""

    model: LoadedModel
    by_report: Mapping[str, Mapping[str, float]]
    skip_reason: str | None


def _served_extra(feature_set: FeatureSet) -> str | None:
    """The side input a set is served from, or None when this build does not serve the set yet."""
    if not isinstance(feature_set, ReportEmbeddingsFeatureSet):
        return None
    (extra,) = feature_set.extras_keys
    return extra if extra in RENDERING_BY_EXTRA else None


def _served_model_extra(served: LoadedModel) -> str:
    extra = _served_extra(served.feature_set)
    if extra is None:
        raise ScoringError(
            f"served model {served.entry.key} is on feature set {served.feature_set.name}, not served yet"
        )
    return extra


def served_rendering(serving: ServingSet) -> str:
    """The rendering the served model reads, so the vector a served score depends on."""
    return RENDERING_BY_EXTRA[_served_model_extra(serving.served)]


def _extras_frame(report_ids: Sequence[str], vectors: Mapping[str, ReportVector]) -> pd.DataFrame:
    present = [report_id for report_id in report_ids if report_id in vectors]
    return pd.DataFrame(
        {
            EMBEDDING_COLUMN: [vectors[report_id].embedding for report_id in present],
            EMBEDDING_INSERTED_AT_COLUMN: [vectors[report_id].inserted_at for report_id in present],
        },
        index=pd.Index(present, name="report_id"),
    )


def _score_model(
    model: LoadedModel, report_ids: Sequence[str], vectors_by_extra: Mapping[str, Mapping[str, ReportVector]]
) -> _ModelScores:
    extra = _served_extra(model.feature_set)
    if extra is None:
        return _ModelScores(
            model=model, by_report={}, skip_reason=f"feature set {model.feature_set.name} is not served yet"
        )
    rows = pd.DataFrame(index=pd.Index(list(report_ids), name="report_id"))
    extras = {extra: _extras_frame(report_ids, vectors_by_extra[extra])}
    # `as_of=None`: serving scores the latest vector, where training reads the one of its moment.
    buildable = model.feature_set.buildable(rows, extras, as_of=None).to_numpy()
    if not buildable.any():
        return _ModelScores(model=model, by_report={}, skip_reason=None)
    matrix = model.feature_set.build_matrix(rows, extras, as_of=None).loc[buildable]
    probabilities = model.predict(matrix.to_numpy())
    by_report = {
        report_id: {head: float(values[index]) for head, values in probabilities.items()}
        for index, report_id in enumerate(matrix.index)
    }
    return _ModelScores(model=model, by_report=by_report, skip_reason=None)


def _copied_metadata(metadata: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in metadata.items() if key not in _METADATA_FIELDS_NOT_COPIED}


def _result(model_scores: _ModelScores, report_id: str) -> RankingModelResult:
    model = model_scores.model
    entry = model.entry
    scores = model_scores.by_report.get(report_id)
    skip_reason = model_scores.skip_reason or (NO_VECTOR if scores is None else None)
    return RankingModelResult(
        model_name=entry.model_name,
        model_version=entry.model_version,
        model_kind=entry.model_kind,
        roles=list(entry.roles),
        feature_schema_version=model.feature_set.schema_version,
        status="skipped" if skip_reason else "scored",
        skip_reason=skip_reason,
        scores=dict(scores or {}),
        metadata=_copied_metadata(model.metadata),
    )


def _unloaded_result(entry: ServingManifestEntry, reason: str) -> RankingModelResult:
    return RankingModelResult(
        model_name=entry.model_name,
        model_version=entry.model_version,
        model_kind=entry.model_kind,
        roles=list(entry.roles),
        feature_schema_version=UNKNOWN_FEATURE_SCHEMA_VERSION,
        status="skipped",
        skip_reason=reason,
    )


def score_reports(
    team_id: int,
    report_ids: Sequence[str],
    *,
    persist: bool,
    now: datetime,
    serving: ServingSet | None = None,
    capture: ScopedCapture | None = None,
) -> list[ReportScoringOutcome]:
    """One outcome per distinct report id, in the order given.

    A report with no current vector for the served model gets no score and `reason="no_vector"`,
    so the caller can try it again later. A challenger with no vector is a skipped result inside
    the score. `persist=False` returns the scores and writes nothing.

    A caller that scores many teams passes the `serving` set it loaded and one `capture`, so each
    team does not read the manifest from object storage again or flush its own events.
    """
    if serving is None:
        serving = load_serving_set()
    if serving is None:
        logger.info("inbox_ranking_scoring_skipped", team_id=team_id, reason="no serving manifest is published")
        return []
    ids = list(dict.fromkeys(str(report_id) for report_id in report_ids))
    if not ids:
        return []
    served = serving.served
    served_extra = _served_model_extra(served)

    models = [served, *serving.others]
    needed_extras = {extra for model in models if (extra := _served_extra(model.feature_set)) is not None}
    vectors_by_extra = {
        extra: latest_report_vectors(team_id, ids, rendering=RENDERING_BY_EXTRA[extra]) for extra in needed_extras
    }
    scored_models = {model.entry.key: _score_model(model, ids, vectors_by_extra) for model in models}
    served_key = serving.manifest.served.key
    served_vectors = vectors_by_extra[served_extra]

    outcomes: list[ReportScoringOutcome] = []
    for report_id in ids:
        if report_id not in scored_models[served_key].by_report:
            outcomes.append(ReportScoringOutcome(report_id=report_id, score=None, reason=NO_VECTOR))
            continue
        results: dict[str, RankingModelResult] = {}
        for entry in serving.manifest.models:
            if entry.key in scored_models:
                results[entry.key] = _result(scored_models[entry.key], report_id)
            else:
                results[entry.key] = _unloaded_result(entry, serving.skipped[entry.key])
        score = RankingScore(
            scored_at=now,
            embedding_inserted_at=served_vectors[report_id].inserted_at,
            manifest_version=serving.manifest.manifest_version,
            served_key=served_key,
            results=results,
        )
        outcomes.append(ReportScoringOutcome(report_id=report_id, score=score, reason=None))

    if persist:
        persist_scores(
            team_id, [(outcome.report_id, outcome.score) for outcome in outcomes if outcome.score], capture=capture
        )
    return outcomes
