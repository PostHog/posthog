---
name: rafapherding
description: >
  Shepherds a list of open PRs to green, unattended: reads review-bot comments, judges each one
  accurate or not, replies to every one, fixes what is real, and drives CI to passing. Use for
  "get these PRs green", "babysit my PRs", "handle the review bot comments", "watch CI on these
  PRs and fix what breaks", "shepherd this stack". Understands Graphite stacks and always works a
  stack bottom-up (fix base, gt restack, gt up, repeat, then gt ss once). Covers separating real
  failures from infra flakes, the migration-number conflict every restack hits, and how to reply
  to a bot you disagree with. Not for authoring a single PR from scratch, and not for aggregate CI
  health (use diagnosing-ci-and-merge-bottlenecks).
---

# Rafapherding: driving PRs to green

The job is custody, not authorship. Someone hands you a list of open PRs and goes away. You bring
each one to a state where CI is green, every review-bot comment has a reasoned reply, and every
accurate finding is fixed with a test that would have caught it. You are the last reviewer awake.

Two rules shape everything else:

1. **A bot comment is a claim, not an instruction.** Verify it against the code before you touch
   anything. Bots produce real findings, findings that are true but out of scope, and findings that
   are simply wrong. All three deserve a reply; only the first deserves a commit.
2. **Stacks are ordered.** Never fix a stacked PR in the middle. Go to the bottom, fix, restack,
   move up. A fix landed out of order gets clobbered by the next restack.

## Order of work

Group the PR list into stacks first (`gt log short`, or `gh pr view <n> --json baseRefName` — a PR
whose base is another PR's head is stacked on it). Then, per stack, bottom to top:

```sh
gt log short                    # see the whole forest and which branches need restacking
git checkout <bottom-branch>
# ... judge comments, fix, test, commit ...
gt restack                      # rebases this branch and everything above it
gt up                           # move to the next PR in the stack, repeat
gt ss                           # submit the whole stack, once, at the end
```

Push once per stack with `gt ss`, not once per branch. Every push fans out a full CI run, and
force-pushing a deep stack at once can exceed GitHub's dispatch cap and take unrelated runs down
with it. Do the whole stack's work, then submit.

Work stacks sequentially when you share one working tree. Two stacks in flight in one checkout is
how you end up committing a half-finished fix to the wrong branch.

## Triage CI before you read a single comment

Most of what looks like a broken PR is not. Classify every red check before fixing anything:

```sh
gh pr checks <n> | grep -E "\bfail\b"
```

Then, for each failing job, ask whether it actually ran:

```sh
gh api repos/PostHog/posthog/actions/jobs/<job-id> --jq '{name, conclusion, steps: (.steps|length)}'
```

- **`steps: 0` and a duration of exactly the job timeout** (10m0s, 15m0s) means the job never
  acquired a runner. That is infra, not you. Several jobs sharing the same zero-step timeout in one
  run is the signature of a bad window. Do not chase it; it clears on the next push.
- **`Something Tests Pass` / `Checks Pass` failing in seconds** is an aggregation gate. It is
  reporting a dependency's failure, not its own. Find the real job.
- **A job that ran and failed** is the only kind worth reading logs for:
  `gh run view --job <id> --log-failed`.

Migration conflicts and lint failures are always yours. Flaky Playwright specs called out in the CI
report comment usually are not.

See [references/reading-ci.md](references/reading-ci.md) for the failure taxonomy in detail.

## Judging bot comments

Fetch both kinds — inline review comments and top-level ones:

```sh
gh api repos/PostHog/posthog/pulls/<n>/comments  --jq '.[] | "\(.user.login) | \(.path):\(.line) | id=\(.id)\n\(.body)\n"'
gh api repos/PostHog/posthog/issues/<n>/comments --jq '.[] | "\(.user.login)\n\(.body)\n"'
```

For each finding, answer three questions in order, and stop at the first "no":

1. **Is the mechanism real?** Trace it in the code. Do not accept the bot's description of what a
   function does — open the function. A high-confidence score is not evidence.
2. **Is it reachable?** A real mechanism behind an unreachable path is a note, not a bug. Say so.
3. **Is it this PR's?** Check `git show master:<path>` — if the code is new in this PR, it is in
   scope even when the pattern predates it. If the PR merely moved existing code, the finding may
   be true and still belong in a follow-up.

Then act:

- **Accurate and in scope** → fix it, add a regression test, reply naming the commit.
- **Accurate but out of scope** → reply agreeing, say why it is not this PR, and be specific about
  where it should go.
- **Wrong** → reply with the evidence that makes it wrong, not just "false positive". If it is a
  linter false positive, suppress it at the line with a justified reason rather than silencing the
  rule.

Reply to the finding, in its thread, so it resolves where the reviewer left it:

```sh
gh api repos/PostHog/posthog/pulls/<n>/comments/<comment-id>/replies -f body='...'
```

A reply is worth writing even when you agree completely. The next human to open the PR needs to
know the finding was read and what happened to it. See
[references/replying-to-bots.md](references/replying-to-bots.md) for what a good reply contains and
worked examples of all three verdicts.

## Prove the fix

Every fix you land for a bot finding needs a test that fails without it. Write the test, then
verify it actually catches the bug by reverting the fix and watching it fail:

```sh
cp <file> /tmp/fix.bak
# revert the fix by hand
hogli test <test-file>::<TestClass>::<test_name>   # must FAIL
cp /tmp/fix.bak <file>
hogli test <test-file>                             # must PASS
```

A test you never saw fail is a test you do not know works. This step catches the vacuous
assertion — the one that passes because the request 401s before it reaches the code under test —
which is the single most common way a security regression test turns out to be worthless.

## Restacking

`gt restack` walks the whole stack upward and will stop on the first conflict. The one you will hit
constantly in this repo is `posthog/migrations/max_migration.txt`, because master keeps taking the
migration number your branch claimed. Do not hand-edit it:

```sh
python manage.py rebase_migration posthog   # or `ee` — renumbers and repoints dependencies
gt add posthog/migrations
gt continue
```

Then confirm no state drift before moving on: `DEBUG=1 python manage.py makemigrations --dry-run
--check` must say "No changes detected".

Renumbering a migration invalidates your local test database, which will then fail with
`DuplicateColumn: column ... already exists`. That is local-only; rebuild with
`hogli test <path> -- --create-db`. It is not a CI failure and not something to "fix" in the code.

## Changing production code breaks test seams

When you fix a finding by changing how code reaches the network — swapping `requests.get` for a
pinned session, moving a validation call — every test that patched the old seam silently stops
intercepting and starts making real calls. The symptom is a wall of failures with a message about
DNS or connection refused for a hostname like `partner.example.com`.

Retarget the patch to the new seam rather than reverting the fix. Prefer patching the narrowest
thing that still covers the path; when you must patch something process-wide (`requests.Session.get`),
expect unrelated traffic to land on the mock, and tighten raw `assert_called_once` /
`assert_not_called` assertions to filter for the call you actually mean.

## Before you call a PR done

- Every failing check is either green or classified as infra with the evidence for that.
- Every bot finding has a reply.
- Every fix has a test you watched fail.
- `ruff check --fix` / `ruff format` clean, and the pre-push `hogli ci:preflight` passes without
  `--no-verify`.
- The stack is restacked and submitted once with `gt ss`.

When something needs a decision only the author can make — whether a production partner actually
holds a credential, whether a behavior change is acceptable — do not guess. Land the code-side
safety net, say plainly in the PR reply what you could not verify, and leave it flagged.
