"""Unit tests for the hogland preview backend.

Self-contained: no network, no live hogland. Runs against a hand-rolled fake
client that stands in for the ``posthog-hogland`` SDK's ``Hogland``. Guarded on
the SDK import so the monorepo's Django pytest collection can't hard-fail here
(the SDK is pulled per-run via ``uv run --with``, not a repo dependency).

    cd tools/hogbox-preview && python -m unittest discover tests
"""

from __future__ import annotations

import unittest

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

    def __init__(self, *, get=None, get_pen=None, boxes=None):
        self._get = get
        self._get_pen = get_pen
        self._boxes = boxes or []
        self.deleted_pens: list[str] = []

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


if __name__ == "__main__":
    unittest.main()
