"""Build the experiment copies of the API-quality scout body from the canonical body.

Three edits, everything else verbatim: (1) preflight pins the commit and prints the hash,
(2) the file sweep is replaced by the fixed page, (3) memory writes go under the copy's own
prefix and the shared cursor is never touched. Run: python3 make_copies.py > copies.json
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).parent
COMMIT = (HERE / "commit.txt").read_text().strip()
BODY = (HERE / "canonical-skill-body.v2.md").read_text()

MODELS = ["gpt-5.6-luna", "gpt-5.6-terra", "gpt-5.6-sol"]
PAGES = [1, 2]
RUNS = [1, 2]

PREFLIGHT_OLD = BODY[BODY.index("## Preflight") : BODY.index("## Choose the 100 files")]
SWEEP_OLD = BODY[BODY.index("## Choose the 100 files") : BODY.index("## Explore patterns")]
REMEMBER_OLD = BODY[BODY.index("## Decide and remember") : BODY.index("## Pull request labeling")]

PREFLIGHT_NEW = f"""## Preflight

Use the configured posthog/posthog checkout. Pin it to commit `{COMMIT}` before reading anything:

~~~bash
cd "$(git rev-parse --show-toplevel)" &&
git fetch --depth=1 origin {COMMIT} &&
git checkout --detach {COMMIT} &&
git rev-parse HEAD
~~~

The last command must print `{COMMIT}`. If it prints anything else or fails, stop: do not inspect files, and close out with the sentence "Could not pin commit {COMMIT}" and the error.

Run later commands from the checkout. Read local AGENTS.md files before judging a directory.

"""


def sweep_new(page: int) -> str:
    files = (HERE / f"page-{page}.txt").read_text().strip().split("\n")
    listing = "\n".join(f"- {p}" for p in files)
    return f"""## The 100 files for this run

Inspect exactly these tracked backend API files, at the pinned commit, and no others:

{listing}

Do not read or write `cursor:api-quality:file-sweep`. Do not run a changed-files pass. Never store a per-file manifest.

"""


def remember_new(copy_id: str) -> str:
    mine = f"api-quality-{copy_id}"
    body = REMEMBER_OLD.replace(
        "Store one concise finding record per route or path. Also store pattern:api-quality:<kind>",
        f"Store one concise finding record per route or path under finding:{mine}:<route-or-path>. Also store pattern:{mine}:<kind>",
    )
    rule = f"""## Memory keys you own

Read any memory you like, including finding:api-quality:, pattern:api-quality: and claim:api-quality: entries, but write only keys that start with `finding:{mine}:`, `pattern:{mine}:`, `followup:signals-scout-{mine}:` or `improve:signals-scout-{mine}:`. Never create, rewrite or condense a key that starts with `finding:api-quality:`, `pattern:api-quality:`, `claim:api-quality:` or `cursor:api-quality:`; those belong to another scout, and rewriting them corrupts its records. If a recurring pattern you see is already recorded under `pattern:api-quality:`, record your own copy under `pattern:{mine}:` instead of editing theirs.

"""
    emit_rule = """## Filing the report

Always file every report you decide on with `scout-emit-report`, with the complete title, summary, evidence, priority and reviewers, even when the project profile or a tool says this scout is in dry-run and the report will not reach the inbox. The call is recorded either way, and a report that exists only in your close-out summary counts as not filed.

"""
    return rule + body + emit_rule


def build() -> list[dict[str, str | int]]:
    copies: list[dict[str, str | int]] = []
    n = 0
    for model in MODELS:
        for page in PAGES:
            for run in RUNS:
                n += 1
                copy_id = f"b{n}"
                body = BODY.replace(PREFLIGHT_OLD, PREFLIGHT_NEW).replace(SWEEP_OLD, sweep_new(page))
                body = body.replace(REMEMBER_OLD, remember_new(copy_id))
                assert body.count(COMMIT) == 5, copy_id
                assert "cursor:api-quality:file-sweep" in body and "Take the first 100 rows" not in body
                assert (
                    f"finding:api-quality-{copy_id}:" in body
                    and "## Memory keys you own" in body
                    and "## Filing the report" in body
                )
                copies.append(
                    {
                        "copy": copy_id,
                        "name": f"signals-scout-api-quality-{copy_id}",
                        "display_name": f"API quality (experiment: {model.split('-')[-1]}, set {page}, run {run})",
                        "model": model,
                        "page": page,
                        "run": run,
                        "body": body,
                    }
                )
    return copies


if __name__ == "__main__":
    print(json.dumps(build(), indent=1))  # noqa: T201 — eval script, stdout is the intended output channel
