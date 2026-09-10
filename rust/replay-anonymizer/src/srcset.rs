#[derive(Clone, Copy, PartialEq, Eq)]
enum DescriptorKind {
    Density,
    Width,
}

struct Candidate<'a> {
    url: &'a str,
    kind: DescriptorKind,
    value: f64,
}

pub(crate) fn largest_candidate(srcset: &str) -> Option<&str> {
    let candidates = parse_candidates(srcset)?;
    let kind = candidates.first()?.kind;
    if candidates.iter().any(|candidate| candidate.kind != kind) {
        return None;
    }
    candidates
        .into_iter()
        .reduce(|best, candidate| {
            if candidate.value > best.value {
                candidate
            } else {
                best
            }
        })
        .map(|candidate| candidate.url)
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
        candidates.push(Candidate { url, kind, value });
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
    use super::largest_candidate;

    #[test]
    fn selects_the_largest_consistent_candidate() {
        for (srcset, expected) in [
            (
                "https://example.com/a.png 1x, https://example.com/b.png 2x",
                "https://example.com/b.png",
            ),
            (
                "https://example.com/a.png 320w, https://example.com/b.png 1280w",
                "https://example.com/b.png",
            ),
            (
                "data:image/png;base64,AAAA 1x, data:image/png;base64,BBBB 2x",
                "data:image/png;base64,BBBB",
            ),
        ] {
            assert_eq!(largest_candidate(srcset), Some(expected));
        }
    }

    #[test]
    fn rejects_mixed_or_malformed_descriptors() {
        for srcset in [
            "https://example.com/a.png 1x, https://example.com/b.png 1280w",
            "https://example.com/a.png 0x",
            "https://example.com/a.png 1x 2x",
            ", https://example.com/a.png 1x",
            "https://example.com/a.png 1x,",
            "https://example.com/a.png 1x,, https://example.com/b.png 2x",
            "https://example.com/a.png,https://example.com/b.png",
        ] {
            assert_eq!(largest_candidate(srcset), None);
        }
    }

    #[test]
    fn the_first_candidate_wins_a_tie() {
        assert_eq!(
            largest_candidate("https://example.com/a.png 2x, https://example.com/b.png 2x"),
            Some("https://example.com/a.png")
        );
    }
}
