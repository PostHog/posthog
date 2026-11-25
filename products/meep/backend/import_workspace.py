import json
import sqlite3
from contextlib import closing
from pathlib import Path
from uuid import UUID, uuid4

from django.core.management.base import CommandError
from django.db import transaction

from posthog.models import Team, User
from posthog.user_permissions import UserPermissions

from products.meep.backend.domain import transition
from products.meep.backend.models import CommandReceipt, Topic, WorkspaceView


@transaction.atomic
def import_workspace(database: Path, project_id: int, owner_id: int, apply: bool) -> int:
    project = Team.objects.get(pk=project_id)
    owner = User.objects.select_for_update().get(pk=owner_id)
    if not owner.is_active or UserPermissions(user=owner, team=project).current_team.effective_membership_level is None:
        raise CommandError("The destination owner must have access to the project.")
    database = database.resolve(strict=True)
    count = 0
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source:
        rows = source.execute(
            "SELECT kind, id, body FROM records WHERE kind IN ('engine/topic','engine/view') AND deleted=0 ORDER BY kind,id"
        )
        for kind, key, body in rows:
            entry = json.loads(body)
            topic = kind == "engine/topic"
            state = transition("import-topic" if topic else "import-view", entry if topic else entry["view"], {})
            identifier = UUID(key)
            if UUID(state["topic"]["id"] if topic else state["id"]) != identifier:
                raise CommandError("Snapshot identity mismatch.")
            model = Topic if topic else WorkspaceView
            existing = model.objects.unscoped().filter(pk=identifier).first()
            if existing:
                if existing.team_id == project.pk and existing.owner_id == owner.pk and existing.state == state:
                    continue
                raise CommandError(f"Conflicting {kind} {identifier}. No records imported.")
            if topic:
                current = Topic.objects.for_team(project.pk).create(
                    pk=identifier,
                    team=project,
                    owner=owner,
                    title=state["topic"]["name"],
                    mission=state["topic"]["mission"],
                    revision=max(1, entry["revision"]),
                    state=state,
                    archived=state["archived"],
                    deleted=state["deleted"],
                )
                CommandReceipt.objects.create(topic=current, command_id=uuid4(), revision=current.revision)
            else:
                WorkspaceView.objects.for_team(project.pk).create(pk=identifier, team=project, owner=owner, state=state)
            count += 1
    if not apply:
        transaction.set_rollback(True)
    return count
