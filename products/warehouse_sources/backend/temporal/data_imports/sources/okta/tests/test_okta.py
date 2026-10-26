from datetime import UTC, date, datetime

import pytest
from unittest import mock

from products.warehouse_sources.backend.temporal.data_imports.sources.common.testing import (
    ScriptedResponse,
    SourceDriver,
    scripted_network,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.generated_configs.okta import OktaSourceConfig
from products.warehouse_sources.backend.temporal.data_imports.sources.okta import okta as okta_module
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.okta import (
    OktaResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.settings import OKTA_ENDPOINTS
from products.warehouse_sources.backend.temporal.data_imports.sources.okta.source import OktaSource


class TestFormatIncrementalValue:
    @pytest.mark.parametrize(
        "value, expected",
        [
            (datetime(2026, 3, 4, 2, 58, 14, tzinfo=UTC), "2026-03-04T02:58:14.000Z"),
            (datetime(2026, 1, 15, 10, 30, 45, 123456, tzinfo=UTC), "2026-01-15T10:30:45.123Z"),
            (datetime(2026, 3, 4, 2, 58, 14), "2026-03-04T02:58:14.000Z"),
            (date(2026, 3, 4), "2026-03-04T00:00:00.000Z"),
            ("already-a-cursor", "already-a-cursor"),
        ],
    )
    def test_format(self, value, expected):
        assert _format_incremental_value(value) == expected


class TestBuildInitialParams:
    def test_applications_never_sends_filter(self):
        # Okta's Apps API `filter` does not support lastUpdated, so an incremental run must
        # not send a server-side filter — it would 400.
        params = _build_initial_params(
            OKTA_ENDPOINTS["applications"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastUpdated",
        )
        assert params == {"limit": 200}

    def test_logs_first_sync_applies_lookback(self):
        params = _build_initial_params(
            OKTA_ENDPOINTS["logs"],
            should_use_incremental_field=True,
            db_incremental_field_last_value=None,
            incremental_field="published",
        )
        # The 90-day lookback means `since` is populated even without a stored watermark.
        assert "since" in params
        assert params["sortOrder"] == "ASCENDING"


class TestValidateCredentials:
    def test_success(self):
        with scripted_network([ScriptedResponse(status=200)]) as network:
            assert validate_credentials("example.okta.com", "tok") == (True, None)
        assert network.requests_log[0].path == "/api/v1/users"
        assert network.requests_log[0].param("limit") == "1"
        assert network.requests_log[0].headers["authorization"] == "SSWS tok"

    def test_403_at_source_create_is_accepted(self):
        with scripted_network([ScriptedResponse(status=403)]):
            assert validate_credentials("example.okta.com", "tok", schema_name=None) == (True, None)

    def test_403_for_scoped_probe_fails(self):
        with scripted_network([ScriptedResponse(status=403)]):
            valid, msg = validate_credentials("example.okta.com", "tok", schema_name="users")
            assert valid is False
            assert msg is not None

    @pytest.mark.parametrize("bad_domain", ["", "not a domain!", "https://"])
    def test_invalid_domain_short_circuits(self, bad_domain):
        valid, msg = validate_credentials(bad_domain, "tok")
        assert valid is False
        assert msg == "Invalid Okta domain"

    def test_rejects_redirect_response(self):
        # A validated host that 3xx-redirects (potentially to an internal address) must be rejected,
        # not followed (SSRF).
        with scripted_network(
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example/"})]
        ) as network:
            valid, msg = validate_credentials("example.okta.com", "tok")
            assert valid is False
            assert msg == okta_module.HOST_NOT_ALLOWED_ERROR
        assert [request.path for request in network.requests_log] == ["/api/v1/users"]

    def test_blocks_unsafe_host(self):
        # When a team_id is supplied, a host that resolves to an internal address is rejected
        # before any HTTP request is made (SSRF guard).
        with (
            mock.patch.object(okta_module, "_is_host_safe", return_value=(False, "internal address")),
            scripted_network([]) as network,
        ):
            valid, msg = validate_credentials("10.0.0.1", "tok", team_id=99)
            assert valid is False
            assert msg == "internal address"
        assert network.requests_log == []


class TestOktaPagination:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(
            OktaSource(),
            OktaSourceConfig(okta_domain="example.okta.com", api_key="tok"),
        )

    def test_follows_link_header_across_pages(self):
        result = self._driver().run(
            "users",
            [
                ScriptedResponse(
                    json=[{"id": "1"}, {"id": "2"}],
                    headers={"Link": '<https://example.okta.com/api/v1/users?after=cur>; rel="next"'},
                ),
                ScriptedResponse(json=[{"id": "3"}]),
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1", "2", "3"]
        assert result.paths == ["/api/v1/users", "/api/v1/users"]
        assert result.requests[0].origin == "https://example.okta.com"
        assert result.requests[0].param("limit") == "200"
        # Second request follows the self-contained Link-header URL.
        assert result.requests[1].param("after") == "cur"
        assert result.requests[1].origin == "https://example.okta.com"

    def test_resumes_from_saved_state(self):
        result = self._driver().run(
            "users",
            [ScriptedResponse(json=[{"id": "9"}])],
            resume_state=OktaResumeConfig(next_url="https://example.okta.com/api/v1/users?after=resume"),
        )

        assert result.raised is None
        assert result.requests[0].origin == "https://example.okta.com"
        assert result.requests[0].path == "/api/v1/users"
        assert result.requests[0].param("after") == "resume"
        assert [row["id"] for row in result.rows] == ["9"]

    def test_empty_page_terminates_even_with_next_link(self):
        # The System Log always returns a next link, so an empty page must end pagination.
        result = self._driver().run(
            "logs",
            [
                ScriptedResponse(
                    json=[],
                    headers={"Link": '<https://example.okta.com/api/v1/logs?after=x>; rel="next"'},
                )
            ],
        )

        assert result.raised is None
        assert result.rows == []
        assert result.paths == ["/api/v1/logs"]

    def test_does_not_follow_next_url_on_foreign_host(self):
        # A server-controlled Link header pointing off-org must not be followed (SSRF guard).
        result = self._driver().run(
            "users",
            [
                ScriptedResponse(
                    json=[{"id": "1"}],
                    headers={"Link": '<http://169.254.169.254/latest/meta-data/>; rel="next"'},
                )
            ],
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == ["1"]
        assert result.paths == ["/api/v1/users"]

    def test_ignores_resume_url_on_foreign_host(self):
        # A poisoned resume URL must fall back to the initial org URL, not be followed.
        result = self._driver().run(
            "users",
            [ScriptedResponse(json=[{"id": "1"}])],
            resume_state=OktaResumeConfig(next_url="http://169.254.169.254/latest/meta-data/"),
        )

        assert result.raised is None
        assert result.requests[0].origin == "https://example.okta.com"
        assert result.requests[0].path == "/api/v1/users"
        assert result.requests[0].param("after") is None
        assert [row["id"] for row in result.rows] == ["1"]

    def test_does_not_follow_redirects(self):
        # Requests disable redirect following, and a redirect response is rejected rather than
        # followed to a (potentially internal) Location (SSRF).
        result = self._driver().run(
            "users",
            [ScriptedResponse(status=302, headers={"Location": "https://internal.example/"})],
        )
        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/v1/users"]

    def test_incremental_filter_reaches_request(self):
        result = self._driver().run(
            "users",
            [ScriptedResponse(json=[{"id": "1"}])],
            should_use_incremental_field=True,
            db_incremental_field_last_value=datetime(2024, 1, 1, tzinfo=UTC),
            incremental_field="lastUpdated",
        )
        assert result.raised is None
        assert result.requests[0].param("filter") == 'lastUpdated gt "2024-01-01T00:00:00.000Z"'
        assert result.requests[0].param("limit") == "200"

    def test_runtime_host_check_blocks_unsafe_domain(self):
        # The configured domain is re-checked at run time (DNS rebinding) before any request.
        with mock.patch.object(okta_module, "_is_host_safe", return_value=(False, "internal address")):
            result = self._driver().run("users", [])
        assert isinstance(result.raised, okta_module.OktaHostNotAllowedError)
        assert result.requests == []


class TestOktaFanout:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(
            OktaSource(),
            OktaSourceConfig(okta_domain="example.okta.com", api_key="tok"),
        )

    @pytest.mark.parametrize(
        "schema, parent_path, child_path, parent_key, child_limit",
        [
            ("group_members", "/api/v1/groups", "/api/v1/groups/{}/users", "group_id", "200"),
            ("application_users", "/api/v1/apps", "/api/v1/apps/{}/users", "app_id", "500"),
            ("application_groups", "/api/v1/apps", "/api/v1/apps/{}/groups", "app_id", "200"),
            ("user_factors", "/api/v1/users", "/api/v1/users/{}/factors", "user_id", None),
        ],
    )
    def test_fans_out_over_parents_and_skips_deleted_parent(
        self, schema, parent_path, child_path, parent_key, child_limit
    ):
        result = self._driver().run(
            schema,
            [
                ScriptedResponse(json=[{"id": "p1"}, {"id": "p2"}]),
                ScriptedResponse(json=[{"id": "c1"}, {"id": "c2"}]),
                # p2 was deleted after the parent listing.
                ScriptedResponse(status=404, json={"errorCode": "E0000007"}),
            ],
        )

        assert result.raised is None
        assert [(row[parent_key], row["id"]) for row in result.rows] == [("p1", "c1"), ("p1", "c2")]
        assert result.paths == [parent_path, child_path.format("p1"), child_path.format("p2")]
        assert result.requests[0].param("limit") == "200"
        assert result.requests[1].param("limit") == child_limit

    def test_user_factors_drop_activation_secrets(self):
        result = self._driver().run(
            "user_factors",
            [
                ScriptedResponse(json=[{"id": "u1"}]),
                ScriptedResponse(
                    json=[
                        {
                            "id": "f1",
                            "factorType": "token:software:totp",
                            "status": "PENDING_ACTIVATION",
                            "_embedded": {"activation": {"sharedSecret": "FAKESECRET"}},
                            "_links": {"qrcode": {"href": "https://example.okta.com/qr/fake"}},
                        }
                    ]
                ),
            ],
        )

        assert result.raised is None
        assert result.rows == [
            {"id": "f1", "factorType": "token:software:totp", "status": "PENDING_ACTIVATION", "user_id": "u1"}
        ]

    def test_follows_child_link_header_across_pages(self):
        result = self._driver().run(
            "group_members",
            [
                ScriptedResponse(json=[{"id": "g1"}]),
                ScriptedResponse(
                    json=[{"id": "u1"}],
                    headers={"Link": '<https://example.okta.com/api/v1/groups/g1/users?after=cur>; rel="next"'},
                ),
                ScriptedResponse(json=[{"id": "u2"}]),
            ],
        )

        assert result.raised is None
        assert [(row["group_id"], row["id"]) for row in result.rows] == [("g1", "u1"), ("g1", "u2")]
        assert result.requests[2].path == "/api/v1/groups/g1/users"
        assert result.requests[2].param("after") == "cur"

    def test_resume_skips_completed_parents(self):
        result = self._driver().run(
            "group_members",
            [
                ScriptedResponse(json=[{"id": "g1"}, {"id": "g2"}]),
                ScriptedResponse(json=[{"id": "u3"}]),
            ],
            resume_state=OktaResumeConfig(
                fanout_state={"completed": ["/groups/g1/users"], "current": None, "child_state": None}
            ),
        )

        assert result.raised is None
        assert result.paths == ["/api/v1/groups", "/api/v1/groups/g2/users"]
        assert [(row["group_id"], row["id"]) for row in result.rows] == [("g2", "u3")]

    def test_resumed_child_url_on_foreign_host_is_refused(self):
        result = self._driver().run(
            "group_members",
            [ScriptedResponse(json=[{"id": "g1"}])],
            resume_state=OktaResumeConfig(
                fanout_state={
                    "completed": [],
                    "current": "/groups/g1/users",
                    "child_state": {"next_url": "http://169.254.169.254/latest/meta-data/"},
                }
            ),
        )

        assert isinstance(result.raised, ValueError)
        assert result.paths == ["/api/v1/groups"]
