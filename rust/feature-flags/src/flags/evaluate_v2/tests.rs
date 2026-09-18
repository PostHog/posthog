use super::*;
use serde_json::json;

#[path = "../../../tests/test_rules_v2_evaluation/corpus.rs"]
mod corpus;

#[test]
fn canonical_white_box_cases_exercise_the_production_ordered_evaluator() {
    let mut count = 0;
    for case in corpus::cases()
        .into_iter()
        .filter(|case| case["family"] == "white_box")
    {
        let flag = corpus::read(&case);
        let config = flag
            .filters
            .non_v1
            .as_ref()
            .unwrap()
            .parsed_v2
            .as_ref()
            .unwrap()
            .as_ref()
            .unwrap();
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
    let config = std::sync::Arc::make_mut(flag.filters.non_v1.as_mut().unwrap())
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
fn prepared_patterns_are_reused_and_diagnostics_do_not_retain_inputs() {
    let mut case = corpus::cases()
        .into_iter()
        .find(|case| case["id"] == "v2_boolean.property.regex")
        .unwrap();
    case["config"]["rules"][0]["targeting"]["properties"][0]["value"] = json!("sensitive-pattern");
    let flag = corpus::read(&case);
    let config = flag
        .filters
        .non_v1
        .as_ref()
        .unwrap()
        .parsed_v2
        .as_ref()
        .unwrap()
        .as_ref()
        .unwrap();
    let evaluator = Evaluator::new(config);
    let properties = corpus::properties(&case);
    let context = corpus::context(&case, &properties);
    let pattern = std::ptr::from_ref(&evaluator.regexes[0][0]);
    let result = evaluator.evaluate(&context);
    assert_eq!(result, evaluator.evaluate(&context));
    assert_eq!(pattern, std::ptr::from_ref(&evaluator.regexes[0][0]));
    assert!(evaluator.estimated_heap_bytes() >= 2048);
    let debug = format!("{evaluator:?} {context:?} {result:?}");
    for sensitive in [
        "sensitive-pattern",
        "person-example",
        "color",
        "metadata",
        "seed",
    ] {
        assert!(!debug.contains(sensitive));
    }
}
