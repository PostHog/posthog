"""Ranking for the What to watch feed: which succeeded observations in a window are worth a look.

Deterministic v1, no model calls. Baselines come from the candidate rows themselves (the scanner's
own window), so "outlier" and "rare" mean unusual for that scanner lately, not against all history.
"""

import re
from collections import deque
from datetime import datetime
from statistics import fmean, stdev
from typing import Any
from uuid import UUID

from posthog.dataclasses import frozen

# Below this many rows a scanner's window baseline is noise, so the scanner gets no type hit.
MIN_BASELINE_ROWS = 5
OUTLIER_STDDEVS = 1.5
RARE_TAG_MAX_SHARE = 0.1
# When more than this share of a scanner's tagged rows carry a "rare" tag, the vocabulary isn't
# discriminating (e.g. freeform tags that never repeat) and rarity means nothing — suppress the rule.
RARE_TAG_MAX_HIT_SHARE = 0.5
# The scan's own judgment of how much a team would benefit from watching the session. At or above this it
# ranks as notable on its own, regardless of what the scanner was asked.
NOTABLE_MIN_SCORE = 0.6
# A monitor verdict carried by at most this share of the scanner's window rows is the unusual
# answer, whatever the prompt's polarity ("did they struggle?" vs "was the experience good?").
UNUSUAL_VERDICT_MAX_SHARE = 0.35
# A summary whose best token overlap with the scanner's other summaries stays at or below this is
# treated as an unusual session. Conservative on purpose: prose varies, so only clear outliers hit.
NOVEL_SUMMARY_MAX_SIMILARITY = 0.15
# Jaccard divides by the union, so a very short summary reads as "novel" against any longer one
# regardless of content. Below this many tokens the comparison measures length, not meaning.
NOVEL_SUMMARY_MIN_TOKENS = 8
# Compare against at most this many of the scanner's newest summaries. Bounds the novelty pass to
# O(rows x this) — all-pairs would be quadratic in the scanner's window, which an authenticated
# viewer could lean on by hammering the broad feed.
NOVEL_SUMMARY_MAX_SIBLINGS = 40

# Component weights for the blended watchability score. The feed is a portfolio of the window's most
# watchable rows, not signals first and everything after, so the signal weight sits below the hit weight: a
# wide outlier or a rare verdict outranks even the most confident lone signal. Retune here.
WATCH_WEIGHT_SIGNAL = 0.8
WATCH_WEIGHT_HIT = 0.9
WATCH_WEIGHT_NOTABILITY = 0.7
WATCH_WEIGHT_FRICTION = 0.3
# A row the reader already opened keeps its evidence but drops by this much, so an unviewed peer with
# comparable evidence comes first while a strong seen row (a signal, a wide outlier) still holds its
# place above routine unseen rows.
WATCH_SEEN_PENALTY = 0.5
# A no-baseline "yes" verdict is the weak conventional something-happened phrasing, so it enters the
# blend below a verdict the scanner's own window shows to be rare.
VERDICT_YES_STRENGTH = 0.5
# Signal strength is the row's most confident finding, and emission floors confidence at 0.4, so a live value
# runs 0.4-1.0. A row scanned before summaries shipped carries a count and no confidence, and takes the
# midpoint of that range: it neither outranks the rows around it nor sinks below them.
SIGNAL_LEGACY_STRENGTH = 0.7
# The share of the feed signal rows may hold, above the leading row and while other rows remain to place.
# Signals corroborate across sessions, so a window full of them says the scanner is working, not that a
# reader should watch all of them.
WATCH_FEED_MAX_SIGNAL_SHARE = 0.4
# Reason kinds that say nothing about the session: the fall-through for a row that scored on no source at
# all. They are ordering, not evidence, so the feed carries them only to reach the floor below.
FILLER_REASON_KINDS = frozenset({"unviewed_recent", "recent"})
# How short the feed may get before filler rows pad it. A feed of 3 real findings beats one of 3 findings
# and 17 "new since you last looked", and a feed that empties the moment nothing is wrong reads as broken.
WATCH_FEED_MIN_ITEMS = 3
# The score deviation, in stddevs, at which an outlier counts full strength. The hit fires at
# OUTLIER_STDDEVS; its strength climbs from there to 1.0 by this many stddevs, so a wider outlier ranks
# above a marginal one instead of both reading as the same boolean hit.
OUTLIER_FULL_STDDEVS = 3.0

_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Friction language in the model's own prose about the session. Stems, so "retried"/"retrying",
# "failed"/"failure", "confused"/"confusing" all hit. Known weakness, not fixable with keywords: a team
# whose product is about errors (error tracking, debugging) matches on happy sessions too, which is why
# friction ranks below seen-state and never reaches the top tiers. Widen with care.
_FRICTION_RE = re.compile(
    r"\b(error|errors|fail(?:ed|ing|ure|s)?|stuck|struggl\w*|confus\w*|frustrat\w*|abandon\w*|"
    r"rage.?click\w*|dead.?end\w*|broken|crash\w*|bug|bugs|retr(?:y|ied|ies|ying)|time(?:d|s)?.?out|"
    r"gave up|give up|churn\w*|unable|couldn.?t|blocked|glitch\w*|freez\w*|froze|unresponsive)\b",
    re.IGNORECASE,
)


@frozen
class WatchFeedEntry:
    observation_id: UUID
    reason: dict[str, Any]


@frozen
class _Candidate:
    observation_id: UUID
    scanner_id: UUID
    created_at: datetime
    viewed: bool
    signals_count: int
    signal_problem_types: tuple[str, ...]
    # (problem_type, headline, confidence) per emitted signal. Empty on rows scanned before this shipped.
    signal_summaries: tuple[tuple[str, str, float], ...]
    scanner_type: str | None
    verdict: str | None
    score: float | None
    tags: tuple[str, ...]
    summary_tokens: frozenset[str]
    friction: bool
    notability: float | None
    notability_reason: str | None


def _parse_candidate(row: dict[str, Any]) -> _Candidate:
    """Read the ranking features off a raw row, tolerating malformed `scanner_result` — a bad row
    ranks by recency only rather than failing the whole feed."""
    result = row.get("scanner_result")
    output = result.get("model_output") if isinstance(result, dict) else None
    if not isinstance(output, dict):
        output = {}
    signals_count = result.get("signals_count") if isinstance(result, dict) else 0
    raw_problem_types = result.get("signal_problem_types") if isinstance(result, dict) else None
    signal_problem_types = (
        tuple(pt for pt in raw_problem_types if isinstance(pt, str)) if isinstance(raw_problem_types, list) else ()
    )
    raw_summaries = result.get("signal_summaries") if isinstance(result, dict) else None
    signal_summaries = (
        tuple(
            (entry["problem_type"], entry["headline"], float(entry["confidence"]))
            for entry in raw_summaries
            if isinstance(entry, dict)
            and isinstance(entry.get("problem_type"), str)
            # A blank headline would leave the card's sentence trailing off, so the row counts instead.
            and isinstance(entry.get("headline"), str)
            and entry["headline"].strip()
            and isinstance(entry.get("confidence"), int | float)
            and not isinstance(entry.get("confidence"), bool)
        )
        if isinstance(raw_summaries, list)
        else ()
    )
    score = output.get("score")
    raw_tags = output.get("tags")
    raw_freeform = output.get("tags_freeform")
    tags = [
        *(raw_tags if isinstance(raw_tags, list) else []),
        *(raw_freeform if isinstance(raw_freeform, list) else []),
    ]
    title = output.get("title")
    summary = output.get("summary")
    reasoning = output.get("reasoning")
    summary_text = " ".join(part for part in (title, summary) if isinstance(part, str))
    prose = " ".join(part for part in (title, summary, reasoning) if isinstance(part, str))
    notability = output.get("notability")
    notability_reason = output.get("notability_reason")
    scanner_type = output.get("scanner_type") if isinstance(output.get("scanner_type"), str) else None
    verdict = output.get("verdict") if isinstance(output.get("verdict"), str) else None
    # A no-verdict monitor's reasoning restates its question in the negative ("did not struggle"),
    # so keyword matching there reads negations as friction; the scan already judged it a non-event.
    friction_eligible = not (scanner_type == "monitor" and verdict == "no")
    return _Candidate(
        observation_id=row["id"],
        scanner_id=row["scanner_id"],
        created_at=row["created_at"],
        viewed=bool(row.get("feed_viewed")),
        signals_count=signals_count if isinstance(signals_count, int) else 0,
        signal_problem_types=signal_problem_types,
        signal_summaries=signal_summaries,
        scanner_type=scanner_type,
        verdict=verdict,
        score=float(score) if isinstance(score, int | float) else None,
        tags=tuple(tag for tag in tags if isinstance(tag, str)),
        summary_tokens=frozenset(_TOKEN_RE.findall(summary_text.lower())),
        friction=friction_eligible and bool(_FRICTION_RE.search(" ".join([prose, *tags]))),
        # The LLM-response schema bounds this to 0-1, but a stored row (or a bool, since bool is an int
        # subclass) can carry anything, so clamp defensively — an out-of-range value would outrank its tier.
        notability=(
            min(1.0, max(0.0, float(notability)))
            if isinstance(notability, int | float) and not isinstance(notability, bool)
            else None
        ),
        notability_reason=notability_reason if isinstance(notability_reason, str) and notability_reason else None,
    )


@frozen
class _ScannerBaseline:
    row_count: int
    score_mean: float | None
    score_stddev: float | None
    tag_shares: dict[str, float]
    rare_tags: frozenset[str]
    verdict_shares: dict[str, float]


def _baselines(candidates: list[_Candidate]) -> dict[UUID, _ScannerBaseline]:
    by_scanner: dict[UUID, list[_Candidate]] = {}
    for candidate in candidates:
        by_scanner.setdefault(candidate.scanner_id, []).append(candidate)
    baselines: dict[UUID, _ScannerBaseline] = {}
    for scanner_id, rows in by_scanner.items():
        scores = [row.score for row in rows if row.score is not None]
        tag_counts: dict[str, int] = {}
        verdict_counts: dict[str, int] = {}
        tagged_rows = [row for row in rows if row.tags]
        for row in rows:
            for tag in set(row.tags):
                tag_counts[tag] = tag_counts.get(tag, 0) + 1
            if row.verdict is not None:
                verdict_counts[row.verdict] = verdict_counts.get(row.verdict, 0) + 1
        verdict_total = sum(verdict_counts.values())
        # Shares are over rows that carry tags at all, so untagged/malformed rows don't make every
        # real tag look rarer than it is (verdict_shares already divides by verdict_total for the
        # same reason). A singleton always counts as rare: a pure share cutoff makes rarity
        # impossible below 1/RARE_TAG_MAX_SHARE rows and then fire on every singleton at exactly
        # that size, so the feed would change character as a scanner accumulates data.
        tag_shares = {tag: count / len(tagged_rows) for tag, count in tag_counts.items()} if tagged_rows else {}
        rare_tags = (
            frozenset(tag for tag, count in tag_counts.items() if count == 1 or tag_shares[tag] <= RARE_TAG_MAX_SHARE)
            if len(tagged_rows) >= MIN_BASELINE_ROWS
            else frozenset()
        )
        if rare_tags:
            rare_rows = sum(1 for row in tagged_rows if rare_tags & set(row.tags))
            if rare_rows / len(tagged_rows) > RARE_TAG_MAX_HIT_SHARE:
                rare_tags = frozenset()
        baselines[scanner_id] = _ScannerBaseline(
            row_count=len(rows),
            score_mean=fmean(scores) if len(scores) >= MIN_BASELINE_ROWS else None,
            score_stddev=stdev(scores) if len(scores) >= MIN_BASELINE_ROWS else None,
            tag_shares=tag_shares,
            rare_tags=rare_tags,
            verdict_shares=(
                {verdict: count / verdict_total for verdict, count in verdict_counts.items()}
                if verdict_total >= MIN_BASELINE_ROWS
                else {}
            ),
        )
    return baselines


def _max_summary_similarity(candidate: _Candidate, siblings: list[_Candidate]) -> float | None:
    """Best token-set Jaccard similarity of this summary against the scanner's newest other summaries
    (at most NOVEL_SUMMARY_MAX_SIBLINGS — siblings arrive newest-first from the candidate query).
    None when the window is too thin to say what "usual" reads like."""
    others = [
        row.summary_tokens for row in siblings if row.observation_id != candidate.observation_id and row.summary_tokens
    ][:NOVEL_SUMMARY_MAX_SIBLINGS]
    if len(candidate.summary_tokens) < NOVEL_SUMMARY_MIN_TOKENS or len(others) < MIN_BASELINE_ROWS - 1:
        return None
    return max(len(candidate.summary_tokens & other) / len(candidate.summary_tokens | other) for other in others)


def _type_hit(
    candidate: _Candidate, baseline: _ScannerBaseline, siblings: list[_Candidate]
) -> tuple[dict[str, Any], float] | None:
    """The type-specific reason this row stands out for its scanner and how strongly, or None.

    The strength is in (0, 1]: a wide score outlier, a very rare verdict or tag, or a summary unlike
    its siblings scores near 1; a marginal hit scores near the floor of its rule. It feeds the blended
    score only — the returned reason dict is unchanged, so the card copy stays the same.
    """
    if candidate.scanner_type == "monitor" and candidate.verdict in ("yes", "no"):
        # With a baseline, the notable answer is the scanner's own minority verdict — prompt
        # polarity doesn't matter ("did they struggle?" vs "was the experience good?"). Without
        # one, fall back to yes, the conventional something-happened phrasing.
        if baseline.verdict_shares:
            share = baseline.verdict_shares.get(candidate.verdict, 0.0)
            if share <= UNUSUAL_VERDICT_MAX_SHARE:
                reason = {"kind": "unusual_verdict", "verdict": candidate.verdict, "verdict_share": round(share, 3)}
                return reason, 1.0 - share
        elif candidate.verdict == "yes":
            return {"kind": "verdict_yes"}, VERDICT_YES_STRENGTH
    if candidate.scanner_type == "summarizer":
        similarity = _max_summary_similarity(candidate, siblings)
        if similarity is not None and similarity <= NOVEL_SUMMARY_MAX_SIMILARITY:
            return {"kind": "novel_summary"}, 1.0 - similarity
    if (
        candidate.scanner_type == "scorer"
        and candidate.score is not None
        and baseline.score_mean is not None
        and baseline.score_stddev is not None
        # A flat window (every score identical) makes any deviation infinite sigmas; skip it.
        and baseline.score_stddev > 0
        and abs(candidate.score - baseline.score_mean) >= OUTLIER_STDDEVS * baseline.score_stddev
    ):
        sigma = abs(candidate.score - baseline.score_mean) / baseline.score_stddev
        reason = {"kind": "outlier_score", "score": candidate.score, "window_mean": round(baseline.score_mean, 2)}
        return reason, min(1.0, sigma / OUTLIER_FULL_STDDEVS)
    if candidate.scanner_type == "classifier" and baseline.rare_tags:
        rare = [(baseline.tag_shares[tag], tag) for tag in set(candidate.tags) if tag in baseline.rare_tags]
        if rare:
            share, tag = min(rare)
            return {"kind": "rare_tag", "tag": tag, "tag_share": round(share, 3)}, 1.0 - share
    return None


def _signal_strength(candidate: _Candidate) -> float:
    """How strongly the row's signals argue for watching it: the confidence of its most confident finding.
    A flat 1.0 for any signal made a marginal finding rank level with an unmistakable one."""
    if candidate.signal_summaries:
        return max(confidence for _, _, confidence in candidate.signal_summaries)
    return SIGNAL_LEGACY_STRENGTH if candidate.signals_count > 0 else 0.0


def _contributions(candidate: _Candidate, hit_strength: float) -> dict[str, float]:
    """The weighted evidence this row carries, one entry per source. `_watchability` sums these and the
    displayed reason names the largest of them, so the order and the copy read the same numbers."""
    return {
        "signal": WATCH_WEIGHT_SIGNAL * _signal_strength(candidate),
        "hit": WATCH_WEIGHT_HIT * hit_strength,
        "notability": WATCH_WEIGHT_NOTABILITY * (candidate.notability if candidate.notability is not None else 0.0),
        "friction": WATCH_WEIGHT_FRICTION * (1.0 if candidate.friction else 0.0),
    }


def _watchability(candidate: _Candidate, hit_strength: float) -> float:
    """Blend the row's signal, type hit, notability, and friction into one score, then dock a row the
    reader already opened. Every source contributes at once, so a row wins on the sum of its evidence
    rather than on a single dominant flag."""
    score = sum(_contributions(candidate, hit_strength).values())
    if candidate.viewed:
        score -= WATCH_SEEN_PENALTY
    return score


def _strongest_reason_part(candidate: _Candidate, contributions: dict[str, float]) -> str | None:
    """Which source the card should name, or None when the row carries no evidence at all.

    The largest weighted part wins. Ties break signal, hit, notability, friction — the order the old
    fixed ladder used — so a row with two equal parts reads the way it always did.
    """
    parts = dict(contributions)
    # Notability below the tier threshold still adds to the score, but the card must not say the scan judged
    # the session worth watching when it did not. The old ladder held this rule; the label holds it now.
    if candidate.notability is None or candidate.notability < NOTABLE_MIN_SCORE:
        parts["notability"] = 0.0
    winner = max(("signal", "hit", "notability", "friction"), key=lambda part: parts[part])
    return winner if parts[winner] > 0 else None


def _cap_signal_share(ranked: list[WatchFeedEntry]) -> list[WatchFeedEntry]:
    """Hold signal cards to WATCH_FEED_MAX_SIGNAL_SHARE of the feed as it is placed.

    The share is checked per place rather than over the whole list, because the view slices the head of this
    list: a feed of 5 obeys the same share as a feed of 50. Two rows are exempt by design. The best row
    always leads, whatever it is. And a window with more signal rows than the share can hold runs out of
    other rows to interleave, so the rest trail the feed rather than disappear from it — reordering the feed
    is the job here, shortening it is not.

    Because `_trim_filler` runs first, the rows a signal is held against are other findings, not padding.
    So a window whose only findings are signals returns a feed of signals: the share keeps signals from
    crowding out an outlier or a rare verdict, and was never meant to dilute them with clips that carry
    nothing.
    """
    placed: list[WatchFeedEntry] = []
    # A deque, because the candidate cap is 1000 and every admitted row pops from the front.
    held: deque[WatchFeedEntry] = deque()
    signals_placed = 0
    for entry in ranked:
        if entry.reason["kind"] == "signal_emitted":
            held.append(entry)
        else:
            placed.append(entry)
        while held and (not placed or (signals_placed + 1) / (len(placed) + 1) <= WATCH_FEED_MAX_SIGNAL_SHARE):
            placed.append(held.popleft())
            signals_placed += 1
    return placed + list(held)


def _trim_filler(ranked: list[WatchFeedEntry]) -> list[WatchFeedEntry]:
    """Drop the no-evidence rows once WATCH_FEED_MIN_ITEMS real findings are in the feed.

    `limit` is a ceiling the feed had been filling: a quiet window returned 20 cards of which 17 said
    "New since you last looked", which buries the few that meant something. Findings are kept whatever
    their count; filler only makes up the difference to the floor, so a window with nothing to say
    returns 3 newest clips rather than 20 or an empty state.
    """
    findings = [entry for entry in ranked if entry.reason["kind"] not in FILLER_REASON_KINDS]
    if len(findings) >= WATCH_FEED_MIN_ITEMS:
        return findings
    # Walk rather than concatenate, because a row the reader already opened is docked half a point and can
    # sort below an unviewed filler row — findings are not always a prefix of the list.
    budget = WATCH_FEED_MIN_ITEMS - len(findings)
    kept: list[WatchFeedEntry] = []
    for entry in ranked:
        if entry.reason["kind"] not in FILLER_REASON_KINDS:
            kept.append(entry)
        elif budget > 0:
            kept.append(entry)
            budget -= 1
    return kept


def rank_watch_feed_candidates(rows: list[dict[str, Any]]) -> list[WatchFeedEntry]:
    """Rank candidate rows (`id`, `scanner_id`, `created_at`, `scanner_result`, `feed_viewed`) most
    watchable first by a blended score, then newest.

    The score adds four sources at once — emitted signals, a type-specific hit, the scan's own
    notability judgment, and prose that reads as friction — each weighted, so a row wins on the sum of
    its evidence. A type hit plus a high notability can outrank a routine signal, rather than every
    signal outranking everything else. A row the reader already opened keeps its evidence but is docked,
    so an unviewed peer comes first while a strong seen row still holds its place above routine unseen
    rows.

    The displayed reason names the largest weighted part of that same score, so the card explains the
    position it earned. It used to name a signal whenever the row carried one, which labelled a row as
    `signal_emitted` even when a wide outlier was the stronger evidence and made the feed read as signals
    with a few other things in it.

    Rows that scored on nothing are then trimmed to a floor of WATCH_FEED_MIN_ITEMS, and the signal rows
    that survive are interleaved down to WATCH_FEED_MAX_SIGNAL_SHARE of the result; see `_trim_filler` and
    `_cap_signal_share`. The trim runs first on purpose: trimming afterwards would strip the very rows the
    cap interleaved signals against, so a feed that satisfied the share when built would breach it on the
    way out.
    """
    candidates = [_parse_candidate(row) for row in rows]
    baselines = _baselines(candidates)
    by_scanner: dict[UUID, list[_Candidate]] = {}
    for candidate in candidates:
        by_scanner.setdefault(candidate.scanner_id, []).append(candidate)
    scored: list[tuple[tuple[float, datetime], WatchFeedEntry]] = []
    for candidate in candidates:
        hit_result = _type_hit(candidate, baselines[candidate.scanner_id], by_scanner[candidate.scanner_id])
        hit = hit_result[0] if hit_result is not None else None
        hit_strength = hit_result[1] if hit_result is not None else 0.0
        contributions = _contributions(candidate, hit_strength)
        strongest = _strongest_reason_part(candidate, contributions)
        if strongest == "signal":
            reason: dict[str, Any] = {"kind": "signal_emitted", "signals_count": candidate.signals_count}
            if candidate.signal_problem_types:
                reason["problem_types"] = list(candidate.signal_problem_types)
            if candidate.signal_summaries:
                # The card names the findings from this; the confidence stays behind, because it ranks the
                # row rather than telling a reader anything they can act on.
                reason["signals"] = [
                    {"problem_type": problem_type, "headline": headline}
                    for problem_type, headline, _ in candidate.signal_summaries
                ]
        elif strongest == "hit" and hit is not None:
            reason = hit
        elif strongest == "notability":
            reason = {"kind": "notable", "notability": candidate.notability}
        elif strongest == "friction":
            reason = {"kind": "friction"}
        elif not candidate.viewed:
            reason = {"kind": "unviewed_recent"}
        else:
            reason = {"kind": "recent"}
        # The scan writes a notability_reason on every session (including "nothing stands out"), so only
        # carry it when notability actually won the row — a signal or type hit can coexist with a high
        # score, and gating on `notable` alone would attach the sentence over the copy that row earned.
        if candidate.notability_reason and reason["kind"] == "notable":
            reason["notability_reason"] = candidate.notability_reason
        sort_key = (_watchability(candidate, hit_strength), candidate.created_at)
        scored.append((sort_key, WatchFeedEntry(observation_id=candidate.observation_id, reason=reason)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return _cap_signal_share(_trim_filler([entry for _, entry in scored]))
