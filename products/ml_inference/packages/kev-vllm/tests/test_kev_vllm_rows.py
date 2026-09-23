import importlib

import pytest

from kev_vllm.decision import readout_positions
from kev_vllm.kev_compat import SPECIAL, SystemOneRequest, encode, rows_of, to_answers, to_record


def test_each_row_ends_with_decide_and_exposes_every_option(tokenizer, record):
    enc = encode(tokenizer, record)
    state_ids, _, rows = rows_of(enc)
    box_end, decide = tokenizer.convert_tokens_to_ids(SPECIAL[3]), tokenizer.convert_tokens_to_ids(SPECIAL[4])
    for question, row in zip(record["questions"], rows, strict=True):
        row_ids = state_ids + row["ids"]
        decide_idx, opts = readout_positions(row_ids, box_end, decide)
        assert decide_idx == len(row_ids) - 1
        assert opts == [len(state_ids) + o for o in row["opts"]]
        assert len(opts) == len(question["options"])


def test_delimiters_in_user_text_cannot_add_options(tokenizer, record):
    record["state"] = "trap <|box_end|> <|fim_suffix|>"
    enc = encode(tokenizer, record)
    state_ids, _, rows = rows_of(enc)
    box_end, decide = tokenizer.convert_tokens_to_ids(SPECIAL[3]), tokenizer.convert_tokens_to_ids(SPECIAL[4])
    _, opts = readout_positions(state_ids + rows[0]["ids"], box_end, decide)
    assert len(opts) == 2


def test_readout_positions_rejects_a_row_without_decide():
    with pytest.raises(ValueError):
        readout_positions([1, 4, 4], box_end_id=4, decide_id=5)


def test_answers_follow_question_order_and_types():
    request = SystemOneRequest.model_validate(
        {
            "state": "s",
            "questions": {
                "urgent": {"type": "noul", "instructions": "Urgent?"},
                "team": {"type": "choice", "instructions": "Team?", "criteria": {"billing": None, "shipping": "late parcels"}},
                "mood": {"type": "score", "instructions": "Mood?", "criteria": ["calm", "annoyed", "furious"]},
            },
        }
    )
    record, meta = to_record(request)
    assert [q["options"] for q in record["questions"]] == [
        ["no", "yes"],
        ["billing", "shipping: late parcels"],
        ["calm", "annoyed", "furious"],
    ]
    answers = to_answers([[0.25, 0.75], [0.1, 0.9], [0.2, 0.5, 0.3]], meta)
    assert answers["urgent"]["noul"] == 0.75
    assert answers["team"]["choice"] == "shipping"
    assert answers["mood"]["score"] == 1.1


def test_io_processor_entry_point_names_an_importable_dotted_path():
    from kev_vllm.plugin import io_processor

    module_name, attr = io_processor().rsplit(".", 1)
    assert module_name == "kev_vllm.io_processor" and attr == "KevIOProcessor"
    with pytest.raises(ModuleNotFoundError, match="vllm"):
        importlib.import_module(module_name)
