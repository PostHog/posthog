# Scout rubric suggestions: development report

2026-09-29 latest: retain the plain-language prompt after [expanded-field checks](#expanded-editor-readability-recheck)
across twelve scouts, six with history and six without. All twelve outputs preserved the scout's
intended behavior. Eleven were readable without required edits; one feedback criterion needed a
localized sentence repair. That is 59 of 60 criteria clear as generated, not a claim of flawless
wording. The instructions are general and contain no scout-specific exceptions.
The earlier [40-generation pass](#readability-pass-2026-09-29) and [additional checks](#additional-sol-checks)
remain recorded below; their readability grades were too lenient for expanded fields.
The broader content gates describe an earlier prompt, not a full retest of this wording change.
GPT-6 Sol at high effort remains the default. Explicit runtime overrides still apply.

2026-09-28: retain the integrated two-step generator for editable rubric drafts. It passed the
registered broad content gates, native API generation and the real browser
Generate → edit → Save → reopen flow. The last native content check required removing one
redundant suggestion. Two subsequent prompt variants completed 68 additional generations but
did not establish an improvement, so neither replaces the integrated version.

This is ready for supervised local use, not automatic acceptance of generated criteria. Owners
must check suggested rules against the scout's intended behavior and existing rubric before
saving. Historical checkpoints, independent originals, separate judging corrections and failed
validations are retained below. The changes have not been deployed.

The earlier content-validation candidate passed nineteen development conditions, 33 copied-scout conditions plus
a separate description-only condition, four fixed repeat comparisons and three original holdouts.
The copied-scout result includes separately recorded source-based judging corrections. Both
reviewers accepted all three untouched outputs without required edits, retaining 13/13 suggestions.
It drafts complete criteria before selecting additions; selection cannot rewrite them.

| Earlier content-validation implementation                                                       | Result                                                                            |
| ----------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------------- |
| Nineteen development conditions                                                                 | Both reviewers accepted all nineteen without required edits                       |
| Ten copied scouts with zero, one or five runs, saved-rubric cases and one description-only case | All 34 accepted after separately recorded source adjudication                     |
| Four repeated inputs                                                                            | Both reviewers accepted every repeat and found the central rules consistent       |
| Three original holdouts                                                                         | Both reviewers accepted all three without required edits                          |
| Two native API generations                                                                      | Completed with saved criteria unchanged; both outputs accepted                    |
| Browser generation and editing                                                                  | Completed, survived reload, saved the selected edit and preserved it on reopening |

The sixty content-validation executions include repeated conditions; they are not sixty independent
scouts. The three additional native generations check integration on familiar inputs. Detailed
original judgments, later corrections, failures and limitations remain distinct below.

## Intended v0 behavior

The generator proposes editable evaluation criteria for one scout. An owner selects suggestions, edits them and saves the rubric. Suggestions contain a title, description, pass condition and applicability. Generation does not replace saved criteria, grade past runs or execute the scout's assignment. Unsaved edits must be saved before generation starts. See the [rubric editor](../../../frontend/inbox/components/config/scouts/ScoutRubricsModal.tsx) and [persistence model](../../../backend/scout_harness/rubrics.py).

The [generator](../../../backend/scout_harness/rubrics_runner.py) uses the description, current instructions, references, up to five recent run summaries and effective saved criteria, including edits and disabled choices. Description-only scouts should also receive useful drafts. Historical behavior is evidence, not policy. No new suggestions are needed when existing criteria suffice.

The implementation supplies bounded source context and reference texts to draft complete criteria, withholding enabled custom saved
criteria until a second request selects whole draft items as additions. Edited defaults and disabled
choices remain visible from the start. One conditional format correction is shared across both
steps. Its exact builder and lifecycle passed 39 focused backend tests before integration,
including preservation of selected text and order, empty selections, invalid indices and safe
rejection of an oversized follow-up. These mocked-session tests establish neither model quality
nor native integration.

The later candidates can bind concrete judgments to named source rules without rewriting every
condition. Evaluations using such criteria must also receive the chosen reference instructions;
they must not silently substitute a tested variant's changed rules. That scoring integration is
outside this rubric-definition feature.

## Evaluation method

The repeated matrix contains fifteen conditions: attendance recaps, playback diagnosis and reminder planning, each with zero, one, five and saved-criteria history variants, plus three description-only jobs. These jobs and their histories were authored for the tests. Saved variants exercise sufficient coverage, gaps and disabled choices. The public comparison uses alert, experiment and PR-follow-up skills from commit `57ca357730843205c2d659098ac8e4c5e07a6698`, without history. The later breadth stage uses product analytics, data warehouse, AI observability and survey skills from that same public commit, also without history.

Two reviewers independently assessed source and final content before phase inspection. Later audits localized errors and recorded corrections separately. Evaluation used ordinary meaning across all criterion fields, respected disabled choices and distinguished central outcomes from peripheral procedures. It required neither specific wording nor a fixed suggestion count.

Ready means no required owner correction. Small means at most one bounded noncentral repair, at least 80% of suggestions retained, and no central omission. Substantial means more work is required. Useful means Ready or Small. High retention alone cannot compensate for an omitted central duty.

The twelve full-instruction conditions require all twelve useful and at least eight Ready, including useful saved-state cases. All three description-only cases must be useful, with at least two Ready. Each public stage requires every case useful and at least two Ready. All gates allow zero Misleading results; a failed run is not a pass. These are development gates, not estimates of production success rates.

## Completed checkpoints

| Checkpoint     | Main change                                                                            | Ready / Small / Substantial                    | Suggestions retained | Gate result                                       |
| -------------- | -------------------------------------------------------------------------------------- | ---------------------------------------------- | -------------------- | ------------------------------------------------- |
| C9             | Evidence-only research, composition, short repair                                      | 11 / 2 / 2                                     | 53/56                | Both invented-case gates failed                   |
| C10            | Ordered duty/coverage composition; preserve sound clauses; authoritative saved context | 10 / 1 / 3, plus one failed run without output | 63/66                | Both failed                                       |
| C11            | Whole-field coverage, source definitions, evidence limits and task-log navigation      | 9 / 2 / 4                                      | 76/80                | Full-instruction gate failed; descriptions passed |
| Public C11     | Unchanged C11 on three published skills                                                | 2 / 0 / 1                                      | 27/28                | Public gate failed                                |
| C12            | Preserve predicates and shared duties; shorter material summaries                      | 10 / 1 / 4                                     | 80/86                | Both invented-case gates failed                   |
| C13            | Evidence → coverage record → final composition                                         | 12 / 2 / 1                                     | 68/70                | Full-instruction gate passed; descriptions failed |
| Public breadth | Unchanged C13 on four additional published skills                                      | 0 / 0 / 4                                      | 32/39                | Public gate failed                                |
| C14 invented   | Fourth-turn source and coverage repair on the same fifteen conditions                  | 11 / 0 / 4                                     | 66/72                | Both invented-case gates failed                   |
| C14 public     | Same fourth-turn design on the four breadth scouts                                     | 1 / 0 / 3                                      | 32/37                | Public gate failed                                |
| C15 invented   | Three turns with source wording and rule scope checks                                  | 13 / 0 / 2                                     | 69/71                | Full-instruction gate passed; descriptions failed |
| C15 public     | Same three-turn design on the four breadth scouts                                      | 0 / 0 / 4                                      | 25/34                | Public gate failed                                |

These are accepted results after corrections. C9's original 7/3/5 result was recalibrated to 11/2/2 after correcting overly literal saved-coverage and peripheral-scope readings. C11 changed from 10/1/4 to 9/2/4 after an unsupported evidence-availability claim was found. Those changes are judging or factual corrections, not generator improvements. C10 retains its failed original; a session-lifecycle change during that stage also prevents a clean prompt-only comparison.

C13's reviewers agreed on 14/15 original grades and retention counts. A separate correction accepted the remaining scope defect: one criterion explicitly left an excluded category of reminder targets unassessed. The final result keeps that failure. The source/read audit introduced no further grade changes.

Both reviewers rated all four public breadth outputs Substantial. Source-based corrections reconciled which suggestions needed changes; the final source/read audit made no further grade changes. The failures narrowed source-supported branches, treated examples as exclusive limits, or allowed a required update to be skipped. Five of six defect mechanisms became explicit during composition; one was already present in the coverage record. No whole-record grades are inferred from that analysis.

C14 has twelve Ready and seven Substantial results across the combined nineteen conditions. Separate source-based corrections preserve the original reviews. In one case a review notice reached the primary reviewer before their record was locked; a third reviewer supplied an independent original, and the nonblind record remains separately identified. No case was replaced or rerun to improve its result.

C14's source/read audit made no further final grade changes. All accepted defects were present before the fourth turn. That turn still made useful repairs, including separating warehouse finding branches and preserving allowed alternatives. Its pre-repair compositions were not established as better, so returning to three turns required another trial. Some overgeneralizations already appeared in the coverage record, supporting an earlier check of source wording and branch scope.

C15 has thirteen Ready and six Substantial results across the same nineteen conditions. All twelve full-instruction conditions are Ready, including the three saved-state cases. Two description-only outputs and all four public outputs require changes. The reviewers agreed on 17/19 original grades; separate corrections preserve the original reviews and do not count as generator improvements. The source/read audit made no further grade changes.

C15's errors include treating one finding type's evidence requirements as universal, excluding permitted alternatives and omitting a required update. Some narrowing already appears in research notes or the coverage record; composition can also discard a correctly recorded branch. The generator therefore still needs better source interpretation, even when tool access and evidence gathering work correctly.

A separate diagnostic changed the two composition prompts to emphasize useful owner judgments and reran the same public AI-observability condition once. The accepted result is Substantial, with 7/9 suggestions retained: the draft still imposes telemetry sample requirements on proactive configuration findings and restricts reviewer resolution to one source. Original reviews and their later source-based corrections remain separate. This single development result does not establish an improvement, replace a failed gate or justify activating the alternative prompts.

A subsequent diagnostic gave that completed draft and its exact original context and reference to one fresh review session. It omitted the earlier research and coverage record, reviewer feedback and defect-specific hints. Both independent final reviews agreed on Substantial, with 8/10 suggestions retained: the same two unsupported restrictions remained. The call took 110.56 seconds and reported $0.4823408. It used one request with no retry, and its sandbox shut down. This single failed repair does not support adding another review call to the product or replace any broader gate.

The fresh review's audit verified the delivered source, reference, draft and final result. The only tool call updated its own task's progress; it did no research or scout-assignment work. Both defects persist from the supplied draft, and the audit required no factual correction to either original content review.

A subsequent paired diagnostic ran six familiar difficult conditions through two approaches. The current three-turn generator included the context fixes described below. Direct composition used one fresh request with the same original context, exact references and effective saved criteria, without research notes or an intermediate coverage record. Both used the same model and reasoning effort. Neither received case-specific repair hints.

After independent reviews and separate source-based adjudications, the three-turn approach had one Ready and five Substantial results, retaining 36/45 suggestions. Direct composition had one Small and five Substantial results, retaining 34/44. The simpler flow therefore did not establish a quality improvement. Median time to a result was 195.77 seconds for three turns and 70.41 seconds for direct composition. This comparison changes both the interaction and input delivery; six single executions do not isolate the cause of that difference.

The paired audit verified the supplied sources, final outputs, runtime selection and session closure. No scout-assignment or project-data writes occurred; five direct sessions used the permitted task-progress update. No factual correction to the final content grades was needed. Originals remain separate from later reviewer corrections.

Review also exposed a limitation of the retention threshold: a single peripheral wording repair among three suggestions receives a worse grade than the same repair among ten. A separate owner-edit-burden label now records unchanged, one bounded noncentral edit, or substantial work. It applies symmetrically, preserves the original grades and gates, and is not counted as a generator improvement.

A later exploratory pilot used direct composition with higher reasoning effort on copied scouts and a description-only condition. Four drafts completed and all four accepted grades were Substantial; the original reviewers agreed on three of four grades. One source-interpretation disagreement remains recorded separately, so retention is reported as 29–30 of 34 suggestions. The concrete repairs concern weakened conditions, omitted required work or routing, and a fallback applied too narrowly.

Completed calls took 501.57–771.81 seconds, with a median of 621.85 seconds. The pilot stopped early because the mandatory description condition failed and the additional completed drafts did not justify that wait. Four outputs were retained, two calls were intentionally cancelled and two conditions were not started. Cancelled and unrun cases receive no content grade. This is an unsuccessful partial diagnostic, not an eight-case result or a general comparison of reasoning settings. The completed-output audit verified supplied context and final text, found no assignment actions and required no factual grade corrections.

A subsequent eight-case pilot returned to normal effort and changed the contract prospectively: selectable criteria could refer precisely to complex source rules while stating the concrete outcome being judged. The evaluator would also receive the reference instructions. This does not excuse explicit contradictions, missing primary outcomes or generic instruction-following checks, and no earlier grade changed under the new contract.

All eight drafts completed. The independent reviewers recorded four Ready / four Substantial and three Ready / five Substantial respectively, retaining 44/49 and 46/49 suggestions; the latter also identified two missing central checks. Both failed the registered pilot gate. Their source-interpretation and coverage disagreements remain in the original records; no pooled grade is asserted. Several drafts still rewrote complex policy incompletely, losing a condition, permitted alternative or fallback. A saved-criteria condition also failed both reviews.

Median time was 55.34 seconds, with a 50.34–80.39-second range and $2.1384586 in reported generation cost. Technical checks verified the inputs, selected runtime, provider completion and isolation. No further model-action trace audit was performed for this rejected candidate.

The next candidate asked for fewer outcome checks and precise source references without partial policy restatement. All eight completed, with a 50.33-second median and $1.9025616 reported cost. Independent originals were four Ready / one Small / three Substantial, retaining 31/35 suggestions, and two Ready / two Small / four Substantial, retaining 34/35 plus four missing checks. A separate correction withdrew one mandatory addition because an enabled saved criterion already caught its counterexample; that draft became Ready for that reviewer. The original remains preserved, and this is a judging correction rather than generator improvement. Both results still fail the pilot gate.

Owner-facing text in that eight-case set fell from 5,348 to 3,484 words. Shorter criteria still missed required affirmative outcomes or discarded permitted fallbacks, and some summaries asserted false conflicts. High retention did not establish completeness.

The next candidate explicitly checked whether every required result reached its outcome, destination and recipient. Seven of eight attempts returned valid drafts; one ended with a prose reference to earlier JSON, which the final-message capture could not validate. That failed original remains ungraded and was not replaced. Both reviewers rated four valid drafts Ready and three Substantial, retaining 31/34 and 30/34 suggestions respectively; one reviewer also identified a missing routing check. The pilot failed. The remaining corrections preserve legitimate unchanged-item decisions and documented delivery alternatives.

All eight sessions closed with verified inputs, runtime and isolation. Reported cost was $1.940133; valid outputs took 40.30–60.36 seconds, with a 40.44-second median. This diagnostic had no format retry, unlike the product. The following candidate uses the existing product's single conditional format correction and an invented example of concrete outcomes bound to named source rules. Its broader evaluation will cover all copied-scout history conditions even if the pilot fails, without treating exploratory breadth as a passed gate. The source-linked judging contract and gates remain unchanged.

That candidate completed all 34 conditions: ten copied scouts with zero, one and five prior runs, three saved-criteria conditions, and a separate description-only condition. Across the 33 copied conditions, independent originals were 26 Ready / 3 Small / 4 Substantial and 30 Ready / 2 Small / 1 Substantial, retaining 172/181 and 179/181 suggestions respectively; the latter also identified a missing state-retention check. Both rated the description-only output Ready. These are original reviews, not a pooled verdict. One reviewer failed a mandatory saved-criteria condition; the other accepted all three saved conditions but found invalid delivery restrictions across a different scout's three history conditions.

The round reported $8.103559 and a 40.40-second median generation time, ranging from 40.29 to 50.54 seconds. All 34 completed without format correction, with verified inputs, runtime, isolation and provider closure. A captured-log audit found only the permitted own-task progress tools and matching initial requests and final packets. It does not establish the absence of activity outside the captured logs. The proposed product builder also matched the source, reference and saved-context content for all 34 fixtures in a separate read-only check; it additionally reports reference clipping limits explicitly.

Separate source-based adjudications brought both reviewers to 26 Ready / 3 Small / 4 Substantial across the 33 copied conditions, retaining 173/181 suggestions plus one missing central check. Both still rated the description-only output Ready. Three history conditions for one scout imposed a normal delivery route on an allowed fallback; a saved-criteria condition omitted required state retention. One original rejection was withdrawn because a precise source reference retained the original rule's scope without adding a conflicting requirement. Original reviews remain unchanged; these corrections are not generator improvements.

The accepted result fails the mandatory saved-criteria gate. A successor kept the same source-linked contract and added an invented negative example of an unconditional requirement that contradicts an allowed alternative. It also checked whether saved coverage includes required output and durable state.

That successor completed the same 34 conditions. Copied-condition originals were 28 Ready / 1 Small / 4 Substantial and 29 Ready / 4 Substantial. Both accepted all three saved-criteria cases and the separate description-only case. The missing memory outcome was covered, but three fallback drafts still imposed the normal route. Another draft granted an unconditional pass when fresh input was absent, despite required pending work.

Separate source-based corrections produced 27 Ready / 1 Small / 5 Substantial and 28 Ready / 1 Small / 4 Substantial across the copied 33, retaining 170–171 of 179 suggestions. The remaining disagreement concerns whether explicitly named exceptions qualify an absolute restriction later in the same criterion. Both original reviews and the separate reasoning are retained; no forced consensus is reported. These results clear the numerical breadth thresholds, but the required repeated-input validation has not run and its selected fallback original is already unusable. This is not a full validation pass.

All 34 sessions closed without format correction, with verified inputs and runtime. Reported generation cost was $8.2727186; median time was 50.32 seconds, ranging from 40.29 to 60.52 seconds. Captured tools only updated the generation's own progress. The next selected prompt gives complex pass conditions a stricter decision-and-source form and forbids appending a partial operating-rule list. It keeps the same model, inputs, output schema and judging contract. The full set will run again; untouched holdouts and product integration remain pending.

The stricter decision-and-source candidate completed all 34 conditions without format correction.
Across the copied 33, independent originals were 32 Ready / 1 Substantial and 30 Ready / 3 Substantial,
retaining 194/194 plus one missing central check and 191/194 suggestions respectively. Both accepted
all three saved-criteria cases and the separate description-only case. Their original disagreements
concern one missing follow-up duty and whether report-format wording rejects permitted alternatives.
These are separate original judgments; source adjudication and repeated-input validation remain pending.

Reported generation cost was $8.3280338; median time was 50.326 seconds, ranging from 40.293 to
60.488 seconds. All inputs, runtime selections and provider closures passed technical checks.
The captured-log audit found only own-task progress actions and matching source and final packets.
Owner-facing output totaled 14,728 words across 198 suggestions and 34 summaries. The prepared product
builder matched the same 34 source contexts in a read-only comparison with the current candidate;
the live product implementation has not yet been replaced.

Separate source adjudications brought both reviewers to 31 Ready / 2 Substantial across the copied33,
retaining 193/194 suggestions plus one missing central check. The description-only case stayed Ready.
The remaining defects omit an update to prior work and reject a permitted capped deferral. Two
report-format references were accepted because they name aspects of complete conditional source
rules rather than adding independent requirements. These are judging corrections, not new generation
improvements; all originals remain preserved. The numerical, history-state and saved-criteria gates
pass. The unchanged candidate now proceeds to the four fixed repeated inputs, then broader validation;
this is not yet a full validation pass.

The four fixed repeats then completed. One original reviewer rated three Ready and one Small; the
other rated two Ready, one Small and one Substantial. A separate source check confirmed the latter:
one applicability clause rejected a valid no-action outcome. The unchanged originals and first pair
comparison remain preserved. Both reviewers now find three of four pairs useful and consistent,
so the required repeat gate fails. The Small draft only needs an incorrect saved-criteria count
removed from its summary; all four of its criteria remain usable.

Reported repeat cost was $1.074693, with all inputs, runtime selections, captured actions and
provider closures verified and no format correction. The next candidate keeps the same source-linked
contract and one-call flow, but prevents applicability fields from restating operating policy. It
also checks required updates to existing deliverables and omits summary inventories. The full34
diagnostic runs again; broader validation and untouched holdouts remain pending.

The applicability-focused successor completed all 34 conditions. Both independent originals agree:
the copied 33 have 32 Ready and one Small, retaining 190/190 criteria with no required additions;
the separate description-only case is Ready with 5/5 criteria retained. All pilot, history-state
and saved-criteria content gates pass. The only required edit qualifies a summary that said evidence
was absent when compact run summaries described the behavior without verifying it. No criterion
needs correction. Repeated applicability wording can be shortened as an optional owner edit.

All 34 sessions closed with verified source, runtime and isolation, no format correction and only
own-task progress actions in the captured logs. Reported generation cost was $8.3107342; median
time was 40.33 seconds, ranging from 40.29 to 70.40 seconds. Median owner-facing text was 434.5 words,
with a 310–566-word range. These familiar development cases are not untouched holdouts or a causal
comparison. The same prompt now undergoes the four fixed repeats before broader validation.

Both reviewers then rated all four fixed repeats Ready, retaining 22/22 criteria. Every matched
pair remains useful and preserves the source's central rules, passing the registered repeat gate.
One draft combines two related judgments without losing coverage or a permitted alternative.
All four sessions closed with verified inputs, runtime and isolation, no format correction and no
captured scout-assignment actions. Reported cost was $0.9303226. The unchanged prompt proceeds to
the existing nineteen-condition development set; repeats add no new scout breadth or holdout credit.

The nineteen-condition set completed. Independent originals are 18 Ready / 1 Substantial and
17 Ready / 2 Substantial, each retaining 89/90 suggestions; the latter also identifies one missing
central outcome. Both rate all four public outputs Ready, retaining 24/24. Both full-instruction
gates fail, for different saved-criteria cases. One reviewer finds a duplicate-only addition; the
other finds that successful completion lacks a required affirmative result. Their description-only
grades are three Ready versus two Ready and one Substantial, with the latter rejecting an added
posting restriction. Separate source adjudication is pending; these are unpooled originals.

All 19 sessions closed with verified source, runtime and isolation, no format correction and only
own-task progress actions in the captured logs. Reported cost was $3.6358274; median time was
40.30 seconds, ranging from 30.27 to 50.64 seconds. Untouched holdouts remain unopened. An inactive
successor proposal checks saved coverage in both directions and preserves the direction of source
conditions across all criterion fields, without adding another generation call.

Separate source reviews converge on 16 Ready / 3 Substantial, retaining 88/90 suggestions plus one
required central addition. A proposed check duplicates an already required result; another draft
does not cover the affirmative successful-result branch; a description adds a restriction absent
from the source. The first and third need bounded owner edits, while the second needs additional
coverage. Their original grades and interpretations remain unchanged in the review records; these
are judging corrections, not generator improvements. The full-instruction and description-only gates
fail, and the public gate passes. The small general correction now runs on the same nineteen cases,
with the original model, inputs, schema, one-call flow and grading contract.

The corrected prompt completed all nineteen conditions. Both original reviewers rated fifteen Ready
and four Substantial, but on different cases. They retained 87/88 and 86/88 suggestions, with three
and two required coverage additions respectively. Both full-instruction and description-only gates
fail. Public-scout originals are three Ready / one Substantial versus four Ready; separate source
review is pending. The failures include missing actual investigation or successful-result coverage,
an added exclusion, and disputed redundancy with saved criteria. Most retained criteria need no edit,
but their quality does not establish that the rubric covers the scout's primary job.

All nineteen sessions closed with verified source, runtime and isolation, no format correction and
only own-task progress actions in the captured logs. Reported cost was $3.837206, with a 40.34-second
median. The next diagnostic changes reasoning effort while keeping the model, prompt, cases, output
schema and review contract fixed. It tests whether more reasoning is useful before adding another
generation phase. A single execution per condition will not establish a causal improvement.

Separate source review confirms the missing monitoring check in the public-scout case. The reviewers
still disagree about whether one saved rubric already excludes a separately labelled estimate:
one retains the proposed check, while the other treats it as redundant. Their corrected totals
are fifteen Ready / four Substantial and fourteen Ready / five Substantial, with three missing
coverage checks each. All three groups fail for both reviewers. Neither original judgments nor
the disagreement are overwritten; this uncertainty does not explain away the agreed omissions.

A targeted reread of the earlier scope candidate's ten zero-history copied-scout drafts found no
additional unambiguous missing investigation check. Eight explicitly cover assigned work or valid
early exits; two use less direct complete source references with affirmative completion duties.
This is a nonblind audit of familiar cases, not new breadth or another independent validation pass.

The higher-effort diagnostic closed with seven valid drafts and one accepted call that reached the
normal fifteen-minute timeout without a final output. The remaining eleven cases never started.
All accepted sessions and their providers are closed. Completed calls took roughly five to eight minutes.
The timeout's captured metadata shows no completed answer awaiting finalization, but cannot
distinguish long upstream inference from a stalled request. Its cost receipt is absent. The failed
original stays ungraded and will not be replaced. This is a partial failed diagnostic, not a
nineteen-case pass or proof that reasoning effort caused the timeout.

The two original reviews rate the valid subset six Ready / one Substantial and seven Ready,
retaining 30/31 and 31/31 suggestions. The same saved-coverage ambiguity explains the disagreement.
Both accept the previously missing successful-result branch in this subset. That observation does
not establish a general improvement, and the timeout leaves the registered full-set gates untested.
Reported receipts total $9.124422; the timed-out call has no receipt and a separate conservative
$15 cost estimate. These are not interchangeable measures of actual spending.

The next selected prompt returns to the faster effort setting. It forms a small complete set of
source-specific judgments before subtracting saved coverage, then checks that required result
branches remain covered. It also retains source categories when expressing simple conditions.
The source-linked contract, inputs, output schema and one-call flow remain unchanged.

That completion-first trial produced nine valid drafts, one technical failure and nine unrun cases.
Both original reviewers rated eight Ready and one Substantial, retaining 29/30 and 30/30 suggestions
with one missing required outcome. Separate source review reconciled retention to 29/30: a criterion
allowed deliberately omitted work to pass merely because its result was correctly labelled unresolved.
The saved-state draft also omitted a required affirmative successful result. The earlier redundant-only
addition disappeared; sufficient saved coverage correctly yielded no suggestions. Originals and the
separate correction remain preserved. The complete nineteen-case gates cannot pass this partial batch.

The technical failure began with a gateway model-access rejection before model progress, followed by
a recovery request against an already completed session. The reported SDK cost and token counters
are zero; this is captured SDK metadata, not a billing receipt. Other calls with the same selected
model and project succeeded. The inconsistency remains under investigation, without changing billing
or access controls and without replacing the failed attempt.

The next proposed diagnostic drafts complete source-specific criteria while withholding enabled
custom saved criteria. Defaults and disabled choices remain visible. A second call selects whole
draft criteria after comparison with the original saved set; code copies their text unchanged.
This isolates subtraction from drafting and prevents the selection call from adding new operating
rules. It adds a serial call and can still omit useful criteria, so it needs fresh validation.

That two-step diagnostic completed all nineteen conditions. Both original reviewers recorded
17 Ready and two Substantial, retaining 80/82 suggestions with no missing central additions.
All three description-only and four public outputs pass their gates. The twelve full-instruction
conditions fail the all-useful gate: one criterion permits skipped work when honestly labelled
unresolved, and a saved-state result repeats an eligibility judgment already covered by the whole
saved criterion. The first requires a central repair; the second requires one bounded noncentral
deletion and its related summary correction. The retention threshold still grades it Substantial.

One reviewer received a notice of agreement on those two already-locked cases after eighteen
originals were locked, before writing the final survey original. The notice contained no peer grade
for that pending case, and no original was changed. This sequence limitation is recorded separately;
the other reviewer completed all nineteen originals without peer information.

The bounded phase inspection locates the skipped-work waiver in the first draft. Selection preserves
it unchanged. Eligibility is a legitimate draft judgment before custom saved criteria are revealed,
but selection wrongly keeps it after receiving the complete saved set. It also adds the inaccurate
coverage explanation. The next prompt changes address these distinct steps: primary work and its
required result must both hold, and all fields of an existing saved criterion define its meaning.
The source-linked contract, schemas, cases and gates remain unchanged.

All nineteen sessions closed with verified inputs, runtime, isolation and exact whole-item selection.
One conditional format correction was used. Captured tools only updated the generation's own progress.
Reported generation cost was $4.765856, with a 60.3-second median and a 40.3–90.5-second range.
Owner-facing text totaled 6,040 words, including 713 summary words, with a 325-word median per result.
These familiar development inputs do not establish untouched performance or a causal comparison.

The targeted successor completed the same nineteen conditions. Both reviewers locked all nineteen
originals before any peer result or phase access, and both rated every result Ready: 79/79 suggestions
retained, no required additions and no owner repairs. Full-instruction, description-only and public
gates all pass. The two previously identified defects are absent in these outputs. This is a familiar
development pass; it cannot be combined with an earlier prompt's copied-scout or repeat results.

All nineteen sessions closed with verified inputs, runtime, isolation and exact whole-item selection.
No format correction was needed, and captured tools only updated the generation's own progress.
Reported generation cost was $4.7193332, with a 50.4-second median and a 40.3–60.4-second range.
Owner-facing text totaled 6,187 words, including 672 summary words; median result length was 324 words
and the range was 35–495. These counts exclude the source instructions needed to apply the criteria.
The unchanged candidate then completed the full copied-scout matrix. All 34 originals from both
reviewers were locked before any peer result was disclosed. Across the 33 copied conditions, the
original grades were 32 Ready / 1 Substantial and 31 Ready / 1 Small / 1 Substantial, retaining
185/186 and 184/186 suggestions. Both rated the separate description-only result Ready, retaining
4/4. One reviewer's original result failed the required saved-state gate.

Separate source checks resolved three disagreements without changing generated text or originals.
One criterion's full source binding preserved distinct permitted branches despite an imprecise title.
Two apparently overlapping completion checks added required investigation or durable outcomes that
the saved checks did not require. In particular, checking the correctness of existing records does
not necessarily require creating a record for an empty or blocked result. One intermediate correction
missed that distinction and is preserved alongside the final correction. Both final assessments are
33 Ready copied results, retaining 186/186, plus the Ready description result. The registered breadth
gate passes. These are judging corrections, not generator improvements.

All 34 sessions closed with verified inputs, runtime, isolation and exact whole-item selection.
No format correction was needed; captured tools only updated the generation's own progress.
Reported generation cost was $10.3006922, with a 50.4-second median and a 50.3–80.6-second range.
Owner-facing text totaled 15,702 words, with a 463.5-word median per result; median pass-condition
length was 35 words. The four fixed repeats remain a separate validation of this same candidate.

## What the iterations established

Recurring defects change prerequisites, lose shared thresholds or duties, duplicate saved coverage, or treat known unmet requirements as unknown evidence. Summaries can overstate inspection or disagree with criteria. Final review repaired some issues but also preserved or introduced others.

Shorter summaries helped reading burden. Across the same fifteen conditions, C12 reduced owner-facing text from 12,493 to 11,305 words, while criterion text increased from 8,780 to 9,848. That supports a narrower summary improvement, not a blanket concision or quality claim.

C13 produced 9,804 owner-facing words, including 1,436 summary words. Median pass-condition length fell from 73.5 to 62.5 words; median start-to-result time rose from 120.59 to 140.69 seconds. Its two smaller defects concern a summary exception and an unnecessary reporting requirement. The central scope defect remains. These observations do not establish a causal advantage from one run per condition.

The four public breadth outputs contained 5,940 owner-facing words, including 384 summary words, across 39 suggestions. Median pass-condition length was 86 words and median start-to-result time was 195.84 seconds, with no format correction. These different jobs are not a controlled latency or quality comparison with the invented matrix. Short summaries still left roughly 1,400–1,660 words per output for an owner to review.

C14 produced 16,860 owner-facing words across 109 suggestions. Compared with C13, the same fifteen invented conditions grew from 9,804 to 10,609 words and median latency from 140.69 to 160.77 seconds. The four public outputs grew from 5,940 to 6,251 words and median latency from 195.84 to 240.96 seconds. The extra turn took a median 24.14 seconds. These single executions do not establish a causal quality improvement.

C15 produced 15,744 owner-facing words, including 1,962 summary words, across 105 suggestions. Median pass-condition length was 72 words and median start-to-result time was 150.66 seconds. No format correction was needed. Fewer turns and shorter output did not establish better quality across the public scouts.

The C15 audit verified all supplied contexts, final outputs and 45 source/history reads. No scout-assignment action occurred. Four final turns omitted the system-required progress update; this did not change the content grades. Four turns emitted several messages, so phase analysis includes the raw log rather than assuming each saved last-message capture is complete.

Existing [backend tests](../../../backend/test/test_scout_rubrics.py) cover saved-state preservation, results and failure/concurrency behavior; [frontend tests](../../../frontend/inbox/logics/scoutRubricsLogic.test.ts) cover selection, saving and generation guards. Development runs also checked context, final output parity and evidence claims. These complement semantic review.

## Limits

The selected candidate passed the registered development, copied-scout, repeat and untouched gates. These finite sets do not establish performance across all scouts or model settings. Repeated conditions are not independent breadth, and these runs do not support causal model or prompt rankings. The final native API and UI observations have the boundaries described below.

The selected generator receives up to five run summaries and four reference files, with reference text capped at 60,000 characters combined. Initial instructions are separately capped at 60,000 characters. Clipping is marked explicitly. It does not receive full historical transcripts or report contents. Access, sampling and shared references limit conclusions. Uninspected material must not be described as unavailable.

A later local fix also marks clipped reference lists, run summaries and emitted-report lists, retaining their existing limits. It removes the inaccurate statement that supplied instructions are always complete. All 28 backend tests and focused lint checks passed, including exact-boundary and clipped-context cases at the session boundary. The paired diagnostic included this fix but does not isolate its effect.

A second context fix supplies the scout's report channel and the matching existing instructions for creating, editing or skipping reports. A shared selector keeps these rules aligned with the normal scout prompt; scouts without report tools receive an empty section. All 40 focused tests passed, and a baseline comparison found identical normal scout prompt text for all four channel modes. This supplies one missing part of the assignment, not the entire execution policy. It adds no generation turn. Both approaches in the paired diagnostic included these instructions, so that trial does not isolate the fix's effect.

The repeated prompt trials used the product prompt builder and session execution through a direct entrypoint. Separate earlier description-only checks exercised authenticated API handlers, ordinary background dispatch, task linkage and persisted completion with an in-process client and an isolated test quota counter. Those checks do not establish a fresh browser-to-generation pass for the latest candidate. Browser selection and save/reopen observations, mocked rendering and deterministic persistence tests provide separate integration evidence. Each selected suggestion must work with the saved rubric and named reference instructions; another new suggestion cannot supply its prerequisites. Later content reviews explicitly assess this independent use.

C15 also completed one local integration check with copied history and saved criteria through the authenticated API handler, ordinary background dispatch and persisted results. Saved criteria and disabled scout settings remained unchanged. Input, output and evidence claims were audited, and the sandbox shut down. One complete history log was retrieved into a file while only selected excerpts were inspected, so the reading was broader than the requested excerpt. Two further planned conditions were not run because the spending guard stopped the stage. This check used an in-process API client and a separate test quota counter; it does not establish browser-to-generation behavior, unchanged quota behavior or a broad quality pass.

A later editor check used an invented fixture, a fresh local session and real rubric GET/PUT requests. Selection, all four edited fields, a disabled default, the save-before-generation guard and persisted reloads at 1440 and 520 pixels passed their assertions. Its final zero-page-errors assertion failed because the check deliberately closed development WebSockets; a separate read-only reproduction traced the error to Vite's connection handler. The failed original remains unchanged. The application shell was mocked and a local request bridge supplied transport, so this does not establish normal navigation, browser-origin behavior or generation. The temporary identity, session and config were removed.

A fresh editor rerun kept every functional assertion and allowed only the two local preview WebSocket paths. It passed with zero page errors, one save request and the same persisted reload checks at both widths. Visual inspection found readable content without horizontal clipping. The temporary identity, session and config were removed again. The earlier failed result and the mocked-shell and local-transport limitations remain; no generation was triggered by this check.

The development inputs, generated outputs and review records are not included here. These aggregates therefore are not a publicly reproducible benchmark. No customer examples are reproduced, no broad quality conclusion is claimed from the copied-data check, and untouched holdouts receive no credit from these development results.

## Joint-selection repeat check

The unchanged two-step candidate completed all four registered repeats. Both reviewers independently
rated all four Ready, retaining 23/23 suggestions with no required additions. After both complete
original sets were locked, each reviewer compared the four exact source-matched baseline/repeat
pairs. Both found every output useful and the central source rules consistent. Optional emphasis
and grouping varied; neither identified a new required repair or changed central rule.

One reviewer corrected swapped metadata labels for the first two packets separately. The original
content reviews used the correct packet sources; the correction verified the actual history counts
and found no corresponding error in either generated summary. Original reviews remain unchanged.

All four attempts completed, their providers and launcher closed, and the request, source, runtime,
isolation and exact-selection checks passed. No format correction was used. Reported generation
cost was $1.3116736; median time was 55.4 seconds, ranging from 50.3 to 60.4 seconds. These are
repeats on familiar development inputs, not new breadth or a production success-rate estimate.

The two prompts and inactive product implementation were then frozen before revealing the three
original holdout inputs. Those fixtures and their expectations retain their earlier identities,
order and acceptance rules; no generated output has been used to revise them.

## Untouched checks

The unchanged candidate completed the three original holdouts, once each. Both reviewers locked
all three independent source-first reviews before reading the prewritten expectations. Both rated
every result Ready, retaining 13/13 suggestions with no required additions or owner edits. Separate
expectation comparisons preserved those grades and the original reviews.

The checks cover disabled saved choices, source-specific comparisons, delivery and quiet outcomes,
permitted fallbacks, missing data and a description-only assignment. An existing assessment can
overlap a useful new criterion without covering it fully. Likewise, assessing delivery of an already
established result does not necessarily restore a deliberately disabled discovery judgment; the
comparison records distinguish those cases using the complete source and saved definitions.

All three requests, runtime selections, final outputs and whole-item selections passed technical
checks. Captured tools only updated generation progress, and no format correction was needed.
The test capture encountered local provider-access and asynchronous completion issues; the original
outputs were recovered unchanged, without model retries or replacements. Provider shutdown was
verified through the existing task worker. The failed capture records remain preserved.

Reported generation cost was $0.898808. Median generation time was 50.4 seconds, ranging from
50.3 to 60.4 seconds; this excludes the subsequent capture recovery. Owner-facing output totaled
1,009 words across three summaries and thirteen criteria. Three untouched cases support this
bounded validation, not a population-wide success rate.

The exact tested implementation and its focused tests were then copied into the product. Lint and
format checks passed. Independent implementation review found no actionable integration issues.

## Native integration and result rendering

Two fresh generations exercised authenticated API handlers, normal quota checks, background
dispatch, task linkage and persisted completion: one copied scout with five run summaries and a
saved rubric, and one description-only scout with no history. Both completed in approximately
61 seconds. Saved criteria and revisions stayed unchanged, and both providers shut down.
Reported generation cost was $0.648402.

Captured requests verified the integrated source and actual runtime. Each session used exactly
two requests, with no format correction or empty-turn retry. The second request received the
complete saved rubric. Its selected indices produced exactly the persisted whole draft items,
including their original order. Only own-task progress updates appeared in the captured tool calls.

Both reviewers independently accepted both final outputs without required edits: 2 Ready, 7/7
suggestions retained. They locked their originals before peer comparison. One reviewer had already
read the implementation and disclosed that familiarity. An optional summary wording clarification
is recorded separately; the corresponding criterion preserves the source rule. These familiar
conditions provide native integration and semantic review evidence, not additional untouched breadth.

The real app then rendered both persisted results at widths of 1440 and 520 pixels. Rubric responses
were not mocked. The checks verified summaries and criteria, selection, adding to the local draft,
editing, the save-before-generation guard and discarding changes. All four saved documents remained
unchanged. Visual inspection found readable layouts without horizontal clipping.

The first browser check passed every functional assertion, then failed because it asserted zero
blocked requests after deliberately blocking the page's unrelated fleet synchronization. The failed
record remains preserved. A corrected run accepted only that explicit block and passed all checks
with zero browser errors. An unrelated feature-gated endpoint returned 403; its notice was recorded
and dismissed. Development asset URLs were mapped to the local asset server without changing CSP.
Thus the browser evidence covers real rubric reads, rendering and local draft interaction with fleet
sync blocked. Generation used an in-process authenticated API client; this is not a fresh browser
Generate → Save end-to-end run. Earlier save/reload checks and deterministic persistence tests
provide separate evidence for saving.

A subsequent full browser check used a fresh disabled copy of the description-only fixture. The
actual Generate button submitted one authenticated request with the normal quota. After reloading
while generation was running, the editor recovered its progress and displayed the completed result.
Generation took 50.5 seconds. Selecting a suggestion, editing its title and saving sent exactly one
update; saved defaults remained unchanged, the revision increased once and the edit persisted after
another reload. Generation was disabled while edits were unsaved and available again after saving.
There were zero browser errors. This check retained the documented local asset mapping, blocked
unrelated fleet synchronization and recorded the unrelated feature-gated 403 response.

The final browser-generated content received independent original grades of Ready, retaining 4/4,
and Substantial, retaining 3/4. Separate source adjudication brought both to the latter: one proposed
judgment repeated an enabled default's explicit coverage. Removing it is one bounded noncentral
edit, but 75% retention falls below the unchanged 80% threshold. Neither reviewer found a central
omission or an incorrect rule. Original judgments and corrections remain separate. This extra
native check does not revise the earlier broad-gate results or count as new untouched breadth.

The captured input, actual runtime and exact two-step materialization passed, and the provider
closed. Reported generation cost was $0.292881. A private capture helper failed while serializing
an already verified completion timestamp; a separate recovery reused its saved evidence without
repeating generation or provider actions. The failed capture record remains preserved.

The next tested candidate tightened selection against explicit coverage in defaults while retaining
useful source-specific primary outcomes. It left the initial draft prompt, model, schema and UI unchanged.

These results describe local validation, not deployment. Private inputs, outputs, screenshots and
detailed review records stay outside version control; this report contains aggregate results only.

The selection-only correction completed its four-case screening subset. Both original reviewers
accepted all four without required edits, retaining 13/13 suggestions. The subset includes a
description-only case and the three mandatory saved-rubric conditions. The redundant default
judgment is absent from this description result, while source-specific required work, writes and
allowed outcomes remain covered. This is a small observed result, not a full regression pass or a
causal estimate. The remaining thirty copied-scout conditions subsequently completed on the unchanged candidate.

Across the 33 copied conditions, independent originals were 33 Ready with 185/185 suggestions
retained, and 32 Ready / 1 Substantial with 184/185 retained. Both accepted the separate
description-only result, retaining 3/3. A separate source adjudication brought both copied results
to 32 Ready / 1 Substantial. Originals remain preserved; this is a judging correction, not a
generator improvement. The broad content thresholds pass, including the saved-state conditions.

The remaining defect is a short but central repair: an explicit list of allowed outcomes excluded
a fallback permitted by the source. A later reference to the full rules did not cancel that added
restriction. Because this case is also a preselected stability input, its failed baseline prevents
a passing stability comparison. No replacement output or additional repeat was used to erase it.
The subsequent candidate clarified that a complex pass condition must use the complete source
binding, without prefixing or appending an incomplete restatement of the policy.

All 34 sessions completed with verified source, runtime, exact selection and provider shutdown.
There were 68 expected requests and no format corrections, empty-turn retries or terminal errors.
Captured actions were limited to own-task progress. Median generation time was 60.36 seconds,
including session setup and both requests but excluding later capture. Reported cost was
$10.5488612. Later development, repeat and familiar-holdout checks were not run for this candidate.

## Final drafting-clarification trial and selection

The drafting clarification completed the same 33 copied conditions and separate description-only
condition. Both reviewers locked all 34 originals before seeing one another's results. Each original
aggregate had 30 Ready, 2 Small and 1 Substantial among copied conditions, but they disagreed about
which outputs needed changes. Both accepted the description-only result, retaining all three criteria.

Separate source adjudication confirmed one central restriction: a proposed criterion applied a
reporting standard to a permitted lower-confidence record. Two standalone suggestions duplicated
enabled instruction checks, and two summaries understated existing rubric coverage. The summaries'
suggestions remained useful. These corrections preserve the original reviews and are not generator
improvements.

One saved-rubric case remains disputed. One reviewer sees a missing blocked outcome; the other
reads that outcome as already covered by the complete saved definition. Their corrected copied
results are respectively 28 Ready / 4 Small / 1 Substantial with 177/180 suggestions retained,
and 27 Ready / 4 Small / 2 Substantial with 176/180 retained. The execution owner uses the latter,
conservative reading: 31/33 Useful, with the mandatory saved-case condition unmet. That case needs
one duplicate removed, not a missing central judgment added. It falls below the unchanged retention
threshold because only three suggestions were returned. The disagreement is retained rather than
presented as consensus. Neither assessment establishes a full acceptance pass for this candidate.

All 34 generations completed with source, runtime, exact selection and provider closure verified.
They used 68 requests, no format repairs and only their own progress updates. Median generation
time was 60.34 seconds, including session setup and both requests; reported cost was $10.5900788.
One shutdown observation failed after generation had completed. A later observation confirmed
termination without repeating the model call or changing its output; both records remain preserved.
A review metadata correction fixed one history-state label without changing its judgment.

Both reviewers recommended retaining the earlier integrated implementation. It has the broader
completed validation and a working editing flow; neither later candidate demonstrated a reliable
quality gain. These single executions on familiar inputs do not isolate the cause of output changes.
Further prepared tests for the rejected candidates were not launched, and their prompts remain
inactive. The retained version's occasional duplicate suggestion remains an explicit limitation,
alongside the need to supply the referenced source instructions to any future evaluator.

## Readability pass, 2026-09-29

Four fixed inputs covered a public analytics scout without runs, two copied scouts with five run
summaries, and an invented description-only scout. Every prompt version ran once per input on
`claude-opus-5-5` and `gpt-6-sol`, both at high effort. At most two sessions ran concurrently.
The source context, generation flow and selection rules stayed fixed. Model defaults did not change.

One separate reviewer recorded content and readability judgments before seeing model or prompt
labels. The execution owner also reviewed the wording and shared a stricter preference for ordinary
terms during the pass. Original reviews remain preserved.

| Prompt version                        | Content: Ready / Small / Substantial | Readability: Clear / Small edit / Rewrite |
| ------------------------------------- | ------------------------------------ | ----------------------------------------- |
| Baseline                              | 6 / 2 / 0                            | 2 / 1 / 5                                 |
| Plain-language footer                 | 5 / 1 / 2                            | 5 / 3 / 0                                 |
| Short action titles                   | 6 / 1 / 1                            | 4 / 2 / 2                                 |
| Concrete wording examples             | 5 / 1 / 2                            | 8 / 0 / 0                                 |
| Meaning-preserving examples, retained | 6 / 2 / 0                            | 7 / 1 / 0                                 |

Earlier attempts shortened categories or made conditional evidence mandatory. The retained footer
gives concrete warnings against those changes while asking for short titles and plain explanations.
Its final eight needed no source-rule repair: 37/39 suggestions were retained. Both code-scanning
outputs repeated a label check already covered by a default. One feedback explanation still needed
plainer wording; one analytics title could also be simpler. Owners should continue reviewing drafts.
The existing grades and retention threshold were not changed, including an earlier duplicate-only
four-item result that fell below the threshold after removing one item.

The final four Sol outputs were Clear; three Opus outputs were Clear and one needed a wording edit.
That small difference does not establish a model ranking. Final median generation times were
80.41 seconds for Sol and 60.35 seconds for Opus, including setup and both requests. These are
familiar development inputs with one execution per combination, not a reliability estimate.

All 40 completed sessions matched their frozen requests, selected runtime and captured final output.
Selection preserved draft text, no format repair was needed, and captured tools only updated the
generation task's own progress. Normal cleanup was recorded in the local sandbox ledger.
Two earlier startup interruptions returned no rubric; their failed attempts and cleanup remain
recorded separately. No independent provider cleanup query is claimed.

The public analytics example was rendered in the current editor with replayed API responses and
unedited Sol output. This checks the displayed result, not a fresh browser-to-backend generation.
Private source context, transcripts, outputs and detailed reviews remain outside version control.

### Additional Sol checks

After selecting Sol/high, two additional scouts used the same writing instructions: one without
history and one with five saved run summaries. Fresh prompts came from the local copies, and the
runtime came from the product resolver. Both outputs preserved the source rules and retained all
five suggestions. The saved-history output was clear as returned. The no-history output needed one
small wording edit to a report-related title and description. Neither output was manually rewritten.

Across these six final-prompt Sol cases, five were rated Clear and one needed a small wording edit.
These remain supervised drafts, not guaranteed polished text for every scout. The reviewer recommended
keeping the prompt and Sol/high without another revision for that isolated wording issue.

One local collection-script error interrupted the saved-history attempt after its initial draft;
the failed attempt was retained and repeated with the same prompt and runtime. Two extra sandbox
allocations created during startup were cleaned through the existing worker. All three attempts are
terminal and all five sandbox ledger records are closed. Captured requests, selected text and runtime
matched the frozen inputs; no format correction was needed. The local scout configs stayed disabled,
non-emitting and unchanged. This checks the sandbox flow, not another browser-triggered generation.

## Expanded editor readability recheck

The owner rejected the expanded analytics screenshot. Its provenance confirmed that it already used
Sol/high and the retained prompt. Earlier Clear grades had overlooked dense passing conditions and
applicability text. Those original grades remain above as history, not evidence that the text met
the owner's standard.

Ten prompt revisions ran on the same public analytics scout without history and a copied feedback
scout with five run summaries: twenty further generations, all Sol/high. One separate reviewer checked
source meaning and every visible field, including the selection-generated summary. The execution
owner also reviewed wording. These were familiar development cases, with no model or prompt blinding.

| Revision                               | Analytics without runs                                               | Feedback with runs                                |
| -------------------------------------- | -------------------------------------------------------------------- | ------------------------------------------------- |
| Explain passing conditions             | Incorrect scoring restriction; dense text                            | Source rules preserved; dense text                |
| Shorten procedures                     | Same restriction; still dense                                        | Incomplete unused-stream condition; still dense   |
| State result, then source rules        | Source rules preserved; awkward terms                                | Source rules preserved; wording edits needed      |
| Describe source rules                  | Primary check lacks report delivery; technical lists                 | Source rules preserved; technical lists           |
| Short references and explicit delivery | Source rules preserved; wording edits needed                         | Source rules preserved; wording edits needed      |
| Concrete field guidance                | Source rules preserved; technical wording remains                    | Source rules preserved; technical wording remains |
| Owner questions                        | Incorrectly restricts regressions to falling metrics; wording issues | Source rules preserved; wording issues            |
| Plain main guidance                    | Primary work and delivery split; wording issues                      | Primary work and delivery split; wording issues   |
| Plain result example                   | Same split; one wording edit                                         | Same split; wording edits needed                  |
| Writing guidance after the source      | Ready and Clear; 5/5 retained                                        | Ready and Clear; 6/6 retained                     |

The fifth revision was initially retained, but both outputs still needed wording edits. That did not
meet the readability requirement. Later reviews included the summary and every editor field instead
of treating readable titles as sufficient. For the eighth and ninth revisions, the complete sets
covered investigation and reporting separately. Their content rejection concerned the declared
requirement that the primary check cover both when selected alone; it was not absence of reporting
coverage from the full set.

The tenth revision rewrites the main instructions in plain language and places concrete writing
guidance plus a short fictional example after the source and schema. It asks for useful results,
plain references to complete source rules and explicit comparison quantities. The selection step
also writes a short explanation for the owner. Model, effort, schemas and the two generation steps
remain unchanged; selection still copies whole draft criteria exactly.

Four additional sources then used that unchanged tenth revision: docs freshness without history,
flag cleanup with five summaries, API quality with five summaries, and a description-only export
scout. All six outputs were Ready for content, retaining 29/29 suggestions. Five were Clear for
readability. The docs output needed one bounded wording edit because a sentence mixed reviewing
documents with comparing code against documentation. Both reviewers of that sentence agreed it
needed correction. No generated output was manually repaired.

All twenty-four calls completed with the expected requests and Sol/high configuration. Selection
preserved the draft text, no format correction was needed, and sandbox sessions closed in the local
ledger. Captured tools only updated the generation task's own progress. Local configs stayed disabled,
non-emitting and unchanged. The existing rubric backend suite passed at the tenth revision.

The tenth revision's public analytics list and all five expanded criteria were rendered and inspected,
with exact-text assertions and no browser errors. Storybook replayed API responses; this was not
another browser-triggered backend generation. Private context, outputs, original reviews and rejected
screenshots remain outside version control. The earlier broad content matrix has not been repeated
for these writing changes.

A further six-case repeat added guidance on separate actions and clear comparisons. All six outputs
were Ready on content, retaining 30/30 suggestions. Three were Clear on readability; three each
needed one wording edit. The remaining problems were vague saved-data language, the same mixed
comparison, and a compressed negative sentence. The original reviews and outputs remain separate.
The twelfth revision permits up to three short complete sentences, removes the soft numerical word
target, and asks for literal descriptions of saved information. It retains the meaning and coverage
rules and the same runtime.

All six twelfth-revision outputs were Clear on readability. Four were Ready for content and two
needed small corrections. One required fresh evidence for every report update, including corrections.
The description-only scout treated using an existing finding as a requirement to edit it. The other
checks retained the source rules, and no core check was missing. A fresh independent reviewer read
the frozen sources before reviewing every output; original reviews remain separate from this report.
All six sessions completed and closed, the request and selection audits passed, and configs stayed
unchanged. No generated output was manually repaired.

The thirteenth revision adds two general writing instructions: preserve action meanings, and do not
apply requirements for one kind of report or update to every kind. The instructions contain no
scout-specific exceptions. All six outputs were Clear for readability. Original content grades were
four Ready and two Small. A separate source-based adjudication accepted one initially rejected
criterion: its contrast between updating and duplicating a report describes a reporting choice,
without explicitly forbidding an allowed skip. That judging correction is not a generator improvement.
The remaining docs criterion incorrectly required a stale claim even for a missing-page report.
The final content grades were five Ready and one Small, with no missing core checks. All six sessions
closed and passed the request, runtime, selection and config audits. The backend suite passed.

The thirteenth revision's public example was also rendered without text edits. The list and all five
editors passed exact-text assertions and visual inspection. Those screenshots remain private because
the twelve-case confirmation uses a later prompt.

The fourteenth revision keeps the same model and generation steps. Its final writing instructions
leave detailed report contents and other complex requirements in the full source rules instead of
reproducing partial lists. The fixed confirmation has twelve cases: all ten copied scouts, the public
analytics example, and the description-only export case. Six have five run summaries and six have
none. Six cases were used during writing revisions; six additional copied sources appeared in earlier
content tests. This is broader confirmation, not an untouched holdout. Every output was reviewed;
the earlier thirteenth-revision breadth plan was never launched.

The first two fourteenth-revision attempts failed before generation because the local app rejected
sandbox callbacks while database migrations were pending. Both sessions closed; the other ten cases
had not started. After local migration and health checks, the same twelve cases were retried with
exactly equal source bundles, prompts and runtime settings. The failed attempts remain recorded
separately and receive no quality grades.

All twelve retried generations completed. The separate reviewer read each frozen source before
reviewing its output. The execution owner also read every visible field. Content was Ready for all
twelve; readability was Clear for eleven and Small wording edit for one. The sixty criteria included
one required wording repair and no missing core checks. All summaries were clear, and no output
needed broad rewriting. Normal domain terms were acceptable when the surrounding explanation was
concrete and understandable to the scout's owner.

The remaining feedback sentence grouped a count comparison and a timestamp check under the same
verb. It needs those actions separated and the comparison quantity named. The original judgment
remains a required repair, not an optional style preference. No generated output was edited to make
the results pass. The prompt already asks for separate actions and explicit comparison quantities;
this result shows that instruction does not guarantee perfect wording on every generation.

The retained version is suitable for an editable v0: owners still review suggestions before saving.
Further tuning to this single sentence would not establish reliable improvement without another
broader comparison. The final twelve cases span onboarding, feedback, code quality and maintenance,
issue readiness, documentation, flags, team conversations, daily summaries, analytics, and a
description-only assignment. No scout-specific prompt rules or extra generation stages were added.

The final audit verified all twelve exact request pairs, Sol/high settings, unchanged selected draft
text, and local session closure. No format repair was needed. Captured tools only updated the
generation task's own progress, and local scout configs remained disabled, non-emitting and unchanged.
The existing rubric backend suite passed with the retained prompt. The public analytics list and
all five expanded editors passed exact-text checks and visual inspection, without browser errors.
The screenshots replay those generated API responses; this was not a fresh browser-to-backend run.

This expanded-field round completed 54 generations across fourteen prompt revisions, plus the two
ungraded infrastructure failures. It is separate from the earlier 40-generation comparison and two
additional Sol checks. All intermediate outputs and original reviews remain in the private cache.
These are development results on familiar inputs, not a blind benchmark or a guarantee for every
future scout. The broader saved-rubric and run-history matrix was not repeated for the final wording.
