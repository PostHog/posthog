from .situations import SITUATION_IDS

_DEFAULT_BINDINGS: dict[str, list[dict]] = {
    "working": [
        {
            "id": "create_pr",
            "label": "Create PR",
            "skillId": "",
            "prompt": "Open a PR for the current branch. Use the task history to write a concise description.",
        },
    ],
    "in_review": [],
    "ci_failing": [
        {
            "id": "fix_ci",
            "label": "Fix CI",
            "skillId": "",
            "prompt": "CI is failing on this PR. Investigate the failing checks and push a fix.",
        },
    ],
    "changes_requested": [
        {
            "id": "address_comments",
            "label": "Address review",
            "skillId": "",
            "prompt": "Address the change requests on this PR — read the latest review and respond with code.",
        },
    ],
    "comments_waiting": [
        {
            "id": "address_threads",
            "label": "Address comments",
            "skillId": "",
            "prompt": "Address the unresolved review comments on this PR.",
        },
    ],
    "ready_to_merge": [
        {
            "id": "final_check",
            "label": "Final check",
            "skillId": "",
            "prompt": "Do a last-pass review of this PR. Call out anything risky before I merge.",
        },
    ],
    "stale": [],
    "done": [],
}


def build_default_bindings() -> dict[str, list[dict]]:
    return {sid: [dict(action) for action in _DEFAULT_BINDINGS.get(sid, [])] for sid in SITUATION_IDS}
