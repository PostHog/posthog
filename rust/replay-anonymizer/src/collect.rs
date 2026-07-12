//! Collect original image bytes for the out-of-band scrub lane.
//!
//! With collection enabled (an [`ImageCollection`] on the anonymize call), each inlined image is
//! replaced by a stable content reference — `image:<pseudoTeam>:<hash>` — instead of the native
//! blur, and the original bytes ride back to the caller on the message. The caller produces them
//! to the `session_replay_image_scrub` Kafka topic keyed by the ref; the scrub consumer re-hashes
//! the bytes against the key, blurs them out of process, and writes them to the ML bucket indexed
//! by `(pseudo_team, hash)` — so the ref embedded in the mirrored lines is the join key.
//!
//! The hash is pinned to the consumer's `hashImageBytes` (`ml-mirror-image-scrub/content-ref.ts`)
//! by the shared `image-hash.json` fixture: any divergence makes the consumer drop every produced
//! message as a key/bytes mismatch.

use std::collections::HashSet;

use base64::Engine;
use sha2::{Digest, Sha256};

/// First 22 base64url chars of the sha256, exactly as `hashImageBytes` computes it.
pub fn hash_image_bytes(bytes: &[u8]) -> String {
    let digest = Sha256::digest(bytes);
    let mut b64 = base64::engine::general_purpose::URL_SAFE_NO_PAD.encode(digest);
    b64.truncate(22);
    b64
}

pub fn image_ref(pseudo_team: &str, hash: &str) -> String {
    format!("image:{pseudo_team}:{hash}")
}

/// True for strings shaped like a content ref. The `image:` prefix cannot collide with a data URI,
/// a URL (no scheme is registered as `image`), or base64 payloads (`:` is not in the alphabet).
pub fn is_image_ref(s: &str) -> bool {
    s.starts_with("image:")
}

/// Per-image cap: a collected image must fit in one Kafka message on the scrub topic with headroom
/// under the broker's 1 MB default. Bigger images stay on the inline blur path.
pub const MAX_IMAGE_BYTES: usize = 900 * 1024;
/// Per-message caps bound what one payload can pin in memory and fan out onto the scrub topic;
/// images past them stay on the inline blur path.
pub const MAX_IMAGES_PER_MESSAGE: usize = 64;
pub const MAX_TOTAL_BYTES_PER_MESSAGE: usize = 8 * 1024 * 1024;

/// Enables collection for one anonymize call.
#[derive(Debug, Clone)]
pub struct ImageCollection {
    /// The non-reversible HMAC team pseudonym (32 hex chars), computed by the caller — the secret
    /// never crosses into this crate. Embedded verbatim in every emitted ref.
    pub pseudo_team: String,
}

pub struct CollectedImage {
    pub hash: String,
    pub bytes: Vec<u8>,
}

/// Accumulates the images of one message. Byte-level dedup on the hash: the same image arriving
/// under different URIs (or after the per-URI memo misses) is collected once but still gets its ref.
pub struct ImageCollector {
    pseudo_team: String,
    images: Vec<CollectedImage>,
    seen: HashSet<String>,
    total_bytes: usize,
}

impl ImageCollector {
    pub fn new(collection: ImageCollection) -> Self {
        Self {
            pseudo_team: collection.pseudo_team,
            images: Vec::new(),
            seen: HashSet::new(),
            total_bytes: 0,
        }
    }

    /// Collect decoded image bytes and return their ref, or `None` when a cap says this image must
    /// stay on the inline blur path.
    pub fn collect(&mut self, bytes: Vec<u8>) -> Option<String> {
        if bytes.len() > MAX_IMAGE_BYTES {
            return None;
        }
        let hash = hash_image_bytes(&bytes);
        if self.seen.contains(&hash) {
            return Some(image_ref(&self.pseudo_team, &hash));
        }
        if self.images.len() >= MAX_IMAGES_PER_MESSAGE
            || self.total_bytes + bytes.len() > MAX_TOTAL_BYTES_PER_MESSAGE
        {
            return None;
        }
        self.total_bytes += bytes.len();
        self.seen.insert(hash.clone());
        self.images.push(CollectedImage {
            hash: hash.clone(),
            bytes,
        });
        Some(image_ref(&self.pseudo_team, &hash))
    }

    /// Drain, sorted by hash — a deterministic order that cannot depend on which scrub engine
    /// walked the message (the differential tests assert meta equality across both).
    pub fn into_images(mut self) -> Vec<CollectedImage> {
        self.images.sort_by(|a, b| a.hash.cmp(&b.hash));
        self.images
    }
}

/// Decode the collectable payload of an image data URI. `None` (not collectable) for anything but
/// a base64 raster image: SVG is a text format whose PII must stay on the inline scrub path, and
/// non-base64 payloads mirror `blur_image_data_uri`'s refusal.
pub fn collectable_data_uri_bytes(uri: &str) -> Option<Vec<u8>> {
    let rest = uri.strip_prefix("data:")?;
    let (meta, payload) = rest.split_once(',')?;
    if !meta.starts_with("image/") || !meta.contains("base64") {
        return None;
    }
    if meta.starts_with("image/svg") {
        return None;
    }
    base64::engine::general_purpose::STANDARD
        .decode(payload.as_bytes())
        .ok()
}

#[cfg(test)]
mod tests {
    use super::*;

    fn collector() -> ImageCollector {
        ImageCollector::new(ImageCollection {
            pseudo_team: "a".repeat(32),
        })
    }

    #[test]
    fn hash_is_22_base64url_chars() {
        let hash = hash_image_bytes(b"hello world");
        assert_eq!(hash.len(), 22);
        assert!(hash
            .chars()
            .all(|c| c.is_ascii_alphanumeric() || c == '-' || c == '_'));
    }

    #[test]
    fn ref_matches_consumer_shape() {
        // The consumer's REF_RE: image:<32 hex>:<22 base64url>.
        let r = image_ref(&"ab".repeat(16), &hash_image_bytes(b"x"));
        assert!(is_image_ref(&r));
        let parts: Vec<&str> = r.splitn(3, ':').collect();
        assert_eq!(parts[0], "image");
        assert_eq!(parts[1].len(), 32);
        assert_eq!(parts[2].len(), 22);
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
        assert!(c.collect(vec![0u8; MAX_IMAGE_BYTES + 1]).is_none());
        assert!(c.into_images().is_empty());
    }

    #[test]
    fn collect_stops_at_the_per_message_count_cap_but_still_refs_seen_images() {
        let mut c = collector();
        for i in 0..MAX_IMAGES_PER_MESSAGE {
            assert!(c.collect(i.to_le_bytes().to_vec()).is_some());
        }
        assert!(c.collect(b"one too many".to_vec()).is_none());
        // A repeat of an already-collected image still resolves to its ref.
        assert!(c.collect(0usize.to_le_bytes().to_vec()).is_some());
        assert_eq!(c.into_images().len(), MAX_IMAGES_PER_MESSAGE);
    }

    #[test]
    fn into_images_sorts_by_hash() {
        let mut c = collector();
        c.collect(b"bbb".to_vec());
        c.collect(b"aaa".to_vec());
        let images = c.into_images();
        assert!(images[0].hash < images[1].hash);
    }

    #[test]
    fn collectable_rejects_svg_non_base64_and_non_image() {
        assert!(collectable_data_uri_bytes("data:image/svg+xml;base64,PHN2Zz4=").is_none());
        assert!(collectable_data_uri_bytes("data:image/svg+xml;utf8,<svg/>").is_none());
        assert!(collectable_data_uri_bytes("data:text/plain;base64,aGk=").is_none());
        assert!(collectable_data_uri_bytes("data:image/png;utf8,notbase64").is_none());
        assert!(collectable_data_uri_bytes("data:image/png;base64,%%%").is_none());
        assert_eq!(
            collectable_data_uri_bytes("data:image/png;base64,aGVsbG8=").as_deref(),
            Some(b"hello".as_slice())
        );
    }
}
