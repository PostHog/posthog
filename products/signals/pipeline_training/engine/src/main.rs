#![recursion_limit = "256"]

#[path = "kernel/classifier.rs"]
mod classifier;
#[path = "kernel/config.rs"]
mod config;
#[path = "kernel/contextual_groupjoin.rs"]
mod contextual_groupjoin;
#[path = "kernel/corpus.rs"]
mod corpus;
#[path = "kernel/feats.rs"]
mod feats;
#[path = "kernel/idents.rs"]
mod idents;
#[path = "training_llm.rs"]
mod llm;
#[path = "kernel/member_repair.rs"]
mod member_repair;
#[path = "kernel/member_repair_oracle.rs"]
mod member_repair_oracle;
#[path = "kernel/model.rs"]
mod model;
#[path = "kernel/neural_groupjoin.rs"]
mod neural_groupjoin;
#[path = "kernel/neural_report_preference.rs"]
mod neural_report_preference;
#[path = "kernel/npy.rs"]
mod npy;
#[path = "kernel/shape.rs"]
mod shape;
#[path = "kernel/sigs.rs"]
mod sigs;
#[path = "kernel/slots.rs"]
mod slots;
#[path = "kernel/store.rs"]
mod store;
#[path = "kernel/textstats.rs"]
mod textstats;

use anyhow::{bail, Context, Result};
use serde::Deserialize;
use serde_json::{json, Value};
use std::collections::{BTreeMap, HashMap};
use std::io::{BufRead, BufReader, BufWriter, Write};
use std::path::Path;
use std::time::Instant;

const USAGE: &str = "usage:\n  signals-training-engine replay CONFIG OUTPUT_DIR\n  \
                     signals-training-engine featurize-pairs CONFIG\n  \
                     signals-training-engine featurize-cuts CONFIG\n  \
                     signals-training-engine score ASSIGNMENT PAIR_LABELS REPORT_LABELS SOURCE_REPORTS OUTPUT";

fn main() -> Result<()> {
    let arguments: Vec<String> = std::env::args().collect();
    match arguments.get(1).map(String::as_str) {
        Some("--help" | "-h" | "help") => {
            println!("{USAGE}");
            Ok(())
        }
        Some("replay") => replay(
            required_argument(&arguments, 2, "config")?,
            required_argument(&arguments, 3, "output directory")?,
        ),
        Some("featurize-pairs") => featurize_pairs(required_argument(&arguments, 2, "config")?),
        Some("featurize-cuts") => featurize_cuts(required_argument(&arguments, 2, "config")?),
        Some("score") => score(
            required_argument(&arguments, 2, "assignment")?,
            required_argument(&arguments, 3, "pair labels")?,
            required_argument(&arguments, 4, "report labels")?,
            required_argument(&arguments, 5, "source reports")?,
            required_argument(&arguments, 6, "output")?,
        ),
        _ => bail!(USAGE),
    }
}

fn required_argument<'a>(arguments: &'a [String], index: usize, name: &str) -> Result<&'a str> {
    arguments
        .get(index)
        .map(String::as_str)
        .with_context(|| format!("missing {name}"))
}

fn load_config(path: &str) -> Result<config::Config> {
    serde_json::from_str(&std::fs::read_to_string(path).with_context(|| path.to_string())?)
        .with_context(|| format!("parse {path}"))
}

fn load_signatures(corpus_dir: &str, replayer: &mut classifier::Replayer) -> Result<()> {
    let path = Path::new(corpus_dir).join("sigs.jsonl");
    if !path.exists() {
        return Ok(());
    }
    for line in BufReader::new(std::fs::File::open(&path)?).lines() {
        let signature: sigs::SigInfo = serde_json::from_str(&line?)?;
        replayer
            .sigs
            .insert(signature.document_id.clone(), signature);
    }
    Ok(())
}

struct LoadedModels {
    pair: model::GbdtModel,
    join: Option<model::GbdtModel>,
    concern: Option<model::GbdtModel>,
    groupjoin: Option<model::GbdtModel>,
    groupjoin_ranker: Option<model::GbdtModel>,
    groupjoin_pair_ranker: Option<model::GbdtModel>,
    groupjoin_net: Option<model::GjNet>,
    burst: HashMap<String, Vec<f64>>,
}

fn load_models(path: &str) -> Result<LoadedModels> {
    let models: model::ModelsFile =
        serde_json::from_str(&std::fs::read_to_string(path).with_context(|| path.to_string())?)
            .with_context(|| format!("parse {path}"))?;
    Ok(LoadedModels {
        pair: models.pair,
        join: models.join,
        concern: models.concern,
        groupjoin: models.groupjoin,
        groupjoin_ranker: models.groupjoin_ranker,
        groupjoin_pair_ranker: models.groupjoin_pair_ranker,
        groupjoin_net: models.groupjoin_net,
        burst: models.burst,
    })
}

fn build_replayer(
    configuration: config::Config,
    dimensions: usize,
) -> Result<classifier::Replayer> {
    if configuration.member_repair_llm_oracle {
        bail!("the training evaluator intentionally excludes hosted-model oracle calls");
    }
    if !matches!(configuration.mode, config::Mode::Classifier) {
        bail!("the training evaluator supports classifier mode only");
    }
    if !matches!(configuration.semantics, config::Semantics::Sequential) {
        bail!("the training evaluator supports sequential semantics only");
    }
    let models_path = configuration
        .models
        .as_deref()
        .context("configuration requires models")?;
    let models = load_models(models_path)?;
    let groupjoin_neural = configuration
        .groupjoin_neural_manifest
        .as_deref()
        .map(neural_groupjoin::NeuralGroupJoin::load)
        .transpose()?;
    let groupjoin_ranker_neural = configuration
        .groupjoin_ranker_neural_manifest
        .as_deref()
        .map(neural_groupjoin::NeuralGroupJoin::load)
        .transpose()?;
    let groupjoin_report_preference = configuration
        .groupjoin_report_preference_manifest
        .as_deref()
        .map(neural_report_preference::NeuralReportPreference::load)
        .transpose()?;
    let contextual_groupjoin = configuration
        .contextual_groupjoin_manifest
        .as_deref()
        .map(contextual_groupjoin::ContextualGroupJoin::load)
        .transpose()?;
    let repair = configuration
        .member_repair_manifest
        .as_deref()
        .map(member_repair::MemberRepair::load)
        .transpose()?;
    let join = configuration
        .use_join_model
        .then_some(models.join)
        .flatten();
    let concern = configuration
        .use_concern
        .then_some(models.concern)
        .flatten();
    let groupjoin = configuration
        .use_groupjoin
        .then_some(models.groupjoin)
        .flatten();
    let groupjoin_ranker = configuration
        .use_groupjoin
        .then_some(models.groupjoin_ranker)
        .flatten();
    let groupjoin_pair_ranker = configuration
        .use_groupjoin
        .then_some(models.groupjoin_pair_ranker)
        .flatten();
    let groupjoin_net = configuration
        .use_groupjoin
        .then_some(models.groupjoin_net)
        .flatten();
    Ok(classifier::Replayer::new(
        configuration,
        dimensions,
        Some(models.pair),
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
        repair,
        None,
        model::BurstIndex::new(models.burst),
    ))
}

fn replay(config_path: &str, output_directory: &str) -> Result<()> {
    let mut configuration = load_config(config_path)?;
    configuration.out_dir = output_directory.to_string();
    let corpus = corpus::Corpus::load(&configuration.corpus_dir)?;
    let limit = configuration
        .limit
        .unwrap_or(corpus.signals.len())
        .min(corpus.signals.len());
    let limited_embeddings = (limit < corpus.raw.rows).then(|| npy::Matrix {
        data: corpus.raw.data[..limit * corpus.raw.cols].to_vec(),
        rows: limit,
        cols: corpus.raw.cols,
    });
    let embeddings = limited_embeddings.as_ref().unwrap_or(&corpus.raw);
    let signals: Vec<classifier::SignalIn> = corpus
        .signals
        .iter()
        .take(limit)
        .map(classifier::SignalIn::from)
        .collect();
    let mut replayer = build_replayer(configuration, embeddings.cols)?;
    load_signatures(&replayer.cfg.corpus_dir.clone(), &mut replayer)?;
    std::fs::create_dir_all(output_directory)?;
    let started = Instant::now();
    replayer.run_sequential(
        &signals,
        embeddings,
        |done, total, reports, _merges, _splits| {
            if done == total || done % 500 == 0 {
                eprintln!("replay: {done}/{total} signals, {reports} reports");
            }
        },
    );
    write_replay(output_directory, &replayer, started.elapsed().as_secs_f64())?;
    Ok(())
}

fn write_json_lines<T: serde::Serialize>(path: &Path, rows: &[T]) -> Result<()> {
    let mut writer = BufWriter::new(std::fs::File::create(path)?);
    for row in rows {
        serde_json::to_writer(&mut writer, row)?;
        writer.write_all(b"\n")?;
    }
    Ok(())
}

fn write_replay(directory: &str, replayer: &classifier::Replayer, elapsed: f64) -> Result<()> {
    let root = Path::new(directory);
    write_json_lines(&root.join("decisions.jsonl"), &replayer.decisions)?;
    write_json_lines(&root.join("merge_events.jsonl"), &replayer.merge_events)?;
    write_json_lines(&root.join("split_events.jsonl"), &replayer.split_events)?;
    write_json_lines(
        &root.join("member_repair_events.jsonl"),
        &replayer.member_repair_events,
    )?;
    if !replayer.group_feature_fixtures.is_empty() {
        write_json_lines(
            &root.join("group_feature_fixtures.jsonl"),
            &replayer.group_feature_fixtures,
        )?;
    }
    let assignment: BTreeMap<String, String> = replayer
        .store
        .signal_ids
        .iter()
        .enumerate()
        .map(|(row, signal_id)| {
            (
                signal_id.clone(),
                replayer.reports.resolve(&replayer.store.report_ids[row]),
            )
        })
        .collect();
    std::fs::write(
        root.join("final_assignment.json"),
        serde_json::to_string(&assignment)?,
    )?;
    std::fs::write(
        root.join("runtime_stats.json"),
        serde_json::to_string_pretty(&json!({
            "signals": replayer.decisions.len(),
            "elapsed_seconds": elapsed,
            "rayon_threads": rayon::current_num_threads(),
            "retrieval_seconds": replayer.retrieval_wall_seconds,
            "decision_seconds": replayer.decision_wall_seconds,
            "concern_seconds": replayer.concern_wall_seconds,
            "concern_evaluations": replayer.concern_evaluations,
            "concern_cuts_scored": replayer.concern_cuts_scored,
            "member_repair_seconds": replayer.member_repair_wall_seconds,
            "member_repair_attempts": replayer.member_repair_attempts,
            "member_repair_applied": replayer.member_repair_applied,
            "split_events": replayer.split_events.len(),
        }))?,
    )?;
    Ok(())
}

fn feature_replayer(
    configuration: config::Config,
    dimensions: usize,
) -> Result<classifier::Replayer> {
    let loaded = configuration
        .models
        .as_deref()
        .map(load_models)
        .transpose()?;
    let (pair, burst) = match loaded {
        Some(models) => (Some(models.pair), models.burst),
        None => (None, HashMap::new()),
    };
    Ok(classifier::Replayer::new(
        configuration,
        dimensions,
        pair,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        model::BurstIndex::new(burst),
    ))
}

fn featurize_pairs(config_path: &str) -> Result<()> {
    let configuration = load_config(config_path)?;
    if configuration.featurize_pairs.is_empty() || configuration.featurize_out.is_empty() {
        bail!("configuration requires featurize_pairs and featurize_out");
    }
    let corpus = corpus::Corpus::load(&configuration.corpus_dir)?;
    let signals: Vec<classifier::SignalIn> = corpus
        .signals
        .iter()
        .map(classifier::SignalIn::from)
        .collect();
    let pairs = configuration.featurize_pairs.clone();
    let output = configuration.featurize_out.clone();
    let mut replayer = feature_replayer(configuration, corpus.raw.cols)?;
    load_signatures(&replayer.cfg.corpus_dir.clone(), &mut replayer)?;
    replayer.featurize(&signals, &corpus.raw, &pairs, &output)
}

fn featurize_cuts(config_path: &str) -> Result<()> {
    let configuration = load_config(config_path)?;
    if configuration.cuts_in.is_empty() || configuration.cuts_out.is_empty() {
        bail!("configuration requires cuts_in and cuts_out");
    }
    let models_path = configuration
        .models
        .as_deref()
        .context("cut featurization requires models")?;
    let models = load_models(models_path)?;
    let corpus = corpus::Corpus::load(&configuration.corpus_dir)?;
    let signals: Vec<classifier::SignalIn> = corpus
        .signals
        .iter()
        .map(classifier::SignalIn::from)
        .collect();
    let cuts_input = configuration.cuts_in.clone();
    let cuts_output = configuration.cuts_out.clone();
    let cut_filter = configuration.cuts_filter.clone();
    let mut replayer = classifier::Replayer::new(
        configuration,
        corpus.raw.cols,
        Some(models.pair),
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        None,
        model::BurstIndex::new(models.burst),
    );
    load_signatures(&replayer.cfg.corpus_dir.clone(), &mut replayer)?;
    let filter = if cut_filter.is_empty() {
        None
    } else {
        Some(read_cut_filter(&cut_filter)?)
    };
    replayer.featurize_cuts(
        &signals,
        &corpus.raw,
        &cuts_input,
        &cuts_output,
        filter.as_ref(),
    )
}

fn read_cut_filter(path: &str) -> Result<std::collections::HashSet<String>> {
    let mut values = std::collections::HashSet::new();
    for line in BufReader::new(std::fs::File::open(path)?).lines() {
        let line = line?;
        let trimmed = line.trim();
        if trimmed.is_empty() {
            continue;
        }
        if trimmed.starts_with('{') {
            let value: Value = serde_json::from_str(trimmed)?;
            values.insert(
                value["cut_id"]
                    .as_str()
                    .context("cut filter object has no cut_id")?
                    .to_string(),
            );
        } else {
            values.insert(trimmed.to_string());
        }
    }
    Ok(values)
}

#[derive(Deserialize)]
struct SourceReport {
    report_id: String,
    member_ids: Vec<String>,
}

fn read_jsonl_values(path: &str) -> Result<Vec<Value>> {
    BufReader::new(std::fs::File::open(path)?)
        .lines()
        .filter_map(|line| match line {
            Ok(value) if value.trim().is_empty() => None,
            other => Some(other),
        })
        .map(|line| serde_json::from_str(&line?).map_err(anyhow::Error::from))
        .collect()
}

fn safe_ratio(numerator: f64, denominator: f64) -> Option<f64> {
    (denominator > 0.0).then_some(numerator / denominator)
}

fn score(
    assignment_path: &str,
    pair_labels_path: &str,
    report_labels_path: &str,
    source_reports_path: &str,
    output_path: &str,
) -> Result<()> {
    let assignment: HashMap<String, String> =
        serde_json::from_str(&std::fs::read_to_string(assignment_path)?)?;
    let mut report_sizes: HashMap<&str, usize> = HashMap::new();
    for report_id in assignment.values() {
        *report_sizes.entry(report_id).or_default() += 1;
    }

    let mut true_positive = 0.0;
    let mut predicted_positive = 0.0;
    let mut actual_positive = 0.0;
    let mut true_negative = 0.0;
    let mut actual_negative = 0.0;
    let mut pair_label_rows = 0usize;
    for row in read_jsonl_values(pair_labels_path)? {
        if row["has_conflict"].as_bool().unwrap_or(false) {
            continue;
        }
        let left = row["signal_a"].as_str().context("pair signal_a")?;
        let right = row["signal_b"].as_str().context("pair signal_b")?;
        let label = row["same_concern"].as_bool().context("pair same_concern")?;
        let weight = row["confidence"].as_f64().unwrap_or(1.0);
        let left_assignment = assignment
            .get(left)
            .with_context(|| format!("pair label references unassigned signal {left}"))?;
        let right_assignment = assignment
            .get(right)
            .with_context(|| format!("pair label references unassigned signal {right}"))?;
        let predicted = left_assignment == right_assignment;
        pair_label_rows += 1;
        if label {
            actual_positive += weight;
            if predicted {
                true_positive += weight;
            }
        } else {
            actual_negative += weight;
            if !predicted {
                true_negative += weight;
            }
        }
        if predicted {
            predicted_positive += weight;
        }
    }

    let source_reports: HashMap<String, Vec<String>> = read_jsonl_values(source_reports_path)?
        .into_iter()
        .map(|row| serde_json::from_value::<SourceReport>(row))
        .collect::<std::result::Result<Vec<_>, _>>()?
        .into_iter()
        .map(|row| (row.report_id, row.member_ids))
        .collect();
    let mut gold_total = 0.0;
    let mut gold_cohesive = 0.0;
    let mut coherent_total = 0.0;
    let mut coherent_intact = 0.0;
    let mut overgroup_total = 0.0;
    let mut overgroup_intact = 0.0;
    let mut report_label_rows = 0usize;
    for row in read_jsonl_values(report_labels_path)? {
        if row["has_conflict"].as_bool().unwrap_or(false) {
            continue;
        }
        let report_id = row["report_id"]
            .as_str()
            .context("report label report_id")?;
        let members = source_reports
            .get(report_id)
            .with_context(|| format!("report label references absent source report {report_id}"))?;
        let assigned_reports = members
            .iter()
            .map(|member| {
                assignment.get(member).with_context(|| {
                    format!("source report {report_id} contains unassigned signal {member}")
                })
            })
            .collect::<Result<std::collections::HashSet<_>>>()?;
        let cohesive = assigned_reports.len() <= 1;
        let weight = row["confidence"].as_f64().unwrap_or(1.0);
        report_label_rows += 1;
        if row["coherent"].as_bool() == Some(true) {
            coherent_total += weight;
            coherent_intact += weight * f64::from(cohesive);
        }
        if row["gold_positive"].as_bool().unwrap_or(false) {
            gold_total += weight;
            gold_cohesive += weight * f64::from(cohesive);
        }
        if row["known_overgroup"].as_bool().unwrap_or(false) {
            overgroup_total += weight;
            overgroup_intact += weight * f64::from(cohesive);
        }
    }

    let precision = safe_ratio(true_positive, predicted_positive);
    let recall = safe_ratio(true_positive, actual_positive);
    let f1 = precision
        .zip(recall)
        .and_then(|(precision, recall)| safe_ratio(2.0 * precision * recall, precision + recall));
    let known_overgroup_intact = safe_ratio(overgroup_intact, overgroup_total);
    let result = json!({
        "pair_precision": precision,
        "pair_recall": recall,
        "pair_f1": f1,
        "keep_apart": safe_ratio(true_negative, actual_negative),
        "general_cohesion": safe_ratio(coherent_intact, coherent_total),
        "gold_cohesion": safe_ratio(gold_cohesive, gold_total),
        "known_overgroup_intact_rate": known_overgroup_intact,
        "known_overgroup_breakup_rate": known_overgroup_intact.map(|value| 1.0 - value),
        "reports": report_sizes.len(),
        "singletons": report_sizes.values().filter(|&&size| size == 1).count(),
        "maximum_report_size": report_sizes.values().max().copied().unwrap_or(0),
        "denominators": {
            "pair_label_rows": pair_label_rows,
            "report_label_rows": report_label_rows,
            "positive_pair_weight": actual_positive,
            "negative_pair_weight": actual_negative,
            "coherent_report_weight": coherent_total,
            "gold_report_weight": gold_total,
            "known_overgroup_weight": overgroup_total,
        },
        "scoring_contract": {
            "pair_metrics": "confidence-weighted atomic labels",
            "keep_apart": "weighted true-negative rate; higher is better",
            "general_cohesion": "weighted share of reports labelled coherent that remain intact; higher is better",
            "gold_cohesion": "weighted share of gold source reports kept together; higher is better",
            "known_overgroup_intact_rate": "weighted share of known overgroups left wholly intact; lower is better",
            "conflicts": "rows marked has_conflict are excluded"
        }
    });
    std::fs::write(output_path, serde_json::to_string_pretty(&result)? + "\n")?;
    println!("{}", serde_json::to_string_pretty(&result)?);
    Ok(())
}
