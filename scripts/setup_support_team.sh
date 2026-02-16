#!/bin/bash
# Setup script for PostHog Support Team PR summaries
# This script helps configure the PR summary tool for team-support

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEAM_FILE="$SCRIPT_DIR/posthog_team_support_members.txt"

echo "🔧 PostHog Support Team PR Summary Setup"
echo "=========================================="
echo ""

# Check if gh is installed
if ! command -v gh &> /dev/null; then
    echo "❌ GitHub CLI (gh) is not installed."
    echo "   Please install it first:"
    echo "   - macOS: brew install gh"
    echo "   - Linux: https://github.com/cli/cli/blob/trunk/docs/install_linux.md"
    exit 1
fi

# Check if gh is authenticated
if ! gh auth status &> /dev/null; then
    echo "❌ GitHub CLI is not authenticated."
    echo "   Please run: gh auth login"
    exit 1
fi

echo "✅ GitHub CLI is installed and authenticated"
echo ""

# Try to fetch team members
echo "📋 Attempting to fetch team-support members..."
echo ""

if gh api /orgs/PostHog/teams/team-support/members --jq '.[].login' > "$TEAM_FILE" 2>/dev/null; then
    echo "✅ Successfully fetched team members!"
    echo "   Saved to: $TEAM_FILE"
    echo ""
    echo "Team members:"
    cat "$TEAM_FILE" | sed 's/^/  - /'
    echo ""
else
    echo "⚠️  Could not fetch team members automatically."
    echo "   This usually means you need team admin permissions."
    echo ""
    echo "📝 Please manually create the team members file:"
    echo ""
    echo "   1. Visit: https://github.com/orgs/PostHog/teams/team-support"
    echo "   2. Copy the GitHub usernames of all team members"
    echo "   3. Create $TEAM_FILE"
    echo "   4. Add one username per line"
    echo ""
    echo "Example format:"
    echo ""
    cat > "$TEAM_FILE" << 'EOF'
# PostHog Support Team Members
# Auto-generated on $(date)
# Update this file as team members change

# Add GitHub usernames below (one per line)
# Lines starting with # are comments and will be ignored

EOF
    echo "  Created template file: $TEAM_FILE"
    echo "  Please edit it and add the team member usernames"
    echo ""
    exit 1
fi

# Test the script
echo "🧪 Testing the PR summary script..."
echo ""

if python3 "$SCRIPT_DIR/pr_weekly_summary.py" --team-members-file "$TEAM_FILE" --days 7 --format text &> /dev/null; then
    echo "✅ Test successful!"
else
    echo "⚠️  Test had issues, but the configuration is ready"
fi

echo ""
echo "🎉 Setup complete!"
echo ""
echo "📊 Generate weekly PR summary:"
echo "   python3 $SCRIPT_DIR/pr_weekly_summary.py --team-members-file $TEAM_FILE"
echo ""
echo "📄 Generate markdown report:"
echo "   python3 $SCRIPT_DIR/pr_weekly_summary.py --team-members-file $TEAM_FILE --format markdown"
echo ""
echo "💾 Save to file:"
echo "   python3 $SCRIPT_DIR/pr_weekly_summary.py --team-members-file $TEAM_FILE --format markdown --output weekly_summary.md"
echo ""
echo "For more options, see: $SCRIPT_DIR/SUPPORT_TEAM_GUIDE.md"
