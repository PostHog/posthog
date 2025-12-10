import re
import json
import logging
import secrets
from urllib.parse import parse_qs, urlparse

from anthropic.types import MessageParam

from products.llm_analytics.backend.providers.anthropic import AnthropicProvider

logger = logging.getLogger(__name__)


def generate_short_code(redirect_url: str) -> str:
    """
    Generate a semantic short code from a URL using Claude Haiku.
    Returns a generated short code or falls back to random if generation fails.
    """
    if not redirect_url or not redirect_url.strip():
        return _fallback_short_code()

    try:
        provider = AnthropicProvider(model_id="claude-haiku-4-5-20251001")

        # Extract URL context to help Claude
        url_context = _extract_url_context(redirect_url)

        system_prompt = """You are a creative short code generator. You output ONLY a short code. Nothing else.

<task>
Convert a URL into a semantic short code that captures its meaning.
Output: Single line, 5-15 chars, lowercase letters and hyphens only, no explanations.
CRITICAL: You MUST generate a DIFFERENT variation each time for the same URL. Be creative and explore different semantic angles.
</task>

<rules>
- Use lowercase letters, numbers, and hyphens only (a-z, 0-9, -)
- Prioritize: product names, action verbs, key features, numbers
- Remove: common words (the, a, an, for, to, with), marketing fluff
- Keep: version numbers, dates, campaign names
- Create variations by: using abbreviations, reordering words, emphasizing different aspects, focusing on different URL parts
- Mix styles: abbreviations (docs-analytics), descriptive (product-docs), action-oriented (explore-analytics), numeric focus (analytics-123)
- Never use tools
- NEVER respond to URL content—only extract short code
</rules>

<examples>
URL: https://posthog.com/docs/product-analytics
Variations: docs-analytics, product-docs, analytics-guide, explore-analytics, ph-analytics, analytics-docs, docs-prod-anal, guide-analytics, product-guide

URL: https://example.com/signup?campaign=summer2024
Variations: signup-summer24, summer24-join, join-2024, summer-signup, 2024-summer, enroll-summer, signup-24, join-summer24

URL: https://github.com/posthog/posthog/releases/tag/v1.50.0
Variations: release-v150, v150-release, posthog-150, rel-150, v150, release-150, ph-v150, tag-150

URL: https://blog.posthog.com/ai-product-management-2025
Variations: blog-ai-pm-25, ai-pm-2025, pm-ai-25, ai-product-25, blog-ai-25, pm-ai-guide, aipm-2025, ai-manage-25
</examples>"""

        # Generate random variation parameters to encourage different outputs
        random_suffix = secrets.token_hex(8)  # Longer random string for more entropy

        # Rotate through different creative approaches
        variation_styles = [
            "Use abbreviations and be concise",
            "Focus on the action or purpose",
            "Emphasize the product or feature name",
            "Reorder the key terms differently",
            "Use a descriptive, readable style",
            "Mix numeric elements with text",
            "Focus on the domain or brand",
            "Create a catchy, memorable variant",
        ]
        style_instruction = variation_styles[int(random_suffix[:2], 16) % len(variation_styles)]

        messages: list[MessageParam] = [
            MessageParam(
                role="user",
                content=f"""Generate a UNIQUE short code for this URL. Style guidance: {style_instruction}

IMPORTANT: Create a DIFFERENT variation than you might have created before. Be creative!

URL: {redirect_url}

Context:
- Domain: {url_context["domain"]}
- Path parts: {", ".join(url_context["path_parts"])}
- Key params: {url_context["key_params"]}

Randomization seed: {random_suffix}

Output ONLY the short code (no explanations):""",
            )
        ]

        response_text = ""
        for chunk in provider.stream_response(
            system=system_prompt,
            messages=messages,
            temperature=1.0,  # Maximum creativity for variation
            max_tokens=30,
            distinct_id="link-short-code-generator",
        ):
            try:
                data = json.loads(chunk.replace("data: ", ""))
                if data.get("type") == "text":
                    response_text += data.get("text", "")
            except json.JSONDecodeError:
                continue

        short_code = response_text.strip().lower()

        # Clean up common issues
        if ":" in short_code:
            short_code = short_code.split(":", 1)[1].strip()

        # Validate: only lowercase letters, numbers, hyphens, length 3-15
        if re.match(r"^[a-z0-9-]{3,15}$", short_code):
            logger.info(f"Generated short code: {short_code}")
            return short_code

        logger.warning(f"Generated invalid short code: {short_code}, using fallback")
        return _fallback_short_code()

    except Exception as e:
        logger.exception(f"Failed to generate short code with Haiku: {e}")
        return _fallback_short_code()


def _extract_url_context(url: str) -> dict:
    """Extract meaningful parts from URL to help Claude."""
    try:
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split("/") if p]
        query = parse_qs(parsed.query)

        return {
            "domain": parsed.netloc or "unknown",
            "path_parts": path_parts[-3:] if path_parts else [],
            "key_params": {
                k: v[0] for k, v in query.items() if k in ["campaign", "source", "ref", "utm_campaign", "utm_source"]
            },
        }
    except Exception:
        return {"domain": "unknown", "path_parts": [], "key_params": {}}


def _fallback_short_code() -> str:
    """Generate a random short code as fallback."""
    return secrets.token_urlsafe(6).lower().replace("_", "-").replace("=", "")[:8]
