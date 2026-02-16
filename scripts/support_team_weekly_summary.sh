#!/bin/bash
# Quick wrapper to generate PR summary for PostHog Support Team
# Usage: ./scripts/support_team_weekly_summary.sh [options]
#
# Options:
#   --days N       Look back N days (default: 7)
#   --format FMT   Output format: text, markdown, json (default: text)
#   --output FILE  Save output to file instead of stdout

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEAM_FILE="$SCRIPT_DIR/posthog_team_support_members.txt"

# Check if team members file exists and has members
if [ ! -f "$TEAM_FILE" ]; then
    echo "❌ Team members file not found: $TEAM_FILE"
    echo ""
    echo "Please run the setup script first:"
    echo "  ./scripts/setup_support_team.sh"
    exit 1
fi

# Check if file has any non-comment lines
if ! grep -v "^#" "$TEAM_FILE" | grep -q "[^[:space:]]"; then
    echo "❌ Team members file is empty: $TEAM_FILE"
    echo ""
    echo "Please add team member usernames to: $TEAM_FILE"
    echo "Or run the setup script:"
    echo "  ./scripts/setup_support_team.sh"
    exit 1
fi

# Run the PR summary script with the team file
python3 "$SCRIPT_DIR/pr_weekly_summary.py" \
    --team-members-file "$TEAM_FILE" \
    "$@"
