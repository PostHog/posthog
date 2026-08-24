from parameterized import parameterized

from products.replay_vision.backend.search import ObservationSearchFilters


class TestObservationFiltersTagClause:
    """Pure-logic clause construction — no DB/ClickHouse, so it runs without the full test stack."""

    @parameterized.expand(
        [
            ("single", ["frustrated_or_confused"]),
            ("multiple", ["abandoned", "completed"]),
            # `where_clauses` registers values verbatim — pre-slugifying is `from_raw`'s job. The SQL
            # slugifies the *stored* side; passing a non-slug here proves the value is not re-normalized.
            ("verbatim_not_renormalized", ["Frustrated Or Confused"]),
        ]
    )
    def test_tags_clause_normalizes_stored_side_and_registers_values(self, _name: str, tags: list[str]) -> None:
        placeholders: dict = {}
        clauses = ObservationSearchFilters(tags=tags).where_clauses(placeholders)

        assert len(clauses) == 1
        # Stored metadata tags are slugified inside the clause (arrayMap) so verbatim-stored tags still match.
        assert clauses[0].startswith("hasAny(")
        assert "arrayMap" in clauses[0]
        # The clause carries no inlined tag value — it lives only in the parameterized placeholder, verbatim.
        assert placeholders["tags"].value == tags
