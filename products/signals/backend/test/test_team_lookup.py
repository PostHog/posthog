import pytest

import temporalio.exceptions

from products.signals.backend.temporal.team_lookup import TEAM_DELETED_ERROR_TYPE, get_team_or_terminal


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_returns_team_when_it_exists(ateam):
    team = await get_team_or_terminal(ateam.id)
    assert team.id == ateam.id


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_select_related_and_only_are_applied(ateam):
    team = await get_team_or_terminal(ateam.id, select_related=("organization",), only=("api_token", "organization"))
    assert team.id == ateam.id
    # organization was prefetched via select_related, so accessing it must not hit the DB again
    assert team.organization_id is not None


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_missing_team_raises_non_retryable_application_error(ateam):
    missing_team_id = ateam.id + 1_000_000

    with pytest.raises(temporalio.exceptions.ApplicationError) as exc_info:
        await get_team_or_terminal(missing_team_id)

    assert exc_info.value.non_retryable is True
    assert exc_info.value.type == TEAM_DELETED_ERROR_TYPE
