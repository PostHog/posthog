//! The keyed hash of the image and URL references in `posthog_replay_anonymizer::v4_image_refs`, and the URL
//! fingerprints of the block index.

use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use hmac::{Hmac, Mac};
use posthog_replay_anonymizer::v4_image_refs::HASH_CHARS;
use sha2::Sha256;

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
