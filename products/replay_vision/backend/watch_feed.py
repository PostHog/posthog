"""Ranking for the What to watch feed: which succeeded observations in a window are worth a look.

Deterministic v1, no model calls. Baselines come from the candidate rows themselves (the scanner's
own window), so "outlier" and "rare" mean unusual for that scanner lately, not against all history.
"""

import re
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
    scanner_type: str | None
    verdict: str | None
    score: float | None
    tags: tuple[str, ...]
    summary_tokens: frozenset[str]
    friction: bool


def _parse_candidate(row: dict[str, Any]) -> _Candidate:
    """Read the ranking features off a raw row, tolerating malformed `scanner_result` — a bad row
    ranks by recency only rather than failing the whole feed."""
    result = row.get("scanner_result")
    output = result.get("model_output") if isinstance(result, dict) else None
    if not isinstance(output, dict):
        output = {}
    signals_count = result.get("signals_count") if isinstance(result, dict) else 0
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
        scanner_type=scanner_type,
        verdict=verdict,
        score=float(score) if isinstance(score, int | float) else None,
        tags=tuple(tag for tag in tags if isinstance(tag, str)),
        summary_tokens=frozenset(_TOKEN_RE.findall(summary_text.lower())),
        friction=friction_eligible and bool(_FRICTION_RE.search(" ".join([prose, *tags]))),
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


def _type_hit(candidate: _Candidate, baseline: _ScannerBaseline, siblings: list[_Candidate]) -> dict[str, Any] | None:
    """The type-specific reason this row stands out for its scanner, or None."""
    if candidate.scanner_type == "monitor" and candidate.verdict in ("yes", "no"):
        # With a baseline, the notable answer is the scanner's own minority verdict — prompt
        # polarity doesn't matter ("did they struggle?" vs "was the experience good?"). Without
        # one, fall back to yes, the conventional something-happened phrasing.
        if baseline.verdict_shares:
            share = baseline.verdict_shares.get(candidate.verdict, 0.0)
            if share <= UNUSUAL_VERDICT_MAX_SHARE:
                return {"kind": "unusual_verdict", "verdict": candidate.verdict, "verdict_share": round(share, 3)}
        elif candidate.verdict == "yes":
            return {"kind": "verdict_yes"}
    if candidate.scanner_type == "summarizer":
        similarity = _max_summary_similarity(candidate, siblings)
        if similarity is not None and similarity <= NOVEL_SUMMARY_MAX_SIMILARITY:
            return {"kind": "novel_summary"}
    if (
        candidate.scanner_type == "scorer"
        and candidate.score is not None
        and baseline.score_mean is not None
        and baseline.score_stddev is not None
        # A flat window (every score identical) makes any deviation infinite sigmas; skip it.
        and baseline.score_stddev > 0
        and abs(candidate.score - baseline.score_mean) >= OUTLIER_STDDEVS * baseline.score_stddev
    ):
        return {"kind": "outlier_score", "score": candidate.score, "window_mean": round(baseline.score_mean, 2)}
    if candidate.scanner_type == "classifier" and baseline.rare_tags:
        rare = [(baseline.tag_shares[tag], tag) for tag in set(candidate.tags) if tag in baseline.rare_tags]
        if rare:
            share, tag = min(rare)
            return {"kind": "rare_tag", "tag": tag, "tag_share": round(share, 3)}
    return None


def rank_watch_feed_candidates(rows: list[dict[str, Any]]) -> list[WatchFeedEntry]:
    """Rank candidate rows (`id`, `scanner_id`, `created_at`, `scanner_result`, `feed_viewed`) most
    watchable first: signal emitters, then type-specific hits, then unviewed before viewed, then
    sessions whose prose reads as friction, then newest.

    Signals and type hits encode what the user configured the scanner to find, so a strong hit they
    saw yesterday still outranks unviewed routine rows — seen-state orders rows within those tiers
    rather than above them. Friction is only a keyword heuristic, so it stays below seen-state:
    it may lift unread rows, never resurface ones a reader already dismissed."""
    candidates = [_parse_candidate(row) for row in rows]
    baselines = _baselines(candidates)
    by_scanner: dict[UUID, list[_Candidate]] = {}
    for candidate in candidates:
        by_scanner.setdefault(candidate.scanner_id, []).append(candidate)
    scored: list[tuple[tuple[bool, bool, bool, bool, datetime], WatchFeedEntry]] = []
    for candidate in candidates:
        hit = _type_hit(candidate, baselines[candidate.scanner_id], by_scanner[candidate.scanner_id])
        has_signal = candidate.signals_count > 0
        if has_signal:
            reason: dict[str, Any] = {"kind": "signal_emitted", "signals_count": candidate.signals_count}
        elif hit is not None:
            reason = hit
        elif candidate.friction:
            reason = {"kind": "friction"}
        elif not candidate.viewed:
            reason = {"kind": "unviewed_recent"}
        else:
            reason = {"kind": "recent"}
        sort_key = (has_signal, hit is not None, not candidate.viewed, candidate.friction, candidate.created_at)
        scored.append((sort_key, WatchFeedEntry(observation_id=candidate.observation_id, reason=reason)))
    scored.sort(key=lambda item: item[0], reverse=True)
    return [entry for _, entry in scored]
