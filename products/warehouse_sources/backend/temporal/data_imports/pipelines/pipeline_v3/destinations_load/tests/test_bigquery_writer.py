import pytest
from unittest.mock import MagicMock

from google.api_core.exceptions import NotFound

from products.warehouse_sources.backend.temporal.data_imports.destinations.contracts import DestinationRunContext
from products.warehouse_sources.backend.temporal.data_imports.pipelines.pipeline_v3.destinations_load.writers.bigquery import (
    _OWNERSHIP_LABEL_KEY,
    BigQueryDestinationWriter,
    UnrelatedTableExistsError,
)


def _ctx(schema_id: str = "schema") -> DestinationRunContext:
    return DestinationRunContext(
        team_id=1,
        schema_id=schema_id,
        source_id="source",
        job_id="job",
        run_uuid="run-a1",
        destination_id="destination",
        destination_type="BigQuery",
        destination_name="test bigquery",
        table_name="charges",
        sync_type="full_refresh",
        config={"project": "proj", "dataset": "dataset"},
    )


def _table(labels: dict | None = None) -> MagicMock:
    table = MagicMock()
    table.labels = labels
    return table


class TestSchemaLabel:
    def test_the_same_schema_id_always_hashes_to_the_same_label(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))

        assert writer._schema_label() == writer._schema_label()

    def test_different_schema_ids_hash_to_different_labels(self) -> None:
        first = BigQueryDestinationWriter(_ctx("schema-a"))
        second = BigQueryDestinationWriter(_ctx("schema-b"))

        assert first._schema_label() != second._schema_label()

    def test_the_label_only_uses_characters_bigquery_labels_allow(self) -> None:
        # Lowercase letters, digits, underscores and dashes only, at most 63 bytes — unlike
        # `schema_id` itself, which carries no such guarantee.
        writer = BigQueryDestinationWriter(_ctx("Schema/With Odd Characters!"))
        label = writer._schema_label()

        assert len(label.encode()) <= 63
        assert all(c.islower() or c.isdigit() or c in "_-" for c in label)


class TestCheckOwnedOrAbsent:
    def test_a_table_that_does_not_exist_is_reported_absent(self) -> None:
        writer = BigQueryDestinationWriter(_ctx())
        client = MagicMock()
        client.get_table.side_effect = NotFound("no such table")

        assert writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it") is True

    def test_a_table_this_schema_marked_owned_is_reported_present_but_not_absent(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))
        client = MagicMock()
        client.get_table.return_value = _table({_OWNERSHIP_LABEL_KEY: writer._schema_label()})

        assert writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it") is False

    def test_a_table_with_no_labels_at_all_raises(self) -> None:
        writer = BigQueryDestinationWriter(_ctx())
        client = MagicMock()
        client.get_table.return_value = _table(None)

        with pytest.raises(UnrelatedTableExistsError):
            writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it")

    def test_a_table_owned_by_a_different_schema_raises(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))
        other = BigQueryDestinationWriter(_ctx("schema-b"))
        client = MagicMock()
        client.get_table.return_value = _table({_OWNERSHIP_LABEL_KEY: other._schema_label()})

        with pytest.raises(UnrelatedTableExistsError):
            writer._check_owned_or_absent(client, "proj.dataset.charges", "write to it")


class TestMarkOwned:
    def test_marking_a_table_owned_preserves_its_other_labels(self) -> None:
        writer = BigQueryDestinationWriter(_ctx("schema-a"))
        client = MagicMock()
        client.get_table.return_value = _table({"team": "data"})

        writer._mark_owned(client, "proj.dataset.charges")

        (updated_table, fields), _kwargs = client.update_table.call_args
        assert fields == ["labels"]
        assert updated_table.labels == {"team": "data", _OWNERSHIP_LABEL_KEY: writer._schema_label()}
