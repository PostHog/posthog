//! An abstract interpreter over the decoded control-flow graph, producing the set of globals a
//! condition reads.
//!
//! The abstract domain has two values: a compile-time literal string, and everything else. That is
//! all `GET_GLOBAL` needs, because it builds its path from literal strings the compiler pushed and
//! nothing else can reach the globals dict.
//!
//! Branches are followed rather than refused. A worklist carries an abstract stack along each path;
//! where paths meet, the stacks are joined cell by cell, and the pass repeats until nothing
//! changes. That matters because the cohort compiler lowers the ordinary operators through jumps:
//! `null_safe_comparisons` rewrites every `>`/`>=`/`<`/`<=` into an `if`, regex goes through
//! `ifNull`, and `between` compiles to a local-slot IIFE. Refusing branches would report almost
//! every date and regex condition as unreadable.
//!
//! Only instructions more than one edge can reach hold a stored stack, and a straight-line run is
//! walked in place with one stack rather than through the worklist. Both matter for cost, not
//! elegance: a `properties.x IN (...)` leaf pushes every list element before `IN` pops them, and
//! catalogs hold lists of several thousand. Storing and copying a stack per instruction over that
//! is quadratic in the program's own length, which on the largest real list size meant seconds of
//! blocking and over a gigabyte, for a program the VM evaluates in kilobytes.
//!
//! That gating answers the shape it was built for and no other. A program that is *all* merge
//! points — a deep stack of literals, then a chain of rejoining diamonds — stores and copies a
//! stack at every one of them, and a transfer-step ceiling does not bound that, because one step
//! can copy a whole stack. So the two ceilings in [`AnalysisBudget`] are both needed: steps for the
//! programs that spend without copying, copied cells for the programs that copy without spending.
//!
//! The pass stays fail-closed everywhere it is not sure. Two paths that meet at different stack
//! depths, a jump into the middle of an instruction, a local slot outside the frame, or a `RETURN`
//! that leaves the stack unbalanced all stop the analysis and widen the condition to every column.
//! Reads accumulate globally rather than per instruction, so a join can never retract one.
//!
//! One case answers rather than widens. A `GET_GLOBAL` root that no globals dict carries reads
//! nothing under any projection, so it claims no path and the walk continues. A bare
//! representation-sensitive native is the exception, because such a root is a closure the program
//! can still call — see [`Interpreter::get_global`].

use std::collections::{BTreeSet, VecDeque};
use std::sync::Arc;

use hogvm::Operation;
use serde_json::Value;

use super::decode::{decode, Decoded, InstrIndex, InstrKind, TokenIndex};
use super::{FullColumnsReason, GlobalRoot, Projection, ReadPath, UnanalyzableReason};

/// `elements_chain` falls back to this property when the event's own column is empty, so a caller
/// that projects an `elements_chain` read must carry it too.
const ELEMENTS_CHAIN_PROPERTY: &str = "$elements_chain";

/// Natives whose result depends on how a JSON number was spelled, rather than on its value.
///
/// A caller acting on [`Projection::Reads`] supplies the claimed paths through its own storage, and
/// the seeder supplies them by having ClickHouse rebuild the blob from the kept keys. That rebuild
/// re-prints every number it copies, so a whole-number float token arrives as an integer one:
/// `{"n": 100.0}` becomes `{"n": 100}`, which the VM loads as `Num::Integer(100)` where live
/// evaluation loads `Num::Float(100.0)`.
///
/// Most of the VM cannot see that. Equality unifies the two variants, arithmetic and ordering widen
/// a mixed pair to `f64`, and the printer renders `Float(100.0)` and `Integer(100)` as the same
/// text. The exceptions are the natives below, each of which branches on `Num::is_float` in a way
/// that reaches its result: `typeof` answers `"float"` or `"integer"`, and `jsonStringify` keeps the
/// decimal point only for the float variant. A condition calling either would seed a membership its
/// live evaluation disagrees with, so the whole condition takes every column instead.
///
/// One residual is accepted rather than covered. `print_hog_value` renders an object carrying an
/// `__hx_ast` key back to SQL, and that printer does distinguish the variants, so `toString` of a
/// property whose value is shaped like a HogQL AST node is sensitive too. That needs a customer
/// blob built to look like compiler output, which no filter the product writes can produce.
const REPRESENTATION_SENSITIVE_NATIVES: [&str; 2] = ["typeof", "jsonStringify"];

/// A ceiling on transfer steps one program may take, so a program the lattice argument does not
/// cover cannot hang the caller. The fixpoint is reached far sooner: a merge point's stack can only
/// move upward, one cell at a time, so the work is quadratic in the program length at worst and
/// this only fires if that reasoning is wrong.
const MAX_WORKLIST_STEPS: usize = 1_000_000;

/// A ceiling on the abstract stack cells one program may copy in total.
///
/// The step ceiling does not bound the work on its own: one step can copy a whole stack at a merge
/// point, so the two multiply. A deep stack followed by a chain of rejoining diamonds is all merge
/// points, so merge-point gating does not apply to it, and the pair of ceilings alone admits about
/// `1e12` cell copies. Charging what is actually copied is what makes the bounded cost the cost
/// incurred.
const MAX_COPIED_CELLS: usize = 16_000_000;

/// A ceiling on the abstract stack cells the pass holds at once, across stored merge-point states
/// and the worklist together. A memory ceiling rather than a work one, so it is per program however
/// the caller shares [`AnalysisBudget`].
///
/// The pass would otherwise be quadratic in a shape production already writes: a `properties.x IN
/// (...)` leaf pushes every list element before `IN` pops them, and catalogs hold lists of several
/// thousand. Storing one stack per instruction across such a program is cells proportional to the
/// square of its length. Merge-point gating removes that for straight-line code; this bounds what
/// is left, so a shape nobody predicted costs a wide answer rather than the process.
const MAX_RETAINED_CELLS: usize = 1_000_000;

/// A ceiling on the work an analysis may do, in transfer steps and copied abstract stack cells.
///
/// Both units are load-bearing. A step ceiling alone lets one step copy a whole stack, so the two
/// multiply; a cell ceiling alone says nothing about a straight-line run, which is walked in place
/// and copies nothing.
///
/// A budget may be shared by a batch of conditions, which is how a caller bounds the batch rather
/// than each member of it: per-condition ceilings alone leave `conditions × ceiling`, and nothing
/// caps the conditions on a run. Sharing keeps the analysis a pure function of its input — a batch
/// is analyzed in a fixed order, so it always spends the budget the same way, which a wall-clock
/// deadline would not. Past the budget every remaining condition reports it and fails closed.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct AnalysisBudget {
    /// Transfer steps left to take.
    pub steps: usize,
    /// Abstract stack cells left to copy.
    pub cells: usize,
}

impl AnalysisBudget {
    /// What one condition may cost on its own.
    pub const fn for_one_condition() -> Self {
        Self {
            steps: MAX_WORKLIST_STEPS,
            cells: MAX_COPIED_CELLS,
        }
    }

    /// What `worst_case_conditions` conditions cost together, each saturating its own ceiling. The
    /// unit is a worst case rather than a condition, so a batch of any size fits a budget the
    /// caller can reason about in wall-clock terms.
    pub const fn for_conditions(worst_case_conditions: usize) -> Self {
        Self {
            steps: MAX_WORKLIST_STEPS.saturating_mul(worst_case_conditions),
            cells: MAX_COPIED_CELLS.saturating_mul(worst_case_conditions),
        }
    }

    fn spend(&mut self, steps: usize, cells: usize) {
        self.steps = self.steps.saturating_sub(steps);
        self.cells = self.cells.saturating_sub(cells);
    }
}

/// Which instructions more than one edge can reach.
///
/// The successor sets are the transfer function's, over-approximated: a conditional jump is counted
/// as reaching both of its edges even where the interpreter later finds only one live, and a refused
/// opcode is counted as falling through. Over-approximating only turns more instructions into merge
/// points, which costs memory and never correctness — while under-approximating would drop a join
/// and let the pass read a stack no path actually produces.
fn merge_points(decoded: &Decoded, starts: &[TokenIndex]) -> Vec<bool> {
    let mut in_degree = vec![0_u32; decoded.instrs.len()];
    if in_degree.is_empty() {
        return Vec::new();
    }
    // The program is entered at its first instruction, which is an edge like any other: a backward
    // jump onto it must make it a merge point rather than overwrite the entry state.
    in_degree[0] = 1;
    for (index, instr) in decoded.instrs.iter().enumerate() {
        let falls_through = !matches!(
            instr.kind,
            InstrKind::Bare(Operation::Return)
                | InstrKind::Branch {
                    op: Operation::Jump,
                    ..
                }
        );
        if falls_through && index + 1 < in_degree.len() {
            in_degree[index + 1] = in_degree[index + 1].saturating_add(1);
        }
        if let InstrKind::Branch {
            target: Some(target),
            ..
        } = instr.kind
        {
            if let Ok(landed) = starts.binary_search(&target) {
                in_degree[landed] = in_degree[landed].saturating_add(1);
            }
        }
    }
    in_degree.into_iter().map(|degree| degree >= 2).collect()
}

/// One cell of the abstract stack.
#[derive(Debug, Clone, PartialEq, Eq)]
enum AbstractValue {
    /// A string literal the compiler pushed, which a `GET_GLOBAL` path may be built from.
    LiteralString(Arc<str>),
    /// A value the model cannot name.
    Opaque,
}

impl AbstractValue {
    /// The join of two cells. Two identical literals stay a literal; anything else is the top of
    /// the two-value lattice, which is what makes the fixpoint terminate.
    fn join(&self, other: &Self) -> Self {
        match (self, other) {
            (Self::LiteralString(left), Self::LiteralString(right)) if left == right => {
                Self::LiteralString(Arc::clone(left))
            }
            _ => Self::Opaque,
        }
    }
}

type AbstractStack = Vec<AbstractValue>;

pub(super) fn project(bytecode: &[Value], budget: &mut AnalysisBudget) -> Projection {
    // A spent budget stops before the decode too. Decoding is work proportional to the whole
    // program, so a batch that ran out on its first condition would otherwise still pay it for
    // every remaining one.
    if budget.steps == 0 {
        return full_columns(UnanalyzableReason::IterationBudget);
    }
    let decoded = match decode(bytecode) {
        Ok(decoded) => decoded,
        Err(error) => return full_columns(UnanalyzableReason::Decode(error)),
    };
    let mut interpreter = Interpreter::new(&decoded, *budget);
    let outcome = interpreter.run();
    // Charged however the pass ended: a condition that spent the budget and then failed closed has
    // still spent it.
    budget.spend(interpreter.steps, interpreter.cells_copied);
    match outcome {
        Ok(reads) => Projection::Reads(reads),
        Err(Stop::Unanalyzable(reason)) => full_columns(reason),
        Err(Stop::Unnarrowable(reason)) => Projection::FullColumns(reason),
    }
}

fn full_columns(reason: UnanalyzableReason) -> Projection {
    Projection::FullColumns(FullColumnsReason::Unanalyzable(reason))
}

/// Why the interpreter stopped early. [`Stop::Unnarrowable`] is an ordinary program the analysis
/// understood and cannot narrow; everything else is the fail-closed arm.
enum Stop {
    Unanalyzable(UnanalyzableReason),
    Unnarrowable(FullColumnsReason),
}

/// What an instruction does to control flow, after its own stack effect has been applied. Both
/// conditional jumps produce [`Control::Fork`]: they differ in whether they pop, and that
/// difference is already spent by the time the successors are computed, so the two edges out of
/// either one carry the same stack.
enum Control {
    /// The program ends on this path.
    Terminate,
    /// Continue with the next instruction.
    Fall,
    /// Continue at one specific token. `None` is a jump the decoder could not resolve, which
    /// fails closed here rather than at decode, so a dead one costs nothing.
    Jump(Option<TokenIndex>),
    /// Continue at the next instruction and at one specific token.
    Fork(Option<TokenIndex>),
}

struct Interpreter<'a> {
    decoded: &'a Decoded,
    /// The token each instruction starts at, so a jump target resolves to an instruction. Linear
    /// rather than a map: programs are short, and this keeps the lookup allocation-free.
    starts: Vec<TokenIndex>,
    /// Which instructions more than one edge can reach. Only those need a stored stack to join
    /// into; the rest have a single predecessor, so their incoming stack is already the joined one
    /// and is handed straight to them on the worklist.
    merge_points: Vec<bool>,
    /// The joined stack every path into a merge point agrees on. Always `None` for the rest, so a
    /// straight-line program stores nothing at all.
    entry: Vec<Option<AbstractStack>>,
    /// Stack cells alive in `entry` and on the worklist together. Bounding this is what keeps the
    /// pass's memory a function of the program's branching rather than of its length.
    retained: usize,
    /// Transfer steps taken and stack cells copied so far. Read back by [`project`] and charged
    /// against the caller's budget, so a batch sharing one budget pays for what each member spent.
    steps: usize,
    cells_copied: usize,
    /// This program's ceilings: its own, capped by what the caller's budget has left.
    step_ceiling: usize,
    cell_ceiling: usize,
    /// Accumulated across every visit and never retracted. Held outside the per-instruction state
    /// on purpose: a join that narrowed a read set could make the analysis claim fewer globals
    /// than the program touches, which is the one failure this module must not have.
    reads: BTreeSet<ReadPath>,
    worklist: VecDeque<(InstrIndex, AbstractStack)>,
}

impl<'a> Interpreter<'a> {
    fn new(decoded: &'a Decoded, budget: AnalysisBudget) -> Self {
        let starts: Vec<TokenIndex> = decoded.instrs.iter().map(|instr| instr.start).collect();
        let count = decoded.instrs.len();
        // Every instruction is re-processed once per widening of a merge point upstream of it, and
        // a merge point widens at most once per stack cell. The quadratic term covers that; the
        // factor is headroom, so a legitimate program never reports the budget instead of an answer.
        let step_ceiling = count
            .checked_mul(count + 1)
            .and_then(|product| product.checked_mul(4))
            .unwrap_or(MAX_WORKLIST_STEPS)
            .min(MAX_WORKLIST_STEPS)
            .min(budget.steps);
        Self {
            merge_points: merge_points(decoded, &starts),
            starts,
            decoded,
            entry: vec![None; count],
            retained: 0,
            steps: 0,
            cells_copied: 0,
            step_ceiling,
            cell_ceiling: MAX_COPIED_CELLS.min(budget.cells),
            reads: BTreeSet::new(),
            worklist: VecDeque::new(),
        }
    }

    fn run(&mut self) -> Result<BTreeSet<ReadPath>, Stop> {
        if self.decoded.instrs.is_empty() {
            return Ok(BTreeSet::new());
        }
        self.enqueue(InstrIndex(0), AbstractStack::new());

        while let Some((InstrIndex(entry_index), stack)) = self.worklist.pop_front() {
            self.retained -= stack.len();
            let mut index = entry_index;
            let mut stack = stack;
            // Walk the straight-line run out of this instruction in place. Handing each step back
            // through the worklist would copy the whole stack per instruction, which is a copy per
            // element of a large `IN` list — quadratic in the program's own length.
            loop {
                self.steps += 1;
                if self.steps > self.step_ceiling {
                    return Err(Stop::Unanalyzable(UnanalyzableReason::IterationBudget));
                }
                if self.retained + stack.len() > MAX_RETAINED_CELLS
                    || self.cells_copied > self.cell_ceiling
                {
                    return Err(Stop::Unanalyzable(UnanalyzableReason::StateBudget));
                }
                let next = match self.transfer(index, &mut stack)? {
                    Control::Terminate => break,
                    Control::Fall => self.next_index(index),
                    Control::Jump(target) => self.target_index(target)?,
                    Control::Fork(target) => {
                        // Two live successors, so neither can take the stack by value.
                        self.propagate_next(index, &stack)?;
                        self.propagate_token(target, &stack)?;
                        break;
                    }
                };
                let Some(next) = next else {
                    break;
                };
                if self.merge_points[next] {
                    self.propagate(InstrIndex(next), &stack)?;
                    break;
                }
                index = next;
            }
        }
        Ok(std::mem::take(&mut self.reads))
    }

    fn enqueue(&mut self, index: InstrIndex, stack: AbstractStack) {
        // Every stack this pass copies is copied on the way here — the worklist entry itself, and
        // the merge-point store that precedes it. Charging by cells rather than by step is what
        // makes the ceiling bound the work: one step can copy a whole stack.
        self.cells_copied = self.cells_copied.saturating_add(stack.len());
        self.retained += stack.len();
        self.worklist.push_back((index, stack));
    }

    /// The instruction after `index`, or `None` at the end of the program. Running off the end is
    /// the program stopping, exactly as the VM's step loop stops when its instruction pointer
    /// leaves the body.
    fn next_index(&self, index: usize) -> Option<usize> {
        (index + 1 < self.decoded.instrs.len()).then_some(index + 1)
    }

    /// The instruction a jump lands on, or `None` when it lands one past the last token — a jump
    /// off the end, which terminates.
    fn target_index(&self, target: Option<TokenIndex>) -> Result<Option<usize>, Stop> {
        let Some(target) = target else {
            return Err(Stop::Unanalyzable(UnanalyzableReason::BadJumpTarget));
        };
        if target == self.decoded.body_end {
            return Ok(None);
        }
        self.starts
            .binary_search(&target)
            .map(Some)
            .map_err(|_| Stop::Unanalyzable(UnanalyzableReason::BadJumpTarget))
    }

    fn propagate_next(&mut self, index: usize, stack: &AbstractStack) -> Result<(), Stop> {
        if let Some(next) = self.next_index(index) {
            self.propagate(InstrIndex(next), stack)?;
        }
        Ok(())
    }

    /// Continue at a jump target. A target that is neither an instruction boundary nor the end of
    /// the program fails closed: the VM would read an immediate as an opcode there.
    fn propagate_token(
        &mut self,
        target: Option<TokenIndex>,
        stack: &AbstractStack,
    ) -> Result<(), Stop> {
        match self.target_index(target)? {
            Some(index) => self.propagate(InstrIndex(index), stack),
            None => Ok(()),
        }
    }

    fn propagate(
        &mut self,
        InstrIndex(index): InstrIndex,
        stack: &AbstractStack,
    ) -> Result<(), Stop> {
        if self.retained > MAX_RETAINED_CELLS {
            return Err(Stop::Unanalyzable(UnanalyzableReason::StateBudget));
        }
        // A single-predecessor instruction has nothing to join against, so its stack goes straight
        // onto the worklist and is never stored. That is what keeps a long straight-line program —
        // the shape a large `IN` list compiles to — from retaining one stack per instruction.
        if !self.merge_points[index] {
            self.enqueue(InstrIndex(index), stack.clone());
            return Ok(());
        }
        match &self.entry[index] {
            None => {
                self.retained += stack.len();
                self.entry[index] = Some(stack.clone());
                self.enqueue(InstrIndex(index), stack.clone());
                Ok(())
            }
            Some(existing) => {
                // Two paths reaching one instruction with different stack depths means the model
                // has lost track of the layout, and every later `GET_GLOBAL` would pop the wrong
                // cells. There is no join that recovers from it, so the program fails closed.
                if existing.len() != stack.len() {
                    return Err(Stop::Unanalyzable(UnanalyzableReason::StackDepthMismatch));
                }
                let joined: AbstractStack = existing
                    .iter()
                    .zip(stack)
                    .map(|(left, right)| left.join(right))
                    .collect();
                if joined != *existing {
                    self.entry[index] = Some(joined.clone());
                    self.enqueue(InstrIndex(index), joined);
                }
                Ok(())
            }
        }
    }

    fn transfer(&mut self, index: usize, stack: &mut AbstractStack) -> Result<Control, Stop> {
        match &self.decoded.instrs[index].kind {
            InstrKind::String(literal) => {
                stack.push(AbstractValue::LiteralString(Arc::clone(literal)));
                Ok(Control::Fall)
            }
            InstrKind::Number(_) => push_opaque(stack),
            InstrKind::Counted(op, count) => self.counted(*op, *count, stack),
            // A native consumes stack values and cannot reach the globals dict, so it never widens
            // the read set — which is what keeps `toDateTime(timestamp) > x` projectable. The
            // exception is a native that reads a value's *spelling* rather than its value; see
            // [`REPRESENTATION_SENSITIVE_NATIVES`].
            InstrKind::CallGlobal { name, argc } => {
                if REPRESENTATION_SENSITIVE_NATIVES.contains(&name.as_str()) {
                    return Err(Stop::Unnarrowable(
                        FullColumnsReason::RepresentationSensitiveCall,
                    ));
                }
                reduce(stack, *argc)
            }
            InstrKind::Bare(op) => self.bare(*op, stack),
            InstrKind::Branch { op, target } => branch(*op, *target, stack),
            // A callable or closure introduces a frame the model has no notion of, and `TRY`
            // installs a handler that can enter one from anywhere. Refused on visit, so an
            // occurrence in code no path reaches costs nothing.
            InstrKind::Callable { .. } => Err(unsupported(Operation::Callable)),
            InstrKind::Closure => Err(unsupported(Operation::Closure)),
            InstrKind::Try => Err(unsupported(Operation::Try)),
        }
    }

    fn counted(
        &mut self,
        op: Operation,
        count: usize,
        stack: &mut AbstractStack,
    ) -> Result<Control, Stop> {
        match op {
            Operation::GetGlobal => self.get_global(count, stack),
            Operation::Dict => reduce(stack, count.saturating_mul(2)),
            // The compiler emits `AND n` / `OR n` rather than a jump-form short circuit, so these
            // stay plain reductions.
            Operation::And | Operation::Or | Operation::Array | Operation::Tuple => {
                reduce(stack, count)
            }
            // The frame base is zero: `CALLABLE`, `CLOSURE`, and `CALL_LOCAL` are all refused, so
            // no path reaching here has pushed a frame, and a slot offset indexes the stack
            // directly. That is what makes the `between` IIFE readable.
            Operation::GetLocal => {
                let value = stack
                    .get(count)
                    .ok_or(Stop::Unanalyzable(UnanalyzableReason::LocalSlotOutOfRange))?
                    .clone();
                stack.push(value);
                Ok(Control::Fall)
            }
            Operation::SetLocal => {
                let value = pop(stack)?;
                // The VM pops before it indexes, so a slot equal to the post-pop depth is out of
                // range there too.
                let slot = stack
                    .get_mut(count)
                    .ok_or(Stop::Unanalyzable(UnanalyzableReason::LocalSlotOutOfRange))?;
                *slot = value;
                Ok(Control::Fall)
            }
            // Upvalue slots address a closure's captured environment, which only the refused frame
            // opcodes create.
            Operation::GetUpvalue | Operation::SetUpvalue | Operation::CallLocal => {
                Err(unsupported(op))
            }
            // `decode` builds `Counted` only from the opcodes above.
            other => Err(unsupported(other)),
        }
    }

    fn bare(&mut self, op: Operation, stack: &mut AbstractStack) -> Result<Control, Stop> {
        match op {
            Operation::True | Operation::False | Operation::Null => push_opaque(stack),
            Operation::Not => reduce(stack, 1),
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
            | Operation::GetPropertyNullish => reduce(stack, 2),
            Operation::Pop => {
                pop(stack)?;
                Ok(Control::Fall)
            }
            Operation::Return => {
                pop(stack)?;
                // The root frame's `RETURN` leaves nothing behind: the compiler emits one
                // expression, and every scope pops its own locals first. Junk left here means a
                // stack effect in the transfer table is wrong, and the next `GET_GLOBAL` would pop
                // the wrong cells — so this turns a silent misread into a wide answer.
                if stack.is_empty() {
                    Ok(Control::Terminate)
                } else {
                    Err(Stop::Unanalyzable(UnanalyzableReason::UnbalancedReturn))
                }
            }
            // `SET_PROPERTY` mutates the heap, which the model does not represent; the cohort
            // opcodes read membership state that is not in the globals dict at all; the exception
            // opcodes move the instruction pointer to a handler this pass does not track.
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
    fn get_global(&mut self, count: usize, stack: &mut AbstractStack) -> Result<Control, Stop> {
        if count == 0 {
            return Err(Stop::Unanalyzable(
                UnanalyzableReason::ZeroLengthGlobalChain,
            ));
        }
        // Checked before the allocation, not during the pops: `Vec::with_capacity` on an
        // out-of-range count aborts the process rather than returning.
        if count > stack.len() {
            return Err(Stop::Unanalyzable(UnanalyzableReason::StackUnderflow));
        }
        let mut chain = Vec::with_capacity(count);
        for _ in 0..count {
            match pop(stack)? {
                AbstractValue::LiteralString(segment) => chain.push(segment),
                AbstractValue::Opaque => {
                    return Err(Stop::Unanalyzable(UnanalyzableReason::DynamicGlobalPath))
                }
            }
        }
        let (root_name, segments) = chain.split_first().expect("count is non-zero");
        let Some(root) = GlobalRoot::parse(root_name) else {
            // A one-element chain also resolves to a first-class closure over a native, and
            // `arrayMap` invokes that closure through `CALL_LOCAL`, so the `CallGlobal` arm never
            // sees the name. Reading a number's spelling is unsafe however the native is reached,
            // so [`REPRESENTATION_SENSITIVE_NATIVES`] has to be checked on both paths.
            if segments.is_empty() && REPRESENTATION_SENSITIVE_NATIVES.contains(&root_name.as_ref())
            {
                return Err(Stop::Unnarrowable(
                    FullColumnsReason::RepresentationSensitiveCall,
                ));
            }
            // Every other such name reads no event data, so it constrains no column. A projection
            // narrows the values *under* the roots a globals builder writes and never removes a
            // root, so a name absent from the dict is absent under every projection: its
            // `GET_GLOBAL` raises `UnknownGlobal` on the projected event and on the full one alike.
            // [`GlobalRoot`] is what makes "not a root" mean "in no dict this crate builds".
            //
            // Opaque rather than terminate: the closure case keeps executing, so ending the path
            // here could prune a genuine later read. Over-approximating is the safe direction.
            return push_opaque(stack);
        };
        // A bare `properties`, `person`, or `pdi` hands a whole object to whatever consumes it, so
        // which keys are read is decided at runtime and cannot be narrowed here. `pdi` counts
        // because the globals build it as a copy of the whole person tree.
        if segments.is_empty() {
            match root {
                GlobalRoot::Properties => {
                    return Err(Stop::Unnarrowable(FullColumnsReason::BarePropertiesRoot))
                }
                GlobalRoot::Person | GlobalRoot::Pdi => {
                    return Err(Stop::Unnarrowable(FullColumnsReason::BarePersonRoot))
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
        let segments = segments.iter().map(|segment| segment.to_string()).collect();
        self.reads.insert(ReadPath::new(root, segments));
        push_opaque(stack)
    }
}

fn branch(
    op: Operation,
    target: Option<TokenIndex>,
    stack: &mut AbstractStack,
) -> Result<Control, Stop> {
    match op {
        Operation::Jump => Ok(Control::Jump(target)),
        // The condition is popped before the branch is taken, so both edges continue from the same
        // stack.
        Operation::JumpIfFalse => {
            pop(stack)?;
            Ok(Control::Fork(target))
        }
        // This one peeks and never pops, on either edge. On an empty stack the VM cannot read a
        // top value, so it silently falls through — and modelling the jump anyway would merge two
        // paths at different depths and fail a program the VM runs fine.
        Operation::JumpIfStackNotNull => Ok(match stack.is_empty() {
            true => Control::Fall,
            false => Control::Fork(target),
        }),
        // `decode` builds `Branch` only from the opcodes above.
        other => Err(unsupported(other)),
    }
}

/// Consume `count` operands and leave one unnameable result.
fn reduce(stack: &mut AbstractStack, count: usize) -> Result<Control, Stop> {
    for _ in 0..count {
        pop(stack)?;
    }
    push_opaque(stack)
}

fn push_opaque(stack: &mut AbstractStack) -> Result<Control, Stop> {
    stack.push(AbstractValue::Opaque);
    Ok(Control::Fall)
}

fn pop(stack: &mut AbstractStack) -> Result<AbstractValue, Stop> {
    stack
        .pop()
        .ok_or(Stop::Unanalyzable(UnanalyzableReason::StackUnderflow))
}

fn unsupported(op: Operation) -> Stop {
    Stop::Unanalyzable(UnanalyzableReason::UnsupportedOp(op))
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
        reads_of(&program(tokens))
    }

    fn reads_of(bytecode: &[Value]) -> Vec<String> {
        match project(bytecode, &mut AnalysisBudget::for_one_condition()) {
            Projection::Reads(paths) => paths.iter().map(ReadPath::render).collect(),
            other => panic!("expected reads, got {other:?}"),
        }
    }

    fn full_columns_reason(tokens: Vec<Value>) -> FullColumnsReason {
        match project(&program(tokens), &mut AnalysisBudget::for_one_condition()) {
            Projection::FullColumns(reason) => reason,
            other => panic!("expected full columns, got {other:?}"),
        }
    }

    fn unanalyzable_within(bytecode: &[Value], budget: &mut AnalysisBudget) -> UnanalyzableReason {
        match project(bytecode, budget) {
            Projection::FullColumns(FullColumnsReason::Unanalyzable(reason)) => reason,
            other => panic!("expected an unanalyzable reason, got {other:?}"),
        }
    }

    fn unanalyzable(tokens: Vec<Value>) -> UnanalyzableReason {
        match full_columns_reason(tokens) {
            FullColumnsReason::Unanalyzable(reason) => reason,
            other => panic!("expected an unanalyzable reason, got {other:?}"),
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

    /// Handing a whole `properties`, `person`, or `pdi` object to something decides its keys at
    /// runtime. These are ordinary programs, so they are reported as bare roots rather than as
    /// failures. `pdi` is a copy of the whole person tree, so a claimed read of it alone would look
    /// narrow while needing every person column.
    #[test]
    fn a_bare_object_root_widens_to_every_column() {
        assert_eq!(
            full_columns_reason(read(&["properties"])),
            FullColumnsReason::BarePropertiesRoot
        );
        assert_eq!(
            full_columns_reason(read(&["person"])),
            FullColumnsReason::BarePersonRoot
        );
        assert_eq!(
            full_columns_reason(read(&["pdi"])),
            FullColumnsReason::BarePersonRoot
        );
    }

    /// The shape a group-type-name filter compiles to. `organization` is a per-team group type: the
    /// SQL printer aliases it onto `group_0`, but the bytecode compiler emits the written chain
    /// verbatim, so the root reaches the VM and no globals dict carries it. Such a root reads no
    /// event data under any projection, so the program claims nothing.
    ///
    /// Written out literally rather than through the `read` helper, so the helper cannot hide the
    /// same mistake, for the same reason
    /// `a_global_chain_is_read_root_first_from_its_reversed_pushes` is written that way.
    #[test]
    fn a_root_no_globals_dict_carries_claims_no_reads() {
        // organization.properties.name == 'Example Org'
        let tokens = vec![
            json!(32),
            json!("Example Org"),
            json!(32),
            json!("name"),
            json!(32),
            json!("properties"),
            json!(32),
            json!("organization"),
            json!(1),
            json!(3),
            json!(11),
        ];
        assert_eq!(reads(tokens), Vec::<String>::new());
    }

    /// The absent root continues the walk rather than ending it, so a read after one is still
    /// claimed. A `Control::Terminate` implementation passes every other test in this file and
    /// fails only here.
    #[test]
    fn a_read_after_an_absent_root_is_still_claimed() {
        let mut tokens = read(&["organization"]);
        tokens.extend(read(&["properties", "plan"]));
        // `AND` of the two, so the program balances its stack the way the compiler would.
        tokens.push(json!(3));
        tokens.push(json!(2));
        assert_eq!(reads(tokens), ["properties.plan"]);
    }

    /// A bare native name is not a read. `GET_GLOBAL` resolves it to a first-class closure, and
    /// `arrayMap` invokes that closure through `CALL_LOCAL`, so the `CALL_GLOBAL` guard never sees
    /// the name. `typeof` answers from how a number was spelled, so a caller rebuilding the blob
    /// from the claimed keys re-prints `100.0` as `100` and the condition decides the other way.
    /// The root carries the same obligation a direct call does.
    #[test]
    fn a_representation_sensitive_native_reached_as_a_root_widens() {
        // arrayMap(typeof, [properties.n]) == ['float']
        let tokens = vec![
            json!(32),
            json!("typeof"),
            json!(1),
            json!(1),
            json!(32),
            json!("n"),
            json!(32),
            json!("properties"),
            json!(1),
            json!(2),
            json!(43),
            json!(1),
            json!(2),
            json!("arrayMap"),
            json!(2),
            json!(32),
            json!("float"),
            json!(43),
            json!(1),
            json!(11),
        ];
        assert_eq!(
            full_columns_reason(tokens),
            FullColumnsReason::RepresentationSensitiveCall
        );
    }

    /// A native the rebuild cannot disturb stays projectable when it arrives as a root, so the
    /// guard above widens on representation sensitivity rather than on every native reference.
    #[test]
    fn an_insensitive_native_reached_as_a_root_still_claims_its_reads() {
        // arrayMap(base64Encode, [properties.n])
        let tokens = vec![
            json!(32),
            json!("base64Encode"),
            json!(1),
            json!(1),
            json!(32),
            json!("n"),
            json!(32),
            json!("properties"),
            json!(1),
            json!(2),
            json!(43),
            json!(1),
            json!(2),
            json!("arrayMap"),
            json!(2),
        ];
        assert_eq!(reads(tokens), ["properties.n"]);
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

    /// A path segment computed at runtime, an unmodeled opcode, and garbage all have to fail
    /// closed, each naming what stopped the analysis.
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
        assert_eq!(unanalyzable(dynamic), UnanalyzableReason::DynamicGlobalPath);
        assert_eq!(
            unanalyzable(vec![json!(1), json!(0)]),
            UnanalyzableReason::ZeroLengthGlobalChain
        );
        // A `TRY` installs a handler this pass does not follow.
        assert_eq!(
            unanalyzable(vec![json!(50), json!(1), json!(29)]),
            UnanalyzableReason::UnsupportedOp(Operation::Try)
        );
        assert_eq!(
            unanalyzable(vec![json!(11)]),
            UnanalyzableReason::StackUnderflow
        );
        assert!(matches!(
            unanalyzable(vec![json!(99)]),
            UnanalyzableReason::Decode(_)
        ));
    }

    /// The `if(cond, a, b)` shape the compiler emits for `null_safe_comparisons`. Both arms are
    /// visited, so a read reachable on either one is claimed. Refusing the branch — as the linear
    /// model did — reported every `>`/`>=`/`<`/`<=` condition as unreadable.
    #[test]
    fn both_arms_of_a_conditional_contribute_their_reads() {
        // if(<opaque>, properties.a, properties.b)
        let then = read(&["properties", "a"]);
        let otherwise = read(&["properties", "b"]);
        let mut tokens = vec![json!(29)];
        tokens.push(json!(40));
        tokens.push(json!(then.len() as i64 + 2));
        tokens.extend(then);
        tokens.push(json!(39));
        tokens.push(json!(otherwise.len() as i64));
        tokens.extend(otherwise);
        assert_eq!(reads(tokens), ["properties.a", "properties.b"]);
    }

    /// The `ifNull(expr, fallback)` shape, which wraps every regex comparison. The peek does not
    /// pop, and the fall-through arm's `POP` is what balances it, so the two paths meet at the
    /// same depth.
    #[test]
    fn an_ifnull_peek_and_its_pop_arm_meet_at_the_same_depth() {
        let mut tokens = read(&["properties", "url"]);
        // JUMP_IF_STACK_NOT_NULL over the POP and the FALSE that replaces the null.
        tokens.push(json!(47));
        tokens.push(json!(2));
        tokens.push(json!(35));
        tokens.push(json!(30));
        assert_eq!(reads(tokens), ["properties.url"]);
    }

    /// The `between` lowering: an IIFE that keeps its operands in local slots, reads them back with
    /// `GET_LOCAL`, merges two arms, and pops the locals on the way out. The whole shape has to
    /// stay readable, because a date range is one of the commonest cohort conditions.
    #[test]
    fn a_between_iife_over_local_slots_stays_readable() {
        // NULL (result slot), then the three operands into slots 1-3.
        let mut tokens = vec![json!(31)];
        tokens.extend(read(&["properties", "score"]));
        tokens.push(json!(33));
        tokens.push(json!(1));
        tokens.push(json!(33));
        tokens.push(json!(10));
        // low != null AND high != null AND expr != null
        for slot in [2, 3, 1] {
            tokens.push(json!(36));
            tokens.push(json!(slot));
            tokens.push(json!(31));
            tokens.push(json!(12));
        }
        tokens.push(json!(3));
        tokens.push(json!(3));
        // expr >= low AND expr <= high
        let between = vec![
            json!(36),
            json!(2),
            json!(36),
            json!(1),
            json!(14),
            json!(36),
            json!(3),
            json!(36),
            json!(1),
            json!(16),
            json!(3),
            json!(2),
        ];
        tokens.push(json!(40));
        tokens.push(json!(between.len() as i64 + 2));
        tokens.extend(between);
        tokens.push(json!(39));
        tokens.push(json!(1));
        tokens.push(json!(30));
        // Store into the result slot, then pop the three locals.
        tokens.push(json!(37));
        tokens.push(json!(0));
        tokens.extend([json!(35), json!(35), json!(35)]);
        assert_eq!(reads(tokens), ["properties.score"]);
    }

    /// A backward jump makes the worklist revisit instructions until the joined stacks stop
    /// changing. Without a fixpoint this would either loop forever or report a program the VM runs.
    #[test]
    fn a_backward_jump_converges_on_a_fixpoint() {
        // properties.a; loop: POP; properties.b; JUMP back to loop.
        let mut tokens = read(&["properties", "a"]);
        let loop_body_len: i64 = 1 + read(&["properties", "b"]).len() as i64;
        tokens.push(json!(35));
        tokens.extend(read(&["properties", "b"]));
        tokens.push(json!(39));
        tokens.push(json!(-(loop_body_len + 2)));
        assert_eq!(reads(tokens), ["properties.a", "properties.b"]);
    }

    /// Two paths that meet holding different stack depths mean the transfer table has lost the
    /// layout, and every later `GET_GLOBAL` would pop the wrong cells.
    #[test]
    fn paths_meeting_at_different_depths_fail_closed() {
        // TRUE; JUMP_IF_FALSE over one push; TRUE; (merge) — the taken edge arrives one shallower.
        let tokens = vec![json!(29), json!(40), json!(1), json!(29)];
        assert_eq!(unanalyzable(tokens), UnanalyzableReason::StackDepthMismatch);
    }

    /// A jump into the middle of an instruction would have the VM read an immediate as an opcode.
    /// Landing one past the last token is different: that is a jump off the end, and the program
    /// simply stops there.
    #[test]
    fn a_jump_off_a_boundary_fails_closed_but_a_jump_off_the_end_terminates() {
        // JUMP into the middle of the following STRING instruction.
        assert_eq!(
            unanalyzable(vec![json!(39), json!(1), json!(32), json!("x"), json!(35)]),
            UnanalyzableReason::BadJumpTarget
        );
        // JUMP past `program`'s trailing RETURN, which is one token past the end.
        assert_eq!(
            unanalyzable(vec![json!(39), json!(99)]),
            UnanalyzableReason::BadJumpTarget
        );
        // A read, then a jump that lands exactly on the end: the read still counts.
        let mut off_the_end = read(&["event"]);
        off_the_end.push(json!(35));
        off_the_end.push(json!(39));
        off_the_end.push(json!(1));
        assert_eq!(reads(off_the_end), ["event"]);
    }

    /// A local slot outside the frame is what the VM's own bounds check refuses, so the analysis
    /// must not silently read or write a cell that is not there.
    #[test]
    fn a_local_slot_outside_the_frame_fails_closed() {
        assert_eq!(
            unanalyzable(vec![json!(36), json!(3), json!(29)]),
            UnanalyzableReason::LocalSlotOutOfRange
        );
        assert_eq!(
            unanalyzable(vec![json!(29), json!(37), json!(4)]),
            UnanalyzableReason::LocalSlotOutOfRange
        );
    }

    /// A `RETURN` that leaves values behind means a stack effect in the transfer table is wrong.
    /// Reporting it turns a class of silent misreads into a wide, safe answer.
    #[test]
    fn a_return_over_an_unbalanced_stack_fails_closed() {
        assert_eq!(
            unanalyzable(vec![json!(29), json!(29)]),
            UnanalyzableReason::UnbalancedReturn
        );
    }

    /// The loader appends a `RETURN` to bytecode that may already end in one, so a repeated
    /// trailing `RETURN` is normal: the first one terminates every path, and the second is simply
    /// never reached.
    #[test]
    fn a_repeated_trailing_return_is_never_reached() {
        assert_eq!(reads(read(&["event"])), ["event"]);
    }

    /// A long straight-line program has no merge point, so the pass stores no per-instruction
    /// state at all.
    ///
    /// This is the shape a large `IN` list compiles to, and catalogs hold lists of several
    /// thousand. Storing one abstract stack per instruction across such a program is cells
    /// proportional to the square of its length: at the largest list size production is known to
    /// carry, that was over a gigabyte and seconds of blocking on the caller's task, for a program
    /// the VM itself evaluates in kilobytes.
    #[test]
    fn a_long_straight_line_program_costs_no_stored_state() {
        const ELEMENTS: usize = 2_000;
        let mut tokens = Vec::new();
        for index in 0..ELEMENTS {
            tokens.push(json!(32));
            tokens.push(json!(format!("v{index}")));
        }
        tokens.push(json!(44));
        tokens.push(json!(ELEMENTS));
        tokens.extend(read(&["properties", "plan"]));
        tokens.push(json!(21));

        let bytecode = program(tokens);
        let decoded = decode(&bytecode).expect("an IN list decodes");
        let starts: Vec<TokenIndex> = decoded.instrs.iter().map(|instr| instr.start).collect();
        assert!(
            !merge_points(&decoded, &starts).contains(&true),
            "an IN list has a merge point, so the pass would store one stack per instruction"
        );
        assert_eq!(reads_of(&bytecode), ["properties.plan"]);
    }

    /// A jump the decoder could not resolve is refused where it is visited, not where it is read.
    /// A dead one costs nothing, which is the same rule every other unmodeled construct follows.
    #[test]
    fn an_unresolvable_jump_fails_closed_only_when_a_path_reaches_it() {
        assert_eq!(
            unanalyzable(vec![json!(39), json!(-99)]),
            UnanalyzableReason::BadJumpTarget
        );
        // The same jump, behind an unconditional jump over it.
        let mut tokens = read(&["properties", "plan"]);
        tokens.push(json!(39));
        tokens.push(json!(2));
        tokens.push(json!(39));
        tokens.push(json!(-99));
        assert_eq!(reads(tokens), ["properties.plan"]);
    }

    /// Refusal happens when an instruction is visited, so an unmodeled opcode no path reaches costs
    /// nothing. Without that, one dead `CALLABLE` would widen an otherwise readable condition.
    #[test]
    fn an_unmodeled_opcode_no_path_reaches_is_harmless() {
        let mut tokens = read(&["properties", "plan"]);
        tokens.push(json!(39));
        // Jump over a CALLABLE with an empty body.
        tokens.push(json!(5));
        tokens.extend([json!(52), json!("f"), json!(0), json!(0), json!(0)]);
        assert_eq!(reads(tokens), ["properties.plan"]);
    }

    /// An ordinary native call is projection-safe, because it only consumes stack values. Refusing
    /// every native would make every `toDateTime(timestamp) > x` condition unprojectable.
    #[test]
    fn a_native_call_over_a_read_keeps_the_read_precise() {
        assert_eq!(reads(call_over_timestamp("toDateTime")), ["timestamp"]);
    }

    /// A native that reads a number's spelling is the one call the read set cannot describe: the
    /// paths are right, but supplying them from re-serialized JSON changes the answer. See
    /// [`REPRESENTATION_SENSITIVE_NATIVES`]. Reported as an understood program rather than as a
    /// failure, because nothing about it escaped the model.
    #[test]
    fn a_representation_sensitive_native_widens_to_every_column() {
        for name in REPRESENTATION_SENSITIVE_NATIVES {
            assert_eq!(
                full_columns_reason(call_over_timestamp(name)),
                FullColumnsReason::RepresentationSensitiveCall,
                "{name}"
            );
        }
    }

    /// The refusal is on the call, not on the read under it: a program that never calls one of
    /// these keeps its narrow answer however many other natives it uses.
    #[test]
    fn a_sensitive_native_name_only_matters_when_it_is_called() {
        assert_eq!(reads(call_over_timestamp("toTypeOf")), ["timestamp"]);
        assert_eq!(
            reads(read(&["properties", "typeof"])),
            ["properties.typeof"]
        );
    }

    /// `name(timestamp) > '2026-01-01'`.
    fn call_over_timestamp(name: &str) -> Vec<Value> {
        let mut tokens = read(&["timestamp"]);
        tokens.push(json!(2));
        tokens.push(json!(name));
        tokens.push(json!(1));
        tokens.push(json!(32));
        tokens.push(json!("2026-01-01"));
        tokens.push(json!(13));
        tokens
    }

    /// A hostile count immediate must not reach an allocation. `u64::MAX` is a capacity-overflow
    /// panic and a merely huge value is an allocation abort; either would take down the caller's
    /// task, which the fail-closed contract cannot absorb.
    ///
    /// The refusal also names the opcode it stopped on. A decode failure is the reason a census
    /// cannot diagnose from the coarse label alone, because it is what a decoder drifting from
    /// `vm.rs` looks like, and the opcode is the field that says which table entry drifted.
    #[test]
    fn a_hostile_global_chain_count_never_allocates() {
        for count in [json!(u64::MAX), json!(4_000_000_000u64)] {
            let reason = unanalyzable(vec![json!(1), count.clone()]);
            assert!(matches!(reason, UnanalyzableReason::Decode(_)));
            assert_eq!(reason.op(), Some(Operation::GetGlobal));
        }
        // A count the decoder accepts, still deeper than the stack.
        let padded = std::iter::repeat_n(json!(29), 8)
            .chain([json!(1), json!(6)])
            .collect::<Vec<_>>();
        assert_eq!(
            unanalyzable(padded),
            UnanalyzableReason::DynamicGlobalPath,
            "eight opaque pushes are enough for a six-deep chain, so this is not an underflow"
        );
        let shallow = vec![json!(29), json!(29), json!(1), json!(6)];
        assert_eq!(unanalyzable(shallow), UnanalyzableReason::StackUnderflow);
    }

    /// Both ceilings, on programs small enough to reach them at unit cost rather than at a million
    /// steps. They are guards rather than dead code, so the risk they carry is not an unreachable
    /// branch — it is a guard that is wrong and nothing that says so.
    ///
    /// The step ceiling is reached through the loop here rather than through the spent-budget
    /// shortcut, which the next test covers.
    #[test]
    fn each_ceiling_fails_closed_under_its_own_reason() {
        // STRING, STRING, GET_GLOBAL, RETURN.
        let straight_line = program(read(&["properties", "plan"]));
        assert_eq!(
            unanalyzable_within(
                &straight_line,
                &mut AnalysisBudget {
                    steps: 1,
                    cells: usize::MAX
                }
            ),
            UnanalyzableReason::IterationBudget
        );

        // A fork whose two edges both land on the POP, so the pass copies its one-deep stack onto
        // the worklist rather than walking it in place. Without a copy there is no cell to charge.
        let forked = program(vec![
            json!(32),
            json!("x"),
            json!(29),
            json!(40),
            json!(0),
            json!(35),
            json!(29),
        ]);
        assert_eq!(
            reads_of(&forked),
            Vec::<String>::new(),
            "the fork analyzes cleanly when the budget allows it"
        );
        assert_eq!(
            unanalyzable_within(
                &forked,
                &mut AnalysisBudget {
                    steps: usize::MAX,
                    cells: 0
                }
            ),
            UnanalyzableReason::StateBudget
        );
    }

    /// One budget across several conditions is what bounds a batch rather than each member of it.
    /// The spend has to be real: a budget that reset per condition would leave `conditions ×
    /// ceiling`, which is the shape this exists to refuse.
    #[test]
    fn a_shared_budget_is_spent_down_and_then_refuses() {
        // STRING, STRING, GET_GLOBAL, RETURN: four transfer steps, exactly.
        let bytecode = program(read(&["properties", "plan"]));
        let mut budget = AnalysisBudget {
            steps: 4,
            cells: usize::MAX,
        };
        assert!(matches!(
            project(&bytecode, &mut budget),
            Projection::Reads(_)
        ));
        assert_eq!(budget.steps, 0);
        // The next condition is refused before it is even decoded.
        assert_eq!(
            unanalyzable_within(&bytecode, &mut budget),
            UnanalyzableReason::IterationBudget
        );
    }

    /// A deep stack, then diamonds whose two arms write different literals into one local slot, so
    /// every rejoin widens a cell and re-enqueues a full-depth stack.
    fn widening_diamonds(depth: usize, count: usize) -> Vec<Value> {
        let mut tokens = Vec::new();
        for index in 0..depth {
            tokens.push(json!(32));
            tokens.push(json!(format!("v{index}")));
        }
        for index in 0..count {
            let slot = index % depth;
            // TRUE; JUMP_IF_FALSE over the first arm.
            tokens.extend([json!(29), json!(40), json!(6)]);
            // STRING "a"; SET_LOCAL slot; JUMP over the second arm.
            tokens.extend([
                json!(32),
                json!("a"),
                json!(37),
                json!(slot),
                json!(39),
                json!(4),
            ]);
            // STRING "b"; SET_LOCAL slot.
            tokens.extend([json!(32), json!("b"), json!(37), json!(slot)]);
        }
        for _ in 0..depth {
            tokens.push(json!(35));
        }
        tokens.push(json!(31));
        tokens
    }

    /// The shape merge-point gating does not answer: a program that is *all* merge points.
    ///
    /// Its cost is the copying, and neither of the other two ceilings sees it. Steps do not, because
    /// one step copies a whole stack. The memory ceiling does not either, because each copy is
    /// popped again, so the pass holds a fraction of what it has copied. At the sizes a catalog row
    /// can carry this ran for over a second on the caller's task before the copied-cell ceiling
    /// existed.
    #[test]
    fn a_program_that_is_all_merge_points_is_charged_by_the_cells_it_copies() {
        let bytecode = program(widening_diamonds(40, 40));
        let decoded = decode(&bytecode).expect("the shape decodes");
        let mut interpreter = Interpreter::new(&decoded, AnalysisBudget::for_one_condition());
        interpreter
            .run()
            .unwrap_or_else(|_| panic!("the shape analyzes cleanly under a whole budget"));
        assert!(
            interpreter.cells_copied > interpreter.steps * 5,
            "{} steps against {} copied cells, so the step ceiling bounds this shape after all",
            interpreter.steps,
            interpreter.cells_copied
        );
        assert!(
            interpreter.retained < MAX_RETAINED_CELLS / 10,
            "{} cells held at the end, so the memory ceiling is what bounds this shape",
            interpreter.retained
        );

        assert_eq!(
            unanalyzable_within(
                &bytecode,
                &mut AnalysisBudget {
                    steps: usize::MAX,
                    cells: 1_000
                }
            ),
            UnanalyzableReason::StateBudget
        );
    }
}
