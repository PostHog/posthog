//! HTTP handlers. The only real endpoint is the SSE version beacon
//! ([`stream`]); readiness/liveness/index live on the router.

pub mod stream;
