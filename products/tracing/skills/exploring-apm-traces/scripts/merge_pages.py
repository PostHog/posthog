"""Merge apm-trace-get pages (`summary: false`) into one trace file the other scripts read.

Usage:
  python3 scripts/merge_pages.py PAGE_FILE [PAGE_FILE ...] > trace.json

Pass every page, from `offset: 0` until the page with `hasMore: false`. Spans that
appear on two pages are kept once (matched by `span_id`).
"""

import sys
import json

from _common import load_trace_file, unwrap_text_envelope

paths = sys.argv[1:]
if not paths:
    print(__doc__, file=sys.stderr)
    sys.exit(1)

spans = []
seen = set()
last_page_seen = False
next_offsets = []
for path in paths:
    with open(path) as f:
        page = unwrap_text_envelope(json.load(f))
    if isinstance(page, dict) and "hasMore" in page:
        if not page["hasMore"]:
            last_page_seen = True
        elif page.get("nextOffset") is not None:
            next_offsets.append(page["nextOffset"])
    for span in load_trace_file(path):
        key = span.get("span_id") or span.get("uuid")
        if key in seen:
            continue
        if key:
            seen.add(key)
        spans.append(span)

json.dump({"results": spans}, sys.stdout)
print(f"Merged {len(spans)} spans from {len(paths)} page(s).", file=sys.stderr)
if next_offsets and not last_page_seen:
    print(
        f"Incomplete: every page has hasMore: true. Fetch the next page with offset: {max(next_offsets)} and merge again.",
        file=sys.stderr,
    )
