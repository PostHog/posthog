import re
from typing import Any

from rest_framework import serializers
from rest_framework.settings import api_settings

from posthog.dataclasses import frozen

from products.messaging.backend.facade.contracts import TEMPLATE_KEY_MAX_LENGTH, TEMPLATE_KEY_PATTERN


class TemplateErrorSerializer(serializers.Serializer):
    type = serializers.CharField(help_text="Error class, such as `invalid_request`.")
    code = serializers.CharField(help_text="Stable error code to branch on, such as `invalid_template_key`.")
    detail = serializers.CharField(help_text="What went wrong.")
    attr = serializers.CharField(allow_null=True, help_text="The request field the error is about, if any.")
    why = serializers.CharField(required=False, help_text="Why PostHog refuses the request.")
    fix = serializers.CharField(required=False, help_text="What to change before you retry.")
    docs_url = serializers.URLField(required=False, help_text="Documentation for this error code.")


TRANSACTIONAL_EMAIL_DOCS_URL = "https://posthog.com/docs/workflows/transactional-email-api"


@frozen
class TemplateRefusal:
    code: str
    detail: str
    attr: str | None
    why: str
    fix: str
    type: str = "invalid_request"

    @property
    def docs_url(self) -> str:
        return f"{TRANSACTIONAL_EMAIL_DOCS_URL}#{self.code}"


@frozen
class FieldError:
    attr: str | None
    message: str


def invalid_template_key(key: object, attr: str = "key") -> TemplateRefusal | None:
    if isinstance(key, str) and len(key) <= TEMPLATE_KEY_MAX_LENGTH and re.fullmatch(TEMPLATE_KEY_PATTERN, key):
        return None
    return TemplateRefusal(
        code="invalid_template_key",
        detail=f"The key can have at most {TEMPLATE_KEY_MAX_LENGTH} letters, digits, hyphens (-) and underscores (_).",
        attr=attr,
        why="Code names the template by its key in every project, so the key must stay the same.",
        fix="Use a key like `password-reset`.",
    )


def invalid_request(errors: Any, *, why: str, retry: str) -> TemplateRefusal:
    error = first_field_error(errors)
    if error.attr is None:
        return TemplateRefusal(
            code="invalid_request",
            detail=error.message,
            attr=None,
            why=why,
            fix=f"Send the body as a JSON object and {retry}.",
        )
    return TemplateRefusal(
        code="invalid_request",
        detail=f"{error.attr}: {error.message}",
        attr=error.attr,
        why=why,
        fix=f"Fix `{error.attr}` and {retry}.",
    )


def first_field_error(errors: Any, path: tuple[str, ...] = ()) -> FieldError:
    if isinstance(errors, dict):
        field, nested = next(iter(errors.items()))
        field_path = path if field == api_settings.NON_FIELD_ERRORS_KEY else (*path, str(field))
        return first_field_error(nested, field_path)
    if isinstance(errors, list) and errors and not isinstance(errors[0], str):
        return first_field_error(errors[0], path)
    return FieldError(attr="__".join(path) or None, message=str(errors[0] if isinstance(errors, list) else errors))
