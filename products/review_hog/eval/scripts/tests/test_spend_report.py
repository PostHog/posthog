from datetime import UTC, datetime

from django.test import SimpleTestCase

from parameterized import parameterized

from products.review_hog.eval.scripts.spend_report import LIST_PRICES, SpendRow, price_for, render_spend_report


def _row(
    *,
    at: tuple[int, int],
    model: str,
    step: str = "",
    ai_stage: str = "",
    run_id: str = "",
    is_error: bool = False,
    tin: float,
    tout: float,
    cache_read: float = 0.0,
    cache_write: float = 0.0,
    gw: float | None = None,
    gw_in: float | None = None,
    gw_out: float | None = None,
    gw_read: float | None = None,
    gw_write: float | None = None,
) -> SpendRow:
    minute, second = at
    return SpendRow(
        timestamp=datetime(2026, 7, 6, 9, minute, second, tzinfo=UTC),
        model=model,
        ai_stage=ai_stage,
        task_title=f"[sandbox_prompt:{step}]" if step else "",
        task_run_id=run_id,
        is_error=is_error,
        input_tokens=tin,
        output_tokens=tout,
        cache_read=cache_read,
        cache_write=cache_write,
        gw_cost=gw,
        gw_input_cost=gw_in,
        gw_output_cost=gw_out,
        gw_cache_read_cost=gw_read,
        gw_cache_write_cost=gw_write,
    )


# One synthetic run that reaches every branch of the section: a warm-up unit plus two forked
# review units on one chunk (so the fork-collision tracker fires), a unit whose second turn
# lands on another model, a date-suffixed model id, the one-shot chunking/dedup calls that carry
# no task_run_id, an unpriced model that still reports per-side gateway costs, a >200K-token
# prompt, a gen with no gateway cost, and a failed gen ahead of its unit's first good one.
ROWS = [
    _row(
        at=(0, 5),
        model="claude-sonnet-5",
        step="warmup-c1",
        run_id="run-aaaa1111",
        tin=90_000,
        tout=400,
        cache_write=84_000,
        gw=0.22,
        gw_in=0.2,
        gw_out=0.004,
        gw_read=0.0,
        gw_write=0.21,
    ),
    _row(
        at=(0, 38),
        model="claude-sonnet-5",
        step="issues-review-c1",
        run_id="run-bbbb2222",
        is_error=True,
        tin=0,
        tout=0,
    ),
    _row(
        at=(0, 41),
        model="claude-sonnet-5",
        step="issues-review-c1",
        run_id="run-bbbb2222",
        tin=210_000,
        tout=3_100,
        cache_read=120_000,
        cache_write=62_000,
        gw=0.31,
        gw_in=0.28,
        gw_out=0.031,
        gw_read=0.024,
        gw_write=0.155,
    ),
    _row(
        at=(0, 44),
        model="claude-sonnet-5",
        step="issues-review-c1",
        run_id="run-cccc3333",
        tin=150_000,
        tout=2_400,
        cache_read=141_000,
        gw=0.07,
        gw_in=0.046,
        gw_out=0.024,
        gw_read=0.0282,
    ),
    _row(
        at=(1, 10),
        model="claude-opus-4-8",
        step="issues-review-c1",
        run_id="run-cccc3333",
        tin=160_000,
        tout=1_800,
        cache_read=150_000,
        gw=0.13,
        gw_in=0.085,
        gw_out=0.045,
        gw_read=0.075,
    ),
    _row(
        at=(2, 2),
        model="claude-sonnet-5-20260601",
        step="blind-spots-c2",
        run_id="run-dddd4444",
        tin=88_000,
        tout=1_500,
        cache_read=60_000,
        cache_write=21_000,
        gw=0.09,
        gw_in=0.075,
        gw_out=0.015,
        gw_read=0.012,
        gw_write=0.0525,
    ),
    _row(
        at=(3, 0),
        model="claude-haiku-4-5",
        ai_stage="chunking",
        tin=12_000,
        tout=900,
        gw=0.017,
        gw_in=0.012,
        gw_out=0.0045,
    ),
    _row(
        at=(3, 30), model="claude-haiku-4-5", ai_stage="dedup", tin=40_000, tout=2_000, gw=0.05, gw_in=0.04, gw_out=0.01
    ),
    _row(
        at=(4, 0),
        model="some-other-model",
        step="validation-1",
        run_id="run-eeee5555",
        tin=30_000,
        tout=800,
        gw=0.04,
        gw_in=0.03,
        gw_out=0.008,
    ),
    _row(at=(4, 30), model="some-other-model", step="validation-2", run_id="run-ffff6666", tin=25_000, tout=600),
]

EXPECTED_MARKDOWN = """\
### Cache-aware spend (local `$ai_generation`, best-effort)

| model | stage | gens | fresh in | cache write | cache read | output | >200K gens | true $ | gw $ |
| ----- | ----- | ---- | -------- | ----------- | ---------- | ------ | ---------- | ------ | ---- |
| claude-sonnet-5 | review | 2 | 37,000 | 62,000 | 261,000 | 5,500 | 1 | $0.34 | $0.38 |
| claude-sonnet-5 | warmup | 1 | 6,000 | 84,000 | 0 | 400 | 0 | $0.23 | $0.22 |
| claude-opus-4-8 | review | 1 | 10,000 | 0 | 150,000 | 1,800 | 0 | $0.17 | $0.13 |
| claude-sonnet-5-20260601 | blind-spot | 1 | 7,000 | 21,000 | 60,000 | 1,500 | 0 | $0.09 | $0.09 |
| claude-haiku-4-5 | dedup | 1 | 40,000 | 0 | 0 | 2,000 | 0 | $0.05 | $0.05 |
| some-other-model | validation | 2 | 55,000 | 0 | 0 | 1,400 | 0 | — | $0.04 |
| claude-haiku-4-5 | chunking | 1 | 12,000 | 0 | 0 | 900 | 0 | $0.02 | $0.02 |
| **total** |  | **9** | **167,000** | **167,000** | **471,000** | **13,500** | **1** | **$0.89** | **$0.93** |

- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); `gw $` = gateway `$ai_total_cost_usd` (LiteLLM). Δ (priced buckets) = -0.6%.
- 1 failed gen(s) (`$ai_is_error`) are left out of every column above and of the per-unit table below.
- `true $` total excludes unpriced model `some-other-model` (2 gen(s), gw $0.04).
- 1 gen(s) had no `$ai_total_cost_usd` — `gw $` undercounts by those gens.
- naive method (all prompt tokens at input price): $2.06 — 2.3× the true cost; never gate on it.
- gateway per-side cross-check (priced gens that emitted the field, both columns over the same gens; LiteLLM's `input_cost` is the whole input side, cache included):
  - input side (fresh + cache write + cache read): $0.7380 over 7 gen(s) (true $0.7587, Δ -2.7%)
  - · of which cache read: $0.1392 over 5 gen(s) (true $0.1392, Δ +0.0%)
  - · of which cache write: $0.4175 over 3 gen(s) (true $0.4175, Δ +0.0%)
  - · of which fresh (derived): $0.1813 over 7 gen(s) (true $0.2020, Δ -10.2%)
  - output: $0.1335 over 7 gen(s) (true $0.1335, Δ +0.0%)
- 1 gen(s) ran with >200K-token prompts; the gateway map prices these models flat, so no long-context premium is included in either column.

### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)

| unit | step | first gen | t1 cache read | t1 cache write | models |
| ---- | ---- | --------- | ------------- | -------------- | ------ |
| …aaaa1111 | warmup-c1 | 09:00:05 | 0 | 84,000 | claude-sonnet-5 |
| …bbbb2222 | issues-review-c1 | 09:00:41 | 120,000 | 62,000 | claude-sonnet-5 |
| …cccc3333 | issues-review-c1 | 09:00:44 | 141,000 | 0 | claude-opus-4-8, claude-sonnet-5 ⚠️SWITCHED |
| …dddd4444 | blind-spots-c2 | 09:02:02 | 60,000 | 21,000 | claude-sonnet-5-20260601 |
| …eeee5555 | validation-1 | 09:04:00 | 0 | 0 | some-other-model |
| …ffff6666 | validation-2 | 09:04:30 | 0 | 0 | some-other-model |

- units with turn-1 cache_read > 0: **3/6** (report the distribution, not a median).
- ⚠️ 1 unit(s) switched models mid-session (overload rescue?) — cache sharing and cost pinning are broken for them: …cccc3333
- chunk 1 forked units: **1 prefix writer(s) / 1 reader(s)** at turn 1 (1 writer is the ideal fork).
- chunk 2 forked units: **1 prefix writer(s) / 0 reader(s)** at turn 1 (1 writer is the ideal fork).
"""

EXPECTED_HEADLINE = (
    "SPEND gens=9 true_usd=$0.89 gw_usd=$0.93 naive_usd=$2.06 failed_gens=1 turn1_hits=3/6 model_switches=1"
)


class TestSpendReport(SimpleTestCase):
    def test_renders_the_section_and_headline_for_a_run(self):
        lines, headline = render_spend_report(ROWS)

        assert "\n".join(lines) == EXPECTED_MARKDOWN
        assert headline == EXPECTED_HEADLINE

    @parameterized.expand(
        [
            ("exact", "claude-sonnet-5", LIST_PRICES["claude-sonnet-5"]),
            ("date suffix", "claude-sonnet-5-20260601", LIST_PRICES["claude-sonnet-5"]),
            ("gateway prefix", "anthropic/claude-opus-4-8", LIST_PRICES["claude-opus-4-8"]),
            ("unknown", "some-other-model", None),
        ]
    )
    def test_price_for_model_id_shapes(self, _name, model, expected):
        assert price_for(model) == expected
