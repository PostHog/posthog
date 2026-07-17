//! Exact repaired member-selection artifacts for live report-pair operations.

use anyhow::{bail, Result};
use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::sync::Arc;

pub const MAX_REPORT_MEMBERS: usize = 300;
pub const MAX_COMBINED_MEMBERS: usize = 450;
pub const TOP_K: usize = 24;
const LEGACY_NODE_FEATURES: usize = 51;
const EDGE_FEATURES: usize = 15;
const EMBEDDING_DIMS: usize = 1536;

pub const RUST_FEATURE_NAMES: [&str; 42] = [
    "best_projected_distance",
    "best_rank",
    "both_et",
    "burst_c",
    "burst_q",
    "contrast_c",
    "contrast_min",
    "contrast_q",
    "cos_raw",
    "cos_residual",
    "firstline_jac",
    "gram3_jac",
    "has_stack_min",
    "id_conflict",
    "id_overlap",
    "id_shared_w",
    "len_ratio",
    "log_gap_hours",
    "log_len_absdiff",
    "n_projections_surfaced",
    "neg_density_min",
    "neg_density_ratio",
    "punct_frac_ratio",
    "residual_norm_c",
    "residual_norm_q",
    "same_hour",
    "same_product",
    "same_source_id",
    "same_type",
    "sig_anchor_match",
    "sig_both_success",
    "sig_cos",
    "sig_failmode_jac",
    "sig_oneliner_jac",
    "sig_polarity_mismatch",
    "sig_surface_jac",
    "sig_tags_jac",
    "slot_conflict_w",
    "surfaced_by_own_type",
    "template_sim",
    "ttr_ratio",
    "upper_frac_ratio",
];

const SCORE_NAMES: [&str; 3] = ["context-logistic", "direct-hgb-d3", "rich-context-logistic"];

const BIPARTITE_SCORE_NAMES: [&str; 9] = [
    "direct-logistic",
    "direct-hgb-d2",
    "direct-hgb-d3",
    "context-logistic",
    "context-hgb-d2",
    "context-hgb-d3",
    "rich-direct-hgb-d2",
    "rich-direct-hgb-d3",
    "rich-context-logistic",
];

#[derive(Clone, Copy, Debug, Deserialize, Serialize, PartialEq, Eq)]
#[serde(rename_all = "snake_case")]
pub enum Architecture {
    Contextual,
    Bipartite,
}

#[derive(Clone)]
pub struct PairEvidence {
    pub left_index: usize,
    pub right_index: usize,
    pub embedding_cosine: f64,
    pub left_rank: Option<usize>,
    pub right_rank: Option<usize>,
    pub mutual_top_k: bool,
    pub pair_raw: f64,
    pub pair_cal: f64,
    pub rust_features: Arc<Vec<f64>>,
    compatibility: HashMap<String, f64>,
    report_compatibility: HashMap<String, f64>,
}

impl PairEvidence {
    pub fn new(
        left_index: usize,
        right_index: usize,
        embedding_cosine: f64,
        left_rank: Option<usize>,
        right_rank: Option<usize>,
        pair_raw: f64,
        pair_cal: f64,
        rust_features: HashMap<String, f64>,
    ) -> Self {
        let values = RUST_FEATURE_NAMES
            .iter()
            .map(|name| {
                *rust_features
                    .get(*name)
                    .unwrap_or_else(|| panic!("missing member-repair Rust feature {name}"))
            })
            .collect();
        Self::new_shared(
            left_index,
            right_index,
            embedding_cosine,
            left_rank,
            right_rank,
            pair_raw,
            pair_cal,
            Arc::new(values),
        )
    }

    #[allow(clippy::too_many_arguments)]
    pub fn new_shared(
        left_index: usize,
        right_index: usize,
        embedding_cosine: f64,
        left_rank: Option<usize>,
        right_rank: Option<usize>,
        pair_raw: f64,
        pair_cal: f64,
        rust_features: Arc<Vec<f64>>,
    ) -> Self {
        assert_eq!(rust_features.len(), RUST_FEATURE_NAMES.len());
        Self {
            left_index,
            right_index,
            embedding_cosine,
            left_rank,
            right_rank,
            mutual_top_k: left_rank.is_some() && right_rank.is_some(),
            pair_raw,
            pair_cal,
            rust_features,
            compatibility: HashMap::new(),
            report_compatibility: HashMap::new(),
        }
    }
}

pub struct Proposal {
    pub left_probabilities: Vec<f64>,
    pub right_probabilities: Vec<f64>,
    pub action_probability: Option<f64>,
    pub safety_probability: Option<f64>,
    pub report_gate: HashMap<String, f64>,
    pub edges: Vec<PairEvidence>,
}

#[derive(Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum PortableClassifier {
    Linear {
        feature_names: Vec<String>,
        weights: Vec<f64>,
        bias: f64,
    },
    Gbdt {
        feature_names: Vec<String>,
        baseline: f64,
        trees: Vec<Vec<PortableTreeNode>>,
    },
}

#[derive(Deserialize)]
struct PortableTreeNode {
    value: f64,
    feature_idx: i32,
    num_threshold: f64,
    missing_go_to_left: bool,
    left: u32,
    right: u32,
    is_leaf: bool,
}

impl PortableClassifier {
    fn predict(&self, features: &HashMap<String, f64>) -> Result<f64> {
        let sigmoid = |value: f64| 1.0 / (1.0 + (-value).exp());
        match self {
            Self::Linear {
                feature_names,
                weights,
                bias,
            } => {
                if feature_names.len() != weights.len() {
                    bail!("portable linear classifier width mismatch");
                }
                let mut logit = *bias;
                for (name, weight) in feature_names.iter().zip(weights) {
                    let value = features
                        .get(name)
                        .ok_or_else(|| anyhow::anyhow!("missing portable feature {name}"))?;
                    logit += weight * (*value as f32 as f64);
                }
                Ok(sigmoid(logit))
            }
            Self::Gbdt {
                feature_names,
                baseline,
                trees,
            } => {
                let values: Vec<f64> = feature_names
                    .iter()
                    .map(|name| {
                        features
                            .get(name)
                            .map(|value| *value as f32 as f64)
                            .ok_or_else(|| anyhow::anyhow!("missing portable feature {name}"))
                    })
                    .collect::<Result<_>>()?;
                let mut logit = *baseline;
                for tree in trees {
                    let mut node = &tree[0];
                    while !node.is_leaf {
                        let value = values[node.feature_idx as usize];
                        node = if value.is_nan() {
                            if node.missing_go_to_left {
                                &tree[node.left as usize]
                            } else {
                                &tree[node.right as usize]
                            }
                        } else if value <= node.num_threshold {
                            &tree[node.left as usize]
                        } else {
                            &tree[node.right as usize]
                        };
                    }
                    logit += node.value;
                }
                Ok(sigmoid(logit))
            }
        }
    }
}

#[derive(Deserialize)]
struct Artifact {
    path: String,
    bytes: u64,
    sha256: String,
}

#[derive(Deserialize)]
struct NeuralContract {
    buckets: Vec<NeuralBucket>,
}

#[derive(Deserialize)]
struct NeuralBucket {
    width: usize,
    artifact: Artifact,
}

#[derive(Deserialize)]
struct Caps {
    top_k_each_direction: usize,
    max_report_members: usize,
    max_combined_members: usize,
    #[serde(default)]
    embedding_dims: Option<usize>,
}

#[derive(Deserialize)]
struct Manifest {
    schema_version: u32,
    model_family: String,
    feature_contract: String,
    caps: Caps,
    node_feature_names: Vec<String>,
    edge_feature_names: Vec<String>,
    compatibility_primary: HashMap<String, PortableClassifier>,
    compatibility_consensus: HashMap<String, PortableClassifier>,
    report_gate: HashMap<String, PortableClassifier>,
    operation_risk_contextual: HashMap<String, PortableClassifier>,
    operation_risk_bipartite: HashMap<String, PortableClassifier>,
    #[serde(default)]
    contextual: Option<NeuralContract>,
    bipartite: NeuralContract,
}

fn quantile(values: &[f64], q: f64) -> f64 {
    if values.is_empty() {
        return 0.0;
    }
    let mut sorted = values.to_vec();
    sorted.sort_by(f64::total_cmp);
    let position = q * (sorted.len() - 1) as f64;
    let low = position.floor() as usize;
    let high = position.ceil() as usize;
    sorted[low] + (sorted[high] - sorted[low]) * (position - low as f64)
}

fn mean(values: &[f64]) -> f64 {
    values.iter().sum::<f64>() / values.len().max(1) as f64
}

fn maximum(values: &[f64]) -> f64 {
    values.iter().copied().max_by(f64::total_cmp).unwrap_or(0.0)
}

fn second_largest(values: &[f64]) -> f64 {
    if values.len() <= 1 {
        return values.first().copied().unwrap_or(0.0);
    }
    let mut ordered = values.to_vec();
    ordered.sort_by(|left, right| right.total_cmp(left));
    ordered[1]
}

fn share_at_least(values: &[f64], threshold: f64) -> f64 {
    values.iter().filter(|value| **value >= threshold).count() as f64 / values.len().max(1) as f64
}

fn rank_shares(values: &[f64], denominator: usize) -> Vec<f64> {
    let mut ordered: Vec<(usize, f64)> = values.iter().copied().enumerate().collect();
    ordered.sort_by(|left, right| right.1.total_cmp(&left.1).then(left.0.cmp(&right.0)));
    let mut ranks = vec![0.0; values.len()];
    let mut start = 0usize;
    while start < ordered.len() {
        let mut end = start + 1;
        while end < ordered.len() && ordered[end].1 == ordered[start].1 {
            end += 1;
        }
        let average_rank = ((start + 1 + end) as f64) / 2.0;
        for (index, _) in &ordered[start..end] {
            ranks[*index] = average_rank / denominator.max(1) as f64;
        }
        start = end;
    }
    ranks
}

fn compatibility_features(
    edge: &PairEvidence,
    left_raw: &[Vec<f64>],
    left_cal: &[Vec<f64>],
    right_raw: &[Vec<f64>],
    right_cal: &[Vec<f64>],
    report_left_raw: &[f64],
    report_right_raw: &[f64],
    left_size: usize,
    right_size: usize,
) -> HashMap<String, f64> {
    let mut features = HashMap::new();
    features.insert("embedding_cosine".to_string(), edge.embedding_cosine);
    features.insert(
        "left_rank_filled".to_string(),
        edge.left_rank.unwrap_or(5) as f64,
    );
    features.insert(
        "right_rank_filled".to_string(),
        edge.right_rank.unwrap_or(5) as f64,
    );
    features.insert(
        "mutual_top_k".to_string(),
        if edge.mutual_top_k { 1.0 } else { 0.0 },
    );
    features.insert("pair_raw".to_string(), edge.pair_raw);
    features.insert("pair_cal".to_string(), edge.pair_cal);
    let sides = [
        (
            "left",
            &left_raw[edge.left_index],
            &left_cal[edge.left_index],
        ),
        (
            "right",
            &right_raw[edge.right_index],
            &right_cal[edge.right_index],
        ),
    ];
    for (side, raw, cal) in sides {
        for (scale, values, edge_value) in
            [("raw", raw, edge.pair_raw), ("cal", cal, edge.pair_cal)]
        {
            let best = maximum(values);
            features.insert(format!("{side}_{scale}_max"), best);
            features.insert(format!("{side}_{scale}_mean"), mean(values));
            features.insert(
                format!("{side}_{scale}_margin"),
                best - second_largest(values),
            );
            features.insert(
                format!("{side}_{scale}_relative"),
                edge_value / best.max(1.0e-6),
            );
        }
    }
    features.insert("left_size_log".to_string(), (left_size as f64).ln_1p());
    features.insert("right_size_log".to_string(), (right_size as f64).ln_1p());
    features.insert(
        "combined_size_log".to_string(),
        ((left_size + right_size) as f64).ln_1p(),
    );
    for (side, values) in [("left", report_left_raw), ("right", report_right_raw)] {
        features.insert(format!("report_{side}_raw_q10"), quantile(values, 0.10));
        features.insert(format!("report_{side}_raw_median"), quantile(values, 0.50));
        features.insert(format!("report_{side}_raw_mean"), mean(values));
    }
    for (name, value) in RUST_FEATURE_NAMES.iter().zip(edge.rust_features.iter()) {
        features.insert(format!("rust_{name}"), *value);
    }
    features
}

fn report_features(
    edges: &[PairEvidence],
    left_size: usize,
    right_size: usize,
) -> HashMap<String, f64> {
    let mut features = HashMap::new();
    features.insert("left_size".to_string(), left_size as f64);
    features.insert("right_size".to_string(), right_size as f64);
    features.insert(
        "combined_size_log".to_string(),
        ((left_size + right_size) as f64).ln_1p(),
    );
    features.insert("left_size_log".to_string(), (left_size as f64).ln_1p());
    features.insert("right_size_log".to_string(), (right_size as f64).ln_1p());
    features.insert(
        "size_ratio".to_string(),
        left_size.min(right_size) as f64 / left_size.max(right_size).max(1) as f64,
    );
    for name in SCORE_NAMES {
        let all: Vec<f64> = edges
            .iter()
            .map(|edge| edge.report_compatibility[name])
            .collect();
        features.insert(format!("{name}_edge_max"), maximum(&all));
        features.insert(format!("{name}_edge_mean"), mean(&all));
        for (suffix, q) in [("q90", 0.90), ("q95", 0.95), ("q99", 0.99)] {
            features.insert(format!("{name}_edge_{suffix}"), quantile(&all, q));
        }
        for (side, size, member_index) in [("left", left_size, true), ("right", right_size, false)]
        {
            let mut best = vec![0.0f64; size];
            for edge in edges {
                let index = if member_index {
                    edge.left_index
                } else {
                    edge.right_index
                };
                best[index] = best[index].max(edge.report_compatibility[name]);
            }
            features.insert(format!("{name}_{side}_best_q10"), quantile(&best, 0.10));
            features.insert(format!("{name}_{side}_best_median"), quantile(&best, 0.50));
            features.insert(format!("{name}_{side}_best_mean"), mean(&best));
            features.insert(
                format!("{name}_{side}_best_min"),
                best.iter().copied().min_by(f64::total_cmp).unwrap_or(0.0),
            );
            for threshold in [0.30, 0.50, 0.70, 0.85] {
                features.insert(
                    format!("{name}_{side}_share_ge_{threshold:.2}"),
                    share_at_least(&best, threshold),
                );
            }
        }
        let mutual: Vec<f64> = edges
            .iter()
            .filter(|edge| edge.mutual_top_k)
            .map(|edge| edge.report_compatibility[name])
            .collect();
        features.insert(format!("{name}_mutual_max"), maximum(&mutual));
        features.insert(format!("{name}_mutual_mean"), mean(&mutual));
        features.insert(format!("{name}_mutual_q90"), quantile(&mutual, 0.90));
        features.insert(format!("{name}_mutual_count"), mutual.len() as f64);
    }
    features
}

fn member_features(
    edges: &[PairEvidence],
    report_gate: &HashMap<String, f64>,
    left_size: usize,
    right_size: usize,
) -> (Vec<HashMap<String, f64>>, Vec<HashMap<String, f64>>) {
    let build_side = |left: bool, side_size: usize, opposite_size: usize| {
        let mut rows = Vec::with_capacity(side_size);
        for member in 0..side_size {
            let incident: Vec<&PairEvidence> = edges
                .iter()
                .filter(|edge| {
                    if left {
                        edge.left_index == member
                    } else {
                        edge.right_index == member
                    }
                })
                .collect();
            let mut features = HashMap::new();
            for name in SCORE_NAMES {
                let values: Vec<f64> = incident
                    .iter()
                    .map(|edge| edge.compatibility[name])
                    .collect();
                let best = maximum(&values);
                features.insert(format!("{name}_max"), best);
                features.insert(format!("{name}_mean"), mean(&values));
                features.insert(format!("{name}_q75"), quantile(&values, 0.75));
                features.insert(format!("{name}_q90"), quantile(&values, 0.90));
                features.insert(format!("{name}_margin"), best - second_largest(&values));
                for threshold in [0.30, 0.50, 0.70, 0.85] {
                    features.insert(
                        format!("{name}_share_ge_{threshold:.2}"),
                        share_at_least(&values, threshold),
                    );
                }
                let mutual: Vec<f64> = incident
                    .iter()
                    .filter(|edge| edge.mutual_top_k)
                    .map(|edge| edge.compatibility[name])
                    .collect();
                features.insert(format!("{name}_mutual_max"), maximum(&mutual));
            }
            let raw: Vec<f64> = incident.iter().map(|edge| edge.pair_raw).collect();
            let cal: Vec<f64> = incident.iter().map(|edge| edge.pair_cal).collect();
            let cosine: Vec<f64> = incident.iter().map(|edge| edge.embedding_cosine).collect();
            features.insert("pair_raw_max".to_string(), maximum(&raw));
            features.insert("pair_raw_mean".to_string(), mean(&raw));
            features.insert("pair_cal_max".to_string(), maximum(&cal));
            features.insert("embedding_cosine_max".to_string(), maximum(&cosine));
            features.insert("side_left".to_string(), if left { 1.0 } else { 0.0 });
            features.insert("left_size".to_string(), left_size as f64);
            features.insert("right_size".to_string(), right_size as f64);
            features.insert("member_side_size".to_string(), side_size as f64);
            features.insert("opposite_side_size".to_string(), opposite_size as f64);
            features.insert(
                "member_side_size_log".to_string(),
                (side_size as f64).ln_1p(),
            );
            features.insert(
                "opposite_side_size_log".to_string(),
                (opposite_size as f64).ln_1p(),
            );
            features.insert(
                "combined_size_log".to_string(),
                ((left_size + right_size) as f64).ln_1p(),
            );
            for (name, value) in report_gate {
                features.insert(format!("report_gate_{name}"), *value);
            }
            rows.push(features);
        }
        for name in SCORE_NAMES {
            let maxima: Vec<f64> = rows.iter().map(|row| row[&format!("{name}_max")]).collect();
            let report_max = maximum(&maxima).max(1.0e-6);
            let ranks = rank_shares(&maxima, side_size);
            for (index, row) in rows.iter_mut().enumerate() {
                row.insert(
                    format!("{name}_relative_to_report_max"),
                    maxima[index] / report_max,
                );
                row.insert(format!("{name}_member_rank_share"), ranks[index]);
            }
        }
        rows
    };
    (
        build_side(true, left_size, right_size),
        build_side(false, right_size, left_size),
    )
}

fn probability_summary(prefix: &str, values: &[f64], features: &mut HashMap<String, f64>) {
    features.insert(
        format!("{prefix}_min"),
        values.iter().copied().min_by(f64::total_cmp).unwrap_or(0.0),
    );
    features.insert(format!("{prefix}_q10"), quantile(values, 0.10));
    features.insert(format!("{prefix}_median"), quantile(values, 0.50));
    features.insert(format!("{prefix}_mean"), mean(values));
    features.insert(format!("{prefix}_q90"), quantile(values, 0.90));
    features.insert(format!("{prefix}_max"), maximum(values));
}

fn operation_risk_features(proposal: &Proposal, member_threshold: f64) -> HashMap<String, f64> {
    let left_size = proposal.left_probabilities.len();
    let right_size = proposal.right_probabilities.len();
    let selected_left: Vec<usize> = proposal
        .left_probabilities
        .iter()
        .enumerate()
        .filter_map(|(index, probability)| (*probability >= member_threshold).then_some(index))
        .collect();
    let selected_right: Vec<usize> = proposal
        .right_probabilities
        .iter()
        .enumerate()
        .filter_map(|(index, probability)| (*probability >= member_threshold).then_some(index))
        .collect();
    let selected_left_set: std::collections::HashSet<usize> =
        selected_left.iter().copied().collect();
    let selected_right_set: std::collections::HashSet<usize> =
        selected_right.iter().copied().collect();
    let selected_probabilities: Vec<f64> = proposal
        .left_probabilities
        .iter()
        .chain(&proposal.right_probabilities)
        .copied()
        .filter(|probability| *probability >= member_threshold)
        .collect();
    let unselected_probabilities: Vec<f64> = proposal
        .left_probabilities
        .iter()
        .chain(&proposal.right_probabilities)
        .copied()
        .filter(|probability| *probability < member_threshold)
        .collect();
    let selected_edges: Vec<&PairEvidence> = proposal
        .edges
        .iter()
        .filter(|edge| {
            selected_left_set.contains(&edge.left_index)
                && selected_right_set.contains(&edge.right_index)
        })
        .collect();
    let selected_count = selected_left.len() + selected_right.len();
    let mut features = HashMap::new();
    features.insert("member_threshold".to_string(), member_threshold);
    features.insert("left_size".to_string(), left_size as f64);
    features.insert("right_size".to_string(), right_size as f64);
    features.insert("left_size_log".to_string(), (left_size as f64).ln_1p());
    features.insert("right_size_log".to_string(), (right_size as f64).ln_1p());
    features.insert(
        "combined_size_log".to_string(),
        ((left_size + right_size) as f64).ln_1p(),
    );
    features.insert(
        "size_ratio".to_string(),
        left_size.min(right_size) as f64 / left_size.max(right_size).max(1) as f64,
    );
    features.insert(
        "selected_left_count".to_string(),
        selected_left.len() as f64,
    );
    features.insert(
        "selected_right_count".to_string(),
        selected_right.len() as f64,
    );
    features.insert("selected_count".to_string(), selected_count as f64);
    features.insert(
        "selected_left_share".to_string(),
        selected_left.len() as f64 / left_size.max(1) as f64,
    );
    features.insert(
        "selected_right_share".to_string(),
        selected_right.len() as f64 / right_size.max(1) as f64,
    );
    features.insert(
        "selected_combined_share".to_string(),
        selected_count as f64 / (left_size + right_size).max(1) as f64,
    );
    features.insert(
        "selected_side_balance".to_string(),
        selected_left.len().min(selected_right.len()) as f64
            / selected_left.len().max(selected_right.len()).max(1) as f64,
    );
    features.insert(
        "left_full".to_string(),
        if selected_left.len() == left_size {
            1.0
        } else {
            0.0
        },
    );
    features.insert(
        "right_full".to_string(),
        if selected_right.len() == right_size {
            1.0
        } else {
            0.0
        },
    );
    features.insert(
        "whole_merge".to_string(),
        if selected_left.len() == left_size && selected_right.len() == right_size {
            1.0
        } else {
            0.0
        },
    );
    probability_summary(
        "selected_probability",
        &selected_probabilities,
        &mut features,
    );
    probability_summary(
        "unselected_probability",
        &unselected_probabilities,
        &mut features,
    );
    features.insert(
        "mask_boundary_margin".to_string(),
        features["selected_probability_min"] - features["unselected_probability_max"],
    );
    for (name, score) in &proposal.report_gate {
        features.insert(format!("report_gate_{name}"), *score);
    }
    for name in SCORE_NAMES {
        let values: Vec<f64> = selected_edges
            .iter()
            .map(|edge| edge.compatibility[name])
            .collect();
        let prefix = format!("selected_edge_{name}");
        probability_summary(&prefix, &values, &mut features);
        for threshold in [0.30, 0.50, 0.70, 0.85] {
            features.insert(
                format!("{prefix}_share_ge_{threshold:.2}"),
                share_at_least(&values, threshold),
            );
        }
        let mut left_best: HashMap<usize, f64> = HashMap::new();
        let mut right_best: HashMap<usize, f64> = HashMap::new();
        for edge in &selected_edges {
            let score = edge.compatibility[name];
            left_best
                .entry(edge.left_index)
                .and_modify(|value| *value = value.max(score))
                .or_insert(score);
            right_best
                .entry(edge.right_index)
                .and_modify(|value| *value = value.max(score))
                .or_insert(score);
        }
        let left_values: Vec<f64> = left_best.into_values().collect();
        let right_values: Vec<f64> = right_best.into_values().collect();
        features.insert(
            format!("{prefix}_left_best_min"),
            left_values
                .iter()
                .copied()
                .min_by(f64::total_cmp)
                .unwrap_or(0.0),
        );
        features.insert(format!("{prefix}_left_best_mean"), mean(&left_values));
        features.insert(
            format!("{prefix}_right_best_min"),
            right_values
                .iter()
                .copied()
                .min_by(f64::total_cmp)
                .unwrap_or(0.0),
        );
        features.insert(format!("{prefix}_right_best_mean"), mean(&right_values));
    }
    features
}

#[cfg(feature = "neural-onnx")]
mod enabled {
    use super::*;
    use anyhow::Context;
    use sha2::{Digest, Sha256};
    use std::path::{Path, PathBuf};
    use tract_onnx::prelude::*;

    pub struct MemberRepair {
        manifest: Manifest,
        contextual: Vec<(usize, TypedRunnableModel<TypedModel>)>,
        bipartite: Vec<(usize, TypedRunnableModel<TypedModel>)>,
        full_embedding: bool,
        integrated: bool,
    }

    fn resolve_sibling(base: &Path, child: &str) -> PathBuf {
        base.parent().unwrap_or_else(|| Path::new(".")).join(child)
    }

    fn load_model(base: &Path, artifact: &Artifact) -> Result<TypedRunnableModel<TypedModel>> {
        let path = resolve_sibling(base, &artifact.path);
        let bytes = std::fs::read(&path).with_context(|| path.display().to_string())?;
        if bytes.len() as u64 != artifact.bytes {
            bail!(
                "member-repair ONNX artifact size mismatch: {}",
                path.display()
            );
        }
        let digest = format!("{:x}", Sha256::digest(&bytes));
        if digest != artifact.sha256 {
            bail!(
                "member-repair ONNX artifact digest mismatch: {}",
                path.display()
            );
        }
        Ok(tract_onnx::onnx()
            .model_for_path(&path)?
            .into_optimized()?
            .into_runnable()?)
    }

    fn load_buckets(
        base: &Path,
        buckets: &[NeuralBucket],
        required_maximum: usize,
    ) -> Result<Vec<(usize, TypedRunnableModel<TypedModel>)>> {
        if buckets.is_empty()
            || buckets
                .last()
                .is_none_or(|bucket| bucket.width != required_maximum)
            || buckets
                .windows(2)
                .any(|pair| pair[0].width >= pair[1].width)
        {
            bail!("member-repair ONNX bucket contract mismatch");
        }
        buckets
            .iter()
            .map(|bucket| Ok((bucket.width, load_model(base, &bucket.artifact)?)))
            .collect()
    }

    impl MemberRepair {
        pub fn load(path: &str) -> Result<Self> {
            let path = Path::new(path);
            let manifest: Manifest = serde_json::from_str(
                &std::fs::read_to_string(path).with_context(|| path.display().to_string())?,
            )?;
            let (full_embedding, integrated) = match (
                manifest.schema_version,
                manifest.model_family.as_str(),
                manifest.feature_contract.as_str(),
            ) {
                (
                    1,
                    "member_aware_report_pair_repair",
                    "lab2-exact-member-v3-live-replay-v2-bucketed-members",
                ) => (false, false),
                (
                    1,
                    "member_aware_report_pair_repair_full_embedding",
                    "lab2-exact-member-v3-full-embedding-live-replay-v1",
                ) => (true, false),
                (
                    2,
                    "integrated_bipartite_report_shuffler",
                    "lab2-exact-member-v3-integrated-shuffler-v1",
                ) => (true, true),
                _ => bail!("unsupported member-repair manifest contract"),
            };
            let expected_node_features = if integrated {
                LEGACY_NODE_FEATURES - 3
            } else {
                LEGACY_NODE_FEATURES
            };
            if manifest.caps.top_k_each_direction != TOP_K
                || manifest.caps.max_report_members != MAX_REPORT_MEMBERS
                || manifest.caps.max_combined_members != MAX_COMBINED_MEMBERS
                || manifest.node_feature_names.len() != expected_node_features
                || manifest.edge_feature_names.len() != EDGE_FEATURES
                || (full_embedding && manifest.caps.embedding_dims != Some(EMBEDDING_DIMS))
                || (integrated
                    && manifest
                        .node_feature_names
                        .iter()
                        .any(|name| name.starts_with("report_gate_")))
            {
                bail!("member-repair manifest shape contract mismatch");
            }
            let contextual = match &manifest.contextual {
                Some(contract) => load_buckets(path, &contract.buckets, MAX_COMBINED_MEMBERS)?,
                None if integrated => Vec::new(),
                None => bail!("member-repair contextual contract is missing"),
            };
            let bipartite = load_buckets(path, &manifest.bipartite.buckets, MAX_REPORT_MEMBERS)?;
            Ok(Self {
                manifest,
                contextual,
                bipartite,
                full_embedding,
                integrated,
            })
        }

        fn score_compatibility(
            &self,
            architecture: Architecture,
            edges: &mut [PairEvidence],
            left_size: usize,
            right_size: usize,
        ) -> Result<()> {
            let mut left_raw = vec![Vec::new(); left_size];
            let mut left_cal = vec![Vec::new(); left_size];
            let mut right_raw = vec![Vec::new(); right_size];
            let mut right_cal = vec![Vec::new(); right_size];
            for edge in edges.iter() {
                left_raw[edge.left_index].push(edge.pair_raw);
                left_cal[edge.left_index].push(edge.pair_cal);
                right_raw[edge.right_index].push(edge.pair_raw);
                right_cal[edge.right_index].push(edge.pair_cal);
            }
            let report_left_raw: Vec<f64> = left_raw.iter().map(|values| maximum(values)).collect();
            let report_right_raw: Vec<f64> =
                right_raw.iter().map(|values| maximum(values)).collect();
            let models = match architecture {
                Architecture::Contextual => &self.manifest.compatibility_primary,
                Architecture::Bipartite => &self.manifest.compatibility_consensus,
            };
            for edge in edges.iter_mut() {
                let features = compatibility_features(
                    edge,
                    &left_raw,
                    &left_cal,
                    &right_raw,
                    &right_cal,
                    &report_left_raw,
                    &report_right_raw,
                    left_size,
                    right_size,
                );
                edge.report_compatibility = self
                    .manifest
                    .compatibility_primary
                    .iter()
                    .map(|(name, model)| Ok((name.clone(), model.predict(&features)?)))
                    .collect::<Result<_>>()?;
                edge.compatibility = models
                    .iter()
                    .map(|(name, model)| Ok((name.clone(), model.predict(&features)?)))
                    .collect::<Result<_>>()?;
            }
            Ok(())
        }

        fn infer_contextual(
            &self,
            left: &[HashMap<String, f64>],
            right: &[HashMap<String, f64>],
            left_embeddings: &[&[f32]],
            right_embeddings: &[&[f32]],
        ) -> Result<(Vec<f64>, Vec<f64>)> {
            let count = left.len() + right.len();
            let (width, model) = self
                .contextual
                .iter()
                .find(|(width, _)| *width >= count)
                .ok_or_else(|| {
                    anyhow::anyhow!("no contextual member-repair bucket for {count} members")
                })?;
            let width = *width;
            let node_features = self.manifest.node_feature_names.len();
            let mut values = vec![0.0f32; width * node_features];
            let mut embedding_values = vec![0.0f32; width * EMBEDDING_DIMS];
            let mut sides = vec![0i64; width];
            let mut mask = vec![false; width];
            for (position, row) in left.iter().chain(right).enumerate() {
                for (feature, name) in self.manifest.node_feature_names.iter().enumerate() {
                    values[position * node_features + feature] = *row
                        .get(name)
                        .ok_or_else(|| anyhow::anyhow!("missing contextual node feature {name}"))?
                        as f32;
                }
                sides[position] = if position < left.len() { 1 } else { 0 };
                mask[position] = true;
            }
            for (position, embedding) in left_embeddings.iter().chain(right_embeddings).enumerate()
            {
                if embedding.len() != EMBEDDING_DIMS
                    || embedding.iter().any(|value| !value.is_finite())
                {
                    bail!("contextual member embedding violates the full-vector contract");
                }
                let start = position * EMBEDDING_DIMS;
                embedding_values[start..start + EMBEDDING_DIMS].copy_from_slice(embedding);
            }
            let features: Tensor =
                tract_ndarray::Array3::from_shape_vec((1, width, node_features), values)?.into();
            let sides: Tensor = tract_ndarray::Array2::from_shape_vec((1, width), sides)?.into();
            let mask: Tensor = tract_ndarray::Array2::from_shape_vec((1, width), mask)?.into();
            let outputs = if self.full_embedding {
                let embeddings: Tensor = tract_ndarray::Array3::from_shape_vec(
                    (1, width, EMBEDDING_DIMS),
                    embedding_values,
                )?
                .into();
                model.run(tvec![
                    features.into(),
                    embeddings.into(),
                    sides.into(),
                    mask.into()
                ])?
            } else {
                model.run(tvec![features.into(), sides.into(), mask.into()])?
            };
            let logits = outputs[0].to_array_view::<f32>()?;
            if logits.len() != width {
                bail!("contextual member selector returned an incompatible output");
            }
            let probabilities: Vec<f64> = logits
                .iter()
                .take(count)
                .map(|value| 1.0 / (1.0 + (-(*value as f64)).exp()))
                .collect();
            Ok((
                probabilities[..left.len()].to_vec(),
                probabilities[left.len()..].to_vec(),
            ))
        }

        fn infer_bipartite(
            &self,
            left: &[HashMap<String, f64>],
            right: &[HashMap<String, f64>],
            left_embeddings: &[&[f32]],
            right_embeddings: &[&[f32]],
            edges: &[PairEvidence],
            member_threshold: f64,
        ) -> Result<(Vec<f64>, Vec<f64>, Option<f64>, Option<f64>)> {
            let left_count = left.len();
            let right_count = right.len();
            let needed = left_count.max(right_count);
            let (width, model) = self
                .bipartite
                .iter()
                .find(|(width, _)| *width >= needed)
                .ok_or_else(|| {
                    anyhow::anyhow!("no bipartite member-repair bucket for {needed} members")
                })?;
            let width = *width;
            let node_features = self.manifest.node_feature_names.len();
            let mut left_values = vec![0.0f32; width * node_features];
            let mut right_values = vec![0.0f32; width * node_features];
            let mut left_embedding_values = vec![0.0f32; width * EMBEDDING_DIMS];
            let mut right_embedding_values = vec![0.0f32; width * EMBEDDING_DIMS];
            for (rows, values) in [(left, &mut left_values), (right, &mut right_values)] {
                for (position, row) in rows.iter().enumerate() {
                    for (feature, name) in self.manifest.node_feature_names.iter().enumerate() {
                        values[position * node_features + feature] =
                            *row.get(name).ok_or_else(|| {
                                anyhow::anyhow!("missing bipartite node feature {name}")
                            })? as f32;
                    }
                }
            }
            for (embeddings, values) in [
                (left_embeddings, &mut left_embedding_values),
                (right_embeddings, &mut right_embedding_values),
            ] {
                for (position, embedding) in embeddings.iter().enumerate() {
                    if embedding.len() != EMBEDDING_DIMS
                        || embedding.iter().any(|value| !value.is_finite())
                    {
                        bail!("bipartite member embedding violates the full-vector contract");
                    }
                    let start = position * EMBEDDING_DIMS;
                    values[start..start + EMBEDDING_DIMS].copy_from_slice(embedding);
                }
            }
            let mut edge_values = vec![0.0f32; width * width * EDGE_FEATURES];
            let mut edge_mask = vec![false; width * width];
            for edge in edges {
                let base = (edge.left_index * width + edge.right_index) * EDGE_FEATURES;
                let mut features = HashMap::new();
                for name in BIPARTITE_SCORE_NAMES {
                    features.insert(format!("probability:{name}"), edge.compatibility[name]);
                }
                features.insert("pair_raw".to_string(), edge.pair_raw);
                features.insert("pair_cal".to_string(), edge.pair_cal);
                features.insert("embedding_cosine".to_string(), edge.embedding_cosine);
                features.insert(
                    "left_rank_filled".to_string(),
                    edge.left_rank.unwrap_or(25) as f64,
                );
                features.insert(
                    "right_rank_filled".to_string(),
                    edge.right_rank.unwrap_or(25) as f64,
                );
                features.insert(
                    "mutual_top_k_float".to_string(),
                    if edge.mutual_top_k { 1.0 } else { 0.0 },
                );
                for (offset, name) in self.manifest.edge_feature_names.iter().enumerate() {
                    edge_values[base + offset] = *features
                        .get(name)
                        .ok_or_else(|| anyhow::anyhow!("missing bipartite edge feature {name}"))?
                        as f32;
                }
                edge_mask[edge.left_index * width + edge.right_index] = true;
            }
            let left_tensor: Tensor =
                tract_ndarray::Array3::from_shape_vec((1, width, node_features), left_values)?
                    .into();
            let right_tensor: Tensor =
                tract_ndarray::Array3::from_shape_vec((1, width, node_features), right_values)?
                    .into();
            let edge_tensor: Tensor = tract_ndarray::Array4::from_shape_vec(
                (1, width, width, EDGE_FEATURES),
                edge_values,
            )?
            .into();
            let mask_tensor: Tensor =
                tract_ndarray::Array3::from_shape_vec((1, width, width), edge_mask)?.into();
            let outputs = if self.full_embedding {
                let left_embeddings: Tensor = tract_ndarray::Array3::from_shape_vec(
                    (1, width, EMBEDDING_DIMS),
                    left_embedding_values,
                )?
                .into();
                let right_embeddings: Tensor = tract_ndarray::Array3::from_shape_vec(
                    (1, width, EMBEDDING_DIMS),
                    right_embedding_values,
                )?
                .into();
                if self.integrated {
                    let threshold: Tensor = tract_ndarray::Array2::from_shape_vec(
                        (1, 1),
                        vec![member_threshold as f32],
                    )?
                    .into();
                    model.run(tvec![
                        left_tensor.into(),
                        right_tensor.into(),
                        left_embeddings.into(),
                        right_embeddings.into(),
                        edge_tensor.into(),
                        mask_tensor.into(),
                        threshold.into()
                    ])?
                } else {
                    model.run(tvec![
                        left_tensor.into(),
                        right_tensor.into(),
                        left_embeddings.into(),
                        right_embeddings.into(),
                        edge_tensor.into(),
                        mask_tensor.into()
                    ])?
                }
            } else {
                model.run(tvec![
                    left_tensor.into(),
                    right_tensor.into(),
                    edge_tensor.into(),
                    mask_tensor.into()
                ])?
            };
            let left_logits = outputs[0].to_array_view::<f32>()?;
            let right_logits = outputs[1].to_array_view::<f32>()?;
            let sigmoid = |value: &f32| 1.0 / (1.0 + (-(*value as f64)).exp());
            let action_probability = if self.integrated {
                Some(sigmoid(
                    outputs[2]
                        .to_array_view::<f32>()?
                        .iter()
                        .next()
                        .ok_or_else(|| anyhow::anyhow!("integrated action output is empty"))?,
                ))
            } else {
                None
            };
            let safety_probability = if self.integrated {
                Some(sigmoid(
                    outputs[3]
                        .to_array_view::<f32>()?
                        .iter()
                        .next()
                        .ok_or_else(|| anyhow::anyhow!("integrated safety output is empty"))?,
                ))
            } else {
                None
            };
            Ok((
                left_logits.iter().take(left.len()).map(sigmoid).collect(),
                right_logits.iter().take(right.len()).map(sigmoid).collect(),
                action_probability,
                safety_probability,
            ))
        }

        pub fn propose(
            &self,
            architecture: Architecture,
            mut edges: Vec<PairEvidence>,
            left_embeddings: &[&[f32]],
            right_embeddings: &[&[f32]],
            member_threshold: f64,
        ) -> Result<Proposal> {
            let left_size = left_embeddings.len();
            let right_size = right_embeddings.len();
            if left_size == 0
                || right_size == 0
                || left_size > MAX_REPORT_MEMBERS
                || right_size > MAX_REPORT_MEMBERS
                || left_size + right_size > MAX_COMBINED_MEMBERS
            {
                bail!("report pair violates the member-repair size contract");
            }
            self.score_compatibility(architecture, &mut edges, left_size, right_size)?;
            let report_features = report_features(&edges, left_size, right_size);
            let report_gate: HashMap<String, f64> = self
                .manifest
                .report_gate
                .iter()
                .map(|(name, model)| Ok((name.clone(), model.predict(&report_features)?)))
                .collect::<Result<_>>()?;
            let (left_features, right_features) =
                member_features(&edges, &report_gate, left_size, right_size);
            let (left_probabilities, right_probabilities, action_probability, safety_probability) =
                match architecture {
                    Architecture::Contextual => {
                        let (left, right) = self.infer_contextual(
                            &left_features,
                            &right_features,
                            left_embeddings,
                            right_embeddings,
                        )?;
                        (left, right, None, None)
                    }
                    Architecture::Bipartite => self.infer_bipartite(
                        &left_features,
                        &right_features,
                        left_embeddings,
                        right_embeddings,
                        &edges,
                        member_threshold,
                    )?,
                };
            Ok(Proposal {
                left_probabilities,
                right_probabilities,
                action_probability,
                safety_probability,
                report_gate,
                edges,
            })
        }

        pub fn operation_risk(
            &self,
            architecture: Architecture,
            proposal: &Proposal,
            member_threshold: f64,
        ) -> Result<HashMap<String, f64>> {
            let features = operation_risk_features(proposal, member_threshold);
            let models = match architecture {
                Architecture::Contextual => &self.manifest.operation_risk_contextual,
                Architecture::Bipartite => &self.manifest.operation_risk_bipartite,
            };
            models
                .iter()
                .map(|(name, model)| Ok((name.clone(), model.predict(&features)?)))
                .collect()
        }
    }
}

#[cfg(feature = "neural-onnx")]
pub use enabled::MemberRepair;

#[cfg(not(feature = "neural-onnx"))]
pub struct MemberRepair;

#[cfg(not(feature = "neural-onnx"))]
impl MemberRepair {
    pub fn load(_path: &str) -> Result<Self> {
        bail!("member repair requested, but engine was built without --features neural-onnx")
    }

    pub fn propose(
        &self,
        _architecture: Architecture,
        _edges: Vec<PairEvidence>,
        _left_embeddings: &[&[f32]],
        _right_embeddings: &[&[f32]],
        _member_threshold: f64,
    ) -> Result<Proposal> {
        bail!("member repair unavailable")
    }

    pub fn operation_risk(
        &self,
        _architecture: Architecture,
        _proposal: &Proposal,
        _member_threshold: f64,
    ) -> Result<HashMap<String, f64>> {
        bail!("member repair unavailable")
    }
}

#[cfg(all(test, feature = "neural-onnx"))]
mod tests {
    use super::*;
    use serde::Deserialize;
    use std::path::PathBuf;

    #[derive(Deserialize)]
    struct Fixture {
        cases: Vec<FixtureCase>,
    }

    #[derive(Deserialize)]
    struct FixtureCase {
        merge_id: String,
        left_size: usize,
        right_size: usize,
        edges: Vec<FixtureEdge>,
        architectures: HashMap<String, FixtureExpected>,
    }

    #[derive(Deserialize)]
    struct FixtureEdge {
        left_index: usize,
        right_index: usize,
        embedding_cosine: f64,
        left_rank: Option<usize>,
        right_rank: Option<usize>,
        pair_raw: f64,
        pair_cal: f64,
        rust_features: HashMap<String, f64>,
        compatibility_features: HashMap<String, f64>,
    }

    #[derive(Deserialize)]
    struct FixtureExpected {
        member_threshold: f64,
        left_probabilities: Vec<f64>,
        right_probabilities: Vec<f64>,
        report_gate: HashMap<String, f64>,
        compatibility: Vec<FixtureCompatibility>,
        report_compatibility: Vec<FixtureCompatibility>,
        operation_risk: HashMap<String, f64>,
    }

    #[derive(Deserialize)]
    struct FixtureCompatibility {
        left_index: usize,
        right_index: usize,
        scores: HashMap<String, f64>,
    }

    fn artifact_path(name: &str) -> PathBuf {
        PathBuf::from(env!("CARGO_MANIFEST_DIR"))
            .join("../data/member_repair/20260713-v1")
            .join(name)
    }

    fn assert_close(label: &str, expected: f64, actual: f64, tolerance: f64) {
        let delta = (expected - actual).abs();
        assert!(
            delta <= tolerance,
            "{label}: expected={expected:.9} actual={actual:.9} delta={delta:.9}"
        );
    }

    fn assert_vector(label: &str, expected: &[f64], actual: &[f64], tolerance: f64) {
        assert_eq!(expected.len(), actual.len(), "{label} length");
        for (index, (expected, actual)) in expected.iter().zip(actual).enumerate() {
            assert_close(&format!("{label}[{index}]"), *expected, *actual, tolerance);
        }
    }

    fn assert_map(
        label: &str,
        expected: &HashMap<String, f64>,
        actual: &HashMap<String, f64>,
        tolerance: f64,
    ) {
        assert_eq!(expected.len(), actual.len(), "{label} width");
        for (name, expected) in expected {
            assert_close(
                &format!("{label}.{name}"),
                *expected,
                actual[name],
                tolerance,
            );
        }
    }

    fn assert_map_subset(
        label: &str,
        expected: &HashMap<String, f64>,
        actual: &HashMap<String, f64>,
        tolerance: f64,
    ) {
        for (name, expected) in expected {
            assert_close(
                &format!("{label}.{name}"),
                *expected,
                actual[name],
                tolerance,
            );
        }
    }

    #[test]
    fn python_rust_report_pair_parity() -> Result<()> {
        let fixture: Fixture = serde_json::from_str(&std::fs::read_to_string(artifact_path(
            "parity_fixture.json",
        ))?)?;
        let repair = MemberRepair::load(
            artifact_path("member_repair.manifest.json")
                .to_str()
                .expect("artifact path is UTF-8"),
        )?;
        for case in fixture.cases {
            let expected_features: HashMap<(usize, usize), &HashMap<String, f64>> = case
                .edges
                .iter()
                .map(|edge| {
                    (
                        (edge.left_index, edge.right_index),
                        &edge.compatibility_features,
                    )
                })
                .collect();
            let edges: Vec<PairEvidence> = case
                .edges
                .iter()
                .map(|edge| {
                    PairEvidence::new(
                        edge.left_index,
                        edge.right_index,
                        edge.embedding_cosine,
                        edge.left_rank,
                        edge.right_rank,
                        edge.pair_raw,
                        edge.pair_cal,
                        edge.rust_features.clone(),
                    )
                })
                .collect();
            let mut left_raw = vec![Vec::new(); case.left_size];
            let mut left_cal = vec![Vec::new(); case.left_size];
            let mut right_raw = vec![Vec::new(); case.right_size];
            let mut right_cal = vec![Vec::new(); case.right_size];
            for edge in &edges {
                left_raw[edge.left_index].push(edge.pair_raw);
                left_cal[edge.left_index].push(edge.pair_cal);
                right_raw[edge.right_index].push(edge.pair_raw);
                right_cal[edge.right_index].push(edge.pair_cal);
            }
            let report_left_raw: Vec<f64> = left_raw.iter().map(|values| maximum(values)).collect();
            let report_right_raw: Vec<f64> =
                right_raw.iter().map(|values| maximum(values)).collect();
            for edge in &edges {
                let actual = compatibility_features(
                    edge,
                    &left_raw,
                    &left_cal,
                    &right_raw,
                    &right_cal,
                    &report_left_raw,
                    &report_right_raw,
                    case.left_size,
                    case.right_size,
                );
                assert_map_subset(
                    &format!(
                        "{}.features.({}, {})",
                        case.merge_id, edge.left_index, edge.right_index
                    ),
                    expected_features[&(edge.left_index, edge.right_index)],
                    &actual,
                    2.0e-7,
                );
            }
            for (name, architecture) in [
                ("contextual", Architecture::Contextual),
                ("bipartite", Architecture::Bipartite),
            ] {
                let expected = &case.architectures[name];
                let left_values = vec![vec![0.0f32; EMBEDDING_DIMS]; case.left_size];
                let right_values = vec![vec![0.0f32; EMBEDDING_DIMS]; case.right_size];
                let left_embeddings = left_values.iter().map(Vec::as_slice).collect::<Vec<_>>();
                let right_embeddings = right_values.iter().map(Vec::as_slice).collect::<Vec<_>>();
                let proposal = repair.propose(
                    architecture,
                    edges.clone(),
                    &left_embeddings,
                    &right_embeddings,
                    expected.member_threshold,
                )?;
                let compatibility: HashMap<(usize, usize), &FixtureCompatibility> = expected
                    .compatibility
                    .iter()
                    .map(|edge| ((edge.left_index, edge.right_index), edge))
                    .collect();
                let report_compatibility: HashMap<(usize, usize), &FixtureCompatibility> = expected
                    .report_compatibility
                    .iter()
                    .map(|edge| ((edge.left_index, edge.right_index), edge))
                    .collect();
                for edge in &proposal.edges {
                    let key = (edge.left_index, edge.right_index);
                    assert_map(
                        &format!("{}.{}.edge.{key:?}", case.merge_id, name),
                        &compatibility[&key].scores,
                        &edge.compatibility,
                        2.0e-7,
                    );
                    assert_map(
                        &format!("{}.{}.report_edge.{key:?}", case.merge_id, name),
                        &report_compatibility[&key].scores,
                        &edge.report_compatibility,
                        2.0e-7,
                    );
                }
                assert_vector(
                    &format!("{}.{}.left", case.merge_id, name),
                    &expected.left_probabilities,
                    &proposal.left_probabilities,
                    2.0e-5,
                );
                assert_vector(
                    &format!("{}.{}.right", case.merge_id, name),
                    &expected.right_probabilities,
                    &proposal.right_probabilities,
                    2.0e-5,
                );
                assert_map(
                    &format!("{}.{}.report", case.merge_id, name),
                    &expected.report_gate,
                    &proposal.report_gate,
                    2.0e-7,
                );
                let risk =
                    repair.operation_risk(architecture, &proposal, expected.member_threshold)?;
                assert_map(
                    &format!("{}.{}.risk", case.merge_id, name),
                    &expected.operation_risk,
                    &risk,
                    2.0e-7,
                );
            }
        }
        Ok(())
    }
}
