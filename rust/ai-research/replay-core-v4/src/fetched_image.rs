//! The frame the image fetcher stores for each fetched image. The fetcher seals it through `replay-core-v4-node`, and a
//! reader rebuilds its context from the image's URL reference.

use posthog_replay_anonymizer::v4_image_refs::{parse, Parsed, Ref, RefKind};

use crate::envelope::{seal_frame, Codec, Context, EnvelopeError, Version};
use crate::refs::reference_hash;
use crate::seal::image_url_key;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum SealError {
    #[error("not an image URL reference")]
    NotAnImageUrlReference,
    #[error(transparent)]
    Envelope(#[from] EnvelopeError),
}

pub fn image_url_ref(reference: &str) -> Option<Ref<'_>> {
    match parse(reference)? {
        Parsed::Ref(parsed) if parsed.kind == RefKind::ImageUrl => Some(parsed),
        _ => None,
    }
}

pub fn fetched_image_context(reference: &str) -> Option<Context> {
    let parsed = image_url_ref(reference)?;
    Some(Context {
        team_id: parsed.team_id,
        key_month: Some(parsed.key_month.to_owned()),
        kind: "image-url".to_owned(),
        codec: Some(Codec::None),
        reference: Some(reference.to_owned()),
        ..Context::default()
    })
}

pub fn seal_fetched_image(
    team_month_key: &[u8; 32],
    reference: &str,
    image: &[u8],
) -> Result<Vec<u8>, SealError> {
    let context = fetched_image_context(reference).ok_or(SealError::NotAnImageUrlReference)?;
    Ok(seal_frame(team_month_key, Version::V4, &context, image)?)
}

pub fn image_url_hash(team_month_key: &[u8; 32], url: &str) -> String {
    reference_hash(&image_url_key(team_month_key), url.as_bytes())
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::envelope::open_frame;

    const REFERENCE: &str = "imageurl:v4:7:2026-10:TEX0ajC0UkaOC9js5c7oqr";

    #[test]
    fn seals_an_image_only_under_an_image_url_reference() {
        let key = [3; 32];
        let frame = seal_fetched_image(&key, REFERENCE, b"png").unwrap();
        let context = fetched_image_context(REFERENCE).unwrap();
        assert_eq!(
            open_frame(&key, Version::V4, &context, &frame).unwrap(),
            b"png"
        );
        for reference in [
            "image:v4:7:2026-10:TEX0ajC0UkaOC9js5c7oqr",
            "imageurl:v4:07:2026-10:TEX0ajC0UkaOC9js5c7oqr",
            "imageurl:v4:7:2026-13:TEX0ajC0UkaOC9js5c7oqr",
            "imageurl:v4:declined:credential",
        ] {
            assert_eq!(
                seal_fetched_image(&key, reference, b"png"),
                Err(SealError::NotAnImageUrlReference),
                "{reference}"
            );
        }
    }
}
