#!/usr/bin/env python3
# ruff: noqa: T201
"""
Generate a weekly summary of PRs authored and merged by team members.

Usage:
    python scripts/pr_weekly_summary.py --team-members user1,user2,user3
    python scripts/pr_weekly_summary.py --team-members-file team.txt
    python scripts/pr_weekly_summary.py --team-members user1,user2 --days 14
"""

import json
import argparse
import subprocess
from datetime import datetime, timedelta
from typing import Any


def run_gh_command(cmd: list[str]) -> str:
    """Run a GitHub CLI command and return the output."""
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error running command: {' '.join(cmd)}")
        print(f"Error: {e.stderr}")
        return ""


def get_pr_details(repo: str, pr_number: int) -> dict[str, Any]:
    """Get detailed information about a specific PR."""
    cmd = [
        "gh",
        "pr",
        "view",
        str(pr_number),
        "--repo",
        repo,
        "--json",
        "number,title,state,createdAt,mergedAt,url,additions,deletions,mergedBy,closedAt",
    ]

    output = run_gh_command(cmd)
    if not output:
        return {}

    try:
        return json.loads(output)
    except json.JSONDecodeError:
        return {}


def get_prs_for_user(username: str, org: str, since_date: str) -> list[dict[str, Any]]:
    """Get all PRs authored by a user in the organization since a date."""
    # Search for PRs authored by the user
    search_query = f"type:pr author:{username} org:{org} created:>={since_date}"

    cmd = ["gh", "search", "prs", "--json", "number,title,state,repository,createdAt,url,author,closedAt", search_query]

    output = run_gh_command(cmd)
    if not output:
        return []

    try:
        prs = json.loads(output)

        # Enrich each PR with detailed information
        enriched_prs = []
        for pr in prs:
            repo_name = pr["repository"]["nameWithOwner"] if "repository" in pr else None
            if repo_name:
                details = get_pr_details(repo_name, pr["number"])
                if details:
                    # Merge search results with detailed info
                    pr.update(details)
            enriched_prs.append(pr)

        return enriched_prs
    except json.JSONDecodeError:
        print(f"Error parsing JSON for user {username}")
        return []


def format_date(date_str: str) -> str:
    """Format ISO date string to readable format."""
    if not date_str:
        return "N/A"
    try:
        dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M")
    except:
        return date_str


def generate_summary(team_members: list[str], org: str, days: int = 7) -> dict[str, Any]:
    """Generate PR summary for team members."""
    since_date = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d")

    summary = {
        "period": f"Last {days} days (since {since_date})",
        "generated_at": datetime.now().isoformat(),
        "members": {},
    }

    print(f"Fetching PRs for {len(team_members)} team members since {since_date}...")

    for username in team_members:
        print(f"  Fetching PRs for {username}...")
        prs = get_prs_for_user(username, org, since_date)

        # Categorize PRs
        authored = []
        merged = []
        open_prs = []
        closed_prs = []

        for pr in prs:
            pr_info = {
                "number": pr.get("number"),
                "title": pr.get("title"),
                "repository": pr["repository"]["name"] if "repository" in pr else "unknown",
                "url": pr.get("url"),
                "state": pr.get("state"),
                "created_at": format_date(pr.get("createdAt", "")),
                "merged_at": format_date(pr.get("mergedAt", "")),
                "additions": pr.get("additions", 0),
                "deletions": pr.get("deletions", 0),
            }

            authored.append(pr_info)

            if pr.get("state") == "MERGED":
                merged.append(pr_info)
            elif pr.get("state") == "OPEN":
                open_prs.append(pr_info)
            elif pr.get("state") == "CLOSED":
                closed_prs.append(pr_info)

        summary["members"][username] = {
            "total_authored": len(authored),
            "total_merged": len(merged),
            "total_open": len(open_prs),
            "total_closed": len(closed_prs),
            "authored_prs": authored,
            "merged_prs": merged,
            "open_prs": open_prs,
            "closed_prs": closed_prs,
        }

    return summary


def print_text_summary(summary: dict[str, Any]):
    """Print a human-readable text summary."""
    print("\n" + "=" * 80)
    print(f"📊 WEEKLY PR SUMMARY")
    print(f"Period: {summary['period']}")
    print(f"Generated: {summary['generated_at']}")
    print("=" * 80)

    # Overall stats
    total_authored = sum(m["total_authored"] for m in summary["members"].values())
    total_merged = sum(m["total_merged"] for m in summary["members"].values())
    total_open = sum(m["total_open"] for m in summary["members"].values())

    print(f"\n📈 TEAM OVERVIEW")
    print(f"  Total PRs Authored: {total_authored}")
    print(f"  Total PRs Merged: {total_merged}")
    print(f"  Total PRs Open: {total_open}")
    print(f"  Team Members: {len(summary['members'])}")

    # Per-member breakdown
    for username, data in summary["members"].items():
        print(f"\n{'─' * 80}")
        print(f"👤 {username}")
        print(f"{'─' * 80}")
        print(f"  📝 Authored: {data['total_authored']} PRs")
        print(f"  ✅ Merged: {data['total_merged']} PRs")
        print(f"  🔄 Open: {data['total_open']} PRs")
        print(f"  ❌ Closed (not merged): {data['total_closed']} PRs")

        if data["merged_prs"]:
            print(f"\n  ✅ Merged PRs:")
            for pr in data["merged_prs"]:
                print(f"    • #{pr['number']} - {pr['title']}")
                print(
                    f"      Repo: {pr['repository']} | +{pr['additions']} -{pr['deletions']} lines | Merged: {pr['merged_at']}"
                )
                print(f"      {pr['url']}")

        if data["open_prs"]:
            print(f"\n  🔄 Open PRs:")
            for pr in data["open_prs"]:
                print(f"    • #{pr['number']} - {pr['title']}")
                print(
                    f"      Repo: {pr['repository']} | +{pr['additions']} -{pr['deletions']} lines | Created: {pr['created_at']}"
                )
                print(f"      {pr['url']}")

    print("\n" + "=" * 80)


def print_markdown_summary(summary: dict[str, Any]):
    """Print a markdown-formatted summary."""
    print("\n# 📊 Weekly PR Summary\n")
    print(f"**Period:** {summary['period']}  ")
    print(f"**Generated:** {summary['generated_at']}\n")

    # Overall stats
    total_authored = sum(m["total_authored"] for m in summary["members"].values())
    total_merged = sum(m["total_merged"] for m in summary["members"].values())
    total_open = sum(m["total_open"] for m in summary["members"].values())

    print("## 📈 Team Overview\n")
    print(f"- **Total PRs Authored:** {total_authored}")
    print(f"- **Total PRs Merged:** {total_merged}")
    print(f"- **Total PRs Open:** {total_open}")
    print(f"- **Team Members:** {len(summary['members'])}\n")

    # Per-member breakdown
    for username, data in summary["members"].items():
        print(f"## 👤 {username}\n")
        print(f"- **Authored:** {data['total_authored']} PRs")
        print(f"- **Merged:** {data['total_merged']} PRs")
        print(f"- **Open:** {data['total_open']} PRs")
        print(f"- **Closed (not merged):** {data['total_closed']} PRs\n")

        if data["merged_prs"]:
            print(f"### ✅ Merged PRs\n")
            for pr in data["merged_prs"]:
                print(f"- [#{pr['number']} - {pr['title']}]({pr['url']})")
                print(f"  - **Repo:** {pr['repository']}")
                print(f"  - **Changes:** +{pr['additions']} -{pr['deletions']} lines")
                print(f"  - **Merged:** {pr['merged_at']}\n")

        if data["open_prs"]:
            print(f"### 🔄 Open PRs\n")
            for pr in data["open_prs"]:
                print(f"- [#{pr['number']} - {pr['title']}]({pr['url']})")
                print(f"  - **Repo:** {pr['repository']}")
                print(f"  - **Changes:** +{pr['additions']} -{pr['deletions']} lines")
                print(f"  - **Created:** {pr['created_at']}\n")

        print("")


def main():
    parser = argparse.ArgumentParser(
        description="Generate a weekly summary of PRs for team members",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument("--team-members", type=str, help="Comma-separated list of GitHub usernames")

    parser.add_argument("--team-members-file", type=str, help="Path to file containing GitHub usernames (one per line)")

    parser.add_argument("--org", type=str, default="PostHog", help="GitHub organization name (default: PostHog)")

    parser.add_argument("--days", type=int, default=7, help="Number of days to look back (default: 7)")

    parser.add_argument(
        "--format", type=str, choices=["text", "markdown", "json"], default="text", help="Output format (default: text)"
    )

    parser.add_argument("--output", type=str, help="Output file (default: stdout)")

    args = parser.parse_args()

    # Get team members list
    team_members = []
    if args.team_members:
        team_members = [m.strip() for m in args.team_members.split(",") if m.strip()]
    elif args.team_members_file:
        try:
            with open(args.team_members_file) as f:
                team_members = [line.strip() for line in f if line.strip() and not line.startswith("#")]
        except FileNotFoundError:
            print(f"Error: File not found: {args.team_members_file}")
            return 1
    else:
        parser.print_help()
        print("\nError: Either --team-members or --team-members-file must be provided")
        return 1

    if not team_members:
        print("Error: No team members specified")
        return 1

    # Generate summary
    summary = generate_summary(team_members, args.org, args.days)

    # Format output
    if args.format == "json":
        output = json.dumps(summary, indent=2)
        print(output)
    elif args.format == "markdown":
        import io
        import sys

        # Capture output
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        print_markdown_summary(summary)
        output = buffer.getvalue()
        sys.stdout = old_stdout

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Summary written to {args.output}")
        else:
            print(output)
    else:  # text format
        import io
        import sys

        # Capture output
        old_stdout = sys.stdout
        sys.stdout = buffer = io.StringIO()
        print_text_summary(summary)
        output = buffer.getvalue()
        sys.stdout = old_stdout

        if args.output:
            with open(args.output, "w") as f:
                f.write(output)
            print(f"Summary written to {args.output}")
        else:
            print(output)

    return 0


if __name__ == "__main__":
    exit(main())
