//! The loaded form of a cohort condition's bytecode: header-validated and token-decoded once.

use std::fmt;

use hogvm::{Program, VmError};
use serde_json::Value;

/// HogVM `RETURN` opcode, appended to each stored program at load. Python-compiled cohort bytecode
/// ends at its root comparison with no `RETURN`, which the Rust VM would hit as `EndOfProgram`. A
/// program already ending in `RETURN` stops at the first, so the appended one is inert.
const OP_RETURN: i64 = 38;

/// A cohort condition's bytecode in the form the evaluator runs: the stored program with the
/// loader's trailing `RETURN`, header-validated and token-decoded once at catalog build. Wraps
/// [`Program`] (two `Arc`s), so cloning one into an `ExecutionContext` is two refcount bumps and
/// never re-decodes.
#[derive(Clone)]
pub struct ConditionProgram(Program);

impl ConditionProgram {
    /// Load a stored cohort program: append `RETURN`, then validate the header and decode the
    /// tokens. The only failure is a rejected header.
    ///
    /// # Errors
    /// [`VmError::InvalidBytecode`] when the array does not start with the `_H` marker followed by
    /// an integer version.
    pub fn from_stored(stored: &[Value]) -> Result<Self, VmError> {
        let mut bytecode = Vec::with_capacity(stored.len() + 1);
        bytecode.extend_from_slice(stored);
        bytecode.push(Value::from(OP_RETURN));
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

    /// A minimal valid program, for fixtures whose subject is the leaf's shape rather than its
    /// bytecode. Never evaluated — the leaf configs simply cannot be built without one.
    #[cfg(test)]
    pub(crate) fn bare_header() -> Self {
        Self::from_stored(&[Value::from("_H"), Value::from(1)])
            .expect("a bare bytecode header is a valid program")
    }
}

/// Required, not stylistic: [`Program`] has no `Debug`, so the leaf configs, [`crate::TeamFilters`],
/// and the seeder's pinned runs could not derive theirs without it. Prints the token count and
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
    fn every_header_rejection_fails_the_load() {
        for (stored, why) in [
            (
                vec![],
                "empty stored array becomes `[RETURN]`, whose marker is a number",
            ),
            (vec![json!("_X"), json!(1)], "marker is not `_H`"),
            (vec![json!("_H"), json!("one")], "version is not an integer"),
        ] {
            assert!(
                matches!(
                    ConditionProgram::from_stored(&stored),
                    Err(VmError::InvalidBytecode(_)),
                ),
                "{why}",
            );
        }
    }
}
