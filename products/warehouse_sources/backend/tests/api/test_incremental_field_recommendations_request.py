from django.test import SimpleTestCase

from parameterized import parameterized

from products.warehouse_sources.backend.facade.incremental_field_model import MAX_TABLES_PER_CALL
from products.warehouse_sources.backend.presentation.views.external_data_source.schema_operations import (
    IncrementalFieldRecommendationsRequestSerializer,
)


def _candidate(name: str) -> dict:
    return {"label": name, "field": name, "type": "timestamp", "field_type": "timestamp"}


class TestIncrementalFieldRecommendationsRequest(SimpleTestCase):
    @parameterized.expand(
        [
            # Every item is invalid, so a child error in the response would mean the items were validated.
            (
                "too_many_tables",
                {"tables": [{"table": 1}] * (MAX_TABLES_PER_CALL + 1)},
                ["tables"],
                MAX_TABLES_PER_CALL,
            ),
            (
                "too_many_candidates",
                {"tables": [{"table": "orders", "incremental_fields": [{"field": 1}] * 17}]},
                ["tables", 0, "incremental_fields"],
                16,
            ),
        ]
    )
    def test_rejects_an_oversized_list_before_validating_its_items(self, _name, data, error_path, limit):
        serializer = IncrementalFieldRecommendationsRequestSerializer(data=data)

        assert not serializer.is_valid()
        errors = serializer.errors
        for key in error_path:
            errors = errors[key]
        assert [str(error) for error in errors] == [f"Ensure this field has no more than {limit} elements."]

    def test_rejects_tables_whose_candidates_together_exceed_one_model_call(self):
        tables = [
            {"table": f"t{n}", "incremental_fields": [_candidate(f"c{i}") for i in range(count)]}
            for n, count in enumerate([16, 16, 1])
        ]
        serializer = IncrementalFieldRecommendationsRequestSerializer(data={"tables": tables})

        assert not serializer.is_valid()
        assert "candidate fields" in str(serializer.errors["tables"][0])

    def test_accepts_a_long_quoted_identifier_verbatim(self):
        name = " " + "nested." * 500 + "updated "
        serializer = IncrementalFieldRecommendationsRequestSerializer(
            data={"tables": [{"table": "orders", "incremental_fields": [_candidate(name), _candidate("id")]}]}
        )

        assert serializer.is_valid(), serializer.errors
        assert serializer.validated_data["tables"][0]["incremental_fields"][0]["field"] == name
