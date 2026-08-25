"""Stage 1 of the taxonomy: turn each session's opening tool calls into a facet.

Reads the pipe-delimited corpus dumped from HogQL, asks gpt-4.1-mini to recover
the user's starting intention, and writes JSONL. Clustering happens downstream.

Model choice matches `products/mcp_analytics/backend/intent_generation.py`,
which already uses gpt-4.1-mini for the closest existing job (summarizing a
session's intents), so the two stay comparable.

PostHog employees only: the key comes from the repo's .env.local, which holds
1Password references rather than literal secrets.

CONSENT: the `opening` column is customer-authored intent text, and this script
sends it to a third-party model. PostHog's backend gates the same class of text
on `organization.is_ai_data_processing_approved` (see intent_generation.py and
failure_classification.py); restrict the corpus to consenting organizations
before running this. The sibling scripts only ever see generated goal labels.

    export OPENAI_API_KEY=$(op read "$(grep -E '^OPENAI_API_KEY=' .env.local | cut -d= -f2- | tr -d '\"')")
    python extract_facets.py corpus.txt facets.jsonl --facet destination \\
        --values email,slack,webhook,person_property,unclear

The third facet is per-tool. See references/facet-schemas.md for how to pick it.
"""

import argparse
import json
import os
import sys
from dataclasses import dataclass
from enum import Enum
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from openai import OpenAI
from pydantic import BaseModel, Field, create_model

MODEL = "gpt-4.1-mini"
WORKERS = 8

SYSTEM = """You are analyzing telemetry from PostHog's MCP server: sequences of tool calls an AI agent made on a user's behalf. Each session ended with the agent calling {tool}.

Recover the USER'S STARTING POINT — what the person set out to accomplish when the session began. This is upstream of the tool call: reaching {tool} is usually where the work landed, not the goal itself.

Rules:
- `goal` is a short imperative phrase, 3-8 words, describing the starting task in general terms. Examples of the right altitude: "investigate an error spike", "build a weekly metrics report", "analyze a conversion funnel drop", "audit feature flag usage".
- Generalize hard. Two sessions doing the same kind of work must produce the SAME goal string, character for character. Strip anything specific to one user.
- NEVER include a customer, company, project, product, person, or app name in any field. These appear constantly in the input; drop them. Write "a mobile app", not the app's name.
- `data_touched` is true if the session queried analytics data (SQL, insights, events, warehouse) before reaching the tool, false if it only read or wrote configuration.
- `{facet}` is one of: {values}. Pick the closest; use the last value when the opening calls do not say."""


def build_model(facet: str, values: list[str]) -> type[BaseModel]:
    """The third facet is per-tool, so the response schema is built at runtime.

    The facet is an Enum rather than a str: structured output enforces types,
    not descriptions, so a `str` field with "one of: ..." in its description
    still lets the model invent values. A 500-session run produced `unclarified`,
    `unclar` and `unclassified` alongside the `unclear` it was given.
    """
    facet_enum = Enum(f"{facet.title()}Value", {v: v for v in values}, type=str)
    return create_model(
        "Facet",
        goal=(str, Field(description="Generalized starting intention, 3-8 words, imperative, no proper nouns")),
        data_touched=(bool, Field(description="Did the session query analytics data before reaching the tool?")),
        **{facet: (facet_enum, Field(description=f"One of: {', '.join(values)}"))},
    )


@dataclass(frozen=True, kw_only=True, slots=True)
class CorpusRow:
    """One session. `meta` holds the pass-through columns between `sid` and `opening`."""

    sid: str
    meta: dict[str, str]
    opening: str


def load_corpus(path: Path) -> list[CorpusRow]:
    """Reads a pipe-delimited dump whose header row names the columns.

    The header must start with `sid` and end with `opening`. Every column
    between them (caller, org) rides through to the output untouched, which
    saves joining them back on by hand later — that join is otherwise a few
    hundred lines of transcription with nothing checking it.

    `opening` stays last so the split can cap its field count and leave any
    pipe inside the intent text alone.
    """
    lines = path.read_text().splitlines()
    if not lines:
        return []
    header = [h.strip() for h in lines[0].split("|")]
    if header[0] != "sid" or header[-1] != "opening":
        raise SystemExit(f"corpus header must be sid|…|opening, got: {'|'.join(header)}")

    rows: list[CorpusRow] = []
    for line in lines[1:]:
        parts = line.split("|", len(header) - 1)
        if len(parts) != len(header):
            continue
        sid, *meta, opening = parts
        if opening.strip():
            named = {k: v.strip() for k, v in zip(header[1:-1], meta) if v.strip()}
            rows.append(CorpusRow(sid=sid.strip(), meta=named, opening=opening))
    return rows


def extract(client: OpenAI, schema: type[BaseModel], system: str, row: CorpusRow) -> dict[str, Any] | None:
    try:
        response = client.beta.chat.completions.parse(
            model=MODEL,
            max_tokens=256,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": f"Session tool-call sequence:\n\n{row.opening}"},
            ],
            response_format=schema,
        )
    except Exception as exc:  # one bad session must not kill a 700-session run
        print(f"  ! {row.sid}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    parsed = response.choices[0].message.parsed
    if parsed is None:
        print(f"  ! {row.sid}: model returned no parsed output", file=sys.stderr)
        return None
    facets = {k: (v.value if isinstance(v, Enum) else v) for k, v in parsed.model_dump().items()}
    return {"sid": row.sid, **row.meta, **facets}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpus", type=Path, help="pipe-delimited dump, header sid|…|opening")
    parser.add_argument("out", type=Path, help="JSONL destination")
    parser.add_argument("--tool", default="the tool", help="MCP tool name the corpus is about")
    parser.add_argument("--facet", required=True, help="name of the third, tool-specific facet")
    parser.add_argument("--values", required=True, help="comma-separated allowed values, catch-all last")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is unset. Resolve it from .env.local with `op read` first — see the module docstring.")

    values = [v.strip() for v in args.values.split(",") if v.strip()]
    schema = build_model(args.facet, values)
    system = SYSTEM.format(tool=args.tool, facet=args.facet, values=", ".join(values))

    rows = load_corpus(args.corpus)
    if not rows:
        raise SystemExit(f"no usable rows in {args.corpus}; the header must be sid|…|opening")
    print(f"extracting facets for {len(rows)} sessions on {MODEL}")

    client = OpenAI()
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        results = list(pool.map(lambda r: extract(client, schema, system, r), rows))

    ok = [r for r in results if r is not None]
    if not ok:
        # Bail before writing. An empty JSONL looks like a finished run to every
        # downstream step, and the real cause is in the per-session errors above.
        raise SystemExit(f"extracted 0 of {len(rows)} sessions; nothing written to {args.out}")

    with args.out.open("w") as fh:
        for record in ok:
            fh.write(json.dumps(record) + "\n")

    distinct = len({r["goal"] for r in ok})
    print(f"wrote {len(ok)}/{len(rows)} facets to {args.out}")
    print(f"{distinct} distinct starting intentions ({len(ok) / distinct:.1f} sessions each)")
    if distinct > len(ok) / 3:
        print(
            f"\n!! {distinct} labels for {len(ok)} sessions is not a taxonomy.\n"
            "   Each session is extracted by its own API call, and no call can see what\n"
            "   the others wrote, so they cannot converge on shared wording however the\n"
            "   prompt is worded. Run canonicalize_intentions.py to collapse them."
        )
    else:
        print("\nRun audit_intentions.py next to catch any remaining near-duplicates.")


if __name__ == "__main__":
    main()
