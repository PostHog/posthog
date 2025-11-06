mod embeddings;
mod event;
mod formats;
mod group;
mod person;
mod team;
pub mod timestamp;

// Events
pub use event::CapturedEvent;
pub use event::CapturedEventHeaders;
pub use event::ClickHouseEvent;
pub use event::InternallyCapturedEvent;
pub use event::PersonMode;
pub use event::RawEngageEvent;
pub use event::RawEvent;

// Teams
pub use team::ProjectId;
pub use team::Team;
pub use team::TeamId;
pub use team::TeamIdentifier;

// Utils
pub mod util;

// Persons
pub use person::Person;
pub use person::PersonId;

// Groups
pub use group::GroupType;

// Error tracking types are exported directly
pub mod error_tracking;

// Embeddings
pub mod embedding {
    pub use crate::embeddings::ApiLimits;
    pub use crate::embeddings::EmbeddingModel;
    pub use crate::embeddings::EmbeddingRecord;
    pub use crate::embeddings::EmbeddingRequest;
}

pub mod format {
    pub use crate::formats::format_ch_datetime;
    pub use crate::formats::parse_datetime_assuming_utc;
    pub use crate::formats::CH_FORMAT;
}
