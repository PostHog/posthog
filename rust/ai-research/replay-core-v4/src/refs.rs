//! Image and URL references, which stand in for an image in a v4 block, and the URL fingerprints of the block index.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;

/// The length v3 truncates a reference hash to: 132 bits of the HMAC.
const HASH_CHARS: usize = 22;
/// 64 bits of the HMAC: enough to tell the pages of one session apart.
const FINGERPRINT_BYTES: usize = 8;

/// The keyed hash in a reference. It is keyed so that a person holding a reference cannot test it against a known
/// image or URL.
pub fn reference_hash(key: &[u8; 32], bytes: &[u8]) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).expect("HMAC takes a key of any length");
    mac.update(bytes);
    let mut encoded = URL_SAFE_NO_PAD.encode(mac.finalize().into_bytes());
    encoded.truncate(HASH_CHARS);
    encoded
}

pub fn image_ref(team_id: i64, key_month: &str, hash: &str) -> String {
    format!("image:v4:{team_id}:{key_month}:{hash}")
}

pub fn image_url_ref(team_id: i64, key_month: &str, hash: &str) -> String {
    format!("imageurl:v4:{team_id}:{key_month}:{hash}")
}

/// A page URL as the block index shows it in plaintext: lowercase hex of the HMAC under
/// [`crate::seal::url_fingerprint_key`].
pub fn url_fingerprint(key: &[u8; 32], url: &str) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(key).expect("HMAC takes a key of any length");
    mac.update(url.as_bytes());
    mac.finalize().into_bytes()[..FINGERPRINT_BYTES]
        .iter()
        .map(|byte| format!("{byte:02x}"))
        .collect()
}
