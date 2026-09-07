"""Resolver for the two supported developer environments: flox (the default) and
the opt-in devenv (devenv.nix).

The shell counterpart is ``bin/helpers/dev-env.sh``; keep the two in step. This
is unrelated to ``hogli_commands.devenv``, which configures which services the
dev stack starts.
"""

import os

# Venv locations relative to a repo root, in the order the shell resolver tries
# them. Tools that act on a repo they did not activate themselves (worktree
# cleanup, for one) must handle all of them, because the repo can belong to
# another developer's setup.
VENV_PATHS = (".devenv/state/venv", ".flox/cache/venv", ".venv", "env")


def is_devenv_active() -> bool:
    """Return whether the caller runs inside a devenv shell."""
    return os.environ.get("DEVENV_ROOT") is not None
