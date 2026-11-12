//! The keyed hash of the image and URL references in `crate::v4_image_refs`, the asset of a URL reference, and the URL fingerprints of the block index.

use crate::v4_image_refs::{
    font_url_declined_marker, font_url_ref, image_url_ref, public_font_ref, url_declined_marker,
    HASH_CHARS,
};
use base64::engine::general_purpose::URL_SAFE_NO_PAD;
use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::{Digest, Sha256};

use crate::url_policy::{redaction, CanonicalUrl, Decline, Redaction, MAX_URL_LEN};

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

/// Google serves each file under `/s/` at a versioned path whose bytes never change. A `/l/` file is a subset that a page's `text=` parameter picked, so its glyphs can hold page text, and it stays with its team.
const PUBLIC_FONT_HOST: &str = "fonts.gstatic.com";
const PUBLIC_FONT_PATH_PREFIX: &str = "/s/";

/// The hash has no key because the URL holds no personal data, so anyone can test a reference against a Google Fonts URL.
pub fn public_font_url_ref(url: &CanonicalUrl) -> Option<String> {
    let parsed = url::Url::parse(&url.fetch).ok()?;
    let shared = parsed.scheme() == "https"
        && parsed.host_str() == Some(PUBLIC_FONT_HOST)
        && parsed.port().is_none()
        && parsed.path().starts_with(PUBLIC_FONT_PATH_PREFIX)
        && parsed.query().is_none();
    shared.then(|| public_font_ref(&public_url_hash(&url.fetch)))
}

/// The unkeyed hash of a public font reference, which the fetcher also binds the font's cached validators with.
pub fn public_url_hash(url: &str) -> String {
    let mut encoded = URL_SAFE_NO_PAD.encode(Sha256::digest(url.as_bytes()));
    encoded.truncate(HASH_CHARS);
    encoded
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord)]
pub enum UrlAsset {
    Image,
    Font,
}

pub fn url_ref(asset: UrlAsset, team_id: i64, key_month: &str, hash: &str) -> String {
    match asset {
        UrlAsset::Image => image_url_ref(team_id, key_month, hash),
        UrlAsset::Font => font_url_ref(team_id, key_month, hash),
    }
}

/// A URL that no reference names, as a block keeps it: without its credentials, or as a decline marker when the
/// redaction cannot read it. `None` when the block keeps the URL as it is.
pub fn unnamed_url(raw: &str, asset: UrlAsset) -> Option<String> {
    match redaction(raw) {
        Redaction::Clean => None,
        Redaction::Redacted(kept) => Some(kept),
        Redaction::Unread if raw.len() > MAX_URL_LEN => {
            Some(declined_url_ref(asset, Decline::TooLong))
        }
        Redaction::Unread => Some(declined_url_ref(asset, Decline::NotAbsolute)),
    }
}

pub fn declined_url_ref(asset: UrlAsset, reason: Decline) -> String {
    match asset {
        UrlAsset::Image => url_declined_marker(reason),
        UrlAsset::Font => font_url_declined_marker(reason),
    }
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
