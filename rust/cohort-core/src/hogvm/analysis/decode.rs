//! Turns a bytecode array into typed instructions, consuming each opcode's immediates exactly as
//! `hogvm::HogVM::step` does.
//!
//! This module holds no policy about which instructions an analysis can handle. It answers one
//! question: where does each instruction start and end. Getting that wrong would misread the
//! following tokens as opcodes, so the immediate counts here must track `vm.rs` and nothing else.

use hogvm::Operation;
use serde_json::Value;

/// One decoded instruction, grouped by the shape of its immediates rather than by what it does.
/// The [`Operation`] is always carried, so the interpreter still dispatches on the exact opcode.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum Instr {
    /// No immediates: comparisons, arithmetic, `NOT`, `POP`, `RETURN`, property reads, `THROW`,
    /// `POP_TRY`, `CLOSE_UPVALUE`, the cohort opcodes, and the bare constants.
    Bare(Operation),
    /// A single count immediate: `GET_GLOBAL`, `AND`, `OR`, `DICT`, `ARRAY`, `TUPLE`, `CALL_LOCAL`,
    /// the local slots, and the upvalue slots.
    Counted(Operation, usize),
    /// A single signed offset immediate: the jumps and `TRY`.
    Branch(Operation),
    /// `STRING` and the literal it pushes. The literal is the only immediate the analysis reads,
    /// because a global path is built from them.
    String(String),
    /// `INTEGER` or `FLOAT`. The value is not retained: the abstract domain cannot name a number,
    /// so nothing downstream could use it.
    Number(Operation),
    /// `CALL_GLOBAL`, with the callee name and its argument count.
    CallGlobal { name: String, argc: usize },
    /// `CALLABLE`. Its body tokens are skipped, exactly as the VM skips them by advancing past
    /// `body_length`, so the instructions after it decode at the right offsets.
    Callable,
    /// `CLOSURE`, with its capture pairs consumed.
    Closure,
}

/// Why a bytecode array could not be split into instructions.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum DecodeError {
    #[error("bytecode does not start with the `_H` marker")]
    MissingHeader,
    #[error("bytecode version marker is not a number")]
    MalformedVersion,
    #[error("token at {ip} is not an opcode")]
    NotAnOpcode { ip: usize },
    #[error("{op:?} at {ip} runs past the end of the bytecode")]
    TruncatedImmediates { ip: usize, op: Operation },
    #[error("{op:?} at {ip} has a malformed immediate")]
    MalformedImmediate { ip: usize, op: Operation },
}

/// Split `bytecode` into instructions.
///
/// The header handling mirrors `hogvm::Program::from_shared` exactly, version ambiguity included: a
/// pre-version program whose first opcode happens to be a number has that opcode read as its
/// version. The VM reads it the same way, so an analysis that disagreed would be describing a
/// program the VM never runs.
pub(super) fn decode(bytecode: &[Value]) -> Result<Vec<Instr>, DecodeError> {
    let mut cursor = Cursor::new(bytecode)?;
    let mut instrs = Vec::new();
    while let Some(instr) = cursor.next_instr()? {
        instrs.push(instr);
    }
    Ok(instrs)
}

struct Cursor<'a> {
    tokens: &'a [Value],
    ip: usize,
}

impl<'a> Cursor<'a> {
    fn new(bytecode: &'a [Value]) -> Result<Self, DecodeError> {
        if bytecode.first().and_then(Value::as_str) != Some("_H") {
            return Err(DecodeError::MissingHeader);
        }
        let body_start = match bytecode.get(1) {
            None => 1,
            Some(Value::Number(_)) => 2,
            Some(_) => return Err(DecodeError::MalformedVersion),
        };
        Ok(Self {
            tokens: bytecode,
            ip: body_start,
        })
    }

    fn next_instr(&mut self) -> Result<Option<Instr>, DecodeError> {
        let Some(token) = self.tokens.get(self.ip) else {
            return Ok(None);
        };
        let op_ip = self.ip;
        let op = Operation::try_from(token.clone())
            .map_err(|_| DecodeError::NotAnOpcode { ip: op_ip })?;
        self.ip += 1;
        self.instr_for(op, op_ip).map(Some)
    }

    /// The immediate table, one arm per opcode. Exhaustive on purpose: a new opcode in the VM must
    /// not silently inherit "no immediates", which would misalign every instruction after it.
    fn instr_for(&mut self, op: Operation, op_ip: usize) -> Result<Instr, DecodeError> {
        match op {
            Operation::String => Ok(Instr::String(self.take_string(&op, op_ip)?)),
            Operation::Integer | Operation::Float => {
                self.take_token(&op, op_ip)?;
                Ok(Instr::Number(op))
            }
            Operation::GetGlobal
            | Operation::And
            | Operation::Or
            | Operation::Dict
            | Operation::Array
            | Operation::Tuple
            | Operation::CallLocal
            | Operation::GetLocal
            | Operation::SetLocal
            | Operation::GetUpvalue
            | Operation::SetUpvalue => Ok(Instr::Counted(op.clone(), self.take_count(&op, op_ip)?)),
            Operation::Jump
            | Operation::JumpIfFalse
            | Operation::JumpIfStackNotNull
            | Operation::Try => {
                self.take_i64(&op, op_ip)?;
                Ok(Instr::Branch(op))
            }
            Operation::CallGlobal => {
                let name = self.take_string(&op, op_ip)?;
                let argc = self.take_count(&op, op_ip)?;
                Ok(Instr::CallGlobal { name, argc })
            }
            Operation::Callable => {
                self.take_string(&op, op_ip)?;
                self.take_count(&op, op_ip)?;
                self.take_count(&op, op_ip)?;
                let body_length = self.take_count(&op, op_ip)?;
                self.skip(body_length, &op, op_ip)?;
                Ok(Instr::Callable)
            }
            Operation::Closure => {
                let captures = self.take_count(&op, op_ip)?;
                // Each capture is an `is_local` flag and a slot offset.
                let pairs = captures
                    .checked_mul(2)
                    .ok_or_else(|| malformed(&op, op_ip))?;
                self.skip(pairs, &op, op_ip)?;
                Ok(Instr::Closure)
            }
            // `DECLARE_FN` reaches the VM only to be refused, so it never consumes its immediates
            // there and there is no arity to copy. Reading it as bare keeps this decoder aligned
            // with the VM; the interpreter refuses the opcode either way.
            Operation::DeclareFn
            | Operation::Not
            | Operation::Plus
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
            | Operation::InCohort
            | Operation::NotInCohort
            | Operation::True
            | Operation::False
            | Operation::Null
            | Operation::Pop
            | Operation::Return
            | Operation::GetProperty
            | Operation::SetProperty
            | Operation::GetPropertyNullish
            | Operation::Throw
            | Operation::PopTry
            | Operation::CloseUpvalue => Ok(Instr::Bare(op)),
        }
    }

    fn take_token(&mut self, op: &Operation, op_ip: usize) -> Result<&'a Value, DecodeError> {
        let token = self.tokens.get(self.ip).ok_or(truncated(op, op_ip))?;
        self.ip += 1;
        Ok(token)
    }

    fn take_string(&mut self, op: &Operation, op_ip: usize) -> Result<String, DecodeError> {
        self.take_token(op, op_ip)?
            .as_str()
            .map(str::to_owned)
            .ok_or(malformed(op, op_ip))
    }

    fn take_count(&mut self, op: &Operation, op_ip: usize) -> Result<usize, DecodeError> {
        self.take_token(op, op_ip)?
            .as_u64()
            .and_then(|count| usize::try_from(count).ok())
            .ok_or(malformed(op, op_ip))
    }

    fn take_i64(&mut self, op: &Operation, op_ip: usize) -> Result<i64, DecodeError> {
        self.take_token(op, op_ip)?
            .as_i64()
            .ok_or(malformed(op, op_ip))
    }

    fn skip(&mut self, count: usize, op: &Operation, op_ip: usize) -> Result<(), DecodeError> {
        let end = self
            .ip
            .checked_add(count)
            .ok_or_else(|| malformed(op, op_ip))?;
        if end > self.tokens.len() {
            return Err(truncated(op, op_ip));
        }
        self.ip = end;
        Ok(())
    }
}

fn truncated(op: &Operation, ip: usize) -> DecodeError {
    DecodeError::TruncatedImmediates { ip, op: op.clone() }
}

fn malformed(op: &Operation, ip: usize) -> DecodeError {
    DecodeError::MalformedImmediate { ip, op: op.clone() }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    fn body(tokens: Vec<Value>) -> Vec<Value> {
        let mut bytecode = vec![json!("_H"), json!(1)];
        bytecode.extend(tokens);
        bytecode
    }

    /// One case per immediate arity class. A wrong count here shifts every later instruction, so
    /// the decoded sequence is asserted whole rather than by length.
    #[test]
    fn each_arity_class_consumes_exactly_its_immediates() {
        let cases: Vec<(Vec<Value>, Vec<Instr>)> = vec![
            (vec![json!(11)], vec![Instr::Bare(Operation::Eq)]),
            (
                vec![json!(32), json!("x"), json!(35)],
                vec![Instr::String("x".to_owned()), Instr::Bare(Operation::Pop)],
            ),
            (
                vec![json!(33), json!(7), json!(34), json!(1.5), json!(35)],
                vec![
                    Instr::Number(Operation::Integer),
                    Instr::Number(Operation::Float),
                    Instr::Bare(Operation::Pop),
                ],
            ),
            (
                vec![json!(1), json!(2), json!(35)],
                vec![
                    Instr::Counted(Operation::GetGlobal, 2),
                    Instr::Bare(Operation::Pop),
                ],
            ),
            (
                vec![json!(39), json!(-4), json!(35)],
                vec![Instr::Branch(Operation::Jump), Instr::Bare(Operation::Pop)],
            ),
            (
                vec![json!(2), json!("toString"), json!(1), json!(35)],
                vec![
                    Instr::CallGlobal {
                        name: "toString".to_owned(),
                        argc: 1,
                    },
                    Instr::Bare(Operation::Pop),
                ],
            ),
            (
                // CALLABLE skips its two body tokens the way the VM does, so POP decodes after it.
                vec![
                    json!(52),
                    json!("f"),
                    json!(0),
                    json!(0),
                    json!(2),
                    json!(29),
                    json!(38),
                    json!(35),
                ],
                vec![Instr::Callable, Instr::Bare(Operation::Pop)],
            ),
            (
                // CLOSURE with two captures consumes four capture tokens.
                vec![
                    json!(53),
                    json!(2),
                    json!(true),
                    json!(0),
                    json!(false),
                    json!(1),
                    json!(35),
                ],
                vec![Instr::Closure, Instr::Bare(Operation::Pop)],
            ),
        ];
        for (tokens, expected) in cases {
            assert_eq!(
                decode(&body(tokens.clone())).unwrap(),
                expected,
                "{tokens:?}"
            );
        }
    }

    /// Truncation must be an error rather than a short read, in every arity class including the
    /// variable-length ones. A silent short read would leave the analysis describing a program that
    /// does not exist.
    #[test]
    fn truncated_immediates_are_rejected_in_every_arity_class() {
        let cases: Vec<(Vec<Value>, Operation)> = vec![
            (vec![json!(32)], Operation::String),
            (vec![json!(33)], Operation::Integer),
            (vec![json!(1)], Operation::GetGlobal),
            (vec![json!(39)], Operation::Jump),
            (vec![json!(2), json!("f")], Operation::CallGlobal),
            (
                vec![json!(52), json!("f"), json!(0), json!(0)],
                Operation::Callable,
            ),
            // The body runs past the end.
            (
                vec![
                    json!(52),
                    json!("f"),
                    json!(0),
                    json!(0),
                    json!(4),
                    json!(29),
                ],
                Operation::Callable,
            ),
            // The capture pairs run past the end, mid-capture.
            (
                vec![json!(53), json!(2), json!(true), json!(0), json!(false)],
                Operation::Closure,
            ),
        ];
        for (tokens, op) in cases {
            let error = decode(&body(tokens.clone())).unwrap_err();
            assert!(
                matches!(&error, DecodeError::TruncatedImmediates { op: actual, .. } if *actual == op),
                "{tokens:?} gave {error:?}"
            );
        }
    }

    #[test]
    fn malformed_immediates_are_rejected_by_kind() {
        let cases: Vec<(Vec<Value>, Operation)> = vec![
            (vec![json!(32), json!(7)], Operation::String),
            (vec![json!(1), json!("two")], Operation::GetGlobal),
            (vec![json!(1), json!(-1)], Operation::GetGlobal),
            (vec![json!(39), json!("far")], Operation::Jump),
            (vec![json!(2), json!(7), json!(1)], Operation::CallGlobal),
        ];
        for (tokens, op) in cases {
            let error = decode(&body(tokens.clone())).unwrap_err();
            assert!(
                matches!(&error, DecodeError::MalformedImmediate { op: actual, .. } if *actual == op),
                "{tokens:?} gave {error:?}"
            );
        }
    }

    #[test]
    fn a_token_that_is_not_an_opcode_is_rejected_with_its_position() {
        assert_eq!(
            decode(&body(vec![json!(11), json!(99)])).unwrap_err(),
            DecodeError::NotAnOpcode { ip: 3 }
        );
        assert_eq!(
            decode(&body(vec![json!("bare")])).unwrap_err(),
            DecodeError::NotAnOpcode { ip: 2 }
        );
    }

    /// The header rules mirror the VM's: `_H` is mandatory, a numeric version token is consumed,
    /// and a non-numeric one is an error rather than a first opcode.
    #[test]
    fn the_header_is_read_exactly_as_the_vm_reads_it() {
        assert_eq!(decode(&[]).unwrap_err(), DecodeError::MissingHeader);
        assert_eq!(
            decode(&[json!(1), json!(32)]).unwrap_err(),
            DecodeError::MissingHeader
        );
        assert_eq!(
            decode(&[json!("_H"), json!("v1")]).unwrap_err(),
            DecodeError::MalformedVersion
        );
        // A bare marker is a valid, empty program.
        assert_eq!(decode(&[json!("_H")]).unwrap(), Vec::new());
        assert_eq!(decode(&[json!("_H"), json!(1)]).unwrap(), Vec::new());
        // The version slot is consumed even when it holds what looks like an opcode, because the
        // VM consumes it too.
        assert_eq!(
            decode(&[json!("_H"), json!(35), json!(35)]).unwrap(),
            vec![Instr::Bare(Operation::Pop)]
        );
    }
}
