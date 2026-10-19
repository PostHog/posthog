import re

from posthog.models.file_system.starred_products import has_starred_product

from ..facade.contracts import HighlightContext


def human(value: float) -> str:
    size = abs(value)
    if size >= 999_500:
        return f"{value / 1_000_000:.1f}M"
    if size >= 9_950:
        return f"{value / 1000:.0f}k"
    if size >= 999.5:
        return f"{value / 1000:.1f}k"
    return f"{value:.0f}" if size >= 10 or float(value).is_integer() else f"{value:.1f}"


def exact(value: float, decimal_places: int | None = None) -> str:
    if abs(value) >= 100_000:
        return human(value)
    if decimal_places is None:
        decimal_places = 0 if abs(value) >= 100 or float(value).is_integer() else 2
    return f"{value:,.{decimal_places}f}"


def users(count: float) -> str:
    return "1 user" if count == 1 else f"{human(count)} users"


def short(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).replace('"', "").strip()
    text = re.sub(r"'([^']*)'", "‘\\1’", text).replace("'", "’")
    if len(text) <= limit:
        return text
    return text[:limit].rsplit(" ", 1)[0].rstrip(",;:(-– ")


def uses_product(context: HighlightContext, *product_paths: str) -> bool:
    return has_starred_product(context.user, context.team, list(product_paths))
