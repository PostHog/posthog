import pytest
from unittest.mock import MagicMock

import duckdb

from posthog.sync import database_sync_to_async

from products.managed_warehouse.backend.temporal import compaction_workflow as compaction_module
from products.managed_warehouse.backend.temporal.compaction_types import DucklakeCompactionInput
from products.managed_warehouse.backend.temporal.compaction_workflow import (
    list_ducklake_compaction_organizations,
    run_ducklake_compaction,
)


def _patch_duckdb_internals(monkeypatch):
    mock_conn = MagicMock()
    mock_conn.execute.return_value.fetchall.return_value = []
    monkeypatch.setattr(duckdb, "connect", lambda: mock_conn)

    mock_heartbeater = MagicMock()
    mock_heartbeater.__enter__ = MagicMock(return_value=mock_heartbeater)
    mock_heartbeater.__exit__ = MagicMock(return_value=False)
    monkeypatch.setattr(compaction_module, "HeartbeaterSync", MagicMock(return_value=mock_heartbeater))

    monkeypatch.setattr(compaction_module, "configure_connection", MagicMock())
    monkeypatch.setattr(compaction_module, "attach_catalog", MagicMock())


@pytest.mark.asyncio
@pytest.mark.parametrize("organization_id", ["org-123", None])
async def test_run_ducklake_compaction_config_source(organization_id, monkeypatch, activity_environment):
    _patch_duckdb_internals(monkeypatch)
    get_org_config = MagicMock(return_value={})
    get_config = MagicMock(return_value={})
    monkeypatch.setattr(compaction_module, "get_org_config", get_org_config)
    monkeypatch.setattr(compaction_module, "get_config", get_config)

    await activity_environment.run(
        run_ducklake_compaction, DucklakeCompactionInput(dry_run=True, organization_id=organization_id)
    )

    if organization_id is not None:
        get_org_config.assert_called_once_with(organization_id)
        get_config.assert_not_called()
    else:
        get_config.assert_called_once()
        get_org_config.assert_not_called()


@pytest.mark.asyncio
async def test_list_ducklake_compaction_organizations_dev_mode_returns_none_sentinel(monkeypatch, activity_environment):
    monkeypatch.setattr(compaction_module, "is_dev_mode", MagicMock(return_value=True))

    result = await activity_environment.run(list_ducklake_compaction_organizations)

    assert result == [None]


@pytest.mark.asyncio
@pytest.mark.django_db
async def test_list_ducklake_compaction_organizations_returns_provisioned_orgs(
    monkeypatch, activity_environment, aorganization
):
    from products.managed_warehouse.backend.models import DuckgresServer

    await database_sync_to_async(DuckgresServer.objects.create)(
        organization=aorganization,
        host="duckgres.internal",
        username="posthog",
        password="hunter2",
    )
    monkeypatch.setattr(compaction_module, "is_dev_mode", MagicMock(return_value=False))

    result = await activity_environment.run(list_ducklake_compaction_organizations)

    assert result == [str(aorganization.id)]
