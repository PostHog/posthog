"""Stage 2: collapse freely-worded intentions onto a shared vocabulary.

`extract_facets.py` runs one API call per session, and no call can see what the
others wrote. However firmly the prompt demands a shared vocabulary, 500 sessions
came back with 487 distinct labels — `create an email workflow`, `build a welcome
email workflow` and `set up onboarding workflow` all describing one job. That is
not a prompt-tuning failure, it is structural: independent calls cannot converge.

This is the pass that fixes it, in two steps:

1. One call that sees every distinct label at once and proposes a canonical
   vocabulary. Seeing them together is the whole point — it is the thing the
   per-session calls could not do.
2. Assignment by embedding similarity rather than a second LLM pass, which is
   cheaper, deterministic, and re-runnable without spending tokens.

A label whose nearest canonical sits below --floor keeps its original wording, so
genuinely unusual sessions are not forced into a bucket they do not belong in.

    export OPENAI_API_KEY=$(op read "$(grep -E '^OPENAI_API_KEY=' .env.local | cut -d= -f2- | tr -d '\"')")
    python canonicalize_intentions.py facets.jsonl facets_canonical.jsonl --target 90
"""

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

import numpy as np
from openai import OpenAI
from pydantic import BaseModel, Field

MODEL = "gpt-4.1-mini"
EMBEDDING_MODEL = "text-embedding-3-small"
BATCH = 256

SYSTEM = """You are given every distinct starting-intention label produced by an extraction pass over MCP sessions, with how many sessions produced each.

Propose a canonical vocabulary of about {target} labels that covers them.

Rules:
- Each canonical label is a short imperative phrase, 3-8 words, in the same style as the input.
- Merge labels that describe the same job in different words. "create an email workflow", "build a welcome email workflow" and "set up onboarding workflow" are one job.
- Keep labels distinct when the job genuinely differs. Checking a configuration is not the same as changing it; sending to email is not the same as sending to a chat channel.
- Cover the common labels first. A label used by many sessions must have a good canonical home; a one-off can fall back to its own wording.
- NEVER include a customer, company, project, product, person, or app name.

Two failure modes to avoid, both seen in real runs:

- **Do not emit near-duplicates of your own labels.** "create automation workflows", "build automated workflows" and "create email automation workflow" are one label, not three. If you cannot articulate how two of your labels differ, emit one.
- **Name the starting point, not the action.** The input labels drift toward describing what the agent did, because that is what the telemetry recorded. "create email automation workflow" is an action. "build an onboarding email sequence" is a starting point: it says what the person wanted before any tool was chosen. A label that could be a button in the product is the wrong altitude.

Return only the vocabulary."""


class Vocabulary(BaseModel):
    labels: list[str] = Field(description="Canonical starting-intention labels, 3-8 words each")


def embed(client: OpenAI, texts: list[str]) -> np.ndarray:
    vectors: list[list[float]] = []
    for start in range(0, len(texts), BATCH):
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts[start : start + BATCH])
        vectors.extend(item.embedding for item in response.data)
    matrix = np.array(vectors, dtype=np.float64)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("facets", type=Path, help="JSONL from extract_facets.py")
    parser.add_argument("out", type=Path, help="JSONL destination with canonical goals")
    parser.add_argument("--field", default="goal", help="field holding the intention")
    parser.add_argument("--target", type=int, default=90, help="roughly how many canonical labels to ask for")
    parser.add_argument("--floor", type=float, default=0.55, help="keep the original below this similarity")
    parser.add_argument("--dedupe", type=float, default=0.82, help="collapse proposed labels above this similarity")
    args = parser.parse_args()

    if not os.environ.get("OPENAI_API_KEY"):
        sys.exit("OPENAI_API_KEY is unset. Resolve it from .env.local with `op read` first — see the module docstring.")

    records = [json.loads(line) for line in args.facets.read_text().splitlines() if line.strip()]
    counts = Counter(r[args.field] for r in records)
    originals = [g for g, _ in counts.most_common()]
    print(f"{len(records)} sessions, {len(originals)} distinct labels going in")

    client = OpenAI()
    listing = "\n".join(f"{counts[g]:>4}  {g}" for g in originals)
    response = client.beta.chat.completions.parse(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM.format(target=args.target)},
            {"role": "user", "content": listing},
        ],
        response_format=Vocabulary,
    )
    parsed = response.choices[0].message.parsed
    if parsed is None or not parsed.labels:
        sys.exit("model returned no vocabulary")
    proposed = sorted({label.strip().lower() for label in parsed.labels if label.strip()})
    print(f"proposed vocabulary: {len(proposed)} labels")

    # The model emits near-duplicates of its own labels even when told not to,
    # so collapse the vocabulary against itself before anything is assigned to
    # it. Without this the redundancy is inherited by every downstream count.
    proposed_vectors = embed(client, proposed)
    with np.errstate(all="ignore"):
        self_similarity = proposed_vectors @ proposed_vectors.T
    vocabulary: list[str] = []
    for i, label in enumerate(proposed):
        if not any(self_similarity[i, proposed.index(kept)] >= args.dedupe for kept in vocabulary):
            vocabulary.append(label)
    if len(vocabulary) < len(proposed):
        print(f"collapsed to {len(vocabulary)} after removing near-duplicates at {args.dedupe}")

    original_vectors = embed(client, originals)
    canonical_vectors = embed(client, vocabulary)
    with np.errstate(all="ignore"):  # spurious Accelerate BLAS warnings, see audit_intentions.py
        similarity = original_vectors @ canonical_vectors.T

    best = similarity.argmax(axis=1)
    scores = similarity.max(axis=1)
    mapping = {
        original: (vocabulary[b] if s >= args.floor else original)
        for original, b, s in zip(originals, best, scores)
    }

    kept = sorted({g for g in originals if mapping[g] == g}, key=lambda g: -counts[g])
    kept_sessions = sum(counts[g] for g in kept)
    for record in records:
        record[args.field] = mapping[record[args.field]]
    with args.out.open("w") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")

    final = Counter(r[args.field] for r in records)
    print(f"\n{len(originals)} labels -> {len(final)} after mapping ({len(records) / len(final):.1f} sessions each)")
    print(f"{len(kept)} labels stayed unmapped below the {args.floor} floor, covering {kept_sessions} sessions")
    print(f"\nwrote {args.out}\n")
    print("Top canonical labels:")
    for label, n in final.most_common(15):
        print(f"  {n:>4}  {100 * n / len(records):>5.1f}%  {label}")


if __name__ == "__main__":
    main()
