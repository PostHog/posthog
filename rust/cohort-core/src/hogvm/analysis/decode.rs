//! Turns a bytecode array into typed instructions, consuming each opcode's immediates exactly as
//! `hogvm::HogVM::step` does.
//!
//! This module holds no policy about which instructions an analysis can handle. It answers two
//! questions: where does each instruction start and end, and where does each branch land. Getting
//! the first wrong would misread the following tokens as opcodes, so the immediate counts here must
//! track `vm.rs` and nothing else. Whether a landing site is *legal* is the analysis layer's call,
//! because only that layer knows where instructions begin.

use std::sync::Arc;

use hogvm::Operation;
use serde_json::Value;

/// A position in the raw token array. Jump offsets are expressed in these, and the VM resolves them
/// against a body-relative instruction pointer — which differs from an index into the full array by
/// the constant header length, so adding an offset gives the same landing site either way.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub(super) struct TokenIndex(pub(super) usize);

/// A position in the decoded instruction list.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub(super) struct InstrIndex(pub(super) usize);

/// One decoded instruction and where it starts, so a branch target can be matched against the
/// instruction boundaries.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Instr {
    pub(super) start: TokenIndex,
    pub(super) kind: InstrKind,
}

/// The instruction itself, grouped by the shape of its immediates rather than by what it does. The
/// [`Operation`] is always carried, so the interpreter still dispatches on the exact opcode.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) enum InstrKind {
    /// No immediates: comparisons, arithmetic, `NOT`, `POP`, `RETURN`, property reads, `THROW`,
    /// `POP_TRY`, `CLOSE_UPVALUE`, the cohort opcodes, and the bare constants.
    Bare(Operation),
    /// A single count immediate: `GET_GLOBAL`, `AND`, `OR`, `DICT`, `ARRAY`, `TUPLE`, `CALL_LOCAL`,
    /// the local slots, and the upvalue slots.
    Counted(Operation, usize),
    /// A jump, with its offset resolved to the token it lands on. `None` when the offset resolves
    /// outside the addressable range, which is refused on visit rather than at decode: an offset no
    /// path follows must not fail a program that never reaches the opcode.
    Branch {
        op: Operation,
        target: Option<TokenIndex>,
    },
    /// `TRY`. It carries a jump offset like the branches, but the interpreter refuses it, so no
    /// landing site is resolved: an offset nothing will follow must not be able to fail a program
    /// that never reaches the opcode.
    Try,
    /// `STRING` and the literal it pushes. The literal is the only immediate the analysis reads,
    /// because a global path is built from them. `Arc<str>` because the interpreter carries these
    /// on abstract stacks it copies at every branch merge, and copying the bytes there is what
    /// turns one long literal into an allocation proportional to the program length.
    String(Arc<str>),
    /// `INTEGER` or `FLOAT`. The value is not retained: the abstract domain cannot name a number,
    /// so nothing downstream could use it.
    Number(Operation),
    /// `CALL_GLOBAL`, with the callee name and its argument count.
    CallGlobal { name: String, argc: usize },
    /// `CALLABLE`, with the span of the body tokens it skips. The interpreter skips them exactly as
    /// the VM does by advancing past `body_length`; the span is kept so a caller that needs to look
    /// inside — the standard-library guard — can decode them in place.
    Callable { body: TokenSpan },
    /// `CLOSURE`, with its capture pairs consumed.
    Closure,
}

/// A half-open token range, in absolute positions so a nested decode resolves jumps the same way
/// the enclosing one does.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub(super) struct TokenSpan {
    pub(super) start: TokenIndex,
    pub(super) end: TokenIndex,
}

/// A decoded program: its instructions, and the token one past its last, which is where a jump off
/// the end lands.
#[derive(Debug, Clone, PartialEq, Eq)]
pub(super) struct Decoded {
    pub(super) instrs: Vec<Instr>,
    pub(super) body_end: TokenIndex,
}

/// Why a bytecode array could not be split into instructions.
#[derive(Debug, Clone, PartialEq, Eq, thiserror::Error)]
pub enum DecodeError {
    #[error("bytecode does not start with the `_H` marker")]
    MissingHeader,
    #[error("bytecode version marker is not an unsigned integer")]
    MalformedVersion,
    #[error("token at {ip} is not an opcode")]
    NotAnOpcode { ip: usize },
    #[error("{op:?} at {ip} runs past the end of the bytecode")]
    TruncatedImmediates { ip: usize, op: Operation },
    #[error("{op:?} at {ip} has a malformed immediate")]
    MalformedImmediate { ip: usize, op: Operation },
}

impl DecodeError {
    /// Which opcode's immediates could not be read, when the failure names one.
    ///
    /// Exhaustive rather than defaulted, so a new variant carrying an [`Operation`] has to decide
    /// whether it surfaces here. Losing the opcode silently is what makes a decoder-versus-VM drift
    /// read as one anonymous bucket, which is the case this label exists for.
    pub fn op(&self) -> Option<Operation> {
        match self {
            Self::TruncatedImmediates { op, .. } | Self::MalformedImmediate { op, .. } => Some(*op),
            Self::MissingHeader | Self::MalformedVersion | Self::NotAnOpcode { .. } => None,
        }
    }
}

/// Split `bytecode` into instructions.
///
/// The header handling mirrors `hogvm::Program::from_shared` exactly, version ambiguity included: a
/// pre-version program whose first opcode happens to be a number has that opcode read as its
/// version. The VM reads it the same way, so an analysis that disagreed would be describing a
/// program the VM never runs. That is also why the version has to be an unsigned integer here: the
/// VM takes it through `as_u64`, so a negative or fractional version is a program it refuses to
/// load, and accepting it would classify bytecode that never runs.
pub(super) fn decode(bytecode: &[Value]) -> Result<Decoded, DecodeError> {
    if bytecode.first().and_then(Value::as_str) != Some("_H") {
        return Err(DecodeError::MissingHeader);
    }
    let body_start = match bytecode.get(1) {
        None => 1,
        Some(Value::Number(version)) if version.as_u64().is_some() => 2,
        Some(_) => return Err(DecodeError::MalformedVersion),
    };
    decode_span(
        bytecode,
        TokenSpan {
            start: TokenIndex(body_start),
            end: TokenIndex(bytecode.len()),
        },
    )
}

/// Decode one span of an already-headered array — a `CALLABLE` body, say. Positions stay absolute,
/// so a jump inside the span resolves to the same token the VM would reach.
pub(super) fn decode_span(tokens: &[Value], span: TokenSpan) -> Result<Decoded, DecodeError> {
    let mut cursor = Cursor {
        tokens,
        ip: span.start.0,
        end: span.end.0,
    };
    let mut instrs = Vec::new();
    while let Some(instr) = cursor.next_instr()? {
        instrs.push(instr);
    }
    Ok(Decoded {
        instrs,
        body_end: span.end,
    })
}

struct Cursor<'a> {
    tokens: &'a [Value],
    ip: usize,
    end: usize,
}

impl<'a> Cursor<'a> {
    fn next_instr(&mut self) -> Result<Option<Instr>, DecodeError> {
        if self.ip >= self.end {
            return Ok(None);
        }
        let op_ip = self.ip;
        let token = &self.tokens[op_ip];
        let op = Operation::try_from(token.clone())
            .map_err(|_| DecodeError::NotAnOpcode { ip: op_ip })?;
        self.ip += 1;
        Ok(Some(Instr {
            start: TokenIndex(op_ip),
            kind: self.kind_for(op, op_ip)?,
        }))
    }

    /// The immediate table, one arm per opcode. Exhaustive on purpose: a new opcode in the VM must
    /// not silently inherit "no immediates", which would misalign every instruction after it.
    fn kind_for(&mut self, op: Operation, op_ip: usize) -> Result<InstrKind, DecodeError> {
        match op {
            Operation::String => Ok(InstrKind::String(Arc::from(
                self.take_string(op, op_ip)?.as_str(),
            ))),
            Operation::Integer | Operation::Float => {
                self.take_token(op, op_ip)?;
                Ok(InstrKind::Number(op))
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
            | Operation::SetUpvalue => Ok(InstrKind::Counted(op, self.take_count(op, op_ip)?)),
            Operation::Jump | Operation::JumpIfFalse | Operation::JumpIfStackNotNull => {
                let target = self.take_target(op, op_ip)?;
                Ok(InstrKind::Branch { op, target })
            }
            // `TRY`'s immediate is consumed so the instructions after it decode at the right
            // offsets, but its offset is deliberately left unresolved — see [`InstrKind::Try`].
            Operation::Try => {
                self.take_i64(op, op_ip)?;
                Ok(InstrKind::Try)
            }
            Operation::CallGlobal => {
                let name = self.take_string(op, op_ip)?;
                let argc = self.take_count(op, op_ip)?;
                Ok(InstrKind::CallGlobal { name, argc })
            }
            Operation::Callable => {
                self.take_string(op, op_ip)?;
                self.take_count(op, op_ip)?;
                self.take_count(op, op_ip)?;
                let body_length = self.take_count(op, op_ip)?;
                let start = TokenIndex(self.ip);
                self.skip(body_length, op, op_ip)?;
                Ok(InstrKind::Callable {
                    body: TokenSpan {
                        start,
                        end: TokenIndex(self.ip),
                    },
                })
            }
            Operation::Closure => {
                let captures = self.take_count(op, op_ip)?;
                let pairs = captures.checked_mul(2).ok_or(malformed(op, op_ip))?;
                self.skip(pairs, op, op_ip)?;
                Ok(InstrKind::Closure)
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
            | Operation::CloseUpvalue => Ok(InstrKind::Bare(op)),
        }
    }

    fn take_token(&mut self, op: Operation, op_ip: usize) -> Result<&'a Value, DecodeError> {
        if self.ip >= self.end {
            return Err(truncated(op, op_ip));
        }
        let token = &self.tokens[self.ip];
        self.ip += 1;
        Ok(token)
    }

    fn take_string(&mut self, op: Operation, op_ip: usize) -> Result<String, DecodeError> {
        self.take_token(op, op_ip)?
            .as_str()
            .map(str::to_owned)
            .ok_or(malformed(op, op_ip))
    }

    /// Read a count immediate, bounded by the token count.
    ///
    /// Every count in the instruction set is either a span of tokens to skip or a number of stack
    /// values to consume, and the stack can never hold more values than the program has tokens to
    /// push them with. So no honest count exceeds `tokens.len()`, and refusing the rest here keeps
    /// a hostile catalog row from reaching a `Vec::with_capacity` downstream — where a `u64::MAX`
    /// is a capacity-overflow panic and a merely huge value is an allocation abort, neither of
    /// which the fail-closed contract can absorb.
    fn take_count(&mut self, op: Operation, op_ip: usize) -> Result<usize, DecodeError> {
        self.take_token(op, op_ip)?
            .as_u64()
            .and_then(|count| usize::try_from(count).ok())
            .filter(|count| *count <= self.tokens.len())
            .ok_or(malformed(op, op_ip))
    }

    fn take_i64(&mut self, op: Operation, op_ip: usize) -> Result<i64, DecodeError> {
        self.take_token(op, op_ip)?
            .as_i64()
            .ok_or(malformed(op, op_ip))
    }

    /// Resolve a jump offset against the instruction pointer the VM would hold: one past the
    /// offset immediate.
    ///
    /// An offset that resolves outside the addressable range yields `None` rather than an error.
    /// Whether a landing site is usable is the analysis layer's question, and it asks it on visit,
    /// so a dead jump cannot fail the decode of instructions a path does reach.
    fn take_target(
        &mut self,
        op: Operation,
        op_ip: usize,
    ) -> Result<Option<TokenIndex>, DecodeError> {
        let offset = self.take_i64(op, op_ip)?;
        Ok(i64::try_from(self.ip)
            .ok()
            .and_then(|ip| ip.checked_add(offset))
            .and_then(|target| usize::try_from(target).ok())
            .map(TokenIndex))
    }

    fn skip(&mut self, count: usize, op: Operation, op_ip: usize) -> Result<(), DecodeError> {
        let end = self.ip.checked_add(count).ok_or(malformed(op, op_ip))?;
        if end > self.end {
            return Err(truncated(op, op_ip));
        }
        self.ip = end;
        Ok(())
    }
}

fn truncated(op: Operation, ip: usize) -> DecodeError {
    DecodeError::TruncatedImmediates { ip, op }
}

fn malformed(op: Operation, ip: usize) -> DecodeError {
    DecodeError::MalformedImmediate { ip, op }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    /// The `["_H", <version>]` header [`body`] prepends, so a token position in a case is readable
    /// as an offset into that case's own tokens.
    const HEADER_LEN: usize = 2;

    fn body(tokens: Vec<Value>) -> Vec<Value> {
        let mut bytecode = vec![json!("_H"), json!(1)];
        bytecode.extend(tokens);
        bytecode
    }

    fn kinds(bytecode: &[Value]) -> Result<Vec<InstrKind>, DecodeError> {
        Ok(decode(bytecode)?
            .instrs
            .into_iter()
            .map(|instr| instr.kind)
            .collect())
    }

    /// One case per immediate arity class. A wrong count here shifts every later instruction, so
    /// the decoded sequence is asserted whole rather than by length.
    #[test]
    fn each_arity_class_consumes_exactly_its_immediates() {
        let cases: Vec<(Vec<Value>, Vec<InstrKind>)> = vec![
            (vec![json!(11)], vec![InstrKind::Bare(Operation::Eq)]),
            (
                vec![json!(32), json!("x"), json!(35)],
                vec![
                    InstrKind::String(Arc::from("x")),
                    InstrKind::Bare(Operation::Pop),
                ],
            ),
            (
                vec![json!(33), json!(7), json!(34), json!(1.5), json!(35)],
                vec![
                    InstrKind::Number(Operation::Integer),
                    InstrKind::Number(Operation::Float),
                    InstrKind::Bare(Operation::Pop),
                ],
            ),
            (
                vec![json!(1), json!(2), json!(35)],
                vec![
                    InstrKind::Counted(Operation::GetGlobal, 2),
                    InstrKind::Bare(Operation::Pop),
                ],
            ),
            (
                // JUMP at tokens 2-3 lands one token past its immediate, minus four: token 0.
                vec![json!(39), json!(-4), json!(35)],
                vec![
                    InstrKind::Branch {
                        op: Operation::Jump,
                        target: Some(TokenIndex(0)),
                    },
                    InstrKind::Bare(Operation::Pop),
                ],
            ),
            (
                vec![json!(50), json!(2), json!(35)],
                vec![InstrKind::Try, InstrKind::Bare(Operation::Pop)],
            ),
            (
                vec![json!(2), json!("toString"), json!(1), json!(35)],
                vec![
                    InstrKind::CallGlobal {
                        name: "toString".to_owned(),
                        argc: 1,
                    },
                    InstrKind::Bare(Operation::Pop),
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
                vec![
                    InstrKind::Callable {
                        body: TokenSpan {
                            start: TokenIndex(7),
                            end: TokenIndex(9),
                        },
                    },
                    InstrKind::Bare(Operation::Pop),
                ],
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
                vec![InstrKind::Closure, InstrKind::Bare(Operation::Pop)],
            ),
        ];
        for (tokens, expected) in cases {
            assert_eq!(
                kinds(&body(tokens.clone())).unwrap(),
                expected,
                "{tokens:?}"
            );
        }
    }

    /// Every opcode's token advance, one row per [`Operation`] variant.
    ///
    /// The exhaustive match in `kind_for` catches a *new* opcode. It does not catch an existing one
    /// gaining an immediate: `kind_for` keeps answering `Bare`, every later instruction decodes at
    /// the wrong offset, and `GET_GLOBAL` then pops the wrong cells — a confidently wrong read set
    /// rather than the fail-closed wide one this module exists to produce.
    ///
    /// The array is typed `[_; 57]` so the count is load-bearing: a new variant fails to compile
    /// here rather than being silently skipped. This pins the decoder against itself, not against
    /// `vm.rs`; a shared arity table both read is the structural fix and a larger change than this.
    #[test]
    fn every_opcode_advances_by_exactly_its_immediates() {
        // (opcode, its immediates, the tokens it consumes after the opcode).
        let cases: [(Operation, Vec<Value>, usize); 57] = [
            (Operation::GetGlobal, vec![json!(1)], 1),
            (Operation::CallGlobal, vec![json!("f"), json!(0)], 2),
            (Operation::And, vec![json!(2)], 1),
            (Operation::Or, vec![json!(2)], 1),
            (Operation::Not, vec![], 0),
            (Operation::Plus, vec![], 0),
            (Operation::Minus, vec![], 0),
            (Operation::Mult, vec![], 0),
            (Operation::Div, vec![], 0),
            (Operation::Mod, vec![], 0),
            (Operation::Eq, vec![], 0),
            (Operation::NotEq, vec![], 0),
            (Operation::Gt, vec![], 0),
            (Operation::GtEq, vec![], 0),
            (Operation::Lt, vec![], 0),
            (Operation::LtEq, vec![], 0),
            (Operation::Like, vec![], 0),
            (Operation::Ilike, vec![], 0),
            (Operation::NotLike, vec![], 0),
            (Operation::NotIlike, vec![], 0),
            (Operation::In, vec![], 0),
            (Operation::NotIn, vec![], 0),
            (Operation::Regex, vec![], 0),
            (Operation::NotRegex, vec![], 0),
            (Operation::Iregex, vec![], 0),
            (Operation::NotIregex, vec![], 0),
            (Operation::InCohort, vec![], 0),
            (Operation::NotInCohort, vec![], 0),
            (Operation::True, vec![], 0),
            (Operation::False, vec![], 0),
            (Operation::Null, vec![], 0),
            (Operation::String, vec![json!("x")], 1),
            (Operation::Integer, vec![json!(7)], 1),
            (Operation::Float, vec![json!(1.5)], 1),
            (Operation::Pop, vec![], 0),
            (Operation::GetLocal, vec![json!(0)], 1),
            (Operation::SetLocal, vec![json!(0)], 1),
            (Operation::Return, vec![], 0),
            (Operation::Jump, vec![json!(0)], 1),
            (Operation::JumpIfFalse, vec![json!(0)], 1),
            // The VM refuses `DECLARE_FN` before it reads an immediate, so there is no arity to
            // copy and bare is what keeps this decoder aligned with it.
            (Operation::DeclareFn, vec![], 0),
            (Operation::Dict, vec![json!(0)], 1),
            (Operation::Array, vec![json!(0)], 1),
            (Operation::Tuple, vec![json!(0)], 1),
            (Operation::GetProperty, vec![], 0),
            (Operation::SetProperty, vec![], 0),
            (Operation::JumpIfStackNotNull, vec![json!(0)], 1),
            (Operation::GetPropertyNullish, vec![], 0),
            (Operation::Throw, vec![], 0),
            (Operation::Try, vec![json!(0)], 1),
            (Operation::PopTry, vec![], 0),
            // Name, arg count, upvalue count, then an empty body.
            (
                Operation::Callable,
                vec![json!("f"), json!(0), json!(0), json!(0)],
                4,
            ),
            (Operation::Closure, vec![json!(0)], 1),
            (Operation::CallLocal, vec![json!(0)], 1),
            (Operation::GetUpvalue, vec![json!(0)], 1),
            (Operation::SetUpvalue, vec![json!(0)], 1),
            (Operation::CloseUpvalue, vec![], 0),
        ];
        for (op, immediates, advance) in cases {
            let mut tokens = vec![json!(op as u8)];
            tokens.extend(immediates);
            // A trailing `POP`, which only decodes as an instruction if the opcode before it
            // consumed exactly `advance` tokens.
            tokens.push(json!(35));
            let decoded = decode(&body(tokens))
                .unwrap_or_else(|error| panic!("{op:?} did not decode: {error}"));
            assert_eq!(
                decoded.instrs.len(),
                2,
                "{op:?} left {:?}",
                decoded
                    .instrs
                    .iter()
                    .map(|instr| instr.kind.clone())
                    .collect::<Vec<_>>()
            );
            assert_eq!(
                decoded.instrs[1].start,
                TokenIndex(HEADER_LEN + 1 + advance),
                "{op:?} advanced to the wrong token"
            );
            assert_eq!(decoded.instrs[1].kind, InstrKind::Bare(Operation::Pop));
        }
    }

    /// A forward jump resolves against the instruction pointer one past its immediate, which is how
    /// the VM adds the offset. Off by one here would land every conditional on the wrong branch.
    #[test]
    fn a_jump_target_is_the_token_the_vm_would_reach() {
        // Header, then JUMP_IF_FALSE +1 at tokens 2-3, FALSE at 4, TRUE at 5.
        let decoded = decode(&body(vec![json!(40), json!(1), json!(30), json!(29)])).unwrap();
        assert_eq!(
            decoded.instrs[0].kind,
            InstrKind::Branch {
                op: Operation::JumpIfFalse,
                target: Some(TokenIndex(5)),
            }
        );
        assert_eq!(decoded.instrs[0].start, TokenIndex(2));
        assert_eq!(decoded.body_end, TokenIndex(6));
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

    /// A count immediate larger than the whole program is refused at the source. Downstream, these
    /// counts size allocations, so `u64::MAX` is a capacity-overflow panic and a merely huge value
    /// is an allocation abort — on the orchestrator's own task, from one catalog row.
    #[test]
    fn a_count_immediate_larger_than_the_program_is_refused() {
        for count in [json!(u64::MAX), json!(4_000_000_000u64), json!(1_000)] {
            let error = decode(&body(vec![json!(1), count.clone()])).unwrap_err();
            assert!(
                matches!(
                    &error,
                    DecodeError::MalformedImmediate {
                        op: Operation::GetGlobal,
                        ..
                    }
                ),
                "GET_GLOBAL {count} gave {error:?}"
            );
        }
    }

    /// A jump that would land before the start of the array has no landing site, which decode
    /// records rather than refuses. Refusing it here would fail the whole program over an offset no
    /// path may even follow; the analysis layer decides that on visit. One past the end is a
    /// different case again: it is where a jump off the end legitimately lands.
    #[test]
    fn a_jump_landing_outside_the_addressable_range_has_no_target() {
        assert_eq!(
            kinds(&body(vec![json!(39), json!(-99)])).unwrap(),
            vec![InstrKind::Branch {
                op: Operation::Jump,
                target: None,
            }]
        );
        assert_eq!(
            kinds(&body(vec![json!(39), json!(0)])).unwrap(),
            vec![InstrKind::Branch {
                op: Operation::Jump,
                target: Some(TokenIndex(4)),
            }]
        );
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

    /// A `CALLABLE` body decodes in place, so its positions and any jump inside it resolve exactly
    /// as they would when the enclosing program runs.
    #[test]
    fn a_callable_body_decodes_at_its_absolute_positions() {
        let tokens = body(vec![
            json!(52),
            json!("f"),
            json!(0),
            json!(0),
            json!(3),
            json!(32),
            json!("x"),
            json!(38),
        ]);
        let InstrKind::Callable { body: span } = decode(&tokens).unwrap().instrs[0].kind.clone()
        else {
            panic!("the first instruction is not a callable");
        };
        let decoded = decode_span(&tokens, span).unwrap();
        assert_eq!(decoded.instrs[0].start, TokenIndex(7));
        assert_eq!(
            decoded
                .instrs
                .into_iter()
                .map(|instr| instr.kind)
                .collect::<Vec<_>>(),
            vec![
                InstrKind::String(Arc::from("x")),
                InstrKind::Bare(Operation::Return),
            ]
        );
    }

    /// The header rules mirror the VM's: `_H` is mandatory, an unsigned-integer version token is
    /// consumed, and anything else is an error rather than a first opcode.
    ///
    /// The version cases are the ones worth pinning. `Program::from_shared` takes the token through
    /// `as_u64`, so a negative or fractional version is bytecode the VM will not load; a decoder
    /// that accepted it would report a read set for a program that never runs.
    #[test]
    fn the_header_is_read_exactly_as_the_vm_reads_it() {
        assert_eq!(decode(&[]).unwrap_err(), DecodeError::MissingHeader);
        assert_eq!(
            decode(&[json!(1), json!(32)]).unwrap_err(),
            DecodeError::MissingHeader
        );
        for version in [json!("v1"), json!(-1), json!(1.5), json!(null)] {
            assert_eq!(
                decode(&[json!("_H"), version.clone()]).unwrap_err(),
                DecodeError::MalformedVersion,
                "version {version} decoded but the VM refuses it"
            );
        }
        // A bare marker is a valid, empty program.
        assert_eq!(kinds(&[json!("_H")]).unwrap(), Vec::new());
        assert_eq!(kinds(&[json!("_H"), json!(1)]).unwrap(), Vec::new());
        // The version slot is consumed even when it holds what looks like an opcode, because the
        // VM consumes it too.
        assert_eq!(
            kinds(&[json!("_H"), json!(35), json!(35)]).unwrap(),
            vec![InstrKind::Bare(Operation::Pop)]
        );
    }
}
