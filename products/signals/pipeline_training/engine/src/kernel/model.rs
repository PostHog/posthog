//! GBDT (sklearn HistGradientBoosting) + isotonic calibration inference, loaded
//! from the JSON produced by export_models.py. Parity target: |Δp| < 1e-6 vs
//! sklearn on the exported fixtures.

use serde::Deserialize;
use std::collections::HashMap;

#[derive(Deserialize)]
pub struct TreeNode {
    pub value: f64,
    pub feature_idx: i32,
    pub num_threshold: f64,
    pub missing_go_to_left: bool,
    pub left: u32,
    pub right: u32,
    pub is_leaf: bool,
}

#[derive(Deserialize)]
pub struct GbdtModel {
    pub baseline: f64,
    pub trees: Vec<Vec<TreeNode>>,
    pub iso_x: Vec<f64>,
    pub iso_y: Vec<f64>,
    pub feature_names: Vec<String>,
    #[serde(default)]
    pub tau: Option<f64>,
    #[serde(default)]
    pub gamma: Option<f64>,
    #[serde(default)]
    pub sigma: Option<f64>,
    /// v2 concern models: gamma/sigma bind on the RAW score, not the calibrated
    /// one (isotonic plateaus made calibrated thresholds a dead knob)
    #[serde(default)]
    pub thresholds_on_raw: bool,
}

impl GbdtModel {
    fn tree_value(nodes: &[TreeNode], x: &[f64]) -> f64 {
        let mut node = &nodes[0];
        while !node.is_leaf {
            let v = x[node.feature_idx as usize];
            node = if v.is_nan() {
                if node.missing_go_to_left {
                    &nodes[node.left as usize]
                } else {
                    &nodes[node.right as usize]
                }
            } else if v <= node.num_threshold {
                &nodes[node.left as usize]
            } else {
                &nodes[node.right as usize]
            };
        }
        node.value
    }

    /// predict_proba[:, 1] — sigmoid of baseline + tree sum.
    pub fn raw_proba(&self, x: &[f64]) -> f64 {
        let mut raw = self.baseline;
        for tree in &self.trees {
            raw += Self::tree_value(tree, x);
        }
        1.0 / (1.0 + (-raw).exp())
    }

    /// Isotonic calibration: np.interp with clip out-of-bounds (sklearn semantics).
    pub fn calibrate(&self, p: f64) -> f64 {
        interp_clip(p, &self.iso_x, &self.iso_y)
    }

    pub fn predict(&self, x: &[f64]) -> (f64, f64) {
        let raw = self.raw_proba(x);
        (raw, self.calibrate(raw))
    }

    /// Assemble the feature vector in this model's training order.
    pub fn vectorize(&self, feats: &HashMap<&'static str, f64>) -> Vec<f64> {
        self.feature_names
            .iter()
            .map(|n| *feats.get(n.as_str()).unwrap_or(&f64::NAN))
            .collect()
    }
}

pub fn interp_clip(x: f64, xs: &[f64], ys: &[f64]) -> f64 {
    if xs.is_empty() {
        return x;
    }
    if x <= xs[0] {
        return ys[0];
    }
    if x >= xs[xs.len() - 1] {
        return ys[ys.len() - 1];
    }
    // np.interp: linear between surrounding knots (xs sorted ascending)
    let j = xs.partition_point(|&v| v <= x); // first index with xs[j] > x
    let (x0, x1) = (xs[j - 1], xs[j]);
    let (y0, y1) = (ys[j - 1], ys[j]);
    if x1 == x0 {
        y0
    } else {
        y0 + (y1 - y0) * (x - x0) / (x1 - x0)
    }
}

/// BurstIndex: same-type arrival counts within ±1h over the FULL universe stream
/// (exported sorted epoch arrays per (product, type)).
pub struct BurstIndex {
    epochs: HashMap<String, Vec<f64>>,
}

impl BurstIndex {
    pub fn new(map: HashMap<String, Vec<f64>>) -> Self {
        Self { epochs: map }
    }

    pub fn count(&self, product: &str, source_type: &str, ts: f64) -> f64 {
        let key = format!("{product}\u{0}{source_type}");
        let Some(arr) = self.epochs.get(&key) else {
            return 0.0;
        };
        let lo = arr.partition_point(|&v| v < ts - 3600.0);
        let hi = arr.partition_point(|&v| v < ts + 3600.0);
        let n = (hi as i64 - lo as i64 - 1).max(0);
        (1.0 + n as f64).ln()
    }
}

#[derive(Deserialize)]
pub struct LinearLayer {
    pub w: Vec<Vec<f64>>, // out x in
    pub b: Vec<f64>,
}

impl LinearLayer {
    pub fn forward(&self, x: &[f64]) -> Vec<f64> {
        self.w
            .iter()
            .zip(&self.b)
            .map(|(row, b)| row.iter().zip(x).map(|(w, v)| w * v).sum::<f64>() + b)
            .collect()
    }
}

/// gj3 dsM deep-sets encoder: phi(token) per member -> masked mean+max pool ->
/// rho -> 16 pooled dims consumed by the stack GBM as features dsm_0..dsm_15
#[derive(Deserialize)]
pub struct GjNet {
    pub phi1: LinearLayer,
    pub phi2: LinearLayer,
    pub rho: LinearLayer,
    pub d_token: usize,
    pub d_pool: usize,
    pub member_cap: usize,
}

impl GjNet {
    pub fn pool(&self, tokens: &[Vec<f64>]) -> Vec<f64> {
        let h: Vec<Vec<f64>> = tokens
            .iter()
            .map(|t| {
                let a: Vec<f64> = self.phi1.forward(t).iter().map(|v| v.max(0.0)).collect();
                self.phi2.forward(&a)
            })
            .collect();
        let d = h.first().map_or(32, |v| v.len());
        let n = h.len().max(1) as f64;
        let mut mean = vec![0f64; d];
        let mut mx = vec![f64::NEG_INFINITY; d];
        for row in &h {
            for (i, v) in row.iter().enumerate() {
                mean[i] += v / n;
                mx[i] = mx[i].max(*v);
            }
        }
        if h.is_empty() {
            mx = vec![0.0; d];
        }
        let cat: Vec<f64> = mean.into_iter().chain(mx).collect();
        self.rho.forward(&cat).iter().map(|v| v.max(0.0)).collect()
    }
}

#[derive(Deserialize)]
pub struct ModelsFile {
    pub pair: GbdtModel,
    #[serde(default)]
    pub join: Option<GbdtModel>,
    #[serde(default)]
    pub concern: Option<GbdtModel>,
    /// one-model groupwise matcher (gj experiment): scores (signal, group)
    /// directly over engineered group features, replacing the pairwise
    /// argmax + tau decision when cfg.use_groupjoin is set
    #[serde(default)]
    pub groupjoin: Option<GbdtModel>,
    /// Optional decision-balanced ranker. When present, this chooses which
    /// candidate report wins while `groupjoin` still controls admission.
    #[serde(default)]
    pub groupjoin_ranker: Option<GbdtModel>,
    /// Optional pairwise preference model comparing an eligible challenger
    /// report with the admission model's incumbent.
    #[serde(default)]
    pub groupjoin_pair_ranker: Option<GbdtModel>,
    #[serde(default)]
    pub groupjoin_net: Option<GjNet>,
    pub burst: HashMap<String, Vec<f64>>,
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn interp_matches_numpy_semantics() {
        let xs = vec![0.0, 0.5, 1.0];
        let ys = vec![0.0, 0.8, 1.0];
        assert!((interp_clip(0.25, &xs, &ys) - 0.4).abs() < 1e-12);
        assert!((interp_clip(-1.0, &xs, &ys) - 0.0).abs() < 1e-12);
        assert!((interp_clip(2.0, &xs, &ys) - 1.0).abs() < 1e-12);
    }
}
