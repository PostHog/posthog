"""Cache-aware `$ai_generation` spend section for the ReviewHog eval run dumps.

`dump_result.py` runs under `manage.py shell` via `exec(open(...).read())`, so its module body
hits ClickHouse and the ORM the moment anything imports it. The spend tally and its Markdown
rendering live here instead, where a test can drive them from synthetic rows.

`$ai_input_tokens` from the gateway is the FULL prompt (fresh + cache read + cache write) —
summing it at input price is the old, naive method and overstates true cost ~5× on cache-heavy
runs. Every gen here splits into fresh (`input - read - write`, 1×) / cache write (1.25×) /
cache read (0.1×) / output per (model × stage); `true $` prices that split at list, `gw $` is the
gateway's LiteLLM-computed `$ai_total_cost_usd`, and the per-side `$ai_*_cost_usd` fields
cross-check the split. A failed gen (`$ai_is_error`) reports no usable tokens or cost, so it is
counted on its own and left out of every tally.
"""

import re
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from posthog.dataclasses import frozen


@frozen
class ListPrice:
    """Per-token list price of one model, mirroring LiteLLM's cost map."""

    fresh_input: float
    output: float
    cache_read: float
    cache_write: float


# List prices per token, mirroring LiteLLM's cost map (the source of the gateway's
# `$ai_total_cost_usd`) as of 2026-07-06. The write rate here is the 5-minute-TTL one
# (1.25× input); 1h-TTL writes bill at 2× input and the events don't carry the 5m/1h split, so
# `true_usd` prices all writes at 1.25× and the gateway's `$ai_cache_creation_cost_usd` (when
# emitted) is the accurate write-side cost.
LIST_PRICES: dict[str, ListPrice] = {
    "claude-sonnet-5": ListPrice(fresh_input=2e-06, output=1e-05, cache_read=2e-07, cache_write=2.5e-06),
    "claude-opus-4-8": ListPrice(fresh_input=5e-06, output=2.5e-05, cache_read=5e-07, cache_write=6.25e-06),
    "claude-fable-5": ListPrice(fresh_input=1e-05, output=5e-05, cache_read=1e-06, cache_write=1.25e-05),
    "claude-haiku-4-5": ListPrice(fresh_input=1e-06, output=5e-06, cache_read=1e-07, cache_write=1.25e-06),
    # Not a pinned model — appears when a session loses its model pin mid-run (session-restart
    # class); priced so a switched unit doesn't poison the run total.
    "claude-sonnet-4-6": ListPrice(fresh_input=3e-06, output=1.5e-05, cache_read=3e-07, cache_write=3.75e-06),
}

# Anthropic's long-context boundary for one request. The gateway's LiteLLM map prices these
# models flat, so the `>200K` column is a diagnostic count, not a pricing input.
_LONG_CTX_TOKENS = 200_000

# Stages that run as their own sandbox unit, so their first gen carries the unit's turn-1 cache split.
_UNIT_STAGES = ("review", "blind-spot", "validation", "warmup")

_SANDBOX_STEP = re.compile(r"\[sandbox_prompt:([a-z0-9_-]+)\]")
_DATE_SUFFIX = re.compile(r"-\d{8}$")
_CHUNK_SUFFIX = re.compile(r"-c(\d+)$")


def price_for(model: str) -> ListPrice | None:
    """List-price row for a model as `$ai_model` reports it; handles date-suffixed variants."""
    if model in LIST_PRICES:
        return LIST_PRICES[model]
    stripped = _DATE_SUFFIX.sub("", model)
    if stripped in LIST_PRICES:
        return LIST_PRICES[stripped]
    for known, prices in LIST_PRICES.items():
        if known in model:
            return prices
    return None


def _stage_of(task_title: str, ai_stage: str) -> str:
    """Pipeline stage of one gen: sandbox units carry `[sandbox_prompt:<step>]` in `task_title`;
    the one-shot chunking/dedup gateway calls carry `ai_stage` instead."""
    m = _SANDBOX_STEP.match(task_title or "")
    step = m.group(1) if m else (ai_stage or "")
    for prefix, stage in (
        ("issues-review", "review"),
        ("blind-spots", "blind-spot"),
        ("validation", "validation"),
        ("chunking", "chunking"),
        ("dedup", "dedup"),
        ("warmup", "warmup"),
    ):
        if step.startswith(prefix):
            return stage
    return f"other:{step}" if step else "other"


def _fmt_tok(n: float) -> str:
    return f"{int(n):,}"


def _fmt_usd(x: float | None) -> str:
    return "—" if x is None else f"${x:,.2f}"


@frozen
class SpendRow:
    """One `$ai_generation` event, as the spend tally reads it."""

    timestamp: datetime
    model: str
    ai_stage: str
    task_title: str
    task_run_id: str
    is_error: bool
    input_tokens: float
    output_tokens: float
    cache_read: float
    cache_write: float
    gw_cost: float | None
    gw_input_cost: float | None
    gw_output_cost: float | None
    gw_cache_read_cost: float | None
    gw_cache_write_cost: float | None

    @classmethod
    def from_clickhouse(cls, row: Sequence[Any]) -> "SpendRow":
        """Row in the column order `fetch_spend_rows` selects."""
        (
            timestamp,
            model,
            ai_stage,
            task_title,
            task_run_id,
            is_error,
            input_tokens,
            output_tokens,
            cache_read,
            cache_write,
            gw_cost,
            gw_input_cost,
            gw_output_cost,
            gw_cache_read_cost,
            gw_cache_write_cost,
        ) = row
        return cls(
            timestamp=timestamp,
            model=model,
            ai_stage=ai_stage,
            task_title=task_title,
            task_run_id=task_run_id,
            is_error=bool(is_error),
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cache_read=cache_read,
            cache_write=cache_write,
            gw_cost=gw_cost,
            gw_input_cost=gw_input_cost,
            gw_output_cost=gw_output_cost,
            gw_cache_read_cost=gw_cache_read_cost,
            gw_cache_write_cost=gw_cache_write_cost,
        )

    @property
    def fresh_input_tokens(self) -> float:
        return max(0.0, self.input_tokens - self.cache_read - self.cache_write)


@frozen
class BucketKey:
    """One (model × stage) cell of the spend table."""

    model: str
    stage: str


@dataclass(frozen=False)
class BucketTally:
    """Token and cost accumulator for one (model × stage) bucket.

    `true_usd` goes `None` for good once an unpriced model lands in the bucket, so the total
    never mixes a partial back-calc with a complete one.
    """

    key: BucketKey
    gens: int = 0
    fresh_in: float = 0.0
    cache_write: float = 0.0
    cache_read: float = 0.0
    output: float = 0.0
    long_ctx_gens: int = 0
    true_usd: float | None = 0.0
    gw_usd: float = 0.0


@dataclass(frozen=False)
class UnitSession:
    """First gen of one sandbox unit, plus every model the unit's session went on to use."""

    run_id: str
    first_gen_at: datetime
    stage: str
    step: str
    cache_read: float
    cache_write: float
    models: set[str]

    @property
    def switched_model(self) -> bool:
        return len(self.models) > 1


@frozen
class RowCost:
    """One gen's list-price cost, split by side. Both the bucket total and the cross-check read
    it, so a row is priced once."""

    fresh: float
    cache_read: float
    cache_write: float
    output: float

    @classmethod
    def of(cls, row: "SpendRow", prices: ListPrice) -> "RowCost":
        return cls(
            fresh=row.fresh_input_tokens * prices.fresh_input,
            cache_read=row.cache_read * prices.cache_read,
            cache_write=row.cache_write * prices.cache_write,
            output=row.output_tokens * prices.output,
        )

    @property
    def input_side(self) -> float:
        return self.fresh + self.cache_read + self.cache_write

    @property
    def total(self) -> float:
        return self.input_side + self.output


@dataclass(frozen=False)
class SideCheck:
    """One cost side of the cross-check: the gateway's own `$ai_*_cost_usd` against the
    back-calc from the token split, over the same gens.

    Holding both columns in one accumulator is what keeps the Δ honest. A row joins a side only
    when the model has a list price and the gateway emitted that row's field, so neither column
    can carry a gen the other one misses.
    """

    gw_usd: float = 0.0
    true_usd: float = 0.0
    gens: int = 0

    def add(self, *, gw_usd: float, true_usd: float) -> None:
        self.gw_usd += gw_usd
        self.true_usd += true_usd
        self.gens += 1

    @property
    def delta_note(self) -> str:
        if not self.true_usd:
            return ""
        return f" (true ${self.true_usd:,.4f}, Δ {(self.gw_usd - self.true_usd) / self.true_usd:+.1%})"


@dataclass(frozen=False)
class SideChecks:
    """The five cross-check lines. `input_side` is the whole input side, cache included, and
    `fresh` is what is left of each row's input cost once its cache sides come off."""

    input_side: SideCheck = field(default_factory=SideCheck)
    cache_read: SideCheck = field(default_factory=SideCheck)
    cache_write: SideCheck = field(default_factory=SideCheck)
    fresh: SideCheck = field(default_factory=SideCheck)
    output: SideCheck = field(default_factory=SideCheck)

    @property
    def any_emitted(self) -> bool:
        return any(side.gens for side in (self.input_side, self.cache_read, self.cache_write, self.output))


@dataclass(frozen=False)
class UnpricedModel:
    gens: int = 0
    gw_usd: float = 0.0


@frozen
class SpendTotals:
    """Run-wide column totals. `true_usd` covers the priced buckets only; `gw_usd` covers all."""

    gens: int
    fresh_in: float
    cache_write: float
    cache_read: float
    output: float
    long_ctx_gens: int
    true_usd: float
    gw_usd: float
    unpriced: dict[str, UnpricedModel]

    @property
    def gw_usd_priced(self) -> float:
        return self.gw_usd - sum(u.gw_usd for u in self.unpriced.values())


class SpendTally:
    """Folds `$ai_generation` rows into (model × stage) buckets and per-unit sessions."""

    def __init__(self) -> None:
        self.buckets: dict[BucketKey, BucketTally] = {}
        self.units: dict[str, UnitSession] = {}
        self.gw_missing = 0
        self.failed_gens = 0
        self.naive_usd = 0.0
        self.sides = SideChecks()

    def add(self, row: SpendRow) -> None:
        # A failed gen usually reports no tokens and no cost, so counting it would drag the
        # per-unit tally to zero and leave the unit's real first turn unrecorded.
        if row.is_error:
            self.failed_gens += 1
            return
        stage = _stage_of(row.task_title, row.ai_stage)
        key = BucketKey(model=row.model or "(unknown)", stage=stage)
        bucket = self.buckets.get(key)
        if bucket is None:
            bucket = self.buckets[key] = BucketTally(key=key)
        self._add_tokens(bucket, row)
        self._add_costs(bucket, row)
        self._track_unit(row, stage)

    @staticmethod
    def _add_tokens(bucket: BucketTally, row: SpendRow) -> None:
        bucket.gens += 1
        bucket.fresh_in += row.fresh_input_tokens
        bucket.cache_write += row.cache_write
        bucket.cache_read += row.cache_read
        bucket.output += row.output_tokens
        bucket.long_ctx_gens += 1 if row.input_tokens > _LONG_CTX_TOKENS else 0

    def _add_costs(self, bucket: BucketTally, row: SpendRow) -> None:
        prices = price_for(row.model or "")
        if prices is None:
            bucket.true_usd = None
        else:
            cost = RowCost.of(row, prices)
            if bucket.true_usd is not None:
                bucket.true_usd += cost.total
            self.naive_usd += row.input_tokens * prices.fresh_input + cost.output
            self._add_crosscheck(row, cost)
        if row.gw_cost is None:
            self.gw_missing += 1
        else:
            bucket.gw_usd += row.gw_cost

    def _add_crosscheck(self, row: SpendRow, cost: RowCost) -> None:
        if row.gw_input_cost is not None:
            self.sides.input_side.add(gw_usd=row.gw_input_cost, true_usd=cost.input_side)
            # The gateway has no fresh-input field, so fresh comes off each row's own input cost.
            # Subtracting run-wide cache totals instead would mix rows that emitted a cache field
            # into a line the other rows never joined.
            gw_fresh = row.gw_input_cost - (row.gw_cache_read_cost or 0.0) - (row.gw_cache_write_cost or 0.0)
            self.sides.fresh.add(gw_usd=gw_fresh, true_usd=cost.fresh)
        if row.gw_cache_read_cost is not None:
            self.sides.cache_read.add(gw_usd=row.gw_cache_read_cost, true_usd=cost.cache_read)
        if row.gw_cache_write_cost is not None:
            self.sides.cache_write.add(gw_usd=row.gw_cache_write_cost, true_usd=cost.cache_write)
        if row.gw_output_cost is not None:
            self.sides.output.add(gw_usd=row.gw_output_cost, true_usd=cost.output)

    def _track_unit(self, row: SpendRow, stage: str) -> None:
        if not row.task_run_id:
            return
        unit = self.units.get(row.task_run_id)
        if unit is not None:
            # A models set > 1 exposes a silent mid-session model switch (e.g. the overload
            # rescue), which breaks cache sharing and cost pinning.
            unit.models.add(row.model)
            return
        if stage not in _UNIT_STAGES:
            return
        step = _SANDBOX_STEP.match(row.task_title or "")
        self.units[row.task_run_id] = UnitSession(
            run_id=row.task_run_id,
            first_gen_at=row.timestamp,
            stage=stage,
            step=step.group(1) if step else "",
            cache_read=row.cache_read,
            cache_write=row.cache_write,
            models={row.model},
        )

    def ordered_buckets(self) -> list[BucketTally]:
        """Buckets by descending gateway spend — the expensive ones read first."""
        return sorted(self.buckets.values(), key=lambda bucket: -bucket.gw_usd)

    def ordered_units(self) -> list[UnitSession]:
        return sorted(self.units.values(), key=lambda unit: unit.first_gen_at)

    def totals(self) -> SpendTotals:
        # Walks the rendered bucket order so the unpriced-model notes read in the same order as
        # the table rows above them.
        gens = long_ctx = 0
        fresh_in = cache_write = cache_read = output = 0.0
        true_total = gw_total = 0.0
        unpriced: dict[str, UnpricedModel] = {}
        for bucket in self.ordered_buckets():
            gens += bucket.gens
            fresh_in += bucket.fresh_in
            cache_write += bucket.cache_write
            cache_read += bucket.cache_read
            output += bucket.output
            long_ctx += bucket.long_ctx_gens
            gw_total += bucket.gw_usd
            if bucket.true_usd is None:
                entry = unpriced.setdefault(bucket.key.model, UnpricedModel())
                entry.gens += bucket.gens
                entry.gw_usd += bucket.gw_usd
            else:
                true_total += bucket.true_usd
        return SpendTotals(
            gens=gens,
            fresh_in=fresh_in,
            cache_write=cache_write,
            cache_read=cache_read,
            output=output,
            long_ctx_gens=long_ctx,
            true_usd=true_total,
            gw_usd=gw_total,
            unpriced=unpriced,
        )


class SpendReport:
    """Renders one run's tally as the dump's Markdown section plus a one-line stdout headline."""

    def __init__(self, tally: SpendTally) -> None:
        self._tally = tally
        self._totals = tally.totals()

    def markdown(self) -> list[str]:
        return [
            *self._bucket_table(),
            "",
            *self._pricing_notes(),
            *self._side_crosscheck(),
            *self._long_ctx_note(),
            "",
            *self._unit_section(),
        ]

    def headline(self) -> str:
        units = self._tally.units.values()
        naive = _fmt_usd(self._tally.naive_usd) if self._tally.naive_usd else "—"
        return (
            f"SPEND gens={self._totals.gens} true_usd={_fmt_usd(self._totals.true_usd)} "
            f"gw_usd={_fmt_usd(self._totals.gw_usd)} naive_usd={naive} "
            f"failed_gens={self._tally.failed_gens} "
            f"turn1_hits={sum(1 for u in units if u.cache_read > 0)}/{len(self._tally.units)} "
            f"model_switches={sum(1 for u in units if u.switched_model)}"
        )

    def _bucket_table(self) -> list[str]:
        t = self._totals
        lines = [
            "### Cache-aware spend (local `$ai_generation`, best-effort)\n",
            "| model | stage | gens | fresh in | cache write | cache read | output | >200K gens | true $ | gw $ |",
            "| ----- | ----- | ---- | -------- | ----------- | ---------- | ------ | ---------- | ------ | ---- |",
        ]
        for b in self._tally.ordered_buckets():
            lines.append(
                f"| {b.key.model} | {b.key.stage} | {b.gens} | {_fmt_tok(b.fresh_in)} | {_fmt_tok(b.cache_write)} "
                f"| {_fmt_tok(b.cache_read)} | {_fmt_tok(b.output)} | {b.long_ctx_gens} "
                f"| {_fmt_usd(b.true_usd)} | {_fmt_usd(b.gw_usd)} |"
            )
        lines.append(
            f"| **total** |  | **{t.gens}** | **{_fmt_tok(t.fresh_in)}** | **{_fmt_tok(t.cache_write)}** "
            f"| **{_fmt_tok(t.cache_read)}** | **{_fmt_tok(t.output)}** | **{t.long_ctx_gens}** "
            f"| **{_fmt_usd(t.true_usd)}** | **{_fmt_usd(t.gw_usd)}** |"
        )
        return lines

    def _pricing_notes(self) -> list[str]:
        t = self._totals
        delta = (
            f"Δ (priced buckets) = {(t.gw_usd_priced - t.true_usd) / t.true_usd:+.1%}."
            if t.true_usd
            else "Δ not computable."
        )
        lines = [
            "- `true $` = list-price back-calc (fresh 1× + cache write 1.25× + cache read 0.1× + output); "
            "`gw $` = gateway `$ai_total_cost_usd` (LiteLLM). " + delta
        ]
        if self._tally.failed_gens:
            lines.append(
                f"- {self._tally.failed_gens} failed gen(s) (`$ai_is_error`) are left out of every "
                "column above and of the per-unit table below."
            )
        for model, u in t.unpriced.items():
            lines.append(
                f"- `true $` total excludes unpriced model `{model}` ({u.gens} gen(s), gw {_fmt_usd(u.gw_usd)})."
            )
        if self._tally.gw_missing:
            lines.append(
                f"- {self._tally.gw_missing} gen(s) had no `$ai_total_cost_usd` — `gw $` undercounts by those gens."
            )
        if self._tally.naive_usd and t.true_usd:
            lines.append(
                f"- naive method (all prompt tokens at input price): ${self._tally.naive_usd:,.2f} — "
                f"{self._tally.naive_usd / t.true_usd:.1f}× the true cost; never gate on it."
            )
        return lines

    def _side_crosscheck(self) -> list[str]:
        sides = self._tally.sides
        if not sides.any_emitted:
            return []
        lines = [
            "- gateway per-side cross-check (priced gens that emitted the field, both columns over "
            "the same gens; LiteLLM's `input_cost` is the whole input side, cache included):"
        ]
        checks = [
            ("input side (fresh + cache write + cache read)", sides.input_side),
            ("· of which cache read", sides.cache_read),
            ("· of which cache write", sides.cache_write),
            ("· of which fresh (derived)", sides.fresh),
            ("output", sides.output),
        ]
        for label, side in checks:
            lines.append(f"  - {label}: ${side.gw_usd:,.4f} over {side.gens} gen(s){side.delta_note}")
        write = sides.cache_write
        if write.gens and write.true_usd and write.gw_usd > write.true_usd * 1.05:
            lines.append(
                "  - write-side excess over the 1.25× back-calc = 1h-TTL cache writes "
                "(billed 2×; the token split can't see the TTL)."
            )
        return lines

    def _long_ctx_note(self) -> list[str]:
        if not self._totals.long_ctx_gens:
            return []
        return [
            f"- {self._totals.long_ctx_gens} gen(s) ran with >200K-token prompts; the gateway map prices these models "
            "flat, so no long-context premium is included in either column."
        ]

    def _unit_section(self) -> list[str]:
        units = self._tally.ordered_units()
        if not units:
            return []
        hits = sum(1 for u in units if u.cache_read > 0)
        lines = [
            "### Turn-1 cache reads per sandbox unit (cross-sandbox sharing tripwire)\n",
            "| unit | step | first gen | t1 cache read | t1 cache write | models |",
            "| ---- | ---- | --------- | ------------- | -------------- | ------ |",
        ]
        for u in units:
            models = ", ".join(sorted(u.models)) + (" ⚠️SWITCHED" if u.switched_model else "")
            lines.append(
                f"| …{u.run_id[-8:]} | {u.step or u.stage} | {u.first_gen_at:%H:%M:%S} | {_fmt_tok(u.cache_read)} "
                f"| {_fmt_tok(u.cache_write)} | {models} |"
            )
        lines.append("")
        lines.append(
            f"- units with turn-1 cache_read > 0: **{hits}/{len(units)}** (report the distribution, not a median)."
        )
        switched = [u.run_id for u in units if u.switched_model]
        if switched:
            lines.append(
                f"- ⚠️ {len(switched)} unit(s) switched models mid-session (overload rescue?) — "
                "cache sharing and cost pinning are broken for them: " + ", ".join(f"…{r[-8:]}" for r in switched)
            )
        lines += self._fork_collision_notes(units)
        lines.append("")
        return lines

    @staticmethod
    def _fork_collision_notes(units: list[UnitSession]) -> list[str]:
        """Per chunk, forked units landing inside the seconds-wide cache-write window each rewrite
        the shared replay prefix. 1 writer + N readers is the ideal; more writers = harmless
        double-writes (~$0.10 each) worth a stagger if common. Warm-up+fork arm only."""
        if not any(u.step.startswith("warmup") for u in units):
            return []
        by_chunk: dict[str, list[UnitSession]] = {}
        for u in units:
            m = _CHUNK_SUFFIX.search(u.step)
            if m and u.stage in ("review", "blind-spot"):
                by_chunk.setdefault(m.group(1), []).append(u)
        lines = []
        for chunk_id in sorted(by_chunk):
            chunk_units = by_chunk[chunk_id]
            writers = sum(1 for u in chunk_units if u.cache_write > 20_000)
            lines.append(
                f"- chunk {chunk_id} forked units: **{writers} prefix writer(s) / "
                f"{len(chunk_units) - writers} reader(s)** at turn 1 (1 writer is the ideal fork)."
            )
        return lines


def fetch_spend_rows(start_dt: datetime) -> list[SpendRow]:
    """Per-gen `$ai_generation` rows since the run started, time-ordered. Raises on CH errors."""
    from posthog.clickhouse.client import sync_execute  # noqa: PLC0415 — optional, only for the spend tally

    rows = sync_execute(
        """
        SELECT
            timestamp,
            JSONExtractString(properties, '$ai_model') AS model,
            JSONExtractString(properties, 'ai_stage') AS ai_stage,
            JSONExtractString(properties, 'task_title') AS task_title,
            JSONExtractString(properties, 'task_run_id') AS task_run_id,
            JSONExtractString(properties, '$ai_is_error') = 'true' AS is_error,
            toFloat64OrZero(JSONExtractString(properties, '$ai_input_tokens')) AS input_tokens,
            toFloat64OrZero(JSONExtractString(properties, '$ai_output_tokens')) AS output_tokens,
            toFloat64OrZero(JSONExtractString(properties, '$ai_cache_read_input_tokens')) AS cache_read,
            toFloat64OrZero(JSONExtractString(properties, '$ai_cache_creation_input_tokens')) AS cache_write,
            toFloat64OrNull(JSONExtractString(properties, '$ai_total_cost_usd')) AS gw_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_input_cost_usd')) AS gw_input_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_output_cost_usd')) AS gw_output_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_cache_read_cost_usd')) AS gw_cache_read_cost,
            toFloat64OrNull(JSONExtractString(properties, '$ai_cache_creation_cost_usd')) AS gw_cache_write_cost
        FROM events
        WHERE event = '$ai_generation' AND timestamp >= %(start)s
        ORDER BY timestamp
        """,
        {"start": start_dt},
    )
    return [SpendRow.from_clickhouse(row) for row in rows]


def render_spend_report(rows: Iterable[SpendRow]) -> tuple[list[str], str]:
    """Markdown lines and stdout headline for a run's gens."""
    tally = SpendTally()
    for row in rows:
        tally.add(row)
    report = SpendReport(tally)
    return report.markdown(), report.headline()


def spend_report(start_dt: datetime) -> tuple[list[str], str | None]:
    """Spend section for the dump. Never raises — spend is a secondary metric next to the
    review-unit count, so a ClickHouse failure degrades to a one-line note."""
    try:
        rows = fetch_spend_rows(start_dt)
    except Exception as e:  # pragma: no cover - best effort
        return [f"- cache-aware spend: unavailable ({type(e).__name__}: {e})"], None
    if not rows:
        return [
            "- cache-aware spend: no `$ai_generation` events in the window "
            "(likely emitted to a cloud project, or not yet ingested)."
        ], None
    return render_spend_report(rows)
