//! The images one replay message collected, held outside the V8 heap until the produce claims them.

use posthog_replay_anonymizer::collect::image_ref;
use posthog_replay_anonymizer::snapshot::ImageEntry;

use crate::dedup::{image_ref_key, DedupKey, RefDedupCache};

struct CollectedImage {
    reference: String,
    key: DedupKey,
    bytes: Vec<u8>,
}

#[derive(Debug, Default, PartialEq)]
pub struct ClaimedImages {
    pub references: Vec<String>,
    pub images: Vec<Vec<u8>>,
    pub bytes: usize,
}

#[derive(Debug, PartialEq, Eq)]
pub struct AlreadyClaimed;

pub struct ImageBatch {
    first_ref: String,
    count: usize,
    unclaimed: Option<Vec<CollectedImage>>,
    claimed_keys: Vec<DedupKey>,
}

impl ImageBatch {
    pub fn collect(
        namespace: &str,
        entries: Vec<ImageEntry>,
        packed: &[u8],
        produced: Option<&RefDedupCache>,
    ) -> (Option<Self>, usize) {
        let mut pending: Vec<(ImageEntry, String, DedupKey)> = entries
            .into_iter()
            .map(|entry| {
                let reference = image_ref(namespace, &entry.hash);
                let key = image_ref_key(&reference);
                (entry, reference, key)
            })
            .collect();
        let deduped = produced.map_or(0, |cache| cache.retain_absent(&mut pending, |item| item.2));
        // One copy per image off the event loop, so that each image moves into its own Kafka value.
        // Views into one shared buffer would keep every image alive until the last one is freed.
        let images = pending
            .into_iter()
            .filter_map(|(entry, reference, key)| {
                let end = entry.offset.checked_add(entry.len)?;
                let bytes = packed.get(entry.offset..end)?.to_vec();
                Some(CollectedImage {
                    reference,
                    key,
                    bytes,
                })
            })
            .collect();
        (Self::from_collected(images), deduped)
    }

    pub fn from_images(namespace: &str, images: Vec<(String, Vec<u8>)>) -> Option<Self> {
        Self::from_collected(
            images
                .into_iter()
                .map(|(hash, bytes)| {
                    let reference = image_ref(namespace, &hash);
                    CollectedImage {
                        key: image_ref_key(&reference),
                        reference,
                        bytes,
                    }
                })
                .collect(),
        )
    }

    fn from_collected(images: Vec<CollectedImage>) -> Option<Self> {
        let first_ref = images.first()?.reference.clone();
        Some(Self {
            first_ref,
            count: images.len(),
            unclaimed: Some(images),
            claimed_keys: Vec::new(),
        })
    }

    pub fn count(&self) -> usize {
        self.count
    }

    pub fn first_ref(&self) -> &str {
        &self.first_ref
    }

    pub fn claim(&mut self, cache: &RefDedupCache) -> Result<ClaimedImages, AlreadyClaimed> {
        let images = self.unclaimed.take().ok_or(AlreadyClaimed)?;
        let keys: Vec<DedupKey> = images.iter().map(|image| image.key).collect();
        let mut claimed = ClaimedImages::default();
        for (image, is_claimed) in images.into_iter().zip(cache.claim(&keys)) {
            if is_claimed {
                claimed.bytes += image.bytes.len();
                self.claimed_keys.push(image.key);
                claimed.references.push(image.reference);
                claimed.images.push(image.bytes);
            }
        }
        Ok(claimed)
    }

    pub fn release(&mut self, cache: &RefDedupCache) {
        cache.release(&std::mem::take(&mut self.claimed_keys));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn entry(hash: &str, offset: usize, len: usize) -> ImageEntry {
        ImageEntry {
            hash: hash.to_string(),
            offset,
            len,
        }
    }

    #[test]
    fn leaves_out_a_produced_image_and_keeps_the_bytes_of_the_rest() {
        let cache = RefDedupCache::new(10);
        cache.claim(&[image_ref_key(&image_ref("7", "first"))]);

        let (batch, deduped) = ImageBatch::collect(
            "7",
            vec![entry("first", 0, 3), entry("second", 3, 2)],
            b"aaabb",
            Some(&cache),
        );
        let mut batch = batch.unwrap();

        assert_eq!(deduped, 1);
        assert_eq!(batch.first_ref(), "image:7:second");
        assert_eq!(
            batch.claim(&RefDedupCache::new(10)),
            Ok(ClaimedImages {
                references: vec!["image:7:second".to_string()],
                images: vec![b"bb".to_vec()],
                bytes: 2,
            })
        );
    }

    #[test]
    fn a_released_claim_produces_again_and_a_second_claim_is_refused() {
        let cache = RefDedupCache::new(10);
        let images = || vec![("h1".to_string(), b"a".to_vec())];
        let mut first = ImageBatch::from_images("7", images()).unwrap();
        assert_eq!(first.claim(&cache).unwrap().references.len(), 1);
        assert_eq!(first.claim(&cache), Err(AlreadyClaimed));

        let mut duplicate = ImageBatch::from_images("7", images()).unwrap();
        assert_eq!(duplicate.claim(&cache).unwrap().references.len(), 0);

        first.release(&cache);
        let mut after_release = ImageBatch::from_images("7", images()).unwrap();
        assert_eq!(after_release.claim(&cache).unwrap().references.len(), 1);
    }
}
