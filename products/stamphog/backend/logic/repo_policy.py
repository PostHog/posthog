"""Read lists from a repository's default-branch `.stamphog/policy.yml` on the server.

The engine validates the whole policy and fails the review on a malformed one, so an entry this
cannot read is skipped here rather than reported twice. The repository's list and its
`extend_<name>` list both count, because the server reads no shipped default to extend.
"""

import yaml


def policy_list(policy_text: str | None, key: str) -> list[dict]:
    try:
        raw = yaml.safe_load(policy_text or "")
    except yaml.YAMLError:
        return []
    if not isinstance(raw, dict):
        return []
    return [
        entry
        for name in (key, f"extend_{key}")
        if isinstance(listed := raw.get(name), list)
        for entry in listed
        if isinstance(entry, dict)
    ]
