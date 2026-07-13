"""Strip the soft-delete tombstone suffix from a feature flag key.

FeatureFlag.tombstoned_key() renames a flag's key to "<original>:deleted:<id>" when
soft-deleting a flag that's still referenced elsewhere (e.g. a stopped experiment) --
this mirrors FeatureFlag.key_without_tombstone() in
products/feature_flags/backend/models/feature_flag.py so activity-log and SQL results
outside Django can recover the original key the same deterministic way, without
depending on the activity log's detail fields (detail.changes / detail.name), which
vary by delete path.

Usage:
  python3 scripts/strip_deleted_suffix.py <flag_id> <key>
  python3 scripts/strip_deleted_suffix.py 12345 "foo:deleted:12345"   # -> foo
  python3 scripts/strip_deleted_suffix.py 999 "bar"                   # -> bar (unchanged)

Batch mode: pipe a JSON array of {"id": ..., "key": ...} objects (e.g. the step 2 SQL
results) on stdin; get the same objects back with an added "original_key" field.

  echo '[{"id": 12345, "key": "foo:deleted:12345"}]' | python3 scripts/strip_deleted_suffix.py
"""

import json
import sys


def strip_suffix(flag_id, key):
    suffix = f":deleted:{flag_id}"
    return key[: -len(suffix)] if key.endswith(suffix) else key


def main():
    if len(sys.argv) == 3:
        print(strip_suffix(sys.argv[1], sys.argv[2]))
        return

    candidates = json.loads(sys.stdin.read())
    for candidate in candidates:
        candidate["original_key"] = strip_suffix(candidate["id"], candidate["key"])
    print(json.dumps(candidates, indent=2))


if __name__ == "__main__":
    main()
