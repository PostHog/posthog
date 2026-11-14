from typing import cast
from uuid import UUID

from django.db import transaction

from posthog.paging import Page, PageRequest
from posthog.queryset_paging import select_page

from products.workflows.backend.facade.contracts import (
    WorkflowViewConflict,
    WorkflowViewNotFound,
    WorkflowViewRecord,
    WorkflowViewState,
)
from products.workflows.backend.models.workflow_view import WorkflowView


class WorkflowViewStore:
    def __init__(self, team_id: int) -> None:
        self.team_id = team_id

    @staticmethod
    def _record(view: WorkflowView) -> WorkflowViewRecord:
        return WorkflowViewRecord(
            id=view.id,
            name=view.name,
            state=cast(WorkflowViewState, view.state),
            version=view.version,
            default_key=view.default_key,
            deleted=view.deleted,
            created_at=view.created_at,
            updated_at=view.updated_at,
        )

    def list(self, page: PageRequest) -> Page[WorkflowViewRecord]:
        views = WorkflowView.objects.for_team(self.team_id).filter(deleted=False).order_by("created_at", "id")
        return select_page(views, page).map(self._record)

    def get(self, view_id: UUID) -> WorkflowViewRecord:
        return self._record(self._find(view_id))

    def _find(self, view_id: UUID, *, for_update: bool = False) -> WorkflowView:
        views = WorkflowView.objects.for_team(self.team_id).filter(deleted=False)
        if for_update:
            views = views.select_for_update()
        try:
            return views.get(pk=view_id)
        except WorkflowView.DoesNotExist as error:
            raise WorkflowViewNotFound() from error

    def create(self, *, name: str, state: WorkflowViewState) -> WorkflowViewRecord:
        view = WorkflowView.objects.for_team(self.team_id).create(team_id=self.team_id, name=name, state=state)
        return self._record(view)

    @staticmethod
    def _default_state() -> WorkflowViewState:
        return {
            "filters": [{"facet": "createdBy", "value": "me", "negated": False}],
            "text": "",
            "columns": ["owner"],
        }

    def initialize(self) -> WorkflowViewRecord:
        view, _ = WorkflowView.objects.for_team(self.team_id).get_or_create(
            default_key="my-workflows",
            defaults={"team_id": self.team_id, "name": "My workflows", "state": self._default_state()},
        )
        return self._record(view)

    def restore_default(self) -> WorkflowViewRecord:
        self.initialize()
        with transaction.atomic():
            view = WorkflowView.objects.for_team(self.team_id).select_for_update().get(default_key="my-workflows")
            if view.deleted:
                view.name = "My workflows"
                view.state = self._default_state()
                view.deleted = False
                view.version += 1
                view.save(update_fields=["name", "state", "deleted", "version", "updated_at"])
        return self._record(view)

    def _lock(self, view_id: UUID, version: int) -> WorkflowView:
        current = self._find(view_id, for_update=True)
        if current.version != version:
            raise WorkflowViewConflict()
        return current

    def update(
        self, view_id: UUID, version: int, *, name: str | None, state: WorkflowViewState | None
    ) -> WorkflowViewRecord:
        with transaction.atomic():
            current = self._lock(view_id, version)
            if name is not None:
                current.name = name
            if state is not None:
                current.state = state
            current.version += 1
            current.save(update_fields=["name", "state", "version", "updated_at"])
        return self._record(current)

    def delete(self, view_id: UUID, version: int) -> None:
        with transaction.atomic():
            current = self._lock(view_id, version)
            if current.default_key is not None:
                current.deleted = True
                current.version += 1
                current.save(update_fields=["deleted", "version", "updated_at"])
            else:
                current.delete()
