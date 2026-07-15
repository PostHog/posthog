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


class _FakeSpec:
    def __init__(self, name: str | None):
        self.name = name


class _FakeBoxView:
    """What iter_boxes() yields: an id + a spec carrying the box name (+ status)."""

    def __init__(self, box_id: str, name: str | None, status: str = "running"):
        self.id = box_id
        self.spec = _FakeSpec(name)
        self.status = status


class _FakeBox:
    def __init__(self, *, box_id: str = "box-new", delete_raises: Exception | None = None):
        self.id = box_id
        self._delete_raises = delete_raises
        self.deleted = False

    def delete(self) -> None:
        if self._delete_raises is not None:
            raise self._delete_raises
        self.deleted = True


class _FakeClient:
    """Minimal stand-in for the SDK client. Each method's behaviour is set by the
    test; every call is recorded so we can assert teardown reached delete_pen and
    reaping deleted the right boxes."""

    def __init__(self, *, get=None, get_pen=None, boxes=None, create=None, update_pen=None):
        self._get = get
        self._get_pen = get_pen
        self._boxes = boxes or []
        self._create = create
        self._update_pen = update_pen
        self.deleted_pens: list[str] = []
        self.update_pen_calls: list[dict] = []
        self.deleted_box_ids: list[str] = []

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


def _make_backend(client):
    from hogbox_preview.hogland_backend import HoglandBackend

    backend = HoglandBackend(host="https://example.invalid", name="preview-pr-999", token="test-token")
    backend._client = client
    return backend


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class BoxNameIsUniquePerAttemptTest(unittest.TestCase):
    """Box names must NOT equal the pen name: hogland enforces per-owner name
    uniqueness across ALL statuses (failed included), and a failed placement
    holds its name for up to an hour — so a deterministic name makes the 5xx
    retry 409 against its own corpse. Each create attempt gets a fresh unique
    suffix so a failed attempt can't block the retry."""

    def _stub_ssh(self):
        from hogbox_preview import hogland_backend

        return unittest.mock.patch.object(
            hogland_backend, "_ephemeral_ssh_pubkey", return_value="ssh-ed25519 AAAA fake"
        )

    def test_create_name_has_unique_suffix(self):
        client = _FakeClient()
        backend = _make_backend(client)
        with self._stub_ssh():
            kwargs = backend._create_kwargs()
        self.assertRegex(kwargs["name"], r"^preview-pr-999-[0-9a-f]{6}$")

    def test_two_attempts_use_different_suffixes(self):
        # A 5xx-failed attempt leaves a failed box holding its unique name; the
        # retry must NOT reuse that exact name, so the suffix is regenerated per
        # create attempt.
        from hogbox_preview import hogland_backend
        from hogland import ServerError

        seen_names: list[str] = []
        attempts = {"n": 0}
        created = _FakeBox()

        def create(**kwargs):
            seen_names.append(kwargs["name"])
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise ServerError("placement failed: place: EOF", status_code=500)
            return created

        client = _FakeClient(create=create)
        backend = _make_backend(client)
        with self._stub_ssh(), unittest.mock.patch.object(hogland_backend.time, "sleep"):
            result = backend._restore_fresh()

        self.assertIs(result, created)
        self.assertEqual(len(seen_names), 2)
        self.assertNotEqual(seen_names[0], seen_names[1])
        for name in seen_names:
            self.assertRegex(name, r"^preview-pr-999-[0-9a-f]{6}$")


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class ProvisionReapsLeftoversTest(unittest.TestCase):
    """After the pen is repointed at the new box, best-effort reap every OTHER
    box whose name equals the pen name (legacy corpses) or starts with the pen
    name + '-' (this-tool corpses from failed runs) — never the just-created
    box."""

    def _backend_ready_to_reap(self, client, new_box):
        backend = _make_backend(client)
        # Pretend provision() already restored + repointed; drive reaping directly.
        backend._box = new_box
        backend._box_id = new_box.id
        backend._pen = _FakePen(current_box_id=new_box.id)
        return backend

    def test_reaps_exact_and_prefix_named_boxes(self):
        new_box = _FakeBox(box_id="box-new")
        deleted_handles: dict[str, _FakeBox] = {}

        boxes = [
            _FakeBoxView("box-new", "preview-pr-999-aaaaaa"),  # the just-created box — keep
            _FakeBoxView("box-legacy", "preview-pr-999"),  # legacy exact-name corpse
            _FakeBoxView("box-corpse", "preview-pr-999-bbbbbb"),  # failed-run corpse
            _FakeBoxView("box-other", "preview-pr-1000-cccccc"),  # different pen — keep
        ]

        def get(box_id):
            h = _FakeBox(box_id=box_id)
            deleted_handles[box_id] = h
            return h

        client = _FakeClient(get=get, boxes=boxes)
        backend = self._backend_ready_to_reap(client, new_box)

        backend._reap_leftovers()

        deleted = {bid for bid, h in deleted_handles.items() if h.deleted}
        self.assertEqual(deleted, {"box-legacy", "box-corpse"})
        self.assertFalse(new_box.deleted)

    def test_never_matches_other_previews_boxes(self):
        # Nested names must not cross-match: preview-pr-99 owns neither
        # preview-pr-999's boxes nor anything without the exact 6-hex tag.
        from hogbox_preview.hogland_backend import HoglandBackend

        backend = HoglandBackend(host="https://example.invalid", name="preview-pr-99", token="test-token")
        self.assertTrue(backend._name_matches("preview-pr-99"))
        self.assertTrue(backend._name_matches("preview-pr-99-abc123"))
        self.assertFalse(backend._name_matches("preview-pr-999-abc123"))  # other preview's box
        self.assertFalse(backend._name_matches("preview-pr-99-abc123-extra"))  # not our tag shape
        self.assertFalse(backend._name_matches("preview-pr-99-ABC123"))  # tag is lowercase hex

    def test_reap_failure_does_not_raise(self):
        from hogland import NotFoundError

        new_box = _FakeBox(box_id="box-new")
        boxes = [_FakeBoxView("box-corpse", "preview-pr-999-bbbbbb")]

        def get(_box_id):
            raise NotFoundError("box gone", status_code=404)

        client = _FakeClient(get=get, boxes=boxes)
        backend = self._backend_ready_to_reap(client, new_box)

        # Must not raise even though the per-box delete path blows up.
        backend._reap_leftovers()

    def test_list_failure_does_not_raise(self):
        # The list call itself failing (transient 5xx while enumerating boxes)
        # must be swallowed too — provision() reaps after the preview is already
        # working, so a reap hiccup must not fail the run.
        class _ListBoom(_FakeClient):
            def iter_boxes(self):
                raise RuntimeError("hogland API error (HTTP 502)")

        new_box = _FakeBox(box_id="box-new")
        backend = self._backend_ready_to_reap(_ListBoom(), new_box)

        backend._reap_leftovers()


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class DestroyReleasesPenTest(unittest.TestCase):
    """destroy() must delete the pen's box AND all name-matched boxes, then always
    reach delete_pen — a box already TTL-reaped counts as 'already gone', it must
    not abort teardown and leak the pen."""

    def test_pen_released_when_box_lookup_404s(self):
        from hogland import NotFoundError

        def boom(_box_id):
            raise NotFoundError("box gone", status_code=404)

        client = _FakeClient(get=boom, get_pen=_FakePen(current_box_id="box-reaped"))
        backend = _make_backend(client)
        backend._box_id = "box-reaped"  # forces _resolve_box down the direct get() path

        backend.destroy()

        self.assertEqual(client.deleted_pens, ["preview-pr-999"])

    def test_pen_released_when_box_delete_404s(self):
        from hogland import NotFoundError

        box = _FakeBox(delete_raises=NotFoundError("box gone", status_code=404))
        client = _FakeClient()
        backend = _make_backend(client)
        backend._box = box  # _resolve_box short-circuits to the live handle

        backend.destroy()

        self.assertEqual(client.deleted_pens, ["preview-pr-999"])

    def test_pen_released_when_box_delete_5xxs(self):
        # Teardown is best-effort all the way: a transient server error deleting
        # the box must not abort before delete_pen (the box has a TTL, the pen
        # doesn't).
        box = _FakeBox(delete_raises=RuntimeError("hogland API error (HTTP 502)"))
        client = _FakeClient()
        backend = _make_backend(client)
        backend._box = box

        backend.destroy()

        self.assertEqual(client.deleted_pens, ["preview-pr-999"])

    def test_happy_path_deletes_box_then_pen(self):
        box = _FakeBox()
        client = _FakeClient()
        backend = _make_backend(client)
        backend._box = box

        backend.destroy()

        self.assertTrue(box.deleted)
        self.assertEqual(client.deleted_pens, ["preview-pr-999"])

    def test_pen_released_when_leftover_listing_fails(self):
        # A transient 5xx while listing boxes for the leftover sweep must not
        # abort teardown before delete_pen — that would leak the pen forever
        # (teardown only runs on PR close).
        class _ListBoom(_FakeClient):
            def iter_boxes(self):
                raise RuntimeError("hogland API error (HTTP 502)")

        box = _FakeBox()
        backend = _make_backend(_ListBoom())
        backend._box = box  # _resolve_box short-circuits, only the reap lists

        backend.destroy()

        self.assertTrue(box.deleted)
        self.assertEqual(backend._client.deleted_pens, ["preview-pr-999"])

    def test_deletes_all_name_matched_boxes(self):
        # No live handle / pen pointer: destroy() should still sweep every box
        # whose name exact- or prefix-matches, then delete the pen.
        from hogland import NotFoundError

        deleted_handles: dict[str, _FakeBox] = {}
        boxes = [
            _FakeBoxView("box-a", "preview-pr-999-aaaaaa"),
            _FakeBoxView("box-legacy", "preview-pr-999"),
            _FakeBoxView("box-other", "preview-pr-1000-cccccc"),  # different pen — keep
        ]

        def get_pen(_name):
            raise NotFoundError("no pen", status_code=404)

        def get(box_id):
            h = _FakeBox(box_id=box_id)
            deleted_handles[box_id] = h
            return h

        client = _FakeClient(get=get, get_pen=get_pen, boxes=boxes)
        backend = _make_backend(client)

        backend.destroy()

        deleted = {bid for bid, h in deleted_handles.items() if h.deleted}
        self.assertEqual(deleted, {"box-a", "box-legacy"})
        self.assertEqual(client.deleted_pens, ["preview-pr-999"])


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class ResolveBoxNameScanTest(unittest.TestCase):
    """The last-resort name scan (used by attach() and destroy() when the pen
    pointer is missing/dangling) matches the exact pen name OR the pen-name '-'
    prefix, preferring a running box."""

    def test_prefix_match_fallback(self):
        from hogland import NotFoundError

        def get_pen(_name):
            raise NotFoundError("no pen", status_code=404)

        target = _FakeBox(box_id="box-corpse")
        boxes = [
            _FakeBoxView("box-other", "preview-pr-1000-cccccc"),
            _FakeBoxView("box-corpse", "preview-pr-999-bbbbbb"),
        ]

        def get(box_id):
            self.assertEqual(box_id, "box-corpse")
            return target

        client = _FakeClient(get=get, get_pen=get_pen, boxes=boxes)
        backend = _make_backend(client)

        self.assertIs(backend._resolve_box(), target)

    def test_prefers_running_box(self):
        from hogland import NotFoundError

        def get_pen(_name):
            raise NotFoundError("no pen", status_code=404)

        boxes = [
            _FakeBoxView("box-failed", "preview-pr-999-aaaaaa", status="failed"),
            _FakeBoxView("box-running", "preview-pr-999-bbbbbb", status="running"),
        ]

        target = _FakeBox(box_id="box-running")

        def get(box_id):
            self.assertEqual(box_id, "box-running")
            return target

        client = _FakeClient(get=get, get_pen=get_pen, boxes=boxes)
        backend = _make_backend(client)

        self.assertIs(backend._resolve_box(), target)


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class CreateRetriesTransient5xxTest(unittest.TestCase):
    """A transient placement 5xx (a node dying mid-restore) must be retried onto
    a healthy node, but a 4xx is a real client error and must surface at once."""

    def _stub_ssh(self):
        from hogbox_preview import hogland_backend

        return unittest.mock.patch.object(
            hogland_backend, "_ephemeral_ssh_pubkey", return_value="ssh-ed25519 AAAA fake"
        )

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
        backend = _make_backend(client)

        # Don't actually sleep the backoff in the test.
        with self._stub_ssh(), unittest.mock.patch.object(hogland_backend.time, "sleep"):
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
        backend = _make_backend(client)

        with self._stub_ssh(), unittest.mock.patch.object(hogland_backend.time, "sleep"):
            with self.assertRaises(ServerError):
                backend._restore_fresh()

        self.assertEqual(attempts["n"], hogland_backend._CREATE_5XX_ATTEMPTS)

    def test_4xx_not_retried(self):
        from hogland import ValidationError

        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            raise ValidationError("bad spec", status_code=422)

        client = _FakeClient(create=create)
        backend = _make_backend(client)

        with self._stub_ssh():
            with self.assertRaises(ValidationError):
                backend._restore_fresh()

        self.assertEqual(attempts["n"], 1)


if __name__ == "__main__":
    unittest.main()
