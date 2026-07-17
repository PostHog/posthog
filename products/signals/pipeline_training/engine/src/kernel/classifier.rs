//! Classifier (model-stack) mode: carried from the old replayer's replay.rs —
//! exact port of LabPipeline.process_batch / _process_one (classifier matching),
//! _consider_bridges (concern mode), and _eval_group_after_join (post-join
//! MST-cut splits). In the engine this runs under the SEQUENTIAL semantics:
//! signals process strictly in arrival order as single-signal batches, so each
//! decision sees ALL prior state (snapshot = store.n, no same-batch races).
//! Dropped from the old replayer per DESIGN.md ("drop the dead lab-1 experiment
//! keys"): oracle/mates, harvest mode, plateau escalation, size/coherence join
//! penalties. Everything else — retrieval lanes, pair features, join veto/rescue,
//! groupjoin (+ deep-sets), concern gate, centroid/band proposers, featurize —
//! is verbatim.

use crate::config::Config;
use crate::feats::{self, pair_features, split_features, Feats, RetrievalMeta};
use crate::idents::{extract_identifiers, merge_identifier_sets, IdSets};
use crate::member_repair::{
    Architecture as MemberRepairArchitecture, MemberRepair, PairEvidence, RUST_FEATURE_NAMES,
};
use crate::model::{BurstIndex, GbdtModel};
use crate::sigs::{group_sig_features, sig_pair_features, SigInfo};
use crate::store::{Candidate, EmbeddingStore, ReportStore};
use crate::textstats::{text_pair_features, TextStats};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, VecDeque};
use std::collections::{HashMap, HashSet};
use std::sync::Arc;

const MEMBER_PAIR_CACHE_LIMIT: usize = 250_000;

const DSM_FEATURE_NAMES: [&str; 32] = [
    "dsm_0", "dsm_1", "dsm_2", "dsm_3", "dsm_4", "dsm_5", "dsm_6", "dsm_7", "dsm_8", "dsm_9",
    "dsm_10", "dsm_11", "dsm_12", "dsm_13", "dsm_14", "dsm_15", "dsm_16", "dsm_17", "dsm_18",
    "dsm_19", "dsm_20", "dsm_21", "dsm_22", "dsm_23", "dsm_24", "dsm_25", "dsm_26", "dsm_27",
    "dsm_28", "dsm_29", "dsm_30", "dsm_31",
];

const CONTEXTUAL_DSM_FEATURE_NAMES: [&str; 64] = [
    "dsm_0", "dsm_1", "dsm_2", "dsm_3", "dsm_4", "dsm_5", "dsm_6", "dsm_7", "dsm_8", "dsm_9",
    "dsm_10", "dsm_11", "dsm_12", "dsm_13", "dsm_14", "dsm_15", "dsm_16", "dsm_17", "dsm_18",
    "dsm_19", "dsm_20", "dsm_21", "dsm_22", "dsm_23", "dsm_24", "dsm_25", "dsm_26", "dsm_27",
    "dsm_28", "dsm_29", "dsm_30", "dsm_31", "dsm_32", "dsm_33", "dsm_34", "dsm_35", "dsm_36",
    "dsm_37", "dsm_38", "dsm_39", "dsm_40", "dsm_41", "dsm_42", "dsm_43", "dsm_44", "dsm_45",
    "dsm_46", "dsm_47", "dsm_48", "dsm_49", "dsm_50", "dsm_51", "dsm_52", "dsm_53", "dsm_54",
    "dsm_55", "dsm_56", "dsm_57", "dsm_58", "dsm_59", "dsm_60", "dsm_61", "dsm_62", "dsm_63",
];

const CONTEXTUAL_MATCH_RAW_FEATURE: &str = "contextual_match_raw";
const CONTEXTUAL_COHERENCE_RAW_FEATURE: &str = "contextual_coherence_raw";
const CONTEXTUAL_ADMISSION_RAW_FEATURE: &str = "contextual_admission_raw";
const NEURAL_MATCH_RAW_FEATURE: &str = "neural_match_raw";
const RANKER_ADMISSION_RAW_FEATURE: &str = "ranker_admission_raw";
const RANKER_NEURAL_RAW_FEATURE: &str = "ranker_neural_raw";

#[derive(Deserialize, Clone)]
pub struct SignalIn {
    pub id: String,
    pub ts: f64,
    pub content: String,
    pub product: String,
    #[serde(rename = "type")]
    pub source_type: String,
    #[serde(default)]
    pub source_id: String,
}

impl From<&crate::corpus::Signal> for SignalIn {
    fn from(s: &crate::corpus::Signal) -> Self {
        Self {
            id: s.id.clone(),
            ts: s.ts,
            content: s.content.clone(),
            product: s.product.clone(),
            source_type: s.kind.clone(),
            source_id: s.source_id.clone().unwrap_or_default(),
        }
    }
}

#[derive(Serialize)]
pub struct Decision {
    pub document_id: String,
    pub timestamp: f64,
    pub run_report_id: String,
    pub matched_existing: bool,
    pub match_reason: String,
    pub batch_index: usize,
    pub level: usize,
    /// scored candidate signal ids (union across projections) — loss attribution
    pub candidate_ids: Vec<String>,
    /// Best scored candidate even when the threshold or join model rejects it.
    pub best_candidate_signal_id: Option<String>,
    pub best_candidate_report_id: Option<String>,
    pub best_candidate_distance: Option<f64>,
    /// The actual edge admitted by this decision. Absent for report creation.
    pub joined_parent_signal_id: Option<String>,
    pub best_pair_p: Option<f64>,
    pub best_pair_raw: Option<f64>,
    /// Margin over the best candidate from another report, on the active score scale.
    pub second_best_report_p: Option<f64>,
    pub pair_margin: Option<f64>,
    pub pair_threshold: f64,
    pub pair_threshold_is_raw: bool,
    pub pair_pass: bool,
    pub candidate_count: usize,
    pub candidate_report_count: usize,
    /// True only for the single train-only branch intervention named in config.
    pub forced_report_choice: bool,
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub candidate_report_states: Vec<DecisionCandidateReportState>,
}

#[derive(Serialize)]
pub struct DecisionCandidateReportState {
    pub report_id: String,
    /// Exact member view consumed by the active behavior model.
    pub members: Vec<String>,
    /// Witness-aware member view for a contextual/risk model over this same
    /// decision state. This differs from `members` for legacy stack policies.
    pub contextual_members: Vec<String>,
    /// Complete live report membership for selected diagnostic replays.
    #[serde(skip_serializing_if = "Vec::is_empty")]
    pub all_members: Vec<String>,
    pub n_members: usize,
    pub rank_best: usize,
    pub n_retrieved: usize,
    pub retrieved_witnesses: Vec<String>,
    pub external_members: Vec<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub behavior_raw: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub ranking_raw: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub preference_risk: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub match_raw: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub coherence_raw: Option<f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub admission_raw: Option<f64>,
}

#[derive(Serialize)]
pub struct MergeEvent {
    pub signal_id: String,
    pub src: String,
    pub dst: String,
    pub trigger_p: f64,
    pub gate_p: f64,
    pub timestamp: f64,
}

#[derive(Serialize)]
pub struct SplitEvent {
    pub src: String,
    pub new: String,
    pub moved: usize,
    pub concern_c: f64,
    pub cut_max_p: f64,
}

#[derive(Serialize)]
pub struct MemberRepairEvent {
    pub trigger_signal: String,
    pub timestamp: f64,
    pub architecture: MemberRepairArchitecture,
    pub left_report: String,
    pub right_report: String,
    pub left_size: usize,
    pub right_size: usize,
    pub edge_cell_count: usize,
    pub populated_edge_count: usize,
    pub left_members: Vec<String>,
    pub right_members: Vec<String>,
    pub left_probabilities: Vec<f64>,
    pub right_probabilities: Vec<f64>,
    pub trigger_score: f64,
    pub member_threshold: f64,
    pub report_gate_name: String,
    pub report_gate_score: Option<f64>,
    pub report_gate_threshold: f64,
    pub risk_gate_name: String,
    pub risk_score: Option<f64>,
    pub risk_threshold: Option<f64>,
    pub selected_left: Vec<String>,
    pub selected_right: Vec<String>,
    pub status: String,
    pub output_report: Option<String>,
    pub moved_members: usize,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub llm_oracle: Option<crate::member_repair_oracle::OracleAudit>,
}

#[derive(Serialize)]
pub struct GroupFeatureFixture {
    pub query: String,
    pub candidate_report: String,
    pub members: Vec<String>,
    pub n_members: usize,
    pub rank_best: usize,
    pub n_retrieved: usize,
    pub features: BTreeMap<String, f64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub retrieved_witnesses: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub external_members: Option<Vec<String>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub report_tokens: Option<Vec<Vec<f32>>>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub external_tokens: Option<Vec<Vec<f32>>>,
}

pub struct Replayer {
    pub cfg: Config,
    pub store: EmbeddingStore,
    pub reports: ReportStore,
    /// pair model — required for replay (classifier mode), optional for
    /// featurize (features only, scores omitted)
    pub pair: Option<GbdtModel>,
    pub join: Option<GbdtModel>,
    pub concern: Option<GbdtModel>,
    pub groupjoin: Option<GbdtModel>,
    pub groupjoin_ranker: Option<GbdtModel>,
    pub groupjoin_pair_ranker: Option<GbdtModel>,
    pub groupjoin_net: Option<crate::model::GjNet>,
    pub groupjoin_neural: Option<crate::neural_groupjoin::NeuralGroupJoin>,
    pub groupjoin_ranker_neural: Option<crate::neural_groupjoin::NeuralGroupJoin>,
    pub groupjoin_report_preference:
        Option<crate::neural_report_preference::NeuralReportPreference>,
    pub contextual_groupjoin: Option<crate::contextual_groupjoin::ContextualGroupJoin>,
    pub member_repair: Option<MemberRepair>,
    pub member_repair_llm_oracle: Option<crate::llm::LlmClient>,
    pub burst: BurstIndex,
    batch_means: HashMap<(String, String), Vec<f32>>,
    batch_scales: HashMap<String, f64>,
    id_cache: HashMap<usize, IdSets>,      // by store row
    text_cache: HashMap<usize, TextStats>, // by store row, warmed with id_cache
    pair_p_memo: HashMap<(usize, usize), f64>,
    member_pair_feature_cache: HashMap<(usize, usize), (Arc<Vec<f64>>, f64, f64)>,
    member_pair_feature_cache_order: VecDeque<(usize, usize)>,
    precomputed_retrieval: Option<Arc<Vec<RetrievalHits>>>,
    xp_cache: HashMap<(String, String, usize, usize), Vec<f64>>,
    bridge_evidence: HashMap<(String, String), Vec<f64>>,
    pub merge_events: Vec<MergeEvent>,
    pub split_events: Vec<SplitEvent>,
    pub member_repair_events: Vec<MemberRepairEvent>,
    pub group_feature_fixtures: Vec<GroupFeatureFixture>,
    pub decisions: Vec<Decision>,
    pub retrieval_wall_seconds: f64,
    pub decision_wall_seconds: f64,
    pub concern_wall_seconds: f64,
    pub concern_evaluations: usize,
    pub concern_cuts_scored: usize,
    pub neural_groupjoin_feature_seconds: f64,
    pub neural_groupjoin_wall_seconds: f64,
    pub neural_groupjoin_batches: usize,
    pub neural_groupjoin_candidate_reports: usize,
    pub neural_ranker_wall_seconds: f64,
    pub neural_ranker_batches: usize,
    pub neural_ranker_candidate_reports: usize,
    pub groupjoin_ranker_override_opportunities: usize,
    pub groupjoin_ranker_interventions: usize,
    pub groupjoin_forced_report_choices: usize,
    pub member_repair_wall_seconds: f64,
    pub member_repair_attempts: usize,
    pub member_repair_applied: usize,
    pub member_pair_cache_hits: usize,
    pub member_pair_cache_misses: usize,
    pub member_pair_cache_evictions: usize,
    pub member_retrieval_reuses: usize,
    pub member_retrieval_fallback_searches: usize,
    /// pairwise p / parent candidate at join time, per signal (founders absent)
    join_p: HashMap<String, f64>,
    join_parent: HashMap<String, String>,
    /// identifier value -> store rows containing it (id retrieval lane)
    id_postings: HashMap<String, Vec<usize>>,
    /// ingest-time concern signatures by document id (empty = features neutral)
    pub sigs: HashMap<String, SigInfo>,
}

struct PreparedSignal {
    signal: SignalIn,
    embedding: Vec<f32>, // normalized
    query_labels: Vec<String>,
    query_embeddings: Vec<Vec<f32>>,
    ch_results: Vec<Vec<Candidate>>,
    neigh_scale: f64,
    snapshot: usize, // pre-batch visibility boundary (CH lag), for post-join searches
}

struct GroupJoinCandidate {
    features: Feats,
    tokens: Vec<Vec<f32>>,
    member_embeddings: Vec<Vec<f32>>,
    external_tokens: Vec<Vec<f32>>,
    retrieved_witnesses: Vec<String>,
    external_members: Vec<String>,
    members: Vec<String>,
    contextual_members: Vec<String>,
    all_members: Vec<String>,
    n_members: usize,
}

/// A processed same-batch signal, visible to later levels via augmentation.
struct ProcessedBatchSignal {
    signal_id: String,
    report_id: String,
    row: usize,
    embedding: Vec<f32>,
}

/// Precomputed retrieval for one signal: everything the search phase produces,
/// minus the decision-dependent candidate report ids (rebuilt at consume time
/// from the live store) and the query vectors (unused at batch size 1).
#[derive(Serialize, Deserialize)]
struct RetrievalHits {
    query_labels: Vec<String>,
    /// per lane (aligned with query_labels): (store row, cosine distance)
    lanes: Vec<Vec<(u32, f64)>>,
    neigh_scale: f64,
}

impl Replayer {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        cfg: Config,
        dims: usize,
        pair: Option<GbdtModel>,
        join: Option<GbdtModel>,
        concern: Option<GbdtModel>,
        groupjoin: Option<GbdtModel>,
        groupjoin_ranker: Option<GbdtModel>,
        groupjoin_pair_ranker: Option<GbdtModel>,
        groupjoin_net: Option<crate::model::GjNet>,
        groupjoin_neural: Option<crate::neural_groupjoin::NeuralGroupJoin>,
        groupjoin_ranker_neural: Option<crate::neural_groupjoin::NeuralGroupJoin>,
        groupjoin_report_preference: Option<
            crate::neural_report_preference::NeuralReportPreference,
        >,
        contextual_groupjoin: Option<crate::contextual_groupjoin::ContextualGroupJoin>,
        member_repair: Option<MemberRepair>,
        member_repair_llm_oracle: Option<crate::llm::LlmClient>,
        burst: BurstIndex,
    ) -> Self {
        let mut store = EmbeddingStore::new(dims);
        store.window_secs = cfg.search_window_days * 86400.0;
        Self {
            cfg,
            store,
            reports: ReportStore::default(),
            pair,
            join,
            concern,
            groupjoin,
            groupjoin_ranker,
            groupjoin_pair_ranker,
            groupjoin_net,
            groupjoin_neural,
            groupjoin_ranker_neural,
            groupjoin_report_preference,
            contextual_groupjoin,
            member_repair,
            member_repair_llm_oracle,
            burst,
            batch_means: HashMap::new(),
            batch_scales: HashMap::new(),
            id_cache: HashMap::new(),
            pair_p_memo: HashMap::new(),
            member_pair_feature_cache: HashMap::new(),
            member_pair_feature_cache_order: VecDeque::new(),
            precomputed_retrieval: None,
            xp_cache: HashMap::new(),
            bridge_evidence: HashMap::new(),
            merge_events: Vec::new(),
            split_events: Vec::new(),
            member_repair_events: Vec::new(),
            group_feature_fixtures: Vec::new(),
            decisions: Vec::new(),
            retrieval_wall_seconds: 0.0,
            decision_wall_seconds: 0.0,
            concern_wall_seconds: 0.0,
            concern_evaluations: 0,
            concern_cuts_scored: 0,
            neural_groupjoin_feature_seconds: 0.0,
            neural_groupjoin_wall_seconds: 0.0,
            neural_groupjoin_batches: 0,
            neural_groupjoin_candidate_reports: 0,
            neural_ranker_wall_seconds: 0.0,
            neural_ranker_batches: 0,
            neural_ranker_candidate_reports: 0,
            groupjoin_ranker_override_opportunities: 0,
            groupjoin_ranker_interventions: 0,
            groupjoin_forced_report_choices: 0,
            member_repair_wall_seconds: 0.0,
            member_repair_attempts: 0,
            member_repair_applied: 0,
            member_pair_cache_hits: 0,
            member_pair_cache_misses: 0,
            member_pair_cache_evictions: 0,
            member_retrieval_reuses: 0,
            member_retrieval_fallback_searches: 0,
            join_p: HashMap::new(),
            join_parent: HashMap::new(),
            id_postings: HashMap::new(),
            sigs: HashMap::new(),
            text_cache: HashMap::new(),
        }
    }

    fn pair_model(&self) -> &GbdtModel {
        self.pair.as_ref().expect("pair model required for scoring")
    }

    fn report_preference_vector(
        model: &GbdtModel,
        challenger: &Feats,
        incumbent: &Feats,
        challenger_admission: f64,
        incumbent_admission: f64,
    ) -> Vec<f64> {
        model
            .feature_names
            .iter()
            .map(|name| match name.as_str() {
                "challenger_admission_raw" => challenger_admission,
                "incumbent_admission_raw" => incumbent_admission,
                "delta_admission_raw" => challenger_admission - incumbent_admission,
                _ => {
                    if let Some(feature) = name.strip_prefix("challenger_") {
                        *challenger.get(feature).unwrap_or(&f64::NAN)
                    } else if let Some(feature) = name.strip_prefix("incumbent_") {
                        *incumbent.get(feature).unwrap_or(&f64::NAN)
                    } else if let Some(feature) = name.strip_prefix("delta_") {
                        challenger.get(feature).unwrap_or(&f64::NAN)
                            - incumbent.get(feature).unwrap_or(&f64::NAN)
                    } else {
                        f64::NAN
                    }
                }
            })
            .collect()
    }

    fn ids_for_row(&mut self, row: usize) -> &IdSets {
        if !self.id_cache.contains_key(&row) {
            let ids = extract_identifiers(&self.store.contents[row]);
            self.id_cache.insert(row, ids);
        }
        &self.id_cache[&row]
    }

    /// Warm the identifier + text-stat caches for many rows at once (regex
    /// extraction is the hotspot; it parallelizes cleanly, insertion stays serial).
    fn warm_ids(&mut self, rows: &[usize]) {
        use rayon::prelude::*;
        let missing: Vec<usize> = rows
            .iter()
            .copied()
            .filter(|r| !self.id_cache.contains_key(r))
            .collect();
        if !missing.is_empty() {
            let extracted: Vec<(usize, IdSets)> = missing
                .par_iter()
                .map(|&r| (r, extract_identifiers(&self.store.contents[r])))
                .collect();
            self.id_cache.extend(extracted);
        }
        let missing_t: Vec<usize> = rows
            .iter()
            .copied()
            .filter(|r| !self.text_cache.contains_key(r))
            .collect();
        if !missing_t.is_empty() {
            let computed: Vec<(usize, TextStats)> = missing_t
                .par_iter()
                .map(|&r| (r, TextStats::compute(&self.store.contents[r])))
                .collect();
            self.text_cache.extend(computed);
        }
    }

    /// Featurize mode: Rust port of train_classifier.compute_features (stage-0
    /// emulation). Seeds the store with the full dataset in arrival order, then
    /// for each {doc_a, doc_b} pair emits the complete v16 feature map + the
    /// loaded pair model's raw/cal score (scores omitted when no models file is
    /// given). Semantics mirror the Python builder: query = later arrival,
    /// visible = rows before the query, type means cached per calendar day
    /// (first-seen visibility, input order), projections = raw + residual
    /// re-projections, retrieval metadata + neighborhood scales from real
    /// snapshot-pinned searches at SEARCH_LIMIT.
    ///
    /// Fast path: pairs sharing a query share one stacked search; day means,
    /// id/text caches, and candidate-time scales are precomputed; the per-query
    /// groups then run read-only under rayon.
    pub fn featurize(
        &mut self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
        pairs_path: &str,
        out_path: &str,
    ) -> anyhow::Result<()> {
        use rayon::prelude::*;
        use std::io::{BufRead, BufReader, Write};
        use std::sync::atomic::{AtomicUsize, Ordering};
        let search_limit = crate::store::SEARCH_LIMIT;
        let mut order: Vec<usize> = (0..signals.len()).collect();
        order.sort_by(|&a, &b| {
            signals[a]
                .ts
                .partial_cmp(&signals[b].ts)
                .unwrap()
                .then(a.cmp(&b))
        });
        for &i in &order {
            let s = &signals[i];
            // report_id gates searchability in search_stacked; the python builder
            // seeds every row as searchable, so give each row a placeholder report
            self.store.store(
                s.id.clone(),
                s.content.clone(),
                embeddings.row(i),
                s.id.clone(),
                s.product.clone(),
                s.source_type.clone(),
                s.source_id.clone(),
                s.ts,
                None,
            );
        }
        #[derive(Deserialize)]
        struct PairIn {
            doc_a: String,
            doc_b: String,
        }
        struct Job {
            pi: usize,
            doc_a: String,
            doc_b: String,
            iq: usize,
            ic: usize,
        }
        let pairs: Vec<PairIn> = BufReader::new(std::fs::File::open(pairs_path)?)
            .lines()
            .map(|l| serde_json::from_str(&l?).map_err(anyhow::Error::from))
            .collect::<anyhow::Result<_>>()?;
        let mut jobs: Vec<Job> = Vec::with_capacity(pairs.len());
        for (pi, p) in pairs.iter().enumerate() {
            let (Some(&ia), Some(&ib)) = (
                self.store.row_by_signal_id.get(&p.doc_a),
                self.store.row_by_signal_id.get(&p.doc_b),
            ) else {
                continue;
            };
            let (iq, ic) = if self.store.timestamps[ia] >= self.store.timestamps[ib] {
                (ia, ib)
            } else {
                (ib, ia)
            };
            if iq == 0 {
                continue;
            }
            jobs.push(Job {
                pi,
                doc_a: p.doc_a.clone(),
                doc_b: p.doc_b.clone(),
                iq,
                ic,
            });
        }
        eprintln!(
            "featurize: {} pairs ({} resolvable)",
            pairs.len(),
            jobs.len()
        );

        // day-means cache, python semantics: keyed by calendar day, first-seen
        // visibility in INPUT order
        let mut day_means: HashMap<i64, HashMap<(String, String), Vec<f32>>> = HashMap::new();
        for j in &jobs {
            let q_ts = self.store.timestamps[j.iq];
            let day = (q_ts / 86400.0).floor() as i64;
            if !day_means.contains_key(&day) {
                let m = self.store.type_means(q_ts, j.iq);
                day_means.insert(day, m);
            }
        }
        let rows: Vec<usize> = jobs.iter().flat_map(|j| [j.iq, j.ic]).collect();
        self.warm_ids(&rows);
        eprintln!("featurize: {} day-means, caches warm", day_means.len());

        // candidate-time neighborhood scales, one raw search per unique candidate row
        let mut c_rows: Vec<usize> = jobs.iter().map(|j| j.ic).collect();
        c_rows.sort_unstable();
        c_rows.dedup();
        let c_scales: HashMap<usize, f64> = c_rows
            .par_iter()
            .map(|&ic| {
                let s = if ic > 0 {
                    let res = self.store.search_stacked(
                        &[self.store.row(ic).to_vec()],
                        self.store.timestamps[ic],
                        search_limit,
                        ic,
                    );
                    if res[0].len() >= 10 {
                        res[0][res[0].len() - 1].distance
                    } else {
                        1.0
                    }
                } else {
                    1.0
                };
                (ic, s)
            })
            .collect();

        // group pairs by query row: one stacked search serves the whole group
        let mut by_q: HashMap<usize, Vec<usize>> = HashMap::new();
        for (k, j) in jobs.iter().enumerate() {
            by_q.entry(j.iq).or_default().push(k);
        }
        let mut groups: Vec<(usize, Vec<usize>)> = by_q.into_iter().collect();
        groups.sort_by_key(|(iq, _)| *iq);
        let done = AtomicUsize::new(0);
        let total = jobs.len();
        let mut lines: Vec<(usize, String)> = groups
            .par_iter()
            .flat_map(|(iq, members)| {
                let iq = *iq;
                let visible = iq;
                let q_ts = self.store.timestamps[iq];
                let day = (q_ts / 86400.0).floor() as i64;
                let means = &day_means[&day];
                let q_type_owned = (
                    self.store.source_products[iq].clone(),
                    self.store.source_types[iq].clone(),
                );
                let e_q: Vec<f32> = self.store.row(iq).to_vec();
                let own = means.get(&q_type_owned);
                let residual: Vec<f32> = match own {
                    Some(m) => e_q
                        .iter()
                        .zip(m)
                        .map(|(a, b)| ((*a as f64) - (*b as f64)) as f32)
                        .collect(),
                    None => e_q.clone(),
                };
                let mut labels: Vec<String> = vec![format!(
                    "residual→raw/{}/{}",
                    q_type_owned.0, q_type_owned.1
                )];
                let mut vectors: Vec<Vec<f32>> = vec![e_q.clone()];
                let mut keys: Vec<&(String, String)> = means.keys().collect();
                keys.sort();
                for key in keys {
                    let mu = &means[key];
                    labels.push(format!("residual→{}/{}", key.0, key.1));
                    vectors.push(
                        residual
                            .iter()
                            .zip(mu)
                            .map(|(a, b)| ((*a as f64) + (*b as f64)) as f32)
                            .collect(),
                    );
                }
                let results = self
                    .store
                    .search_stacked(&vectors, q_ts, search_limit, visible);
                let own_a = format!("residual→{}/{}", q_type_owned.0, q_type_owned.1);
                let own_b = labels[0].clone();
                let scale_q = if results[0].len() >= 10 {
                    results[0][results[0].len() - 1].distance
                } else {
                    1.0
                };
                let q_type = (
                    self.store.source_products[iq].as_str(),
                    self.store.source_types[iq].as_str(),
                );
                let burst_q = self.burst.count(q_type.0, q_type.1, q_ts);
                let sig_q = self.sigs.get(&self.store.signal_ids[iq]);
                let out: Vec<(usize, String)> = members
                    .iter()
                    .map(|&k| {
                        let job = &jobs[k];
                        let ic = job.ic;
                        let c_ts = self.store.timestamps[ic];
                        let cand_id = &self.store.signal_ids[ic];
                        let mut rm: Option<RetrievalMeta> = None;
                        for (label, res) in labels.iter().zip(&results) {
                            let is_own = *label == own_a || *label == own_b;
                            for (rank, c) in res.iter().enumerate() {
                                if &c.signal_id == cand_id {
                                    let m = rm.get_or_insert(RetrievalMeta {
                                        n_projections: 0.0,
                                        best_rank: (rank + 1) as f64,
                                        best_distance: c.distance,
                                        own_type: 0.0,
                                    });
                                    m.n_projections += 1.0;
                                    if ((rank + 1) as f64) < m.best_rank {
                                        m.best_rank = (rank + 1) as f64;
                                    }
                                    if c.distance < m.best_distance {
                                        m.best_distance = c.distance;
                                    }
                                    if is_own {
                                        m.own_type = 1.0;
                                    }
                                }
                            }
                        }
                        let c_type = (
                            self.store.source_products[ic].as_str(),
                            self.store.source_types[ic].as_str(),
                        );
                        let burst_c = self.burst.count(c_type.0, c_type.1, c_ts);
                        let mut f = pair_features(
                            &e_q,
                            q_type,
                            q_ts,
                            &self.store.contents[iq],
                            &self.store.source_ids[iq],
                            self.store.row(ic),
                            c_type,
                            c_ts,
                            &self.store.contents[ic],
                            &self.store.source_ids[ic],
                            means,
                            rm.as_ref(),
                            burst_q,
                            burst_c,
                            &self.id_cache[&iq],
                            &self.id_cache[&ic],
                            scale_q,
                            c_scales[&ic],
                        );
                        let sig_c = self.sigs.get(cand_id);
                        for (kk, v) in sig_pair_features(sig_q, sig_c) {
                            f.insert(kk, v);
                        }
                        for (kk, v) in
                            text_pair_features(&self.text_cache[&iq], &self.text_cache[&ic])
                        {
                            f.insert(kk, v);
                        }
                        let mut obj = serde_json::Map::new();
                        obj.insert("doc_a".into(), serde_json::Value::String(job.doc_a.clone()));
                        obj.insert("doc_b".into(), serde_json::Value::String(job.doc_b.clone()));
                        if let Some(pair) = &self.pair {
                            let x = pair.vectorize(&f);
                            let (raw, cal) = pair.predict(&x);
                            obj.insert("pair_raw".into(), raw.into());
                            obj.insert("pair_cal".into(), cal.into());
                        }
                        for (kk, v) in &f {
                            obj.insert((*kk).to_string(), (*v).into());
                        }
                        let n = done.fetch_add(1, Ordering::Relaxed) + 1;
                        if n % 10000 == 0 {
                            eprintln!("featurized {n}/{total}");
                        }
                        (job.pi, serde_json::Value::Object(obj).to_string())
                    })
                    .collect();
                out
            })
            .collect();
        lines.sort_by_key(|(pi, _)| *pi);
        let mut out = std::io::BufWriter::new(std::fs::File::create(out_path)?);
        for (_pi, line) in &lines {
            writeln!(out, "{line}")?;
        }
        eprintln!(
            "featurized {}/{} pairs -> {out_path}",
            lines.len(),
            pairs.len()
        );
        Ok(())
    }

    /// Featurize-cuts mode: serve-identical featurization of harvested MST cut
    /// proposals (concern-gate training frames). Mirrors eval_group_after_join:
    /// for each harvested cut, rebuild the full pairwise p matrix over the
    /// sampled members (retrieval-imputed row_pair_p_batch, insert-time
    /// neighborhood scales, trigger-time type means), recompute the MST, order
    /// sides a >= b, and emit group_pair_feats + split_extras keyed by cut_id
    /// ("<cuts file basename>#<0-based line index over ALL lines>", matching
    /// labels/pair_bank/label_cuts.py). Merge-proposal rows (no members_a),
    /// torn lines, and cuts with unknown member docs are skipped; skipped lines
    /// still consume a line index.
    pub fn featurize_cuts(
        &mut self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
        cuts_in: &str,
        cuts_out: &str,
        filter: Option<&HashSet<String>>,
    ) -> anyhow::Result<()> {
        use rayon::prelude::*;
        use std::io::{BufRead, BufReader, Write};
        // seed the store with the full corpus, same as `featurize`: arrival
        // order, every row searchable via a placeholder report id
        let mut order: Vec<usize> = (0..signals.len()).collect();
        order.sort_by(|&a, &b| {
            signals[a]
                .ts
                .partial_cmp(&signals[b].ts)
                .unwrap()
                .then(a.cmp(&b))
        });
        for &i in &order {
            let s = &signals[i];
            self.store.store(
                s.id.clone(),
                s.content.clone(),
                embeddings.row(i),
                s.id.clone(),
                s.product.clone(),
                s.source_type.clone(),
                s.source_id.clone(),
                s.ts,
                None,
            );
        }

        #[derive(Deserialize)]
        struct ProvEntry {
            id: String,
            #[serde(default)]
            join_p: Option<f64>,
            #[serde(default)]
            parent: Option<String>,
        }
        #[derive(Deserialize)]
        struct CutIn {
            // all optional: merge-proposal rows share the harvest stream with a
            // different schema (kind=merge_trigger, no members_a/trigger)
            #[serde(default)]
            trigger: Option<String>,
            #[serde(default)]
            true_size: Option<usize>,
            #[serde(default)]
            members_a: Option<Vec<String>>,
            #[serde(default)]
            members_b: Option<Vec<String>>,
            #[serde(default)]
            provenance: Vec<ProvEntry>,
        }
        struct Job {
            cut_id: String,
            trigger_row: usize,
            rows_a: Vec<usize>, // larger side, ascending arrival order
            rows_b: Vec<usize>,
            true_size: usize,
            trigger: String,
            provenance: Vec<(String, Option<f64>, Option<String>)>,
        }

        let basename = std::path::Path::new(cuts_in)
            .file_name()
            .map(|f| f.to_string_lossy().to_string())
            .unwrap_or_else(|| cuts_in.to_string());
        let (mut n_lines, mut n_filtered, mut n_merge, mut n_torn, mut n_unknown) =
            (0usize, 0usize, 0usize, 0usize, 0usize);
        let mut jobs: Vec<Job> = Vec::new();
        for (i, line) in BufReader::new(std::fs::File::open(cuts_in)?)
            .lines()
            .enumerate()
        {
            n_lines += 1;
            let cut_id = format!("{basename}#{i}");
            if let Some(f) = filter {
                if !f.contains(&cut_id) {
                    n_filtered += 1;
                    continue;
                }
            }
            let line = line?;
            let Ok(cut) = serde_json::from_str::<CutIn>(&line) else {
                n_torn += 1; // torn tail line of an in-progress file
                continue;
            };
            let (Some(members_a), Some(members_b)) = (cut.members_a, cut.members_b) else {
                n_merge += 1; // merge-proposal row, separate schema
                continue;
            };
            let (Some(trigger), Some(true_size)) = (cut.trigger, cut.true_size) else {
                n_torn += 1; // cut row missing required fields — malformed
                continue;
            };
            let resolve = |docs: &[String]| -> Option<Vec<usize>> {
                let mut rows: Vec<usize> = docs
                    .iter()
                    .map(|d| self.store.row_by_signal_id.get(d).copied())
                    .collect::<Option<_>>()?;
                rows.sort_unstable(); // arrival order, matching report_view sampling
                Some(rows)
            };
            let (Some(mut rows_a), Some(mut rows_b), Some(&trigger_row)) = (
                resolve(&members_a),
                resolve(&members_b),
                self.store.row_by_signal_id.get(&trigger),
            ) else {
                n_unknown += 1;
                continue;
            };
            if rows_a.is_empty() || rows_b.is_empty() {
                n_unknown += 1;
                continue;
            }
            if rows_a.len() < rows_b.len() {
                std::mem::swap(&mut rows_a, &mut rows_b); // a = larger side (serve swap)
            }
            jobs.push(Job {
                cut_id,
                trigger_row,
                rows_a,
                rows_b,
                true_size,
                trigger,
                provenance: cut
                    .provenance
                    .into_iter()
                    .map(|p| (p.id, p.join_p, p.parent))
                    .collect(),
            });
        }
        eprintln!(
            "featurize-cuts: {n_lines} lines -> {} cuts ({n_filtered} filtered out, {n_merge} merge rows, {n_torn} unparseable, {n_unknown} unknown-doc)",
            jobs.len()
        );

        // insert-time neighborhood scales for every row the pair scorer will
        // touch (members + severed-join parents), matching serve's store-time
        // values: own raw top-10 distance at the row's snapshot
        let mut need: Vec<usize> = jobs
            .iter()
            .flat_map(|j| {
                j.rows_a
                    .iter()
                    .chain(&j.rows_b)
                    .copied()
                    .chain(j.provenance.iter().filter_map(|(_id, _p, par)| {
                        par.as_deref()
                            .and_then(|p| self.store.row_by_signal_id.get(p).copied())
                    }))
                    .collect::<Vec<_>>()
            })
            .collect();
        need.sort_unstable();
        need.dedup();
        let scales: Vec<(usize, f64)> = need
            .par_iter()
            .map(|&r| {
                let s = if r > 0 {
                    let res = self.store.search_stacked(
                        &[self.store.row(r).to_vec()],
                        self.store.timestamps[r],
                        crate::store::SEARCH_LIMIT,
                        r,
                    );
                    if res[0].len() >= 10 {
                        res[0][res[0].len() - 1].distance
                    } else {
                        1.0
                    }
                } else {
                    1.0
                };
                (r, s)
            })
            .collect();
        for (r, s) in scales {
            self.store
                .neigh_scale
                .insert(self.store.signal_ids[r].clone(), s);
        }
        eprintln!(
            "featurize-cuts: {} neighborhood scales computed",
            need.len()
        );

        let mut out = std::io::BufWriter::new(std::fs::File::create(cuts_out)?);
        let total = jobs.len();
        let mut cur_trigger: Option<usize> = None;
        let started = std::time::Instant::now();
        for (done, job) in jobs.iter().enumerate() {
            // type means as at the trigger's decision (sequential semantics:
            // snapshot = trigger row). Memoized pair p depends on the means, so
            // the memo is scoped to one trigger and cleared when it changes.
            if cur_trigger != Some(job.trigger_row) {
                self.pair_p_memo.clear();
                self.batch_means = self
                    .store
                    .type_means(self.store.timestamps[job.trigger_row], job.trigger_row);
                cur_trigger = Some(job.trigger_row);
            }
            // provenance -> join_p/join_parent BEFORE featurizing (split_extras
            // reads them); cleared per cut so provenance never leaks across cuts
            self.join_p.clear();
            self.join_parent.clear();
            for (id, jp, parent) in &job.provenance {
                if let Some(p) = jp {
                    self.join_p.insert(id.clone(), *p);
                }
                if let Some(par) = parent {
                    self.join_parent.insert(id.clone(), par.clone());
                }
            }

            // full pairwise p matrix over ALL members, arrival order (as
            // eval_group_after_join builds it over view.content_rows)
            let mut rows: Vec<usize> = job.rows_a.iter().chain(&job.rows_b).copied().collect();
            rows.sort_unstable();
            let n = rows.len();
            let mut pair_list = Vec::with_capacity(n * (n - 1) / 2);
            for i in 0..n {
                for j in (i + 1)..n {
                    pair_list.push((rows[i], rows[j]));
                }
            }
            let ps = self.row_pair_p_batch(&pair_list);
            let mut p = vec![vec![1.0f64; n]; n];
            let mut k = 0;
            for i in 0..n {
                for j in (i + 1)..n {
                    p[i][j] = ps[k];
                    p[j][i] = ps[k];
                    k += 1;
                }
            }
            let edges = Self::mst_edges(&p);
            let mst_ps: Vec<f64> = edges.iter().map(|&(a, b)| p[a][b]).collect();

            // cut_p in serve iteration order: a_idx ascending x b_idx ascending
            let idx_of: HashMap<usize, usize> =
                rows.iter().enumerate().map(|(i, &r)| (r, i)).collect();
            let mut cut_p = Vec::with_capacity(job.rows_a.len() * job.rows_b.len());
            for &ra in &job.rows_a {
                for &rb in &job.rows_b {
                    cut_p.push(p[idx_of[&ra]][idx_of[&rb]]);
                }
            }
            let mut feats = self.group_pair_feats(&cut_p, &job.rows_a, &job.rows_b, 2.0);
            let extras =
                self.split_extras(&cut_p, &mst_ps, &job.rows_b, job.true_size, n, &job.trigger);
            feats.extend(extras);

            let mut obj = serde_json::Map::new();
            obj.insert(
                "cut_id".into(),
                serde_json::Value::String(job.cut_id.clone()),
            );
            let mut names: Vec<&&str> = feats.keys().collect();
            names.sort();
            for name in names {
                obj.insert((**name).to_string(), feats[*name].into());
            }
            writeln!(out, "{}", serde_json::Value::Object(obj))?;
            if (done + 1) % 1000 == 0 {
                let rate = (done + 1) as f64 / started.elapsed().as_secs_f64().max(1e-6);
                eprintln!("featurized {}/{total} cuts ({rate:.0}/s)", done + 1);
            }
        }
        out.flush()?;
        eprintln!(
            "featurize-cuts: {total} cuts -> {cuts_out} in {:.1}s",
            started.elapsed().as_secs_f64()
        );
        Ok(())
    }

    /// Read-only pair scoring (ids must be warmed): safe to call from rayon.
    #[allow(clippy::too_many_arguments)]
    fn score_pair_vs_row_ro(
        &self,
        e_q: &[f32],
        q_type: (&str, &str),
        q_ts: f64,
        content_q: &str,
        source_id_q: &str,
        ids_q: &IdSets,
        burst_q: f64,
        neigh_scale_q: f64,
        sig_q: Option<&SigInfo>,
        text_q: &TextStats,
        row: usize,
        rmeta: Option<&RetrievalMeta>,
    ) -> (f64, f64) {
        let c_type = (
            self.store.source_products[row].as_str(),
            self.store.source_types[row].as_str(),
        );
        let c_ts = self.store.timestamps[row];
        let burst_c = self.burst.count(c_type.0, c_type.1, c_ts);
        let neigh_c = self.store.neigh_scale_of(&self.store.signal_ids[row]);
        let ids_c = &self.id_cache[&row];
        let mut f = pair_features(
            e_q,
            q_type,
            q_ts,
            content_q,
            source_id_q,
            self.store.row(row),
            c_type,
            c_ts,
            &self.store.contents[row],
            &self.store.source_ids[row],
            &self.batch_means,
            rmeta,
            burst_q,
            burst_c,
            ids_q,
            ids_c,
            neigh_scale_q,
            neigh_c,
        );
        let sig_c = self.sigs.get(&self.store.signal_ids[row]);
        for (k, v) in sig_pair_features(sig_q, sig_c) {
            f.insert(k, v);
        }
        for (k, v) in text_pair_features(text_q, &self.text_cache[&row]) {
            f.insert(k, v);
        }
        let pair = self.pair_model();
        let x = pair.vectorize(&f);
        pair.predict(&x)
    }

    /// stored-row vs stored-row pair p (retrieval imputed not-retrieved), memoized.
    /// Query = later arrival, matching the pipeline convention. Misses are scored
    /// in parallel; the memo is filled serially afterwards.
    fn row_pair_p_batch(&mut self, pairs: &[(usize, usize)]) -> Vec<f64> {
        use rayon::prelude::*;
        let mut out = vec![0.0f64; pairs.len()];
        let mut missing: Vec<usize> = Vec::new();
        for (k, (a, b)) in pairs.iter().enumerate() {
            let key = (*a.min(b), *a.max(b));
            match self.pair_p_memo.get(&key) {
                Some(p) => out[k] = *p,
                None => missing.push(k),
            }
        }
        if missing.is_empty() {
            return out;
        }
        let rows: Vec<usize> = missing
            .iter()
            .flat_map(|&k| [pairs[k].0, pairs[k].1])
            .collect();
        self.warm_ids(&rows);
        let computed: Vec<(usize, f64)> = missing
            .par_iter()
            .map(|&k| {
                let (row_a, row_b) = pairs[k];
                let (rq, rc) = if self.store.timestamps[row_a] >= self.store.timestamps[row_b] {
                    (row_a, row_b)
                } else {
                    (row_b, row_a)
                };
                let q_type = (
                    self.store.source_products[rq].as_str(),
                    self.store.source_types[rq].as_str(),
                );
                let q_ts = self.store.timestamps[rq];
                let burst_q = self.burst.count(q_type.0, q_type.1, q_ts);
                let neigh_q = self.store.neigh_scale_of(&self.store.signal_ids[rq]);
                let ids_q = &self.id_cache[&rq];
                let (_raw, p) = self.score_pair_vs_row_ro(
                    self.store.row(rq),
                    q_type,
                    q_ts,
                    &self.store.contents[rq],
                    &self.store.source_ids[rq],
                    ids_q,
                    burst_q,
                    neigh_q,
                    self.sigs.get(&self.store.signal_ids[rq]),
                    &self.text_cache[&rq],
                    rc,
                    None,
                );
                (k, p)
            })
            .collect();
        for (k, p) in computed {
            let (a, b) = pairs[k];
            self.pair_p_memo.insert((a.min(b), a.max(b)), p);
            out[k] = p;
        }
        out
    }

    /// Concern score on the artifact's threshold scale (raw for v2, calibrated for v1).
    fn concern_p(&mut self, feats: &Feats) -> f64 {
        let concern = self.concern.as_ref().expect("concern model");
        let x = concern.vectorize(feats);
        let (raw, cal) = concern.predict(&x);
        if concern.thresholds_on_raw {
            raw
        } else {
            cal
        }
    }

    /// numpy-compatible linear-interpolation quantile of an unsorted slice
    fn quantile(values: &[f64], q: f64) -> f64 {
        if values.is_empty() {
            return 0.0;
        }
        let mut v = values.to_vec();
        v.sort_by(|a, b| a.partial_cmp(b).unwrap());
        let pos = q * (v.len() - 1) as f64;
        let lo = pos.floor() as usize;
        let hi = pos.ceil() as usize;
        v[lo] + (v[hi] - v[lo]) * (pos - lo as f64)
    }

    /// Concern-v2 extras for a split-eval cut. sev_join_p_* recompute the severed
    /// members' pair p vs their join parent through the memoized retrieval-imputed
    /// path (matching the trainer's OOF-rescored scale, NOT the recorded join p
    /// which carried retrieval context).
    fn split_extras(
        &mut self,
        cut_p: &[f64],
        mst_ps: &[f64],
        rows_b: &[usize],
        true_size: usize,
        n_sampled: usize,
        trigger_signal: &str,
    ) -> Feats {
        let mut sev_pairs: Vec<(usize, usize)> = Vec::new();
        let mut founders = 0usize;
        let mut has_trigger = 0.0;
        for &r in rows_b {
            let sid = &self.store.signal_ids[r];
            if sid == trigger_signal {
                has_trigger = 1.0;
            }
            match self
                .join_parent
                .get(sid)
                .and_then(|p| self.store.row_by_signal_id.get(p))
            {
                Some(&pr) => sev_pairs.push((r, pr)),
                None => founders += 1,
            }
        }
        let sev_ps = if sev_pairs.is_empty() {
            Vec::new()
        } else {
            self.row_pair_p_batch(&sev_pairs)
        };
        let mut f: Feats = HashMap::with_capacity(10);
        f.insert("is_split_eval", 1.0);
        f.insert("true_log_size", (true_size as f64).ln_1p());
        f.insert("sample_frac", n_sampled as f64 / true_size.max(1) as f64);
        f.insert("cut_p_p90", Self::quantile(cut_p, 0.9));
        f.insert(
            "cut_p_frac_03",
            if cut_p.is_empty() {
                0.0
            } else {
                cut_p.iter().filter(|p| **p >= 0.3).count() as f64 / cut_p.len() as f64
            },
        );
        f.insert("mst_median_p", Self::quantile(mst_ps, 0.5));
        f.insert(
            "sev_join_p_max",
            if sev_ps.is_empty() {
                -1.0
            } else {
                sev_ps.iter().cloned().fold(f64::NEG_INFINITY, f64::max)
            },
        );
        f.insert(
            "sev_join_p_mean",
            if sev_ps.is_empty() {
                -1.0
            } else {
                sev_ps.iter().sum::<f64>() / sev_ps.len() as f64
            },
        );
        f.insert(
            "sev_frac_founders",
            founders as f64 / rows_b.len().max(1) as f64,
        );
        f.insert("sev_has_trigger", has_trigger);
        f
    }

    /// Concern-v2 extras for a merge-shaped evaluation (sentinels documented in
    /// the trainer; true_log_size = sampled member count like the label rows).
    /// sig-aware concern models (v2.5+) train merge rows with TRUE report sizes
    /// and a real sample fraction; older cascades used the capped member lists
    fn merge_extras(
        xp: &[f64],
        n_a: usize,
        n_b: usize,
        true_total: usize,
        sig_aware: bool,
    ) -> Feats {
        let mut f: Feats = HashMap::with_capacity(10);
        f.insert("is_split_eval", 0.0);
        if sig_aware {
            f.insert("true_log_size", (true_total as f64).ln_1p());
            f.insert("sample_frac", (n_a + n_b) as f64 / true_total.max(1) as f64);
        } else {
            f.insert("true_log_size", ((n_a + n_b) as f64).ln_1p());
            f.insert("sample_frac", 1.0);
        }
        f.insert("cut_p_p90", Self::quantile(xp, 0.9));
        f.insert(
            "cut_p_frac_03",
            if xp.is_empty() {
                0.0
            } else {
                xp.iter().filter(|p| **p >= 0.3).count() as f64 / xp.len() as f64
            },
        );
        f.insert("mst_median_p", 0.0);
        f.insert("sev_join_p_max", -1.0);
        f.insert("sev_join_p_mean", -1.0);
        f.insert("sev_frac_founders", 1.0);
        f.insert("sev_has_trigger", 0.0);
        f
    }

    /// split_features over a bipartition of stored rows (rows_a = larger half enforced by caller).
    fn group_pair_feats(
        &mut self,
        cut_p: &[f64],
        rows_a: &[usize],
        rows_b: &[usize],
        n_components: f64,
    ) -> Feats {
        for &r in rows_a.iter().chain(rows_b) {
            self.ids_for_row(r);
        }
        let ids_a: Vec<&IdSets> = rows_a.iter().map(|r| &self.id_cache[r]).collect();
        let ids_b: Vec<&IdSets> = rows_b.iter().map(|r| &self.id_cache[r]).collect();
        let merged_a = merge_identifier_sets(&ids_a);
        let merged_b = merge_identifier_sets(&ids_b);
        let emb_a: Vec<&[f32]> = rows_a.iter().map(|&r| self.store.row(r)).collect();
        let emb_b: Vec<&[f32]> = rows_b.iter().map(|&r| self.store.row(r)).collect();
        let ts_a: Vec<f64> = rows_a.iter().map(|&r| self.store.timestamps[r]).collect();
        let ts_b: Vec<f64> = rows_b.iter().map(|&r| self.store.timestamps[r]).collect();
        let prods_a: HashSet<String> = rows_a
            .iter()
            .map(|&r| self.store.source_products[r].clone())
            .collect();
        let prods_b: HashSet<String> = rows_b
            .iter()
            .map(|&r| self.store.source_products[r].clone())
            .collect();
        let mut f = split_features(
            cut_p,
            &emb_a,
            &emb_b,
            &ts_a,
            &ts_b,
            &merged_a,
            &merged_b,
            &prods_a,
            &prods_b,
            n_components,
        );
        let sig_side = |rows: &[usize]| -> Vec<(Option<&SigInfo>, (String, String))> {
            rows.iter()
                .map(|&r| {
                    (
                        self.sigs.get(&self.store.signal_ids[r]),
                        (
                            self.store.source_products[r].clone(),
                            self.store.source_types[r].clone(),
                        ),
                    )
                })
                .collect()
        };
        for (k, v) in group_sig_features(&sig_side(rows_a), &sig_side(rows_b)) {
            f.insert(k, v);
        }
        f
    }

    /// cross-pair p over the last-k content samples of two report views, cached by (pair, sizes).
    fn cross_pair_ps(
        &mut self,
        rid_a: &str,
        rows_a: &[usize],
        size_a: usize,
        rid_b: &str,
        rows_b: &[usize],
        size_b: usize,
    ) -> Vec<f64> {
        const K: usize = 5;
        let key = (rid_a.to_string(), rid_b.to_string(), size_a, size_b);
        if let Some(v) = self.xp_cache.get(&key) {
            return v.clone();
        }
        let last = |v: &[usize]| v[v.len().saturating_sub(K)..].to_vec();
        let mut pair_list = Vec::new();
        for &i in &last(rows_a) {
            for &j in &last(rows_b) {
                pair_list.push((i, j));
            }
        }
        let ps = self.row_pair_p_batch(&pair_list);
        self.xp_cache.insert(key, ps.clone());
        ps
    }

    /// maximum spanning tree edges over the pair-p matrix of `rows` (Prim's).
    fn mst_edges(p: &[Vec<f64>]) -> Vec<(usize, usize)> {
        let n = p.len();
        let mut used = vec![false; n];
        used[0] = true;
        let mut best: Vec<f64> = p[0].clone();
        let mut best_from = vec![0usize; n];
        let mut edges = Vec::with_capacity(n - 1);
        for _ in 0..n - 1 {
            let mut j = usize::MAX;
            let mut jv = f64::NEG_INFINITY;
            for (k, &u) in used.iter().enumerate() {
                if !u && best[k] > jv {
                    jv = best[k];
                    j = k;
                }
            }
            edges.push((best_from[j], j));
            used[j] = true;
            for k in 0..n {
                if !used[k] && p[j][k] > best[k] {
                    best[k] = p[j][k];
                    best_from[k] = j;
                }
            }
        }
        edges
    }

    /// v2.1 final stage: post-join whole-group re-eval; split at the worst MST cut when C <= sigma.
    fn eval_group_after_join(&mut self, report_id: &str, trigger_signal: &str) {
        if self.concern.is_none() {
            return;
        }
        let rid = self.reports.resolve(report_id);
        let prior_splits = self
            .split_events
            .iter()
            .filter(|e| e.src == rid || e.new == rid)
            .count();
        if prior_splits >= self.cfg.concern_split_budget {
            return;
        }
        let Some(view) = self.store.report_view(&rid, 20, 20) else {
            return;
        };
        if view.size < self.cfg.split_min_size || view.content_rows.len() < 3 {
            return;
        }
        let rows = view.content_rows.clone();
        let n = rows.len();
        let concern_started = std::time::Instant::now();
        self.concern_evaluations += 1;
        let mut pair_list = Vec::with_capacity(n * (n - 1) / 2);
        for i in 0..n {
            for j in (i + 1)..n {
                pair_list.push((rows[i], rows[j]));
            }
        }
        let ps = self.row_pair_p_batch(&pair_list);
        let mut p = vec![vec![1.0f64; n]; n];
        let mut k = 0;
        for i in 0..n {
            for j in (i + 1)..n {
                p[i][j] = ps[k];
                p[j][i] = ps[k];
                k += 1;
            }
        }
        let edges = Self::mst_edges(&p);
        self.concern_cuts_scored += edges.len();
        let mut adj: Vec<Vec<usize>> = vec![Vec::new(); n];
        for &(a, b) in &edges {
            adj[a].push(b);
            adj[b].push(a);
        }
        let mst_ps: Vec<f64> = edges.iter().map(|&(a, b)| p[a][b]).collect();
        let mut worst: Option<(f64, Vec<usize>, Vec<usize>, f64)> = None; // (C, a_idx, b_idx, cut_max_p)
        for &(ea, eb) in &edges {
            let mut seen = vec![false; n];
            seen[ea] = true;
            let mut stack = vec![ea];
            while let Some(x) = stack.pop() {
                for &y in &adj[x] {
                    if (x == ea && y == eb) || (x == eb && y == ea) || seen[y] {
                        continue;
                    }
                    seen[y] = true;
                    stack.push(y);
                }
            }
            let mut a_idx: Vec<usize> = (0..n).filter(|&i| seen[i]).collect();
            let mut b_idx: Vec<usize> = (0..n).filter(|&i| !seen[i]).collect();
            if a_idx.len() < b_idx.len() {
                std::mem::swap(&mut a_idx, &mut b_idx);
            }
            let mut cut_p = Vec::with_capacity(a_idx.len() * b_idx.len());
            for &i in &a_idx {
                for &j in &b_idx {
                    cut_p.push(p[i][j]);
                }
            }
            let rows_a: Vec<usize> = a_idx.iter().map(|&i| rows[i]).collect();
            let rows_b: Vec<usize> = b_idx.iter().map(|&i| rows[i]).collect();
            let mut feats = self.group_pair_feats(&cut_p, &rows_a, &rows_b, 2.0);
            let extras = self.split_extras(&cut_p, &mst_ps, &rows_b, view.size, n, trigger_signal);
            feats.extend(extras);
            let c = self.concern_p(&feats);
            if worst.as_ref().map_or(true, |w| c < w.0) {
                let cut_max = *feats.get("cut_max_p").unwrap();
                worst = Some((c, rows_a, rows_b, cut_max));
            }
        }
        let Some((c_min, _rows_a, rows_b, cut_max_p)) = worst else {
            return;
        };
        self.concern_wall_seconds += concern_started.elapsed().as_secs_f64();
        let sigma = self
            .cfg
            .concern_split_sigma
            .or(self.concern.as_ref().unwrap().sigma)
            .unwrap_or(0.285);
        if c_min > sigma {
            return;
        }
        // unsampled (older) members stay put: only the severed smaller half moves
        let new_id = format!(
            "split-{}-{}",
            &rid[..rid.len().min(24)],
            self.split_events.len()
        );
        let move_ids: HashSet<String> = rows_b
            .iter()
            .map(|&r| self.store.signal_ids[r].clone())
            .collect();
        let all_rows = self
            .store
            .rows_by_report
            .get(&rid)
            .cloned()
            .unwrap_or_default();
        let keep: HashSet<String> = all_rows
            .iter()
            .map(|&r| self.store.signal_ids[r].clone())
            .filter(|s| !move_ids.contains(s))
            .collect();
        let moved = self.store.split_report(&rid, &keep, &new_id);
        if moved > 0 {
            self.split_events.push(SplitEvent {
                src: rid,
                new: new_id,
                moved,
                concern_c: c_min,
                cut_max_p,
            });
        }
    }

    /// _consider_bridges, concern mode: top-5 foreign reports holding >= trigger-tau
    /// candidates propose merges; the concern model disposes.
    fn consider_bridges(
        &mut self,
        signal_id: &str,
        signal_ts: f64,
        cand_report_of: &[(String, f64)], // (store-time report id, cal p) per scored candidate
        best_report: &str,
        _best_p: f64,
    ) -> usize {
        if self.concern.is_none() {
            return 0;
        }
        let mut per_report: HashMap<String, f64> = HashMap::new();
        for (raw_rid, p_c) in cand_report_of {
            let rid = self.reports.resolve(raw_rid);
            if rid != best_report {
                let e = per_report.entry(rid).or_insert(0.0);
                *e = e.max(*p_c);
            }
        }
        let mut ranked: Vec<(String, f64)> = per_report.into_iter().collect();
        ranked.sort_by(|a, b| b.1.partial_cmp(&a.1).unwrap().then(a.0.cmp(&b.0)));
        ranked.truncate(5);
        let mut merged = 0;
        for (rid0, p_other) in ranked {
            if p_other < self.cfg.bridge_trigger_tau {
                continue;
            }
            let rid = self.reports.resolve(&rid0); // an earlier trigger may have merged it
            if rid == best_report {
                continue;
            }
            let Some(_view_own) = self.store.report_view(best_report, 40, 10) else {
                continue;
            };
            let Some(_view_other) = self.store.report_view(&rid, 40, 10) else {
                continue;
            };
            let key = if *best_report < *rid {
                (best_report.to_string(), rid.clone())
            } else {
                (rid.clone(), best_report.to_string())
            };
            self.bridge_evidence.entry(key).or_default().push(p_other);
            if self.try_merge(signal_id, signal_ts, best_report, &rid, p_other) {
                merged += 1;
            }
        }
        merged
    }

    /// Build the exact groupjoin model inputs. Feature semantics are a bit-exact
    /// port of the Python builder: cosine aggregates over the last 40 members,
    /// identifiers/signatures over the first 10 of that window.
    #[allow(clippy::too_many_arguments)]
    fn gj_candidate(
        &mut self,
        q_emb: &[f32],
        q_sig_id: &str,
        ids_q: &IdSets,
        qts: f64,
        qprod: &str,
        qtype: &str,
        rid: &str,
        rank_best: usize,
        n_retrieved: usize,
        retrieved_rows: &[usize],
    ) -> Option<GroupJoinCandidate> {
        if self.groupjoin.is_none()
            && self.groupjoin_neural.is_none()
            && self.contextual_groupjoin.is_none()
        {
            return None;
        }
        let all_rows = self.store.rows_by_report.get(rid)?.clone();
        if all_rows.is_empty() {
            return None;
        }
        let true_n = all_rows.len();
        let contextual = self.contextual_groupjoin.is_some();
        let witnesses = retrieved_rows
            .iter()
            .copied()
            .filter(|row| self.reports.resolve(&self.store.report_ids[*row]) == rid)
            .collect::<Vec<_>>();
        let external_rows = retrieved_rows
            .iter()
            .copied()
            .filter(|row| self.reports.resolve(&self.store.report_ids[*row]) != rid)
            .take(crate::contextual_groupjoin::EXTERNAL_CAP)
            .collect::<Vec<_>>();
        let recent_take = all_rows[all_rows
            .len()
            .saturating_sub(crate::contextual_groupjoin::MEMBER_CAP)..]
            .to_vec();
        let contextual_take: Vec<usize> = if !contextual && !self.cfg.emit_candidate_report_states {
            recent_take.clone()
        } else if true_n <= crate::contextual_groupjoin::MEMBER_CAP {
            recent_take.clone()
        } else {
            let all_set = all_rows.iter().copied().collect::<HashSet<_>>();
            let mut selected = Vec::with_capacity(crate::contextual_groupjoin::MEMBER_CAP);
            let mut seen = HashSet::new();
            for row in witnesses.iter().copied().take(10) {
                if all_set.contains(&row) && seen.insert(row) {
                    selected.push(row);
                }
            }
            let mut source_latest: HashMap<(String, String), usize> = HashMap::new();
            for row in &all_rows {
                source_latest.insert(
                    (
                        self.store.source_products[*row].clone(),
                        self.store.source_types[*row].clone(),
                    ),
                    *row,
                );
            }
            let mut source_prototypes = source_latest.into_values().collect::<Vec<_>>();
            source_prototypes.sort_unstable_by(|left, right| right.cmp(left));
            for row in source_prototypes.into_iter().take(8) {
                if selected.len() >= crate::contextual_groupjoin::MEMBER_CAP {
                    break;
                }
                if seen.insert(row) {
                    selected.push(row);
                }
            }
            let mut history_prototypes = all_rows.clone();
            history_prototypes.sort_unstable_by_key(|row| {
                crate::contextual_groupjoin::prototype_priority(&self.store.signal_ids[*row])
            });
            for row in history_prototypes.into_iter().take(10) {
                if selected.len() >= crate::contextual_groupjoin::MEMBER_CAP {
                    break;
                }
                if seen.insert(row) {
                    selected.push(row);
                }
            }
            for row in all_rows.iter().rev().copied() {
                if selected.len() >= crate::contextual_groupjoin::MEMBER_CAP {
                    break;
                }
                if seen.insert(row) {
                    selected.push(row);
                }
            }
            selected.sort_unstable();
            selected
        };
        let take = if contextual {
            contextual_take.clone()
        } else {
            recent_take
        };
        let d = self.store.dims;
        fn dot(a: &[f32], b: &[f32]) -> f64 {
            a.iter()
                .zip(b)
                .map(|(x, y)| (*x as f64) * (*y as f64))
                .sum()
        }
        let mut cs: Vec<f64> = Vec::with_capacity(take.len());
        let mut acc = vec![0f64; d];
        for &r in &take {
            let v = &self.store.matrix[r * d..(r + 1) * d];
            cs.push(dot(q_emb, v));
            for (a, x) in acc.iter_mut().zip(v) {
                *a += *x as f64;
            }
        }
        let n = take.len() as f64;
        let mean: Vec<f64> = acc.iter().map(|a| a / n).collect();
        let coherence = mean.iter().map(|a| a * a).sum::<f64>().sqrt();
        let cnorm = coherence.max(1e-9);
        let cos_centroid = mean
            .iter()
            .zip(q_emb)
            .map(|(a, x)| a * (*x as f64))
            .sum::<f64>()
            / cnorm;
        let with_q_norm = acc
            .iter()
            .zip(q_emb)
            .map(|(a, x)| {
                let v = (a + *x as f64) / (n + 1.0);
                v * v
            })
            .sum::<f64>()
            .sqrt();
        let mut srt = cs.clone();
        srt.sort_by(|a, b| b.partial_cmp(a).unwrap());
        let (mut same_prod, mut same_type) = (0.0, 0.0);
        let (mut ts_min, mut ts_max) = (f64::INFINITY, f64::NEG_INFINITY);
        for &r in &take {
            if self.store.source_products[r] == qprod {
                same_prod += 1.0;
            }
            if self.store.source_types[r] == qtype {
                same_type += 1.0;
            }
            let t = self.store.timestamps[r];
            ts_min = ts_min.min(t);
            ts_max = ts_max.max(t);
        }
        let head10: Vec<usize> = take.iter().copied().take(10).collect();
        self.warm_ids(&head10);
        let (mut shared, mut conflict) = (0.0f64, 0.0f64);
        for &r in &head10 {
            let mi = &self.id_cache[&r];
            for (k, a) in ids_q.iter() {
                if a.is_empty() {
                    continue;
                }
                if let Some(b) = mi.get(k) {
                    if !b.is_empty() {
                        let inter = a.intersection(b).count();
                        shared += inter as f64;
                        if inter == 0 {
                            conflict += 1.0;
                        }
                    }
                }
            }
        }
        let sig_side = |rows: &[usize]| -> Vec<(Option<&SigInfo>, (String, String))> {
            rows.iter()
                .map(|&r| {
                    (
                        self.sigs.get(&self.store.signal_ids[r]),
                        (
                            self.store.source_products[r].clone(),
                            self.store.source_types[r].clone(),
                        ),
                    )
                })
                .collect()
        };
        let side_q = vec![(
            self.sigs.get(q_sig_id),
            (qprod.to_string(), qtype.to_string()),
        )];
        let mut f: HashMap<&'static str, f64> = HashMap::new();
        f.insert("cos_max", srt[0]);
        f.insert("cos_2nd", if srt.len() > 1 { srt[1] } else { 0.0 });
        f.insert("cos_mean", cs.iter().sum::<f64>() / n);
        f.insert("cos_centroid", cos_centroid);
        f.insert("coherence", coherence);
        f.insert("coherence_delta", with_q_norm - coherence);
        f.insert("log_size", (1.0 + true_n as f64).ln());
        f.insert("rank_best", rank_best.min(25) as f64 / 25.0);
        f.insert("n_retrieved", n_retrieved.min(10) as f64 / 10.0);
        f.insert("frac_same_product", same_prod / n);
        f.insert("frac_same_type", same_type / n);
        f.insert("log_gap_hours", (1.0 + (qts - ts_max).abs() / 3600.0).ln());
        f.insert("log_span_hours", (1.0 + (ts_max - ts_min) / 3600.0).ln());
        f.insert("id_shared", shared.min(10.0) / 10.0);
        f.insert("id_conflict", conflict.min(10.0) / 10.0);
        for (k, v) in group_sig_features(&side_q, &sig_side(&head10)) {
            f.insert(k, v);
        }
        // dsM stack: deep-sets over per-member relation tokens (12 channels, bit-
        // parity with train_gj3) + Matryoshka-64 member embedding -> 16 pooled
        // dims consumed by the stack GBM as dsm_0..dsm_15
        let needs_tokens = self.groupjoin_net.is_some()
            || self.groupjoin_neural.is_some()
            || self.contextual_groupjoin.is_some();
        let mut tokens: Vec<Vec<f32>> = Vec::new();
        let member_embeddings = take
            .iter()
            .map(|row| self.store.row(*row).to_vec())
            .collect::<Vec<_>>();
        let mut external_tokens: Vec<Vec<f32>> = Vec::new();
        if needs_tokens {
            fn renorm(v: &[f32], k: usize) -> Vec<f64> {
                let s: Vec<f64> = v[..k].iter().map(|x| *x as f64).collect();
                let nrm = s.iter().map(|x| x * x).sum::<f64>().sqrt().max(1e-9);
                s.into_iter().map(|x| x / nrm).collect()
            }
            fn jacs(a: &[String], b: &[String]) -> f64 {
                use std::collections::HashSet as HS;
                let sa: HS<&String> = a.iter().collect();
                let sb: HS<&String> = b.iter().collect();
                let inter = sa.intersection(&sb).count();
                let uni = sa.union(&sb).count().max(1);
                inter as f64 / uni as f64
            }
            let mut token_rows = take.clone();
            if contextual {
                token_rows.extend(external_rows.iter().copied());
            }
            self.warm_ids(&token_rows);
            let qn64 = renorm(q_emb, 64);
            let qn256 = renorm(q_emb, 256);
            let q_sig = self.sigs.get(q_sig_id);
            let n_take = take.len();
            let witness_rank = witnesses
                .iter()
                .enumerate()
                .map(|(index, row)| (*row, index))
                .collect::<HashMap<_, _>>();
            tokens = Vec::with_capacity(n_take);
            for (ti, &r) in take.iter().enumerate() {
                let v = &self.store.matrix[r * d..(r + 1) * d];
                let m64 = renorm(v, 64);
                let m256 = renorm(v, 256);
                let m_sig = self.sigs.get(&self.store.signal_ids[r]);
                let sig_cos = match (q_sig, m_sig) {
                    (Some(a), Some(b)) if !a.emb.is_empty() && !b.emb.is_empty() => a
                        .emb
                        .iter()
                        .zip(&b.emb)
                        .map(|(x, y)| (*x as f64) * (*y as f64))
                        .sum(),
                    _ => 0.5,
                };
                let tags_jac = match (q_sig, m_sig) {
                    (Some(a), Some(b)) => jacs(&a.tags, &b.tags),
                    _ => 0.5,
                };
                let mi = &self.id_cache[&r];
                let (mut sh, mut cf) = (0.0f64, 0.0f64);
                for (k, a) in ids_q.iter() {
                    if a.is_empty() {
                        continue;
                    }
                    if let Some(b) = mi.get(k) {
                        if !b.is_empty() {
                            let inter = a.intersection(b).count();
                            sh += inter as f64;
                            if inter == 0 {
                                cf += 1.0;
                            }
                        }
                    }
                }
                let typ = v
                    .iter()
                    .zip(&mean)
                    .map(|(x, a)| (*x as f64) * a)
                    .sum::<f64>()
                    / cnorm;
                let mut tok = vec![
                    cs[ti] as f32,
                    qn256.iter().zip(&m256).map(|(a, b)| a * b).sum::<f64>() as f32,
                    qn64.iter().zip(&m64).map(|(a, b)| a * b).sum::<f64>() as f32,
                    sig_cos as f32,
                    tags_jac as f32,
                    if self.store.source_products[r] == qprod {
                        1.0
                    } else {
                        0.0
                    },
                    if self.store.source_types[r] == qtype {
                        1.0
                    } else {
                        0.0
                    },
                    (sh.min(5.0) / 5.0) as f32,
                    (cf.min(5.0) / 5.0) as f32,
                    ((1.0 + (qts - self.store.timestamps[r]).abs() / 3600.0).ln() / 8.0) as f32,
                    ((n_take - ti) as f64 / n_take.max(1) as f64) as f32,
                    typ as f32,
                ];
                if contextual {
                    let rank = witness_rank.get(&r);
                    tok.extend([
                        if rank.is_some() { 1.0 } else { 0.0 },
                        1.0,
                        rank.map_or(0.0, |index| {
                            1.0 - *index as f32 / witnesses.len().max(1) as f32
                        }),
                    ]);
                }
                tok.extend(m64.into_iter().map(|value| value as f32));
                tokens.push(tok);
            }
            if contextual {
                let n_external = external_rows.len();
                external_tokens = Vec::with_capacity(n_external);
                for (position, &r) in external_rows.iter().enumerate() {
                    let v = &self.store.matrix[r * d..(r + 1) * d];
                    let m64 = renorm(v, 64);
                    let m256 = renorm(v, 256);
                    let m_sig = self.sigs.get(&self.store.signal_ids[r]);
                    let sig_cos = match (q_sig, m_sig) {
                        (Some(a), Some(b)) if !a.emb.is_empty() && !b.emb.is_empty() => a
                            .emb
                            .iter()
                            .zip(&b.emb)
                            .map(|(x, y)| (*x as f64) * (*y as f64))
                            .sum(),
                        _ => 0.5,
                    };
                    let tags_jac = match (q_sig, m_sig) {
                        (Some(a), Some(b)) => jacs(&a.tags, &b.tags),
                        _ => 0.5,
                    };
                    let mi = &self.id_cache[&r];
                    let (mut shared, mut conflict) = (0.0f64, 0.0f64);
                    for (category, query_values) in ids_q.iter() {
                        if query_values.is_empty() {
                            continue;
                        }
                        if let Some(member_values) = mi.get(category) {
                            if !member_values.is_empty() {
                                let intersection = query_values.intersection(member_values).count();
                                shared += intersection as f64;
                                if intersection == 0 {
                                    conflict += 1.0;
                                }
                            }
                        }
                    }
                    let candidate_centroid_cosine = v
                        .iter()
                        .zip(&mean)
                        .map(|(value, centroid_value)| (*value as f64) * centroid_value)
                        .sum::<f64>()
                        / cnorm;
                    let similarity = dot(q_emb, v);
                    let mut token = vec![
                        similarity as f32,
                        qn256.iter().zip(&m256).map(|(a, b)| a * b).sum::<f64>() as f32,
                        qn64.iter().zip(&m64).map(|(a, b)| a * b).sum::<f64>() as f32,
                        sig_cos as f32,
                        tags_jac as f32,
                        if self.store.source_products[r] == qprod {
                            1.0
                        } else {
                            0.0
                        },
                        if self.store.source_types[r] == qtype {
                            1.0
                        } else {
                            0.0
                        },
                        (shared.min(5.0) / 5.0) as f32,
                        (conflict.min(5.0) / 5.0) as f32,
                        ((1.0 + (qts - self.store.timestamps[r]).abs() / 3600.0).ln() / 8.0) as f32,
                        ((n_external - position) as f64 / n_external.max(1) as f64) as f32,
                        candidate_centroid_cosine as f32,
                        1.0,
                        0.0,
                        1.0 - position as f32 / n_external.max(1) as f32,
                    ];
                    token.extend(m64.into_iter().map(|value| value as f32));
                    external_tokens.push(token);
                }
            }
            if !contextual {
                if let Some(net) = &self.groupjoin_net {
                    let legacy_tokens = tokens
                        .iter()
                        .map(|token| token.iter().map(|value| *value as f64).collect::<Vec<_>>())
                        .collect::<Vec<_>>();
                    let pooled = net.pool(&legacy_tokens);
                    for (name, value) in DSM_FEATURE_NAMES.iter().zip(&pooled) {
                        f.insert(name, *value);
                    }
                }
            }
        }
        Some(GroupJoinCandidate {
            features: f,
            tokens,
            member_embeddings,
            external_tokens,
            retrieved_witnesses: witnesses
                .iter()
                .map(|row| self.store.signal_ids[*row].clone())
                .collect(),
            external_members: external_rows
                .iter()
                .map(|row| self.store.signal_ids[*row].clone())
                .collect(),
            members: take
                .iter()
                .map(|&row| self.store.signal_ids[row].clone())
                .collect(),
            contextual_members: contextual_take
                .iter()
                .map(|&row| self.store.signal_ids[row].clone())
                .collect(),
            all_members: if self.cfg.emit_candidate_report_states {
                all_rows
                    .iter()
                    .map(|&row| self.store.signal_ids[row].clone())
                    .collect()
            } else {
                Vec::new()
            },
            n_members: true_n,
        })
    }

    fn retrieval_meta_from_precomputed(
        hits: &RetrievalHits,
        product: &str,
        source_type: &str,
        candidate: usize,
    ) -> Option<RetrievalMeta> {
        let own_label = format!("residual→{product}/{source_type}");
        let raw_own_label = format!("residual→raw/{product}/{source_type}");
        let mut retrieval = None;
        for (label, lane) in hits.query_labels.iter().zip(&hits.lanes) {
            if label == "ids/lookup" {
                continue;
            }
            let is_own = label == &own_label || label == &raw_own_label;
            for (rank, &(row, distance)) in lane.iter().take(crate::store::SEARCH_LIMIT).enumerate()
            {
                if row as usize != candidate {
                    continue;
                }
                let value = retrieval.get_or_insert(RetrievalMeta {
                    n_projections: 0.0,
                    best_rank: (rank + 1) as f64,
                    best_distance: distance,
                    own_type: 0.0,
                });
                value.n_projections += 1.0;
                value.best_rank = value.best_rank.min((rank + 1) as f64);
                value.best_distance = value.best_distance.min(distance);
                if is_own {
                    value.own_type = 1.0;
                }
            }
        }
        retrieval
    }

    /// Serve-compatible pair features for sparse edges between two live reports.
    fn stored_pair_features_batch(
        &mut self,
        pairs: &[(usize, usize)],
    ) -> anyhow::Result<Vec<(Arc<Vec<f64>>, f64, f64)>> {
        if pairs.is_empty() {
            return Ok(Vec::new());
        }
        let mut output: Vec<Option<(Arc<Vec<f64>>, f64, f64)>> = vec![None; pairs.len()];
        let mut missing = Vec::new();
        for (pair_index, &(left, right)) in pairs.iter().enumerate() {
            let key = (left.min(right), left.max(right));
            if let Some(cached) = self.member_pair_feature_cache.get(&key) {
                output[pair_index] = Some(cached.clone());
                self.member_pair_cache_hits += 1;
            } else {
                missing.push((pair_index, left, right));
                self.member_pair_cache_misses += 1;
            }
        }
        if missing.is_empty() {
            return output
                .into_iter()
                .map(|value| value.ok_or_else(|| anyhow::anyhow!("member edge cache hole")))
                .collect();
        }
        let rows: Vec<usize> = missing
            .iter()
            .flat_map(|(_, left, right)| [*left, *right])
            .collect();
        self.warm_ids(&rows);
        let mut by_query: BTreeMap<usize, Vec<(usize, usize)>> = BTreeMap::new();
        for &(pair_index, left, right) in &missing {
            let (query, candidate) = if self.store.timestamps[left] >= self.store.timestamps[right]
            {
                (left, right)
            } else {
                (right, left)
            };
            by_query
                .entry(query)
                .or_default()
                .push((pair_index, candidate));
        }
        let precomputed_retrieval = self.precomputed_retrieval.as_ref().map(Arc::clone);
        let can_reuse_precomputed = self.cfg.search_limit >= crate::store::SEARCH_LIMIT;
        for (query, jobs) in by_query {
            let timestamp = self.store.timestamps[query];
            let means = self.store.type_means(timestamp, query);
            let signal = SignalIn {
                id: self.store.signal_ids[query].clone(),
                ts: timestamp,
                content: self.store.contents[query].clone(),
                product: self.store.source_products[query].clone(),
                source_type: self.store.source_types[query].clone(),
                source_id: self.store.source_ids[query].clone(),
            };
            let query_embedding = self.store.row(query).to_vec();
            let precomputed_hits = can_reuse_precomputed
                .then(|| precomputed_retrieval.as_ref()?.get(query))
                .flatten();
            let replayed_search = if precomputed_hits.is_some() {
                self.member_retrieval_reuses += 1;
                None
            } else {
                self.member_retrieval_fallback_searches += 1;
                let mut feature_cfg = self.cfg.clone();
                feature_cfg.search_limit = crate::store::SEARCH_LIMIT;
                feature_cfg.id_lane_limit = 0;
                Some(Self::search_signal(
                    &feature_cfg,
                    &self.store,
                    &means,
                    &HashMap::new(),
                    &signal,
                    &query_embedding,
                    query,
                ))
            };
            let neigh_scale_q = precomputed_hits.map_or_else(
                || {
                    replayed_search
                        .as_ref()
                        .expect("fallback search is present")
                        .3
                },
                |hits| hits.neigh_scale,
            );
            let query_type = (signal.product.as_str(), signal.source_type.as_str());
            let burst_q = self.burst.count(query_type.0, query_type.1, timestamp);
            for (pair_index, candidate) in jobs {
                let candidate_id = &self.store.signal_ids[candidate];
                let retrieval = if let Some(hits) = precomputed_hits {
                    Self::retrieval_meta_from_precomputed(
                        hits,
                        &signal.product,
                        &signal.source_type,
                        candidate,
                    )
                } else {
                    let (labels, _vectors, results, _neigh_scale) = replayed_search
                        .as_ref()
                        .expect("fallback search is present");
                    let mut retrieval = None;
                    for (label, lane) in labels.iter().zip(results) {
                        if label == "ids/lookup" {
                            continue;
                        }
                        let is_own = label
                            == &format!("residual→{}/{}", signal.product, signal.source_type)
                            || label
                                == &format!(
                                    "residual→raw/{}/{}",
                                    signal.product, signal.source_type
                                );
                        for (rank, hit) in lane.iter().enumerate() {
                            if hit.row != candidate {
                                continue;
                            }
                            let value = retrieval.get_or_insert(RetrievalMeta {
                                n_projections: 0.0,
                                best_rank: (rank + 1) as f64,
                                best_distance: hit.distance,
                                own_type: 0.0,
                            });
                            value.n_projections += 1.0;
                            value.best_rank = value.best_rank.min((rank + 1) as f64);
                            value.best_distance = value.best_distance.min(hit.distance);
                            if is_own {
                                value.own_type = 1.0;
                            }
                        }
                    }
                    retrieval
                };
                let neigh_scale_c = self.store.neigh_scale_of(candidate_id);
                let candidate_type = (
                    self.store.source_products[candidate].as_str(),
                    self.store.source_types[candidate].as_str(),
                );
                let burst_c = self.burst.count(
                    candidate_type.0,
                    candidate_type.1,
                    self.store.timestamps[candidate],
                );
                let mut features = pair_features(
                    &query_embedding,
                    query_type,
                    timestamp,
                    &signal.content,
                    &signal.source_id,
                    self.store.row(candidate),
                    candidate_type,
                    self.store.timestamps[candidate],
                    &self.store.contents[candidate],
                    &self.store.source_ids[candidate],
                    &means,
                    retrieval.as_ref(),
                    burst_q,
                    burst_c,
                    &self.id_cache[&query],
                    &self.id_cache[&candidate],
                    neigh_scale_q,
                    neigh_scale_c,
                );
                for (name, value) in
                    sig_pair_features(self.sigs.get(&signal.id), self.sigs.get(candidate_id))
                {
                    features.insert(name, value);
                }
                for (name, value) in
                    text_pair_features(&self.text_cache[&query], &self.text_cache[&candidate])
                {
                    features.insert(name, value);
                }
                let vector = self.pair_model().vectorize(&features);
                let (raw, calibrated) = self.pair_model().predict(&vector);
                let rust_features = Arc::new(
                    RUST_FEATURE_NAMES
                        .iter()
                        .map(|name| {
                            features.get(name).copied().ok_or_else(|| {
                                anyhow::anyhow!("missing member-repair Rust feature {name}")
                            })
                        })
                        .collect::<anyhow::Result<Vec<_>>>()?,
                );
                let cached = (rust_features, raw, calibrated);
                let (left, right) = pairs[pair_index];
                let key = (left.min(right), left.max(right));
                if !self.member_pair_feature_cache.contains_key(&key) {
                    while self.member_pair_feature_cache.len() >= MEMBER_PAIR_CACHE_LIMIT {
                        let evicted = self
                            .member_pair_feature_cache_order
                            .pop_front()
                            .expect("nonempty member-pair cache has insertion order");
                        if self.member_pair_feature_cache.remove(&evicted).is_some() {
                            self.member_pair_cache_evictions += 1;
                        }
                    }
                    self.member_pair_feature_cache.insert(key, cached.clone());
                    self.member_pair_feature_cache_order.push_back(key);
                }
                output[pair_index] = Some(cached);
            }
        }
        output
            .into_iter()
            .map(|value| value.ok_or_else(|| anyhow::anyhow!("member edge was not featurized")))
            .collect()
    }

    fn member_repair_edges(
        &mut self,
        left_rows: &[usize],
        right_rows: &[usize],
    ) -> anyhow::Result<Vec<PairEvidence>> {
        let similarities = self.store.cross_similarities(left_rows, right_rows);
        let mut left_ranks: HashMap<(usize, usize), usize> = HashMap::new();
        let mut right_ranks: HashMap<(usize, usize), usize> = HashMap::new();
        let mut selected = std::collections::BTreeSet::new();
        for left in 0..left_rows.len() {
            let mut candidates: Vec<usize> = (0..right_rows.len()).collect();
            candidates.sort_by(|right_a, right_b| {
                similarities[left * right_rows.len() + *right_b]
                    .total_cmp(&similarities[left * right_rows.len() + *right_a])
                    .then(right_a.cmp(right_b))
            });
            for (rank, right) in candidates
                .into_iter()
                .take(crate::member_repair::TOP_K)
                .enumerate()
            {
                selected.insert((left, right));
                left_ranks.insert((left, right), rank + 1);
            }
        }
        for right in 0..right_rows.len() {
            let mut candidates: Vec<usize> = (0..left_rows.len()).collect();
            candidates.sort_by(|left_a, left_b| {
                similarities[*left_b * right_rows.len() + right]
                    .total_cmp(&similarities[*left_a * right_rows.len() + right])
                    .then(left_a.cmp(left_b))
            });
            for (rank, left) in candidates
                .into_iter()
                .take(crate::member_repair::TOP_K)
                .enumerate()
            {
                selected.insert((left, right));
                right_ranks.insert((left, right), rank + 1);
            }
        }
        let selected: Vec<(usize, usize)> = selected.into_iter().collect();
        let row_pairs: Vec<(usize, usize)> = selected
            .iter()
            .map(|(left, right)| (left_rows[*left], right_rows[*right]))
            .collect();
        let scored = self.stored_pair_features_batch(&row_pairs)?;
        Ok(selected
            .into_iter()
            .zip(scored)
            .map(|((left, right), (features, raw, calibrated))| {
                PairEvidence::new_shared(
                    left,
                    right,
                    similarities[left * right_rows.len() + right] as f64,
                    left_ranks.get(&(left, right)).copied(),
                    right_ranks.get(&(left, right)).copied(),
                    raw,
                    calibrated,
                    features,
                )
            })
            .collect())
    }

    fn member_repair_oracle_evidence(
        &self,
        rows: &[usize],
        trigger_signal: &str,
    ) -> Vec<crate::member_repair_oracle::MemberEvidence> {
        rows.iter()
            .map(|row| crate::member_repair_oracle::MemberEvidence {
                id: self.store.signal_ids[*row].clone(),
                product: self.store.source_products[*row].clone(),
                source_type: self.store.source_types[*row].clone(),
                content: self.store.contents[*row].clone(),
                is_trigger: self.store.signal_ids[*row] == trigger_signal,
            })
            .collect()
    }

    fn judge_member_repair_with_llm(
        &self,
        trigger_signal: &str,
        trigger_score: f64,
        left_rows: &[usize],
        right_rows: &[usize],
        selected_left: &[String],
        selected_right: &[String],
    ) -> anyhow::Result<crate::member_repair_oracle::OracleChoice> {
        let client = self
            .member_repair_llm_oracle
            .as_ref()
            .ok_or_else(|| anyhow::anyhow!("member-repair LLM oracle is not configured"))?;
        let prompt = crate::member_repair_oracle::build_prompt(
            trigger_score,
            self.member_repair_oracle_evidence(left_rows, trigger_signal),
            self.member_repair_oracle_evidence(right_rows, trigger_signal),
            selected_left,
            selected_right,
        );
        let response = client.one_shot(&prompt.text, self.cfg.member_repair_llm_max_tokens)?;
        let first = crate::member_repair_oracle::parse_json_text(&response).and_then(|value| {
            crate::member_repair_oracle::parse_response(
                &value,
                &client.model,
                &prompt,
                selected_left,
                selected_right,
            )
        });
        match first {
            Ok(choice) => Ok(choice),
            Err(error) => {
                let correction = format!(
                    "{}\n\nYour previous response failed validation. Return a corrected JSON object only.\nVALIDATOR ERROR: {}\nPREVIOUS RESPONSE: {}",
                    prompt.text,
                    error,
                    response
                );
                let response =
                    client.one_shot(&correction, self.cfg.member_repair_llm_max_tokens)?;
                let value = crate::member_repair_oracle::parse_json_text(&response)?;
                crate::member_repair_oracle::parse_response(
                    &value,
                    &client.model,
                    &prompt,
                    selected_left,
                    selected_right,
                )
            }
        }
    }

    fn consider_member_repair(
        &mut self,
        trigger_signal: &str,
        timestamp: f64,
        own_report: &str,
        competitor_report: &str,
        trigger_score: f64,
    ) -> Option<String> {
        let architecture = self.cfg.member_repair_architecture?;
        let trigger_tau = self.cfg.member_repair_trigger_tau.unwrap_or(0.0);
        if trigger_score < trigger_tau {
            return None;
        }
        let left_report = self.reports.resolve(own_report);
        let right_report = self.reports.resolve(competitor_report);
        if left_report == right_report {
            return None;
        }
        let left_rows = self
            .store
            .rows_by_report
            .get(&left_report)
            .cloned()
            .unwrap_or_default();
        let right_rows = self
            .store
            .rows_by_report
            .get(&right_report)
            .cloned()
            .unwrap_or_default();
        if left_rows.is_empty() || right_rows.is_empty() {
            return None;
        }
        let left_members: Vec<String> = left_rows
            .iter()
            .map(|row| self.store.signal_ids[*row].clone())
            .collect();
        let right_members: Vec<String> = right_rows
            .iter()
            .map(|row| self.store.signal_ids[*row].clone())
            .collect();
        self.member_repair_attempts += 1;
        let member_threshold = self.cfg.member_repair_member_tau.unwrap_or(0.5);
        let gate_threshold = self.cfg.member_repair_report_gate_tau.unwrap_or(0.5);
        let gate_name = if self.cfg.member_repair_integrated_gates {
            "integrated-action".to_string()
        } else {
            self.cfg.member_repair_report_gate.clone()
        };
        let risk_gate_name = if self.cfg.member_repair_integrated_gates {
            "integrated-safety".to_string()
        } else {
            self.cfg.member_repair_risk_gate.clone()
        };
        let edge_cell_count = left_rows.len().saturating_mul(right_rows.len());
        let started = std::time::Instant::now();
        let edges = match self.member_repair_edges(&left_rows, &right_rows) {
            Ok(edges) => edges,
            Err(error) => {
                self.member_repair_events.push(MemberRepairEvent {
                    trigger_signal: trigger_signal.to_string(),
                    timestamp,
                    architecture,
                    left_report,
                    right_report,
                    left_size: left_rows.len(),
                    right_size: right_rows.len(),
                    edge_cell_count,
                    populated_edge_count: 0,
                    left_members,
                    right_members,
                    left_probabilities: Vec::new(),
                    right_probabilities: Vec::new(),
                    trigger_score,
                    member_threshold,
                    report_gate_name: gate_name.clone(),
                    report_gate_score: None,
                    report_gate_threshold: gate_threshold,
                    risk_gate_name: risk_gate_name.clone(),
                    risk_score: None,
                    risk_threshold: self.cfg.member_repair_risk_tau,
                    selected_left: Vec::new(),
                    selected_right: Vec::new(),
                    status: format!("feature_error:{error}"),
                    output_report: None,
                    moved_members: 0,
                    llm_oracle: None,
                });
                self.member_repair_wall_seconds += started.elapsed().as_secs_f64();
                return None;
            }
        };
        let populated_edge_count = edges.len();
        let left_embeddings = left_rows
            .iter()
            .map(|row| self.store.row(*row))
            .collect::<Vec<_>>();
        let right_embeddings = right_rows
            .iter()
            .map(|row| self.store.row(*row))
            .collect::<Vec<_>>();
        let proposal = match self
            .member_repair
            .as_ref()
            .expect("member repair architecture requires loaded artifact")
            .propose(
                architecture,
                edges,
                &left_embeddings,
                &right_embeddings,
                member_threshold,
            ) {
            Ok(proposal) => proposal,
            Err(error) => {
                self.member_repair_events.push(MemberRepairEvent {
                    trigger_signal: trigger_signal.to_string(),
                    timestamp,
                    architecture,
                    left_report,
                    right_report,
                    left_size: left_rows.len(),
                    right_size: right_rows.len(),
                    edge_cell_count,
                    populated_edge_count,
                    left_members,
                    right_members,
                    left_probabilities: Vec::new(),
                    right_probabilities: Vec::new(),
                    trigger_score,
                    member_threshold,
                    report_gate_name: gate_name.clone(),
                    report_gate_score: None,
                    report_gate_threshold: gate_threshold,
                    risk_gate_name: risk_gate_name.clone(),
                    risk_score: None,
                    risk_threshold: self.cfg.member_repair_risk_tau,
                    selected_left: Vec::new(),
                    selected_right: Vec::new(),
                    status: format!("inference_error:{error}"),
                    output_report: None,
                    moved_members: 0,
                    llm_oracle: None,
                });
                self.member_repair_wall_seconds += started.elapsed().as_secs_f64();
                return None;
            }
        };
        let mut selected_left: Vec<String> = proposal
            .left_probabilities
            .iter()
            .enumerate()
            .filter(|(_, probability)| **probability >= member_threshold)
            .map(|(index, _)| self.store.signal_ids[left_rows[index]].clone())
            .collect();
        let mut selected_right: Vec<String> = proposal
            .right_probabilities
            .iter()
            .enumerate()
            .filter(|(_, probability)| **probability >= member_threshold)
            .map(|(index, _)| self.store.signal_ids[right_rows[index]].clone())
            .collect();
        let gate_score = if self.cfg.member_repair_integrated_gates {
            proposal.action_probability
        } else {
            proposal
                .report_gate
                .get(&self.cfg.member_repair_report_gate)
                .copied()
        };
        let risk_score = if selected_left.is_empty() || selected_right.is_empty() {
            None
        } else if self.cfg.member_repair_integrated_gates {
            proposal.safety_probability
        } else {
            match self
                .member_repair
                .as_ref()
                .expect("member repair architecture requires loaded artifact")
                .operation_risk(architecture, &proposal, member_threshold)
            {
                Ok(scores) => scores.get(&self.cfg.member_repair_risk_gate).copied(),
                Err(error) => {
                    self.member_repair_events.push(MemberRepairEvent {
                        trigger_signal: trigger_signal.to_string(),
                        timestamp,
                        architecture,
                        left_report,
                        right_report,
                        left_size: left_rows.len(),
                        right_size: right_rows.len(),
                        edge_cell_count,
                        populated_edge_count: proposal.edges.len(),
                        left_members,
                        right_members,
                        left_probabilities: proposal.left_probabilities.clone(),
                        right_probabilities: proposal.right_probabilities.clone(),
                        trigger_score,
                        member_threshold,
                        report_gate_name: gate_name.clone(),
                        report_gate_score: gate_score,
                        report_gate_threshold: gate_threshold,
                        risk_gate_name: risk_gate_name.clone(),
                        risk_score: None,
                        risk_threshold: self.cfg.member_repair_risk_tau,
                        selected_left,
                        selected_right,
                        status: format!("risk_inference_error:{error}"),
                        output_report: None,
                        moved_members: 0,
                        llm_oracle: None,
                    });
                    self.member_repair_wall_seconds += started.elapsed().as_secs_f64();
                    return None;
                }
            }
        };
        let mut llm_oracle = None;
        let mut llm_oracle_rejected = false;
        let mut llm_oracle_error = None;
        if self.cfg.member_repair_llm_oracle {
            match self.judge_member_repair_with_llm(
                trigger_signal,
                trigger_score,
                &left_rows,
                &right_rows,
                &selected_left,
                &selected_right,
            ) {
                Ok(crate::member_repair_oracle::OracleChoice::Accept(audit)) => {
                    llm_oracle = Some(audit);
                }
                Ok(crate::member_repair_oracle::OracleChoice::Reject(audit)) => {
                    llm_oracle_rejected = true;
                    llm_oracle = Some(audit);
                }
                Ok(crate::member_repair_oracle::OracleChoice::Alternative(audit)) => {
                    selected_left = audit.selected_left.clone();
                    selected_right = audit.selected_right.clone();
                    llm_oracle = Some(audit);
                }
                Err(error) => {
                    llm_oracle_error = Some(error.to_string());
                }
            }
        }
        let status = if let Some(error) = llm_oracle_error.as_deref() {
            format!("llm_oracle_error:{error}")
        } else if llm_oracle_rejected {
            "rejected_llm_oracle".to_string()
        } else if self.cfg.member_repair_llm_oracle
            && (selected_left.is_empty() || selected_right.is_empty())
        {
            "rejected_one_sided_mask".to_string()
        } else if self.cfg.member_repair_llm_oracle && !self.cfg.member_repair_apply {
            "proposal_only".to_string()
        } else if self.cfg.member_repair_llm_oracle {
            "ready".to_string()
        } else if gate_score.is_none() {
            "missing_report_gate".to_string()
        } else if gate_score.is_some_and(|score| score < gate_threshold) {
            "rejected_report_gate".to_string()
        } else if selected_left.is_empty() || selected_right.is_empty() {
            "rejected_one_sided_mask".to_string()
        } else if self.cfg.member_repair_risk_tau.is_some() && risk_score.is_none() {
            "missing_risk_gate".to_string()
        } else if self
            .cfg
            .member_repair_risk_tau
            .is_some_and(|threshold| risk_score.is_some_and(|score| score < threshold))
        {
            "rejected_operation_risk".to_string()
        } else if !self.cfg.member_repair_apply {
            "proposal_only".to_string()
        } else {
            "ready".to_string()
        };
        if status != "ready" {
            self.member_repair_events.push(MemberRepairEvent {
                trigger_signal: trigger_signal.to_string(),
                timestamp,
                architecture,
                left_report,
                right_report,
                left_size: left_rows.len(),
                right_size: right_rows.len(),
                edge_cell_count,
                populated_edge_count: proposal.edges.len(),
                left_members,
                right_members,
                left_probabilities: proposal.left_probabilities.clone(),
                right_probabilities: proposal.right_probabilities.clone(),
                trigger_score,
                member_threshold,
                report_gate_name: gate_name.clone(),
                report_gate_score: gate_score,
                report_gate_threshold: gate_threshold,
                risk_gate_name: risk_gate_name.clone(),
                risk_score,
                risk_threshold: self.cfg.member_repair_risk_tau,
                selected_left,
                selected_right,
                status,
                output_report: None,
                moved_members: 0,
                llm_oracle,
            });
            self.member_repair_wall_seconds += started.elapsed().as_secs_f64();
            return None;
        }
        let left_ids: HashSet<String> = selected_left.iter().cloned().collect();
        let right_ids: HashSet<String> = selected_right.iter().cloned().collect();
        let left_full = selected_left.len() == left_rows.len();
        let right_full = selected_right.len() == right_rows.len();
        let (output_report, action, moved_members) = if left_full && right_full {
            let moved = right_rows.len();
            self.store.merge_reports(&right_report, &left_report);
            self.reports.merge(&right_report, &left_report);
            (left_report.clone(), "applied_whole_merge", moved)
        } else if left_full {
            let moved = self
                .store
                .move_members(&right_report, &left_report, &right_ids);
            if !self.store.rows_by_report.contains_key(&right_report) {
                self.reports.merge(&right_report, &left_report);
            }
            (left_report.clone(), "applied_into_left", moved)
        } else if right_full {
            let moved = self
                .store
                .move_members(&left_report, &right_report, &left_ids);
            if !self.store.rows_by_report.contains_key(&left_report) {
                self.reports.merge(&left_report, &right_report);
            }
            (right_report.clone(), "applied_into_right", moved)
        } else {
            let output = format!(
                "repair-{}-{}",
                self.member_repair_events.len(),
                &trigger_signal[..trigger_signal.len().min(20)]
            );
            let moved_left = self.store.move_members(&left_report, &output, &left_ids);
            let moved_right = self.store.move_members(&right_report, &output, &right_ids);
            (output, "applied_subset_extract", moved_left + moved_right)
        };
        self.member_repair_applied += 1;
        self.member_repair_events.push(MemberRepairEvent {
            trigger_signal: trigger_signal.to_string(),
            timestamp,
            architecture,
            left_report,
            right_report,
            left_size: left_rows.len(),
            right_size: right_rows.len(),
            edge_cell_count,
            populated_edge_count: proposal.edges.len(),
            left_members,
            right_members,
            left_probabilities: proposal.left_probabilities,
            right_probabilities: proposal.right_probabilities,
            trigger_score,
            member_threshold,
            report_gate_name: gate_name,
            report_gate_score: gate_score,
            report_gate_threshold: gate_threshold,
            risk_gate_name,
            risk_score,
            risk_threshold: self.cfg.member_repair_risk_tau,
            selected_left,
            selected_right,
            status: action.to_string(),
            output_report: Some(output_report.clone()),
            moved_members,
            llm_oracle,
        });
        if self.cfg.member_repair_split_after {
            self.eval_group_after_join(&output_report, trigger_signal);
        }
        self.member_repair_wall_seconds += started.elapsed().as_secs_f64();
        Some(
            self.reports.resolve(
                &self.store.report_ids[*self
                    .store
                    .row_by_signal_id
                    .get(trigger_signal)
                    .expect("trigger signal was stored before member repair")],
            ),
        )
    }

    fn try_merge(
        &mut self,
        signal_id: &str,
        signal_ts: f64,
        dst: &str,
        src: &str,
        trigger_p: f64,
    ) -> bool {
        if self.concern.is_none() {
            return false;
        }
        // blob guard (both proposal sources): merge verdicts on mixed mega-reports
        // are a contents lottery the gate cannot see from its 10-member sample
        let cap = self.cfg.centroid_max_report_size;
        if cap > 0 {
            let too_big = |rid: &str| {
                self.store
                    .rows_by_report
                    .get(rid)
                    .is_some_and(|r| r.len() > cap)
            };
            if too_big(dst) || too_big(src) {
                return false;
            }
        }
        let Some(view_own) = self.store.report_view(dst, 40, 10) else {
            return false;
        };
        let Some(view_other) = self.store.report_view(src, 40, 10) else {
            return false;
        };
        let xp = self.cross_pair_ps(
            dst,
            &view_own.content_rows,
            view_own.size,
            src,
            &view_other.content_rows,
            view_other.size,
        );
        // a = larger side by true size (split_features convention)
        let (va, vb) = if view_own.size >= view_other.size {
            (&view_own, &view_other)
        } else {
            (&view_other, &view_own)
        };
        let rows_a = va.content_rows.clone();
        let rows_b = vb.content_rows.clone();
        let mut feats = self.group_pair_feats(&xp, &rows_a, &rows_b, 2.0);
        let sig_aware = self
            .concern
            .as_ref()
            .is_some_and(|c| c.feature_names.iter().any(|n| n == "g_sig_coverage"));
        feats.extend(Self::merge_extras(
            &xp,
            rows_a.len(),
            rows_b.len(),
            va.size + vb.size,
            sig_aware,
        ));
        let gate_p = self.concern_p(&feats);
        let gamma = self
            .cfg
            .concern_merge_gamma
            .or(self.concern.as_ref().unwrap().gamma)
            .unwrap_or(0.855);
        if gate_p < gamma {
            return false;
        }
        self.merge_events.push(MergeEvent {
            signal_id: signal_id.to_string(),
            src: src.to_string(),
            dst: dst.to_string(),
            trigger_p,
            gate_p,
            timestamp: signal_ts,
        });
        self.store.merge_reports(src, dst);
        self.reports.merge(src, dst);
        true
    }

    /// Centroid merge proposer (design: Oliver): when a signal joins report R,
    /// compute R's member centroid in type-NORMALIZED space (last <=40 members,
    /// each minus its own type mean), re-project into every known type mean,
    /// search the store (visibility snapshot + window as the signal's own
    /// retrieval), and feed the distinct hit reports to the shared merge gate.
    fn centroid_propose(&mut self, report_id: &str, sig: &SignalIn, snapshot: usize) {
        let k = self.cfg.centroid_proposer_k;
        let cap = self.cfg.centroid_max_report_size;
        let Some(all_rows) = self.store.rows_by_report.get(report_id) else {
            return;
        };
        if cap > 0 && all_rows.len() > cap {
            return; // own report is blob-sized: proposals from it are a lottery
        }
        let rows: Vec<usize> = all_rows.iter().rev().take(40).copied().collect();
        if rows.is_empty() {
            return;
        }
        let dims = self.store.dims;
        let mut centroid = vec![0.0f64; dims];
        for &r in &rows {
            let e = self.store.row(r);
            let key = (
                self.store.source_products[r].clone(),
                self.store.source_types[r].clone(),
            );
            let mu = self.batch_means.get(&key);
            for i in 0..dims {
                centroid[i] += e[i] as f64 - mu.map_or(0.0, |m| m[i] as f64);
            }
        }
        let n = rows.len() as f64;
        for x in centroid.iter_mut() {
            *x /= n;
        }
        let norm: f64 = centroid.iter().map(|x| x * x).sum::<f64>().sqrt();
        if norm < 1e-9 {
            return;
        }
        let residual: Vec<f32> = centroid.iter().map(|x| (*x / norm) as f32).collect();
        // raw (type-neutral) query always included, then one per known type mean
        let mut queries: Vec<Vec<f32>> = vec![feats::normalize(&residual)];
        for mu in self.batch_means.values() {
            let q: Vec<f32> = residual.iter().zip(mu).map(|(r, m)| r + m).collect();
            queries.push(feats::normalize(&q));
        }
        let results = self.store.search_stacked(&queries, sig.ts, k, snapshot);
        let member_rows: HashSet<usize> = all_rows.iter().copied().collect();
        // rank distinct foreign reports by their closest hit
        let mut best_of: HashMap<String, f64> = HashMap::new();
        for cands in &results {
            for c in cands {
                if member_rows.contains(&c.row) {
                    continue;
                }
                let rid = self.reports.resolve(&c.report_id);
                if rid == report_id || rid.is_empty() {
                    continue;
                }
                let e = best_of.entry(rid).or_insert(f64::INFINITY);
                *e = e.min(c.distance);
            }
        }
        let mut ranked: Vec<(String, f64)> = best_of.into_iter().collect();
        ranked.sort_by(|a, b| a.1.partial_cmp(&b.1).unwrap().then(a.0.cmp(&b.0)));
        ranked.truncate(self.cfg.centroid_merge_topn);
        for (rid, dist) in ranked {
            let rid = self.reports.resolve(&rid); // an earlier proposal may have merged it
            if rid == self.reports.resolve(report_id) {
                continue;
            }
            if cap > 0
                && self
                    .store
                    .rows_by_report
                    .get(&rid)
                    .is_some_and(|r| r.len() > cap)
            {
                continue; // blob-sized target
            }
            // trigger_p slot records 1-distance: centroid proximity, not a pair p
            self.try_merge(&sig.id, sig.ts, report_id, &rid, 1.0 - dist);
        }
    }

    /// Sequential replay: every signal is its own batch, so each decision sees
    /// ALL prior state (snapshot = store.n) — the engine's canonical regime.
    /// The old replayer's batch machinery is reused with batch size 1: with a
    /// single-signal batch the dependency partition is one level and batch
    /// augmentation is a no-op, so the decision flow is unchanged.
    ///
    /// With cfg.precompute_retrieval (default on), the retrieval phase — which
    /// in sequential semantics depends only on STREAM ORDER, never on decisions
    /// — is precomputed for all signals in a parallel pass; the sequential loop
    /// then consumes the stored hits instead of searching. Byte-identical to
    /// the live-search path (verified on tune); report-dependent evidence
    /// (candidate report ids, join/group features, digests, gate) stays live.
    pub fn run_sequential(
        &mut self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
        mut on_progress: impl FnMut(usize, usize, usize, usize, usize),
    ) {
        assert_eq!(
            signals.len(),
            embeddings.rows,
            "signals and embeddings must be stream-aligned"
        );
        let n = signals.len();
        if self.cfg.precompute_retrieval {
            let retrieval_started = std::time::Instant::now();
            let hits = Arc::new(self.load_or_precompute_branch_retrieval(signals, embeddings));
            self.precomputed_retrieval = Some(Arc::clone(&hits));
            self.retrieval_wall_seconds += retrieval_started.elapsed().as_secs_f64();
            eprintln!(
                "engine: retrieval precomputed for {n} signals in {:.1}s",
                self.retrieval_wall_seconds
            );
            let decision_started = std::time::Instant::now();
            for i in 0..n {
                self.process_batch_precomputed(signals, embeddings, i, &hits[i]);
                on_progress(
                    i + 1,
                    n,
                    self.store.rows_by_report.len(),
                    self.merge_events.len(),
                    self.split_events.len(),
                );
            }
            self.decision_wall_seconds += decision_started.elapsed().as_secs_f64();
            return;
        }
        self.precomputed_retrieval = None;
        let decision_started = std::time::Instant::now();
        for i in 0..n {
            self.process_batch(signals, embeddings, i, &[i]);
            on_progress(
                i + 1,
                n,
                self.store.rows_by_report.len(),
                self.merge_events.len(),
                self.split_events.len(),
            );
        }
        self.decision_wall_seconds += decision_started.elapsed().as_secs_f64();
    }

    /// Complete-suffix ranking branches share exactly the same stream-ordered
    /// retrieval. Persist it once so each causal intervention pays only the
    /// decision-dependent suffix cost. Validation sweeps can explicitly reuse
    /// it too, while ordinary pipeline replays remain uncached.
    fn load_or_precompute_branch_retrieval(
        &self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
    ) -> Vec<RetrievalHits> {
        if self.cfg.groupjoin_forced_query.is_none() && !self.cfg.reuse_precomputed_retrieval_cache
        {
            return self.precompute_retrieval(signals, embeddings);
        }
        let cache_name = format!(
            ".branch-retrieval-v1-n{}-d{}-k{}-id{}-w{:016x}.json",
            signals.len(),
            embeddings.cols,
            self.cfg.search_limit,
            self.cfg.id_lane_limit,
            self.cfg.search_window_days.to_bits(),
        );
        let cache_path = std::path::Path::new(&self.cfg.corpus_dir).join(cache_name);
        if let Ok(bytes) = std::fs::read(&cache_path) {
            if let Ok(hits) = serde_json::from_slice::<Vec<RetrievalHits>>(&bytes) {
                if hits.len() == signals.len() {
                    eprintln!(
                        "engine: loaded branch retrieval cache {}",
                        cache_path.display()
                    );
                    return hits;
                }
            }
        }
        let hits = self.precompute_retrieval(signals, embeddings);
        if let Ok(bytes) = serde_json::to_vec(&hits) {
            let temporary = cache_path.with_extension(format!("{}.tmp", std::process::id()));
            if std::fs::write(&temporary, bytes).is_ok() {
                let _ = std::fs::rename(&temporary, &cache_path);
            }
        }
        hits
    }

    /// Precompute per-signal retrieval hits (rows + distances + lane labels +
    /// neighborhood scale — everything the search phase produces) for the whole
    /// stream, in parallel. Valid because in sequential semantics retrieval
    /// reads only stream-ordered state: type means read stored signals (not
    /// reports), search visibility is `!report_id.is_empty()` which every live
    /// row satisfies (matched, "lab-", "split-", merged — all non-empty), and
    /// id postings accrete per stored row. Candidate report ids ARE decision-
    /// dependent (store-time ids rewritten by merges/splits), so hits store row
    /// indexes only; report ids are read from the live store at decision time,
    /// exactly as a live search would have cloned them.
    fn precompute_retrieval(
        &self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
    ) -> Vec<RetrievalHits> {
        use rayon::prelude::*;
        // shadow store, seeded in STREAM ORDER (row j == live row j). The live
        // store normalizes prep.embedding (itself normalize(raw)) at store time,
        // so seed with normalize(raw) and let store() renormalize — the matrix
        // must be bit-identical to the live one.
        let mut shadow = EmbeddingStore::new(self.store.dims);
        shadow.window_secs = self.cfg.search_window_days * 86400.0;
        for (i, s) in signals.iter().enumerate() {
            let e = feats::normalize(embeddings.row(i));
            // placeholder report id: non-empty = searchable, like every live row
            shadow.store(
                s.id.clone(),
                s.content.clone(),
                &e,
                s.id.clone(),
                s.product.clone(),
                s.source_type.clone(),
                s.source_id.clone(),
                s.ts,
                None,
            );
        }
        // full id postings (id_lane filters rows to < snapshot itself)
        let mut postings: HashMap<String, Vec<usize>> = HashMap::new();
        if self.cfg.id_lane_limit > 0 {
            let extracted: Vec<IdSets> = signals
                .par_iter()
                .map(|s| extract_identifiers(&s.content))
                .collect();
            for (row, ids) in extracted.iter().enumerate() {
                for vals in ids.values() {
                    for v in vals {
                        postings.entry(v.clone()).or_default().push(row);
                    }
                }
            }
        }
        let n = signals.len();
        let mut hits: Vec<RetrievalHits> = Vec::with_capacity(n);
        const CHUNK: usize = 256;
        let mut start = 0usize;
        while start < n {
            let end = (start + CHUNK).min(n);
            // type means need &mut shadow (range cache) — serial, cheap; the
            // cached means are bit-identical to a fresh computation
            let means: Vec<HashMap<(String, String), Vec<f32>>> = (start..end)
                .map(|i| shadow.type_means(signals[i].ts, i))
                .collect();
            let chunk_hits: Vec<RetrievalHits> = (start..end)
                .into_par_iter()
                .map(|i| {
                    let e = feats::normalize(embeddings.row(i));
                    let (query_labels, _query_embeddings, ch_results, neigh_scale) =
                        Self::search_signal(
                            &self.cfg,
                            &shadow,
                            &means[i - start],
                            &postings,
                            &signals[i],
                            &e,
                            i,
                        );
                    RetrievalHits {
                        query_labels,
                        lanes: ch_results
                            .into_iter()
                            .map(|cands| {
                                cands
                                    .into_iter()
                                    .map(|c| (c.row as u32, c.distance))
                                    .collect()
                            })
                            .collect(),
                        neigh_scale,
                    }
                })
                .collect();
            hits.extend(chunk_hits);
            start = end;
        }
        hits
    }

    /// Sequential single-signal batch consuming precomputed retrieval hits: the
    /// decision phase (candidate scoring, join, gate, merges, splits) is the
    /// same live code; only the searches are replaced by the stored hits.
    fn process_batch_precomputed(
        &mut self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
        batch_index: usize,
        hits: &RetrievalHits,
    ) {
        let snapshot = self.store.n; // pre-batch visibility boundary (CH lag)
        let sig = signals[batch_index].clone();
        // still needed live: decision-phase featurizers read self.batch_means
        self.batch_means = self.store.type_means(sig.ts, snapshot);
        let e = feats::normalize(embeddings.row(batch_index));
        let ch_results: Vec<Vec<Candidate>> = hits
            .lanes
            .iter()
            .map(|lane| {
                lane.iter()
                    .map(|&(row, distance)| {
                        let row = row as usize;
                        Candidate {
                            row,
                            signal_id: self.store.signal_ids[row].clone(),
                            // current store-time id, as a live search would clone it
                            report_id: self.store.report_ids[row].clone(),
                            distance,
                        }
                    })
                    .collect()
            })
            .collect();
        self.batch_scales.insert(sig.id.clone(), hits.neigh_scale);
        let prep = PreparedSignal {
            signal: sig,
            embedding: e,
            // query vectors are only consulted by multi-signal batch machinery
            // (dependency partition / augmentation), both no-ops at batch size 1
            query_embeddings: Vec::new(),
            query_labels: hits.query_labels.clone(),
            ch_results,
            neigh_scale: hits.neigh_scale,
            snapshot,
        };
        // single-signal batch: one level, augmentation is the identity
        let decision = self.process_one(&prep, &prep.ch_results, batch_index, 0);
        self.decisions.push(decision);
    }

    fn process_batch(
        &mut self,
        signals: &[SignalIn],
        embeddings: &crate::npy::Matrix,
        batch_index: usize,
        batch_rows: &[usize],
    ) {
        let snapshot = self.store.n; // pre-batch visibility boundary (CH lag)
        let now = batch_rows
            .iter()
            .map(|&i| signals[i].ts)
            .fold(f64::NEG_INFINITY, f64::max);
        self.batch_means = self.store.type_means(now, snapshot);

        // === PARALLEL PHASE: residual-projection retrieval, pinned to snapshot ===
        let mut prepared: Vec<PreparedSignal> = Vec::with_capacity(batch_rows.len());
        for &i in batch_rows {
            let sig = signals[i].clone();
            let e = feats::normalize(embeddings.row(i));
            let (query_labels, query_embeddings, ch_results, neigh_scale) = Self::search_signal(
                &self.cfg,
                &self.store,
                &self.batch_means,
                &self.id_postings,
                &sig,
                &e,
                snapshot,
            );
            self.batch_scales.insert(sig.id.clone(), neigh_scale);
            prepared.push(PreparedSignal {
                signal: sig,
                embedding: e,
                query_labels,
                query_embeddings,
                ch_results,
                neigh_scale,
                snapshot,
            });
        }

        // === dependency partition into levels (limit 10, as in Python) ===
        let levels = Self::partition_levels(&prepared, self.cfg.augment_limit);

        // === SEQUENTIAL PHASE ===
        let mut processed: Vec<ProcessedBatchSignal> = Vec::new();
        for (level, indices) in levels.iter().enumerate() {
            // augmentation snapshot is taken before the level runs (Python evaluates
            // the augment expression when building the gather list)
            let augmented: Vec<Vec<Vec<Candidate>>> = indices
                .iter()
                .map(|&idx| {
                    Self::augment(
                        &prepared[idx].query_embeddings,
                        &prepared[idx].ch_results,
                        &processed,
                        &self.store,
                        self.cfg.augment_limit,
                    )
                })
                .collect();
            for (k, &idx) in indices.iter().enumerate() {
                let decision = self.process_one(&prepared[idx], &augmented[k], batch_index, level);
                let row = self.store.n - 1; // just stored
                processed.push(ProcessedBatchSignal {
                    signal_id: prepared[idx].signal.id.clone(),
                    report_id: decision.run_report_id.clone(),
                    row,
                    embedding: prepared[idx].embedding.clone(),
                });
                self.decisions.push(decision);
            }
        }
    }

    /// The retrieval (search) phase for one signal: residual projections over the
    /// type means + stacked search + neighborhood scale + best-distance ordering
    /// + optional identifier lane. Takes the store/means/postings explicitly so
    /// the live loop and the retrieval-precompute pass run the exact same code
    /// (`store` is the live store or a full-corpus shadow seeded in stream order).
    fn search_signal(
        cfg: &Config,
        store: &EmbeddingStore,
        means: &HashMap<(String, String), Vec<f32>>,
        id_postings: &HashMap<String, Vec<usize>>,
        sig: &SignalIn,
        e: &[f32],
        snapshot: usize,
    ) -> (Vec<String>, Vec<Vec<f32>>, Vec<Vec<Candidate>>, f64) {
        let own_key = (sig.product.clone(), sig.source_type.clone());
        let own_mean = means.get(&own_key);
        let residual: Vec<f32> = match own_mean {
            Some(m) => e
                .iter()
                .zip(m)
                .map(|(a, b)| ((*a as f64) - (*b as f64)) as f32)
                .collect(),
            None => e.to_vec(),
        };
        // the raw query must always be among the projections
        let mut projections: Vec<((String, String), Vec<f32>)> = Vec::new();
        if own_mean.is_none() {
            projections.push((
                (
                    "raw".to_string(),
                    format!("{}/{}", sig.product, sig.source_type),
                ),
                e.to_vec(),
            ));
        }
        let mut keys: Vec<&(String, String)> = means.keys().collect();
        keys.sort(); // HashMap order is nondeterministic; sorted for reproducibility
        for key in keys {
            let mean = &means[key];
            let v: Vec<f32> = residual
                .iter()
                .zip(mean)
                .map(|(a, b)| ((*a as f64) + (*b as f64)) as f32)
                .collect();
            projections.push((key.clone(), v));
        }
        let vectors: Vec<Vec<f32>> = projections.iter().map(|(_k, v)| v.clone()).collect();
        let stacked = store.search_stacked(&vectors, sig.ts, cfg.search_limit, snapshot);
        // neighborhood scale: own raw top-10 distance at insert time (10th NN regardless of K)
        let raw_results = projections
            .iter()
            .zip(&stacked)
            .find(|((key, _v), _res)| key.0 == "raw" || (key.0 == own_key.0 && key.1 == own_key.1))
            .map(|(_kv, res)| res.clone())
            .unwrap_or_default();
        let neigh_scale = if raw_results.len() >= 10 {
            raw_results[9].distance
        } else {
            1.0
        };
        // sort projections by best candidate distance; classifier keeps all
        let mut searched: Vec<((String, String), Vec<f32>, Vec<Candidate>)> = projections
            .into_iter()
            .zip(stacked)
            .map(|((k, v), res)| (k, v, res))
            .collect();
        searched.sort_by(|a, b| {
            let da = a.2.first().map_or(f64::INFINITY, |c| c.distance);
            let db = b.2.first().map_or(f64::INFINITY, |c| c.distance);
            da.partial_cmp(&db).unwrap()
        });
        let mut query_labels = Vec::with_capacity(searched.len() + 1);
        let mut query_embeddings = Vec::with_capacity(searched.len() + 1);
        let mut ch_results = Vec::with_capacity(searched.len() + 1);
        for (key, vector, candidates) in searched {
            query_labels.push(format!("residual→{}/{}", key.0, key.1));
            query_embeddings.push(vector);
            ch_results.push(candidates);
        }
        if cfg.id_lane_limit > 0 {
            let lane = Self::id_lane(store, id_postings, cfg.id_lane_limit, sig, e, snapshot);
            if !lane.is_empty() {
                query_labels.push("ids/lookup".to_string());
                query_embeddings.push(e.to_vec());
                ch_results.push(lane);
            }
        }
        (query_labels, query_embeddings, ch_results, neigh_scale)
    }

    fn partition_levels(prepared: &[PreparedSignal], limit: usize) -> Vec<Vec<usize>> {
        let n = prepared.len();
        let mut levels = vec![0usize; n];
        for j in 1..n {
            let mut max_dep_level: Option<usize> = None;
            for i in 0..j {
                if Self::would_be_candidate(
                    &prepared[j].query_embeddings,
                    &prepared[j].ch_results,
                    &prepared[i].embedding,
                    limit,
                ) {
                    max_dep_level =
                        Some(max_dep_level.map_or(levels[i], |m: usize| m.max(levels[i])));
                }
            }
            if let Some(m) = max_dep_level {
                levels[j] = m + 1;
            }
        }
        let max_level = levels.iter().copied().max().unwrap_or(0);
        let mut out = vec![Vec::new(); max_level + 1];
        for (idx, &l) in levels.iter().enumerate() {
            out[l].push(idx);
        }
        out
    }

    /// identifier lane: candidates sharing a rare identifier with the query,
    /// visibility-pinned like every other search, ranked by cosine distance.
    fn id_lane(
        store: &EmbeddingStore,
        id_postings: &HashMap<String, Vec<usize>>,
        limit: usize,
        sig: &SignalIn,
        e: &[f32],
        snapshot: usize,
    ) -> Vec<Candidate> {
        const MAX_POSTING: usize = 100; // ubiquitous identifiers carry no signal
        let ids = extract_identifiers(&sig.content);
        let window_start = sig.ts - store.window_secs;
        let mut rows: HashSet<usize> = HashSet::new();
        for vals in ids.values() {
            for v in vals {
                if let Some(post) = id_postings.get(v) {
                    // postings ascend by row; the ubiquity gate must see only
                    // rows stored before `snapshot` — in the live loop that is
                    // the whole list, in the retrieval-precompute pass the list
                    // covers the full stream and the visible prefix is the
                    // as-of-snapshot posting the live gate would have seen
                    let vis = post.partition_point(|&r| r < snapshot);
                    if vis <= MAX_POSTING {
                        rows.extend(post[..vis].iter().copied().filter(|&r| {
                            !store.report_ids[r].is_empty()
                                && store.timestamps[r] >= window_start
                                && store.timestamps[r] <= sig.ts
                        }));
                    }
                }
            }
        }
        let mut cands: Vec<Candidate> = rows
            .into_iter()
            .map(|r| Candidate {
                row: r,
                signal_id: store.signal_ids[r].clone(),
                report_id: store.report_ids[r].clone(),
                distance: (1.0 - feats::dot(store.row(r), e)).max(0.0),
            })
            .collect();
        cands.sort_by(|a, b| {
            a.distance
                .partial_cmp(&b.distance)
                .unwrap()
                .then(a.row.cmp(&b.row))
        });
        cands.truncate(limit);
        cands
    }

    fn cosine_distance(a: &[f32], b: &[f32]) -> f64 {
        let na = feats::norm(a);
        let nb = feats::norm(b);
        if na == 0.0 || nb == 0.0 {
            return 1.0;
        }
        1.0 - feats::dot(a, b) / (na * nb)
    }

    fn would_be_candidate(
        query_embeddings: &[Vec<f32>],
        ch_results: &[Vec<Candidate>],
        embedding: &[f32],
        limit: usize,
    ) -> bool {
        for (q, cands) in query_embeddings.iter().zip(ch_results) {
            let worst = cands.last().map_or(f64::INFINITY, |c| c.distance);
            let dist = Self::cosine_distance(q, embedding);
            if cands.len() < limit || dist < worst {
                return true;
            }
        }
        false
    }

    fn augment(
        query_embeddings: &[Vec<f32>],
        ch_results: &[Vec<Candidate>],
        processed: &[ProcessedBatchSignal],
        store: &EmbeddingStore,
        limit: usize,
    ) -> Vec<Vec<Candidate>> {
        if processed.is_empty() {
            return ch_results.to_vec();
        }
        let mut out = Vec::with_capacity(ch_results.len());
        for (q, cands0) in query_embeddings.iter().zip(ch_results) {
            let mut cands = cands0.clone();
            let worst = cands.last().map_or(f64::INFINITY, |c| c.distance);
            for ps in processed {
                let dist = Self::cosine_distance(q, &ps.embedding);
                if cands.len() < limit || dist < worst {
                    cands.push(Candidate {
                        row: ps.row,
                        signal_id: ps.signal_id.clone(),
                        // batch-processed rows carry the report id assigned at decision
                        // time (store-time id); resolution happens at scoring time
                        report_id: store
                            .report_ids
                            .get(ps.row)
                            .cloned()
                            .unwrap_or_else(|| ps.report_id.clone()),
                        distance: dist,
                    });
                }
            }
            cands.sort_by(|a, b| {
                a.distance
                    .partial_cmp(&b.distance)
                    .unwrap()
                    .then(a.row.cmp(&b.row))
            });
            cands.truncate(limit);
            out.push(cands);
        }
        out
    }

    fn process_one(
        &mut self,
        prep: &PreparedSignal,
        augmented: &[Vec<Candidate>],
        batch_index: usize,
        level: usize,
    ) -> Decision {
        let sig = &prep.signal;
        let q_type = (sig.product.as_str(), sig.source_type.as_str());
        let own_labels = [
            format!("residual→{}/{}", sig.product, sig.source_type),
            format!("residual→raw/{}/{}", sig.product, sig.source_type),
        ];
        // retrieval metadata accumulation (features.retrieval_metadata)
        let mut rmeta: HashMap<String, RetrievalMeta> = HashMap::new();
        for (label, cands) in prep.query_labels.iter().zip(augmented) {
            let is_own = own_labels.contains(label);
            for (rank, c) in cands.iter().enumerate() {
                let m = rmeta.entry(c.signal_id.clone()).or_insert(RetrievalMeta {
                    n_projections: 0.0,
                    best_rank: (rank + 1) as f64,
                    best_distance: c.distance,
                    own_type: 0.0,
                });
                m.n_projections += 1.0;
                m.best_rank = m.best_rank.min((rank + 1) as f64);
                m.best_distance = m.best_distance.min(c.distance);
                if is_own {
                    m.own_type = 1.0;
                }
            }
        }
        // candidates_by_id: first occurrence wins (insertion order across projections)
        let mut candidates_by_id: Vec<Candidate> = Vec::new();
        let mut seen: HashSet<String> = HashSet::new();
        for cands in augmented {
            for c in cands {
                if seen.insert(c.signal_id.clone()) {
                    candidates_by_id.push(c.clone());
                }
            }
        }

        let ids_q = extract_identifiers(&sig.content);
        let text_q = TextStats::compute(&sig.content);
        let burst_q = self.burst.count(&sig.product, &sig.source_type, sig.ts);
        let neigh_q = prep.neigh_scale;

        let cand_rows: Vec<usize> = candidates_by_id.iter().map(|c| c.row).collect();
        self.warm_ids(&cand_rows);
        let scored: Vec<(f64, f64)> = {
            use rayon::prelude::*;
            candidates_by_id
                .par_iter()
                .map(|c| {
                    self.score_pair_vs_row_ro(
                        &prep.embedding,
                        q_type,
                        sig.ts,
                        &sig.content,
                        &sig.source_id,
                        &ids_q,
                        burst_q,
                        neigh_q,
                        self.sigs.get(&sig.id),
                        &text_q,
                        c.row,
                        rmeta.get(&c.signal_id),
                    )
                })
                .collect()
        };
        let mut raw_ps: Vec<f64> = scored.iter().map(|s| s.0).collect();
        let mut cal_ps: Vec<f64> = scored.iter().map(|s| s.1).collect();

        // argmax by calibrated p, raw as tie-break, LAST index among full ties (np.lexsort)
        let mut best_i: Option<usize> = None;
        for i in 0..cal_ps.len() {
            match best_i {
                None => best_i = Some(i),
                Some(b) => {
                    if (cal_ps[i], raw_ps[i]) >= (cal_ps[b], raw_ps[b]) {
                        best_i = Some(i);
                    }
                }
            }
        }
        let tau = self
            .cfg
            .classifier_tau
            .or(self.pair.as_ref().and_then(|p| p.tau))
            .unwrap_or(0.8);
        let (mut best_p, mut best_raw) = best_i.map_or((0.0, 0.0), |i| (cal_ps[i], raw_ps[i]));
        let mut pair_pass = match self.cfg.classifier_raw_tau {
            Some(rt) => best_raw >= rt,
            None => best_p >= tau,
        };
        let mut tau_note = self
            .cfg
            .classifier_raw_tau
            .map_or(String::new(), |rt| format!(", raw_tau={rt:.3}"));

        // gj experiment: the ONE-MODEL groupwise matcher replaces the pairwise
        // argmax + tau — candidates collapse to distinct reports, each (signal,
        // group) is scored directly, argmax joins if >= gj_tau. Downstream
        // (join execution, concern splits) is untouched.
        let groupjoin_active = self.groupjoin.is_some()
            || self.groupjoin_neural.is_some()
            || self.contextual_groupjoin.is_some();
        let mut groupjoin_report_scores: Option<HashMap<String, f64>> = None;
        let mut decision_candidate_report_states = Vec::new();
        let mut forced_report_choice = false;
        if groupjoin_active {
            let mut groups: Vec<(String, usize, usize)> = Vec::new(); // rid, best rank, n retrieved
            let mut seen_g: HashMap<String, usize> = HashMap::new();
            for (i, c) in candidates_by_id.iter().enumerate() {
                let rid = self.reports.resolve(&c.report_id);
                match seen_g.get(&rid) {
                    Some(&gi) => groups[gi].2 += 1,
                    None => {
                        seen_g.insert(rid.clone(), groups.len());
                        groups.push((rid, i, 1));
                    }
                }
            }
            let qprod = sig.product.clone();
            let qtype = sig.source_type.clone();
            let feature_started = std::time::Instant::now();
            let mut candidates = Vec::with_capacity(groups.len());
            for (rid, rank, count) in &groups {
                if let Some(candidate) = self.gj_candidate(
                    &prep.embedding,
                    &sig.id,
                    &ids_q,
                    sig.ts,
                    &qprod,
                    &qtype,
                    rid,
                    *rank,
                    *count,
                    &cand_rows,
                ) {
                    candidates.push((rid.clone(), *rank, *count, candidate));
                }
            }
            if self.cfg.emit_candidate_report_states {
                decision_candidate_report_states = candidates
                    .iter()
                    .map(|(report_id, rank_best, n_retrieved, candidate)| {
                        DecisionCandidateReportState {
                            report_id: report_id.clone(),
                            members: candidate.members.clone(),
                            contextual_members: candidate.contextual_members.clone(),
                            all_members: candidate.all_members.clone(),
                            n_members: candidate.n_members,
                            rank_best: *rank_best,
                            n_retrieved: *n_retrieved,
                            retrieved_witnesses: candidate.retrieved_witnesses.clone(),
                            external_members: candidate.external_members.clone(),
                            behavior_raw: None,
                            ranking_raw: None,
                            preference_risk: None,
                            match_raw: None,
                            coherence_raw: None,
                            admission_raw: None,
                        }
                    })
                    .collect();
            }
            if self.groupjoin_neural.is_some() || self.contextual_groupjoin.is_some() {
                self.neural_groupjoin_feature_seconds += feature_started.elapsed().as_secs_f64();
            }
            let mut group_scores: Vec<(f64, f64)> = Vec::with_capacity(candidates.len());
            let mut group_match: Vec<Option<f64>> = Vec::with_capacity(candidates.len());
            let mut group_coherence: Vec<Option<f64>> = Vec::with_capacity(candidates.len());
            let mut group_admission: Vec<Option<f64>> = Vec::with_capacity(candidates.len());
            if candidates.is_empty() {
                // Match the legacy groupjoin loop: no scoreable report means
                // create a report without invoking a model.
            } else if let Some(contextual) = &self.contextual_groupjoin {
                let report_batches = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| candidate.tokens.as_slice())
                    .collect::<Vec<_>>();
                let external_batches = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| candidate.external_tokens.as_slice())
                    .collect::<Vec<_>>();
                let engineered = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| &candidate.features)
                    .collect::<Vec<_>>();
                let started = std::time::Instant::now();
                let outputs = contextual
                    .infer(&report_batches, &external_batches, &engineered)
                    .expect("exact contextual groupjoin inference failed");
                self.neural_groupjoin_wall_seconds += started.elapsed().as_secs_f64();
                self.neural_groupjoin_batches += 1;
                self.neural_groupjoin_candidate_reports += outputs.len();
                match self
                    .cfg
                    .groupjoin_neural_mode
                    .unwrap_or(crate::config::GroupJoinNeuralMode::Direct)
                {
                    crate::config::GroupJoinNeuralMode::Direct => {
                        group_scores
                            .extend(outputs.iter().map(|output| (output.raw, output.calibrated)));
                        group_match.extend(outputs.iter().map(|output| Some(output.raw)));
                        group_coherence.extend(outputs.iter().map(|output| output.coherence_raw));
                        group_admission.extend(outputs.iter().map(|output| output.admission_raw));
                    }
                    crate::config::GroupJoinNeuralMode::Stack => {
                        let tree = self
                            .groupjoin
                            .as_ref()
                            .expect("contextual neural stack mode requires a groupjoin tree");
                        for ((_, _, _, candidate), output) in candidates.iter_mut().zip(outputs) {
                            group_coherence.push(output.coherence_raw);
                            group_admission.push(output.admission_raw);
                            group_match.push(Some(output.raw));
                            candidate
                                .features
                                .insert(CONTEXTUAL_MATCH_RAW_FEATURE, output.raw);
                            if let Some(coherence_raw) = output.coherence_raw {
                                candidate
                                    .features
                                    .insert(CONTEXTUAL_COHERENCE_RAW_FEATURE, coherence_raw);
                            }
                            if let Some(admission_raw) = output.admission_raw {
                                candidate
                                    .features
                                    .insert(CONTEXTUAL_ADMISSION_RAW_FEATURE, admission_raw);
                            }
                            for (name, value) in
                                CONTEXTUAL_DSM_FEATURE_NAMES.iter().zip(output.pooled)
                            {
                                candidate.features.insert(name, value);
                            }
                            let x = tree.vectorize(&candidate.features);
                            group_scores.push(tree.predict(&x));
                        }
                    }
                }
            } else if let Some(neural) = &self.groupjoin_neural {
                let token_batches = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| candidate.tokens.as_slice())
                    .collect::<Vec<_>>();
                let query_embeddings = candidates
                    .iter()
                    .map(|_| prep.embedding.as_slice())
                    .collect::<Vec<_>>();
                let member_embeddings = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| candidate.member_embeddings.as_slice())
                    .collect::<Vec<_>>();
                let engineered = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| &candidate.features)
                    .collect::<Vec<_>>();
                let started = std::time::Instant::now();
                let outputs = neural
                    .infer(
                        &token_batches,
                        &query_embeddings,
                        &member_embeddings,
                        &engineered,
                    )
                    .expect("exact neural groupjoin inference failed");
                self.neural_groupjoin_wall_seconds += started.elapsed().as_secs_f64();
                self.neural_groupjoin_batches += 1;
                self.neural_groupjoin_candidate_reports += outputs.len();
                match self
                    .cfg
                    .groupjoin_neural_mode
                    .expect("neural groupjoin manifest requires groupjoin_neural_mode")
                {
                    crate::config::GroupJoinNeuralMode::Direct => {
                        group_scores
                            .extend(outputs.iter().map(|output| (output.raw, output.calibrated)));
                        group_match.extend(outputs.iter().map(|_| None));
                        group_coherence.extend(outputs.iter().map(|_| None));
                        group_admission.extend(outputs.iter().map(|_| None));
                    }
                    crate::config::GroupJoinNeuralMode::Stack => {
                        let tree = self
                            .groupjoin
                            .as_ref()
                            .expect("neural stack mode requires a groupjoin tree");
                        for ((_, _, _, candidate), output) in candidates.iter_mut().zip(outputs) {
                            group_coherence.push(None);
                            group_admission.push(None);
                            group_match.push(None);
                            candidate
                                .features
                                .insert(NEURAL_MATCH_RAW_FEATURE, output.raw);
                            for (name, value) in DSM_FEATURE_NAMES.iter().zip(output.pooled) {
                                candidate.features.insert(name, value);
                            }
                            let x = tree.vectorize(&candidate.features);
                            group_scores.push(tree.predict(&x));
                        }
                    }
                }
            } else {
                let tree = self
                    .groupjoin
                    .as_ref()
                    .expect("tree groupjoin mode requires a groupjoin model");
                group_scores.extend(candidates.iter().map(|(_, _, _, candidate)| {
                    let x = tree.vectorize(&candidate.features);
                    tree.predict(&x)
                }));
                group_coherence.resize(candidates.len(), None);
                group_admission.resize(candidates.len(), None);
                group_match.resize(candidates.len(), None);
            }
            let gj_tau = self
                .cfg
                .gj_tau
                .or(self.groupjoin.as_ref().and_then(|g| g.tau))
                .unwrap_or(0.5);
            let neural_rank_scores = if let Some(neural_ranker) = &self.groupjoin_ranker_neural {
                if candidates.is_empty() {
                    Some(Vec::new())
                } else {
                    let token_batches = candidates
                        .iter()
                        .map(|(_, _, _, candidate)| candidate.tokens.as_slice())
                        .collect::<Vec<_>>();
                    let query_embeddings = candidates
                        .iter()
                        .map(|_| prep.embedding.as_slice())
                        .collect::<Vec<_>>();
                    let member_embeddings = candidates
                        .iter()
                        .map(|(_, _, _, candidate)| candidate.member_embeddings.as_slice())
                        .collect::<Vec<_>>();
                    let engineered = candidates
                        .iter()
                        .map(|(_, _, _, candidate)| &candidate.features)
                        .collect::<Vec<_>>();
                    let started = std::time::Instant::now();
                    let outputs = neural_ranker
                        .infer(
                            &token_batches,
                            &query_embeddings,
                            &member_embeddings,
                            &engineered,
                        )
                        .expect("exact neural groupjoin ranker inference failed");
                    self.neural_ranker_wall_seconds += started.elapsed().as_secs_f64();
                    self.neural_ranker_batches += 1;
                    self.neural_ranker_candidate_reports += outputs.len();
                    Some(outputs.into_iter().map(|output| output.raw).collect())
                }
            } else {
                None
            };
            let preference_incumbent = (self.groupjoin_pair_ranker.is_some()
                || self.groupjoin_report_preference.is_some())
            .then(|| {
                candidates
                    .iter()
                    .zip(group_scores.iter().copied())
                    .enumerate()
                    .filter(|(candidate_index, (_, (raw, cal)))| {
                        let coherence_pass = self.cfg.gj_coherence_raw_tau.is_none_or(|tau| {
                            group_coherence[*candidate_index].is_some_and(|score| score >= tau)
                        });
                        let admission_pass = candidates[*candidate_index].3.n_members
                            < self.cfg.gj_admission_min_report_size
                            || self.cfg.gj_admission_raw_tau.is_none_or(|tau| {
                                group_admission[*candidate_index].is_some_and(|score| score >= tau)
                            });
                        let ranking_admission_pass =
                            !self.cfg.groupjoin_ranker_admission_eligible_only
                                || self
                                    .cfg
                                    .gj_raw_tau
                                    .map_or(*cal >= gj_tau, |tau| *raw >= tau);
                        coherence_pass && admission_pass && ranking_admission_pass
                    })
                    .max_by(|(_, (_, left)), (_, (_, right))| {
                        left.1
                            .total_cmp(&right.1)
                            .then_with(|| left.0.total_cmp(&right.0))
                    })
                    .map(|(candidate_index, _)| candidate_index)
            })
            .flatten();
            let mut preference_risk_scores: Option<Vec<Option<f64>>> = None;
            let group_rank_scores = if let (Some(preference), Some(incumbent_index)) =
                (&self.groupjoin_report_preference, preference_incumbent)
            {
                let threshold = self
                    .cfg
                    .groupjoin_report_preference_tau
                    .expect("neural report preference requires a threshold");
                let challenger_tokens = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| candidate.tokens.as_slice())
                    .collect::<Vec<_>>();
                let challenger_embeddings = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| candidate.member_embeddings.as_slice())
                    .collect::<Vec<_>>();
                let challenger_engineered = candidates
                    .iter()
                    .map(|(_, _, _, candidate)| &candidate.features)
                    .collect::<Vec<_>>();
                let challenger_admission = group_scores
                    .iter()
                    .map(|(raw, _calibrated)| *raw)
                    .collect::<Vec<_>>();
                let incumbent = &candidates[incumbent_index].3;
                let started = std::time::Instant::now();
                let outputs = preference
                    .infer(
                        &prep.embedding,
                        &challenger_tokens,
                        &challenger_embeddings,
                        &challenger_engineered,
                        &challenger_admission,
                        &incumbent.tokens,
                        &incumbent.member_embeddings,
                        &incumbent.features,
                        group_scores[incumbent_index].0,
                    )
                    .expect("exact full-vector report-preference inference failed");
                self.neural_ranker_wall_seconds += started.elapsed().as_secs_f64();
                self.neural_ranker_batches += 1;
                self.neural_ranker_candidate_reports += outputs.len();
                preference_risk_scores =
                    Some(outputs.iter().map(|output| output.risk_score).collect());
                Some(
                    outputs
                        .into_iter()
                        .enumerate()
                        .map(|(candidate_index, output)| {
                            if candidate_index == incumbent_index {
                                0.5
                            } else if output.benefit_probability >= threshold
                                && self.cfg.groupjoin_report_preference_risk_tau.is_none_or(
                                    |risk_tau| {
                                        output.risk_score.is_some_and(|risk| risk <= risk_tau)
                                    },
                                )
                            {
                                output.benefit_probability
                            } else {
                                -1.0
                            }
                        })
                        .collect::<Vec<_>>(),
                )
            } else if let (Some(ranker), Some(incumbent_index)) =
                (&self.groupjoin_pair_ranker, preference_incumbent)
            {
                let threshold = self.cfg.groupjoin_pair_ranker_tau.unwrap_or(0.5);
                let incumbent_features = &candidates[incumbent_index].3.features;
                let incumbent_admission = group_scores[incumbent_index].0;
                Some(
                    candidates
                        .iter()
                        .enumerate()
                        .map(|(candidate_index, (_, _, _, candidate))| {
                            if candidate_index == incumbent_index {
                                return 0.5;
                            }
                            let vector = Self::report_preference_vector(
                                ranker,
                                &candidate.features,
                                incumbent_features,
                                group_scores[candidate_index].0,
                                incumbent_admission,
                            );
                            let preference = ranker.raw_proba(&vector);
                            if preference >= threshold {
                                preference
                            } else {
                                -1.0
                            }
                        })
                        .collect::<Vec<_>>(),
                )
            } else if let Some(feature) = &self.cfg.groupjoin_ranker_feature {
                Some(
                    candidates
                        .iter()
                        .map(|(_, _, _, candidate)| {
                            *candidate.features.get(feature.as_str()).unwrap_or_else(|| {
                                panic!("configured groupjoin rank feature {feature:?} is missing")
                            })
                        })
                        .collect::<Vec<_>>(),
                )
            } else if let Some(ranker) = &self.groupjoin_ranker {
                Some(
                    candidates
                        .iter_mut()
                        .enumerate()
                        .map(|(index, (_, _, _, candidate))| {
                            candidate
                                .features
                                .insert(RANKER_ADMISSION_RAW_FEATURE, group_scores[index].0);
                            if let Some(score) = neural_rank_scores
                                .as_ref()
                                .and_then(|scores| scores.get(index))
                            {
                                candidate.features.insert(RANKER_NEURAL_RAW_FEATURE, *score);
                            }
                            let x = ranker.vectorize(&candidate.features);
                            ranker.raw_proba(&x)
                        })
                        .collect::<Vec<_>>(),
                )
            } else {
                neural_rank_scores
            };
            if self.cfg.emit_candidate_report_states {
                for (index, state) in decision_candidate_report_states.iter_mut().enumerate() {
                    state.behavior_raw = group_scores.get(index).map(|score| score.0);
                    state.ranking_raw = group_rank_scores
                        .as_ref()
                        .and_then(|scores| scores.get(index))
                        .copied();
                    state.preference_risk = preference_risk_scores
                        .as_ref()
                        .and_then(|scores| scores.get(index))
                        .copied()
                        .flatten();
                    state.match_raw = group_match.get(index).copied().flatten();
                    state.coherence_raw = group_coherence.get(index).copied().flatten();
                    state.admission_raw = group_admission.get(index).copied().flatten();
                }
            }
            let scores_are_raw = self.cfg.gj_raw_tau.is_some();
            groupjoin_report_scores = Some(
                candidates
                    .iter()
                    .zip(&group_scores)
                    .map(|((rid, _, _, _), (raw, calibrated))| {
                        (rid.clone(), if scores_are_raw { *raw } else { *calibrated })
                    })
                    .collect(),
            );

            let mut gj_best: Option<usize> = None;
            let mut admission_best: Option<usize> = None;
            for (candidate_index, ((rid, rank, count, candidate), (raw, cal))) in candidates
                .iter()
                .zip(group_scores.iter().copied())
                .enumerate()
            {
                if self.group_feature_fixtures.len() < self.cfg.group_feature_fixture_limit {
                    self.group_feature_fixtures.push(GroupFeatureFixture {
                        query: sig.id.clone(),
                        candidate_report: rid.clone(),
                        members: candidate.members.clone(),
                        n_members: candidate.n_members,
                        rank_best: *rank,
                        n_retrieved: *count,
                        features: candidate
                            .features
                            .iter()
                            .map(|(name, value)| ((*name).to_string(), *value))
                            .collect(),
                        retrieved_witnesses: self
                            .contextual_groupjoin
                            .as_ref()
                            .map(|_| candidate.retrieved_witnesses.clone()),
                        external_members: self
                            .contextual_groupjoin
                            .as_ref()
                            .map(|_| candidate.external_members.clone()),
                        report_tokens: self
                            .contextual_groupjoin
                            .as_ref()
                            .map(|_| candidate.tokens.clone()),
                        external_tokens: self
                            .contextual_groupjoin
                            .as_ref()
                            .map(|_| candidate.external_tokens.clone()),
                    });
                }
                let coherence_pass = self.cfg.gj_coherence_raw_tau.is_none_or(|tau| {
                    group_coherence[candidate_index].is_some_and(|score| score >= tau)
                });
                let admission_pass = candidate.n_members < self.cfg.gj_admission_min_report_size
                    || self.cfg.gj_admission_raw_tau.is_none_or(|tau| {
                        group_admission[candidate_index].is_some_and(|score| score >= tau)
                    });
                let ranking_admission_pass = group_rank_scores.is_none()
                    || !self.cfg.groupjoin_ranker_admission_eligible_only
                    || self.cfg.gj_raw_tau.map_or(cal >= gj_tau, |tau| raw >= tau);
                let outranks_best = gj_best.is_none_or(|best_index| {
                    group_rank_scores.as_ref().map_or_else(
                        || {
                            let (best_raw, best_cal) = group_scores[best_index];
                            (cal, raw) >= (best_cal, best_raw)
                        },
                        |rank_scores| {
                            (rank_scores[candidate_index], cal, raw)
                                >= (
                                    rank_scores[best_index],
                                    group_scores[best_index].1,
                                    group_scores[best_index].0,
                                )
                        },
                    )
                });
                let outranks_admission_best = admission_best.is_none_or(|best_index| {
                    let (best_raw, best_cal) = group_scores[best_index];
                    (cal, raw) >= (best_cal, best_raw)
                });
                if coherence_pass && admission_pass && ranking_admission_pass && outranks_best {
                    gj_best = Some(candidate_index);
                }
                if coherence_pass
                    && admission_pass
                    && ranking_admission_pass
                    && outranks_admission_best
                {
                    admission_best = Some(candidate_index);
                }
            }
            if let (Some(rank_scores), Some(rank_best), Some(original_best)) =
                (&group_rank_scores, gj_best, admission_best)
            {
                if rank_best != original_best {
                    self.groupjoin_ranker_override_opportunities += 1;
                    let margin = rank_scores[rank_best] - rank_scores[original_best];
                    let admission_gap = group_scores[original_best].0 - group_scores[rank_best].0;
                    let rank_margin_rejected = self
                        .cfg
                        .groupjoin_ranker_override_margin
                        .is_some_and(|threshold| margin < threshold);
                    let admission_gap_rejected = self
                        .cfg
                        .groupjoin_ranker_admission_gap_max
                        .is_some_and(|threshold| admission_gap > threshold);
                    if rank_margin_rejected || admission_gap_rejected {
                        gj_best = Some(original_best);
                    } else {
                        self.groupjoin_ranker_interventions += 1;
                    }
                }
            }
            if self.cfg.groupjoin_forced_query.as_deref() == Some(sig.id.as_str()) {
                let anchor = self
                    .cfg
                    .groupjoin_forced_report_member
                    .as_deref()
                    .expect("forced report query requires a report member anchor");
                let anchor_row = *self.store.row_by_signal_id.get(anchor).unwrap_or_else(|| {
                    panic!("forced report member {anchor:?} is not in the live prefix")
                });
                let target_report = self.reports.resolve(&self.store.report_ids[anchor_row]);
                let forced_index = candidates
                    .iter()
                    .position(|(report_id, _, _, _)| report_id == &target_report)
                    .unwrap_or_else(|| {
                        panic!(
                            "forced report containing {anchor:?} is not a candidate for query {:?}",
                            sig.id
                        )
                    });
                let (forced_raw, forced_cal) = group_scores[forced_index];
                let forced_coherence_pass = self.cfg.gj_coherence_raw_tau.is_none_or(|tau| {
                    group_coherence[forced_index].is_some_and(|score| score >= tau)
                });
                let forced_admission_pass = candidates[forced_index].3.n_members
                    < self.cfg.gj_admission_min_report_size
                    || self.cfg.gj_admission_raw_tau.is_none_or(|tau| {
                        group_admission[forced_index].is_some_and(|score| score >= tau)
                    });
                let forced_threshold_pass = self
                    .cfg
                    .gj_raw_tau
                    .map_or(forced_cal >= gj_tau, |tau| forced_raw >= tau);
                assert!(
                    forced_coherence_pass && forced_admission_pass && forced_threshold_pass,
                    "forced report candidate for query {:?} is not admission eligible",
                    sig.id
                );
                gj_best = Some(forced_index);
                forced_report_choice = true;
                self.groupjoin_forced_report_choices += 1;
            }
            match gj_best {
                Some(best_index) => {
                    let rid = candidates[best_index].0.clone();
                    let (raw, cal) = group_scores[best_index];
                    best_i = candidates_by_id
                        .iter()
                        .position(|c| self.reports.resolve(&c.report_id) == rid);
                    best_p = cal;
                    best_raw = raw;
                    pair_pass = self.cfg.gj_raw_tau.map_or(cal >= gj_tau, |tau| raw >= tau);
                    if let Some(bi) = best_i {
                        cal_ps[bi] = cal;
                        raw_ps[bi] = raw;
                    }
                    tau_note.push_str(&self.cfg.gj_raw_tau.map_or_else(
                        || format!(", gj cal={cal:.3} raw={raw:.3} gj_tau={gj_tau:.3}"),
                        |tau| format!(", gj cal={cal:.3} raw={raw:.3} gj_raw_tau={tau:.3}"),
                    ));
                    if let Some(rank_raw) = group_rank_scores
                        .as_ref()
                        .and_then(|scores| scores.get(best_index))
                    {
                        tau_note.push_str(&format!(", rank_raw={rank_raw:.3}"));
                    }
                    if let Some(coherence_tau) = self.cfg.gj_coherence_raw_tau {
                        let coherence = candidates
                            .iter()
                            .position(|(candidate_rid, _, _, _)| candidate_rid == &rid)
                            .and_then(|index| group_coherence[index])
                            .unwrap_or(f64::NAN);
                        tau_note.push_str(&format!(
                            ", coherence_raw={coherence:.3} coherence_tau={coherence_tau:.3}"
                        ));
                    }
                    if let Some(admission_tau) = self.cfg.gj_admission_raw_tau {
                        let admission = candidates
                            .iter()
                            .position(|(candidate_rid, _, _, _)| candidate_rid == &rid)
                            .and_then(|index| group_admission[index])
                            .unwrap_or(f64::NAN);
                        tau_note.push_str(&format!(
                            ", admission_raw={admission:.3} admission_tau={admission_tau:.3} admission_min_size={}",
                            self.cfg.gj_admission_min_report_size
                        ));
                    }
                }
                None => {
                    best_i = None;
                    best_p = 0.0;
                    best_raw = 0.0;
                    pair_pass = false;
                    tau_note.push_str(if self.cfg.gj_admission_raw_tau.is_some() {
                        ", gj: no admission-eligible group"
                    } else if self.cfg.gj_coherence_raw_tau.is_some() {
                        ", gj: no coherence-eligible group"
                    } else {
                        ", gj: no scoreable group"
                    });
                }
            }
        }

        let best_candidate_signal_id = best_i.map(|i| candidates_by_id[i].signal_id.clone());
        let best_candidate_report_id =
            best_i.map(|i| self.reports.resolve(&candidates_by_id[i].report_id));
        let best_candidate_distance = best_i.map(|i| candidates_by_id[i].distance);
        let report_best: HashMap<String, f64> = groupjoin_report_scores.unwrap_or_else(|| {
            let active_scores = if self.cfg.classifier_raw_tau.is_some() {
                &raw_ps
            } else {
                &cal_ps
            };
            let mut scores = HashMap::new();
            for (candidate, score) in candidates_by_id.iter().zip(active_scores) {
                let rid = self.reports.resolve(&candidate.report_id);
                let entry = scores.entry(rid).or_insert(f64::NEG_INFINITY);
                *entry = entry.max(*score);
            }
            scores
        });
        let second_best_report_p = best_candidate_report_id.as_ref().and_then(|best_report| {
            report_best
                .iter()
                .filter(|(report, _)| *report != best_report)
                .map(|(_, score)| *score)
                .max_by(f64::total_cmp)
        });
        let best_active_score = if self.cfg.classifier_raw_tau.is_some() {
            best_raw
        } else {
            best_p
        };
        let pair_margin = second_best_report_p.map(|second| best_active_score - second);
        if let Some(margin_tau) = self.cfg.classifier_margin_tau {
            let margin_pass = pair_margin.is_none_or(|margin| margin >= margin_tau);
            pair_pass &= margin_pass;
            tau_note.push_str(&format!(
                ", margin={:.3} margin_tau={margin_tau:.3}",
                pair_margin.unwrap_or(f64::INFINITY)
            ));
        }
        let candidate_report_count = report_best.len();

        // group-join second opinion (v1.5/v1.6 semantics, oracle dropped)
        let mut join_decision: Option<bool> = None;
        let mut join_note = String::new();
        if let (Some(bi), true) = (best_i, self.join.is_some() && self.cfg.use_join_model) {
            let top_report = self.reports.resolve(&candidates_by_id[bi].report_id);
            let mut report_ps: HashMap<String, Vec<f64>> = HashMap::new();
            for (c, p_c) in candidates_by_id.iter().zip(&cal_ps) {
                report_ps
                    .entry(self.reports.resolve(&c.report_id))
                    .or_default()
                    .push(*p_c);
            }
            if let Some(q) = self.join_q(
                prep,
                &rmeta,
                &ids_q,
                burst_q,
                &top_report,
                &report_ps[&top_report],
            ) {
                let jm = self.join.as_ref().unwrap();
                let tau_r = self.cfg.join_model_tau.or(jm.tau).unwrap_or(0.5);
                let pair_verdict = pair_pass;
                let group_verdict =
                    if self.cfg.join_veto_q.is_some() || self.cfg.join_rescue_q.is_some() {
                        let lo = self.cfg.join_veto_q.unwrap_or(-1.0);
                        let hi = self.cfg.join_rescue_q.unwrap_or(2.0);
                        if pair_verdict {
                            q > lo
                        } else {
                            q >= hi
                        }
                    } else {
                        q >= tau_r
                    };
                join_decision = Some(group_verdict);
                join_note = format!("; join model q={q:.3} (tau_r={tau_r:.3})");
            }
        }

        let pair_threshold = if groupjoin_active {
            self.cfg.gj_raw_tau.or(self.cfg.gj_tau).unwrap_or(0.5)
        } else {
            self.cfg.classifier_raw_tau.unwrap_or(tau)
        };
        let pair_threshold_is_raw = if groupjoin_active {
            self.cfg.gj_raw_tau.is_some()
        } else {
            self.cfg.classifier_raw_tau.is_some()
        };
        let joined = join_decision.unwrap_or(best_i.is_some() && pair_pass);
        let repair_competitor = if joined {
            best_candidate_report_id.as_ref().and_then(|best_report| {
                report_best
                    .iter()
                    .filter(|(report, _)| *report != best_report)
                    .max_by(|left, right| left.1.total_cmp(right.1).then(left.0.cmp(right.0)))
                    .map(|(report, score)| (report.clone(), *score))
            })
        } else {
            report_best
                .iter()
                .max_by(|left, right| left.1.total_cmp(right.1).then(left.0.cmp(right.0)))
                .map(|(report, score)| (report.clone(), *score))
        };
        let (mut report_id, matched, mut reason) = if let (Some(bi), true) = (best_i, joined) {
            self.join_p.insert(sig.id.clone(), best_p);
            self.join_parent
                .insert(sig.id.clone(), candidates_by_id[bi].signal_id.clone());
            let best_report = self.reports.resolve(&candidates_by_id[bi].report_id);
            let cand_report_of: Vec<(String, f64)> = candidates_by_id
                .iter()
                .zip(&cal_ps)
                .map(|(c, p)| (c.report_id.clone(), *p))
                .collect();
            let merged_count =
                self.consider_bridges(&sig.id, sig.ts, &cand_report_of, &best_report, best_p);
            let scorer = if groupjoin_active {
                "groupjoin"
            } else {
                "classifier"
            };
            let mut reason = format!("{scorer} join at p={best_p:.3} (raw={best_raw:.4}, tau={pair_threshold:.3}{tau_note}){join_note}");
            if merged_count > 0 {
                reason += &format!("; bridge-merged {merged_count} report(s)");
            }
            (best_report, true, reason)
        } else {
            // Non-join bridge trigger: the signal clears tau for nothing, but if it
            // holds >= trigger-p candidates in 2+ reports it is still bridging
            // evidence between them (the A…C-then-B fork echo).
            if self.concern.is_some() && !candidates_by_id.is_empty() {
                let mut per_report: HashMap<String, f64> = HashMap::new();
                for (c, p_c) in candidates_by_id.iter().zip(&cal_ps) {
                    let rid = self.reports.resolve(&c.report_id);
                    let e = per_report.entry(rid).or_insert(0.0);
                    *e = e.max(*p_c);
                }
                let eligible: Vec<(&String, &f64)> = per_report
                    .iter()
                    .filter(|(_r, p)| **p >= self.cfg.bridge_trigger_tau)
                    .collect();
                if eligible.len() >= 2 {
                    let (top_report, top_p) = eligible
                        .iter()
                        .max_by(|a, b| a.1.partial_cmp(b.1).unwrap().then(b.0.cmp(a.0)))
                        .map(|(r, p)| ((*r).clone(), **p))
                        .unwrap();
                    let cand_report_of: Vec<(String, f64)> = candidates_by_id
                        .iter()
                        .zip(&cal_ps)
                        .map(|(c, p)| (c.report_id.clone(), *p))
                        .collect();
                    self.consider_bridges(&sig.id, sig.ts, &cand_report_of, &top_report, top_p);
                }
            }
            let reason = if best_i.is_none() {
                "no retrieved candidates".to_string()
            } else {
                let scorer = if groupjoin_active {
                    "groupjoin"
                } else {
                    "classifier"
                };
                format!("best {scorer} p={best_p:.3} (raw={best_raw:.4}) vs tau={pair_threshold:.3}{tau_note}{join_note}")
            };
            (format!("lab-{}", sig.id), false, reason)
        };

        self.store.store(
            sig.id.clone(),
            sig.content.clone(),
            &prep.embedding,
            report_id.clone(),
            sig.product.clone(),
            sig.source_type.clone(),
            sig.source_id.clone(),
            sig.ts,
            Some(prep.neigh_scale),
        );
        if self.cfg.id_lane_limit > 0 {
            let row = self.store.n - 1;
            for vals in ids_q.values() {
                for v in vals {
                    self.id_postings.entry(v.clone()).or_default().push(row);
                }
            }
        }
        if matched {
            self.eval_group_after_join(&report_id, &sig.id);
        }
        if let Some((competitor, trigger_score)) = repair_competitor {
            let signal_row = *self
                .store
                .row_by_signal_id
                .get(&sig.id)
                .expect("current signal was just stored");
            let own = self.reports.resolve(&self.store.report_ids[signal_row]);
            if let Some(current_report) =
                self.consider_member_repair(&sig.id, sig.ts, &own, &competitor, trigger_score)
            {
                report_id = current_report;
                reason.push_str("; member-aware report-pair repair applied");
            }
        }
        if matched && self.cfg.centroid_proposer_k > 0 {
            // after split and member repair so proposals see the settled report
            let rid = self.reports.resolve(&report_id);
            self.centroid_propose(&rid, sig, prep.snapshot);
        }
        if self.cfg.band_trigger_hits > 0 {
            // band-aware merge trigger: >= N candidates from one foreign report
            // in the far band = group-level agreement; the gate disposes
            let own = self.reports.resolve(&report_id);
            let mut hits: HashMap<String, (usize, f64)> = HashMap::new();
            for c in &candidates_by_id {
                if c.distance >= self.cfg.band_trigger_lo && c.distance < self.cfg.band_trigger_hi {
                    let rid = self.reports.resolve(&c.report_id);
                    if rid != own && !rid.is_empty() {
                        let e = hits.entry(rid).or_insert((0usize, f64::INFINITY));
                        e.0 += 1;
                        e.1 = e.1.min(c.distance);
                    }
                }
            }
            let mut ranked: Vec<(String, usize, f64)> = hits
                .into_iter()
                .filter(|(_r, (n, _d))| *n >= self.cfg.band_trigger_hits)
                .map(|(r, (n, d))| (r, n, d))
                .collect();
            ranked.sort_by(|a, b| {
                b.1.cmp(&a.1)
                    .then(a.2.partial_cmp(&b.2).unwrap())
                    .then(a.0.cmp(&b.0))
            });
            ranked.truncate(self.cfg.centroid_merge_topn);
            for (rid0, _n_hits, dmin) in ranked {
                let rid = self.reports.resolve(&rid0);
                let own_now = self.reports.resolve(&report_id);
                if rid == own_now {
                    continue;
                }
                self.try_merge(&sig.id, sig.ts, &own_now, &rid, 1.0 - dmin);
            }
        }

        Decision {
            document_id: sig.id.clone(),
            timestamp: sig.ts,
            run_report_id: report_id,
            matched_existing: matched,
            match_reason: reason,
            batch_index,
            level,
            candidate_ids: candidates_by_id
                .iter()
                .map(|c| c.signal_id.clone())
                .collect(),
            best_candidate_signal_id: best_candidate_signal_id.clone(),
            best_candidate_report_id,
            best_candidate_distance,
            joined_parent_signal_id: if matched {
                best_candidate_signal_id
            } else {
                None
            },
            best_pair_p: best_i.map(|_| best_p),
            best_pair_raw: best_i.map(|_| best_raw),
            second_best_report_p,
            pair_margin,
            pair_threshold,
            pair_threshold_is_raw,
            pair_pass,
            candidate_count: candidates_by_id.len(),
            candidate_report_count,
            forced_report_choice,
            candidate_report_states: decision_candidate_report_states,
        }
    }

    /// join-model q for signal vs report (full-report sample, cap 40 / id_cap 14).
    fn join_q(
        &mut self,
        prep: &PreparedSignal,
        rmeta: &HashMap<String, RetrievalMeta>,
        ids_q: &IdSets,
        burst_q: f64,
        rid: &str,
        report_ps: &[f64],
    ) -> Option<f64> {
        let view = self.store.report_view(rid, 40, 14)?;
        let sig = &prep.signal;
        let q_type = (sig.product.as_str(), sig.source_type.as_str());
        self.warm_ids(&view.content_rows);
        let text_q = TextStats::compute(&sig.content);
        let sampled_p: Vec<f64> = {
            use rayon::prelude::*;
            view.content_rows
                .par_iter()
                .map(|&row| {
                    self.score_pair_vs_row_ro(
                        &prep.embedding,
                        q_type,
                        sig.ts,
                        &sig.content,
                        &sig.source_id,
                        ids_q,
                        burst_q,
                        prep.neigh_scale,
                        self.sigs.get(&sig.id),
                        &text_q,
                        row,
                        rmeta.get(&self.store.signal_ids[row]),
                    )
                    .1
                })
                .collect()
        };
        let member_id_sets: Vec<&IdSets> = view
            .content_rows
            .iter()
            .map(|r| &self.id_cache[r])
            .collect();
        let member_ids_agg = merge_identifier_sets(&member_id_sets);
        let member_emb: Vec<&[f32]> = view.emb_rows.iter().map(|&r| self.store.row(r)).collect();
        let prods: HashSet<&str> = view
            .content_rows
            .iter()
            .map(|&r| self.store.source_products[r].as_str())
            .collect();
        let mut top3: Vec<f64> = report_ps.to_vec();
        top3.sort_by(|a, b| b.partial_cmp(a).unwrap());
        top3.truncate(3);
        let ts_max = view
            .emb_rows
            .iter()
            .map(|&r| self.store.timestamps[r])
            .fold(f64::NEG_INFINITY, f64::max);
        let jf = feats::join_features(
            &sampled_p,
            &prep.embedding,
            &member_emb,
            ids_q,
            &member_ids_agg,
            view.size,
            report_ps.len(),
            report_ps
                .iter()
                .cloned()
                .fold(f64::NEG_INFINITY, f64::max)
                .max(0.0),
            if top3.is_empty() {
                0.0
            } else {
                top3.iter().sum::<f64>() / top3.len() as f64
            },
            (sig.ts - ts_max) / 3600.0,
            if prods.contains(sig.product.as_str()) {
                1.0
            } else {
                0.0
            },
            if sig.product == "error_tracking"
                && prods.len() == 1
                && prods.contains("error_tracking")
            {
                1.0
            } else {
                0.0
            },
        );
        let jm = self.join.as_ref().unwrap();
        let x = jm.vectorize(&jf);
        Some(jm.predict(&x).1)
    }
}
