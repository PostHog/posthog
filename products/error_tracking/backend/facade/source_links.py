"""Facade for error tracking source links.

Kept separate from ``facade/api.py`` so the object-storage and GitHub integration imports
stay off the django.setup() path of the read-oriented main facade.
"""

from ..logic import source_links as _logic
from . import contracts

MAX_RAW_IDS_PER_REQUEST = _logic.MAX_RAW_IDS_PER_REQUEST


def resolve_source_links(team_id: int, release_id: str, raw_ids: list[str]) -> list[contracts.ErrorTrackingSourceLink]:
    return [
        contracts.ErrorTrackingSourceLink(raw_id=link.raw_id, provider=link.provider, url=link.url, path=link.path)
        for link in _logic.resolve_source_links(team_id, release_id, raw_ids)
    ]
