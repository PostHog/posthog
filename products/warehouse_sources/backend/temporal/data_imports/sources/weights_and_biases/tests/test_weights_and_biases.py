import json
import base64
import threading
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    RecordedRequest,
    ScriptedResponse,
    SourceDriver,
    always,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing.inputs import source_inputs
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.weightsandbiases import (
    WeightsAndBiasesSourceConfig,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.settings import (
    ENDPOINTS,
    WANDB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.source import (
    WeightsAndBiasesSource,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.weights_and_biases import (
    WeightsAndBiasesConfigError,
    WeightsAndBiasesGraphQLError,
    WeightsAndBiasesResumeConfig,
    _format_timestamp,
    _graphql_url,
    get_rows,
    validate_credentials,
    validate_host,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.weights_and_biases"


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
        "incremental_field, expected_filter_key, expected_order",
        [
            ("createdAt", "createdAt", "+created_at"),
            ("heartbeatAt", "heartbeatAt", "+heartbeat_at"),
            # An unknown/legacy field falls back to the stable default rather than sending a
            # filter the server would reject.
            ("nonsense", "createdAt", "+created_at"),
        ],
    )
    def test_incremental_filter_and_order(self, incremental_field, expected_filter_key, expected_order):
        result = _driver().run(
            "runs",
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
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
