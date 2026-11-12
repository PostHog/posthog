"""Scores inbox reports with every model the serving manifest names.

One pass loads the serving set, reads each report's current vector once per rendering the models
need, builds each model's matrix through its own `FeatureSet.build_matrix`, and produces one
validated `RankingScore` per report. `build_matrix` is the code the training dag fits and grades
with, so a served score is the value the dag would produce for the same model and vector.

Nothing is written until every report of the call is scored, so a failure part of the way through
a call writes nothing.

A model that reads its team's project vectors gets the team's row of the day the manifest names,
repeated for each report, through the same `project_inputs` the training dag builds them with. Each
model gets its own kinds in its own order. A model that reads a kind the day has no rows for is
skipped, so it never scores on all-zero vectors.

A model whose set declares the `priority` state column gets each report's latest priority judgment,
read once per call and only when a model needs it. The sweep rescores a report when its vector
changes, not when its priority, the manifest or the served model changes, so an edited priority
keeps the old score until the next vector. The summary workflow writes the first priority judgment
before the rewrite that re-embeds the report, so a newborn's score normally sees that judgment.

A model whose set reads the `report_sources` side input gets the source products of each report's
live signals, read once per call and only when a model needs it. A failed read skips those models
with `no_report_sources`, so they never score on all-zero source columns. Like the priority, the
sources are read when the report is scored, and a signal that joins the report later does not
rescore it.

A model whose set declares a report-fact state column (`FACT_STATE_COLUMNS`) gets the facts of each
report (`report_facts.py`), read once per call before scoring and only when a model needs them. The
dataset dag builds the same columns through the same `report_row_facts` and `judgment_facts`, and the
set's `build_matrix` buckets them, so training and serving share every step after the read. The
creation time is not a fact, so `report_created_at` comes from the report row. A failed facts read
skips those models with `no_report_facts`.

A call that persists also records the facts of each report it scores, so training can later read the
values the sweep saw. When a model of the call read the facts, the events come from that same read.
Otherwise the call reads them once after scoring, for the scored reports only. A failed facts read
costs those models and the facts events: the other scores still persist.
"""

from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

from django.conf import settings

import numpy as np
import pandas as pd
import structlog

from posthog.dataclasses import frozen
from posthog.ph_client import ScopedCapture

from products.signals.backend.artefact_schemas import RankingModelResult, RankingScore
from products.signals.backend.models import SignalReport
from products.signals.backend.ranking.features import (
    ACTIONABILITY_COLUMN,
    ALREADY_ADDRESSED_COLUMN,
    CONTENT_COLUMNS,
    EMBEDDING_COLUMN,
    EMBEDDING_INSERTED_AT_COLUMN,
    PRIORITY_COLUMN,
    REPORT_CREATED_AT_COLUMN,
    REPORT_EMBEDDINGS_EXTRA,
    REPORT_LIVE_SOURCES_COLUMNS,
    REPORT_SOURCES_EXTRA,
    SIGNAL_COUNT_COLUMN,
    SUMMARY_CHARS_COLUMN,
    TITLE_CHARS_COLUMN,
    Extras,
    FeatureSet,
    ProjectInputs,
    ReportEmbeddingsFeatureSet,
)
from products.signals.backend.ranking.model_contract import head_lifts
from products.signals.backend.ranking.model_store import (
    LoadedModel,
    ProjectVectors,
    ServingSet,
    load_project_vectors,
    load_serving_set,
)
from products.signals.backend.ranking.report_facts import ReportFacts, read_report_facts
from products.signals.backend.ranking.serving_manifest import ServingManifestEntry
from products.signals.backend.ranking.sinks import persist_scores
from products.signals.backend.report_embedding_reader import ReportVector, latest_report_vectors
from products.signals.backend.report_embeddings import EMBEDDING_RENDERING_TITLE_SUMMARY
from products.signals.backend.report_priority import latest_report_priorities
from products.signals.backend.report_sources_reader import live_report_sources

logger = structlog.get_logger(__name__)

NO_VECTOR = "no_vector"
NO_PROJECT_VECTORS = "no_project_vectors"
PROJECT_VECTOR_KINDS_MISSING = "project_vector_kinds_missing"
NO_REPORT_SOURCES = "no_report_sources"
NO_REPORT_FACTS = "no_report_facts"

# The rendering each embedding side input is the vector of. The dataset dag snapshots the same
# renderings under the same keys, so a model reads the text it was fit on.
RENDERING_BY_EXTRA: Mapping[str, str] = {
    REPORT_EMBEDDINGS_EXTRA: EMBEDDING_RENDERING_TITLE_SUMMARY,
}
# The side inputs a set may read after its report vector, which the scorer reads at scoring time.
SERVED_SIDE_INPUTS = frozenset({REPORT_SOURCES_EXTRA})
# The report-state columns the scorer fills from `ReportFacts`. Each one is the `ReportFacts` field of
# the same name, so a fact read another way moves both sides at once.
FACT_STATE_COLUMNS = (
    TITLE_CHARS_COLUMN,
    SUMMARY_CHARS_COLUMN,
    ACTIONABILITY_COLUMN,
    ALREADY_ADDRESSED_COLUMN,
    SIGNAL_COUNT_COLUMN,
    *CONTENT_COLUMNS,
)

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
    """The report-vector side input a set is served from, or None when this build does not serve the
    set yet. A set's other side inputs must each be one of `SERVED_SIDE_INPUTS`."""
    if not isinstance(feature_set, ReportEmbeddingsFeatureSet):
        return None
    extra, *others = feature_set.extras_keys
    if extra not in RENDERING_BY_EXTRA or not set(others) <= SERVED_SIDE_INPUTS:
        return None
    return extra


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


def pass_project_vectors(serving: ServingSet, team_ids: Sequence[int]) -> ProjectVectors | None:
    """The project vectors of `team_ids`, read once for a pass, or None when no model reads them.

    A failed read is no vectors at all, so it costs only the models that read them.
    """
    if not any(model.reads_project_vectors for model in (serving.served, *serving.others)):
        return None
    try:
        return load_project_vectors(serving.manifest, team_ids)
    except Exception:
        logger.exception(
            "inbox_ranking_project_vectors_unreadable", project_vectors_key=serving.manifest.project_vectors
        )
        return ProjectVectors(available=False, by_team={})


def _state_rows(
    team_id: int, report_ids: Sequence[str], columns: set[str], facts: Mapping[str, ReportFacts] | None
) -> pd.DataFrame:
    """The report-state columns of `columns` that the scorer can read, indexed by report id. A
    column is read only when a model of the pass declares it. The fact columns come from `facts`, and
    are left out when it is None."""
    rows = pd.DataFrame(index=pd.Index(list(report_ids), name="report_id"))
    if PRIORITY_COLUMN in columns:
        priorities = latest_report_priorities(team_id, report_ids)
        rows[PRIORITY_COLUMN] = [priorities.get(report_id) for report_id in report_ids]
    if facts is not None:
        for column in FACT_STATE_COLUMNS:
            if column in columns:
                rows[column] = pd.Series(
                    [getattr(facts[report_id], column) if report_id in facts else None for report_id in report_ids],
                    index=rows.index,
                    dtype=object,
                )
    if REPORT_CREATED_AT_COLUMN in columns:
        created_ats = {
            str(report_id): created_at
            for report_id, created_at in SignalReport.objects.filter(team_id=team_id, id__in=report_ids).values_list(
                "id", "created_at"
            )
        }
        rows[REPORT_CREATED_AT_COLUMN] = pd.to_datetime(
            [created_ats.get(report_id) for report_id in report_ids], utc=True
        )
    return rows


def _reads_sources(model: LoadedModel) -> bool:
    return REPORT_SOURCES_EXTRA in model.feature_set.extras_keys


def _sources_frame(team_id: int, report_ids: Sequence[str]) -> pd.DataFrame | None:
    """The live signals of `report_ids` as the `report_sources` side input, or None when the read
    fails, so it costs only the models that read it."""
    try:
        rows = live_report_sources(team_id, report_ids)
    except Exception:
        logger.exception("inbox_ranking_report_sources_unreadable", team_id=team_id)
        return None
    return pd.DataFrame(rows, columns=list(REPORT_LIVE_SOURCES_COLUMNS), dtype=object)


def _reads_facts(model: LoadedModel) -> bool:
    return any(column in FACT_STATE_COLUMNS for column in model.feature_set.state_columns)


def _report_facts(team_id: int, report_ids: Sequence[str]) -> Mapping[str, ReportFacts] | None:
    """The facts of `report_ids`, or None when the read fails, so it costs only the models that read
    them and the facts events."""
    if not report_ids:
        return {}
    try:
        return read_report_facts(team_id, report_ids)
    except Exception:
        logger.warning("inbox_ranking_report_facts_unreadable", team_id=team_id, reports=len(report_ids), exc_info=True)
        return None


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
    model: LoadedModel,
    report_ids: Sequence[str],
    rows: pd.DataFrame,
    vectors_by_extra: Mapping[str, Mapping[str, ReportVector]],
    team_id: int,
    project_vectors: ProjectVectors | None,
    sources: pd.DataFrame | None = None,
    facts_read: bool = False,
) -> _ModelScores:
    """`rows` holds the report-state columns of the pass, one row per id of `report_ids`. `sources`
    holds the live signals of the call's reports, None when no model reads them or the read failed.
    `facts_read` is True when `rows` holds the fact columns."""
    extra = _served_extra(model.feature_set)
    if extra is None:
        return _ModelScores(
            model=model, by_report={}, skip_reason=f"feature set {model.feature_set.name} is not served yet"
        )
    if _reads_facts(model) and not facts_read:
        return _ModelScores(model=model, by_report={}, skip_reason=NO_REPORT_FACTS)
    unread = [column for column in model.feature_set.state_columns if column not in rows]
    if unread:
        return _ModelScores(
            model=model,
            by_report={},
            skip_reason=f"state columns {unread} of {model.feature_set.name} are not served yet",
        )
    if _reads_sources(model) and sources is None:
        return _ModelScores(model=model, by_report={}, skip_reason=NO_REPORT_SOURCES)
    team_project = None
    if model.reads_project_vectors:
        if project_vectors is None or not project_vectors.available:
            return _ModelScores(model=model, by_report={}, skip_reason=NO_PROJECT_VECTORS)
        if project_vectors.missing_kinds(model.project_vector_kinds):
            return _ModelScores(model=model, by_report={}, skip_reason=PROJECT_VECTOR_KINDS_MISSING)
        team_project = project_vectors.for_team(team_id, model.project_vector_kinds)
    extras: Extras = {extra: _extras_frame(report_ids, vectors_by_extra[extra])}
    if sources is not None and _reads_sources(model):
        extras = {**extras, REPORT_SOURCES_EXTRA: sources}
    # `as_of=None`: serving scores the latest vector, where training reads the one of its moment.
    buildable = model.feature_set.buildable(rows, extras, as_of=None).to_numpy()
    if not buildable.any():
        return _ModelScores(model=model, by_report={}, skip_reason=None)
    matrix = model.feature_set.build_matrix(rows, extras, as_of=None).loc[buildable]
    project = None
    if team_project is not None:
        project = ProjectInputs(
            vectors=np.repeat(team_project.vectors, len(matrix), axis=0),
            has_history=np.repeat(team_project.has_history, len(matrix), axis=0),
        )
    probabilities = model.predict(matrix.to_numpy(), project)
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
        lifts=head_lifts(scores or {}, model.metadata),
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
    project_vectors: ProjectVectors | None = None,
) -> list[ReportScoringOutcome]:
    """One outcome per distinct report id, in the order given.

    A report with no current vector for the served model gets no score and `reason="no_vector"`,
    so the caller can try it again later. A challenger with no vector is a skipped result inside
    the score. `persist=False` returns the scores and writes nothing.

    A caller that scores many teams passes the `serving` set it loaded, one `capture`, and the
    `project_vectors` of every team it scores, so each team does not read the manifest or the
    project vectors from object storage again or flush its own events. A served model that reads
    project vectors when the pass has none, reads a kind the pass has no rows for, or reads report
    sources or facts the call could not read, raises, because no report could get a served score.
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
    if project_vectors is None:
        project_vectors = pass_project_vectors(serving, [team_id])
    if served.reads_project_vectors:
        if project_vectors is None or not project_vectors.available:
            raise ScoringError(f"served model {served.entry.key} reads project vectors and the pass has none")
        missing = project_vectors.missing_kinds(served.project_vector_kinds)
        if missing:
            raise ScoringError(
                f"served model {served.entry.key} reads project vector kinds {missing} the pass has no rows for"
            )
    needed_extras = {extra for model in models if (extra := _served_extra(model.feature_set)) is not None}
    vectors_by_extra = {
        extra: latest_report_vectors(team_id, ids, rendering=RENDERING_BY_EXTRA[extra]) for extra in needed_extras
    }
    reads_facts = any(_reads_facts(model) for model in models)
    facts = _report_facts(team_id, ids) if reads_facts else None
    if facts is None and _reads_facts(served):
        raise ScoringError(f"served model {served.entry.key} reads report facts and the pass has none")
    rows = _state_rows(team_id, ids, {column for model in models for column in model.feature_set.state_columns}, facts)
    sources = _sources_frame(team_id, ids) if any(_reads_sources(model) for model in models) else None
    if sources is None and _reads_sources(served):
        raise ScoringError(f"served model {served.entry.key} reads report sources and the pass has none")
    scored_models = {
        model.entry.key: _score_model(
            model, ids, rows, vectors_by_extra, team_id, project_vectors, sources, facts_read=facts is not None
        )
        for model in models
    }
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
        scores = [(outcome.report_id, outcome.score) for outcome in outcomes if outcome.score]
        recorded: Mapping[str, ReportFacts] | None = {}
        if settings.INBOX_RANKING_RECORD_REPORT_FACTS:
            # `persist_scores` records facts only for the scored reports, so a pass that read them for
            # every report records the same events as one that reads them after scoring.
            recorded = facts if reads_facts else _report_facts(team_id, [report_id for report_id, _ in scores])
        persist_scores(
            team_id,
            scores,
            capture=capture,
            served_override=serving.served_override,
            facts=recorded or {},
        )
    return outcomes
