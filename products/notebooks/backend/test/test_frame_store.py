import io
import urllib.request
from typing import IO, cast

from posthog.test.base import APIBaseTest
from unittest.mock import patch

from django.conf import settings
from django.test import SimpleTestCase

from parameterized import parameterized

from posthog.storage import object_storage
from posthog.storage.object_storage import ObjectStorageError, UnavailableStorage

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
        # authorization, and must carry a signature. The local store serves anonymous reads, so
        # the round trip alone would also pass for a bare object URL that 403s in cloud; the
        # signature assertion is what rejects that. Mapping the URL onto a public host is a
        # deployment concern covered in posthog/storage/test/test_object_storage.py.
        payload = b"arrow-ipc-bytes" * 1024
        # Presign against the endpoint this process writes through, so the fetch below does not
        # depend on OBJECT_STORAGE_PUBLIC_ENDPOINT resolving from here — the frame-store runbook
        # tells devs to point that at the sandbox's network, which on macOS is
        # host.docker.internal and resolves only inside Docker. Dropping the cached client is
        # what makes the override bite: the storage client keeps its presigning endpoint in a
        # module global and rebuilds only after a call made while storage is disabled.
        with (
            self.settings(OBJECT_STORAGE_ENABLED=True, OBJECT_STORAGE_PUBLIC_ENDPOINT=settings.OBJECT_STORAGE_ENDPOINT),
            patch.object(object_storage, "_client", UnavailableStorage()),
        ):
            stored_bytes = frame_store.write_stream(self.KEY, io.BytesIO(payload))
            url = frame_store.presign_get(self.KEY, team_id=999999)
        self.assertEqual(stored_bytes, len(payload))
        self.assertIn("X-Amz-Signature=", url)
        with urllib.request.urlopen(url) as response:  # deliberately credential-free
            self.assertEqual(response.read(), payload)

    def test_presign_signs_against_the_dedicated_frame_bucket(self):
        # Frames get their own bucket in cloud, and the app-side presign must sign against it —
        # not the general OBJECT_STORAGE_BUCKET. If presign_get drops the bucket override, the
        # kernel is 302'd to a URL signed for a bucket ClickHouse never wrote to → 404. The
        # write→presign→fetch round-trip can't catch this (there both buckets are the default and
        # coincide), so drive a distinct frame bucket and assert it lands in the signed URL.
        # (presign is a client-side signing op, so the bucket need not exist.)
        with self.settings(OBJECT_STORAGE_ENABLED=True, NOTEBOOKS_FRAME_STORE_S3_BUCKET="ph-notebook-frames"):
            url = frame_store.presign_get(self.KEY, team_id=999999)
        self.assertIn("ph-notebook-frames", url)

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
                frame_store.write_stream(self.KEY, cast("IO[bytes]", _TornStream()))
            self.assertIsNone(object_storage.head_object(self.KEY))
