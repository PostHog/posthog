import uuid

from unittest.mock import MagicMock, patch

from django.db import OperationalError

from parameterized import parameterized

from products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table import (
    RepartitionActivityInputs,
    _handle_failure,
)

TEAM_ID = 1
SCHEMA_ID = uuid.uuid4()
SOURCE_ID = uuid.uuid4()
JOB_ID = uuid.uuid4()

MODULE = "products.warehouse_sources.backend.temporal.data_imports.workflow_activities.repartition_table"


def _inputs() -> RepartitionActivityInputs:
    return RepartitionActivityInputs(
        team_id=TEAM_ID, schema_id=str(SCHEMA_ID), job_id=str(JOB_ID), source_id=str(SOURCE_ID)
    )


class TestHandleFailure:
    @parameterized.expand(
        [
            # Where the second (DB) error strikes: on the refresh, or on the attempt-bookkeeping write.
            ("refresh_from_db",),
            ("set_repartition_pending",),
        ]
    )
    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.base_event_props", return_value={})
    @patch(f"{MODULE}.close_old_connections")
    def test_dead_db_connection_does_not_reraise(
        self,
        failing_method: str,
        _close: MagicMock,
        _props: MagicMock,
        mock_capture_event: MagicMock,
        mock_capture_exception: MagicMock,
    ) -> None:
        # The whole point of the outer except block is that a repartition failure never fails the sync.
        # A dead Postgres connection at the same time must not let the handler re-raise (the original
        # incident: refresh_from_db raised OperationalError from _handle_failure and failed the activity).
        schema = MagicMock()
        schema.repartition_pending = None  # fall back to the passed-in pending -> deterministic attempts
        db_error = OperationalError("server closed the connection unexpectedly")
        getattr(schema, failing_method).side_effect = db_error
        original_error = RuntimeError("s3 connect timeout during rewrite")

        _handle_failure(_inputs(), schema, {"attempts": 0}, "resume", original_error, MagicMock())

        # The failed event is still emitted and the original error is still captured...
        mock_capture_event.assert_called_once()
        assert mock_capture_event.call_args[0][0] == "warehouse_repartition_failed"
        # ...along with the residual DB error, so the blip is still observable.
        captured = {type(c.args[0]) for c in mock_capture_exception.call_args_list}
        assert RuntimeError in captured
        assert OperationalError in captured

    @patch(f"{MODULE}.capture_exception")
    @patch(f"{MODULE}.capture_repartition_event")
    @patch(f"{MODULE}.base_event_props", return_value={})
    @patch(f"{MODULE}.close_old_connections")
    def test_recycles_connection_before_orm_access(
        self,
        mock_close: MagicMock,
        _props: MagicMock,
        _event: MagicMock,
        _capture: MagicMock,
    ) -> None:
        # close_old_connections must run before touching the ORM so a stale pooler socket is replaced.
        schema = MagicMock()
        schema.repartition_pending = {"attempts": 1}

        _handle_failure(_inputs(), schema, {"attempts": 1}, "resume", RuntimeError("boom"), MagicMock())

        mock_close.assert_called_once()
        # Attempt recorded on the healthy path: bumped from 1 to 2 and re-persisted.
        schema.set_repartition_pending.assert_called_once()
        assert schema.set_repartition_pending.call_args[0][0]["attempts"] == 2
