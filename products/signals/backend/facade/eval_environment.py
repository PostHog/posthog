from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from products.signals.backend.scout_harness.eval_environment.bundle import ScoutEnvironmentBundle

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt
    from products.posthog_ai.eval_harness.environment.schema import EnvironmentManifest


def validate_scout_bundle(path: Path, manifest: EnvironmentManifest) -> None:
    ScoutEnvironmentBundle.validate(path, manifest)


def preflight_scout_bundle(path: Path, receipt: EnvironmentReceipt) -> None:
    ScoutEnvironmentBundle.preflight(path, receipt)


def restore_scout_bundle(path: Path, receipt: EnvironmentReceipt, workspace: Path) -> str:
    return ScoutEnvironmentBundle.restore(path, receipt, workspace)


def verify_scout_bundle(path: Path, receipt: EnvironmentReceipt, workspace: Path, seed_sha256: str | None) -> None:
    ScoutEnvironmentBundle.verify(path, receipt, workspace, seed_sha256)


def freeze_scout_bundle(path: Path, bundle: Path, workspace: Path) -> None:
    ScoutEnvironmentBundle.freeze(path, bundle, workspace)
