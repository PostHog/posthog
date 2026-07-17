import json
from typing import Any, Optional

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.argocd import argocd as argocd_module
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.argocd import (
    HOST_NOT_ALLOWED_ERROR,
    HTTPS_REQUIRED_ERROR,
    ArgocdHostNotAllowedError,
    ArgocdResponseTooLargeError,
    _history_rows,
    _items,
    _list_params,
    _normalize_application,
    _normalize_cluster,
    _normalize_repository,
    argocd_source,
    get_rows,
    normalize_host,
    validate_credentials,
)

APPLICATION = {
    "metadata": {
        "name": "guestbook",
        "namespace": "argocd",
        "uid": "uid-1",
        "creationTimestamp": "2025-01-01T00:00:00Z",
    },
    "spec": {"project": "default", "source": {"repoURL": "https://github.com/org/repo"}},
    "status": {
        "sync": {"status": "Synced"},
        "health": {"status": "Healthy"},
        "history": [
            {"id": 1, "revision": "abc", "deployedAt": "2025-01-02T00:00:00Z", "deployStartedAt": None},
            {"id": 2, "revision": "def", "deployedAt": "2025-01-03T00:00:00Z", "initiatedBy": {"username": "jane"}},
        ],
    },
}


def _response(*, status_code: int = 200, json_data: Any = None, text: str = "") -> mock.MagicMock:
    response = mock.MagicMock()
    response.status_code = status_code
    response.ok = 200 <= status_code < 400
    response.is_redirect = status_code in (302, 303, 307)
    response.is_permanent_redirect = status_code in (301, 308)
    response.headers = {}
    # Bodies are streamed and read through iter_content, never .text / .json().
    body = json.dumps(json_data).encode() if json_data is not None else text.encode()
    response.iter_content = mock.Mock(side_effect=lambda chunk_size: iter([body] if body else []))
    response.__enter__ = mock.Mock(return_value=response)
    response.__exit__ = mock.Mock(return_value=False)
    return response


def _patch_session(response: Optional[mock.MagicMock] = None, raises: Optional[Exception] = None):
    session = mock.MagicMock()
    if raises is not None:
        session.get.side_effect = raises
    else:
        session.get.return_value = response
    return mock.patch.object(argocd_module, "make_tracked_session", return_value=session)


class TestNormalizeHost:
    @pytest.mark.parametrize(
        "raw, expected",
        [
            ("argocd.example.com", "https://argocd.example.com"),
            ("https://argocd.example.com/", "https://argocd.example.com"),
            ("  https://argocd.example.com  ", "https://argocd.example.com"),
            ("https://argocd.example.com/api/v1", "https://argocd.example.com"),
            # A sub-path deployment (server --rootpath) must be preserved.
            ("https://example.com/argocd", "https://example.com/argocd"),
            ("http://argocd.internal", "http://argocd.internal"),
            ("", ""),
            (None, ""),
        ],
    )
    def test_normalize_host(self, raw, expected):
        assert normalize_host(raw) == expected


class TestListParams:
    @pytest.mark.parametrize("endpoint", ["applications", "deployment_history"])
    def test_project_scoping_sends_both_param_spellings(self, endpoint):
        params = _list_params(endpoint, "team-a")
        assert params == {"project": "team-a", "projects": "team-a"}

    @pytest.mark.parametrize("endpoint", ["projects", "repositories", "clusters"])
    def test_project_scoping_not_applied_to_other_endpoints(self, endpoint):
        assert _list_params(endpoint, "team-a") == {}

    @pytest.mark.parametrize("project", [None, ""])
    def test_no_project_no_params(self, project):
        assert _list_params("applications", project) == {}


class TestItems:
    @pytest.mark.parametrize(
        "data, expected",
        [
            ({"items": [{"a": 1}]}, [{"a": 1}]),
            # Kubernetes-style lists marshal an empty collection as null, not [].
            ({"items": None}, []),
            ({}, []),
            (None, []),
            ([], []),
        ],
    )
    def test_items(self, data, expected):
        assert _items(data) == expected


class TestNormalization:
    def test_application_lifts_identity_and_status_columns(self):
        row = _normalize_application(APPLICATION)
        assert row["name"] == "guestbook"
        assert row["namespace"] == "argocd"
        assert row["uid"] == "uid-1"
        assert row["created_at"] == "2025-01-01T00:00:00Z"
        assert row["project"] == "default"
        assert row["sync_status"] == "Synced"
        assert row["health_status"] == "Healthy"
        assert row["spec"] == APPLICATION["spec"]

    def test_application_with_missing_status_does_not_raise(self):
        row = _normalize_application({"metadata": {"name": "bare"}})
        assert row["name"] == "bare"
        assert row["sync_status"] is None
        assert row["health_status"] is None

    def test_history_rows_carry_parent_identity(self):
        rows = _history_rows(APPLICATION)
        assert len(rows) == 2
        for row in rows:
            assert row["application_name"] == "guestbook"
            assert row["application_namespace"] == "argocd"
            assert row["project"] == "default"
        assert rows[0]["id"] == 1
        assert rows[0]["revision"] == "abc"
        assert rows[0]["deployed_at"] == "2025-01-02T00:00:00Z"
        assert rows[1]["initiated_by"] == {"username": "jane"}

    def test_history_rows_empty_when_no_history(self):
        assert _history_rows({"metadata": {"name": "new-app"}, "status": {}}) == []

    def test_cluster_config_is_dropped(self):
        # `config` carries the cluster's connection credentials and must never reach the warehouse.
        row = _normalize_cluster({"server": "https://k8s.example.com", "name": "prod", "config": {"bearerToken": "s"}})
        assert "config" not in row
        assert row["server"] == "https://k8s.example.com"

    def test_repository_secret_fields_are_dropped(self):
        row = _normalize_repository({"repo": "https://github.com/org/repo", "password": "x", "sshPrivateKey": "y"})
        assert row == {"repo": "https://github.com/org/repo"}


class TestGetRows:
    def _run(self, endpoint: str, response: mock.MagicMock, host: str = "https://argocd.example.com", **kwargs: Any):
        with _patch_session(response) as patched:
            rows: list[dict[str, Any]] = []
            for batch in get_rows(
                host=host, api_token="tok", endpoint=endpoint, team_id=1, logger=mock.MagicMock(), **kwargs
            ):
                rows.extend(batch)
        return rows, patched.return_value

    def test_applications_yields_normalized_rows(self):
        rows, session = self._run("applications", _response(json_data={"items": [APPLICATION]}))

        assert [r["name"] for r in rows] == ["guestbook"]
        url = session.get.call_args.args[0]
        assert url == "https://argocd.example.com/api/v1/applications"
        assert session.get.call_args.kwargs["headers"]["Authorization"] == "Bearer tok"
        assert session.get.call_args.kwargs["allow_redirects"] is False

    def test_project_scope_is_passed_as_query_params(self):
        _rows, session = self._run("applications", _response(json_data={"items": []}), project="team-a")
        url = session.get.call_args.args[0]
        assert "project=team-a" in url
        assert "projects=team-a" in url

    def test_deployment_history_flattens_from_applications_endpoint(self):
        rows, session = self._run("deployment_history", _response(json_data={"items": [APPLICATION]}))

        assert [r["id"] for r in rows] == [1, 2]
        assert session.get.call_args.args[0] == "https://argocd.example.com/api/v1/applications"

    def test_null_items_yields_nothing(self):
        rows, _session = self._run("applications", _response(json_data={"items": None}))
        assert rows == []

    def test_rows_are_batched_without_loss(self):
        apps = [
            {"metadata": {"name": f"app-{i}", "namespace": "argocd", "uid": f"u{i}"}, "spec": {}, "status": {}}
            for i in range(5)
        ]
        with (
            mock.patch.object(argocd_module, "_ROWS_PER_BATCH", 2),
            _patch_session(_response(json_data={"items": apps})),
        ):
            batches = list(
                get_rows(
                    host="https://argocd.example.com",
                    api_token="tok",
                    endpoint="applications",
                    team_id=1,
                    logger=mock.MagicMock(),
                )
            )
        assert [len(b) for b in batches] == [2, 2, 1]
        assert [r["name"] for b in batches for r in b] == [f"app-{i}" for i in range(5)]

    def test_http_host_is_rejected_before_any_request(self):
        with _patch_session(_response(json_data={"items": []})) as patched:
            with pytest.raises(ArgocdHostNotAllowedError, match=HTTPS_REQUIRED_ERROR):
                list(
                    get_rows(
                        host="http://argocd.internal",
                        api_token="tok",
                        endpoint="applications",
                        team_id=1,
                        logger=mock.MagicMock(),
                    )
                )
            patched.return_value.get.assert_not_called()

    def test_unsafe_host_is_rejected_before_any_request(self):
        with (
            mock.patch.object(argocd_module, "_is_host_safe", return_value=(False, "internal address")),
            _patch_session(_response(json_data={"items": []})) as patched,
        ):
            with pytest.raises(ArgocdHostNotAllowedError, match="internal address"):
                list(
                    get_rows(
                        host="https://10.0.0.1",
                        api_token="tok",
                        endpoint="applications",
                        team_id=1,
                        logger=mock.MagicMock(),
                    )
                )
            patched.return_value.get.assert_not_called()

    def test_redirect_response_is_not_followed(self):
        # A redirect could point at an internal address; it must raise, not be parsed or followed.
        with pytest.raises(ArgocdHostNotAllowedError, match="redirect"):
            self._run("applications", _response(status_code=302))

    def test_session_opts_out_of_sample_capture_and_redacts_token(self):
        # Raw cluster/repository responses carry credential fields the name-based sample
        # scrubbers can't recognise, so the session must be excluded from HTTP sample capture.
        with _patch_session(_response(json_data={"items": None})) as patched:
            list(
                get_rows(
                    host="https://argocd.example.com",
                    api_token="tok",
                    endpoint="clusters",
                    team_id=1,
                    logger=mock.MagicMock(),
                )
            )
        assert patched.call_args.kwargs["capture"] is False
        assert "tok" in patched.call_args.kwargs["redact_values"]

    def test_oversized_response_aborts_instead_of_buffering(self):
        # The host is customer-controlled: a response bigger than the byte cap must fail the
        # sync rather than being buffered into worker memory.
        big = _response()
        big.iter_content = mock.Mock(return_value=iter([b"x" * 10, b"x" * 10]))
        with (
            mock.patch.object(argocd_module, "MAX_RESPONSE_BYTES", 15),
            _patch_session(big),
            pytest.raises(ArgocdResponseTooLargeError),
        ):
            list(
                get_rows(
                    host="https://argocd.example.com",
                    api_token="tok",
                    endpoint="applications",
                    team_id=1,
                    logger=mock.MagicMock(),
                )
            )


class TestValidateCredentials:
    def test_success_without_reading_the_body(self):
        # The probe runs inline on the API thread; on success it must decide from the status
        # alone — ingesting the body would let a huge response buffer into memory.
        ok = _response(json_data={"items": None})
        with _patch_session(ok):
            assert validate_credentials("https://argocd.example.com", "tok") == (True, None)
        ok.iter_content.assert_not_called()

    def test_probe_url_uses_name_filter_for_applications(self):
        with _patch_session(_response(json_data={"items": None})) as patched:
            validate_credentials("https://argocd.example.com", "tok", schema_name="applications")
        url = patched.return_value.get.call_args.args[0]
        assert url.startswith("https://argocd.example.com/api/v1/applications?")
        assert "name=posthog-connectivity-probe" in url

    def test_probe_url_for_projects_hits_projects_path(self):
        with _patch_session(_response(json_data={"items": None})) as patched:
            validate_credentials("https://argocd.example.com", "tok", schema_name="projects")
        url = patched.return_value.get.call_args.args[0]
        assert url == "https://argocd.example.com/api/v1/projects"

    def test_invalid_token(self):
        with _patch_session(_response(status_code=401)):
            assert validate_credentials("https://argocd.example.com", "tok") == (False, "Invalid Argo CD API token")

    def test_403_at_source_create_is_accepted(self):
        with _patch_session(_response(status_code=403)):
            assert validate_credentials("https://argocd.example.com", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with _patch_session(_response(status_code=403)):
            valid, msg = validate_credentials("https://argocd.example.com", "tok", schema_name="clusters")
            assert valid is False
            assert "clusters" in (msg or "")

    @pytest.mark.parametrize("status_code", [429, 500, 503])
    def test_transient_errors_are_not_reported_as_bad_credentials(self, status_code):
        with _patch_session(_response(status_code=status_code)):
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert "temporarily unavailable" in (msg or "")

    def test_unexpected_status_surfaces_api_message(self):
        with _patch_session(_response(status_code=400, json_data={"message": "bad request", "error": "bad"})):
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert msg == "bad request"

    @pytest.mark.parametrize("bad_host", ["", "   ", "https://"])
    def test_invalid_host_short_circuits(self, bad_host):
        valid, msg = validate_credentials(bad_host, "tok")
        assert valid is False
        assert msg == "Invalid Argo CD host"

    def test_http_host_is_rejected(self):
        valid, msg = validate_credentials("http://argocd.internal", "tok")
        assert valid is False
        assert msg == HTTPS_REQUIRED_ERROR

    def test_blocks_unsafe_host_before_any_request(self):
        with (
            mock.patch.object(argocd_module, "_is_host_safe", return_value=(False, "internal address")),
            _patch_session(_response(status_code=200)) as patched,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            patched.return_value.get.assert_not_called()

    def test_rejects_redirect_response(self):
        with _patch_session(_response(status_code=302)) as patched:
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert patched.return_value.get.call_args.kwargs["allow_redirects"] is False

    def test_ssl_error_gets_actionable_message(self):
        import requests

        with _patch_session(raises=requests.exceptions.SSLError("self signed certificate")):
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert "certificate" in (msg or "")

    def test_connection_error_returns_failure(self):
        import requests

        with _patch_session(raises=requests.exceptions.ConnectionError("boom")):
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert "boom" in (msg or "")

    def test_session_opts_out_of_sample_capture_and_redacts_token(self):
        with _patch_session(_response(json_data={"items": None})) as patched:
            validate_credentials("https://argocd.example.com", "tok")
        assert patched.call_args.kwargs["capture"] is False
        assert "tok" in patched.call_args.kwargs["redact_values"]


class TestArgocdSourceResponse:
    @pytest.mark.parametrize(
        "endpoint, primary_keys, partition_key",
        [
            ("applications", ["namespace", "name"], "created_at"),
            ("deployment_history", ["application_namespace", "application_name", "id"], "deployed_at"),
            ("projects", ["name"], "created_at"),
            ("repositories", ["repo"], None),
            ("clusters", ["server"], None),
        ],
    )
    def test_response_shape(self, endpoint, primary_keys, partition_key):
        response = argocd_source(
            host="https://argocd.example.com",
            api_token="tok",
            endpoint=endpoint,
            team_id=1,
            logger=mock.MagicMock(),
        )
        assert response.name == endpoint
        assert response.primary_keys == primary_keys
        if partition_key:
            assert response.partition_keys == [partition_key]
            assert response.partition_mode == "datetime"
        else:
            assert response.partition_keys is None
            assert response.partition_mode is None
