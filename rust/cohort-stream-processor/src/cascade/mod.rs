//! Pure decision logic for cohort-of-cohort cascade re-evaluation.
//!
//! [`should_emit`] and [`first_cascade`] are pure functions over [`CascadeMessage`]; the module
//! depends only on the data types [`CohortId`](crate::filters::CohortId) and
//! [`CohortMembershipChange`](crate::producer::CohortMembershipChange), never on I/O or Stage 2 state.

pub mod decision;
pub mod message;

pub use decision::{first_cascade, should_emit};
pub use message::{CascadeDecision, CascadeMessage, DropReason};
