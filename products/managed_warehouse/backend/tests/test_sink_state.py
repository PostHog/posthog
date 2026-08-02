from uuid import uuid4

import pytest
from freezegun import freeze_time

from django.db import connection
from django.test.utils import CaptureQueriesContext

from products.managed_warehouse.backend.facade import sink_state
from products.managed_warehouse.backend.facade.contracts import DuckgresSinkState, DuckgresSinkStateCreateInput
from products.managed_warehouse.backend.facade.testing import create_sink_state, get_sink_state


@pytest.mark.django_db
def test_mark_sink_state_primed_is_pinned_to_the_backfill_generation() -> None:
    state = create_sink_state(
        DuckgresSinkStateCreateInput(
            team_id=1,
            schema_id=uuid4(),
            state=DuckgresSinkState.BACKFILLING,
            backfill_run_uuid="run-r2",
            chunk_count=2,
        )
    )

    assert not sink_state.mark_sink_state_primed(
        state.schema_id,
        backfill_run_uuid="run-r1",
        chunks_applied=2,
    )
    stale = get_sink_state(state.id)
    assert stale is not None
    assert stale.state == DuckgresSinkState.BACKFILLING
    assert stale.chunks_applied == 0

    assert sink_state.mark_sink_state_primed(
        state.schema_id,
        backfill_run_uuid="run-r2",
        chunks_applied=2,
    )
    primed = get_sink_state(state.id)
    assert primed is not None
    assert primed.state == DuckgresSinkState.PRIMED
    assert primed.chunks_applied == 2


@pytest.mark.django_db
def test_live_apply_stamp_does_not_change_lifecycle_updated_at() -> None:
    with freeze_time("2026-01-01T00:00:00Z"):
        state = create_sink_state(
            DuckgresSinkStateCreateInput(
                team_id=1,
                schema_id=uuid4(),
                state=DuckgresSinkState.PRIMED,
            )
        )

    with freeze_time("2026-01-02T00:00:00Z"):
        sink_state.record_live_batch_applied(state.schema_id)

    stamped = get_sink_state(state.id)
    assert stamped is not None
    assert stamped.updated_at == state.updated_at
    assert stamped.queue_last_applied_at is not None
    assert stamped.queue_last_applied_at.isoformat() == "2026-01-02T00:00:00+00:00"


@pytest.mark.django_db
def test_list_sink_backfill_run_references_selects_only_required_fields() -> None:
    state = create_sink_state(
        DuckgresSinkStateCreateInput(
            team_id=1,
            schema_id=uuid4(),
            state=DuckgresSinkState.BACKFILLING,
            backfill_run_uuid="run-1",
            last_error="large error payload",
        )
    )

    with CaptureQueriesContext(connection) as queries:
        references = sink_state.list_sink_backfill_run_references([state.team_id])

    assert [(reference.schema_id, reference.backfill_run_uuid) for reference in references] == [
        (state.schema_id, "run-1")
    ]
    assert len(queries) == 1
    sql = queries[0]["sql"]
    assert '"schema_id"' in sql
    assert '"backfill_run_uuid"' in sql
    assert '"last_error"' not in sql
