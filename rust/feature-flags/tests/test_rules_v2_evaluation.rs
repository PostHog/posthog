use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use feature_flags::flags;
use feature_flags::flags::config_v2::ParseError;
use feature_flags::flags::evaluate_v2::Evaluator;
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_matching_utils::calculate_hash;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};

pub mod common;
#[path = "test_rules_v2_evaluation/corpus.rs"]
mod corpus;

#[test]
fn pinned_evaluation_artifacts_are_complete_and_intact() {
    let source = corpus::load("SOURCE.json");
    let revision = source["source_revision"].as_str().unwrap();
    assert_eq!(revision.len(), 40);
    assert!(revision.bytes().all(|c| c.is_ascii_hexdigit()));
    assert_eq!(source["release_status"], "unreleased");
    let index = std::fs::read(corpus::root().join("SHA256SUMS")).unwrap();
    assert_eq!(
        hex::encode(Sha256::digest(&index)),
        source["source_sha256sums_digest"]
    );
    let digests: BTreeMap<_, _> = std::str::from_utf8(&index)
        .unwrap()
        .lines()
        .map(|line| line.split_once("  ").unwrap())
        .map(|(digest, path)| (path, digest))
        .collect();
    let files: BTreeSet<_> = source["files"]
        .as_array()
        .unwrap()
        .iter()
        .map(|path| path.as_str().unwrap())
        .collect();
    assert_eq!(files.len(), source["files"].as_array().unwrap().len());
    for path in files {
        assert_eq!(
            hex::encode(Sha256::digest(
                std::fs::read(corpus::root().join(path)).unwrap()
            )),
            digests[path],
            "{path}"
        );
    }
    let manifest = corpus::load("manifest.json");
    assert_eq!(manifest["contract"]["version"], source["contract_version"]);
    assert_eq!(
        manifest["v2_boolean_evaluation"]["version"],
        source["v2_boolean_evaluation_version"]
    );
    let cases = corpus::cases();
    let ids: Vec<_> = cases.iter().map(|case| case["id"].clone()).collect();
    let artifact = manifest["artifacts"]
        .as_array()
        .unwrap()
        .iter()
        .find(|artifact| artifact["path"] == "corpus/v2_boolean_evaluation.json")
        .unwrap();
    assert_eq!(json!(ids), artifact["case_ids"]);
    assert_eq!(
        ids.iter()
            .map(Value::to_string)
            .collect::<BTreeSet<_>>()
            .len(),
        ids.len()
    );
    let mut counts = BTreeMap::new();
    for case in &cases {
        *counts.entry(case["family"].as_str().unwrap()).or_insert(0) += 1;
    }
    assert_eq!(
        counts,
        BTreeMap::from([
            ("ordering", 18),
            ("properties", 52),
            ("context", 8),
            ("errors", 6),
            ("hashing", 20),
            ("white_box", 10),
            ("eligibility", 3),
            ("parser", 2),
        ])
    );
}

#[test]
fn parsed_configs_match_every_core_case_without_mutating_cached_inputs() {
    let mut executed = 0;
    let mut rejected = 0;
    for case in corpus::cases() {
        let id = case["id"].as_str().unwrap();
        match case["family"].as_str().unwrap() {
            "white_box" | "eligibility" => continue,
            "ordering" | "properties" | "context" | "errors" | "hashing" | "parser" => {}
            other => panic!("unhandled family: {other}"),
        }
        let flag = corpus::read(&case);
        let before = serde_json::to_value(&flag).unwrap();
        let cached = PreparedFlags::seal(vec![flag]);
        let retained = cached[0].filters.non_v1.as_ref().unwrap();
        let parsed = retained.parsed_v2.as_ref().unwrap();
        if case["family"] == "parser" {
            let kind = match parsed {
                Err(ParseError::Malformed(_)) => "malformed",
                Err(ParseError::Unsupported(_)) => "unsupported",
                other => panic!("{id}: unexpected parse result {other:?}"),
            };
            assert_eq!(
                json!({"status":"parse_error","kind":kind}),
                case["expected"],
                "{id}"
            );
            rejected += 1;
            continue;
        }
        let evaluator = Evaluator::new(parsed.as_ref().unwrap());
        let properties = corpus::properties(&case);
        let properties_before = properties.clone();
        let context = corpus::context(&case, &properties);
        for _ in 0..2 {
            assert_eq!(
                corpus::result_json(evaluator.evaluate(&context)),
                case["expected"],
                "{id}"
            );
        }
        let cloned = cached[0].clone();
        assert!(Arc::ptr_eq(
            retained,
            cloned.filters.non_v1.as_ref().unwrap()
        ));
        assert_eq!(serde_json::to_value(&cached[0]).unwrap(), before, "{id}");
        assert_eq!(properties, properties_before);
        if let Some(evidence) = case.get("hash_evidence") {
            let rule = parsed
                .as_ref()
                .unwrap()
                .rules
                .iter()
                .find_map(|rule| match &rule.outcome {
                    flags::config_v2::Outcome::PercentageRollout {
                        seed,
                        rollout_percentage,
                        ..
                    } => Some((seed, *rollout_percentage)),
                    _ => None,
                })
                .unwrap();
            let subject: String = context.person_identifier.chars().take(200).collect();
            assert_eq!(subject, evidence["identifier"]);
            let hash = calculate_hash(&format!("{}.", rule.0), &subject, "").unwrap();
            assert_eq!(
                format!("{:016x}", hash.to_bits()),
                evidence["hash01_binary64_hex"],
                "{id}"
            );
            assert_eq!(
                format!("{:016x}", (rule.1 / 100.0).to_bits()),
                evidence["threshold_binary64_hex"],
                "{id}"
            );
        }
        executed += 1;
    }
    assert_eq!((executed, rejected), (104, 2));
}

#[tokio::test]
async fn corpus_eligibility_uses_the_request_boundary_and_valid_v2_stays_closed() {
    use feature_flags::config::DEFAULT_TEST_CONFIG;
    use feature_flags::utils::test_utils::{
        insert_flags_for_team_in_redis, insert_new_team_in_redis, setup_redis_client,
    };
    let config = DEFAULT_TEST_CONFIG.clone();
    let redis = setup_redis_client(Some(config.redis_url.clone())).await;
    let team = insert_new_team_in_redis(redis.clone()).await.unwrap();
    let cases: Vec<_> = corpus::cases()
        .into_iter()
        .filter(|case| case["family"] == "eligibility")
        .collect();
    let mut flags = vec![
        json!({"id":1,"team_id":team.id,"key":"healthy","active":true,"filters":{"groups":[{"rollout_percentage":100}]}}),
    ];
    let mut requested = vec!["healthy".to_string(), "eligible-v2".to_string()];
    for (index, case) in cases.iter().enumerate() {
        let mut flag = corpus::read(case);
        flag.id = (index + 2) as i32;
        flag.team_id = team.id;
        flag.key = case["id"].as_str().unwrap().to_string();
        if case["flag"]["requested"] == true {
            requested.push(flag.key.clone());
        }
        flags.push(serde_json::to_value(flag).unwrap());
    }
    let mut eligible = corpus::read(&cases[0]);
    eligible.id = 20;
    eligible.team_id = team.id;
    eligible.key = "eligible-v2".to_string();
    eligible.active = true;
    let evaluator = Evaluator::new(
        eligible
            .filters
            .non_v1
            .as_ref()
            .unwrap()
            .parsed_v2
            .as_ref()
            .unwrap()
            .as_ref()
            .unwrap(),
    );
    assert_eq!(
        corpus::result_json(
            evaluator.evaluate(&corpus::context(&cases[0], &corpus::properties(&cases[0])))
        )["value"],
        true
    );
    flags.push(serde_json::to_value(eligible).unwrap());
    insert_flags_for_team_in_redis(redis, team.id, Some(json!(flags).to_string()))
        .await
        .unwrap();
    let server = common::ServerHandle::for_config(config).await;
    let body: Value = reqwest::Client::new()
        .post(format!("http://{}/flags?v=2&config=false", server.addr))
        .json(&json!({"token":team.api_token,"distinct_id":"example-person","flag_keys":requested}))
        .send()
        .await
        .unwrap()
        .error_for_status()
        .unwrap()
        .json()
        .await
        .unwrap();
    assert_eq!(body["flags"]["healthy"]["enabled"], true);
    assert_eq!(body["flags"]["eligible-v2"]["failed"], true);
    assert_eq!(
        body["flags"]["eligible-v2"]["reason"]["code"],
        "flag_data_parsing_error"
    );
    for case in &cases {
        assert!(body["flags"].get(case["id"].as_str().unwrap()).is_none());
        assert_eq!(case["expected"], json!({"status":"omitted"}));
    }
    assert_eq!(cases.len(), 3);
}
