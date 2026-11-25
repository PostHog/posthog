from typing import Any

import pytest

from products.warehouse_sources.sources.particle._config import ParticleSourceConfig
from products.warehouse_sources.sources.particle.particle import (
    WEBHOOK_AUTH_ERROR,
    _webhook_table_transformer,
    create_webhook,
    delete_webhook,
    event_prefixes,
    get_external_webhook_info,
)
from products.warehouse_sources.sources.particle.settings import WEBHOOK_SECRET_HEADER
from products.warehouse_sources.sources.particle.source import ParticleSource
from products.warehouse_sources.sources.sdk.internals import table_from_py_list
from products.warehouse_sources.sources.sdk.testing import (
    ScriptedResponse,
    SourceDriver,
    always,
    route,
    scripted_network,
)

WEBHOOK_URL = "https://webhooks.us.posthog.com/public/webhooks/dwh/0199f0c4-1b2a-7c3d-8e4f-5a6b7c8d9e0f"
TOKEN = "particle-api-user-token"


def _config(product_id: str | None = None, event_prefixes: str = "env/, status") -> ParticleSourceConfig:
    return ParticleSourceConfig(access_token=TOKEN, product_id=product_id, event_prefixes=event_prefixes)


def _hook(hook_id: str, url: str = WEBHOOK_URL, event: str = "env/", integration_type: str = "Webhook") -> dict:
    return {"id": hook_id, "event": event, "url": url, "integration_type": integration_type, "requestType": "POST"}


class TestDevices:
    def test_sandbox_devices_come_from_the_user_device_list(self):
        result = SourceDriver(ParticleSource(), _config()).run(
            "devices",
            [ScriptedResponse(json=[{"id": "d1", "name": "kitchen", "online": True}, {"id": "d2", "online": False}])],
        )

        assert result.raised is None
        assert result.paths == ["/v1/devices"]
        assert [row["id"] for row in result.rows] == ["d1", "d2"]
        assert result.requests[0].headers["authorization"] == f"Bearer {TOKEN}"

    def test_product_devices_walk_every_page(self):
        result = SourceDriver(ParticleSource(), _config(product_id="31337")).run(
            "devices",
            [
                ScriptedResponse(json={"devices": [{"id": "d1"}], "customers": [], "meta": {"total_pages": 2}}),
                ScriptedResponse(json={"devices": [{"id": "d2"}], "customers": [], "meta": {"total_pages": 2}}),
            ],
        )

        assert result.raised is None
        assert result.paths == ["/v1/products/31337/devices", "/v1/products/31337/devices"]
        assert result.params("page") == ["1", "2"]
        assert [row["id"] for row in result.rows] == ["d1", "d2"]


class TestSims:
    @pytest.mark.parametrize(
        ("product_id", "script", "expected_paths", "expected_pages"),
        [
            # The sandbox list is one response; only the product list pages.
            (None, [ScriptedResponse(json={"sims": [{"_id": "s1"}, {"_id": "s2"}]})], ["/v1/sims"], [None]),
            (
                "31337",
                [
                    ScriptedResponse(json={"sims": [{"_id": "s1"}], "meta": {"total_pages": 2}}),
                    ScriptedResponse(json={"sims": [{"_id": "s2"}], "meta": {"total_pages": 2}}),
                ],
                ["/v1/products/31337/sims", "/v1/products/31337/sims"],
                ["1", "2"],
            ),
        ],
    )
    def test_lists_every_sim(self, product_id, script, expected_paths, expected_pages):
        result = SourceDriver(ParticleSource(), _config(product_id=product_id)).run("sims", script)

        assert result.raised is None
        assert result.paths == expected_paths
        assert result.params("page") == expected_pages
        assert [row["_id"] for row in result.rows] == ["s1", "s2"]


class TestFanOut:
    @pytest.mark.parametrize("product_id", [None, "31337"])
    def test_sim_data_usage_reads_each_sim_and_tags_rows_with_its_iccid(self, product_id):
        base = f"/v1/products/{product_id}" if product_id else "/v1"
        meta = {"meta": {"total_pages": 2}} if product_id else {}
        sims_pages = (
            [
                ScriptedResponse(json={"sims": [{"_id": "s1"}], **meta}),
                ScriptedResponse(json={"sims": [{"_id": "s2"}, {"_id": "gone"}], **meta}),
            ]
            if product_id
            else [ScriptedResponse(json={"sims": [{"_id": "s1"}, {"_id": "s2"}, {"_id": "gone"}]})]
        )
        result = SourceDriver(ParticleSource(), _config(product_id=product_id)).run(
            "sim_data_usage",
            route(
                {
                    f"{base}/sims": sims_pages,
                    f"{base}/sims/s1/data_usage": [
                        ScriptedResponse(
                            json={
                                "iccid": "s1",
                                "usage_by_day": [
                                    {"date": "2026-11-01", "mbs_used": 1.5, "mbs_used_cumulative": 1.5},
                                    {"date": "2026-11-02", "mbs_used": 0.5, "mbs_used_cumulative": 2.0},
                                ],
                            }
                        )
                    ],
                    f"{base}/sims/s2/data_usage": [ScriptedResponse(json={"iccid": "s2", "usage_by_day": []})],
                    # Released between the listing and this read.
                    f"{base}/sims/gone/data_usage": [ScriptedResponse(status=404, json={"ok": False})],
                }
            ),
            incremental_field="date",
        )

        assert result.raised is None
        assert [(row["iccid"], row["date"], row["mbs_used"]) for row in result.rows] == [
            ("s1", "2026-11-01", 1.5),
            ("s1", "2026-11-02", 0.5),
        ]
        assert all("_sims__id" not in row for row in result.rows)
        assert [path for path in result.paths if path.endswith("/data_usage")] == [
            f"{base}/sims/s1/data_usage",
            f"{base}/sims/s2/data_usage",
            f"{base}/sims/gone/data_usage",
        ]
        # The children take no paging params; only the product SIM list pages.
        assert all(not query for query, path in zip(result.queries, result.paths) if path.endswith("/data_usage"))

    @pytest.mark.parametrize("product_id", [None, "31337"])
    def test_device_diagnostics_keeps_the_last_vitals_of_each_device(self, product_id):
        base = f"/v1/products/{product_id}" if product_id else "/v1"
        devices = [{"id": "d1"}, {"id": "d2"}]
        result = SourceDriver(ParticleSource(), _config(product_id=product_id)).run(
            "device_diagnostics",
            route(
                {
                    f"{base}/devices": [
                        ScriptedResponse(json={"devices": devices, "meta": {"total_pages": 1}})
                        if product_id
                        else ScriptedResponse(json=devices)
                    ],
                    f"{base}/diagnostics/d1/last": [
                        ScriptedResponse(
                            json={
                                "diagnostics": {
                                    "updated_at": "2026-11-24T10:00:00.000Z",
                                    "deviceID": "d1",
                                    "payload": {"device": {"power": {"battery": {"charge": 88}}}},
                                }
                            }
                        )
                    ],
                    # A device that never sent vitals.
                    f"{base}/diagnostics/d2/last": [ScriptedResponse(status=404, json={"ok": False})],
                }
            ),
        )

        assert result.raised is None
        assert [row["deviceID"] for row in result.rows] == ["d1"]
        assert result.rows[0]["payload"] == {"device": {"power": {"battery": {"charge": 88}}}}


class TestDeviceGroups:
    def test_product_groups_are_listed(self):
        result = SourceDriver(ParticleSource(), _config(product_id="31337")).run(
            "device_groups",
            [ScriptedResponse(json={"groups": [{"name": "group_a", "color": "#34495e"}, {"name": "group_b"}]})],
        )

        assert result.raised is None
        assert result.paths == ["/v1/products/31337/groups"]
        assert [row["name"] for row in result.rows] == ["group_a", "group_b"]

    def test_sandbox_has_no_groups_and_says_so_in_the_table_picker(self):
        result = SourceDriver(ParticleSource(), _config()).run("device_groups", [])

        assert result.raised is None
        assert result.rows == []
        assert result.paths == []
        permissions = ParticleSource().get_endpoint_permissions(
            _config(), team_id=1, endpoints=["device_groups", "sims"]
        )
        assert permissions["sims"] is None
        assert "product ID" in (permissions["device_groups"] or "")


class TestSchemas:
    def test_events_is_webhook_only_so_it_cannot_be_switched_to_full_refresh(self):
        schemas = {s.name: s for s in ParticleSource().get_schemas(_config(), team_id=1)}

        assert schemas["events"].supports_webhooks is True
        assert schemas["events"].webhook_only is True
        assert schemas["devices"].webhook_only is False


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("env/, status", ["env/", "status"]),
        # Particle matches by prefix, so `env/` already receives `env/temp`; a second hook would
        # capture every `env/temp` publish twice.
        ("env/, env/temp, status", ["env/", "status"]),
        ("env/temp, env/", ["env/"]),
        ("env/, env/", ["env/"]),
        (" , ", []),
    ],
)
def test_event_prefixes_drop_prefixes_covered_by_a_broader_one(raw, expected):
    assert event_prefixes(_config(event_prefixes=raw)) == expected


class TestValidateCredentials:
    @pytest.mark.parametrize(
        ("status", "product_id", "expected_path", "expected_error"),
        [
            (200, None, "/v1/devices", None),
            (200, "31337", "/v1/products/31337/devices", None),
            (401, None, "/v1/devices", "Invalid Particle access token"),
            (403, "31337", "/v1/products/31337/devices", "devices:list"),
            (404, "31337", "/v1/products/31337/devices", "Particle product 31337"),
        ],
    )
    def test_maps_the_device_probe(self, status, product_id, expected_path, expected_error):
        with scripted_network(always(ScriptedResponse(status=status, json={}))) as network:
            ok, error = ParticleSource().validate_credentials(_config(product_id=product_id), team_id=1)

        assert ok is (expected_error is None)
        if expected_error is not None:
            assert expected_error in (error or "")
        assert {request.path for request in network.requests_log} == {expected_path}


class TestWebhooks:
    @pytest.mark.parametrize(
        ("product_id", "base_path"),
        [(None, "/v1/integrations"), ("31337", "/v1/products/31337/integrations")],
    )
    def test_create_replaces_our_hooks_with_one_per_prefix(self, product_id, base_path):
        listing = [_hook("stale"), _hook("theirs", url="https://example.com/other")]
        with scripted_network(
            [
                ScriptedResponse(json=listing),
                ScriptedResponse(status=201, json={"ok": True, "id": "h1"}),
                ScriptedResponse(status=201, json={"ok": True, "id": "h2"}),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = create_webhook(_config(product_id=product_id), WEBHOOK_URL)

        assert result.success is True, result.error
        secret = result.extra_inputs["signing_secret"]
        assert secret
        requests = network.requests_log
        # Every hook shares one secret, so a stale hook from an earlier setup is removed rather
        # than left delivering with a secret the function no longer accepts. It is removed only
        # after the new hooks exist, so a failed setup keeps the previous configuration.
        assert [(r.method, r.path) for r in requests] == [
            ("GET", base_path),
            ("POST", base_path),
            ("POST", base_path),
            ("DELETE", f"{base_path}/stale"),
        ]
        bodies = [requests[1].json(), requests[2].json()]
        assert [body["event"] for body in bodies] == ["env/", "status"]
        for body in bodies:
            assert body["integration_type"] == "Webhook"
            assert body["url"] == WEBHOOK_URL
            assert body["requestType"] == "POST"
            assert body["noDefaults"] is True
            assert body["headers"][WEBHOOK_SECRET_HEADER] == secret
            assert body["headers"]["Content-Type"] == "application/json"
            assert body["body"] == "{{{PARTICLE_EVENT_JSON}}}"
            assert body["query"]["device_id"] == "{{{PARTICLE_DEVICE_ID}}}"
            assert body["query"]["event_id"] == "{{{PARTICLE_EVENT_ID}}}"
        assert network.session_options[0]["redact_values"] == (TOKEN,)

    @pytest.mark.parametrize("status", [401, 403])
    def test_create_surfaces_a_token_without_integration_scopes(self, status):
        with scripted_network([ScriptedResponse(json=[]), ScriptedResponse(status=status, json={"ok": False})]):
            result = create_webhook(_config(), WEBHOOK_URL)

        assert result.success is False
        assert result.error == WEBHOOK_AUTH_ERROR

    @pytest.mark.parametrize("status", [403, 500])
    def test_create_rolls_back_new_hooks_and_keeps_old_ones_when_a_later_hook_fails(self, status):
        # The first hook registers, the second fails: the first must not stay active with a
        # secret PostHog never stored, and the stale hook from the previous setup must survive.
        with scripted_network(
            [
                ScriptedResponse(json=[_hook("stale")]),
                ScriptedResponse(status=201, json={"ok": True, "id": "h1"}),
                ScriptedResponse(status=status, json={"ok": False}),
                ScriptedResponse(status=204),
            ]
        ) as network:
            result = create_webhook(_config(), WEBHOOK_URL)

        assert result.success is False
        assert not result.extra_inputs
        assert [(r.method, r.path) for r in network.requests_log] == [
            ("GET", "/v1/integrations"),
            ("POST", "/v1/integrations"),
            ("POST", "/v1/integrations"),
            ("DELETE", "/v1/integrations/h1"),
        ]

    def test_create_rejects_a_config_without_prefixes(self):
        with scripted_network([]) as network:
            result = create_webhook(_config(event_prefixes=" , "), WEBHOOK_URL)

        assert result.success is False
        assert "event name prefix" in (result.error or "")
        assert network.requests_log == []

    def test_delete_removes_only_our_hooks(self):
        listing = [_hook("h1"), _hook("h2", event="status"), _hook("theirs", url="https://example.com/other")]
        with scripted_network(
            route(
                {
                    "/v1/products/31337/integrations": [ScriptedResponse(json=listing)],
                    "/v1/products/31337/integrations/h1": [ScriptedResponse(status=204)],
                    "/v1/products/31337/integrations/h2": [ScriptedResponse(status=204)],
                }
            )
        ) as network:
            result = delete_webhook(_config(product_id="31337"), WEBHOOK_URL)

        assert result.success is True
        assert sorted(r.path for r in network.requests_log if r.method == "DELETE") == [
            "/v1/products/31337/integrations/h1",
            "/v1/products/31337/integrations/h2",
        ]

    def test_info_reports_the_prefixes_routed_to_posthog(self):
        listing = [
            _hook("h1"),
            _hook("h2", event="status"),
            _hook("gcp", url=WEBHOOK_URL, integration_type="GoogleCloudPubSub"),
        ]
        with scripted_network([ScriptedResponse(json=listing)]):
            info = get_external_webhook_info(_config(), WEBHOOK_URL)

        assert info.exists is True
        assert info.url == WEBHOOK_URL
        assert info.enabled_events == ["env/", "status"]

    def test_info_reports_missing_hooks(self):
        with scripted_network([ScriptedResponse(json=[_hook("theirs", url="https://example.com/other")])]):
            info = get_external_webhook_info(_config(), WEBHOOK_URL)

        assert info.exists is False
        assert info.error is None


def test_webhook_batch_keeps_one_row_per_particle_event():
    # Particle delivers at least once, so a retried delivery can land in the same batch.
    rows: list[dict[str, Any]] = [
        {"event_id": "a", "event": "env/reading", "data": "1"},
        {"event_id": "a", "event": "env/reading", "data": "1"},
        {"event_id": "b", "event": "env/reading", "data": "2"},
        {"event_id": None, "event": "env/reading", "data": "3"},
    ]

    result = _webhook_table_transformer(table_from_py_list(rows)).to_pylist()

    assert [row["event_id"] for row in result] == ["a", "b"]
