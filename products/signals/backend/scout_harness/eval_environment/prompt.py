from __future__ import annotations

import re
import stat
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Literal, Self, cast
from uuid import UUID

from pydantic import Field, model_validator

from products.posthog_ai.eval_harness.environment.schema import EnvironmentModel
from products.posthog_ai.eval_harness.environment.storage import require_private_path
from products.posthog_ai.eval_harness.environment.transform import EnvironmentTransform
from products.signals.backend.scout_harness.eval_environment.schema import ScoutPromptTransformation
from products.signals.backend.scout_harness.eval_environment.trials import FrozenEnvironment
from products.signals.backend.scout_harness.prompt import _run_note_section


class ScoutRuntimeContext(EnvironmentModel):
    team_id: int
    config_id: UUID
    skill_name: str
    skill_version: int
    allowed_tools: list[str]
    harness_prompt_version: str
    frozen_inputs: dict[str, str]
    frozen_manifest: str


class NativeScoutPrompt(ScoutRuntimeContext):
    prompt_mode: Literal["native"] = "native"


class RecordedScoutPrompt(ScoutRuntimeContext):
    prompt_mode: Literal["recorded"] = "recorded"
    recorded_prompt: str
    prompt_transformations: list[ScoutPromptTransformation] = Field(default_factory=list)
    replacements: dict[str, str] = Field(default_factory=dict)
    time_strings: list[str] = Field(default_factory=list)
    source_project_url: str | None = None
    target_project_url: str | None = None

    def transformed_instructions(self) -> str:
        prompt = self.recorded_prompt
        for transformation in self.prompt_transformations:
            if prompt.count(transformation.source) != transformation.expected_occurrences:
                raise ValueError("A declared prompt transformation no longer matches its recorded source.")
            prompt = prompt.replace(transformation.source, transformation.replacement)
        return prompt

    @model_validator(mode="after")
    def validate_transformations(self) -> Self:
        self.transformed_instructions()
        return self

    def render(self, *, run_id: str, started_at: datetime, run_note: str) -> str:
        prompt = self.transformed_instructions()
        if "" in self.replacements:
            raise ValueError("Recorded prompt replacements cannot have empty keys.")
        if self.replacements:
            replacement_pattern = EnvironmentTransform._replacement_pattern(self.replacements, set(self.time_strings))
            if replacement_pattern:
                prompt = replacement_pattern.sub(lambda match: self.replacements[match[0]], prompt)
        prompt = EnvironmentTransform.bind_project_url(prompt, self.source_project_url, self.target_project_url)
        for field, value in (
            ("team_id", str(self.team_id)),
            ("run_id", run_id),
            ("started_at", started_at.replace(microsecond=0).isoformat()),
        ):
            pattern = rf"(?m)^(- \*\*{field}\*\*: `)[^`]+(`)"

            def replace_identity(match: re.Match[str], replacement: str = value) -> str:
                return match[1] + replacement + match[2]

            prompt, count = re.subn(pattern, replace_identity, prompt)
            if count != 1:
                raise ValueError(f"Recorded prompt must contain exactly one {field} identity line.")
        prompt, count = re.subn(
            r"<run_note>\n[\s\S]*?\n</run_note>", lambda _: "<run_note>\n" + run_note + "\n</run_note>", prompt
        )
        if count > 1:
            raise ValueError("Recorded prompt must contain at most one one-time steering block.")
        if count == 0 and (section := _run_note_section(run_note)):
            # A run without a note records no block, and the live harness renders the note section last.
            prompt += "\n\n" + section
        return prompt


def _read_runtime_prompt[TPrompt: RecordedScoutPrompt | NativeScoutPrompt](
    path: Path, document_type: type[TPrompt]
) -> TPrompt:
    path = require_private_path(path)
    mode = path.lstat().st_mode
    if not stat.S_ISREG(mode) or stat.S_IMODE(mode) & 0o077:
        raise ValueError("Scout runtime configuration must be an owner-only regular private file.")
    content = path.read_bytes()
    document = document_type.model_validate_json(content)
    manifest_path = require_private_path(Path(document.frozen_manifest))
    frozen = FrozenEnvironment.model_validate_json(manifest_path.read_bytes())
    frozen.verify()
    if (
        frozen.runtime_prompt_path != str(path)
        or frozen.runtime_prompt_sha256 != hashlib.sha256(content).hexdigest()
        or frozen.team_id != document.team_id
        or frozen.config_id != document.config_id
        or frozen.inputs != document.frozen_inputs
        or frozen.prompt_mode != document.prompt_mode
    ):
        raise ValueError("The scout runtime configuration does not match its frozen environment.")
    # Pydantic constructs the concrete class passed in, while mypy widens Self over the union bound.
    return cast("TPrompt", document)


def read_native_prompt(path: Path) -> NativeScoutPrompt:
    return _read_runtime_prompt(path, NativeScoutPrompt)


def read_recorded_prompt(path: Path) -> RecordedScoutPrompt:
    return _read_runtime_prompt(path, RecordedScoutPrompt)


def recorded_prompt_override(
    *,
    path: str,
    debug: bool,
    team_id: int,
    config_id: UUID,
    skill_name: str,
    skill_version: int,
    allowed_tools: list[str],
    run_id: str,
    started_at: datetime,
    run_note: str,
    is_private_trial: bool,
) -> RecordedPromptOverride | None:
    if not debug:
        raise ValueError("Recorded scout prompts are available only in a local DEBUG environment.")
    document = read_recorded_prompt(Path(path))
    if document.team_id != team_id or document.skill_name != skill_name:
        return None
    if (
        not is_private_trial
        or document.config_id != config_id
        or document.skill_version != skill_version
        or document.allowed_tools != allowed_tools
    ):
        raise ValueError("The run does not match the frozen private scout configuration.")
    prompt = document.render(run_id=run_id, started_at=started_at, run_note=run_note)
    return RecordedPromptOverride(
        text=prompt,
        harness_prompt_version=document.harness_prompt_version,
        sha256=hashlib.sha256(prompt.encode()).hexdigest(),
    )


class RecordedPromptOverride(EnvironmentModel):
    text: str
    harness_prompt_version: str
    sha256: str
