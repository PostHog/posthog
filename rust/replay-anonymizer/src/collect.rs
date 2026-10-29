//! Collect original image bytes for the out-of-band scrub lane.
//!
//! With collection enabled (an [`ImageCollection`] on the anonymize call), each inlined image is
//! replaced by a stable content reference, `image:<teamId>:<hash>`, and the original bytes ride
//! back to the caller on the message. An image the lane cannot take is blanked instead. The caller
//! produces them to the `session_replay_image_scrub` Kafka topic keyed by the ref; the scrub
//! consumer trusts the ref (this producer is the only writer), scrubs the bytes out of process, and
//! writes them to the ML bucket indexed by `(team_id, hash)`, so the ref embedded in the mirrored
//! lines is the join key.
//!
//! The hash is a *keyed* HMAC, not a plain digest: the ML bucket is unencrypted, and a plain
//! content hash would let any bucket reader confirm whether specific known bytes appeared in a
//! session (and correlate identical images across teams). The per-team key is derived by the
//! caller from the KMS-held pseudonymization secret, which never leaves the ingester.
//! `image-hash.json` pins the construction against Node `createHmac` reference vectors.

use std::collections::HashSet;

use base64::Engine;
use hmac::{Hmac, Mac};
use sha2::Sha256;

/// First 22 base64url chars of `HMAC-SHA256(content_key, bytes)`.
pub fn hash_image_bytes(content_key: &[u8], bytes: &[u8]) -> String {
    let mut mac = Hmac::<Sha256>::new_from_slice(content_key).expect("hmac accepts any key length");
    mac.update(bytes);
    let digest = mac.finalize().into_bytes();
    let mut b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest);
    b64.truncate(22);
    b64
}

pub fn image_ref(team_id: &str, hash: &str) -> String {
    format!("image:{team_id}:{hash}")
}

/// The prefix of a ref whose hash comes from a URL rather than from bytes.
///
/// Deliberately not `image:`. A content ref promises that the hash names the bytes behind it, which
/// is what lets a reader treat one as content-addressed. A URL ref promises only that the hash
/// names the URL the image came from, and the bytes at that URL can change. Sharing one prefix
/// would leave a reader unable to tell which promise it holds, and the failure would be a silent
/// mis-join rather than an error.
pub const URL_REF_PREFIX: &str = "imageurl";

pub fn url_ref(hash: &str) -> String {
    format!("{URL_REF_PREFIX}:{hash}")
}

/// True for strings shaped like a content ref. The `image:` prefix cannot collide with a data URI,
/// a URL (no scheme is registered as `image`), or base64 payloads (`:` is not in the alphabet).
///
/// Only sound on values this crate produced. To decide whether a value *read back out of a payload*
/// may skip scrubbing, use [`is_image_ref_strict`]: capture input is attacker-controlled and this
/// prefix is trivial to forge.
pub fn is_image_ref(s: &str) -> bool {
    s.starts_with("image:")
}

/// True only for a fully well-formed content ref or URL ref.
///
/// The loose prefix check would let a captured page set a media attribute to `image:<anything>` and
/// have it copied verbatim into anonymized output. Limit preserved refs to a numeric team ID
/// or legacy pseudonym and a fixed-width hash.
pub fn is_image_ref_strict(s: &str) -> bool {
    if let Some(rest) = ["image:v2:", "image:v3:", "imageurl:v2:", "imageurl:v3:"]
        .iter()
        .find_map(|prefix| s.strip_prefix(prefix))
    {
        let parts: Vec<&str> = rest.split(':').collect();
        return parts.len() == 3
            && is_raw_team_id(parts[0])
            && parts[1].len() == 7
            && parts[1].as_bytes()[..4].iter().all(u8::is_ascii_digit)
            && parts[1].as_bytes()[4] == b'-'
            && matches!(
                &parts[1][5..],
                "01" | "02" | "03" | "04" | "05" | "06" | "07" | "08" | "09" | "10" | "11" | "12"
            )
            && is_ref_hash(parts[2]);
    }
    if let Some(rest) = s.strip_prefix("image:") {
        let Some((team, hash)) = rest.split_once(':') else {
            return false;
        };
        return (is_raw_team_id(team) || is_legacy_team_pseudonym(team)) && is_ref_hash(hash);
    }
    if let Some(rest) = s.strip_prefix("imageurl:") {
        return is_ref_hash(rest)
            || rest
                .split_once(':')
                .is_some_and(|(team, hash)| is_legacy_team_pseudonym(team) && is_ref_hash(hash));
    }
    false
}

fn is_legacy_team_pseudonym(team: &str) -> bool {
    team.len() == 32
        && team
            .bytes()
            .all(|b| b.is_ascii_digit() || b.is_ascii_lowercase() && b <= b'f')
}

fn is_raw_team_id(team: &str) -> bool {
    !team.starts_with('0')
        && !team.is_empty()
        && team.len() <= 16
        && team.bytes().all(|b| b.is_ascii_digit())
        && team
            .parse::<u64>()
            .is_ok_and(|id| id <= 9_007_199_254_740_991)
}

fn is_ref_hash(hash: &str) -> bool {
    hash.len() == 22
        && hash
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

/// Default per-image cap: the image-scrub consumer and its sidecar refuse decoded images over
/// 20 MiB, so a bigger image would only dangle as a ref. A bigger image is blanked.
pub const MAX_IMAGE_BYTES: usize = 20 * 1024 * 1024;
/// Per-message caps bound what one payload can pin in memory and fan out onto the scrub topic.
/// Capture refuses messages over 64 MB, so the byte cap only binds on a payload that cv nesting
/// expanded past that. Collection peaks at about twice the byte cap per in-flight message
/// (collector vec plus the packed FFI buffer).
pub const MAX_IMAGES_PER_MESSAGE: usize = 4096;
pub const MAX_TOTAL_BYTES_PER_MESSAGE: usize = 64 * 1024 * 1024;

/// Why an image did not reach the scrub lane. Each one is blanked and counted under this reason.
pub(crate) const DROP_COLLECTION_OFF: &str = "image_collection_off";
pub(crate) const DROP_NOT_RASTER: &str = "image_not_base64_raster";
pub const DROP_SVG: &str = "image_svg";
pub const DROP_SVG_TOO_COMPLEX: &str = "image_svg_too_complex";
pub(crate) const DROP_BMP: &str = "image_bmp";
pub(crate) const DROP_AVIF: &str = "image_avif";
pub(crate) const DROP_TOO_LARGE: &str = "image_too_large";
pub(crate) const DROP_MESSAGE_CAP: &str = "image_message_cap";

/// Enables collection for one anonymize call.
#[derive(Debug, Clone)]
pub struct ImageCollection {
    pub team_id: String,
    /// Per-team key for the content HMAC, derived by the caller. Its ASCII
    /// bytes key [`hash_image_bytes`].
    pub content_key: String,
    pub max_image_bytes: usize,
}

impl ImageCollection {
    pub fn new(team_id: String, content_key: String) -> Self {
        Self {
            team_id,
            content_key,
            max_image_bytes: MAX_IMAGE_BYTES,
        }
    }
}

pub struct CollectedImage {
    pub hash: String,
    pub bytes: Vec<u8>,
}

/// Accumulates the images of one message. Byte-level dedup on the hash: the same image arriving
/// under different URIs (or after the per-URI memo misses) is collected once but still gets its ref.
pub struct ImageCollector {
    team_id: String,
    content_key: String,
    max_image_bytes: usize,
    images: Vec<CollectedImage>,
    seen: HashSet<String>,
    total_bytes: usize,
}

impl ImageCollector {
    pub fn new(collection: ImageCollection) -> Self {
        Self {
            team_id: collection.team_id,
            content_key: collection.content_key,
            max_image_bytes: collection.max_image_bytes,
            images: Vec::new(),
            seen: HashSet::new(),
            total_bytes: 0,
        }
    }

    pub fn max_image_bytes(&self) -> usize {
        self.max_image_bytes
    }

    pub(crate) fn len(&self) -> usize {
        self.images.len()
    }

    pub(crate) fn truncate(&mut self, len: usize) -> HashSet<String> {
        let mut removed = HashSet::new();
        for image in self.images.drain(len.min(self.images.len())..) {
            self.total_bytes -= image.bytes.len();
            self.seen.remove(&image.hash);
            removed.insert(image_ref(&self.team_id, &image.hash));
        }
        removed
    }

    pub fn collect(&mut self, bytes: Vec<u8>) -> Result<String, &'static str> {
        if bytes.len() > self.max_image_bytes {
            return Err(DROP_TOO_LARGE);
        }
        let hash = hash_image_bytes(self.content_key.as_bytes(), &bytes);
        if self.seen.contains(&hash) {
            return Ok(image_ref(&self.team_id, &hash));
        }
        if self.images.len() >= MAX_IMAGES_PER_MESSAGE
            || self.total_bytes + bytes.len() > MAX_TOTAL_BYTES_PER_MESSAGE
        {
            return Err(DROP_MESSAGE_CAP);
        }
        self.total_bytes += bytes.len();
        self.seen.insert(hash.clone());
        self.images.push(CollectedImage {
            hash: hash.clone(),
            bytes,
        });
        Ok(image_ref(&self.team_id, &hash))
    }

    /// Drain, sorted by hash — a deterministic order that cannot depend on which scrub engine
    /// walked the message (the differential tests assert meta equality across both).
    pub fn into_images(mut self) -> Vec<CollectedImage> {
        self.images.sort_by(|a, b| a.hash.cmp(&b.hash));
        self.images
    }
}

/// Raster subtypes preserved on a collected canvas blob's `type` field — downstream replay
/// reassembly uses it as the format hint for the image behind the ref. Anything else (unknown
/// subtypes, parameters — where client-controlled text could ride through unscrubbed) normalizes
/// to `image/png`. Exact matches only, so no client string survives in this field.
const COLLECTED_MIME_ALLOWLIST: &[&str] = &["image/png", "image/jpeg", "image/gif", "image/webp"];

pub fn normalize_collected_mime(mime: &str) -> &'static str {
    let lower = mime.trim().to_ascii_lowercase();
    COLLECTED_MIME_ALLOWLIST
        .iter()
        .find(|allowed| **allowed == lower)
        .copied()
        .unwrap_or("image/png")
}

/// Decode the collectable payload of an image data URI, or name why it is not one: only a base64
/// raster image the scrub can decode qualifies. MIME types are case-insensitive, so the checks run
/// on a lowercased meta — `image/SVG+xml` must not dodge the SVG exclusion.
pub fn collectable_data_uri_bytes(
    uri: &str,
    max_image_bytes: usize,
) -> Result<Vec<u8>, &'static str> {
    let (meta, payload) = uri
        .strip_prefix("data:")
        .and_then(|rest| rest.split_once(','))
        .ok_or(DROP_NOT_RASTER)?;
    let meta = meta.to_ascii_lowercase();
    let mime_type = meta
        .split_once(';')
        .map_or(meta.as_str(), |(mime_type, _)| mime_type);
    if mime_type.starts_with("image/svg") {
        return crate::svg::svg_document(&meta, payload, max_image_bytes);
    }
    if !meta.starts_with("image/") || !meta.contains("base64") {
        return Err(DROP_NOT_RASTER);
    }
    if mime_type.contains("bmp") {
        return Err(DROP_BMP);
    }
    if mime_type.contains("avif") {
        return Err(DROP_AVIF);
    }
    // An encoded payload that can't decode under the per-image cap would be decoded here only to
    // be rejected by `collect` — bail on the encoded length instead.
    if payload.len() > max_image_bytes.div_ceil(3) * 4 {
        return Err(DROP_TOO_LARGE);
    }
    let bytes = base64::engine::general_purpose::STANDARD
        .decode(payload.as_bytes())
        .map_err(|_| DROP_NOT_RASTER)?;
    if bytes.starts_with(b"BM") {
        return Err(DROP_BMP);
    }
    // An ISO-BMFF container (AVIF, HEIC) under any label: the scrub refuses it, so a ref would dangle.
    if bytes.get(4..8) == Some(b"ftyp") {
        return Err(DROP_AVIF);
    }
    Ok(bytes)
}

#[cfg(test)]
mod tests {
    use super::*;

    fn collectable(uri: &str) -> Option<Vec<u8>> {
        collectable_data_uri_bytes(uri, MAX_IMAGE_BYTES).ok()
    }

    const TEST_KEY: &[u8] = b"0123456789abcdef0123456789abcdef";

    fn collector() -> ImageCollector {
        ImageCollector::new(ImageCollection::new(
            "a".repeat(32),
            String::from_utf8(TEST_KEY.to_vec()).unwrap(),
        ))
    }

    #[test]
    fn hash_is_22_base64url_chars_and_keyed() {
        let hash = hash_image_bytes(TEST_KEY, b"hello world");
        assert_eq!(hash.len(), 22);
        assert!(hash
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
        // Different keys must produce unrelated hashes for the same bytes — the keying is the
        // point (no unkeyed content oracle in the ML bucket).
        assert_ne!(hash, hash_image_bytes(b"another-key", b"hello world"));
    }

    #[test]
    fn ref_matches_consumer_shape() {
        let hash = hash_image_bytes(TEST_KEY, b"x");
        for prefix in ["image:v2", "imageurl:v2", "image:v3", "imageurl:v3"] {
            assert!(is_image_ref_strict(&format!("{prefix}:42:2026-09:{hash}")));
            for invalid in [
                "42:2026-13",
                "42:2026-00",
                "42:202-09",
                "42:2026-9",
                "0:2026-09",
                "42:2026_09",
                "42",
            ] {
                assert!(!is_image_ref_strict(&format!("{prefix}:{invalid}:{hash}")));
            }
        }
        for team in ["42", "9007199254740991", "0123456789abcdef0123456789abcdef"] {
            assert!(is_image_ref_strict(&image_ref(team, &hash)));
        }
        for team in ["0", "01", "-1", "9007199254740992", "1e3", "secret"] {
            assert!(!is_image_ref_strict(&image_ref(team, &hash)));
        }
    }

    #[test]
    fn collect_dedups_on_bytes_and_returns_the_same_ref() {
        let mut c = collector();
        let a = c.collect(vec![1, 2, 3]).unwrap();
        let b = c.collect(vec![1, 2, 3]).unwrap();
        assert_eq!(a, b);
        assert_eq!(c.into_images().len(), 1);
    }

    #[test]
    fn collect_rejects_oversized_image() {
        let mut c = collector();
        assert_eq!(
            c.collect(vec![0u8; MAX_IMAGE_BYTES + 1]),
            Err(DROP_TOO_LARGE)
        );
        // A 1 MiB image is within the default cap.
        assert!(c.collect(vec![1u8; 1024 * 1024]).is_ok());
        assert_eq!(c.into_images().len(), 1);
    }

    #[test]
    fn collect_stops_at_the_per_message_count_cap_but_still_refs_seen_images() {
        let mut c = collector();
        for i in 0..MAX_IMAGES_PER_MESSAGE {
            assert!(c.collect(i.to_le_bytes().to_vec()).is_ok());
        }
        assert_eq!(c.collect(b"one too many".to_vec()), Err(DROP_MESSAGE_CAP));
        // A repeat of an already-collected image still resolves to its ref.
        assert!(c.collect(0usize.to_le_bytes().to_vec()).is_ok());
        assert_eq!(c.into_images().len(), MAX_IMAGES_PER_MESSAGE);
    }

    #[test]
    fn into_images_sorts_by_hash() {
        let mut c = collector();
        c.collect(b"bbb".to_vec()).unwrap();
        c.collect(b"aaa".to_vec()).unwrap();
        let images = c.into_images();
        assert!(images[0].hash < images[1].hash);
    }

    #[test]
    fn collectable_rejects_broken_svg_non_base64_and_non_image() {
        assert!(collectable("data:image/svg+xml;base64,bm90IHN2Zw==").is_none());
        assert!(collectable("data:image/bmp;base64,Qk0=").is_none());
        assert!(collectable("data:image/x-bmp;base64,Qk0=").is_none());
        assert!(collectable("data:image/x-ms-bmp;base64,Qk0=").is_none());
        assert!(collectable("data:image/avif;base64,AAAAHGZ0eXBhdmlm").is_none());
        // AVIF bytes behind a raster label.
        assert!(collectable("data:image/png;base64,AAAAHGZ0eXBhdmlm").is_none());
        assert!(collectable("data:image/png;base64,Qk0=").is_none());
        assert_eq!(
            collectable("data:image/svg+xml;utf8,<svg/>").as_deref(),
            Some(b"<svg/>".as_slice())
        );
        assert!(collectable("data:text/plain;base64,aGk=").is_none());
        assert!(collectable("data:image/png;utf8,notbase64").is_none());
        assert!(collectable("data:image/png;base64,%%%").is_none());
        assert_eq!(
            collectable("data:image/png;base64,aGVsbG8=").as_deref(),
            Some(b"hello".as_slice())
        );
    }

    #[test]
    fn collectable_rejects_oversized_encoded_payload_without_decoding() {
        // 4/3 * MAX_IMAGE_BYTES encoded chars is the fit boundary; one full quartet past it means
        // the decoded bytes cannot fit, so it must bail before paying the decode.
        let over = "A".repeat(MAX_IMAGE_BYTES.div_ceil(3) * 4 + 4);
        assert!(collectable(&format!("data:image/png;base64,{over}")).is_none());
    }

    #[test]
    fn collected_mime_normalizes_to_the_allowlist() {
        assert_eq!(normalize_collected_mime("image/jpeg"), "image/jpeg");
        assert_eq!(normalize_collected_mime("IMAGE/WebP"), "image/webp");
        assert_eq!(normalize_collected_mime(" image/png "), "image/png");
        // Parameters and unknown subtypes are exactly where client text could ride through.
        assert_eq!(
            normalize_collected_mime("image/png;evil=payload"),
            "image/png"
        );
        assert_eq!(
            normalize_collected_mime("image/x-arbitrary-client-text"),
            "image/png"
        );
        assert_eq!(normalize_collected_mime("image/svg+xml"), "image/png");
    }

    #[test]
    fn collectable_mime_checks_are_case_insensitive() {
        // MIME types are case-insensitive; a mixed-case SVG must still take the SVG path, which
        // alone accepts a URL-encoded payload, and a mixed-case raster/base64 marker must collect.
        for uri in [
            "data:image/SVG+xml;utf8,<svg/>",
            "data:image/Svg+Xml;utf8,<svg/>",
        ] {
            assert_eq!(
                collectable(uri).as_deref(),
                Some(b"<svg/>".as_slice()),
                "{uri}"
            );
        }
        assert_eq!(
            collectable("data:image/PNG;BASE64,aGVsbG8=").as_deref(),
            Some(b"hello".as_slice())
        );
    }
}
