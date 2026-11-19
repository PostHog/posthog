from posthog.test.base import BaseTest
from unittest.mock import patch

from parameterized import parameterized

from posthog.models.group.group import Group

from products.growth.backend.enrichment.bridge import (
    OrganizationBridgeInputs,
    OrganizationGroupTypeMissing,
    WizardBridgeInputs,
    read_organization_bridge_inputs,
)

_ORGANIZATION_GROUP_TYPES = [{"group_type": "organization", "group_type_index": 3}]


class TestEnrichmentBridge(BaseTest):
    def _read(self, group, group_types=_ORGANIZATION_GROUP_TYPES, region="US", scan_found=False):
        with (
            patch("products.growth.backend.enrichment.bridge.get_instance_region", return_value=region),
            patch("products.growth.backend.enrichment.bridge.Team.objects.get", return_value=self.team),
            patch(
                "products.growth.backend.enrichment.bridge.get_group_types_for_project",
                return_value=group_types,
            ),
            patch("products.growth.backend.enrichment.bridge.get_group_by_key", return_value=group) as get_group,
            patch(
                "products.growth.backend.enrichment.bridge.wizard_facade.organization_has_detected_tool",
                return_value=scan_found,
            ) as self.scan_lookup,
        ):
            return read_organization_bridge_inputs(organization_id="org-1"), get_group

    @parameterized.expand([("eu", "EU"), ("self_hosted", None)])
    def test_non_us_regions_skip_the_lookup_entirely(self, _name, region):
        inputs, get_group = self._read(Group(group_properties={"wizard_ai_sdk_detected": True}), region=region)

        assert inputs == OrganizationBridgeInputs()
        get_group.assert_not_called()

    def test_reads_the_organization_group_by_its_type_index_and_key(self):
        inputs, get_group = self._read(Group(group_properties={"wizard_ai_sdk_detected": True}))

        assert inputs == OrganizationBridgeInputs(wizard=WizardBridgeInputs(ai_sdk_detected=True))
        assert get_group.call_args.kwargs["group_type_index"] == 3
        assert get_group.call_args.kwargs["group_key"] == "org-1"

    def test_org_with_no_group_yet_reads_as_all_absent(self):
        inputs, _ = self._read(None)
        assert inputs == OrganizationBridgeInputs()

    @parameterized.expand(
        [
            ("stamp_only", Group(group_properties={"wizard_ai_sdk_detected": True}), False, True),
            ("scan_only", Group(group_properties={}), True, True),
            ("scan_with_no_group_yet", None, True, True),
            ("neither", Group(group_properties={}), False, False),
            ("non_boolean_stamp", Group(group_properties={"wizard_ai_sdk_detected": "true"}), False, False),
        ]
    )
    def test_wizard_input_combines_the_old_stamp_with_stored_scans(self, _name, group, scan_found, expected):
        inputs, _ = self._read(group, scan_found=scan_found)

        assert inputs.wizard == WizardBridgeInputs(ai_sdk_detected=expected)
        if self.scan_lookup.called:
            assert self.scan_lookup.call_args.kwargs["organization_id"] == "org-1"
            assert "OpenAI" in self.scan_lookup.call_args.kwargs["kinds"]

    def test_missing_organization_group_type_raises_rather_than_reading_as_absent(self):
        with self.assertRaises(OrganizationGroupTypeMissing):
            self._read(Group(group_properties={}), group_types=[{"group_type": "project", "group_type_index": 0}])
