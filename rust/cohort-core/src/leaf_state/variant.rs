/// Which state representation a leaf uses.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum StateVariant {
    /// `performed_event`: a single "has any matching event in window" bit.
    BehavioralSingle,
    /// `performed_event_multiple` with a `1..=180`-day window: dense per-calendar-day counts.
    BehavioralDailyBuckets,
    /// `performed_event_multiple` with a window over 180 days: sparse run-length per-calendar-day
    /// counts.
    BehavioralCompressedHistory,
    /// A person-property filter: a last-write-wins boolean.
    PersonProperty,
}

impl StateVariant {
    /// The metric-label / log form.
    pub fn as_str(self) -> &'static str {
        match self {
            Self::BehavioralSingle => "behavioral_single",
            Self::BehavioralDailyBuckets => "behavioral_daily_buckets",
            Self::BehavioralCompressedHistory => "behavioral_compressed_history",
            Self::PersonProperty => "person_property",
        }
    }
}
