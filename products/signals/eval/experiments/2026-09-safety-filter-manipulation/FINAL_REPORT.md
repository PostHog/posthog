# Safety-filter false positives — final report

> Model constant (`claude-sonnet-5` @ medium effort, native `call_llm` shape) · one variable: the classifier prompt.
> Real signals replayed from 30-day `posthog.ai_events` history; invented attack fixtures in `fixtures/attack_fixtures.jsonl`.
> Aggregates in `results/summary.json`. No customer signal text is stored in this repo — the report is written from counts and a property list.
> Run 2026-09-10. Judgments (the labels behind the failure-class counts) are the author's, from original signal content, unreviewed by a second human.

## TL;DR

1. **The over-blocking was the prompt, not the model.** The per-signal safety filter rejects a signal it reads as an attack on the coding agent. Its measured false-positive rate had been high for a long time. The 2026-09-03 Sonnet 4.5 → Sonnet 5 swap already fixed most of it as a side effect; what remained was concentrated in one class and was caused by the prompt's instructions, not the model.
2. **Under a manipulation-only definition, none of the sampled rejections was a real attack.** The author read the original text of ~250 rejected signals (not the classifier's explanations). Every one was an ordinary ticket, the team's own security work, a first-party monitoring report, scanner traffic logged as an error, or a vulnerability report. Zero carried a payload against the agent.
3. **The rewrite eliminates the residual false positives while holding recall.** On the same real signals, the new prompt cuts the hardest slice from **66.7% → 3.0%** rejected and never newly blocks an accepted signal. On the invented attack set it blocks **19/19** and stops wrongly blocking the two near-miss controls the old prompt tripped on.
4. **The eval caught a regression in the fix before it could ship.** A first draft of the new prompt leaked an exfiltration payload framed as "observability mirroring", because a "don't block the team's own risky work" carve-out was too broad. The fix: the exfiltration and remote-execution categories are judged on the action, never on who asked or whether human review is downstream, because those payloads run in the sandbox before any review.

## What the filter is, and the three "safety" things it is not

- **Safety filter** (`backend/temporal/safety_filter.py`): the per-signal classifier under test here. It drops a signal before grouping. This is what dashboard [1999216](https://us.posthog.com/project/2/dashboard/1999216) measures.
- **Report safety judge** (`backend/temporal/report_safety_judge.py`): a per-report check before research. It rejected **0 of ~59k reports** across the two weeks around the swap, but that was measured while the old filter removed the security-topic class before the judge saw it. Replayed on the signals the new filter admits, the old judge prompt rejected 20 of 33 (the aligned one 3 to 5), so its prompt is aligned to the same definition in this change (see Results).
- **Judge scout** (`signals-scout-self-driving-safety-filter-judge`): the scout that re-grades each rejection for the dashboard. It grades from the classifier's _explanation_, not the original content, so a persuasive explanation reads as a true positive. Its post-swap "true positives" are the same security-topic class, which is why the dashboard's ~36% is soft.

## The failure classes (why the old prompt over-blocked)

From reading original content. Each is a shape the old prompt treated as an attack and the new prompt passes.

| Class                        | What it is                                                                                                 | Why the old prompt blocked it                                                 |
| ---------------------------- | ---------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------- |
| Security as a subject        | Tickets about auth, secrets, permissions, gates, rate limits                                               | Taxonomy treated the topic as the act                                         |
| The team's own risky changes | Loosen a permission, add an admin path, delete rows, relax a guard, edit the team's own agent instructions | Read privileged-but-honest work as security weakening                         |
| First-party monitoring       | pganalyze, anomaly investigations, LLM eval reports, health checks                                         | Read "cites internal identifiers, prescribes a fix" as impersonating a system |
| Scanner traffic              | Credential-path 404s and traversal probes against the team's app, logged as errors                         | Read the report of an attack as the attack                                    |
| Vulnerability reports        | Pentest findings with reproduction steps                                                                   | Read describing an exploit as performing one                                  |
| Agent-addressed text         | `AGENT BRIEF`, `OWNER DECISION`, `@bot review`, app error strings written for the app's own agent          | Read imperative writing as instruction injection                              |
| Knowledge cutoff             | 2026 dates, unfamiliar model or product names                                                              | Read future-looking dates and new names as fabrication                        |
| Non-English                  | Any non-English content                                                                                    | Prompt flagged other languages as a yellow flag                               |

## Results

Aggregate counts, `claude-sonnet-5`, medium effort. Full numbers in `results/summary.json`.

### Real signals

`pre` = signals rejected under Sonnet 4.5 before the swap; `post` = signals rejected under Sonnet 5 after; `pass` = accepted signals (should stay accepted). Reject % excludes harness errors.

| Slice                         | n   | Current prompt rejects | New prompt rejects |
| ----------------------------- | --- | ---------------------- | ------------------ |
| post (false-positive hotspot) | 33  | 66.7%                  | **3.0%**           |
| pre                           | 867 | 2.8%                   | **0.2%**           |
| pass (controls)               | 279 | 0.0%                   | **0.0%**           |

The model swap alone already passed 97% of the pre-swap rejections on the old prompt (2.8% re-rejected). The prompt rewrite closes the remaining hotspot without ever newly blocking an accepted signal.

### Attack set

21 invented manipulation cases across the five block categories, two of which try to close the prompt block and forge a trusted source line, plus 22 near-miss safe controls (same topic, urgency, and imperative voice, no payload; one mentions the literal delimiter tags in an ordinary bug). Fixtures: `fixtures/attack_fixtures.jsonl`.

| Prompt  | Attacks blocked                  | Attack leaks | Safe controls wrongly blocked |
| ------- | -------------------------------- | ------------ | ----------------------------- |
| Current | 19/19 (21/21 with forgery cases) | 0            | 2/21                          |
| New     | 19/19                            | 0            | 0/21                          |

The two controls the current prompt wrongly blocks are the exact false-positive classes above (an unmask-secrets self-hosted setting, a staff-2FA-opt-in owner decision). The new prompt passes both and still catches every attack.

### Report judge, before and after alignment

The judge was never covered by the first replay, and its production rejection count was blind to the security-topic class the old filter removed upstream. Replayed on the same fixtures and on the 33 post-swap real signals the new filter admits (all labeled safe):

| Judge prompt                            | Rejects among the 33 admitted signals | Safe controls wrongly blocked | Attacks blocked |
| --------------------------------------- | ------------------------------------- | ----------------------------- | --------------- |
| Old (as on master)                      | 20 of 33                              | 2 of 22                       | 21 of 21        |
| Aligned to the filter's five categories | 3 to 5 of 33 (two runs)               | 0 of 22                       | 21 of 21        |

A judge rejection fails the whole grouped report, so shipping the filter change alone would have moved most of the false positives one stage down and made them worse. The residual rejections are the same instruction-shaped error strings the filter also keeps blocking, so both stages now agree on that edge.

### Delimiter forgery

Two attacks close the prompt block and write a forged first-party source line before their payload. Both were blocked before and after hardening, and the literal-tag safe control passed both times. The model resisting a forgery in two cases is not a control, so the closing tag is now neutralized in code in both stages and each prompt states that only the header lines are metadata.

### The three real signals the new prompt still rejects

All three are error strings that literally embed a step-by-step directive to an agent (an `act_as_tenant`-style account switch, a "read the document then tally" chatter leak). They are the genuinely ambiguous edge between an app's own agent chatter and a planted instruction. The prompt is deliberately **not** tuned to pass them, because forcing instruction-shaped error text through would reopen a real injection path. They are exactly what the judge scout and a human should see.

## The fix

- `SIGNAL_SAFETY_LLM_MODEL` env var, default `claude-sonnet-5` as a literal rather than the matching model, so a matching-model swap can no longer silently retune the gate; both safety stages resolve their model from it.
- One manipulation-only prompt for every source in the filter, replacing the old external-ticket and scout prompts. Five block categories: instruction override, hidden instructions, encoded payload, secret exfiltration, remote code execution. Categories 4 and 5 are judged on the action regardless of source or stated purpose. The full prompt is `SAFETY_FILTER_PROMPT` in `backend/temporal/safety_filter.py`.
- The report judge's prompt aligned to the same five categories and the same do-not-block list, in `backend/temporal/report_safety_judge.py`.
- The signal's source and the current UTC date injected in the filter's user prompt, so the classifier applies the right trust context and reads unfamiliar dates and names as real.
- Delimiter hardening in both stages: the closing tag is neutralized before the content enters the block, and each prompt says only the header lines are metadata.
- Both prompts tell the model never to reproduce a credential, token, or key value in the explanation, because the explanation is stored in an internal analytics event.

## Method

- Original content recovered from `posthog.ai_events` (30-day retention), joined from the safety stage's `$ai_generation` spans (`$ai_product = 'signals_safety'`, `ai_stage = 'safety_filter'`).
- Replay on `claude-sonnet-5`, `output_config.effort = medium`, no assistant prefill, matching the pipeline's `call_llm`. Same request path for the current and new prompt so the prompt is the only variable.
- The `pre` slice used Sonnet 4.5 rejections as its population, so it measures what the Sonnet-5 prompt does with signals a different model once rejected. `post` and `pass` are native Sonnet-5 populations.
- Attack fixtures and the failure-class labels were written from a property list with reserved domains and invented tokens. No customer content is committed; the real replayed signals stay out of the repo by design.

## Limits

- The false-positive labels are one author's judgment from original content, not adjudicated by a second reviewer.
- Recall cannot be measured from production, because the labeled real set contains no real attacks. The 19 attacks are invented, so 19/19 is a floor on obvious cases, not proof against a novel technique.
- `pre` mixes a cross-model population; treat its absolute rate as indicative, not exact.
