from typing import Any

from posthog.test.base import TestMigrations

MULTIVARIATE = {
    "variants": [
        {"key": "control", "name": "", "rollout_percentage": 50},
        {"key": "test", "name": "", "rollout_percentage": 50},
    ]
}


def group(**overrides: Any) -> dict:
    return {"properties": [], "rollout_percentage": 100, "variant": None, **overrides}


class CleanInertFilterViolationsMigrationTest(TestMigrations):
    migrate_from = "0013_narrow_whole_rollout_percentages"
    migrate_to = "0014_clean_flag_filters_inert_violations"

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
        project = Project.objects.create(id=999995, organization=org, name="Test Project")
        team = Team.objects.create(organization=org, project=project, name="Test Team")

        def make_flag(key: str, filters: dict, **kwargs: Any) -> Any:
            return FeatureFlag.objects.create(team=team, created_by=None, key=key, filters=filters, **kwargs)

        self.orphan_payload_id = make_flag(
            "orphan-payload",
            {"groups": [group()], "multivariate": MULTIVARIATE, "payloads": {"control": "1", "ghost": "2"}},
        ).id
        self.resolvable_payloads_id = make_flag(
            "resolvable-payloads",
            {
                "groups": [group()],
                "multivariate": MULTIVARIATE,
                "payloads": {"control": "1", "false": "2", "holdout-7": "3", "ghost": "4"},
            },
        ).id
        self.boolean_payloads_id = make_flag(
            "boolean-payloads",
            {"groups": [group()], "payloads": {"true": "1", "false": "2", "holdout-9": "3", "control": "4"}},
        ).id
        self.dangling_variant_id = make_flag(
            "dangling-variant",
            {"groups": [group(variant="ghost"), group(variant="control")], "multivariate": MULTIVARIATE},
        ).id
        self.already_clean_id = make_flag(
            "already-clean",
            {"groups": [group(variant="control")], "multivariate": MULTIVARIATE, "payloads": {"control": "1"}},
        ).id
        self.soft_deleted_id = make_flag(
            "soft-deleted",
            {"groups": [group(variant="ghost")], "multivariate": MULTIVARIATE},
            deleted=True,
        ).id
        self.inactive_id = make_flag(
            "inactive",
            {"groups": [group(variant="ghost")], "multivariate": MULTIVARIATE},
            active=False,
        ).id
        # Rules this migration deliberately does not own.
        self.non_inert_id = make_flag(
            "non-inert",
            {
                "groups": [group(properties=[{"key": "1", "type": "flag", "value": True, "operator": "exact"}])],
                "multivariate": {
                    "variants": [
                        {"key": "a", "name": "", "rollout_percentage": 40},
                        {"key": "b", "name": "", "rollout_percentage": 40},
                        {"key": "c", "name": "", "rollout_percentage": 40},
                    ]
                },
            },
        ).id
        # Every payload key on an encrypted flag is ciphertext, so pruning one destroys a secret.
        self.encrypted_id = make_flag(
            "encrypted",
            {"groups": [group()], "payloads": {"true": "cipher-1", "staging": "cipher-2"}},
            has_encrypted_payloads=True,
        ).id
        self.encrypted_legacy_null_id = make_flag(
            "encrypted-legacy-null",
            {
                "groups": [group(variant="ghost")],
                "multivariate": MULTIVARIATE,
                "payloads": {"control": "1", "ghost": "2"},
            },
            has_encrypted_payloads=None,
        ).id

        # Shapes the scan must skip rather than raise on, which would abort the whole migration.
        self.junk_ids = [
            make_flag("junk-groups", {"groups": {}}).id,
            make_flag("junk-group-entry", {"groups": ["nope"], "multivariate": MULTIVARIATE}).id,
            make_flag(
                "junk-multivariate-list", {"groups": [group()], "multivariate": ["nope"], "payloads": {"x": "1"}}
            ).id,
            make_flag(
                "junk-multivariate-str", {"groups": [group()], "multivariate": "nope", "payloads": {"x": "1"}}
            ).id,
            make_flag("junk-payloads", {"groups": [group()], "payloads": []}).id,
        ]

    def _filters(self, flag_id: int) -> dict:
        assert self.apps is not None
        FeatureFlag = self.apps.get_model("feature_flags", "FeatureFlag")
        return FeatureFlag.objects.get(id=flag_id).filters

    def test_drops_payload_keys_no_evaluation_can_resolve(self) -> None:
        assert self._filters(self.orphan_payload_id)["payloads"] == {"control": "1"}

    def test_keeps_payload_keys_the_evaluator_resolves(self) -> None:
        # "false" is reached by a boolean result and "holdout-N" by the synthesised holdout variant.
        assert self._filters(self.resolvable_payloads_id)["payloads"] == {
            "control": "1",
            "false": "2",
            "holdout-7": "3",
        }
        assert self._filters(self.boolean_payloads_id)["payloads"] == {
            "true": "1",
            "false": "2",
            "holdout-9": "3",
        }

    def test_clears_only_dangling_variant_overrides(self) -> None:
        groups = self._filters(self.dangling_variant_id)["groups"]
        assert groups[0]["variant"] is None
        assert groups[1]["variant"] == "control"

    def test_covers_soft_deleted_and_inactive_flags(self) -> None:
        assert self._filters(self.soft_deleted_id)["groups"][0]["variant"] is None
        assert self._filters(self.inactive_id)["groups"][0]["variant"] is None

    def test_leaves_an_already_clean_flag_untouched(self) -> None:
        assert self._filters(self.already_clean_id) == {
            "groups": [group(variant="control")],
            "multivariate": MULTIVARIATE,
            "payloads": {"control": "1"},
        }

    def test_leaves_violations_it_does_not_own(self) -> None:
        filters = self._filters(self.non_inert_id)
        assert filters["groups"][0]["properties"][0]["operator"] == "exact"
        assert [variant["rollout_percentage"] for variant in filters["multivariate"]["variants"]] == [40, 40, 40]

    def test_leaves_encrypted_flags_alone(self) -> None:
        assert self._filters(self.encrypted_id)["payloads"] == {"true": "cipher-1", "staging": "cipher-2"}

    def test_still_cleans_flags_with_a_null_encrypted_marker(self) -> None:
        filters = self._filters(self.encrypted_legacy_null_id)
        assert filters["payloads"] == {"control": "1"}
        assert filters["groups"][0]["variant"] is None

    def test_skips_malformed_filters_without_raising(self) -> None:
        # Reaching any assertion here means the scan completed; these rows stay as they were.
        assert self._filters(self.junk_ids[0]) == {"groups": {}}
        assert self._filters(self.junk_ids[2])["payloads"] == {"x": "1"}
        assert self._filters(self.junk_ids[3])["payloads"] == {"x": "1"}
        assert self._filters(self.junk_ids[4])["payloads"] == []
