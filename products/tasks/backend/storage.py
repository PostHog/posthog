import json
from typing import Any

from posthog.storage import object_storage


def append_jsonl_object(object_storage_key: str, entries: list[dict[str, Any]]) -> bool:
    existing_content = object_storage.read(object_storage_key, missing_ok=True) or ""
    is_new_object = not existing_content
    new_lines = "\n".join(json.dumps(entry) for entry in entries)
    content = existing_content + ("\n" if existing_content else "") + new_lines

    object_storage.write(object_storage_key, content)

    return is_new_object
