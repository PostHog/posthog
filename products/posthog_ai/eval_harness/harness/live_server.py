from __future__ import annotations

import socket
import logging
import threading

from django.conf import settings
from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler
from django.db import connections
from django.db.backends.base.base import BaseDatabaseWrapper
from django.db.backends.sqlite3.creation import DatabaseCreation as SQLiteDatabaseCreation

import uvicorn

from posthog.asgi import application

from .ports import DJANGO_LIVE_PORT

logger = logging.getLogger(__name__)


class _EvalUvicornServer(uvicorn.Server):
    def __init__(self, config: uvicorn.Config, ready: threading.Event) -> None:
        super().__init__(config)
        self.ready = ready
        self.startup_error: BaseException | None = None

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        try:
            await super().startup(sockets=sockets)
        except BaseException as error:
            self.startup_error = error
            raise
        finally:
            self.ready.set()


class EvalLiveServer:
    """Session-lifetime ASGI server backed by the eval test database.

    Serving PostHog's full ASGI application keeps the sandbox event-ingest route
    available alongside normal Django URLs. Docker sandboxes reach the listener
    through ``host.docker.internal``.
    """

    def __init__(self, port: int = DJANGO_LIVE_PORT) -> None:
        # If using in-memory SQLite, share the main thread's connection with the
        # server thread. Postgres needs no override.
        connections_override: dict[str, BaseDatabaseWrapper] = {}
        for connection in connections.all():
            if isinstance(connection.creation, SQLiteDatabaseCreation) and connection.creation.is_in_memory_db(
                connection.settings_dict["NAME"]
            ):
                connections_override[connection.alias] = connection

        asgi_application = (
            ASGIStaticFilesHandler(application)
            if "django.contrib.staticfiles" in settings.INSTALLED_APPS
            else application
        )
        self._connections_override = connections_override
        self._ready = threading.Event()
        self._thread_error: BaseException | None = None
        self._stopped = False

        # Bind before starting the thread so port=0 is race-free and ``url`` can
        # immediately advertise the actual OS-assigned port.
        # Docker sandboxes connect through host.docker.internal, which cannot reach a loopback-only listener.
        self._socket = socket.socket(  # nosemgrep: python.lang.security.audit.network.bind.avoid-bind-to-all-interfaces
            socket.AF_INET, socket.SOCK_STREAM
        )
        self._socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._socket.bind(("0.0.0.0", port))
        self._socket.listen(2048)
        self.port = self._socket.getsockname()[1]

        config = uvicorn.Config(
            asgi_application,
            host="0.0.0.0",
            port=self.port,
            loop="asyncio",
            lifespan="on",
            log_level="warning",
            access_log=False,
            timeout_graceful_shutdown=10,
        )
        self.server = _EvalUvicornServer(config, self._ready)
        self.thread = threading.Thread(target=self._serve, name="sandboxed-eval-asgi", daemon=True)

        for connection in connections_override.values():
            connection.inc_thread_sharing()

        self.thread.start()
        if not self._ready.wait(timeout=30):
            self.stop()
            raise RuntimeError("Django ASGI server did not start within 30 seconds")
        if self.server.startup_error is not None:
            error = self.server.startup_error
            self.stop()
            raise error
        if not self.server.started:
            self.stop()
            raise RuntimeError("Django ASGI server stopped during startup")

        logger.info("Django live server started at %s (bound on 0.0.0.0)", self.url)

    def _serve(self) -> None:
        for alias, connection in self._connections_override.items():
            connections[alias] = connection
        try:
            self.server.run(sockets=[self._socket])
        except BaseException as error:
            self._thread_error = error
            self._ready.set()
            if self.server.startup_error is None:
                logger.exception("Django ASGI server crashed")
        finally:
            connections.close_all()

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def __str__(self) -> str:
        return self.url

    def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self.server.should_exit = True
        self.thread.join(timeout=15)
        if self.thread.is_alive():
            self.server.force_exit = True
            self.thread.join(timeout=5)
        if self.thread.is_alive():
            logger.warning("Django ASGI server thread did not stop within 20 seconds")
        self._socket.close()
        for connection in self._connections_override.values():
            connection.dec_thread_sharing()
        logger.info("Django live server stopped")
