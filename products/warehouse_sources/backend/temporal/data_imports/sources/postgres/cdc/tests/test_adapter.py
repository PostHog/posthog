import uuid

import pytest
from unittest.mock import MagicMock, patch

import psycopg.errors

from products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter import PostgresCDCAdapter

_ADAPTER = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.cdc.adapter"
_POSTGRES = "products.warehouse_sources.backend.temporal.data_imports.sources.postgres.postgres"


def _source(**cdc_overrides):
    job_inputs = {
        "host": "localhost",
        "port": 5432,
        "database": "app",
        "user": "user",
        "password": "pass",
        "schema": "public",
        **cdc_overrides,
    }
    source = MagicMock()
    source.id = uuid.UUID("019ef4e8-3bfd-0000-63c8-31abf0d57db8")
    source.job_inputs = job_inputs
    return source


def _fake_conn():
    cm = MagicMock()
    cm.return_value.__enter__.return_value = object()
    cm.return_value.__exit__.return_value = None
    return cm


class TestSetupResourcesPreflight:
    @patch(f"{_ADAPTER}.drop_slot_and_publication")
    @patch(f"{_ADAPTER}.create_publication")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_refuses_when_slot_already_exists(
        self, _conn, _slot_exists, _pub_exists, mock_create_slot, mock_create_publication, mock_drop
    ) -> None:
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(), {"cdc_management_mode": "posthog", "cdc_slot_name": "existing_slot"}
        )
        assert fields == {}
        assert error is not None and "already exists" in error
        # Must not create, and must not roll back (drop) a slot it didn't create.
        mock_create_slot.assert_not_called()
        mock_create_publication.assert_not_called()
        mock_drop.assert_not_called()

    @patch(f"{_ADAPTER}.drop_slot_and_publication")
    @patch(f"{_ADAPTER}.create_publication")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=False)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_refuses_when_publication_already_exists(
        self, _conn, _slot_exists, _pub_exists, mock_create_slot, mock_create_publication, mock_drop
    ) -> None:
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(), {"cdc_management_mode": "posthog", "cdc_publication_name": "existing_pub"}
        )
        assert fields == {}
        assert error is not None and "already exists" in error
        mock_create_slot.assert_not_called()
        mock_create_publication.assert_not_called()
        mock_drop.assert_not_called()

    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.create_publication")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_adopts_existing_default_slot_and_publication(
        self, _conn, _slot_exists, _pub_exists, mock_create_publication, mock_create_slot
    ) -> None:
        source = _source()
        fields, error = PostgresCDCAdapter().setup_resources(source, {"cdc_management_mode": "posthog"})

        assert error is None
        assert fields == {
            "cdc_management_mode": "posthog",
            "cdc_slot_name": "posthog_019ef4e83bfd",
            "cdc_publication_name": "posthog_pub_019ef4e83bfd",
        }
        mock_create_slot.assert_not_called()
        mock_create_publication.assert_not_called()

    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.create_publication")
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_recreates_missing_default_publication_when_adopting_slot(
        self, _conn, _slot_exists, _pub_exists, mock_create_publication, mock_create_slot
    ) -> None:
        source = _source()
        fields, error = PostgresCDCAdapter().setup_resources(source, {"cdc_management_mode": "posthog"})

        assert error is None
        assert fields["cdc_slot_name"] == "posthog_019ef4e83bfd"
        assert fields["cdc_publication_name"] == "posthog_pub_019ef4e83bfd"
        mock_create_publication.assert_called_once()
        assert mock_create_publication.call_args.args[1] == "posthog_pub_019ef4e83bfd"
        mock_create_slot.assert_not_called()

    @patch(f"{_ADAPTER}.create_slot", return_value="0/AA")
    @patch(f"{_ADAPTER}.create_publication")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=False)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_adopts_existing_default_publication_and_creates_missing_slot(
        self, _conn, _slot_exists, _pub_exists, mock_create_publication, mock_create_slot
    ) -> None:
        source = _source()
        fields, error = PostgresCDCAdapter().setup_resources(source, {"cdc_management_mode": "posthog"})

        assert error is None
        assert fields["cdc_slot_name"] == "posthog_019ef4e83bfd"
        assert fields["cdc_publication_name"] == "posthog_pub_019ef4e83bfd"
        assert fields["cdc_consistent_point"] == "0/AA"
        mock_create_slot.assert_called_once()
        assert mock_create_slot.call_args.args[1] == "posthog_019ef4e83bfd"
        mock_create_publication.assert_not_called()

    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_self_managed_refuses_when_slot_already_exists(
        self, _conn, _slot_exists, _pub_exists, mock_create, mock_drop
    ) -> None:
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(), {"cdc_management_mode": "self_managed", "cdc_slot_name": "existing_slot"}
        )
        assert fields == {}
        assert error is not None and "already exists" in error
        mock_create.assert_not_called()
        mock_drop.assert_not_called()

    @patch(f"{_ADAPTER}.drop_publication")
    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.create_slot", side_effect=RuntimeError("boom"))
    @patch(f"{_ADAPTER}.create_publication")
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.slot_exists", return_value=False)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_posthog_rolls_back_only_after_verifying_absence(
        self, _conn, _slot_exists, _pub_exists, mock_create_publication, _create_slot, mock_drop_slot, mock_drop_pub
    ) -> None:
        # Publication was created before slot creation failed → only the publication is rolled back.
        fields, error = PostgresCDCAdapter().setup_resources(
            _source(),
            {"cdc_management_mode": "posthog", "cdc_slot_name": "s", "cdc_publication_name": "p"},
        )
        assert fields == {}
        assert error is not None and "boom" in error
        mock_create_publication.assert_called_once()
        mock_drop_slot.assert_not_called()
        mock_drop_pub.assert_called_once()
        assert mock_drop_pub.call_args.args[1] == "p"


class TestRecreateSlot:
    @patch(f"{_ADAPTER}.create_slot_and_publication")
    @patch(f"{_ADAPTER}.create_slot", return_value="0/AA")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_drops_and_recreates_slot_against_existing_publication(
        self, _conn, mock_drop, _pub_exists, mock_create, mock_create_slot_and_pub
    ) -> None:
        source = _source(
            cdc_enabled=True,
            cdc_management_mode="posthog",
            cdc_slot_name="posthog_slot",
            cdc_publication_name="posthog_pub",
        )

        fields = PostgresCDCAdapter().recreate_slot(source, tables=["users", "orders"])

        assert fields == {"cdc_consistent_point": "0/AA"}
        mock_drop.assert_called_once()
        assert mock_drop.call_args.args[1] == "posthog_slot"
        mock_create.assert_called_once()
        assert mock_create.call_args.args[1] == "posthog_slot"
        mock_create_slot_and_pub.assert_not_called()

    @pytest.mark.parametrize(
        "tables,expected_pairs",
        [
            # Bare names fall back to the source's default schema.
            (["users"], [("public", "users")]),
            # A schema-qualified name keeps its own schema; a bare name still uses the default.
            # Regression: previously every table was forced under the source default schema,
            # so `tll.students` became `public."tll.students"` and CREATE PUBLICATION failed.
            (["tll.students", "orders"], [("tll", "students"), ("public", "orders")]),
        ],
    )
    @patch(f"{_ADAPTER}.create_slot_and_publication", return_value="0/BB")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_recreates_publication_qualifying_each_table_by_its_own_schema(
        self, _conn, mock_drop, _pub_exists, mock_create, mock_create_slot_and_pub, tables, expected_pairs
    ) -> None:
        source = _source(
            cdc_enabled=True,
            cdc_management_mode="posthog",
            cdc_slot_name="posthog_slot",
            cdc_publication_name="posthog_pub",
        )

        fields = PostgresCDCAdapter().recreate_slot(source, tables=tables)

        assert fields == {"cdc_consistent_point": "0/BB"}
        mock_create_slot_and_pub.assert_called_once()
        assert mock_create_slot_and_pub.call_args.args[1:3] == ("posthog_slot", "posthog_pub")
        assert mock_create_slot_and_pub.call_args.kwargs["tables"] == expected_pairs
        mock_create.assert_not_called()

    @patch(f"{_ADAPTER}.create_slot_and_publication")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_raises_when_self_managed_publication_missing(
        self, _conn, mock_drop, _pub_exists, mock_create, mock_create_slot_and_pub
    ) -> None:
        source = _source(
            cdc_enabled=True,
            cdc_management_mode="self_managed",
            cdc_slot_name="posthog_slot",
            cdc_publication_name="customer_pub",
        )

        with pytest.raises(RuntimeError, match="does not exist"):
            PostgresCDCAdapter().recreate_slot(source, tables=["users"])

        mock_create.assert_not_called()
        mock_create_slot_and_pub.assert_not_called()

    def test_raises_without_slot_name(self) -> None:
        source = _source(cdc_enabled=True)
        with pytest.raises(RuntimeError, match="no slot name"):
            PostgresCDCAdapter().recreate_slot(source, tables=[])

    @patch(f"{_POSTGRES}.time.sleep")
    @patch(f"{_ADAPTER}.create_slot")
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.drop_slot")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_retries_recreation_after_transient_connection_drop(
        self, _conn, mock_drop, _pub_exists, mock_create_slot, _sleep
    ) -> None:
        # The source terminates our backend mid-recreate (deploy/failover); recovery must reconnect
        # and retry rather than fail the whole run. drop-before-create keeps the retry idempotent.
        mock_create_slot.side_effect = [
            psycopg.errors.AdminShutdown("terminating connection due to administrator command"),
            "0/CC",
        ]
        source = _source(
            cdc_enabled=True,
            cdc_management_mode="posthog",
            cdc_slot_name="posthog_slot",
            cdc_publication_name="posthog_pub",
        )

        fields = PostgresCDCAdapter().recreate_slot(source, tables=["users"])

        assert fields == {"cdc_consistent_point": "0/CC"}
        assert mock_create_slot.call_count == 2
        assert mock_drop.call_count == 2


class TestAlterPublicationMembership:
    @patch(f"{_ADAPTER}.add_table_to_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_add_table_noop_for_self_managed(self, _conn, mock_add) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="self_managed", cdc_publication_name="pub")
        PostgresCDCAdapter().add_table(source, "public", "orders")
        mock_add.assert_not_called()

    @patch(f"{_ADAPTER}.add_table_to_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_add_table_for_posthog_managed(self, _conn, mock_add) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="posthog", cdc_publication_name="pub")
        PostgresCDCAdapter().add_table(source, "public", "orders")
        mock_add.assert_called_once()
        assert mock_add.call_args.args[1:] == ("pub", "public", "orders")

    @patch(f"{_ADAPTER}.remove_table_from_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_remove_table_for_posthog_managed(self, _conn, mock_remove) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="posthog", cdc_publication_name="pub")
        PostgresCDCAdapter().remove_table(source, "analytics", "events")
        mock_remove.assert_called_once()
        assert mock_remove.call_args.args[1:] == ("pub", "analytics", "events")

    @patch(f"{_ADAPTER}.add_table_to_publication")
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_add_table_noop_without_publication(self, _conn, mock_add) -> None:
        source = _source(cdc_enabled=True, cdc_management_mode="posthog")
        PostgresCDCAdapter().add_table(source, "public", "orders")
        mock_add.assert_not_called()


class TestGetStatus:
    @patch(f"{_ADAPTER}.get_publication_tables", return_value=["public.orders", "public.users"])
    @patch(f"{_ADAPTER}.get_slot_lag_bytes", return_value=42)
    @patch(f"{_ADAPTER}.publication_exists", return_value=True)
    @patch(f"{_ADAPTER}.slot_exists", return_value=True)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_includes_published_tables(self, _conn, _slot, _pub, _lag, mock_tables) -> None:
        source = _source(cdc_enabled=True, cdc_slot_name="slot", cdc_publication_name="pub")
        status = PostgresCDCAdapter().get_status(source)
        assert status == {
            "slot_exists": True,
            "publication_exists": True,
            "lag_bytes": 42,
            "published_tables": ["public.orders", "public.users"],
        }
        mock_tables.assert_called_once()
        assert mock_tables.call_args.args[1] == "pub"

    @patch(f"{_ADAPTER}.get_publication_tables")
    @patch(f"{_ADAPTER}.get_slot_lag_bytes", return_value=None)
    @patch(f"{_ADAPTER}.publication_exists", return_value=False)
    @patch(f"{_ADAPTER}.slot_exists", return_value=False)
    @patch(f"{_ADAPTER}.cdc_pg_connection", new_callable=_fake_conn)
    def test_skips_table_lookup_when_publication_missing(self, _conn, _slot, _pub, _lag, mock_tables) -> None:
        source = _source(cdc_enabled=True, cdc_slot_name="slot", cdc_publication_name="pub")
        status = PostgresCDCAdapter().get_status(source)
        assert status["published_tables"] == []
        mock_tables.assert_not_called()
