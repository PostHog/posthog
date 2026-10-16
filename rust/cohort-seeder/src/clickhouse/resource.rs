//! Classifies a failed scan by the ClickHouse error behind it, for the run breaker.

use std::error::Error;
use std::io;

/// What the crate reports for a `500` whose body mixes buffered rows with the exception, which is
/// how ClickHouse answers a query that fails after its first rows but before it sends the headers.
const UNREADABLE_SERVER_ERROR: &str = "500 Internal Server Error";

/// A ClickHouse error meaning the query did not fit the server's resources.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResourceError {
    /// Also raised when the overcommit tracker stops the query to free memory for others.
    MemoryLimitExceeded,
    TimeoutExceeded,
    TooSlow,
    TooManySimultaneousQueries,
    /// The query failed after ClickHouse started the response, so the client never reads the error
    /// code. It counts, because the memory and time limits stop a scan mid-stream and the client
    /// cannot tell them from another server error there.
    ResponseCut,
}

impl ResourceError {
    pub const ALL: [Self; 5] = [
        Self::MemoryLimitExceeded,
        Self::TimeoutExceeded,
        Self::TooSlow,
        Self::TooManySimultaneousQueries,
        Self::ResponseCut,
    ];

    pub const fn as_str(self) -> &'static str {
        match self {
            Self::MemoryLimitExceeded => "241",
            Self::TimeoutExceeded => "159",
            Self::TooSlow => "160",
            Self::TooManySimultaneousQueries => "202",
            Self::ResponseCut => "response_cut",
        }
    }

    fn from_code(code: u32) -> Option<Self> {
        match code {
            241 => Some(Self::MemoryLimitExceeded),
            159 => Some(Self::TimeoutExceeded),
            160 => Some(Self::TooSlow),
            202 => Some(Self::TooManySimultaneousQueries),
            _ => None,
        }
    }

    /// Walks the source chain, because the chunk pipeline wraps the `clickhouse` crate's error.
    pub fn classify(error: &(dyn Error + 'static)) -> Option<Self> {
        let mut current = Some(error);
        while let Some(error) = current {
            if let Some(error) = error.downcast_ref::<clickhouse::error::Error>() {
                return Self::from_clickhouse(error);
            }
            current = error.source();
        }
        None
    }

    fn from_clickhouse(error: &clickhouse::error::Error) -> Option<Self> {
        match error {
            clickhouse::error::Error::BadResponse(message)
                if message == UNREADABLE_SERVER_ERROR =>
            {
                Some(Self::ResponseCut)
            }
            clickhouse::error::Error::BadResponse(message) => {
                server_error_code(message).and_then(Self::from_code)
            }
            // Once the headers are out, ClickHouse ends the body early instead.
            clickhouse::error::Error::Network(source) => {
                ends_early(source.as_ref()).then_some(Self::ResponseCut)
            }
            _ => None,
        }
    }
}

/// The crate reports a server exception raised before the response starts as `BadResponse` text
/// starting `Code: <n>.`.
fn server_error_code(message: &str) -> Option<u32> {
    let rest = message.trim_start().strip_prefix("Code:")?.trim_start();
    let digits = rest
        .find(|character: char| !character.is_ascii_digit())
        .map_or(rest, |end| &rest[..end]);
    digits.parse().ok()
}

/// A refused or reset connection is not a cut response, so only an early end of the body counts.
fn ends_early(error: &(dyn Error + 'static)) -> bool {
    let mut current = Some(error);
    while let Some(error) = current {
        if error
            .downcast_ref::<io::Error>()
            .is_some_and(|error| error.kind() == io::ErrorKind::UnexpectedEof)
        {
            return true;
        }
        current = error.source();
    }
    false
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::clickhouse::ScanError;

    fn bad_response(message: &str) -> ScanError {
        ScanError::Cursor(clickhouse::error::Error::BadResponse(message.to_owned()))
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
            ("500 Internal Server Error", Some(ResourceError::ResponseCut)),
            ("503 Service Unavailable", None),
        ] {
            assert_eq!(
                ResourceError::classify(&bad_response(message)),
                expected,
                "{message}"
            );
        }
        assert_eq!(
            ResourceError::classify(&ScanError::Cursor(clickhouse::error::Error::TimedOut)),
            None
        );
        for (kind, expected) in [
            (
                io::ErrorKind::UnexpectedEof,
                Some(ResourceError::ResponseCut),
            ),
            (io::ErrorKind::ConnectionRefused, None),
        ] {
            let network = clickhouse::error::Error::Network(Box::new(io::Error::new(kind, "body")));
            assert_eq!(
                ResourceError::classify(&ScanError::Cursor(network)),
                expected,
                "{kind:?}"
            );
        }
    }
}
