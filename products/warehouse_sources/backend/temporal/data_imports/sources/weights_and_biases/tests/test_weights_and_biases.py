import json
from datetime import UTC, date, datetime
from typing import Any

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.settings import (
    ENDPOINTS,
    WANDB_ENDPOINTS,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.weights_and_biases import (
    PAGE_SIZE,
    WeightsAndBiasesConfigError,
    WeightsAndBiasesGraphQLError,
    WeightsAndBiasesResumeConfig,
    _format_timestamp,
    _graphql_url,
    get_rows,
    validate_credentials,
    validate_host,
    weights_and_biases_source,
)

_MODULE = "products.warehouse_sources.backend.temporal.data_imports.sources.weights_and_biases.weights_and_biases"


def _make_manager(resume_state: WeightsAndBiasesResumeConfig | None = None) -> mock.MagicMock:
    manager = mock.MagicMock()
    manager.can_resume.return_value = resume_state is not None
    manager.load_state.return_value = resume_state
    return manager


def _connection_response(
    connection_path: tuple[str, ...],
    edges: list[dict[str, Any]],
    has_next: bool = False,
    end_cursor: str | None = None,
) -> mock.MagicMock:
    data: Any = {
        "edges": edges,
        "pageInfo": {"endCursor": end_cursor or (edges[-1].get("cursor") if edges else None), "hasNextPage": has_next},
    }
    for key in reversed(connection_path):
        data = {key: data}
    return _ok_response({"data": data})


def _ok_response(payload: dict[str, Any]) -> mock.MagicMock:
    # _execute reads the body via response.raw.read(...) under a size cap, not response.json().
    resp = mock.MagicMock()
    resp.status_code = 200
    resp.ok = True
    resp.raw.read.return_value = json.dumps(payload).encode()
    return resp


def _project_edge(name: str) -> dict[str, Any]:
    return {"node": {"id": f"proj-id-{name}", "name": name, "createdAt": "2024-01-01T00:00:00Z"}}


def _run_edge(run_id: str) -> dict[str, Any]:
    return {"node": {"id": run_id, "name": run_id, "state": "finished", "createdAt": "2024-01-01T00:00:00Z"}}


def _projects_response(names: list[str], has_next: bool = False, end_cursor: str | None = None) -> mock.MagicMock:
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
    def test_host_normalization(self, host, expected):
        assert _graphql_url(host) == expected

    @pytest.mark.parametrize("host", ["http://acme.wandb.io", "http://api.wandb.ai", "ftp://acme.wandb.io"])
    def test_non_https_host_is_rejected(self, host):
        # The API key is sent as HTTP Basic auth, so a plaintext scheme would leak it on the wire.
        with pytest.raises(WeightsAndBiasesConfigError, match="https"):
            _graphql_url(host)
        with pytest.raises(WeightsAndBiasesConfigError, match="https"):
            validate_host(host)


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
    @pytest.mark.parametrize(
        "viewer, expected",
        [
            ({"id": "abc", "username": "someone"}, True),
            (None, False),  # the API returns 200 with viewer=null for a bad key
        ],
    )
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_viewer_presence_decides_validity(self, mock_session, viewer, expected):
        mock_session.return_value.post.return_value = _ok_response({"data": {"viewer": viewer}})

        assert validate_credentials("key", None) is expected

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_invalid_on_exception(self, mock_session):
        mock_session.return_value.post.side_effect = Exception("boom")
        assert validate_credentials("key", None) is False

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_session_uses_basic_auth_with_api_username(self, mock_session):
        mock_session.return_value.post.return_value = _ok_response({"data": {"viewer": {"id": "abc"}}})

        validate_credentials("secret-key", "https://acme.wandb.io")

        assert mock_session.return_value.auth == ("api", "secret-key")
        assert mock_session.return_value.post.call_args.args[0] == "https://acme.wandb.io/graphql"


class TestProjectsEndpoint:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_paginates_and_saves_state_after_yield(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _projects_response(["p1", "p2"], has_next=True, end_cursor="cur-1"),
            _projects_response(["p3"], has_next=False),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", None, "acme", "projects", mock.MagicMock(), manager))

        assert [row["name"] for batch in batches for row in batch] == ["p1", "p2", "p3"]
        manager.save_state.assert_called_once()
        assert manager.save_state.call_args.args[0].cursor == "cur-1"
        second_vars = mock_session.return_value.post.call_args_list[1].kwargs["json"]["variables"]
        assert second_vars["after"] == "cur-1"
        assert second_vars["first"] == PAGE_SIZE

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_empty_edges_page_with_has_next_keeps_paginating(self, mock_session):
        # The live API returns empty edges with hasNextPage=true for pages whose rows are
        # hidden from the caller — terminating on the empty page would silently truncate.
        mock_session.return_value.post.side_effect = [
            _connection_response(("models",), [], has_next=True, end_cursor="cur-1"),
            _projects_response(["p1"], has_next=False),
        ]

        batches = list(get_rows("key", None, "acme", "projects", mock.MagicMock(), _make_manager()))

        assert [row["name"] for batch in batches for row in batch] == ["p1"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_non_advancing_cursor_terminates(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _projects_response(["p1"], has_next=True, end_cursor="cur-1"),
            _projects_response(["p2"], has_next=True, end_cursor="cur-1"),
        ]

        batches = list(get_rows("key", None, "acme", "projects", mock.MagicMock(), _make_manager()))

        assert mock_session.return_value.post.call_count == 2
        assert [row["name"] for batch in batches for row in batch] == ["p1", "p2"]

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_resumes_from_saved_cursor(self, mock_session):
        mock_session.return_value.post.return_value = _projects_response(["p9"], has_next=False)

        manager = _make_manager(WeightsAndBiasesResumeConfig(cursor="cur-resume"))
        list(get_rows("key", None, "acme", "projects", mock.MagicMock(), manager))

        variables = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert variables["after"] == "cur-resume"


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
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_incremental_filter_and_order(self, mock_session, incremental_field, expected_filter_key, expected_order):
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a"]),
            _connection_response(("project", "runs"), []),
        ]

        list(
            get_rows(
                "key",
                None,
                "acme",
                "runs",
                mock.MagicMock(),
                _make_manager(),
                should_use_incremental_field=True,
                db_incremental_field_last_value=datetime(2024, 1, 2, tzinfo=UTC),
                incremental_field=incremental_field,
            )
        )

        variables = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert json.loads(variables["filters"]) == {expected_filter_key: {"$gt": "2024-01-02T00:00:00Z"}}
        assert variables["order"] == expected_order

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_full_refresh_has_null_filters_and_stable_order(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a"]),
            _connection_response(("project", "runs"), []),
        ]

        list(get_rows("key", None, "acme", "runs", mock.MagicMock(), _make_manager()))

        variables = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert variables["filters"] is None
        assert variables["order"] == "+created_at"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_carry_project_name_and_state_saved_per_page(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a"]),
            _connection_response(("project", "runs"), [_run_edge("r1")], has_next=True, end_cursor="cur-1"),
            _connection_response(("project", "runs"), [_run_edge("r2")], has_next=False),
        ]

        manager = _make_manager()
        batches = list(get_rows("key", None, "acme", "runs", mock.MagicMock(), manager))

        rows = [row for batch in batches for row in batch]
        assert [(row["id"], row["projectName"]) for row in rows] == [("r1", "proj-a"), ("r2", "proj-a")]
        manager.save_state.assert_called_once()
        saved = manager.save_state.call_args.args[0]
        assert (saved.project, saved.cursor) == ("proj-a", "cur-1")

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_fan_out_resumes_from_bookmarked_project(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a", "proj-b", "proj-c"]),
            _connection_response(("project", "runs"), [_run_edge("rb")], has_next=False),
            _connection_response(("project", "runs"), [_run_edge("rc")], has_next=False),
        ]

        manager = _make_manager(WeightsAndBiasesResumeConfig(project="proj-b", cursor="cur-9"))
        batches = list(get_rows("key", None, "acme", "runs", mock.MagicMock(), manager))

        run_calls = [
            call.kwargs["json"]["variables"]
            for call in mock_session.return_value.post.call_args_list
            if call.kwargs["json"]["variables"].get("project")
        ]
        # proj-a is skipped entirely; only the resumed-into project uses the saved cursor.
        assert [(v["project"], v["after"]) for v in run_calls] == [("proj-b", "cur-9"), ("proj-c", None)]
        assert [row["id"] for batch in batches for row in batch] == ["rb", "rc"]
        # The bookmark advanced to proj-c once proj-b completed.
        assert (manager.save_state.call_args.args[0].project, manager.save_state.call_args.args[0].cursor) == (
            "proj-c",
            None,
        )

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_deleted_bookmarked_project_restarts_from_first(self, mock_session):
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a"]),
            _connection_response(("project", "runs"), [_run_edge("ra")], has_next=False),
        ]

        manager = _make_manager(WeightsAndBiasesResumeConfig(project="deleted-proj", cursor="cur-9"))
        batches = list(get_rows("key", None, "acme", "runs", mock.MagicMock(), manager))

        run_vars = mock_session.return_value.post.call_args.kwargs["json"]["variables"]
        assert (run_vars["project"], run_vars["after"]) == ("proj-a", None)
        assert [row["id"] for batch in batches for row in batch] == ["ra"]


class TestArtifactsEndpoint:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_rows_carry_parent_identifiers(self, mock_session):
        artifact_edge = {
            "version": "v3",
            "node": {"id": "art-1", "digest": "abc", "state": "COMMITTED", "createdAt": "2024-01-01T00:00:00Z"},
        }
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a"]),
            _connection_response(("project", "artifactTypes"), [{"node": {"name": "model"}}]),
            _connection_response(("project", "artifactType", "artifactCollections"), [{"node": {"name": "coll-1"}}]),
            _connection_response(("project", "artifactType", "artifactCollection", "artifacts"), [artifact_edge]),
        ]

        batches = list(get_rows("key", None, "acme", "artifacts", mock.MagicMock(), _make_manager()))

        rows = [row for batch in batches for row in batch]
        assert len(rows) == 1
        assert rows[0]["id"] == "art-1"
        assert rows[0]["version"] == "v3"
        assert rows[0]["projectName"] == "proj-a"
        assert rows[0]["artifactTypeName"] == "model"
        assert rows[0]["collectionName"] == "coll-1"

    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_artifact_type_deleted_mid_sync_is_skipped(self, mock_session):
        null_type_resp = _ok_response({"data": {"project": {"artifactType": None}}})
        mock_session.return_value.post.side_effect = [
            _projects_response(["proj-a"]),
            _connection_response(("project", "artifactTypes"), [{"node": {"name": "model"}}]),
            null_type_resp,
        ]

        batches = list(get_rows("key", None, "acme", "artifacts", mock.MagicMock(), _make_manager()))

        assert batches == []


class TestErrors:
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_graphql_error_raises(self, mock_session):
        mock_session.return_value.post.return_value = _ok_response({"errors": [{"message": "permission denied"}]})

        with pytest.raises(WeightsAndBiasesGraphQLError, match="permission denied"):
            list(get_rows("key", None, "acme", "projects", mock.MagicMock(), _make_manager()))

    def test_unknown_endpoint_raises(self):
        with pytest.raises(ValueError, match="Unknown Weights & Biases endpoint"):
            list(get_rows("key", None, "acme", "nope", mock.MagicMock(), _make_manager()))

    @mock.patch(f"{_MODULE}.MAX_RESPONSE_BYTES", 16)
    @mock.patch(f"{_MODULE}.make_tracked_session")
    def test_oversized_response_body_is_rejected(self, mock_session):
        # The host is customer-controlled; an unbounded body must not be buffered into a worker.
        oversized = mock.MagicMock()
        oversized.status_code = 200
        oversized.ok = True
        oversized.raw.read.return_value = b"x" * 17
        mock_session.return_value.post.return_value = oversized

        with pytest.raises(WeightsAndBiasesGraphQLError, match="oversized"):
            list(get_rows("key", None, "acme", "projects", mock.MagicMock(), _make_manager()))


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(ENDPOINTS))
    def test_response_metadata_per_endpoint(self, endpoint):
        response = weights_and_biases_source("key", None, "acme", endpoint, mock.MagicMock(), _make_manager())

        assert response.name == endpoint
        assert response.primary_keys == WANDB_ENDPOINTS[endpoint].primary_keys
        # Fan-out over projects means rows only ascend within one project — the watermark
        # commits at run end.
        assert response.sort_mode == "desc"
        assert response.partition_mode == "datetime"
        assert response.partition_keys == ["createdAt"]
