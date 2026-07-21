//! The reusable, domain-agnostic framework machinery.
//!
//! Everything here is generic over the event type and the effects struct — it knows
//! nothing about analytics events, tokens, or overflow. The dependency direction is
//! strictly one-way: `framework` never references [`events`](crate::events),
//! [`steps`](crate::steps), or [`pipeline`](crate::pipeline). Those domain layers are
//! built *on top of* this one.

pub mod batch;
pub mod chain;
pub mod chunk;
pub mod concurrency;
pub mod extend;
pub mod fail_open;
pub mod fx;
pub mod observer;
pub mod outputs;
pub mod result;
pub mod retry;
pub mod step;
