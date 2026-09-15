---
name: designing-replay-vision-scanners
description: "Designs a Replay Vision scanner that produces trustworthy observations: one visible question per scanner, a type chosen from the answer shape, a query that selects only sessions able to answer it, a prompt that demands on-screen proof and allows no or inconclusive, a model picked by the cost of a wrong answer, and a first-batch calibration pass. Sizing and the create call stay in creating-replay-vision-scanners.\nTRIGGER when: user wants to design, draft, or improve a Replay Vision scanner or its prompt, asks what to scan for, asks why a scanner returns vague observations, or asks an agent to propose scanners for a product.\nDO NOT TRIGGER when: the question and prompt are settled and the job is to size and create (use creating-replay-vision-scanners), the scanner targets one experiment (use scanning-experiments-with-replay-vision), or the job is to read existing observations (use exploring-replay-vision-observations)."
---

# Designing Replay Vision scanners

A scanner is one prompt applied to one recording at a time. It watches the recording and writes an observation. Replay Vision fixes the watching part. It does not fix the thinking part. The thinking is the design work this skill covers.

Every scanner that produces useful observations shares three properties:

1. One focused question that only the recording can answer.
2. A recording query that selects only sessions able to answer it.
3. Permission to answer no or inconclusive.

Design in this order: question, type, query, prompt, model, first-batch test. Then hand off to [[creating-replay-vision-scanners]] for sizing and the create call.

## Step 1: Test the question

Write the question in one sentence before you touch the API. Then run three checks.

**Only the recording can answer it.** If an event already answers the question, build an insight instead. A rage click event already proves the rage click. The scanner question must add something the event cannot: "did the clicked control actually fail?"

**One recording answers it.** A scanner sees one recording and cannot compare it with recordings it has never seen. Push every cross-session question to a scout, a digest, or product analytics. Comparisons between experiment variants, trends over time, and "how common is this" all live outside the scanner prompt.

**The answer has a fixed shape.** A yes or no with proof. One tag from a short list. A score on a stated scale. A summary with fixed labeled lines. If you cannot name the answer shape, you do not have a question yet.

Reject these questions and rewrite them:

- "Flag anything interesting." The model then decides what matters. That is the user's job.
- "Summarize what happened." Nobody reads a pile of plausible session summaries.
- "Compare the variants." One recording holds one variant.
- "Explain why they gave a low score." The recording shows behavior, not motive.

If the user has specific sessions in front of them and a one-off question, they do not need a scanner. Use `vision-scanners-inline-scan-create` instead.

## Step 2: Pick the type from the answer shape

| Answer shape                                     | Type         | Design rule                                                                                                             |
| ------------------------------------------------ | ------------ | ----------------------------------------------------------------------------------------------------------------------- |
| Yes or no, with proof                            | `monitor`    | Set `allow_inconclusive: true`. Yes only when the proof is on screen.                                                   |
| One label from a short list                      | `classifier` | Keep 5 to 9 tags. Always include an escape tag. Set `multi_label: false` unless one session truly carries several jobs. |
| A number on a rubric                             | `scorer`     | Use when the distribution matters more than any single observation. Define both ends of the scale in the prompt.        |
| A fixed set of labeled lines about one recording | `summarizer` | Name the lines in the prompt (for example Journey, Friction, Outcome, Evidence). Never ask for free prose.              |

`scanner_type` is locked after creation. Get this right before the create call.

Escape tags for classifiers are not optional. A classifier must pick a tag. Without `nothing-broken`, `never-reached`, `cant-tell`, or `inconclusive` in the list, the model invents friction on sessions that contain none. Make the escape tag exclusive: the prompt must say it never combines with a defect tag.

Use `allow_freeform_tags: true` only when the goal is taxonomy discovery, and say so in the prompt: "invent a short snake_case tag only when the recording clearly shows a job outside this list". Freeform tags also hide drift between the prompt and the tag list, so re-read both together after every edit.

## Step 3: Aim the query

The query decides which recordings deserve a judgment. The prompt decides what judgment to make. A better query improves quality more than another paragraph of prompt.

Build the query from the project's real data. Call `event-definitions-list` or inspect existing scanners. Never invent an event name.

A query that works has three parts:

1. One high-intent event or URL that proves the person used the surface in question. Examples: a filter change, a saved object, an export, a survey submission, a wizard step.
2. A minimum active duration. Use a `having_predicates` entry on `active_seconds`. Brief visits waste credits and add clutter.
3. An exclusion for employees and test accounts. Use `filter_test_accounts: true` and, where the project supports it, a person-property filter on the email domain.

When the query is a conjunction of two events, the recording may contain both without them being related. Make the prompt verify the premise first (see Step 4). A session that viewed an issue and also opened an AI chat may have asked the AI about something else entirely.

Set `date_from` and `date_to` to nothing. The scanner's schedule controls time.

Sizing the query against the credit budget is the job of [[creating-replay-vision-scanners]]. Do that before you create.

## Step 4: Write the prompt

Write the prompt in seven parts, in this order:

1. **Context.** Name the product surface and the real screens, controls, and workflows the model may see. Use the product's own names. A coding agent can pull these from the codebase. PostHog AI can pull them from the project.
2. **The question.** One sentence. The same sentence you wrote in Step 1.
3. **The proof rule.** State what must be visible on screen for a yes, a defect tag, or a high score. Require citations to the decisive moments.
4. **The no list.** Name the ordinary things that are not findings: validation errors the user fixes, slowness, styling, browsing, missing features.
5. **The inconclusive rule.** State when to answer inconclusive: a hidden half, masked UI, a session that cuts off, a goal that never becomes visible.
6. **The output shape.** Labeled parts, in a fixed order.
7. **Privacy.** No names, emails, IDs, or verbatim sensitive content. Paraphrase.

Patterns that hold up in production:

- **Verify the premise first.** "This session was selected because X and Y both happened. FIRST verify they are related. If not, output UNRELATED and one sentence on what actually happened, then stop."
- **Both halves on screen.** "Only report a finding if you can see BOTH the claim the product made AND the behavior that contradicted it."
- **Evidence, unmet job, smallest test, alternative explanation.** For opportunity findings, require all four parts. The fourth part forces the model to argue against itself.
- **Boring is expected.** "Most sessions contain no such defect. That is the expected outcome. Return inconclusive rather than stretching an ordinary error to fit the pattern." Write this sentence into every monitor.
- **Behavior before words.** When a survey response or chat message is in the session, tell the model to judge the on-screen actions first and the text second. People write feature requests when they made an operational mistake.

Anti-patterns to strip out of any draft:

- Asking the model to infer intent from navigation alone.
- Asking for a comparison, a trend, or a frequency.
- Asking for a cause ("why did they churn").
- Instructions that seem obvious until the model reads them literally. Test for these in Step 6.

## Step 5: Pick the model by the cost of a wrong answer

Each model has a fixed price per observation. Pick by asking what one wrong observation costs the reader.

- **Cheapest tier.** High-volume jobs where the distribution matters and no single observation triggers action. A broken-render classifier on a marketing site. One wrong label nudges a trend.
- **Default tier.** A fixed rubric with some judgment. An experiment outcome classifier. A scout compares the pattern across variants afterwards.
- **Priciest tier.** Someone may act on a single observation. A contradiction monitor, an opportunity miner, a survey-triage classifier. A plausible wrong answer costs a person an hour.

If observations are close but not right, tighten the prompt before moving up a tier. A sharper instruction is usually cheaper than a bigger model.

## Step 6: Test on the first batch

Do not polish the prompt before it runs. The first batch shows how the prompt actually performs.

1. Create the scanner. Create it disabled when the estimate from [[creating-replay-vision-scanners]] is material.
2. Run it on a small batch of recent recordings. Use the bulk scan action from the recordings list, or call `vision-scanners-scan-session` for a handful of session IDs.
3. Read each observation beside its recording. Look for four failures: overclaims, missed proof, weak labels, and instructions the model read literally.
4. Rate each observation in the Calibration tab. Add a sentence when the scanner got the premise wrong.
5. Call `vision-scanners-prompt-suggestions-generate` to draft prompt edits from that feedback. Apply an edit only when the user agrees.
6. Add the cross-observation step. Create a scout from the scanner's Scouts tab (daily digest, trend watch, or new issue watch). The scout compares observations. The scanner never does.

Return to Step 3 before Step 4 when the observations are mostly "no" or "inconclusive". A weak query is the usual cause, not a weak prompt.

## Worked examples

These are PostHog's own scanners over PostHog's own product. Use the shapes, not the text.

**Ghost bugs (monitor).** Question: did the product contradict itself or dead-end the user in a task it invited? Query: a pageview URL regex on the product surface plus `active_seconds > 30` plus test-account filter. Prompt: seven named contradiction patterns, a five-item no list, "both halves on screen", and "most sessions contain no such defect". Priciest tier, because one yes opens a bug.

**Broken render (classifier).** Question: did the page render correctly for this visitor? Query: `visited_page` contains the site domain. Tags: eight defect tags plus `nothing-broken` and `cant-tell`, the last two exclusive. Prompt: every defect tag needs page, location, and timestamp, or the model tags `nothing-broken`. Cheapest tier, because one wrong label only nudges a trend.

**Escape to the AI assistant (summarizer).** Question: what could the user not do in the UI right before they asked the assistant? Query: an issue-viewed event AND a chat-started event. Prompt: verify the two are related first, else output UNRELATED and stop. Then three fixed parts and one closing sentence that names the missing capability.

**Product opportunity miner (monitor).** Question: does this session reveal one concrete, testable product opportunity? Query: an OR of nine high-intent events, the product URL, `active_seconds > 60`, employee exclusion. Prompt: yes only when three conditions are visible, then Evidence, Unmet job, Smallest test, Alternative explanation. Priciest tier, sampled hard, credit-capped, and fed to a daily scout.

## Gotchas

- `allow_inconclusive` is off by default. A monitor without it must answer yes or no and will stretch ordinary sessions into findings.
- A prompt that names a tag missing from the tag list is a silent bug. With freeform tags on, the model invents the tag and nobody notices.
- Prompt edits bump `scanner_version`. Past observations keep the old prompt, so compare calibration ratings within one version.
- One observation per scanner per session. Re-running a scanner on a session it already observed is a no-op. Test a prompt edit on fresh sessions.
