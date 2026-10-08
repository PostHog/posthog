import copy
from typing import Any

from django.conf import settings

import requests

# Unlayer renders synchronously; exports of large designs take a few seconds.
EXPORT_TIMEOUT_SECONDS = 30

# Custom block types come from tools the visual editor registers in its customJS
# (frontend/src/scenes/hog-functions/email-templater/custom-tools/). The export API has no access to
# that registration, so it replaces every custom block with a "Missing" placeholder. Each entry maps
# a tool's slug to the option holding the html its editor-side exporter returns, so the block can be
# expanded before the export call. Keep in sync with the registered tools.
CUSTOM_TOOL_HTML_OPTIONS = {"unsubscribe_link": "unsubscribe_link_content"}


class UnlayerError(Exception):
    pass


class UnlayerNotConfiguredError(UnlayerError):
    pass


class UnlayerRenderError(UnlayerError):
    pass


def _dicts(value: Any) -> list[dict[str, Any]]:
    return [item for item in value if isinstance(item, dict)] if isinstance(value, list) else []


def expand_custom_tools(design: dict[str, Any]) -> dict[str, Any]:
    """Return a copy of the design with known custom tool blocks rewritten as plain html blocks.

    The block keeps its id, container values and _meta, so the export renders the same padding and
    class names the editor shows. Only the copy sent to Unlayer is rewritten — the stored design
    keeps the custom block, so the template still opens with the tool's own editing UI.
    """

    expanded = copy.deepcopy(design)
    body = expanded.get("body")
    if not isinstance(body, dict):
        return expanded

    for row in _dicts(body.get("rows")) + _dicts(body.get("headers")) + _dicts(body.get("footers")):
        for column in _dicts(row.get("columns")):
            for content in _dicts(column.get("contents")):
                slug = content.get("slug")
                option = CUSTOM_TOOL_HTML_OPTIONS.get(slug) if isinstance(slug, str) else None
                values = content.get("values")
                if content.get("type") != "custom" or option is None or not isinstance(values, dict):
                    continue
                content["type"] = "html"
                values["html"] = values.get(option) or ""

    return expanded


def render_design_html(design: dict[str, Any]) -> str:
    """Render an Unlayer design to email HTML via the Unlayer export API.

    This is the server-side equivalent of the visual editor's exportHtml() — same renderer, with
    custom tool blocks expanded first, so design-only saves produce the same HTML a human save would.
    """
    if not settings.UNLAYER_API_KEY:
        raise UnlayerNotConfiguredError("UNLAYER_API_KEY is not set")

    try:
        response = requests.post(
            f"{settings.UNLAYER_API_BASE_URL}/v2/export/html",
            auth=(settings.UNLAYER_API_KEY, ""),
            json={"displayMode": "email", "design": expand_custom_tools(design)},
            timeout=EXPORT_TIMEOUT_SECONDS,
        )
    except requests.RequestException as e:
        raise UnlayerRenderError(f"Unlayer export request failed: {e}") from e

    if response.status_code != 200:
        raise UnlayerRenderError(f"Unlayer export returned HTTP {response.status_code}")

    data = response.json().get("data") or {}
    html = data.get("html")
    if not html:
        raise UnlayerRenderError("Unlayer export returned no HTML")
    return html
