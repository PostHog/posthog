from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.group.group import Group

from products.growth.backend.enrichment.bridge import (
    ClayBridgeInputs,
    OrganizationGroupTypeMissing,
    read_clay_bridge_inputs,
)

_ORGANIZATION_GROUP_TYPES = [{"group_type": "organization", "group_type_index": 3}]


class TestEnrichmentBridge(BaseTest):
    def _read(self, group, group_types=_ORGANIZATION_GROUP_TYPES):
        with (
            patch("products.growth.backend.enrichment.bridge.Team.objects.get", return_value=self.team),
            patch(
                "products.growth.backend.enrichment.bridge.get_group_types_for_project",
                return_value=group_types,
            ),
            patch("products.growth.backend.enrichment.bridge.get_group_by_key", return_value=group) as get_group,
        ):
            return read_clay_bridge_inputs(organization_id="org-1"), get_group

    def test_reads_clays_columns_off_the_organization_group(self):
        group = Group(
            group_properties={
                "icp_est_revenue": 25_000_000,
                "icp_company_type": "private",
                "icp_github_profile_url": "https://github.com/someone",
                "icp_employees": 750,
            }
        )
        inputs, get_group = self._read(group)

        assert inputs == ClayBridgeInputs(
            est_revenue=25_000_000.0,
            company_type="private",
            github_profile_url="https://github.com/someone",
        )
        assert get_group.call_args.kwargs["group_type_index"] == 3
        assert get_group.call_args.kwargs["group_key"] == "org-1"

    def test_org_with_no_group_yet_reads_as_all_absent(self):
        inputs, _ = self._read(None)
        assert inputs == ClayBridgeInputs()

    def test_group_without_clays_columns_reads_as_all_absent(self):
        inputs, _ = self._read(Group(group_properties={"icp_employees": 750}))
        assert inputs == ClayBridgeInputs()

    @parameterized.expand(
        [
            ("json_number", 25_000_000, 25_000_000.0),
            ("float", 25_000_000.5, 25_000_000.5),
            # Clay writes through capture, so a numeric string is possible; JS would coerce it.
            ("numeric_string", "25000000", 25_000_000.0),
            ("padded_string", " 25000000 ", 25_000_000.0),
            ("non_numeric_string", "unknown", None),
            ("empty_string", "", None),
            ("boolean", True, None),
            ("null", None, None),
        ]
    )
    def test_est_revenue_coercion(self, _name, raw, expected):
        inputs, _ = self._read(Group(group_properties={"icp_est_revenue": raw}))
        assert inputs.est_revenue == expected

    @parameterized.expand([("empty_string", "", None), ("non_string", 12, None), ("value", "private", "private")])
    def test_company_type_coercion(self, _name, raw, expected):
        inputs, _ = self._read(Group(group_properties={"icp_company_type": raw}))
        assert inputs.company_type == expected

    def test_missing_organization_group_type_raises_rather_than_reading_as_absent(self):
        with self.assertRaises(OrganizationGroupTypeMissing):
            self._read(Group(group_properties={}), group_types=[{"group_type": "project", "group_type_index": 0}])
