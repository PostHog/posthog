import pytest

from django.db import OperationalError, connections

from posthog.models.organization import Organization
from posthog.models.team.util import delete_team_records

from products.error_tracking.backend.logic import team_purge
from products.error_tracking.backend.models import ErrorTrackingStackFrame

# The holding session must see the committed frame row, which the rollback-based TestCase never commits.
pytestmark = [pytest.mark.django_db(transaction=True)]


@pytest.mark.timeout(60)
@pytest.mark.parametrize(
    "holding_statement",
    [
        "SELECT id FROM posthog_errortrackingstackframe WHERE id = %s FOR UPDATE",
        # A migration takes this lock, and it blocks the batch read as well as the batch delete.
        "LOCK TABLE posthog_errortrackingstackframe IN ACCESS EXCLUSIVE MODE",
    ],
)
def test_a_purge_batch_fails_fast_behind_a_transaction_that_holds_a_frame_lock(
    monkeypatch: pytest.MonkeyPatch, holding_statement: str
) -> None:
    _, _, team = Organization.objects.bootstrap(None)
    frame = ErrorTrackingStackFrame.objects.create(team=team, raw_id="raw", contents={}, resolved=True)
    monkeypatch.setattr(team_purge, "BATCH_LOCK_TIMEOUT_MS", 200)
    holder = connections.create_connection("default")
    try:
        holder.set_autocommit(False)
        with holder.cursor() as cursor:
            cursor.execute(holding_statement, [frame.id] if "%s" in holding_statement else [])

        with pytest.raises(OperationalError, match="lock timeout"):
            delete_team_records([team.id])
    finally:
        holder.rollback()
        holder.close()

    assert ErrorTrackingStackFrame.objects.filter(id=frame.id).exists()
