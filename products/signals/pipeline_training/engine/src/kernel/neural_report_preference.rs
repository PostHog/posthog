//! Full-vector challenger-versus-incumbent report preference execution.

use anyhow::{bail, Result};
use std::collections::HashMap;

use crate::neural_groupjoin::{
    EMBEDDING_DIMS, ENGINEERED_DIMS, MEMBER_CAP, RELATION_DIMS, TOKEN_DIMS,
};

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

    const INPUT_NAMES: [&str; 11] = [
        "query_embeddings",
        "challenger_relations",
        "challenger_embeddings",
        "challenger_mask",
        "challenger_engineered",
        "challenger_admission_raw",
        "incumbent_relations",
        "incumbent_embeddings",
        "incumbent_mask",
        "incumbent_engineered",
        "incumbent_admission_raw",
    ];

    #[derive(Deserialize)]
    struct Artifact {
        path: String,
        bytes: u64,
        sha256: String,
    }

    #[derive(Deserialize)]
    struct OutputContract {
        name: String,
        #[serde(default)]
        probability: String,
    }

    #[derive(Deserialize)]
    struct DualOutputContract {
        benefit: OutputContract,
        risk: OutputContract,
    }

    #[derive(Deserialize)]
    struct Manifest {
        schema_version: u32,
        model_family: String,
        feature_contract: String,
        artifact: Artifact,
        member_cap: usize,
        relation_dims: usize,
        embedding_dims: usize,
        engineered_features: Vec<String>,
        inputs: Vec<String>,
        #[serde(default)]
        output: Option<OutputContract>,
        #[serde(default)]
        outputs: Option<DualOutputContract>,
    }

    pub struct ReportPreferenceOutput {
        pub benefit_probability: f64,
        pub risk_score: Option<f64>,
    }

    pub struct NeuralReportPreference {
        model: TypedRunnableModel<TypedModel>,
        feature_names: Vec<String>,
        has_risk: bool,
    }

    struct SideTensors {
        relations: Tensor,
        embeddings: Tensor,
        mask: Tensor,
        engineered: Tensor,
        admission: Tensor,
    }

    fn resolve_sibling(base: &Path, child: &str) -> PathBuf {
        base.parent().unwrap_or_else(|| Path::new(".")).join(child)
    }

    impl NeuralReportPreference {
        pub fn load(manifest_path: &str) -> Result<Self> {
            let manifest_path = Path::new(manifest_path);
            let manifest: Manifest = serde_json::from_str(
                &std::fs::read_to_string(manifest_path)
                    .with_context(|| manifest_path.display().to_string())?,
            )?;
            let single_contract = manifest.model_family
                == "trajectory_report_preference_full_vector"
                && manifest.feature_contract == "lab2-candidate-report-preference-full-vector-v1"
                && manifest.output.as_ref().is_some_and(|output| {
                    output.name == "preference_logit"
                        && output.probability == "sigmoid(preference_logit)"
                })
                && manifest.outputs.is_none();
            let dual_contract = manifest.model_family
                == "trajectory_report_preference_full_vector_dual"
                && manifest.feature_contract
                    == "lab2-candidate-report-preference-full-vector-dual-v1"
                && manifest.output.is_none()
                && manifest.outputs.as_ref().is_some_and(|outputs| {
                    outputs.benefit.name == "benefit_logit"
                        && outputs.benefit.probability == "sigmoid(benefit_logit)"
                        && outputs.risk.name == "risk_score"
                });
            if manifest.schema_version != 1
                || (!single_contract && !dual_contract)
                || manifest.member_cap != MEMBER_CAP
                || manifest.relation_dims != RELATION_DIMS
                || manifest.embedding_dims != EMBEDDING_DIMS
                || manifest.inputs != INPUT_NAMES
            {
                bail!("unsupported neural report-preference manifest contract");
            }
            let expected_features = FEATURE_NAMES
                .iter()
                .map(|value| value.to_string())
                .collect::<Vec<_>>();
            if manifest.engineered_features != expected_features {
                bail!("neural report-preference engineered feature order mismatch");
            }
            let model_path = resolve_sibling(manifest_path, &manifest.artifact.path);
            let bytes =
                std::fs::read(&model_path).with_context(|| model_path.display().to_string())?;
            if bytes.len() as u64 != manifest.artifact.bytes {
                bail!("neural report-preference artifact size mismatch");
            }
            if format!("{:x}", Sha256::digest(&bytes)) != manifest.artifact.sha256 {
                bail!("neural report-preference artifact digest mismatch");
            }
            let model = tract_onnx::onnx()
                .model_for_path(&model_path)?
                .into_optimized()?
                .into_runnable()?;
            Ok(Self {
                model,
                feature_names: expected_features,
                has_risk: dual_contract,
            })
        }

        pub fn has_risk(&self) -> bool {
            self.has_risk
        }

        fn side_tensors(
            &self,
            token_batches: &[&[Vec<f32>]],
            embedding_batches: &[&[Vec<f32>]],
            engineered: &[&HashMap<&'static str, f64>],
            admission: &[f64],
        ) -> Result<SideTensors> {
            let batch = token_batches.len();
            if embedding_batches.len() != batch
                || engineered.len() != batch
                || admission.len() != batch
            {
                bail!("neural report preference needs aligned side inputs");
            }
            let mut relation_values = vec![0.0f32; batch * MEMBER_CAP * RELATION_DIMS];
            let mut embedding_values = vec![0.0f32; batch * MEMBER_CAP * EMBEDDING_DIMS];
            let mut mask_values = vec![false; batch * MEMBER_CAP];
            let mut engineered_values = Vec::with_capacity(batch * ENGINEERED_DIMS);
            for (candidate, tokens) in token_batches.iter().enumerate() {
                if tokens.is_empty()
                    || tokens.len() > MEMBER_CAP
                    || embedding_batches[candidate].len() != tokens.len()
                {
                    bail!("candidate {candidate} violates the report-member contract");
                }
                for (member, (token, embedding)) in tokens
                    .iter()
                    .zip(embedding_batches[candidate].iter())
                    .enumerate()
                {
                    if token.len() != TOKEN_DIMS
                        || embedding.len() != EMBEDDING_DIMS
                        || token.iter().any(|value| !value.is_finite())
                        || embedding.iter().any(|value| !value.is_finite())
                    {
                        bail!("candidate {candidate} member {member} violates the full-vector contract");
                    }
                    let relation_start = (candidate * MEMBER_CAP + member) * RELATION_DIMS;
                    relation_values[relation_start..relation_start + RELATION_DIMS]
                        .copy_from_slice(&token[..RELATION_DIMS]);
                    let embedding_start = (candidate * MEMBER_CAP + member) * EMBEDDING_DIMS;
                    embedding_values[embedding_start..embedding_start + EMBEDDING_DIMS]
                        .copy_from_slice(embedding);
                    mask_values[candidate * MEMBER_CAP + member] = true;
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
                if !admission[candidate].is_finite() {
                    bail!("candidate {candidate} has non-finite admission score");
                }
            }
            Ok(SideTensors {
                relations: tract_ndarray::Array3::from_shape_vec(
                    (batch, MEMBER_CAP, RELATION_DIMS),
                    relation_values,
                )?
                .into(),
                embeddings: tract_ndarray::Array3::from_shape_vec(
                    (batch, MEMBER_CAP, EMBEDDING_DIMS),
                    embedding_values,
                )?
                .into(),
                mask: tract_ndarray::Array2::from_shape_vec((batch, MEMBER_CAP), mask_values)?
                    .into(),
                engineered: tract_ndarray::Array2::from_shape_vec(
                    (batch, ENGINEERED_DIMS),
                    engineered_values,
                )?
                .into(),
                admission: tract_ndarray::Array1::from_vec(
                    admission.iter().map(|value| *value as f32).collect(),
                )
                .into(),
            })
        }

        #[allow(clippy::too_many_arguments)]
        pub fn infer(
            &self,
            query_embedding: &[f32],
            challenger_tokens: &[&[Vec<f32>]],
            challenger_embeddings: &[&[Vec<f32>]],
            challenger_engineered: &[&HashMap<&'static str, f64>],
            challenger_admission: &[f64],
            incumbent_tokens: &[Vec<f32>],
            incumbent_embeddings: &[Vec<f32>],
            incumbent_engineered: &HashMap<&'static str, f64>,
            incumbent_admission: f64,
        ) -> Result<Vec<ReportPreferenceOutput>> {
            let batch = challenger_tokens.len();
            if batch == 0 || query_embedding.len() != EMBEDDING_DIMS {
                bail!("neural report preference needs a non-empty batch and one complete query embedding");
            }
            let query_values = query_embedding.repeat(batch);
            let challenger = self.side_tensors(
                challenger_tokens,
                challenger_embeddings,
                challenger_engineered,
                challenger_admission,
            )?;
            let incumbent_token_batches = vec![incumbent_tokens; batch];
            let incumbent_embedding_batches = vec![incumbent_embeddings; batch];
            let incumbent_engineered_batches = vec![incumbent_engineered; batch];
            let incumbent_admissions = vec![incumbent_admission; batch];
            let incumbent = self.side_tensors(
                &incumbent_token_batches,
                &incumbent_embedding_batches,
                &incumbent_engineered_batches,
                &incumbent_admissions,
            )?;
            let query: Tensor =
                tract_ndarray::Array2::from_shape_vec((batch, EMBEDDING_DIMS), query_values)?
                    .into();
            let outputs = self.model.run(tvec![
                query.into(),
                challenger.relations.into(),
                challenger.embeddings.into(),
                challenger.mask.into(),
                challenger.engineered.into(),
                challenger.admission.into(),
                incumbent.relations.into(),
                incumbent.embeddings.into(),
                incumbent.mask.into(),
                incumbent.engineered.into(),
                incumbent.admission.into(),
            ])?;
            let expected_outputs = if self.has_risk { 2 } else { 1 };
            if outputs.len() != expected_outputs {
                bail!(
                    "neural report preference returned {} outputs",
                    outputs.len()
                );
            }
            let benefit_logits = outputs[0].to_array_view::<f32>()?;
            if benefit_logits.len() != batch {
                bail!("neural report preference returned an incompatible output shape");
            }
            let risk_scores = if self.has_risk {
                let values = outputs[1].to_array_view::<f32>()?;
                if values.len() != batch {
                    bail!("neural report preference returned an incompatible risk shape");
                }
                Some(values.iter().map(|value| *value as f64).collect::<Vec<_>>())
            } else {
                None
            };
            benefit_logits
                .iter()
                .enumerate()
                .map(|(index, logit)| {
                    let probability = 1.0 / (1.0 + (-(*logit as f64)).exp());
                    let risk_score = risk_scores.as_ref().map(|values| values[index]);
                    if !probability.is_finite() || risk_score.is_some_and(|risk| !risk.is_finite())
                    {
                        bail!("neural report preference returned a non-finite value");
                    }
                    Ok(ReportPreferenceOutput {
                        benefit_probability: probability,
                        risk_score,
                    })
                })
                .collect()
        }
    }
}

#[cfg(feature = "neural-onnx")]
pub use enabled::NeuralReportPreference;

#[cfg(not(feature = "neural-onnx"))]
pub struct NeuralReportPreference;

#[cfg(not(feature = "neural-onnx"))]
pub struct ReportPreferenceOutput {
    pub benefit_probability: f64,
    pub risk_score: Option<f64>,
}

#[cfg(not(feature = "neural-onnx"))]
impl NeuralReportPreference {
    pub fn load(_manifest_path: &str) -> Result<Self> {
        bail!("neural report preference requested, but engine was built without --features neural-onnx")
    }

    pub fn has_risk(&self) -> bool {
        false
    }

    #[allow(clippy::too_many_arguments)]
    pub fn infer(
        &self,
        _query_embedding: &[f32],
        _challenger_tokens: &[&[Vec<f32>]],
        _challenger_embeddings: &[&[Vec<f32>]],
        _challenger_engineered: &[&HashMap<&'static str, f64>],
        _challenger_admission: &[f64],
        _incumbent_tokens: &[Vec<f32>],
        _incumbent_embeddings: &[Vec<f32>],
        _incumbent_engineered: &HashMap<&'static str, f64>,
        _incumbent_admission: f64,
    ) -> Result<Vec<ReportPreferenceOutput>> {
        bail!("neural report preference unavailable")
    }
}
