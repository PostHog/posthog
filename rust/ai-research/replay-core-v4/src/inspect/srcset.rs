//! The one `srcset` candidate the recorder keeps. A renderer picks a candidate for its viewport and shows nothing offline
//! for one the fetcher did not take, and each fetched image costs a scrub, so a srcset keeps one candidate: the one the
//! screenshotter's Chromium shows, at the device pixel ratio of 1 that it renders at.

use crate::scan::images::keeps_inline_image;
use crate::url_policy::{is_remote, try_canonicalize};

const MAX_SRCSET_WIDTH: f64 = 1024.0;
const SCREENSHOT_DEVICE_PIXEL_RATIO: f64 = 1.0;

#[derive(Clone, Copy, PartialEq, Eq)]
enum DescriptorKind {
    Density,
    Width,
}

struct Candidate<'a> {
    index: usize,
    url: &'a str,
    kind: DescriptorKind,
    value: f64,
}

impl Candidate<'_> {
    /// Of density descriptors, Chromium's choice at the screenshot's device pixel ratio: the smallest density at or
    /// above it, or the largest when all are below it (`SelectionLogic` in Blink's `html_srcset_parser.cc`). A width
    /// gives a density only against the layout width, which the recorder does not know, so of width descriptors this
    /// keeps the v3 choice (`rust/replay-anonymizer/src/srcset.rs`): the largest at or below 1024w, or the smallest
    /// when all are wider. A tie keeps `self`, so the first candidate wins it.
    fn loses_to(&self, other: &Candidate<'_>) -> bool {
        let (best, candidate) = (self.value, other.value);
        match self.kind {
            DescriptorKind::Density => {
                let target = SCREENSHOT_DEVICE_PIXEL_RATIO;
                match (best >= target, candidate >= target) {
                    (false, true) => true,
                    (true, true) => candidate < best,
                    (false, false) => candidate > best,
                    (true, false) => false,
                }
            }
            DescriptorKind::Width => {
                match (best <= MAX_SRCSET_WIDTH, candidate <= MAX_SRCSET_WIDTH) {
                    (false, true) => true,
                    (true, true) => candidate > best,
                    (false, false) => candidate < best,
                    (true, false) => false,
                }
            }
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct KeptCandidate<'s> {
    pub index: usize,
    pub url: &'s str,
    /// The srcset has no 1x candidate and no width descriptor, so HTML adds an img's non-empty `src` as a 1x candidate,
    /// which wins at the screenshot's device pixel ratio.
    pub yields_to_img_src: bool,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SrcsetSlot {
    /// Nothing else competes with the candidate: an img with no `src`, an img whose `src` the event does not hold, or
    /// a picture source of a type the fetcher stores.
    Alone,
    BesideImgSrc,
    /// A picture source of a type the fetcher does not store. A remote candidate there gets no fetch job, so only an
    /// inline one can show.
    UnfetchedTypeSource,
}

/// `None` for a malformed srcset, or one that mixes width and density descriptors.
pub fn kept_candidate(srcset: &str) -> Option<KeptCandidate<'_>> {
    let mut first_kind = None;
    let mut mixed = false;
    let mut kept: Option<Candidate<'_>> = None;
    for_each_candidate(srcset, |candidate| {
        let kind = *first_kind.get_or_insert(candidate.kind);
        mixed |= candidate.kind != kind;
        kept = Some(match kept.take() {
            Some(best) if !best.loses_to(&candidate) => best,
            _ => candidate,
        });
    })?;
    kept.filter(|_| !mixed).map(|candidate| KeptCandidate {
        index: candidate.index,
        url: candidate.url,
        yields_to_img_src: candidate.kind == DescriptorKind::Density
            && candidate.value != SCREENSHOT_DEVICE_PIXEL_RATIO,
    })
}

/// The kept candidate when it can show offline, as a URL the fetcher can take or an inline image the image scan keeps.
pub fn usable_candidate(srcset: &str) -> Option<KeptCandidate<'_>> {
    kept_candidate(srcset).filter(|kept| {
        if is_remote(kept.url) {
            try_canonicalize(kept.url).is_ok()
        } else {
            keeps_inline_image(kept.url)
        }
    })
}

/// The inspector fetches this candidate and the writer keeps only it, so that the two agree on what the slot shows.
pub fn shown_candidate(srcset: &str, slot: SrcsetSlot) -> Option<KeptCandidate<'_>> {
    usable_candidate(srcset).filter(|kept| match slot {
        SrcsetSlot::Alone => true,
        SrcsetSlot::BesideImgSrc => !kept.yields_to_img_src,
        SrcsetSlot::UnfetchedTypeSource => !is_remote(kept.url),
    })
}

/// Streams the candidates, so that a message-sized srcset needs no list of them. `None` for a malformed srcset.
fn for_each_candidate<'s>(srcset: &'s str, mut found: impl FnMut(Candidate<'s>)) -> Option<()> {
    let bytes = srcset.as_bytes();
    let mut index = 0;
    let mut position = 0;
    while position < bytes.len() {
        while matches!(bytes.get(position), Some(byte) if byte.is_ascii_whitespace()) {
            position += 1;
        }
        if position == bytes.len() {
            break;
        }
        if bytes[position] == b',' {
            return None;
        }

        let url_start = position;
        while matches!(bytes.get(position), Some(byte) if !byte.is_ascii_whitespace()) {
            position += 1;
        }
        let mut url_end = position;
        while bytes.get(url_end.wrapping_sub(1)) == Some(&b',') && url_end > url_start {
            url_end -= 1;
        }
        if url_end == url_start {
            return None;
        }
        if position - url_end > 1 {
            return None;
        }
        let url = &srcset[url_start..url_end];
        if !url.starts_with("data:") && url.contains(',') {
            return None;
        }
        let ended_with_comma = url_end < position;

        while matches!(bytes.get(position), Some(byte) if byte.is_ascii_whitespace()) {
            position += 1;
        }
        let descriptor_start = position;
        if !ended_with_comma {
            while matches!(bytes.get(position), Some(byte) if *byte != b',') {
                position += 1;
            }
        }
        let descriptor = srcset[descriptor_start..position].trim();
        let separated = if bytes.get(position) == Some(&b',') {
            position += 1;
            true
        } else {
            ended_with_comma
        };

        let (kind, value) = parse_descriptor(descriptor)?;
        found(Candidate {
            index,
            url,
            kind,
            value,
        });
        index += 1;
        if separated {
            let mut next = position;
            while matches!(bytes.get(next), Some(byte) if byte.is_ascii_whitespace()) {
                next += 1;
            }
            if next == bytes.len() || bytes[next] == b',' {
                return None;
            }
        }
    }
    Some(())
}

fn parse_descriptor(descriptor: &str) -> Option<(DescriptorKind, f64)> {
    if descriptor.is_empty() {
        return Some((DescriptorKind::Density, 1.0));
    }
    if descriptor.split_ascii_whitespace().count() != 1 {
        return None;
    }
    if let Some(width) = descriptor.strip_suffix('w') {
        let value = width.parse::<u32>().ok()?;
        return (value > 0).then_some((DescriptorKind::Width, f64::from(value)));
    }
    let density = descriptor.strip_suffix('x')?.parse::<f64>().ok()?;
    (density.is_finite() && density > 0.0).then_some((DescriptorKind::Density, density))
}

#[cfg(test)]
mod tests {
    use base64::engine::general_purpose::STANDARD;
    use base64::Engine;

    use super::*;

    fn kept_url(srcset: &str) -> Option<&str> {
        kept_candidate(srcset).map(|kept| kept.url)
    }

    #[test]
    fn keeps_the_density_chromium_shows_at_1x_and_the_v3_width() {
        for (srcset, expected) in [
            (
                "https://example.com/a.png 1x, https://example.com/b.png 2x",
                "https://example.com/a.png",
            ),
            (
                "https://example.com/a.png 320w, https://example.com/b.png 1280w",
                "https://example.com/a.png",
            ),
            (
                "large.png 3840w, medium.png 960w, small.png 320w, extra.png 1920w",
                "medium.png",
            ),
            (
                "small.png 960w, exact.png 1024w, large.png 2048w",
                "exact.png",
            ),
            (
                "large.png 3840w, small.png 1280w, medium.png 1920w",
                "small.png",
            ),
            ("large.png 4x, medium.png 2x, small.png 1x", "small.png"),
            ("medium.png 1.5x, large.png 3x", "medium.png"),
            ("large.png 4x, small.png 3x", "small.png"),
            ("tiny.png 0.5x, large.png 2x", "large.png"),
            ("tiny.png 0.5x, small.png 0.75x", "small.png"),
            ("default.png, large.png 3x", "default.png"),
            ("only.png 4096w", "only.png"),
            (
                "data:image/png;base64,AAAA 1x, data:image/png;base64,BBBB 2x",
                "data:image/png;base64,AAAA",
            ),
        ] {
            assert_eq!(kept_url(srcset), Some(expected), "{srcset}");
        }
        assert_eq!(
            kept_candidate("c.png 3x, b.png 2x, a.png 1x").map(|kept| kept.index),
            Some(2)
        );
    }

    #[test]
    fn an_img_src_wins_over_a_srcset_with_no_1x_or_width_candidate() {
        let (a, b) = (
            "https://cdn.example.com/a.png",
            "https://cdn.example.com/b.png",
        );
        for (srcset, shown_beside_src) in [
            (format!("{a} 1x, {b} 2x"), Some(a)),
            (format!("{b} 2x, {a} 1.0x"), Some(a)),
            (format!("{a} 320w, {b} 1280w"), Some(a)),
            (format!("{b} 2x"), None),
            (format!("{a} 0.5x"), None),
        ] {
            let alone = shown_candidate(&srcset, SrcsetSlot::Alone).map(|kept| kept.url);
            let beside_src =
                shown_candidate(&srcset, SrcsetSlot::BesideImgSrc).map(|kept| kept.url);
            assert!(alone.is_some(), "{srcset}");
            assert_eq!(beside_src, shown_beside_src, "{srcset}");
        }
    }

    #[test]
    fn keeps_no_candidate_of_a_mixed_or_malformed_srcset() {
        for srcset in [
            "https://example.com/a.png 1x, https://example.com/b.png 1280w",
            "https://example.com/a.png 0x",
            "https://example.com/a.png 1x 2x",
            ", https://example.com/a.png 1x",
            "https://example.com/a.png 1x,",
            "https://example.com/a.png 1x,, https://example.com/b.png 2x",
            "https://example.com/a.png,https://example.com/b.png",
        ] {
            assert_eq!(kept_candidate(srcset), None, "{srcset}");
        }
    }

    #[test]
    fn the_first_candidate_wins_a_tie() {
        for descriptor in ["0.5x", "1x", "2x", "3x", "1024w", "2048w"] {
            assert_eq!(
                kept_url(&format!("first.png {descriptor}, second.png {descriptor}")),
                Some("first.png")
            );
        }
    }

    #[test]
    fn a_srcset_is_usable_when_its_kept_candidate_can_show_offline() {
        let inline =
            |mime: &str, bytes: &[u8]| format!("data:{mime};base64,{} 1x", STANDARD.encode(bytes));
        for (srcset, usable) in [
            ("https://cdn.example.com/a.png 1x".to_owned(), true),
            ("//cdn.example.com/a.png 1x".to_owned(), true),
            (inline("image/png", b"\x89PNG\r\n\x1a\nbytes"), true),
            ("data:image/svg+xml,%3Csvg%2F%3E 1x".to_owned(), true),
            (
                inline(
                    "image/avif",
                    b"\x00\x00\x00\x1cftypavif\x00\x00\x00\x00avifmif1miaf",
                ),
                false,
            ),
            (inline("image/bmp", b"BMbitmap"), false),
            ("/relative/a.png 1x".to_owned(), false),
            ("https://10.0.0.7/a.png 1x".to_owned(), false),
            (
                "https://cdn.example.com/a.png 1x, b.png 1280w".to_owned(),
                false,
            ),
        ] {
            assert_eq!(usable_candidate(&srcset).is_some(), usable, "{srcset}");
        }
    }
}
