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
//! # Why the read set can be trusted
//!
//! `GET_GLOBAL` is the VM's only path into the globals dict, and it takes its path from literal
//! strings the compiler pushed. Every other opcode consumes values already on the stack. So a
//! program whose `GET_GLOBAL`s all resolve to literal paths cannot reach a global this analysis did
//! not record, however it combines those values afterwards.

mod decode;
mod event_only;
mod projection;

use std::collections::BTreeSet;

use hogvm::Operation;
use serde_json::Value;

pub use decode::DecodeError;

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
    Reads(BTreeSet<ReadPath>),
    /// The read set could not be narrowed, so a caller must supply every column.
    FullColumns(FullColumnsReason),
}

/// Why a condition fell back to every column. The two bare-root cases are ordinary programs whose
/// reads genuinely cannot be narrowed; [`FullColumnsReason::Unanalyzable`] is the fail-closed arm.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum FullColumnsReason {
    /// The program passes the whole `properties` dict somewhere, for example to a function.
    BarePropertiesRoot,
    /// The program passes the whole `person` object somewhere.
    BarePersonRoot,
    Unanalyzable(UnanalyzableReason),
}

impl FullColumnsReason {
    /// A closed, bounded label. Safe as a metric dimension: it never carries program text.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::BarePropertiesRoot => "bare_properties_root",
            Self::BarePersonRoot => "bare_person_root",
            Self::Unanalyzable(reason) => reason.as_str(),
        }
    }
}

/// Why a program escaped the linear abstract model. Each variant is a closed metric label, so this
/// vocabulary is what a census reports on.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum UnanalyzableReason {
    Decode(DecodeError),
    /// An opcode whose stack effect the linear model does not reproduce, most often a branch.
    UnsupportedOp(Operation),
    /// A global root outside [`GlobalRoot`], so the program reads something this build cannot name.
    UnknownGlobalRoot(String),
    /// A `GET_GLOBAL` path segment that is not a compile-time literal.
    DynamicGlobalPath,
    StackUnderflow,
    /// `GET_GLOBAL 0`, which the VM itself rejects.
    ZeroLengthGlobalChain,
    /// Instructions after the terminating `RETURN` that are not themselves `RETURN`.
    CodeAfterReturn,
}

impl UnanalyzableReason {
    /// A closed, bounded label. The payloads (an opcode, a root name, a decode position) stay out
    /// of it, so it is safe as a metric dimension however hostile the bytecode is.
    pub fn as_str(&self) -> &'static str {
        match self {
            Self::Decode(_) => "decode",
            Self::UnsupportedOp(_) => "unsupported_op",
            Self::UnknownGlobalRoot(_) => "unknown_global_root",
            Self::DynamicGlobalPath => "dynamic_global_path",
            Self::StackUnderflow => "stack_underflow",
            Self::ZeroLengthGlobalChain => "zero_length_global_chain",
            Self::CodeAfterReturn => "code_after_return",
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

/// The roots of the behavioral globals dict, which is the whole surface a condition can read.
///
/// A root outside this list fails closed through [`UnanalyzableReason::UnknownGlobalRoot`]: if the
/// globals gain a key and this enum does not, the analysis reports it rather than claiming a
/// narrower read set than the program has.
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
}

impl GlobalRoot {
    /// Resolve a literal root name. `None` means the name is not a behavioral global.
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

/// Analyze one condition's loaded bytecode.
///
/// Total: it returns no error and never panics. Anything the model does not cover becomes
/// [`Projection::FullColumns`] carrying the reason, because a wrong narrow answer would drop rows
/// from a scan while a wide one only costs time.
pub fn analyze_condition(bytecode: &[Value]) -> ConditionAnalysis {
    ConditionAnalysis {
        evaluation: event_only::classify(bytecode),
        projection: projection::project(bytecode),
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
    #[test]
    fn no_standard_library_function_body_reads_a_global() {
        let module = hogvm::hog_stl();
        let functions = module.functions();
        assert!(
            !functions.is_empty(),
            "the standard library is empty, so this check would pass vacuously"
        );
        for (name, function) in functions {
            // The bodies are raw instruction lists, so give them the header the decoder expects.
            let mut body = vec![json!("_H"), json!(1)];
            let mut index = 0;
            while let Some(token) = function.get(index) {
                body.push(token.clone());
                index += 1;
            }
            let instrs = decode::decode(&body).unwrap_or_else(|error| {
                panic!("standard library function {name} did not decode: {error}")
            });
            assert!(
                !instrs
                    .iter()
                    .any(|instr| matches!(instr, decode::Instr::Counted(Operation::GetGlobal, _))),
                "standard library function {name} reads a global, so a condition calling it would \
                 read globals this analysis does not record"
            );
        }
    }

    #[test]
    fn every_behavioral_global_root_round_trips_through_its_name() {
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
