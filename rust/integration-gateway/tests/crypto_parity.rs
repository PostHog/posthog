//! Crypto tests for the Fernet decryptor + per-leaf JSON walk.
//!
//! These are round-trip tests: they encrypt with a Fernet key derived the SAME way the decryptor
//! derives its keys, then assert the decryptor recovers the plaintext. They lock the derivation
//! math (url-safe base64 of a 32-byte salt key; PBKDF2-HMAC-SHA256 100k for legacy) and the
//! JSON-walk semantics.
//!
//! TODO (before enabling any consumer — highest-risk item in the plan): add a cross-implementation
//! parity test that decrypts ciphertext produced by Django's `EncryptedJSONField`, like
//! `flag_payload_decryptor.rs`'s hardcoded `TOK_*` fixtures. Generate with, in a Django shell:
//!     from posthog.models.integration import Integration
//!     i = Integration(team_id=1, kind="slack", sensitive_config={"access_token": "hello"})
//!     i.save(); print(get_db_field_value("sensitive_config", i.id))
//! then paste the emitted Fernet token(s) here and assert they decrypt to "hello".

use base64::{prelude::BASE64_URL_SAFE, Engine};
use fernet::Fernet;
use serde_json::{json, Value};
use sha2::Sha256;

use integration_gateway::crypto::{decrypt_sensitive_config, IntegrationDecryptor};

// 32 bytes — matches the dev default of ENCRYPTION_SALT_KEYS.
const SALT_KEY_32: &str = "00beef0000beef0000beef0000beef00";

fn fernet_for_salt_key(k: &str) -> Fernet {
    Fernet::new(&BASE64_URL_SAFE.encode(k.as_bytes())).unwrap()
}

fn fernet_for_legacy(secret: &str, salt: &str) -> Fernet {
    let mut derived = [0u8; 32];
    pbkdf2::pbkdf2_hmac::<Sha256>(secret.as_bytes(), salt.as_bytes(), 100_000, &mut derived);
    Fernet::new(&BASE64_URL_SAFE.encode(derived)).unwrap()
}

#[test]
fn decrypts_salt_key_leaf() {
    let token = fernet_for_salt_key(SALT_KEY_32).encrypt(b"super-secret-token");
    let d = IntegrationDecryptor::build(&[SALT_KEY_32.to_string()], &[], &[]).unwrap();
    assert_eq!(d.decrypt_leaf(&token).unwrap(), "super-secret-token");
}

#[test]
fn decrypts_legacy_pbkdf2_leaf() {
    let secret = "django-secret-key";
    let salt = "some-salt";
    let token = fernet_for_legacy(secret, salt).encrypt(b"legacy-value");
    let d = IntegrationDecryptor::build(
        &[SALT_KEY_32.to_string()],
        &[secret.to_string()],
        &[salt.to_string()],
    )
    .unwrap();
    assert_eq!(d.decrypt_leaf(&token).unwrap(), "legacy-value");
}

#[test]
fn walks_nested_and_passes_through_undecryptable() {
    let f = fernet_for_salt_key(SALT_KEY_32);
    let d = IntegrationDecryptor::build(&[SALT_KEY_32.to_string()], &[], &[]).unwrap();

    let encrypted = json!({
        "access_token": f.encrypt(b"ACCESS"),
        "nested": { "refresh_token": f.encrypt(b"REFRESH") },
        "not_encrypted": "plain",   // undecryptable -> passthrough (ignore_decrypt_errors)
        "id_token": Value::Null,
        "count": 3,
    });

    let out = decrypt_sensitive_config(&d, &encrypted);
    assert_eq!(out["access_token"], json!("ACCESS"));
    assert_eq!(out["nested"]["refresh_token"], json!("REFRESH"));
    assert_eq!(out["not_encrypted"], json!("plain"));
    assert_eq!(out["id_token"], Value::Null);
    assert_eq!(out["count"], json!(3));
}

#[test]
fn build_requires_a_primary_key() {
    assert!(IntegrationDecryptor::build(&[], &["s".to_string()], &["salt".to_string()]).is_err());
}
