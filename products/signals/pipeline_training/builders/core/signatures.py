"""Ingest-time concern signatures: one small-LLM call per SIGNAL (not per pair)
producing a structured concern description, cached forever. Pair features are
agreement measures between two signals' signatures — zero match-time LLM cost.

Schema (dictated by the plateau blind-judge rationales): polarity
(problem/success/neutral), surface, failure_mode, error_anchor,
affected_entity, concern_tags, one_liner. Signatures live in
cache/concern_signatures_haiku.jsonl; signature-text embeddings in
cache/concern_signature_embs.jsonl.
"""

import os
import re
import json
from collections import Counter

import numpy as np

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "raw")
SIG_CACHE = os.path.abspath(os.path.join(CACHE, "concern_signatures_haiku.jsonl"))
SIG_EMB_CACHE = os.path.abspath(os.path.join(CACHE, "concern_signature_embs.jsonl"))
PROMPT_VERSION = "sig-v1"

SIG_FEATURE_NAMES = [
    "sig_both_success",
    "sig_polarity_mismatch",
    "sig_surface_jac",
    "sig_failmode_jac",
    "sig_tags_jac",
    "sig_anchor_match",
    "sig_oneliner_jac",
    "sig_cos",
]

_TOK = re.compile(r"[a-z0-9_$]+")


def _toks(v: object) -> set[str]:
    return set(_TOK.findall(str(v).lower())) if v else set()


def _jac(a: set[str], b: set[str]) -> float:
    return len(a & b) / max(len(a | b), 1)


def load_signatures() -> dict[str, dict]:
    """document_id -> signature dict (current prompt version only)."""
    out: dict[str, dict] = {}
    if os.path.exists(SIG_CACHE):
        for line in open(SIG_CACHE):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("prompt_version") == PROMPT_VERSION and "error" not in (r.get("signature") or {}):
                out[r["document_id"]] = r["signature"]
    return out


def load_signature_embeddings() -> dict[str, np.ndarray]:
    """document_id -> L2-normalized embedding of the signature text."""
    out: dict[str, np.ndarray] = {}
    if os.path.exists(SIG_EMB_CACHE):
        for line in open(SIG_EMB_CACHE):
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            v = np.asarray(r["emb"], dtype=np.float32)
            out[r["document_id"]] = v / max(float(np.linalg.norm(v)), 1e-9)
    return out


def signature_text(sig: dict) -> str:
    return " | ".join(str(sig.get(k) or "") for k in ("surface", "failure_mode", "one_liner"))[:800]


def signature_token_sets(sig: dict) -> dict[str, object]:
    """Precomputed per-signal pieces (this is what the Rust exporter emits)."""
    return {
        "polarity": sig.get("polarity") or "neutral",
        "surface": sorted(_toks(sig.get("surface"))),
        "failmode": sorted(_toks(sig.get("failure_mode"))),
        "tags": sorted({t for tag in (sig.get("concern_tags") or []) for t in _toks(tag)}),
        "anchor": sorted(_toks(sig.get("error_anchor"))),
        "oneliner": sorted(_toks(sig.get("one_liner"))),
        "has_failmode": bool(sig.get("failure_mode")),
        "has_anchor": bool(sig.get("error_anchor")),
    }


def signature_pair_features(
    ta: dict | None,
    tb: dict | None,
    emb_a: "np.ndarray | None" = None,
    emb_b: "np.ndarray | None" = None,
) -> dict[str, float]:
    """Agreement features from two signals' precomputed token sets. Missing
    signatures degrade to neutral values (0.5 for match channels, 0 for flags)."""
    if not ta or not tb:
        return {
            "sig_both_success": 0.0,
            "sig_polarity_mismatch": 0.0,
            "sig_surface_jac": 0.5,
            "sig_failmode_jac": 0.5,
            "sig_tags_jac": 0.5,
            "sig_anchor_match": 0.5,
            "sig_oneliner_jac": 0.5,
            "sig_cos": 0.5,
        }
    pa, pb = ta["polarity"], tb["polarity"]
    anchors_ok = ta["has_anchor"] and tb["has_anchor"]
    out = {
        "sig_both_success": float(pa == "success" and pb == "success"),
        "sig_polarity_mismatch": float({pa, pb} == {"problem", "success"}),
        "sig_surface_jac": _jac(set(ta["surface"]), set(tb["surface"])),
        "sig_failmode_jac": _jac(set(ta["failmode"]), set(tb["failmode"]))
        if (ta["has_failmode"] and tb["has_failmode"])
        else 0.5,
        "sig_tags_jac": _jac(set(ta["tags"]), set(tb["tags"])),
        "sig_anchor_match": float(_jac(set(ta["anchor"]), set(tb["anchor"])) > 0.6) if anchors_ok else 0.5,
        "sig_oneliner_jac": _jac(set(ta["oneliner"]), set(tb["oneliner"])),
    }
    out["sig_cos"] = float(emb_a @ emb_b) if (emb_a is not None and emb_b is not None) else 0.5
    return out


GROUP_SIG_FEATURE_NAMES = [
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

_GROUP_SIG_NEUTRAL = {
    "g_tags_jac": 0.0,
    "g_surface_jac": 0.0,
    "g_failmode_jac": 0.0,
    "g_oneliner_jac": 0.0,
    "g_anchor_shared": 0.0,
    "g_polarity_absdiff": 0.0,
    "g_typedist_cos": 0.0,
    "g_sig_cos_centroid": 0.5,
    "g_sig_cos_max": 0.5,
    "g_sig_cos_mean": 0.5,
    "g_sig_coverage": 0.0,
}

_XSIG_CAP = 8  # cross-member sig_cos matrix cap per side


def group_signature_features(
    side_a: "list[tuple[dict | None, np.ndarray | None, tuple[str, str]]]",
    side_b: "list[tuple[dict | None, np.ndarray | None, tuple[str, str]]]",
) -> dict[str, float]:
    """Group-pair signature agreement for the concern model (merge AND split
    contexts): each side is a list of (token_sets, embedding, (product, type))
    per member — token_sets/embedding None when the member is unsigned.
    Inverted channels (anchor_shared, typedist_cos) are kept deliberately:
    sharing an error anchor or an identical type mix is same-template evidence,
    which at the group level correlates with the different-concern trap."""
    signed_a = [t for t, _e, _p in side_a if t]
    signed_b = [t for t, _e, _p in side_b if t]
    n_total = len(side_a) + len(side_b)
    coverage = (len(signed_a) + len(signed_b)) / max(n_total, 1)
    if not signed_a or not signed_b:
        return dict(_GROUP_SIG_NEUTRAL, g_sig_coverage=coverage)

    def pooled(sides: list[dict], key: str) -> set:
        out: set = set()
        for t in sides:
            out.update(t[key])
        return out

    def pol_frac(sides: list[dict]) -> float:
        return sum(1 for t in sides if t["polarity"] == "problem") / max(len(sides), 1)

    # type-distribution cosine over member counts
    da = Counter(p for _t, _e, p in side_a)
    db = Counter(p for _t, _e, p in side_b)
    keys = sorted(set(da) | set(db))
    va = np.array([float(da.get(k, 0)) for k in keys])
    vb = np.array([float(db.get(k, 0)) for k in keys])
    na, nb = float(np.linalg.norm(va)), float(np.linalg.norm(vb))
    typedist = float(va @ vb / (na * nb)) if na > 0 and nb > 0 else 0.0

    ea = [e for _t, e, _p in side_a if e is not None]
    eb = [e for _t, e, _p in side_b if e is not None]
    out = {
        "g_tags_jac": _jac(pooled(signed_a, "tags"), pooled(signed_b, "tags")),
        "g_surface_jac": _jac(pooled(signed_a, "surface"), pooled(signed_b, "surface")),
        "g_failmode_jac": _jac(pooled(signed_a, "failmode"), pooled(signed_b, "failmode")),
        "g_oneliner_jac": _jac(pooled(signed_a, "oneliner"), pooled(signed_b, "oneliner")),
        "g_anchor_shared": float(bool(pooled(signed_a, "anchor") & pooled(signed_b, "anchor"))),
        "g_polarity_absdiff": abs(pol_frac(signed_a) - pol_frac(signed_b)),
        "g_typedist_cos": typedist,
        "g_sig_coverage": coverage,
    }
    if ea and eb:
        centro_a = np.mean(ea, axis=0)
        centro_b = np.mean(eb, axis=0)
        norm_a, norm_b = float(np.linalg.norm(centro_a)), float(np.linalg.norm(centro_b))
        out["g_sig_cos_centroid"] = float(centro_a @ centro_b / (norm_a * norm_b)) if norm_a > 0 and norm_b > 0 else 0.5
        m = np.array(ea[:_XSIG_CAP]) @ np.array(eb[:_XSIG_CAP]).T
        out["g_sig_cos_max"] = float(m.max())
        out["g_sig_cos_mean"] = float(m.mean())
    else:
        out["g_sig_cos_centroid"] = out["g_sig_cos_max"] = out["g_sig_cos_mean"] = 0.5
    return out
