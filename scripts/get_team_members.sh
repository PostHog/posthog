#!/bin/bash
# Helper script to get GitHub team members
# Usage: ./scripts/get_team_members.sh <org> <team-slug>
#
# Example: ./scripts/get_team_members.sh PostHog team-support

ORG="${1:-PostHog}"
TEAM="${2:-team-support}"

echo "Fetching members of $ORG/$TEAM..."
echo ""

# Try to get team members (requires appropriate permissions)
gh api "/orgs/$ORG/teams/$TEAM/members" --jq '.[].login' 2>/dev/null || {
    echo "❌ Could not fetch team members directly (may require team admin permissions)"
    echo ""
    echo "Alternative methods:"
    echo ""
    echo "1. If you have team access, visit: https://github.com/orgs/$ORG/teams/$TEAM"
    echo "   and manually copy the usernames into a file."
    echo ""
    echo "2. Ask a team admin to run this script with appropriate permissions."
    echo ""
    echo "3. Use gh api with authentication:"
    echo "   gh api /orgs/$ORG/teams/$TEAM/members --jq '.[].login'"
    exit 1
}
