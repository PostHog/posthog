//! Symbol resolution engine shared by both run modes: the processing
//! pipeline's resolution stage (`crate::stages::resolution`) calls it inline,
//! and resolution mode (`crate::modes::resolution`) serves it over gRPC.
//!
//! - [`symbol`] — the [`symbol::SymbolResolver`] trait and the local resolver.
//! - [`symbol_store`] — symbol-set providers, caching, and the [`symbolication::symbol_store::Catalog`].

pub mod resolve;
pub mod symbol;
pub mod symbol_store;
