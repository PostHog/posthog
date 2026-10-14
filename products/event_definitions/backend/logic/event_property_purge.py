"""Batched deletion of a team's event properties."""

import time
from collections.abc import Callable

from django.db import connections, router, transaction

from products.event_definitions.backend.models.event_property import EventProperty


def delete_event_properties_for_team(
    team_id: int, should_stop: Callable[[], bool] | None = None, batch_size: int = 10000
) -> bool:
    """Delete the team's event properties in batches. Return False when ``should_stop`` ended the purge first.

    Each batch resumes the (team_id, property) index walk after the last (property, id) it deleted, so no batch
    reads the index entries of rows that earlier batches deleted. ``should_stop`` is checked before each batch.
    """
    table = EventProperty._meta.db_table
    alias = router.db_for_write(EventProperty)
    # The table name comes from the model, never from input, so interpolating it is safe.
    select_batch = (
        f'SELECT id, property, ctid::text FROM "{table}" WHERE team_id = %s AND (property, id) > (%s, %s) '
        "ORDER BY property, id LIMIT %s"
    )
    # The ctid finds each row without a primary key lookup. The id and team_id checks skip a row that an update
    # moved after the select, and the Team cascade deletes such a row later.
    delete_batch = f'DELETE FROM "{table}" WHERE ctid = ANY(%s::tid[]) AND id = ANY(%s) AND team_id = %s'

    last_property, last_id = "", 0
    while True:
        if should_stop is not None and should_stop():
            return False
        with transaction.atomic(using=alias), connections[alias].cursor() as cursor:
            cursor.execute(select_batch, [team_id, last_property, last_id, batch_size])
            rows = cursor.fetchall()
            if rows:
                cursor.execute(delete_batch, [[row[2] for row in rows], [row[0] for row in rows], team_id])
        if len(rows) < batch_size:
            return True
        last_id, last_property = rows[-1][0], rows[-1][1]
        time.sleep(0.1)
