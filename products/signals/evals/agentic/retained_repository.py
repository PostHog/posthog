from __future__ import annotations

import os
import re
import json
import shlex
import hashlib
import logging
import tempfile
import threading
import subprocess
from contextlib import ExitStack
from pathlib import Path, PurePosixPath
from types import TracebackType
from typing import TYPE_CHECKING, Literal, Self

from unittest.mock import patch

if TYPE_CHECKING:
    from products.tasks.backend.logic.services.docker_sandbox import DockerSandbox
    from products.tasks.backend.logic.services.sandbox import ExecutionResult

logger = logging.getLogger(__name__)


class RetainedScoutRepository:
    _installation_lock = threading.Lock()

    def __init__(
        self,
        source: Path,
        commit: str,
        repository: str = "posthog/posthog",
        *,
        history_depth: Literal[1] | None = None,
        cache_directory: Path | None = None,
    ) -> None:
        if not re.fullmatch(r"[0-9a-f]{40}", commit):
            raise ValueError("The retained repository requires a complete lowercase commit SHA.")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise ValueError("The repository must use an owner/name pair.")
        if any(part in {".", ".."} for part in repository.split("/")):
            raise ValueError("The repository must use an owner/name pair.")
        if history_depth not in (None, 1):
            raise ValueError("Retain either the complete history or only the pinned commit (history_depth=1).")
        self.source = source.resolve()
        self.commit = commit
        self.repository = repository.lower()
        self.history_depth = history_depth
        self.cache_directory = cache_directory
        self.bundle_path: Path | None = None
        self.bundle_sha256 = ""
        self.verified_sandboxes: dict[str, dict[str, str]] = {}
        self._stack: ExitStack | None = None

    @staticmethod
    def _git(directory: Path, *arguments: str, timeout: int = 300) -> str:
        try:
            return subprocess.run(
                [
                    "git",
                    "-c",
                    "protocol.allow=never",
                    "-c",
                    "protocol.file.allow=always",
                    "-C",
                    str(directory),
                    *arguments,
                ],
                env={
                    **os.environ,
                    "GIT_NO_LAZY_FETCH": "1",
                    "GIT_TERMINAL_PROMPT": "0",
                    "GIT_CONFIG_GLOBAL": "/dev/null",
                    "GIT_CONFIG_NOSYSTEM": "1",
                },
                check=True,
                capture_output=True,
                text=True,
                timeout=timeout,
            ).stdout.strip()
        except subprocess.CalledProcessError as error:
            logger.exception("Retained repository git command failed: %s", error.stderr.strip())
            raise

    def _prepare_shallow_source(self, staging: Path) -> None:
        self._git(staging.parent, "init", "--bare", str(staging))
        objects = self._git(self.source, "rev-parse", "--path-format=absolute", "--git-path", "objects")
        alternates = staging / "objects" / "info" / "alternates"
        alternates.write_text(objects + "\n")
        shallow = staging / "shallow"
        shallow.write_text(self.commit + "\n")
        self._git(staging, "update-ref", "refs/heads/master", self.commit)
        self._git(staging, "symbolic-ref", "HEAD", "refs/heads/master")
        try:
            self._git(staging, "rev-list", "--objects", "--missing=error", "--quiet", "HEAD")
        except subprocess.CalledProcessError:
            self._git(staging, "update-ref", "-d", "refs/heads/master")
            alternates.unlink()
            shallow.unlink()
            logger.info("Fetching the pinned repository tree from public GitHub")
            self._git(
                staging,
                "-c",
                "protocol.https.allow=always",
                "-c",
                "credential.helper=",
                "-c",
                "http.extraHeader=",
                "fetch",
                "--depth=1",
                "--no-tags",
                f"https://github.com/{self.repository}.git",
                f"{self.commit}:refs/heads/master",
                timeout=900,
            )

    def _check_bundle(self, bundle: Path, manifest_path: Path) -> Path:
        metadata = json.loads(manifest_path.read_text())
        expected = {
            "repository": self.repository,
            "commit": self.commit,
            "history_depth": str(self.history_depth or "full"),
        }
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise ValueError("The retained repository cache has a different commit or history depth.")
        with bundle.open("rb") as content:
            digest = hashlib.file_digest(content, "sha256").hexdigest()
        if metadata.get("bundle_sha256") != digest:
            raise ValueError("The retained repository cache checksum does not match.")
        heads = set(self._git(bundle.parent, "bundle", "list-heads", str(bundle)).splitlines())
        if heads != {f"{self.commit} HEAD", f"{self.commit} refs/heads/master"}:
            raise ValueError("The retained repository bundle exposes unexpected refs.")
        self.bundle_path, self.bundle_sha256 = bundle, digest
        return bundle

    def prepare_bundle(self, directory: Path) -> Path:
        directory = directory.resolve()
        bundle = directory / "repository.bundle"
        manifest_path = directory / "repository.json"
        if bundle.exists():
            return self._check_bundle(bundle, manifest_path)
        if not self.source.is_dir():
            raise ValueError("The repository source is unavailable and no prepared bundle exists.")
        if self.history_depth is None and self._git(self.source, "rev-parse", "--is-shallow-repository") != "false":
            raise ValueError("Use a complete local repository so the saved commit retains its history.")
        if self._git(self.source, "rev-parse", "--verify", f"{self.commit}^{{commit}}") != self.commit:
            raise ValueError("The retained commit does not match the requested commit.")
        directory.mkdir(parents=True, exist_ok=True)
        logger.info(
            "Preparing retained repository at %s (history depth: %s)", self.commit, self.history_depth or "full"
        )
        partial = directory / "repository.bundle.partial"
        with tempfile.TemporaryDirectory(prefix="scout-git-source-") as temporary:
            staging = Path(temporary) / "source.git"
            if self.history_depth == 1:
                self._prepare_shallow_source(staging)
            else:
                self._git(directory, "clone", "--bare", "--shared", "--", str(self.source), str(staging))
                self._git(staging, "update-ref", "refs/heads/master", self.commit)
                self._git(staging, "symbolic-ref", "HEAD", "refs/heads/master")
            # Explicit refs exclude later commits and other branches from the saved world.
            self._git(staging, "bundle", "create", str(partial), "HEAD", "refs/heads/master", timeout=900)
            self._git(staging, "bundle", "verify", str(partial))
        partial.replace(bundle)
        with bundle.open("rb") as content:
            self.bundle_sha256 = hashlib.file_digest(content, "sha256").hexdigest()
        self.bundle_path = bundle
        manifest_path.write_text(json.dumps(self.metadata, indent=2) + "\n")
        return bundle

    @property
    def metadata(self) -> dict[str, str]:
        if not self.bundle_sha256:
            raise RuntimeError("Prepare the retained repository before reading its metadata.")
        return {
            "repository": self.repository,
            "commit": self.commit,
            "history_depth": str(self.history_depth or "full"),
            "bundle_sha256": self.bundle_sha256,
            "boot_mode": "clone_before_boot",
        }

    def checkout_command(self, bundle: PurePosixPath, workspace: PurePosixPath) -> str:
        if not self.bundle_sha256:
            raise RuntimeError("Prepare the retained repository before materializing it.")
        checkout = workspace / "repos" / self.repository
        origin = workspace / ".retained-repositories" / f"{self.repository}.git"

        def command(*arguments: str | PurePosixPath) -> str:
            return shlex.join([str(argument) for argument in arguments])

        commands = [
            "set -euo pipefail",
            "umask 077",
            command("test", "!", "-e", origin),
            command("printf", "%s  %s\n", self.bundle_sha256, bundle) + " | sha256sum --check --status",
            command("mkdir", "-p", checkout.parent, origin.parent),
            command("git", "init", "--bare", origin),
        ]
        if self.history_depth == 1:
            # Bundles do not encode shallow boundaries; install the boundary before checking connectivity.
            commands.append(command("printf", "%s\n", self.commit) + " > " + shlex.quote(str(origin / "shallow")))
        commands.extend(
            [
                command("git", "-C", origin, "bundle", "unbundle", bundle),
                command("git", "-C", origin, "update-ref", "refs/heads/master", self.commit),
                command("git", "-C", origin, "symbolic-ref", "HEAD", "refs/heads/master"),
                command("git", "clone", "--no-hardlinks", "--", origin, checkout),
                command("git", "-C", checkout, "checkout", "--detach", self.commit),
                command(
                    "git", "-C", checkout, "symbolic-ref", "refs/remotes/origin/HEAD", "refs/remotes/origin/master"
                ),
            ]
        )
        repository_names = {self.repository}
        if self.repository == "posthog/posthog":
            repository_names.add("PostHog/posthog")
        for repository_name in sorted(repository_names):
            for prefix in ("https://github.com/", "http://github.com/", "git@github.com:", "ssh://git@github.com/"):
                for suffix in ("", ".git"):
                    commands.append(
                        command(
                            "git",
                            "config",
                            "--global",
                            "--add",
                            f"url.{origin.as_uri()}.insteadOf",
                            f"{prefix}{repository_name}{suffix}",
                        )
                    )
        for ref in ("HEAD", "origin/HEAD"):
            revision = command("git", "-C", checkout, "rev-parse", ref)
            commands.append(f'test "$({revision})" = {shlex.quote(self.commit)}')
        commands.extend(
            [
                command("chmod", "-R", "a-w", origin),
                command("git", "-C", checkout, "rev-parse", "HEAD", "origin/HEAD"),
            ]
        )
        return "\n".join(commands)

    def _clone(self, sandbox: DockerSandbox) -> ExecutionResult:
        from products.tasks.backend.exceptions import (
            SandboxNotFoundError,  # noqa: PLC0415 - Django initializes before the Docker adapter is installed.
        )

        if self.bundle_path is None:
            raise RuntimeError("The retained repository has not been prepared.")
        bundle = PurePosixPath("/tmp/scout-retained-repository.bundle")
        try:
            subprocess.run(
                ["docker", "cp", str(self.bundle_path), f"{sandbox.id}:{bundle}"],
                check=True,
                capture_output=True,
                text=True,
                timeout=300,
            )
            result = sandbox.execute(
                self.checkout_command(bundle, PurePosixPath("/tmp/workspace")), timeout_seconds=300
            )
            if result.exit_code != 0:
                raise RuntimeError(f"Retained repository verification failed: {result.stderr}")
            revisions = result.stdout.strip().splitlines()[-2:]
            if revisions != [self.commit, self.commit]:
                raise RuntimeError("Retained repository verification did not return the expected revisions.")
            self.verified_sandboxes[sandbox.id] = {
                **self.metadata,
                "head": revisions[0],
                "origin_head": revisions[1],
            }
            return result
        except Exception as error:
            # The production workflow tolerates clone failures, so stop this container before it can run without its fixture.
            try:
                sandbox.destroy()
            finally:
                raise SandboxNotFoundError(
                    "Retained repository setup failed; the eval sandbox was stopped.",
                    {"sandbox_id": sandbox.id, "repository": self.repository},
                    cause=error,
                    capture=False,
                ) from error

    def __enter__(self) -> Self:
        from django.conf import settings  # noqa: PLC0415 - The preparation helpers work without Django.

        from products.posthog_ai.eval_harness.harness import lifecycle  # noqa: PLC0415
        from products.tasks.backend.constants import OVERLAP_CLONE_BOOT_FEATURE_FLAG  # noqa: PLC0415
        from products.tasks.backend.logic.services import (
            sandbox as sandbox_module,  # noqa: PLC0415 - Django must initialize before sandbox imports.
        )
        from products.tasks.backend.logic.services.docker_sandbox import (
            DockerSandbox,  # noqa: PLC0415 - Django must initialize before sandbox imports.
        )

        if not settings.TEST or settings.SANDBOX_PROVIDER != "docker":
            raise RuntimeError("Retained scout repositories require the local Docker eval provider.")
        if self.repository in sandbox_module.parse_sandbox_repo_mount_map():
            raise RuntimeError("Remove this repository from SANDBOX_REPO_MOUNT_MAP before running its retained case.")
        if not self._installation_lock.acquire(blocking=False):
            raise RuntimeError("Only one retained repository configuration can be active in an eval process.")
        stack = ExitStack()
        stack.callback(self._installation_lock.release)
        try:
            directory = self.cache_directory or Path(
                stack.enter_context(tempfile.TemporaryDirectory(prefix="scout-retained-repository-"))
            )
            self.prepare_bundle(Path(directory))
            original_clone = DockerSandbox.clone_repository

            def clone_repository(
                sandbox: DockerSandbox,
                repository: str,
                github_token: str | None = "",
                shallow: bool = True,
                branch: str | None = None,
                blobless: bool = False,
            ) -> ExecutionResult:
                if repository.lower() == self.repository:
                    return self._clone(sandbox)
                return original_clone(sandbox, repository, github_token, shallow, branch, blobless)

            stack.enter_context(patch.object(DockerSandbox, "clone_repository", clone_repository))
            stack.enter_context(
                patch.object(
                    lifecycle,
                    "FORCED_OFF_FEATURE_FLAGS",
                    lifecycle.FORCED_OFF_FEATURE_FLAGS | {OVERLAP_CLONE_BOOT_FEATURE_FLAG},
                )
            )
            stack.enter_context(
                patch.object(
                    sandbox_module, "PUBLIC_SANDBOX_REPOS", sandbox_module.PUBLIC_SANDBOX_REPOS | {self.repository}
                )
            )
        except BaseException:
            stack.close()
            raise
        self._stack = stack
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._stack is not None:
            self._stack.close()
            self._stack = None
