from types import SimpleNamespace
from typing import cast

from posthog.test.base import APIBaseTest
from unittest.mock import Mock, patch

from rest_framework.request import Request

from products.signals.backend.report_metric_access import ReportMetricAccessPolicy


class TestReportMetricAccessPolicy(APIBaseTest):
    def _policy(
        self,
        scopes: list[str],
        *,
        allowed: dict[str, set[int]] | None = None,
        blocked: dict[str, set[int]] | None = None,
    ) -> ReportMetricAccessPolicy:
        request = cast(Request, SimpleNamespace(user=self.user, successful_authenticator=object()))
        with (
            patch("products.signals.backend.report_metric_access.get_authenticator_scopes", return_value=scopes),
            patch(
                "products.signals.backend.report_metric_access.get_restricted_properties_with_group_type_index_for_team",
                return_value=[],
            ),
        ):
            policy = ReportMetricAccessPolicy(request=request, team=self.team)

        allowed = allowed or {}
        blocked = blocked or {}
        access_control = Mock()
        access_control.blocked_resource_ids_by_scope = {
            resource: frozenset(str(resource_id) for resource_id in resource_ids)
            for resource, resource_ids in blocked.items()
        }
        access_control.allowlisted_resource_ids_by_scope = {
            resource: frozenset(str(resource_id) for resource_id in resource_ids)
            for resource, resource_ids in allowed.items()
        }
        access_control.has_resource_access.side_effect = lambda resource: resource not in allowed
        policy.__dict__["_user_access_control"] = access_control
        policy.__dict__["_viewer_property_restrictions"] = frozenset()
        policy.__dict__["_materializer_property_restrictions"] = frozenset()
        return policy

    def _metric(self, **source_fields: object) -> dict[str, object]:
        source = {
            "kind": "TrendsQuery",
            "series": [{"kind": "EventsNode", "event": "$pageview", "math": "dau"}],
            **source_fields,
        }
        return {"query": {"kind": "InsightVizNode", "source": source}}

    def test_allows_ordinary_filters_in_each_supported_location(self) -> None:
        ordinary_filter = {"type": "event", "key": "$browser", "operator": "exact", "value": "Chrome"}
        metric = self._metric(
            properties={"type": "AND", "values": [{"type": "OR", "values": [ordinary_filter]}]},
            series=[
                {
                    "kind": "EventsNode",
                    "event": "$pageview",
                    "math": "dau",
                    "properties": [ordinary_filter],
                    "fixedProperties": [{"type": "person", "key": "plan", "value": "free"}],
                }
            ],
        )

        policy = self._policy(["query:read", "event_definition:read"])

        assert policy.may_read_query(metric)
        assert policy.may_read_snapshot(metric)

    def test_requires_scopes_and_object_access_for_nested_cohorts(self) -> None:
        metric = self._metric(
            properties={
                "type": "AND",
                "values": [{"type": "OR", "values": [{"type": "cohort", "key": "id", "value": 12}]}],
            }
        )

        assert not self._policy(["query:read", "event_definition:read"]).may_read_query(metric)
        assert not self._policy(
            ["query:read", "event_definition:read", "cohort:read"], allowed={"cohort": {13}}
        ).may_read_query(metric)
        assert not self._policy(
            ["query:read", "event_definition:read", "cohort:read"], allowed={"cohort": {12}}
        ).may_read_query(metric)

    def test_checks_cohorts_in_series_properties_and_fixed_properties(self) -> None:
        for field in ("properties", "fixedProperties"):
            with self.subTest(field=field):
                metric = self._metric(
                    series=[
                        {
                            "kind": "EventsNode",
                            "event": "$pageview",
                            "math": "dau",
                            field: [{"type": "cohort", "key": "id", "value": 12}],
                        }
                    ]
                )

                assert not self._policy(["query:read", "event_definition:read"]).may_read_snapshot(metric)

    def test_checks_cohorts_in_source_fixed_properties(self) -> None:
        metric = self._metric(fixedProperties=[{"type": "cohort", "key": "id", "value": 12}])

        assert not self._policy(["query:read", "event_definition:read"]).may_read_snapshot(metric)

    def test_requires_scope_and_object_access_for_conversion_action(self) -> None:
        metric = self._metric(conversionGoal={"actionId": 42})

        assert not self._policy(["query:read", "event_definition:read"]).may_read_query(metric)
        assert not self._policy(
            ["query:read", "event_definition:read", "action:read"], allowed={"action": {41}}
        ).may_read_query(metric)
        assert not self._policy(
            ["query:read", "event_definition:read", "action:read"], blocked={"action": {42}}
        ).may_read_query(metric)
        assert self._policy(
            ["query:read", "event_definition:read", "action:read"], allowed={"action": {42}}
        ).may_read_query(metric)

    def test_rejects_unknown_filter_and_resource_shapes(self) -> None:
        invalid_filters = [
            {"type": "future_resource", "key": "id", "value": 12},
            {"type": "cohort", "key": "name", "value": 12},
            {"type": "AND", "values": "not-a-list"},
            {"type": "hogql", "key": "properties.secret"},
            {"type": [], "key": "id", "value": 12},
            {"type": {}, "key": "id", "value": 12},
        ]

        policy = self._policy(["query:read", "event_definition:read", "cohort:read"])
        for property_filter in invalid_filters:
            with self.subTest(property_filter=property_filter):
                assert not policy.may_read_query(self._metric(properties=[property_filter]))

        assert not policy.may_read_query(self._metric(conversionGoal={"actionId": 42, "futureField": True}))
        assert not policy.may_read_query(self._metric(conversionGoal={"futureResourceId": 42}))

    def test_rejects_property_groups_over_the_depth_limit(self) -> None:
        property_filter: dict[str, object] = {"type": "event", "key": "$browser", "value": "Chrome"}
        for _ in range(22):
            property_filter = {"type": "AND", "values": [property_filter]}

        policy = self._policy(["query:read", "event_definition:read"])

        assert not policy.may_read_query(self._metric(properties=property_filter))
