# Support Team PR Summary Guide

Quick guide for generating weekly PR summaries for the PostHog support team.

## Quick Start (Recommended)

### Step 1: Run the Setup Script

The easiest way to get started:

```bash
./scripts/setup_support_team.sh
```

This script will:

- Check if GitHub CLI is installed and authenticated
- Attempt to automatically fetch team-support members
- Create a configured team members file
- Test the PR summary tool

If you don't have team admin permissions, it will create a template file that you need to fill in manually.

### Step 2: Add Team Members (if needed)

If the setup script couldn't fetch members automatically, edit the file:

```bash
# Visit https://github.com/orgs/PostHog/teams/team-support
# Then add usernames to:
vim scripts/posthog_team_support_members.txt
```

### Step 3: Generate Weekly Reports

Use the convenience wrapper script:

```bash
# Default: 7 days, text format
./scripts/support_team_weekly_summary.sh

# Markdown format
./scripts/support_team_weekly_summary.sh --format markdown

# Last 14 days, save to file
./scripts/support_team_weekly_summary.sh --days 14 --format markdown --output weekly_summary.md
```

## Alternative: Manual Setup

If you prefer to do it manually:

### Step 1: Create Team Members File

```bash
cat > scripts/posthog_team_support_members.txt << 'EOF'
# PostHog Support Team Members
# Visit https://github.com/orgs/PostHog/teams/team-support for current members
# Add GitHub usernames (one per line)

# Add team member usernames below:

EOF
```

Visit [https://github.com/orgs/PostHog/teams/team-support](https://github.com/orgs/PostHog/teams/team-support) and add the usernames to the file.

### Step 2: Generate Reports

For text output (terminal):

```bash
python3 scripts/pr_weekly_summary.py --team-members-file scripts/posthog_team_support_members.txt
```

For markdown output (great for posting in Slack or issues):

```bash
python3 scripts/pr_weekly_summary.py \
  --team-members-file scripts/posthog_team_support_members.txt \
  --format markdown \
  --output weekly_summary_$(date +%Y-%m-%d).md
```

For JSON output (for data analysis):

```bash
python3 scripts/pr_weekly_summary.py \
  --team-members-file scripts/posthog_team_support_members.txt \
  --format json \
  --output weekly_summary_$(date +%Y-%m-%d).json
```

## Sharing Reports

The markdown output can be:

- Posted in the weekly team meeting notes
- Shared in the team Slack channel
- Included in weekly status reports
- Archived for future reference

## Customization

### Different Time Periods

Last 14 days:

```bash
./scripts/support_team_weekly_summary.sh --days 14
```

Last 30 days (monthly report):

```bash
./scripts/support_team_weekly_summary.sh --days 30
```

### Specific Team Members

To generate a report for specific team members only:

```bash
python3 scripts/pr_weekly_summary.py \
  --team-members paolodamico,mariusandra
```

## Automation

### Weekly GitHub Action

Create `.github/workflows/support-team-weekly-summary.yml`:

```yaml
name: Support Team Weekly PR Summary

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
          ./scripts/support_team_weekly_summary.sh \
            --format markdown \
            --output weekly_summary.md

      - name: Post to Slack
        uses: slackapi/slack-github-action@v1
        with:
          channel-id: 'C0123456789' # Replace with your Slack channel ID
          slack-message: |
            Weekly PR Summary for Support Team
            $(cat weekly_summary.md)
        env:
          SLACK_BOT_TOKEN: ${{ secrets.SLACK_BOT_TOKEN }}
```

### Local Cron Job

Add to your crontab (`crontab -e`):

```bash
# Generate support team PR summary every Monday at 9 AM
0 9 * * 1 cd ~/posthog && ./scripts/support_team_weekly_summary.sh --format markdown --output ~/weekly_summary_$(date +\%Y-\%m-\%d).md
```

## Tips

1. **Keep the team members file updated**: Regularly update `scripts/posthog_team_support_members.txt` as team members join or leave. Re-run `./scripts/setup_support_team.sh` periodically if you have team admin access.
2. **Archive reports**: Save weekly reports for historical tracking
3. **Combine with other metrics**: Use the JSON output to combine with other team metrics
4. **Filter by repository**: Modify the script if you only want PRs from specific repositories
5. **Use the wrapper script**: The `support_team_weekly_summary.sh` script is the easiest way to generate reports

## Troubleshooting

If the script doesn't find any PRs, check:

1. The usernames in the team members file are correct
2. The date range is appropriate (e.g., if running on Monday morning, last 7 days might not capture Friday's work yet)
3. The GitHub CLI (`gh`) is authenticated: `gh auth status`

For more details, see [PR_SUMMARY_README.md](./PR_SUMMARY_README.md)
