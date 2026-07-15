//! Crypto tests for the Fernet decryptor + per-leaf JSON walk.
//!
//! Two flavours of test:
//!   1. Round-trip: encrypt with a Fernet key derived the SAME way the decryptor derives its keys,
//!      then assert the decryptor recovers the plaintext. Locks the derivation math (url-safe base64
//!      of a 32-byte salt key; PBKDF2-HMAC-SHA256 100k for legacy) and the JSON-walk semantics.
//!   2. Cross-implementation parity: decrypt ciphertext produced by Python's `cryptography` Fernet
//!      — the exact library + key derivation Django's `EncryptedJSONField` uses — proving the Rust
//!      `fernet` crate reads Django-written tokens byte-for-byte. This is the highest-risk guarantee
//!      before any consumer reads through the gateway.

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

// Cross-implementation parity fixture. Produced by Python's `cryptography` Fernet (the exact
// library + key derivation Django's EncryptedJSONField uses) under the dev ENCRYPTION_SALT_KEYS
// default, then pasted here. Fernet tokens carry a timestamp but no TTL is enforced on decrypt, so
// these stay valid indefinitely. Regenerate under the same salt key with:
//   python3 -c "import base64; from cryptography.fernet import Fernet, MultiFernet; \
//     f=MultiFernet([Fernet(base64.urlsafe_b64encode(b'00beef0000beef0000beef0000beef00'))]); \
//     print(f.encrypt(b'django-produced-access-token').decode())"
const DJANGO_ACCESS_TOKEN_CIPHERTEXT: &str =
    "gAAAAABqV056wiDg4SFg1WMXPi0eSlEqDSqNapKDGEOjxStwnQdRnt2XsLu-lfRiXBq3Y3WZUtpKmjDJp8xPkMVh-iZyUGbSf8Q24WUeLApdA4ilqpLjUSY=";
const DJANGO_REFRESH_TOKEN_CIPHERTEXT: &str =
    "gAAAAABqV056405em_3t-Gy4hfqS4x7PqxbufIr5T5sUaNHRBHVU5pl0rTcL-V06r0Bb1bO2FXLbCe8_EMoAKjGh1veSsDvsyXC7BsCGorv61P2cQDYV_m8=";

#[test]
fn decrypts_django_produced_ciphertext() {
    let d = IntegrationDecryptor::build(&[SALT_KEY_32.to_string()], &[], &[]).unwrap();
    assert_eq!(
        d.decrypt_leaf(DJANGO_ACCESS_TOKEN_CIPHERTEXT).unwrap(),
        "django-produced-access-token"
    );
    assert_eq!(
        d.decrypt_leaf(DJANGO_REFRESH_TOKEN_CIPHERTEXT).unwrap(),
        "django-produced-refresh-token"
    );
}

#[test]
fn walks_django_produced_sensitive_config() {
    let d = IntegrationDecryptor::build(&[SALT_KEY_32.to_string()], &[], &[]).unwrap();
    let encrypted = json!({
        "access_token": DJANGO_ACCESS_TOKEN_CIPHERTEXT,
        "nested": { "refresh_token": DJANGO_REFRESH_TOKEN_CIPHERTEXT },
        "not_encrypted": "plain",
    });
    let out = decrypt_sensitive_config(&d, &encrypted);
    assert_eq!(out["access_token"], json!("django-produced-access-token"));
    assert_eq!(out["nested"]["refresh_token"], json!("django-produced-refresh-token"));
    assert_eq!(out["not_encrypted"], json!("plain"));
}
