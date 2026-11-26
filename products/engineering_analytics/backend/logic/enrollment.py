"""A team is enrolled when it has the product's managed viewset row. Only a user action creates
the row. See SPEC.md, "Exposed warehouse views"."""

from django.db.models import QuerySet

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.warehouse_sources.backend.facade.models import ExternalDataSource
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind, ExternalDataSourceType

_KIND = DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
_enrollments = DataWarehouseManagedViewSet.objects.filter(kind=_KIND)


def enrolled_sources(source_type: ExternalDataSourceType) -> QuerySet[ExternalDataSource]:
    return (
        ExternalDataSource.objects.filter(
            source_type=source_type, team_id__in=_enrollments.values_list("team_id", flat=True)
        )
        .exclude(deleted=True)
        .select_related("team")
    )


def get_enrollment(team: Team) -> DataWarehouseManagedViewSet | None:
    return _enrollments.filter(team=team).first()


def enroll(team: Team) -> None:
    """Create the opt-in row if missing, and sync the views only on creation.

    The UI calls this on every product open, and a sync on each call would hold the team's sync
    lock and reach Temporal inside a web request.
    """
    managed_viewset, created = DataWarehouseManagedViewSet.objects.get_or_create(team=team, kind=_KIND)
    if created:
        managed_viewset.sync_views()
