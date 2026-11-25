from __future__ import annotations

import os
import logging
import contextlib
from collections.abc import Generator, Iterator

import django
from django.conf import settings

logger = logging.getLogger(__name__)

_DJANGO_INITIALIZED = False


def setup_django(*, debug: bool = True, keep_logging: bool = False) -> None:
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

    if keep_logging:
        settings.LOGGING_CONFIG = None
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
        self._eval_setup: Generator[None] | None = None

    def setup(self) -> None:
        from django.test.utils import setup_databases  # noqa: PLC0415 — must import only after django.setup()

        from posthog.conftest import (
            _django_db_setup,  # noqa: PLC0415 — pulls in Django models; keep off the pre-setup import path
        )

        # The persons and ClickHouse databases outlive a missing default database. Reusing them under a new
        # default database gives the regenerated master team an id that their old rows already use.
        keepdb = self.keepdb and _default_test_database_exists()

        # Only the base Django ("default") DB is created here. Person DB setup is
        # handled by PostHog's eval setup below, after the default test DB name is
        # known (see SANDBOXED_EVAL_SETUP_DATABASES in the original conftest).
        setup_databases(
            verbosity=1,
            interactive=False,
            keepdb=keepdb,
            aliases={"default": None},
            serialized_aliases=set(),
        )
        self._eval_setup = _django_db_setup(keepdb, self.blocker)
        next(self._eval_setup)

        from posthog.clickhouse.client.deferred_setup import (
            clickhouse_test_setup,  # noqa: PLC0415 — must import only after django.setup()
        )

        # Replicated tables get a unique ZooKeeper path only while settings.TEST is true. The demo data
        # setup sends the first ClickHouse query under override_settings(TEST=False), so a deferred setup
        # would create the tables there, on the paths the development database uses.
        clickhouse_test_setup.run()

    def teardown(self) -> None:
        """Keep every database for the next run, which reuses them unless it passes ``--create-db``."""
        from django.db import connections  # noqa: PLC0415 — must import only after django.setup()

        if self._eval_setup is not None:
            # Closing the generator skips its post-``yield`` cleanup, which drops the ClickHouse database
            # when the run rebuilt it.
            self._eval_setup.close()
            self._eval_setup = None
        connections.close_all()


def _default_test_database_exists() -> bool:
    from django.db import connections  # noqa: PLC0415 — must import only after django.setup()

    connection = connections["default"]
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1 FROM pg_database WHERE datname = %s", [connection.creation._get_test_db_name()])
        return cursor.fetchone() is not None
