# Signals Grouping Strategy Comparison

Test dataset: 42 curated signals. Ranges from 4-5 full runs per strategy. LLM-judged evaluation.

| Strategy                         | Overall | Coherence | Groups              | Weak-chains | Misplaced | Under-grouped |
| -------------------------------- | ------- | --------- | ------------------- | ----------- | --------- | ------------- |
| `current` (production)           | 2/5     | 1.97–2.65 | 15–18 (5–6 multi)   | 2–3         | 13–18     | 1–4           |
| `group_aware`                    | 3/5     | 2.86–3.71 | 31–33 (4–6 multi)   | 1–2         | 4–6       | 1–12          |
| `verification_gate`              | 2/5     | 2.87–3.36 | 29–30 (10–11 multi) | 3–5         | 6–10      | 1–2           |
| `multilink`                      | 2/5     | 2.53–2.87 | 16–18 (6–7 multi)   | 3           | 13–18     | 0–1           |
| `pr_specificity`                 | 3/5     | 3.23–4.21 | 33–34 (5–6 multi)   | 1–2         | 2–5       | 1–4           |
| `pr_specificity_and_group_aware` | 3/5     | 3.78–4.50 | 35–37 (4–6 multi)   | 0–1         | 1–2       | 1–3           |

---

Hey. I spent a bit of time iterating with grouping approaches, as it seems like a pressure point after Team 2 research we did this week. My findings and context on different stratagies are in the thread.

The main problem was time, as working with production data is incredibly slow (we inject signals one by one for proper grouping, with multiple LLM calls in-between). So, I created a test harness (README, PR) with in-memory processing, so we can use it for ranking grouping approaches and evals.

I then handpicked 42 signals, removed PII, and tested 9 different strategies (~40 15-min runs in total).

**TLDR:** The core problem is weak-chaining. Adding group context when matching gives the best precision. PR-specificity ("write a PR title for this group") is the most effective filter — it forces the LLM to synthesize rather than judge.

## Pros/cons per strategy

**`current`** — Baseline, in production . Signal-to-signal matching.

- **Pros:** Good at discovering related signals, groups them aggressively
- **Cons:** Weak-chaining: unrelated signals chain through shared keywords (13–18 misplaced)

**`group_aware`** — Shows LLM full report context (N signals in group) when matching.

- **Pros:** Dramatically fewer misplaced signals (4–6 vs 13–18)
- **Cons:** Too conservative — over-splits into singletons, under-grouping can spike to 12

**`verification_gate`** — Two steps: current discovery + LLM "does this fit?" verification.

- **Pros:** Catches some weak chains with detailed explanations
- **Cons:** Subjective and inconsistent — actually increases weak-chain groups (3–5), still 6–10 misplaced

**`multilink`** — Current discovery + new signal must be close to multiple existing group members.

- **Pros:** Near-zero under-grouping
- **Cons:** Doesn't work — embeddings can't distinguish "same domain" from "same work item". Nearly identical to baseline (13–18 misplaced)

**`pr_specificity`** — Two steps: current discovery + "can you write a specific PR title for all these signals?" verification.

- **Pros:** 70–85% reduction in misplaced signals vs baseline (2–5), high coherence (3.23–4.21)
- **Cons:** More singletons (27–29), occasional under-grouping (1–4)

**`pr_specificity_and_group_aware`** — PR-specificity gate + group context in matching + title feedback loop.

- **Pros:** Highest coherence (3.78–4.50), lowest misplaced (1–2), near-zero weak-chains (0–1)
- **Cons:** Most singletons (29–33), under-grouping (1–3). Tradeoff: groups that DO form are high quality

---

---

## Failed (for now) approaches:

- Generate additional links between 1-1 matched signals (ask additional questions after matching). The goal was to have "weighted" connections to make it easier to split weaker groups. Works, but there are limitless "links" LLM can find between two large GitHub issues, so the approach is completely undeterministic.

- Generate links from one signal to multiple other matching candidates. The goal was later to calculate internal connectivity of the group and, again, make it easier to split weaker groups. When generating as-is it breaks the "one signal matches one report" contract. When limiting to a single report (`multilink`) - works, but shows mixed results. Plus, it significantly complicates the math, UI, and follow-up verification.

- `pr_specificity` buth with a cold start skip (if selected report has only one signal - just attach new one to it without validation). It causes bad initial groups, and can't fix itself afterward.

## Cheating

- The potentially best working approach was just to give agent the evaluation prompt and tools to remove/add signals to specific reports. However, it required either enforcing summaries for all signals (to minimize size/meaning spread), or provide full signal context. Not a problem per-se, but it get seriously expensive pretty fast.

@Andy uses a similar approach (kudos to @Josh for sharing the knowledge), so we can probably make it work, but I have noticeable concerns on how scalable it is on thousands of signals (time/money).
