//! # capture-pipelines-poc
//!
//! A proof-of-concept for the capture pipelines framework, built with **static
//! dispatch only** — generics and `macro_rules!`, no `Box<dyn …>`, no `async_trait`.
//! It answers the open question in the design: can the framework's composition,
//! effects, observers, and async stages all be expressed without type erasure? Yes.
//!
//! This is a *demonstration crate*: no server, no Kafka, no real config. It compiles,
//! passes tests and `clippy -D warnings`, and reads as the skeleton the real framework
//! would grow from. See `README.md` for how it maps onto the plan and #70814.
//!
//! ## Tour
//!
//! - [`result`] — the verdict vocabulary: [`StepResult`](result::StepResult),
//!   [`Outputs`](result::Outputs), [`NoOutputs`](result::NoOutputs).
//! - [`step`] — the [`Step`](step::Step) workhorse and its
//!   [`FallibleStep`](step::FallibleStep) sibling.
//! - [`chain`] — monomorphized composition: [`Chain`](chain::Chain), the typestate
//!   [`PipelineBuilder`](chain::PipelineBuilder), and the runnable
//!   [`Pipeline`](chain::Pipeline).
//! - [`fail_open`] — turn a fallible step into an infallible one (capture's failure
//!   philosophy, compile-enforced).
//! - [`capability`] — minimal-input capability bounds, phase wrappers, and type-level
//!   lanes. Home of the [`impl_passthrough_caps!`] macro.
//! - [`fx`] — cross-cutting effects as compile-time capabilities. Home of the
//!   [`compose_fx!`] macro and the `compile_fail` proof that a missing sink is a
//!   compile error.
//! - [`observer`] — read-only verdict hooks composed as tuples. Home of the
//!   [`impl_observer_tuple!`] macro.
//! - [`outputs`] — typed redirect targets and the startup-checked
//!   [`OutputRegistry`](outputs::OutputRegistry).
//! - [`chunk`] — async chunk stages via native async-fn-in-trait.
//! - [`demo`] — a small analytics pipeline wired end to end (see the
//!   `tests/analytics_demo.rs` integration test).
//!
//! ## The three macros
//!
//! | Macro | Eliminates |
//! |---|---|
//! | [`impl_passthrough_caps!`] | hand-written capability forwarding through wrappers |
//! | [`compose_fx!`] | hand-written `HasSink` wiring for a pipeline's effects struct |
//! | [`impl_observer_tuple!`] | hand-written `Observer` impls for tuple composition |

#![warn(missing_docs)]

pub mod capability;
pub mod chain;
pub mod chunk;
pub mod demo;
pub mod fail_open;
pub mod fx;
pub mod observer;
pub mod outputs;
pub mod result;
pub mod step;
