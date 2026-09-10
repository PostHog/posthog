from __future__ import annotations

import os
import logging
import contextlib
from collections.abc import Generator, Iterator
from typing import Any

import django

logger = logging.getLogger(__name__)

_DJANGO_INITIALIZED = False


def setup_django(*, debug: bool = True) -> None:
    """Configure the environment and initialize Django for a harness run.

    Sets the eval env flags (``DEBUG``/``TEST``/``IN_EVAL_TESTING``) and disables
    local self-capture before Django reads them, then runs ``django.setup()`` and
    Django's test-environment setup. Safe to call more than once — subsequent
    calls are a no-op.
    """
    global _DJANGO_INITIALIZED
    if _DJANGO_INITIALIZED:
        return

    os.environ["DJANGO_SETTINGS_MODULE"] = "posthog.settings"
    os.environ["DEBUG"] = "1" if debug else "0"
    os.environ["TEST"] = "1"
    os.environ["IN_EVAL_TESTING"] = "1"
    # Eval traces use an explicit regional client; local self-capture would poll flags with the development API key.
    os.environ["SELF_CAPTURE"] = "0"

    django.setup()

    from django.test.utils import setup_test_environment  # noqa: PLC0415 — must import only after django.setup()

    setup_test_environment()
    _DJANGO_INITIALIZED = True


class NullDbBlocker:
    """Inert stand-in for pytest-django's ``django_db_blocker``.

    Outside pytest nothing blocks ORM access in the first place, so this only
    needs to satisfy the shared setup helpers' interface: an ``unblock()``
    context manager (the sole thing callers use, as ``with blocker.unblock():``)
    plus no-op ``block()``/``restore()``.
    """

    @contextlib.contextmanager
    def unblock(self) -> Iterator[None]:
        yield

    def block(self) -> None:
        pass

    def restore(self) -> None:
        pass


class EvalDatabase:
    """Owns the eval test database lifecycle for a harness run.

    Mirrors what pytest-django's ``django_db_setup`` did for sandboxed evals:
    create the base Django test DB once, then drive PostHog's own eval DB setup
    (persons DB, ClickHouse) and leave it committed for the whole run. Sandboxed
    evals intentionally strip per-test DB markers to avoid transactions/flushes,
    so the base Django DB is set up explicitly here.
    """

    def __init__(self, *, keepdb: bool) -> None:
        self.keepdb = keepdb
        self.blocker = NullDbBlocker()
        self._db_cfg: Any = None
        self._eval_setup: Generator[None] | None = None

    def setup(self) -> None:
        from django.test.utils import setup_databases  # noqa: PLC0415 — must import only after django.setup()

        from posthog.conftest import (
            _django_db_setup,  # noqa: PLC0415 — pulls in Django models; keep off the pre-setup import path
        )

        # Only the base Django ("default") DB is created here. Person DB setup is
        # handled by PostHog's eval setup below, after the default test DB name is
        # known (see SANDBOXED_EVAL_SETUP_DATABASES in the original conftest).
        self._db_cfg = setup_databases(
            verbosity=1,
            interactive=False,
            keepdb=self.keepdb,
            aliases={"default": None},
            serialized_aliases=set(),
        )
        self._eval_setup = _django_db_setup(self.keepdb, self.blocker)
        next(self._eval_setup)

    def teardown(self) -> None:
        from django.test.utils import teardown_databases  # noqa: PLC0415 — must import only after django.setup()

        if self._eval_setup is not None:
            # Run the generator's post-``yield`` cleanup (ClickHouse reset / drop).
            try:
                next(self._eval_setup)
            except StopIteration:
                pass
            self._eval_setup = None

        if not self.keepdb and self._db_cfg is not None:
            teardown_databases(self._db_cfg, verbosity=1)
