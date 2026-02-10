# PR Weekly Summary Tool

Automated tool for generating weekly PR summaries for GitHub teams.

## 🚀 Quick Start (PostHog Support Team)

If you're a member of the PostHog support team, use these simple commands:

```bash
# 1. Setup (first time only)
./scripts/setup_support_team.sh

# 2. Generate weekly summary
./scripts/support_team_weekly_summary.sh

# 3. Generate markdown report
./scripts/support_team_weekly_summary.sh --format markdown --output weekly_summary.md
```

**That's it!** See [SUPPORT_TEAM_GUIDE.md](./SUPPORT_TEAM_GUIDE.md) for more details.

## 📁 Files Overview

### Main Scripts

- **`pr_weekly_summary.py`** - Core Python script that generates PR summaries
- **`support_team_weekly_summary.sh`** - Convenience wrapper for PostHog support team
- **`setup_support_team.sh`** - One-time setup script for support team
- **`get_team_members.sh`** - Helper to fetch team members from GitHub

### Configuration Files

- **`posthog_team_support_members.txt`** - Team member usernames for team-support
- **`example_team_members.txt`** - Example/template file

### Documentation

- **`SUPPORT_TEAM_GUIDE.md`** - Complete guide for PostHog support team
- **`PR_SUMMARY_README.md`** - Full documentation for the tool
- **`example_output.md`** - Sample output showing what reports look like
- **`README_PR_SUMMARY.md`** - This file

## 🎯 Features

- **Multiple Output Formats**: Text, Markdown, JSON
- **Flexible Time Ranges**: 7 days (default), 14 days, 30 days, or custom
- **Comprehensive Tracking**:
  - PRs authored by each team member
  - PRs merged
  - PRs still open
  - PRs closed without merging
- **Detailed Metrics**:
  - Line changes (+/-)
  - Repository names
  - Dates (created/merged)
  - Direct PR links
- **Easy Integration**: GitHub Actions, cron jobs, Slack notifications

## 📊 Output Examples

### Text Format (Terminal)

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
```

### Markdown Format

Perfect for posting in Slack, GitHub issues, or team documentation.

See [example_output.md](./example_output.md) for a complete example.

### JSON Format

Machine-readable format for data analysis and integration with other tools.

## 🔧 Usage

### For PostHog Support Team

```bash
# Simple weekly summary
./scripts/support_team_weekly_summary.sh

# Last 14 days
./scripts/support_team_weekly_summary.sh --days 14

# Save as markdown
./scripts/support_team_weekly_summary.sh --format markdown --output report.md
```

### For Other Teams/Organizations

```bash
# Create a team members file
cat > my_team.txt << 'EOF'
username1
username2
username3
EOF

# Generate summary
python3 scripts/pr_weekly_summary.py \
  --team-members-file my_team.txt \
  --org YourOrg \
  --days 7
```

## 📝 Common Use Cases

### Weekly Team Meetings

```bash
./scripts/support_team_weekly_summary.sh --format markdown > weekly_report.md
# Share weekly_report.md in your team meeting
```

### Monthly Reviews

```bash
./scripts/support_team_weekly_summary.sh --days 30 --format markdown --output monthly_report.md
```

### Performance Tracking

```bash
./scripts/support_team_weekly_summary.sh --format json > data.json
# Process data.json with your analytics tools
```

### Automated Reports (GitHub Actions)

See [SUPPORT_TEAM_GUIDE.md](./SUPPORT_TEAM_GUIDE.md#weekly-github-action) for GitHub Actions workflow example.

## 🛠️ Requirements

- Python 3.7+
- GitHub CLI (`gh`) installed and authenticated
- Access to the GitHub organization/repositories

## 📚 Documentation

- **Quick Start**: This file (you are here)
- **Support Team Guide**: [SUPPORT_TEAM_GUIDE.md](./SUPPORT_TEAM_GUIDE.md)
- **Full Documentation**: [PR_SUMMARY_README.md](./PR_SUMMARY_README.md)
- **Example Output**: [example_output.md](./example_output.md)

## 🤝 Contributing

To add features or fix bugs, edit `pr_weekly_summary.py` and test with:

```bash
python3 scripts/pr_weekly_summary.py --team-members user1,user2 --days 7
```

## ❓ Troubleshooting

### No PRs Found

- Check that usernames in the team file are correct
- Verify the date range is appropriate
- Ensure `gh` is authenticated: `gh auth status`

### Permission Errors

- You need read access to the organization's repositories
- Team member listing requires team admin permissions (or manual entry)

### Script Not Found

Make sure you're running from the repository root:

```bash
cd /path/to/posthog
./scripts/support_team_weekly_summary.sh
```

For more help, see [PR_SUMMARY_README.md](./PR_SUMMARY_README.md#troubleshooting)

## 📄 License

Part of the PostHog project.
