from typing import Any

from posthog.test.base import TestMigrations


def prop(operator: str, value: Any) -> dict:
    return {"key": "version", "type": "person", "operator": operator, "value": value}


def group(*properties: dict) -> dict:
    return {"properties": list(properties), "rollout_percentage": 100, "variant": None}


class StringifyNumericComparisonValuesMigrationTest(TestMigrations):
    migrate_from = "0020_alter_featureflag_created_by_alter_featureflag_team_and_more"
    migrate_to = "0021_stringify_numeric_comparison_values"

    CLASS_DATA_LEVEL_SETUP = False

    @property
    def app(self) -> str:
        return "feature_flags"

    def setUpBeforeMigration(self, apps: Any) -> None:
        Organization = apps.get_model("posthog", "Organization")
        Project = apps.get_model("posthog", "Project")
        Team = apps.get_model("posthog", "Team")
        FeatureFlag = apps.get_model("feature_flags", "FeatureFlag")

        org = Organization.objects.create(name="Test Organization")
        project = Project.objects.create(id=999994, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        def make_flag(key: str, filters: dict, **kwargs: Any) -> Any:
            return FeatureFlag.objects.create(team=team, created_by=None, key=key, filters=filters, **kwargs)

        self.int_id = make_flag("int-value", {"groups": [group(prop("gte", 5))]}).id
        self.float_id = make_flag("float-value", {"groups": [group(prop("lt", 1.5))]}).id
        self.every_operator_id = make_flag(
            "every-operator",
            {"groups": [group(prop("gt", 1), prop("gte", 2), prop("lt", 3), prop("lte", 4))]},
        ).id
        self.already_string_id = make_flag("already-string", {"groups": [group(prop("gte", "5"))]}).id
        # bool subclasses int, and "True" is not a number the evaluators can compare.
        self.bool_id = make_flag("bool-value", {"groups": [group(prop("gte", True))]}).id
        # The same rule covers these, but picking one entry from a list changes who is targeted.
        self.list_icontains_id = make_flag("list-icontains", {"groups": [group(prop("icontains", ["a", "b"]))]}).id
        self.number_on_other_operator_id = make_flag("number-on-exact", {"groups": [group(prop("exact", 5))]}).id
        self.soft_deleted_id = make_flag("soft-deleted", {"groups": [group(prop("gte", 7))]}, deleted=True).id

        self.junk_ids = [
            make_flag("junk-groups", {"groups": {}}).id,
            make_flag("junk-group-entry", {"groups": ["nope"]}).id,
            make_flag("junk-properties", {"groups": [{"properties": "nope"}]}).id,
            make_flag("junk-property-entry", {"groups": [{"properties": ["nope"]}]}).id,
        ]

    def _properties(self, flag_id: int) -> list[dict]:
        assert self.apps is not None
        FeatureFlag = self.apps.get_model("feature_flags", "FeatureFlag")
        return FeatureFlag.objects.get(id=flag_id).filters["groups"][0]["properties"]

    def test_rewrites_numbers_as_strings(self) -> None:
        assert self._properties(self.int_id)[0]["value"] == "5"
        assert self._properties(self.float_id)[0]["value"] == "1.5"

    def test_covers_every_numeric_comparison_operator(self) -> None:
        assert [p["value"] for p in self._properties(self.every_operator_id)] == ["1", "2", "3", "4"]

    def test_leaves_values_it_must_not_change(self) -> None:
        assert self._properties(self.already_string_id)[0]["value"] == "5"
        assert self._properties(self.bool_id)[0]["value"] is True
        assert self._properties(self.list_icontains_id)[0]["value"] == ["a", "b"]
        assert self._properties(self.number_on_other_operator_id)[0]["value"] == 5

    def test_covers_soft_deleted_flags(self) -> None:
        assert self._properties(self.soft_deleted_id)[0]["value"] == "7"

    def test_skips_malformed_filters_without_raising(self) -> None:
        assert self.apps is not None
        FeatureFlag = self.apps.get_model("feature_flags", "FeatureFlag")
        assert FeatureFlag.objects.get(id=self.junk_ids[0]).filters == {"groups": {}}
        assert FeatureFlag.objects.get(id=self.junk_ids[1]).filters == {"groups": ["nope"]}
        assert FeatureFlag.objects.get(id=self.junk_ids[2]).filters["groups"][0]["properties"] == "nope"
        assert FeatureFlag.objects.get(id=self.junk_ids[3]).filters["groups"][0]["properties"] == ["nope"]
