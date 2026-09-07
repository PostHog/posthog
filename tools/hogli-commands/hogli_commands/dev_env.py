"""Resolver for the two supported developer environments: flox (the default) and
the opt-in devenv (devenv.nix).

The shell counterpart is ``bin/helpers/dev-env.sh``; keep the two in step. This
is unrelated to ``hogli_commands.devenv``, which configures which services the
dev stack starts.
"""

import os

DEVENV = "devenv"
FLOX = "flox"

# Venv locations relative to a repo root, one per environment. Tools that act on
# a repo they did not activate themselves (worktree cleanup, for one) must handle
# both, because the repo can belong to another developer's setup.
VENV_PATHS = (".flox/cache/venv", ".devenv/state/venv")


def dev_env_kind() -> str:
    """Return ``devenv`` or ``flox``.

    devenv exports ``DEVENV_ROOT`` inside an active shell, and
    ``POSTHOG_DEV_ENV`` is how a developer opts in before one exists (.envrc
    reads the same variable).
    """
    if is_devenv_active() or os.environ.get("POSTHOG_DEV_ENV") == DEVENV:
        return DEVENV
    return FLOX


def is_devenv_active() -> bool:
    """Return whether the caller runs inside a devenv shell."""
    return os.environ.get("DEVENV_ROOT") is not None
