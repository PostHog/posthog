from typing import Any

from django.conf import settings

import requests

# Unlayer renders synchronously; exports of large designs take a few seconds.
EXPORT_TIMEOUT_SECONDS = 30


class UnlayerError(Exception):
    pass


class UnlayerNotConfiguredError(UnlayerError):
    pass


class UnlayerRenderError(UnlayerError):
    pass


def render_design_html(design: dict[str, Any]) -> str:
    """Render an Unlayer design to email HTML via the Unlayer export API.

    This is the server-side equivalent of the visual editor's exportHtml() —
    same renderer, so design-only saves produce the same HTML a human save would.
    """
    if not settings.UNLAYER_API_KEY:
        raise UnlayerNotConfiguredError("UNLAYER_API_KEY is not set")

    try:
        response = requests.post(
            f"{settings.UNLAYER_API_BASE_URL}/v2/export/html",
            auth=(settings.UNLAYER_API_KEY, ""),
            json={"displayMode": "email", "design": design},
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
