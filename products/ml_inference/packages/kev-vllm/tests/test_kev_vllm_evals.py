import pytest

from kev_vllm.evals import request_of, score_record, summarize

RECORD = {
    "_meta": {"id": "r1"},
    "state": "Filed on June 26, 2026, due July 4, 2026.",
    "questions": {
        "late": {"type": "noul", "instructions": "Late?", "criteria": None, "label": 1, "src": "deadline"},
        "queue": {
            "type": "choice",
            "instructions": "Which team?",
            "criteria": {"billing": "money", "support": "help"},
            "label": "support",
            "src": "routing",
        },
        "tone": {"type": "score", "instructions": "How upset?", "criteria": ["calm", "angry"], "label": 0, "src": "tone"},
    },
}


def test_request_strips_labels_and_optionally_states_the_day_count():
    plain = request_of(RECORD, date_facts=False)
    assert plain["state"] == RECORD["state"]
    assert set(plain["questions"]["late"]) == {"type", "instructions"}
    assert "label" not in plain["questions"]["queue"]

    assert "July 4, 2026 is 8 days after June 26, 2026." in request_of(RECORD, date_facts=True)["state"]


def test_scores_each_question_against_its_label_in_option_order():
    rows = score_record(RECORD, [[0.3, 0.7], [0.9, 0.1], [0.8, 0.2]])

    assert [(r["question"], r["correct"]) for r in rows] == [("late", True), ("queue", False), ("tone", True)]
    assert all(r["two_dates"] for r in rows)
    assert summarize(rows)["by_task"]["deadline"] == {"questions": 1, "accuracy": 1.0}


def test_rejects_a_row_count_that_does_not_match_the_questions():
    with pytest.raises(ValueError, match="rows back"):
        score_record(RECORD, [[0.5, 0.5]])
