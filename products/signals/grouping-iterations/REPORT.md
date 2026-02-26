# Signals Grouping Strategy Comparison

Test dataset: 42 curated signals. Ranges from 2-4 full runs per strategy. LLM-judged evaluation.

| Strategy                         | Overall | Coherence | Groups              | Weak-chains | Misplaced | Under-grouped |
| -------------------------------- | ------- | --------- | ------------------- | ----------- | --------- | ------------- |
| `current` (production)           | 2/5     | 1.97–2.65 | 15–18 (5–6 multi)   | 2–3         | 13–18     | 1–4           |
| `group_aware`                    | 3/5     | 2.86–3.71 | 31–33 (4–6 multi)   | 1–2         | 4–6       | 1–12          |
| `verification_gate`              | 2/5     | 2.87–3.36 | 29–30 (10–11 multi) | 3–5         | 6–10      | 1–2           |
| `multilink`                      | 2/5     | 2.53–2.87 | 16–18 (6–7 multi)   | 3           | 13–18     | 0–1           |
| `pr_specificity` v1              | 2/5     | 2.64–2.92 | 27–29 (9–11 multi)  | 5–6         | 8–11      | 1             |
| `pr_specificity` v2              | 3/5     | 3.23–4.21 | 33–34 (5–6 multi)   | 1–2         | 2–5       | 1–4           |
| `pr_specificity_and_group_aware` | 3/5     | 3.78–4.50 | 35–37 (4–6 multi)   | 0–1         | 1–2       | 1–3           |

## Pros/cons per strategy

**`current`** — Production baseline. Signal-to-signal matching.

- **Pros:** Good at discovering related signals, groups them aggressively
- **Cons:** Weak-chaining: unrelated signals chain through shared keywords (13–18 misplaced)

**`group_aware`** — Shows LLM full report context (all signals in group) before matching.

- **Pros:** Dramatically fewer misplaced signals (4–6 vs 13–18)
- **Cons:** Too conservative — over-splits into singletons, under-grouping can spike to 12

**`verification_gate`** — Current discovery + LLM "does this fit?" verification step.

- **Pros:** Catches some weak chains with detailed explanations
- **Cons:** Subjective and inconsistent — actually increases weak-chain groups (3–5), still 6–10 misplaced

**`multilink`** — Current discovery + embedding-based transitive verification (new signal must be close to multiple existing group members).

- **Pros:** Near-zero under-grouping
- **Cons:** Doesn't work — embeddings can't distinguish "same domain" from "same work item". Nearly identical to baseline (13–18 misplaced)

**`pr_specificity` v1** — Current discovery + "can you write a specific PR title for all signals?" gate. Cold-start skip (only checks groups 2+).

- **Pros:** Novel approach: forces synthesis over subjective judgment
- **Cons:** Cold-start skip leaves initial weak pairings unchecked (5–6 weak-chain groups, 8–11 misplaced)

**`pr_specificity` v2** — Same gate, no cold-start skip, tighter prompt.

- **Pros:** 70–85% reduction in misplaced signals vs baseline (2–5), high coherence (3.23–4.21)
- **Cons:** More singletons (27–29), occasional under-grouping (1–4)

**`pr_specificity_and_group_aware`** — Best of both: PR-specificity gate + group context in matching + title feedback loop.

- **Pros:** Highest coherence (3.78–4.50), lowest misplaced (1–2), near-zero weak-chains (0–1)
- **Cons:** Most singletons (29–33), under-grouping (1–3). Tradeoff: groups that DO form are high quality, but some related signals stay isolated

---

- I expclicitly didn't test many-to-many connections and focused on DAG for simplicity and to support graph UI

## TL;DR

The core problem is weak-chaining. PR-specificity ("write a PR title for this group") is the most effective filter — it forces the LLM to synthesize rather than judge. Adding group context on top gives the best precision. The tradeoff across all improvements: fewer bad groups, more singletons. The question is whether high-quality multi-signal groups + some singletons > messy large groups.
