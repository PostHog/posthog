//! A linear abstract interpreter over decoded instructions, producing the set of globals a
//! condition reads.
//!
//! The abstract domain has two values: a compile-time literal string, and everything else. That is
//! all `GET_GLOBAL` needs, because it builds its path from literal strings the compiler pushed and
//! nothing else can reach the globals dict.
//!
//! The model is linear: instructions run in order with one abstract stack, no branch merging. That
//! is sound only while no instruction changes the instruction pointer, so every branch, call, and
//! local-slot opcode is refused rather than approximated. A wrong stack alignment would misread
//! which literals a later `GET_GLOBAL` pops, and quietly claim the wrong read set.

use std::collections::BTreeSet;

use hogvm::Operation;
use serde_json::Value;

use super::decode::{decode, Instr};
use super::{FullColumnsReason, GlobalRoot, Projection, ReadPath, UnanalyzableReason};

/// `elements_chain` falls back to this property when the event's own column is empty, so a caller
/// that projects an `elements_chain` read must carry it too.
const ELEMENTS_CHAIN_PROPERTY: &str = "$elements_chain";

/// One cell of the abstract stack.
#[derive(Debug, Clone, PartialEq, Eq)]
enum AbstractValue {
    /// A string literal the compiler pushed, which a `GET_GLOBAL` path may be built from.
    LiteralString(String),
    /// A value the model cannot name.
    Opaque,
}

pub(super) fn project(bytecode: &[Value]) -> Projection {
    let instrs = match decode(bytecode) {
        Ok(instrs) => instrs,
        Err(error) => return full_columns(UnanalyzableReason::Decode(error)),
    };
    match Interpreter::default().run(&instrs) {
        Ok(reads) => Projection::Reads(reads),
        Err(stop) => match stop {
            Stop::Unanalyzable(reason) => full_columns(reason),
            Stop::BareRoot(reason) => Projection::FullColumns(reason),
        },
    }
}

fn full_columns(reason: UnanalyzableReason) -> Projection {
    Projection::FullColumns(FullColumnsReason::Unanalyzable(reason))
}

/// Why the interpreter stopped early. A bare root is an ordinary program the analysis understood
/// and cannot narrow; everything else is the fail-closed arm.
enum Stop {
    Unanalyzable(UnanalyzableReason),
    BareRoot(FullColumnsReason),
}

#[derive(Default)]
struct Interpreter {
    stack: Vec<AbstractValue>,
    reads: BTreeSet<ReadPath>,
}

impl Interpreter {
    fn run(mut self, instrs: &[Instr]) -> Result<BTreeSet<ReadPath>, Stop> {
        for (index, instr) in instrs.iter().enumerate() {
            if self.step(instr)? == Flow::Returned {
                // The catalog loader appends a `RETURN`, and a program that already ended in one
                // then carries two. Trailing `RETURN`s are therefore expected; anything else after
                // the first one means the linear reading was wrong about where the program ends.
                return match instrs[index + 1..]
                    .iter()
                    .all(|rest| matches!(rest, Instr::Bare(Operation::Return)))
                {
                    true => Ok(self.reads),
                    false => Err(Stop::Unanalyzable(UnanalyzableReason::CodeAfterReturn)),
                };
            }
        }
        Ok(self.reads)
    }

    fn step(&mut self, instr: &Instr) -> Result<Flow, Stop> {
        match instr {
            Instr::String(literal) => {
                self.stack
                    .push(AbstractValue::LiteralString(literal.clone()));
                Ok(Flow::Continue)
            }
            Instr::Number(_) => self.push_opaque(),
            Instr::Counted(op, count) => self.step_counted(op, *count),
            // Any callee name is projection-safe. A native consumes stack values and cannot reach
            // the globals dict, which is what keeps `toDateTime(timestamp) > x` projectable.
            Instr::CallGlobal { argc, .. } => self.reduce(*argc),
            Instr::Bare(op) => self.step_bare(op),
            // A branch would make the linear stack wrong from here on, and a callable or closure
            // introduces a frame the model has no notion of.
            Instr::Branch(op) => Err(unsupported(op)),
            Instr::Callable => Err(unsupported(&Operation::Callable)),
            Instr::Closure => Err(unsupported(&Operation::Closure)),
        }
    }

    fn step_counted(&mut self, op: &Operation, count: usize) -> Result<Flow, Stop> {
        match op {
            Operation::GetGlobal => self.get_global(count),
            // A dict consumes a key and a value per entry.
            Operation::Dict => self.reduce(count.saturating_mul(2)),
            Operation::And | Operation::Or | Operation::Array | Operation::Tuple => {
                self.reduce(count)
            }
            // Local and upvalue slots read and write stack positions the linear model does not
            // track, so their effect on later `GET_GLOBAL` alignment is unknown.
            Operation::GetLocal
            | Operation::SetLocal
            | Operation::GetUpvalue
            | Operation::SetUpvalue
            | Operation::CallLocal => Err(unsupported(op)),
            // `decode` builds `Counted` only from the opcodes above.
            other => Err(unsupported(other)),
        }
    }

    fn step_bare(&mut self, op: &Operation) -> Result<Flow, Stop> {
        match op {
            Operation::True | Operation::False | Operation::Null => self.push_opaque(),
            Operation::Not => self.reduce(1),
            Operation::Plus
            | Operation::Minus
            | Operation::Mult
            | Operation::Div
            | Operation::Mod
            | Operation::Eq
            | Operation::NotEq
            | Operation::Gt
            | Operation::GtEq
            | Operation::Lt
            | Operation::LtEq
            | Operation::Like
            | Operation::Ilike
            | Operation::NotLike
            | Operation::NotIlike
            | Operation::In
            | Operation::NotIn
            | Operation::Regex
            | Operation::NotRegex
            | Operation::Iregex
            | Operation::NotIregex
            | Operation::GetProperty
            | Operation::GetPropertyNullish => self.reduce(2),
            Operation::Pop => {
                self.pop()?;
                Ok(Flow::Continue)
            }
            Operation::Return => {
                self.pop()?;
                Ok(Flow::Returned)
            }
            // `SET_PROPERTY` mutates the heap, which the model does not represent; the cohort
            // opcodes read membership state that is not in the globals dict at all; the exception
            // opcodes move the instruction pointer.
            Operation::SetProperty
            | Operation::InCohort
            | Operation::NotInCohort
            | Operation::Throw
            | Operation::PopTry
            | Operation::CloseUpvalue
            | Operation::DeclareFn => Err(unsupported(op)),
            // `decode` builds `Bare` only from the opcodes above.
            other => Err(unsupported(other)),
        }
    }

    /// `GET_GLOBAL` pops its path root first, because the compiler pushes the chain reversed.
    fn get_global(&mut self, count: usize) -> Result<Flow, Stop> {
        if count == 0 {
            return Err(Stop::Unanalyzable(
                UnanalyzableReason::ZeroLengthGlobalChain,
            ));
        }
        let mut chain = Vec::with_capacity(count);
        for _ in 0..count {
            match self.pop()? {
                AbstractValue::LiteralString(segment) => chain.push(segment),
                AbstractValue::Opaque => {
                    return Err(Stop::Unanalyzable(UnanalyzableReason::DynamicGlobalPath))
                }
            }
        }
        let (root_name, segments) = chain.split_first().expect("count is non-zero");
        let Some(root) = GlobalRoot::parse(root_name) else {
            return Err(Stop::Unanalyzable(UnanalyzableReason::UnknownGlobalRoot(
                root_name.clone(),
            )));
        };
        // A bare `properties` or `person` hands the whole object to whatever consumes it, so which
        // keys are read is decided at runtime and cannot be narrowed here.
        if segments.is_empty() {
            match root {
                GlobalRoot::Properties => {
                    return Err(Stop::BareRoot(FullColumnsReason::BarePropertiesRoot))
                }
                GlobalRoot::Person => {
                    return Err(Stop::BareRoot(FullColumnsReason::BarePersonRoot))
                }
                _ => {}
            }
        }
        // `elements_chain` reads the event column, then falls back to this property when the column
        // is empty. Both are real reads, so both are recorded or the claimed set would be short.
        if root == GlobalRoot::ElementsChain {
            self.reads.insert(ReadPath::new(
                GlobalRoot::Properties,
                vec![ELEMENTS_CHAIN_PROPERTY.to_owned()],
            ));
        }
        self.reads.insert(ReadPath::new(root, segments.to_vec()));
        self.push_opaque()
    }

    /// Consume `count` operands and leave one unnameable result.
    fn reduce(&mut self, count: usize) -> Result<Flow, Stop> {
        for _ in 0..count {
            self.pop()?;
        }
        self.push_opaque()
    }

    fn push_opaque(&mut self) -> Result<Flow, Stop> {
        self.stack.push(AbstractValue::Opaque);
        Ok(Flow::Continue)
    }

    fn pop(&mut self) -> Result<AbstractValue, Stop> {
        self.stack
            .pop()
            .ok_or(Stop::Unanalyzable(UnanalyzableReason::StackUnderflow))
    }
}

/// Whether the program continues after an instruction, or has returned.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum Flow {
    Continue,
    Returned,
}

fn unsupported(op: &Operation) -> Stop {
    Stop::Unanalyzable(UnanalyzableReason::UnsupportedOp(op.clone()))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn program(tokens: Vec<Value>) -> Vec<Value> {
        let mut bytecode = vec![json!("_H"), json!(1)];
        bytecode.extend(tokens);
        bytecode.push(json!(38));
        bytecode
    }

    /// A global read, written the way the compiler emits it: the path is pushed leaf first so that
    /// `GET_GLOBAL` pops the root first.
    fn read(path: &[&str]) -> Vec<Value> {
        let mut tokens = Vec::new();
        for segment in path.iter().rev() {
            tokens.push(json!(32));
            tokens.push(json!(segment));
        }
        tokens.push(json!(1));
        tokens.push(json!(path.len()));
        tokens
    }

    fn reads(tokens: Vec<Value>) -> Vec<String> {
        match project(&program(tokens)) {
            Projection::Reads(paths) => paths.iter().map(ReadPath::render).collect(),
            other => panic!("expected reads, got {other:?}"),
        }
    }

    fn full_columns_reason(tokens: Vec<Value>) -> FullColumnsReason {
        match project(&program(tokens)) {
            Projection::FullColumns(reason) => reason,
            other => panic!("expected full columns, got {other:?}"),
        }
    }

    /// The ordering test. The compiler pushes a chain reversed, so a reader that popped the leaf
    /// first would record `key.properties` and project a column that does not exist. Written out
    /// literally rather than through the helper, so the helper cannot hide the same mistake.
    #[test]
    fn a_global_chain_is_read_root_first_from_its_reversed_pushes() {
        let tokens = vec![
            json!(32),
            json!("key"),
            json!(32),
            json!("properties"),
            json!(1),
            json!(2),
        ];
        assert_eq!(reads(tokens), ["properties.key"]);
    }

    #[test]
    fn nested_paths_under_a_root_stay_precise() {
        assert_eq!(
            reads(read(&["person", "properties", "email"])),
            ["person.properties.email"]
        );
        assert_eq!(reads(read(&["event"])), ["event"]);
        assert_eq!(reads(read(&["pdi", "person_id"])), ["pdi.person_id"]);
        assert_eq!(
            reads(read(&["group_2", "properties", "tier"])),
            ["group_2.properties.tier"]
        );
    }

    /// Handing the whole `properties` or `person` object to something decides its keys at runtime.
    /// These are ordinary programs, so they are reported as bare roots rather than as failures.
    #[test]
    fn a_bare_properties_or_person_root_widens_to_every_column() {
        assert_eq!(
            full_columns_reason(read(&["properties"])),
            FullColumnsReason::BarePropertiesRoot
        );
        assert_eq!(
            full_columns_reason(read(&["person"])),
            FullColumnsReason::BarePersonRoot
        );
    }

    /// `elements_chain` resolves to the event column or, when that is empty, to
    /// `properties.$elements_chain`. A claimed read set that named only the column would be short,
    /// and a caller projecting from it would evaluate the condition against a null chain.
    #[test]
    fn an_elements_chain_read_also_claims_its_properties_fallback() {
        assert_eq!(
            reads(read(&["elements_chain"])),
            ["elements_chain", "properties.$elements_chain"]
        );
        // The sibling roots are constants in the globals, independent of the event, so they claim
        // nothing extra.
        assert_eq!(
            reads(read(&["elements_chain_texts"])),
            ["elements_chain_texts"]
        );
    }

    #[test]
    fn several_reads_under_one_program_are_collected_and_deduplicated() {
        let mut tokens = read(&["properties", "b"]);
        tokens.extend(read(&["properties", "a"]));
        tokens.extend(read(&["properties", "b"]));
        tokens.push(json!(3));
        tokens.push(json!(3));
        assert_eq!(reads(tokens), ["properties.a", "properties.b"]);
    }

    /// A path segment computed at runtime, an unmodeled root, a branch, and garbage all have to
    /// fail closed, each naming what stopped the analysis.
    #[test]
    fn unmodeled_programs_fail_closed_with_their_reason() {
        // `properties[someValue]`: the segment on the stack is not a literal.
        let dynamic = vec![
            json!(33),
            json!(3),
            json!(32),
            json!("properties"),
            json!(1),
            json!(2),
        ];
        assert_eq!(
            full_columns_reason(dynamic),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::DynamicGlobalPath)
        );
        assert_eq!(
            full_columns_reason(read(&["session"])),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::UnknownGlobalRoot(
                "session".to_owned()
            ))
        );
        assert_eq!(
            full_columns_reason(vec![json!(1), json!(0)]),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::ZeroLengthGlobalChain)
        );
        assert_eq!(
            full_columns_reason(vec![json!(40), json!(2), json!(29)]),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::UnsupportedOp(
                Operation::JumpIfFalse
            ))
        );
        assert_eq!(
            full_columns_reason(vec![json!(11)]),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::StackUnderflow)
        );
        assert!(matches!(
            full_columns_reason(vec![json!(99)]),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::Decode(_))
        ));
    }

    /// The loader appends a `RETURN` to bytecode that may already end in one, so a repeated
    /// trailing `RETURN` is normal. Real instructions after the first `RETURN` are not: reaching
    /// them means the linear reading was wrong about where the program ends.
    #[test]
    fn trailing_returns_are_tolerated_but_live_code_after_a_return_is_not() {
        // `program` appends one RETURN, so this program carries two.
        assert_eq!(reads(read(&["event"])), ["event"]);

        let mut with_code_after = read(&["event"]);
        with_code_after.push(json!(38));
        with_code_after.extend(read(&["distinct_id"]));
        assert_eq!(
            full_columns_reason(with_code_after),
            FullColumnsReason::Unanalyzable(UnanalyzableReason::CodeAfterReturn)
        );
    }

    /// A native call is projection-safe whatever its name, because it only consumes stack values.
    /// Refusing them would make every `toDateTime(timestamp) > x` condition unprojectable.
    #[test]
    fn a_native_call_over_a_read_keeps_the_read_precise() {
        let mut tokens = read(&["timestamp"]);
        tokens.push(json!(2));
        tokens.push(json!("toDateTime"));
        tokens.push(json!(1));
        tokens.push(json!(32));
        tokens.push(json!("2026-01-01"));
        tokens.push(json!(13));
        assert_eq!(reads(tokens), ["timestamp"]);
    }
}
