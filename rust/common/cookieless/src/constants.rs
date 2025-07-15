// Constants shared between Rust and TypeScript implementations
use chrono_tz::Tz;

// String constants
pub const COOKIELESS_SENTINEL_VALUE: &str = "$posthog_cookieless";
pub const COOKIELESS_DISTINCT_ID_PREFIX: &str = "cookieless";
pub const COOKIELESS_MODE_FLAG_PROPERTY: &str = "$cookieless_mode";
pub const COOKIELESS_EXTRA_HASH_CONTENTS_PROPERTY: &str = "$cookieless_extra";
pub const TIMEZONE_FALLBACK: Tz = Tz::UTC;

// Timezone constants
pub const MAX_NEGATIVE_TIMEZONE_HOURS: i32 = 12; // Baker Island, Howland Island (UTC-12)
pub const MAX_POSITIVE_TIMEZONE_HOURS: i32 = 14; // Line Islands (UTC+14)

// Time constants
pub const SALT_TTL_SECONDS: u64 = 60 * 60 * 24; // 24 hours
pub const SESSION_TTL_SECONDS: u64 = 60 * 60 * 24; // 24 hours
pub const SESSION_INACTIVITY_MS: u64 = 30 * 60 * 1000; // 30 minutes
const IDENTIFIES_TTL_HOURS: u64 = (24 // Time salt is valid within the same time zone
    + 24 // Max supported ingestion lag (hours)
    + MAX_NEGATIVE_TIMEZONE_HOURS
    + MAX_POSITIVE_TIMEZONE_HOURS) as u64;
pub const IDENTIFIES_TTL_SECONDS: u64 = IDENTIFIES_TTL_HOURS * (60 * 60);
