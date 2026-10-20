from uuid import UUID

from django.db import IntegrityError

from ..facade import contracts
from ..facade.contracts import ResearchSourceAlreadyExistsError, ResearchSourceNotFoundError
from ..models import ResearchSource


def list_sources(*, active_only: bool = False) -> list[ResearchSource]:
    queryset = ResearchSource.objects.order_by("kind", "label")
    if active_only:
        queryset = queryset.filter(active=True)
    return list(queryset)


def create_source(data: contracts.CreateResearchSourceInput) -> ResearchSource:
    try:
        return ResearchSource.objects.create(
            team_id=data.team_id,
            kind=data.kind,
            external_id=data.external_id.strip(),
            label=data.label.strip(),
            owner_email=data.owner_email.strip().lower(),
            product_area=data.product_area.strip(),
            origin=data.origin,
        )
    except IntegrityError as e:
        raise ResearchSourceAlreadyExistsError(f"A {data.kind} source with ID {data.external_id} exists.") from e


def update_source(team_id: int, source_id: UUID, data: contracts.UpdateResearchSourceInput) -> ResearchSource:
    try:
        source = ResearchSource.objects.get(team_id=team_id, id=source_id)
    except ResearchSource.DoesNotExist as e:
        raise ResearchSourceNotFoundError(str(source_id)) from e

    if data.label is not None:
        source.label = data.label.strip()
    if data.owner_email is not None:
        source.owner_email = data.owner_email.strip().lower()
    if data.product_area is not None:
        source.product_area = data.product_area.strip()
    if data.active is not None:
        source.active = data.active
    source.save()
    return source
