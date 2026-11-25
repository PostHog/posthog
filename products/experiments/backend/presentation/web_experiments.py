import re
import html
import string
from typing import Any, cast

from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt

import nh3
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.api.pagination import DefaultLimitOffsetPagination, FacadeLimitOffsetPagination, facade_page_response
from posthog.api.routing import PathParameter, TeamAndOrgViewSetMixin
from posthog.api.utils import get_token
from posthog.exceptions import generate_exception_response
from posthog.models import Team, User
from posthog.paging import Page, PageRequest
from posthog.utils_cors import cors_response

from products.experiments.backend.facade import web_experiments as web_experiments_facade
from products.experiments.backend.facade.contracts import (
    WebExperimentConfig,
    WebExperimentNotFound,
    WebExperimentWrite,
    WebExperimentWriteField,
)

_EVENT_HANDLER_MESSAGE = "contains disallowed event handlers (onclick, onerror, etc.)"
_JAVASCRIPT_URL_MESSAGE = "contains disallowed javascript: protocol"
_VBSCRIPT_URL_MESSAGE = "contains disallowed vbscript: protocol"
_DATA_HTML_URL_MESSAGE = "contains disallowed data:text/html"

_XSS_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"<script[^>]*>", re.IGNORECASE), "contains disallowed <script> tags"),
    (re.compile(r"</script>", re.IGNORECASE), "contains disallowed </script> tags"),
    (re.compile(r"[\s/\"']on\w+\s*=", re.IGNORECASE), _EVENT_HANDLER_MESSAGE),
    (re.compile(r"javascript\s*:", re.IGNORECASE), _JAVASCRIPT_URL_MESSAGE),
    (re.compile(r"data\s*:\s*text/html", re.IGNORECASE), _DATA_HTML_URL_MESSAGE),
    (re.compile(r"<iframe[^>]*>", re.IGNORECASE), "contains disallowed <iframe> tags"),
    (re.compile(r"<(object|embed)[^>]*>", re.IGNORECASE), "contains disallowed <object> or <embed> tags"),
]

# Browsers ignore whitespace and control characters in a URL scheme; ";" and "," split SVG "values" lists.
_URL_CONTROL_CHARS = re.compile(r"[\x00-\x20\s]+")
_URL_SCHEMES: list[tuple[str, str]] = [
    ("javascript:", _JAVASCRIPT_URL_MESSAGE),
    ("vbscript:", _VBSCRIPT_URL_MESSAGE),
    ("data:text/html", _DATA_HTML_URL_MESSAGE),
]

_START_TAG_NAME = re.compile(r"<([a-zA-Z][^\t\n\f\r />]*)")
# The HTML5 parse cost is quadratic in nesting depth and in attributes per tag, so these caps bound it per request.
_MAX_START_TAGS_PER_REQUEST = 5000
_MAX_ATTRIBUTE_STARTS_PER_REQUEST = 10000
# Every attribute name starts after whitespace, "/" or a quote, so this also counts text words but never misses an attribute.
_ATTRIBUTE_START = re.compile(r"(?<=[\t\n\f\r /\"'])[^\t\n\f\r />]")
# The HTML5 tokenizer lowercases only ASCII letters in a tag name and replaces NUL with U+FFFD.
_ASCII_LOWER = str.maketrans(string.ascii_uppercase + "\x00", string.ascii_lowercase + "\ufffd")
# nh3 drops elements missing from its allow list with their attributes, and html5ever camel-cases these SVG names.
_SVG_TAG_NAMES = {
    name.lower(): name
    for name in (
        "altGlyph altGlyphDef altGlyphItem animateColor animateMotion animateTransform clipPath feBlend "
        "feColorMatrix feComponentTransfer feComposite feConvolveMatrix feDiffuseLighting feDisplacementMap "
        "feDistantLight feDropShadow feFlood feFuncA feFuncB feFuncG feFuncR feGaussianBlur feImage feMerge "
        "feMergeNode feMorphology feOffset fePointLight feSpecularLighting feSpotLight feTile feTurbulence "
        "foreignObject glyphRef linearGradient radialGradient textPath"
    ).split()
}
_URL_SCHEMES_TO_INSPECT = set(nh3.ALLOWED_URL_SCHEMES) | {"javascript", "vbscript", "data"}


def _find_unsafe_url(value: str, anywhere: bool = False) -> str | None:
    url = _URL_CONTROL_CHARS.sub("", value).lower()
    for scheme, message in _URL_SCHEMES:
        if scheme in url if anywhere else re.search(rf"(?:^|[;,]){re.escape(scheme)}", url):
            return message
    return None


def _find_unsafe_attribute(content: str) -> str | None:
    """
    Parses the content as an HTML5 fragment, as innerHTML does in the browser, and checks every attribute.

    A parser that is not HTML5-compliant can end raw-text elements such as <style> in a different
    place than the browser does, and then it does not see the attributes that the browser creates.
    """
    tag_names: set[str] = set()
    for raw_name in _START_TAG_NAME.findall(content):
        name = raw_name.translate(_ASCII_LOWER)
        tag_names.add(_SVG_TAG_NAMES.get(name, name))

    problems: list[str] = []

    def inspect_attribute(_tag: str, attribute: str, value: str) -> str:
        if attribute.lower().startswith("on"):
            problems.append(_EVENT_HANDLER_MESSAGE)
        problem = _find_unsafe_url(value)
        if problem:
            problems.append(problem)
        return value

    nh3.clean(
        content,
        tags=tag_names,
        clean_content_tags=set(),
        attributes={},
        generic_attribute_prefixes={""},
        attribute_filter=inspect_attribute,
        url_schemes=_URL_SCHEMES_TO_INSPECT,
        link_rel=None,
    )
    return problems[0] if problems else None


def find_unsafe_html(content: str) -> str | None:
    problem = _find_unsafe_attribute(content)
    if problem:
        return problem
    for pattern, message in _XSS_PATTERNS:
        if pattern.search(content):
            return message
    return _find_unsafe_url(html.unescape(content), anywhere=True)


def validate_no_xss(content: str, field_name: str) -> None:
    """
    Raises ValidationError if the content contains markup that can run script.

    The check rejects the content and does not change it, so valid content keeps its original formatting.
    """
    problem = find_unsafe_html(content)
    if problem:
        raise ValidationError(f"{field_name} {problem}")


class WebExperimentsAPISerializer(serializers.Serializer):
    """
    Serializer for the exposed /api/web_experiments endpoint, to be used in posthog-js and for headless APIs.
    """

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(max_length=400)
    # TODO: a client can set the creation time here. The server should own it, so make this field read-only.
    created_at = serializers.DateTimeField(required=False)
    feature_flag_key = serializers.CharField(read_only=True)

    variants = serializers.JSONField(
        help_text="""Variants for the web experiment. Example:

        {
            "control": {
                "transforms": [
                    {
                        "text": "Here comes Superman!",
                        "html": "",
                        "selector": "#page > #body > .header h1"
                    }
                ],
                "conditions": "None",
                "rollout_percentage": 50
            },
        }""",
    )

    # Validates that the `variants` property in the request follows this known object format.
    # {
    #     "name": "create-params-debug",
    #     "variants": {
    #         "control": {
    #             "transforms": [
    #                 {
    #                     "text": "Here comes Superman!",
    #                     "html": "",
    #                     "selector": "#page > #body > .header h1"
    #                 }
    #             ],
    #             "conditions": "None",
    #             "rollout_percentage": 50
    #         },
    #     }
    # }
    def validate(self, attrs):
        variants = attrs.get("variants")
        if variants is None:
            raise ValidationError("Experiment does not have any variants")
        if variants and not isinstance(variants, dict):
            raise ValidationError("Experiment variants should be a dictionary of keys -> transforms")
        if "control" not in variants:
            raise ValidationError("Experiment should contain a control variant")
        start_tag_count = 0
        attribute_start_count = 0
        for name, variant in variants.items():
            if variant.get("rollout_percentage") is None:
                raise ValidationError(f"Experiment variant '{name}' does not have any rollout percentage")
            if name != "control":
                transforms = variant.get("transforms", {})
                for idx, transform in enumerate(transforms):
                    if transform.get("selector") is None:
                        raise ValidationError(
                            f"Experiment transform [${idx}] variant '{name}' does not have a valid selector"
                        )

                    # Validate text and html fields to prevent XSS attacks
                    for field in ("text", "html"):
                        content = transform.get(field)
                        if not isinstance(content, str):
                            continue
                        start_tag_count += len(_START_TAG_NAME.findall(content))
                        attribute_start_count += len(_ATTRIBUTE_START.findall(content))
                        if (
                            start_tag_count > _MAX_START_TAGS_PER_REQUEST
                            or attribute_start_count > _MAX_ATTRIBUTE_STARTS_PER_REQUEST
                        ):
                            raise ValidationError(
                                "Experiment transforms contain too much HTML to check. Split the change into fewer or smaller transforms."
                            )
                        validate_no_xss(content, f"Transform {field} in variant '{name}'")

        return attrs

    def to_write(self) -> WebExperimentWrite:
        data = self.validated_data
        return WebExperimentWrite(
            fields_set=frozenset(cast(WebExperimentWriteField, name) for name in data),
            name=data.get("name"),
            created_at=data.get("created_at"),
            variants=data.get("variants"),
        )


# The second base gives this list the schema of the project-wide default paginator, which states no maximum
# for `limit`.
class WebExperimentsPagination(FacadeLimitOffsetPagination, DefaultLimitOffsetPagination):
    pass


# Codegen routes an endpoint by its x-product. Only the toolbar calls these routes, through its own
# client, and "web_experiments" names no product folder, so the generated clients leave them out.
@extend_schema(extensions={"x-product": "web_experiments"})
class WebExperimentViewSet(TeamAndOrgViewSetMixin, viewsets.GenericViewSet):
    scope_object = "experiment"
    serializer_class = WebExperimentsAPISerializer
    pagination_class = WebExperimentsPagination
    path_parameters = {
        "pk": PathParameter(type=int, description="A unique integer value identifying this web experiment."),
    }
    # No access control resource maps to a web experiment, so no access rule can name one record.
    records_have_object_access_rules = False

    def read_object(self) -> WebExperimentConfig | None:
        return web_experiments_facade.get_web_experiment(
            project_id=self.team.project_id, web_experiment_id=self.kwargs["pk"]
        )

    def list(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        project_id = self.team.project_id

        def fetch(page: PageRequest) -> Page[WebExperimentConfig]:
            return web_experiments_facade.list_web_experiments(project_id=project_id, page=page)

        return facade_page_response(self, fetch)

    def retrieve(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return Response(self.get_serializer(self.get_object()).data)

    def create(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        serializer = WebExperimentsAPISerializer(data=request.data, context=self.get_serializer_context())
        serializer.is_valid(raise_exception=True)
        web_experiment = web_experiments_facade.create_web_experiment(
            team=self.team,
            project_id=self.project_id,
            user=cast(User, request.user),
            write=serializer.to_write(),
            serializer_context=serializer.context,
        )
        return Response(self.get_serializer(web_experiment).data, status=status.HTTP_201_CREATED)

    def update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=False)

    def partial_update(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        return self._update(request, partial=True)

    def _update(self, request: Request, *, partial: bool) -> Response:
        web_experiment = self.get_object()
        serializer = WebExperimentsAPISerializer(
            web_experiment, data=request.data, partial=partial, context=self.get_serializer_context()
        )
        serializer.is_valid(raise_exception=True)
        try:
            web_experiment = web_experiments_facade.update_web_experiment(
                team=self.team,
                user=cast(User, request.user),
                web_experiment_id=web_experiment.id,
                write=serializer.to_write(),
                serializer_context=serializer.context,
            )
        except WebExperimentNotFound:
            raise NotFound()
        return Response(self.get_serializer(web_experiment).data)

    def destroy(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        web_experiment = self.get_object()
        try:
            web_experiments_facade.delete_web_experiment(
                project_id=self.team.project_id, web_experiment_id=web_experiment.id
            )
        except WebExperimentNotFound:
            raise NotFound()
        return Response(status=status.HTTP_204_NO_CONTENT)


@csrf_exempt
@action(methods=["GET"], detail=True)
def web_experiments(request: Request):
    token = get_token(None, request)
    if request.method == "OPTIONS":
        return cors_response(request, HttpResponse(""))
    if not token:
        return cors_response(
            request,
            generate_exception_response(
                "experiments",
                "Project token not provided. You can find your project token in your PostHog project settings.",
                type="authentication_error",
                code="missing_api_key",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
        )

    if request.method == "GET":
        team = Team.objects.get_team_from_cache_or_token(token)
        if team is None:
            return cors_response(
                request,
                generate_exception_response(
                    "experiments",
                    "Project token invalid. You can find your project token in your PostHog project settings.",
                    type="authentication_error",
                    code="invalid_api_key",
                    status_code=status.HTTP_401_UNAUTHORIZED,
                ),
            )

        result = WebExperimentsAPISerializer(
            web_experiments_facade.list_toolbar_web_experiments(team_id=team.id), many=True
        ).data

        return cors_response(request, JsonResponse({"experiments": result}))
