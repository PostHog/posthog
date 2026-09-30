//! Classifies a failed scan by the ClickHouse error code behind it, for the run breaker.

use std::error::Error;

/// A ClickHouse error meaning the query did not fit the server's resources.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResourceError {
    /// Also raised when the overcommit tracker stops the query to free memory for others.
    MemoryLimitExceeded,
    TimeoutExceeded,
    TooSlow,
    TooManySimultaneousQueries,
}

impl ResourceError {
    pub const ALL: [Self; 4] = [
        Self::MemoryLimitExceeded,
        Self::TimeoutExceeded,
        Self::TooSlow,
        Self::TooManySimultaneousQueries,
    ];

    pub const fn code(self) -> u32 {
        match self {
            Self::MemoryLimitExceeded => 241,
            Self::TimeoutExceeded => 159,
            Self::TooSlow => 160,
            Self::TooManySimultaneousQueries => 202,
        }
    }

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::MemoryLimitExceeded => "241",
            Self::TimeoutExceeded => "159",
            Self::TooSlow => "160",
            Self::TooManySimultaneousQueries => "202",
        }
    }

    fn from_code(code: u32) -> Option<Self> {
        Self::ALL.into_iter().find(|error| error.code() == code)
    }

    /// Walks the source chain, because the chunk pipeline wraps the `clickhouse` crate's error.
    pub fn classify(error: &(dyn Error + 'static)) -> Option<Self> {
        let mut current = Some(error);
        while let Some(error) = current {
            if let Some(clickhouse::error::Error::BadResponse(message)) =
                error.downcast_ref::<clickhouse::error::Error>()
            {
                return server_error_code(message).and_then(Self::from_code);
            }
            current = error.source();
        }
        None
    }
}

/// The crate reports a server exception as `BadResponse` text starting `Code: <n>.`, whether it
/// arrives before or during the stream.
fn server_error_code(message: &str) -> Option<u32> {
    let rest = message.trim_start().strip_prefix("Code:")?.trim_start();
    let digits = rest
        .find(|character: char| !character.is_ascii_digit())
        .map_or(rest, |end| &rest[..end]);
    digits.parse().ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[derive(Debug, thiserror::Error)]
    #[error("streaming ClickHouse scan cursor")]
    struct Wrapper(#[source] clickhouse::error::Error);

    fn bad_response(message: &str) -> Wrapper {
        Wrapper(clickhouse::error::Error::BadResponse(message.to_owned()))
    }

    #[test]
    fn resource_codes_are_read_through_the_source_chain() {
        for (message, expected) in [
            (
                "Code: 241. DB::Exception: Memory limit (for query) exceeded: would use 16.00 GiB. (MEMORY_LIMIT_EXCEEDED) (version 26.6.2.158)",
                Some(ResourceError::MemoryLimitExceeded),
            ),
            (
                "Code: 241. DB::Exception: Memory limit (total) exceeded. OvercommitTracker decision: Query was selected to stop by OvercommitTracker. (MEMORY_LIMIT_EXCEEDED)",
                Some(ResourceError::MemoryLimitExceeded),
            ),
            (
                "Code: 159. DB::Exception: Timeout exceeded: elapsed 14400.1 seconds, maximum: 14400. (TIMEOUT_EXCEEDED)",
                Some(ResourceError::TimeoutExceeded),
            ),
            (
                "Code: 160. DB::Exception: Estimated query execution time is too long. (TOO_SLOW)",
                Some(ResourceError::TooSlow),
            ),
            (
                "Code: 202. DB::Exception: Too many simultaneous queries for user cohort_seeder. (TOO_MANY_SIMULTANEOUS_QUERIES)",
                Some(ResourceError::TooManySimultaneousQueries),
            ),
            (
                "Code: 47. DB::Exception: Unknown expression identifier `mat_x`. (UNKNOWN_IDENTIFIER)",
                None,
            ),
            (
                "Code: 452. DB::Exception: Setting max_threads shouldn't be greater than 8. (SETTING_CONSTRAINT_VIOLATION)",
                None,
            ),
            ("503 Service Unavailable", None),
        ] {
            assert_eq!(
                ResourceError::classify(&bad_response(message)),
                expected,
                "{message}"
            );
        }
        assert_eq!(
            ResourceError::classify(&Wrapper(clickhouse::error::Error::TimedOut)),
            None
        );
    }
}
