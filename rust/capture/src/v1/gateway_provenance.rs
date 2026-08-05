// AI-gateway provenance verification.
//
// The gateway bills a customer's LLM calls against a prepaid wallet and posts an
// `$ai_generation` per call through capture, so those events must be excluded from
// the team's billable AIO usage. The `$ai_gateway*` properties are client-settable
// and untrusted, so the gateway HMAC-signs each event and capture verifies here,
// before the llm_events limiter: a valid, fresh signature stamps a trusted
// `$ai_gateway_verified` and exempts the event; anything else has the whole
// `$ai_gateway*` namespace stripped so a forged marker can't survive.

use axum::http::HeaderMap;
use chrono::{DateTime, Duration, Utc};
use hmac::{Hmac, Mac};
use serde_json::value::RawValue;
use serde_json::{Map, Value};
use sha2::Sha256;

use super::constants::{
    POSTHOG_AI_GATEWAY_REQUEST_ID, POSTHOG_AI_GATEWAY_SIGNATURE, POSTHOG_AI_GATEWAY_SIGNED_AT,
};

type HmacSha256 = Hmac<Sha256>;

const GATEWAY_PREFIX: &str = "$ai_gateway";
pub const VERIFIED_PROPERTY: &str = "$ai_gateway_verified";

/// Stamped from the signed header (not the client value) so billing can dedup
/// exemptions by it.
const REQUEST_ID_PROPERTY: &str = "$ai_gateway_request_id";

/// Counter on every event-mutating provenance decision, labelled by `reason`
/// (`verified`/`stale`/`forged`) so forgery and clock skew are alertable.
pub const PROVENANCE_METRIC: &str = "capture_v1_gateway_provenance";

/// JSON-key form of `GATEWAY_PREFIX` (leading quote, no escapes) for the fast-path
/// scan. The static assert below pins it to `GATEWAY_PREFIX` so it can't drift.
const GATEWAY_KEY_NEEDLE: &str = "\"$ai_gateway";
const _: () = assert!(
    {
        let needle = GATEWAY_KEY_NEEDLE.as_bytes();
        let prefix = GATEWAY_PREFIX.as_bytes();
        let mut ok = needle.len() == prefix.len() + 1 && needle[0] == b'"';
        let mut i = 0;
        while i < prefix.len() {
            ok = ok && needle[i + 1] == prefix[i];
            i += 1;
        }
        ok
    },
    "GATEWAY_KEY_NEEDLE must be a quote followed by GATEWAY_PREFIX"
);

/// How far `signed_at` may sit from capture's receive time. Capture stamps the
/// event (no ingestion lag), so the window only absorbs gateway/capture clock skew.
pub const FRESHNESS_WINDOW_SECS: i64 = 5 * 60;

/// The provenance signature carried on the request headers.
#[derive(Debug, Clone)]
pub struct GatewaySignature {
    pub signature: String,
    pub signed_at: String,
    pub request_id: String,
}

/// Reads the provenance headers. `None` unless both signature and signed_at are
/// present; `request_id` defaults to empty when absent (untrusted downstream).
pub fn parse_signature(headers: &HeaderMap) -> Option<GatewaySignature> {
    Some(GatewaySignature {
        signature: header_str(headers, POSTHOG_AI_GATEWAY_SIGNATURE)?,
        signed_at: header_str(headers, POSTHOG_AI_GATEWAY_SIGNED_AT)?,
        request_id: header_str(headers, POSTHOG_AI_GATEWAY_REQUEST_ID).unwrap_or_default(),
    })
}

fn header_str(headers: &HeaderMap, name: &str) -> Option<String> {
    headers.get(name)?.to_str().ok().map(str::to_owned)
}

/// Outcome of checking a gateway signature, so callers can tell a forgery
/// (`Invalid`) from clock skew (`Stale`) for metrics. Only `Verified` is trusted.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Provenance {
    /// Valid HMAC, signed within the freshness window.
    Verified,
    /// Valid HMAC, but `signed_at` is outside the freshness window (clock skew, or
    /// a signature replayed past its lifetime).
    Stale,
    /// HMAC mismatch, unparseable signature, or no signature at all.
    Invalid,
}

/// Verifies the HMAC over the gateway's canonical tuple, then checks freshness.
pub fn verify(
    secret: &[u8],
    token: &str,
    distinct_id: &str,
    sig: &GatewaySignature,
    now: DateTime<Utc>,
) -> Provenance {
    let message = canonical(&[token, distinct_id, &sig.request_id, &sig.signed_at]);
    if !verify_hmac(secret, &message, &sig.signature) {
        return Provenance::Invalid;
    }
    if is_fresh(&sig.signed_at, now) {
        Provenance::Verified
    } else {
        Provenance::Stale
    }
}

// Length-prefixed encoding: each field is its big-endian u32 length then its bytes.
// distinct_id is customer-controlled, so a delimiter wouldn't be injective;
// length-prefixing stops any field's content from shifting another's boundary. Must
// match the gateway signer byte-for-byte (ai-gateway internal/emitter/signer.go).
fn canonical(fields: &[&str]) -> Vec<u8> {
    let mut buf = Vec::with_capacity(fields.iter().map(|f| f.len() + 4).sum());
    for f in fields {
        buf.extend_from_slice(&(f.len() as u32).to_be_bytes());
        buf.extend_from_slice(f.as_bytes());
    }
    buf
}

// HMAC-SHA256 over the canonical message, signature as lowercase hex. Compared
// in constant time via `verify_slice`.
fn verify_hmac(secret: &[u8], message: &[u8], signature_hex: &str) -> bool {
    let Ok(expected) = hex::decode(signature_hex) else {
        return false;
    };
    let Ok(mut mac) = HmacSha256::new_from_slice(secret) else {
        return false;
    };
    mac.update(message);
    mac.verify_slice(&expected).is_ok()
}

fn is_fresh(signed_at: &str, now: DateTime<Utc>) -> bool {
    match DateTime::parse_from_rfc3339(signed_at) {
        Ok(t) => (now - t.with_timezone(&Utc)).abs() <= Duration::seconds(FRESHNESS_WINDOW_SECS),
        Err(_) => false,
    }
}

/// Stamps the trusted marker and the signed request_id, overwriting client values.
/// Other `$ai_gateway*` props rode a valid signature, so they survive.
pub fn stamp_verified(props: &mut Map<String, Value>, request_id: &str) {
    props.insert(VERIFIED_PROPERTY.to_string(), Value::Bool(true));
    props.insert(
        REQUEST_ID_PROPERTY.to_string(),
        Value::String(request_id.to_owned()),
    );
}

/// Removes the whole `$ai_gateway*` namespace so a forged marker can't reach billing.
pub fn strip_gateway(props: &mut Map<String, Value>) {
    props.retain(|k, _| !k.starts_with(GATEWAY_PREFIX));
}

/// Cheap raw-bytes pre-check: does the property object plausibly carry a
/// `$ai_gateway*` key? Lets the hot path skip the allocating parse for ordinary
/// `$ai_*` events. The literal prefix covers every legit event and unescaped client
/// value; only a JSON `\u` escape can hide the all-ASCII prefix, so with no `\u` the
/// substring scan is conclusive. With a `\u`, scan object keys only (never values),
/// so a value-side `\u` can't force the parse; a literal false-positive only wastes a parse.
pub fn has_gateway_props(properties: &RawValue) -> bool {
    let raw = properties.get();
    if raw.contains(GATEWAY_KEY_NEEDLE) {
        return true;
    }
    raw.contains("\\u") && scan_for_escaped_gateway_key(raw)
}

/// Single pass over a JSON object's bytes looking for an object key that decodes
/// to a string starting with `$ai_gateway`, without materializing any value. A
/// string token is a key iff the next non-whitespace byte is `:` — so a `\u`
/// escape inside a value is skipped over and never decoded.
fn scan_for_escaped_gateway_key(raw: &str) -> bool {
    let b = raw.as_bytes();
    let mut i = 0;
    while i < b.len() {
        if b[i] != b'"' {
            i += 1;
            continue;
        }
        // Find the closing quote, skipping escaped bytes (incl. `\uXXXX`).
        let start = i + 1;
        let mut j = start;
        let mut closed = false;
        while j < b.len() {
            match b[j] {
                b'\\' => j += 2,
                b'"' => {
                    closed = true;
                    break;
                }
                _ => j += 1,
            }
        }
        if !closed {
            return false; // unterminated string — malformed, nothing more to find
        }
        let mut k = j + 1;
        while k < b.len() && b[k].is_ascii_whitespace() {
            k += 1;
        }
        if k < b.len() && b[k] == b':' && key_starts_with_gateway(&b[start..j]) {
            return true;
        }
        i = j + 1;
    }
    false
}

/// Decodes the (possibly `\u`-escaped) key content just far enough to test the
/// `$ai_gateway` prefix. Any non-`\u` escape, or a `\u` codepoint outside ASCII,
/// can't be part of the all-ASCII prefix, so it's a mismatch.
fn key_starts_with_gateway(content: &[u8]) -> bool {
    let target = GATEWAY_PREFIX.as_bytes();
    let mut ti = 0;
    let mut i = 0;
    while ti < target.len() {
        if i >= content.len() {
            return false;
        }
        let (ch, next) = if content[i] == b'\\' {
            if content.get(i + 1) != Some(&b'u') || i + 6 > content.len() {
                return false;
            }
            match parse_hex4(&content[i + 2..i + 6]) {
                Some(cp) if cp <= 0x7f => (cp as u8, i + 6),
                _ => return false,
            }
        } else {
            (content[i], i + 1)
        };
        if ch != target[ti] {
            return false;
        }
        ti += 1;
        i = next;
    }
    true
}

fn parse_hex4(b: &[u8]) -> Option<u32> {
    let mut v = 0u32;
    for &c in b {
        let d = match c {
            b'0'..=b'9' => c - b'0',
            b'a'..=b'f' => c - b'a' + 10,
            b'A'..=b'F' => c - b'A' + 10,
            _ => return None,
        };
        v = v * 16 + d as u32;
    }
    Some(v)
}

/// Outcome of stripping the `$ai_gateway*` namespace from raw properties.
#[derive(Debug)]
pub enum StripOutcome {
    /// Stripped at least one key. `forged` is true if the trusted marker
    /// `$ai_gateway_verified` was among them — a client-supplied marker, since the
    /// gateway never sends it (capture stamps it post-verify), so always a forgery.
    Stripped { props: Box<RawValue>, forged: bool },
    /// Parsed fine, no `$ai_gateway*` key to strip (the raw pre-check matched a value).
    Unchanged,
    /// Couldn't parse the properties as an object. `RawValue` accepts JSON that the
    /// typed parse rejects (out-of-range numbers, over-deep nesting) and ClickHouse's
    /// reader is more lenient still, so a forged marker we can't strip could survive
    /// to billing. The caller must fail closed (drop the event).
    Unparseable,
}

pub fn strip_gateway_raw(properties: &RawValue) -> StripOutcome {
    let Ok(mut map) = serde_json::from_str::<Map<String, Value>>(properties.get()) else {
        return StripOutcome::Unparseable;
    };
    let forged = map.contains_key(VERIFIED_PROPERTY);
    let before = map.len();
    strip_gateway(&mut map);
    if map.len() == before {
        return StripOutcome::Unchanged;
    }
    match reserialize(map) {
        Some(props) => StripOutcome::Stripped { props, forged },
        None => StripOutcome::Unparseable,
    }
}

/// Stamps the trusted marker and signed request_id onto raw properties.
/// `Unparseable` (see [`StripOutcome::Unparseable`]) when the typed parse fails, so
/// the caller fails closed rather than passing an unstrippable forged marker through.
#[derive(Debug)]
pub enum StampOutcome {
    Stamped(Box<RawValue>),
    Unparseable,
}

pub fn stamp_verified_raw(properties: &RawValue, request_id: &str) -> StampOutcome {
    let Ok(mut map) = serde_json::from_str::<Map<String, Value>>(properties.get()) else {
        return StampOutcome::Unparseable;
    };
    stamp_verified(&mut map, request_id);
    match reserialize(map) {
        Some(props) => StampOutcome::Stamped(props),
        None => StampOutcome::Unparseable,
    }
}

fn reserialize(map: Map<String, Value>) -> Option<Box<RawValue>> {
    RawValue::from_string(serde_json::to_string(&Value::Object(map)).ok()?).ok()
}

/// Test-only signer: produces the hex HMAC the gateway would emit for this tuple,
/// so other modules' (and integration) tests can build signatures `verify` accepts.
#[cfg(any(test, feature = "test-utils"))]
pub fn sign_for_test(
    secret: &[u8],
    token: &str,
    distinct_id: &str,
    request_id: &str,
    signed_at: &str,
) -> String {
    let mut mac = HmacSha256::new_from_slice(secret).expect("hmac accepts any key length");
    mac.update(&canonical(&[token, distinct_id, request_id, signed_at]));
    hex::encode(mac.finalize().into_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;

    const SECRET: &[u8] = b"test-signing-secret";
    const TOKEN: &str = "phc_test";
    const DISTINCT_ID: &str = "user-7";

    fn sign(token: &str, distinct_id: &str, request_id: &str, signed_at: &str) -> String {
        sign_for_test(SECRET, token, distinct_id, request_id, signed_at)
    }

    fn now() -> DateTime<Utc> {
        "2026-05-28T10:00:00Z".parse().unwrap()
    }

    fn valid_sig(request_id: &str) -> GatewaySignature {
        let signed_at = "2026-05-28T10:00:00Z".to_string();
        GatewaySignature {
            signature: sign(TOKEN, DISTINCT_ID, request_id, &signed_at),
            signed_at,
            request_id: request_id.to_string(),
        }
    }

    #[test]
    fn verifies_a_valid_fresh_signature() {
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &valid_sig("req-1"), now()),
            Provenance::Verified
        );
    }

    #[test]
    fn verifies_with_an_empty_request_id() {
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &valid_sig(""), now()),
            Provenance::Verified
        );
    }

    #[test]
    fn rejects_a_tampered_distinct_id() {
        assert_eq!(
            verify(SECRET, TOKEN, "user-8", &valid_sig("req-1"), now()),
            Provenance::Invalid
        );
    }

    #[test]
    fn rejects_a_tampered_token() {
        assert_eq!(
            verify(SECRET, "phc_other", DISTINCT_ID, &valid_sig("req-1"), now()),
            Provenance::Invalid
        );
    }

    #[test]
    fn rejects_a_garbage_signature() {
        let mut sig = valid_sig("req-1");
        sig.signature = "deadbeef".to_string();
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Invalid
        );
    }

    #[test]
    fn rejects_a_non_hex_signature() {
        let mut sig = valid_sig("req-1");
        sig.signature = "not-hex".to_string();
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Invalid
        );
    }

    #[test]
    fn rejects_a_wrong_secret() {
        let signed_at = "2026-05-28T10:00:00Z".to_string();
        let mut mac = HmacSha256::new_from_slice(b"other-secret").unwrap();
        mac.update(&canonical(&[TOKEN, DISTINCT_ID, "req-1", &signed_at]));
        let sig = GatewaySignature {
            signature: hex::encode(mac.finalize().into_bytes()),
            signed_at,
            request_id: "req-1".to_string(),
        };
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Invalid
        );
    }

    #[test]
    fn distinct_id_cannot_shift_field_boundaries() {
        // A signature for (distinct_id="user", request_id="req") must NOT verify
        // when the boundary-shifting candidate (distinct_id="user\nreq",
        // request_id="") is presented. A delimiter join would collide here;
        // length-prefixing keeps the two encodings distinct.
        let signed_at = "2026-05-28T10:00:00Z".to_string();
        let signature = sign(TOKEN, "user", "req", &signed_at);
        let forged = GatewaySignature {
            signature,
            signed_at,
            request_id: String::new(),
        };
        assert_eq!(
            verify(SECRET, TOKEN, "user\nreq", &forged, now()),
            Provenance::Invalid
        );
    }

    #[test]
    fn rejects_a_stale_signature() {
        let stale = (now() - chrono::Duration::seconds(FRESHNESS_WINDOW_SECS + 1)).to_rfc3339();
        let sig = GatewaySignature {
            signature: sign(TOKEN, DISTINCT_ID, "req-1", &stale),
            signed_at: stale,
            request_id: "req-1".to_string(),
        };
        // Valid HMAC, but outside the window — clock skew, not forgery.
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Stale
        );
    }

    #[test]
    fn accepts_a_signature_at_the_window_edge() {
        let edge = (now() - chrono::Duration::seconds(FRESHNESS_WINDOW_SECS)).to_rfc3339();
        let sig = GatewaySignature {
            signature: sign(TOKEN, DISTINCT_ID, "req-1", &edge),
            signed_at: edge,
            request_id: "req-1".to_string(),
        };
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Verified
        );
    }

    #[test]
    fn accepts_a_future_signature_at_the_window_edge() {
        // Freshness is symmetric: a signed_at exactly +window in the future is
        // accepted, mirroring the past edge. Guards the `.abs()` on the skew.
        let edge = (now() + chrono::Duration::seconds(FRESHNESS_WINDOW_SECS)).to_rfc3339();
        let sig = GatewaySignature {
            signature: sign(TOKEN, DISTINCT_ID, "req-1", &edge),
            signed_at: edge,
            request_id: "req-1".to_string(),
        };
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Verified
        );
    }

    #[test]
    fn rejects_a_future_signature_past_the_window() {
        // One second past the future edge is rejected.
        let beyond = (now() + chrono::Duration::seconds(FRESHNESS_WINDOW_SECS + 1)).to_rfc3339();
        let sig = GatewaySignature {
            signature: sign(TOKEN, DISTINCT_ID, "req-1", &beyond),
            signed_at: beyond,
            request_id: "req-1".to_string(),
        };
        // Valid HMAC, but past the future edge — skew, not forgery.
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Stale
        );
    }

    #[test]
    fn rejects_an_unparseable_signed_at() {
        let sig = GatewaySignature {
            signature: sign(TOKEN, DISTINCT_ID, "req-1", "not-a-date"),
            signed_at: "not-a-date".to_string(),
            request_id: "req-1".to_string(),
        };
        // HMAC is valid (the gateway signed it), but the timestamp doesn't
        // parse, so freshness fails — never trusted.
        assert_eq!(
            verify(SECRET, TOKEN, DISTINCT_ID, &sig, now()),
            Provenance::Stale
        );
    }

    #[test]
    fn parse_requires_signature_and_signed_at() {
        let mut headers = HeaderMap::new();
        assert!(parse_signature(&headers).is_none());
        headers.insert(POSTHOG_AI_GATEWAY_SIGNATURE, "abc".parse().unwrap());
        assert!(parse_signature(&headers).is_none());
        headers.insert(
            POSTHOG_AI_GATEWAY_SIGNED_AT,
            "2026-05-28T10:00:00Z".parse().unwrap(),
        );
        let sig = parse_signature(&headers).unwrap();
        assert_eq!(sig.signature, "abc");
        assert_eq!(sig.request_id, "");
    }

    #[test]
    fn stamp_verified_overwrites_a_client_value_and_keeps_other_props() {
        let mut props: Map<String, Value> = serde_json::from_str(
            r#"{"$ai_gateway": true, "$ai_gateway_verified": false, "$ai_gateway_request_id": "client-fake", "$ai_model": "claude"}"#,
        )
        .unwrap();
        stamp_verified(&mut props, "signed-req");
        assert_eq!(props["$ai_gateway_verified"], Value::Bool(true));
        // request_id is overwritten with the signed value, not the client's.
        assert_eq!(
            props["$ai_gateway_request_id"],
            Value::String("signed-req".to_string())
        );
        assert_eq!(props["$ai_gateway"], Value::Bool(true));
        assert_eq!(props["$ai_model"], Value::String("claude".to_string()));
    }

    #[test]
    fn strip_gateway_removes_the_whole_namespace_including_a_forged_marker() {
        let mut props: Map<String, Value> = serde_json::from_str(
            r#"{"$ai_gateway": true, "$ai_gateway_verified": true, "$ai_model": "claude"}"#,
        )
        .unwrap();
        strip_gateway(&mut props);
        assert!(!props.contains_key("$ai_gateway"));
        assert!(!props.contains_key("$ai_gateway_verified"));
        assert_eq!(props["$ai_model"], Value::String("claude".to_string()));
    }

    fn raw(s: &str) -> Box<RawValue> {
        RawValue::from_string(s.to_string()).unwrap()
    }

    #[test]
    fn has_gateway_props_detects_a_key_but_not_a_bare_value() {
        assert!(has_gateway_props(&raw(r#"{"$ai_gateway_verified": true}"#)));
        assert!(!has_gateway_props(&raw(r#"{"$ai_model": "claude"}"#)));
        assert!(!has_gateway_props(&raw(
            r#"{"note": "mentions ai_gateway"}"#
        )));
    }

    #[test]
    fn has_gateway_props_catches_a_unicode_escaped_key() {
        // "\\u0024" decodes to "$", so this key parses to "$ai_gateway_verified"
        // even though the raw bytes lack the literal prefix. The \\u fallback must
        // catch it so the strip path isn't skipped on a forged escaped marker.
        assert!(has_gateway_props(&raw(
            r#"{"\u0024ai_gateway_verified": true}"#
        )));
    }

    #[test]
    fn strip_gateway_raw_returns_unchanged_when_nothing_to_strip() {
        assert!(matches!(
            strip_gateway_raw(&raw(r#"{"$ai_model": "claude"}"#)),
            StripOutcome::Unchanged
        ));
        match strip_gateway_raw(&raw(r#"{"$ai_gateway": true, "$ai_model": "x"}"#)) {
            StripOutcome::Stripped { props, forged } => {
                assert!(!forged, "no verified marker present");
                assert!(!props.get().contains("$ai_gateway"));
                assert!(props.get().contains("$ai_model"));
            }
            other => panic!("expected Stripped, got {other:?}"),
        }
    }

    #[test]
    fn strip_gateway_raw_flags_a_forged_verified_marker() {
        match strip_gateway_raw(&raw(r#"{"$ai_gateway_verified": true, "$ai_model": "x"}"#)) {
            StripOutcome::Stripped { forged, .. } => assert!(forged),
            other => panic!("expected Stripped, got {other:?}"),
        }
    }

    #[test]
    fn strip_gateway_raw_is_unparseable_for_objects_serde_rejects() {
        // RawValue accepts JSON the typed parse rejects (an out-of-range number);
        // a forged marker we can't strip must fail closed, not pass through.
        assert!(matches!(
            strip_gateway_raw(&raw(r#"{"$ai_gateway_verified": true, "x": 1e500}"#)),
            StripOutcome::Unparseable
        ));
    }

    #[test]
    fn has_gateway_props_ignores_a_unicode_escape_in_a_value() {
        // A \u escape inside a value must NOT trigger the parse — only keys are
        // scanned. This is the DoS guard: a value-side escape can't force a full
        // strip parse.
        assert!(!has_gateway_props(&raw(r#"{"$ai_model": "caf\u00e9"}"#)));
    }

    #[test]
    fn has_gateway_props_catches_a_mid_prefix_escaped_key() {
        // Escaping a char other than the leading $ evades the literal check, so
        // this exercises the key scanner: a decodes to 'a'.
        assert!(has_gateway_props(&raw(
            r#"{"$\u0061i_gateway_verified": true}"#
        )));
    }

    #[test]
    fn has_gateway_props_ignores_an_escaped_gateway_string_in_value_position() {
        // An escaped gateway-looking string in value position is not a property
        // key, so the scanner skips it and no parse is triggered.
        assert!(!has_gateway_props(&raw(
            r#"{"x": "\u0024ai_gateway_verified"}"#
        )));
    }

    #[test]
    fn strip_gateway_raw_strips_a_unicode_escaped_key() {
        // The escaped key decodes to "$ai_gateway_verified" on parse, so strip
        // (which matches decoded keys) removes it like any other gateway prop.
        match strip_gateway_raw(&raw(
            r#"{"\u0024ai_gateway_verified": true, "$ai_model": "x"}"#,
        )) {
            StripOutcome::Stripped { props, forged } => {
                assert!(forged, "the escaped key decodes to the verified marker");
                assert!(!props.get().contains("ai_gateway"));
                assert!(props.get().contains("$ai_model"));
            }
            other => panic!("expected Stripped, got {other:?}"),
        }
    }

    #[test]
    fn stamp_verified_raw_adds_the_marker() {
        let stamped = match stamp_verified_raw(&raw(r#"{"$ai_gateway": true}"#), "req-1") {
            StampOutcome::Stamped(p) => p,
            StampOutcome::Unparseable => panic!("expected Stamped"),
        };
        let map: Map<String, Value> = serde_json::from_str(stamped.get()).unwrap();
        assert_eq!(map["$ai_gateway_verified"], Value::Bool(true));
        assert_eq!(
            map["$ai_gateway_request_id"],
            Value::String("req-1".to_string())
        );
        assert_eq!(map["$ai_gateway"], Value::Bool(true));
    }

    #[test]
    fn accepts_the_cross_language_known_answer() {
        // The exact hex the Go signer produces for this input (ai-gateway
        // internal/emitter/signer_test.go TestSigner_KnownAnswer). If either
        // side's length-prefixed canonical form drifts, this fails and real
        // gateway signatures stop verifying.
        let sig = GatewaySignature {
            signature: "a3de0bf6819919c28f6bf6e8b61f01d53d4f313bd57a67e4a31d3f4fc1161351"
                .to_string(),
            signed_at: "2026-05-28T10:00:00Z".to_string(),
            request_id: "req-123".to_string(),
        };
        let now: DateTime<Utc> = "2026-05-28T10:00:00Z".parse().unwrap();
        assert_eq!(
            verify(b"test-signing-secret", "phc_test", "user-7", &sig, now),
            Provenance::Verified
        );
    }
}
