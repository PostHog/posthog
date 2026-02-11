"""Seed visual review with dummy runs using real repo data."""

import random
import hashlib
import subprocess
from pathlib import Path

from django.core.management.base import BaseCommand
from django.utils import timezone

from posthog.models.team import Team

from products.visual_review.backend.facade.enums import ReviewState, RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import Artifact, Repo, Run, RunSnapshot
from products.visual_review.backend.storage import ArtifactStorage


class Command(BaseCommand):
    help = "Seed visual review with dummy runs from real master commits and repo snapshots"

    def add_arguments(self, parser):
        parser.add_argument(
            "--team-id",
            type=int,
            default=1,
            help="Team ID to create runs for (default: 1)",
        )
        parser.add_argument(
            "--runs",
            type=int,
            default=20,
            help="Number of runs to create (default: 20)",
        )
        parser.add_argument(
            "--snapshots-per-run",
            type=int,
            default=10,
            help="Max snapshots per run (default: 10)",
        )
        parser.add_argument(
            "--repo-name",
            type=str,
            default="posthog/posthog",
            help="GitHub repo name (default: posthog/posthog)",
        )

    def handle(self, *_args, **options):
        team_id = options["team_id"]
        num_runs = options["runs"]
        snapshots_per_run = options["snapshots_per_run"]
        repo_name = options["repo_name"]

        try:
            team = Team.objects.get(id=team_id)
        except Team.DoesNotExist:
            self.stderr.write(f"Team {team_id} not found")
            return

        # Get or create repo
        repo, created = Repo.objects.get_or_create(
            team=team,
            name="Visual Review Demo",
            defaults={
                "repo_full_name": repo_name,
                "baseline_file_paths": {
                    "storybook": ".storybook/snapshots.yml",
                    "playwright": "playwright/snapshots.yml",
                },
            },
        )
        if created:
            self.stdout.write(f"Created repo: {repo.name}")
        else:
            self.stdout.write(f"Using existing repo: {repo.name}")

        # Collect snapshot files
        repo_root = Path(__file__).resolve().parents[5]  # Go up to repo root
        storybook_snapshots = list((repo_root / "frontend" / "__snapshots__").glob("*.png"))
        playwright_snapshots = list((repo_root / "playwright" / "__snapshots__").rglob("*.png"))

        if not storybook_snapshots:
            self.stderr.write("No storybook snapshots found in frontend/__snapshots__")
            return
        self.stdout.write(f"Found {len(storybook_snapshots)} storybook snapshots")
        self.stdout.write(f"Found {len(playwright_snapshots)} playwright snapshots")

        # Get recent merged PRs from GitHub
        prs = self._get_merged_prs(num_runs * 2)  # Fetch extra in case some fail
        if not prs:
            self.stderr.write("No merged PRs found, using git log fallback")
            prs = self._get_commits_from_git(num_runs)

        self.stdout.write(f"Found {len(prs)} commits to use")

        # Create storage for this repo
        storage = ArtifactStorage(str(repo.id))

        # Create runs alternating between storybook and playwright
        runs_created = 0
        for i, pr_data in enumerate(prs[:num_runs]):
            run_type = RunType.STORYBOOK if i % 2 == 0 else RunType.PLAYWRIGHT
            snapshots = storybook_snapshots if run_type == RunType.STORYBOOK else playwright_snapshots

            if not snapshots:
                snapshots = storybook_snapshots  # Fallback to storybook

            run = self._create_run(repo, pr_data, run_type, snapshots, snapshots_per_run, storage)
            if run:
                runs_created += 1
                self.stdout.write(
                    f"  [{runs_created}/{num_runs}] {run.branch[:40]:<40} "
                    f"PR#{run.pr_number or 'N/A':<5} {run.run_type:<10} "
                    f"changed={run.changed_count} new={run.new_count}"
                )

        self.stdout.write(self.style.SUCCESS(f"\nCreated {runs_created} runs for repo '{repo.name}'"))

    def _get_merged_prs(self, limit: int) -> list[dict]:
        """Fetch recent merged PRs from GitHub."""
        try:
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "merged",
                    "--limit",
                    str(limit),
                    "--json",
                    "number,headRefName,mergeCommit,title",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )
            if result.returncode != 0:
                return []

            import json

            prs = json.loads(result.stdout)
            return [
                {
                    "commit_sha": pr["mergeCommit"]["oid"],
                    "branch": pr["headRefName"],
                    "pr_number": pr["number"],
                    "pr_title": pr.get("title", ""),
                }
                for pr in prs
                if pr.get("mergeCommit")
            ]
        except Exception:
            return []

    def _get_commits_from_git(self, limit: int) -> list[dict]:
        """Fallback: get commits from git log."""
        try:
            result = subprocess.run(
                ["git", "log", "master", f"-{limit}", "--format=%H %s"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            commits = []
            for line in result.stdout.strip().split("\n"):
                if " " in line:
                    sha, title = line.split(" ", 1)
                    commits.append(
                        {
                            "commit_sha": sha,
                            "branch": f"commit-{sha[:8]}",
                            "pr_number": None,
                            "pr_title": title,
                        }
                    )
            return commits
        except Exception:
            return []

    def _create_run(
        self,
        repo: Repo,
        pr_data: dict,
        run_type: RunType,
        available_snapshots: list[Path],
        max_snapshots: int,
        storage: ArtifactStorage,
    ) -> Run | None:
        """Create a run with snapshots."""
        # Pick random snapshots
        num_snapshots = min(max_snapshots, len(available_snapshots))
        selected = random.sample(available_snapshots, num_snapshots)

        # Create run
        run = Run.objects.create(
            repo=repo,
            status=RunStatus.COMPLETED,
            run_type=run_type,
            commit_sha=pr_data["commit_sha"],
            branch=pr_data["branch"],
            pr_number=pr_data.get("pr_number"),
            total_snapshots=num_snapshots,
            metadata={
                "pr_title": pr_data.get("pr_title", ""),
                "ci_job_url": f"https://github.com/PostHog/posthog/actions/runs/{random.randint(10000000000, 99999999999)}",
            },
            completed_at=timezone.now(),
        )

        # Create snapshots with realistic distribution
        # ~60% unchanged, ~25% changed, ~10% new, ~5% removed
        changed_count = 0
        new_count = 0
        removed_count = 0

        for snapshot_path in selected:
            result = self._pick_result()
            identifier = snapshot_path.stem  # Use filename without extension

            # Create artifact for current image - upload to storage if not exists
            content_hash = self._hash_file(snapshot_path)
            existing = Artifact.objects.filter(repo=repo, content_hash=content_hash).first()

            if existing:
                artifact = existing
            else:
                # Read and upload the actual image to MinIO
                image_bytes = snapshot_path.read_bytes()
                storage_path = storage.write(content_hash, image_bytes)

                artifact = Artifact.objects.create(
                    repo=repo,
                    content_hash=content_hash,
                    storage_path=storage_path,
                    width=random.randint(800, 1920),
                    height=random.randint(600, 1080),
                    size_bytes=len(image_bytes),
                )

            # Determine baseline artifact
            if result == SnapshotResult.NEW:
                baseline_artifact = None
                baseline_hash = ""
                new_count += 1
            elif result == SnapshotResult.REMOVED:
                baseline_artifact = artifact
                baseline_hash = content_hash
                artifact = None
                removed_count += 1
            elif result == SnapshotResult.CHANGED:
                # Use same artifact but different hash to simulate change
                baseline_hash = hashlib.sha256(content_hash.encode() + b"baseline").hexdigest()
                baseline_artifact = artifact
                changed_count += 1
            else:  # UNCHANGED
                baseline_artifact = artifact
                baseline_hash = content_hash

            # Historic data: all changes are approved (changed, new, or removed)
            review_state = ReviewState.APPROVED if result != SnapshotResult.UNCHANGED else ReviewState.PENDING

            RunSnapshot.objects.create(
                run=run,
                identifier=identifier,
                current_hash=content_hash if artifact else "",
                baseline_hash=baseline_hash,
                current_artifact=artifact if result != SnapshotResult.REMOVED else None,
                baseline_artifact=baseline_artifact,
                result=result,
                review_state=review_state,
                reviewed_at=timezone.now() if review_state == ReviewState.APPROVED else None,
                approved_hash=content_hash if review_state == ReviewState.APPROVED else "",
                diff_percentage=random.uniform(0.1, 15.0) if result == SnapshotResult.CHANGED else None,
                diff_pixel_count=random.randint(100, 10000) if result == SnapshotResult.CHANGED else None,
                metadata={
                    "browser": random.choice(["chromium", "firefox", "webkit"]),
                    "viewport": random.choice(["desktop", "mobile", "tablet"]),
                },
            )

        # Update run counts - all historic runs are approved
        run.changed_count = changed_count
        run.new_count = new_count
        run.removed_count = removed_count
        run.approved = True
        run.approved_at = timezone.now()
        run.save()

        return run

    def _pick_result(self) -> SnapshotResult:
        """Pick a snapshot result with realistic distribution."""
        r = random.random()
        if r < 0.60:
            return SnapshotResult.UNCHANGED
        elif r < 0.85:
            return SnapshotResult.CHANGED
        elif r < 0.95:
            return SnapshotResult.NEW
        else:
            return SnapshotResult.REMOVED

    def _hash_file(self, path: Path) -> str:
        """Get SHA256 hash of file contents."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest()
