#!/usr/bin/env python3
"""Refresh the signed-agent entries vendored in bot_signature_agent_directory.py.

Cloudflare's Radar bots directory tracks agents verified through Web Bot Auth
(RFC 9421) and exposes each agent's Signature-Agent key directory URL. The host
of that URL is what agents send in their Signature-Agent request header, which
is the value we classify on. This script pulls the directory and rewrites
products/web_analytics/backend/hogql_queries/bot_signature_agent_directory.py.

Requires a Cloudflare API token (any token works — Radar endpoints just need
authentication) in the CLOUDFLARE_API_TOKEN environment variable.

Usage, from the repo root:
    CLOUDFLARE_API_TOKEN=... python products/web_analytics/scripts/refresh_signature_agents.py

Then review the diff, run the signature agent tests, and commit.
"""

import os
import re
import sys
import json
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

API_BASE = "https://api.cloudflare.com/client/v4/radar/bots"

# Radar category -> (category, traffic_type) in the BotDefinition vocabulary.
# Signed agents without an AI/security category are automation platforms
# (agentic browsers, payment/commerce executors), hence the automation default.
CATEGORY_MAP: dict[str, tuple[str, str]] = {
    "AI_ASSISTANT": ("ai_assistant", "AI Agent"),
    "AI_CRAWLER": ("ai_crawler", "AI Agent"),
    "AI_SEARCH": ("ai_search", "AI Agent"),
    "SECURITY": ("monitoring", "Bot"),
    "MONITORING_AND_ANALYTICS": ("monitoring", "Bot"),
}
DEFAULT_CATEGORY = ("headless_browser", "Automation")

# An AI Agent slug is a filter value people save, so it is pinned in the generated data rather
# than derived at query time from a display name Radar can rename under us. Bots and automation
# share the per-category fallback slugs, so they stay unpinned.
# A name listed here takes the slug the user-agent definition already uses, so one agent does not
# split across two agent_source values depending on which signal caught it.
AGENT_SOURCE_OVERRIDES: dict[str, str] = {
    "Amazon Bedrock AgentCore Browser": "amazon-bedrock-agentcore",
}

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "backend" / "hogql_queries" / "bot_signature_agent_directory.py"


def _get(url: str, token: str) -> dict:
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    # nosemgrep: python.lang.security.audit.dynamic-urllib-use-detected.dynamic-urllib-use-detected (urls are the hardcoded Radar API base plus directory-returned slugs, never user input)
    with urllib.request.urlopen(request, timeout=30) as response:
        payload = json.load(response)
    if not payload.get("success"):
        raise ValueError(f"{url} failed: {payload.get('errors')}")
    return payload["result"]


def fetch_signed_agents(token: str) -> list[dict]:
    bots: list[dict] = []
    offset = 0
    while True:
        page = _get(f"{API_BASE}?limit=500&offset={offset}", token).get("bots", [])
        bots.extend(page)
        if len(page) < 500:
            break
        offset += 500
    # The listing's `kind` field is deprecated, so pre-filtering on it could silently drop a
    # signed agent listed under another kind. Fetch every bot's detail instead; only the
    # detail response carries signatureAgentUrl, which is the actual signed-agent marker.
    details = [_get(f"{API_BASE}/{b['slug']}", token)["bot"] for b in bots]
    agents = [d for d in details if d.get("signatureAgentUrl")]
    if not agents:
        raise ValueError("Radar directory returned no signed agents — API shape may have changed")
    return agents


def agent_source_slug(name: str, traffic_type: str) -> str:
    if traffic_type != "AI Agent":
        return ""
    return AGENT_SOURCE_OVERRIDES.get(name) or re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def to_entry(agent: dict) -> dict[str, str] | None:
    url = agent.get("signatureAgentUrl") or ""
    host = urlparse(url).netloc.lower()
    if not host:
        return None
    radar_category = agent.get("category") or ""
    if radar_category and radar_category not in CATEGORY_MAP:
        # A category-less agent is an automation platform (the default below, by design).
        # A category we have never seen means Radar grew vocabulary — map it, don't guess.
        raise ValueError(f"Unmapped Radar bot category {radar_category!r} for {agent.get('name')!r}")
    category, traffic_type = CATEGORY_MAP.get(radar_category, DEFAULT_CATEGORY)
    # Collapse per-region variants ("... Browser (US East 1)") into one display name
    name = re.sub(r"\s*\([^)]*\)$", "", agent.get("name") or host)
    return {
        "host": host,
        "name": name,
        "category": category,
        "traffic_type": traffic_type,
        "operator": agent.get("operator") or "",
        "documentation_url": agent.get("operatorUrl") or "",
        "agent_source": agent_source_slug(name, traffic_type),
    }


def main() -> int:
    token = os.environ.get("CLOUDFLARE_API_TOKEN")
    if not token:
        print("CLOUDFLARE_API_TOKEN is not set", file=sys.stderr)  # noqa: T201
        return 1

    agents = fetch_signed_agents(token)
    entries = sorted(
        (e for e in (to_entry(a) for a in agents) if e is not None),
        key=lambda e: e["host"],
    )
    skipped = len(agents) - len(entries)
    print(f"{len(agents)} signed agents in directory -> {len(entries)} with a Signature-Agent host ({skipped} skipped)")  # noqa: T201

    lines = []
    for e in entries:
        lines.append("    {")
        for key in ("host", "name", "category", "traffic_type", "operator", "documentation_url", "agent_source"):
            lines.append(f'        "{key}": {json.dumps(e[key])},')
        lines.append("    },")
    body = "\n".join(lines)
    OUTPUT_PATH.write_text(
        "# Generated by products/web_analytics/scripts/refresh_signature_agents.py — do not edit by hand.\n"
        "# Signed agents from Cloudflare's Radar bots directory (bots with a signatureAgentUrl), keyed by\n"
        "# the host of the Signature-Agent key directory each agent sends in its Web Bot Auth headers.\n\n"
        "SIGNATURE_AGENT_ENTRIES: tuple[dict[str, str], ...] = (\n"
        f"{body}\n"
        ")\n"
    )
    print(f"wrote {OUTPUT_PATH}")  # noqa: T201
    return 0


if __name__ == "__main__":
    sys.exit(main())
