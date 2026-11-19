import json
import base64
import threading
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.sources.sdk.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
    source_inputs,
)
from products.warehouse_sources.sources.weights_and_biases._config import WeightsAndBiasesSourceConfig
from products.warehouse_sources.sources.weights_and_biases.settings import ENDPOINTS, WANDB_ENDPOINTS
from products.warehouse_sources.sources.weights_and_biases.source import WeightsAndBiasesSource
from products.warehouse_sources.sources.weights_and_biases.weights_and_biases import (
    WeightsAndBiasesConfigError,
    WeightsAndBiasesGraphQLError,
    WeightsAndBiasesResumeConfig,
    _format_timestamp,
    _graphql_url,
    _history_row,
    _system_metrics_row,
    get_rows,
    validate_credentials,
    validate_host,
)

_MODULE = "products.warehouse_sources.sources.weights_and_biases.weights_and_biases"


def _driver() -> SourceDriver:
    return SourceDriver(WeightsAndBiasesSource(), WeightsAndBiasesSourceConfig(api_key="key", entity="acme"))


def _connection_response(
    connection_path: tuple[str, ...],
    edges: list[dict[str, Any]],
    has_next: bool = False,
    end_cursor: str | None = None,
) -> ScriptedResponse:
    data: Any = {
        "edges": edges,
        "pageInfo": {"endCursor": end_cursor or (edges[-1].get("cursor") if edges else None), "hasNextPage": has_next},
    }
    for key in reversed(connection_path):
        data = {key: data}
    return _ok_response({"data": data})


def _ok_response(payload: dict[str, Any]) -> ScriptedResponse:
    return ScriptedResponse(json=payload)


def _project_edge(name: str) -> dict[str, Any]:
    return {"node": {"id": f"proj-id-{name}", "name": name, "createdAt": "2024-01-01T00:00:00Z"}}


def _run_edge(run_id: str) -> dict[str, Any]:
    return {"node": {"id": run_id, "name": run_id, "state": "finished", "createdAt": "2024-01-01T00:00:00Z"}}


def _projects_response(names: list[str], has_next: bool = False, end_cursor: str | None = None) -> ScriptedResponse:
    return _connection_response(("models",), [_project_edge(n) for n in names], has_next, end_cursor)


class TestGraphQLUrl:
    @pytest.mark.parametrize(
        "host, expected",
        [
            (None, "https://api.wandb.ai/graphql"),
            ("", "https://api.wandb.ai/graphql"),
            ("  ", "https://api.wandb.ai/graphql"),
            ("https://acme.wandb.io", "https://acme.wandb.io/graphql"),
            ("https://acme.wandb.io/", "https://acme.wandb.io/graphql"),
            # A bare host is assumed https rather than rejected — users routinely paste one.
            ("acme.wandb.io", "https://acme.wandb.io/graphql"),
        ],
    )
    # is_url_allowed runs real DNS when DEBUG=False (as in CI); the fake hosts here aren't SSRF
    # cases, so allow them deterministically.
    @mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None))
    def test_host_normalization(self, _mock_allowed, host, expected):
        assert _graphql_url(host) == expected

    @pytest.mark.parametrize("host", ["http://acme.wandb.io", "http://api.wandb.ai", "ftp://acme.wandb.io"])
    def test_non_https_host_is_rejected(self, host):
        # The API key is sent as HTTP Basic auth, so a plaintext scheme would leak it on the wire.
        with pytest.raises(WeightsAndBiasesConfigError, match="https"):
            _graphql_url(host)
        with pytest.raises(WeightsAndBiasesConfigError, match="https"):
            validate_host(host)

    @mock.patch(f"{_MODULE}.is_url_allowed", return_value=(False, "blocked: private IP"))
    def test_ssrf_blocked_host_is_rejected(self, _mock_allowed):
        # A custom host resolving to an internal/metadata address must be refused before any
        # request leaves the worker (defense-in-depth over the Smokescreen egress proxy).
        with pytest.raises(WeightsAndBiasesConfigError, match="not allowed"):
            _graphql_url("https://internal.example")
        with pytest.raises(WeightsAndBiasesConfigError, match="not allowed"):
            validate_host("https://internal.example")


class TestFormatTimestamp:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2024, 1, 2, 3, 4, 5, tzinfo=UTC), "2024-01-02T03:04:05Z"),
            (datetime(2024, 1, 2, 3, 4, 5), "2024-01-02T03:04:05Z"),
            (date(2024, 1, 2), "2024-01-02T00:00:00Z"),
            ("2024-01-02T03:04:05Z", "2024-01-02T03:04:05Z"),
        ],
    )
    def test_format_values(self, value, expected):
        assert _format_timestamp(value) == expected


class TestValidateCredentials:
    @mock.patch(f"{_MODULE}.is_url_allowed", return_value=(True, None))
    def test_session_uses_basic_auth_with_api_username(self, _mock_allowed):
        with scripted_network([_ok_response({"data": {"viewer": {"id": "abc"}}})]) as network:
            validate_credentials("secret-key", "https://acme.wandb.io")

        assert network.requests_log[0].url == "https://acme.wandb.io/graphql"
        expected = base64.b64encode(b"api:secret-key").decode()
        assert network.requests_log[0].headers["authorization"] == f"Basic {expected}"


def _variables(requests_log: list[RecordedRequest]) -> list[dict[str, Any]]:
    return [request.json()["variables"] for request in requests_log]


class TestRunsEndpoint:
    @pytest.mark.parametrize(
        "endpoint, incremental_field, expected_filter_key, expected_order",
        [
            ("runs", "createdAt", "createdAt", "+created_at"),
            ("runs", "heartbeatAt", "heartbeatAt", "+heartbeat_at"),
            # An unknown/legacy field falls back to the stable default rather than sending a
            # filter the server would reject.
            ("runs", "nonsense", "createdAt", "+created_at"),
            # Run-child tables carry the run's heartbeatAt and filter the runs connection on it.
            ("run_artifacts", "runHeartbeatAt", "heartbeatAt", "+heartbeat_at"),
            ("run_history", "runHeartbeatAt", "heartbeatAt", "+heartbeat_at"),
        ],
    )
    def test_incremental_filter_and_order(self, endpoint, incremental_field, expected_filter_key, expected_order):
        result = _driver().run(
            endpoint,
            [_projects_response(["proj-a"]), _connection_response(("project", "runs"), [])],
            incremental_field=incremental_field,
            db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
        )

        variables = _variables(result.requests)[-1]
        assert json.loads(variables["filters"]) == {expected_filter_key: {"$gt": "2024-01-02T00:00:00Z"}}
        assert variables["order"] == expected_order

    def test_rows_carry_project_name_and_state_saved_per_page(self):
        result = _driver().run(
            "runs",
            [
                _projects_response(["proj-a"]),
                _connection_response(("project", "runs"), [_run_edge("r1")], has_next=True, end_cursor="cur-1"),
                _connection_response(("project", "runs"), [_run_edge("r2")], has_next=False),
            ],
        )

        assert [(row["id"], row["projectName"]) for row in result.rows] == [("r1", "proj-a"), ("r2", "proj-a")]
        assert result.saved_states == [WeightsAndBiasesResumeConfig(project="proj-a", cursor="cur-1")]

    def test_fan_out_resumes_from_bookmarked_project(self):
        result = _driver().run(
            "runs",
            [
                _projects_response(["proj-a", "proj-b", "proj-c"]),
                _connection_response(("project", "runs"), [_run_edge("rb")], has_next=False),
                _connection_response(("project", "runs"), [_run_edge("rc")], has_next=False),
            ],
            resume_state=WeightsAndBiasesResumeConfig(project="proj-b", cursor="cur-9"),
        )

        run_calls = [variables for variables in _variables(result.requests) if variables.get("project")]
        # proj-a is skipped entirely; only the resumed-into project uses the saved cursor.
        assert [(v["project"], v["after"]) for v in run_calls] == [("proj-b", "cur-9"), ("proj-c", None)]
        assert [row["id"] for row in result.rows] == ["rb", "rc"]
        # The bookmark advanced to proj-c once proj-b completed.
        assert result.saved_states[-1] == WeightsAndBiasesResumeConfig(project="proj-c", cursor=None)


class TestArtifactsEndpoint:
    def test_rows_carry_parent_identifiers(self):
        artifact_edge = {
            "version": "v3",
            "node": {"id": "art-1", "digest": "abc", "state": "COMMITTED", "createdAt": "2024-01-01T00:00:00Z"},
        }
        result = _driver().run(
            "artifacts",
            [
                _projects_response(["proj-a"]),
                _connection_response(("project", "artifactTypes"), [{"node": {"name": "model"}}]),
                _connection_response(
                    ("project", "artifactType", "artifactCollections"), [{"node": {"name": "coll-1"}}]
                ),
                _connection_response(("project", "artifactType", "artifactCollection", "artifacts"), [artifact_edge]),
            ],
        )

        rows = result.rows
        assert len(rows) == 1
        assert rows[0]["id"] == "art-1"
        assert rows[0]["version"] == "v3"
        assert rows[0]["projectName"] == "proj-a"
        assert rows[0]["artifactTypeName"] == "model"
        assert rows[0]["collectionName"] == "coll-1"

    def test_artifact_type_deleted_mid_sync_is_skipped(self):
        result = _driver().run(
            "artifacts",
            [
                _projects_response(["proj-a"]),
                _connection_response(("project", "artifactTypes"), [{"node": {"name": "model"}}]),
                _ok_response({"data": {"project": {"artifactType": None}}}),
            ],
        )

        assert result.raised is None
        assert result.items == []


class TestArtifactLookupEndpoints:
    def test_artifact_collection_rows_are_flattened(self):
        node = {
            "__typename": "ArtifactSequence",
            "id": "coll-id",
            "name": "my-model",
            "createdAt": "2024-01-01T00:00:00Z",
            "defaultArtifactType": {"name": "model"},
            "tags": {"edges": [{"node": {"name": "prod"}}, {"node": None}]},
        }
        result = _driver().run(
            "artifact_collections",
            [
                _projects_response(["proj-a"]),
                _connection_response(("project", "artifactCollections"), [{"node": node}]),
            ],
        )

        assert result.rows == [
            {
                "id": "coll-id",
                "name": "my-model",
                "collectionType": "ArtifactSequence",
                "description": None,
                "createdAt": "2024-01-01T00:00:00Z",
                "updatedAt": None,
                "artifactTypeName": "model",
                "tags": ["prod"],
                "projectName": "proj-a",
            }
        ]

    def test_members_without_an_id_are_skipped(self):
        members = [
            {"id": "user-1", "username": "ada", "name": "Ada", "pending": False},
            {"id": None, "username": None, "name": "invitee", "pending": True},
        ]
        result = _driver().run("members", [_ok_response({"data": {"entity": {"members": members}}})])

        assert [row["username"] for row in result.rows] == ["ada"]
        assert len(result.requests) == 1
        assert "apiKey" not in result.requests[0].json()["query"]

    @pytest.mark.parametrize(
        "entity, expected_ids",
        [
            ({"id": "ent-1", "name": "acme", "isTeam": True, "storageBytes": 2048}, ["ent-1"]),
            # The API answers null for an entity the key cannot see, instead of an error.
            (None, []),
        ],
    )
    def test_entity_row(self, entity, expected_ids):
        result = _driver().run("entities", [_ok_response({"data": {"entity": entity}})])

        assert [row["id"] for row in result.rows] == expected_ids
        assert result.requests[0].json()["variables"] == {"entity": "acme"}
        assert "photoUrl" not in result.requests[0].json()["query"]


def _lineage_run(name: str, inputs: list[str], outputs: list[str], outputs_next: str | None = None) -> dict[str, Any]:
    def connection(ids: list[str], next_cursor: str | None = None) -> dict[str, Any]:
        return {
            "edges": [
                {
                    "node": {
                        "id": i,
                        "versionIndex": 0,
                        "artifactType": {"name": "model"},
                        "artifactSequence": {"name": "m"},
                    }
                }
                for i in ids
            ],
            "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None},
        }

    return {
        "node": {
            "id": f"id-{name}",
            "name": name,
            "createdAt": "2024-01-01T00:00:00Z",
            "heartbeatAt": "2024-01-02T00:00:00Z",
            "inputArtifacts": connection(inputs),
            "outputArtifacts": connection(outputs, outputs_next),
        }
    }


class TestRunArtifactsEndpoint:
    def test_nested_lineage_pages_are_followed_per_run(self):
        result = _driver().run(
            "run_artifacts",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"),
                    [_lineage_run("r1", ["in-1"], ["out-1"], outputs_next="out-cur"), _lineage_run("r2", [], [])],
                    has_next=True,
                    end_cursor="runs-cur",
                ),
                _connection_response(("project", "run", "outputArtifacts"), [{"node": {"id": "out-2"}}]),
                _connection_response(("project", "runs"), [_lineage_run("r3", [], ["out-3"])]),
            ],
        )

        assert [(r["runId"], r["direction"], r["artifactId"]) for r in result.rows] == [
            ("id-r1", "input", "in-1"),
            ("id-r1", "output", "out-1"),
            ("id-r1", "output", "out-2"),
            ("id-r3", "output", "out-3"),
        ]
        follow_up = _variables(result.requests)[2]
        assert (follow_up["run"], follow_up["after"]) == ("r1", "out-cur")
        # Each artifact page is its own batch, so a run with many artifact pages is never buffered.
        assert len(result.items) == 4
        # The bookmark past a run is committed with its last batch, and the next page after the first.
        assert result.committed_states == [
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r1"),
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r2"),
            WeightsAndBiasesResumeConfig(project="proj-a", cursor="runs-cur"),
            WeightsAndBiasesResumeConfig(project="proj-a", cursor="runs-cur", run="r3"),
        ]


def _files_run(name: str, files: list[str], next_cursor: str | None = None) -> dict[str, Any]:
    return {
        "node": {
            "id": f"id-{name}",
            "name": name,
            "createdAt": "2024-01-01T00:00:00Z",
            "heartbeatAt": "2024-01-02T00:00:00Z",
            "files": {
                "edges": [{"node": {"id": f"file-{f}", "name": f, "sizeBytes": 10}} for f in files],
                "pageInfo": {"endCursor": next_cursor, "hasNextPage": next_cursor is not None},
            },
        }
    }


class TestRunFilesEndpoint:
    def test_nested_file_pages_are_followed_per_run(self):
        result = _driver().run(
            "run_files",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"),
                    [_files_run("r1", ["config.yaml"], next_cursor="files-cur"), _files_run("r2", [])],
                ),
                _connection_response(
                    ("project", "run", "files"),
                    [{"node": {"id": "file-model.pt", "name": "model.pt", "sizeBytes": 99}}, {"node": {"id": "x"}}],
                ),
            ],
        )

        assert [(r["runId"], r["name"], r["sizeBytes"]) for r in result.rows] == [
            ("id-r1", "config.yaml", 10),
            ("id-r1", "model.pt", 99),
        ]
        follow_up = _variables(result.requests)[2]
        assert (follow_up["run"], follow_up["after"]) == ("r1", "files-cur")
        # Signed download URLs expire, so they are never requested.
        assert all("url" not in request.json()["query"].lower() for request in result.requests[1:])
        assert result.committed_states == [
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r1"),
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r2"),
        ]


def _events_run(name: str, line_count: int | None) -> dict[str, Any]:
    return {
        "node": {
            "id": f"id-{name}",
            "name": name,
            "createdAt": "2024-01-01T00:00:00Z",
            "heartbeatAt": "2024-01-02T00:00:00Z",
            "eventsLineCount": line_count,
        }
    }


def _events_response(timestamps: list[float]) -> ScriptedResponse:
    lines = [json.dumps({"_timestamp": ts, "_runtime": 30, "_wandb": True, "system.cpu": 50.0}) for ts in timestamps]
    return _ok_response({"data": {"project": {"run": {"events": lines}}}})


class TestRunSystemMetricsEndpoint:
    def test_runs_without_samples_are_not_fetched_and_each_run_commits(self):
        result = _driver().run(
            "run_system_metrics",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"),
                    [_events_run("r1", 2), _events_run("r2", 0), _events_run("r3", None)],
                ),
                _events_response([1704067200, 1704067230]),
                _events_response([1704067260]),
            ],
        )

        event_calls = [v for v in _variables(result.requests) if "samples" in v]
        assert [v["run"] for v in event_calls] == ["r1", "r3"]
        assert [(row["runName"], row["timestamp"]) for row in result.rows] == [
            ("r1", "2024-01-01T00:00:00+00:00"),
            ("r1", "2024-01-01T00:00:30+00:00"),
            ("r3", "2024-01-01T00:01:00+00:00"),
        ]
        assert result.committed_states == [
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r2"),
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r3"),
        ]

    def test_pages_of_runs_with_empty_samples_reach_a_safe_point(self):
        result = _driver().run(
            "run_system_metrics",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"), [_events_run("r1", 3), _events_run("r2", 3), _events_run("r3", 3)]
                ),
                _events_response([]),
                _events_response([]),
                _ok_response({"data": {"project": {"run": None}}}),
            ],
        )

        assert result.rows == []
        assert result.raised is None
        # Each run is one request, so a run with no samples must commit its bookmark on its own.
        assert result.committed_states == [
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r2"),
            WeightsAndBiasesResumeConfig(project="proj-a", cursor=None, run="r3"),
        ]

    @pytest.mark.parametrize(
        "line, expected",
        [
            (
                json.dumps({"_timestamp": 1704067200.5, "_runtime": 12, "_wandb": True, "system.gpu.0.gpu": 80}),
                {"timestamp": "2024-01-01T00:00:00.500000+00:00", "runtime": 12.0, "metrics": {"system.gpu.0.gpu": 80}},
            ),
            (
                {"_timestamp": 1704067200, "system.cpu": 1},
                {"timestamp": "2024-01-01T00:00:00+00:00", "runtime": None, "metrics": {"system.cpu": 1}},
            ),
            # The timestamp is part of the primary key, so a sample without a usable one is dropped.
            (json.dumps({"_runtime": 1, "system.cpu": 1}), None),
            (json.dumps({"_timestamp": "bad"}), None),
            (json.dumps({"_timestamp": True}), None),
            (json.dumps([1, 2]), None),
        ],
    )
    def test_system_metrics_row_shaping(self, line, expected):
        row = _system_metrics_row({"runId": "id-r1"}, line)

        if expected is None:
            assert row is None
            return
        assert row is not None
        assert row["runId"] == "id-r1"
        assert (row["timestamp"], row["runtime"]) == (expected["timestamp"], expected["runtime"])
        assert json.loads(row["metrics"]) == expected["metrics"]


def _history_run(name: str, last_step: int, line_count: int) -> dict[str, Any]:
    return {
        "node": {
            "id": f"id-{name}",
            "name": name,
            "createdAt": "2024-01-01T00:00:00Z",
            "heartbeatAt": "2024-01-02T00:00:00Z",
            "historyLineCount": line_count,
            "historyKeys": json.dumps({"lastStep": last_step}),
        }
    }


def _history_response(steps: list[int]) -> ScriptedResponse:
    lines = [json.dumps({"_step": step, "loss": step / 10}) for step in steps]
    return _ok_response({"data": {"project": {"run": {"history": lines}}}})


class TestRunHistoryEndpoint:
    @mock.patch(f"{_MODULE}.RUN_HISTORY_PAGE_SIZE", 2)
    def test_window_that_was_sampled_is_split_and_read_again(self):
        # 4 lines over 8 steps -> the first window spans 4 steps. A window returning more than
        # the page size may have been sampled, so it is halved and re-read; nothing is dropped.
        result = _driver().run(
            "run_history",
            [
                _projects_response(["proj-a"]),
                _connection_response(("project", "runs"), [_history_run("r1", last_step=7, line_count=4)]),
                _history_response([0, 1, 2]),  # [0, 4) sampled -> rejected
                _history_response([0, 1]),  # [0, 2)
                _history_response([2, 3]),  # [2, 4)
                _history_response([]),  # [4, 6)
                _history_response([7]),  # [6, 10) after an empty window doubles it
            ],
        )

        history_calls = [v for v in _variables(result.requests) if "minStep" in v]
        assert [(v["minStep"], v["maxStep"]) for v in history_calls] == [(0, 4), (0, 2), (2, 4), (4, 6), (6, 10)]
        assert [(row["runId"], row["step"]) for row in result.rows] == [
            ("id-r1", 0),
            ("id-r1", 1),
            ("id-r1", 2),
            ("id-r1", 3),
            ("id-r1", 7),
        ]
        assert result.raised is None

    @mock.patch(f"{_MODULE}.RUN_HISTORY_PAGE_SIZE", 2)
    def test_resumes_at_the_saved_run_and_step(self):
        result = _driver().run(
            "run_history",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"),
                    [_history_run("r1", last_step=3, line_count=4), _history_run("r2", last_step=3, line_count=4)],
                ),
                _history_response([2, 3]),
                _history_response([0, 1]),
                _history_response([2, 3]),
            ],
            resume_state=WeightsAndBiasesResumeConfig(project="proj-a", cursor="runs-cur", run="r2", step=2),
        )

        variables = _variables(result.requests)
        assert variables[1]["after"] == "runs-cur"
        # r1 precedes the bookmark and is skipped; r2 starts at the saved step, the run after it at 0.
        assert [(row["runName"], row["step"]) for row in result.rows][:2] == [("r2", 2), ("r2", 3)]
        assert next((v["run"], v["minStep"]) for v in variables if "minStep" in v) == ("r2", 2)

    @mock.patch(f"{_MODULE}.RUN_HISTORY_PAGE_SIZE", 2)
    def test_state_is_staged_with_the_next_window_before_rows_are_yielded(self):
        result = _driver().run(
            "run_history",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"),
                    [_history_run("r1", last_step=3, line_count=4), _history_run("r2", last_step=3, line_count=4)],
                ),
                _history_response([0, 1]),
                _history_response([2, 3]),
                _history_response([0, 1]),
                _history_response([2, 3]),
            ],
        )

        # The last window of r1 commits the bookmark past r1, so a resume does not read r1 again.
        assert result.committed_states == [
            WeightsAndBiasesResumeConfig(project="proj-a", run="r1", step=2),
            WeightsAndBiasesResumeConfig(project="proj-a", run="r2"),
            WeightsAndBiasesResumeConfig(project="proj-a", run="r2", step=2),
        ]

    def test_pages_of_runs_without_history_reach_a_safe_point(self):
        result = _driver().run(
            "run_history",
            [
                _projects_response(["proj-a"]),
                _connection_response(
                    ("project", "runs"),
                    [_history_run("r1", last_step=-1, line_count=0)],
                    has_next=True,
                    end_cursor="c1",
                ),
                _connection_response(("project", "runs"), [_history_run("r2", last_step=-1, line_count=0)]),
            ],
        )

        assert result.rows == []
        assert result.committed_states == [WeightsAndBiasesResumeConfig(project="proj-a", cursor="c1")]

    @pytest.mark.parametrize(
        "line, expected",
        [
            (
                json.dumps({"_step": 5, "_runtime": 12, "_timestamp": 1704067200.5, "loss": 0.1, "acc": None}),
                {
                    "step": 5,
                    "runtime": 12.0,
                    "timestamp": "2024-01-01T00:00:00.500000+00:00",
                    "metrics": {"loss": 0.1, "acc": None},
                },
            ),
            # Some hosts return already-decoded rows instead of JSON strings.
            ({"_step": 0, "loss": 1}, {"step": 0, "runtime": None, "timestamp": None, "metrics": {"loss": 1}}),
            (
                '{"_step": 1, "loss": NaN, "_timestamp": "bad"}',
                {"step": 1, "runtime": None, "timestamp": None, "metrics": {"loss": float("nan")}},
            ),
            (json.dumps({"loss": 1}), None),
            (json.dumps({"_step": "3"}), None),
            (json.dumps({"_step": True}), None),
            (json.dumps([1, 2]), None),
        ],
    )
    def test_history_row_shaping(self, line, expected):
        row = _history_row({"runId": "id-r1"}, line)

        if expected is None:
            assert row is None
            return
        assert row is not None
        assert row["runId"] == "id-r1"
        for key in ("step", "runtime", "timestamp"):
            assert row[key] == expected[key]
        metrics = json.loads(row["metrics"])
        assert metrics.keys() == expected["metrics"].keys()
        assert all(
            (v != v and expected["metrics"][k] != expected["metrics"][k]) or v == expected["metrics"][k]
            for k, v in metrics.items()
        )


class TestErrors:
    def test_graphql_error_raises(self):
        result = _driver().run("projects", always(_ok_response({"errors": [{"message": "permission denied"}]})))

        assert isinstance(result.raised, WeightsAndBiasesGraphQLError)
        assert "permission denied" in str(result.raised)

    def test_unknown_endpoint_raises(self):
        manager = WeightsAndBiasesSource().get_resumable_source_manager(source_inputs("nope"))

        with pytest.raises(ValueError, match="Unknown Weights & Biases endpoint"):
            list(get_rows("key", None, "acme", "nope", mock.MagicMock(), manager))

    @mock.patch(f"{_MODULE}.MAX_PAGES_PER_CONNECTION", 3)
    def test_pagination_stops_at_page_cap(self):
        # A hostile host that returns hasNextPage=true with a fresh cursor forever must not loop
        # indefinitely — the page cap bounds it.
        counter = {"n": 0}

        def endless_post(_request: RecordedRequest) -> ScriptedResponse:
            counter["n"] += 1
            return _projects_response([f"proj-{counter['n']}"], has_next=True, end_cursor=f"c{counter['n']}")

        result = _driver().run("projects", endless_post)

        assert len(result.requests) == 3
        assert len(result.items) == 3

    @mock.patch(f"{_MODULE}.MAX_RESPONSE_BYTES", 16)
    def test_oversized_response_body_is_rejected(self):
        # The host is customer-controlled; an unbounded body must not be buffered into a worker.
        result = _driver().run("projects", always(ScriptedResponse(body=b"x" * 17)))

        assert isinstance(result.raised, WeightsAndBiasesGraphQLError)
        assert "oversized" in str(result.raised)

    @mock.patch(f"{_MODULE}.make_tracked_session")
    @mock.patch(f"{_MODULE}.MAX_TRANSFER_SECONDS", 0.2)
    def test_slow_response_exceeding_transfer_deadline_is_rejected(self, mock_session):
        # A host that keeps a read blocked (dripping bytes below the per-read inactivity timeout)
        # must still be cut off by the wall-clock deadline, which interrupts the blocked read by
        # closing the response. The read here blocks until close() releases it.
        release = threading.Event()
        resp = mock.MagicMock()
        resp.status_code = 200
        resp.ok = True
        resp.headers = {}
        resp.raw.read.side_effect = lambda *a, **k: (release.wait(timeout=5), b"")[1]
        resp.close.side_effect = release.set
        mock_session.return_value.post.return_value = resp

        manager = WeightsAndBiasesSource().get_resumable_source_manager(source_inputs("projects"))
        with pytest.raises(WeightsAndBiasesGraphQLError, match="deadline"):
            list(get_rows("key", None, "acme", "projects", mock.MagicMock(), manager))

        assert resp.close.called

    def test_forced_content_encoding_is_rejected(self):
        # We request Accept-Encoding: identity and read the body undecoded; a host that compresses
        # anyway (a decompression-bomb vector) must be rejected rather than decoded.
        result = _driver().run("projects", always(ScriptedResponse(json={}, headers={"Content-Encoding": "gzip"})))

        assert isinstance(result.raised, WeightsAndBiasesGraphQLError)
        assert "Content-Encoding" in str(result.raised)

    @mock.patch(f"{_MODULE}.MAX_RETAINED_PROJECT_NAME_BYTES", 10)
    def test_oversized_fan_out_project_list_is_rejected(self):
        # A hostile host can page project names back indefinitely; the fan-out enumeration must
        # stop buffering them before the retained list can exhaust a worker.
        result = _driver().run(
            "runs",
            [
                _projects_response(["p" * 4], has_next=True, end_cursor="c1"),
                _projects_response(["q" * 8], has_next=False),
            ],
        )

        assert isinstance(result.raised, WeightsAndBiasesGraphQLError)
        assert "unreasonably large project list" in str(result.raised)


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        result = _driver().run(endpoint, always(_ok_response({"data": {}})))

        response = result.response
        assert response is not None
        assert response.name == endpoint
        assert response.primary_keys == WANDB_ENDPOINTS[endpoint].primary_keys
        # Fan-out over projects means rows only ascend within one project — the watermark
        # commits at run end.
        assert response.sort_mode == "desc"
        partition_key = WANDB_ENDPOINTS[endpoint].partition_key
        if partition_key is None:
            assert response.partition_mode is None
            assert response.partition_keys is None
        else:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [partition_key]
