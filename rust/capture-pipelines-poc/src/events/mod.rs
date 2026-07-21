//! The demo event domain.
//!
//! This layer defines the vocabulary the demo steps speak: the capability traits a
//! step bounds on ([`capabilities`]), the phase/enrichment wrapper types that carry an
//! event through the pipeline ([`wrappers`]), and the concrete boundary event type
//! ([`parsed::ParsedEvent`]).
//!
//! It sits *above* [`crate::framework`] and may use it; the framework never depends
//! back on this layer.

pub mod capabilities;
pub mod parsed;
pub mod wrappers;
