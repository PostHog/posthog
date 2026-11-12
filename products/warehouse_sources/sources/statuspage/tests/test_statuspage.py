from typing import Any, cast

import pytest
from unittest import mock

import requests

from products.warehouse_sources.sources.sdk import RESTClientRetryableError
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, always, route
from products.warehouse_sources.sources.statuspage._config import StatuspageSourceConfig
from products.warehouse_sources.sources.statuspage.settings import STATUSPAGE_ENDPOINTS
from products.warehouse_sources.sources.statuspage.source import StatuspageSource
from products.warehouse_sources.sources.statuspage.statuspage import StatuspageAuth, StatuspageResumeConfig


def _ok(body: Any) -> ScriptedResponse:
    return ScriptedResponse(json=body)


def _driver() -> SourceDriver:
    return SourceDriver(StatuspageSource(), StatuspageSourceConfig(api_key="key"))


class TestAuth:
    def test_sends_static_oauth_prefixed_key(self):
        request = mock.MagicMock()
        request.headers = {}
        StatuspageAuth("abc123")(request)
        # Statuspage's static API key is sent with an "OAuth" prefix despite not being an OAuth token.
        assert request.headers["Authorization"] == "OAuth abc123"

    def test_key_is_declared_as_a_redactable_secret(self):
        # The key must reach the client's redaction set so it's scrubbed from errors and log samples.
        assert StatuspageAuth("abc123").secret_values() == ("abc123",)


class TestTopLevelPagination:
    def test_paginates_pages_until_empty(self):
        result = _driver().run("pages", [_ok([{"id": "p1"}, {"id": "p2"}]), _ok([{"id": "p3"}]), _ok([])])

        assert [r["id"] for r in result.rows] == ["p1", "p2", "p3"]
        assert result.params("page") == ["1", "2", "3"]
        assert result.requests[0].param("per_page") == "100"
        # Checkpoint saved once per non-empty yielded page (each points at the NEXT page); the empty
        # third page ends the walk without a checkpoint.
        assert [s.paginator_state for s in result.saved_states] == [{"page": 2}, {"page": 3}]


class TestFanOut:
    def test_fans_out_over_pages_and_injects_page_id(self):
        result = _driver().run(
            "components",
            [
                _ok([{"id": "p1"}, {"id": "p2"}]),  # /pages page 1
                _ok([{"id": "c1"}]),  # p1 components page 1
                _ok([]),  # p1 components page 2 (empty)
                _ok([{"id": "c2"}]),  # p2 components page 1
                _ok([]),  # p2 components page 2 (empty)
                _ok([]),  # /pages page 2 (empty, ends parent walk)
            ],
        )

        # Each child row carries its parent page id under page_id — unique table-wide.
        assert result.rows == [{"id": "c1", "page_id": "p1"}, {"id": "c2", "page_id": "p2"}]
        child_paths = [path for path in result.paths if path.endswith("/components")]
        assert child_paths[0] == "/v1/pages/p1/components"
        assert child_paths[2] == "/v1/pages/p2/components"


class TestChainedFanOut:
    @pytest.mark.parametrize(
        "endpoint, middle_path, uptime_path",
        [
            ("component_uptime", "/pages/p1/components", "/pages/p1/components/{id}/uptime"),
            ("component_group_uptime", "/pages/p1/component-groups", "/pages/p1/component-groups/{id}/uptime"),
        ],
    )
    def test_uptime_reads_one_object_per_row_and_skips_unprocessable(self, endpoint, middle_path, uptime_path):
        middle_rows = [
            {"id": "a", "page_id": "p1", "showcase": True, "group": False},
            {"id": "b", "page_id": "p1", "showcase": True, "group": False},
        ]
        result = _driver().run(
            endpoint,
            route(
                {
                    "/v1/pages": [_ok([{"id": "p1"}]), _ok([])],
                    middle_path: [_ok(middle_rows), _ok([])],
                    uptime_path.format(id="a"): [_ok({"id": "a", "uptime_percentage": 99.5, "major_outage": 60})],
                    # No uptime showcase: the vendor answers 422, which must not fail the sync.
                    uptime_path.format(id="b"): [ScriptedResponse(status=422, json={"error": "showcase disabled"})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [{"id": "a", "uptime_percentage": 99.5, "major_outage": 60, "page_id": "p1"}]
        # The single-object endpoint is not paged: one request per row.
        assert [p for p in result.paths if p.endswith("/uptime")] == [
            f"/v1{uptime_path.format(id='a')}",
            f"/v1{uptime_path.format(id='b')}",
        ]

    def test_component_uptime_skips_components_without_showcase_and_groups(self):
        result = _driver().run(
            "component_uptime",
            route(
                {
                    "/v1/pages": [_ok([{"id": "p1"}]), _ok([])],
                    "/pages/p1/components": [
                        _ok(
                            [
                                {"id": "shown", "page_id": "p1", "showcase": True, "group": False},
                                {"id": "hidden", "page_id": "p1", "showcase": False, "group": False},
                                {"id": "grp", "page_id": "p1", "showcase": True, "group": True},
                            ]
                        ),
                        _ok([]),
                    ],
                    "/pages/p1/components/shown/uptime": [_ok({"id": "shown", "uptime_percentage": 100.0})],
                }
            ),
        )

        assert result.raised is None
        assert [p for p in result.paths if p.endswith("/uptime")] == ["/v1/pages/p1/components/shown/uptime"]
        assert result.rows == [{"id": "shown", "uptime_percentage": 100.0, "page_id": "p1"}]

    def test_page_access_user_components_pages_each_user_and_keys_on_the_user(self):
        result = _driver().run(
            "page_access_user_components",
            route(
                {
                    "/v1/pages": [_ok([{"id": "p1"}, {"id": "p2"}]), _ok([])],
                    "/pages/p1/page_access_users": [_ok([{"id": "u1", "page_id": "p1"}]), _ok([])],
                    "/pages/p2/page_access_users": [_ok([{"id": "u2", "page_id": "p2"}]), _ok([])],
                    "/pages/p1/page_access_users/u1/components": [
                        _ok([{"id": "c1", "page_id": "p1"}]),
                        _ok([{"id": "c2", "page_id": "p1"}]),
                        _ok([]),
                    ],
                    # The user was removed after the listing: a 404 means no rows, not a failed sync.
                    "/pages/p2/page_access_users/u2/components": [ScriptedResponse(status=404, json={})],
                }
            ),
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "c1", "page_id": "p1", "page_access_user_id": "u1"},
            {"id": "c2", "page_id": "p1", "page_access_user_id": "u1"},
        ]
        child_requests = [r for r in result.requests if r.path.endswith("/u1/components")]
        assert [r.param("page") for r in child_requests] == ["1", "2", "3"]
        assert child_requests[0].param("per_page") == "100"
        # A chain saves no resume state.
        assert result.saved_states == []

    def test_chain_does_not_ignore_a_failure_outside_its_ignore_list(self):
        result = _driver().run(
            "page_access_user_components",
            route(
                {
                    "/v1/pages": [_ok([{"id": "p1"}])],
                    "/pages/p1/page_access_users": [_ok([{"id": "u1", "page_id": "p1"}])],
                    "/pages/p1/page_access_users/u1/components": [ScriptedResponse(status=401, json={})],
                }
            ),
        )

        assert isinstance(result.raised, requests.HTTPError)


class TestRetry:
    @pytest.mark.parametrize("status_code", [420, 429, 500, 502, 503])
    def test_retryable_statuses_exhaust_then_raise(self, status_code):
        result = _driver().run("pages", always(ScriptedResponse(status=status_code, json=[])))

        assert isinstance(result.raised, RESTClientRetryableError)
        # 8 attempts total (the configured cap) before reraise.
        assert len(result.requests) == 8

    def test_client_error_raises_and_is_not_retried(self):
        result = _driver().run("pages", [ScriptedResponse(status=401, json={"error": "Could not authenticate"})])

        assert isinstance(result.raised, requests.HTTPError)
        # A 401 is permanent — issued exactly once, no retry.
        assert len(result.requests) == 1


class TestSourceResponse:
    @pytest.mark.parametrize("endpoint", list(STATUSPAGE_ENDPOINTS.keys()))
    def test_source_response_shape(self, endpoint):
        config = STATUSPAGE_ENDPOINTS[endpoint]
        response = _driver().run(endpoint, []).response
        assert response is not None

        assert response.name == endpoint
        assert response.primary_keys == config.primary_key
        assert response.sort_mode == "asc"
        # Chained endpoints save no cursor, so the pipeline must not hand them off as resumable.
        assert response.supports_resume is (config.parent is None)
        if config.partition_key:
            assert response.partition_mode == "datetime"
            assert response.partition_keys == [config.partition_key]
        else:
            assert response.partition_mode is None

    @pytest.mark.parametrize(
        "endpoint, expected_keys",
        [
            ("pages", ["id"]),
            ("components", ["page_id", "id"]),
            ("subscribers", ["page_id", "id"]),
            ("component_uptime", ["page_id", "id"]),
            ("component_group_uptime", ["page_id", "id"]),
            ("page_access_user_components", ["page_id", "page_access_user_id", "id"]),
        ],
    )
    def test_primary_keys_are_unique_table_wide(self, endpoint, expected_keys):
        # Fan-out children carry the parent page id in their key so rows from different pages never
        # collide on a bare resource id.
        assert STATUSPAGE_ENDPOINTS[endpoint].primary_key == expected_keys


class TestResumeConfigCompatibility:
    def test_legacy_saved_state_still_parses(self):
        # A checkpoint written by the pre-framework code must still deserialize via dataclass(**saved).
        cfg = StatuspageResumeConfig(**cast("dict[str, Any]", {"page": 3, "parent_page_id": "p2"}))
        assert cfg.page == 3
        assert cfg.parent_page_id == "p2"
        assert cfg.paginator_state is None
        assert cfg.fanout_state is None
