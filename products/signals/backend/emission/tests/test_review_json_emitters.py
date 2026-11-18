import json
from typing import Any

import pytest

from products.signals.backend.emission.beamer_feature_requests import BEAMER_CONFIG
from products.signals.backend.emission.g2_reviews import G2_CONFIG

TEXT = "The export button crashes whenever a board has more than fifty cards"
OTHER = "Dark mode would help a lot when working late at night"


def _g2(answers: Any, title: Any = "Solid tool with rough edges") -> dict[str, Any]:
    return {
        "id": "rev-1",
        "title": title,
        "answers": answers,
        "star_rating": 4.0,
        "product_name": "Example App",
        "url": "https://www.g2.com/products/example/reviews/rev-1",
        "submitted_at": "2026-01-01T00:00:00.000-06:00",
    }


_G2_ANSWERS = {
    "love": {"text": "What do you like best?", "value": OTHER},
    "hate": {"text": "What do you dislike?", "value": TEXT},
    "nps": {"text": "How likely is it that you would recommend this product?", "value": 5.0},
    "product_role": {"text": "Your role", "value": "Administrator"},
    "switched_reason": {"text": None, "value": None},
}


@pytest.mark.parametrize("encode", [json.dumps, lambda value: value], ids=["json_string", "native"])
def test_g2_keeps_title_and_prose_answers_only(encode):
    output = G2_CONFIG.emitter(1, _g2(encode(_G2_ANSWERS)))

    assert output is not None
    assert output.description == (
        f"Solid tool with rough edges\nWhat do you like best?: {OTHER}\nWhat do you dislike?: {TEXT}"
    )
    assert "Administrator" not in output.description
    assert output.source_id == "rev-1"
    assert output.extra["star_rating"] == "4.0"


@pytest.mark.parametrize(
    "answers",
    [
        None,
        "",
        "not json",
        "[]",
        {},
        {"product_role": {"text": "Your role", "value": "Administrator"}},
        {"hate": {"text": "What do you dislike?", "value": "   "}},
        {"hate": {"text": "What do you dislike?", "value": 3}},
        {"hate": "flat string, not an object"},
    ],
    ids=[
        "none",
        "empty",
        "garbage",
        "list",
        "empty_map",
        "only_choice_answers",
        "blank_prose",
        "numeric_prose",
        "malformed_item",
    ],
)
def test_g2_review_without_prose_is_skipped(answers):
    assert G2_CONFIG.emitter(1, _g2(answers)) is None


@pytest.mark.parametrize("title", [None, "", "   "], ids=["none", "empty", "blank"])
def test_g2_review_without_title_uses_answers(title):
    output = G2_CONFIG.emitter(1, _g2({"hate": {"text": None, "value": TEXT}}, title=title))

    assert output is not None
    assert output.description == TEXT


def test_g2_missing_id_raises():
    record = _g2(_G2_ANSWERS)
    record.pop("id")
    with pytest.raises(ValueError):
        G2_CONFIG.emitter(1, record)


def _beamer(translations: Any) -> dict[str, Any]:
    return {
        "id": "123",
        "translations": translations,
        "status": "under_review",
        "category": "bug",
        "votes_count": 10,
        "comments_count": "2",
        "date": "2026-01-01T00:00:00Z",
    }


_FRENCH = {"title": "Mode sombre", "content": "Un mode sombre", "language": "FR", "permalink": "https://x/fr"}
_ENGLISH = {"title": "Dark mode", "content": OTHER, "language": "EN", "permalink": "https://x/en"}


@pytest.mark.parametrize(
    "translations,expected,permalink",
    [
        ([_FRENCH, _ENGLISH], f"Dark mode\n{OTHER}", "https://x/en"),
        ([_FRENCH], "Mode sombre\nUn mode sombre", "https://x/fr"),
        ([{"title": "Dark mode", "language": "en"}], "Dark mode", None),
        ([{"title": "", "language": "EN"}, _FRENCH], "Mode sombre\nUn mode sombre", "https://x/fr"),
        (json.dumps([_ENGLISH]), f"Dark mode\n{OTHER}", "https://x/en"),
    ],
    ids=["prefers_english", "falls_back_to_first", "title_only", "skips_untitled_item", "json_string"],
)
def test_beamer_picks_a_translation(translations, expected, permalink):
    output = BEAMER_CONFIG.emitter(1, _beamer(translations))

    assert output is not None
    assert output.description == expected
    assert output.source_id == "123"
    assert output.extra["permalink"] == permalink
    assert output.extra["votes_count"] == "10"


@pytest.mark.parametrize(
    "translations",
    [None, "", "not json", "[]", [], [{"content": TEXT}], [{"title": "   "}], ["not a dict"]],
    ids=["none", "empty", "garbage", "empty_json", "empty_list", "no_title", "blank_title", "not_a_dict"],
)
def test_beamer_request_without_title_is_skipped(translations):
    assert BEAMER_CONFIG.emitter(1, _beamer(translations)) is None


def test_beamer_missing_id_raises():
    record = _beamer([_ENGLISH])
    record.pop("id")
    with pytest.raises(ValueError):
        BEAMER_CONFIG.emitter(1, record)
