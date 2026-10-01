from __future__ import annotations

import os
import re
import hashlib
import tempfile
from contextlib import closing
from pathlib import Path
from urllib.parse import urlsplit

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

MAX_DOWNLOAD_BYTES = 2 * 1024**3


def validate_sha256(value: str | None) -> str:
    if value is None or re.fullmatch(r"[0-9a-fA-F]{64}", value) is None:
        raise ValueError("--sha256 must contain the bundle's 64-character SHA-256 digest from its publisher")
    return value.lower()


class S3EnvironmentSource:
    def __init__(self, uri: str, *, sha256: str | None, profile: str | None = None) -> None:
        try:
            parsed = urlsplit(uri)
        except ValueError:
            raise ValueError(
                "Use an s3://bucket/key.tar.gz URI without credentials, ports, queries or fragments"
            ) from None
        if (
            not uri.startswith("s3://")
            or re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", parsed.netloc) is None
            or not parsed.path.removeprefix("/").endswith(".tar.gz")
            or parsed.query
            or parsed.fragment
            or "?" in uri
            or "#" in uri
            or any(ord(character) < 32 or ord(character) == 127 for character in uri)
        ):
            raise ValueError("Use an s3://bucket/key.tar.gz URI without credentials, ports, queries or fragments")
        self.uri = uri
        self.bucket = parsed.netloc
        self.key = parsed.path.removeprefix("/")
        self.sha256 = validate_sha256(sha256)
        self.profile = profile

    def fetch(self, workspace: Path) -> Path:
        destination = workspace / f"download-{self.sha256}.tar.gz"
        if destination.is_symlink() or (destination.exists() and not destination.is_file()):
            raise ValueError("The cached S3 bundle must be a private regular file")
        if destination.exists():
            if destination.stat().st_size > MAX_DOWNLOAD_BYTES:
                raise ValueError("The cached S3 bundle exceeds the download size limit")
            with destination.open("rb") as content:
                cached_digest = hashlib.file_digest(content, "sha256").hexdigest()
            if cached_digest != self.sha256:
                raise ValueError(
                    "The cached S3 bundle does not match --sha256; remove the corrupt download before retrying"
                )
            destination.chmod(0o600)
            return destination

        try:
            session = boto3.Session(profile_name=self.profile)
            # Local object-storage endpoint settings must not redirect this AWS download.
            config = Config(  # type: ignore[call-arg]  # Botocore stubs omit ignore_configured_endpoint_urls.
                signature_version="s3v4",
                ignore_configured_endpoint_urls=True,
                connect_timeout=10,
                read_timeout=60,
                retries={"mode": "standard", "total_max_attempts": 3},
            )
            with closing(session.client("s3", config=config)) as client:
                response = client.get_object(Bucket=self.bucket, Key=self.key)
                with closing(response["Body"]) as body:
                    expected_size = response.get("ContentLength", 0)
                    if expected_size <= 0 or expected_size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("The S3 bundle is empty or exceeds the download size limit")
                    with tempfile.TemporaryDirectory(prefix=".download-", dir=workspace) as temporary:
                        partial = Path(temporary) / "bundle.tar.gz"
                        descriptor = os.open(partial, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                        digest = hashlib.sha256()
                        size = 0
                        with os.fdopen(descriptor, "wb") as output:
                            for block in body.iter_chunks(chunk_size=1024 * 1024):
                                size += len(block)
                                if size > MAX_DOWNLOAD_BYTES or size > expected_size:
                                    raise ValueError("The S3 bundle exceeds its declared or maximum download size")
                                digest.update(block)
                                output.write(block)
                            if size != expected_size:
                                raise ValueError("The S3 bundle download is incomplete")
                            if digest.hexdigest() != self.sha256:
                                raise ValueError("The S3 bundle does not match --sha256; no environment was prepared")
                            output.flush()
                            os.fsync(output.fileno())
                        os.replace(partial, destination)
        except (BotoCoreError, ClientError) as error:
            raise ValueError(
                f"S3 download failed ({type(error).__name__}). Check your AWS login, --aws-profile and read access "
                "to the bundle. Private response details were not printed."
            ) from None
        return destination
