"""What a valid `scanner_config` looks like for each scanner type.

Its own module because both the API serializers and Max validate a config before saving or scanning
with it, and neither should import the other."""

from typing import Any, cast

from pydantic import ValidationError as PydanticValidationError

from posthog.models.user import User

from products.replay_vision.backend.models.replay_scanner import ScannerType
from products.replay_vision.backend.tags import slugify_tag
from products.replay_vision.backend.temporal.scanners import validate_scanner_config

MAX_PROMPT_LENGTH = 20_000
MAX_TAGS = 100
MAX_TAG_LENGTH = 100


def scanner_config_error(scanner_type: ScannerType, scanner_config: Any) -> str | None:
    if not isinstance(scanner_config, dict):
        return "Scanner configuration must be a JSON object."
    prompt = scanner_config.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return "Prompt is required."
    if len(prompt) > MAX_PROMPT_LENGTH:
        return f"Prompt can be at most {MAX_PROMPT_LENGTH:,} characters."
    if scanner_type == ScannerType.CLASSIFIER:
        tags = scanner_config.get("tags") or []
        if len(tags) == 0:
            return "Add at least one category."
        if len(tags) > MAX_TAGS:
            return f"You can have at most {MAX_TAGS} categories."
        if any(not isinstance(t, str) or not t.strip() for t in tags):
            return "Categories can't be blank."
        if any(len(t) > MAX_TAG_LENGTH for t in tags):
            return f"Categories can be at most {MAX_TAG_LENGTH} characters."
        # Uniqueness on the slug, since filtering/stripping/search all compare slugified tags downstream.
        slugged: dict[str, str] = {}
        for t in tags:
            slug = slugify_tag(t)
            if not slug:
                return "Categories must contain letters or numbers."
            if slug in slugged:
                return f"Categories must be unique: '{slugged[slug]}' and '{t}' are the same category."
            slugged[slug] = t
    if scanner_type == ScannerType.SCORER:
        scale = scanner_config.get("scale")
        if not isinstance(scale, dict):
            return "Scale is required."
        min_v, max_v = scale.get("min"), scale.get("max")
        if not isinstance(min_v, (int, float)) or not isinstance(max_v, (int, float)):
            return "Scale min and max must be numbers."
        if min_v >= max_v:
            return "Scale max must be greater than min."
    try:
        scanner = validate_scanner_config(scanner_config=scanner_config, scanner_type=scanner_type)
    except (ValueError, PydanticValidationError):
        return "Scanner configuration is invalid."
    # The pydantic models ignore extra keys — reject here so typos and junk don't snapshot onto every observation.
    unknown = set(scanner_config) - set(type(scanner).model_fields)
    if unknown:
        return f"Unknown scanner configuration keys: {', '.join(sorted(unknown))}."
    return None


def acting_user(context: dict[str, Any]) -> User:
    """Who a serializer write is on behalf of.

    Max has no DRF request, so it passes `user` in the context directly. Everything else that reads the
    request stays optional, since `report_user_action` treats a missing one as "no request-derived
    properties" rather than an error.
    """
    request = context.get("request")
    return cast(User, context.get("user") or (request.user if request is not None else None))
