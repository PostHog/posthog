//! The frame the image fetcher stores for each fetched image or font file. The fetcher seals it through
//! `replay-core-v4-node`, and a reader rebuilds its context from the file's URL reference. A public font file belongs
//! to no team, so the fetcher stores it unsealed.

use crate::v4_image_refs::{parse, Parsed, Ref, RefKind};

use crate::envelope::{seal_frame, Codec, Context, EnvelopeError, Version};
use crate::refs::{public_font_url_ref, reference_hash, UrlAsset};
use crate::seal::image_url_key;
use crate::url_policy::canonicalize;

#[derive(Debug, thiserror::Error, PartialEq, Eq)]
pub enum SealError {
    #[error("not a team URL reference")]
    NotATeamUrlReference,
    #[error(transparent)]
    Envelope(#[from] EnvelopeError),
}

/// A reference to a file that the image fetcher fetches and stores.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum FetchedRef<'a> {
    Team { asset: UrlAsset, parsed: Ref<'a> },
    PublicFont { hash: &'a str },
}

pub fn fetched_url_ref(reference: &str) -> Option<FetchedRef<'_>> {
    match parse(reference)? {
        Parsed::Ref(parsed) if parsed.kind == RefKind::ImageUrl => Some(FetchedRef::Team {
            asset: UrlAsset::Image,
            parsed,
        }),
        Parsed::Ref(parsed) if parsed.kind == RefKind::FontUrl => Some(FetchedRef::Team {
            asset: UrlAsset::Font,
            parsed,
        }),
        Parsed::PublicFont(hash) => Some(FetchedRef::PublicFont { hash }),
        _ => None,
    }
}

pub fn fetched_image_context(reference: &str) -> Option<Context> {
    let Some(FetchedRef::Team { asset, parsed }) = fetched_url_ref(reference) else {
        return None;
    };
    let kind = match asset {
        UrlAsset::Image => "image-url",
        UrlAsset::Font => "font-url",
    };
    Some(Context {
        team_id: parsed.team_id,
        key_month: Some(parsed.key_month.to_owned()),
        kind: kind.to_owned(),
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
    let context = fetched_image_context(reference).ok_or(SealError::NotATeamUrlReference)?;
    Ok(seal_frame(team_month_key, Version::V4, &context, image)?)
}

pub fn image_url_hash(team_month_key: &[u8; 32], url: &str) -> String {
    reference_hash(&image_url_key(team_month_key), url.as_bytes())
}

/// The public font reference that a fetch URL names, which the fetcher compares with a job's reference so that a
/// redirect target never becomes the shared file.
pub fn public_font_ref_of(fetch_url: &str) -> Option<String> {
    public_font_url_ref(&canonicalize(fetch_url)?)
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::envelope::open_frame;

    const REFERENCE: &str = "imageurl:v4:7:2026-10:TEX0ajC0UkaOC9js5c7oqr";
    const FONT_REFERENCE: &str = "fonturl:v4:7:2026-10:Bwu1146AUxxsfd2I6Co_JI";

    #[test]
    fn seals_a_file_only_under_a_team_url_reference() {
        let key = [3; 32];
        for (reference, kind) in [(REFERENCE, "image-url"), (FONT_REFERENCE, "font-url")] {
            let frame = seal_fetched_image(&key, reference, b"bytes").unwrap();
            let context = fetched_image_context(reference).unwrap();
            assert_eq!(context.kind, kind);
            assert_eq!(
                open_frame(&key, Version::V4, &context, &frame).unwrap(),
                b"bytes"
            );
        }
        for reference in [
            "image:v4:7:2026-10:TEX0ajC0UkaOC9js5c7oqr",
            "imageurl:v4:07:2026-10:TEX0ajC0UkaOC9js5c7oqr",
            "imageurl:v4:7:2026-13:TEX0ajC0UkaOC9js5c7oqr",
            "imageurl:v4:declined:credential",
            "fonturl:v4:public:I6bjVBXgjPcaYLPITibNM4",
            "fonturl:v4:bundled:roboto",
        ] {
            assert_eq!(
                seal_fetched_image(&key, reference, b"bytes"),
                Err(SealError::NotATeamUrlReference),
                "{reference}"
            );
        }
    }
}
