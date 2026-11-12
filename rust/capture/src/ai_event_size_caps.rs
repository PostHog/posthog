use std::collections::HashMap;
use std::sync::Arc;

use tracing::{info, warn};

use crate::ai_event_limits::AI_MAX_EVENT_BYTES_OVERRIDES;

/// The largest AI event each project token may send.
#[derive(Clone, Debug, Default)]
pub struct AiEventSizeCaps {
    default: u64,
    by_token: Arc<HashMap<String, u64>>,
}

impl From<u64> for AiEventSizeCaps {
    fn from(default: u64) -> Self {
        Self {
            default,
            by_token: Arc::default(),
        }
    }
}

impl AiEventSizeCaps {
    /// Skips and logs any entry that is invalid or would not raise `default`,
    /// so one bad entry cannot stop capture from booting.
    pub fn parse(default: u64, by_token: &str, ceiling: u64) -> Self {
        let mut caps = HashMap::new();
        for entry in by_token.split(',').map(str::trim).filter(|e| !e.is_empty()) {
            match parse_entry(entry, default, ceiling) {
                Ok((token, bytes)) => {
                    caps.insert(token.to_string(), bytes);
                }
                Err(reason) => {
                    warn!(
                        entry,
                        reason, "skipping an AI_MAX_EVENT_BYTES_BY_TOKEN entry"
                    )
                }
            }
        }
        if !caps.is_empty() {
            info!(
                tokens = caps.len(),
                "AI event size cap raised for listed tokens"
            );
        }
        Self {
            default,
            by_token: Arc::new(caps),
        }
    }

    pub fn default_bytes(&self) -> u64 {
        self.default
    }

    pub fn for_token(&self, token: &str) -> u64 {
        self.by_token.get(token).copied().unwrap_or(self.default)
    }
}

fn parse_entry(entry: &str, default: u64, ceiling: u64) -> Result<(&str, u64), &'static str> {
    let (token, bytes) = entry.split_once('=').ok_or("expected token=bytes")?;
    let token = token.trim();
    if token.is_empty() {
        return Err("empty token");
    }
    let bytes: u64 = bytes
        .trim()
        .parse()
        .map_err(|_| "bytes is not an integer")?;
    if !AI_MAX_EVENT_BYTES_OVERRIDES.contains(&bytes) {
        return Err("bytes is not one of the shared override options");
    }
    if default == 0 {
        return Err("the default cap is disabled");
    }
    let bytes = bytes.min(ceiling);
    if bytes <= default {
        return Err("it would not raise the default cap");
    }
    Ok((token, bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    const DEFAULT: u64 = 8_388_608;
    const CEILING: u64 = 48_000_000;

    #[rstest]
    #[case::raises_a_listed_token("phc_big=24000000", "phc_big", 24_000_000)]
    #[case::other_tokens_keep_the_default("phc_big=24000000", "phc_other", DEFAULT)]
    #[case::trims_and_skips_empty_entries(" , phc_big = 48000000 ,", "phc_big", 48_000_000)]
    #[case::not_an_option_is_skipped("phc_big=30000000", "phc_big", DEFAULT)]
    #[case::not_an_integer_is_skipped("phc_big=24MB", "phc_big", DEFAULT)]
    #[case::missing_separator_is_skipped("phc_big", "phc_big", DEFAULT)]
    #[case::a_bad_entry_keeps_the_good_ones("phc_bad=1,phc_big=24000000", "phc_big", 24_000_000)]
    fn caps_come_from_valid_entries_only(
        #[case] by_token: &str,
        #[case] token: &str,
        #[case] expected: u64,
    ) {
        let caps = AiEventSizeCaps::parse(DEFAULT, by_token, CEILING);

        assert_eq!(caps.for_token(token), expected);
    }

    #[rstest]
    #[case::lowered_to_the_ceiling(DEFAULT, 30_000_000, 30_000_000)]
    #[case::skipped_when_the_ceiling_does_not_raise_the_default(DEFAULT, 1_000_000, DEFAULT)]
    #[case::skipped_when_the_default_is_disabled(0, CEILING, 0)]
    fn caps_stay_between_the_default_and_the_ceiling(
        #[case] default: u64,
        #[case] ceiling: u64,
        #[case] expected: u64,
    ) {
        let caps = AiEventSizeCaps::parse(default, "phc_big=48000000", ceiling);

        assert_eq!(caps.for_token("phc_big"), expected);
    }
}
