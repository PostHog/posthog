//! Batch execution of one Hog program against many event-globals.

use std::time::Instant;

use hogvm::{sync_execute, ExecutionContext, Program};
use napi_derive::napi;
use rayon::prelude::*;
use serde_json::Value;

use crate::ext_fns::transformation_ext_fns;

const PARALLEL_CHUNK_SIZE: usize = 500;

// The Node VM has no heap ceiling; the crate's 1MB default trips on real events with large
// properties. A cap (not a preallocation), and rayon bounds how many contexts run at once.
const MAX_HEAP_SIZE_BYTES: usize = 64 * 1024 * 1024;

#[napi(object)]
pub struct HogExecResult {
    /// The program's return value; None when the execution errored.
    pub result: Option<Value>,
    pub error: Option<String>,
    pub duration_us: f64,
}

pub fn run_batch(
    tokens: &[Value],
    events: &[Value],
    parallel: bool,
    max_steps: Option<usize>,
) -> Vec<HogExecResult> {
    if tokens.is_empty() {
        return events
            .iter()
            .map(|_| error_result("invalid program: bytecode must be a non-empty array", 0.0))
            .collect();
    }

    if !parallel {
        return run_chunk(tokens, events, max_steps);
    }

    events
        .par_chunks(PARALLEL_CHUNK_SIZE)
        .flat_map_iter(|chunk| run_chunk(tokens, chunk, max_steps).into_iter())
        .collect()
}

// Run a slice of events through one reused ExecutionContext (STL and ext fns built once, globals
// swapped per event).
fn run_chunk(tokens: &[Value], chunk: &[Value], max_steps: Option<usize>) -> Vec<HogExecResult> {
    let program = match Program::new(tokens.to_vec()) {
        Ok(p) => p,
        Err(e) => {
            return chunk
                .iter()
                .map(|_| error_result(&format!("invalid program: {e}"), 0.0))
                .collect();
        }
    };

    // Coercing comparisons are the TS reference's semantics (unifyComparisonTypes): ordering
    // coerces across number/string/boolean/null instead of erroring.
    let mut ctx = ExecutionContext::with_defaults(program)
        .with_ext_fns(transformation_ext_fns())
        .with_coercing_comparisons();
    ctx.max_heap_size = MAX_HEAP_SIZE_BYTES;
    if let Some(max_steps) = max_steps {
        ctx.max_steps = max_steps;
    }

    chunk
        .iter()
        .map(|event| {
            ctx.set_globals(event.clone());
            let start = Instant::now();
            let outcome = sync_execute(&ctx, false);
            let duration_us = start.elapsed().as_secs_f64() * 1_000_000.0;
            match outcome {
                Ok(value) => HogExecResult {
                    result: Some(value),
                    error: None,
                    duration_us,
                },
                Err(failure) => error_result(&failure.error.to_string(), duration_us),
            }
        })
        .collect()
}

fn error_result(error: &str, duration_us: f64) -> HogExecResult {
    HogExecResult {
        result: None,
        error: Some(error.to_string()),
        duration_us,
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;
    use crate::ext_fns::set_bot_lists_for_tests;

    // "_H" header, version 1, push int 1, push int 2, PLUS, RETURN
    fn add_program() -> Vec<Value> {
        vec![
            json!("_H"),
            json!(1),
            json!(33),
            json!(1),
            json!(33),
            json!(2),
            json!(6),
            json!(38),
        ]
    }

    // push "name", GET_GLOBAL (1 chain part), RETURN — returns globals.name
    fn get_global_program(name: &str) -> Vec<Value> {
        vec![
            json!("_H"),
            json!(1),
            json!(32),
            json!(name),
            json!(1),
            json!(1),
            json!(38),
        ]
    }

    // push arg (a string), CALL_GLOBAL fn with 1 arg, RETURN
    fn call_fn_program(fn_name: &str, arg: &str) -> Vec<Value> {
        vec![
            json!("_H"),
            json!(1),
            json!(32),
            json!(arg),
            json!(2),
            json!(fn_name),
            json!(1),
            json!(38),
        ]
    }

    #[test]
    fn executes_each_event_with_its_own_globals_in_order() {
        let events: Vec<Value> = (0..1200)
            .map(|i| json!({ "name": i.to_string() }))
            .collect();
        for parallel in [false, true] {
            let results = run_batch(&get_global_program("name"), &events, parallel, None);
            assert_eq!(results.len(), events.len());
            for (i, r) in results.iter().enumerate() {
                assert_eq!(r.error, None);
                assert_eq!(r.result, Some(json!(i.to_string())));
                assert!(r.duration_us > 0.0);
            }
        }
    }

    #[test]
    fn per_event_error_does_not_fail_the_batch() {
        let events = vec![json!({ "name": "ok" }), json!({ "other": 1 })];
        let results = run_batch(&get_global_program("name"), &events, false, None);
        assert_eq!(results[0].result, Some(json!("ok")));
        assert!(results[1].result.is_none());
        assert!(results[1].error.as_deref().unwrap().contains("name"));
    }

    #[test]
    fn invalid_program_errors_every_event() {
        let results = run_batch(
            &[json!("not bytecode")],
            &[json!({}), json!({})],
            false,
            None,
        );
        assert_eq!(results.len(), 2);
        for r in &results {
            assert!(r.error.as_deref().unwrap().starts_with("invalid program"));
        }
    }

    #[test]
    fn empty_program_errors_every_event() {
        let results = run_batch(&[], &[json!({})], false, None);
        assert!(results[0].error.is_some());
    }

    #[test]
    fn comparisons_coerce_booleans_and_nulls_like_the_reference() {
        // rev > 0 where rev is boolean (or-chains yield booleans): true coerces to 1.
        let gt_true_zero = vec![
            json!("_H"),
            json!(1),
            json!(33),
            json!(0),
            json!(29),
            json!(13),
            json!(38),
        ];
        let results = run_batch(&gt_true_zero, &[json!({})], false, None);
        assert_eq!(results[0].error, None);
        assert_eq!(results[0].result, Some(json!(true)));

        // octet < 0 where octet is null: null coerces to 0.
        let lt_zero_null = vec![
            json!("_H"),
            json!(1),
            json!(33),
            json!(0),
            json!(31),
            json!(15),
            json!(38),
        ];
        let results = run_batch(&lt_zero_null, &[json!({})], false, None);
        assert_eq!(results[0].error, None);
        assert_eq!(results[0].result, Some(json!(false)));
    }

    #[test]
    fn max_steps_budget_is_enforced() {
        let results = run_batch(&add_program(), &[json!({})], false, Some(1));
        assert!(results[0].error.is_some());
        let results = run_batch(&add_program(), &[json!({})], false, None);
        assert_eq!(results[0].result, Some(json!(3)));
    }

    #[test]
    fn posthog_capture_errors_like_the_node_executor() {
        let results = run_batch(
            &call_fn_program("postHogCapture", "x"),
            &[json!({})],
            false,
            None,
        );
        assert!(results[0]
            .error
            .as_deref()
            .unwrap()
            .contains("posthogCapture is not supported in transformations"));
    }

    #[test]
    fn unsupported_ext_fns_are_classifiable() {
        let results = run_batch(
            &call_fn_program("generateMessagingPreferencesUrl", "x"),
            &[json!({})],
            false,
            None,
        );
        assert!(results[0]
            .error
            .as_deref()
            .unwrap()
            .contains("unsupported_ext_fn:generateMessagingPreferencesUrl"));
    }

    #[test]
    fn geoip_lookup_without_init_is_classified_unsupported() {
        // GEOIP is never initialized in the test process.
        let results = run_batch(
            &call_fn_program("geoipLookup", "89.160.20.129"),
            &[json!({})],
            false,
            None,
        );
        assert!(results[0]
            .error
            .as_deref()
            .unwrap()
            .contains("unsupported_ext_fn:geoipLookup"));
    }

    #[test]
    fn print_is_a_noop_and_execution_continues() {
        // print("x") (POP the call result), then return 1+2
        let mut program = vec![
            json!("_H"),
            json!(1),
            json!(32),
            json!("x"),
            json!(2),
            json!("print"),
            json!(1),
            json!(35),
        ];
        program.extend(add_program().into_iter().skip(2));
        let results = run_batch(&program, &[json!({})], false, None);
        assert_eq!(results[0].error, None);
        assert_eq!(results[0].result, Some(json!(3)));
    }

    #[test]
    fn known_bot_user_agent_matches_lowercased_substring() {
        set_bot_lists_for_tests();
        let results = run_batch(
            &call_fn_program("isKnownBotUserAgent", "Mozilla/5.0 GoogleBot/2.1"),
            &[json!({})],
            false,
            None,
        );
        assert_eq!(results[0].result, Some(json!(true)));
        let results = run_batch(
            &call_fn_program("isKnownBotUserAgent", "Mozilla/5.0 Safari"),
            &[json!({})],
            false,
            None,
        );
        assert_eq!(results[0].result, Some(json!(false)));
    }

    #[test]
    fn known_bot_ip_matches_exactly() {
        set_bot_lists_for_tests();
        let results = run_batch(
            &call_fn_program("isKnownBotIp", "1.2.3.4"),
            &[json!({})],
            false,
            None,
        );
        assert_eq!(results[0].result, Some(json!(true)));
        let results = run_batch(
            &call_fn_program("isKnownBotIp", "1.2.3.40"),
            &[json!({})],
            false,
            None,
        );
        assert_eq!(results[0].result, Some(json!(false)));
    }

    #[test]
    fn clean_null_values_via_the_vm_strips_nulls_from_globals() {
        let results = run_batch(
            &call_fn_program("cleanNullValues", "unused"),
            &[json!({})],
            false,
            None,
        );
        // A string arg passes through untouched.
        assert_eq!(results[0].result, Some(json!("unused")));

        // cleanNullValues(globals.g)
        let program = vec![
            json!("_H"),
            json!(1),
            json!(32),
            json!("g"),
            json!(1),
            json!(1),
            json!(2),
            json!("cleanNullValues"),
            json!(1),
            json!(38),
        ];
        let results = run_batch(
            &program,
            &[json!({ "g": { "a": null, "b": 1, "c": [null, 2] } })],
            false,
            None,
        );
        assert_eq!(results[0].result, Some(json!({ "b": 1, "c": [2] })));
    }
}
