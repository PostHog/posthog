"""Stage 1.5: embed the extracted intentions and flag near-duplicate phrasings.

Extraction is asked to produce the same string for the same kind of work, and it
does not quite manage it — across a long run the wording drifts, so one job ends
up split across two or three labels. Every split inflates the intention count and
deflates each share, and neither shows up as an error.

This embeds each distinct intention with text-embedding-3-small and prints the
pairs above a cosine threshold, highest first, so they can be merged by hand.

The 0.80 default is calibrated, not guessed. On a 105-intention corpus the
highest pair scored 0.819 and only three cleared 0.80, so a threshold much above
that flags nothing at all — which is easy to mistake for a clean result.

It deliberately does not merge anything. Two intentions can be semantically close
and still worth separating — "verify a feature flag configuration" and "manage
feature flag rollout" sit near each other and belong in different themes, because
one is checking state and the other is changing it. That call is yours.

    export OPENAI_API_KEY=$(op read "$(grep -E '^OPENAI_API_KEY=' .env.local | cut -d= -f2- | tr -d '\"')")
    python audit_intentions.py facets.jsonl --threshold 0.80

Note the model name differs from the backend's `text-embedding-3-small-1536`.
That is a PostHog gateway alias carrying a dimension count; calling OpenAI
directly needs the plain model id.
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from openai import OpenAI

EMBEDDING_MODEL = "text-embedding-3-small"
BATCH = 256


def embed(client: OpenAI, texts: list[str]) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        chunk = texts[start : start + BATCH]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=chunk)
        vectors.extend(item.embedding for item in response.data)
    matrix = np.array(vectors, dtype=np.float64)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facets", type=Path, help="JSONL from extract_facets.py")
    parser.add_argument("--threshold", type=float, default=0.80, help="cosine similarity to flag at")
    parser.add_argument("--field", default="goal", help="field holding the intention")
    parser.add_argument("--top", type=int, default=15, help="pairs to show when nothing crosses the threshold")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is unset. Resolve it from .env.local with `op read` first — see the module docstring.")

    records = [json.loads(line) for line in args.facets.read_text().splitlines() if line.strip()]
    counts = Counter(r[args.field] for r in records)
    intentions = sorted(counts)
    print(f"{len(records)} sessions, {len(intentions)} distinct intentions")
    if len(intentions) < 2:
        # No pairs exist, so there is nothing to audit. Say that rather than
        # reporting a clean result, which would read as "checked, found nothing".
        print("Fewer than two distinct intentions; no pairs to compare.")
        return

    client = OpenAI()
    vectors = embed(client, intentions)
    # Apple's Accelerate BLAS raises divide-by-zero and overflow on this matmul
    # whatever the dtype, and the result is correct regardless — norms are 1.0
    # and the diagonal comes back 1.0. Left unsuppressed the warnings sit right
    # above a "nothing flagged" line and read like corrupt data.
    with np.errstate(all="ignore"):
        similarity = vectors @ vectors.T

    ranked = sorted(
        (
            (float(similarity[i, j]), intentions[i], intentions[j])
            for i in range(len(intentions))
            for j in range(i + 1, len(intentions))
        ),
        reverse=True,
    )
    flagged = [p for p in ranked if p[0] >= args.threshold]

    # Always show the closest pairs, threshold or not. An empty flag list means
    # "nothing crossed the line you chose", which is not the same as "verified
    # clean" — print the ceiling so the operator can judge the threshold itself.
    shown = flagged or ranked[: args.top]
    header = (
        f"{len(flagged)} pairs at or above {args.threshold}, "
        f"touching {sum(counts[a] + counts[b] for _, a, b in flagged)} sessions"
        if flagged
        else f"Nothing reached {args.threshold}. Closest {len(shown)} pairs, highest similarity {ranked[0][0]:.3f}"
    )
    print(f"\n{header}")
    print("Merging a pair moves both counts onto one label. Semantic closeness is")
    print("not a merge instruction — check that the two describe the same job.\n")
    for score, a, b in shown:
        print(f"  {score:.3f}  {a} ({counts[a]})")
        print(f"         {b} ({counts[b]})")


if __name__ == "__main__":
    main()
