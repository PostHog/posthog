//! Exact-artifact ONNX execution for the source-pinned direct GroupJoin encoder.

use anyhow::{bail, Result};
use std::collections::HashMap;

pub const MEMBER_CAP: usize = 40;
pub const TOKEN_DIMS: usize = 76;
pub const RELATION_DIMS: usize = 12;
pub const EMBEDDING_DIMS: usize = 1536;
pub const ENGINEERED_DIMS: usize = 26;
pub const POOL_DIMS: usize = 32;

pub struct NeuralGroupJoinOutput {
    pub raw: f64,
    pub calibrated: f64,
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
        #[serde(default)]
        report_tokens: Option<TensorContract>,
        #[serde(default)]
        relations: Option<TensorContract>,
        #[serde(default)]
        query_embeddings: Option<TensorContract>,
        #[serde(default)]
        member_embeddings: Option<TensorContract>,
        member_mask: TensorContract,
        engineered_features: TensorContract,
    }

    #[derive(Deserialize)]
    struct OutputContract {
        join_logit: TensorContract,
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
        #[serde(default)]
        architecture: Option<String>,
        artifact: Artifact,
        inputs: InputContract,
        outputs: OutputContract,
        calibration: Calibration,
    }

    pub struct NeuralGroupJoin {
        model: TypedRunnableModel<TypedModel>,
        feature_names: Vec<String>,
        calibration_x: Vec<f64>,
        calibration_y: Vec<f64>,
        full_embedding: bool,
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
                "invalid neural groupjoin tensor contract: dtype {} shape {:?}, expected {dtype} {:?}",
                contract.dtype,
                contract.shape,
                expected
            );
        }
        Ok(())
    }

    impl NeuralGroupJoin {
        pub fn load(manifest_path: &str) -> Result<Self> {
            let manifest_path = Path::new(manifest_path);
            let manifest: Manifest = serde_json::from_str(
                &std::fs::read_to_string(manifest_path)
                    .with_context(|| manifest_path.display().to_string())?,
            )?;
            if manifest.schema_version != 1 {
                bail!("unsupported neural groupjoin manifest contract");
            }
            let full_embedding = match (
                manifest.model_family.as_str(),
                manifest.feature_contract.as_str(),
            ) {
                ("groupjoin_direct_deepsets", "lab2-groupjoin-v1") => false,
                ("groupjoin_full_embedding", "lab2-groupjoin-full-embedding-v1") => {
                    if !matches!(
                        manifest.architecture.as_deref(),
                        Some("full-member" | "full-relational" | "full-interaction")
                    ) {
                        bail!("unsupported full-embedding groupjoin architecture");
                    }
                    true
                }
                _ => bail!("unsupported neural groupjoin manifest contract"),
            };
            let dynamic = serde_json::Value::String("candidate_reports".to_string());
            if full_embedding {
                fixed_shape(
                    manifest
                        .inputs
                        .relations
                        .as_ref()
                        .context("full-embedding manifest is missing relations")?,
                    "float32",
                    &[dynamic.clone(), MEMBER_CAP.into(), RELATION_DIMS.into()],
                )?;
                fixed_shape(
                    manifest
                        .inputs
                        .query_embeddings
                        .as_ref()
                        .context("full-embedding manifest is missing query embeddings")?,
                    "float32",
                    &[dynamic.clone(), EMBEDDING_DIMS.into()],
                )?;
                fixed_shape(
                    manifest
                        .inputs
                        .member_embeddings
                        .as_ref()
                        .context("full-embedding manifest is missing member embeddings")?,
                    "float32",
                    &[dynamic.clone(), MEMBER_CAP.into(), EMBEDDING_DIMS.into()],
                )?;
            } else {
                fixed_shape(
                    manifest
                        .inputs
                        .report_tokens
                        .as_ref()
                        .context("groupjoin manifest is missing report tokens")?,
                    "float32",
                    &[dynamic.clone(), MEMBER_CAP.into(), TOKEN_DIMS.into()],
                )?;
            }
            fixed_shape(
                &manifest.inputs.member_mask,
                "bool",
                &[dynamic.clone(), MEMBER_CAP.into()],
            )?;
            fixed_shape(
                &manifest.inputs.engineered_features,
                "float32",
                &[dynamic.clone(), ENGINEERED_DIMS.into()],
            )?;
            fixed_shape(
                &manifest.outputs.join_logit,
                "float32",
                std::slice::from_ref(&dynamic),
            )?;
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
                bail!("neural groupjoin engineered feature order mismatch");
            }
            if manifest.calibration.r#type != "isotonic_linear_interpolation_clip"
                || manifest.calibration.input != "sigmoid(join_logit)"
                || manifest.calibration.x.len() != manifest.calibration.y.len()
                || manifest.calibration.x.is_empty()
            {
                bail!("unsupported neural groupjoin calibration contract");
            }
            let model_path = resolve_sibling(manifest_path, &manifest.artifact.path);
            let bytes =
                std::fs::read(&model_path).with_context(|| model_path.display().to_string())?;
            if bytes.len() as u64 != manifest.artifact.bytes {
                bail!("neural groupjoin artifact size mismatch");
            }
            let digest = format!("{:x}", Sha256::digest(&bytes));
            if digest != manifest.artifact.sha256 {
                bail!("neural groupjoin artifact digest mismatch");
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
                full_embedding,
            })
        }

        pub fn infer(
            &self,
            report_tokens: &[&[Vec<f32>]],
            query_embeddings: &[&[f32]],
            member_embeddings: &[&[Vec<f32>]],
            engineered: &[&HashMap<&'static str, f64>],
        ) -> Result<Vec<NeuralGroupJoinOutput>> {
            let batch = report_tokens.len();
            if batch == 0
                || query_embeddings.len() != batch
                || member_embeddings.len() != batch
                || engineered.len() != batch
            {
                bail!("neural groupjoin needs an aligned non-empty candidate batch");
            }
            let mut token_values = vec![0.0f32; batch * MEMBER_CAP * TOKEN_DIMS];
            let mut relation_values = vec![0.0f32; batch * MEMBER_CAP * RELATION_DIMS];
            let mut query_values = Vec::with_capacity(batch * EMBEDDING_DIMS);
            let mut member_values = vec![0.0f32; batch * MEMBER_CAP * EMBEDDING_DIMS];
            let mut mask_values = vec![false; batch * MEMBER_CAP];
            let mut engineered_values = Vec::with_capacity(batch * ENGINEERED_DIMS);
            for (candidate, tokens) in report_tokens.iter().enumerate() {
                if tokens.is_empty() || tokens.len() > MEMBER_CAP {
                    bail!(
                        "candidate {candidate} has invalid member count {}",
                        tokens.len()
                    );
                }
                for (member, token) in tokens.iter().enumerate() {
                    if token.len() != TOKEN_DIMS || token.iter().any(|value| !value.is_finite()) {
                        bail!("candidate {candidate} member {member} violates the token contract");
                    }
                    let start = (candidate * MEMBER_CAP + member) * TOKEN_DIMS;
                    token_values[start..start + TOKEN_DIMS].copy_from_slice(token);
                    let relation_start = (candidate * MEMBER_CAP + member) * RELATION_DIMS;
                    relation_values[relation_start..relation_start + RELATION_DIMS]
                        .copy_from_slice(&token[..RELATION_DIMS]);
                    mask_values[candidate * MEMBER_CAP + member] = true;
                }
                if member_embeddings[candidate].len() != tokens.len() {
                    bail!("candidate {candidate} has misaligned member embeddings");
                }
                for (member, embedding) in member_embeddings[candidate].iter().enumerate() {
                    if embedding.len() != EMBEDDING_DIMS
                        || embedding.iter().any(|value| !value.is_finite())
                    {
                        bail!(
                            "candidate {candidate} member {member} violates the embedding contract"
                        );
                    }
                    let start = (candidate * MEMBER_CAP + member) * EMBEDDING_DIMS;
                    member_values[start..start + EMBEDDING_DIMS].copy_from_slice(embedding);
                }
                let query = query_embeddings[candidate];
                if query.len() != EMBEDDING_DIMS || query.iter().any(|value| !value.is_finite()) {
                    bail!("candidate {candidate} query violates the embedding contract");
                }
                query_values.extend_from_slice(query);
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
            let mask: Tensor =
                tract_ndarray::Array2::from_shape_vec((batch, MEMBER_CAP), mask_values)?.into();
            let engineered: Tensor =
                tract_ndarray::Array2::from_shape_vec((batch, ENGINEERED_DIMS), engineered_values)?
                    .into();
            let outputs = if self.full_embedding {
                let relations: Tensor = tract_ndarray::Array3::from_shape_vec(
                    (batch, MEMBER_CAP, RELATION_DIMS),
                    relation_values,
                )?
                .into();
                let query_embeddings: Tensor =
                    tract_ndarray::Array2::from_shape_vec((batch, EMBEDDING_DIMS), query_values)?
                        .into();
                let member_embeddings: Tensor = tract_ndarray::Array3::from_shape_vec(
                    (batch, MEMBER_CAP, EMBEDDING_DIMS),
                    member_values,
                )?
                .into();
                self.model.run(tvec![
                    relations.into(),
                    query_embeddings.into(),
                    member_embeddings.into(),
                    mask.into(),
                    engineered.into()
                ])?
            } else {
                let tokens: Tensor = tract_ndarray::Array3::from_shape_vec(
                    (batch, MEMBER_CAP, TOKEN_DIMS),
                    token_values,
                )?
                .into();
                self.model
                    .run(tvec![tokens.into(), mask.into(), engineered.into()])?
            };
            if outputs.len() != 3 {
                bail!("neural groupjoin returned {} outputs", outputs.len());
            }
            let logits = outputs[0].to_array_view::<f32>()?;
            let pools = outputs[2].to_array_view::<f32>()?;
            if logits.len() != batch || pools.len() != batch * POOL_DIMS {
                bail!("neural groupjoin returned incompatible output shapes");
            }
            let pools = pools.iter().copied().collect::<Vec<_>>();
            logits
                .iter()
                .enumerate()
                .map(|(candidate, logit)| {
                    let raw = 1.0 / (1.0 + (-(*logit as f64)).exp());
                    let calibrated =
                        crate::model::interp_clip(raw, &self.calibration_x, &self.calibration_y);
                    let pooled = pools[candidate * POOL_DIMS..(candidate + 1) * POOL_DIMS]
                        .iter()
                        .map(|value| *value as f64)
                        .collect::<Vec<_>>();
                    if !raw.is_finite()
                        || !calibrated.is_finite()
                        || pooled.iter().any(|value| !value.is_finite())
                    {
                        bail!("neural groupjoin returned a non-finite value");
                    }
                    Ok(NeuralGroupJoinOutput {
                        raw,
                        calibrated,
                        pooled,
                    })
                })
                .collect()
        }
    }
}

#[cfg(feature = "neural-onnx")]
pub use enabled::NeuralGroupJoin;

#[cfg(not(feature = "neural-onnx"))]
pub struct NeuralGroupJoin;

#[cfg(not(feature = "neural-onnx"))]
impl NeuralGroupJoin {
    pub fn load(_manifest_path: &str) -> Result<Self> {
        bail!("neural groupjoin requested, but engine was built without --features neural-onnx")
    }

    pub fn infer(
        &self,
        _report_tokens: &[&[Vec<f32>]],
        _query_embeddings: &[&[f32]],
        _member_embeddings: &[&[Vec<f32>]],
        _engineered: &[&HashMap<&'static str, f64>],
    ) -> Result<Vec<NeuralGroupJoinOutput>> {
        bail!("neural groupjoin unavailable")
    }
}
