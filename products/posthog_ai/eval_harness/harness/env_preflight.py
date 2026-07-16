"""Environment loading and validation for the eval harness.

Django-free on purpose: ``__main__`` loads the env file before ``django.setup()``,
so nothing here may touch Django settings or the ORM.
"""

from __future__ import annotations

import os
import re
from collections.abc import Collection
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..engines.types import EnvVarSpec
from .providers import PreflightError
from .requirements import SuiteKind

REPO_ROOT = Path(__file__).parents[4]

_ASSIGNMENT_RE = re.compile(r"^\s*(?:export\s+)?(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?P<value>.*)$")
_ESCAPES = {"n": "\n", "r": "\r", "t": "\t", '"': '"', "'": "'", "\\": "\\"}


class SandboxEvalEnv(BaseModel):
    """Additional variables sandboxed suites need."""

    model_config = ConfigDict(extra="ignore")

    SANDBOX_JWT_PRIVATE_KEY: str = Field(
        min_length=1,
        description="signs the sandboxed agent's API tokens; the dev key ships in .env.example",
    )
    LLM_GATEWAY_ANTHROPIC_API_KEY: str = Field(
        min_length=1,
        description="Anthropic API key the LLM gateway proxies the agent's model calls with",
    )


class OneShotEvalEnv(BaseModel):
    """Additional variables one-shot suites need."""

    model_config = ConfigDict(extra="ignore")

    LLM_GATEWAY_ANTHROPIC_API_KEY: str = Field(
        min_length=1,
        description="Anthropic API key one-shot generation tasks call the model with directly",
    )


class CodexEvalEnv(BaseModel):
    """Additional variables required when sandboxed suites use the codex runtime."""

    model_config = ConfigDict(extra="ignore")

    LLM_GATEWAY_OPENAI_API_KEY: str = Field(
        min_length=1,
        description="OpenAI API key the LLM gateway proxies the codex agent's model calls with",
    )


ENV_MODELS_BY_KIND: dict[SuiteKind, tuple[type[BaseModel], ...]] = {
    SuiteKind.SANDBOXED: (SandboxEvalEnv,),
    SuiteKind.ONE_SHOT: (OneShotEvalEnv,),
}


def _read_quoted(text: str, quote: str) -> tuple[str, bool]:
    """Consume ``text`` up to an unescaped closing ``quote``; returns (body, closed)."""
    escaped = False
    for idx, char in enumerate(text):
        if quote == '"' and char == "\\" and not escaped:
            escaped = True
            continue
        if char == quote and not escaped:
            return text[:idx], True
        escaped = False
    return text, False


def _decode_escapes(value: str) -> str:
    return re.sub(r"\\(.)", lambda m: _ESCAPES.get(m.group(1), f"\\{m.group(1)}"), value)


def parse_env_file(path: Path) -> dict[str, str]:
    """Parse a ``.env`` file with the stdlib (no python-dotenv dependency).

    Handles what PostHog's env files actually use: blank lines, ``#`` comments,
    optional ``export`` prefixes, unquoted values with trailing inline comments,
    single-quoted literals, and double-quoted values with escape decoding
    (``"...\\n..."`` PEM keys) and multiline continuation.
    """
    values: dict[str, str] = {}
    lines = path.read_text().splitlines()
    index = 0
    while index < len(lines):
        line = lines[index]
        index += 1
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        match = _ASSIGNMENT_RE.match(line)
        if not match:
            continue
        key, raw = match.group("key"), match.group("value").strip()
        if raw[:1] in ('"', "'"):
            quote = raw[0]
            body, closed = _read_quoted(raw[1:], quote)
            while not closed and index < len(lines):
                more, closed = _read_quoted(lines[index], quote)
                index += 1
                body = f"{body}\n{more}"
            values[key] = _decode_escapes(body) if quote == '"' else body
        else:
            values[key] = re.split(r"\s+#", raw, maxsplit=1)[0].rstrip()
    return values


def load_env_file() -> None:
    """Load the repo-root ``.env`` into the environment, shell values winning.

    Replaces the manual ``set -a; source .env; set +a`` incantation. Only ``.env``
    is loaded here: hogli already loads ``.env.local`` / ``.env.development`` /
    ``.env.services`` before `hogli evals:sandboxed` reaches this process, and its
    line-based parser cannot represent ``.env``'s quoted/escaped PEM keys — so
    this file is the harness's job, via ``parse_env_file``, which decodes them
    correctly. ``setdefault`` keeps hogli's precedence: anything already exported
    (by the shell or by hogli's env loading) wins over ``.env``.
    """
    env_file = REPO_ROOT / ".env"
    if not env_file.exists():
        return
    for key, value in parse_env_file(env_file).items():
        os.environ.setdefault(key, value)


def validate_eval_env(
    agent_runtime: str = "claude",
    *,
    kinds: Collection[SuiteKind] = (SuiteKind.SANDBOXED,),
    engine_env: Collection[EnvVarSpec] = (),
) -> None:
    """Fail fast, before any infrastructure boots, if a required variable is unset.

    ``engine_env`` is the selected engine's ``required_env()`` (e.g. the Braintrust
    engine's ``BRAINTRUST_API_KEY``). Only the env models for the selected suites'
    kinds are checked, so a run without sandboxed suites doesn't demand sandbox
    credentials. Without this a missing key surfaces minutes into a run as an
    opaque mid-case failure (gateway 401s, engine login errors) instead of a
    one-line fix.
    """
    models: list[type[BaseModel]] = []
    for kind, kind_models in ENV_MODELS_BY_KIND.items():
        if kind in kinds:
            models.extend(kind_models)
    if SuiteKind.SANDBOXED in kinds and agent_runtime == "codex":
        models.append(CodexEvalEnv)

    lines = []
    seen: set[str] = set()
    # Engine env first, so its line (e.g. BRAINTRUST_API_KEY) leads the report as
    # the core CoreEvalEnv field used to.
    for spec in engine_env:
        if spec.name in seen or os.environ.get(spec.name):
            continue
        seen.add(spec.name)
        lines.append(f"  - {spec.name}: {spec.description}")
    for model in models:
        try:
            model.model_validate(dict(os.environ))
        except ValidationError as e:
            fields = model.model_fields
            for error in e.errors():
                name = str(error["loc"][0]) if error["loc"] else "?"
                if name in seen:
                    continue
                seen.add(name)
                description = fields[name].description if name in fields else ""
                lines.append(f"  - {name}: {description}")
    if lines:
        raise PreflightError(
            "Missing required environment variables:\n"
            + "\n".join(lines)
            + f"\nExport them in your shell, add them to {REPO_ROOT / '.env'} (loaded automatically), "
            "or keep them in .env.local and run via `hogli evals:sandboxed`."
        )
