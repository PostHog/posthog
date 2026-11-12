from typing import Any, cast

from django.conf import settings
from django.utils.datastructures import MultiValueDict

from rest_framework import exceptions, status
from rest_framework.response import Response


class ExplainedRefusal(exceptions.APIException):
    """A refusal that tells the caller why it happened and how to fix the request."""

    def __init__(
        self,
        detail: str,
        *,
        code: str,
        why: str,
        fix: str,
        attr: str | None = None,
        status_code: int = status.HTTP_400_BAD_REQUEST,
    ) -> None:
        super().__init__(detail, code)
        self.status_code = status_code
        self.exception_type = "server_error" if status_code >= 500 else "invalid_request"
        self.why, self.fix, self.attr = why, fix, attr

    def explain(self, response: Response) -> None:
        response.data = {**response.data, "attr": self.attr, "why": self.why, "fix": self.fix}


def request_cap() -> str:
    return f"{settings.DATA_UPLOAD_MAX_MEMORY_SIZE // (1024 * 1024)} MB"


def email_body_too_large() -> ExplainedRefusal:
    return ExplainedRefusal(
        f"The request body is over {request_cap()}, so PostHog didn't send the email.",
        code="content_too_large",
        why=f"PostHog reads at most {request_cap()} of request body, so it refused the email without reading it.",
        fix=f"Keep the request under {request_cap()}. To send a large file, link to it from the email body.",
    )


class RequestBodyCapMixin:
    request: Any

    def body_too_large(self) -> ExplainedRefusal:
        raise NotImplementedError

    def refuse_body_over_the_cap(self) -> exceptions.APIException:
        self._empty_the_body_django_refuses_to_read_again()
        return self._denial_from_the_interrupted_permission_checks() or self.body_too_large()

    def _empty_the_body_django_refuses_to_read_again(self) -> None:
        self.request._full_data = self.request._data = {}
        self.request._files = MultiValueDict()

    def _denial_from_the_interrupted_permission_checks(self) -> exceptions.APIException | None:
        try:
            cast(Any, super()).check_permissions(self.request)
        except exceptions.APIException as denied:
            return denied
        return None
