import re
import base64
import asyncio
import logging
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime, timedelta
from typing import Literal, cast
from urllib.parse import quote

from django.conf import settings
from django.db.models import BooleanField, Case, Value, When
from django.utils import timezone

import requests
from asgiref.sync import async_to_sync
from pydantic import BaseModel, JsonValue
from redis.exceptions import LockNotOwnedError
from temporalio.api.enums.v1 import PendingActivityState
from temporalio.service import RPCError, RPCStatusCode

from posthog.egress.github.transport import github_request
from posthog.egress.limiter.policies import Priority
from posthog.temporal.common.client import async_connect

from products.tasks.backend.constants import DEV_STACK_IMAGE_NAME
from products.tasks.backend.models import SandboxCustomImage
from products.tasks.backend.redis import get_tasks_cache, get_tasks_stream_redis_sync

logger = logging.getLogger(__name__)

IMAGE_NAMES = ("base", "notebook", "streamlit", "pi", "autoresearch", "vm")
MAX_IMAGES = 1000
CACHE_SECONDS = 60


class SourceSnapshot(BaseModel):
    status: Literal["ok", "error", "refreshing"]
    observed_at: datetime | None = None
    data: JsonValue = None


class CustomImageStatus(BaseModel):
    id: str
    team_id: int
    status: str
    version: int
    base_image_reference: str | None
    base_image_refresh_reference: str | None
    has_published_image: bool
    has_error: bool
    has_spec: bool
    updated_at: datetime
    workflow_url: str


def workflow_url(workflow_id: str) -> str:
    return (
        f"{settings.TEMPORAL_UI_HOST.rstrip('/')}/namespaces/{quote(settings.TEMPORAL_NAMESPACE, safe='')}"
        f"/workflows/{quote(workflow_id, safe='')}"
    )


class InfrastructureStatus:
    def _json(self, url: str, *, headers: dict[str, str] | None = None) -> requests.Response:
        response = requests.get(url, headers=headers, timeout=5)
        response.raise_for_status()
        return response

    def _github(self, path: str) -> dict[str, JsonValue]:
        headers = {"Authorization": f"Bearer {settings.GITHUB_TOKEN}"} if settings.GITHUB_TOKEN else {}
        response = github_request(
            "GET",
            f"https://api.github.com/repos/PostHog/posthog/{path}",
            source="tasks_infrastructure_admin",
            priority=Priority.NORMAL,
            headers=headers,
            timeout=5,
        )
        response.raise_for_status()
        return cast(dict[str, JsonValue], response.json())

    def package(self) -> JsonValue:
        package = self._json("https://registry.npmjs.org/@posthog/agent/latest").json()
        return {"version": package["version"], "revision": package.get("gitHead")}

    def build_jobs(self, run_id: JsonValue) -> list[JsonValue]:
        response = self._github(f"actions/runs/{int(str(run_id))}/jobs?per_page=100")
        names = {
            "Build and push Tasks Sandbox container image": "Base images",
            "Build and push the derived sandbox images": "Derived images",
        }
        return [
            {
                "name": names[str(job["name"])],
                "status": job.get("status"),
                "conclusion": job.get("conclusion"),
                "promotion": next(
                    (
                        step.get("conclusion") or step.get("status")
                        for step in cast(list[dict[str, JsonValue]], job.get("steps", []))
                        if step.get("name") == "Promote the smoked base image to :master"
                    ),
                    None,
                ),
            }
            for job in cast(list[dict[str, JsonValue]], response["jobs"])
            if job.get("name") in names
        ]

    def release(self) -> JsonValue:
        content = self._github("contents/products/tasks/backend/sandbox/images/Dockerfile.sandbox-base?ref=master")
        dockerfile = base64.b64decode(str(content["content"])).decode()
        pin = re.search(r"^ARG AGENT_VERSION=(\S+)", dockerfile, re.MULTILINE)
        if pin is None:
            raise ValueError("Missing agent version")
        runs = self._github("actions/workflows/cd-sandbox-base-image.yml/runs?branch=master&event=push&per_page=5")
        return {
            "pin": pin.group(1),
            "runs": [
                {
                    **{
                        key: run.get(key)
                        for key in ("id", "head_sha", "status", "conclusion", "html_url", "created_at")
                    },
                    "build_jobs": self.build_jobs(run["id"]),
                }
                for run in cast(list[dict[str, JsonValue]], runs["workflow_runs"])
            ],
        }

    def registry(self, name: str) -> JsonValue:
        repo = f"posthog/posthog-sandbox-{name}"
        token = self._json(f"https://ghcr.io/token?service=ghcr.io&scope=repository:{repo}:pull").json()["token"]
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.oci.image.index.v1+json, application/vnd.oci.image.manifest.v1+json, application/vnd.docker.distribution.manifest.list.v2+json, application/vnd.docker.distribution.manifest.v2+json",
        }
        response = self._json(f"https://ghcr.io/v2/{repo}/manifests/master", headers=headers)
        digest = response.headers["Docker-Content-Digest"]
        platforms: list[JsonValue] = []
        for entry in response.json().get("manifests", []):
            arch = entry.get("platform", {}).get("architecture")
            if arch not in ("amd64", "arm64"):
                continue
            manifest = self._json(f"https://ghcr.io/v2/{repo}/manifests/{entry['digest']}", headers=headers).json()
            config = self._json(
                f"https://ghcr.io/v2/{repo}/blobs/{manifest['config']['digest']}", headers=headers
            ).json()
            labels = config.get("config", {}).get("Labels", {})
            platforms.append(
                {
                    "arch": arch,
                    "digest": entry["digest"],
                    "version": labels.get("com.posthog.sandbox.agent-version"),
                    "revision": labels.get("org.opencontainers.image.revision"),
                    "base_revision": labels.get("com.posthog.sandbox.base-revision"),
                    "inputs_digest": labels.get("com.posthog.sandbox.inputs-digest"),
                }
            )
        if {cast(dict[str, JsonValue], platform)["arch"] for platform in platforms} != {"amd64", "arm64"}:
            raise ValueError("Incomplete image platforms")
        return {"name": name, "reference": f"ghcr.io/{repo}@{digest}", "platforms": platforms}

    def custom_images(self) -> JsonValue:
        rows = list(
            SandboxCustomImage.objects.unscoped()
            .exclude(status=SandboxCustomImage.Status.ARCHIVED)
            .annotate(
                has_published_image=Case(
                    When(modal_image_name="", then=Value(False)), default=Value(True), output_field=BooleanField()
                ),
                has_error=Case(When(error="", then=Value(False)), default=Value(True), output_field=BooleanField()),
                has_spec=Case(When(spec={}, then=Value(False)), default=Value(True), output_field=BooleanField()),
            )
            .order_by("id")
            .values(
                "id",
                "team_id",
                "status",
                "version",
                "base_image_reference",
                "base_image_refresh_reference",
                "has_published_image",
                "has_error",
                "has_spec",
                "updated_at",
            )[: MAX_IMAGES + 1]
        )
        images: list[JsonValue] = [
            CustomImageStatus(
                **{**row, "id": str(row["id"])}, workflow_url=workflow_url(f"build-sandbox-image-{row['id']}")
            ).model_dump(mode="json")
            for row in rows[:MAX_IMAGES]
        ]
        return {"images": images, "truncated": len(rows) > MAX_IMAGES, "limit": MAX_IMAGES}

    def dev_stack(self) -> JsonValue:
        reference = get_tasks_cache().get(f"tasks:dev-stack-image:baked-base-reference:{DEV_STACK_IMAGE_NAME}")
        return {
            "name": DEV_STACK_IMAGE_NAME,
            "base_image_reference": reference if isinstance(reference, str) else None,
            "workflow_url": workflow_url(f"bake-dev-stack-image-{DEV_STACK_IMAGE_NAME}"),
        }

    @async_to_sync
    async def workflow(self, workflow_id: str) -> JsonValue:
        client = await asyncio.wait_for(async_connect(), timeout=5)
        try:
            description = await client.get_workflow_handle(workflow_id).describe(rpc_timeout=timedelta(seconds=5))
        except RPCError as error:
            if error.status == RPCStatusCode.NOT_FOUND:
                return {"status": "not_found", "activities": [], "url": workflow_url(workflow_id)}
            raise
        return {
            "status": description.status.name.lower() if description.status else "unknown",
            "run_id": description.run_id,
            "started_at": description.start_time.isoformat() if description.start_time else None,
            "closed_at": description.close_time.isoformat() if description.close_time else None,
            "url": f"{workflow_url(workflow_id)}/{quote(description.run_id, safe='')}/history",
            "activities": [
                {
                    "name": activity.activity_type.name,
                    "state": PendingActivityState.Name(activity.state).removeprefix("PENDING_ACTIVITY_STATE_").lower(),
                    "attempt": activity.attempt,
                }
                for activity in description.raw_description.pending_activities
            ],
        }

    def read(self, name: str, loader: Callable[[], JsonValue]) -> SourceSnapshot:
        cache = get_tasks_cache()
        key = f"tasks:infrastructure-admin:v1:{name}"
        cached = cache.get(key)
        previous = SourceSnapshot.model_validate_json(cached) if isinstance(cached, str) else None
        if (
            previous
            and previous.observed_at
            and timezone.now() - previous.observed_at < timedelta(seconds=CACHE_SECONDS)
        ):
            return previous
        lock = get_tasks_stream_redis_sync(use_dedicated=bool(settings.TASKS_REDIS_URL)).lock(
            f"{key}:lock", timeout=90, blocking=False
        )
        if not lock.acquire():
            return (
                previous.model_copy(update={"status": "refreshing"})
                if previous
                else SourceSnapshot(status="refreshing")
            )
        try:
            data = loader()
            if not lock.owned():
                return (
                    previous.model_copy(update={"status": "refreshing"})
                    if previous
                    else SourceSnapshot(status="refreshing")
                )
            snapshot = SourceSnapshot(status="ok", observed_at=timezone.now(), data=data)
            cache.set(key, snapshot.model_dump_json(), timeout=3600)
            return snapshot
        except Exception:
            logger.exception("tasks_infrastructure_source_failed", extra={"source": name})
            return previous.model_copy(update={"status": "error"}) if previous else SourceSnapshot(status="error")
        finally:
            with suppress(LockNotOwnedError):
                lock.release()
