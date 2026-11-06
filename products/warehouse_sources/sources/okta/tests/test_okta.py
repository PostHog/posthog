from datetime import UTC, date, datetime

import pytest
from unittest import mock

from products.warehouse_sources.sources.okta import okta as okta_module
from products.warehouse_sources.sources.okta._config import OktaSourceConfig
from products.warehouse_sources.sources.okta.okta import (
    OktaResumeConfig,
    _build_initial_params,
    _format_incremental_value,
    validate_credentials,
)
from products.warehouse_sources.sources.okta.settings import OKTA_ENDPOINTS, POLICY_TYPES
from products.warehouse_sources.sources.okta.source import OktaSource
from products.warehouse_sources.sources.sdk.testing import ScriptedResponse, SourceDriver, scripted_network


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
            ("user_role_assignments", "/api/v1/users", "/api/v1/users/{}/roles", "user_id", None),
            ("group_role_assignments", "/api/v1/groups", "/api/v1/groups/{}/roles", "group_id", None),
            ("identity_provider_users", "/api/v1/idps", "/api/v1/idps/{}/users", "idp_id", "200"),
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

    @pytest.mark.parametrize(
        "schema, script, expected_rows",
        [
            (
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
                [{"id": "f1", "factorType": "token:software:totp", "status": "PENDING_ACTIVATION", "user_id": "u1"}],
            ),
            (
                "identity_providers",
                [
                    ScriptedResponse(
                        json=[
                            {
                                "id": "idp1",
                                "type": "OIDC",
                                "protocol": {
                                    "type": "OIDC",
                                    "scopes": ["openid"],
                                    "credentials": {"client": {"client_id": "fake-id", "client_secret": "FAKESECRET"}},
                                },
                            },
                            {"id": "idp2", "type": "SAML2", "protocol": None},
                        ]
                    )
                ],
                [
                    {"id": "idp1", "type": "OIDC", "protocol": {"type": "OIDC", "scopes": ["openid"]}},
                    {"id": "idp2", "type": "SAML2", "protocol": None},
                ],
            ),
        ],
    )
    def test_drops_secret_fields(self, schema, script, expected_rows):
        result = self._driver().run(schema, script)

        assert result.raised is None
        assert result.rows == expected_rows

    @pytest.mark.parametrize(
        "device_user, expected_user_id",
        [
            ({"created": "2026-01-01T00:00:00.000Z", "user": {"id": "u1", "status": "ACTIVE"}}, "u1"),
            ({"created": "2026-01-01T00:00:00.000Z", "user": None}, None),
        ],
    )
    def test_device_users_lift_the_nested_user_id(self, device_user, expected_user_id):
        result = self._driver().run(
            "device_users",
            [ScriptedResponse(json=[{"id": "d1"}]), ScriptedResponse(json=[device_user])],
        )

        assert result.raised is None
        assert [(row["device_id"], row["user_id"]) for row in result.rows] == [("d1", expected_user_id)]
        assert result.paths == ["/api/v1/devices", "/api/v1/devices/d1/users"]
        assert result.params("limit") == ["200", None]

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


def test_connection_target_change_requires_secret_reentry() -> None:
    # The API token is sent to `okta_domain`.
    # A change to this field must make the update API ask for the secret again.
    assert OktaSource().connection_host_fields == ["okta_domain"]


class TestOktaCustomRoles:
    @pytest.mark.parametrize(
        "next_href, expected_ids, expected_requests",
        [
            ("https://example.okta.com/api/v1/iam/roles?after=cr1", ["cr1", "cr2"], 2),
            ("http://169.254.169.254/latest/meta-data/", ["cr1"], 1),
        ],
    )
    def test_follows_body_link_on_org_host_only(self, next_href, expected_ids, expected_requests):
        script = [
            ScriptedResponse(json={"roles": [{"id": "cr1"}], "_links": {"next": {"href": next_href}}}),
            ScriptedResponse(json={"roles": [{"id": "cr2"}], "_links": {}}),
        ]
        result = SourceDriver(OktaSource(), OktaSourceConfig(okta_domain="example.okta.com", api_key="tok")).run(
            "custom_roles", script[:expected_requests]
        )

        assert result.raised is None
        assert [row["id"] for row in result.rows] == expected_ids
        assert result.paths == ["/api/v1/iam/roles"] * expected_requests
        assert result.requests[0].param("limit") is None


class TestOktaPolicies:
    @staticmethod
    def _driver() -> SourceDriver:
        return SourceDriver(
            OktaSource(),
            OktaSourceConfig(okta_domain="example.okta.com", api_key="tok"),
        )

    @staticmethod
    def _policies_script(request):
        policy_type = request.param("type")
        if policy_type == "ACCESS_POLICY":
            return ScriptedResponse(status=400, json={"errorCode": "E0000001", "errorSummary": "Api validation failed"})
        if policy_type == "ENTITY_RISK":
            return ScriptedResponse(status=401, json={"errorCode": "E0000015", "errorSummary": "Feature not enabled"})
        if request.path == "/api/v1/policies":
            return ScriptedResponse(json=[{"id": f"pol-{policy_type}", "type": policy_type}])
        return ScriptedResponse(json=[{"id": "rule1"}])

    def test_reads_every_policy_type_and_skips_rejected_types(self):
        result = self._driver().run("policies", self._policies_script)

        assert result.raised is None
        assert result.params("type") == list(POLICY_TYPES)
        assert result.params("limit") == [None] * len(POLICY_TYPES)
        assert [row["type"] for row in result.rows] == [
            t for t in POLICY_TYPES if t not in ("ACCESS_POLICY", "ENTITY_RISK")
        ]
        assert result.committed_states[-1] == OktaResumeConfig(policy_type=POLICY_TYPES[-1])

    def test_policy_rules_fan_out_per_policy_type(self):
        result = self._driver().run("policy_rules", self._policies_script)

        assert result.raised is None
        assert result.paths[:3] == [
            "/api/v1/policies",
            "/api/v1/policies/pol-OKTA_SIGN_ON/rules",
            "/api/v1/policies",
        ]
        assert [request.param("type") for request in result.requests if request.path == "/api/v1/policies"] == list(
            POLICY_TYPES
        )
        assert ("pol-PASSWORD", "rule1") in [(row["policy_id"], row["id"]) for row in result.rows]
        assert not any(row["policy_id"] in ("pol-ACCESS_POLICY", "pol-ENTITY_RISK") for row in result.rows)

    @pytest.mark.parametrize("schema", ["policies", "policy_rules"])
    def test_resumes_at_saved_policy_type(self, schema):
        result = self._driver().run(
            schema,
            self._policies_script,
            resume_state=OktaResumeConfig(policy_type="CLIENT_UPDATE"),
        )

        assert result.raised is None
        assert [r.param("type") for r in result.requests if r.path == "/api/v1/policies"] == [
            "CLIENT_UPDATE",
            "IDENTITY_CLAIM_SOURCING",
        ]

    def test_other_errors_still_fail_the_sync(self):
        result = self._driver().run(
            "policies",
            [ScriptedResponse(status=401, json={"errorCode": "E0000011", "errorSummary": "Invalid token provided"})],
        )

        assert result.raised is not None
        assert result.params("type") == ["OKTA_SIGN_ON"]
