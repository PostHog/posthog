//! The loaded form of a cohort condition's bytecode: header-validated and token-decoded once.

use std::fmt;

use hogvm::{Operation, Program, VmError};
use serde_json::Value;

/// A cohort condition's bytecode in the form the evaluator runs: the stored program with the
/// loader's trailing `RETURN`, header-validated and token-decoded once at catalog build. Wraps
/// [`Program`] (two `Arc`s), so cloning one into an `ExecutionContext` is two refcount bumps and
/// never re-decodes.
#[derive(Clone)]
pub struct ConditionProgram(Program);

impl ConditionProgram {
    /// Mirrors the VM's load acceptance without decoding duplicate condition bodies. A differential
    /// test guards this mirror against changes to the VM loader.
    pub(crate) fn has_valid_stored_header(stored: &[Value]) -> bool {
        // A missing version becomes the appended RETURN, which is a valid u64 version.
        stored.first().and_then(Value::as_str) == Some("_H")
            && stored
                .get(1)
                .is_none_or(|version| version.as_u64().is_some())
    }

    /// Load a stored cohort program: append `RETURN`, then validate the header and decode the
    /// tokens. The only failure is a rejected header.
    ///
    /// # Errors
    /// [`VmError::InvalidBytecode`] when the array does not start with the `_H` marker followed by
    /// an integer version.
    pub fn from_stored(stored: &[Value]) -> Result<Self, VmError> {
        let mut bytecode = Vec::with_capacity(stored.len() + 1);
        bytecode.extend_from_slice(stored);
        // Python-compiled cohort bytecode ends at its root comparison with no `RETURN`, which the
        // Rust VM would hit as `EndOfProgram`. A program already ending in `RETURN` stops at the
        // first, so the appended one is inert.
        bytecode.push(Value::from(Operation::Return));
        Program::new(bytecode).map(Self)
    }

    /// The full token array, header and appended `RETURN` included: the input of the static
    /// analysis and the view a census or a test needs.
    pub fn tokens(&self) -> &[Value] {
        self.0.tokens()
    }

    pub(crate) fn program(&self) -> &Program {
        &self.0
    }
}

/// Required, not stylistic: [`Program`] has no `Debug`, so [`crate::TeamFilters`] and the seeder's
/// pinned runs could not derive theirs without it. Prints the token count and
/// version rather than the tokens, which would otherwise dump every condition's whole program.
impl fmt::Debug for ConditionProgram {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ConditionProgram")
            .field("tokens", &self.0.tokens().len())
            .field("version", &self.0.version())
            .finish()
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::hogvm::{evaluate_detailed, EvalOutcome};
    use serde_json::json;

    const OP_TRUE: i64 = 29;
    const OP_RETURN: i64 = Operation::Return as i64;

    #[test]
    fn from_stored_appends_the_terminating_return() {
        let stored = [json!("_H"), json!(1), json!(OP_TRUE)];
        let program = ConditionProgram::from_stored(&stored).expect("a valid header loads");
        assert_eq!(
            program.tokens(),
            &[json!("_H"), json!(1), json!(OP_TRUE), json!(OP_RETURN)],
        );
    }

    #[test]
    fn an_already_terminated_program_evaluates_the_same_after_the_append() {
        // The first `RETURN` finishes the run with an empty frame stack, so the appended one is
        // unreachable — a stored program that already ends in `RETURN` must not change meaning.
        let terminated = [json!("_H"), json!(1), json!(OP_TRUE), json!(OP_RETURN)];
        let program = ConditionProgram::from_stored(&terminated).expect("a valid header loads");
        assert_eq!(program.tokens().len(), terminated.len() + 1);
        assert!(matches!(
            evaluate_detailed(&terminated, json!({})),
            EvalOutcome::Matched(true),
        ));
        assert!(matches!(
            evaluate_detailed(program.tokens(), json!({})),
            EvalOutcome::Matched(true),
        ));
    }

    #[test]
    fn stored_header_validation_matches_the_vm_load() {
        for (stored, expected) in [
            (json!([]), false),
            (json!(["_X", 1]), false),
            (json!(["_H", "one"]), false),
            (json!(["_H", -1]), false),
            (json!(["_H", true]), false),
            (json!(["_H", 1.0]), false),
            (json!(["_H", null]), false),
            (json!(["_H", []]), false),
            (json!(["_H"]), true),
            (json!(["_H", 0]), true),
            (json!(["_H", 1, OP_TRUE]), true),
            (json!(["_H", u64::MAX]), true),
            (
                serde_json::from_str("[\"_H\",18446744073709551616]").unwrap(),
                false,
            ),
        ] {
            let stored = stored.as_array().unwrap();
            assert_eq!(
                ConditionProgram::has_valid_stored_header(stored),
                expected,
                "{stored:?}"
            );
            assert_eq!(
                ConditionProgram::from_stored(stored).is_ok(),
                expected,
                "{stored:?}"
            );
        }

        let header_values = [
            Value::Null,
            json!(false),
            json!(true),
            json!(-1),
            json!(0),
            json!(u64::MAX),
            json!(1.0),
            serde_json::from_str("18446744073709551616").unwrap(),
            json!(""),
            json!("_H"),
            json!("_X"),
            json!([]),
            json!({}),
        ];
        for marker in &header_values {
            for version in &header_values {
                for body in [json!([]), json!([OP_TRUE, OP_RETURN]), json!(header_values)] {
                    let mut stored = vec![marker.clone(), version.clone()];
                    stored.extend(body.as_array().unwrap().iter().cloned());
                    assert_eq!(
                        ConditionProgram::has_valid_stored_header(&stored),
                        ConditionProgram::from_stored(&stored).is_ok(),
                        "{stored:?}",
                    );
                }
            }
        }
    }
}
