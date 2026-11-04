"""Hook inversion for skill archival and rename, so another product can refuse one.

Archiving is permanent — there is no unarchive endpoint — and a skill can be the definition
another product runs. That product knows when removing it is not the caller's call to make, but
this one cannot import it: the dependency runs the other way. So it offers a registry instead,
which siblings fill during ``django.setup()`` (in ``AppConfig.ready()``).

Signals registers the only guard today: a scout that locked its lifecycle refuses to be archived
by anyone but the person its runs act as, or a project admin.

A rename gets the same treatment, because another product can key its rows on the skill name.
A rename hook runs inside the rename transaction, before the skill rows move. It can refuse the
rename, or move its own rows to the new name in the same transaction.
"""

from collections.abc import Callable

from posthog.models.team.team import Team
from posthog.models.user import User


class SkillArchiveRefused(Exception):
    """A registered guard refused this archive. Carries the message to show the caller."""


# (team, skill_name, user, authenticator) -> None, raising SkillArchiveRefused to refuse.
# The authenticator is the DRF one when the call came through an endpoint, so a guard can record
# whether a token or a person at a browser tried; None everywhere else.
SkillArchiveGuard = Callable[[Team, str, User, object], None]

_archive_guards: list[SkillArchiveGuard] = []


def register_skill_archive_guard(fn: SkillArchiveGuard) -> None:
    _archive_guards.append(fn)


def assert_skill_archive_allowed(
    *,
    team: Team,
    skill_name: str,
    user: User | None,
    authenticator: object = None,
) -> None:
    """Run every registered guard, raising `SkillArchiveRefused` on the first refusal.

    A caller with no acting user is a system path (seeding, a management command, a test fixture)
    rather than someone asking to remove a skill, so it is not gated.
    """
    if user is None:
        return
    for guard in _archive_guards:
        guard(team, skill_name, user, authenticator)


class SkillRenameRefused(Exception):
    """A registered rename hook refused this rename. Carries the message to show the caller."""


class SkillRenameConflict(Exception):
    """A registered rename hook found its own rows already under the new name."""


# (team, skill_name, new_name, user, authenticator) -> None, raising SkillRenameRefused or
# SkillRenameConflict to stop the rename. `user` is None for a system path.
SkillRenameHook = Callable[[Team, str, str, User | None, object], None]

_rename_hooks: list[SkillRenameHook] = []


def register_skill_rename_hook(fn: SkillRenameHook) -> None:
    _rename_hooks.append(fn)


def run_skill_rename_hooks(
    *,
    team: Team,
    skill_name: str,
    new_name: str,
    user: User | None,
    authenticator: object = None,
) -> None:
    """Run every registered rename hook. Call it inside the rename transaction."""
    for hook in _rename_hooks:
        hook(team, skill_name, new_name, user, authenticator)
