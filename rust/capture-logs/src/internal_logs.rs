//! Lets an internal PostHog service send logs that the logs consumer stores outside billing.
//!
//! The caller proves itself with a static key. This service then signs the Kafka batch, because
//! only this service sees the final payload bytes. The consumer verifies that signature against
//! the team it resolves from the token, so a caller that claims another team gets billed as normal.

use std::sync::Arc;

use axum::http::HeaderMap;
use hmac::{Hmac, Mac};
use metrics::counter;
use sha2::{Digest, Sha256};

type HmacSha256 = Hmac<Sha256>;

pub const CALLER_KEY_HEADER: &str = "x-posthog-internal-key";
pub const SOURCE_HEADER: &str = "x-posthog-internal-source";
pub const TEAM_ID_HEADER: &str = "x-posthog-internal-team-id";
pub const SIGNATURE_KAFKA_HEADER: &str = "posthog-internal";

// Must match `computeSignature` in `nodejs/src/logs/internal-logs.ts`.
const SIGNATURE_VERSION: &str = "v1";
const OUTCOME_COUNTER: &str = "capture_logs_internal_requests_total";

/// A verified internal request. Signing needs the payload, which exists only after the batch is encoded.
#[derive(Clone, Debug)]
pub struct InternalBatch {
    source: String,
    team_id: u64,
    signing_key: Arc<str>,
}

impl InternalBatch {
    pub fn sign(&self, payload: &[u8]) -> String {
        let payload_sha256 = hex::encode(Sha256::digest(payload));
        let mut mac = HmacSha256::new_from_slice(self.signing_key.as_bytes())
            .expect("hmac accepts any key length");
        mac.update(
            format!(
                "{SIGNATURE_VERSION}|{}|{}|{payload_sha256}",
                self.source, self.team_id
            )
            .as_bytes(),
        );
        format!(
            "{SIGNATURE_VERSION}.{}.{}",
            self.source,
            hex::encode(mac.finalize().into_bytes())
        )
    }
}

#[derive(Clone, Default)]
pub struct InternalLogsSigner {
    caller_key_digests: Vec<[u8; 32]>,
    signing_key: Option<Arc<str>>,
}

impl InternalLogsSigner {
    /// Both lists are comma-separated, newest first. An empty list turns the feature off.
    pub fn new(caller_keys: &str, signing_keys: &str) -> Self {
        Self {
            caller_key_digests: parse_keys(caller_keys)
                .map(|key| Sha256::digest(key.as_bytes()).into())
                .collect(),
            signing_key: parse_keys(signing_keys).next().map(Arc::from),
        }
    }

    /// `None` for an ordinary customer request, and for an internal request that fails a check.
    /// A failed check never rejects the request, so the logs still arrive and are billed as normal.
    pub fn claim(&self, headers: &HeaderMap) -> Option<InternalBatch> {
        let caller_key = header(headers, CALLER_KEY_HEADER)?;
        match self.check(caller_key, headers) {
            Ok(batch) => {
                counter!(OUTCOME_COUNTER, "outcome" => "accepted", "reason" => "").increment(1);
                Some(batch)
            }
            Err(reason) => {
                counter!(OUTCOME_COUNTER, "outcome" => "rejected", "reason" => reason).increment(1);
                None
            }
        }
    }

    fn check(&self, caller_key: &str, headers: &HeaderMap) -> Result<InternalBatch, &'static str> {
        let signing_key = match &self.signing_key {
            Some(key) if !self.caller_key_digests.is_empty() => key.clone(),
            _ => return Err("not_configured"),
        };
        let digest: [u8; 32] = Sha256::digest(caller_key.as_bytes()).into();
        // Every key is compared, so a rotation can add a key before callers switch to it.
        if !self
            .caller_key_digests
            .iter()
            .any(|known| constant_time_eq(known, &digest))
        {
            return Err("invalid_key");
        }
        let source = header(headers, SOURCE_HEADER)
            .filter(|source| is_valid_source(source))
            .ok_or("invalid_source")?;
        let team_id = header(headers, TEAM_ID_HEADER)
            .and_then(|value| value.parse::<u64>().ok())
            .ok_or("invalid_team_id")?;
        Ok(InternalBatch {
            source: source.to_string(),
            team_id,
            signing_key,
        })
    }
}

fn parse_keys(comma_separated: &str) -> impl Iterator<Item = &str> {
    comma_separated
        .split(',')
        .map(str::trim)
        .filter(|key| !key.is_empty())
}

fn header<'a>(headers: &'a HeaderMap, name: &str) -> Option<&'a str> {
    headers.get(name)?.to_str().ok()
}

// The source is the second dot-separated part of the signature, so it cannot hold a dot.
fn is_valid_source(source: &str) -> bool {
    (1..=64).contains(&source.len())
        && source
            .bytes()
            .all(|b| b.is_ascii_lowercase() || b.is_ascii_digit() || b == b'_')
}

fn constant_time_eq(a: &[u8; 32], b: &[u8; 32]) -> bool {
    a.iter().zip(b).fold(0u8, |acc, (x, y)| acc | (x ^ y)) == 0
}

#[cfg(test)]
mod tests {
    use super::*;
    use axum::http::HeaderValue;

    const CALLER_KEY: &str = "caller-key";
    const SIGNING_KEY: &str = "internal-logs-test-key";

    fn headers(pairs: &[(&'static str, &str)]) -> HeaderMap {
        let mut map = HeaderMap::new();
        for (name, value) in pairs {
            map.insert(*name, HeaderValue::from_str(value).unwrap());
        }
        map
    }

    fn internal_headers() -> Vec<(&'static str, &'static str)> {
        vec![
            (CALLER_KEY_HEADER, CALLER_KEY),
            (SOURCE_HEADER, "hog_flow"),
            (TEAM_ID_HEADER, "2"),
        ]
    }

    // The same vector is pinned in `nodejs/src/logs/internal-logs.test.ts`, so a format change on
    // either side fails a test.
    #[test]
    fn signs_with_the_newest_key_in_the_format_the_consumer_verifies() {
        let signer = InternalLogsSigner::new(CALLER_KEY, &format!("{SIGNING_KEY},old-key"));
        let batch = signer.claim(&headers(&internal_headers())).unwrap();
        assert_eq!(
            batch.sign(b"avro container bytes"),
            "v1.hog_flow.b97466e15a9bf1a2658e8d92e5f63ed60df91bd4e838e4ab4426cbb5280d2055"
        );
    }

    #[test]
    fn accepts_an_older_caller_key_during_rotation() {
        let signer = InternalLogsSigner::new(&format!("new-key,{CALLER_KEY}"), SIGNING_KEY);
        assert!(signer.claim(&headers(&internal_headers())).is_some());
    }

    type FailedCheck = (
        &'static str,
        InternalLogsSigner,
        Vec<(&'static str, &'static str)>,
    );

    #[test]
    fn treats_a_request_as_billed_when_a_check_fails() {
        let cases: Vec<FailedCheck> = vec![
            (
                "no caller key",
                InternalLogsSigner::new(CALLER_KEY, SIGNING_KEY),
                vec![(SOURCE_HEADER, "hog_flow"), (TEAM_ID_HEADER, "2")],
            ),
            (
                "a wrong caller key",
                InternalLogsSigner::new("another-key", SIGNING_KEY),
                internal_headers(),
            ),
            (
                "no caller keys configured",
                InternalLogsSigner::new("", SIGNING_KEY),
                internal_headers(),
            ),
            (
                "no signing key configured",
                InternalLogsSigner::new(CALLER_KEY, ""),
                internal_headers(),
            ),
            (
                "a source with a dot",
                InternalLogsSigner::new(CALLER_KEY, SIGNING_KEY),
                vec![
                    (CALLER_KEY_HEADER, CALLER_KEY),
                    (SOURCE_HEADER, "hog.flow"),
                    (TEAM_ID_HEADER, "2"),
                ],
            ),
            (
                "no source",
                InternalLogsSigner::new(CALLER_KEY, SIGNING_KEY),
                vec![(CALLER_KEY_HEADER, CALLER_KEY), (TEAM_ID_HEADER, "2")],
            ),
            (
                "a non-numeric team id",
                InternalLogsSigner::new(CALLER_KEY, SIGNING_KEY),
                vec![
                    (CALLER_KEY_HEADER, CALLER_KEY),
                    (SOURCE_HEADER, "hog_flow"),
                    (TEAM_ID_HEADER, "two"),
                ],
            ),
        ];
        for (name, signer, pairs) in cases {
            assert!(signer.claim(&headers(&pairs)).is_none(), "{name}");
        }
    }
}
