from posthog.models.team import Team

from products.web_analytics.backend.models import (
    ContentAutopilotProposal,
    ContentAutopilotRun,
    ContentAutopilotSiteProfile,
)

UNSET_CONTENT_PACKAGE = object()


def create_content_autopilot_profile(
    team: Team,
    *,
    domain: str = "https://example.com",
    search_console_enabled: bool = False,
) -> ContentAutopilotSiteProfile:
    return ContentAutopilotSiteProfile.objects.for_team(team.id).create(
        team=team,
        name="Example",
        domain=domain,
        source_urls=[f"{domain}/sitemap.xml"],
        content_boundaries=["/"],
        search_console_enabled=search_console_enabled,
    )


def create_content_autopilot_run(
    team: Team,
    profile: ContentAutopilotSiteProfile,
    *,
    run_status: str = ContentAutopilotRun.RunStatus.PENDING,
) -> ContentAutopilotRun:
    return ContentAutopilotRun.objects.for_team(team.id).create(
        team=team,
        profile=profile,
        run_status=run_status,
    )


def create_content_autopilot_proposal(
    team: Team,
    run: ContentAutopilotRun,
    *,
    proposal_type: str = ContentAutopilotProposal.ProposalType.PAGE_IMPROVEMENT,
    lifecycle_status: str = ContentAutopilotProposal.LifecycleStatus.READY_FOR_REVIEW,
    file_path: object = "content/guides/example.md",
    validation_passed: bool = True,
    markdown: str = "# Improved guide\n\nUseful content.",
    content_package: object = UNSET_CONTENT_PACKAGE,
) -> ContentAutopilotProposal:
    default_package: dict[str, object] = {
        "file_path": file_path,
        "title": "Improved guide",
        "description": "A clearer guide.",
        "slug": "example",
        "frontmatter": [{"key": "title", "value": "Improved guide"}],
        "internal_links": ["https://example.com/docs"],
        "source_notes": [],
    }
    return ContentAutopilotProposal.objects.for_team(team.id).create(
        team=team,
        run=run,
        proposal_type=proposal_type,
        lifecycle_status=lifecycle_status,
        title="Improve the example guide",
        target_url="https://example.com/guides/example",
        evidence=[
            {
                "opportunity_kind": "poor_ctr",
                "explanation": "The page ranks for this query but is clicked rarely.",
                "page_url": "https://example.com/guides/example",
                "query": "example guide",
                "metrics": {"impressions": 1240, "clicks": 21, "click_through_rate": 0.017},
            }
        ],
        validation_report={"passed": validation_passed, "checks": []},
        content_package=default_package if content_package is UNSET_CONTENT_PACKAGE else content_package,
        proposed_markdown=markdown,
    )
