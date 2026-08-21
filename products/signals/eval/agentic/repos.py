from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OSSRepo:
    key: str
    full_name: str
    primary_language: str
    domain: str

    @property
    def repo(self) -> str:
        return self.full_name.split("/", 1)[1]


REGISTRY: dict[str, OSSRepo] = {
    repo.key: repo
    for repo in (
        OSSRepo("cal", "calcom/cal.com", "TypeScript", "Open-source booking and scheduling platform."),
        OSSRepo("supabase", "supabase/supabase", "TypeScript", "Hosted Postgres, auth, storage, and realtime."),
        OSSRepo("n8n", "n8n-io/n8n", "TypeScript", "Node-based workflow automation platform."),
        OSSRepo("excalidraw", "excalidraw/excalidraw", "TypeScript", "Hand-drawn-style collaborative whiteboard."),
        OSSRepo("strapi", "strapi/strapi", "JavaScript", "Headless CMS with an admin panel and content API."),
        OSSRepo(
            "posthog-js",
            "posthog/posthog-js",
            "TypeScript",
            "PostHog browser SDK for analytics, autocapture, and session replay.",
        ),
        OSSRepo(
            "posthog-python",
            "posthog/posthog-python",
            "Python",
            "PostHog server-side Python SDK for capture, feature flags, and LLM analytics.",
        ),
    )
}
