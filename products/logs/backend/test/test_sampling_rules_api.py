from posthog.test.base import APIBaseTest
from unittest.mock import patch

from parameterized import parameterized
from rest_framework import status

from products.logs.backend.models import LogsExclusionRule


class TestLogsSamplingRulesAPI(APIBaseTest):
    def setUp(self):
        super().setUp()
        self.base_url = f"/api/projects/{self.team.pk}/logs/sampling_rules/"
        self._ff_patcher = patch("posthoganalytics.feature_enabled", return_value=True)
        self._ff_patcher.start()
        self.addCleanup(self._ff_patcher.stop)

    def _payload(self, **overrides):
        data = {
            "name": "Drop healthz",
            "rule_type": "path_drop",
            "config": {"patterns": ["/healthz"]},
            "scope_attribute_filters": [],
        }
        data.update(overrides)
        return data

    @patch("products.logs.backend.presentation.views.sampling_api.report_user_action")
    def test_create_defaults_disabled_and_priority(self, mock_report):
        response = self.client.post(self.base_url, self._payload(), format="json")
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["enabled"] is False
        assert body["priority"] == 0
        assert body["version"] == 1
        mock_report.assert_called_once()

    def test_list_scoped_to_team(self):
        self.client.post(self.base_url, self._payload(name="r1"), format="json")
        other_team = self.create_team_with_organization(organization=self.organization)
        LogsExclusionRule.objects.create(
            team_id=other_team.id,
            name="other",
            enabled=False,
            priority=0,
            rule_type=LogsExclusionRule.RuleType.PATH_DROP,
            config={"patterns": []},
        )

        response = self.client.get(self.base_url)
        assert response.status_code == status.HTTP_200_OK
        results = response.json()["results"]
        assert len(results) == 1
        assert results[0]["name"] == "r1"

    def test_reorder(self):
        a = self.client.post(self.base_url, self._payload(name="a"), format="json").json()
        b = self.client.post(self.base_url, self._payload(name="b"), format="json").json()

        reorder_url = f"{self.base_url}reorder/"
        r = self.client.post(reorder_url, {"ordered_ids": [b["id"], a["id"]]}, format="json")
        assert r.status_code == status.HTTP_200_OK, r.json()
        ordered = r.json()
        assert ordered[0]["id"] == b["id"]
        assert ordered[0]["priority"] == 0
        assert ordered[1]["id"] == a["id"]
        assert ordered[1]["priority"] == 1

    def test_create_rate_limit_without_scope_service(self):
        # scope_service is no longer required for rate_limit — the matching
        # happens through config.filter_group instead.
        response = self.client.post(
            self.base_url,
            self._payload(
                name="Cap api",
                rule_type="rate_limit",
                scope_service=None,
                config={"logs_per_second": 100},
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["scope_service"] is None

    def test_create_rate_limit_success(self):
        response = self.client.post(
            self.base_url,
            self._payload(
                name="Cap api",
                rule_type="rate_limit",
                scope_service="payment-api",
                config={"logs_per_second": 5000, "burst_logs": 15000},
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["rule_type"] == "rate_limit"
        assert body["scope_service"] == "payment-api"
        assert body["config"]["logs_per_second"] == 5000
        assert body["config"]["burst_logs"] == 15000

    def test_create_rate_limit_kb_success(self):
        # KB-mode is the new shape: cost-per-record is the row's bytes_uncompressed,
        # matching how billing measures ingested bytes.
        response = self.client.post(
            self.base_url,
            self._payload(
                name="Cap api by bytes",
                rule_type="rate_limit",
                scope_service="payment-api",
                config={"kb_per_second": 500, "burst_kb": 1500},
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        body = response.json()
        assert body["config"]["kb_per_second"] == 500
        assert body["config"]["burst_kb"] == 1500

    # Configs that should be rejected by the rate_limit validator. Keep this list
    # close to the inverse of `test_create_rate_limit_*_success` — every accepted
    # shape has a symmetric set of rejection cases here.
    INVALID_RATE_LIMIT_CONFIGS = [
        ("both_modes_set", {"logs_per_second": 100, "kb_per_second": 100}),
        ("neither_mode_set", {}),
        ("kb_per_second_below_min", {"kb_per_second": 0}),
        ("kb_per_second_above_max", {"kb_per_second": 1_000_001}),
        ("burst_kb_below_kb_per_second", {"kb_per_second": 500, "burst_kb": 100}),
        ("burst_kb_above_max", {"kb_per_second": 1, "burst_kb": 10_000_001}),
    ]

    @parameterized.expand([(label, payload) for label, payload in INVALID_RATE_LIMIT_CONFIGS])
    def test_create_rate_limit_rejects_invalid_config(self, _label, invalid_config):
        response = self.client.post(
            self.base_url,
            self._payload(rule_type="rate_limit", scope_service="payment-api", config=invalid_config),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    def test_create_path_drop_with_valid_filter_group(self):
        # The drop-rules UI writes the inner group wrapped in an outer AND envelope.
        filter_group = {
            "type": "AND",
            "values": [
                {
                    "type": "AND",
                    "values": [
                        {"key": "service.name", "operator": "exact", "value": "api", "type": "log_resource_attribute"}
                    ],
                }
            ],
        }
        response = self.client.post(
            self.base_url,
            self._payload(
                name="Drop api logs",
                config={"patterns": [], "filter_group": filter_group},
            ),
            format="json",
        )
        assert response.status_code == status.HTTP_201_CREATED, response.json()
        assert response.json()["config"]["filter_group"] == filter_group

    # Each case is a config payload that the Pydantic PropertyGroupFilter validator
    # should reject at write time, so a malformed shape never reaches the worker.
    MALFORMED_FILTER_GROUPS = [
        ("filter_group_is_list", []),
        ("filter_group_is_string", "not a group"),
        ("missing_type", {"values": []}),
        ("invalid_logical_operator", {"type": "XOR", "values": []}),
        ("values_is_not_list", {"type": "AND", "values": "oops"}),
        ("inner_group_is_list", {"type": "AND", "values": [[{"key": "x"}]]}),
    ]

    @parameterized.expand([(label, payload) for label, payload in MALFORMED_FILTER_GROUPS])
    def test_create_path_drop_rejects_malformed_filter_group(self, _label, malformed):
        response = self.client.post(
            self.base_url,
            self._payload(config={"patterns": [], "filter_group": malformed}),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        # The error attaches under config → filter_group; precise message comes from Pydantic.
        body = response.json()
        assert "filter_group" in str(body), body

    @parameterized.expand([(label, payload) for label, payload in MALFORMED_FILTER_GROUPS])
    def test_patch_path_drop_rejects_malformed_filter_group(self, _label, malformed):
        create = self.client.post(self.base_url, self._payload(), format="json")
        assert create.status_code == status.HTTP_201_CREATED, create.json()
        rule_id = create.json()["id"]

        response = self.client.patch(
            f"{self.base_url}{rule_id}/",
            {"config": {"patterns": [], "filter_group": malformed}},
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()

    # Well-formed but vacuous shapes: they pass Pydantic validation, but the worker's
    # matchFilterGroup returns false for empty groups, so the rule silently never
    # applies. Worst on rate_limit, where `{"type": "AND", "values": []}` reads like
    # "cap everything" but caps nothing (omitting filter_group entirely is how to
    # match all logs).
    VACUOUS_FILTER_GROUPS = [
        ("outer_empty", {"type": "AND", "values": []}),
        ("inner_empty", {"type": "AND", "values": [{"type": "AND", "values": []}]}),
        (
            "empty_group_beside_leaf",
            {
                "type": "AND",
                "values": [
                    {
                        "type": "AND",
                        "values": [
                            {
                                "key": "service.name",
                                "operator": "exact",
                                "value": "api",
                                "type": "log_resource_attribute",
                            },
                            {"type": "OR", "values": []},
                        ],
                    }
                ],
            },
        ),
    ]

    @parameterized.expand(
        [
            (f"{rule_type}_{shape_label}", rule_type, base_config, shape)
            for shape_label, shape in VACUOUS_FILTER_GROUPS
            for rule_type, base_config in [("path_drop", {"patterns": []}), ("rate_limit", {"kb_per_second": 100})]
        ]
    )
    def test_create_rejects_vacuous_filter_group(self, _label, rule_type, base_config, vacuous):
        response = self.client.post(
            self.base_url,
            self._payload(rule_type=rule_type, config={**base_config, "filter_group": vacuous}),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "at least one filter" in str(response.json()), response.json()

    def test_patch_unrelated_fields_succeeds_when_stored_filter_group_is_vacuous(self):
        # Rows that predate the vacuous-group validator may carry an empty group;
        # a PATCH that doesn't rewrite config (e.g. disabling the rule) must not 400.
        rule = LogsExclusionRule.objects.create(
            team_id=self.team.pk,
            name="legacy empty group",
            enabled=True,
            priority=0,
            rule_type=LogsExclusionRule.RuleType.RATE_LIMIT,
            config={"kb_per_second": 100, "filter_group": {"type": "AND", "values": []}},
        )
        response = self.client.patch(f"{self.base_url}{rule.id}/", {"enabled": False}, format="json")
        assert response.status_code == status.HTTP_200_OK, response.json()
        assert response.json()["enabled"] is False

    def test_create_path_drop_rejects_filter_group_nested_too_deeply(self):
        # 20 nested AND groups around a single leaf — well past the cap of 16.
        # Worker recurses per record, so an unbounded depth is a stack-overflow + CPU footgun.
        node = {
            "type": "AND",
            "values": [{"key": "service.name", "operator": "exact", "value": "api", "type": "log_resource_attribute"}],
        }
        for _ in range(20):
            node = {"type": "AND", "values": [node]}
        response = self.client.post(
            self.base_url,
            self._payload(config={"patterns": [], "filter_group": node}),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "nested too deeply" in str(response.json()), response.json()

    def test_create_path_drop_rejects_filter_group_with_too_many_nodes(self):
        # A shallow group with 300 sibling leaves passes the depth check but
        # forces the ingestion worker to evaluate every leaf on every log
        # record. MAX_FILTER_GROUP_NODES (256) is enforced server-side.
        leaves = [
            {"key": "service.name", "operator": "exact", "value": f"svc-{i}", "type": "log_resource_attribute"}
            for i in range(300)
        ]
        filter_group = {"type": "AND", "values": [{"type": "AND", "values": leaves}]}
        response = self.client.post(
            self.base_url,
            self._payload(config={"patterns": [], "filter_group": filter_group}),
            format="json",
        )
        assert response.status_code == status.HTTP_400_BAD_REQUEST, response.json()
        assert "too many nodes" in str(response.json()), response.json()
