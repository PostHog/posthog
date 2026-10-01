from __future__ import annotations

import io
import sys
import json
import time
import uuid
import random
import asyncio
import datetime as dt
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

import boto3
import requests
from botocore.client import Config as BotoConfig
from google.genai import types as genai_types
from pydantic import ValidationError

from products.posthog_ai.eval_harness.harness.context import EvalContext
from products.posthog_ai.eval_harness.scorers.contract import Score, Scorer
from products.replay_vision.backend.temporal.activities.call_scanner_provider import apply_known_freeform_tags
from products.replay_vision.backend.temporal.scanners import ClassifierScanner
from products.replay_vision.backend.temporal.scanners.base import SignalFinding
from products.replay_vision.backend.temporal.scanners.monitor import MonitorOutput
from products.replay_vision.backend.temporal.types import (
    ScannerCallOutput,
    ScannerLlmInputs,
    ScannerSnapshot,
    VerificationRecord,
)
from products.replay_vision.evals import (
    collect as collect_cli,
    collector,
    dataset as dataset_module,
    eval_scanner_quality,
    pin_lifecycle,
)
from products.replay_vision.evals.collector import (
    _VideoAsset,
    asset_is_recorded_video,
    build_llm_inputs,
    order_candidates,
)
from products.replay_vision.evals.dataset import (
    DATASET_BUCKET_ENV_VAR,
    DATASET_ENV_VAR,
    DATASET_KEY_ENV_VAR,
    GoldenCase,
    GoldenDataset,
    download_pinned_dataset,
    ensure_dataset_consent,
    load_dataset,
    parse_utc,
    save_dataset,
    upload_pinned_dataset,
)
from products.replay_vision.evals.eval_scanner_quality import build_case
from products.replay_vision.evals.pin_lifecycle import DATASET_ENDPOINT_ENV_VAR
from products.replay_vision.evals.scorers import (
    LabeledOutcome,
    OutputStability,
    ScanCompleted,
    ScoreAlignment,
    SummaryAlignment,
)


def _eval(scorer: Scorer, output: dict[str, Any] | None, expected: dict[str, Any] | None) -> Score:
    # eval_async is the entrypoint the harness dispatches through.
    score = asyncio.run(scorer.eval_async(output, expected))
    assert isinstance(score, Score)
    return score


def _monitor_output(verdict: str) -> dict[str, Any]:
    return {"model_output": {"verdict": verdict, "reasoning": "r", "confidence": 0.9}}


def _golden(
    scanner_type: str,
    label_is_correct: bool | None,
    recorded_output: dict[str, Any],
    case_id: str = "0199aaaa-0000-7000-8000-000000000001",
    scale: dict[str, Any] | None = None,
) -> GoldenCase:
    scanner_config: dict[str, Any] = {"prompt": "watch for rage clicks"}
    if scanner_type == "classifier":
        scanner_config["tags"] = ["a", "b"]
    if scanner_type == "scorer":
        scanner_config["scale"] = {"min": 1, "max": 5} if scale is None else scale
    return GoldenCase(
        case_id=case_id,
        scanner_id="s1",
        scanner_name="Test scanner",
        scanner_type=scanner_type,
        session_id="sess-1",
        team_id=2,
        team_name="Team",
        snapshot=ScannerSnapshot(
            name="Test scanner",
            scanner_type=scanner_type,
            scanner_version=1,
            model="gemini-3.6-flash",
            provider="google",
            emits_signals=False,
            scanner_config=scanner_config,
        ),
        recorded_output=recorded_output,
        label_is_correct=label_is_correct,
        collected_at="2026-07-30T00:00:00+00:00",
    )


@pytest.mark.parametrize(
    "is_correct,fresh_verdict,expected_score,expected_outcome",
    [
        (True, "yes", 1.0, "kept"),
        (True, "no", 0.0, "regressed"),
        (False, "no", 1.0, "fixed"),
        (False, "yes", 0.0, "still_wrong"),
    ],
)
def test_labeled_outcome_scores_thumbs_semantics(
    is_correct: bool, fresh_verdict: str, expected_score: float, expected_outcome: str
) -> None:
    expected = {"labeled_outcome": {"is_correct": is_correct, "recorded_primary": "Verdict: yes"}}
    score = _eval(LabeledOutcome(), _monitor_output(fresh_verdict), expected)
    assert score.score == expected_score
    assert score.metadata["outcome"] == expected_outcome


@pytest.mark.parametrize(
    "scorer",
    [LabeledOutcome(), OutputStability(), ScoreAlignment()],
    ids=lambda s: s._name(),
)
def test_inapplicable_cases_skip_instead_of_failing(scorer: Any) -> None:
    # None means "skipped" in the aggregate; returning 0.0 here would silently drag every
    # experiment's mean down for cases the scorer was never meant to grade.
    score = _eval(scorer, _monitor_output("yes"), {})
    assert score.score is None


def test_labeled_outcome_fails_when_scan_produced_nothing() -> None:
    expected = {"labeled_outcome": {"is_correct": True, "recorded_primary": "Verdict: yes"}}
    score = _eval(LabeledOutcome(), {"model_output": None, "error": "boom"}, expected)
    assert score.score == 0.0


@pytest.mark.parametrize(
    "fresh,expected_score",
    [
        (3.0, 1.0),
        (4.0, 0.75),
        (1.0, 0.5),
        (None, 0.0),
    ],
)
def test_score_alignment_normalizes_distance_by_scale(fresh: float | None, expected_score: float) -> None:
    expected = {"score_alignment": {"recorded_score": 3.0, "scale_min": 1.0, "scale_max": 5.0}}
    output = {"model_output": {"score": fresh} if fresh is not None else None}
    score = _eval(ScoreAlignment(), output, expected)
    assert score.score == pytest.approx(expected_score)


def test_score_alignment_skips_zero_width_scale() -> None:
    # min == max used to divide by zero and kill the case; a degenerate scale is inapplicable, not failing.
    expected = {"score_alignment": {"recorded_score": 3.0, "scale_min": 3.0, "scale_max": 3.0}}
    score = _eval(ScoreAlignment(), {"model_output": {"score": 3.0}}, expected)
    assert score.score is None
    assert score.metadata["reason"] == "zero-width scale"


@pytest.mark.parametrize(
    "scale,expected_bounds",
    [
        ({}, (0.0, 1.0)),
        ({"min": 1, "max": 5}, (1, 5)),
        ({"min": 1}, None),
        ({"max": 5}, None),
    ],
)
def test_build_case_only_defaults_scale_bounds_as_a_pair(
    scale: dict[str, Any], expected_bounds: tuple[float, float] | None
) -> None:
    case = build_case(_golden("scorer", None, {"score": 3.0}, scale=scale))
    spec = case.expected.get("score_alignment")
    if expected_bounds is None:
        assert spec is None
    else:
        assert spec is not None
        assert (spec["scale_min"], spec["scale_max"]) == expected_bounds


def test_output_stability_compares_primary_outcomes() -> None:
    expected = {"output_stability": {"recorded_primary": "Verdict: yes"}}
    assert _eval(OutputStability(), _monitor_output("yes"), expected).score == 1.0
    assert _eval(OutputStability(), _monitor_output("no"), expected).score == 0.0


def test_scan_completed_fails_on_schema_breakage() -> None:
    assert _eval(ScanCompleted(), _monitor_output("yes"), {}).score == 1.0
    failed = _eval(ScanCompleted(), {"model_output": None, "error": "required step rejected"}, {})
    assert failed.score == 0.0
    assert "rejected" in failed.metadata["reason"]


@pytest.mark.parametrize(
    "signals",
    [
        [],
        [
            {
                "problem_type": "design_flaw",
                "headline": "Navigation panel covers the book list",
                "start_time": 7,
                "end_time": 11,
                "url": "https://example.com/library",
                "description": "The navigation panel overlaps the book list.",
                "confidence": 0.8,
            },
            {
                "problem_type": "crash",
                "headline": "Reader errors out after a book opens",
                "start_time": 23,
                "end_time": 29,
                "url": "https://example.com/reader",
                "description": "The reader shows an error screen after the book opens.",
                "confidence": 0.95,
            },
        ],
    ],
    ids=["empty", "multiple_findings"],
)
@pytest.mark.parametrize(
    "verification",
    [
        None,
        VerificationRecord(mode="enforce", draws=["yes", "yes"], resolved_verdict="yes", served_verdict="yes"),
    ],
    ids=["unverified", "verified"],
)
def test_scan_task_retains_structured_signals(
    signals: list[dict[str, str | int | float]], verification: VerificationRecord | None, tmp_path: Path
) -> None:
    golden = _golden("monitor", True, {"verdict": "yes"})
    golden = golden.model_copy(update={"snapshot": golden.snapshot.model_copy(update={"emits_signals": True})})
    scan_output = ScannerCallOutput(
        model_output=MonitorOutput(verdict="yes", reasoning="The book list is covered.", confidence=0.9),
        signals=[SignalFinding.model_validate(signal) for signal in signals],
        verification=verification,
    )
    with (
        patch.object(GoldenCase, "load_inputs", return_value=MagicMock(spec=ScannerLlmInputs)),
        patch.object(eval_scanner_quality, "gemini_api_key", return_value="fake-eval-api-key"),
        patch.object(eval_scanner_quality, "RawGenAIClient"),
        patch.object(
            eval_scanner_quality,
            "_upload_video",
            return_value=genai_types.File(
                name="files/eval-video", uri="https://example.com/video.mp4", mime_type="video/mp4"
            ),
        ),
        patch.object(eval_scanner_quality, "_delete_file_quiet"),
        patch.object(eval_scanner_quality, "run_scan", new=AsyncMock(return_value=scan_output)),
    ):
        output = asyncio.run(
            eval_scanner_quality._scan_task(
                tmp_path, {golden.case_id: golden}, build_case(golden), MagicMock(spec=EvalContext)
            )
        )

    assert json.loads(json.dumps(output)) == {
        "exit_code": 0,
        "model_output": scan_output.model_output.model_dump(mode="json"),
        "error": None,
        "scanner_type": "monitor",
        "signals_count": len(signals),
        "signals": signals,
        "verification": verification.model_dump(mode="json") if verification else None,
        "primary": "Verdict: yes",
        "last_message": "Verdict: yes",
    }


def test_summary_alignment_prepare_gates_on_reference() -> None:
    # _prepare directly: going through eval_async would call the LLM judge.
    judge = SummaryAlignment()
    skipped = judge._prepare(_monitor_output("yes"), {})
    assert isinstance(skipped, Score)
    assert skipped.score is None
    spec = {"summary_alignment": {"reference": {"title": "t", "summary": "s"}}}
    no_output = judge._prepare({"model_output": None}, spec)
    assert isinstance(no_output, Score)
    assert no_output.score == 0.0
    prepared = judge._prepare({"model_output": {"title": "t2", "summary": "s2"}}, spec)
    assert isinstance(prepared, dict)
    assert "t2" in prepared["output"]
    assert "t" in prepared["expected"]


@pytest.mark.parametrize(
    "scanner_type,label_is_correct,recorded_output,expected_key",
    [
        ("monitor", True, {"verdict": "yes"}, "labeled_outcome"),
        ("monitor", None, {"verdict": "yes"}, "output_stability"),
        ("classifier", False, {"tags": ["a"]}, "labeled_outcome"),
        ("scorer", None, {"score": 3.0}, "score_alignment"),
        ("scorer", True, {"score": 3.0}, "score_alignment"),
        ("summarizer", None, {"title": "t", "summary": "s"}, "summary_alignment"),
    ],
)
def test_build_case_routes_to_the_right_scorer(
    scanner_type: str, label_is_correct: bool | None, recorded_output: dict[str, Any], expected_key: str
) -> None:
    case = build_case(_golden(scanner_type, label_is_correct, recorded_output))
    assert list(case.expected.keys()) == [expected_key]


@pytest.mark.parametrize(
    "scanner_type,recorded_output",
    [
        ("scorer", {"score": 3.0}),
        ("summarizer", {"title": "t", "summary": "s"}),
    ],
)
def test_build_case_never_trusts_a_thumbs_downed_reference(scanner_type: str, recorded_output: dict[str, Any]) -> None:
    case = build_case(_golden(scanner_type, False, recorded_output))
    assert case.expected == {}


def test_case_names_do_not_collide_on_shared_uuid_prefix() -> None:
    # UUIDv7 ids minted in the same minute share their leading characters; a truncated name
    # collapsed such cases into one dataset entry, scoring one against another session's video.
    goldens = [
        _golden("monitor", True, {"verdict": "yes"}, case_id="0199aaaa-0000-7000-8000-000000000001"),
        _golden("monitor", True, {"verdict": "yes"}, case_id="0199aaaa-0000-7000-8000-000000000002"),
    ]
    cases = [build_case(golden) for golden in goldens]
    assert cases[0].name != cases[1].name
    golden_by_case_id = {case.metadata["case_id"]: golden for case, golden in zip(cases, goldens)}
    assert len(golden_by_case_id) == len(goldens)


def test_order_candidates_puts_labeled_first_per_type() -> None:
    def candidate(scanner_type: str, obs_id: str, labeled: bool) -> dict[str, Any]:
        observation: dict[str, Any] = {"id": obs_id, "label": {"is_correct": True} if labeled else None}
        return {"observation": observation, "scanner": {}, "scanner_type": scanner_type}

    candidates = [
        candidate("monitor", "u1", False),
        candidate("monitor", "l1", True),
        candidate("monitor", "u2", False),
        candidate("scorer", "u3", False),
        candidate("monitor", "l2", True),
    ]
    ordered = order_candidates(candidates, random.Random(42))
    monitor_ids = [c["observation"]["id"] for c in ordered["monitor"]]
    assert monitor_ids[:2] == ["l1", "l2"]
    assert sorted(monitor_ids[2:]) == ["u1", "u2"]
    assert [c["observation"]["id"] for c in ordered["scorer"]] == ["u3"]
    assert ordered == order_candidates(candidates, random.Random(42))


def test_parse_utc_rejects_naive_timestamps() -> None:
    with pytest.raises(ValueError, match="no timezone"):
        parse_utc("2026-08-01T12:00:00")
    assert parse_utc("2026-08-01T12:00:00+12:00") == dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=dt.UTC)


# Organization ids are UUID strings in the API.
_ORG_ID = "0199bbbb-0000-7000-8000-000000000001"


@pytest.mark.parametrize("approved", [True, False])
def test_ensure_dataset_consent_reads_the_source_org(approved: bool) -> None:
    dataset = GoldenDataset(
        created_at=dt.datetime.now(dt.UTC).isoformat(),
        host="https://us.posthog.com",
        project_id=2,
        organization_id=_ORG_ID,
        cases=[],
    )
    response = MagicMock()
    response.json.return_value = {"is_ai_data_processing_approved": approved}
    with patch("requests.get", return_value=response):
        if approved:
            ensure_dataset_consent(dataset, "test-key")
        else:
            with pytest.raises(RuntimeError, match="withdrawn AI data-processing consent"):
                ensure_dataset_consent(dataset, "test-key")


@pytest.mark.parametrize(
    "host,api_key,error",
    [
        ("https://us.posthog.com", "", "POSTHOG_API_KEY"),
        ("https://attacker.example.com", "test-key", "refusing to send the API key"),
        ("http://us.posthog.com", "test-key", "refusing to send the API key"),
    ],
)
def test_ensure_dataset_consent_refuses_without_a_key_or_a_trusted_host(host: str, api_key: str, error: str) -> None:
    dataset = GoldenDataset(
        created_at=dt.datetime.now(dt.UTC).isoformat(),
        host=host,
        project_id=2,
        organization_id=_ORG_ID,
        cases=[],
    )
    with patch("requests.get") as get, pytest.raises(RuntimeError, match=error):
        ensure_dataset_consent(dataset, api_key)
    get.assert_not_called()


def test_ensure_dataset_consent_resolves_the_org_on_legacy_manifests() -> None:
    dataset = GoldenDataset(
        created_at=dt.datetime.now(dt.UTC).isoformat(),
        host="https://us.posthog.com",
        project_id=2,
        organization_id=None,
        cases=[],
    )
    environment = MagicMock()
    environment.json.return_value = {"organization": _ORG_ID}
    organization = MagicMock()
    organization.json.return_value = {"is_ai_data_processing_approved": True}
    with patch("requests.get", side_effect=[environment, organization]) as get:
        ensure_dataset_consent(dataset, "test-key")
    assert get.call_count == 2
    assert get.call_args_list[0].args[0].endswith("/api/environments/2/")
    assert get.call_args_list[1].args[0].endswith(f"/api/organizations/{_ORG_ID}/")


def _golden_case_on_disk(case_id: str, root: Path, *, write_files: bool = True) -> GoldenCase:
    case = _golden("monitor", None, _monitor_output("no"), case_id=case_id).model_copy(
        update={"session_id": f"sess-{case_id}"}
    )
    if write_files:
        case.case_dir(root).mkdir(parents=True)
        case.video_path(root).write_bytes(f"video-{case_id}".encode())
        case.inputs_path(root).write_text("{}")
    return case


_PIN_KEY = "replay-vision/golden/v1/manifest.json"


class _FakePinStore:
    """In-memory stand-in for the pin's S3 client that logs reads and writes in order."""

    class exceptions:
        class NoSuchKey(Exception):
            pass

    def __init__(self, objects: dict[str, bytes] | None = None) -> None:
        self.objects = dict(objects or {})
        self.reads: list[str] = []
        self.writes: list[str] = []

    def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
        self.reads.append(Key)
        if Key not in self.objects:
            raise self.exceptions.NoSuchKey()
        return {"Body": io.BytesIO(self.objects[Key])}

    def put_object(self, *, Bucket: str, Key: str, Body: bytes) -> None:
        self.objects[Key] = Body
        self.writes.append(Key)

    def upload_file(self, Filename: str, Bucket: str, Key: str) -> None:
        self.objects[Key] = Path(Filename).read_bytes()
        self.writes.append(Key)

    def list_objects_v2(self, *, Bucket: str, Prefix: str) -> dict[str, Any]:
        return {"Contents": [{"Key": key} for key in sorted(self.objects) if key.startswith(Prefix)]}

    def delete_object(self, *, Bucket: str, Key: str) -> None:
        self.objects.pop(Key, None)


@pytest.fixture
def pin_store() -> Iterator[_FakePinStore]:
    store = _FakePinStore()
    with patch.object(dataset_module, "pin_client", return_value=store):
        yield store


class _FakePostHogApi:
    """Stands in for `requests.get` against US Cloud: recordings, the organization, and the environment."""

    def __init__(self) -> None:
        self.deleted: set[str] = set()
        self.expired: set[str] = set()
        self.failing: set[str] = set()
        self.approved = True
        self.urls: list[str] = []

    def __call__(self, url: str, **_: Any) -> MagicMock:
        self.urls.append(url)
        response = MagicMock(status_code=200)
        if "/session_recordings/" in url:
            session_id = url.rstrip("/").rsplit("/", 1)[-1]
            if session_id in self.failing:
                response.status_code = 503
                response.raise_for_status.side_effect = requests.HTTPError("503", response=response)
            elif session_id in self.deleted:
                response.status_code = 404
            else:
                expiry = dt.datetime.now(dt.UTC) + dt.timedelta(days=-1 if session_id in self.expired else 30)
                response.json.return_value = {"expiry_time": expiry.isoformat()}
        elif "/organizations/" in url:
            response.json.return_value = {"is_ai_data_processing_approved": self.approved}
        else:
            response.json.return_value = {"organization": _ORG_ID}
        return response

    def recording_checks(self) -> list[str]:
        return [url.rstrip("/").rsplit("/", 1)[-1] for url in self.urls if "/session_recordings/" in url]


@pytest.fixture
def posthog_api() -> Iterator[_FakePostHogApi]:
    api = _FakePostHogApi()
    with patch("requests.get", side_effect=api):
        yield api


def _pinned_dataset(*cases: GoldenCase) -> GoldenDataset:
    return GoldenDataset(
        created_at=dt.datetime.now(dt.UTC).isoformat(),
        host="https://us.posthog.com",
        project_id=2,
        organization_id=_ORG_ID,
        cases=list(cases),
    )


@pytest.mark.parametrize(
    "state,live",
    [("live", True), ("expired", False), ("deleted", False)],
)
def test_recording_is_live_follows_the_source_recording(posthog_api: _FakePostHogApi, state: str, live: bool) -> None:
    if state != "live":
        getattr(posthog_api, state).add("sess-1")
    assert (
        pin_lifecycle.recording_is_live(
            host="https://us.posthog.com",
            project_id=2,
            session_id="sess-1",
            api_key="test-key",
            now=dt.datetime.now(dt.UTC),
        )
        == live
    )


def test_recording_is_live_raises_when_the_api_cannot_say(posthog_api: _FakePostHogApi) -> None:
    posthog_api.failing.add("sess-1")
    with pytest.raises(requests.HTTPError):
        pin_lifecycle.recording_is_live(
            host="https://us.posthog.com",
            project_id=2,
            session_id="sess-1",
            api_key="test-key",
            now=dt.datetime.now(dt.UTC),
        )


def test_upload_pinned_dataset_writes_every_case_and_the_manifest_last(
    tmp_path: Path, pin_store: _FakePinStore
) -> None:
    dataset = _pinned_dataset(_golden_case_on_disk("c1", tmp_path), _golden_case_on_disk("c2", tmp_path))
    upload_pinned_dataset(tmp_path, dataset, bucket="test-bucket", key=_PIN_KEY)
    assert sorted(pin_store.writes[:-1]) == [
        "replay-vision/golden/v1/cases/c1/inputs.json",
        "replay-vision/golden/v1/cases/c1/video.mp4",
        "replay-vision/golden/v1/cases/c2/inputs.json",
        "replay-vision/golden/v1/cases/c2/video.mp4",
    ]
    # Manifest lands last, so a reader never sees a manifest naming absent case files.
    assert pin_store.writes[-1] == _PIN_KEY


@pytest.mark.parametrize("key_taken", [False, True])
def test_upload_pinned_dataset_refuses_without_writing(
    tmp_path: Path, pin_store: _FakePinStore, key_taken: bool
) -> None:
    if key_taken:
        pin_store.objects[_PIN_KEY] = b"{}"
        dataset = _pinned_dataset(_golden_case_on_disk("c1", tmp_path))
        error = "upload under a new key prefix"
    else:
        dataset = _pinned_dataset(_golden_case_on_disk("c1", tmp_path, write_files=False))
        error = "missing files"
    with pytest.raises(RuntimeError, match=error):
        upload_pinned_dataset(tmp_path, dataset, bucket="test-bucket", key=_PIN_KEY)
    assert pin_store.writes == []


def test_collect_records_the_org_and_reuses_only_live_cases_of_the_collected_team(
    tmp_path: Path, posthog_api: _FakePostHogApi
) -> None:
    same_team = _golden_case_on_disk("c1", tmp_path)
    other_team = _golden_case_on_disk("c2", tmp_path).model_copy(update={"team_id": 3})
    deleted_recording = _golden_case_on_disk("c3", tmp_path)
    posthog_api.deleted.add(deleted_recording.session_id)
    inputs = build_llm_inputs(_FakeApi(), 2, "sess-1")  # type: ignore[arg-type]
    assert inputs is not None
    for case in (same_team, other_team, deleted_recording):
        case.inputs_path(tmp_path).write_text(inputs.model_dump_json())
    save_dataset(tmp_path, _pinned_dataset(same_team, other_team, deleted_recording))
    api = MagicMock()
    api.get_json.side_effect = lambda path: (
        {"id": 2, "project_id": 2, "organization": _ORG_ID, "name": "Team"}
        if path == "/api/environments/2/"
        else {"is_ai_data_processing_approved": True}
    )

    with (
        patch.object(collector, "PostHogApi", return_value=api),
        patch.object(collector, "fetch_product_context_via_api", return_value=""),
        patch.object(collector, "EventDescriptionLookup"),
        patch.object(collector, "_fetch_candidates", return_value=[]),
        patch.object(collector, "lookup_video_assets", return_value={}),
    ):
        dataset = collector.collect(
            host="https://us.posthog.com", project_id=2, api_key="test-key", output=tmp_path, per_type=1
        )

    assert dataset.organization_id == _ORG_ID
    assert [case.case_id for case in dataset.cases] == ["c1"]
    assert load_dataset(tmp_path) == dataset


@pytest.mark.parametrize(
    "error", [requests.ReadTimeout("slow"), requests.HTTPError("500", response=MagicMock(status_code=500))]
)
def test_collect_skips_a_case_whose_request_fails(
    tmp_path: Path, posthog_api: _FakePostHogApi, error: Exception
) -> None:
    api = MagicMock()
    api.get_json.side_effect = lambda path: (
        {"id": 2, "project_id": 2, "organization": _ORG_ID, "name": "Team"}
        if path == "/api/environments/2/"
        else {"is_ai_data_processing_approved": True}
    )
    candidates = [{"scanner_type": "monitor", "observation": {"id": f"o{i}", "session_id": f"s{i}"}} for i in (1, 2)]
    kept = _golden_case_on_disk("c2", tmp_path)

    with (
        patch.object(collector, "PostHogApi", return_value=api),
        patch.object(collector, "fetch_product_context_via_api", return_value=""),
        patch.object(collector, "EventDescriptionLookup"),
        patch.object(collector, "_fetch_candidates", return_value=candidates),
        patch.object(collector, "order_candidates", return_value={"monitor": candidates}),
        patch.object(collector, "lookup_video_assets", return_value={"s1": MagicMock(), "s2": MagicMock()}),
        patch.object(collector, "asset_is_recorded_video", return_value=True),
        patch.object(collector, "_write_case", side_effect=[error, kept]),
    ):
        dataset = collector.collect(
            host="https://us.posthog.com", project_id=2, api_key="test-key", output=tmp_path, per_type=2
        )

    assert [case.case_id for case in dataset.cases] == ["c2"]


def test_download_pinned_dataset_replaces_existing_local_case_files(
    tmp_path: Path, pin_store: _FakePinStore, posthog_api: _FakePostHogApi
) -> None:
    dataset = _pinned_dataset(
        _golden_case_on_disk("c1", tmp_path), _golden_case_on_disk("c2", tmp_path, write_files=False)
    )
    pin_store.objects[_PIN_KEY] = dataset.model_dump_json().encode()
    for case_id in ("c1", "c2"):
        for name in ("video.mp4", "inputs.json"):
            pin_store.objects[f"replay-vision/golden/v1/cases/{case_id}/{name}"] = f"remote-{case_id}-{name}".encode()

    downloaded = download_pinned_dataset(tmp_path, api_key="test-key", bucket="test-bucket", key=_PIN_KEY)

    assert downloaded == dataset
    # c1's stale local bytes must not survive, or they are scored under the pinned manifest.
    for case in dataset.cases:
        assert case.video_path(tmp_path).read_bytes() == f"remote-{case.case_id}-video.mp4".encode()
        assert case.inputs_path(tmp_path).read_text() == f"remote-{case.case_id}-inputs.json"


@pytest.mark.parametrize("case_id", ["../escape", "/tmp/escape", "a/b", ""])
def test_golden_case_rejects_ids_that_leave_the_dataset_directory(case_id: str) -> None:
    with pytest.raises(ValidationError):
        _golden("monitor", None, _monitor_output("no"), case_id=case_id)


def test_download_pinned_dataset_skips_cases_whose_recording_is_gone(
    tmp_path: Path, pin_store: _FakePinStore, posthog_api: _FakePostHogApi
) -> None:
    live, deleted, expired = (_golden_case_on_disk(case_id, tmp_path / "source") for case_id in ("c1", "c2", "c3"))
    posthog_api.deleted.add(deleted.session_id)
    posthog_api.expired.add(expired.session_id)
    pin_store.objects[_PIN_KEY] = _pinned_dataset(live, deleted, expired).model_dump_json().encode()
    # The prune job already removed the dead cases' bytes, so only the live case is still stored.
    for name in ("video.mp4", "inputs.json"):
        pin_store.objects[f"replay-vision/golden/v1/cases/c1/{name}"] = b"{}"

    downloaded = download_pinned_dataset(tmp_path / "target", api_key="test-key", bucket="test-bucket", key=_PIN_KEY)

    assert [case.case_id for case in downloaded.cases] == ["c1"]
    assert load_dataset(tmp_path / "target") == downloaded
    assert not [key for key in pin_store.reads if "/c2/" in key or "/c3/" in key]


@pytest.mark.parametrize("missing", ["video.mp4", "inputs.json"])
def test_download_pinned_dataset_fails_when_a_case_file_is_absent_remote(
    tmp_path: Path, pin_store: _FakePinStore, posthog_api: _FakePostHogApi, missing: str
) -> None:
    dataset = _pinned_dataset(_golden_case_on_disk("c1", tmp_path, write_files=False))
    pin_store.objects[_PIN_KEY] = dataset.model_dump_json().encode()
    for name in ("video.mp4", "inputs.json"):
        if name != missing:
            pin_store.objects[f"replay-vision/golden/v1/cases/c1/{name}"] = b"{}"
    with pytest.raises(RuntimeError, match=f"missing {missing.split('.')[0]} for case c1"):
        download_pinned_dataset(tmp_path, api_key="test-key", bucket="test-bucket", key=_PIN_KEY)


@pytest.fixture
def real_pin_key(settings: Any, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    # The local S3-compatible store the test stack runs, reached through the pin's own client.
    monkeypatch.setenv(DATASET_ENDPOINT_ENV_VAR, settings.OBJECT_STORAGE_ENDPOINT)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", settings.OBJECT_STORAGE_ACCESS_KEY_ID)
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", settings.OBJECT_STORAGE_SECRET_ACCESS_KEY)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.delenv("AWS_SESSION_TOKEN", raising=False)
    monkeypatch.delenv("AWS_PROFILE", raising=False)
    prefix = f"test-replay-vision-pin-{uuid.uuid4().hex}"
    yield f"{prefix}/v1/manifest.json"
    s3 = boto3.resource(
        "s3",
        endpoint_url=settings.OBJECT_STORAGE_ENDPOINT,
        config=BotoConfig(signature_version="s3v4"),
    )
    s3.Bucket(settings.OBJECT_STORAGE_BUCKET).objects.filter(Prefix=prefix).delete()


def test_pinned_dataset_round_trips_through_real_object_storage(
    tmp_path: Path, real_pin_key: str, settings: Any, posthog_api: _FakePostHogApi
) -> None:
    source, target = tmp_path / "source", tmp_path / "target"
    dataset = _pinned_dataset(_golden_case_on_disk("c1", source), _golden_case_on_disk("c2", source))
    bucket = settings.OBJECT_STORAGE_BUCKET

    upload_pinned_dataset(source, dataset, bucket=bucket, key=real_pin_key)
    downloaded = download_pinned_dataset(target, api_key="test-key", bucket=bucket, key=real_pin_key)

    assert downloaded == dataset
    for case in dataset.cases:
        assert case.video_path(target).read_bytes() == case.video_path(source).read_bytes()
        assert case.inputs_path(target).read_text() == case.inputs_path(source).read_text()
    with pytest.raises(RuntimeError, match="upload under a new key prefix"):
        upload_pinned_dataset(source, dataset, bucket=bucket, key=real_pin_key)
    with pytest.raises(RuntimeError, match="No pinned golden dataset"):
        download_pinned_dataset(target, api_key="test-key", bucket=bucket, key=real_pin_key.replace("/v1/", "/v9/"))


def test_collect_cli_extends_a_pin_under_a_new_key(
    tmp_path: Path, real_pin_key: str, settings: Any, monkeypatch: pytest.MonkeyPatch, posthog_api: _FakePostHogApi
) -> None:
    bucket = settings.OBJECT_STORAGE_BUCKET
    pinned = _pinned_dataset(_golden_case_on_disk("c1", tmp_path / "seed"))
    upload_pinned_dataset(tmp_path / "seed", pinned, bucket=bucket, key=real_pin_key)
    new_key = real_pin_key.replace("/v1/", "/v2/")
    output = tmp_path / "output"
    seen_before_collect: list[list[str]] = []

    def fake_collect(*, output: Path, **_: Any) -> GoldenDataset:
        seen_before_collect.append([case.case_id for case in load_dataset(output).cases])
        grown = _pinned_dataset(*pinned.cases, _golden_case_on_disk("c2", output))
        save_dataset(output, grown)
        return grown

    monkeypatch.setenv("POSTHOG_API_KEY", "test-key")
    monkeypatch.setenv(DATASET_BUCKET_ENV_VAR, bucket)
    monkeypatch.setattr(sys, "argv", ["collect", "--output", str(output), "--from", real_pin_key, "--upload", new_key])
    with patch("products.replay_vision.evals.collector.collect", side_effect=fake_collect):
        collect_cli.main()

    assert seen_before_collect == [["c1"]]
    grown = download_pinned_dataset(tmp_path / "grown", api_key="test-key", bucket=bucket, key=new_key)
    assert [case.case_id for case in grown.cases] == ["c1", "c2"]
    original = download_pinned_dataset(tmp_path / "original", api_key="test-key", bucket=bucket, key=real_pin_key)
    assert [case.case_id for case in original.cases] == ["c1"]


@pytest.mark.parametrize("pinned", [True, False])
@pytest.mark.parametrize("approved", [True, False])
def test_eval_scanner_quality_checks_consent_and_recordings_before_scanning(
    tmp_path: Path,
    pin_store: _FakePinStore,
    posthog_api: _FakePostHogApi,
    monkeypatch: pytest.MonkeyPatch,
    pinned: bool,
    approved: bool,
) -> None:
    root = tmp_path / "dataset"
    live, deleted = _golden_case_on_disk("c1", root), _golden_case_on_disk("c2", root)
    posthog_api.deleted.add(deleted.session_id)
    posthog_api.approved = approved
    dataset = _pinned_dataset(live, deleted)
    if pinned:
        pin_store.objects[_PIN_KEY] = dataset.model_dump_json().encode()
        pin_store.objects["replay-vision/golden/v1/cases/c1/video.mp4"] = b"video"
        pin_store.objects["replay-vision/golden/v1/cases/c1/inputs.json"] = b"{}"
        monkeypatch.setenv(DATASET_BUCKET_ENV_VAR, "test-bucket")
        monkeypatch.setenv(DATASET_KEY_ENV_VAR, _PIN_KEY)
    else:
        save_dataset(root, dataset)
    monkeypatch.setenv(DATASET_ENV_VAR, str(root))
    monkeypatch.setenv("POSTHOG_API_KEY", "test-key")
    one_shot = AsyncMock()

    with (
        patch.object(eval_scanner_quality, "gemini_api_key", return_value="test-gemini-key"),
        patch.object(eval_scanner_quality, "OneShotPrivateEval", one_shot),
    ):
        if approved:
            asyncio.run(eval_scanner_quality.eval_scanner_quality(MagicMock()))
        else:
            with pytest.raises(RuntimeError, match="withdrawn AI data-processing consent"):
                asyncio.run(eval_scanner_quality.eval_scanner_quality(MagicMock()))

    assert (_PIN_KEY in pin_store.reads) == pinned
    case_reads = [key for key in pin_store.reads if "/cases/" in key]
    assert case_reads == (
        ["replay-vision/golden/v1/cases/c1/video.mp4", "replay-vision/golden/v1/cases/c1/inputs.json"]
        if pinned and approved
        else []
    )
    assert sorted(posthog_api.recording_checks()) == (["sess-c1", "sess-c2"] if approved else [])
    assert one_shot.call_count == (1 if approved else 0)
    if approved:
        assert [case.metadata["case_id"] for case in one_shot.call_args.kwargs["cases"]] == ["c1"]


def test_eval_scanner_quality_refuses_when_no_recording_is_left(
    tmp_path: Path, posthog_api: _FakePostHogApi, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / "dataset"
    gone = _golden_case_on_disk("c1", root)
    posthog_api.deleted.add(gone.session_id)
    save_dataset(root, _pinned_dataset(gone))
    monkeypatch.setenv(DATASET_ENV_VAR, str(root))
    monkeypatch.setenv("POSTHOG_API_KEY", "test-key")
    one_shot = AsyncMock()
    with (
        patch.object(eval_scanner_quality, "gemini_api_key", return_value="test-gemini-key"),
        patch.object(eval_scanner_quality, "OneShotPrivateEval", one_shot),
        pytest.raises(RuntimeError, match="live source recording"),
    ):
        asyncio.run(eval_scanner_quality.eval_scanner_quality(MagicMock()))
    one_shot.assert_not_called()


def _store_with_two_versions(tmp_path: Path) -> tuple[_FakePinStore, list[GoldenCase]]:
    cases = [_golden_case_on_disk(case_id, tmp_path) for case_id in ("c1", "c2", "c3")]
    store = _FakePinStore()
    for version, members in (("v1", cases[:2]), ("v2", cases)):
        store.objects[f"replay-vision/golden/{version}/manifest.json"] = (
            _pinned_dataset(*members).model_dump_json().encode()
        )
        for case in members:
            for name in ("video.mp4", "inputs.json"):
                store.objects[f"replay-vision/golden/{version}/cases/{case.case_id}/{name}"] = b"{}"
    return store, cases


def test_prune_deletes_dead_cases_from_every_version(tmp_path: Path, posthog_api: _FakePostHogApi) -> None:
    store, (_, deleted, expired) = _store_with_two_versions(tmp_path)
    posthog_api.deleted.add(deleted.session_id)
    posthog_api.expired.add(expired.session_id)

    removed = pin_lifecycle.prune_pinned_datasets(
        client=store, bucket="test-bucket", prefix="replay-vision/golden/", api_key="test-key"
    )

    assert sorted(removed) == [
        "replay-vision/golden/v1/cases/c2/inputs.json",
        "replay-vision/golden/v1/cases/c2/video.mp4",
        "replay-vision/golden/v2/cases/c2/inputs.json",
        "replay-vision/golden/v2/cases/c2/video.mp4",
        "replay-vision/golden/v2/cases/c3/inputs.json",
        "replay-vision/golden/v2/cases/c3/video.mp4",
    ]
    assert sorted(store.objects) == [
        "replay-vision/golden/v1/cases/c1/inputs.json",
        "replay-vision/golden/v1/cases/c1/video.mp4",
        "replay-vision/golden/v1/manifest.json",
        "replay-vision/golden/v2/cases/c1/inputs.json",
        "replay-vision/golden/v2/cases/c1/video.mp4",
        "replay-vision/golden/v2/manifest.json",
    ]
    for version, kept in (("v1", ["c1"]), ("v2", ["c1"])):
        manifest = GoldenDataset.model_validate_json(store.objects[f"replay-vision/golden/{version}/manifest.json"])
        assert [case.case_id for case in manifest.cases] == kept
    # One check per recording, even though v1 and v2 share two of them.
    assert sorted(posthog_api.recording_checks()) == ["sess-c1", "sess-c2", "sess-c3"]
    assert (
        pin_lifecycle.prune_pinned_datasets(
            client=store, bucket="test-bucket", prefix="replay-vision/golden/", api_key="test-key"
        )
        == []
    )
    assert len(store.writes) == 2


def test_prune_keeps_the_manifest_entry_until_the_case_files_are_gone(
    tmp_path: Path, posthog_api: _FakePostHogApi
) -> None:
    store, (_, deleted, _) = _store_with_two_versions(tmp_path)
    posthog_api.deleted.add(deleted.session_id)
    manifests = {key: body for key, body in store.objects.items() if key.endswith("manifest.json")}
    with (
        patch.object(store, "delete_object", side_effect=RuntimeError("storage down")),
        pytest.raises(RuntimeError, match="storage down"),
    ):
        pin_lifecycle.prune_pinned_datasets(
            client=store, bucket="test-bucket", prefix="replay-vision/golden/", api_key="test-key"
        )
    assert {key: store.objects[key] for key in manifests} == manifests


def test_prune_deletes_nothing_when_the_api_cannot_say(tmp_path: Path, posthog_api: _FakePostHogApi) -> None:
    store, (live, deleted, _) = _store_with_two_versions(tmp_path)
    posthog_api.failing.add(live.session_id)
    posthog_api.deleted.add(deleted.session_id)
    before = dict(store.objects)
    with pytest.raises(requests.HTTPError):
        pin_lifecycle.prune_pinned_datasets(
            client=store, bucket="test-bucket", prefix="replay-vision/golden/", api_key="test-key"
        )
    assert store.objects == before


def test_apply_known_freeform_tags_only_touches_freeform_classifiers() -> None:
    freeform = ClassifierScanner(prompt="x", tags=["a"], allow_freeform_tags=True)
    tagged = apply_known_freeform_tags(freeform, ["search_error"])
    assert isinstance(tagged, ClassifierScanner)
    assert tagged.known_freeform_tags == ["search_error"]
    # A fixed-vocab classifier rejects freeform output, so injecting tags there would break its validation.
    fixed = ClassifierScanner(prompt="x", tags=["a"], allow_freeform_tags=False)
    assert apply_known_freeform_tags(fixed, ["search_error"]) is fixed
    assert apply_known_freeform_tags(freeform, []) is freeform


def test_asset_is_recorded_video_rejects_rerasterized_assets() -> None:
    asset = _VideoAsset(asset_id=1, created_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC))
    assert asset_is_recorded_video(asset, {"completed_at": "2026-08-01T00:00:01+00:00"})
    assert not asset_is_recorded_video(asset, {"completed_at": "2026-07-31T23:59:59+00:00"})
    assert not asset_is_recorded_video(asset, {"completed_at": None})


def test_known_freeform_tags_ranks_recent_observations_only() -> None:
    now = dt.datetime.now(dt.UTC)

    def observation(days_ago: int, model_output: dict[str, Any] | None) -> dict[str, Any]:
        return {
            "created_at": (now - dt.timedelta(days=days_ago)).isoformat(),
            "scanner_result": {"model_output": model_output},
        }

    observations = [
        observation(1, {"tags_freeform": ["Search Error", "slow page"]}),
        observation(2, {"tags_freeform": ["search_error"]}),
        observation(60, {"tags_freeform": ["ancient_tag"]}),
        observation(0, None),
    ]
    assert collector._known_freeform_tags(observations) == ["search_error", "slow_page"]


_SESSION_START = "2026-08-01T12:00:00+12:00"
_SESSION_END = "2026-08-01T12:05:00+12:00"


class _FakeApi:
    project_id = 2

    def hogql(self, query: str, values: dict[str, Any] | None = None) -> list[list[Any]]:
        if "session_replay_events" in query:
            return [["d1", _SESSION_START, _SESSION_END, 3, 4, 5, 60_000, 0, "https://example.com/a"]]
        # Field order: DEFAULT_EVENT_FIELDS + _EXTRA_FIELDS.
        return [
            [
                "$pageview",
                "2026-08-01T12:00:10+12:00",
                "",
                [],
                [],
                "w1",
                "https://example.com/a",
                None,
                "00000000-0000-0000-0000-00000000000a",
                [],
                [],
                [],
            ],
            [
                "$autocapture",
                "2026-08-01T12:01:10+12:00",
                "",
                [],
                [],
                "w1",
                "https://example.com/b",
                "click",
                "00000000-0000-0000-0000-00000000000b",
                [],
                [],
                [],
            ],
            [
                "file_uploaded",
                "2026-08-01T12:02:10+12:00",
                "",
                [],
                [],
                "w1",
                "https://example.com/b",
                None,
                "00000000-0000-0000-0000-00000000000c",
                [],
                [],
                [],
            ],
        ]


def test_event_offsets_do_not_depend_on_local_timezone(monkeypatch: pytest.MonkeyPatch) -> None:
    def offsets_under(tz: str) -> dict[str, int]:
        monkeypatch.setenv("TZ", tz)
        time.tzset()
        inputs = build_llm_inputs(_FakeApi(), 2, "sess-1")  # type: ignore[arg-type]
        assert inputs is not None
        return inputs.event_timestamps

    try:
        utc_offsets = offsets_under("UTC")
        nz_offsets = offsets_under("Pacific/Auckland")
    finally:
        monkeypatch.undo()
        time.tzset()
    assert utc_offsets == nz_offsets
    assert utc_offsets["00000000-0000-0000-0000-00000000000a"] == 10_000
    assert utc_offsets["00000000-0000-0000-0000-00000000000b"] == 70_000


class _DefinitionsApi(_FakeApi):
    def __init__(self) -> None:
        self.definition_requests = 0

    def paginate(self, path: str, params: dict[str, Any] | None = None, max_items: int | None = None) -> Any:
        self.definition_requests += 1
        yield {"name": "file_uploaded", "description": "User uploaded a file"}


def test_build_llm_inputs_carries_prompt_context() -> None:
    api = _DefinitionsApi()
    lookup = collector.EventDescriptionLookup(api)  # type: ignore[arg-type]
    for _ in range(2):
        inputs = build_llm_inputs(api, 2, "sess-1", product_context="Acme sells anvils", event_descriptions=lookup)  # type: ignore[arg-type]
        assert inputs is not None
        assert inputs.product_context == "Acme sells anvils"
        assert inputs.event_descriptions == {"file_uploaded": "User uploaded a file"}
    # The description cache spans sessions, so the second build must not refetch.
    assert api.definition_requests == 1


class _PagedApi:
    def __init__(self, pages: list[list[list[Any]]]) -> None:
        self._pages = pages
        self._served = 0

    def hogql(self, query: str, values: dict[str, Any] | None = None) -> list[list[Any]]:
        page = self._pages[self._served] if self._served < len(self._pages) else []
        self._served += 1
        return page


def test_fetch_events_caps_total_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(collector, "_EVENTS_PER_PAGE", 2)
    monkeypatch.setattr(collector, "_MAX_TOTAL_EVENT_ROWS", 5)
    row = ["$pageview", _SESSION_START, "u"]
    api = _PagedApi([[row, row], [row, row], [row, row], [row, row]])
    start = dt.datetime(2026, 8, 1, 0, 0, 0, tzinfo=dt.UTC)
    fetched = collector._fetch_events(api, "sess-1", start, start + dt.timedelta(minutes=5))  # type: ignore[arg-type]
    assert len(fetched.rows) == 5
    assert fetched.truncated
