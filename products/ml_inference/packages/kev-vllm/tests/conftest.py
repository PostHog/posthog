from typing import ClassVar

import pytest


class FakeTokenizer:
    """Character tokenizer with Kev's five delimiter tokens, enough to exercise the row layout without a Hub download."""

    SPECIAL_IDS: ClassVar[dict[str, int]] = {
        "<|fim_prefix|>": 1,
        "<|fim_middle|>": 2,
        "<|box_start|>": 3,
        "<|box_end|>": 4,
        "<|fim_suffix|>": 5,
    }
    pad_token_id = 0

    class _Encoding:
        def __init__(self, ids):
            self.input_ids = ids

    def __call__(self, text, add_special_tokens=False):
        return self._Encoding([100 + ord(c) for c in text])

    def convert_tokens_to_ids(self, token):
        return self.SPECIAL_IDS[token]


@pytest.fixture
def tokenizer():
    return FakeTokenizer()


@pytest.fixture
def record():
    return {
        "state": "Order 4411 arrived late and the box was crushed.",
        "questions": [
            {"instr": "Is there a billing problem?", "options": ["yes", "no"], "label": 0},
            {"instr": "Which team?", "options": ["returns", "shipping", "billing", "other"], "label": 2},
            {"instr": "How upset?", "options": ["calm", "annoyed", "furious"], "label": 1},
        ],
    }
