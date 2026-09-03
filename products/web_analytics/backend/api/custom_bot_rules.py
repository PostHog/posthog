from typing import Any
from uuid import uuid4

from drf_spectacular.utils import extend_schema
from rest_framework import serializers, viewsets
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.request import Request
from rest_framework.response import Response

from posthog.schema import CustomBotDefinition

from posthog.api.routing import TeamAndOrgViewSetMixin

from products.web_analytics.backend.hogql_queries.custom_bot_definitions import (
    CIDR_MATCHER,
    CUSTOM_BOT_FIELDS,
    MAX_CUSTOM_BOT_DEFINITIONS,
    PATTERN_MATCHERS,
    assert_patterns_compile,
    compiled_patterns,
    validate_definition,
)

_MATCHERS = (*PATTERN_MATCHERS, CIDR_MATCHER)
_FIELD_LIST = ", ".join(CUSTOM_BOT_FIELDS)


class CustomBotRuleSerializer(serializers.Serializer):
    id = serializers.CharField(read_only=True, help_text="Stable id for the rule. Pass it to the delete endpoint.")
    name = serializers.CharField(
        help_text="Label reported by the `Bot name` property when the rule matches. Also the operator for a rule on a bot PostHog does not know."
    )
    key = serializers.CharField(help_text=f"Event property the rule reads. One of: {_FIELD_LIST}.")
    matcher = serializers.CharField(
        help_text="How `pattern` is compared: 'contains' (case-insensitive substring), 'regex' (RE2), or 'cidr' (an IP network range, only valid with the `$ip` property)."
    )
    pattern = serializers.CharField(
        help_text="Value matched against the property named by `key`. For 'cidr' this is a network range like 192.0.2.0/24."
    )
    category = serializers.CharField(
        required=False,
        allow_blank=True,
        help_text="Reported by the `Traffic category` property. Defaults to 'custom'. A built-in category such as ai_crawler or search_crawler relabels the traffic type too.",
    )

    def validate_key(self, value: str) -> str:
        if value not in CUSTOM_BOT_FIELDS:
            raise serializers.ValidationError(f"Must be one of: {_FIELD_LIST}.")
        return value

    def validate_matcher(self, value: str) -> str:
        if value not in _MATCHERS:
            raise serializers.ValidationError(f"Must be one of: {', '.join(_MATCHERS)}.")
        return value


class CustomBotRuleViewSet(TeamAndOrgViewSetMixin, viewsets.ViewSet):
    """A project's own bot rules, stored on the team and read by `Is bot`, `Bot name`, and the
    traffic-type properties everywhere HogQL runs. A rule extends the built-in bot list rather than
    replacing it, so a project can flag a scraper PostHog does not know about."""

    scope_object = "web_analytics"
    serializer_class = CustomBotRuleSerializer

    def _definitions(self) -> list[dict[str, Any]]:
        return list((self.team.modifiers or {}).get("customBotDefinitions") or [])

    def _save(self, definitions: list[dict[str, Any]]) -> None:
        # Merge so replacing the rules never wipes another modifier the team relies on.
        modifiers = dict(self.team.modifiers or {})
        modifiers["customBotDefinitions"] = definitions
        self.team.modifiers = modifiers
        self.team.save(update_fields=["modifiers"])

    @extend_schema(
        operation_id="web_analytics_bot_rules_list",
        summary="List custom bot rules",
        description="The project's own bot rules, in the order they are checked at query time.",
        responses={200: CustomBotRuleSerializer(many=True)},
    )
    def list(self, request: Request, **kwargs: Any) -> Response:
        return Response(self._definitions())

    @extend_schema(
        operation_id="web_analytics_bot_rules_create",
        summary="Create a custom bot rule",
        description="Add one bot rule to the project. The pattern is rejected if it cannot run, because a broken rule would break every query that classifies traffic for the project.",
        request=CustomBotRuleSerializer,
        responses={201: CustomBotRuleSerializer},
    )
    def create(self, request: Request, **kwargs: Any) -> Response:
        serializer = CustomBotRuleSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        definitions = self._definitions()
        if len(definitions) >= MAX_CUSTOM_BOT_DEFINITIONS:
            raise ValidationError(f"You can define at most {MAX_CUSTOM_BOT_DEFINITIONS} bots.")

        rule = {
            "id": str(uuid4()),
            "name": data["name"],
            "key": data["key"],
            "matcher": data["matcher"],
            "pattern": data["pattern"],
        }
        if data.get("category"):
            rule["category"] = data["category"]

        try:
            definition = CustomBotDefinition(**rule)
            validate_definition(definition)
            assert_patterns_compile(compiled_patterns([definition]))
        except ValueError as error:
            raise ValidationError(str(error))

        self._save([*definitions, rule])
        return Response(rule, status=201)

    @extend_schema(
        operation_id="web_analytics_bot_rules_destroy",
        summary="Delete a custom bot rule",
        description="Remove one bot rule by its id. The built-in bot list is unaffected.",
        responses={204: None},
    )
    def destroy(self, request: Request, pk: str | None = None, **kwargs: Any) -> Response:
        definitions = self._definitions()
        remaining = [definition for definition in definitions if definition.get("id") != pk]
        if len(remaining) == len(definitions):
            raise NotFound("No such bot rule.")
        self._save(remaining)
        return Response(status=204)
