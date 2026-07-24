//! Exact ports of features.py: pair_features, join_features, split_features
//! (via group_features internals). All embeddings arrive L2-normalized f32;
//! feature arithmetic is f64 like Python floats.

use crate::idents::{id_features, IdSets};
use crate::slots::{slot_features, SLOT_GATE_COS};
use std::collections::HashMap;

pub const NOT_RETRIEVED_RANK: f64 = 99.0;

#[inline]
pub fn dot(a: &[f32], b: &[f32]) -> f64 {
    a.iter()
        .zip(b)
        .map(|(x, y)| (*x as f64) * (*y as f64))
        .sum()
}

#[inline]
pub fn norm(a: &[f32]) -> f64 {
    dot(a, a).sqrt()
}

pub fn normalize(v: &[f32]) -> Vec<f32> {
    let n = norm(v);
    if n > 0.0 {
        v.iter().map(|x| (*x as f64 / n) as f32).collect()
    } else {
        v.to_vec()
    }
}

pub struct RetrievalMeta {
    pub n_projections: f64,
    pub best_rank: f64,
    pub best_distance: f64,
    pub own_type: f64,
}

pub type Feats = HashMap<&'static str, f64>;

#[allow(clippy::too_many_arguments)]
pub fn pair_features(
    e_q: &[f32], // normalized query embedding
    q_type: (&str, &str),
    q_ts: f64,
    content_q: &str,
    source_id_q: &str,
    e_c: &[f32], // normalized candidate embedding
    c_type: (&str, &str),
    c_ts: f64,
    content_c: &str,
    source_id_c: &str,
    means: &HashMap<(String, String), Vec<f32>>,
    rmeta: Option<&RetrievalMeta>,
    burst_q: f64,
    burst_c: f64,
    ids_q: &IdSets,
    ids_c: &IdSets,
    neigh_scale_q: f64,
    neigh_scale_c: f64,
) -> Feats {
    let cos_raw = (1.0 - dot(e_q, e_c)).max(0.0);

    let mu_q = means.get(&(q_type.0.to_string(), q_type.1.to_string()));
    let mu_c = means.get(&(c_type.0.to_string(), c_type.1.to_string()));
    let r_q: Vec<f64> = match mu_q {
        Some(m) => e_q
            .iter()
            .zip(m)
            .map(|(a, b)| *a as f64 - *b as f64)
            .collect(),
        None => e_q.iter().map(|a| *a as f64).collect(),
    };
    let r_c: Vec<f64> = match mu_c {
        Some(m) => e_c
            .iter()
            .zip(m)
            .map(|(a, b)| *a as f64 - *b as f64)
            .collect(),
        None => e_c.iter().map(|a| *a as f64).collect(),
    };
    let nq = r_q.iter().map(|x| x * x).sum::<f64>().sqrt();
    let nc = r_c.iter().map(|x| x * x).sum::<f64>().sqrt();
    let cos_residual = if nq > 1e-6 && nc > 1e-6 {
        1.0 - r_q.iter().zip(&r_c).map(|(a, b)| a * b).sum::<f64>() / (nq * nc)
    } else {
        cos_raw
    };

    let (n_proj, best_rank, best_dist, own) = match rmeta {
        Some(m) => (m.n_projections, m.best_rank, m.best_distance, m.own_type),
        None => (0.0, NOT_RETRIEVED_RANK, cos_raw, 0.0),
    };

    let gap_h = (q_ts - c_ts).abs() / 3600.0;
    let idf = id_features(ids_q, ids_c);
    let contrast_q = cos_raw / neigh_scale_q.max(1e-3);
    let contrast_c = cos_raw / neigh_scale_c.max(1e-3);

    // v1.5 extras: slot alignment only in the near band (twins), sentinels beyond
    let (template_sim, slot_conflict_w) = if cos_raw < SLOT_GATE_COS {
        slot_features(content_q, content_c)
    } else {
        (0.0, 0.0)
    };
    let same_source_id = if !source_id_q.is_empty() && source_id_q == source_id_c {
        1.0
    } else {
        0.0
    };

    let mut f: Feats = HashMap::with_capacity(28);
    f.insert("template_sim", template_sim);
    f.insert("slot_conflict_w", slot_conflict_w);
    f.insert("same_source_id", same_source_id);
    f.insert("contrast_q", contrast_q);
    f.insert("contrast_c", contrast_c);
    f.insert("contrast_min", contrast_q.min(contrast_c));
    f.insert("cos_raw", cos_raw);
    f.insert("cos_residual", cos_residual);
    f.insert("residual_norm_q", nq);
    f.insert("residual_norm_c", nc);
    f.insert("best_projected_distance", best_dist);
    f.insert("n_projections_surfaced", n_proj);
    f.insert("best_rank", best_rank);
    f.insert("surfaced_by_own_type", own);
    f.insert("log_gap_hours", gap_h.ln_1p());
    f.insert("same_hour", if gap_h <= 1.0 { 1.0 } else { 0.0 });
    f.insert("burst_q", burst_q);
    f.insert("burst_c", burst_c);
    f.insert("id_overlap", idf.id_overlap);
    f.insert("id_shared_w", idf.id_shared_w);
    f.insert("id_conflict", idf.id_conflict);
    f.insert("same_product", if q_type.0 == c_type.0 { 1.0 } else { 0.0 });
    f.insert("same_type", if q_type == c_type { 1.0 } else { 0.0 });
    f.insert(
        "both_et",
        if q_type.0 == "error_tracking" && c_type.0 == "error_tracking" {
            1.0
        } else {
            0.0
        },
    );
    f
}

/// mean of pairwise upper-triangle cosine distances (clipped at 0), 0.0 for n<2
fn within_mean(rows: &[&[f32]]) -> f64 {
    if rows.len() < 2 {
        return 0.0;
    }
    let mut total = 0.0;
    let mut n = 0usize;
    for i in 0..rows.len() {
        for j in (i + 1)..rows.len() {
            total += (1.0 - dot(rows[i], rows[j])).max(0.0);
            n += 1;
        }
    }
    total / n as f64
}

fn centroid(rows: &[&[f32]]) -> Vec<f32> {
    let dims = rows[0].len();
    let mut c = vec![0f64; dims];
    for r in rows {
        for (acc, v) in c.iter_mut().zip(*r) {
            *acc += *v as f64;
        }
    }
    let n = rows.len() as f64;
    let mean: Vec<f32> = c.iter().map(|v| (v / n) as f32).collect();
    let nrm = norm(&mean);
    if nrm > 0.0 {
        mean.iter().map(|v| (*v as f64 / nrm) as f32).collect()
    } else {
        mean
    }
}

#[allow(clippy::too_many_arguments)]
pub fn join_features(
    sampled_p: &[f64],
    e_signal: &[f32], // normalized
    member_emb: &[&[f32]],
    ids_signal: &IdSets,
    ids_members: &IdSets,
    report_size: usize,
    n_retrieved: usize,
    r_best_p: f64,
    r_mean_top3: f64,
    gap_last_h: f64,
    same_product_any: f64,
    both_et_report: f64,
) -> Feats {
    let cen = centroid(member_emb);
    let d_members_mean = member_emb
        .iter()
        .map(|m| (1.0 - dot(m, e_signal)).max(0.0))
        .sum::<f64>()
        / member_emb.len().max(1) as f64;
    let within = within_mean(member_emb);
    let gid = id_features(ids_signal, ids_members);

    let n = sampled_p.len() as f64;
    let mut f: Feats = HashMap::with_capacity(20);
    let sj_best = if sampled_p.is_empty() {
        0.0
    } else {
        sampled_p.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
    };
    f.insert("sj_best_p", sj_best);
    f.insert(
        "sj_mean_p",
        if n > 0.0 {
            sampled_p.iter().sum::<f64>() / n
        } else {
            0.0
        },
    );
    f.insert(
        "sj_frac_05",
        if n > 0.0 {
            sampled_p.iter().filter(|p| **p >= 0.5).count() as f64 / n
        } else {
            0.0
        },
    );
    f.insert(
        "sj_frac_03",
        if n > 0.0 {
            sampled_p.iter().filter(|p| **p >= 0.3).count() as f64 / n
        } else {
            0.0
        },
    );
    f.insert(
        "retrieved_frac",
        n_retrieved as f64 / report_size.max(1) as f64,
    );
    f.insert("log_size", (report_size as f64).ln_1p());
    f.insert("r_best_p", r_best_p);
    f.insert("r_mean_top3", r_mean_top3);
    f.insert("r_n_cands", n_retrieved as f64);
    f.insert("centroid_dist", (1.0 - dot(&cen, e_signal)).max(0.0));
    f.insert("report_within_mean", within);
    f.insert("fit_delta", d_members_mean - within);
    f.insert("jid_overlap", gid.id_overlap);
    f.insert("jid_conflict", gid.id_conflict);
    f.insert("log_gap_last_h", gap_last_h.max(0.0).ln_1p());
    f.insert("same_product_any", same_product_any);
    f.insert("both_et_report", both_et_report);
    f
}

/// split_features (the concern model's featurizer): a = larger half by member count.
#[allow(clippy::too_many_arguments)]
pub fn split_features(
    cut_p: &[f64],
    emb_a: &[&[f32]],
    emb_b: &[&[f32]],
    ts_a: &[f64],
    ts_b: &[f64],
    ids_a: &IdSets,
    ids_b: &IdSets,
    prods_a: &std::collections::HashSet<String>,
    prods_b: &std::collections::HashSet<String>,
    n_components: f64,
) -> Feats {
    let (na, nb) = (emb_a.len(), emb_b.len());
    let cen_a = centroid(emb_a);
    let cen_b = centroid(emb_b);
    let centroid_dist = (1.0 - dot(&cen_a, &cen_b)).max(0.0);

    let mut cross_min = f64::INFINITY;
    let mut cross_sum = 0.0;
    for a in emb_a {
        for b in emb_b {
            let d = (1.0 - dot(a, b)).max(0.0);
            cross_min = cross_min.min(d);
            cross_sum += d;
        }
    }
    let cross_mean = cross_sum / (na * nb) as f64;

    let w_a = if na >= 2 {
        Some(within_mean(emb_a))
    } else {
        None
    };
    let w_b = if nb >= 2 {
        Some(within_mean(emb_b))
    } else {
        None
    };
    let withins: Vec<f64> = [w_a, w_b].into_iter().flatten().collect();
    let within = if withins.is_empty() {
        0.0
    } else {
        withins.iter().sum::<f64>() / withins.len() as f64
    };
    let ward_delta = cross_mean - within;

    let (s_lo, s_hi) = (na.min(nb), na.max(nb));

    // temporal overlap + interleave (group_features semantics)
    let fmin = |v: &[f64]| v.iter().cloned().fold(f64::INFINITY, f64::min);
    let fmax = |v: &[f64]| v.iter().cloned().fold(f64::NEG_INFINITY, f64::max);
    let (a0, a1) = (fmin(ts_a), fmax(ts_a));
    let (b0, b1) = (fmin(ts_b), fmax(ts_b));
    let union_span = a1.max(b1) - a0.min(b0);
    let overlap = (a1.min(b1) - a0.max(b0)).max(0.0);
    let time_overlap = if union_span > 0.0 {
        overlap / union_span
    } else {
        1.0
    };
    // stable merged arrival order
    let mut order: Vec<(f64, u8)> = ts_a
        .iter()
        .map(|t| (*t, 0u8))
        .chain(ts_b.iter().map(|t| (*t, 1u8)))
        .collect();
    order.sort_by(|x, y| x.0.partial_cmp(&y.0).unwrap());
    let transitions = order.windows(2).filter(|w| w[0].1 != w[1].1).count() as f64;
    let max_transitions = (2 * s_lo - usize::from(na == nb)) as f64;
    let interleave = if max_transitions > 0.0 {
        transitions / max_transitions
    } else {
        0.0
    };

    let gid = id_features(ids_a, ids_b);

    let mut f: Feats = HashMap::with_capacity(20);
    let n_cut = cut_p.len() as f64;
    f.insert(
        "cut_max_p",
        if cut_p.is_empty() {
            0.0
        } else {
            cut_p.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
        },
    );
    f.insert(
        "cut_mean_p",
        if n_cut > 0.0 {
            cut_p.iter().sum::<f64>() / n_cut
        } else {
            0.0
        },
    );
    f.insert("cut_centroid_dist", centroid_dist);
    f.insert("cut_cross_min", cross_min);
    f.insert("cut_cross_mean", cross_mean);
    f.insert(
        "half_within_a",
        if na >= 2 { within_mean(emb_a) } else { 0.0 },
    );
    f.insert(
        "half_within_b",
        if nb >= 2 { within_mean(emb_b) } else { 0.0 },
    );
    f.insert("cut_ward_delta", ward_delta);
    f.insert("log_size_a", (na as f64).ln_1p());
    f.insert("log_size_b", (nb as f64).ln_1p());
    f.insert("size_ratio", s_lo as f64 / s_hi.max(1) as f64);
    f.insert("n_components", n_components);
    f.insert("cut_id_overlap", gid.id_overlap);
    f.insert("cut_id_conflict", gid.id_conflict);
    f.insert("cut_time_overlap", time_overlap);
    f.insert("cut_interleave", interleave);
    f.insert(
        "same_product_halves",
        if prods_a == prods_b { 1.0 } else { 0.0 },
    );
    f
}
