"""The owner tag a destination stores on the final tables it creates.

A destination that has table comments stores the tag there, as a JSON object with a version key:

    {"posthog_destination": 1, "owner_tag": "a"}

The version key lets the object gain keys later. A comment that is not a JSON object with the
version key is not tagged. A comment that has the version key but that this code cannot read
(another version, or an owner tag that is not a string) is malformed. Neither carries a tag, and
`parse` never raises for them.
"""

import json

_VERSION_KEY = "posthog_destination"
_VERSION = 1


def encode(owner_tag: str) -> str:
    """Return the comment that tags a table with `owner_tag`."""
    return json.dumps({_VERSION_KEY: _VERSION, "owner_tag": owner_tag}, sort_keys=True, separators=(",", ":"))


def parse(comment: str | None) -> str | None:
    """Return the owner tag in `comment`, or None for a missing, untagged or malformed comment."""
    if not comment:
        return None
    try:
        payload = json.loads(comment)
    except ValueError:
        return None
    if not isinstance(payload, dict) or _VERSION_KEY not in payload:
        return None

    owner_tag = payload.get("owner_tag")
    if payload[_VERSION_KEY] != _VERSION or not isinstance(owner_tag, str):
        return None
    return owner_tag


def is_tagged_with(comment: str | None, owner_tag: str) -> bool:
    """Whether the table with `comment` carries exactly `owner_tag`.

    A comment that is not tagged counts only when it equals the tag itself, so a table tagged
    with the plain tag text before the JSON format existed is still recognized.
    """
    tag = parse(comment)
    if tag is None:
        return comment == owner_tag
    return tag == owner_tag
