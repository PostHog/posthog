//! Static analysis of a pinned condition's HogVM bytecode: which event globals it reads, and
//! whether it is nothing more than an event-name equality. Depends on `hogvm::Operation` only.
//!
//! Cohort policy stays out of the shared `common/hogvm` crate, the same way [`super::executor`]
//! layers evaluation on top of the VM's primitives rather than changing them.
//!
//! # Fail closed
//!
//! Every unmodeled input becomes [`Projection::FullColumns`], which means "read everything". A
//! caller acting on the result is then slower than it could be, never wrong. That is why
//! [`analyze_condition`] is total: it returns no error and never panics, because the alternative
//! (treating an analysis failure as "reads nothing") would silently drop rows from a scan.
//!
//! One input is answered rather than widened: a `GET_GLOBAL` root outside [`GlobalRoot`] claims no
//! read. That is not an exception to the rule above, but a consequence of the section below — such
//! a root reads no event data at all. A root naming a representation-sensitive native still widens,
//! because it resolves to a closure the program can call.
//!
//! # Why the read set can be trusted
//!
//! `GET_GLOBAL` is the VM's only path into the globals dict, and it takes its path from literal
//! strings the compiler pushed. Every other opcode consumes values already on the stack. So a
//! program whose `GET_GLOBAL`s all resolve to literal paths cannot reach a global this analysis did
//! not record, however it combines those values afterwards.
//!
//! A path whose root is outside [`GlobalRoot`] records nothing, which is sound because a projection
//! narrows the values *under* a root and never removes one. A name no globals dict carries is
//! absent from the projected event and from the full one alike, so it names no column. That rests
//! on [`GlobalRoot`] covering every dict this crate builds, which
//! `every_globals_dict_key_is_a_named_root` in `hogvm::globals` checks.
//!
//! Reading no event data is only half the obligation. A bare native name resolves to a closure
//! instead of a read, so such a root widens whenever calling it would read a value's spelling
//! rather than its value, the same way a direct call to it does.

mod decode;
mod event_only;
mod projection;

use std::collections::BTreeSet;

use hogvm::Operation;
use serde_json::Value;

pub use decode::DecodeError;
pub use projection::AnalysisBudget;

/// What a static pass could establish about one condition's bytecode.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ConditionAnalysis {
    pub evaluation: EvaluationClass,
    pub projection: Projection,
}

/// How much of the VM a condition actually needs.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum EvaluationClass {
    /// The whole program is `event == <name>`. Such a condition is decided by the event name a
    /// scan already filters on, so it needs no per-row evaluation at all.
    EventOnly { event: String },
    /// Anything else.
    General,
}

/// The globals a condition reads, when they can be named.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Projection {
    /// Exactly these paths, and nothing else. Empty means the program reads no globals.
    ///
    /// A path names a subtree, not a leaf: `person.properties` claims everything under it, because
    /// the program may hand that object to a function that indexes it at runtime. A caller
    /// building a projection has to supply the whole subtree each path names. The analysis never
    /// returns a bare object root here — [`FullColumnsReason::BarePropertiesRoot`] and
    /// [`FullColumnsReason::BarePersonRoot`] carry those — so a `Reads` path is always at least one
    /// key deep under `properties`, `person`, or `pdi`.
    Reads(BTreeSet<ReadPath>),
    /// The read set could not be narrowed, so a caller must supply every column.
    FullColumns(FullColumnsReason),
}

/// Why a condition fell back to every column. Every case but [`FullColumnsReason::Unanalyzable`] is
/// an ordinary program the analysis understood and still cannot narrow; that one is the fail-closed
/// arm, where the model lost track of the program.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FullColumnsReason {
    /// The program passes the whole `properties` dict somewhere, for example to a function.
    BarePropertiesRoot,
    /// The program passes the whole `person` object somewhere.
    BarePersonRoot,
    /// The program calls a native that reads how a number was spelled rather than what it is, so a
    /// caller supplying the claimed paths from re-serialized JSON would change the answer. The read
    /// set itself is exact; what cannot be narrowed is how it may be supplied.
    RepresentationSensitiveCall,
    Unanalyzable(UnanalyzableReason),
}

impl FullColumnsReason {
    /// A closed, bounded label. Safe as a metric dimension: it never carries program text.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::BarePropertiesRoot => "bare_properties_root",
            Self::BarePersonRoot => "bare_person_root",
            Self::RepresentationSensitiveCall => "representation_sensitive_call",
            Self::Unanalyzable(reason) => reason.as_str(),
        }
    }

    /// Which opcode stopped the analysis, when one did. See [`UnanalyzableReason::op`].
    pub fn op(&self) -> Option<Operation> {
        match self {
            Self::Unanalyzable(reason) => reason.op(),
            Self::RepresentationSensitiveCall => Some(Operation::CallGlobal),
            Self::BarePropertiesRoot | Self::BarePersonRoot => None,
        }
    }
}

/// Why a program escaped the abstract model. Each variant is a closed metric label, so this
/// vocabulary is what a census reports on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UnanalyzableReason {
    Decode(DecodeError),
    /// An opcode whose effect the model does not reproduce: a frame, a heap write, or an exception
    /// handler.
    UnsupportedOp(Operation),
    /// A `GET_GLOBAL` path segment that is not a compile-time literal.
    DynamicGlobalPath,
    StackUnderflow,
    /// `GET_GLOBAL 0`, which the VM itself rejects.
    ZeroLengthGlobalChain,
    /// Two paths reached one instruction holding stacks of different depths, so the model has lost
    /// the layout every later `GET_GLOBAL` depends on.
    StackDepthMismatch,
    /// A jump landing inside an instruction rather than on one, which the VM would read as an
    /// opcode where an immediate is.
    BadJumpTarget,
    /// The worklist ran past its step ceiling, so the fixpoint argument does not hold for this
    /// program. Never expected on its own; it exists so an unforeseen shape is a wide answer, not a
    /// hang. Also how a condition reports a shared [`AnalysisBudget`] its siblings already spent.
    IterationBudget,
    /// The pass would have had to hold or copy more abstract stack state than its ceiling allows.
    /// Bounds the memory and the copying a condition can cost, whatever its branching shape, and
    /// reports a shared [`AnalysisBudget`] spent down to its cell half.
    StateBudget,
    /// A local slot outside the current frame, which the VM's own bounds check refuses.
    LocalSlotOutOfRange,
    /// A `RETURN` that left values on the stack, meaning a stack effect in the transfer table is
    /// wrong.
    UnbalancedReturn,
}

impl UnanalyzableReason {
    /// A closed, bounded label. The payloads (an opcode, a decode position) stay out of it, so it
    /// is safe as a metric dimension however hostile the bytecode is. Use [`Self::op`] for the one
    /// payload that is itself bounded.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Decode(_) => "decode",
            Self::UnsupportedOp(_) => "unsupported_op",
            Self::DynamicGlobalPath => "dynamic_global_path",
            Self::StackUnderflow => "stack_underflow",
            Self::ZeroLengthGlobalChain => "zero_length_global_chain",
            Self::StackDepthMismatch => "stack_depth_mismatch",
            Self::BadJumpTarget => "bad_jump_target",
            Self::IterationBudget => "iteration_budget",
            Self::StateBudget => "state_budget",
            Self::LocalSlotOutOfRange => "local_slot_out_of_range",
            Self::UnbalancedReturn => "unbalanced_return",
        }
    }

    /// Which opcode stopped the analysis, when one did.
    ///
    /// [`Operation`] is a closed 57-variant enum, so this is as bounded as [`Self::as_str`] and
    /// safe as a second metric dimension. It is worth carrying because "unsupported_op" alone
    /// cannot tell one fixable compiler template apart from a genuinely unreadable program.
    ///
    /// A decode failure names its opcode too, and that is the case the label earns the most: a
    /// decoder whose immediate table drifts from `vm.rs` fails on the opcode that drifted.
    /// Exhaustive rather than defaulted, so a new variant has to decide.
    pub fn op(&self) -> Option<Operation> {
        match self {
            Self::Decode(error) => error.op(),
            Self::UnsupportedOp(op) => Some(*op),
            Self::DynamicGlobalPath
            | Self::StackUnderflow
            | Self::ZeroLengthGlobalChain
            | Self::StackDepthMismatch
            | Self::BadJumpTarget
            | Self::IterationBudget
            | Self::StateBudget
            | Self::LocalSlotOutOfRange
            | Self::UnbalancedReturn => None,
        }
    }
}

/// One global the program reads, as a root plus the keys taken under it. `Ord` so a
/// [`BTreeSet`] of these has a stable order, which keeps a census reproducible.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct ReadPath {
    pub root: GlobalRoot,
    pub segments: Vec<String>,
}

impl ReadPath {
    pub fn new(root: GlobalRoot, segments: Vec<String>) -> Self {
        Self { root, segments }
    }

    /// The dotted rendering, for logs and census output.
    pub fn render(&self) -> String {
        let mut rendered = self.root.as_str().to_owned();
        for segment in &self.segments {
            rendered.push('.');
            rendered.push_str(segment);
        }
        rendered
    }
}

/// A group ordinal, which the behavioral globals define for 0 through 4.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub struct GroupIndex(u8);

impl GroupIndex {
    pub const COUNT: u8 = 5;

    pub fn parse(index: u8) -> Option<Self> {
        (index < Self::COUNT).then_some(Self(index))
    }

    pub const fn get(self) -> u8 {
        self.0
    }
}

/// Every root of every globals dict this crate builds, which is the whole surface a condition can
/// read.
///
/// The list is load-bearing in one direction. A name outside it claims no read, so a key added to a
/// globals dict without a variant here would be pruned from a scan while the program still reads
/// it. `every_globals_dict_key_is_a_named_root` in `hogvm::globals` is what earns that: it walks
/// the dicts themselves rather than a list, so it fails as soon as one gains a key.
///
/// The other direction is benign. A variant no dict carries over-claims a read, which costs bytes
/// and never correctness, so nothing here has to chase it.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum GlobalRoot {
    Event,
    Uuid,
    ElementsChain,
    ElementsChainHref,
    ElementsChainTexts,
    ElementsChainIds,
    ElementsChainElements,
    Timestamp,
    Properties,
    Person,
    Pdi,
    DistinctId,
    DollarGroup(GroupIndex),
    Group(GroupIndex),
    Variables,
    /// Only in the person-scope dict, never in the behavioral one. Named here so that "not a
    /// [`GlobalRoot`]" means "in no globals dict this crate builds" rather than "in the behavioral
    /// one".
    Project,
}

impl GlobalRoot {
    /// Resolve a literal root name. `None` means no globals dict this crate builds carries the
    /// name — which the analysis reads as "this path touches no event data", so the scope of the
    /// `None` is what makes that sound.
    pub fn parse(name: &str) -> Option<Self> {
        match name {
            "event" => Some(Self::Event),
            "uuid" => Some(Self::Uuid),
            "elements_chain" => Some(Self::ElementsChain),
            "elements_chain_href" => Some(Self::ElementsChainHref),
            "elements_chain_texts" => Some(Self::ElementsChainTexts),
            "elements_chain_ids" => Some(Self::ElementsChainIds),
            "elements_chain_elements" => Some(Self::ElementsChainElements),
            "timestamp" => Some(Self::Timestamp),
            "properties" => Some(Self::Properties),
            "person" => Some(Self::Person),
            "pdi" => Some(Self::Pdi),
            "distinct_id" => Some(Self::DistinctId),
            "variables" => Some(Self::Variables),
            "project" => Some(Self::Project),
            _ => name
                .strip_prefix("$group_")
                .and_then(group_index)
                .map(Self::DollarGroup)
                .or_else(|| {
                    name.strip_prefix("group_")
                        .and_then(group_index)
                        .map(Self::Group)
                }),
        }
    }

    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Event => "event",
            Self::Uuid => "uuid",
            Self::ElementsChain => "elements_chain",
            Self::ElementsChainHref => "elements_chain_href",
            Self::ElementsChainTexts => "elements_chain_texts",
            Self::ElementsChainIds => "elements_chain_ids",
            Self::ElementsChainElements => "elements_chain_elements",
            Self::Timestamp => "timestamp",
            Self::Properties => "properties",
            Self::Person => "person",
            Self::Pdi => "pdi",
            Self::DistinctId => "distinct_id",
            Self::DollarGroup(index) => DOLLAR_GROUP_NAMES[index.get() as usize],
            Self::Group(index) => GROUP_NAMES[index.get() as usize],
            Self::Variables => "variables",
            Self::Project => "project",
        }
    }
}

const DOLLAR_GROUP_NAMES: [&str; GroupIndex::COUNT as usize] =
    ["$group_0", "$group_1", "$group_2", "$group_3", "$group_4"];
const GROUP_NAMES: [&str; GroupIndex::COUNT as usize] =
    ["group_0", "group_1", "group_2", "group_3", "group_4"];

/// A single-digit group ordinal, rejecting `group_00` and `group_10` alike.
fn group_index(suffix: &str) -> Option<GroupIndex> {
    let [digit] = suffix.as_bytes() else {
        return None;
    };
    GroupIndex::parse(digit.checked_sub(b'0')?)
}

/// Analyze one condition's loaded bytecode, under a budget of its own.
///
/// Total: it returns no error and never panics. Anything the model does not cover becomes
/// [`Projection::FullColumns`] carrying the reason, because a wrong narrow answer would drop rows
/// from a scan while a wide one only costs time.
pub fn analyze_condition(bytecode: &[Value]) -> ConditionAnalysis {
    analyze_condition_within(bytecode, &mut AnalysisBudget::for_one_condition())
}

/// Analyze one condition against a budget its siblings share.
///
/// A caller with many conditions wants the batch bounded, not each member of it: the per-condition
/// ceilings leave `conditions × ceiling`, which is unbounded wherever nothing caps the conditions.
/// Spending one budget in a fixed order keeps that bounded and keeps the analysis a pure function
/// of its input, so the same batch always classifies the same way.
pub fn analyze_condition_within(
    bytecode: &[Value],
    budget: &mut AnalysisBudget,
) -> ConditionAnalysis {
    ConditionAnalysis {
        evaluation: event_only::classify(bytecode),
        projection: projection::project(bytecode, budget),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    /// The assumption the read set rests on, checked against the VM's own standard library.
    ///
    /// A `CALL_GLOBAL` to a hog-implemented standard-library function is not a native call: the VM
    /// pushes a frame and runs that function's body against the *same* globals dict. The abstract
    /// interpreter does not follow the callee, so if any of those bodies read a global, a condition
    /// calling it would read a global this analysis never recorded, and a projection built from the
    /// claimed set would evaluate it against a truncated event.
    ///
    /// Today no standard-library body contains a `GET_GLOBAL`; they work purely on their arguments.
    /// This fails if one ever does, which is the moment `CALL_GLOBAL` would stop being safe to treat
    /// as a plain stack reduction.
    ///
    /// A body may itself define a lambda, whose tokens `decode` steps over rather than into —
    /// `sortableSemver` already does. Those tokens are still code the VM runs against the same
    /// globals dict, so the scan follows every nested `CALLABLE` body too. Without that, the check
    /// would pass on exactly the shape it exists to catch.
    #[test]
    fn no_standard_library_function_body_reads_a_global() {
        let module = hogvm::hog_stl();
        let functions = module.functions();
        assert!(
            !functions.is_empty(),
            "the standard library is empty, so this check would pass vacuously"
        );
        let mut nested_bodies_seen = 0;
        for (name, function) in functions {
            // The bodies are raw instruction lists, so give them the header the decoder expects.
            let mut body = vec![json!("_H"), json!(1)];
            let mut index = 0;
            while let Some(token) = function.get(index) {
                body.push(token.clone());
                index += 1;
            }
            let decoded = decode::decode(&body).unwrap_or_else(|error| {
                panic!("standard library function {name} did not decode: {error}")
            });
            let mut pending = vec![decoded];
            while let Some(decoded) = pending.pop() {
                for instr in &decoded.instrs {
                    assert!(
                        !matches!(
                            instr.kind,
                            decode::InstrKind::Counted(Operation::GetGlobal, _)
                        ),
                        "standard library function {name} reads a global, so a condition calling \
                         it would read globals this analysis does not record"
                    );
                    if let decode::InstrKind::Callable { body: span } = instr.kind {
                        nested_bodies_seen += 1;
                        pending.push(decode::decode_span(&body, span).unwrap_or_else(|error| {
                            panic!("a lambda body in {name} did not decode: {error}")
                        }));
                    }
                }
            }
        }
        assert!(
            nested_bodies_seen > 0,
            "no standard library function defines a lambda, so the recursion is untested"
        );
    }

    #[test]
    fn every_global_root_round_trips_through_its_name() {
        let roots = [
            GlobalRoot::Event,
            GlobalRoot::Uuid,
            GlobalRoot::ElementsChain,
            GlobalRoot::ElementsChainHref,
            GlobalRoot::ElementsChainTexts,
            GlobalRoot::ElementsChainIds,
            GlobalRoot::ElementsChainElements,
            GlobalRoot::Timestamp,
            GlobalRoot::Properties,
            GlobalRoot::Person,
            GlobalRoot::Pdi,
            GlobalRoot::DistinctId,
            GlobalRoot::Variables,
            GlobalRoot::Project,
        ];
        for root in roots {
            assert_eq!(GlobalRoot::parse(root.as_str()), Some(root.clone()));
        }
        for index in 0..GroupIndex::COUNT {
            let index = GroupIndex::parse(index).unwrap();
            for root in [GlobalRoot::DollarGroup(index), GlobalRoot::Group(index)] {
                assert_eq!(GlobalRoot::parse(root.as_str()), Some(root.clone()));
            }
        }
    }

    /// A name close to a real root must not resolve to one. Accepting `group_9` would let the
    /// analysis claim a read of a global the event does not carry.
    #[test]
    fn near_miss_root_names_do_not_resolve() {
        for name in [
            "group_5",
            "group_9",
            "group_00",
            "group_10",
            "group_",
            "$group_5",
            "$group_",
            "Event",
            "properties2",
            "",
            "person.properties",
        ] {
            assert_eq!(GlobalRoot::parse(name), None, "{name} resolved to a root");
        }
    }

    #[test]
    fn read_paths_render_dotted_and_sort_by_root_then_segments() {
        let path = ReadPath::new(
            GlobalRoot::Person,
            vec!["properties".to_owned(), "email".to_owned()],
        );
        assert_eq!(path.render(), "person.properties.email");
        assert_eq!(
            ReadPath::new(GlobalRoot::Event, Vec::new()).render(),
            "event"
        );

        let mut set = BTreeSet::new();
        set.insert(ReadPath::new(GlobalRoot::Properties, vec!["b".to_owned()]));
        set.insert(ReadPath::new(GlobalRoot::Event, Vec::new()));
        set.insert(ReadPath::new(GlobalRoot::Properties, vec!["a".to_owned()]));
        assert_eq!(
            set.iter().map(ReadPath::render).collect::<Vec<_>>(),
            ["event", "properties.a", "properties.b"]
        );
    }
}
