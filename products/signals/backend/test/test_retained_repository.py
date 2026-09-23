from __future__ import annotations

import os
import tempfile
import subprocess
from pathlib import Path, PurePosixPath

import unittest

from products.signals.evals.agentic.retained_repository import RetainedScoutRepository


class TestRetainedScoutRepository(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.source = self.root / "source with 'quotes'"
        self.source.mkdir()
        self.environment = {
            **os.environ,
            "GIT_CONFIG_GLOBAL": str(self.root / "gitconfig"),
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
        self.git(self.source, "init", "--initial-branch=master")
        self.first = self.commit("original")
        self.saved = self.commit("saved")
        self.future = self.commit("future")
        self.fixture = RetainedScoutRepository(self.source, self.saved)
        self.bundle = self.fixture.prepare_bundle(self.root / "retained")

    def git(self, directory: Path, *arguments: str) -> str:
        return subprocess.run(
            ["git", "-C", str(directory), *arguments],
            env=self.environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        ).stdout.strip()

    def commit(self, content: str) -> str:
        (self.source / "api.py").write_text(content)
        self.git(self.source, "add", "api.py")
        self.git(
            self.source,
            "-c",
            "user.name=Fixture author",
            "-c",
            "user.email=fixture@example.com",
            "-c",
            "commit.gpgsign=false",
            "commit",
            "-m",
            content,
        )
        return self.git(self.source, "rev-parse", "HEAD")

    def materialize(self, name: str) -> Path:
        workspace = self.root / name
        subprocess.run(
            ["bash", "-c", self.fixture.checkout_command(PurePosixPath(self.bundle), PurePosixPath(workspace))],
            env=self.environment,
            check=True,
            capture_output=True,
            text=True,
            timeout=15,
        )
        return workspace / "repos" / "posthog" / "posthog"

    def test_fetches_keep_saved_commit_and_history_without_future_objects(self) -> None:
        checkout = self.materialize("trial with 'quotes' and $(false)")
        self.commit("later")

        self.git(checkout, "fetch", "origin")
        self.git(checkout, "fetch", "https://github.com/PostHog/posthog.git", "master")

        self.assertEqual(
            self.git(checkout, "rev-parse", "HEAD", "origin/HEAD", "FETCH_HEAD").splitlines(), [self.saved] * 3
        )
        self.assertEqual(self.git(checkout, "rev-parse", "HEAD^"), self.first)
        self.assertEqual((checkout / "api.py").read_text(), "saved")
        future = subprocess.run(
            ["git", "-C", str(checkout), "cat-file", "-e", self.future],
            env=self.environment,
            capture_output=True,
            timeout=15,
        )
        self.assertNotEqual(future.returncode, 0)

    def test_trials_have_separate_writable_checkouts_and_frozen_origins(self) -> None:
        first_checkout = self.materialize("first")
        second_checkout = self.materialize("second")

        (first_checkout / "api.py").write_text("trial-specific edit")
        self.git(first_checkout, "update-ref", "refs/remotes/origin/master", self.first)

        self.assertEqual((second_checkout / "api.py").read_text(), "saved")
        self.assertEqual(self.git(second_checkout, "rev-parse", "origin/HEAD"), self.saved)
        self.assertNotEqual(
            self.git(first_checkout, "remote", "get-url", "origin"),
            self.git(second_checkout, "remote", "get-url", "origin"),
        )
        self.git(first_checkout, "fetch", "origin")
        self.assertEqual(self.git(first_checkout, "rev-parse", "origin/HEAD"), self.saved)
        self.assertEqual((first_checkout / "api.py").read_text(), "trial-specific edit")
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.future)

    def test_one_commit_retention_restores_shallow_boundary_and_reuses_verified_cache(self) -> None:
        self.fixture = RetainedScoutRepository(self.source, self.saved, history_depth=1)
        self.bundle = self.fixture.prepare_bundle(self.root / "shallow")
        checkout = self.materialize("shallow-trial")

        self.git(checkout, "fetch", "origin")

        self.assertEqual(self.git(checkout, "rev-parse", "HEAD", "origin/HEAD").splitlines(), [self.saved] * 2)
        self.assertEqual(self.git(checkout, "rev-list", "--count", "HEAD"), "1")
        self.assertEqual(self.git(checkout, "rev-parse", "--is-shallow-repository"), "true")
        self.assertEqual((checkout / "api.py").read_text(), "saved")
        cached = RetainedScoutRepository(self.root / "unavailable-source", self.saved, history_depth=1)
        self.assertEqual(cached.prepare_bundle(self.root / "shallow"), self.bundle)
        self.assertEqual(cached.metadata, self.fixture.metadata)
        with self.bundle.open("ab") as content:
            content.write(b"corrupt")
        with self.assertRaisesRegex(ValueError, "checksum"):
            cached.prepare_bundle(self.root / "shallow")

    def test_corrupt_bundle_fails_before_creating_a_checkout(self) -> None:
        with self.bundle.open("ab") as content:
            content.write(b"corrupt")

        with self.assertRaises(subprocess.CalledProcessError):
            self.materialize("corrupt")

        self.assertFalse((self.root / "corrupt" / "repos").exists())

    def test_missing_commit_fails_without_changing_source(self) -> None:
        fixture = RetainedScoutRepository(self.source, "0" * 40)

        with self.assertRaises(subprocess.CalledProcessError):
            fixture.prepare_bundle(self.root / "missing")

        self.assertFalse((self.root / "missing").exists())
        self.assertEqual(self.git(self.source, "rev-parse", "HEAD"), self.future)
