# Judging rubric: did ReviewHog find the incident-causing bug?

You are judging ONE incident. ReviewHog (an automated PR reviewer) reviewed a resurrected copy of the PR
that caused a real production incident. Decide whether any ReviewHog finding identifies the bug that
caused the incident. Be adversarial with yourself: topic proximity is NOT a hit.

## Inputs

1. Incident ground truth: `<scratch>/incidents/<INC>.json`. Fields that define THE bug:
   `detailed_bug_cause`, `generated_cause`, `code_file`, `code_hunk`, `code_diff_excerpt`, `title`,
   `short_description`. `attribution_evidence` / `detailed_bug_cause` may name the FIX PR
   (e.g. "Attribution detail: <url>" or "Reverts #NNN"). The fix PR is the strongest statement of what
   was wrong: read it with `gh pr view <url> --json title,body` and `gh pr diff <url>` (pipe through
   `head -600` if large). If `alternative_attributed_prs` is set, the attribution is weaker: note it.
   This file contains internal data (customers, money, Slack). Never copy it into anything public;
   your output is internal.
2. The ReviewHog review. If `<scratch>/reviews/<INC>.json` exists, read it from disk (it is the same
   payload). Otherwise fetch it: load the MCP tool with
   ToolSearch `select:mcp__plugin_posthog_posthog__exec`, then
   `call --json review-hog-reviews-get {"id": "<report_id>"}`. If the result is too large the tool
   persists it to a file and prints the path; parse that file with python (`json.load` — if the file is
   a JSON array with a `text` field, `json.loads(arr[0]['text'])`). Save the parsed review to
   `<scratch>/reviews/<INC>.json` so later checks can verify your quotes.
   Review shape: `findings` = validated (each has `title`, `file`, `lines`, `body`, `suggestion`,
   `effective_priority` in must_fix|should_fix|consider, `reviewer_priority`, `validator_note`);
   `dismissed_findings` = the validator dropped them (same shape, `validator_note` says why);
   `report_markdown` = what was posted to the PR.
3. The reviewed diff: `gh pr diff <resurrected_pr_url>` (same diff as the original PR). Use it to
   check whether a finding's code path is the incident's code path. `gh pr view <url> --json title,body`
   gives the PR text.

## Two verdicts

- **published verdict**: consider ONLY findings with `effective_priority` must_fix or should_fix
  (these are the ones a human saw on the PR; `consider` findings are not posted).
- **funnel verdict**: consider ALL findings (any priority) plus `dismissed_findings`.
  If the funnel verdict beats the published one, record who lost it:
  `validator_dismissed` (the match is in dismissed_findings) or `priority_too_low` (the match is a
  validated finding at `consider`). Note that the validator may have DOWNGRADED a finding
  (`reviewer_priority` higher than `effective_priority`); a reviewer must_fix that ends at consider
  is a validator loss of the `priority_too_low` kind, say so in notes.

## Verdict scale

- **hit**: a finding identifies the same root cause on the same code path. The MECHANISM must be
  named (what goes wrong and why), not just the file or the area. If a human had acted on the
  finding's suggestion, the incident would not have happened.
- **partial**: a finding flags the dangerous area, the symptom, or a precondition of the bug without
  the mechanism, in a way that a reasonable human reviewer would likely have dug into and then found
  the real bug. Acting on the suggestion alone would NOT necessarily have prevented the incident.
- **miss**: nothing relevant. Findings on the same file about a different mechanism are a miss.

Tests for a hit, all must hold: same code path (same function/config key/query, or the direct caller
of it) AND same failure mechanism AND the consequence named is the incident's consequence or its
direct precursor. If any test fails, at most partial. If the only overlap is the file, the feature,
or a general theme ("this is unbounded", "this could time out"), it is a miss.

For each candidate match, write the strongest counter-argument BEFORE deciding. Prefer miss over
partial and partial over hit when in doubt.

## Memorization check (mandatory)

The reviewer is an off-the-shelf LLM; these PRs and their fixes are public and the sandbox clones
the current repo, so the later fix sits in git history. For every match (and every near-miss), check:
- does the finding text or validator_note mirror the fix PR's title/body/commit wording?
- does the validator_note cite `master`, `origin/master`, "the team eventually adopted", "later
  fixed", a specific later migration/file that only exists after the fix? (This means it looked at
  the future.)
Report `memorization_suspicion`: none | possible | likely, with the evidence. A finding that was
derived from the future is still recorded with its verdict, but flagged.

## Output

Return the structured object the harness asks for. Quotes must be VERBATIM substrings of the review
JSON (title or body or validator_note) so they can be verified mechanically. Keep `public_safe_bug_summary`
to one sentence that uses only facts visible in the public PR/fix PR (title-level: what the change did
and what broke), no customer names, money, user counts, incident title/description, or Slack content.
For repos PostHog/charts and PostHog/posthog-cloud-infra, set `public_safe_bug_summary` to "" (private repo).
