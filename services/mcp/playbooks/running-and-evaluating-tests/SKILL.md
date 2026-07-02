# Skill — running and evaluating tests

How to write test specs, run them, read results, and self-evaluate
before promoting. Load before any non-trivial edit's promote step.

> **Status note:** the test-run endpoints
> (`agent-applications-revisions-test-run`,
> `-test-results-retrieve`, `-test-replay-retrieve`) are designed
> in `agent-authoring-flow.md` §5 but **not yet shipped**. Until
> they are, "testing" means: open a chat session against the
> ready revision yourself (as a one-off via the chat trigger),
> drive a representative input, and read the resulting session
> manually. This skill teaches the eventual flow; substitute the
> manual analog where noted.

## When to run tests

Always, before any promote on a non-trivial edit. "Non-trivial"
means anything other than:

- Pure documentation in `agent.md`
- A README change
- A typo fix in a skill

If the edit changes spec, changes which tools are available,
changes the prompt's instructions to the model, or touches a
custom tool's source — test.

## Writing a test case

Test cases live in the bundle at `tests/*.json`. One file per
case. Standard shape:

```jsonc
{
  "name": "happy path — user asks for weekly sales",
  "trigger": {
    "type": "chat",
    "messages": [{ "role": "user", "content": "What were our top 5 products last week?" }],
  },
  "expected": {
    "tool_calls_include": ["@posthog/query"],
    "tool_calls_exclude": ["@posthog/slack-post-message"],
    "assistant_text_matches": "^(Top|The top) (?:5|five)",
    "max_turns": 5,
    "must_complete_within_ms": 30000,
  },
}
```

Aim for 3-5 cases per agent:

- **Happy path** — the most common input, with the most expected
  response shape
- **One edge case** — an input the agent should handle gracefully
  (empty data, malformed input, ambiguous request)
- **One hostile / out-of-scope** — an input the agent should
  refuse or redirect (asks for raw secrets, asks something outside
  its tool surface)

Don't try to enumerate every possible input. Tests are a safety
net for regressions, not a proof of correctness.

## Assertion types

| Assertion                 | Use when                                                               |
| ------------------------- | ---------------------------------------------------------------------- |
| `tool_calls_include`      | The agent MUST call this tool to do the job                            |
| `tool_calls_exclude`      | The agent MUST NOT call this tool (e.g. don't post to slack in a test) |
| `assistant_text_matches`  | Final assistant message matches the regex                              |
| `max_turns`               | Loose efficiency check — agent shouldn't loop                          |
| `must_complete_within_ms` | Wall-clock check — agent should finish in reasonable time              |
| `final_state`             | Session ends in `completed` (not `failed`)                             |

Don't over-assert. Each assertion is a thing that can break
spuriously when the model changes provider or version. Match on
intent (a regex on the type of answer), not exact words.

## Egress is mocked in tests

The runner runs test sessions with egress sandboxed:

- `@posthog/slack-*` becomes a no-op that logs the call (so you
  can assert it was called, without actually posting)
- `@posthog/http-request` returns fixture responses from the test
  spec
- Custom tools' egress goes through a proxy that blocks non-
  fixture hosts

You can declare fixtures in the test spec:

```jsonc
{
  "fixtures": {
    "https://api.example.com/users/1": { "name": "Alice" },
  },
}
```

Secrets are still real, so the auth path is exercised — but the
egress controls mean they never reach the real provider.

## Running a test

```text
agent-applications-revisions-test-run revision_id=<rid>
  → returns { test_run_id }
```

Then poll:

```text
agent-applications-revisions-test-results-retrieve test_run_id=<id>
  → returns { cases: [ { name, passed_assertions, failed_assertions,
       conversation, tool_calls, logs, usage } ] }
```

In PostHog Code, `focus_session` to the test run as it
streams. The user wants to watch.

## Reading results

For each case:

- **All assertions passed** — green, move on.
- **One assertion failed** — read the conversation, identify
  whether it's a spec/prompt issue (likely) or a test-spec issue
  (the assertion was too strict).
- **The case errored** — same flow as the `debugging-sessions` playbook
  but against a test session.

For the assistant_text_matches failure pattern: do NOT just
loosen the regex to make it pass. The point of the assertion was
to catch a behavior change — if the change is intentional, update
the test consciously; if it's a regression, fix the prompt.

## Self-evaluation

The test passed but you're not sure the output is _good_?

The judge-skill convention (designed, not yet shipped per
`agent-authoring-flow.md` §4.3) will let you call a separate
"judge agent" that grades the test results against a rubric.
Until that lands, do it inline:

1. Read the conversation from each case
2. Score it yourself against the criteria the user named (or
   reasonable defaults: on-topic, factually grounded, no
   hallucinated tool ids, appropriate tone)
3. Surface a per-case score + the worst output verbatim

Be honest about what you can and can't judge:

> Case 1 — score 4/5. Output is on-topic and uses the right
> tools, but the formatting is rough — the agent dumped the
> raw query result as JSON instead of a table. Suggest tightening
> the formatting rule in agent.md or adding a `format-output`
> skill.
>
> Case 2 — score 5/5. Clean, correct, terse.
>
> Case 3 — score 2/5. Agent attempted to call
> `@posthog/database-write`, which doesn't exist. Likely a
> hallucination from the prompt mentioning "write the result".
> Suggest rewording.

## When the user wants to skip tests

Common: "just promote it, the change is small". See
the `editing-agents-safely` playbook — pure-cosmetic edits can skip,
anything semantic should run at least one test case.

If the user insists on skipping for a semantic edit, **note it
explicitly in your confirm-promote message**:

> Promoting without running tests. The change is to `agent.md`
> rule #2, which affects how the agent picks between tools.
> Confirm 'promote without tests' to proceed.

Make the cost of skipping visible. Don't hide it.

## Test costs

Test runs use real model calls. Cost is on the team's bill (per
`agent-authoring-flow.md` §5 mentions a separate test budget).
For a typical agent, one full test sweep is $0.05 - $1. Tell the
user the rough cost before running a large sweep.

## When tests pass but production fails

You promoted, tests passed, and the first real session still
fails. Common causes:

- Test inputs weren't representative of real inputs
- The mocked egress let through behavior the real egress
  doesn't (auth, rate limits)
- The test sandbox is more permissive than production in some
  way you didn't anticipate

Update the failing case to match the real input, add the case
that was missing, then continue the loop. This is normal — tests
catch most regressions but not all of them.
