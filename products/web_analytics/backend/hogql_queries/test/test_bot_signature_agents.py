import re

from products.web_analytics.backend.hogql_queries.bot_definitions import BOT_DEFINITIONS
from products.web_analytics.backend.hogql_queries.bot_signature_agents import SIGNATURE_AGENT_DEFINITIONS


class TestSignatureAgentDefinitionsDataStructure:
    def test_all_definitions_have_required_fields_and_valid_vocabulary(self):
        valid_types = {"AI Agent", "Bot", "Automation"}
        valid_categories = {
            "ai_crawler",
            "ai_search",
            "ai_assistant",
            "search_crawler",
            "seo_crawler",
            "social_crawler",
            "monitoring",
            "http_client",
            "headless_browser",
        }
        for host, sig_def in SIGNATURE_AGENT_DEFINITIONS.items():
            assert host == host.lower().strip('"'), f"Host {host} must be a normalized lowercase domain"
            assert "://" not in host, f"Host {host} must not include a scheme"
            assert sig_def.name, f"Signature agent definition {host} missing name"
            assert sig_def.operator, f"Signature agent definition {host} missing operator"
            assert sig_def.traffic_type in valid_types, f"Invalid traffic_type for {host}: {sig_def.traffic_type}"
            assert sig_def.category in valid_categories, f"Invalid category for {host}: {sig_def.category}"
            assert re.fullmatch(r"[a-z0-9-]+", sig_def.agent_source_slug), (
                f"Malformed agent_source slug for {host}: {sig_def.agent_source_slug!r}"
            )

    def test_ai_agents_pin_their_agent_source(self):
        # Same rule the UA and IP definitions follow: an AI Agent slug is a filter value people
        # save, so the refresh script pins it in the directory instead of letting a Radar rename
        # move it. Bots and automation share the per-category fallback slugs.
        for host, sig_def in SIGNATURE_AGENT_DEFINITIONS.items():
            if sig_def.traffic_type != "AI Agent":
                continue
            assert sig_def.agent_source, f"AI Agent definition {host} must set agent_source explicitly"

    def test_slugs_do_not_shadow_a_user_agent_slug(self):
        # An agent that both signs its requests and sends a known UA must land on one
        # agent_source, or filtering by it drops whichever half the other signal caught. A
        # signature slug that only extends a UA slug ("...-browser") is that split; pin it to
        # the UA slug in the script's AGENT_SOURCE_OVERRIDES and regenerate.
        ua_slugs = {bot_def.agent_source_slug for bot_def in BOT_DEFINITIONS.values()}
        for host, sig_def in SIGNATURE_AGENT_DEFINITIONS.items():
            slug = sig_def.agent_source_slug
            shadowed = sorted(
                ua_slug
                for ua_slug in ua_slugs
                if ua_slug != slug and (slug.startswith(f"{ua_slug}-") or ua_slug.startswith(f"{slug}-"))
            )
            assert not shadowed, f"agent_source {slug!r} for {host} splits the agent from UA slug(s) {shadowed}"
