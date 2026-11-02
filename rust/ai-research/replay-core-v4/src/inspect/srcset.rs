//! The one `srcset` candidate the recorder keeps, by the v3 rule in `rust/replay-anonymizer/src/srcset.rs`. A renderer
//! picks a candidate for its viewport and shows nothing offline for one the fetcher did not take, and each fetched image
//! costs a scrub, so a srcset keeps one candidate.

use crate::scan::images::keeps_inline_image;
use crate::url_policy::{is_remote, try_canonicalize};

const MAX_SRCSET_WIDTH: f64 = 1024.0;
const MAX_SRCSET_DENSITY: f64 = 2.0;

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

/// The kept candidate, as its index in the srcset and its URL: the largest at or below 1024w or 2x, or the smallest
/// when all are larger. The first candidate wins a tie. `None` for a malformed srcset, or one that mixes width and
/// density descriptors.
pub fn kept_candidate(srcset: &str) -> Option<(usize, &str)> {
    let candidates = parse_candidates(srcset)?;
    let kind = candidates.first()?.kind;
    if candidates.iter().any(|candidate| candidate.kind != kind) {
        return None;
    }
    let limit = match kind {
        DescriptorKind::Width => MAX_SRCSET_WIDTH,
        DescriptorKind::Density => MAX_SRCSET_DENSITY,
    };
    candidates
        .into_iter()
        .reduce(
            |best, candidate| match (best.value <= limit, candidate.value <= limit) {
                (false, true) => candidate,
                (true, true) if candidate.value > best.value => candidate,
                (false, false) if candidate.value < best.value => candidate,
                _ => best,
            },
        )
        .map(|candidate| (candidate.index, candidate.url))
}

/// The kept candidate when it can show offline, as a URL the fetcher can take or an inline image the image scan keeps.
/// An img with such a srcset shows that candidate, so v3 fetches neither its `src` nor its `rr_src`. The writer keeps
/// this candidate alone, and none when there is no such candidate, so that the img shows its `src`.
pub fn usable_candidate(srcset: &str) -> Option<(usize, &str)> {
    kept_candidate(srcset).filter(|&(_, url)| {
        if is_remote(url) {
            try_canonicalize(url).is_ok()
        } else {
            keeps_inline_image(url)
        }
    })
}

fn parse_candidates(srcset: &str) -> Option<Vec<Candidate<'_>>> {
    let bytes = srcset.as_bytes();
    let mut candidates = Vec::new();
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
        candidates.push(Candidate {
            index: candidates.len(),
            url,
            kind,
            value,
        });
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
    (!candidates.is_empty()).then_some(candidates)
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
        kept_candidate(srcset).map(|(_, url)| url)
    }

    #[test]
    fn keeps_the_largest_candidate_within_the_limit_or_the_smallest_above_it() {
        for (srcset, expected) in [
            (
                "https://example.com/a.png 1x, https://example.com/b.png 2x",
                "https://example.com/b.png",
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
            ("large.png 4x, medium.png 2x, small.png 1x", "medium.png"),
            ("small.png 1x, medium.png 1.5x, large.png 3x", "medium.png"),
            ("large.png 4x, small.png 3x", "small.png"),
            ("default.png, large.png 3x", "default.png"),
            ("only.png 4096w", "only.png"),
            (
                "data:image/png;base64,AAAA 1x, data:image/png;base64,BBBB 2x",
                "data:image/png;base64,BBBB",
            ),
        ] {
            assert_eq!(kept_url(srcset), Some(expected), "{srcset}");
        }
        assert_eq!(
            kept_candidate("a.png 1x, b.png 2x, c.png 3x"),
            Some((1, "b.png"))
        );
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
        for descriptor in ["2x", "3x", "1024w", "2048w"] {
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
