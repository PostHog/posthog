"""The attestation entries of a repository's policy, as the server reads them before the engine runs.

The engine parses and validates `.stamphog/policy.yml`. The server needs two things from it first:
the workflow publishers whose signed results it verifies, and the check names whose runs the engine
decides on. The engine refuses a policy with a malformed entry, so such an entry is skipped here.
"""

import yaml

from posthog.dataclasses import frozen

# The engine's `attestations.WORKFLOW_PROOF_KEY`, which the backend cannot import.
WORKFLOW_PROOF_KEY = "stamphog_workflow_proof"
# The engine's `policy.WORKFLOW_PUBLISHER_EVENTS`. The engine refuses a policy that names any other
# event, and the server checks each token against the same list.
_PUBLISHER_EVENTS = frozenset({"workflow_run", "pull_request_target"})
_ENTRY_KEYS = ("attestations", "extend_attestations")


@frozen
class WorkflowPublisher:
    """A workflow attestation entry of a repository's policy, as the server needs it."""

    name: str
    check: str
    workflow: str
    job: str
    events: tuple[str, ...]


def _text(entry: dict, key: str) -> str:
    value = entry.get(key)
    return value if isinstance(value, str) else ""


def workflow_publisher(entry: object) -> WorkflowPublisher | None:
    """The publisher one policy entry names, or None when the entry names no valid workflow publisher."""
    if not isinstance(entry, dict):
        return None
    name, check, workflow, job = (_text(entry, key) for key in ("name", "check", "workflow", "job"))
    if not (name and check and workflow and job):
        return None
    events = entry.get("events")
    if not isinstance(events, list) or not events:
        return None
    if not all(isinstance(event, str) and event in _PUBLISHER_EVENTS for event in events):
        return None
    return WorkflowPublisher(name=name, check=check, workflow=workflow, job=job, events=tuple(events))


def _entries(policy_text: str | None) -> list[object]:
    if not policy_text:
        return []
    try:
        parsed = yaml.safe_load(policy_text)
    except yaml.YAMLError:
        return []
    if not isinstance(parsed, dict):
        return []
    return [entry for key in _ENTRY_KEYS if isinstance(parsed.get(key), list) for entry in parsed[key]]


def workflow_publishers(policy_text: str | None) -> tuple[WorkflowPublisher, ...]:
    """The entries in the repository's policy that name a workflow publisher."""
    return tuple(publisher for entry in _entries(policy_text) if (publisher := workflow_publisher(entry)) is not None)


def attestation_check_names(policy_text: str | None) -> frozenset[str]:
    """The check name of every attestation entry in the repository's policy."""
    return frozenset(
        entry["check"]
        for entry in _entries(policy_text)
        if isinstance(entry, dict) and isinstance(entry.get("check"), str)
    )
