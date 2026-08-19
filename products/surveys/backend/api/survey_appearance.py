import nh3
from rest_framework import serializers

from posthog.constants import DEFAULT_SURVEY_APPEARANCE, AvailableFeature
from posthog.models.organization import Organization

# Appearance fields that require the SURVEYS_STYLING entitlement to change.
# These mirror the inputs the frontend disables when the styling paywall is active:
# colors, fonts, spacing, and placement. Behavior and content fields (thank-you
# text, popup delay, widget label and selector) stay free, and whiteLabel keeps
# its own WHITE_LABELLING gate below.
SURVEY_STYLING_APPEARANCE_FIELDS = frozenset(
    {
        "backgroundColor",
        "textColor",
        "textSubtleColor",
        "borderColor",
        "inputBackground",
        "inputTextColor",
        "ratingButtonColor",
        "ratingButtonActiveColor",
        "ratingButtonHoverColor",
        "submitButtonColor",
        "submitButtonTextColor",
        "placeholder",
        "fontFamily",
        "maxWidth",
        "boxPadding",
        "boxShadow",
        "borderRadius",
        "zIndex",
        "disabledButtonOpacity",
        "position",
        "tabPosition",
    }
)


def validate_survey_appearance(
    appearance: dict | None,
    current_appearance: dict | None,
    organization: Organization,
) -> dict | None:
    """Validate and sanitize a survey appearance object.

    Enforces the SURVEYS_STYLING and WHITE_LABELLING entitlements on the server so a
    client cannot persist paid styling by re-enabling a disabled input. An org without
    SURVEYS_STYLING may still save styling fields it is not changing: each styling field
    is compared against the survey's current value (or the default for a new survey).
    """
    if appearance is None:
        return appearance

    if not isinstance(appearance, dict):
        raise serializers.ValidationError("Appearance must be an object")

    thank_you_message = appearance.get("thankYouMessageHeader")
    if thank_you_message and nh3.is_html(thank_you_message):
        appearance["thankYouMessageHeader"] = nh3_clean_with_allow_list(thank_you_message)

    thank_you_description = appearance.get("thankYouMessageDescription")
    if thank_you_description and nh3.is_html(thank_you_description):
        appearance["thankYouMessageDescription"] = nh3_clean_with_allow_list(thank_you_description)

    thank_you_close_button = appearance.get("thankYouMessageCloseButtonText")
    if thank_you_close_button and nh3.is_html(thank_you_close_button):
        appearance["thankYouMessageCloseButtonText"] = nh3_clean_with_allow_list(thank_you_close_button)

    thank_you_description_content_type = appearance.get("thankYouMessageDescriptionContentType")
    if thank_you_description_content_type and thank_you_description_content_type not in ["text", "html"]:
        raise serializers.ValidationError("thankYouMessageDescriptionContentType must be one of ['text', 'html']")

    survey_popup_delay_seconds = appearance.get("surveyPopupDelaySeconds")
    if survey_popup_delay_seconds and survey_popup_delay_seconds < 0:
        raise serializers.ValidationError("Survey popup delay seconds must be a positive integer")

    survey_white_label = appearance.get("whiteLabel")
    if survey_white_label is not None and not isinstance(survey_white_label, bool):
        raise serializers.ValidationError("whiteLabel must be a boolean")

    if survey_white_label and not organization.is_feature_available(AvailableFeature.WHITE_LABELLING):
        raise serializers.ValidationError("You need to upgrade to PostHog Enterprise to use white labelling")

    if not organization.is_feature_available(AvailableFeature.SURVEYS_STYLING):
        baseline = {**DEFAULT_SURVEY_APPEARANCE, **(current_appearance or {})}
        changed_styling_fields = [
            field
            for field in SURVEY_STYLING_APPEARANCE_FIELDS
            if field in appearance and appearance.get(field) != baseline.get(field)
        ]
        if changed_styling_fields:
            raise serializers.ValidationError("You need to upgrade your plan to customize survey styling")

    return appearance


def nh3_clean_with_allow_list(to_clean: str):
    return nh3.clean(
        to_clean,
        link_rel="noopener",
        tags={
            "a",
            "abbr",
            "acronym",
            "area",
            "article",
            "aside",
            "b",
            "bdi",
            "bdo",
            "blockquote",
            "br",
            "caption",
            "center",
            "cite",
            "code",
            "col",
            "colgroup",
            "data",
            "dd",
            "del",
            "details",
            "dfn",
            "div",
            "dl",
            "dt",
            "em",
            "figcaption",
            "figure",
            "footer",
            "h1",
            "h2",
            "h3",
            "h4",
            "h5",
            "h6",
            "header",
            "hgroup",
            "hr",
            "i",
            "img",
            "ins",
            "kbd",
            "li",
            "map",
            "mark",
            "nav",
            "ol",
            "p",
            "pre",
            "q",
            "rp",
            "rt",
            "rtc",
            "ruby",
            "s",
            "samp",
            "small",
            "span",
            "strike",
            "strong",
            "sub",
            "summary",
            "sup",
            "table",
            "tbody",
            "td",
            "th",
            "thead",
            "time",
            "tr",
            "tt",
            "u",
            "ul",
            "var",
            "wbr",
        },
        attributes={
            "*": {"style", "lang", "title", "width", "height"},
            # below are mostly defaults to ammonia, but we need to add them explicitly
            # because this python binding doesn't allow additive allowing
            "a": {"href", "hreflang", "target"},
            "bdo": {"dir"},
            "blockquote": {"cite"},
            "col": {"align", "char", "charoff", "span"},
            "colgroup": {"align", "char", "charoff", "span"},
            "del": {"cite", "datetime"},
            "hr": {"align", "size", "width"},
            "img": {"align", "alt", "height", "src", "width"},
            "ins": {"cite", "datetime"},
            "ol": {"start", "type"},
            "q": {"cite"},
            "table": {
                "align",
                "bgcolor",
                "border",
                "cellpadding",
                "cellspacing",
                "frame",
                "rules",
                "summary",
                "width",
            },
            "tbody": {"align", "char", "charoff", "valign"},
            "td": {
                "abbr",
                "align",
                "axis",
                "bgcolor",
                "char",
                "charoff",
                "colspan",
                "headers",
                "height",
                "nowrap",
                "rowspan",
                "scope",
                "valign",
                "width",
            },
            "tfoot": {"align", "char", "charoff", "valign"},
            "th": {
                "abbr",
                "align",
                "axis",
                "bgcolor",
                "char",
                "charoff",
                "colspan",
                "headers",
                "height",
                "nowrap",
                "rowspan",
                "scope",
                "valign",
                "width",
            },
            "thead": {"align", "char", "charoff", "valign"},
            "tr": {"align", "bgcolor", "char", "charoff", "valign"},
        },
    )
