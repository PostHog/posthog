from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from products.posthog_ai.eval_harness.environment.storage import file_sha256, require_private_path
from products.signals.backend.scout_harness.eval_environment.schema import ScoutEnvironmentCase, ScoutEnvironmentSeed
from products.signals.backend.scout_harness.eval_environment.support import ScoutEnvironmentSupport
from products.signals.backend.scout_harness.profile_version import INVENTORY_SOURCE_VERSION

if TYPE_CHECKING:
    from products.posthog_ai.eval_harness.environment.restore import EnvironmentReceipt
    from products.posthog_ai.eval_harness.environment.schema import EnvironmentManifest


class ScoutEnvironmentBundle:
    @staticmethod
    def load(path: Path) -> ScoutEnvironmentCase:
        case = ScoutEnvironmentCase.model_validate_json(require_private_path(path).read_bytes())
        ScoutEnvironmentSupport.validate(case)
        if case.prompt_mode == "native":
            profile = case.state.profile
            if profile is None or profile.fields.get("source_version") != INVENTORY_SOURCE_VERSION:
                raise ValueError("Native scout bundles require the current cached project profile.")
            expiry = profile.fields.get("expires_at")
            if not isinstance(profile.fields.get("payload"), dict) or not isinstance(expiry, str):
                raise ValueError("The cached project profile requires its payload and expiry.")
            if datetime.fromisoformat(expiry.replace("Z", "+00:00")) <= case.source_cutoff:
                raise ValueError("Native scout bundles require a project profile fresh at the source cutoff.")
        if case.prompt_mode == "recorded":
            if not case.recorded_prompt or not case.expected_harness_prompt_version:
                raise ValueError("Recorded scout bundles require the full prompt and its harness version.")
            prompt = case.recorded_prompt
            for change in case.prompt_transformations:
                if prompt.count(change.source) != change.expected_occurrences:
                    raise ValueError("Recorded prompt transformations do not match their source.")
                prompt = prompt.replace(change.source, change.replacement)
            for name in ("team_id", "run_id", "started_at"):
                if len(re.findall(rf"(?m)^- \*\*{name}\*\*: `[^`]+`", prompt)) != 1:
                    raise ValueError("Recorded scout prompts require exactly one run identity line per field.")
            if len(re.findall(r"<run_note>\n[\s\S]*?\n</run_note>", prompt)) > 1:
                raise ValueError("Recorded scout prompts cannot contain multiple steering blocks.")
        return case

    @classmethod
    def validate(cls, path: Path, manifest: EnvironmentManifest) -> None:
        case = cls.load(path)
        if (
            case.environment_id != manifest.environment_id
            or case.source_cutoff != manifest.source_cutoff
            or case.checkpoint != manifest.checkpoint
            or case.timezone != manifest.timezone
            or case.time_strings != manifest.time_strings
            or case.string_replacements != manifest.string_replacements
            or case.source_project_url != manifest.source_project_url
        ):
            raise ValueError("The scout attachment and data must share identity, cutoff, timezone and text policy.")

    @classmethod
    def preflight(cls, path: Path, receipt: EnvironmentReceipt) -> None:
        from django.core.exceptions import ValidationError  # noqa: PLC0415 — only model validation needs Django

        from products.signals.backend.scout_harness.eval_environment.state import (  # noqa: PLC0415 — Django models are available only after environment validation
            ScoutEnvironmentState,
        )

        try:
            ScoutEnvironmentState.validate_input(cls.load(path), receipt)
        except (ValidationError, ValueError, TypeError):
            raise ValueError("The scout attachment is incompatible with the supported local models.") from None

    @classmethod
    def restore(cls, path: Path, receipt: EnvironmentReceipt, workspace: Path) -> str:
        from products.signals.backend.scout_harness.eval_environment.ingestion import (  # noqa: PLC0415 — restore runs after Django setup
            ScoutEnvironmentIngestion,
        )
        from products.signals.backend.scout_harness.eval_environment.state import (  # noqa: PLC0415 — restore runs after Django setup
            ScoutEnvironmentState,
        )
        from products.signals.backend.scout_harness.eval_environment.trials import (  # noqa: PLC0415 — trials import Django-backed services
            write_private_json,
        )

        seed_path = workspace / "scout-seed.json"
        if seed_path.exists() or seed_path.is_symlink():
            raise ValueError("Scout state already exists; restore into a fresh workspace.")
        case = cls.load(path)
        seed = ScoutEnvironmentState.seed(case, receipt)
        ScoutEnvironmentIngestion.prepare(receipt)
        ScoutEnvironmentState.verify(case, receipt, seed)
        write_private_json(seed_path, seed)
        return file_sha256(seed_path)

    @classmethod
    def verify(cls, path: Path, receipt: EnvironmentReceipt, workspace: Path, seed_sha256: str | None) -> None:
        from products.signals.backend.scout_harness.eval_environment.ingestion import (  # noqa: PLC0415 — verification runs after Django setup
            ScoutEnvironmentIngestion,
        )
        from products.signals.backend.scout_harness.eval_environment.state import (  # noqa: PLC0415 — verification runs after Django setup
            ScoutEnvironmentState,
        )

        seed_path = require_private_path(workspace / "scout-seed.json")
        if seed_sha256 is None or not seed_path.is_file() or file_sha256(seed_path) != seed_sha256:
            raise ValueError("The restored scout seed changed or is incomplete; use a fresh workspace.")
        seed = ScoutEnvironmentSeed.model_validate_json(seed_path.read_bytes())
        ScoutEnvironmentState.verify(cls.load(path), receipt, seed)
        ScoutEnvironmentIngestion.verify(receipt)

    @staticmethod
    def freeze(path: Path, bundle: Path, workspace: Path) -> None:
        from products.signals.backend.scout_harness.eval_environment.cli import (  # noqa: PLC0415 — freeze uses Django-backed preparation
            ScoutEnvironmentCommand,
        )

        ScoutEnvironmentCommand(workspace).freeze(path, bundle)
