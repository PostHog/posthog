//! Recognizes the one bytecode shape that is nothing but an event-name equality.
//!
//! A scan already filters on event name, so such a condition is decided before any row is read.
//! The match is positional over the raw tokens with a single hole for the name, rather than a rule
//! over the decoded instructions: the value of recognizing this shape is that it is exact, and a
//! looser rule risks claiming a condition needs no evaluation when it does.

use hogvm::Operation;
use serde_json::Value;

use super::EvaluationClass;

/// `["_H", <version>, STRING, <name>, STRING, "event", GET_GLOBAL, 1, EQ]`, as the compiler emits
/// `event == '<name>'`, followed by the `RETURN` the catalog loader appends.
const PREFIX_LEN: usize = 2;

/// The opcodes as they appear on the wire. Derived from [`Operation`] rather than written out:
/// its discriminants *are* the wire format, so a renumbering that breaks decoding must break this
/// matcher too. A hand-copied table would instead keep matching the old numbers and silently
/// classify the wrong programs as event-only.
const OP_STRING: u64 = Operation::String as u64;
const OP_GET_GLOBAL: u64 = Operation::GetGlobal as u64;
const OP_EQ: u64 = Operation::Eq as u64;
const OP_RETURN: u64 = Operation::Return as u64;

pub(super) fn classify(bytecode: &[Value]) -> EvaluationClass {
    match match_event_equality(bytecode) {
        Some(event) => EvaluationClass::EventOnly { event },
        None => EvaluationClass::General,
    }
}

fn match_event_equality(bytecode: &[Value]) -> Option<String> {
    // Version-0 bytecode carries no version token, so the body would start one slot earlier. The
    // compiler has emitted a version for as long as these catalogs have existed, so this matcher
    // requires one and anything else falls through to a general classification.
    //
    // `as_u64`, not `is_number`: the VM refuses a fractional or negative version outright, so a
    // program carrying one never runs. Accepting it here would classify a program the VM rejects as
    // needing no evaluation, which is the one direction this matcher must not be wrong in.
    if bytecode.first()?.as_str()? != "_H" || bytecode.get(1)?.as_u64().is_none() {
        return None;
    }
    let body = &bytecode[PREFIX_LEN..];
    let [push_name, name, push_event, event_key, get_global, chain_len, eq, rest @ ..] = body
    else {
        return None;
    };
    let opcodes_match = number(push_name) == Some(OP_STRING)
        && number(push_event) == Some(OP_STRING)
        && event_key.as_str() == Some("event")
        && number(get_global) == Some(OP_GET_GLOBAL)
        && number(chain_len) == Some(1)
        && number(eq) == Some(OP_EQ);
    if !opcodes_match {
        return None;
    }
    // The loader appends a `RETURN` to bytecode that may already end in one, so one or more is the
    // expected tail. Anything else means the program does more than the equality.
    if rest.is_empty() || !rest.iter().all(|token| number(token) == Some(OP_RETURN)) {
        return None;
    }
    Some(name.as_str()?.to_owned())
}

fn number(token: &Value) -> Option<u64> {
    token.as_u64()
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn event_equality(name: &str) -> Vec<Value> {
        vec![
            json!("_H"),
            json!(1),
            json!(32),
            json!(name),
            json!(32),
            json!("event"),
            json!(1),
            json!(1),
            json!(11),
            json!(38),
        ]
    }

    #[test]
    fn the_event_equality_shape_is_recognized_with_its_name() {
        assert_eq!(
            classify(&event_equality("purchase")),
            EvaluationClass::EventOnly {
                event: "purchase".to_owned()
            }
        );
    }

    /// The catalog loader appends a `RETURN` to bytecode that may already end in one, so the shape
    /// reaches this matcher with either tail.
    #[test]
    fn a_repeated_trailing_return_still_matches() {
        let mut doubled = event_equality("purchase");
        doubled.push(json!(38));
        assert_eq!(
            classify(&doubled),
            EvaluationClass::EventOnly {
                event: "purchase".to_owned()
            }
        );
    }

    /// Every near miss must classify as general. Reading any of these as event-only would skip the
    /// per-row evaluation the condition actually needs, and admit rows that do not match.
    #[test]
    fn near_misses_all_classify_as_general() {
        let cases: Vec<(&str, Vec<Value>)> = vec![
            ("missing header", event_equality("purchase")[1..].to_vec()),
            ("no version token", {
                let mut tokens = event_equality("purchase");
                tokens.remove(1);
                tokens
            }),
            ("greater-or-equal instead of equality", {
                let mut tokens = event_equality("purchase");
                tokens[8] = json!(14);
                tokens
            }),
            ("a different global", {
                let mut tokens = event_equality("purchase");
                tokens[5] = json!("distinct_id");
                tokens
            }),
            ("a two-segment global chain", {
                let mut tokens = event_equality("purchase");
                tokens[7] = json!(2);
                tokens
            }),
            ("an extra instruction before the return", {
                let mut tokens = event_equality("purchase");
                tokens.insert(9, json!(5));
                tokens
            }),
            ("no return at all", event_equality("purchase")[..9].to_vec()),
            ("a non-literal event name", {
                let mut tokens = event_equality("purchase");
                tokens[3] = json!(7);
                tokens
            }),
            ("empty bytecode", Vec::new()),
            ("header only", vec![json!("_H"), json!(1)]),
            // The VM refuses a version it cannot read as a `u64`, so these programs never run.
            // Classifying one as event-only would say "needs no evaluation" about a program that
            // would in fact have errored.
            ("a negative version", {
                let mut tokens = event_equality("purchase");
                tokens[1] = json!(-1);
                tokens
            }),
            ("a fractional version", {
                let mut tokens = event_equality("purchase");
                tokens[1] = json!(1.5);
                tokens
            }),
        ];
        for (label, tokens) in cases {
            assert_eq!(classify(&tokens), EvaluationClass::General, "{label}");
        }
    }
}
