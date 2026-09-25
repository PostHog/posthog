from __future__ import annotations

from pathlib import Path
from uuid import UUID

from django.db import transaction
from django.utils import timezone

from owners_yaml import OwnersResolver
from pydantic import BaseModel, ConfigDict, Field, field_validator

from posthog.models import Team

from products.access_control.backend.facade.api import get_routing_roles
from products.signals.backend.models import SignalProductDomain


class ImportedDomain(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=100)
    description: str = Field(max_length=4000)
    ownership_paths: list[str] = Field(min_length=1, max_length=100)
    code_paths: list[str] = Field(default_factory=list, max_length=100)

    @field_validator("ownership_paths", "code_paths")
    @classmethod
    def relative_paths(cls, paths: list[str]) -> list[str]:
        if any(not path or path.startswith("/") or ".." in path.split("/") or len(path) > 500 for path in paths):
            raise ValueError("Use bounded repository-relative paths without parent traversal.")
        return paths


class OwnershipImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    repository: str = Field(min_length=1, max_length=200)
    revision: str = Field(min_length=1, max_length=100)
    owner_roles: dict[str, UUID] = Field(max_length=100)
    domains: list[ImportedDomain] = Field(max_length=100)


def import_product_domains(*, team_id: int, repo_root: Path, definition: OwnershipImport, apply: bool) -> list[dict]:
    """The repository resolver supplies ownership; an explicit map supplies project role identities."""
    roles = {role.id for role in get_routing_roles(team_id=team_id)}
    if set(definition.owner_roles.values()) - roles:
        raise ValueError("An owner mapping refers to a role outside this project's organization.")
    if len({item.key for item in definition.domains}) != len(definition.domains):
        raise ValueError("Import keys must be unique.")
    resolver = OwnersResolver(repo_root=repo_root)
    results: list[dict] = []
    with transaction.atomic():
        # Import workers serialize on the project; individual edits serialize on each domain.
        Team.objects.select_for_update().get(id=team_id)
        for item in definition.domains:
            resolutions = [resolver.resolve(path) for path in item.ownership_paths]
            owners = {owner for result in resolutions for owner in result.owners or []}
            mapped = {definition.owner_roles[owner] for owner in owners if owner in definition.owner_roles}
            known = (
                bool(owners)
                and all(result.owners for result in resolutions)
                and owners <= definition.owner_roles.keys()
            )
            role_id = str(next(iter(mapped))) if known and len(mapped) == 1 else None
            incoming = {
                "name": item.name,
                "description": item.description,
                "repository": definition.repository,
                "code_paths": item.code_paths,
                "owning_role_id": role_id,
            }
            domain = (
                SignalProductDomain.objects.for_team(team_id)
                .select_for_update()
                .filter(import_state__repository=definition.repository, import_state__key=item.key)
                .first()
            )
            if domain is None and SignalProductDomain.objects.for_team(team_id).filter(name=item.name).exists():
                results.append({"key": item.key, "status": "manual_definition_preserved"})
                continue
            previous = domain.import_state.get("fields", {}) if domain else {}
            preserved = []
            updates = {}
            for field, value in incoming.items():
                current = getattr(domain, field, None)
                if isinstance(current, UUID):
                    current = str(current)
                if domain is not None and current != previous.get(field):
                    preserved.append(field)
                else:
                    updates[field] = value
            result = {
                "key": item.key,
                "status": "updated" if domain else "created",
                "unmapped_ownership": role_id is None,
                "preserved_fields": preserved,
            }
            results.append(result)
            if not apply:
                continue
            provenance = {
                "key": item.key,
                "repository": definition.repository,
                "revision": definition.revision,
                "refreshed_at": timezone.now().isoformat(),
                "sources": sorted({result.source for result in resolutions if result.source}),
                # Remember the original imported value of an edited field so future imports keep respecting the edit.
                "fields": {**previous, **updates},
                "preserved_fields": preserved,
            }
            if domain is None:
                SignalProductDomain.objects.for_team(team_id).create(
                    team_id=team_id, **incoming, import_state=provenance
                )
            else:
                for field, value in updates.items():
                    setattr(domain, field, value)
                domain.import_state = provenance
                domain.revision += 1
                domain.save()
    return results
