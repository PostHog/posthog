"""Resolver for the two supported developer environments: flox (the default) and
the opt-in devenv (devenv.nix).

The shell counterpart is ``bin/helpers/dev-env.sh``; keep the two in step. This
is unrelated to ``hogli_commands.devenv``, which configures which services the
dev stack starts.
"""

import os
import shutil

DEVENV = "devenv"
FLOX = "flox"

# Venv locations relative to a repo root, one per environment. Tools that act on
# a repo they did not activate themselves (worktree cleanup, for one) must handle
# both, because the repo can belong to another developer's setup.
VENV_PATHS = (".flox/cache/venv", ".devenv/state/venv")


def dev_env_kind() -> str:
    """Return ``devenv`` or ``flox``.

    ``POSTHOG_DEV_ENV`` wins in both directions, so a developer can force
    either environment. Without it, an installed devenv binary is the opt-in:
    an activated devenv shell exports ``DEVENV_ROOT``, and a shell outside one
    still has the binary on PATH. ``.envrc`` applies the same rule.
    """
    forced = os.environ.get("POSTHOG_DEV_ENV")
    if forced in (DEVENV, FLOX):
        return forced
    if is_devenv_active() or shutil.which(DEVENV) is not None:
        return DEVENV
    return FLOX


def is_devenv_active() -> bool:
    """Return whether the caller runs inside a devenv shell."""
    return os.environ.get("DEVENV_ROOT") is not None
