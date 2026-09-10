import uuid
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from posthog.test.base import NonAtomicAPIBaseTest
from unittest.mock import Mock, patch

from django.db import connection, connections, transaction

from rest_framework import status

from products.warehouse_sources.backend.facade.models import ExternalDataSchema, ExternalDataSource
from products.warehouse_sources.backend.temporal.data_imports.sources.common.schema import SourceSchema

LOCK_TIMEOUT_SECONDS = 10


class TestRefreshSchemasSourceLock(NonAtomicAPIBaseTest):
    """Real row locks need two committed connections, so these run on TransactionTestCase. It flushes
    every table between tests, hence CLASS_DATA_LEVEL_SETUP = False to rebuild the fixtures per test."""

    CLASS_DATA_LEVEL_SETUP = False

    def setUp(self) -> None:
        super().setUp()
        self.source = ExternalDataSource.objects.create(
            team_id=self.team.pk,
            source_id=str(uuid.uuid4()),
            connection_id=str(uuid.uuid4()),
            destination_id=str(uuid.uuid4()),
            source_type="Stripe",
            created_by=self.user,
            prefix="test",
            job_inputs={"auth_method": {"selection": "api_key", "stripe_secret_key": "sk_test_123"}},
        )
        self.lock_held = threading.Event()
        self.release_lock = threading.Event()

    def _stub_one_discovered_table(self, mock_get_source: Mock) -> None:
        mock_get_source.return_value.parse_config.return_value = Mock(spec=["to_dict"])
        mock_get_source.return_value.get_schemas.return_value = [
            SourceSchema(name="table_a", supports_incremental=False, supports_append=False)
        ]

    def _hold(self, take_lock: Callable[[], None]) -> None:
        try:
            with transaction.atomic():
                take_lock()
                self.lock_held.set()
                self.release_lock.wait(LOCK_TIMEOUT_SECONDS)
        finally:
            # Also set on the failure path, so the request below never waits for a lock nobody holds.
            self.lock_held.set()
            connections.close_all()

    def _refresh_schemas_while_holding(self, take_lock: Callable[[], None]):
        with ThreadPoolExecutor(max_workers=1) as executor:
            holder = executor.submit(self._hold, take_lock)
            assert self.lock_held.wait(LOCK_TIMEOUT_SECONDS)
            try:
                response = self.client.post(
                    f"/api/projects/{self.team.pk}/external_data_sources/{self.source.pk}/refresh_schemas/"
                )
            finally:
                self.release_lock.set()
            holder.result(timeout=LOCK_TIMEOUT_SECONDS)
        return response

    @patch("products.warehouse_sources.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_is_not_blocked_by_a_child_write_holding_key_share(self, mock_get_source: Mock) -> None:
        self._stub_one_discovered_table(mock_get_source)

        def hold_key_share() -> None:
            # What a sync's schema and job writes take on the source row: those foreign keys are
            # DEFERRABLE INITIALLY DEFERRED, so Postgres runs the referential-integrity check at
            # commit and holds this lock for the commit window.
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT 1 FROM posthog_externaldatasource WHERE id = %s FOR KEY SHARE", [str(self.source.pk)]
                )

        response = self._refresh_schemas_while_holding(hold_key_share)

        assert response.status_code == status.HTTP_200_OK
        assert response.json()["added"] == 1

    @patch("products.warehouse_sources.backend.presentation.views.external_data_source.SOURCE_LOCK_TIMEOUT_MS", 250)
    @patch("products.warehouse_sources.backend.presentation.views.external_data_source.SourceRegistry.get_source")
    def test_refresh_schemas_returns_409_while_another_writer_holds_the_source_row(self, mock_get_source: Mock) -> None:
        self._stub_one_discovered_table(mock_get_source)

        def lock_source_row() -> None:
            ExternalDataSource._base_manager.filter(pk=self.source.pk).select_for_update(no_key=True).get()

        response = self._refresh_schemas_while_holding(lock_source_row)

        assert response.status_code == status.HTTP_409_CONFLICT
        assert "Wait for it to finish" in response.json()["detail"]
        assert not ExternalDataSchema.objects.filter(team_id=self.team.pk, source_id=self.source.pk).exists()
