from typing import Any

from rest_framework import serializers
from rest_framework_dataclasses.serializers import DataclassSerializer

from ..facade.contracts import (
    DEFAULT_ELEMENT_PATH_STEPS,
    DEFAULT_ELEMENT_PATHS,
    MAX_ELEMENT_PATH_STEPS,
    MAX_ELEMENT_PATHS,
    MAX_ELEMENT_PATHS_RANGE_DAYS,
    MAX_SELECTOR_LENGTH,
    MAX_TEXT_LENGTH,
    MAX_URL_LENGTH,
    ElementClickStep,
    ElementPath,
    ElementPathNode,
    ElementPathsQuery,
    ElementPathsResult,
)
from ..facade.enums import JourneyStepType, UrlMatching
from .serializers import ElementClickStepSerializer, JourneyStepField


class ElementPathsQuerySerializer(serializers.Serializer):
    selector = serializers.CharField(
        max_length=MAX_SELECTOR_LENGTH, help_text="CSS selector of the clicked element, for example `button.signup`."
    )
    text = serializers.CharField(
        required=False,
        max_length=MAX_TEXT_LENGTH,
        help_text="Exact text of the clicked element. Leave out to match any text.",
    )
    href = serializers.CharField(
        required=False,
        max_length=MAX_URL_LENGTH,
        help_text="Exact link target of the clicked element. Leave out to match any link.",
    )
    url = serializers.CharField(
        required=False,
        max_length=MAX_URL_LENGTH,
        help_text="URL of the page the click happens on. Leave out to match the click on any page.",
    )
    url_matching = serializers.ChoiceField(
        choices=UrlMatching.choices,
        default=UrlMatching.EXACT.value,
        help_text="How `url` is compared with the page URL: `exact`, `contains` (case-insensitive) or `regex`.",
    )
    date_from = serializers.CharField(
        default="-7d",
        help_text=(
            "Start of the date range, as a relative date such as `-7d` or an ISO date. "
            f"The range can be at most {MAX_ELEMENT_PATHS_RANGE_DAYS} days."
        ),
    )
    date_to = serializers.CharField(
        required=False, help_text="End of the date range, as a relative or ISO date. Leave out for now."
    )
    steps_before = serializers.IntegerField(
        default=DEFAULT_ELEMENT_PATH_STEPS,
        min_value=0,
        max_value=MAX_ELEMENT_PATH_STEPS,
        help_text="Most steps to show before the click.",
    )
    steps_after = serializers.IntegerField(
        default=DEFAULT_ELEMENT_PATH_STEPS,
        min_value=0,
        max_value=MAX_ELEMENT_PATH_STEPS,
        help_text="Most steps to show after the click.",
    )
    limit = serializers.IntegerField(
        default=DEFAULT_ELEMENT_PATHS,
        min_value=1,
        max_value=MAX_ELEMENT_PATHS,
        help_text="Most paths to return.",
    )
    filter_test_accounts = serializers.BooleanField(
        default=False, help_text="Leave out clicks by the project's test accounts."
    )

    def validate(self, attrs: dict[str, Any]) -> dict[str, Any]:
        if attrs["steps_before"] == 0 and attrs["steps_after"] == 0:
            raise serializers.ValidationError("Set steps_before or steps_after to at least 1.")
        anchor = ElementClickStepSerializer(
            data={
                "type": JourneyStepType.ELEMENT_CLICK.value,
                **{key: attrs[key] for key in ("selector", "text", "href", "url", "url_matching") if key in attrs},
            }
        )
        anchor.is_valid(raise_exception=True)
        attrs["anchor"] = ElementClickStep(**anchor.validated_data)
        return attrs


def element_paths_query_from(validated: dict[str, Any]) -> ElementPathsQuery:
    return ElementPathsQuery(
        anchor=validated["anchor"],
        date_from=validated["date_from"],
        date_to=validated.get("date_to"),
        steps_before=validated["steps_before"],
        steps_after=validated["steps_after"],
        limit=validated["limit"],
        filter_test_accounts=validated["filter_test_accounts"],
    )


class ElementPathNodeSerializer(DataclassSerializer):
    step = JourneyStepField(
        help_text=(
            "The journey step this node stands for, in the shape that journey `steps` accept. "
            "Send it as is to save the path as a journey."
        )
    )

    class Meta:
        dataclass = ElementPathNode
        extra_kwargs = {
            "label": {"help_text": "Display name of the node: the page path, or the text, link or tag of the element."},
            "is_anchor": {"help_text": "True for the clicked element that the request asked about."},
            "step_is_exact": {
                "help_text": (
                    "True when `step` matches exactly the events this node counts. False when it is a best-effort "
                    "match: an element step names only the innermost tag or id of the clicked element, and a "
                    "pageview step built from a cleaned path also matches other paths that clean to the same value."
                )
            },
        }


class ElementPathSerializer(DataclassSerializer):
    nodes = ElementPathNodeSerializer(many=True, help_text="Steps of the path in time order.")

    class Meta:
        dataclass = ElementPath
        extra_kwargs = {
            "session_count": {"help_text": "Number of analyzed sessions that took this path."},
            "share_of_anchor_sessions": {
                "help_text": "`session_count` divided by `analyzed_session_count`, from 0 to 1."
            },
            "anchor_index": {"help_text": "Zero-based position of the clicked element in `nodes`."},
        }


class ElementPathsResultSerializer(DataclassSerializer):
    paths = ElementPathSerializer(
        many=True,
        help_text=(
            "Most common paths, most sessions first. Only paths that at least two sessions took are included, so "
            "an element with clicks can have no paths."
        ),
    )

    class Meta:
        dataclass = ElementPathsResult
        extra_kwargs = {
            "date_from": {"help_text": "Start of the date range that the query used."},
            "date_to": {"help_text": "End of the date range that the query used."},
            "anchor_click_count": {
                "help_text": "Autocaptured clicks on the element in the date range. Zero means nobody clicked it."
            },
            "anchor_session_count": {"help_text": "Sessions with at least one click on the element."},
            "analyzed_session_count": {
                "help_text": (
                    "Sessions that the paths come from. Less than `anchor_session_count` when the query takes "
                    "a sample of the sessions to limit its cost."
                )
            },
        }
