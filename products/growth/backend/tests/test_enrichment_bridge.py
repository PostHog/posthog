from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.group.group import Group

from products.growth.backend.enrichment.bridge import (
    ClayBridgeInputs,
    OrganizationBridgeInputs,
    OrganizationGroupTypeMissing,
    WizardBridgeInputs,
    read_organization_bridge_inputs,
)

_ORGANIZATION_GROUP_TYPES = [{"group_type": "organization", "group_type_index": 3}]


class TestEnrichmentBridge(BaseTest):
    def _read(self, group, group_types=_ORGANIZATION_GROUP_TYPES, region="US"):
        with (
            patch("products.growth.backend.enrichment.bridge.get_instance_region", return_value=region),
            patch("products.growth.backend.enrichment.bridge.Team.objects.get", return_value=self.team),
            patch(
                "products.growth.backend.enrichment.bridge.get_group_types_for_project",
                return_value=group_types,
            ),
            patch("products.growth.backend.enrichment.bridge.get_group_by_key", return_value=group) as get_group,
        ):
            return read_organization_bridge_inputs(organization_id="org-1"), get_group

    @parameterized.expand([("eu", "EU"), ("self_hosted", None)])
    def test_non_us_regions_skip_the_lookup_entirely(self, _name, region):
        inputs, get_group = self._read(Group(group_properties={"icp_company_type": "private"}), region=region)

        assert inputs == OrganizationBridgeInputs()
        get_group.assert_not_called()

    def test_reads_score_inputs_off_the_organization_group(self):
        group = Group(
            group_properties={
                "icp_est_revenue": 25_000_000,
                "icp_company_type": "private",
                "icp_employees": 750,
                "wizard_ai_sdk_detected": True,
            }
        )
        inputs, get_group = self._read(group)

        assert inputs == OrganizationBridgeInputs(
            clay=ClayBridgeInputs(est_revenue=25_000_000.0, clay_processed=True),
            wizard=WizardBridgeInputs(ai_sdk_detected=True),
        )
        assert get_group.call_args.kwargs["group_type_index"] == 3
        assert get_group.call_args.kwargs["group_key"] == "org-1"

    def test_org_with_no_group_yet_reads_as_all_absent(self):
        inputs, _ = self._read(None)
        assert inputs == OrganizationBridgeInputs()

    def test_group_without_clays_columns_reads_as_all_absent(self):
        inputs, _ = self._read(Group(group_properties={"icp_employees": 750}))
        assert inputs.clay == ClayBridgeInputs()

    def test_clay_processed_true_even_when_the_company_type_value_itself_is_unusable(self):
        # clay_processed is a raw key-presence check, not the coerced value — Clay fills this
        # column on essentially every row it writes, so presence alone is the ran/didn't-run signal.
        inputs, _ = self._read(Group(group_properties={"icp_company_type": 12}))
        assert inputs.clay.clay_processed is True

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
        assert inputs.clay.est_revenue == expected

    def test_non_boolean_wizard_value_reads_as_false(self):
        inputs, _ = self._read(Group(group_properties={"wizard_ai_sdk_detected": "true"}))
        assert inputs.wizard == WizardBridgeInputs()

    def test_missing_organization_group_type_raises_rather_than_reading_as_absent(self):
        with self.assertRaises(OrganizationGroupTypeMissing):
            self._read(Group(group_properties={}), group_types=[{"group_type": "project", "group_type_index": 0}])
