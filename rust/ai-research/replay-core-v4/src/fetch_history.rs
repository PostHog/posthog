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

/// The prefix of the image packs the fetcher writes to `images-v4`.
pub const URL_PACK_PREFIX: &str = "images/url/packs/";

/// `Number.MAX_SAFE_INTEGER`: the fetcher writes these numbers from JavaScript.
const MAX_SAFE_INTEGER: f64 = 9_007_199_254_740_991.0;

#[derive(Debug, Clone, PartialEq)]
pub struct UrlHistory {
    pub next_fetch_at_ms: f64,
    pub stored_at_ms: Option<f64>,
    /// `None` when the stored copy is the one object of its reference.
    pub pack: Option<PackedCopy>,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct PackedCopy {
    pub key: String,
    /// Inclusive byte range of the sealed frame in the pack.
    pub byte_start: u64,
    pub byte_end: u64,
    pub mime: String,
    pub byte_size: u64,
}

impl UrlHistory {
    /// Parses the `value` attribute of the crawl history row `key`. `None` is a row that the fetcher reads as a miss.
    ///
    /// A `pack` names the copy that its own `storedAtMs` describes. A writer that does not know the field can keep it
    /// while it sets a new `storedAtMs` for a copy elsewhere, so a pack with another time is not this row's copy.
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
        let stored_at_ms = number("storedAtMs");
        let pack = match value.get("pack") {
            None => None,
            Some(pack) => {
                let (copy, packed_at_ms) = packed_copy(pack)?;
                (Some(packed_at_ms) == stored_at_ms).then_some(copy)
            }
        };
        Some(Self {
            next_fetch_at_ms: number("nextFetchAtMs")?,
            stored_at_ms,
            pack,
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

/// The pack and the time it was written, or `None` for a malformed `pack`, which makes the whole row a miss.
fn packed_copy(pack: &Value) -> Option<(PackedCopy, f64)> {
    let count = |field: &str| {
        let number = pack.get(field)?.as_f64()?;
        (number.fract() == 0.0 && (0.0..=MAX_SAFE_INTEGER).contains(&number))
            .then_some(number as u64)
    };
    let key = pack.get("key")?.as_str()?;
    let names_a_pack = key.strip_prefix(URL_PACK_PREFIX).is_some_and(|rest| {
        !rest.is_empty()
            && rest
                .split('/')
                .all(|part| !part.is_empty() && part != "." && part != "..")
    });
    let (byte_start, byte_end, byte_size) =
        (count("byteStart")?, count("byteEnd")?, count("byteSize")?);
    let mime = pack.get("mime")?.as_str()?;
    let stored_at_ms = pack.get("storedAtMs")?.as_f64()?;
    if !names_a_pack || byte_end < byte_start || mime.is_empty() {
        return None;
    }
    Some((
        PackedCopy {
            key: key.to_owned(),
            byte_start,
            byte_end,
            mime: mime.to_owned(),
            byte_size,
        },
        stored_at_ms,
    ))
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
                pack: None,
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
                pack: None,
            })
        );
        let pack = json!({
            "key": "images/url/packs/dt=2026-10-14/7/1792000000000-00000000000000aa",
            "byteStart": 10,
            "byteEnd": 99,
            "mime": "image/png",
            "byteSize": 40,
            "storedAtMs": 1_792_000_000_000i64,
        });
        let packed = |field: &str, value: Value| {
            let mut changed = pack.clone();
            changed[field] = value;
            with("pack", changed)
        };
        assert_eq!(
            UrlHistory::parse(key, &with("pack", pack.clone())).and_then(|history| history.pack),
            Some(PackedCopy {
                key: "images/url/packs/dt=2026-10-14/7/1792000000000-00000000000000aa".to_owned(),
                byte_start: 10,
                byte_end: 99,
                mime: "image/png".to_owned(),
                byte_size: 40,
            })
        );
        // A writer that does not know `pack` moved `storedAtMs` to a copy elsewhere.
        let elsewhere =
            UrlHistory::parse(key, &packed("storedAtMs", json!(1_792_000_000_001i64))).unwrap();
        assert_eq!(elsewhere.pack, None);
        assert_eq!(elsewhere.stored_at_ms, Some(1_792_000_000_000.0));
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
            with("pack", json!("images/url/packs/dt=2026-10-14/7/1")),
            packed(
                "key",
                json!("images/url/month=2026-10/7/AAAAAAAAAAAAAAAAAAAAAA"),
            ),
            packed("key", json!("images/url/packs/../packs/7/1")),
            packed("byteEnd", json!(9)),
            packed("byteStart", json!(-1)),
            packed("byteSize", json!(1.5)),
            packed("mime", json!("")),
            packed("storedAtMs", Value::Null),
        ] {
            assert_eq!(UrlHistory::parse(key, &value), None, "{value}");
        }
    }
}
