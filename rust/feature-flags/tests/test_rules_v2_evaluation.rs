use std::collections::{BTreeMap, BTreeSet};
use std::sync::Arc;

use feature_flags::flags::config_v2::{Outcome, ParseError};
use feature_flags::flags::evaluate_v2::{Evaluation, EvaluationError, Evaluator};
use feature_flags::flags::feature_flag_list::PreparedFlags;
use feature_flags::flags::flag_matching_utils::calculate_hash;
use feature_flags::flags::flag_request::MAX_DISTINCT_ID_LEN;
use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use uuid::Uuid;

pub mod common;
#[path = "test_rules_v2_evaluation/corpus.rs"]
mod corpus;

#[test]
fn pinned_evaluation_artifact_subset_is_intact() {
    let source = corpus::load("SOURCE.json");
    let revision = source["source_revision"].as_str().unwrap();
    assert_eq!(revision.len(), 40);
    assert!(revision.bytes().all(|c| c.is_ascii_hexdigit()));
    assert_eq!(source["release_status"], "released");
    assert_eq!(source["source_release"], "1.8.0");
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
            ("properties", 67),
            ("context", 8),
            ("errors", 6),
            ("hashing", 21),
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
        if case["family"] == "parser" {
            let kind = match retained.parsed_v2.as_ref() {
                Some(Err(ParseError::Malformed(_))) => "malformed",
                Some(Err(ParseError::Unsupported(_))) | None => "unsupported",
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
        let config = corpus::config(&cached[0]);
        let evaluator = Evaluator::new(config);
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
            let (seed, rollout_percentage) = config
                .rules
                .iter()
                .find_map(|rule| match &rule.outcome {
                    Outcome::PercentageRollout {
                        seed,
                        rollout_percentage,
                        ..
                    } => Some((seed, rollout_percentage)),
                    _ => None,
                })
                .unwrap();
            let subject: String = context
                .person_identifier
                .chars()
                .take(MAX_DISTINCT_ID_LEN)
                .collect();
            assert_eq!(subject, evidence["identifier"]);
            let hash = calculate_hash(&format!("{seed}."), &subject, "").unwrap();
            assert_eq!(
                format!("{:016x}", hash.to_bits()),
                evidence["hash01_binary64_hex"],
                "{id}"
            );
            assert_eq!(
                format!("{:016x}", (rollout_percentage / 100.0).to_bits()),
                evidence["threshold_binary64_hex"],
                "{id}"
            );
        }
        executed += 1;
    }
    assert_eq!((executed, rejected), (120, 2));
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
    let evaluator = Evaluator::new(corpus::config(&eligible));
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

#[test]
fn canonical_white_box_cases_exercise_the_production_ordered_evaluator() {
    let mut count = 0;
    for case in corpus::cases()
        .into_iter()
        .filter(|case| case["family"] == "white_box")
    {
        let flag = corpus::read(&case);
        let config = corpus::config(&flag);
        let evaluator = Evaluator::new(config);
        let properties = corpus::properties(&case);
        let context = corpus::context(&case, &properties);
        let hash = f64::from_bits(
            u64::from_str_radix(
                case["white_box"]["hash01_binary64_hex"].as_str().unwrap(),
                16,
            )
            .unwrap(),
        );
        let result = evaluator.evaluate_with_hash(&context, |_, _| Ok(hash));
        assert_eq!(
            corpus::result_json(result),
            case["expected"],
            "{}",
            case["id"]
        );
        count += 1;
    }
    assert_eq!(count, 10);
}

#[test]
fn hashing_is_lazy_subject_is_resolved_once_and_repeated_seeds_reuse_the_hash() {
    let case = corpus::cases()
        .into_iter()
        .find(|case| case["id"] == "v2_boolean.hash.full")
        .unwrap();
    let mut flag = corpus::read(&case);
    let config = Arc::make_mut(flag.filters.non_v1.as_mut().unwrap())
        .parsed_v2
        .as_mut()
        .unwrap()
        .as_mut()
        .unwrap();
    let properties = corpus::properties(&case);
    let mut context = corpus::context(&case, &properties);
    assert!(Evaluator::new(config)
        .evaluate_with_hash(&context, |_, _| panic!("100% must not hash"))
        .is_ok());
    context.person_identifier = "";
    assert!(matches!(
        Evaluator::new(config)
            .evaluate_with_hash(&context, |_, _| panic!("empty subject must not hash")),
        Ok(Evaluation::NoRuleMatch { .. })
    ));
    if let Outcome::PercentageRollout {
        rollout_percentage, ..
    } = &mut config.rules[0].outcome
    {
        *rollout_percentage = 0.0;
    }
    let mut second = config.rules[0].clone();
    second.id = Uuid::new_v4();
    config.rules.push(second);
    let subject = "😀".repeat(201);
    context.person_identifier = &subject;
    let mut calls = 0;
    assert!(matches!(
        Evaluator::new(config).evaluate_with_hash(&context, |seed, subject| {
            calls += 1;
            assert_eq!(seed, "example-allocation");
            assert_eq!(subject, "😀".repeat(200));
            Ok(0.5)
        }),
        Ok(Evaluation::NoRuleMatch { .. })
    ));
    assert_eq!(calls, 1);
    assert_eq!(
        Evaluator::new(config).evaluate_with_hash(&context, |_, _| Err(EvaluationError::Hash)),
        Err(EvaluationError::Hash)
    );
}

#[test]
fn regex_execution_errors_are_not_inverted_by_negation() {
    let mut case = corpus::cases()
        .into_iter()
        .find(|case| case["id"] == "v2_boolean.property.regex")
        .unwrap();
    case["config"]["rules"][0]["targeting"]["properties"][0]["value"] = json!(r"^(a+)+\1$");
    case["context"]["properties"]["color"] = json!("aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!");
    for negation in [false, true] {
        case["config"]["rules"][0]["targeting"]["properties"][0]["negation"] = json!(negation);
        let flag = corpus::read(&case);
        let config = corpus::config(&flag);
        let properties = corpus::properties(&case);
        let context = corpus::context(&case, &properties);
        assert_eq!(
            Evaluator::new(config).evaluate(&context),
            Err(EvaluationError::InvalidRegex),
            "negation={negation}"
        );
    }
}

#[test]
fn evaluation_is_repeatable_and_diagnostics_do_not_retain_inputs() {
    let mut case = corpus::cases()
        .into_iter()
        .find(|case| case["id"] == "v2_boolean.property.regex")
        .unwrap();
    case["config"]["rules"][0]["targeting"]["properties"][0]["value"] = json!("sensitive-pattern");
    let flag = corpus::read(&case);
    let config = corpus::config(&flag);
    let evaluator = Evaluator::new(config);
    let properties = corpus::properties(&case);
    let context = corpus::context(&case, &properties);
    let result = evaluator.evaluate(&context);
    assert_eq!(result, evaluator.evaluate(&context));
    assert!(config.estimated_heap_bytes() >= 2048);
    let debug = format!("{evaluator:?} {context:?} {result:?}");
    for sensitive in ["sensitive-pattern", "person-example", "color"] {
        assert!(!debug.contains(sensitive));
    }

    let mut case = corpus::cases()
        .into_iter()
        .find(|case| case["id"] == "v2_boolean.hash.full")
        .unwrap();
    case["config"]["rules"][0]["seed"] = json!("sensitive-seed");
    let flag = corpus::read(&case);
    let evaluator = Evaluator::new(corpus::config(&flag));
    let properties = corpus::properties(&case);
    let context = corpus::context(&case, &properties);
    let result = evaluator.evaluate(&context);
    assert!(matches!(result, Ok(Evaluation::TargetingMatch { .. })));
    assert!(!format!("{evaluator:?} {result:?}").contains("sensitive-seed"));
}
