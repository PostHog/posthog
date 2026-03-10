from typing import Any

from rest_framework import serializers

SCORE_KIND_LABEL = "label"
SCORE_KIND_NUMERIC = "numeric"


def normalize_and_validate_score_fields(
    attrs: dict[str, Any],
    *,
    current_score_kind: str | None,
    current_score_label: str | None,
    current_score_numeric: Any | None,
) -> dict[str, Any]:
    score_kind_supplied = "score_kind" in attrs
    score_label_supplied = "score_label" in attrs
    score_numeric_supplied = "score_numeric" in attrs

    score_kind = attrs.get("score_kind", current_score_kind)
    switching_score_kind = score_kind_supplied and score_kind != current_score_kind

    if score_kind is None:
        if score_kind_supplied:
            if (score_label_supplied and attrs.get("score_label") is not None) or (
                score_numeric_supplied and attrs.get("score_numeric") is not None
            ):
                raise serializers.ValidationError(
                    {"score_kind": "Clear `score_label` and `score_numeric` when `score_kind` is null."}
                )

            attrs["score_label"] = None
            attrs["score_numeric"] = None
            return attrs

        if score_label_supplied or score_numeric_supplied:
            raise serializers.ValidationError(
                {"score_kind": "Set `score_kind` when providing `score_label` or `score_numeric`."}
            )

        return attrs

    if score_kind == SCORE_KIND_LABEL:
        if score_numeric_supplied and attrs.get("score_numeric") is not None:
            raise serializers.ValidationError({"score_numeric": "Clear `score_numeric` when `score_kind` is `label`."})

        score_label = attrs.get("score_label")
        if not score_label_supplied and not switching_score_kind:
            score_label = current_score_label

        if score_label is None:
            raise serializers.ValidationError({"score_label": "This field is required when `score_kind` is `label`."})

        attrs["score_numeric"] = None
        return attrs

    if score_kind == SCORE_KIND_NUMERIC:
        if score_label_supplied and attrs.get("score_label") is not None:
            raise serializers.ValidationError({"score_label": "Clear `score_label` when `score_kind` is `numeric`."})

        score_numeric = attrs.get("score_numeric")
        if not score_numeric_supplied and not switching_score_kind:
            score_numeric = current_score_numeric

        if score_numeric is None:
            raise serializers.ValidationError(
                {"score_numeric": "This field is required when `score_kind` is `numeric`."}
            )

        attrs["score_label"] = None
        return attrs

    return attrs
