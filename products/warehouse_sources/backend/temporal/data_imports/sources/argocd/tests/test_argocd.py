import ssl
import json
from typing import Any

import pytest
from unittest import mock

import requests

from products.warehouse_sources.backend.temporal.data_imports.sources.argocd import argocd as argocd_module
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.argocd import (
    HOST_NOT_ALLOWED_ERROR,
    HTTPS_REQUIRED_ERROR,
    ArgocdHostNotAllowedError,
    ArgocdResponseTimeoutError,
    ArgocdResponseTooLargeError,
    _has_ambiguous_authority,
    _history_rows,
    _items,
    _list_params,
    _normalize_application,
    _normalize_cluster,
    _normalize_event,
    _normalize_managed_resource,
    _normalize_repository,
    _normalize_resource_node,
    _revision_requests,
    argocd_source,
    normalize_host,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.settings import ARGOCD_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.argocd.source import ArgocdSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.argocd import ArgocdSourceConfig

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
    if not response.ok:
        response.raise_for_status.side_effect = requests.HTTPError(
            f"{status_code} Client Error: for url: https://argocd.example.com", response=response
        )
    return response


def _patch_session(response: mock.MagicMock):
    session = mock.MagicMock()
    session.get.return_value = response
    return mock.patch.object(argocd_module, "make_tracked_session", return_value=session)


def _driver(host: str = "https://argocd.example.com", project: str | None = None) -> SourceDriver:
    return SourceDriver(ArgocdSource(), ArgocdSourceConfig(host=host, api_token="tok", project=project))


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


class TestAmbiguousAuthority:
    @pytest.mark.parametrize(
        "host, ambiguous",
        [
            ("https://argocd.example.com", False),
            ("https://argocd.example.com/api/v1", False),
            # Backslash + userinfo: urlparse says public.example, a `\`→`/` client says internal.
            ("https://internal.example\\@public.example", True),
            # Percent-encoded backslash hides the same trick from urlparse.
            ("https://internal.example%5c@public.example", True),
            # Plain userinfo is never valid for an Argo CD URL and muddies the authority.
            ("https://user@argocd.example.com", True),
        ],
    )
    def test_flags_parser_mismatches(self, host, ambiguous):
        assert _has_ambiguous_authority(host) is ambiguous


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
        # gcpServiceAccountKey carries a GCS service-account JSON — it must be stripped like the
        # other write-only credential fields in case a server version echoes it back.
        row = _normalize_repository(
            {
                "repo": "https://github.com/org/repo",
                "password": "x",
                "sshPrivateKey": "y",
                "gcpServiceAccountKey": "z",
            }
        )
        assert row == {"repo": "https://github.com/org/repo"}

    def test_event_lifts_identity_and_involved_object(self):
        row = _normalize_event(
            {
                "metadata": {"uid": "ev-1", "creationTimestamp": "2025-02-01T00:00:00Z"},
                "reason": "OperationCompleted",
                "message": "Sync operation to abc succeeded",
                "type": "Normal",
                "involvedObject": {"kind": "Application", "name": "guestbook", "namespace": "argocd"},
            }
        )
        assert row["uid"] == "ev-1"
        assert row["created_at"] == "2025-02-01T00:00:00Z"
        assert row["reason"] == "OperationCompleted"
        assert row["involved_object_name"] == "guestbook"

    @pytest.mark.parametrize(
        "normalize, item",
        [
            (_normalize_managed_resource, {"kind": "Namespace", "name": "web"}),
            (lambda item: _normalize_resource_node(item, orphaned=False), {"kind": "Namespace", "name": "web"}),
        ],
    )
    def test_key_columns_are_never_null(self, normalize, item):
        # group and namespace are absent for core-API and cluster-scoped resources, and both
        # are primary key columns.
        row = normalize(item)
        assert row["group"] == ""
        assert row["namespace"] == ""
        assert row["name"] == "web"

    def test_managed_resource_carries_live_and_target_state(self):
        row = _normalize_managed_resource(
            {
                "group": "apps",
                "kind": "Deployment",
                "namespace": "web",
                "name": "frontend",
                "modified": True,
                "liveState": '{"spec":{"replicas":3}}',
                "targetState": '{"spec":{"replicas":2}}',
                "normalizedLiveState": '{"spec":{"replicas":3}}',
                "predictedLiveState": '{"spec":{"replicas":2}}',
            }
        )
        assert row["modified"] is True
        assert row["live_state"] == '{"spec":{"replicas":3}}'
        assert row["target_state"] == '{"spec":{"replicas":2}}'

    def test_resource_node_lifts_health(self):
        row = _normalize_resource_node(
            {
                "kind": "Pod",
                "name": "frontend-abc",
                "namespace": "web",
                "uid": "pod-1",
                "health": {"status": "Degraded", "message": "back-off restarting"},
            },
            orphaned=False,
        )
        assert row["health_status"] == "Degraded"
        assert row["health_message"] == "back-off restarting"
        assert row["orphaned"] is False


class TestGetRows:
    def test_applications_yields_normalized_rows(self):
        result = _driver().run("applications", [ScriptedResponse(json={"items": [APPLICATION]})])

        assert [r["name"] for r in result.rows] == ["guestbook"]
        assert result.urls == ["https://argocd.example.com/api/v1/applications"]
        assert result.requests[0].headers["authorization"] == "Bearer tok"
        assert result.raised is None

    def test_project_scope_is_passed_as_query_params(self):
        result = _driver(project="team-a").run("applications", [ScriptedResponse(json={"items": []})])
        assert result.params("project") == ["team-a"]
        assert result.params("projects") == ["team-a"]

    def test_deployment_history_flattens_from_applications_endpoint(self):
        result = _driver().run("deployment_history", [ScriptedResponse(json={"items": [APPLICATION]})])

        assert [r["id"] for r in result.rows] == [1, 2]
        assert result.paths == ["/api/v1/applications"]

    def test_null_items_yields_nothing(self):
        result = _driver().run("applications", [ScriptedResponse(json={"items": None})])
        assert result.rows == []
        assert result.raised is None

    def test_rows_are_batched_without_loss(self):
        apps = [
            {"metadata": {"name": f"app-{i}", "namespace": "argocd", "uid": f"u{i}"}, "spec": {}, "status": {}}
            for i in range(5)
        ]
        with mock.patch.object(argocd_module, "_ROWS_PER_BATCH", 2):
            result = _driver().run("applications", [ScriptedResponse(json={"items": apps})])
        assert [len(batch) for batch in result.items] == [2, 2, 1]
        assert [row["name"] for row in result.rows] == [f"app-{i}" for i in range(5)]

    def test_http_host_is_rejected_before_any_request(self):
        result = _driver(host="http://argocd.internal").run("applications", [])
        assert isinstance(result.raised, ArgocdHostNotAllowedError)
        assert HTTPS_REQUIRED_ERROR in str(result.raised)
        assert result.requests == []

    def test_authority_parser_mismatch_is_rejected_before_any_request(self):
        # `urlparse` reads the host after `@` (public.example) while an HTTP client that folds
        # `\` into `/` reaches internal.example. The SSRF check must not be handed the wrong
        # host — the request must never be attempted.
        result = _driver(host="https://internal.example\\@public.example").run("applications", [])
        assert isinstance(result.raised, ArgocdHostNotAllowedError)
        assert result.requests == []

    def test_unsafe_host_is_rejected_before_any_request(self):
        with mock.patch.object(argocd_module, "_is_host_safe", return_value=(False, "internal address")):
            result = _driver(host="https://10.0.0.1").run("applications", [])
        assert isinstance(result.raised, ArgocdHostNotAllowedError)
        assert "internal address" in str(result.raised)
        assert result.requests == []

    def test_redirect_response_is_not_followed(self):
        # A redirect could point at an internal address; it must raise, not be parsed or followed.
        result = _driver().run("applications", [ScriptedResponse(status=302, headers={"Location": "http://10.0.0.1/"})])
        assert isinstance(result.raised, ArgocdHostNotAllowedError)
        assert "redirect" in str(result.raised)
        assert result.paths == ["/api/v1/applications"]

    def test_session_opts_out_of_sample_capture_and_redacts_token(self):
        # Raw cluster/repository responses carry credential fields the name-based sample
        # scrubbers can't recognise, so the session must be excluded from HTTP sample capture.
        result = _driver().run("clusters", [ScriptedResponse(json={"items": None})])
        assert result.session_options[0]["capture"] is False
        assert "tok" in result.session_options[0]["redact_values"]
        # `_fetch` owns the retry budget via tenacity; the adapter must not retry underneath it,
        # or a stalling host could hold a worker for adapter × tenacity × timeout.
        assert result.session_options[0]["retry"].total == 0

    def test_oversized_response_aborts_instead_of_buffering(self):
        # The host is customer-controlled: a response bigger than the byte cap must fail the
        # sync rather than being buffered into worker memory.
        with mock.patch.object(argocd_module, "MAX_RESPONSE_BYTES", 1024 * 1024):
            result = _driver().run("applications", [ScriptedResponse(body=b"x" * (1024 * 1024 + 1))])
        assert isinstance(result.raised, ArgocdResponseTooLargeError)

    def test_slow_drip_response_aborts_on_total_deadline(self):
        # A body that stays under the byte cap and never trips the per-read timeout but keeps
        # dripping past the total transfer budget must fail the sync, not hold the worker.
        slow = mock.MagicMock()
        slow.iter_content = mock.Mock(return_value=iter([b"x", b"x", b"x"]))
        # First call sets the deadline; the next read is already past it. Patched on the
        # module's time reference so real elapsed time doesn't make the test flaky.
        monotonic = mock.Mock(side_effect=[0.0, 601.0])
        with (
            mock.patch.object(argocd_module.time, "monotonic", monotonic),
            pytest.raises(ArgocdResponseTimeoutError),
        ):
            argocd_module._read_bounded(slow, max_bytes=1_000, max_seconds=600)


MULTI_SOURCE_APPLICATION = {
    "metadata": {"name": "multi", "namespace": "team-ns", "uid": "uid-2"},
    "spec": {"project": "team-a"},
    "status": {
        "history": [
            {
                "id": 1,
                "revisions": ["sha-old", "1.2.3"],
                "sources": [{"repoURL": "https://github.com/org/repo"}, {"chart": "nginx"}],
            },
            {
                "id": 2,
                "revisions": ["sha-new", "1.2.4"],
                "sources": [{"repoURL": "https://github.com/org/repo"}, {"chart": "nginx"}],
            },
        ]
    },
}


class TestRevisionRequests:
    @pytest.mark.parametrize(
        "app, expected",
        [
            # The metadata endpoint resolves git commits through the repo server. A Helm chart
            # version is not one, so source index 1 of the multi-source app is never requested.
            (MULTI_SOURCE_APPLICATION, [("sha-new", 0), ("sha-old", 0)]),
            # Newest first, so the cap keeps the recent revisions.
            (APPLICATION, [("def", 0), ("abc", 0)]),
            # A revision deployed twice is resolved once.
            ({"status": {"history": [{"revision": "abc"}, {"revision": "abc"}]}}, [("abc", 0)]),
            ({"metadata": {"name": "new-app"}, "status": {}}, []),
        ],
    )
    def test_revisions_to_resolve(self, app, expected):
        assert _revision_requests(app) == expected

    def test_cap_keeps_the_most_recent_revisions(self):
        app = {"status": {"history": [{"revision": f"sha-{i}"} for i in range(10)]}}
        with mock.patch.object(argocd_module, "MAX_REVISIONS_PER_APPLICATION", 3):
            assert _revision_requests(app) == [("sha-9", 0), ("sha-8", 0), ("sha-7", 0)]


class TestFanOut:
    def test_events_are_fetched_per_application_with_parent_scope(self):
        events = {"items": [{"metadata": {"uid": "ev-1"}, "reason": "ResourceUpdated"}]}
        result = _driver().run(
            "application_events",
            [ScriptedResponse(json={"items": [APPLICATION]}), ScriptedResponse(json=events)],
        )

        assert [row["uid"] for row in result.rows] == ["ev-1"]
        assert result.rows[0]["application_name"] == "guestbook"
        assert result.rows[0]["application_namespace"] == "argocd"
        # The namespace and project come from the application that was walked, not from the
        # source's optional project filter, because the name alone is ambiguous across
        # namespaces.
        child = result.requests[1]
        assert child.origin == "https://argocd.example.com"
        assert child.path == "/api/v1/applications/guestbook/events"
        assert child.param("appNamespace") == "argocd"
        assert child.param("project") == "default"

    def test_application_name_is_url_quoted_in_the_path(self):
        app = {"metadata": {"name": "team/app one", "namespace": "argocd"}, "spec": {}, "status": {}}
        result = _driver().run(
            "resource_tree",
            [ScriptedResponse(json={"items": [app]}), ScriptedResponse(json={"nodes": []})],
        )
        assert result.requests[1].origin == "https://argocd.example.com"
        assert result.paths[1] == "/api/v1/applications/team%2Fapp%20one/resource-tree"

    def test_revision_metadata_requests_each_revision_with_its_source_index(self):
        result = _driver().run(
            "revision_metadata",
            [
                ScriptedResponse(json={"items": [MULTI_SOURCE_APPLICATION]}),
                ScriptedResponse(json={"author": "Jane <jane@example.com>", "message": "ship it"}),
                ScriptedResponse(json={"author": "Jane <jane@example.com>", "message": "ship it"}),
            ],
        )

        assert [row["revision"] for row in result.rows] == ["sha-new", "sha-old"]
        assert result.rows[0]["author"] == "Jane <jane@example.com>"
        assert result.rows[0]["source_index"] == 0
        assert result.rows[0]["application_name"] == "multi"
        assert result.requests[1].origin == "https://argocd.example.com"
        assert result.paths[1:] == [
            "/api/v1/applications/multi/revisions/sha-new/metadata",
            "/api/v1/applications/multi/revisions/sha-old/metadata",
        ]
        assert result.params("sourceIndex")[1:] == ["0", "0"]

    def test_resource_tree_flattens_managed_and_orphaned_nodes(self):
        tree = {
            "nodes": [{"kind": "Pod", "name": "frontend-abc", "namespace": "web", "uid": "pod-1"}],
            "orphanedNodes": [{"kind": "ConfigMap", "name": "left-over", "namespace": "web", "uid": "cm-1"}],
        }
        result = _driver().run(
            "resource_tree",
            [ScriptedResponse(json={"items": [APPLICATION]}), ScriptedResponse(json=tree)],
        )

        assert [(row["name"], row["orphaned"]) for row in result.rows] == [
            ("frontend-abc", False),
            ("left-over", True),
        ]

    def test_empty_resource_tree_yields_nothing(self):
        # An application with no cached tree marshals both node arrays as null.
        result = _driver().run(
            "resource_tree",
            [
                ScriptedResponse(json={"items": [APPLICATION]}),
                ScriptedResponse(json={"nodes": None, "orphanedNodes": None}),
            ],
        )
        assert result.rows == []
        assert result.raised is None

    def test_managed_resources_are_batched_smaller_than_other_endpoints(self):
        # Each row carries the resource's full manifests, so the batch size must be the
        # managed-resource one rather than the shared default.
        items = [{"kind": "Pod", "name": f"pod-{i}", "namespace": "web"} for i in range(5)]
        with (
            mock.patch.object(argocd_module, "_MANAGED_RESOURCE_ROWS_PER_BATCH", 2),
            mock.patch.object(argocd_module, "_ROWS_PER_BATCH", 1000),
        ):
            result = _driver().run(
                "managed_resources",
                [ScriptedResponse(json={"items": [APPLICATION]}), ScriptedResponse(json={"items": items})],
            )
        assert [len(batch) for batch in result.items] == [2, 2, 1]

    def test_parent_walk_honours_the_project_filter(self):
        result = _driver(project="team-a").run(
            "application_events",
            [ScriptedResponse(json={"items": []})],
        )
        assert result.requests[0].param("projects") == "team-a"

    def test_application_walk_is_capped(self):
        apps = [{"metadata": {"name": f"app-{i}", "namespace": "argocd"}, "spec": {}, "status": {}} for i in range(4)]
        logger = mock.MagicMock()
        with mock.patch.object(argocd_module, "MAX_FAN_OUT_APPLICATIONS", 2):
            result = _driver().run(
                "resource_tree",
                [
                    ScriptedResponse(json={"items": apps}),
                    ScriptedResponse(json={"nodes": []}),
                    ScriptedResponse(json={"nodes": []}),
                ],
                logger=logger,
            )
        assert result.paths == [
            "/api/v1/applications",
            "/api/v1/applications/app-0/resource-tree",
            "/api/v1/applications/app-1/resource-tree",
        ]
        logger.warning.assert_called_once()

    def test_walk_stops_at_its_time_budget(self):
        # Per-request limits reset on the next request, so without a budget for the walk a slow
        # host holds an import worker for one request per application. A budget already spent
        # stops the walk, so no application is requested.
        apps = [{"metadata": {"name": f"app-{i}", "namespace": "argocd"}, "spec": {}, "status": {}} for i in range(4)]
        logger = mock.MagicMock()
        with mock.patch.object(argocd_module, "MAX_FAN_OUT_SECONDS", -1):
            result = _driver().run("resource_tree", [ScriptedResponse(json={"items": apps})], logger=logger)
        assert result.paths == ["/api/v1/applications"]
        logger.warning.assert_called_once()

    @pytest.mark.parametrize(
        "endpoint, fragment, json_data",
        [
            ("application_events", "/events", {"items": [{"metadata": {"uid": "ev-1"}}]}),
            ("revision_metadata", "/revisions/", {"author": "Jane"}),
            ("managed_resources", "/managed-resources", {"items": [{"kind": "Pod", "name": "frontend"}]}),
            ("resource_tree", "/resource-tree", {"nodes": [{"kind": "Pod", "name": "frontend"}]}),
        ],
    )
    def test_every_row_carries_its_primary_key_columns(self, endpoint, fragment, json_data):
        # A key column missing from a normalized row makes the Delta merge match on null, so
        # the rows duplicate on every sync.
        child_responses = [ScriptedResponse(json=json_data)] * (2 if endpoint == "revision_metadata" else 1)
        result = _driver().run(
            endpoint,
            [ScriptedResponse(json={"items": [APPLICATION]}), *child_responses],
        )
        assert fragment in result.urls[1]
        assert result.rows
        assert result.raised is None
        for row in result.rows:
            for key in ARGOCD_ENDPOINTS[endpoint].primary_keys:
                assert row.get(key) is not None

    @pytest.mark.parametrize("status_code", [400, 404, 500])
    def test_one_broken_application_is_skipped_not_fatal(self, status_code):
        # Argo CD reports a deleted application, an uncomparable spec and an unresolvable
        # revision as 404/500 for that one application. The rest of the table must still sync.
        apps = [
            {"metadata": {"name": "broken", "namespace": "argocd"}, "spec": {}, "status": {}},
            {"metadata": {"name": "healthy", "namespace": "argocd"}, "spec": {}, "status": {}},
        ]
        logger = mock.MagicMock()
        responses = [
            ScriptedResponse(json={"items": apps}),
            ScriptedResponse(status=status_code),
            ScriptedResponse(json={"nodes": [{"kind": "Pod", "name": "p", "namespace": "web"}]}),
        ]
        with mock.patch.object(argocd_module, "MAX_CHILD_RETRIES", 1):
            result = _driver().run("resource_tree", responses, logger=logger)

        assert [row["application_name"] for row in result.rows] == ["healthy"]
        assert result.paths == [
            "/api/v1/applications",
            "/api/v1/applications/broken/resource-tree",
            "/api/v1/applications/healthy/resource-tree",
        ]
        assert result.raised is None
        logger.warning.assert_called_once()

    @pytest.mark.parametrize("status_code", [401, 403])
    def test_rejected_token_fails_the_sync(self, status_code):
        # A skipped application must not hide a token that the server no longer accepts.
        with mock.patch.object(argocd_module, "MAX_CHILD_RETRIES", 1):
            result = _driver().run(
                "resource_tree",
                [ScriptedResponse(json={"items": [APPLICATION]}), ScriptedResponse(status=status_code)],
            )
        assert isinstance(result.raised, requests.HTTPError)


class TestValidateCredentials:
    def test_success_without_reading_the_body(self):
        # The probe runs inline on the API thread; on success it must decide from the status
        # alone — ingesting the body would let a huge response buffer into memory.
        ok = _response(json_data={"items": None})
        with _patch_session(ok):
            assert validate_credentials("https://argocd.example.com", "tok") == (True, None)
        ok.iter_content.assert_not_called()

    def test_probe_url_uses_name_filter_for_applications(self):
        with scripted_network([ScriptedResponse(json={"items": None})]) as network:
            validate_credentials("https://argocd.example.com", "tok", schema_name="applications")
        assert network.requests_log[0].origin == "https://argocd.example.com"
        assert network.requests_log[0].path == "/api/v1/applications"
        assert network.requests_log[0].param("name") == "posthog-connectivity-probe"

    def test_probe_url_for_projects_hits_projects_path(self):
        with scripted_network([ScriptedResponse(json={"items": None})]) as network:
            validate_credentials("https://argocd.example.com", "tok", schema_name="projects")
        assert [request.url for request in network.requests_log] == ["https://argocd.example.com/api/v1/projects"]

    @pytest.mark.parametrize(
        "schema_name", ["application_events", "revision_metadata", "managed_resources", "resource_tree"]
    )
    def test_per_application_schema_probes_the_applications_list(self, schema_name):
        # These paths need an application name, so the probe cannot request them directly.
        # They are reached by walking the applications list and need the same permission.
        with scripted_network([ScriptedResponse(json={"items": None})]) as network:
            assert validate_credentials("https://argocd.example.com", "tok", schema_name=schema_name) == (True, None)
        assert network.requests_log[0].origin == "https://argocd.example.com"
        assert network.requests_log[0].path == "/api/v1/applications"
        assert network.requests_log[0].param("name") == "posthog-connectivity-probe"

    def test_authority_parser_mismatch_is_rejected_without_probing(self):
        # The probe must not be sent to a host the SSRF check never validated.
        with scripted_network([]) as network:
            valid, _msg = validate_credentials("https://internal.example\\@public.example", "tok", team_id=1)
            assert valid is False
        assert network.requests_log == []

    def test_403_at_source_create_is_accepted(self):
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials("https://argocd.example.com", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials("https://argocd.example.com", "tok", schema_name="clusters")
            assert valid is False
            assert "clusters" in (msg or "")

    @pytest.mark.parametrize("status_code", [429, 503])
    def test_transient_errors_are_not_reported_as_bad_credentials(self, status_code):
        with scripted_network([ScriptedResponse(status=status_code)]):
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert "temporarily unavailable" in (msg or "")

    def test_unexpected_status_surfaces_api_message(self):
        with scripted_network([ScriptedResponse(status=400, json={"message": "bad request", "error": "bad"})]):
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
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("https://10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
            assert network.requests_log == []

    def test_rejects_redirect_response(self):
        with scripted_network([ScriptedResponse(status=302, headers={"Location": "http://10.0.0.1/"})]) as network:
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert msg == HOST_NOT_ALLOWED_ERROR
            assert [request.path for request in network.requests_log] == ["/api/v1/applications"]

    def test_ssl_error_gets_actionable_message(self):
        with scripted_network([ssl.SSLError("self signed certificate")]):
            valid, msg = validate_credentials("https://argocd.example.com", "tok")
            assert valid is False
            assert "certificate" in (msg or "")

    def test_session_opts_out_of_sample_capture_and_redacts_token(self):
        with scripted_network([ScriptedResponse(json={"items": None})]) as network:
            validate_credentials("https://argocd.example.com", "tok")
        assert network.session_options[0]["capture"] is False
        assert "tok" in network.session_options[0]["redact_values"]
        # The probe runs inline on an API worker and takes a single attempt — adapter retries
        # would let a stalling host hold the worker across several timeouts.
        assert network.session_options[0]["retry"].total == 0


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
