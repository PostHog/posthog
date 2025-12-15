#!/usr/bin/env python3
"""
Test script that creates a task and runs the agent using DockerSandbox.
"""
# ruff: noqa: T201, E402

import os
import sys
import argparse
from pathlib import Path

script_dir = Path(__file__).resolve().parent
repo_root = script_dir.parent.parent.parent

if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "posthog.settings")
os.environ["DEBUG"] = "1"

import django

django.setup()

from django.db import transaction

from posthog.models import FeatureFlag, Integration, PersonalAPIKey, Team, User
from posthog.models.personal_api_key import hash_key_value
from posthog.models.utils import generate_random_token_personal

from products.tasks.backend.models import Task, TaskRun
from products.tasks.backend.services.docker_sandbox import DockerSandbox
from products.tasks.backend.services.sandbox import SandboxConfig, SandboxTemplate


def create_test_task(repository=None):
    with transaction.atomic():
        team = Team.objects.get(id=1)
        user = User.objects.get(email="test@posthog.com")

        if repository:
            parts = repository.split("/")
            if len(parts) != 2 or not parts[0] or not parts[1]:
                raise ValueError("Repository must be in format 'owner/repo'")
            org, repo = parts
        else:
            org, repo = "posthog", "posthog-js"

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

        github_integration, _ = Integration.objects.get_or_create(
            team=team, kind="github", defaults={"config": {"organization": org, "repositories": [repo]}}
        )

        github_token = (
            github_integration.sensitive_config.get("access_token") if github_integration.sensitive_config else None
        )

        repository = f"{org}/{repo}"

        task = Task.objects.create(
            team=team,
            title="Add a joke to the README.md file",
            description="Add a joke to the README.md file",
            origin_product=Task.OriginProduct.USER_CREATED,
            github_integration=github_integration,
            repository=repository,
        )

        task_run = TaskRun.objects.create(task=task, team=team)

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
        print(f"  - Run ID: {task_run.id}")
        print(f"  - Team: {team.id}")
        print(f"  - API Key: {api_key_value}")
        print(f"  - GitHub token: {'✓' if github_token else '✗ (not configured)'}")

        return task, task_run, api_key, api_key_value, github_token


def cleanup_test_data(task_id, api_key_id):
    print(f"\nCleaning up test data...")
    with transaction.atomic():
        task = Task.objects.filter(id=task_id).first()
        if task:
            task.soft_delete()
        PersonalAPIKey.objects.filter(id=api_key_id).delete()
    print("✓ Cleanup complete")


def main():
    parser = argparse.ArgumentParser(description="Test agent in DockerSandbox")
    parser.add_argument("--repository", help="GitHub repository", default="joshsny/test-repo")
    parser.add_argument("--github-token", help="GitHub personal access token")
    parser.add_argument("--no-cleanup", action="store_true", help="Don't cleanup test data")
    parser.add_argument("--keep-sandbox", action="store_true", help="Don't destroy sandbox after running")

    args = parser.parse_args()

    task, task_run, api_key, api_key_value, github_token_from_integration = create_test_task(args.repository)
    github_token = args.github_token or github_token_from_integration

    sandbox = None
    try:
        config = SandboxConfig(
            name=f"test-sandbox-{task.id}",
            template=SandboxTemplate.DEFAULT_BASE,
            environment_variables={
                "GITHUB_TOKEN": github_token or "",
                "POSTHOG_PERSONAL_API_KEY": api_key_value,
                "POSTHOG_API_URL": "http://localhost:8000",  # Use 8000 directly, not 8010 (Caddy returns empty from Docker)
                "POSTHOG_PROJECT_ID": "1",
            },
        )

        print(f"\n{'=' * 60}")
        print("Creating DockerSandbox...")
        print(f"{'=' * 60}")
        sandbox = DockerSandbox.create(config)
        print(f"✓ Sandbox created: {sandbox.id}")

        print(f"\nCloning {task.repository}...")
        clone_result = sandbox.clone_repository(task.repository, github_token=github_token or "")
        print(f"Clone exit code: {clone_result.exit_code}")
        if clone_result.exit_code != 0:
            print(f"Clone stderr: {clone_result.stderr}")
            raise RuntimeError("Failed to clone repository")

        print(f"\nExecuting task {task.id} (run {task_run.id})...")
        result = sandbox.execute_task(
            task_id=str(task.id),
            run_id=str(task_run.id),
            repository=task.repository,
        )

        print(f"\n{'=' * 60}")
        print(f"Task completed with exit code: {result.exit_code}")
        print(f"{'=' * 60}")
        print(f"\nstdout:\n{result.stdout}")
        print(f"\nstderr:\n{result.stderr}")

        exit_code = result.exit_code

    except Exception as e:
        print(f"\nERROR: {e}")
        import traceback

        traceback.print_exc()
        exit_code = 1

    finally:
        if sandbox and not args.keep_sandbox:
            print(f"\nDestroying sandbox...")
            sandbox.destroy()
            print("✓ Sandbox destroyed")
        elif sandbox:
            print(f"\n⚠ Sandbox kept alive: {sandbox.id}")
            print(f"  To destroy: docker rm -f {sandbox.id}")

        if not args.no_cleanup:
            cleanup_test_data(task.id, api_key.id)
        else:
            print(f"\n⚠ Test data not cleaned up")
            print(f"  Task ID: {task.id}")
            print(f"  Run ID: {task_run.id}")

    sys.exit(exit_code)


if __name__ == "__main__":
    main()
