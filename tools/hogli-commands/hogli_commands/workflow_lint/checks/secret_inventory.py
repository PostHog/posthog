"""Every ``secrets.NAME`` read from a store is declared in the secrets inventory.

An undeclared secret is not a syntax error: GitHub interpolates a missing
secret to an empty string, so the step runs with a blank credential and
whatever it guards silently does nothing. Two references in this repo already
resolve that way. Declaring the reads makes a typo or an unprovisioned secret
a lint failure instead of a feature that quietly stopped working.

Names a reusable workflow declares under ``on.workflow_call.secrets`` are
*inputs* supplied by its callers, not store reads, so they are excluded here
and checked by WF011 instead.

Variables are out of scope. ``vars.X`` is unset-means-off for kill switches
such as ``PRIVATE_SYNC_PAUSED``, so an absent variable is a legitimate state
and requiring declaration would reject working workflows.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml
from hogli.manifest import REPO_ROOT

from ..check import CheckResult, Issue, WorkflowCheck
from ..model import Workflow

INVENTORY_PATH = Path(".github") / "secrets-inventory.yml"
VALID_STORES = ("org", "repo", "missing")
ENVIRONMENT_PREFIX = "environment:"

# GITHUB_TOKEN is minted per run, never provisioned, so it is never declared.
IMPLICIT_SECRETS = frozenset({"GITHUB_TOKEN"})

_SECRET_REF = re.compile(r"secrets\.([A-Za-z0-9_]+)")


def _declared_call_secrets(wf: Workflow) -> set[str]:
    """Names this workflow accepts from its callers, which are inputs rather than store reads."""
    on = wf.on
    if not isinstance(on, dict):
        return set()
    call = on.get("workflow_call")
    if not isinstance(call, dict):
        return set()
    secrets = call.get("secrets")
    return set(secrets.keys()) if isinstance(secrets, dict) else set()


def _store_reads(wf: Workflow) -> set[str]:
    """Secret names this workflow reads from a store, in source order-independent form."""
    text = wf.path.read_text(encoding="utf-8")
    return set(_SECRET_REF.findall(text)) - IMPLICIT_SECRETS - _declared_call_secrets(wf)


def _store_is_valid(store: object) -> bool:
    if not isinstance(store, str):
        return False
    if store.startswith(ENVIRONMENT_PREFIX):
        return len(store) > len(ENVIRONMENT_PREFIX)
    return store in VALID_STORES


class SecretInventoryCheck(WorkflowCheck):
    id = "WF010-secret-inventory"
    label = "secret inventory"
    description = f"every secrets.NAME read from a store is declared in {INVENTORY_PATH}"

    def __init__(self, repo_root: Path | None = None) -> None:
        # Injected so tests can point at a fixture tree without monkeypatching env vars.
        self._repo_root = repo_root or REPO_ROOT

    @property
    def fix_hint(self) -> str | None:
        return (
            f"Add the secret to {INVENTORY_PATH} with the store that provides it "
            "(org, repo, environment:<name>, or missing plus a note)."
        )

    def run(self, workflows: list[Workflow]) -> CheckResult:
        result = CheckResult()
        inventory_file = self._repo_root / INVENTORY_PATH

        if not inventory_file.exists():
            result.issues.append(
                Issue(
                    workflow=INVENTORY_PATH.name,
                    message=f"{INVENTORY_PATH} is missing; WF010 cannot verify secret references",
                    file=str(inventory_file),
                )
            )
            return result

        try:
            raw = yaml.safe_load(inventory_file.read_text(encoding="utf-8"))
        except yaml.YAMLError as exc:
            result.issues.append(
                Issue(
                    workflow=INVENTORY_PATH.name,
                    message=f"{INVENTORY_PATH} failed to parse as YAML: {exc}",
                    file=str(inventory_file),
                )
            )
            return result

        entries = raw.get("secrets") if isinstance(raw, dict) else None
        if not isinstance(entries, dict):
            result.issues.append(
                Issue(
                    workflow=INVENTORY_PATH.name,
                    message=f"{INVENTORY_PATH} must define a top-level `secrets:` mapping",
                    file=str(inventory_file),
                )
            )
            return result

        for name, entry in sorted(entries.items()):
            body = entry if isinstance(entry, dict) else {}
            store = body.get("store")
            if not _store_is_valid(store):
                result.issues.append(
                    Issue(
                        workflow=INVENTORY_PATH.name,
                        message=(
                            f"{name}: store must be one of {', '.join(VALID_STORES)} "
                            f"or {ENVIRONMENT_PREFIX}<name>, got {store!r}"
                        ),
                        file=str(inventory_file),
                    )
                )
            elif store == "missing" and not body.get("note"):
                result.issues.append(
                    Issue(
                        workflow=INVENTORY_PATH.name,
                        message=f"{name}: store is 'missing', so it needs a note saying what breaks",
                        file=str(inventory_file),
                    )
                )

        for wf in workflows:
            for name in sorted(_store_reads(wf)):
                if name not in entries:
                    result.issues.append(
                        Issue(
                            workflow=wf.path.name,
                            message=f"reads secrets.{name}, which is not declared in {INVENTORY_PATH}",
                            file=str(wf.path),
                        )
                    )

        return result
