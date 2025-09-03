//! Common HTTP server utilities for PostHog Rust services
//!
//! This crate provides reusable utilities commonly needed by HTTP servers:
//!
//! - **Deserializers**: Serde deserializers for handling HTTP query parameters
//!   and request data in a flexible way
//! - **Shutdown**: Graceful shutdown utilities for HTTP servers
//!
//! # Deserializers
//!
//! The deserializers module provides utilities for parsing HTTP parameters:
//!
//! - [`deserialize_optional_bool`] - Parse boolean query parameters with presence-as-true logic
//! - [`empty_string_as_none`] - Treat empty strings as None for any FromStr type
//! - [`deserialize_optional_timestamp`] - Parse timestamps from strings or integers
//!
//! # Shutdown
//!
//! The shutdown module provides:
//!
//! - [`graceful_shutdown`] - Future that completes on SIGTERM/SIGINT for graceful server shutdown
//!
//! # Examples
//!
//! ## Using deserializers in query parameters
//!
//! ```rust
//! use serde::Deserialize;
//! use http_server::{deserialize_optional_bool, empty_string_as_none};
//!
//! #[derive(Deserialize)]
//! struct QueryParams {
//!     #[serde(default, deserialize_with = "deserialize_optional_bool")]
//!     debug: Option<bool>,
//!     
//!     #[serde(default, deserialize_with = "empty_string_as_none")]
//!     version: Option<String>,
//! }
//! ```
//!
//! ## Using graceful shutdown with a server
//!
//! ```no_run
//! use http_server::graceful_shutdown;
//!
//! # async fn example() -> Result<(), Box<dyn std::error::Error>> {
//! // With any HTTP server that supports graceful shutdown
//! // axum::Server::bind(&addr)
//! //     .serve(app.into_make_service())
//! //     .with_graceful_shutdown(graceful_shutdown())
//! //     .await?;
//! # Ok(())
//! # }
//! ```

pub mod deserializers;
pub mod shutdown;

// Re-export the most commonly used items for convenience
pub use deserializers::{
    deserialize_optional_bool, deserialize_optional_timestamp, empty_string_as_none,
};
pub use shutdown::graceful_shutdown;
