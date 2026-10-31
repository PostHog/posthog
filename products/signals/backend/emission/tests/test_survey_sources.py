import json
from typing import Any

import pytest

from products.signals.backend.emission._survey import SurveyAnswer, free_text_description, is_free_text_kind
from products.signals.backend.emission.formbricks_responses import FORMBRICKS_CONFIG
from products.signals.backend.emission.qualtrics_survey_responses import QUALTRICS_CONFIG
from products.signals.backend.emission.surveymonkey_survey_responses import SURVEYMONKEY_CONFIG
from products.signals.backend.emission.surveysparrow_responses import SURVEYSPARROW_CONFIG
from products.signals.backend.emission.survicate_responses import SURVICATE_CONFIG
from products.signals.backend.emission.typeform_responses import TYPEFORM_CONFIG
from products.signals.backend.emission.usersnap_feedbacks import USERSNAP_CONFIG

TEXT = "The export button crashes whenever a board has more than fifty cards"
OTHER = "Dark mode would help a lot when working late at night"


def _run(config, record: dict[str, Any]):
    return config.emitter(1, record)


# (config, base record, answers column, answers value with free text and non-text answers)
CASES = [
    pytest.param(
        USERSNAP_CONFIG,
        {
            "feedback_id": "f1",
            "feedback_number": 7,
            "public_link": "https://app.usersnap.com/f1",
            "status_type": "open",
        },
        "ordered_inputs",
        [
            {"label": "Comment", "text_value": TEXT},
            {"label": "Rating", "value": "4", "boolean_value": None},
            {"label": "Your email", "text_value": "jane@example.com"},
        ],
        "Comment: " + TEXT,
        "f1",
        id="usersnap",
    ),
    pytest.param(
        TYPEFORM_CONFIG,
        {"response_id": "r1", "form_id": "F9", "submitted_at": "2026-01-01T00:00:00Z"},
        "answers",
        [
            {"type": "text", "text": TEXT, "field": {"type": "long_text"}},
            {"type": "text", "text": "jane@example.com", "field": {"type": "email"}},
            {"type": "choice", "choice": {"label": "Other"}, "field": {"type": "multiple_choice"}},
            {"type": "number", "number": 5, "field": {"type": "rating"}},
        ],
        TEXT,
        "F9:r1",
        id="typeform",
    ),
    pytest.param(
        QUALTRICS_CONFIG,
        {"response_id": "R_1", "survey_id": "SV_1", "finished": True},
        "values",
        {"QID1": "2", "QID2_TEXT": TEXT, "recipientEmail": "jane@example.com", "QID3": "pick"},
        TEXT,
        "R_1",
        id="qualtrics",
    ),
    pytest.param(
        SURVEYMONKEY_CONFIG,
        {"id": "9", "survey_id": "S1", "response_status": "completed"},
        "pages",
        [
            {
                "questions": [
                    {"answers": [{"text": TEXT}]},
                    {"answers": [{"choice_id": "c1"}]},
                    {"answers": [{"choice_id": "c2", "text": "Option B"}]},
                    {"answers": [{"row_id": "r1", "col_id": "c1", "text": "Agree"}]},
                    {"answers": [{"other_id": "o1", "text": OTHER}]},
                ]
            }
        ],
        TEXT + "\n" + OTHER,
        "9",
        id="surveymonkey",
    ),
    pytest.param(
        FORMBRICKS_CONFIG,
        {"id": "cl1", "survey_id": "s1", "finished": True},
        "data",
        {
            "q1": "yes",
            "q2": TEXT,
            "q3": "jane.doe@example.com",
            "q4": "https://example.com/a/very/long/file/path",
            "email": "please contact me at this address soon",
            "q5": 5,
        },
        TEXT,
        "cl1",
        id="formbricks",
    ),
    pytest.param(
        SURVICATE_CONFIG,
        {"uuid": "u1", "survey_id": "sv", "url": "https://app.example.com/page?token=secret#frag"},
        "answers",
        [
            {"question_id": 1, "type": "text", "answer": TEXT},
            {"question_id": 2, "type": "single_choice", "answer": {"value": "Yes"}},
            {"question_id": 3, "type": "nps", "answer": "9"},
        ],
        TEXT,
        "u1",
        id="survicate",
    ),
    pytest.param(
        SURVEYSPARROW_CONFIG,
        {"id": 5, "survey_id": 12, "completed": True},
        "answers",
        [
            {"question_type": "TextInput", "answer": TEXT},
            {"question_type": "OpinionScale", "answer": "8"},
            {"question_type": "EmailInput", "answer": "jane@example.com"},
        ],
        TEXT,
        "12:5",
        id="surveysparrow",
    ),
]


@pytest.mark.parametrize("config,base,column,answers,expected,source_id", CASES)
class TestSurveyEmitters:
    def _record(self, base: dict[str, Any], column: str, value: Any) -> dict[str, Any]:
        return {**base, column: value}

    @pytest.mark.parametrize("encode", [json.dumps, lambda value: value], ids=["json_string", "native"])
    def test_keeps_only_free_text(self, config, base, column, answers, expected, source_id, encode):
        output = _run(config, self._record(base, column, encode(answers)))

        assert output is not None
        assert output.description == expected
        assert output.source_id == source_id
        assert "jane" not in output.description

    @pytest.mark.parametrize(
        "value",
        [None, "", "not json", "{broken", "[]", "{}", 7, '"just a string"'],
        ids=["none", "empty", "garbage", "truncated", "empty_list", "empty_map", "number", "json_string"],
    )
    def test_missing_or_malformed_answers_skip(self, config, base, column, answers, expected, source_id, value):
        assert _run(config, self._record(base, column, value)) is None

    def test_extra_never_carries_respondent_identity(self, config, base, column, answers, expected, source_id):
        output = _run(config, self._record(base, column, answers))

        assert output is not None
        for forbidden in ("email", "ip", "name", "respondent", "contact", "hidden", "recipient"):
            assert not any(forbidden in key for key in output.extra)

    def test_no_text_answers_means_no_signal(self, config, base, column, answers, expected, source_id):
        assert _run(config, self._record(base, column, [] if isinstance(answers, list) else {})) is None

    def test_missing_id_column_raises(self, config, base, column, answers, expected, source_id):
        record = self._record(base, column, answers)
        record.pop(next(iter(base)))
        with pytest.raises(ValueError):
            _run(config, record)


class TestSourceSpecificRules:
    def test_unfinished_qualtrics_response_is_skipped(self):
        record = {"response_id": "R_1", "finished": False, "values": json.dumps({"QID2_TEXT": TEXT})}
        assert _run(QUALTRICS_CONFIG, record) is None

    @pytest.mark.parametrize("finished", [True, 1, "1", "true", None])
    def test_finished_or_unknown_qualtrics_response_is_kept(self, finished):
        record = {"response_id": "R_1", "finished": finished, "values": json.dumps({"QID2_TEXT": TEXT})}
        assert _run(QUALTRICS_CONFIG, record) is not None

    def test_survicate_url_loses_query_and_fragment(self):
        record = {
            "uuid": "u1",
            "url": "https://app.example.com/page?token=secret#frag",
            "answers": json.dumps([{"type": "text", "answer": TEXT}]),
        }
        output = _run(SURVICATE_CONFIG, record)
        assert output is not None
        assert output.extra["url"] == "https://app.example.com/page"

    @pytest.mark.parametrize(
        "url,expected",
        [
            ("https://user:secret@app.example.com:8443/page?token=x", "https://app.example.com:8443/page"),
            ("https://token@app.example.com/page", "https://app.example.com/page"),
            ("/feedback?ref=mail", "/feedback"),
            ("https://[broken/page", None),
        ],
    )
    def test_survicate_url_loses_credentials(self, url, expected):
        record = {"uuid": "u1", "url": url, "answers": json.dumps([{"type": "text", "answer": TEXT}])}
        output = _run(SURVICATE_CONFIG, record)
        assert output is not None
        assert output.extra["url"] == expected

    def test_typeform_dropdown_text_answer_is_skipped(self):
        answers = [{"type": "text", "text": "Enterprise plan with yearly billing", "field": {"type": "dropdown"}}]
        record = {"response_id": "r1", "form_id": "F9", "answers": json.dumps(answers)}
        assert _run(TYPEFORM_CONFIG, record) is None

    def test_surveysparrow_answer_without_embedded_question_type_is_skipped(self):
        answers = [{"question_id": 123, "answer": TEXT}]
        record = {"id": 5, "survey_id": 12, "answers": json.dumps(answers)}
        assert _run(SURVEYSPARROW_CONFIG, record) is None

    def test_qualtrics_contact_like_text_keys_are_skipped(self):
        values = {"shipping_address_TEXT": "123 Example Street, Sample City", "QID2_TEXT": TEXT}
        output = _run(QUALTRICS_CONFIG, {"response_id": "R_1", "values": json.dumps(values)})
        assert output is not None
        assert output.description == TEXT

    def test_usersnap_address_label_is_skipped(self):
        inputs = [{"label": "Billing address", "text_value": "123 Example Street, Sample City"}]
        assert _run(USERSNAP_CONFIG, {"feedback_id": "f1", "ordered_inputs": json.dumps(inputs)}) is None

    def test_formbricks_address_key_is_skipped(self):
        data = {"billingAddress": "123 Example Street, Sample City"}
        assert _run(FORMBRICKS_CONFIG, {"id": "cl1", "data": json.dumps(data)}) is None

    @pytest.mark.parametrize("config", [c.values[0] for c in CASES])
    def test_raw_answer_columns_are_unloggable(self, config):
        assert config.unloggable_fields

    def test_usersnap_labels_are_a_list(self):
        record = {
            "feedback_id": "f1",
            "labels": '["bug"]',
            "ordered_inputs": json.dumps([{"label": "Comment", "text_value": TEXT}]),
        }
        output = _run(USERSNAP_CONFIG, record)
        assert output is not None
        assert output.extra["labels"] == ["bug"]

    def test_surveymonkey_only_fetches_completed_responses(self):
        assert SURVEYMONKEY_CONFIG.where_clause == "response_status = 'completed'"

    def test_email_check_is_linear_on_adversarial_input(self):
        import time

        text = "a@" * 20000 + "a." * 20000 + " invalid feedback"
        started = time.monotonic()
        description = free_text_description([SurveyAnswer(kind="text", text=text)])
        assert time.monotonic() - started < 1
        assert description is not None

    def test_description_is_capped(self):
        description = free_text_description([SurveyAnswer(kind="text", text="word " * 5000)])
        assert description is not None
        assert len(description) == 4000


@pytest.mark.parametrize(
    "kind,expected",
    [
        ("text", True),
        ("long_text", True),
        ("Long-Text", True),
        ("TextInput", True),
        ("open_ended", True),
        ("choice", False),
        ("email", False),
        ("phone_number", False),
        ("nps", False),
        (None, False),
        (3, False),
    ],
)
def test_is_free_text_kind(kind, expected):
    assert is_free_text_kind(kind) is expected
