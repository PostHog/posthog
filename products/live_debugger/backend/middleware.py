"""Middleware that opens a hogtrace request scope around each Django request.

The scope provides probes with a per-request `$req.*` store backed by a
thread-local context. Without it, probes that read or write request-scoped
variables would have no place to persist state across the multiple probes
that fire within a single request.

Place this near the top of MIDDLEWARE so the scope outlives everything
inner code might want to instrument.
"""

from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from hogtrace.context import new_context


class HogtraceRequestScopeMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        with new_context():
            return self.get_response(request)
