import threading

from unittest.mock import patch

from django.test import SimpleTestCase

from asgiref.sync import async_to_sync, sync_to_async

from products.replay_vision.backend.temporal import decorators
from products.replay_vision.backend.temporal.decorators import track_activity


class TestTrackActivity(SimpleTestCase):
    def test_async_activity_closes_connections_on_the_thread_that_holds_them(self) -> None:
        # Django keeps connections per thread, so cleanup on the event loop would leave the
        # expired connection that the body reaches Postgres with untouched.
        cleanup_threads: list[int] = []
        body_threads: list[int] = []

        @track_activity()
        async def activity() -> None:
            body_threads.append(await sync_to_async(threading.get_ident)())

        with patch.object(
            decorators, "close_stale_db_connections", lambda: cleanup_threads.append(threading.get_ident())
        ):
            async_to_sync(activity)()

        assert cleanup_threads == body_threads
