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
class DestroyReleasesPenTest(unittest.TestCase):
    def test_explicit_box_is_deleted_when_pen_is_missing(self):
        from hogland import NotFoundError

        box = _FakeBox(box_id="box-explicit")
        client = _FakeClient(get=box)
        backend = _make_backend(client)
        backend._box_id = box.id
        backend._delete_pen_if_current_box = unittest.mock.Mock(side_effect=NotFoundError("no pen", status_code=404))

        backend.destroy()

        self.assertTrue(box.deleted)
        backend._delete_pen_if_current_box.assert_called_once_with(box.id)

    def test_explicit_box_is_deleted_when_pen_was_replaced(self):
        from hogland import ConflictError

        box = _FakeBox(box_id="box-explicit")
        backend = _make_backend(_FakeClient(get=box))
        backend._box_id = box.id
        backend._delete_pen_if_current_box = unittest.mock.Mock(side_effect=ConflictError("pen moved", status_code=409))

        backend.destroy()

        self.assertTrue(box.deleted)
        backend._delete_pen_if_current_box.assert_called_once_with(box.id)

    def test_name_only_teardown_deletes_empty_pen(self):
        backend = _make_backend(_FakeClient(get_pen=_FakePen(current_box_id=None)))
        backend._delete_pen = unittest.mock.Mock()

        backend.destroy()

        backend._delete_pen.assert_called_once_with()


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


@unittest.skipUnless(HAVE_SDK, "posthog-hogland SDK not installed")
class CreateFailsFastOnNoCapacityTest(unittest.TestCase):
    """A capacity 503 already cost ~4 minutes server-side (auction retry
    budget) before hogland gave up, so it must raise on the first attempt
    instead of burning 3x that in runner time. Every other 5xx keeps
    retrying — see CreateRetriesTransient5xxTest."""

    def _stub_ssh(self):
        from hogbox_preview import hogland_backend

        return unittest.mock.patch.object(
            hogland_backend, "_ephemeral_ssh_pubkey", return_value="ssh-ed25519 AAAA fake"
        )

    def test_capacity_503_raises_immediately(self):
        from hogbox_preview import hogland_backend
        from hogland import ServerError

        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            raise ServerError(
                "no hogd has capacity: scale-up did not produce a willing hogd within 5m0s",
                status_code=503,
            )

        client = _FakeClient(create=create)
        backend = _make_backend(client)

        with self._stub_ssh(), unittest.mock.patch.object(hogland_backend.time, "sleep") as sleep:
            with self.assertRaises(ServerError) as ctx:
                backend._restore_fresh()

        self.assertEqual(attempts["n"], 1)
        sleep.assert_not_called()
        self.assertIn("no capacity", str(ctx.exception))
        self.assertIn("retry", str(ctx.exception))

    def test_generic_5xx_still_retries_three_times(self):
        from hogbox_preview import hogland_backend
        from hogland import ServerError

        attempts = {"n": 0}

        def create(**_kwargs):
            attempts["n"] += 1
            raise ServerError("placement failed: place: EOF", status_code=500)

        client = _FakeClient(create=create)
        backend = _make_backend(client)

        with self._stub_ssh(), unittest.mock.patch.object(hogland_backend.time, "sleep"):
            with self.assertRaises(ServerError):
                backend._restore_fresh()

        self.assertEqual(attempts["n"], hogland_backend._CREATE_5XX_ATTEMPTS)


if __name__ == "__main__":
    unittest.main()
