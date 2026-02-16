# Example PR Weekly Summary Output

This is an example of what the PR weekly summary tool generates.

## Command

```bash
python3 scripts/pr_weekly_summary.py --team-members-file team_members.txt --format markdown
```

## Sample Output

# 📊 Weekly PR Summary

**Period:** Last 7 days (since 2024-02-03)  
**Generated:** 2024-02-10T10:30:00

## 📈 Team Overview

- **Total PRs Authored:** 18
- **Total PRs Merged:** 14
- **Total PRs Open:** 4
- **Team Members:** 3

## 👤 alice

- **Authored:** 7 PRs
- **Merged:** 6 PRs
- **Open:** 1 PR
- **Closed (not merged):** 0 PRs

### ✅ Merged PRs

- [#5432 - Fix authentication timeout issue](https://github.com/PostHog/posthog/pull/5432)
  - **Repo:** posthog
  - **Changes:** +125 -45 lines
  - **Merged:** 2024-02-09 14:30

- [#5421 - Update user settings page layout](https://github.com/PostHog/posthog/pull/5421)
  - **Repo:** posthog
  - **Changes:** +234 -156 lines
  - **Merged:** 2024-02-08 11:15

- [#5418 - Add rate limiting to API endpoints](https://github.com/PostHog/posthog/pull/5418)
  - **Repo:** posthog
  - **Changes:** +89 -12 lines
  - **Merged:** 2024-02-07 16:45

- [#5410 - Fix mobile responsive layout issues](https://github.com/PostHog/posthog/pull/5410)
  - **Repo:** posthog
  - **Changes:** +67 -34 lines
  - **Merged:** 2024-02-06 09:20

- [#156 - Update Python SDK documentation](https://github.com/PostHog/posthog-python/pull/156)
  - **Repo:** posthog-python
  - **Changes:** +45 -12 lines
  - **Merged:** 2024-02-05 14:00

- [#155 - Add retry logic for failed requests](https://github.com/PostHog/posthog-python/pull/155)
  - **Repo:** posthog-python
  - **Changes:** +112 -23 lines
  - **Merged:** 2024-02-04 10:30

### 🔄 Open PRs

- [#5445 - Implement new dashboard widget](https://github.com/PostHog/posthog/pull/5445)
  - **Repo:** posthog
  - **Changes:** +456 -89 lines
  - **Created:** 2024-02-09 17:00

## 👤 bob

- **Authored:** 6 PRs
- **Merged:** 5 PRs
- **Open:** 1 PR
- **Closed (not merged):** 0 PRs

### ✅ Merged PRs

- [#5438 - Optimize database query performance](https://github.com/PostHog/posthog/pull/5438)
  - **Repo:** posthog
  - **Changes:** +78 -145 lines
  - **Merged:** 2024-02-09 13:45

- [#5429 - Add caching layer for feature flags](https://github.com/PostHog/posthog/pull/5429)
  - **Repo:** posthog
  - **Changes:** +234 -67 lines
  - **Merged:** 2024-02-08 15:20

- [#5425 - Fix memory leak in event processing](https://github.com/PostHog/posthog/pull/5425)
  - **Repo:** posthog
  - **Changes:** +45 -89 lines
  - **Merged:** 2024-02-07 12:00

- [#5415 - Update dependencies to latest versions](https://github.com/PostHog/posthog/pull/5415)
  - **Repo:** posthog
  - **Changes:** +12 -12 lines
  - **Merged:** 2024-02-06 10:15

- [#234 - Add TypeScript types for new events](https://github.com/PostHog/posthog-js/pull/234)
  - **Repo:** posthog-js
  - **Changes:** +156 -34 lines
  - **Merged:** 2024-02-05 16:30

### 🔄 Open PRs

- [#5441 - Refactor event ingestion pipeline](https://github.com/PostHog/posthog/pull/5441)
  - **Repo:** posthog
  - **Changes:** +567 -234 lines
  - **Created:** 2024-02-09 11:00

## 👤 charlie

- **Authored:** 5 PRs
- **Merged:** 3 PRs
- **Open:** 2 PRs
- **Closed (not merged):** 0 PRs

### ✅ Merged PRs

- [#5435 - Add support for custom properties](https://github.com/PostHog/posthog/pull/5435)
  - **Repo:** posthog
  - **Changes:** +123 -45 lines
  - **Merged:** 2024-02-09 10:00

- [#5422 - Fix timezone handling in reports](https://github.com/PostHog/posthog/pull/5422)
  - **Repo:** posthog
  - **Changes:** +67 -34 lines
  - **Merged:** 2024-02-07 14:30

- [#5412 - Update error messages for better UX](https://github.com/PostHog/posthog/pull/5412)
  - **Repo:** posthog
  - **Changes:** +45 -23 lines
  - **Merged:** 2024-02-05 11:45

### 🔄 Open PRs

- [#5448 - Implement new billing system](https://github.com/PostHog/posthog/pull/5448)
  - **Repo:** posthog
  - **Changes:** +789 -234 lines
  - **Created:** 2024-02-09 18:30

- [#5443 - Add A/B testing feature](https://github.com/PostHog/posthog/pull/5443)
  - **Repo:** posthog
  - **Changes:** +456 -123 lines
  - **Created:** 2024-02-08 16:00

---

## Text Format Output

When using `--format text`, the output looks like this in the terminal:

```text
================================================================================
📊 WEEKLY PR SUMMARY
Period: Last 7 days (since 2024-02-03)
Generated: 2024-02-10T10:30:00
================================================================================

📈 TEAM OVERVIEW
  Total PRs Authored: 18
  Total PRs Merged: 14
  Total PRs Open: 4
  Team Members: 3

────────────────────────────────────────────────────────────────────────────────
👤 alice
────────────────────────────────────────────────────────────────────────────────
  📝 Authored: 7 PRs
  ✅ Merged: 6 PRs
  🔄 Open: 1 PR
  ❌ Closed (not merged): 0 PRs

  ✅ Merged PRs:
    • #5432 - Fix authentication timeout issue
      Repo: posthog | +125 -45 lines | Merged: 2024-02-09 14:30
      https://github.com/PostHog/posthog/pull/5432

    • #5421 - Update user settings page layout
      Repo: posthog | +234 -156 lines | Merged: 2024-02-08 11:15
      https://github.com/PostHog/posthog/pull/5421

    [... more PRs ...]

  🔄 Open PRs:
    • #5445 - Implement new dashboard widget
      Repo: posthog | +456 -89 lines | Created: 2024-02-09 17:00
      https://github.com/PostHog/posthog/pull/5445

[... more team members ...]
```
