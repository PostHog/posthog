"""Kev's record encoding and TypeSafe API mapping, vendored so serving needs no `kev` install.

Copied verbatim from https://github.com/jaredpalmer/kev at commit
35566d73bea14cc417df016f6044d5cd311f697b (kev/model.py and kev/api.py), Apache License 2.0, Copyright
Jared Palmer. Only the torch-free parts are here: the delimiter tokens, `encode` (state plus
per-question branches), `rows_of` (one causal row per question, the form a hybrid backbone needs),
and the request/response shapes. The `kev` package itself pins torch below 2.9 and cannot share an
environment with vLLM. Re-vendor with models/kev/scripts/vendor_kev_compat.py in the MLHog repo when
the pinned commit moves, and keep the text as is (ruff skips this file), so a diff against upstream
stays trivial.
"""

import json
import re
from datetime import datetime
from typing import Any, Literal, Union

from pydantic import BaseModel, Field, model_validator

KEV_SOURCE_COMMIT = "35566d73bea14cc417df016f6044d5cd311f697b"

SPECIAL = ["<|fim_prefix|>", "<|fim_middle|>", "<|box_start|>", "<|box_end|>", "<|fim_suffix|>"]


MAX_STATE, MAX_BRANCH, MAX_PACKED = 384, 1024, 2048


_SPECIAL_RE = re.compile(r"<\|([A-Za-z0-9_]+)\|>")


def user_tokens(tok, text):
    """Tokenize caller-supplied text so it can never produce delimiter/control tokens (option boundaries are unforgeable).
    The fast tokenizer ignores split_special_tokens, so `<|name|>` is rewritten to `<¦name¦>` before tokenizing."""
    return tok(_SPECIAL_RE.sub(r"<¦\1¦>", text), add_special_tokens=False).input_ids


OPT_NONE, OPT_DECIDE = -1, -2


def encode(tok, rec, max_state=MAX_STATE, max_branch=MAX_BRANCH, strict=False, option_isolation=False):
    """Pack one record: [<state> ...] then per-question [<q> instr <opt> o </opt>... <decide>].

    Returns ids, seg (0 = state, k = question k), pos (branch positions restart after state),
    decide_idx [Q], opt_idx [Q][K] (index of </opt> token for each option), opt (per-token option index within its
    question: OPT_NONE for state/instruction, 0..K-1 for option spans, OPT_DECIDE for <decide>).

    option_isolation=True: every option span is its own sub-branch (it sees state + instruction + itself only), all
    option spans share the same position ids, and <decide> sits at one fixed position after the longest span. Then the
    per-option representations and <decide>'s attention over them are permutation-invariant by construction.
    """
    state_tokens = user_tokens(tok, rec["state"])
    if strict and len(state_tokens) + 1 > max_state:
        raise ValueError(f"state exceeds {max_state} tokens: {len(state_tokens) + 1}")
    S = [tok.convert_tokens_to_ids(SPECIAL[0])] + state_tokens[: max_state - 1]
    ids, seg, pos, opt = list(S), [0] * len(S), list(range(len(S))), [OPT_NONE] * len(S)
    q_id, o_id, c_id, d_id = (tok.convert_tokens_to_ids(t) for t in SPECIAL[1:])
    decide_idx, opt_idx = [], []
    for k, q in enumerate(rec["questions"], start=1):
        instr = [q_id] + user_tokens(tok, q["instr"])
        spans = [[o_id] + user_tokens(tok, o) + [c_id] for o in q["options"]]
        br = instr + [t for sp in spans for t in sp] + [d_id]
        if len(br) > max_branch - len(S):
            raise ValueError(f"branch too long: {len(br)}")
        base = len(ids); p0 = len(S)
        br_opt = [OPT_NONE] * len(instr) + [j for j, sp in enumerate(spans) for _ in sp] + [OPT_DECIDE]
        if option_isolation:
            longest = max(len(sp) for sp in spans)
            br_pos = list(range(p0, p0 + len(instr))) + [p0 + len(instr) + i for sp in spans for i in range(len(sp))] + [p0 + len(instr) + longest]
        else:
            br_pos = list(range(p0, p0 + len(br)))
        ends, cursor = [], len(instr)
        for sp in spans:
            cursor += len(sp); ends.append(cursor - 1)
        ids += br; seg += [k] * len(br); pos += br_pos; opt += br_opt
        decide_idx.append(base + len(br) - 1); opt_idx.append([base + e for e in ends])
    return {"ids": ids, "seg": seg, "pos": pos, "opt": opt, "option_isolation": option_isolation, "decide_idx": decide_idx, "opt_idx": opt_idx,
            "labels": [q["label"] for q in rec["questions"]], "state_truncated": len(state_tokens) + 1 > max_state}


def rows_of(enc):
    """Split a packed encoding into its state and per-question branch rows.

    Returns (state_ids, state_pos, rows) with rows[k] = {"ids", "pos", "decide", "opts"}: the branch tokens of question
    k with their (already state-continuing) positions, and the readout offsets *within the branch*. Feeding
    state + rows[k] as one causal row is equivalent to the packed block-causal form for that question, on any
    architecture: the row contains exactly the tokens question k may attend to, in the same positions."""
    seg = enc["seg"]; Ls = seg.count(0)
    rows, start = [], Ls
    for k, (d, oi) in enumerate(zip(enc["decide_idx"], enc["opt_idx"]), start=1):
        end = d + 1                                    # <decide> is the last token of its branch
        if seg[start] != k or seg[end - 1] != k: raise ValueError("branch layout mismatch")
        rows.append({"ids": enc["ids"][start:end], "pos": enc["pos"][start:end], "decide": d - start, "opts": [o - start for o in oi]})
        start = end
    return enc["ids"][:Ls], enc["pos"][:Ls], rows


JSONContent = Union[str, dict, list, int, float, bool, None]


MAX_OPTIONS = 255


class Noul(BaseModel):
    type: Literal["noul"]
    instructions: JSONContent
    criteria: dict[str, JSONContent] | None = None


class Choice(BaseModel):
    type: Literal["choice"]
    instructions: JSONContent
    criteria: dict[str, JSONContent]

    @model_validator(mode="after")
    def _check(self):
        if not 1 <= len(self.criteria) <= MAX_OPTIONS: raise ValueError(f"criteria must have 1..{MAX_OPTIONS} options")
        return self


class Score(BaseModel):
    type: Literal["score"]
    instructions: JSONContent
    criteria: list[JSONContent] = Field(min_length=2, max_length=MAX_OPTIONS)


Question = Union[Noul, Choice, Score]


class SystemOneRequest(BaseModel):
    state: JSONContent
    model: str = "kev-latest"
    questions: dict[str, Question] = Field(min_length=1)


def render(v: JSONContent, indent: int = 0) -> str:
    """Flatten str | object | array into text the model sees. Field names are kept as labels."""
    pad = "  " * indent
    if v is None: return ""
    if isinstance(v, (str, int, float, bool)): return str(v)
    if isinstance(v, list): return "\n".join(f"{pad}- {render(x, indent + 1).lstrip()}" for x in v)
    return "\n".join(f"{pad}{k}:\n{render(x, indent + 1)}" if isinstance(x, (dict, list)) else f"{pad}{k}: {render(x)}" for k, x in v.items())


def option_text(name: str, desc: JSONContent) -> str:
    return name if desc is None or desc == "" else f"{name}: {render(desc)}"


MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"


_DATE = re.compile(rf"\b(?:{MONTHS}) \d{{1,2}}, \d{{4}}\b|\b\d{{4}}-\d{{2}}-\d{{2}}\b")


def date_facts(text: str) -> str:
    """Deterministic date arithmetic for the model: every pair of absolute dates found in `text`, as one sentence each
    ("August 3, 2026 is 12 days after July 22, 2026."). The model cannot subtract dates reliably (issue #8); it can use a
    stated day count. Returns "" when fewer than two dates are found. Dates are listed in order of first appearance."""
    found = []
    for m in _DATE.finditer(text):
        raw = m.group(0)
        try: d = datetime.strptime(raw, "%B %d, %Y") if "," in raw else datetime.strptime(raw, "%Y-%m-%d")
        except ValueError: continue
        if raw not in [r for r, _ in found]: found.append((raw, d))
    facts = []
    for i in range(len(found)):
        for j in range(i + 1, len(found)):
            n = (found[j][1] - found[i][1]).days
            facts.append(f"{found[j][0]} is {abs(n)} day{'s' if abs(n) != 1 else ''} {'after' if n > 0 else 'before'} {found[i][0]}." if n else f"{found[j][0]} is the same day as {found[i][0]}.")
    return " ".join(facts)


def with_date_facts(state):
    """State with a `date_facts` field (object states) or an appended paragraph (string states) when two or more absolute
    dates appear. Opt-in preprocessing (KEV_DATE_FACTS=1 in kev.serve, --date_facts in kev.benchmark)."""
    facts = date_facts(render(state))
    if not facts: return state
    if isinstance(state, dict): return {**state, "date_facts": facts}
    if isinstance(state, list): return state + [{"date_facts": facts}]
    return f"{state}\n\ndate_facts: {facts}"


def question_keys(qtype: str, criteria) -> list[str]:
    """The keys a question's probabilities are reported under, in option order: the criteria names (choice),
    ["false", "true"] (noul), the level indices as strings (score). Labels, targets and anchors use the same keys."""
    if qtype == "choice": return list(criteria)
    if qtype == "noul": return ["false", "true"]
    return [str(i) for i in range(len(criteria))]


def to_record(req: SystemOneRequest):
    """-> internal record for encode(), plus per-question metadata ({"id", "type", "keys", "legend" for score}) to map
    probabilities back."""
    qs, meta = [], []
    for qid, q in req.questions.items():
        m = {"id": qid, "type": q.type, "keys": question_keys(q.type, q.criteria)}
        if q.type == "noul":
            c = q.criteria or {}
            opts = [option_text("no", c.get("false")), option_text("yes", c.get("true"))]
        elif q.type == "choice":
            opts = [option_text(k, v) for k, v in q.criteria.items()]
        else:
            opts = [render(x) for x in q.criteria]
            m["legend"] = dict(zip(m["keys"], opts))
        qs.append({"instr": render(q.instructions), "options": opts, "label": 0}); meta.append(m)
    return {"state": render(req.state), "questions": qs}, meta


def choice_confidence(p: list[float]) -> float:
    K = len(p)
    return 1.0 if K == 1 else (max(p) - 1 / K) / (1 - 1 / K)


def score_confidence(p: list[float]) -> float:
    """Approximation of TypeSafe's 'distance from the modal level' statistic (exact formula unpublished):
    1 - E|level - mode| / (L - 1)."""
    L = len(p); mode = max(range(L), key=lambda i: p[i])
    return 1.0 - sum(pi * abs(i - mode) for i, pi in enumerate(p)) / (L - 1)


def r2(x: float) -> float:
    return round(float(x), 2)


def to_answers(probs: list[list[float]], meta: list[dict]) -> dict[str, Any]:
    out = {}
    for p, m in zip(probs, meta):
        if m["type"] == "noul":
            out[m["id"]] = {"type": "noul", "noul": r2(p[1])}
        elif m["type"] == "choice":
            dist = {k: r2(v) for k, v in zip(m["keys"], p)}
            out[m["id"]] = {"type": "choice", "choice": m["keys"][max(range(len(p)), key=lambda i: p[i])], "confidence": r2(choice_confidence(p)), "probabilities": dist}
        else:
            score = sum(i * pi for i, pi in enumerate(p))
            out[m["id"]] = {"type": "score", "score": r2(score), "legend": m["legend"], "probabilities": {str(i): r2(v) for i, v in enumerate(p)}, "confidence": r2(score_confidence(p))}
    return out


def output_tokens(tok, answers: dict) -> int:
    """Billing-style figure: tokens of the serialised answers. Not a measure of generation (there is none)."""
    return len(tok(json.dumps(answers), add_special_tokens=False).input_ids)
