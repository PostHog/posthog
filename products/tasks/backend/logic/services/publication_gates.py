"""Protected-base publication gate policy parsing and execution contracts."""

import json
import hashlib
from pathlib import PurePosixPath
from typing import Literal

from posthog.dataclasses import frozen

from products.tasks.backend.logic.services.publication_base import TrustedBaseManifest

PUBLICATION_GATE_POLICY_PATH = ".posthog/pulse-publication-gates.json"
_MAX_GATES = 4
_MAX_ARGV_ENTRIES = 16
_MAX_ARG_BYTES = 256
_MAX_ARGV_BYTES = 500
_MAX_LABEL_BYTES = 80
_MAX_PROTECTED_PATH_PREFIXES = 32
_MAX_PROTECTED_PATH_PREFIX_BYTES = 240


class PublicationGatePolicyError(RuntimeError):
    """The protected-base gate policy cannot safely run in the candidate workspace."""


@frozen
class PublicationGateDefinition:
    label: str
    argv: tuple[str, ...]


@frozen
class ResolvedPublicationGatePolicy:
    status: Literal["ready", "unavailable"]
    reason: str | None
    source_path: str | None
    source_sha256: str | None
    gates: tuple[PublicationGateDefinition, ...]
    protected_path_prefixes: tuple[str, ...]


def resolve_publication_gate_policy(manifest: TrustedBaseManifest) -> ResolvedPublicationGatePolicy:
    """Read a controlled-dogfood gate manifest from the immutable GitHub base.

    The runner executes only ``argv`` arrays from this exact protected-base file.
    Workspace changes, model output, and repository instructions cannot create or
    alter gates. Repositories without the explicitly versioned contract fail closed.
    """
    document = manifest.old_text_for(PUBLICATION_GATE_POLICY_PATH)
    if document is None:
        return _unavailable()
    try:
        payload = json.loads(document)
    except json.JSONDecodeError:
        return _unavailable()
    parsed = _parse_policy(payload)
    if parsed is None:
        return _unavailable()
    gates, protected_path_prefixes = parsed
    return ResolvedPublicationGatePolicy(
        status="ready",
        reason=None,
        source_path=PUBLICATION_GATE_POLICY_PATH,
        source_sha256=hashlib.sha256(document.encode("utf-8")).hexdigest(),
        gates=gates,
        protected_path_prefixes=protected_path_prefixes,
    )


def assert_publication_gate_paths_safe(policy: ResolvedPublicationGatePolicy, changed_paths: tuple[str, ...]) -> None:
    """Reject candidate changes that could alter a protected-base gate before execution."""
    if policy.status != "ready" or not policy.protected_path_prefixes:
        raise PublicationGatePolicyError("gate_policy_unavailable")
    for path in changed_paths:
        if not _valid_path(path):
            raise PublicationGatePolicyError("publication_gate_protected_path_changed")
        if path == PUBLICATION_GATE_POLICY_PATH or any(
            path == prefix or path.startswith(f"{prefix}/") for prefix in policy.protected_path_prefixes
        ):
            raise PublicationGatePolicyError("publication_gate_protected_path_changed")


def _parse_policy(payload: object) -> tuple[tuple[PublicationGateDefinition, ...], tuple[str, ...]] | None:
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 2
        or set(payload) != {"version", "gates", "protected_path_prefixes"}
    ):
        return None
    raw_gates = payload.get("gates")
    raw_prefixes = payload.get("protected_path_prefixes")
    if not isinstance(raw_gates, list) or not raw_gates or len(raw_gates) > _MAX_GATES:
        return None
    protected_path_prefixes = _parse_protected_path_prefixes(raw_prefixes)
    if protected_path_prefixes is None:
        return None
    gates: list[PublicationGateDefinition] = []
    labels: set[str] = set()
    for raw_gate in raw_gates:
        if not isinstance(raw_gate, dict) or set(raw_gate) != {"label", "argv"}:
            return None
        label = raw_gate.get("label")
        argv = raw_gate.get("argv")
        if (
            not isinstance(label, str)
            or not isinstance(argv, list)
            or not all(isinstance(arg, str) for arg in argv)
            or not _valid_label(label)
            or not _valid_argv(argv)
            or label.casefold() in labels
        ):
            return None
        labels.add(label.casefold())
        gates.append(PublicationGateDefinition(label=label, argv=tuple(argv)))
    return tuple(gates), protected_path_prefixes


def _valid_label(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and value == value.strip()
        and "\x00" not in value
        and "\n" not in value
        and len(value.encode("utf-8")) <= _MAX_LABEL_BYTES
    )


def _valid_argv(value: object) -> bool:
    if not isinstance(value, list) or not value or len(value) > _MAX_ARGV_ENTRIES:
        return False
    if not all(
        isinstance(arg, str)
        and bool(arg.strip())
        and arg == arg.strip()
        and "\x00" not in arg
        and "\n" not in arg
        and len(arg.encode("utf-8")) <= _MAX_ARG_BYTES
        for arg in value
    ):
        return False
    return len(json.dumps(value, separators=(",", ":")).encode("utf-8")) <= _MAX_ARGV_BYTES


def _parse_protected_path_prefixes(value: object) -> tuple[str, ...] | None:
    if not isinstance(value, list) or not value or len(value) > _MAX_PROTECTED_PATH_PREFIXES:
        return None
    if not all(_valid_path(prefix) for prefix in value):
        return None
    prefixes: tuple[str, ...] = tuple(prefix for prefix in value if isinstance(prefix, str))
    if len(set(prefixes)) != len(prefixes):
        return None
    return prefixes


def _valid_path(value: object) -> bool:
    if not isinstance(value, str) or not value or "\x00" in value or "\\" in value:
        return False
    try:
        if len(value.encode("utf-8")) > _MAX_PROTECTED_PATH_PREFIX_BYTES:
            return False
    except UnicodeEncodeError:
        return False
    path = PurePosixPath(value)
    return not path.is_absolute() and str(path) == value and all(part not in {"", ".", ".."} for part in path.parts)


def _unavailable() -> ResolvedPublicationGatePolicy:
    return ResolvedPublicationGatePolicy(
        status="unavailable",
        reason="gate_policy_unavailable",
        source_path=None,
        source_sha256=None,
        gates=(),
        protected_path_prefixes=(),
    )
