//! Engine run config. The engine executes one ACTIVITY of a perf-DB run: the config names the
//! run_id + stage (+ member/params for sweep members); candidate/reference runs themselves are
//! created by the Python orchestration with the mandatory description/model fields. The engine
//! refuses a config whose run_id does not exist in the perf DB.

use serde::Deserialize;

#[derive(Deserialize, Clone)]
pub struct Config {
    // perf-DB identity (required for `engine run`; the `featurize` subcommand doesn't touch the DB)
    #[serde(default)]
    pub run_id: String,
    #[serde(default)]
    pub stage: String, // sweep | test | eval
    #[serde(default)]
    pub member: Option<String>,
    #[serde(default)]
    pub sweep_id: Option<String>,
    #[serde(default = "default_perf_db")]
    pub perf_db: String,

    // corpus (materialized by engine/prepare_corpus.py): dir with signals.jsonl + embeddings.npy
    // (+ optional sigs.jsonl concern signatures for the model-stack featurizers)
    pub corpus_dir: String,
    #[serde(default)]
    pub shard: Option<String>, // recorded on metrics rows

    // outputs (required for `engine run`)
    #[serde(default)]
    pub out_dir: String,

    // pipeline variation under test
    #[serde(default)]
    pub mode: Mode,
    #[serde(default)]
    pub models: Option<String>, // models.json for model-stack modes

    // LLM disk cache — ALWAYS ON (Oliver, 2026-07-09): identical (model, prompt) never makes a
    // second API call. Speed + determinism: a cached re-run of an LLM mode replays byte-identical
    // responses. Set to a fresh dir to deliberately re-sample.
    #[serde(default = "default_llm_cache")]
    pub llm_cache_dir: String,
    /// Warm the caches for all query-gen calls + query embeddings in a parallel pass before
    /// the sequential loop (decision-independent, byte-identical prompts — see
    /// llm_modes::prefetch). Turns serial LLM latency into ~parallel latency.
    #[serde(default = "default_true")]
    pub prefetch_llm: bool,

    // Semantics (Oliver, 2026-07-09): `sequential` is the default and canonical regime — signals
    // process strictly in arrival order, each seeing ALL prior state; no same-batch races, no
    // CH-lag hiding. Search within a decision parallelizes freely (read-only) so this costs no
    // meaningful speed. `prod_batch` replicates prod's concurrency artifacts (BATCH_SIZE, pre-batch
    // retrieval visibility, dependency races) for fidelity studies only.
    #[serde(default)]
    pub semantics: Semantics,
    #[serde(default = "default_batch")]
    pub batch_size: usize, // prod_batch only

    // mode parameters
    #[serde(default = "default_threshold")]
    pub match_distance_threshold: f64, // ET auto-merge distance (prod 0.019)
    #[serde(default = "default_nn_limit")]
    pub nn_limit: usize, // k nearest neighbors considered; >1 = modal-report vote among under-threshold hits
    #[serde(default)]
    pub fast_lane_threshold: Option<f64>,
    /// fast-lane eligible source products (pipeline.py fast_lane_sources);
    /// empty vec = all sources (Python's None)
    #[serde(default = "default_fast_lane_sources")]
    pub fast_lane_sources: Vec<String>,
    #[serde(default = "default_band")]
    pub hybrid_llm_band: (f64, f64),
    #[serde(default = "default_search")]
    pub search_limit: usize,
    /// Anthropic model for the LLM matching modes (pipeline.py MATCHING_MODEL)
    #[serde(default = "default_matching_model")]
    pub matching_model: String,
    /// smoke runs: process only the first N signals of the corpus
    #[serde(default)]
    pub limit: Option<usize>,

    // === classifier (model-stack) mode — names/defaults carried from the old replayer ===
    pub classifier_tau: Option<f64>,
    /// join test on the RAW pair score instead of calibrated p — isotonic
    /// plateaus collapse raw .88-.95 onto one calibrated value just below
    /// tau .8, hiding real separation (the two-member-tie FN bucket)
    pub classifier_raw_tau: Option<f64>,
    /// Require the best candidate report to beat the second-best report by this
    /// amount on the active calibrated or raw pair-score scale. Single-report
    /// candidate sets pass automatically.
    pub classifier_margin_tau: Option<f64>,
    pub join_model_tau: Option<f64>,
    pub join_veto_q: Option<f64>,
    pub join_rescue_q: Option<f64>,
    #[serde(default)]
    pub use_join_model: bool,
    #[serde(default)]
    pub use_concern: bool,
    pub concern_merge_gamma: Option<f64>,
    pub concern_split_sigma: Option<f64>,
    #[serde(default = "d_budget")]
    pub concern_split_budget: usize,
    #[serde(default = "d_trigger")]
    pub bridge_trigger_tau: f64,
    #[serde(default = "d_minsize")]
    pub split_min_size: usize,
    /// retrieval window in days (prod: 30). Full-universe judged recall is
    /// window-capped; corpus streams compress time so it rarely binds there.
    #[serde(default = "d_window")]
    pub search_window_days: f64,
    /// per-projection candidate cap applied at batch augmentation (prod behavior
    /// hard-codes 10, which silently re-capped every K>10 experiment)
    #[serde(default = "d_augment")]
    pub augment_limit: usize,
    /// identifier retrieval lane: surface candidates sharing a rare extracted
    /// identifier with the query, regardless of embedding distance (the
    /// cross-product misses live here). 0 = off.
    #[serde(default)]
    pub id_lane_limit: usize,
    /// gj experiment: replace the pairwise argmax + tau with the ONE-MODEL
    /// groupwise matcher (models.json 'groupjoin' GBDT over 26 group features)
    #[serde(default)]
    pub use_groupjoin: bool,
    /// Optional report-only ONNX artifact used by the groupjoin path. `direct`
    /// uses its join head; `stack` feeds its pooled representation into the
    /// groupjoin tree from models.json.
    #[serde(default)]
    pub groupjoin_neural_manifest: Option<String>,
    /// Optional report-only ONNX head used only to rank candidate reports.
    /// The primary groupjoin path still supplies the admission score.
    #[serde(default)]
    pub groupjoin_ranker_neural_manifest: Option<String>,
    /// Full-vector challenger-versus-incumbent report preference model.
    #[serde(default)]
    pub groupjoin_report_preference_manifest: Option<String>,
    /// Minimum predicted preference required to replace the frozen incumbent.
    pub groupjoin_report_preference_tau: Option<f64>,
    /// Maximum directional operation-risk score allowed for a dual-head report
    /// preference model. Lower is safer.
    pub groupjoin_report_preference_risk_tau: Option<f64>,
    /// Train-only causal replay intervention. At this query, force the
    /// admission-eligible candidate report currently containing this member.
    /// Both fields must be present together.
    pub groupjoin_forced_query: Option<String>,
    pub groupjoin_forced_report_member: Option<String>,
    /// Optional deterministic group feature used only to rank candidate
    /// reports. The primary groupjoin path still supplies admission.
    pub groupjoin_ranker_feature: Option<String>,
    /// Minimum pairwise preference probability required for an eligible
    /// challenger to replace the admission model's incumbent report.
    pub groupjoin_pair_ranker_tau: Option<f64>,
    /// Restrict ranking to candidates that already clear the frozen groupjoin
    /// admission threshold. This preserves the local join/create decision.
    #[serde(default = "default_true")]
    pub groupjoin_ranker_admission_eligible_only: bool,
    /// Minimum rank-score advantage over the original admission-model winner
    /// before the ranker may change the selected report.
    pub groupjoin_ranker_override_margin: Option<f64>,
    /// Maximum admission-score disadvantage the proposed report may have
    /// relative to the original admission-model winner.
    pub groupjoin_ranker_admission_gap_max: Option<f64>,
    /// Experimental dual-set neural groupjoin. With no mode it uses the direct
    /// head; `stack` feeds its 64 pooled dimensions into models.json groupjoin.
    #[serde(default)]
    pub contextual_groupjoin_manifest: Option<String>,
    #[serde(default)]
    pub groupjoin_neural_mode: Option<GroupJoinNeuralMode>,
    pub gj_tau: Option<f64>,
    /// Apply report admission on the uncalibrated groupjoin score. This mirrors
    /// classifier_raw_tau and avoids losing resolution to isotonic plateaus.
    pub gj_raw_tau: Option<f64>,
    /// Optional pre-mutation coherence gate for the contextual dual-head model.
    /// Candidates below this raw sigmoid score are ineligible before match ranking.
    pub gj_coherence_raw_tau: Option<f64>,
    /// Optional pre-mutation safe-admission gate for the repaired contextual
    /// model. This remains separate from both match ranking and coherence.
    pub gj_admission_raw_tau: Option<f64>,
    /// Apply the safe-admission gate only to candidate reports at or above this
    /// pre-mutation size. Zero preserves the global-gate behavior.
    #[serde(default)]
    pub gj_admission_min_report_size: usize,
    /// Research parity recorder: persist the first N report-candidate feature
    /// maps so the Python training builder can be checked against live Rust.
    /// Zero disables recording.
    #[serde(default)]
    pub group_feature_fixture_limit: usize,
    /// Persist the exact report-member and external-retrieval views scored for
    /// every groupjoin candidate. This is intentionally opt-in because the
    /// resulting decision artifact is large; train-time on-policy labelling
    /// needs it to remain correct after report splits and merges.
    #[serde(default)]
    pub emit_candidate_report_states: bool,
    /// Optional member-aware report-pair repair branch. Candidate pairs come
    /// only from the ordinary pairwise retrieval decision: the chosen report
    /// plus its strongest competitor, or a new singleton plus its best report.
    #[serde(default)]
    pub member_repair_manifest: Option<String>,
    #[serde(default)]
    pub member_repair_architecture: Option<crate::member_repair::Architecture>,
    /// Use the neural artifact's action and safety outputs instead of the
    /// external report-relatedness and operation-risk controls.
    #[serde(default)]
    pub member_repair_integrated_gates: bool,
    /// Minimum competing report score on the active admission score scale.
    pub member_repair_trigger_tau: Option<f64>,
    /// Per-member neural inclusion threshold.
    pub member_repair_member_tau: Option<f64>,
    /// Frozen report-relatedness gate and threshold applied before mutation.
    #[serde(default = "default_member_repair_gate")]
    pub member_repair_report_gate: String,
    pub member_repair_report_gate_tau: Option<f64>,
    /// Independently trained pre-mutation operation-risk gate. A missing
    /// threshold disables it for explicit ablation runs.
    #[serde(default = "default_member_repair_risk_gate")]
    pub member_repair_risk_gate: String,
    pub member_repair_risk_tau: Option<f64>,
    /// Harvest proposals without changing assignment when false.
    #[serde(default = "default_true")]
    pub member_repair_apply: bool,
    /// Re-run the existing whole-report split gate on the repaired destination.
    #[serde(default = "default_true")]
    pub member_repair_split_after: bool,
    /// Replace the learned action and safety gates with a cached LLM judgment
    /// over the single neural member-mask proposal. The oracle may accept,
    /// reject, or return one corrected cross-report mask.
    #[serde(default)]
    pub member_repair_llm_oracle: bool,
    #[serde(default = "default_member_repair_llm_max_tokens")]
    pub member_repair_llm_max_tokens: u32,
    /// centroid merge proposer: top-K per projected query; 0 = off.
    #[serde(default)]
    pub centroid_proposer_k: usize,
    /// max distinct candidate reports evaluated per centroid proposal pass
    #[serde(default = "d_centroid_topn")]
    pub centroid_merge_topn: usize,
    /// blob guard: skip centroid proposals when either report exceeds this many
    /// members. 0 = off.
    #[serde(default)]
    pub centroid_max_report_size: usize,
    /// band-aware merge trigger: >= N candidates from ONE foreign report in
    /// [band_trigger_lo, band_trigger_hi) propose that pair to the gate. 0 = off.
    #[serde(default)]
    pub band_trigger_hits: usize,
    #[serde(default = "d_band_lo")]
    pub band_trigger_lo: f64,
    #[serde(default = "d_band_hi")]
    pub band_trigger_hi: f64,
    /// precompute per-signal retrieval hits (projection searches + id lane) for
    /// the whole stream in a parallel pass before the sequential decision loop
    /// (sequential classifier mode only). Retrieval depends only on stream order,
    /// not decisions; report-dependent evidence stays live in the loop.
    /// Byte-identical output verified against the live-search path.
    #[serde(default = "default_true")]
    pub precompute_retrieval: bool,
    /// Reuse the persisted stream-order retrieval cache outside forced-branch
    /// experiments. This is opt-in so ordinary validation replays retain their
    /// historical behavior unless a sweep deliberately shares retrieval work.
    #[serde(default)]
    pub reuse_precomputed_retrieval_cache: bool,

    // === featurize subcommand (engine featurize <config.json>) ===
    /// jsonl of {"doc_a": ..., "doc_b": ...} pairs to featurize
    #[serde(default)]
    pub featurize_pairs: String,
    #[serde(default)]
    pub featurize_out: String,

    // === featurize-cuts subcommand (engine featurize-cuts <config.json>) ===
    /// jsonl of harvested MST cut proposals (rows without members_a are
    /// merge-proposal rows sharing the stream and are skipped)
    #[serde(default)]
    pub cuts_in: String,
    #[serde(default)]
    pub cuts_out: String,
    /// optional cut_id allowlist (jsonl with a cut_id field, or one cut_id per
    /// line): featurize only labeled cuts instead of the full harvest stream
    #[serde(default)]
    pub cuts_filter: String,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "snake_case")]
pub enum GroupJoinNeuralMode {
    Direct,
    Stack,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug, Default)]
#[serde(rename_all = "snake_case")]
pub enum Semantics {
    #[default]
    Sequential,
    ProdBatch,
}

#[derive(Deserialize, Clone, Copy, PartialEq, Eq, Debug, Default)]
#[serde(rename_all = "snake_case")]
pub enum Mode {
    #[default]
    Threshold, // nearest stored signal < threshold joins; else new (ET-style, $0)
    Hybrid,     // distance tiers + one combined LLM call in the contested band (llm_modes.rs)
    Llm,        // prod parity: query gen + match + specificity LLM calls (llm_modes.rs)
    Classifier, // model stack: pair GBDT (+ join veto/rescue, concern gate, groupjoin)
}

fn default_perf_db() -> String {
    "perf/perf.sqlite".into()
}
fn default_true() -> bool {
    true
}
fn default_llm_cache() -> String {
    "data/llm_cache".into()
}
fn default_batch() -> usize {
    5
}
fn default_threshold() -> f64 {
    0.019
}
fn default_nn_limit() -> usize {
    1
}
fn default_band() -> (f64, f64) {
    (0.05, 0.30)
}
fn default_search() -> usize {
    10
}
fn default_fast_lane_sources() -> Vec<String> {
    vec!["error_tracking".to_string()]
}
fn default_matching_model() -> String {
    "claude-sonnet-4-5".into()
}
fn default_member_repair_gate() -> String {
    "hgb-d2".into()
}
fn default_member_repair_risk_gate() -> String {
    "logistic".into()
}
fn default_member_repair_llm_max_tokens() -> u32 {
    6000
}
fn d_centroid_topn() -> usize {
    3
}
fn d_band_lo() -> f64 {
    0.15
}
fn d_band_hi() -> f64 {
    0.50
}
fn d_budget() -> usize {
    8
}
fn d_trigger() -> f64 {
    0.3
}
fn d_minsize() -> usize {
    3
}
fn d_window() -> f64 {
    30.0
}
fn d_augment() -> usize {
    10
}
