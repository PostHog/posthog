//! Ingest-time concern signatures (signatures.py port): per-signal token sets
//! plus an embedded signature text, loaded from data_dir/sigs.jsonl (emitted by
//! export_inputs.py from the Haiku signature cache). Pair features are
//! agreement measures; a missing signature on either side degrades every
//! channel to its neutral value, matching the Python reference exactly.

use serde::Deserialize;
use std::collections::HashSet;

#[derive(Deserialize)]
pub struct SigInfo {
    pub document_id: String,
    pub polarity: String,
    pub surface: Vec<String>,
    pub failmode: Vec<String>,
    pub tags: Vec<String>,
    pub anchor: Vec<String>,
    pub oneliner: Vec<String>,
    pub has_failmode: bool,
    pub has_anchor: bool,
    #[serde(default)]
    pub emb: Vec<f32>, // L2-normalized signature-text embedding (may be empty)
}

fn jac(a: &[String], b: &[String]) -> f64 {
    let sa: HashSet<&str> = a.iter().map(|s| s.as_str()).collect();
    let sb: HashSet<&str> = b.iter().map(|s| s.as_str()).collect();
    let inter = sa.intersection(&sb).count() as f64;
    let union = sa.union(&sb).count() as f64;
    inter / union.max(1.0)
}

pub fn sig_pair_features(sa: Option<&SigInfo>, sb: Option<&SigInfo>) -> [(&'static str, f64); 8] {
    let (ta, tb) = match (sa, sb) {
        (Some(a), Some(b)) => (a, b),
        _ => {
            return [
                ("sig_both_success", 0.0),
                ("sig_polarity_mismatch", 0.0),
                ("sig_surface_jac", 0.5),
                ("sig_failmode_jac", 0.5),
                ("sig_tags_jac", 0.5),
                ("sig_anchor_match", 0.5),
                ("sig_oneliner_jac", 0.5),
                ("sig_cos", 0.5),
            ];
        }
    };
    let both_success = f64::from(ta.polarity == "success" && tb.polarity == "success");
    let mismatch = f64::from(
        (ta.polarity == "problem" && tb.polarity == "success")
            || (ta.polarity == "success" && tb.polarity == "problem"),
    );
    let failmode = if ta.has_failmode && tb.has_failmode {
        jac(&ta.failmode, &tb.failmode)
    } else {
        0.5
    };
    let anchor = if ta.has_anchor && tb.has_anchor {
        f64::from(jac(&ta.anchor, &tb.anchor) > 0.6)
    } else {
        0.5
    };
    let cos = if !ta.emb.is_empty() && !tb.emb.is_empty() {
        crate::feats::dot(&ta.emb, &tb.emb)
    } else {
        0.5
    };
    [
        ("sig_both_success", both_success),
        ("sig_polarity_mismatch", mismatch),
        ("sig_surface_jac", jac(&ta.surface, &tb.surface)),
        ("sig_failmode_jac", failmode),
        ("sig_tags_jac", jac(&ta.tags, &tb.tags)),
        ("sig_anchor_match", anchor),
        ("sig_oneliner_jac", jac(&ta.oneliner, &tb.oneliner)),
        ("sig_cos", cos),
    ]
}

/// Group-pair signature agreement (signatures.py group_signature_features port):
/// each member is (signature-or-None, (product, source_type)). Inverted channels
/// (anchor_shared, typedist_cos) are same-template evidence — kept deliberately.
pub fn group_sig_features(
    side_a: &[(Option<&SigInfo>, (String, String))],
    side_b: &[(Option<&SigInfo>, (String, String))],
) -> [(&'static str, f64); 11] {
    let signed_a: Vec<&SigInfo> = side_a.iter().filter_map(|(s, _)| *s).collect();
    let signed_b: Vec<&SigInfo> = side_b.iter().filter_map(|(s, _)| *s).collect();
    let n_total = (side_a.len() + side_b.len()).max(1) as f64;
    let coverage = (signed_a.len() + signed_b.len()) as f64 / n_total;
    if signed_a.is_empty() || signed_b.is_empty() {
        return [
            ("g_tags_jac", 0.0),
            ("g_surface_jac", 0.0),
            ("g_failmode_jac", 0.0),
            ("g_oneliner_jac", 0.0),
            ("g_anchor_shared", 0.0),
            ("g_polarity_absdiff", 0.0),
            ("g_typedist_cos", 0.0),
            ("g_sig_cos_centroid", 0.5),
            ("g_sig_cos_max", 0.5),
            ("g_sig_cos_mean", 0.5),
            ("g_sig_coverage", coverage),
        ];
    }
    fn pooled<'a>(
        sides: &[&'a SigInfo],
        f: impl Fn(&'a SigInfo) -> &'a [String],
    ) -> HashSet<&'a str> {
        sides
            .iter()
            .flat_map(|s| f(s).iter().map(|t| t.as_str()))
            .collect()
    }
    fn sjac(a: &HashSet<&str>, b: &HashSet<&str>) -> f64 {
        let inter = a.intersection(b).count() as f64;
        (inter / (a.union(b).count() as f64).max(1.0)).min(1.0)
    }
    fn pol_frac(sides: &[&SigInfo]) -> f64 {
        sides.iter().filter(|s| s.polarity == "problem").count() as f64 / sides.len().max(1) as f64
    }
    // type-distribution cosine over ALL members (signed or not)
    let mut da: std::collections::HashMap<&(String, String), f64> =
        std::collections::HashMap::new();
    for (_s, p) in side_a {
        *da.entry(p).or_insert(0.0) += 1.0;
    }
    let mut db: std::collections::HashMap<&(String, String), f64> =
        std::collections::HashMap::new();
    for (_s, p) in side_b {
        *db.entry(p).or_insert(0.0) += 1.0;
    }
    let keys: HashSet<&&(String, String)> = da.keys().chain(db.keys()).collect();
    let (mut dot, mut na, mut nb) = (0.0f64, 0.0f64, 0.0f64);
    for k in keys {
        let va = *da.get(*k).unwrap_or(&0.0);
        let vb = *db.get(*k).unwrap_or(&0.0);
        dot += va * vb;
        na += va * va;
        nb += vb * vb;
    }
    let typedist = if na > 0.0 && nb > 0.0 {
        dot / (na.sqrt() * nb.sqrt())
    } else {
        0.0
    };

    let ea: Vec<&[f32]> = signed_a
        .iter()
        .filter(|s| !s.emb.is_empty())
        .map(|s| s.emb.as_slice())
        .collect();
    let eb: Vec<&[f32]> = signed_b
        .iter()
        .filter(|s| !s.emb.is_empty())
        .map(|s| s.emb.as_slice())
        .collect();
    let (centroid, xmax, xmean) = if !ea.is_empty() && !eb.is_empty() {
        let dim = ea[0].len();
        let mean_of = |vs: &[&[f32]]| -> Vec<f64> {
            let mut m = vec![0.0f64; dim];
            for v in vs {
                for (i, x) in v.iter().enumerate() {
                    m[i] += *x as f64;
                }
            }
            for x in m.iter_mut() {
                *x /= vs.len() as f64;
            }
            m
        };
        let ca = mean_of(&ea);
        let cb = mean_of(&eb);
        let dotp: f64 = ca.iter().zip(&cb).map(|(x, y)| x * y).sum();
        let na: f64 = ca.iter().map(|x| x * x).sum::<f64>().sqrt();
        let nb: f64 = cb.iter().map(|x| x * x).sum::<f64>().sqrt();
        let centroid = if na > 0.0 && nb > 0.0 {
            dotp / (na * nb)
        } else {
            0.5
        };
        let (mut mx, mut sum, mut cnt) = (f64::NEG_INFINITY, 0.0f64, 0usize);
        for va in ea.iter().take(8) {
            for vb in eb.iter().take(8) {
                let d = crate::feats::dot(va, vb);
                mx = mx.max(d);
                sum += d;
                cnt += 1;
            }
        }
        (centroid, mx, sum / cnt.max(1) as f64)
    } else {
        (0.5, 0.5, 0.5)
    };
    [
        (
            "g_tags_jac",
            sjac(
                &pooled(&signed_a, |s| &s.tags),
                &pooled(&signed_b, |s| &s.tags),
            ),
        ),
        (
            "g_surface_jac",
            sjac(
                &pooled(&signed_a, |s| &s.surface),
                &pooled(&signed_b, |s| &s.surface),
            ),
        ),
        (
            "g_failmode_jac",
            sjac(
                &pooled(&signed_a, |s| &s.failmode),
                &pooled(&signed_b, |s| &s.failmode),
            ),
        ),
        (
            "g_oneliner_jac",
            sjac(
                &pooled(&signed_a, |s| &s.oneliner),
                &pooled(&signed_b, |s| &s.oneliner),
            ),
        ),
        ("g_anchor_shared", {
            let aa = pooled(&signed_a, |s| &s.anchor);
            let ab = pooled(&signed_b, |s| &s.anchor);
            f64::from(!aa.is_disjoint(&ab))
        }),
        (
            "g_polarity_absdiff",
            (pol_frac(&signed_a) - pol_frac(&signed_b)).abs(),
        ),
        ("g_typedist_cos", typedist),
        ("g_sig_cos_centroid", centroid),
        ("g_sig_cos_max", xmax),
        ("g_sig_cos_mean", xmean),
        ("g_sig_coverage", coverage),
    ]
}
