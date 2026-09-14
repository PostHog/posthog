//! Runs the vendored Feature Flag Rules v2 contract corpus against production code:
//! the `sha1_60_v1` hash vectors against `calculate_hash` and the evaluator's rollout,
//! holdout, and variant paths; the version 1 lock-down cases against
//! `FeatureFlagMatcher::evaluate_all_feature_flags`; and the legacy projection matrix
//! against the `/flags` and `/decide` response conversions.
//!
//! The corpus lives under `tests/fixtures/rules_v2_contract/<contract version>/`.
//! `SOURCE.json` there records the upstream revision, the digests this test verifies, and
//! the update procedure. CI never fetches the harness repository.

use std::collections::{BTreeSet, HashMap, HashSet};
use std::fs;
use std::path::{Path, PathBuf};
use std::sync::Arc;

use feature_flags::api::types::{
    DecideV1Response, DecideV2Response, FlagDetails, FlagDetailsMetadata, FlagEvaluationReason,
    FlagsResponse, LegacyFlagsResponse,
};
use feature_flags::cohorts::cohort_cache_manager::CohortCacheManager;
use feature_flags::flags::cache_builder::compute_flag_dependencies;
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_matching::FeatureFlagMatcher;
use feature_flags::flags::flag_matching_utils::calculate_hash;
use feature_flags::flags::flag_models::{FeatureFlag, FeatureFlagList};
use feature_flags::flags::flag_request::FlagRequest;
use feature_flags::utils::test_utils::{mock_group_type_cache, TestContext};
use regex::Regex;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

const CORPUS_DIR: &str = "tests/fixtures/rules_v2_contract/1.2.0";

/// Corpus rows that supply a precomputed `hash01` instead of hash inputs. The evaluator
/// computes its hash internally and exposes no seam that accepts one, so these rows stay
/// unsupported until the shared hashing primitives are extracted behind such a seam.
const UNSUPPORTED_CASE_IDS: &[&str] = &[
    "threshold.equal_is_included",
    "threshold.next_binary64_above_is_excluded",
    "threshold.zero_percent_zero_hash",
    "threshold.zero_percent_smallest_hash",
    "threshold.hundred_percent_short_circuit",
    "threshold.two_decimal_division_equal",
    "threshold.two_decimal_division_excluded",
    "threshold.two_decimal_division_included_below_quotient",
    "variant.zero_hash_first_variant",
    "variant.boundary_is_exclusive",
    "variant.just_below_boundary",
    "variant.accumulated_boundary_left_to_right",
    "variant.accumulated_boundary_third",
    "variant.two_decimal_weights_boundary",
    "variant.hash_one_off_the_end",
    "variant.sum_below_one_off_the_end",
    "parity.final_variant_fallback_divergent",
];

/// A dependency target absent from the fixture definitions maps to an id no fixture flag
/// uses, so the target is missing from the flag list entirely. That is the only way the
/// evaluator reports `missing_dependency`: a deleted target that another flag references
/// stays in the cached list and pre-seeds as false.
const MISSING_DEPENDENCY_ID: i64 = 0;

#[test]
fn vendored_corpus_is_intact() {
    let source = load_json("SOURCE.json");
    let manifest = load_json("manifest.json");

    let recorded = source["files"].as_object().expect("SOURCE.json files");
    let mut on_disk = BTreeSet::new();
    collect_files(&corpus_dir(), &corpus_dir(), &mut on_disk);
    on_disk.remove("SOURCE.json");
    assert_eq!(
        on_disk,
        recorded.keys().cloned().collect::<BTreeSet<_>>(),
        "vendored files must match the files listed in SOURCE.json"
    );
    for (rel, digest) in recorded {
        let bytes = fs::read(corpus_dir().join(rel)).unwrap();
        assert_eq!(
            hex::encode(Sha256::digest(&bytes)),
            digest.as_str().unwrap(),
            "{rel}: bytes differ from the digest in SOURCE.json; a changed expectation needs a new corpus version, see update_procedure"
        );
    }

    assert_eq!(source["contract_version"], manifest["contract"]["version"]);
    assert_eq!(source["corpus_version"], manifest["corpus"]["version"]);
    for artifact in corpus_artifacts(&manifest) {
        let path = str_field(artifact, "path");
        let file = load_json(path);
        assert_eq!(
            file["corpus_version"], manifest["corpus"]["version"],
            "{path}: corpus_version"
        );
        let in_file = file_case_ids(&file);
        let unique: BTreeSet<&String> = in_file.iter().collect();
        assert_eq!(unique.len(), in_file.len(), "{path}: duplicate case ids");
        let declared: BTreeSet<String> = artifact["case_ids"]
            .as_array()
            .unwrap()
            .iter()
            .map(|id| id.as_str().unwrap().to_string())
            .collect();
        assert_eq!(
            unique.into_iter().cloned().collect::<BTreeSet<_>>(),
            declared,
            "{path}: case ids differ from the manifest"
        );
    }
}

#[tokio::test]
async fn corpus_matches_production_evaluator_and_projections() {
    let manifest = load_json("manifest.json");
    let db = TestContext::new(None).await;
    let team_id = db.insert_new_team(None).await.expect("insert team").id;

    let mut covered = HashSet::new();
    covered.extend(run_hash_corpus(&db, team_id).await);
    covered.extend(run_v1_corpus(&db, team_id).await);
    covered.extend(run_projection_corpus());

    let unsupported: HashSet<String> = UNSUPPORTED_CASE_IDS.iter().map(|s| s.to_string()).collect();
    let declared: HashSet<String> = corpus_artifacts(&manifest)
        .flat_map(|artifact| artifact["case_ids"].as_array().unwrap().iter())
        .map(|id| id.as_str().unwrap().to_string())
        .collect();
    let both: BTreeSet<_> = covered.intersection(&unsupported).collect();
    assert!(
        both.is_empty(),
        "cases both run and listed as unsupported: {both:?}"
    );
    let accounted: HashSet<String> = covered.union(&unsupported).cloned().collect();
    let missing: BTreeSet<_> = declared.difference(&accounted).collect();
    assert!(
        missing.is_empty(),
        "manifest cases neither run nor listed as unsupported: {missing:?}"
    );
    let unknown: BTreeSet<_> = accounted.difference(&declared).collect();
    assert!(
        unknown.is_empty(),
        "cases run or listed that the manifest does not declare: {unknown:?}"
    );
}

async fn run_hash_corpus(db: &TestContext, team_id: i32) -> HashSet<String> {
    let corpus = load_json("corpus/hash_sha1_60_v1.json");
    let mut covered = HashSet::new();

    for vector in corpus["vectors"].as_array().unwrap() {
        let id = str_field(vector, "id");
        let prefix = str_field(vector, "prefix");
        let identifier = str_field(vector, "identifier");
        let salt = str_field(vector, "salt");

        let input = format!("{prefix}{identifier}{salt}");
        assert_eq!(
            input,
            str_field(vector, "input"),
            "{id}: input concatenation"
        );
        assert_eq!(
            hex::encode(input.as_bytes()),
            str_field(vector, "input_utf8_hex"),
            "{id}: input bytes"
        );
        let hash = calculate_hash(prefix, identifier, salt).unwrap();
        assert_hash01(id, hash, &vector["hash01"]);
        assert_eq!(
            format!("{:016x}", hash.to_bits()),
            str_field(vector, "hash01_binary64_hex"),
            "{id}: hash01 binary64 bits"
        );

        if let Some(before) = vector["identifier_before_truncation"].as_str() {
            let request = FlagRequest {
                distinct_id: Some(before.to_string()),
                ..Default::default()
            };
            assert_eq!(
                request.extract_distinct_id().unwrap(),
                identifier,
                "{id}: request-level identifier truncation"
            );
        }

        // Rollout, holdout, and variant checks run through the evaluator so the comparison
        // and the boundary accumulation are the production ones, not a copy kept here.
        // Production hashes `<flag key>.`, so the flag key is the prefix minus its dot. The
        // holdout vector's `holdout-` prefix has no dot: `get_holdout_hash` always hashes
        // that literal, so the flag key never reaches it.
        let key = prefix.strip_suffix('.').unwrap_or(prefix);
        let (context, group_type_mapping, aggregation) = match vector["identifier_source"]
            .get("json_group_key")
        {
            Some(group_key) => (
                json!({"distinct_id": "person", "person_properties": {}, "groups": {"organization": group_key}}),
                json!({"0": "organization"}),
                Some(0),
            ),
            None => (
                json!({"distinct_id": identifier, "person_properties": {}}),
                Value::Null,
                None,
            ),
        };

        for check in vector["rollout_checks"].as_array().into_iter().flatten() {
            let percentage = check["rollout_percentage"].as_f64().unwrap();
            assert_eq!(
                percentage / 100.0,
                check["threshold"].as_f64().unwrap(),
                "{id}: threshold for {percentage}"
            );
            let flag = hash_check_flag(
                team_id,
                key,
                aggregation,
                json!({"groups": [{"properties": [], "rollout_percentage": percentage}]}),
            );
            let details = evaluate_single(db, team_id, flag, &group_type_mapping, &context).await;
            assert_eq!(
                json!(details.enabled),
                check["included"],
                "{id}: rollout at {percentage} percent"
            );
        }
        for check in vector["holdout_checks"].as_array().into_iter().flatten() {
            let percentage = check["exclusion_percentage"].as_f64().unwrap();
            let flag = hash_check_flag(
                team_id,
                key,
                None,
                json!({"groups": [{"properties": [], "rollout_percentage": 100}], "holdout": {"id": 7, "exclusion_percentage": percentage}}),
            );
            let details = evaluate_single(db, team_id, flag, &group_type_mapping, &context).await;
            assert_eq!(
                json!(details.variant.as_deref() == Some("holdout-7")),
                check["member"],
                "{id}: holdout membership at {percentage} percent"
            );
        }
        if let Some(check) = vector.get("variant_check") {
            let flag = hash_check_flag(
                team_id,
                key,
                aggregation,
                json!({"groups": [{"properties": [], "rollout_percentage": 100}], "multivariate": {"variants": check["variants"]}}),
            );
            let details = evaluate_single(db, team_id, flag, &group_type_mapping, &context).await;
            assert_eq!(
                details.variant.as_deref(),
                check["selected"].as_str(),
                "{id}: variant selection"
            );
        }
        covered.insert(id.to_string());
    }

    // Parity rows pin that the v1 input and the converted v2 input hash identically.
    // `identical_outcome` and `divergence` describe version 2 semantics, which nothing in
    // this crate implements yet, so they are not asserted here.
    for parity in corpus["seed_parity"].as_array().unwrap() {
        let id = str_field(parity, "id");
        let Some(v2) = parity.get("v2") else {
            continue; // white-box row, listed in UNSUPPORTED_CASE_IDS
        };
        let v1_input = str_field(parity, "v1_input");
        let v1_hash = hash_of_input(v1_input);
        let v2_hash = calculate_hash(
            str_field(v2, "prefix"),
            str_field(v2, "identifier"),
            str_field(v2, "salt"),
        )
        .unwrap();
        assert_hash01(id, v2_hash, &parity["hash01"]);
        assert_eq!(
            v1_hash.to_bits(),
            v2_hash.to_bits(),
            "{id}: v1 and converted v2 inputs must hash identically"
        );
        assert_eq!(
            json!(v1_input == str_field(v2, "input")),
            parity["identical_bytes"],
            "{id}: identical_bytes"
        );
        covered.insert(id.to_string());
    }
    covered
}

async fn run_v1_corpus(db: &TestContext, team_id: i32) -> HashSet<String> {
    let corpus = load_json("corpus/v1_evaluation.json");
    let mut covered = HashSet::new();

    for case in corpus["cases"].as_array().unwrap() {
        let id = str_field(case, "id");
        for evidence in case["hash_evidence"].as_array().into_iter().flatten() {
            assert_hash01(
                id,
                hash_of_input(str_field(evidence, "input")),
                &evidence["hash01"],
            );
        }

        let (flags, filtered_out) = corpus_flags(team_id, &case["definitions"]["flags"]);
        let response = evaluate(
            db,
            team_id,
            flags,
            filtered_out,
            &case["definitions"]["group_type_mapping"],
            &case["context"],
        )
        .await;
        assert!(
            !response.errors_while_computing_flags,
            "{id}: errorsWhileComputingFlags"
        );

        let mut unexpected: BTreeSet<&String> = response.flags.keys().collect();
        for (key, expected) in case["expected"]["flags"].as_object().unwrap() {
            let actual = response
                .flags
                .get(key)
                .unwrap_or_else(|| panic!("{id}: flag {key} missing from the response"));
            unexpected.remove(key);
            assert_eq!(
                json!(actual.to_value()),
                expected["value"],
                "{id}: {key} value"
            );
            assert_eq!(
                json!(actual.enabled),
                expected["enabled"],
                "{id}: {key} enabled"
            );
            assert_eq!(
                json!(actual.variant),
                expected["variant"],
                "{id}: {key} variant"
            );
            assert_eq!(
                json!(actual.metadata.payload),
                expected["payload"],
                "{id}: {key} payload"
            );
            assert_eq!(
                json!(actual.reason.code),
                expected["reason"]["code"],
                "{id}: {key} reason code"
            );
            assert_eq!(
                json!(actual.reason.condition_index),
                expected["reason"]["condition_index"],
                "{id}: {key} condition index"
            );
        }
        for omitted in case["expected"]["omitted_flags"].as_array().unwrap() {
            let omitted = omitted.as_str().unwrap();
            assert!(
                !response.flags.contains_key(omitted),
                "{id}: {omitted} must be omitted from the response"
            );
        }
        assert!(
            unexpected.is_empty(),
            "{id}: response carries flags the corpus does not expect: {unexpected:?}"
        );
        covered.insert(id.to_string());
    }
    covered
}

fn run_projection_corpus() -> HashSet<String> {
    let corpus = load_json("corpus/legacy_projection.json");
    let mut covered = HashSet::new();

    for case in corpus["cases"].as_array().unwrap() {
        let id = str_field(case, "id");
        let outcome = &case["outcome"];
        let build = || response_from_outcome(outcome);
        let actuals = [
            ("flags_v2", serde_json::to_value(build()).unwrap()),
            (
                "flags_v1",
                serde_json::to_value(LegacyFlagsResponse::from_response(build())).unwrap(),
            ),
            (
                "decide_v2",
                serde_json::to_value(DecideV2Response::from_response(build())).unwrap(),
            ),
            (
                "decide_v1",
                serde_json::to_value(DecideV1Response::from_response(build())).unwrap(),
            ),
        ];
        for (protocol, actual) in actuals {
            assert_projection(id, protocol, &case["projections"][protocol], &actual);
        }
        covered.insert(id.to_string());
    }
    covered
}

/// Builds the detailed response the evaluator would have produced for a corpus outcome.
fn response_from_outcome(outcome: &Value) -> FlagsResponse {
    let mut flags = HashMap::new();
    if !outcome["omitted"].as_bool().unwrap() {
        let key = str_field(outcome, "key").to_string();
        let detail = FlagDetails {
            key: key.clone(),
            enabled: outcome["enabled"].as_bool().unwrap(),
            variant: outcome["variant"].as_str().map(String::from),
            failed: outcome["failed"].as_bool().unwrap(),
            reason: FlagEvaluationReason {
                code: str_field(&outcome["reason"], "code").to_string(),
                condition_index: outcome["reason"]["condition_index"]
                    .as_i64()
                    .map(|i| i as i32),
                description: None,
            },
            metadata: FlagDetailsMetadata {
                id: outcome["flag_id"].as_i64().unwrap() as i32,
                version: outcome["flag_version"].as_i64().unwrap() as i32,
                description: None,
                payload: Some(outcome["payload"].clone()).filter(|p| !p.is_null()),
                has_experiment: false,
            },
            conditions: None,
        };
        flags.insert(key, detail);
    }
    FlagsResponse::new(
        outcome["failed"].as_bool().unwrap(),
        flags,
        None,
        Uuid::nil(),
    )
}

/// The corpus pins a subset of each response: every listed field must match, the flag maps
/// must contain exactly the listed keys, and `failed` must be absent unless listed.
fn assert_projection(id: &str, protocol: &str, expected: &Value, actual: &Value) {
    for (field, expected_value) in expected.as_object().unwrap() {
        if field == "response_version" {
            continue;
        }
        let actual_value = actual
            .get(field)
            .unwrap_or_else(|| panic!("{id}: {protocol} response lacks {field}"));
        assert_subset(id, protocol, field, expected_value, actual_value);
        if let (Some(e), Some(a)) = (expected_value.as_object(), actual_value.as_object()) {
            assert_eq!(
                e.keys().collect::<BTreeSet<_>>(),
                a.keys().collect::<BTreeSet<_>>(),
                "{id}: {protocol} {field} keys"
            );
        }
    }
    for (key, detail) in expected["flags"].as_object().into_iter().flatten() {
        if detail.get("failed").is_none() {
            assert!(
                actual["flags"][key].get("failed").is_none(),
                "{id}: {protocol} {key} must not carry failed"
            );
        }
    }
}

fn assert_subset(id: &str, protocol: &str, path: &str, expected: &Value, actual: &Value) {
    match (expected.as_object(), actual.as_object()) {
        (Some(e), Some(a)) => {
            for (field, expected_value) in e {
                let actual_value = a
                    .get(field)
                    .unwrap_or_else(|| panic!("{id}: {protocol} {path}.{field} missing"));
                assert_subset(
                    id,
                    protocol,
                    &format!("{path}.{field}"),
                    expected_value,
                    actual_value,
                );
            }
        }
        _ => assert_eq!(expected, actual, "{id}: {protocol} {path}"),
    }
}

/// Maps corpus flag definitions onto the evaluator's input shape: the team id is attached,
/// dependency filters name their target by id instead of key, and inactive flags join the
/// filtered-out set exactly as the request handler builds it.
fn corpus_flags(team_id: i32, definitions: &Value) -> (Vec<FeatureFlag>, HashSet<i32>) {
    let definitions = definitions.as_array().unwrap();
    let key_to_id: HashMap<&str, i64> = definitions
        .iter()
        .map(|flag| (str_field(flag, "key"), flag["id"].as_i64().unwrap()))
        .collect();

    let mut flags = Vec::new();
    let mut filtered_out = HashSet::new();
    for definition in definitions {
        let mut definition = definition.clone();
        definition["team_id"] = json!(team_id);
        for group in definition["filters"]["groups"]
            .as_array_mut()
            .into_iter()
            .flatten()
        {
            for property in group["properties"].as_array_mut().into_iter().flatten() {
                if property["type"] == "flag" {
                    let target = key_to_id
                        .get(str_field(property, "key"))
                        .copied()
                        .unwrap_or(MISSING_DEPENDENCY_ID);
                    property["key"] = json!(target.to_string());
                }
            }
        }
        let flag: FeatureFlag =
            serde_json::from_value(definition).expect("corpus flag must deserialize");
        if !flag.active {
            filtered_out.insert(flag.id);
        }
        flags.push(flag);
    }
    (flags, filtered_out)
}

fn hash_check_flag(
    team_id: i32,
    key: &str,
    aggregation: Option<i32>,
    mut filters: Value,
) -> FeatureFlag {
    if let Some(index) = aggregation {
        filters["aggregation_group_type_index"] = json!(index);
    }
    serde_json::from_value(
        json!({"id": 1, "team_id": team_id, "key": key, "active": true, "filters": filters}),
    )
    .expect("hash check flag must deserialize")
}

async fn evaluate_single(
    db: &TestContext,
    team_id: i32,
    flag: FeatureFlag,
    group_type_mapping: &Value,
    context: &Value,
) -> FlagDetails {
    let key = flag.key.clone();
    let mut response = evaluate(
        db,
        team_id,
        vec![flag],
        HashSet::new(),
        group_type_mapping,
        context,
    )
    .await;
    response
        .flags
        .remove(&key)
        .unwrap_or_else(|| panic!("flag {key} missing from the response"))
}

async fn evaluate(
    db: &TestContext,
    team_id: i32,
    flags: Vec<FeatureFlag>,
    filtered_out_flag_ids: HashSet<i32>,
    group_type_mapping: &Value,
    context: &Value,
) -> FlagsResponse {
    let types_to_indexes: HashMap<String, i32> = group_type_mapping
        .as_object()
        .into_iter()
        .flatten()
        .map(|(index, name)| (name.as_str().unwrap().to_string(), index.parse().unwrap()))
        .collect();
    let groups: Option<HashMap<String, Value>> = context
        .get("groups")
        .map(|g| serde_json::from_value(g.clone()).unwrap());
    let person_properties: HashMap<String, Value> =
        serde_json::from_value(context["person_properties"].clone()).unwrap();
    let group_properties: Option<HashMap<String, HashMap<String, Value>>> = context
        .get("group_properties")
        .map(|g| serde_json::from_value(g.clone()).unwrap());

    let mut matcher = FeatureFlagMatcher::new(
        str_field(context, "distinct_id").to_string(),
        None,
        team_id,
        db.create_postgres_router(),
        Arc::new(CohortCacheManager::new(
            db.non_persons_reader.clone(),
            None,
            None,
        )),
        mock_group_type_cache(types_to_indexes),
        groups,
    );
    // Dependency stages and missing targets come from the production builder, the same
    // way the batch evaluation handler assembles its flag list.
    let evaluation_metadata = compute_flag_dependencies(&flags).expect("dependency metadata");
    let flag_list = FeatureFlagList {
        flags: PreparedFlags::seal(flags),
        filtered_out_flag_ids,
        evaluation_metadata: Arc::new(evaluation_metadata),
        cohorts: None,
    };
    matcher
        .evaluate_all_feature_flags(
            flag_list,
            Some(person_properties),
            group_properties,
            None,
            Uuid::new_v4(),
            None,
            false,
        )
        .await
        .expect("evaluation must not fail")
}

/// Hashes a corpus row that supplies the whole concatenated input instead of its parts.
fn hash_of_input(input: &str) -> f64 {
    calculate_hash(input, "", "").unwrap()
}

fn assert_hash01(id: &str, actual: f64, expected: &Value) {
    let expected: f64 = expected
        .as_str()
        .and_then(|literal| literal.parse().ok())
        .unwrap_or_else(|| panic!("{id}: hash01 must be a decimal literal"));
    assert_eq!(
        actual.to_bits(),
        expected.to_bits(),
        "{id}: hash01 is {actual:?}, corpus expects {expected:?}"
    );
}

fn corpus_dir() -> PathBuf {
    Path::new(env!("CARGO_MANIFEST_DIR")).join(CORPUS_DIR)
}

/// serde_json parses long decimals with best-effort precision unless its `float_roundtrip`
/// feature is on, and 17-digit `hash01` literals can land one ulp off. Those literals are
/// quoted here so `assert_hash01` can parse them exactly with `str::parse::<f64>`.
fn load_json(rel: &str) -> Value {
    let path = corpus_dir().join(rel);
    let text = fs::read_to_string(&path).unwrap_or_else(|e| panic!("read {}: {e}", path.display()));
    let text = Regex::new(r#"("hash01"\s*:\s*)([-+.0-9eE]+)"#)
        .unwrap()
        .replace_all(&text, "$1\"$2\"");
    serde_json::from_str(&text).unwrap_or_else(|e| panic!("parse {rel}: {e}"))
}

fn corpus_artifacts(manifest: &Value) -> impl Iterator<Item = &Value> {
    manifest["artifacts"]
        .as_array()
        .unwrap()
        .iter()
        .filter(|artifact| artifact["kind"] == "corpus")
}

/// Every `id` of an object inside a top-level array, which is how all three corpus files
/// lay out their cases and vectors.
fn file_case_ids(file: &Value) -> Vec<String> {
    file.as_object()
        .unwrap()
        .values()
        .filter_map(Value::as_array)
        .flatten()
        .filter_map(|row| row["id"].as_str())
        .map(String::from)
        .collect()
}

fn collect_files(root: &Path, dir: &Path, out: &mut BTreeSet<String>) {
    for entry in fs::read_dir(dir).unwrap() {
        let path = entry.unwrap().path();
        if path.is_dir() {
            collect_files(root, &path, out);
        } else {
            let rel = path.strip_prefix(root).unwrap();
            out.insert(
                rel.iter()
                    .map(|s| s.to_string_lossy())
                    .collect::<Vec<_>>()
                    .join("/"),
            );
        }
    }
}

fn str_field<'a>(value: &'a Value, field: &str) -> &'a str {
    value[field]
        .as_str()
        .unwrap_or_else(|| panic!("corpus field {field} must be a string in {value}"))
}
