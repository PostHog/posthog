from copy import deepcopy
from io import StringIO

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase

from parameterized import parameterized
from pydantic import JsonValue

from products.signals.backend.facade.filter_catalog import SignalFilterField, get_filter_catalog
from products.signals.backend.filter_catalog_schema import validate_catalog_bundle
from products.signals.backend.filter_catalog_seeds import LINEAR_ISSUE_SEED
from products.signals.backend.models import SignalFilterCatalogVersion, SignalFilterSourceDefinition


def catalog_field(**changes: JsonValue) -> dict[str, JsonValue]:
    return {
        "name": "category_name",
        "type": "string",
        "description": "The candidate's category name.",
        "binding": {"kind": "json_path", "column": "category", "path": ["name"]},
        "missing_value": "null",
        "malformed_value": "error",
        **changes,
    }


def catalog_bundle(**changes: JsonValue) -> dict[str, JsonValue]:
    return {
        "schema_version": 1,
        "fields": [catalog_field()],
        "starter_expressions": ["category_name IS NULL"],
        "provenance": {"origin": "manual"},
        "overrides": {"descriptions": True},
        **changes,
    }


class TestCatalogBundle(SimpleTestCase):
    @parameterized.expand(
        [
            ("column", {"kind": "column", "column": "category"}, "string", "null"),
            ("json_path", {"kind": "json_path", "column": "category", "path": ["name"]}, "string", "null"),
            (
                "array",
                {"kind": "json_array_map", "column": "tags", "array_path": ["items"], "value_path": ["name"]},
                "array<string>",
                "empty_array",
            ),
        ]
    )
    def test_supported_recipe_shapes(self, _name: str, binding: JsonValue, field_type: str, missing: str) -> None:
        validate_catalog_bundle(
            catalog_bundle(fields=[catalog_field(binding=binding, type=field_type, missing_value=missing)])
        )

    @parameterized.expand(
        [
            ("unknown_recipe", catalog_bundle(fields=[catalog_field(binding={"kind": "sql", "expression": "1"})])),
            (
                "extra_recipe_key",
                catalog_bundle(fields=[catalog_field(binding={"kind": "column", "column": "category", "sql": "1"})]),
            ),
            (
                "path_depth",
                catalog_bundle(
                    fields=[catalog_field(binding={"kind": "json_path", "column": "category", "path": ["x"] * 9})]
                ),
            ),
            ("unknown_type", catalog_bundle(fields=[catalog_field(type="object")])),
            (
                "array_recipe_for_scalar",
                catalog_bundle(
                    fields=[
                        catalog_field(
                            binding={
                                "kind": "json_array_map",
                                "column": "tags",
                                "array_path": [],
                                "value_path": ["name"],
                            }
                        )
                    ]
                ),
            ),
            ("missing_array_for_scalar", catalog_bundle(fields=[catalog_field(missing_value="empty_array")])),
            ("malformed_as_missing", catalog_bundle(fields=[catalog_field(malformed_value="null")])),
            ("duplicate_name", catalog_bundle(fields=[catalog_field(), catalog_field()])),
            ("bad_identifier", catalog_bundle(fields=[catalog_field(name="category.name")])),
            ("starter_type", catalog_bundle(starter_expressions=[False])),
            ("unknown_schema", catalog_bundle(schema_version=2)),
            ("too_many_fields", catalog_bundle(fields=[catalog_field(name=f"field_{index}") for index in range(257)])),
            ("oversized", catalog_bundle(provenance={"note": "x" * 131072})),
        ]
    )
    def test_invalid_bundle(self, _name: str, bundle: object) -> None:
        with self.assertRaises(ValidationError):
            validate_catalog_bundle(bundle)

    def test_metadata_nesting_is_bounded(self) -> None:
        value: JsonValue = "origin"
        for _ in range(20):
            value = {"nested": value}
        with self.assertRaises(ValidationError):
            validate_catalog_bundle(catalog_bundle(provenance={"origin": value}))


class TestFilterCatalogPersistence(TestCase):
    source: SignalFilterSourceDefinition
    catalog: SignalFilterCatalogVersion

    @classmethod
    def setUpTestData(cls) -> None:
        cls.source = SignalFilterSourceDefinition.objects.create(
            source_product="example_tracker", source_type="issue", adapter_kind="warehouse"
        )
        cls.catalog = SignalFilterCatalogVersion.objects.create(source=cls.source, version=1, bundle=catalog_bundle())

    def test_activation_and_rollback_retain_versions(self) -> None:
        second = SignalFilterCatalogVersion.objects.create(source=self.source, version=2, bundle=catalog_bundle())
        self.source.activate(second)
        self.source.refresh_from_db()
        self.assertEqual(self.source.active_catalog_version_id, second.pk)
        self.assertFalse(self.source.filter_query_eligible)
        self.source.activate(self.catalog)
        self.source.refresh_from_db()
        self.assertEqual(self.source.active_catalog_version_id, self.catalog.pk)
        self.assertEqual(self.source.catalog_versions.count(), 2)

    def test_unsaved_version_cannot_be_activated(self) -> None:
        with self.assertRaises(ValidationError):
            self.source.activate(SignalFilterCatalogVersion(source=self.source, version=2, bundle=catalog_bundle()))

    def test_cross_source_activation_preserves_active_version(self) -> None:
        self.source.activate(self.catalog)
        other = SignalFilterSourceDefinition.objects.create(
            source_product="another_tracker", source_type="issue", adapter_kind="warehouse"
        )
        other_catalog = SignalFilterCatalogVersion.objects.create(source=other, version=1, bundle=catalog_bundle())
        with self.assertRaises(ValidationError):
            self.source.activate(other_catalog)
        self.source.refresh_from_db()
        self.assertEqual(self.source.active_catalog_version_id, self.catalog.pk)

    @parameterized.expand(["add", "set"])
    def test_reverse_relation_cannot_reassign_active_version(self, operation: str) -> None:
        self.source.activate(self.catalog)
        other = SignalFilterSourceDefinition.objects.create(
            source_product="another_tracker", source_type="issue", adapter_kind="warehouse"
        )
        with self.assertRaises(ValidationError):
            if operation == "add":
                other.catalog_versions.add(self.catalog)
            else:
                other.catalog_versions.set([self.catalog])
        self.catalog.refresh_from_db()
        self.source.refresh_from_db()
        self.assertEqual(self.catalog.source_id, self.source.pk)
        self.assertEqual(self.source.active_catalog_version_id, self.catalog.pk)

    @parameterized.expand(["bundle", "version", "source_id"])
    def test_published_version_is_immutable(self, field: str) -> None:
        original = deepcopy(self.catalog.bundle)
        setattr(self.catalog, field, {"changed": True} if field == "bundle" else 999)
        with self.assertRaises(ValidationError):
            self.catalog.save()
        self.catalog.refresh_from_db()
        self.assertEqual(self.catalog.bundle, original)
        self.assertEqual(self.catalog.version, 1)
        self.assertEqual(self.catalog.source_id, self.source.pk)

    def test_invalid_bundle_cannot_be_saved(self) -> None:
        with self.assertRaises(ValidationError):
            SignalFilterCatalogVersion.objects.create(source=self.source, version=2, bundle={})

    @parameterized.expand(["source_product", "source_type", "adapter_kind"])
    def test_source_identity_is_immutable(self, field: str) -> None:
        setattr(self.source, field, "changed")
        with self.assertRaises(ValidationError):
            self.source.save()

    def test_eligibility_requires_active_catalog(self) -> None:
        self.source.filter_query_eligible = True
        with self.assertRaises(ValidationError):
            self.source.save()

    def test_duplicate_source_and_version_are_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            SignalFilterSourceDefinition.objects.create(
                source_product="example_tracker", source_type="issue", adapter_kind="warehouse"
            )
        with self.assertRaises(ValidationError):
            SignalFilterCatalogVersion.objects.create(source=self.source, version=1, bundle=catalog_bundle())
        with self.assertRaises(IntegrityError), transaction.atomic():
            duplicate = SignalFilterCatalogVersion(source=self.source, version=1, bundle=catalog_bundle())
            super(SignalFilterCatalogVersion, duplicate).save(force_insert=True)

    def test_bulk_writes_and_deletion_cannot_bypass_invariants(self) -> None:
        with self.assertRaises(ValidationError):
            SignalFilterCatalogVersion.objects.filter(pk=self.catalog.pk).update(bundle={})
        with self.assertRaises(ValidationError):
            SignalFilterCatalogVersion.objects.bulk_create(
                [SignalFilterCatalogVersion(source=self.source, version=2, bundle={})]
            )
        with self.assertRaises(ValidationError):
            SignalFilterSourceDefinition.objects.filter(pk=self.source.pk).update(active_catalog_version_id=999)
        with self.assertRaises(ValidationError):
            self.catalog.delete()
        with self.assertRaises(ValidationError):
            SignalFilterCatalogVersion.objects.filter(pk=self.catalog.pk).delete()


def publish(bundle: dict[str, JsonValue]) -> None:
    SignalFilterSourceDefinition.publish(
        source_product="linear",
        source_type="issue",
        adapter_kind=SignalFilterSourceDefinition.AdapterKind.WAREHOUSE,
        initial_rollout_state=SignalFilterSourceDefinition.RolloutState.INTERNAL,
        bundle=bundle,
    )


class TestFilterCatalogPublication(TestCase):
    def test_publish_is_idempotent_and_keeps_rollout_decisions(self) -> None:
        self.assertIsNone(get_filter_catalog(source_product="linear", source_type="issue"))
        call_command("publish_signal_filter_catalogs", stdout=StringIO())
        call_command("publish_signal_filter_catalogs", stdout=StringIO())
        source = SignalFilterSourceDefinition.objects.get(source_product="linear", source_type="issue")
        self.assertEqual(source.catalog_versions.count(), 1)
        self.assertEqual(source.rollout_state, "internal")
        self.assertFalse(source.filter_query_eligible)

        source.rollout_state = SignalFilterSourceDefinition.RolloutState.ENABLED
        source.save()
        revised = deepcopy(LINEAR_ISSUE_SEED.bundle)
        revised["starter_expressions"] = ["assignee_id IS NULL"]
        publish(revised)

        source.refresh_from_db()
        self.assertEqual(source.rollout_state, "enabled")
        self.assertEqual(source.catalog_versions.count(), 2)
        catalog = get_filter_catalog(source_product="linear", source_type="issue")
        assert catalog is not None
        self.assertEqual(catalog.version, 2)
        self.assertEqual(catalog.starter_expressions, ("assignee_id IS NULL",))
        self.assertEqual(
            catalog.fields[0],
            SignalFilterField(name="team_id", type="string", description="ID of the Linear team the issue belongs to."),
        )

    @parameterized.expand(
        [
            ("unknown_starter_field", {"starter_expressions": ["category_id IS NULL"]}),
            ("starter_not_boolean", {"starter_expressions": ["priority"]}),
            ("unexecutable_field_type", {"fields": [catalog_field(type="number")], "starter_expressions": []}),
        ]
    )
    def test_unfilterable_catalog_is_not_published(self, _name: str, changes: dict[str, JsonValue]) -> None:
        with self.assertRaises(ValidationError):
            publish({**LINEAR_ISSUE_SEED.bundle, **changes})
        self.assertFalse(SignalFilterSourceDefinition.objects.exists())
