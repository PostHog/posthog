"""Strip the soft-delete tombstone suffix from feature flag keys.

FeatureFlag.tombstoned_key() renames a flag's key to "<original>:deleted:<id>" when
soft-deleting a flag that's still referenced elsewhere (e.g. a stopped experiment) --
this mirrors FeatureFlag.key_without_tombstone() in
products/feature_flags/backend/models/feature_flag.py so activity-log and SQL results
outside Django can recover the original key the same deterministic way. See step 5 of
the skill's SKILL.md for why this beats reading the activity log's detail fields.

Usage: pass a JSON array of {"id": ..., "key": ...} objects (e.g. the step 2 SQL
results for every candidate at once) as a file argument or on stdin. Prints the same
array back with an added "original_key" field on each object.

  echo '[{"id": 12345, "key": "foo:deleted:12345"}]' | python3 scripts/strip_deleted_suffix.py
  python3 scripts/strip_deleted_suffix.py candidates.json
"""

import json
import sys


def strip_suffix(flag_id, key):
    suffix = f":deleted:{flag_id}"
    return key[: -len(suffix)] if key.endswith(suffix) else key


def main():
    raw = open(sys.argv[1]).read() if len(sys.argv) > 1 else sys.stdin.read()
    candidates = json.loads(raw)
    for candidate in candidates:
        candidate["original_key"] = strip_suffix(candidate["id"], candidate["key"])
    print(json.dumps(candidates, indent=2))


if __name__ == "__main__":
    main()
