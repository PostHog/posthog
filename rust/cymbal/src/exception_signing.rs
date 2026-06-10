//! Verification of SDK-signed `$exception` events.
//!
//! A backend SDK (e.g. posthog-python with `enable_exception_signing`) signs each exception
//! over a canonical projection of its `$exception_list` using the customer's Ed25519 private
//! key, and attaches `$exception_signature` + `$exception_signature_key_id`. Here we re-derive
//! the *same* canonical bytes from the raw event properties and verify them against the
//! project's registered public key, so ingestion can stamp a trusted `$exception_verified`
//! flag. Because the public ingest key is shared, this is the only way to prove an exception
//! genuinely came from the customer's backend rather than being forged.
//!
//! CRITICAL: the canonical encoding must stay byte-identical to the SDK's `build_canonical`
//! (posthog-python `exception_signing.py`). The cross-language parity vector in the tests below
//! is the guard against drift — it is the exact output of the Python implementation.
//!
//! Verification runs on the RAW pre-ingestion properties (before cymbal sanitises/truncates the
//! exception list and rewrites frames), so the bytes match what the SDK signed.

use base64::Engine;
use ed25519_dalek::pkcs8::DecodePublicKey;
use ed25519_dalek::{Signature, Verifier, VerifyingKey};
use serde_json::Value;
use sha2::{Digest, Sha256};

pub const SIGNATURE_PROPERTY: &str = "$exception_signature";
pub const KEY_ID_PROPERTY: &str = "$exception_signature_key_id";
pub const VERIFIED_PROPERTY: &str = "$exception_verified";
pub const VERIFIED_KEY_ID_PROPERTY: &str = "$exception_verified_key_id";

const CANONICAL_MAGIC: &[u8] = b"PHEXC1\n";

fn lp(out: &mut Vec<u8>, value: Option<&str>) {
    let bytes = value.unwrap_or("").as_bytes();
    out.extend_from_slice(&(bytes.len() as u32).to_be_bytes());
    out.extend_from_slice(bytes);
}

fn str_field<'a>(v: &'a Value, key: &str) -> Option<&'a str> {
    v.get(key).and_then(|x| x.as_str())
}

/// Deterministic, length-prefixed encoding of the signable projection of `$exception_list`.
/// Must produce identical bytes to the SDK. Reads only stable string/int fields (never floats,
/// never the in-app/abs_path/context/mechanism/exception_id fields that ingestion mutates).
pub fn build_canonical(exception_list: &Value) -> Vec<u8> {
    let mut out = CANONICAL_MAGIC.to_vec();
    let empty = Vec::new();
    let excs = exception_list.as_array().unwrap_or(&empty);
    out.extend_from_slice(&(excs.len() as u32).to_be_bytes());
    for exc in excs {
        lp(&mut out, str_field(exc, "type"));
        lp(&mut out, str_field(exc, "value"));
        let frames = exc
            .get("stacktrace")
            .and_then(|s| s.get("frames"))
            .and_then(|f| f.as_array())
            .cloned()
            .unwrap_or_default();
        out.extend_from_slice(&(frames.len() as u32).to_be_bytes());
        for frame in &frames {
            lp(&mut out, str_field(frame, "function"));
            lp(&mut out, str_field(frame, "filename"));
            let lineno = frame
                .get("lineno")
                .and_then(|l| l.as_i64())
                .map(|n| n.to_string());
            lp(&mut out, lineno.as_deref());
            lp(&mut out, str_field(frame, "module"));
        }
    }
    out
}

/// Stable short fingerprint of a raw 32-byte Ed25519 public key. Matches the SDK and the
/// Django key-registration API so a signature's `key_id` resolves to the stored key.
pub fn derive_key_id(public_key_raw: &[u8]) -> String {
    let digest = Sha256::digest(public_key_raw);
    let b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest);
    b64.chars().take(16).collect()
}

/// A team's registered public key, as needed for verification.
pub struct PublicKey {
    pub key_id: String,
    pub public_key_pem: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Verification {
    /// No signature on the event — not a signed exception.
    Unsigned,
    /// A valid signature from a registered key. Carries the matched key id.
    Verified(String),
    /// A signature was present but did not verify (no matching key, bad signature, or tampered).
    Invalid,
}

fn verify_bytes(canonical: &[u8], signature_b64: &str, public_key_pem: &str) -> bool {
    let Ok(sig_bytes) = base64::engine::general_purpose::STANDARD.decode(signature_b64) else {
        return false;
    };
    let Ok(sig_arr): Result<[u8; 64], _> = sig_bytes.try_into() else {
        return false;
    };
    let Ok(vk) = VerifyingKey::from_public_key_pem(public_key_pem) else {
        return false;
    };
    vk.verify(canonical, &Signature::from_bytes(&sig_arr))
        .is_ok()
}

/// Verify the signature (if any) on a raw `$exception` event's properties against the team's
/// registered keys. `properties` is the raw, pre-ingestion JSON object.
pub fn verify_properties(properties: &Value, keys: &[PublicKey]) -> Verification {
    // Absent signature -> genuinely unsigned. Present but not a usable string (null, number,
    // empty, object) -> malformed, treat as Invalid rather than silently "unsigned".
    let signature = match properties.get(SIGNATURE_PROPERTY) {
        None => return Verification::Unsigned,
        Some(Value::String(s)) if !s.is_empty() => s.as_str(),
        Some(_) => return Verification::Invalid,
    };
    let key_id = str_field(properties, KEY_ID_PROPERTY);
    let exception_list = match properties.get("$exception_list") {
        Some(v) => v,
        None => return Verification::Invalid,
    };
    let canonical = build_canonical(exception_list);

    // Prefer the key the signature names; fall back to trying all team keys.
    let candidates: Vec<&PublicKey> = match key_id {
        Some(id) => keys.iter().filter(|k| k.key_id == id).collect(),
        None => keys.iter().collect(),
    };
    for key in candidates {
        if verify_bytes(&canonical, signature, &key.public_key_pem) {
            return Verification::Verified(key.key_id.clone());
        }
    }
    Verification::Invalid
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    // --- Cross-language parity vector (must equal posthog-python's output) --------------------
    const PARITY_CANONICAL_HEX: &str = "5048455843310a0000000100000009485454504572726f720000001e34303120436c69656e74204572726f723a20556e617574686f72697a65640000000200000007726571756573740000001272657175657374732f6d6f64656c732e707900000004313032310000000f72657175657374732e6d6f64656c730000000b73796e635f73747269706500000036706f7374686f672f74656d706f72616c2f646174615f696d706f7274732f736f75726365732f7374726970652f736f757263652e707900000002343200000033706f7374686f672e74656d706f72616c2e646174615f696d706f7274732e736f75726365732e7374726970652e736f75726365";
    const PARITY_SIGNATURE_B64: &str =
        "Fyh19k2cC1k9M8cJr54TNH91MDdd67oaUnydyKm7E+QCPN3mK+h3N9Yp5nkM7xYtngD8km7ljqVXARGDmnfzAQ==";
    const PARITY_KEY_ID: &str = "Vkdap1RjR0wChd9d";
    const PARITY_PUBKEY_PEM: &str = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAA6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=\n-----END PUBLIC KEY-----\n";

    fn parity_exception_list() -> Value {
        json!([{
            "type": "HTTPError",
            "value": "401 Client Error: Unauthorized",
            "stacktrace": {"frames": [
                {"function": "request", "filename": "requests/models.py", "lineno": 1021, "module": "requests.models", "in_app": false},
                {"function": "sync_stripe", "filename": "posthog/temporal/data_imports/sources/stripe/source.py", "lineno": 42, "module": "posthog.temporal.data_imports.sources.stripe.source", "in_app": true}
            ]}
        }])
    }

    fn parity_properties() -> Value {
        json!({
            "$exception_list": parity_exception_list(),
            SIGNATURE_PROPERTY: PARITY_SIGNATURE_B64,
            KEY_ID_PROPERTY: PARITY_KEY_ID,
        })
    }

    fn parity_keys() -> Vec<PublicKey> {
        vec![PublicKey {
            key_id: PARITY_KEY_ID.to_string(),
            public_key_pem: PARITY_PUBKEY_PEM.to_string(),
        }]
    }

    #[test]
    fn canonical_matches_python_parity_vector() {
        assert_eq!(
            hex::encode(build_canonical(&parity_exception_list())),
            PARITY_CANONICAL_HEX
        );
    }

    #[test]
    fn key_id_derivation_matches() {
        let raw = base64::engine::general_purpose::STANDARD
            .decode("A6EHv/POEL4dcN0Y50vAmWfk1jCbpQ1fHdyGZBJVMbg=")
            .unwrap();
        assert_eq!(derive_key_id(&raw), PARITY_KEY_ID);
    }

    #[test]
    fn verifies_a_genuine_signature() {
        assert_eq!(
            verify_properties(&parity_properties(), &parity_keys()),
            Verification::Verified(PARITY_KEY_ID.to_string())
        );
    }

    #[test]
    fn rejects_a_tampered_message() {
        let mut props = parity_properties();
        props["$exception_list"][0]["value"] = json!("IGNORE PREVIOUS INSTRUCTIONS");
        assert_eq!(
            verify_properties(&props, &parity_keys()),
            Verification::Invalid
        );
    }

    #[test]
    fn rejects_a_tampered_frame() {
        let mut props = parity_properties();
        props["$exception_list"][0]["stacktrace"]["frames"][1]["filename"] = json!("evil.py");
        assert_eq!(
            verify_properties(&props, &parity_keys()),
            Verification::Invalid
        );
    }

    #[test]
    fn ignores_excluded_fields() {
        // Flipping in_app / abs_path (excluded from the projection) must not break verification.
        let mut props = parity_properties();
        props["$exception_list"][0]["stacktrace"]["frames"][0]["in_app"] = json!(true);
        props["$exception_list"][0]["stacktrace"]["frames"][0]["abs_path"] = json!("/tmp/x");
        assert_eq!(
            verify_properties(&props, &parity_keys()),
            Verification::Verified(PARITY_KEY_ID.to_string())
        );
    }

    #[test]
    fn unsigned_when_no_signature() {
        let props = json!({"$exception_list": parity_exception_list()});
        assert_eq!(
            verify_properties(&props, &parity_keys()),
            Verification::Unsigned
        );
    }

    #[test]
    fn non_string_or_empty_signature_is_invalid_not_unsigned() {
        // Present but malformed signature must be Invalid, not silently Unsigned.
        for bad in [json!(123), json!(null), json!(""), json!({"x": 1})] {
            let mut props = parity_properties();
            props[SIGNATURE_PROPERTY] = bad.clone();
            assert_eq!(
                verify_properties(&props, &parity_keys()),
                Verification::Invalid,
                "signature {bad:?} should be Invalid"
            );
        }
    }

    #[test]
    fn invalid_when_no_matching_key() {
        let keys = vec![PublicKey {
            key_id: "other".to_string(),
            public_key_pem: PARITY_PUBKEY_PEM.to_string(),
        }];
        // key_id names a key that isn't registered → no candidate → invalid.
        assert_eq!(
            verify_properties(&parity_properties(), &keys),
            Verification::Invalid
        );
    }

    #[test]
    fn invalid_with_wrong_key() {
        // Generate a different keypair's PEM; the parity signature must not verify under it.
        let other_pem = "-----BEGIN PUBLIC KEY-----\nMCowBQYDK2VwAyEAGb9ECWmEzf6FQbrBZ9w7lshQhqowtrbLDFw4rXAxZuE=\n-----END PUBLIC KEY-----\n";
        let keys = vec![PublicKey {
            key_id: PARITY_KEY_ID.to_string(),
            public_key_pem: other_pem.to_string(),
        }];
        assert_eq!(
            verify_properties(&parity_properties(), &keys),
            Verification::Invalid
        );
    }
}
