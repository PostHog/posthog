"""Pair features for the grouping classifier (designs/pair_feature_classifier.md).

v1 feature set (user-trimmed): geometry + retrieval by-products + temporal +
identifiers-lite (structural rarity, no IDF table). No type-structure features
(they encode the anti-cross-type base rate we're trying to escape) and no
lexical features (that judgment is the LLM's job in non-pure variants).

The same `pair_features` function is used to build the training frame (stage-0
emulated against the full dataset) and at match time inside the pipeline, so
train/serve skew is limited to the store contents themselves.
"""

import re
import math
from datetime import datetime

import numpy as np

# --- identifiers-lite: structural categories, weighted by construction-rarity ---

ID_CATEGORIES: list[tuple[str, str, float]] = [
    # (category, pattern, weight) — weight reflects how identifying a shared value is
    ("uuid", r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", 3.0),
    ("hash", r"\b[0-9a-f]{12,40}\b", 3.0),
    ("longnum", r"\b\d{5,}\b", 2.0),
    ("path", r"/[a-zA-Z0-9_.\-/]{6,}", 2.0),
    ("dotted", r"[a-zA-Z_][a-zA-Z0-9_]{2,}\.[a-zA-Z_][a-zA-Z0-9_.]{3,}", 1.5),
    ("kebab", r"[a-zA-Z_][a-zA-Z0-9_]*-[a-zA-Z0-9_\-]{4,}", 1.0),
    ("error_class", r"[A-Z][a-zA-Z]*Error[a-zA-Z]*", 1.0),
]
_COMPILED = [(cat, re.compile(pat), w) for cat, pat, w in ID_CATEGORIES]


def extract_identifiers(text: str) -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    snippet = str(text)[:4000]
    for cat, rx, _w in _COMPILED:
        found = set(rx.findall(snippet))
        if found:
            out[cat] = found
    return out


# Conflict is only evidence for NAMED identifiers (flag keys, paths, modules, error
# classes). UUIDs/hashes/long numbers differ between almost any two distinct events,
# so conflict on those categories is noise — it measurably backfired on far-band
# positives (median id_conflict=1.0 among the classifier's feature-gap misses).
CONFLICT_CATEGORIES = {"kebab", "path", "dotted", "error_class"}


def id_features(ids_a: dict[str, set[str]], ids_b: dict[str, set[str]]) -> dict[str, float]:
    """Category-weighted overlap (all categories) + conflict (named categories only)."""
    weights = {cat: w for cat, _p, w in ID_CATEGORIES}
    shared_w = 0.0
    union_w = 0.0
    conflict = 0.0
    for cat in set(ids_a) | set(ids_b):
        a, b = ids_a.get(cat, set()), ids_b.get(cat, set())
        w = weights[cat]
        shared_w += w * len(a & b)
        union_w += w * len(a | b)
        if cat in CONFLICT_CATEGORIES and a and b and not (a & b):
            conflict = 1.0
    return {
        "id_overlap": shared_w / union_w if union_w else 0.0,
        "id_shared_w": shared_w,
        "id_conflict": conflict,
    }


# --- template/slot lexical features (pair v1.5) ---------------------------------
# Twin-band pairs are embedding-identical; the distinguishing information lives in
# the TEXT: align the two contents token-wise, decompose into shared template vs
# differing slots, and describe the slots. IMPORTANT SEMANTICS (Oliver, 2026-07-08):
# slot difference means "the difference lives here — judge it", NOT "different
# concern" (payment-failure-per-org is ONE issue; 404 vs 408 is two). These are
# context features the model weighs against judged labels, not a split rule.
# The matcher is a plain greedy Ratcliff-Obershelp (longest common block, recurse
# both sides) implemented identically in Rust — do not swap in difflib.

_SLOT_TOKEN = re.compile(r"[A-Za-z0-9_\-\./]+")
SLOT_GATE_COS = 0.12  # alignment only runs in the near band, where twins live
_SLOT_TOKEN_CAP = 400


def _slot_tokens(text: str) -> list[str]:
    return _SLOT_TOKEN.findall(str(text)[:3000])[:_SLOT_TOKEN_CAP]


def _match_blocks(a: list[str], b: list[str], alo: int, ahi: int, blo: int, bhi: int, out: list) -> None:
    """Longest common contiguous block in a[alo:ahi] vs b[blo:bhi], recurse both sides."""
    best_i, best_j, best_k = alo, blo, 0
    b2j: dict[str, list[int]] = {}
    for j in range(blo, bhi):
        b2j.setdefault(b[j], []).append(j)
    j2len: dict[int, int] = {}
    for i in range(alo, ahi):
        new_j2len: dict[int, int] = {}
        for j in b2j.get(a[i], ()):
            k = j2len.get(j - 1, 0) + 1
            new_j2len[j] = k
            if k > best_k:
                best_i, best_j, best_k = i - k + 1, j - k + 1, k
        j2len = new_j2len
    if best_k == 0:
        return
    _match_blocks(a, b, alo, best_i, blo, best_j, out)
    out.append((best_i, best_j, best_k))
    _match_blocks(a, b, best_i + best_k, ahi, best_j + best_k, bhi, out)


def _slot_conflictish(token: str) -> bool:
    """Identifier-ish slot token: carries an ASCII digit or a path separator (portable rule)."""
    return any(c.isdigit() for c in token) or "/" in token


def slot_features(text_a: str, text_b: str) -> tuple[float, float]:
    """(template_sim, slot_conflict_w): token-level alignment ratio, and the count
    of identifier-ish tokens appearing in exactly one side's unmatched slots."""
    ta, tb = _slot_tokens(text_a), _slot_tokens(text_b)
    if not ta or not tb:
        return 0.0, 0.0
    blocks: list[tuple[int, int, int]] = []
    _match_blocks(ta, tb, 0, len(ta), 0, len(tb), blocks)
    matched = sum(k for _i, _j, k in blocks)
    template_sim = 2.0 * matched / (len(ta) + len(tb))
    in_a = [False] * len(ta)
    in_b = [False] * len(tb)
    for i, j, k in blocks:
        for d in range(k):
            in_a[i + d] = True
            in_b[j + d] = True
    slots_a = {t for t, m in zip(ta, in_a) if not m}
    slots_b = {t for t, m in zip(tb, in_b) if not m}
    conflict_w = float(sum(1 for t in slots_a ^ slots_b if _slot_conflictish(t)))
    return template_sim, conflict_w


PAIR_V15_EXTRA_NAMES = ["template_sim", "slot_conflict_w", "same_source_id"]

FEATURE_NAMES = [
    # geometry
    "cos_raw",
    "cos_residual",
    "residual_norm_q",
    "residual_norm_c",
    "best_projected_distance",
    # retrieval by-products
    "n_projections_surfaced",
    "best_rank",
    "surfaced_by_own_type",
    # temporal
    "log_gap_hours",
    "same_hour",
    "burst_q",
    "burst_c",
    # local contrast: pair distance relative to each side's neighborhood scale
    # (AUC 0.727 alone on the v1.1 model's far-band misses)
    "contrast_q",
    "contrast_c",
    "contrast_min",
    # identifiers-lite
    "id_overlap",
    "id_shared_w",
    "id_conflict",
    # source structure (v1.3 experiment): originally vetoed for fear the model
    # learns the anti-cross-type base rate; corpus-et showed the cost of omission
    # is per-source mis-calibration (ET mid-band scored like mixed-universe mid-band)
    "same_product",
    "same_type",
    "both_et",
]

FEATURE_NAMES_V15 = FEATURE_NAMES + PAIR_V15_EXTRA_NAMES

# pair v1.6: + ingest-time concern-signature agreement (one Haiku call per
# SIGNAL at ingest, cached; zero match-time LLM cost). See signatures.py.
PAIR_V16_EXTRA_NAMES = [
    "sig_both_success",
    "sig_polarity_mismatch",
    "sig_surface_jac",
    "sig_failmode_jac",
    "sig_tags_jac",
    "sig_anchor_match",
    "sig_oneliner_jac",
    "sig_cos",
]

FEATURE_NAMES_V16 = FEATURE_NAMES_V15 + PAIR_V16_EXTRA_NAMES

# pair v1.7: + dumb text statistics (no models, no gating — lengths, char-class
# densities, naive negative-word density, char-3-gram / first-line overlap)
PAIR_V17_EXTRA_NAMES = [
    "gram3_jac",
    "firstline_jac",
    "len_ratio",
    "log_len_absdiff",
    "ttr_ratio",
    "neg_density_min",
    "neg_density_ratio",
    "punct_frac_ratio",
    "upper_frac_ratio",
    "has_stack_min",
]

FEATURE_NAMES_V17 = FEATURE_NAMES_V16 + PAIR_V17_EXTRA_NAMES

NOT_RETRIEVED_RANK = 99.0  # rank sentinel when a candidate never surfaced in a projection

_TEXT_WORD = re.compile(r"[A-Za-z]{2,}")
_TEXT_NEG = re.compile(
    r"\b(error|fail|failed|failing|broken|stuck|crash|frustrat|unhappy|complain|"
    r"unable|cannot|wrong|missing|invalid|denied|slow|bug|blocked)\b",
    re.I,
)
_TEXT_STACK = re.compile(r" in [\w/.@-]+ line \d+|Traceback|at [\w$.]+\(")
_TEXT_WS = re.compile(r"\s+")


def text_stats(text: str) -> dict:
    """Per-signal dumb text statistics (Rust-portable: cache per stored row)."""
    t = str(text)[:4000]
    n = max(len(t), 1)
    words = _TEXT_WORD.findall(t)
    nw = max(len(words), 1)
    collapsed = _TEXT_WS.sub(" ", str(text)[:2000].lower())
    first = str(text).strip().split("\n", 1)[0][:300].lower()
    return {
        "len": float(len(t)),
        "ttr": len({w.lower() for w in words}) / nw,
        "neg_density": len(_TEXT_NEG.findall(t)) / nw,
        "punct_frac": sum(not c.isalnum() and not c.isspace() for c in t) / n,
        "upper_frac": sum(c.isupper() for c in t) / n,
        "has_stack": float(bool(_TEXT_STACK.search(t))),
        "gram3": {collapsed[i : i + 3] for i in range(len(collapsed) - 2)},
        "firstline": set(_TEXT_WORD.findall(first)),
    }


def _sjac(a: set, b: set) -> float:
    return len(a & b) / max(len(a | b), 1)


def _ratio(a: float, b: float) -> float:
    return min(a, b) / max(max(a, b), 1e-9)


def text_pair_features(sa: dict, sb: dict) -> dict[str, float]:
    return {
        "gram3_jac": _sjac(sa["gram3"], sb["gram3"]),
        "firstline_jac": _sjac(sa["firstline"], sb["firstline"]),
        "len_ratio": _ratio(sa["len"], sb["len"]),
        "log_len_absdiff": abs(math.log1p(sa["len"]) - math.log1p(sb["len"])),
        "ttr_ratio": _ratio(sa["ttr"], sb["ttr"]),
        "neg_density_min": min(sa["neg_density"], sb["neg_density"]),
        "neg_density_ratio": _ratio(sa["neg_density"], sb["neg_density"]),
        "punct_frac_ratio": _ratio(sa["punct_frac"], sb["punct_frac"]),
        "upper_frac_ratio": _ratio(sa["upper_frac"], sb["upper_frac"]),
        "has_stack_min": min(sa["has_stack"], sb["has_stack"]),
    }


def pair_features(
    query_embedding: np.ndarray,
    query_content: str,
    query_type: tuple[str, str],
    query_ts: datetime,
    cand_embedding: np.ndarray,
    cand_content: str,
    cand_type: tuple[str, str],
    cand_ts: datetime,
    means: dict[tuple[str, str], np.ndarray],
    retrieval: dict[str, dict[str, float]] | None,
    cand_signal_id: str,
    burst_q: float,
    burst_c: float,
    query_ids: dict[str, set[str]] | None = None,
    cand_ids: dict[str, set[str]] | None = None,
    neigh_scale_q: float = 1.0,
    neigh_scale_c: float = 1.0,
    query_source_id: str = "",
    cand_source_id: str = "",
) -> dict[str, float]:
    """One feature row. `retrieval` maps candidate signal_id -> {n_projections,
    best_rank, best_distance, own_type} as accumulated from stage-0 results."""
    e_q = query_embedding / (np.linalg.norm(query_embedding) or 1.0)
    e_c = cand_embedding / (np.linalg.norm(cand_embedding) or 1.0)
    cos_raw = float(max(0.0, 1.0 - float(e_q @ e_c)))

    mu_q = means.get(query_type)
    mu_c = means.get(cand_type)
    r_q = e_q - mu_q if mu_q is not None else e_q
    r_c = e_c - mu_c if mu_c is not None else e_c
    nq, nc = float(np.linalg.norm(r_q)), float(np.linalg.norm(r_c))
    cos_residual = float(1.0 - float(r_q @ r_c) / (nq * nc)) if nq > 1e-6 and nc > 1e-6 else cos_raw

    rmeta = (retrieval or {}).get(cand_signal_id)
    if rmeta:
        n_proj = float(rmeta["n_projections"])
        best_rank = float(rmeta["best_rank"])
        best_dist = float(rmeta["best_distance"])
        own = float(rmeta["own_type"])
    else:
        n_proj, best_rank, best_dist, own = 0.0, NOT_RETRIEVED_RANK, cos_raw, 0.0

    gap_h = abs((query_ts - cand_ts).total_seconds()) / 3600.0

    ids_q = query_ids if query_ids is not None else extract_identifiers(query_content)
    ids_c = cand_ids if cand_ids is not None else extract_identifiers(cand_content)
    idf = id_features(ids_q, ids_c)

    contrast_q = cos_raw / max(neigh_scale_q, 1e-3)
    contrast_c = cos_raw / max(neigh_scale_c, 1e-3)

    # v1.5 extras: slot alignment only in the near band (twins), sentinels beyond
    if cos_raw < SLOT_GATE_COS:
        template_sim, slot_conflict_w = slot_features(query_content, cand_content)
    else:
        template_sim, slot_conflict_w = 0.0, 0.0
    same_source_id = 1.0 if query_source_id and query_source_id == cand_source_id else 0.0

    return {
        **text_pair_features(text_stats(query_content), text_stats(cand_content)),
        "template_sim": template_sim,
        "slot_conflict_w": slot_conflict_w,
        "same_source_id": same_source_id,
        "contrast_q": contrast_q,
        "contrast_c": contrast_c,
        "contrast_min": min(contrast_q, contrast_c),
        "cos_raw": cos_raw,
        "cos_residual": cos_residual,
        "residual_norm_q": nq,
        "residual_norm_c": nc,
        "best_projected_distance": best_dist,
        "n_projections_surfaced": n_proj,
        "best_rank": best_rank,
        "surfaced_by_own_type": own,
        "log_gap_hours": math.log1p(gap_h),
        "same_hour": 1.0 if gap_h <= 1.0 else 0.0,
        "burst_q": burst_q,
        "burst_c": burst_c,
        "id_overlap": idf["id_overlap"],
        "id_shared_w": idf["id_shared_w"],
        "id_conflict": idf["id_conflict"],
        "same_product": 1.0 if query_type[0] == cand_type[0] else 0.0,
        "same_type": 1.0 if query_type == cand_type else 0.0,
        "both_et": 1.0 if query_type[0] == cand_type[0] == "error_tracking" else 0.0,
    }


class BurstIndex:
    """Same-type arrival counts within ±window hours, computed from the FULL
    signal stream (prod would have the full stream too; blank-slate corpus
    stores would understate burstiness, so this ships as an environment table
    alongside the model)."""

    def __init__(self, types: "list[tuple[str, str]]", epochs: "list[np.ndarray]"):
        self._index = {t: np.sort(e) for t, e in zip(types, epochs)}

    @classmethod
    def from_frame(cls, df) -> "BurstIndex":
        import pandas as pd  # noqa: PLC0415 — keeps the module numpy-only for pipeline use

        frame = pd.DataFrame(
            {
                "p": df["source_product"].fillna("").astype(str).to_numpy(),
                "t": df["source_type"].fillna("").astype(str).to_numpy(),
                "ts": df["timestamp"].astype("int64").to_numpy() / 1e9,
            }
        )
        types, epochs = [], []
        for (p, t), grp in frame.groupby(["p", "t"]):
            types.append((p, t))
            epochs.append(grp["ts"].to_numpy())
        return cls(types, epochs)

    def count(self, signal_type: "tuple[str, str]", ts: datetime, window_hours: float = 1.0) -> float:
        arr = self._index.get(signal_type)
        if arr is None:
            return 0.0
        t = ts.timestamp()
        lo = np.searchsorted(arr, t - window_hours * 3600)
        hi = np.searchsorted(arr, t + window_hours * 3600)
        return float(np.log1p(max(0, hi - lo - 1)))  # exclude self; log-scale


# ---------------------------------------------------------------------------
# Signal -> report JOIN features (v1.5 group-join model). The pairwise argmax
# still picks WHICH report; this model decides WHETHER to join it — from the
# FULL report (sampled), not just the members retrieval happened to surface.
# Two bias fixes over retrieved-subset views: honest support (retrieval surfaces
# the nearest members, inflating subset averages) and a denominator (3 members
# at p=0.6 means 75% support of a 4-member report, 0.06% of a clone stack).
# ---------------------------------------------------------------------------

JOIN_FEATURE_NAMES = [
    # full-report sampled support (pair-model p against a fair member sample)
    "sj_best_p",
    "sj_mean_p",
    "sj_frac_05",
    "sj_frac_03",
    # denominator-aware support
    "retrieved_frac",
    "log_size",
    # retrieved-subset view (kept: carries retrieval-rank information)
    "r_best_p",
    "r_mean_top3",
    "r_n_cands",
    # geometry / cohesion fit
    "centroid_dist",
    "report_within_mean",
    "fit_delta",
    # identifiers + temporal
    "jid_overlap",
    "jid_conflict",
    "log_gap_last_h",
    # source structure
    "same_product_any",
    "both_et_report",
]


def join_features(
    sampled_p: "np.ndarray",
    signal_emb: "np.ndarray",
    member_emb: "np.ndarray",
    signal_ids_: "dict[str, set[str]]",
    member_ids_: "dict[str, set[str]]",
    report_size: int,
    n_retrieved: int,
    r_best_p: float,
    r_mean_top3: float,
    gap_last_h: float,
    same_product_any: float,
    both_et_report: float,
) -> dict[str, float]:
    """Assemble the join-feature row. `sampled_p` = pair-model p of the signal vs
    each sampled FULL-report member; `member_emb` = those members' embeddings."""
    e = signal_emb / (np.linalg.norm(signal_emb) or 1.0)
    cen = member_emb.mean(axis=0)
    cen = cen / (np.linalg.norm(cen) or 1.0)
    with np.errstate(all="ignore"):
        d_members = np.clip(1.0 - member_emb @ e, 0.0, None)
    if len(member_emb) >= 2:
        with np.errstate(all="ignore"):
            dm = 1.0 - member_emb @ member_emb.T
        iu = np.triu_indices(len(member_emb), k=1)
        within = float(np.clip(dm[iu], 0.0, None).mean())
    else:
        within = 0.0
    gid = id_features(signal_ids_, member_ids_)
    return {
        "sj_best_p": float(sampled_p.max()) if len(sampled_p) else 0.0,
        "sj_mean_p": float(sampled_p.mean()) if len(sampled_p) else 0.0,
        "sj_frac_05": float((sampled_p >= 0.5).mean()) if len(sampled_p) else 0.0,
        "sj_frac_03": float((sampled_p >= 0.3).mean()) if len(sampled_p) else 0.0,
        "retrieved_frac": n_retrieved / max(report_size, 1),
        "log_size": math.log1p(report_size),
        "r_best_p": r_best_p,
        "r_mean_top3": r_mean_top3,
        "r_n_cands": float(n_retrieved),
        "centroid_dist": float(max(0.0, 1.0 - float(cen @ e))),
        "report_within_mean": within,
        "fit_delta": float(d_members.mean()) - within,
        "jid_overlap": gid["id_overlap"],
        "jid_conflict": gid["id_conflict"],
        "log_gap_last_h": math.log1p(max(0.0, gap_last_h)),
        "same_product_any": same_product_any,
        "both_et_report": both_et_report,
    }


# ---------------------------------------------------------------------------
# Group-level features for the merge gate (report-pair "same concern" model).
# The bridge trigger proposes report pairs; these features let a trained gate
# dispose — replacing the score-only bridge that percolated (NOTES 2026-07-07).
# ---------------------------------------------------------------------------

GROUP_FEATURE_NAMES = [
    # linkage geometry (embeddings are L2-normalized; distances are cosine)
    "centroid_dist",
    "cross_min",
    "cross_mean",
    "cross_max",
    "within_mean",
    "ward_delta",
    "ward_ratio",
    "frac_cross_close_005",
    "frac_cross_close_015",
    # local contrast: tightest cross link relative to ambient neighborhood scale
    "cross_min_contrast",
    # pair-model / trigger evidence (directional: own = report the signal joined)
    "trigger_p_own",
    "trigger_p_other",
    "n_triggers",
    "max_trigger_p",
    "trigger_joined",
    # sizes
    "log_size_a",
    "log_size_b",
    "log_size_min",
    "size_ratio",
    # temporal
    "time_overlap",
    "log_range_gap_hours",
    "interleave",
    # identifiers (aggregated per report)
    "gid_overlap",
    "gid_shared_w",
    "gid_conflict",
    # supplied by the pipeline, not group_features(): the triggering signal's
    # per-side pair-model aggregates, and cross-pair pair-model aggregates over
    # sampled member pairs (retrieval features imputed as not-retrieved, which is
    # consistent between gate training and serving)
    "own_n_cands",
    "own_mean_p",
    "other_n_cands",
    "other_mean_p",
    "xp_max",
    "xp_mean",
    "xp_frac_03",
    "xp_frac_05",
]

GROUP_MEMBER_CAP = 40  # most-recent members per side used for geometry
GROUP_ID_MEMBER_CAP = 10  # members per side whose contents feed identifier aggregation


def merge_identifier_sets(id_dicts: "list[dict[str, set[str]]]") -> dict[str, set[str]]:
    out: dict[str, set[str]] = {}
    for d in id_dicts:
        for cat, vals in d.items():
            out.setdefault(cat, set()).update(vals)
    return out


def group_features(
    emb_a: np.ndarray,
    emb_b: np.ndarray,
    ts_a: np.ndarray,
    ts_b: np.ndarray,
    ids_a: "dict[str, set[str]]",
    ids_b: "dict[str, set[str]]",
    neigh_scale: float,
    trigger_p_own: float,
    trigger_p_other: float,
    n_triggers: float,
    max_trigger_p: float,
    trigger_joined: float = 1.0,
    size_a: int | None = None,
    size_b: int | None = None,
) -> dict[str, float]:
    """One gate feature row for a report pair. `emb_*` are (n, d) normalized member
    matrices (possibly capped samples); `size_*` are the TRUE report sizes when the
    matrices are capped. Geometry is symmetric except the directional trigger p's,
    so a/b order only matters for those (a = report the triggering signal joined)."""
    na, nb = len(emb_a), len(emb_b)
    size_a = size_a if size_a is not None else na
    size_b = size_b if size_b is not None else nb

    cen_a = emb_a.mean(axis=0)
    cen_b = emb_b.mean(axis=0)
    cen_a = cen_a / (np.linalg.norm(cen_a) or 1.0)
    cen_b = cen_b / (np.linalg.norm(cen_b) or 1.0)
    centroid_dist = float(max(0.0, 1.0 - float(cen_a @ cen_b)))

    with np.errstate(all="ignore"):
        cross = 1.0 - emb_a @ emb_b.T  # (na, nb) cosine distances
    np.clip(cross, 0.0, None, out=cross)
    cross_min = float(cross.min())
    cross_mean = float(cross.mean())
    cross_max = float(cross.max())
    frac_005 = float((cross < 0.05).mean())
    frac_015 = float((cross < 0.15).mean())

    def within_mean_of(m: np.ndarray) -> float | None:
        if len(m) < 2:
            return None
        with np.errstate(all="ignore"):
            d = 1.0 - m @ m.T
        iu = np.triu_indices(len(m), k=1)
        return float(np.clip(d[iu], 0.0, None).mean())

    w_a, w_b = within_mean_of(emb_a), within_mean_of(emb_b)
    withins = [w for w in (w_a, w_b) if w is not None]
    within_mean = float(np.mean(withins)) if withins else 0.0
    ward_delta = cross_mean - within_mean
    # scale-invariant cohesion contrast: a loose-but-real group joining its fork looks
    # like ratio ~1-3 whether the group is a clone stack or a far-band concern
    ward_ratio = cross_mean / max(within_mean, 0.01)

    s_lo, s_hi = min(size_a, size_b), max(size_a, size_b)

    # temporal: overlap of the two [min,max] ts ranges over their union span;
    # interleave = fraction of adjacent same-report transitions broken, in the
    # merged arrival order (0 = fully separated in time, 1 = perfectly alternating)
    a0, a1 = float(ts_a.min()), float(ts_a.max())
    b0, b1 = float(ts_b.min()), float(ts_b.max())
    union_span = max(a1, b1) - min(a0, b0)
    overlap = max(0.0, min(a1, b1) - max(a0, b0))
    time_overlap = overlap / union_span if union_span > 0 else 1.0
    range_gap_h = max(0.0, max(a0, b0) - min(a1, b1)) / 3600.0
    order = np.argsort(np.concatenate([ts_a, ts_b]), kind="stable")
    labels = np.concatenate([np.zeros(na), np.ones(nb)])[order]
    transitions = float((labels[1:] != labels[:-1]).sum())
    max_transitions = 2 * min(na, nb) - (1 if na == nb else 0)
    interleave = transitions / max_transitions if max_transitions > 0 else 0.0

    gid = id_features(ids_a, ids_b)

    return {
        "centroid_dist": centroid_dist,
        "cross_min": cross_min,
        "cross_mean": cross_mean,
        "cross_max": cross_max,
        "within_mean": within_mean,
        "ward_delta": ward_delta,
        "ward_ratio": ward_ratio,
        "frac_cross_close_005": frac_005,
        "frac_cross_close_015": frac_015,
        "cross_min_contrast": cross_min / max(neigh_scale, 1e-3),
        "trigger_p_own": trigger_p_own,
        "trigger_p_other": trigger_p_other,
        "n_triggers": n_triggers,
        "max_trigger_p": max_trigger_p,
        "trigger_joined": trigger_joined,
        "log_size_a": math.log1p(size_a),
        "log_size_b": math.log1p(size_b),
        "log_size_min": math.log1p(s_lo),
        "size_ratio": s_lo / max(s_hi, 1),
        "time_overlap": time_overlap,
        "log_range_gap_hours": math.log1p(range_gap_h),
        "interleave": interleave,
        "gid_overlap": gid["id_overlap"],
        "gid_shared_w": gid["id_shared_w"],
        "gid_conflict": gid["id_conflict"],
    }


# ---------------------------------------------------------------------------
# Split features (v2.0 fission gate): a report's members were partitioned into
# two components by the pair-p graph; is the cut real (two concerns) or does it
# sever one concern? The mirror question of the merge gate, on the proposal
# distribution that loose joins produce.
# ---------------------------------------------------------------------------

SPLIT_FEATURE_NAMES = [
    # the cut, in pair-model terms
    "cut_max_p",
    "cut_mean_p",
    # the cut, geometrically
    "cut_centroid_dist",
    "cut_cross_min",
    "cut_cross_mean",
    "half_within_a",
    "half_within_b",
    "cut_ward_delta",
    # shape
    "log_size_a",
    "log_size_b",
    "size_ratio",
    "n_components",
    # identifiers + temporal + source
    "cut_id_overlap",
    "cut_id_conflict",
    "cut_time_overlap",
    "cut_interleave",
    "same_product_halves",
]


def split_features(
    cut_p: "np.ndarray",
    emb_a: "np.ndarray",
    emb_b: "np.ndarray",
    ts_a: "np.ndarray",
    ts_b: "np.ndarray",
    ids_a: "dict[str, set[str]]",
    ids_b: "dict[str, set[str]]",
    prods_a: "set[str]",
    prods_b: "set[str]",
    n_components: int,
) -> dict[str, float]:
    """`cut_p` = pair-model p over the cross pairs the proposed cut severs;
    emb/ts/ids per proposed half (a = larger half)."""
    g = group_features(
        emb_a=emb_a,
        emb_b=emb_b,
        ts_a=ts_a,
        ts_b=ts_b,
        ids_a=ids_a,
        ids_b=ids_b,
        neigh_scale=1.0,
        trigger_p_own=0.0,
        trigger_p_other=0.0,
        n_triggers=0.0,
        max_trigger_p=0.0,
        trigger_joined=0.0,
        size_a=len(emb_a),
        size_b=len(emb_b),
    )

    def _within(m: "np.ndarray") -> float:
        if len(m) < 2:
            return 0.0
        with np.errstate(all="ignore"):
            d = 1.0 - m @ m.T
        iu = np.triu_indices(len(m), k=1)
        return float(np.clip(d[iu], 0.0, None).mean())

    return {
        "cut_max_p": float(cut_p.max()) if len(cut_p) else 0.0,
        "cut_mean_p": float(cut_p.mean()) if len(cut_p) else 0.0,
        "cut_centroid_dist": g["centroid_dist"],
        "cut_cross_min": g["cross_min"],
        "cut_cross_mean": g["cross_mean"],
        "half_within_a": _within(emb_a),
        "half_within_b": _within(emb_b),
        "cut_ward_delta": g["ward_delta"],
        "log_size_a": g["log_size_a"],
        "log_size_b": g["log_size_b"],
        "size_ratio": g["size_ratio"],
        "n_components": float(n_components),
        "cut_id_overlap": g["gid_overlap"],
        "cut_id_conflict": g["gid_conflict"],
        "cut_time_overlap": g["time_overlap"],
        "cut_interleave": g["interleave"],
        "same_product_halves": 1.0 if prods_a == prods_b else 0.0,
    }


# Concern model v2 extras: cut context the 17 core features can't see — role flag,
# true (unsampled) size, cut_p distribution shape, MST skeleton context, and the
# severed side's JOIN PROVENANCE (at what pairwise p did its members join, and is
# the just-joined trigger signal among them — the "undo the last join" case).
# Merge-shaped rows use documented sentinels: mst_median_p=0, sev_join_p_*=-1 when
# unknown, sev_has_trigger=0 — consistent between training and serve.
CONCERN_V2_EXTRA_NAMES = [
    "is_split_eval",
    "true_log_size",
    "sample_frac",
    "cut_p_p90",
    "cut_p_frac_03",
    "mst_median_p",
    "sev_join_p_max",
    "sev_join_p_mean",
    "sev_frac_founders",
    "sev_has_trigger",
]

CONCERN_V2_FEATURE_NAMES = SPLIT_FEATURE_NAMES + CONCERN_V2_EXTRA_NAMES

# concern v2.5: + group-pair signature agreement (see signatures.py) — the
# semantic channel the merge role lacked (v2.4 proved the limitation was
# features, not labels: correct operating-point labels at 4x supply and merges
# still couldn't fire)
CONCERN_V25_FEATURE_NAMES = CONCERN_V2_FEATURE_NAMES + [
    "g_tags_jac",
    "g_surface_jac",
    "g_failmode_jac",
    "g_oneliner_jac",
    "g_anchor_shared",
    "g_polarity_absdiff",
    "g_typedist_cos",
    "g_sig_cos_centroid",
    "g_sig_cos_max",
    "g_sig_cos_mean",
    "g_sig_coverage",
]


# One-liners for every feature across all models: what it measures and how it is
# derived. Rendered as hover docs in the dashboard's model explorer; keep in sync
# when adding features.
FEATURE_DOCS: dict[str, str] = {
    # --- pairwise (signal x signal) ---
    "cos_raw": "Cosine distance between the two signals' raw content embeddings (text-embedding-3-small, L2-normalized). The base geometry.",
    "cos_residual": "Cosine distance after subtracting each side's (product, type) mean embedding — geometry with the source-type 'accent' removed, so cross-type pairs about the same concern get closer.",
    "residual_norm_q": "Norm of the query signal's residual (embedding minus its type mean). Small = a generic exemplar of its type; large = unusual content for its type.",
    "residual_norm_c": "Norm of the candidate signal's residual — same construction as residual_norm_q.",
    "best_projected_distance": "Best distance at which retrieval surfaced this candidate across all ~40 type projections (raw cos_raw if never surfaced).",
    "n_projections_surfaced": "How many of the residual-retrieval projections surfaced this candidate in their top-K. Broad agreement across projections = robust neighbor.",
    "best_rank": "Best rank (1 = nearest) the candidate achieved in any projection's top-K; 99 = never retrieved (imputation sentinel).",
    "surfaced_by_own_type": "1 if the candidate surfaced in the query's own-type/raw projection — homogeneous evidence, not just a cross-type echo.",
    "log_gap_hours": "log1p of the arrival-time gap in hours between the two signals.",
    "same_hour": "1 if the two signals arrived within one hour of each other.",
    "burst_q": "log1p count of same-type arrivals within ±1h of the query signal (from the full-universe burst index) — is its type bursting right now?",
    "burst_c": "Same as burst_q, for the candidate signal.",
    "contrast_q": "cos_raw divided by the query's neighborhood scale (its 10th-nearest-neighbor distance at insert time). <1 = closer than the query's typical neighbors — the strongest far-band signal.",
    "contrast_c": "cos_raw divided by the candidate's stored neighborhood scale — same construction from the candidate's side.",
    "contrast_min": "min(contrast_q, contrast_c): the pair is 'close' if EITHER side considers the other closer than its usual neighborhood.",
    "id_overlap": "Rarity-weighted Jaccard overlap of extracted identifiers (uuids, hashes, long numbers, paths, dotted/kebab names, error classes) between the two contents.",
    "id_shared_w": "Absolute rarity-weighted count of shared identifiers (overlap numerator, unnormalized).",
    "id_conflict": "1 if a NAMED identifier category (path/dotted/kebab/error-class) is present on both sides with zero intersection. UUIDs/numbers excluded — they differ between almost any two events.",
    "same_product": "1 if both signals come from the same source product.",
    "same_type": "1 if both signals share (product, type) exactly.",
    "both_et": "1 if both signals are error-tracking — lets the model calibrate ET's harsher distance semantics without a global cross-type prior.",
    # --- group-join (signal x report) ---
    "sj_best_p": "Best pairwise-model p between the signal and a fair sample of the FULL report's members (not just retrieved ones).",
    "sj_mean_p": "Mean pairwise p over the sampled full-report members — honest support, not inflated by retrieval surfacing only the nearest members.",
    "sj_frac_05": "Fraction of sampled members with pairwise p >= 0.5.",
    "sj_frac_03": "Fraction of sampled members with pairwise p >= 0.3.",
    "retrieved_frac": "Retrieved members / true report size — the denominator feature: 3 attracted members mean 75% of a 4-member report but ~0% of a clone stack.",
    "log_size": "log1p of the true report size.",
    "r_best_p": "Best pairwise p among the RETRIEVED members (carries retrieval-rank information the sampled view lacks).",
    "r_mean_top3": "Mean of the top-3 retrieved-member pairwise p's.",
    "r_n_cands": "Number of retrieved candidates belonging to this report.",
    "report_within_mean": "Mean pairwise cosine distance among the report's sampled members — its internal cohesion.",
    "fit_delta": "Mean signal-to-member distance minus report_within_mean: would this signal sit inside the report's cloud (≈0/negative) or stretch it (positive)?",
    "jid_overlap": "id_overlap between the signal's identifiers and the report's aggregated member identifiers.",
    "jid_conflict": "id_conflict between the signal and the report's aggregated identifier profile.",
    "log_gap_last_h": "log1p hours since the report last received a member.",
    "same_product_any": "1 if any report member shares the signal's source product.",
    "both_et_report": "1 if the signal is error-tracking AND the report is purely error-tracking.",
    # --- group pair (merge gate / concern core) ---
    "centroid_dist": "Cosine distance between the two groups' (normalized) centroid embeddings.",
    "cross_min": "Minimum member-to-member cosine distance across the two groups — the tightest bridge.",
    "cross_mean": "Mean cross-group member distance.",
    "cross_max": "Maximum cross-group member distance — the widest span a merge would have to absorb.",
    "within_mean": "Mean of the two groups' internal pairwise distances — the cohesion baseline the cross distances are judged against.",
    "ward_delta": "cross_mean minus within_mean: how much looser the merged group would be than its parts.",
    "ward_ratio": "cross_mean / within_mean — scale-invariant cohesion contrast (a loose-but-real group merging its fork looks ~1-3x whether it is a clone stack or a far-band concern).",
    "frac_cross_close_005": "Fraction of cross-group member pairs closer than 0.05 (near-duplicate band).",
    "frac_cross_close_015": "Fraction of cross-group member pairs closer than 0.15.",
    "cross_min_contrast": "cross_min divided by the triggering signal's neighborhood scale — is the tightest bridge close by local standards?",
    "trigger_p_own": "Pairwise p that joined the triggering signal to its report (the merge proposal's own side).",
    "trigger_p_other": "Best pairwise p the triggering signal held in the OTHER report — the strength of the bridge that proposed this merge.",
    "n_triggers": "How many signals have proposed this report pair so far (evidence accumulates across arrivals).",
    "max_trigger_p": "Strongest trigger p seen for this report pair across all proposals.",
    "trigger_joined": "1 if the triggering signal actually joined a report (vs a non-join bridge echo: attracted to 2+ reports but clearing tau for none).",
    "log_size_a": "log1p size of side A (the larger/joined side).",
    "log_size_b": "log1p size of side B (the smaller/other side).",
    "log_size_min": "log1p of the smaller side's size.",
    "size_ratio": "Smaller size / larger size.",
    "time_overlap": "Overlap of the two sides' [first, last] arrival windows over their union span (0 = disjoint eras, 1 = same era).",
    "log_range_gap_hours": "log1p hours of dead time between the two sides' arrival windows (0 if they overlap).",
    "interleave": "Fraction of adjacent transitions in the merged arrival order that switch sides (0 = fully separated in time, 1 = perfectly alternating).",
    "gid_overlap": "id_overlap between the two sides' aggregated member identifiers.",
    "gid_shared_w": "Absolute rarity-weighted shared identifier count between the sides.",
    "gid_conflict": "id_conflict between the sides' aggregated identifier profiles (named categories only).",
    "own_n_cands": "How many retrieved candidates the triggering signal had in its OWN report.",
    "own_mean_p": "Mean pairwise p of the trigger's own-report candidates.",
    "other_n_cands": "How many retrieved candidates the trigger had in the other report.",
    "other_mean_p": "Mean pairwise p of the trigger's other-report candidates.",
    "xp_max": "Max pairwise-model p over sampled cross pairs of the two reports (retrieval imputed as not-retrieved, consistent train/serve).",
    "xp_mean": "Mean sampled cross-pair p.",
    "xp_frac_03": "Fraction of sampled cross pairs with p >= 0.3.",
    "xp_frac_05": "Fraction of sampled cross pairs with p >= 0.5.",
    # --- split / concern featurizer ---
    "cut_max_p": "Max pairwise p across the proposed boundary (for MST cuts this IS the severed tree edge, by the cut property). High = the boundary severs a confident link.",
    "cut_mean_p": "Mean pairwise p across the boundary.",
    "cut_centroid_dist": "Cosine distance between the two halves' centroids.",
    "cut_cross_min": "Minimum member distance across the boundary.",
    "cut_cross_mean": "Mean member distance across the boundary.",
    "half_within_a": "Internal mean pairwise distance of the larger half (0 for singletons).",
    "half_within_b": "Internal mean pairwise distance of the smaller half.",
    "cut_ward_delta": "cross_mean minus mean within-half cohesion — how much the boundary 'costs' geometrically.",
    "n_components": "Number of connected components the pair-p graph fell into at the link threshold (v2.0 semantics; 2 for MST cuts and merges).",
    "cut_id_overlap": "Identifier overlap between the two halves (gid_overlap on the halves).",
    "cut_id_conflict": "Named-identifier conflict between the halves.",
    "cut_time_overlap": "Temporal overlap of the halves' arrival windows (see time_overlap).",
    "cut_interleave": "Arrival-order interleaving of the halves (see interleave).",
    "same_product_halves": "1 if both halves draw from exactly the same set of source products.",
    # --- concern v2 extras ---
    "is_split_eval": "Role flag: 1 = post-join split evaluation, 0 = merge-shaped evaluation (bridge trigger / labeled group pair). Lets one model serve both without sentinel confusion.",
    "true_log_size": "log1p of the TRUE report size (splits) or combined sampled member count (merges) — the sampled halves understate mega-reports.",
    "sample_frac": "Sampled members / true size: how much of the report the evaluation actually saw (1.0 for merge rows).",
    "cut_p_p90": "90th percentile of the boundary's pairwise p's — distribution shape beyond max/mean.",
    "cut_p_frac_03": "Fraction of boundary pairs with p >= 0.3.",
    "mst_median_p": "Median edge p of the group's maximum spanning tree — skeleton strength context: a weak cut edge in a STRONG skeleton is a seam; in a weak skeleton it is a chain link (0 sentinel for merge rows).",
    "sev_join_p_max": "Max pairwise p (retrieval-imputed, memoized path) between severed-side members and their original join parents — did the severed side join on confident links? (-1 = no recorded parents).",
    "sev_join_p_mean": "Mean severed-member-to-parent pairwise p (-1 sentinel when unknown).",
    "sev_frac_founders": "Fraction of the severed side with no join parent (report founders / seeded members).",
    "sev_has_trigger": "1 if the severed side contains the signal whose join triggered this evaluation — the 'undo the last join' shape.",
    # --- pair v1.5 template/slot extras ---
    "template_sim": "Token-level alignment ratio (Ratcliff-Obershelp common blocks) between the two contents, computed only in the near band (cos_raw < 0.12) where template twins live; 0 beyond. ~1.0 = same template with slot substitutions.",
    "slot_conflict_w": "Count of identifier-ish tokens (containing a digit or '/') that appear in exactly one side's unmatched slot regions. High on same-template-different-entity pairs; ~0 on true re-renders. CONTEXT, not a split rule: whether a slot difference means a different concern is the judged labels' call (404 vs 408: yes; per-org ids: usually no).",
    "same_source_id": "1 if both signals carry the same non-empty source_id (e.g. the same error-tracking issue) — near-ground-truth same-concern evidence that was previously loaded but unused.",
    # --- pair v1.6 concern-signature extras (ingest-time Haiku call, cached) ---
    "sig_both_success": "1 if BOTH signals' ingest-time signatures have polarity=success (normal/successful product usage). Two success signals about different users are different concerns by the judge's actionability frame — the llm_analytics engagement-eval trap cluster.",
    "sig_polarity_mismatch": "1 if one signature says problem and the other says success — a working-vs-broken pair is rarely one concern.",
    "sig_surface_jac": "Token Jaccard of the signatures' 'surface' fields (product surface/feature area, e.g. 'session replay player'). 0.5 when either signature is missing.",
    "sig_failmode_jac": "Token Jaccard of the signatures' 'failure_mode' fields (e.g. 'stuck buffering' vs 'blank render'); 0.5 unless both signals are problems with a stated failure mode.",
    "sig_tags_jac": "Token Jaccard of the signatures' concern_tags keyword sets — the distilled concern identity, robust to narration.",
    "sig_anchor_match": "1 if both signatures carry an error_anchor (ExceptionClass @ distinctive file:line) and their token Jaccard exceeds 0.6; 0 if both carry anchors that disagree; 0.5 when either side has no anchor.",
    "sig_oneliner_jac": "Token Jaccard of the signatures' one_liner issue titles.",
    "sig_cos": "Cosine similarity of the embedded signature texts (surface | failure_mode | one_liner, text-embedding-3-small). The distilled-concern geometry, with narration and template stripped by the signing model.",
    # --- pair v1.7 dumb text statistics (no models, no gating) ---
    "gram3_jac": "Character-3-gram Jaccard of the two contents (first 2000 chars, whitespace collapsed, lowercased). Ungated cheap lexical similarity; twin-band AUC .721 standalone.",
    "firstline_jac": "Word-token Jaccard of the two contents' first lines (titles/headlines carry the concern for many sources).",
    "len_ratio": "min/max ratio of content lengths (chars, capped 4000). Same-concern re-renders tend to be similar length.",
    "log_len_absdiff": "Absolute difference of log1p content lengths.",
    "ttr_ratio": "min/max ratio of type-token ratios (vocabulary diversity). Templated vs narrated text differ sharply here.",
    "neg_density_min": "Smaller of the two sides' negative-word densities (error/fail/broken/stuck... per word). Both-sides-negative distinguishes two problem reports from problem-vs-normal narration.",
    "neg_density_ratio": "min/max ratio of negative-word densities — do the two texts carry similar amounts of failure language?",
    "punct_frac_ratio": "min/max ratio of punctuation character fractions (stack traces and code are punctuation-dense; prose is not).",
    "upper_frac_ratio": "min/max ratio of uppercase character fractions (exception names and constants vs prose).",
    "has_stack_min": "1 only if BOTH contents contain a stack-trace marker (frame lines, Traceback). Two traces are compared differently than trace-vs-narrative.",
    # --- concern v2.5 group-pair signature extras (signatures.py) ---
    "g_tags_jac": "Jaccard of the two groups' POOLED signature concern-tag token sets.",
    "g_surface_jac": "Jaccard of the two groups' pooled signature surface tokens (product surface/feature area). Trigger-population AUC .773 at base rate .031.",
    "g_failmode_jac": "Jaccard of the two groups' pooled failure-mode tokens.",
    "g_oneliner_jac": "Jaccard of the two groups' pooled one-liner issue-title tokens.",
    "g_anchor_shared": "1 if the groups share any error-anchor token. INVERTED channel: shared anchors at the group level mark same-template-different-concern traps (trigger AUC .43 raw).",
    "g_polarity_absdiff": "Absolute difference of the groups' problem-polarity member fractions (a problem-group vs a success-group is rarely one concern).",
    "g_typedist_cos": "Cosine of the groups' source (product,type) count distributions. INVERTED channel: identical type mix is template-twin evidence at the group level (trigger AUC .38 raw).",
    "g_sig_cos_centroid": "Cosine between the groups' mean signature embeddings — the distilled-concern geometry at group level. Strongest merge channel found: trigger-population AUC .872 at base rate .031.",
    "g_sig_cos_max": "Max cross-member signature-embedding cosine between the groups (capped 8x8): the strongest semantic bridge pair.",
    "g_sig_cos_mean": "Mean cross-member signature-embedding cosine between the groups (capped 8x8).",
    "g_sig_coverage": "Fraction of the two groups' sampled members that carry an ingest signature — lets the model discount the sig channels on low-coverage (older/unsigned) rows.",
}


def retrieval_metadata(
    queries: list[str],
    query_results: list[list],
    own_type_labels: set[str],
) -> dict[str, dict[str, float]]:
    """Stage-0 by-products per candidate signal_id, from the pipeline's
    (queries, per-query results) shape. `own_type_labels` = query labels that
    represent the raw/own-type projection for this signal."""
    meta: dict[str, dict[str, float]] = {}
    for q_label, candidates in zip(queries, query_results):
        is_own = q_label in own_type_labels
        for rank, c in enumerate(candidates, start=1):
            m = meta.setdefault(
                c.signal_id,
                {"n_projections": 0.0, "best_rank": float(rank), "best_distance": float(c.distance), "own_type": 0.0},
            )
            m["n_projections"] += 1.0
            m["best_rank"] = min(m["best_rank"], float(rank))
            m["best_distance"] = min(m["best_distance"], float(c.distance))
            if is_own:
                m["own_type"] = 1.0
    return meta
