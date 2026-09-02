from collections.abc import Callable
from urllib.parse import urlparse

from django.conf import settings
from django.http import HttpRequest, HttpResponse


def surveys_public_origin() -> str:
    return settings.SURVEYS_PUBLIC_URL.rstrip("/")


def is_surveys_public_host(request: HttpRequest) -> bool:
    public_host = urlparse(surveys_public_origin()).netloc
    return bool(public_host and request.get_host().casefold() == public_host.casefold())


def is_surveys_public_origin(request: HttpRequest) -> bool:
    public_url = urlparse(surveys_public_origin())
    request_url = urlparse(request.build_absolute_uri("/"))
    return (request_url.scheme.casefold(), request_url.netloc.casefold()) == (
        public_url.scheme.casefold(),
        public_url.netloc.casefold(),
    )


def surveys_public_url_for_request(request: HttpRequest) -> str:
    return f"{surveys_public_origin()}{request.get_full_path()}"


class SurveyCookieIsolationMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        if is_surveys_public_host(request):
            response.cookies.clear()
        return response
