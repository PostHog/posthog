from __future__ import annotations

import re

import yaml
from pydantic import BaseModel, Field, field_validator

from products.tasks.backend.constants import RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS, is_blocked_sandbox_env_key

SANDBOX_IMAGE_SPEC_PATH = "/tmp/workspace/image-spec.yaml"

MAX_APT_PACKAGES = 128
MAX_RUN_COMMANDS = 64
MAX_COMMAND_LENGTH = 4096
MAX_ENV_VARS = 64
MAX_ENV_VALUE_LENGTH = 4096

_APT_PACKAGE_PATTERN = re.compile(r"^[a-z0-9][a-z0-9+.\-]*$")
_LINE_CONTINUATION_PATTERN = re.compile(r"[ \t]*\\\r?\n\s*")
_ENV_KEY_PATTERN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


class SandboxImageSpecError(ValueError):
    pass


class SandboxImageSpec(BaseModel):
    version: int = Field(default=1, description="Spec schema version; only 1 exists today and it may be omitted.")
    apt_packages: list[str] = Field(default_factory=list, description="Debian packages installed via apt-get.")
    run_commands: list[str] = Field(
        default_factory=list, description="Shell commands executed in order at image build time."
    )
    repo_setup_commands: list[str] = Field(
        default_factory=list,
        description="Commands run inside a fresh checkout of the image's linked repository at build time to warm "
        "dependency stores; the checkout is discarded, global caches persist.",
    )
    env: dict[str, str] = Field(default_factory=dict, description="Environment variables baked into the image.")

    @field_validator("version")
    @classmethod
    def _validate_version(cls, value: int) -> int:
        if value != 1:
            raise ValueError(
                f"Unsupported spec schema version {value}; only 1 exists (this field is the spec format "
                "version, not the image's build number — builds auto-increment on each save)"
            )
        return value

    @field_validator("apt_packages")
    @classmethod
    def _validate_apt_packages(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_APT_PACKAGES:
            raise ValueError(f"Too many apt packages (max {MAX_APT_PACKAGES})")
        for package in value:
            if not _APT_PACKAGE_PATTERN.match(package):
                raise ValueError(f"Invalid apt package name: {package!r}")
        return value

    @field_validator("run_commands", "repo_setup_commands")
    @classmethod
    def _validate_run_commands(cls, value: list[str]) -> list[str]:
        if len(value) > MAX_RUN_COMMANDS:
            raise ValueError(f"Too many run commands (max {MAX_RUN_COMMANDS})")
        normalized: list[str] = []
        for command in value:
            command = _LINE_CONTINUATION_PATTERN.sub(" ", command).strip()
            if not command:
                raise ValueError("Run commands must not be empty")
            if "\n" in command:
                raise ValueError(
                    "Run commands must be single-line: each command becomes one Dockerfile RUN "
                    "instruction, so embedded newlines break the build — chain steps with '&&'"
                )
            if len(command) > MAX_COMMAND_LENGTH:
                raise ValueError(f"Run command exceeds {MAX_COMMAND_LENGTH} characters")
            normalized.append(command)
        return normalized

    @field_validator("env")
    @classmethod
    def _validate_env(cls, value: dict[str, str]) -> dict[str, str]:
        if len(value) > MAX_ENV_VARS:
            raise ValueError(f"Too many env vars (max {MAX_ENV_VARS})")
        for key, val in value.items():
            if not _ENV_KEY_PATTERN.match(key):
                raise ValueError(f"Invalid env var key: {key!r}")
            if key in RESERVED_SANDBOX_ENVIRONMENT_VARIABLE_KEYS or is_blocked_sandbox_env_key(key):
                raise ValueError(f"Env var key {key!r} is not allowed in custom images")
            if len(val) > MAX_ENV_VALUE_LENGTH:
                raise ValueError(f"Env var {key!r} value exceeds {MAX_ENV_VALUE_LENGTH} characters")
        return value

    @property
    def is_empty(self) -> bool:
        return not self.apt_packages and not self.run_commands and not self.repo_setup_commands and not self.env

    def to_yaml(self) -> str:
        return yaml.safe_dump(self.model_dump(), sort_keys=False)


def validate_spec_buildable(spec: SandboxImageSpec, repository: str) -> None:
    if spec.repo_setup_commands and not repository:
        raise SandboxImageSpecError(
            "The spec has repo_setup_commands but the image has no linked repository to run them in; "
            "link a repository to the image or remove repo_setup_commands"
        )


def parse_image_spec_yaml(raw: str) -> SandboxImageSpec:
    try:
        data = yaml.safe_load(raw)
    except yaml.YAMLError as e:
        raise SandboxImageSpecError(f"Invalid YAML: {e}")
    if not isinstance(data, dict):
        raise SandboxImageSpecError("Image spec must be a YAML mapping")
    try:
        return SandboxImageSpec.model_validate(data)
    except ValueError as e:
        raise SandboxImageSpecError(str(e))


def parse_image_spec_json(data: dict) -> SandboxImageSpec:
    try:
        return SandboxImageSpec.model_validate(data)
    except ValueError as e:
        raise SandboxImageSpecError(str(e))


def spec_json_to_yaml(spec: dict) -> str:
    """User-facing YAML; omits `version: 1` — users mistake it for the build counter."""
    if not spec:
        return ""
    display = {key: value for key, value in spec.items() if key != "version" or value != 1}
    if not display:
        return ""
    return yaml.safe_dump(display, sort_keys=False)
