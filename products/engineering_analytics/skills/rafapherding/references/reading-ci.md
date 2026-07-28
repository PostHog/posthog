# Reading a red PR

The goal of this pass is a short list: which failures are yours. Everything else you note and move
past. Getting this wrong in either direction is expensive — chasing an infra flake wastes a night,
and dismissing a real failure as flaky ships a bug.

## Get the failures

`gh pr checks <n>` prints every check including hundreds of skipped ones. Filter:

```sh
gh pr checks <n> | grep -E "\bfail\b"
gh pr checks <n> | grep -E "\bpending\b"    # still running, revisit later
```

A PR with no `fail` and no `pending` lines is green regardless of what the Graphite UI shows.

## The taxonomy

### Runner starvation (not yours)

```sh
gh api repos/PostHog/posthog/actions/jobs/<job-id> --jq '{name, conclusion, steps: (.steps|length), started_at, completed_at}'
```

`steps: 0`, and `completed_at - started_at` exactly equal to the job's `timeout-minutes`. The job
was queued, never got a runner, and was killed by its own timeout. `gh run view --job <id>
--log-failed` returns `log not found`, which is itself a tell — there are no logs because nothing
ran.

Several unrelated jobs in one workflow run sharing the same zero-step timeout means the whole run
hit a bad capacity window. Push and they will schedule normally.

### Aggregation gates (not the real failure)

Jobs named `<Something> Tests Pass`, `<Something> Checks Pass`, `Check matrix outcome`, `Check
dependency results`. They fail in seconds with a step that just reads its dependencies' results.
They tell you a matrix leg failed; they never tell you which or why. Find the matrix leg.

### Superseded runs (not yours either)

A push cancels the run already in flight for that branch, and every aggregation gate then reports its
CANCELLED dependencies as FAILURE. So a wall of `Tests Pass` failures appearing right after you push
means _superseded_, not broken. Check the state breakdown before reading anything:

```sh
gh pr checks <n> --json name,state --jq 'group_by(.state)[] | "\(.[0].state): \(length)"'
```

A large `CANCELLED` count next to `IN_PROGRESS` is the signature. The gates will be replaced as the
new run's legs finish. This is worth filtering out of any CI monitor you set up, or it will wake you
for every push you make:

```sh
# Real failures only: drop the gates, which carry nothing the underlying job doesn't
gh pr checks <n> --json name,state --jq '.[] | select(.state=="FAILURE")
  | select(.name | test("Tests Pass|tests pass|CI Pass|Checks Pass|does not block merge") | not) | .name'
```

### Real failures

The job has steps, ran for a plausible duration, and `--log-failed` returns content.

```sh
gh run view --job <id> --log-failed | grep -E "FAILED|^E |AssertionError|Error:" | head -30
```

The GitHub Actions log format prefixes every line with the job name and a timestamp, so grep for
the assertion rather than reading linearly. For pytest, `FAILED <nodeid>` lines at the end are the
summary; the `E` lines above them are the actual assertion.

### Semgrep

`semgrep-python` failing with `Ran N rules on M files: 1 finding` is a real finding. Extract it:

```sh
gh run view --job <id> --log | grep -A 4 "Code Finding"
```

Judge it like any other bot finding. A security rule firing on a **test** that deliberately
constructs the unsafe thing in order to assert it is rejected is a false positive — suppress it at
the line with the rule id and a reason, per the repo's nosemgrep convention:

```python
# nosemgrep: python.jwt.security.jwt-none-alg.jwt-python-none-alg (forging an alg=none token is the point: this asserts the verifier refuses it)
```

Never suppress by disabling the rule globally, and never suppress a finding in production code you
have not traced.

### Migration validation

`Validate migrations` failing after your branch has sat for a day is almost always the number
collision: master took the migration number you claimed. This surfaces as a `max_migration.txt`
conflict during restack, not usually as a standalone CI failure — if CI reports it directly, restack
first and it resolves.

### The CI report comment

The bot posts a `## 🤖 CI report` comment with sections for Playwright flakes and backend patch
coverage. Flaky specs listed there are explicitly annotated "not necessarily caused by your
changes" — treat them as informational unless your diff touches that area. Patch coverage is
advisory: it names uncovered changed lines. Worth a look when you are already adding a test, not
worth chasing to a number.

### stamphog REFUSED

Not a CI failure. It means the automated reviewer declined to review — usually because the diff is
too large for its ceiling or matches a deny-list (auth-sensitive code). It also surfaces unresolved
findings from other bots, which is useful as a checklist. A REFUSED verdict does not block merge and
is not something to "fix"; resolve the findings it cites.

## What to re-run vs. what to fix

You do not need `gh run rerun`. Pushing the stack re-triggers everything, and you will be pushing
anyway. Only re-run explicitly when a PR is otherwise finished and its sole red check is a confirmed
infra timeout.
