"""Provision an isolated team for one self-driving eval task.

Run through Django:
    DEBUG=1 python manage.py shell -c "
    from products.signals.eval.self_driving.harness.provision import provision_task_team
    print(provision_task_team('smoke-checkout', 'acme/smoke-checkout'))"

Creates (idempotently, keyed on team name):
- an eval Organization (AI data processing approved) shared by all eval task teams
- a Team per task — isolates ClickHouse data, signal embeddings, and reports
- a synthetic GitHub Integration whose cached access token never expires locally,
  so no call ever reaches GitHub; the repo itself is bind-mounted into the sandbox
  via SANDBOX_REPO_MOUNT_MAP
- SignalTeamConfig with P4 autostart (auto-start everything) and a SignalSourceConfig
  row enabling the zendesk source
- membership for the driving user so reviewer resolution and autostart assignee work
"""

import time
import uuid

from django.utils import timezone

EVAL_ORG_NAME = "Self-Driving SWE Evals"
EVAL_USER_EMAIL = "test@posthog.com"
GITHUB_LOGIN = "dana-acme"


def provision_task_team(task_id: str, repo_full_name: str, repo_dir: str | None = None) -> dict:
    from posthog.models import Integration, Organization, OrganizationMembership, Team, User
    from posthog.models.integration_repository_cache import IntegrationRepositoryCacheEntry
    from posthog.models.utils import generate_random_token_project

    from products.signals.backend.models import SignalSourceConfig, SignalTeamConfig

    user = User.objects.get(email=EVAL_USER_EMAIL)

    org = Organization.objects.filter(name=EVAL_ORG_NAME).first()
    if org is None:
        org = Organization.objects.create(name=EVAL_ORG_NAME, is_ai_data_processing_approved=True)
    elif not org.is_ai_data_processing_approved:
        org.is_ai_data_processing_approved = True
        org.save(update_fields=["is_ai_data_processing_approved"])

    OrganizationMembership.objects.get_or_create(
        organization=org, user=user, defaults={"level": OrganizationMembership.Level.OWNER}
    )

    team_name = f"eval-{task_id}"
    team = Team.objects.filter(organization=org, name=team_name).first()
    if team is None:
        from posthog.models.project import Project

        project = Project.objects.create(organization=org, name=team_name, id=Team.objects.increment_id_sequence())
        team = Team.objects.create(
            id=project.id,
            project=project,
            organization=org,
            name=team_name,
            api_token=generate_random_token_project(),
        )

    org_part, repo_part = repo_full_name.split("/")
    integration = Integration.objects.filter(team=team, kind="github").first()
    config = {
        "eval_synthetic": True,
        "account": {"name": org_part, "type": "Organization"},
        "installation_id": 90000000 + (abs(hash(task_id)) % 1000000),
        "repository_selection": "selected",
        "connecting_user_github_login": GITHUB_LOGIN,
        # Never-expiring cached token: access_token_expired() checks
        # refreshed_at + expires_in, so the dummy token below is always served
        # from cache and no request ever reaches GitHub.
        "expires_in": 10 * 365 * 24 * 3600,
        "refreshed_at": time.time(),
    }
    repo_cache = [{"id": abs(hash(repo_full_name)) % 10**9, "name": repo_part, "full_name": repo_full_name}]
    if integration is None:
        integration = Integration.objects.create(
            team=team,
            kind="github",
            integration_id=str(config["installation_id"]),
            config=config,
            sensitive_config={"access_token": f"ghs_eval_dummy_{uuid.uuid4().hex[:12]}"},
            repository_cache=repo_cache,
            repository_cache_updated_at=timezone.now(),
            created_by=user,
        )
    else:
        integration.config = config
        integration.repository_cache = repo_cache
        integration.repository_cache_updated_at = timezone.now()
        integration.errors = ""
        integration.save()

    # The repo-selection candidate list comes from the heavy per-row cache, not the JSON
    # field — entries must exist, be non-archived, and be fresh (TTL) so the sync's
    # GitHub refresh path never fires for our synthetic installation.
    readme = ""
    tree_paths = ""
    if repo_dir:
        from pathlib import Path

        root = Path(repo_dir)
        readme_file = root / "README.md"
        readme = readme_file.read_text() if readme_file.exists() else ""
        tree_paths = "\n".join(
            sorted(
                str(p.relative_to(root))
                for p in root.rglob("*")
                if p.is_file() and ".git" not in p.parts and "node_modules" not in p.parts
            )
        )
    IntegrationRepositoryCacheEntry.objects.update_or_create(
        integration=integration,
        team=team,
        full_name=repo_full_name,
        defaults={
            "description": f"{repo_part} service",
            "topics": [],
            "archived": False,
            "fork": False,
            "primary_language": "JavaScript",
            "default_branch": "main",
            "default_branch_sha": uuid.uuid4().hex + uuid.uuid4().hex[:8],
            "readme": readme,
            "tree_paths": tree_paths,
            "tree_truncated": False,
        },
    )

    SignalTeamConfig.objects.get_or_create(team=team, defaults={"default_autostart_priority": "P4"})
    for source_product, source_type in [
        ("zendesk", "ticket"),
        ("conversations", "ticket"),
        ("github", "issue"),
        ("linear", "issue"),
        ("pganalyze", "issue"),
    ]:
        SignalSourceConfig.objects.update_or_create(
            team=team,
            source_product=source_product,
            source_type=source_type,
            defaults={"enabled": True, "created_by": user},
        )

    return {
        "team_id": team.id,
        "api_token": team.api_token,
        "user_id": user.id,
        "integration_id": integration.id,
        "repo": repo_full_name,
    }
