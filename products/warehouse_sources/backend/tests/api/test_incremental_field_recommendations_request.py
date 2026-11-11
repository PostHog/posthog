from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.presentation.views.external_data_source.schema_operations import (
    IncrementalFieldRecommendationsRequestSerializer,
)


def _candidate(name: str) -> dict:
    return {"label": name, "field": name, "type": "timestamp", "field_type": "timestamp"}


class TestIncrementalFieldRecommendationsRequest(SimpleTestCase):
    @parameterized.expand(
        [
            # Every item is invalid, so a child error in the response would mean the items were validated.
            ("too_many_tables", {"tables": [{"table": 1}] * 513}, ["tables"]),
            (
                "too_many_candidates",
                {"tables": [{"table": "orders", "incremental_fields": [{"field": 1}] * 17}]},
                ["tables", 0, "incremental_fields"],
            ),
        ]
    )
    def test_rejects_an_oversized_list_before_validating_its_items(self, _name, data, error_path):
        serializer = IncrementalFieldRecommendationsRequestSerializer(data=data)

        assert not serializer.is_valid()
        errors = serializer.errors
        for key in error_path:
            errors = errors[key]
        assert [str(error) for error in errors] == [
            f"Ensure this field has no more than {512 if error_path == ['tables'] else 16} elements."
        ]

    def test_accepts_a_long_quoted_identifier_verbatim(self):
        name = " " + "nested." * 500 + "updated "
        serializer = IncrementalFieldRecommendationsRequestSerializer(
            data={"tables": [{"table": "orders", "incremental_fields": [_candidate(name), _candidate("id")]}]}
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["tables"][0]["incremental_fields"][0]["field"] == name
