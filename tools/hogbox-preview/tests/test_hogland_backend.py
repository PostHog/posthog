"""Unit tests for the hogland preview backend.

Self-contained: no network, no live hogland. Runs against a hand-rolled fake
client that stands in for the ``posthog-hogland`` SDK's ``Hogland``. Guarded on
the SDK import so the monorepo's Django pytest collection can't hard-fail here
(the SDK is pulled per-run via ``uv run --with``, not a repo dependency).

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest
import unittest.mock

try:
    import hogland  # noqa: F401

    HAVE_SDK = True
except ImportError:
    HAVE_SDK = False


class _FakePen:
    def __init__(self, current_box_id: str | None = None):
        self.current_box_id = current_box_id
        self.id = "pen-deadbeef"


class _FakeBox:
    def __init__(self, *, delete_raises: Exception | None = None):
        self._delete_raises = delete_raises
        self.deleted = False

    def delete(self) -> None:
        if self._delete_raises is not None:
            raise self._delete_raises
        self.deleted = True


class _FakeClient:
    """Minimal stand-in for the SDK client. Each method's behaviour is set by the
    test; every call is recorded so we can assert teardown reached delete_pen."""

    def __init__(self, *, get=None, get_pen=None, boxes=None, create=None, update_pen=None):
        self._get = get
        self._get_pen = get_pen
        self._boxes = boxes or []
        self._create = create
        self._update_pen = update_pen
        self.deleted_pens: list[str] = []
        self.update_pen_calls: list[dict] = []

    def get(self, box_id):
        if callable(self._get):
            return self._get(box_id)
        return self._get

    def get_pen(self, name):
        if callable(self._get_pen):
            return self._get_pen(name)
        return self._get_pen

    def iter_boxes(self):
        return iter(self._boxes)

    def delete_pen(self, name):
        self.deleted_pens.append(name)

    def create(self, **kwargs):
        if callable(self._create):
            return self._create(**kwargs)
        return self._create

    def update_pen(self, name, **kwargs):
        self.update_pen_calls.append({"name": name, **kwargs})
        if callable(self._update_pen):
            return self._update_pen(name, **kwargs)
        return self._update_pen


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class DestroyReleasesPenTest(unittest.TestCase):
    """destroy() must always reach delete_pen — a box already TTL-reaped counts
    as 'already gone', it must not abort teardown and leak the pen."""

    def _backend(self, client):
        from hogbox_preview.hogland_backend import HoglandBackend

        backend = HoglandBackend(host="https://example.invalid", name="preview-pr-999", token="test-token")
        backend._client = client
        return backend

    def test_pen_released_when_box_lookup_404s(self):
        # The pen still points at a dead box id; resolving it raises NotFoundError.
        from hogland import NotFoundError

        def boom(_box_id):
            raise NotFoundError("box gone", status_code=404)

        client = _FakeClient(get=boom, get_pen=_FakePen(current_box_id="box-reaped"))
        backend = self._backend(client)
        backend._box_id = "box-reaped"  # forces _resolve_box down the direct get() path

        backend.destroy()

        self.assertEqual(client.deleted_pens, ["preview-pr-999"])

    def test_pen_released_when_box_delete_404s(self):
        # A stale live handle whose box was reaped between resolve and delete.
        from hogland import NotFoundError

        box = _FakeBox(delete_raises=NotFoundError("box gone", status_code=404))
        client = _FakeClient()
        backend = self._backend(client)
        backend._box = box  # _resolve_box short-circuits to the live handle

        backend.destroy()

        self.assertEqual(client.deleted_pens, ["preview-pr-999"])

    def test_happy_path_deletes_box_then_pen(self):
        box = _FakeBox()
        client = _FakeClient()
        backend = self._backend(client)
        backend._box = box

        backend.destroy()

        self.assertTrue(box.deleted)
        self.assertEqual(client.deleted_pens, ["preview-pr-999"])


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class RestoreFreshHandlesStaleConflictTest(unittest.TestCase):
    """A name conflict on create() means a prior run's box is still in the way.
    If that box was already reaped (TTL cleanup or a racing teardown) between
    resolving it and deleting it, the retry must still proceed — not abort."""

    def _backend(self, client):
        from hogbox_preview.hogland_backend import HoglandBackend

        backend = HoglandBackend(host="https://example.invalid", name="preview-pr-999", token="test-token")
        backend._client = client
        return backend

    def test_retries_create_when_stale_box_already_gone(self):
        from hogland import ConflictError, NotFoundError

        stale_box = _FakeBox(delete_raises=NotFoundError("box gone", status_code=404))
        created = object()
        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConflictError("name taken", status_code=409)
            return created

        client = _FakeClient(create=create)
        backend = self._backend(client)
        backend._box = stale_box  # _resolve_box short-circuits to the live handle

        result = backend._restore_fresh()

        self.assertIs(result, created)

    def test_clears_pen_pointer_after_stale_delete(self):
        # After reaping the stale box, the pen pointer must be cleared right away
        # so the run dying before provision() repoints it doesn't leave the pen
        # dangling at a deleted box.
        from hogland import ConflictError

        stale_box = _FakeBox()
        created = object()
        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConflictError("name taken", status_code=409)
            return created

        client = _FakeClient(create=create)
        backend = self._backend(client)
        backend._box = stale_box

        result = backend._restore_fresh()

        self.assertIs(result, created)
        self.assertTrue(stale_box.deleted)
        self.assertEqual(client.update_pen_calls, [{"name": "preview-pr-999", "current_box_id": ""}])

    def test_clear_pen_pointer_failure_does_not_abort_run(self):
        # Clearing the pointer is best-effort: the server reconciler sweep is the
        # real backstop, so a failure to clear must not fail the run.
        from hogland import ConflictError, NotFoundError

        stale_box = _FakeBox()
        created = object()
        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ConflictError("name taken", status_code=409)
            return created

        def update_pen(_name, **_kwargs):
            raise NotFoundError("no pen yet", status_code=404)

        client = _FakeClient(create=create, update_pen=update_pen)
        backend = self._backend(client)
        backend._box = stale_box

        result = backend._restore_fresh()

        self.assertIs(result, created)


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class CreateRetriesTransient5xxTest(unittest.TestCase):
    """A transient placement 5xx (a node dying mid-restore) must be retried onto
    a healthy node, but a 4xx is a real client error and must surface at once."""

    def _backend(self, client):
        from hogbox_preview.hogland_backend import HoglandBackend

        backend = HoglandBackend(host="https://example.invalid", name="preview-pr-999", token="test-token")
        backend._client = client
        return backend

    def test_first_create_500s_second_succeeds(self):
        from hogbox_preview import hogland_backend
        from hogland import ServerError

        created = object()
        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ServerError("placement failed: place: EOF", status_code=500)
            return created

        client = _FakeClient(create=create)
        backend = self._backend(client)

        # Don't actually sleep the backoff in the test.
        with unittest.mock.patch.object(hogland_backend.time, "sleep"):
            result = backend._restore_fresh()

        self.assertIs(result, created)
        self.assertEqual(attempts["n"], 2)

    def test_persistent_500_exhausts_and_raises(self):
        from hogbox_preview import hogland_backend
        from hogland import ServerError

        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            raise ServerError("placement failed", status_code=500)

        client = _FakeClient(create=create)
        backend = self._backend(client)

        with unittest.mock.patch.object(hogland_backend.time, "sleep"):
            with self.assertRaises(ServerError):
                backend._restore_fresh()

        # Bounded: exactly _CREATE_5XX_ATTEMPTS, not multiplied by the conflict loop.
        self.assertEqual(attempts["n"], hogland_backend._CREATE_5XX_ATTEMPTS)

    def test_4xx_not_retried(self):
        from hogland import ValidationError

        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            raise ValidationError("bad spec", status_code=422)

        client = _FakeClient(create=create)
        backend = self._backend(client)

        with self.assertRaises(ValidationError):
            backend._restore_fresh()

        self.assertEqual(attempts["n"], 1)


if __name__ == "__main__":
    unittest.main()
