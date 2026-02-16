# PR Weekly Summary Tool

Generate weekly summaries of PRs authored and merged by team members.

## Prerequisites

- GitHub CLI (`gh`) installed and authenticated
- Python 3.7+

## Quick Start

### 1. Get Team Members

First, you need a list of GitHub usernames for your team. You can get this in several ways:

#### Option A: Use the helper script (if you have team access)

```bash
./scripts/get_team_members.sh PostHog team-support > team_members.txt
```

#### Option B: Manually create a file

Create a text file with one username per line:

```bash
cat > team_members.txt << 'EOF'
user1
user2
user3
EOF
```

#### Option C: Use the GitHub web interface

1. Visit your team page: `https://github.com/orgs/PostHog/teams/team-support`
2. Copy the usernames of all members
3. Create a file with one username per line

### 2. Generate the PR Summary

#### Using a file with team members:

```bash
python scripts/pr_weekly_summary.py --team-members-file team_members.txt
```

#### Using a comma-separated list:

```bash
python scripts/pr_weekly_summary.py --team-members alice,bob,charlie
```

#### Generate for the last 14 days:

```bash
python scripts/pr_weekly_summary.py --team-members-file team_members.txt --days 14
```

#### Output to markdown file:

```bash
python scripts/pr_weekly_summary.py \
  --team-members-file team_members.txt \
  --format markdown \
  --output weekly_summary.md
```

#### For a different organization:

```bash
python scripts/pr_weekly_summary.py \
  --team-members alice,bob \
  --org MyOrg \
  --days 7
```

## Output Formats

### Text (default)

Human-readable console output with emojis and formatting.

```bash
python scripts/pr_weekly_summary.py --team-members-file team_members.txt
```

### Markdown

Great for posting in GitHub issues, wiki pages, or Slack.

```bash
python scripts/pr_weekly_summary.py --team-members-file team_members.txt --format markdown
```

### JSON

Machine-readable format for further processing.

```bash
python scripts/pr_weekly_summary.py --team-members-file team_members.txt --format json
```

## Example Output

```text
================================================================================
📊 WEEKLY PR SUMMARY
Period: Last 7 days (since 2026-02-03)
Generated: 2026-02-10T10:30:00
================================================================================

📈 TEAM OVERVIEW
  Total PRs Authored: 15
  Total PRs Merged: 12
  Total PRs Open: 3
  Team Members: 5

────────────────────────────────────────────────────────────────────────────────
👤 alice
────────────────────────────────────────────────────────────────────────────────
  📝 Authored: 4 PRs
  ✅ Merged: 3 PRs
  🔄 Open: 1 PR
  ❌ Closed (not merged): 0 PRs

  ✅ Merged PRs:
    • #1234 - Fix authentication bug
      Repo: posthog | +45 -23 lines | Merged: 2026-02-09 14:30
      https://github.com/PostHog/posthog/pull/1234
```

## Automation

### Weekly Cron Job

Add to your crontab to generate weekly reports:

```bash
# Every Monday at 9 AM
0 9 * * 1 cd /path/to/repo && python scripts/pr_weekly_summary.py --team-members-file team_members.txt --format markdown --output weekly_summary_$(date +\%Y-\%m-\%d).md
```

### GitHub Actions

Create `.github/workflows/weekly-pr-summary.yml`:

```yaml
name: Weekly PR Summary

on:
  schedule:
    - cron: '0 9 * * 1' # Every Monday at 9 AM UTC
  workflow_dispatch: # Allow manual trigger

jobs:
  generate-summary:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v3

      - name: Set up Python
        uses: actions/setup-python@v4
        with:
          python-version: '3.10'

      - name: Generate PR Summary
        env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          python scripts/pr_weekly_summary.py \
            --team-members-file team_members.txt \
            --format markdown \
            --output weekly_summary.md

      - name: Create Issue with Summary
        uses: peter-evans/create-issue-from-file@v4
        with:
          title: Weekly PR Summary - ${{ github.run_id }}
          content-filepath: weekly_summary.md
          labels: report, automated
```

## Troubleshooting

### "gh: command not found"

Install the GitHub CLI:

- macOS: `brew install gh`
- Linux: See https://github.com/cli/cli/blob/trunk/docs/install_linux.md
- Windows: See https://github.com/cli/cli#installation

### "gh: Not authenticated"

Authenticate with GitHub:

```bash
gh auth login
```

### "Not Found" errors when fetching team members

This usually means you don't have permission to view the team members. Try:

1. Manually creating a list of team members
2. Asking a team admin to run the script
3. Using a GitHub token with `read:org` scope

### Rate limiting

If you have a large team, you might hit GitHub API rate limits. Consider:

- Using a GitHub token with higher rate limits
- Reducing the number of days with `--days`
- Running the script less frequently

## Advanced Usage

### Filter by specific repositories

Modify the search query in the script to filter by repository:

```python
search_query = f"type:pr author:{username} org:{org} repo:{org}/posthog created:>={since_date}"
```

### Include PR reviews

The script can be extended to show PRs reviewed by team members. Add to `get_prs_for_user`:

```python
# Search for PRs reviewed by the user
search_query = f"type:pr reviewed-by:{username} org:{org} created:>={since_date}"
```

### Export to CSV

Add CSV format support for importing into spreadsheets or data analysis tools.

## Support

For issues or feature requests, please create an issue in the repository.
