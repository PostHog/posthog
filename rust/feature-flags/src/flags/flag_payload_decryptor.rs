//! Decrypts encrypted remote-config flag payloads.
//!
//! Wire-compatible with Django's `FlagPayloadCodec`
//! (`products/feature_flags/backend/encrypted_flag_payloads.py`): Fernet over a key
//! derived by `_prepare_key` (pad/truncate raw key material to 32 bytes, then url-safe
//! base64), wrapped in a `MultiFernet` so older keys still decrypt during rotation.
//!
//! Keys come from `FLAGS_SECRET_KEYS` (comma-separated, ordered: Django encrypts with the
//! first key; this service only decrypts and tries all of them). Matching Django, an empty
//! list falls back to `[SECRET_KEY]` for self-hosted.

use base64::{prelude::BASE64_URL_SAFE, Engine};
use fernet::{Fernet, MultiFernet};

/// Returned for encrypted payloads when the caller is not allowed to decrypt
/// (i.e. not authenticated with a personal API key). Byte-identical to Django's
/// `REDACTED_PAYLOAD_VALUE` so responses match.
pub const REDACTED_PAYLOAD_VALUE: &str = "\"********* (encrypted)\"";

#[derive(Debug, thiserror::Error)]
pub enum FlagPayloadDecryptorError {
    #[error("no decryption keys configured (FLAGS_SECRET_KEYS and SECRET_KEY are both empty)")]
    NoKeys,
    #[error("{built} of {configured} configured keys are valid Fernet keys")]
    InvalidKeys { built: usize, configured: usize },
    #[error("failed to decrypt payload")]
    Decrypt,
    #[error("decrypted payload is not valid UTF-8")]
    Utf8,
}

/// Derive a Fernet from raw key material, mirroring Django's `_prepare_key`.
///
/// Pads (left, NUL) or truncates to the 32 bytes Fernet requires, then url-safe
/// base64-encodes. NOTE: this differs from `batch-import-worker`, which assumes keys
/// are already 32 bytes. Flag keys are 43 chars (`secrets.token_urlsafe(32)`); skipping
/// the resize would make `Fernet::new` reject them and startup fail with `InvalidKeys`
/// (`from_keys` requires every key to build). With the resize, any input becomes a valid
/// 32-byte base64 key, so this returns `None` only defensively and never in practice.
fn flag_fernet(raw: &str) -> Option<Fernet> {
    let kb = raw.as_bytes();
    let prepared: Vec<u8> = if kb.len() >= 32 {
        kb[..32].to_vec()
    } else {
        let mut v = vec![0u8; 32 - kb.len()];
        v.extend_from_slice(kb);
        v
    };
    Fernet::new(&BASE64_URL_SAFE.encode(prepared))
}

#[derive(Clone)]
pub struct FlagPayloadDecryptor {
    multi: MultiFernet,
}

impl FlagPayloadDecryptor {
    /// Resolve keys Django-style (`FLAGS_SECRET_KEYS = get_list(...) or [SECRET_KEY]`)
    /// and build the decryptor. Fails loudly at startup if no keys resolve or any key
    /// fails to build, rather than silently dropping keys and failing every decrypt.
    ///
    /// Note: empty comma-entries are dropped (`"k1,,k2"` -> `["k1", "k2"]`), unlike Django's
    /// `get_list`, which keeps them. This is safe because Django encrypts only with the first key
    /// (the first non-empty entry in both); an empty entry would only ever be an unused decrypt
    /// fallback.
    pub fn from_config(
        flags_secret_keys: &str,
        secret_key: &str,
    ) -> Result<Self, FlagPayloadDecryptorError> {
        let mut keys: Vec<String> = flags_secret_keys
            .split(',')
            .map(|k| k.trim().to_string())
            .filter(|k| !k.is_empty())
            .collect();

        if keys.is_empty() {
            let sk = secret_key.trim();
            if !sk.is_empty() {
                keys.push(sk.to_string());
            }
        }

        Self::from_keys(&keys)
    }

    /// Build from an already-resolved, ordered key list (Django encrypts with the first key;
    /// this service only decrypts and tries all of them).
    pub fn from_keys(keys: &[String]) -> Result<Self, FlagPayloadDecryptorError> {
        if keys.is_empty() {
            return Err(FlagPayloadDecryptorError::NoKeys);
        }
        let fernets: Vec<Fernet> = keys.iter().filter_map(|k| flag_fernet(k)).collect();
        // Defensive: `flag_fernet` resizes any input to a valid 32-byte key, so this never
        // trips in practice. It exists so that if the resize were ever removed or broken,
        // startup fails loudly here instead of silently dropping keys (which would surface
        // later as unexplained decrypt failures).
        if fernets.len() != keys.len() {
            return Err(FlagPayloadDecryptorError::InvalidKeys {
                built: fernets.len(),
                configured: keys.len(),
            });
        }
        Ok(Self {
            multi: MultiFernet::new(fernets),
        })
    }

    /// Decrypt a Fernet token, trying every key (primary then fallbacks).
    pub fn decrypt(&self, token: &str) -> Result<String, FlagPayloadDecryptorError> {
        let bytes = self
            .multi
            .decrypt(token)
            .map_err(|_| FlagPayloadDecryptorError::Decrypt)?;
        String::from_utf8(bytes).map_err(|_| FlagPayloadDecryptorError::Utf8)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    // Ciphertext produced by Django's FlagPayloadCodec
    // (products/feature_flags/backend/encrypted_flag_payloads.py).
    const PLAINTEXT: &str = r#"{"hello":"world","n":42}"#;
    const K1: &str = "ZtTE8u7zKlorOQYJGS8EM2lFggYttXVaqnxWQP-dXEc"; // 43 chars, token_urlsafe(32)
    const K2: &str = "DhdZV2HWVtwu8T7yPr5D7Pmg8WjYlD1B8ngynT0GAOc";
    const TOK_PRIMARY: &str = "gAAAAABqKCSqLF1UmKt8anAe6Um8knblGLl8nLyg6qoynbsE398Yl28Nh1xZZmYB8_WKXkO7v3LjHmNOxkYWjLCbLF0gTWR0V7UO4ziqvY43WlYiG1d3ZjQ=";
    const TOK_FALLBACK: &str = "gAAAAABqKCSqmH-bdY2DBxrvA6U9Rk2VG0rg2lgAHUVTKdkIyOFa-2Th2sbMNb_8UwkX_o1WI6r8rSC_-kfiZ7ZtMuDynAkiyXuuKeExHtQKy3SGnVI6-M8=";
    // Encrypted under a key shorter than 32 bytes, so decrypting exercises the
    // left-pad-with-NULs branch of `flag_fernet` (a self-hosted SECRET_KEY shorter than 32
    // bytes). K1/K2 above are 43 chars and only ever hit the truncate branch.
    const SHORT_KEY: &str = "short-secret"; // 12 bytes
    const TOK_SHORT: &str = "gAAAAABqKxx2qb8lEOK_V04oEJ21oc8InnsjZHp54jnnbnomqFvG8HSSWQn6FXDV6tBhoaQQ1c_cuyUZYg5lQqT9WThNKt9ywJFPZr7C2eNfBFFAhgjv_M4=";

    #[test]
    fn decrypts_python_ciphertext_via_primary_and_fallback() {
        let d = FlagPayloadDecryptor::from_keys(&[K1.to_string(), K2.to_string()]).unwrap();
        assert_eq!(d.decrypt(TOK_PRIMARY).unwrap(), PLAINTEXT);
        // Encrypted under K2 only; decrypts through the fallback slot.
        assert_eq!(d.decrypt(TOK_FALLBACK).unwrap(), PLAINTEXT);
    }

    #[test]
    fn decrypts_python_ciphertext_under_short_key() {
        // Pins the pad direction: if the NUL padding were on the wrong side, this fails
        // while the 43-char fixtures above still pass.
        let d = FlagPayloadDecryptor::from_keys(&[SHORT_KEY.to_string()]).unwrap();
        assert_eq!(d.decrypt(TOK_SHORT).unwrap(), PLAINTEXT);
    }

    #[test]
    fn from_config_splits_and_trims_flags_secret_keys() {
        let d = FlagPayloadDecryptor::from_config(&format!(" {K1} , {K2} "), "").unwrap();
        assert_eq!(d.decrypt(TOK_PRIMARY).unwrap(), PLAINTEXT);
        assert_eq!(d.decrypt(TOK_FALLBACK).unwrap(), PLAINTEXT);
    }

    #[test]
    fn from_config_falls_back_to_secret_key_when_flags_empty() {
        // Self-hosted: FLAGS_SECRET_KEYS unset -> use [SECRET_KEY]. K1 acts as SECRET_KEY here.
        let d = FlagPayloadDecryptor::from_config("", K1).unwrap();
        assert_eq!(d.decrypt(TOK_PRIMARY).unwrap(), PLAINTEXT);
    }

    #[test]
    fn from_config_errors_when_no_keys() {
        assert!(matches!(
            FlagPayloadDecryptor::from_config("", ""),
            Err(FlagPayloadDecryptorError::NoKeys)
        ));
    }

    #[test]
    fn wrong_key_fails_to_decrypt() {
        let d = FlagPayloadDecryptor::from_keys(&[K2.to_string()]).unwrap();
        assert!(matches!(
            d.decrypt(TOK_PRIMARY),
            Err(FlagPayloadDecryptorError::Decrypt)
        ));
    }
}
