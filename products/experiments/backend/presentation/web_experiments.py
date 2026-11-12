import re
import html
import string
from typing import Any

from django.http import HttpResponse, JsonResponse
from django.utils.text import slugify
from django.views.decorators.csrf import csrf_exempt

import nh3
from drf_spectacular.utils import extend_schema
from nanoid import generate
from rest_framework import serializers, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request

from posthog.api.routing import TeamAndOrgViewSetMixin
from posthog.api.utils import get_token
from posthog.event_usage import report_user_action
from posthog.exceptions import generate_exception_response
from posthog.models import Team
from posthog.utils_cors import cors_response

from products.experiments.backend.models.experiment import Experiment
from products.experiments.backend.models.web_experiment import WebExperiment
from products.feature_flags.backend.facade.api import create_flag, update_flag
from products.feature_flags.backend.facade.filters import replace_variant_distribution

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


class WebExperimentsAPISerializer(serializers.ModelSerializer):
    """
    Serializer for the exposed /api/web_experiments endpoint, to be used in posthog-js and for headless APIs.
    """

    feature_flag_key = serializers.CharField(source="feature_flag.key", read_only=True)

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

    class Meta:
        model = WebExperiment
        fields = ["id", "name", "created_at", "feature_flag_key", "variants"]

    def to_representation(self, instance):
        """
        Override to return variants with actual rollout percentages from the feature flag.
        """
        data = super().to_representation(instance)

        # Get corrected variants with actual feature flag rollout percentages
        data["variants"] = self._get_corrected_variants(instance)

        return data

    def _get_corrected_variants(self, obj):
        """
        Returns ALL variants from the feature flag with actual rollout percentages,
        combined with transforms from the experiment variants where available.
        """
        if not obj.feature_flag:
            return obj.variants or {}

        variants_list = obj.feature_flag.variants

        # If no feature flag variants, fall back to experiment variants
        if not variants_list:
            return obj.variants or {}

        # Build result using ALL feature flag variants as the source of truth
        result_variants = {}
        experiment_variants = obj.variants or {}

        for variant in variants_list:
            key = variant.get("key")
            rollout_percentage = variant.get("rollout_percentage", 0)
            if key:
                # Start with feature flag data
                result_variants[key] = {"rollout_percentage": rollout_percentage}

                # Add experiment-specific data (transforms, etc.) if available
                if key in experiment_variants:
                    experiment_data = experiment_variants[key].copy()
                    # Remove rollout_percentage from experiment data to avoid conflicts
                    experiment_data.pop("rollout_percentage", None)
                    # Merge experiment data into result
                    result_variants[key].update(experiment_data)

        return result_variants

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

    def create(self, validated_data: dict[str, Any]) -> WebExperiment:
        create_params = {
            "name": validated_data.get("name", ""),
            "description": "",
            "type": "web",
            "created_by": self.context["request"].user,
            "variants": validated_data.get("variants", None),
        }

        filters = {
            "groups": [{"properties": [], "rollout_percentage": 100}],
            "multivariate": self.get_variants_for_feature_flag(validated_data),
        }

        team = self.context["get_team"]()
        feature_flag = create_flag(
            {
                "key": self.get_feature_flag_name(validated_data.get("name", "")),
                "name": f"Feature Flag for Experiment {validated_data['name']}",
                "filters": filters,
                "active": False,
                "creation_context": "web_experiments",
            },
            team=team,
            user=self.context["request"].user,
            request=self.context["request"],
        )

        # Get team's default stats method setting
        from posthog.models.team.extensions import get_or_create_team_extension

        from products.experiments.backend.models.team_experiments_config import TeamExperimentsConfig

        config = get_or_create_team_extension(team, TeamExperimentsConfig)
        default_method = config.default_experiment_stats_method or "bayesian"
        stats_config = {
            "method": default_method,
        }

        experiment = WebExperiment.objects.create(
            team_id=self.context["team_id"], feature_flag=feature_flag, **create_params, stats_config=stats_config
        )

        report_user_action(
            self.context["request"].user,
            "experiment created",
            {**experiment.get_analytics_metadata(), "creation_mode": "new"},
            team=team,
            request=self.context["request"],
        )

        return experiment

    def update(self, instance: WebExperiment, validated_data: dict[str, Any]) -> WebExperiment:
        variants = validated_data.get("variants", None)
        if variants is not None and isinstance(variants, dict):
            feature_flag = instance.feature_flag
            filters = replace_variant_distribution(
                feature_flag.get_filters(),
                self.get_variants_for_feature_flag(validated_data)["variants"],
            )
            update_flag(
                feature_flag,
                {"filters": filters},
                team=self.context["get_team"](),
                user=self.context["request"].user,
                request=self.context["request"],
            )

        instance = super().update(instance, validated_data)
        return instance

    def get_variants_for_feature_flag(self, validated_data: dict[str, Any]):
        variant_names = []
        variants = validated_data.get("variants", None)
        if variants is not None and isinstance(variants, dict):
            for variant, transforms in variants.items():
                variant_names.append({"key": variant, "rollout_percentage": transforms.get("rollout_percentage", 0)})
        return {"variants": variant_names}

    def get_feature_flag_name(self, experiment_name: str) -> str:
        random_id = generate("1234567890abcdef", 10)
        prefix = experiment_name.replace(" ", "-").lower() + "-web-experiment-feature"
        feature_flag_key = slugify(f"{prefix}-{random_id}")
        return feature_flag_key


# Codegen routes an endpoint by its x-product. Only the toolbar calls these routes, through its own
# client, and "web_experiments" names no product folder, so the generated clients leave them out.
@extend_schema(extensions={"x-product": "web_experiments"})
class WebExperimentViewSet(TeamAndOrgViewSetMixin, viewsets.ModelViewSet):
    scope_object = "experiment"
    serializer_class = WebExperimentsAPISerializer
    queryset = WebExperiment.objects.select_related("feature_flag", "created_by").order_by("-created_at", "-id").all()

    def safely_get_queryset(self, queryset):
        if self.action == "list":
            queryset = queryset.filter(deleted=False)
        return queryset


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
            WebExperiment.objects.filter(team_id=team.id)
            .exclude(archived=True)
            .exclude(deleted=True)
            .filter(status__in=[Experiment.Status.DRAFT, Experiment.Status.RUNNING])
            .select_related("feature_flag", "created_by")
            .order_by("-created_at"),
            many=True,
        ).data

        return cors_response(request, JsonResponse({"experiments": result}))
