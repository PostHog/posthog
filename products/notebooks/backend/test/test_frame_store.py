import io
import urllib.request

from posthog.test.base import APIBaseTest

from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError

from products.notebooks.backend import frame_store


class TestFrameKeys(SimpleTestCase):
    def test_key_is_namespaced_under_the_team_prefix(self):
        # The team prefix is the tenant isolation unit: presign_get's cross-tenant check
        # relies on every built key starting with it.
        key = frame_store.build_frame_key(42, "nb42abc", "deadbeef01")
        self.assertEqual(key, "notebooks/frames/team_42/nb42abc/deadbeef01.arrow")
        self.assertTrue(key.startswith(frame_store.team_prefix(42)))

    @parameterized.expand(
        [
            ("path_traversal", "../team_1", "deadbeef"),
            ("separator_in_short_id", "a/b", "deadbeef"),
            ("empty_short_id", "", "deadbeef"),
            ("separator_in_hash", "nb1", "dead/beef"),
            ("whitespace", "nb 1", "deadbeef"),
        ]
    )
    def test_rejects_unsafe_key_segments(self, _name, short_id, query_hash):
        # A segment with a path separator could place an object outside the team prefix,
        # defeating the tenant check at presign time.
        with self.assertRaises(frame_store.FrameStoreError):
            frame_store.build_frame_key(1, short_id, query_hash)

    def test_presign_refuses_keys_outside_the_team_prefix(self):
        # Last line of defense: a poisoned stored key must never presign across tenants.
        with self.assertRaises(frame_store.FrameStoreError):
            frame_store.presign_get("notebooks/frames/team_2/nb/hash.arrow", team_id=1)


class TestFrameStoreObjects(APIBaseTest):
    KEY = "notebooks/frames/team_999999/nbtest/deadbeef.arrow"

    def tearDown(self):
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            object_storage.delete(self.KEY)
        super().tearDown()

    def test_write_stream_then_presigned_fetch_needs_no_credentials(self):
        # The sandbox holds no storage identity — the presigned URL must be the whole
        # authorization. A broken presign config (wrong signature version, wrong endpoint
        # client) surfaces here.
        payload = b"arrow-ipc-bytes" * 1024
        with self.settings(OBJECT_STORAGE_ENABLED=True):
            stored_bytes = frame_store.write_stream(self.KEY, io.BytesIO(payload))
            url = frame_store.presign_get(self.KEY, team_id=999999)
        self.assertEqual(stored_bytes, len(payload))
        with urllib.request.urlopen(url) as response:  # deliberately credential-free
            self.assertEqual(response.read(), payload)

    def test_failed_upload_leaves_no_object(self):
        # A torn ClickHouse stream mid-upload must abort the multipart upload — a partial
        # frame served to the kernel would silently truncate a dataframe.
        class _TornStream(io.RawIOBase):
            def __init__(self):
                self._served = False

            def readable(self):
                return True

            def readinto(self, buffer):
                if not self._served:
                    self._served = True
                    chunk = b"x" * min(len(buffer), 1024)
                    buffer[: len(chunk)] = chunk
                    return len(chunk)
                raise OSError("connection reset mid-stream")

        with self.settings(OBJECT_STORAGE_ENABLED=True):
            with self.assertRaises(ObjectStorageError):
                frame_store.write_stream(self.KEY, _TornStream())
            self.assertIsNone(object_storage.head_object(self.KEY))
