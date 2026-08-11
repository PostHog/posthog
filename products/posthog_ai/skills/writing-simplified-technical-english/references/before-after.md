# Before and after

Every example below is invented to show a rule.
None comes from a real report, ticket, or conversation.

## Single sentences

| Rule                 | Before                                                               | After                                                         |
| -------------------- | -------------------------------------------------------------------- | ------------------------------------------------------------- |
| One meaning per word | "Verify the flag, then confirm the rollout, then check the payload." | "Check the flag, the rollout, and the payload."               |
| Precise verb         | "Follow the retry policy."                                           | "Obey the retry policy."                                      |
| Simple tense         | "We have received 400 exceptions since Tuesday."                     | "We received 400 exceptions since Tuesday."                   |
| Active voice         | "The stale cache entry is evicted on the next write."                | "The next write evicts the stale cache entry."                |
| Noun cluster         | "the task queue priority handler config"                             | "the config that sets task-queue priority"                    |
| No missing words     | "Sessions not sampled are dropped."                                  | "The worker drops a session that the sampler did not select." |

## Tool description

Before:

> This tool will attempt to synchronize state across the various backends that have been configured, and if a conflict is detected it may resolve it automatically depending on the strategy that has been set, or otherwise it will surface the conflict for manual review.

What it breaks: two instructions in one sentence, three hedges, 55 words against a 25-word cap.

After:

> The tool syncs state across the configured backends.
> If it finds a conflict, it reads the current strategy.
> If the strategy allows automatic resolution, the tool resolves the conflict.
> If not, the tool reports the conflict for manual review.

## Error message

Before:

> An error may have occurred while processing your request due to a possible mismatch in the expected data format, which could be caused by an outdated client version.

What it breaks: passive voice with no actor, two hedges stacked, two claims in one sentence.

After:

> The request failed.
> The data format did not match what the server expected.
> Check your client version.
> An outdated client is the most common cause.

## Instruction to another agent

Before:

> Once the upstream job has completed and assuming no errors were raised, the downstream agent should proceed to consume the output artifact, though it is worth noting that partial artifacts are sometimes produced under timeout conditions.

What it breaks: present perfect, three facts in one sentence, 42 words against a 20-word cap.

After:

> Wait for the upstream job to finish with no errors.
> Then read the output artifact.
> A timeout can produce a partial artifact, so check that the artifact is complete before you use it.

## Report finding

Before:

> It appears that there may be an issue with the way in which the signup funnel is currently being instrumented, as the property that identifies the plan the user selected has not been being sent on the final step of the funnel since around the middle of last month, which means that any breakdown by plan is likely to be undercounting.

What it breaks: 62 words, three hedges, present perfect progressive, a vague date.

After:

> The signup funnel drops the plan property on its final step.
> The property stopped arriving on 12 May.
> Every breakdown by plan undercounts from that date.

## What not to simplify

Keep the longer sentence when the shorter one loses something:

- A condition: "Delete the row only after the export finishes."
- A scope qualifier: "This applies to teams on the legacy ingestion path."
- A number, a date, or a unit.

Say why you kept it, in one line, rather than dropping it.
