"""JevK5's prompt and readout, ported from its runtime (github.com/allebee/jevk5, jevk5/runtime.py at v0.2.0).

JevK5 is Qwen3.5-4B with a merged LoRA. It answers one question per causal row: a fixed system instruction, the
decision as JSON (evidence, criterion, lettered options), the chat template with thinking off, then a softmax over the
answer letters' next-token logits divided by one calibration temperature. The prompt text must match the runtime byte
for byte, because the LoRA was trained on it.
"""

import json
import math
from collections.abc import Sequence
from dataclasses import dataclass

from kev_vllm.kev_compat import JSONContent, Noul, Question, Score

LETTERS = "ABCDEFGHIJKLMNOP"
MAX_OPTIONS = len(LETTERS)
# The runtime refuses longer inputs rather than cutting them.
MAX_INPUT_TOKENS = 16_384
SYSTEM = (
    "Apply the supplied criterion to the supplied evidence. Choose exactly one listed option. "
    "Respond with only its uppercase letter, with no explanation or reasoning."
)


@dataclass(frozen=True, kw_only=True, slots=True)
class Option:
    key: str
    text: str


def options(question: Question) -> list[Option]:
    """Options in the order the letters are assigned: noul is true then false, choice follows its criteria, score is the
    levels lowest first."""
    if isinstance(question, Noul):
        criteria = question.criteria or {}
        pairs = [(key, criteria.get(key) or f"The proposition is {key}.") for key in ("true", "false")]
    elif isinstance(question, Score):
        pairs = [(str(level), description) for level, description in enumerate(question.criteria)]
    else:
        pairs = [(key, description or key) for key, description in question.criteria.items()]
    return [Option(key=key, text=f"{key}: {description}") for key, description in pairs]


def messages(state: JSONContent, question: Question) -> list[dict[str, str]]:
    texts = [option.text for option in options(question)]
    if len(texts) > MAX_OPTIONS:
        raise ValueError(f"JevK5 answers at most {MAX_OPTIONS} options per question, got {len(texts)}")
    payload = {
        "evidence": state,
        "criterion": question.instructions,
        "options": [{"letter": LETTERS[i], "description": text} for i, text in enumerate(texts)],
    }
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
    ]


def prompt_ids(tokenizer, state: JSONContent, question: Question) -> list[int]:
    prompt = tokenizer.apply_chat_template(messages(state, question), tokenize=False, add_generation_prompt=True, enable_thinking=False)
    ids = tokenizer.encode(prompt, add_special_tokens=False)
    if len(ids) > MAX_INPUT_TOKENS:
        raise ValueError(f"JevK5 answers inputs of at most {MAX_INPUT_TOKENS} tokens, this question has {len(ids)}")
    return ids


def letter_token_ids(tokenizer) -> list[int]:
    ids = [tokenizer.encode(letter, add_special_tokens=False) for letter in LETTERS]
    if any(len(letter_ids) != 1 for letter_ids in ids):
        raise ValueError("every answer letter must be one token")
    return [letter_ids[0] for letter_ids in ids]


def probabilities(letter_logits: Sequence[float], question: Question, temperature: float, keys: Sequence[str]) -> list[float]:
    """Calibrated probabilities reported in `keys` order (kev_compat.question_keys), which for noul is false then true,
    the reverse of the letter order."""
    by_letter = [option.key for option in options(question)]
    scaled = [logit / temperature for logit in letter_logits[: len(by_letter)]]
    top = max(scaled)
    weights = [math.exp(value - top) for value in scaled]
    total = sum(weights)
    by_key = {key: weight / total for key, weight in zip(by_letter, weights, strict=True)}
    return [by_key[key] for key in keys]
