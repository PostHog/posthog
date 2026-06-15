use crate::flags::flag_request::FlagRequestType;
use crate::handler::types::Library;
use std::time::{SystemTime, UNIX_EPOCH};

pub const SURVEY_TARGETING_FLAG_PREFIX: &str = "survey-targeting-";
pub const PRODUCT_TOUR_TARGETING_FLAG_PREFIX: &str = "product-tour-targeting-";

pub fn is_billable_flag_key(key: &str) -> bool {
    !key.starts_with(SURVEY_TARGETING_FLAG_PREFIX)
        && !key.starts_with(PRODUCT_TOUR_TARGETING_FLAG_PREFIX)
}

pub const CACHE_BUCKET_SIZE: u64 = 60 * 2; // duration in seconds

/// Current 2-minute bucket, expressed as `unix_seconds / CACHE_BUCKET_SIZE`.
pub fn current_bucket() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map(|d| d.as_secs() / CACHE_BUCKET_SIZE)
        .unwrap_or(0)
}

pub fn get_team_request_key(team_id: i32, request_type: FlagRequestType) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:{team_id}"),
        FlagRequestType::FlagDefinitions => format!("posthog:local_evaluation_requests:{team_id}"),
    }
}

pub fn get_team_request_library_key(
    team_id: i32,
    request_type: FlagRequestType,
    library: Library,
) -> String {
    match request_type {
        FlagRequestType::Decide => format!("posthog:decide_requests:sdk:{team_id}:{library}"),
        FlagRequestType::FlagDefinitions => {
            format!("posthog:local_evaluation_requests:sdk:{team_id}:{library}")
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[tokio::test]
    async fn test_get_team_request_key() {
        assert_eq!(
            get_team_request_key(123, FlagRequestType::Decide),
            "posthog:decide_requests:123"
        );
        assert_eq!(
            get_team_request_key(456, FlagRequestType::FlagDefinitions),
            "posthog:local_evaluation_requests:456"
        );
    }

    #[tokio::test]
    async fn test_get_team_request_library_key() {
        assert_eq!(
            get_team_request_library_key(123, FlagRequestType::Decide, Library::PosthogNode),
            "posthog:decide_requests:sdk:123:posthog-node"
        );
        assert_eq!(
            get_team_request_library_key(456, FlagRequestType::FlagDefinitions, Library::PosthogJs),
            "posthog:local_evaluation_requests:sdk:456:posthog-js"
        );
        assert_eq!(
            get_team_request_library_key(789, FlagRequestType::Decide, Library::PosthogAndroid),
            "posthog:decide_requests:sdk:789:posthog-android"
        );
        // Test new SDK variants
        assert_eq!(
            get_team_request_library_key(100, FlagRequestType::Decide, Library::PosthogDotnet),
            "posthog:decide_requests:sdk:100:posthog-dotnet"
        );
        assert_eq!(
            get_team_request_library_key(
                101,
                FlagRequestType::FlagDefinitions,
                Library::PosthogElixir
            ),
            "posthog:local_evaluation_requests:sdk:101:posthog-elixir"
        );
        // Test Other variant
        assert_eq!(
            get_team_request_library_key(102, FlagRequestType::Decide, Library::Other),
            "posthog:decide_requests:sdk:102:other"
        );
    }
}
