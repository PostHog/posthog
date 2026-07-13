use serde_json::Value;

use super::decryptor::IntegrationDecryptor;

/// Recursively decrypt a `sensitive_config` value.
///
/// Mirrors `EncryptedJSONField._decrypt_values` + `ignore_decrypt_errors=True`: every string
/// leaf is an independent Fernet token; an undecryptable string passes through unchanged
/// (handles values written before the field was encrypted); non-string scalars and nulls pass
/// through. This matches the plugin-server's `EncryptedFields.decryptObject`
/// (`nodejs/src/cdp/utils/encryption-utils.ts`), so the decrypted shape is identical to what
/// CDP produces today.
pub fn decrypt_sensitive_config(decryptor: &IntegrationDecryptor, value: &Value) -> Value {
    match value {
        Value::Object(map) => Value::Object(
            map.iter()
                .map(|(k, v)| (k.clone(), decrypt_sensitive_config(decryptor, v)))
                .collect(),
        ),
        Value::Array(items) => Value::Array(
            items
                .iter()
                .map(|v| decrypt_sensitive_config(decryptor, v))
                .collect(),
        ),
        Value::String(s) => match decryptor.decrypt_leaf(s) {
            Some(plaintext) => Value::String(plaintext),
            None => Value::String(s.clone()),
        },
        other => other.clone(),
    }
}
