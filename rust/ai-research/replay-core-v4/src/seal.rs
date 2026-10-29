//! Keys derived from a team month key: the seal on a session key, and the two HMAC keys behind image references. Also
//! the key derived from a session key for the URL fingerprints in the block index.

use aes_gcm::aead::{Aead, AeadCore, KeyInit, OsRng, Payload};
use aes_gcm::{Aes256Gcm, Key, Nonce};
use hkdf::Hkdf;
use serde_json::{Map, Value};
use sha2::Sha256;

use crate::envelope::{canonical_json, EnvelopeError, NONCE_BYTES, TAG_BYTES};

// HKDF gives each job its own key, so a flaw in one use of the team month key cannot reach another.
const SESSION_KEY_WRAP_INFO: &[u8] = b"ml-session-key-wrap";
const IMAGE_CONTENT_KEY_INFO: &[u8] = b"ml-image-content-key";
const IMAGE_URL_KEY_INFO: &[u8] = b"ml-image-url-key";
const URL_FINGERPRINT_KEY_INFO: &[u8] = b"ml-url-fingerprint-key";

/// The KMS encryption context of a v4 key. A sealed session key authenticates the same context.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct WrappingContext {
    pub team_id: i64,
    pub key_month: String,
    pub session_id: Option<String>,
}

impl WrappingContext {
    pub const PURPOSE: &'static str = "ai-research-v4";

    /// The context as KMS takes it: string keys to string values.
    pub fn entries(&self) -> Vec<(&'static str, String)> {
        let mut entries = vec![
            ("key_month", self.key_month.clone()),
            ("purpose", Self::PURPOSE.to_owned()),
            ("team_id", self.team_id.to_string()),
        ];
        if let Some(session_id) = &self.session_id {
            entries.push(("session_id", session_id.clone()));
        }
        entries
    }

    fn authenticated_data(&self) -> String {
        let map: Map<String, Value> = self
            .entries()
            .into_iter()
            .map(|(k, v)| (k.to_owned(), Value::from(v)))
            .collect();
        canonical_json(&Value::Object(map))
    }
}

/// A session key sealed under its team month key, as the key table stores it.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct SealedKey {
    /// The ciphertext followed by the 16-byte tag.
    pub sealed: Vec<u8>,
    pub nonce: [u8; NONCE_BYTES],
}

fn derive(input_key: &[u8; 32], info: &[u8]) -> [u8; 32] {
    let mut out = [0u8; 32];
    Hkdf::<Sha256>::new(None, input_key)
        .expand(info, &mut out)
        .expect("32 bytes is a valid HKDF-SHA256 output length");
    out
}

/// The key for the HMAC of an inline image's bytes.
pub fn image_content_key(team_month_key: &[u8; 32]) -> [u8; 32] {
    derive(team_month_key, IMAGE_CONTENT_KEY_INFO)
}

/// The key for the HMAC of a remote image's URL.
pub fn image_url_key(team_month_key: &[u8; 32]) -> [u8; 32] {
    derive(team_month_key, IMAGE_URL_KEY_INFO)
}

/// The key for the HMAC of a page URL in the block index. It comes from the session key, so a fingerprint compares
/// only with fingerprints of the same session.
pub fn url_fingerprint_key(session_key: &[u8; 32]) -> [u8; 32] {
    derive(session_key, URL_FINGERPRINT_KEY_INFO)
}

pub fn seal_session_key(
    team_month_key: &[u8; 32],
    context: &WrappingContext,
    session_key: &[u8; 32],
) -> SealedKey {
    seal_session_key_with_nonce(
        team_month_key,
        context,
        session_key,
        Aes256Gcm::generate_nonce(&mut OsRng).into(),
    )
}

/// Seals with a caller-chosen nonce. Only the test vectors may fix a nonce.
pub fn seal_session_key_with_nonce(
    team_month_key: &[u8; 32],
    context: &WrappingContext,
    session_key: &[u8; 32],
    nonce: [u8; NONCE_BYTES],
) -> SealedKey {
    let wrapping_key = derive(team_month_key, SESSION_KEY_WRAP_INFO);
    let aad = context.authenticated_data();
    let sealed = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(&wrapping_key))
        .encrypt(
            Nonce::from_slice(&nonce),
            Payload {
                msg: session_key,
                aad: aad.as_bytes(),
            },
        )
        .expect("AES-GCM encryption of 32 bytes does not fail");
    SealedKey { sealed, nonce }
}

/// Opens a sealed session key. The context must match, so a sealed key cannot move to another session or team.
pub fn open_session_key(
    team_month_key: &[u8; 32],
    context: &WrappingContext,
    sealed: &SealedKey,
) -> Result<[u8; 32], EnvelopeError> {
    if sealed.sealed.len() <= TAG_BYTES {
        return Err(EnvelopeError::Truncated);
    }
    let wrapping_key = derive(team_month_key, SESSION_KEY_WRAP_INFO);
    let aad = context.authenticated_data();
    let plaintext = Aes256Gcm::new(Key::<Aes256Gcm>::from_slice(&wrapping_key))
        .decrypt(
            Nonce::from_slice(&sealed.nonce),
            Payload {
                msg: &sealed.sealed,
                aad: aad.as_bytes(),
            },
        )
        .map_err(|_| EnvelopeError::Authentication)?;
    plaintext
        .try_into()
        .map_err(|_| EnvelopeError::Authentication)
}
