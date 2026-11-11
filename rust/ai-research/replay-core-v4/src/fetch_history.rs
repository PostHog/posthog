//! The image fetcher's crawl history entry for a reference, and what the fetcher does with a job for it. The fetcher
//! calls this through `replay-core-v4-node` and the recorder calls it directly, so both drop the same jobs.

use serde_json::Value;

/// The `images-v4` lifecycle is 98 days: the 90-day raw window plus this interval and one day.
pub const REFRESH_INTERVAL_MS: f64 = 7.0 * 24.0 * 3600.0 * 1000.0;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum UrlJob {
    Drop,
    Refresh,
    Fetch,
}

impl UrlJob {
    pub fn label(self) -> &'static str {
        match self {
            UrlJob::Drop => "drop",
            UrlJob::Refresh => "refresh",
            UrlJob::Fetch => "fetch",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq)]
pub struct UrlHistory {
    pub next_fetch_at_ms: f64,
    pub stored_at_ms: Option<f64>,
}

impl UrlHistory {
    /// Parses the `value` attribute of the crawl history row `key`. `None` is a row that the fetcher reads as a miss.
    pub fn parse(key: &str, value: &str) -> Option<Self> {
        let value: Value = serde_json::from_str(value).ok()?;
        let number = |field: &str| value.get(field).and_then(Value::as_f64);
        let valid = value.get("kind").and_then(Value::as_str) == Some("url")
            && value.get("key").and_then(Value::as_str) == Some(key)
            && value.get("outcome").is_some_and(Value::is_string)
            && number("storageExpiresAtMs").is_some()
            && value.get("cache").is_none_or(is_http_cache)
            && value.get("storedAtMs").is_none_or(Value::is_number)
            && value.get("_bodyChunks").is_none();
        if !valid {
            return None;
        }
        Some(Self {
            next_fetch_at_ms: number("nextFetchAtMs")?,
            stored_at_ms: number("storedAtMs"),
        })
    }

    pub fn job_at(&self, at_ms: f64) -> UrlJob {
        let refresh_due = self
            .stored_at_ms
            .is_some_and(|stored_at_ms| at_ms - stored_at_ms >= REFRESH_INTERVAL_MS);
        if self.next_fetch_at_ms > at_ms {
            if refresh_due {
                UrlJob::Refresh
            } else {
                UrlJob::Drop
            }
        } else {
            UrlJob::Fetch
        }
    }
}

fn is_http_cache(cache: &Value) -> bool {
    const TEXT_FIELDS: [&str; 8] = [
        "responseUrlHmac",
        "responseUrl",
        "etag",
        "lastModified",
        "date",
        "age",
        "cacheControl",
        "expires",
    ];
    cache.get("requestTimeMs").is_some_and(Value::is_number)
        && cache.get("responseTimeMs").is_some_and(Value::is_number)
        && TEXT_FIELDS
            .iter()
            .all(|field| cache.get(field).is_none_or(Value::is_string))
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    const NOW_MS: f64 = 1_794_000_000_000.0;
    const DAY_MS: f64 = 24.0 * 3600.0 * 1000.0;

    #[test]
    fn decides_each_job_as_the_fetcher_does() {
        for (name, next_fetch_in_ms, stored_ago_ms, job) in [
            (
                "a copy one day old",
                20.0 * DAY_MS,
                Some(DAY_MS),
                UrlJob::Drop,
            ),
            ("no stored copy", 20.0 * DAY_MS, None, UrlJob::Drop),
            (
                "a copy 1 ms younger than 7 days",
                20.0 * DAY_MS,
                Some(7.0 * DAY_MS - 1.0),
                UrlJob::Drop,
            ),
            (
                "a copy 7 days old",
                20.0 * DAY_MS,
                Some(7.0 * DAY_MS),
                UrlJob::Refresh,
            ),
            ("its refetch time", 0.0, Some(DAY_MS), UrlJob::Fetch),
            (
                "an old copy past its refetch time",
                -1.0,
                Some(14.0 * DAY_MS),
                UrlJob::Fetch,
            ),
        ] {
            let history = UrlHistory {
                next_fetch_at_ms: NOW_MS + next_fetch_in_ms,
                stored_at_ms: stored_ago_ms.map(|ago_ms| NOW_MS - ago_ms),
            };
            assert_eq!(history.job_at(NOW_MS), job, "{name}");
        }
    }

    #[test]
    fn parses_only_url_entries_the_fetcher_accepts_for_their_key() {
        let key = "imageurl:v4:7:2026-10:AAAAAAAAAAAAAAAAAAAAAA";
        let entry = json!({
            "kind": "url",
            "key": key,
            "nextFetchAtMs": 1_795_000_000_000i64,
            "storageExpiresAtMs": 1_794_000_000_000i64,
            "outcome": "ok",
            "cache": {"requestTimeMs": 1, "responseTimeMs": 2, "etag": "\"x\""},
            "storedAtMs": 1_792_000_000_000i64,
        });
        let with = |field: &str, value: Value| {
            let mut changed = entry.clone();
            changed[field] = value;
            changed.to_string()
        };
        let without = |field: &str| {
            let mut changed = entry.clone();
            changed.as_object_mut().unwrap().remove(field);
            changed.to_string()
        };

        assert_eq!(
            UrlHistory::parse(key, &entry.to_string()),
            Some(UrlHistory {
                next_fetch_at_ms: 1_795_000_000_000.0,
                stored_at_ms: Some(1_792_000_000_000.0),
            })
        );
        assert_eq!(
            UrlHistory::parse(key, &without("cache")).map(|history| history.next_fetch_at_ms),
            Some(1_795_000_000_000.0)
        );
        for value in [
            "{\"kind\":\"url\",".to_owned(),
            with("kind", json!("robots")),
            with("key", json!("imageurl:v4:7:2026-10:other")),
            without("nextFetchAtMs"),
            without("outcome"),
            without("storageExpiresAtMs"),
            with("storedAtMs", Value::Null),
            with("cache", json!({"requestTimeMs": 1})),
            with(
                "cache",
                json!({"requestTimeMs": 1, "responseTimeMs": 2, "etag": null}),
            ),
            with("_bodyChunks", json!({"count": 1, "sha256": "0".repeat(64)})),
        ] {
            assert_eq!(UrlHistory::parse(key, &value), None, "{value}");
        }
    }
}
