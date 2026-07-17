//! Exact-artifact execution for the contextual dual-set groupjoin offshoot.

use anyhow::{bail, Result};
use std::collections::HashMap;

pub const MEMBER_CAP: usize = 40;
pub const EXTERNAL_CAP: usize = 32;
pub const TOKEN_DIMS: usize = 79;
pub const ENGINEERED_DIMS: usize = 26;
pub const POOL_DIMS: usize = 64;

pub struct ContextualGroupJoinOutput {
    pub raw: f64,
    pub calibrated: f64,
    pub coherence_raw: Option<f64>,
    pub coherence_calibrated: Option<f64>,
    pub admission_raw: Option<f64>,
    pub admission_calibrated: Option<f64>,
    pub pointer: Vec<f64>,
    pub pooled: Vec<f64>,
}

#[cfg(feature = "neural-onnx")]
mod enabled {
    use super::*;
    use anyhow::Context;
    use serde::Deserialize;
    use sha2::{Digest, Sha256};
    use std::path::{Path, PathBuf};
    use tract_onnx::prelude::*;

    const FEATURE_NAMES: [&str; ENGINEERED_DIMS] = [
        "cos_max",
        "cos_2nd",
        "cos_mean",
        "cos_centroid",
        "coherence",
        "coherence_delta",
        "log_size",
        "rank_best",
        "n_retrieved",
        "frac_same_product",
        "frac_same_type",
        "log_gap_hours",
        "log_span_hours",
        "id_shared",
        "id_conflict",
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
    ];

    #[derive(Deserialize)]
    struct Artifact {
        path: String,
        bytes: u64,
        sha256: String,
    }

    #[derive(Deserialize)]
    struct TensorContract {
        dtype: String,
        shape: Vec<serde_json::Value>,
        #[serde(default)]
        names: Vec<String>,
    }

    #[derive(Deserialize)]
    struct InputContract {
        report_tokens: TensorContract,
        report_mask: TensorContract,
        external_tokens: TensorContract,
        external_mask: TensorContract,
        engineered_features: TensorContract,
    }

    #[derive(Deserialize)]
    struct OutputContract {
        #[serde(default)]
        join_logit: Option<TensorContract>,
        #[serde(default)]
        match_logit: Option<TensorContract>,
        #[serde(default)]
        coherence_logit: Option<TensorContract>,
        #[serde(default)]
        admission_logit: Option<TensorContract>,
        pointer_logits: TensorContract,
        pooled_representation: TensorContract,
    }

    #[derive(Deserialize)]
    struct Calibration {
        r#type: String,
        input: String,
        x: Vec<f64>,
        y: Vec<f64>,
    }

    #[derive(Deserialize)]
    struct Manifest {
        schema_version: u32,
        model_family: String,
        feature_contract: String,
        artifact: Artifact,
        inputs: InputContract,
        outputs: OutputContract,
        calibration: Calibration,
        #[serde(default)]
        coherence_calibration: Option<Calibration>,
        #[serde(default)]
        admission_calibration: Option<Calibration>,
    }

    pub struct ContextualGroupJoin {
        model: TypedRunnableModel<TypedModel>,
        feature_names: Vec<String>,
        calibration_x: Vec<f64>,
        calibration_y: Vec<f64>,
        coherence_calibration_x: Option<Vec<f64>>,
        coherence_calibration_y: Option<Vec<f64>>,
        admission_calibration_x: Option<Vec<f64>>,
        admission_calibration_y: Option<Vec<f64>>,
        has_coherence: bool,
        has_admission: bool,
    }

    fn resolve_sibling(base: &Path, child: &str) -> PathBuf {
        base.parent().unwrap_or_else(|| Path::new(".")).join(child)
    }

    fn fixed_shape(
        contract: &TensorContract,
        dtype: &str,
        expected: &[serde_json::Value],
    ) -> Result<()> {
        if contract.dtype != dtype || contract.shape != expected {
            bail!(
                "invalid contextual groupjoin tensor contract: dtype {} shape {:?}, expected {dtype} {:?}",
                contract.dtype,
                contract.shape,
                expected
            );
        }
        Ok(())
    }

    pub fn prototype_priority(document_id: &str) -> u64 {
        let digest = Sha256::digest(document_id.as_bytes());
        u64::from_be_bytes(
            digest[..8]
                .try_into()
                .expect("sha256 prefix is eight bytes"),
        )
    }

    impl ContextualGroupJoin {
        pub fn load(manifest_path: &str) -> Result<Self> {
            let manifest_path = Path::new(manifest_path);
            let manifest: Manifest = serde_json::from_str(
                &std::fs::read_to_string(manifest_path)
                    .with_context(|| manifest_path.display().to_string())?,
            )?;
            let old_contract = manifest.schema_version == 1
                && manifest.model_family == "contextual_groupjoin_dual_deepsets";
            let dual_head_contract = manifest.schema_version == 2
                && manifest.model_family == "contextual_groupjoin_match_coherence";
            let admission_head_contract = manifest.schema_version == 3
                && manifest.model_family == "contextual_groupjoin_admission_heads";
            if (!old_contract && !dual_head_contract && !admission_head_contract)
                || manifest.feature_contract != "lab2-contextual-groupjoin-v1"
            {
                bail!("unsupported contextual groupjoin manifest contract");
            }
            let dynamic = serde_json::Value::String("candidate_reports".to_string());
            fixed_shape(
                &manifest.inputs.report_tokens,
                "float32",
                &[dynamic.clone(), MEMBER_CAP.into(), TOKEN_DIMS.into()],
            )?;
            fixed_shape(
                &manifest.inputs.report_mask,
                "bool",
                &[dynamic.clone(), MEMBER_CAP.into()],
            )?;
            fixed_shape(
                &manifest.inputs.external_tokens,
                "float32",
                &[dynamic.clone(), EXTERNAL_CAP.into(), TOKEN_DIMS.into()],
            )?;
            fixed_shape(
                &manifest.inputs.external_mask,
                "bool",
                &[dynamic.clone(), EXTERNAL_CAP.into()],
            )?;
            fixed_shape(
                &manifest.inputs.engineered_features,
                "float32",
                &[dynamic.clone(), ENGINEERED_DIMS.into()],
            )?;
            let match_contract = manifest
                .outputs
                .join_logit
                .as_ref()
                .or(manifest.outputs.match_logit.as_ref())
                .context("contextual groupjoin manifest lacks a match output")?;
            fixed_shape(match_contract, "float32", std::slice::from_ref(&dynamic))?;
            if dual_head_contract || admission_head_contract {
                fixed_shape(
                    manifest
                        .outputs
                        .coherence_logit
                        .as_ref()
                        .context("dual-head contextual manifest lacks coherence output")?,
                    "float32",
                    std::slice::from_ref(&dynamic),
                )?;
            }
            if admission_head_contract {
                fixed_shape(
                    manifest
                        .outputs
                        .admission_logit
                        .as_ref()
                        .context("admission-head contextual manifest lacks admission output")?,
                    "float32",
                    std::slice::from_ref(&dynamic),
                )?;
            }
            fixed_shape(
                &manifest.outputs.pointer_logits,
                "float32",
                &[dynamic.clone(), MEMBER_CAP.into()],
            )?;
            fixed_shape(
                &manifest.outputs.pooled_representation,
                "float32",
                &[dynamic, POOL_DIMS.into()],
            )?;
            if manifest.inputs.engineered_features.names
                != FEATURE_NAMES
                    .iter()
                    .map(|value| value.to_string())
                    .collect::<Vec<_>>()
            {
                bail!("contextual groupjoin engineered feature order mismatch");
            }
            if manifest.calibration.r#type != "isotonic_linear_interpolation_clip"
                || !matches!(
                    manifest.calibration.input.as_str(),
                    "sigmoid(join_logit)" | "sigmoid(match_logit)"
                )
                || manifest.calibration.x.len() != manifest.calibration.y.len()
                || manifest.calibration.x.is_empty()
            {
                bail!("unsupported contextual groupjoin calibration contract");
            }
            if dual_head_contract || admission_head_contract {
                let coherence = manifest
                    .coherence_calibration
                    .as_ref()
                    .context("dual-head contextual manifest lacks coherence calibration")?;
                if coherence.r#type != "isotonic_linear_interpolation_clip"
                    || coherence.input != "sigmoid(coherence_logit)"
                    || coherence.x.len() != coherence.y.len()
                    || coherence.x.is_empty()
                {
                    bail!("unsupported contextual coherence calibration contract");
                }
            }
            if admission_head_contract {
                let admission = manifest
                    .admission_calibration
                    .as_ref()
                    .context("admission-head contextual manifest lacks admission calibration")?;
                if admission.r#type != "isotonic_linear_interpolation_clip"
                    || admission.input != "sigmoid(admission_logit)"
                    || admission.x.len() != admission.y.len()
                    || admission.x.is_empty()
                {
                    bail!("unsupported contextual admission calibration contract");
                }
            }
            let model_path = resolve_sibling(manifest_path, &manifest.artifact.path);
            let bytes =
                std::fs::read(&model_path).with_context(|| model_path.display().to_string())?;
            if bytes.len() as u64 != manifest.artifact.bytes {
                bail!("contextual groupjoin artifact size mismatch");
            }
            let digest = format!("{:x}", Sha256::digest(&bytes));
            if digest != manifest.artifact.sha256 {
                bail!("contextual groupjoin artifact digest mismatch");
            }
            let model = tract_onnx::onnx()
                .model_for_path(&model_path)?
                .into_optimized()?
                .into_runnable()?;
            Ok(Self {
                model,
                feature_names: manifest.inputs.engineered_features.names,
                calibration_x: manifest.calibration.x,
                calibration_y: manifest.calibration.y,
                coherence_calibration_x: manifest
                    .coherence_calibration
                    .as_ref()
                    .map(|value| value.x.clone()),
                coherence_calibration_y: manifest
                    .coherence_calibration
                    .as_ref()
                    .map(|value| value.y.clone()),
                admission_calibration_x: manifest
                    .admission_calibration
                    .as_ref()
                    .map(|value| value.x.clone()),
                admission_calibration_y: manifest
                    .admission_calibration
                    .as_ref()
                    .map(|value| value.y.clone()),
                has_coherence: dual_head_contract || admission_head_contract,
                has_admission: admission_head_contract,
            })
        }

        pub fn infer(
            &self,
            report_tokens: &[&[Vec<f32>]],
            external_tokens: &[&[Vec<f32>]],
            engineered: &[&HashMap<&'static str, f64>],
        ) -> Result<Vec<ContextualGroupJoinOutput>> {
            let batch = report_tokens.len();
            if batch == 0 || external_tokens.len() != batch || engineered.len() != batch {
                bail!("contextual groupjoin needs aligned non-empty candidate batches");
            }
            let mut report_values = vec![0.0f32; batch * MEMBER_CAP * TOKEN_DIMS];
            let mut report_masks = vec![false; batch * MEMBER_CAP];
            let mut external_values = vec![0.0f32; batch * EXTERNAL_CAP * TOKEN_DIMS];
            let mut external_masks = vec![false; batch * EXTERNAL_CAP];
            let mut engineered_values = Vec::with_capacity(batch * ENGINEERED_DIMS);
            for candidate in 0..batch {
                let report = report_tokens[candidate];
                let external = external_tokens[candidate];
                if report.is_empty() || report.len() > MEMBER_CAP || external.len() > EXTERNAL_CAP {
                    bail!("candidate {candidate} violates contextual set caps");
                }
                for (position, token) in report.iter().enumerate() {
                    if token.len() != TOKEN_DIMS || token.iter().any(|value| !value.is_finite()) {
                        bail!(
                            "candidate {candidate} report token {position} violates the contract"
                        );
                    }
                    let start = (candidate * MEMBER_CAP + position) * TOKEN_DIMS;
                    report_values[start..start + TOKEN_DIMS].copy_from_slice(token);
                    report_masks[candidate * MEMBER_CAP + position] = true;
                }
                for (position, token) in external.iter().enumerate() {
                    if token.len() != TOKEN_DIMS || token.iter().any(|value| !value.is_finite()) {
                        bail!(
                            "candidate {candidate} external token {position} violates the contract"
                        );
                    }
                    let start = (candidate * EXTERNAL_CAP + position) * TOKEN_DIMS;
                    external_values[start..start + TOKEN_DIMS].copy_from_slice(token);
                    external_masks[candidate * EXTERNAL_CAP + position] = true;
                }
                for name in &self.feature_names {
                    let value = *engineered[candidate]
                        .get(name.as_str())
                        .unwrap_or(&f64::NAN);
                    if !value.is_finite() {
                        bail!("candidate {candidate} has non-finite engineered feature {name}");
                    }
                    engineered_values.push(value as f32);
                }
            }
            let report: Tensor = tract_ndarray::Array3::from_shape_vec(
                (batch, MEMBER_CAP, TOKEN_DIMS),
                report_values,
            )?
            .into();
            let report_mask: Tensor =
                tract_ndarray::Array2::from_shape_vec((batch, MEMBER_CAP), report_masks)?.into();
            let external: Tensor = tract_ndarray::Array3::from_shape_vec(
                (batch, EXTERNAL_CAP, TOKEN_DIMS),
                external_values,
            )?
            .into();
            let external_mask: Tensor =
                tract_ndarray::Array2::from_shape_vec((batch, EXTERNAL_CAP), external_masks)?
                    .into();
            let engineered: Tensor =
                tract_ndarray::Array2::from_shape_vec((batch, ENGINEERED_DIMS), engineered_values)?
                    .into();
            let outputs = self.model.run(tvec![
                report.into(),
                report_mask.into(),
                external.into(),
                external_mask.into(),
                engineered.into()
            ])?;
            let expected_outputs = if self.has_admission {
                5
            } else if self.has_coherence {
                4
            } else {
                3
            };
            if outputs.len() != expected_outputs {
                bail!("contextual groupjoin returned {} outputs", outputs.len());
            }
            let logits = outputs[0].to_array_view::<f32>()?;
            let coherence_logits = if self.has_coherence {
                Some(outputs[1].to_array_view::<f32>()?)
            } else {
                None
            };
            let admission_logits = if self.has_admission {
                Some(outputs[2].to_array_view::<f32>()?)
            } else {
                None
            };
            let pointer_index = if self.has_admission {
                3
            } else if self.has_coherence {
                2
            } else {
                1
            };
            let pool_index = pointer_index + 1;
            let pointers = outputs[pointer_index].to_array_view::<f32>()?;
            let pools = outputs[pool_index].to_array_view::<f32>()?;
            if logits.len() != batch
                || coherence_logits
                    .as_ref()
                    .is_some_and(|values| values.len() != batch)
                || admission_logits
                    .as_ref()
                    .is_some_and(|values| values.len() != batch)
                || pointers.len() != batch * MEMBER_CAP
                || pools.len() != batch * POOL_DIMS
            {
                bail!("contextual groupjoin returned incompatible output shapes");
            }
            let pointers = pointers.iter().copied().collect::<Vec<_>>();
            let pools = pools.iter().copied().collect::<Vec<_>>();
            logits
                .iter()
                .enumerate()
                .map(|(candidate, logit)| {
                    let raw = 1.0 / (1.0 + (-(*logit as f64)).exp());
                    let calibrated =
                        crate::model::interp_clip(raw, &self.calibration_x, &self.calibration_y);
                    let coherence_raw = coherence_logits
                        .as_ref()
                        .map(|values| 1.0 / (1.0 + (-(values[candidate] as f64)).exp()));
                    let coherence_calibrated = coherence_raw.map(|value| {
                        crate::model::interp_clip(
                            value,
                            self.coherence_calibration_x
                                .as_ref()
                                .expect("coherence calibration x is present"),
                            self.coherence_calibration_y
                                .as_ref()
                                .expect("coherence calibration y is present"),
                        )
                    });
                    let admission_raw = admission_logits
                        .as_ref()
                        .map(|values| 1.0 / (1.0 + (-(values[candidate] as f64)).exp()));
                    let admission_calibrated = admission_raw.map(|value| {
                        crate::model::interp_clip(
                            value,
                            self.admission_calibration_x
                                .as_ref()
                                .expect("admission calibration x is present"),
                            self.admission_calibration_y
                                .as_ref()
                                .expect("admission calibration y is present"),
                        )
                    });
                    let pooled = pools[candidate * POOL_DIMS..(candidate + 1) * POOL_DIMS]
                        .iter()
                        .map(|value| *value as f64)
                        .collect::<Vec<_>>();
                    let pointer = pointers[candidate * MEMBER_CAP..(candidate + 1) * MEMBER_CAP]
                        .iter()
                        .map(|value| *value as f64)
                        .collect::<Vec<_>>();
                    if !raw.is_finite()
                        || !calibrated.is_finite()
                        || coherence_raw.is_some_and(|value| !value.is_finite())
                        || coherence_calibrated.is_some_and(|value| !value.is_finite())
                        || admission_raw.is_some_and(|value| !value.is_finite())
                        || admission_calibrated.is_some_and(|value| !value.is_finite())
                        || pointer.iter().any(|value| !value.is_finite())
                        || pooled.iter().any(|value| !value.is_finite())
                    {
                        bail!("contextual groupjoin returned a non-finite value");
                    }
                    Ok(ContextualGroupJoinOutput {
                        raw,
                        calibrated,
                        coherence_raw,
                        coherence_calibrated,
                        admission_raw,
                        admission_calibrated,
                        pointer,
                        pooled,
                    })
                })
                .collect()
        }
    }
}

#[cfg(feature = "neural-onnx")]
pub use enabled::{prototype_priority, ContextualGroupJoin};

#[cfg(not(feature = "neural-onnx"))]
pub struct ContextualGroupJoin;

#[cfg(not(feature = "neural-onnx"))]
pub fn prototype_priority(_document_id: &str) -> u64 {
    0
}

#[cfg(not(feature = "neural-onnx"))]
impl ContextualGroupJoin {
    pub fn load(_manifest_path: &str) -> Result<Self> {
        bail!("contextual groupjoin requested, but engine was built without --features neural-onnx")
    }

    pub fn infer(
        &self,
        _report_tokens: &[&[Vec<f32>]],
        _external_tokens: &[&[Vec<f32>]],
        _engineered: &[&HashMap<&'static str, f64>],
    ) -> Result<Vec<ContextualGroupJoinOutput>> {
        bail!("contextual groupjoin unavailable")
    }
}
