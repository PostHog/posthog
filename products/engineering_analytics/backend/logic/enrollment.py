"""Which teams opted into engineering analytics.

The product's ``DataWarehouseManagedViewSet`` row is the opt-in, the same way revenue analytics
reads its own row. A user action creates it; nothing in the background does. Every sweep that
works on behalf of a team (view sync after a warehouse load, the test census, the job-log
fetchers) asks this module first, so a team with a GitHub source it connected for another
reason never gets views, events or Logs from this product.
"""

from django.db.models import QuerySet

from posthog.models.team import Team

from products.data_modeling.backend.facade.models import DataWarehouseManagedViewSet
from products.warehouse_sources.backend.facade.types import DataWarehouseManagedViewSetKind


def enrolled_team_ids() -> QuerySet[DataWarehouseManagedViewSet, int]:
    """Team ids of every enrolled team, as a subquery for ``team_id__in`` filters."""
    return DataWarehouseManagedViewSet.objects.filter(
        kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
    ).values_list("team_id", flat=True)


def get_enrollment(team: Team) -> DataWarehouseManagedViewSet | None:
    return DataWarehouseManagedViewSet.objects.filter(
        team=team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
    ).first()


def enroll(team: Team) -> DataWarehouseManagedViewSet:
    """Create the opt-in row if missing and sync the views. Safe to call again on an enrolled team."""
    managed_viewset, _ = DataWarehouseManagedViewSet.objects.get_or_create(
        team=team, kind=DataWarehouseManagedViewSetKind.ENGINEERING_ANALYTICS
    )
    managed_viewset.sync_views()
    return managed_viewset
