#!/usr/bin/env python3
"""
Wrapper script that creates a task locally, then runs the agent in Docker.
"""
# ruff: noqa: T201, E402

import os
import sys
import argparse
import subprocess
from pathlib import Path

script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parent.parent.parent

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")

import django

django.setup()

from django.db import transaction

from posthog.models import FeatureFlag, Integration, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.tasks.backend.models import Task


def create_test_task(repository=None):
    with transaction.atomic():
        # Use existing hedgebox demo team
        team = Team.objects.get(id=1)
        user = User.objects.get(email="test@posthog.com")

        # Parse repository argument or use default
        if repository:
            parts = repository.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError("Repository must be in format 'owner/repo'")
            org, repo = parts
        else:
            org, repo = "posthog", "posthog-js"

        # Enable tasks feature flag on team 1 if not already enabled
        feature_flag, created = FeatureFlag.objects.get_or_create(
            team=team,
            key="tasks",
            defaults={
                "created_by": user,
                "filters": {"groups": [{"properties": [], "rollout_percentage": 100}]},
                "active": True,
            },
        )
        if not created and not feature_flag.active:
            feature_flag.active = True
            feature_flag.save()

        # Get or create GitHub integration
        github_integration, _ = Integration.objects.get_or_create(
            team=team, kind="github", defaults={"config": {"organization": org, "repositories": [repo]}}
        )

        # Get GitHub token from integration
        github_token = (
            github_integration.sensitive_config.get("access_token") if github_integration.sensitive_config else None
        )

        repository = f"{org}/{repo}"

        task = Task.objects.create(
            team=team,
            title="Test Task for runAgent.mjs",
            description="This is a test task created to test the runAgent.mjs script outside of sandbox",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=github_integration,
            repository=repository,
        )

        api_key_value = generate_random_token_personal()
        api_key = PersonalAPIKey.objects.create(
            user=user,
            label="Test runAgent",
            secure_value=hash_key_value(api_key_value),
            scopes=[
                "error_tracking:read",
                "user:read",
                "organization:read",
                "project:read",
                "task:read",
                "task:write",
            ],
            scoped_teams=[team.id],
        )

        print(f"✓ Created test task: {task.id}")
        print(f"  - Team: {team.id}")
        print(f"  - Task slug: {task.slug}")
        print(f"  - API Key: {api_key_value}")
        print(f"  - GitHub token: {'✓' if github_token else '✗ (not configured)'}")

        return task, api_key.id, api_key_value, github_token


def cleanup_test_data(task_id, api_key_id):
    print(f"\nCleaning up test data...")
    with transaction.atomic():
        Task.objects.filter(id=task_id).delete()
        PersonalAPIKey.objects.filter(id=api_key_id).delete()
    print("✓ Cleanup complete")


def run_agent_in_docker(
    task_id, repository_path, api_key, team_id, repository, github_token=None, prompt=None, max_turns=None
):
    image_name = "posthog-sandbox-base"
    # Access PostHog web server directly on host port 8000
    host_url = "http://host.docker.internal:8000"

    # Match production sandbox structure: /tmp/workspace/repos/{org}/{repo}
    org, repo = repository.lower().split("/")
    container_repo_path = f"/tmp/workspace/repos/{org}/{repo}"

    # Build image if needed
    check_result = subprocess.run(["docker", "images", "-q", image_name], capture_output=True, text=True)

    if not check_result.stdout.strip():
        print("Building sandbox-base image...")
        subprocess.run(
            [
                "docker",
                "build",
                "-f",
                f"{repo_root}/products/tasks/backend/sandbox/images/Dockerfile.sandbox-base",
                "-t",
                image_name,
                str(repo_root),
            ],
            check=True,
        )

    # Clone repository first, then run agent (matching production flow)
    # Use token in URL for authentication if available
    # GitHub accepts tokens in the format: https://x-access-token:TOKEN@github.com/...
    if github_token:
        clone_url = f"https://x-access-token:{github_token}@github.com/{repository}.git"
    else:
        clone_url = f"https://github.com/{repository}.git"
    clone_cmd = f"mkdir -p /tmp/workspace/repos/{org} && cd /tmp/workspace/repos/{org} && git clone {clone_url} {repo}"

    # Build node command
    cmd_parts = ["node", "/scripts/runAgent.mjs"]

    if prompt:
        cmd_parts.extend(["--prompt", f"'{prompt}'"])
        if max_turns:
            cmd_parts.extend(["--max-turns", str(max_turns)])
    else:
        cmd_parts.extend(["--taskId", str(task_id)])

    cmd_parts.extend(["--repositoryPath", container_repo_path])

    run_cmd = " ".join(cmd_parts)

    # Match production sandbox.py:298 - git reset + IS_SANDBOX inline
    agent_cmd = f"git reset --hard HEAD && IS_SANDBOX=True {run_cmd}"

    # Combine clone and run commands
    full_cmd = f"{clone_cmd} && cd {container_repo_path} && {agent_cmd}"

    print(f"\nRunning agent in Docker container...")
    print(f"  Clone + Run command: {full_cmd}")
    print(f"  Host URL: {host_url}")
    print(f"  Project ID: {team_id}")
    print(f"  Repository: {repository}")
    print(f"  GitHub token: {'✓' if github_token else '✗ (not configured - will fail on git push)'}")
    print()

    # Mount the updated runAgent.mjs script
    runagent_path = f"{repo_root}/products/tasks/scripts/runAgent.mjs"

    docker_args = [
        "docker",
        "run",
        "--rm",
        "-v",
        f"{runagent_path}:/scripts/runAgent.mjs:ro",
        "-e",
        f"POSTHOG_API_URL={host_url}",
        "-e",
        f"POSTHOG_PERSONAL_API_KEY={api_key}",
        "-e",
        f"POSTHOG_PROJECT_ID={team_id}",
    ]

    if github_token:
        docker_args.extend(["-e", f"GITHUB_TOKEN={github_token}"])

    docker_args.extend([image_name, "bash", "-c", full_cmd])

    result = subprocess.run(docker_args)

    print(f"\n{'='*60}")
    print(f"Agent completed with exit code: {result.returncode}")
    print(f"{'='*60}\n")

    return result.returncode


def main():
    parser = argparse.ArgumentParser(description="Test runAgent.mjs in Docker with @posthog/agent package")
    parser.add_argument("--prompt", help="Optional prompt to run")
    parser.add_argument("--max-turns", type=int, help="Maximum turns (with --prompt)")
    parser.add_argument("--repository-path", default=str(repo_root), help="Repository path")
    parser.add_argument("--repository", help="GitHub repository", default="posthog/posthog-js")
    parser.add_argument("--github-token", help="GitHub personal access token")
    parser.add_argument("--no-cleanup", action="store_true", help="Don't cleanup test data")

    args = parser.parse_args()

    task, api_key_id, api_key_value, github_token_from_integration = create_test_task(args.repository)
    task_id = str(task.id)
    api_key = api_key_value
    github_token = args.github_token or github_token_from_integration
    team_id = 1  # Hardcoded to hedgebox team
    repository = task.repository

    try:
        exit_code = run_agent_in_docker(
            task_id,
            args.repository_path,
            api_key,
            team_id,
            repository,
            github_token=github_token,
            prompt=args.prompt,
            max_turns=args.max_turns,
        )

        if not args.no_cleanup:
            cleanup_test_data(task_id, api_key_id)
        else:
            print(f"\n⚠ Test data not cleaned up")
            print(f"  Task ID: {task_id}")

        sys.exit(exit_code)

    except Exception as e:
        print(f"\nERROR: {e}")
        if not args.no_cleanup:
            cleanup_test_data(task_id, api_key_id)
        sys.exit(1)


if __name__ == "__main__":
    main()
