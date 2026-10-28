from __future__ import annotations

import io
import hashlib
import tempfile
from pathlib import Path

from unittest import TestCase
from unittest.mock import Mock, patch

from boto3.session import Session
from botocore.response import StreamingBody
from botocore.stub import Stubber
from parameterized import parameterized

from products.posthog_ai.eval_harness.environment import download

URI = "s3://example-fixture-bucket/environments/example.tar.gz"
CONTENT = b"invented archive bytes"
DIGEST = hashlib.sha256(CONTENT).hexdigest()
OBJECT = {"Bucket": "example-fixture-bucket", "Key": "environments/example.tar.gz"}


class TestS3EnvironmentSource(TestCase):
    def setUp(self) -> None:
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.workspace = self.root / "state"
        self.workspace.mkdir(mode=0o700)
        self.client = Session(
            aws_access_key_id="testing",
            aws_secret_access_key="testing",
            aws_session_token="testing",
            region_name="us-east-1",
        ).client("s3", endpoint_url="https://s3.amazonaws.com")
        self.addCleanup(self.client.close)
        self.stubber = Stubber(self.client)
        self.stubber.activate()
        self.addCleanup(self.stubber.deactivate)
        self.session = Mock()
        self.session.client.return_value = self.client
        session_patch = patch.object(download.boto3, "Session", return_value=self.session)
        self.session_factory = session_patch.start()
        self.addCleanup(session_patch.stop)

    @parameterized.expand([(None,), ("example-employee",)])
    def test_verified_private_download_is_reused_without_aws_access(self, profile: str | None) -> None:
        content = io.BytesIO(CONTENT)
        self.stubber.add_response(
            "get_object", {"Body": StreamingBody(content, len(CONTENT)), "ContentLength": len(CONTENT)}, OBJECT
        )
        source = download.S3EnvironmentSource(URI, sha256=DIGEST.upper(), profile=profile)

        path = source.fetch(self.workspace)

        self.stubber.assert_no_pending_responses()
        self.session_factory.assert_called_once_with(profile_name=profile)
        self.assertEqual(path.name, f"download-{DIGEST}.tar.gz")
        self.assertEqual(path.read_bytes(), CONTENT)
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertTrue(content.closed)
        self.assertEqual(list(self.workspace.iterdir()), [path])
        self.session_factory.reset_mock()
        self.assertEqual(source.fetch(self.workspace), path)
        self.session_factory.assert_not_called()

    @parameterized.expand(
        [
            ("https://example.com/example.tar.gz", DIGEST),
            ("s3:///example.tar.gz", DIGEST),
            ("s3://example-fixture-bucket/", DIGEST),
            ("s3://example-fixture-bucket/example.zip", DIGEST),
            ("s3://example-fixture-bucket/example.tar.gz?token=example", DIGEST),
            ("s3://example-fixture-bucket/example.tar.gz#fragment", DIGEST),
            ("s3://user:password@example-fixture-bucket/example.tar.gz", DIGEST),
            ("s3://example-fixture-bucket:443/example.tar.gz", DIGEST),
            (URI, None),
            (URI, "0" * 63),
            (URI, "g" * 64),
        ]
    )
    def test_invalid_source_is_rejected_before_aws_access(self, uri: str, digest: str | None) -> None:
        with self.assertRaises(ValueError):
            download.S3EnvironmentSource(uri, sha256=digest).fetch(self.workspace)
        self.session_factory.assert_not_called()
        self.assertEqual(list(self.workspace.iterdir()), [])

    @parameterized.expand(["checksum", "declared_size", "stream_size", "truncated"])
    def test_invalid_download_closes_stream_and_does_not_publish_partial_cache(self, failure: str) -> None:
        content = io.BytesIO(CONTENT)
        limit = len(CONTENT) - 1 if failure in {"declared_size", "stream_size"} else 100
        reported = 1 if failure == "stream_size" else len(CONTENT) + (failure == "truncated")
        body_size = len(CONTENT) + (failure == "truncated")
        self.stubber.add_response(
            "get_object", {"Body": StreamingBody(content, body_size), "ContentLength": reported}, OBJECT
        )
        unrelated = self.workspace / "existing.txt"
        unrelated.write_bytes(b"existing private state")
        source = download.S3EnvironmentSource(URI, sha256="0" * 64 if failure == "checksum" else DIGEST)

        with patch.object(download, "MAX_DOWNLOAD_BYTES", limit), self.assertRaises(ValueError):
            source.fetch(self.workspace)

        self.stubber.assert_no_pending_responses()
        self.assertTrue(content.closed)
        self.assertEqual(list(self.workspace.iterdir()), [unrelated])
        self.assertEqual(unrelated.read_bytes(), b"existing private state")

    @parameterized.expand(["AccessDenied", "NoSuchKey"])
    def test_aws_errors_do_not_expose_service_response_or_publish_cache(self, error_code: str) -> None:
        self.stubber.add_client_error(
            "get_object",
            service_error_code=error_code,
            service_message="invented-private-service-message",
            expected_params=OBJECT,
        )
        with self.assertRaises(ValueError) as error:
            download.S3EnvironmentSource(URI, sha256=DIGEST).fetch(self.workspace)
        self.stubber.assert_no_pending_responses()
        self.assertNotIn("invented-private-service-message", str(error.exception))
        self.assertEqual(list(self.workspace.iterdir()), [])

    @parameterized.expand(["corrupt", "symlink", "directory"])
    def test_unsafe_existing_cache_is_rejected_without_overwrite_or_aws_access(self, failure: str) -> None:
        cached = self.workspace / f"download-{DIGEST}.tar.gz"
        outside = self.root / "outside.tar.gz"
        outside.write_bytes(CONTENT)
        if failure == "corrupt":
            cached.write_bytes(b"changed cache")
        elif failure == "symlink":
            cached.symlink_to(outside)
        else:
            cached.mkdir()

        with self.assertRaises(ValueError):
            download.S3EnvironmentSource(URI, sha256=DIGEST).fetch(self.workspace)

        self.session_factory.assert_not_called()
        self.assertEqual(outside.read_bytes(), CONTENT)
        if failure == "corrupt":
            self.assertEqual(cached.read_bytes(), b"changed cache")
        elif failure == "symlink":
            self.assertTrue(cached.is_symlink())
        else:
            self.assertTrue(cached.is_dir())
