//! Fernet decryptor, wire-compatible with Django's `EncryptedJSONField`
//! (`posthog/helpers/encrypted_fields.py`).
//!
//! Key derivation must match `EncryptedFieldMixin.keys` EXACTLY — a mismatch fails to decrypt
//! silently in prod. It differs from `feature-flags`' `flag_payload_decryptor.rs`, which
//! pad/truncates raw key material; integration fields use `ENCRYPTION_SALT_KEYS` entries as
//! 32-byte Fernet key material directly (url-safe base64), plus PBKDF2-derived legacy keys.

use base64::{prelude::BASE64_URL_SAFE, Engine};
use fernet::{Fernet, MultiFernet};
use sha2::Sha256;

/// Matches `PBKDF2HMAC(..., iterations=100000)` in encrypted_fields.py.
const PBKDF2_ITERATIONS: u32 = 100_000;
/// Fernet keys are 32 bytes of material, url-safe-base64 encoded.
const FERNET_KEY_LEN: usize = 32;

#[derive(Debug, thiserror::Error)]
pub enum DecryptorError {
    #[error("no usable primary decryption keys were built (ENCRYPTION_SALT_KEYS is empty or every entry is not 32 bytes)")]
    NoKeys,
}

/// Holds the ordered `MultiFernet` (primary salt keys first, legacy PBKDF2 keys last).
/// `MultiFernet::decrypt` tries every key, so newer-key ciphertext and legacy ciphertext both work.
#[derive(Clone)]
pub struct IntegrationDecryptor {
    multi: MultiFernet,
    primary_key_count: usize,
    legacy_key_count: usize,
}

impl IntegrationDecryptor {
    /// Build the decryptor from the same inputs Django uses:
    ///   1. Primary: `urlsafe_b64(k)` for each `k` in `ENCRYPTION_SALT_KEYS` (each is 32 raw bytes).
    ///   2. Legacy (decrypt-only, appended last): `urlsafe_b64(PBKDF2-HMAC-SHA256(secret, salt, 100k, 32))`
    ///      for every `secret` in `[SECRET_KEY, *SECRET_KEY_FALLBACKS]` × every `salt` in `SALT_KEY`.
    ///
    /// Fails fast (`NoKeys`) if no valid primary key is built — never runs with only legacy keys,
    /// mirroring the intent that new values are always encryptable under a primary key.
    pub fn build(
        encryption_salt_keys: &[String],
        legacy_secret_keys: &[String],
        salt_keys: &[String],
    ) -> Result<Self, DecryptorError> {
        let mut keys: Vec<Fernet> = Vec::new();

        // Primary keys. Django: base64.urlsafe_b64encode(k.encode("utf-8")).
        for k in encryption_salt_keys {
            match Fernet::new(&BASE64_URL_SAFE.encode(k.as_bytes())) {
                Some(f) => keys.push(f),
                None => tracing::warn!(
                    "ENCRYPTION_SALT_KEYS entry is not a valid 32-byte Fernet key; skipping it"
                ),
            }
        }
        let primary_key_count = keys.len();

        if primary_key_count == 0 {
            return Err(DecryptorError::NoKeys);
        }

        // Legacy keys, appended last so they're only ever used as decrypt fallbacks.
        for secret in legacy_secret_keys {
            for salt in salt_keys {
                let mut derived = [0u8; FERNET_KEY_LEN];
                pbkdf2::pbkdf2_hmac::<Sha256>(
                    secret.as_bytes(),
                    salt.as_bytes(),
                    PBKDF2_ITERATIONS,
                    &mut derived,
                );
                if let Some(f) = Fernet::new(&BASE64_URL_SAFE.encode(derived)) {
                    keys.push(f);
                }
            }
        }
        let legacy_key_count = keys.len() - primary_key_count;

        Ok(Self {
            multi: MultiFernet::new(keys),
            primary_key_count,
            legacy_key_count,
        })
    }

    pub fn primary_key_count(&self) -> usize {
        self.primary_key_count
    }

    pub fn legacy_key_count(&self) -> usize {
        self.legacy_key_count
    }

    /// Decrypt one Fernet token. Returns `None` when no key can decrypt it (or the plaintext
    /// isn't valid UTF-8). Callers treat `None` as pass-through (see `json_walk`), matching
    /// Django's `ignore_decrypt_errors=True` on `Integration.sensitive_config`.
    pub fn decrypt_leaf(&self, token: &str) -> Option<String> {
        self.multi
            .decrypt(token)
            .ok()
            .and_then(|bytes| String::from_utf8(bytes).ok())
    }
}
