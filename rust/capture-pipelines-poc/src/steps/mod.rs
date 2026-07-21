//! The demo steps, one primary step per file.
//!
//! **Steps are open by default.** Each is generic over its input `In`, bounding only
//! the capability traits it actually reads, and generic over the effects struct `Fx`.
//! A step fixes a concrete input or output type *only* when it has a specific reason,
//! stated in that step's doc comment — the legitimate cases being boundary steps that
//! create the initial type, and steps whose job is type-specific
//! aggregation/folding. Everything here follows that rule (the only concrete type in
//! sight is the enrichment *output* wrapper an [`enrich`]-style step constructs).

pub mod annotate;
pub mod enrich;
pub mod quota;
pub mod restrictions;
pub mod validate;
