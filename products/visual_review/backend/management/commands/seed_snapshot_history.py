"""Seed visual review with a long history for one snapshot identifier (light + dark)."""

import random
from datetime import timedelta
from pathlib import Path
from uuid import UUID

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from blake3 import blake3

from products.visual_review.backend.facade.enums import ReviewState, RunStatus, RunType, SnapshotResult
from products.visual_review.backend.models import Artifact, Repo, Run, RunSnapshot
from products.visual_review.backend.storage import ArtifactStorage


class Command(BaseCommand):
    help = "Seed long history for one identifier (with --light + --dark variants)"

    def add_arguments(self, parser):
        parser.add_argument(
            "--repo-id",
            type=str,
            required=True,
            help="Repo UUID to seed into (use a repo from `seed_dummy_runs` first).",
        )
        parser.add_argument(
            "--stem",
            type=str,
            default="insight-trends-popover",
            help="Identifier stem; --light and --dark variants are seeded.",
        )
        parser.add_argument(
            "--run-type",
            type=str,
            default=RunType.PLAYWRIGHT,
            choices=[RunType.PLAYWRIGHT, RunType.STORYBOOK],
        )
        parser.add_argument("--entries", type=int, default=24, help="Number of historical entries (default: 24)")

    def handle(self, *_args, **options):
        repo_id = UUID(options["repo_id"])
        stem = options["stem"]
        run_type = options["run_type"]
        n = options["entries"]

        try:
            repo = Repo.objects.get(id=repo_id)
        except Repo.DoesNotExist:
            raise CommandError(f"Repo {repo_id} not found")

        repo_root = Path(__file__).resolve().parents[5]
        pool = list((repo_root / "frontend" / "__snapshots__").glob("*.png")) or list(
            (repo_root / "playwright" / "__snapshots__").rglob("*.png")
        )
        if not pool:
            raise CommandError("No source PNGs found in frontend/__snapshots__ or playwright/__snapshots__")

        # Use 1-2 different source images so we get a believable "drift over time" effect
        # — pick a small set then bias the sampling toward the same handful for most entries.
        anchor_images = random.sample(pool, min(4, len(pool)))
        storage = ArtifactStorage(str(repo.id))

        # Track the previous master run so we can mark it superseded — there's a
        # partial unique constraint on (repo, branch, run_type) WHERE superseded_by IS NULL.
        # Pre-existing master run (from earlier seeds or real data) needs to be the head
        # of the supersession chain so our first new run can become the new head.
        prev_master_run: Run | None = (
            Run.objects.filter(repo=repo, branch="master", run_type=run_type, superseded_by__isnull=True)
            .order_by("-created_at")
            .first()
        )

        for i in range(n):
            # Older first → newer; we'll set created_at to space them out
            age_days = (n - i) * 3 + random.randint(0, 2)
            sha = blake3(f"history-{stem}-{i}".encode()).hexdigest()[:12]

            # 75% of entries reuse a recent anchor, 25% drift to a new one
            img_path = anchor_images[i % len(anchor_images)] if random.random() < 0.75 else random.choice(pool)
            # branch="master" so the entries qualify as baseline-history (logic filters
            # by default-branch). About 1 in 6 entries lives on a PR branch — those should
            # NOT show up in history, useful for visual confirmation of the filter.
            on_master = i % 6 != 0
            # Supersede the previous head BEFORE inserting the new one — the partial unique
            # constraint on (repo, branch, run_type) WHERE superseded_by IS NULL is enforced
            # at INSERT time, so the prev row must already have superseded_by set.
            placeholder: Run | None = None
            if on_master and prev_master_run is not None:
                placeholder = Run.objects.create(
                    repo=repo,
                    team_id=repo.team_id,
                    status=RunStatus.COMPLETED,
                    run_type=run_type,
                    commit_sha=f"placeholder-{i}",
                    branch=f"_supersede_placeholder_{i}",
                    total_snapshots=0,
                    completed_at=timezone.now(),
                )
                Run.objects.filter(id=prev_master_run.id).update(superseded_by=placeholder)
            run = Run.objects.create(
                repo=repo,
                team_id=repo.team_id,
                status=RunStatus.COMPLETED,
                run_type=run_type,
                commit_sha=sha,
                branch="master" if on_master else f"feat/history-seed-{i:02d}",
                pr_number=50000 + i,
                total_snapshots=2,
                metadata={"pr_title": f"history seed {i}", "ci_job_url": ""},
                approved=True,
                approved_at=timezone.now(),
                completed_at=timezone.now(),
            )
            if placeholder is not None:
                assert prev_master_run is not None  # placeholder only created when prev exists
                # Re-point: prev → real new run, then drop the placeholder.
                Run.objects.filter(id=prev_master_run.id).update(superseded_by=run)
                placeholder.delete()
            if on_master:
                prev_master_run = run
            # Rewind created_at so the timeline isn't bunched at "now".
            Run.objects.filter(id=run.id).update(
                created_at=timezone.now() - timedelta(days=age_days),
                approved_at=timezone.now() - timedelta(days=age_days),
                completed_at=timezone.now() - timedelta(days=age_days),
            )

            for theme in ("light", "dark"):
                identifier = f"{stem}--{theme}"
                content_hash = blake3(f"{sha}-{theme}-{img_path.name}".encode()).hexdigest()
                artifact = Artifact.objects.filter(repo=repo, content_hash=content_hash).first()
                if not artifact:
                    image_bytes = img_path.read_bytes()
                    storage_path = storage.write(content_hash, image_bytes)
                    artifact = Artifact.objects.create(
                        repo=repo,
                        team_id=repo.team_id,
                        content_hash=content_hash,
                        storage_path=storage_path,
                        width=1280,
                        height=720,
                        size_bytes=len(image_bytes),
                    )

                # First entry is the birth; everything after is "approved change".
                result = SnapshotResult.NEW if i == 0 else SnapshotResult.CHANGED
                RunSnapshot.objects.create(
                    run=run,
                    team_id=repo.team_id,
                    identifier=identifier,
                    current_hash=content_hash,
                    baseline_hash="" if result == SnapshotResult.NEW else content_hash,
                    current_artifact=artifact,
                    baseline_artifact=artifact if result == SnapshotResult.CHANGED else None,
                    result=result,
                    review_state=ReviewState.APPROVED,
                    reviewed_at=timezone.now() - timedelta(days=age_days),
                    approved_hash=content_hash,
                    diff_percentage=round(random.uniform(0.2, 18.0), 2) if result == SnapshotResult.CHANGED else None,
                    diff_pixel_count=random.randint(50, 12000) if result == SnapshotResult.CHANGED else None,
                    metadata={"browser": "chromium", "viewport": "desktop"},
                )

        self.stdout.write(
            self.style.SUCCESS(
                f"Seeded {n} runs × 2 themes for {stem} on repo {repo.repo_full_name} ({run_type})\n"
                f"Light: /visual_review/repos/{repo.id}/{run_type}/snapshots/{stem}--light\n"
                f"Dark:  /visual_review/repos/{repo.id}/{run_type}/snapshots/{stem}--dark"
            )
        )
