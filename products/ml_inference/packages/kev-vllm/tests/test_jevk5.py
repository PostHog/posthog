import json
import math

import pytest

from kev_vllm import jevk5
from kev_vllm.kev_compat import SystemOneRequest, to_answers, to_record

STATE = {"order": "4411", "note": "Billed €40 twice, refund the duplicate"}


@pytest.mark.parametrize(
    "question,descriptions",
    [
        ({"type": "noul", "instructions": "Refund due?"}, ["true: The proposition is true.", "false: The proposition is false."]),
        (
            {"type": "noul", "instructions": "Refund due?", "criteria": {"true": "It is due", "false": "It is not"}},
            ["true: It is due", "false: It is not"],
        ),
        (
            {"type": "choice", "instructions": "Team?", "criteria": {"billing": "Payments", "tech": None}},
            ["billing: Payments", "tech: tech"],
        ),
        ({"type": "score", "instructions": "How upset?", "criteria": ["calm", "furious"]}, ["0: calm", "1: furious"]),
    ],
)
def test_the_prompt_is_the_one_jevk5_was_trained_on(question, descriptions):
    parsed = SystemOneRequest.model_validate({"state": STATE, "questions": {"q": question}}).questions["q"]
    system, user = jevk5.messages(STATE, parsed)
    assert system == {"role": "system", "content": jevk5.SYSTEM}
    expected = {
        "evidence": STATE,
        "criterion": question["instructions"],
        "options": [{"letter": jevk5.LETTERS[i], "description": text} for i, text in enumerate(descriptions)],
    }
    assert user == {"role": "user", "content": json.dumps(expected, ensure_ascii=False)}


def test_a_noul_answer_is_the_probability_of_true_although_true_takes_the_first_letter():
    request = SystemOneRequest.model_validate({"state": "s", "questions": {"refund": {"type": "noul", "instructions": "?"}}})
    _, meta = to_record(request)
    probs = jevk5.probabilities([2.0, 0.0, 9.0], request.questions["refund"], temperature=1.5, keys=meta[0]["keys"])
    p_true = 1 / (1 + math.exp(-2.0 / 1.5))
    assert probs == pytest.approx([1 - p_true, p_true])
    assert to_answers([probs], meta)["refund"]["noul"] == round(p_true, 2)


def test_more_options_than_letters_are_refused():
    question = SystemOneRequest.model_validate(
        {"state": "s", "questions": {"q": {"type": "choice", "instructions": "?", "criteria": {str(i): None for i in range(17)}}}}
    ).questions["q"]
    with pytest.raises(ValueError, match="at most 16 options"):
        jevk5.messages("s", question)
