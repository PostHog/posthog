# Repository config: `.github/review-hog.yml`

A repository turns on automatic PostHog Review (ReviewHog) Flash reviews by committing `.github/review-hog.yml`.
Without the file, pull requests in that repository get no automatic review.
The repository must be covered by the reviewing team's GitHub App installation, which for PostHog is the org-wide installation.

The automatic trigger reads the file from the repository's **default branch**, never from the pull request's head.
The file decides who is reviewed and adds guidance to the reviewer's prompt, so a pull request cannot change those rules for its own review.
A change to the file takes effect once it merges.
An open pull request is evaluated against it on its next eligible event (a push, ready for review, a removed label, or a base branch change); open pull requests are not backfilled.
A pull request whose head lives in a fork is never reviewed automatically.

The file decides _whether_ a pull request is reviewed and with what budget.
The review perspectives, the validator, the blind-spot check, and the severity threshold stay with each author's own settings in the Code review scene.

## Every option, with its default

```yaml
# Turn the file off without deleting it.
enabled: true

# Who is reviewed. Every author must map to a PostHog user on the reviewing team.
#   opted_in: only authors who turned on "Review all your PRs in Flash mode".
#   members:  every author, no per-user opt-in needed.
authors: opted_in

# Review draft pull requests. With false, the first review runs when the pull request is marked ready for review.
drafts: true

# Start a new review on every push to an open pull request, not only when it opens.
pushes: true

# fnmatch patterns the pull request's base branch must match.
base_branches: ['*']

# A pull request carrying any of these labels is skipped. Label names are compared without regard to case.
skip_labels: ['no-reviewhog']

# Patterns on the author's GitHub login, compared without regard to case. `*` and `?` are wildcards
# and brackets are literal, so `*[bot]` matches every GitHub App bot.
ignore_authors: []

flash:
  # medium | xhigh. null lets each author's own Flash strength setting apply.
  effort: null

# Repository-wide guidance rendered into every review perspective's prompt. At most 4,000 characters.
instructions: ''
```

Unknown keys make the file invalid.
An empty file is valid and means every default above.
A key with no value means that key's default.

## What happens when the file is wrong

An invalid file (not UTF-8, not YAML, not a mapping, a repeated key, an unknown key, a bad value) skips the review and records a `config_invalid` outcome on the `posthog_review_hog_authored_pr_review_total` counter, with the reason in the worker log.
The file is validated by `products/review_hog/backend/repository_config.py`; run its tests to check a change locally.

## A minimal file

```yaml
authors: members
skip_labels: ['no-reviewhog']
```

Every pull request from a team member in that repository is then reviewed, except those labeled `no-reviewhog`.
