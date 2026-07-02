//! Session-replay anonymizer: PII-scrubs parsed rrweb events for the ml-mirror pipeline.
//!
//! This is a Rust port of `nodejs/src/ingestion/pipelines/sessionreplay/anonymize/*.ts` (the source of
//! truth). It walks a parsed message's events in place, redacting text/URLs, blurring images natively,
//! and de/recompressing `cv` payloads. Parity with the TS is asserted via shared JSON fixtures under
//! `tests/fixtures/` (the same fixtures the Jest suite runs against).

pub mod allow_lists;
pub mod assets;
pub mod blur;
pub mod canvas;
pub mod css;
pub mod cv;
pub mod dom;
pub mod event;
pub mod json;
pub mod text;
pub mod url;
pub mod value;

pub use allow_lists::AllowLists;
pub use event::{anonymize_event, anonymize_event_str, anonymize_message};
