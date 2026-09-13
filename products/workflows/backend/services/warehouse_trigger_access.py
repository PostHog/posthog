from collections.abc import Sequence
from functools import cached_property
from uuid import UUID

from posthog.hogql.database.database import get_data_warehouse_table_name

from posthog.models import Team, User

from products.access_control.backend.facade.user_access_control import UserAccessControl
from products.data_modeling.backend.facade.models import DataWarehouseSavedQuery
from products.warehouse_sources.backend.facade.models import DataWarehouseTable
from products.workflows.backend.models import HogFlow


class WarehouseTriggerAccess:
    def __init__(self, team: Team) -> None:
        self.team = team
        self._users: dict[int, UserAccessControl] = {}
        self._views: dict[str, DataWarehouseSavedQuery | None] = {}

    @cached_property
    def tables(self) -> dict[str, DataWarehouseTable]:
        return {
            get_data_warehouse_table_name(table.external_data_source, table.name): table
            for table in DataWarehouseTable.objects.queryable()
            .filter(team=self.team)
            .select_related(None)
            .select_related("external_data_source")
            .prefetch_related(None)
            .only(
                "id",
                "team_id",
                "name",
                "created_by_id",
                "external_data_source_id",
                "external_data_source__id",
                "external_data_source__source_type",
                "external_data_source__prefix",
                "external_data_source__access_method",
            )
        }

    def can_read(self, user: User | None, trigger_type: str, table_name: str) -> bool:
        if user is None or not user.is_active or not table_name:
            return False
        if user.pk not in self._users:
            self._users[user.pk] = UserAccessControl(user=user, team=self.team)
        access = self._users[user.pk]
        if not access.check_access_level_for_object(self.team, "member"):
            return False

        table: DataWarehouseTable | DataWarehouseSavedQuery | None
        if trigger_type == "data-warehouse-table":
            table = self.tables.get(table_name)
        elif trigger_type == "data-warehouse-view":
            if table_name not in self._views:
                self._views[table_name] = (
                    DataWarehouseSavedQuery.objects.filter(team=self.team, name=table_name)
                    .exclude(deleted=True)
                    .only("id", "team_id", "created_by_id")
                    .first()
                )
            table = self._views[table_name]
        else:
            return False
        return table is not None and access.check_access_level_for_object(table, "viewer")


def allowed_warehouse_flows(team: Team, trigger_type: str, table_name: str, flow_ids: Sequence[UUID]) -> list[str]:
    access = WarehouseTriggerAccess(team)
    return [
        str(flow.id)
        for flow in HogFlow.objects.filter(
            team=team,
            id__in=flow_ids,
            status=HogFlow.State.ACTIVE,
            trigger__type=trigger_type,
            trigger__table_name=table_name,
        )
        .select_related("created_by")
        .only("id", "created_by")
        if access.can_read(flow.created_by, trigger_type, table_name)
    ]
