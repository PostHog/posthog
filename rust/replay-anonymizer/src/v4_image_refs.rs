//! The strings that stand in for an image in a v4 replay block: references and decline markers.
//!
//! The v4 recorder writes them with this module. A reader that scrubs the text of a block keeps
//! each one intact for the image scrub, and finds them with [`parse`]. A captured page can hold
//! text that looks like a reference, so [`parse`] accepts only the exact strings the recorder
//! writes.

use std::fmt;

use crate::url_policy::Decline;

/// Starts a reference whose hash names the image bytes. The recorder stores the bytes.
pub const IMAGE_PREFIX: &str = "image:v4:";
/// Starts a reference whose hash names the image URL. The image fetcher stores the bytes.
pub const IMAGE_URL_PREFIX: &str = "imageurl:v4:";
/// The length v3 truncates a reference hash to: 132 bits of the HMAC, in URL-safe base64.
pub const HASH_CHARS: usize = 22;
/// What a remote URL becomes when the recorder replaces it without a check by the URL policy.
pub const URL_UNCHECKED_MARKER: &str = "imageurl:v4:declined:unchecked";

const DECLINED: &str = "declined:";

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum ImageDecline {
    /// The dataset keeps no AVIF image, inline or fetched.
    Avif,
}

impl ImageDecline {
    pub const ALL: [ImageDecline; 1] = [ImageDecline::Avif];

    pub const fn marker(self) -> &'static str {
        match self {
            ImageDecline::Avif => "image:v4:declined:avif",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum RefKind {
    Image,
    ImageUrl,
}

impl RefKind {
    pub const fn prefix(self) -> &'static str {
        match self {
            RefKind::Image => IMAGE_PREFIX,
            RefKind::ImageUrl => IMAGE_URL_PREFIX,
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct Ref<'a> {
    pub kind: RefKind,
    /// Positive, because a PostHog team id starts at 1.
    pub team_id: i64,
    /// The UTC month of the write, as `YYYY-MM`.
    pub key_month: &'a str,
    pub hash: &'a str,
}

/// A marker for an image that the dataset does not keep. No bytes stand behind it.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Declined {
    Image(ImageDecline),
    /// A remote URL that the URL policy refused.
    Url(Decline),
    UrlUnchecked,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Parsed<'a> {
    /// A reference, which names image bytes in the dataset.
    Ref(Ref<'a>),
    Declined(Declined),
}

impl fmt::Display for Ref<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(
            f,
            "{}{}:{}:{}",
            self.kind.prefix(),
            self.team_id,
            self.key_month,
            self.hash
        )
    }
}

impl fmt::Display for Declined {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Declined::Image(reason) => f.write_str(reason.marker()),
            Declined::Url(reason) => write!(f, "{IMAGE_URL_PREFIX}{DECLINED}{}", reason.label()),
            Declined::UrlUnchecked => f.write_str(URL_UNCHECKED_MARKER),
        }
    }
}

impl fmt::Display for Parsed<'_> {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Parsed::Ref(reference) => reference.fmt(f),
            Parsed::Declined(declined) => declined.fmt(f),
        }
    }
}

pub fn image_ref(team_id: i64, key_month: &str, hash: &str) -> String {
    Ref {
        kind: RefKind::Image,
        team_id,
        key_month,
        hash,
    }
    .to_string()
}

pub fn image_url_ref(team_id: i64, key_month: &str, hash: &str) -> String {
    Ref {
        kind: RefKind::ImageUrl,
        team_id,
        key_month,
        hash,
    }
    .to_string()
}

pub fn url_declined_marker(reason: Decline) -> String {
    Declined::Url(reason).to_string()
}

/// Reads a reference or a marker. Any other string is `None`, also one that differs from a string
/// the recorder writes only in letter case, a leading zero, whitespace or a trailing byte.
pub fn parse(s: &str) -> Option<Parsed<'_>> {
    if let Some(declined) = parse_declined(s) {
        return Some(Parsed::Declined(declined));
    }
    let (kind, rest) = match s.strip_prefix(IMAGE_PREFIX) {
        Some(rest) => (RefKind::Image, rest),
        None => (RefKind::ImageUrl, s.strip_prefix(IMAGE_URL_PREFIX)?),
    };
    let mut fields = rest.split(':');
    let (team_id, key_month, hash) = (fields.next()?, fields.next()?, fields.next()?);
    if fields.next().is_some() || !is_key_month(key_month) || !is_hash(hash) {
        return None;
    }
    Some(Parsed::Ref(Ref {
        kind,
        team_id: parse_team_id(team_id)?,
        key_month,
        hash,
    }))
}

fn parse_declined(s: &str) -> Option<Declined> {
    if s == URL_UNCHECKED_MARKER {
        return Some(Declined::UrlUnchecked);
    }
    if let Some(reason) = ImageDecline::ALL
        .into_iter()
        .find(|reason| reason.marker() == s)
    {
        return Some(Declined::Image(reason));
    }
    let label = s.strip_prefix(IMAGE_URL_PREFIX)?.strip_prefix(DECLINED)?;
    Decline::ALL
        .into_iter()
        .find(|reason| reason.label() == label)
        .map(Declined::Url)
}

/// Digits alone, as `i64` writes a positive number: no sign and no leading zero.
fn parse_team_id(digits: &str) -> Option<i64> {
    if digits.starts_with('0') || !digits.bytes().all(|b| b.is_ascii_digit()) {
        return None;
    }
    digits.parse().ok()
}

fn is_key_month(month: &str) -> bool {
    let [y0, y1, y2, y3, b'-', m0, m1] = *month.as_bytes() else {
        return false;
    };
    [y0, y1, y2, y3].iter().all(u8::is_ascii_digit)
        && matches!((m0, m1), (b'0', b'1'..=b'9') | (b'1', b'0'..=b'2'))
}

fn is_hash(hash: &str) -> bool {
    hash.len() == HASH_CHARS
        && hash
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'-' || b == b'_')
}

#[cfg(test)]
mod tests {
    use std::collections::HashSet;

    use super::*;

    const HASH: &str = "AbCdEfGhIjKlMnOpQr-_09";

    #[test]
    fn every_string_the_recorder_writes_round_trips() {
        let reference = |kind| {
            Parsed::Ref(Ref {
                kind,
                team_id: 7,
                key_month: "2026-10",
                hash: HASH,
            })
        };
        let url = |reason| Parsed::Declined(Declined::Url(reason));
        let vectors = [
            (
                "image:v4:7:2026-10:AbCdEfGhIjKlMnOpQr-_09",
                reference(RefKind::Image),
            ),
            (
                "imageurl:v4:7:2026-10:AbCdEfGhIjKlMnOpQr-_09",
                reference(RefKind::ImageUrl),
            ),
            (
                "image:v4:declined:avif",
                Parsed::Declined(Declined::Image(ImageDecline::Avif)),
            ),
            (
                "imageurl:v4:declined:unchecked",
                Parsed::Declined(Declined::UrlUnchecked),
            ),
            ("imageurl:v4:declined:too_long", url(Decline::TooLong)),
            (
                "imageurl:v4:declined:not_absolute",
                url(Decline::NotAbsolute),
            ),
            ("imageurl:v4:declined:bad_scheme", url(Decline::BadScheme)),
            ("imageurl:v4:declined:bad_port", url(Decline::BadPort)),
            ("imageurl:v4:declined:no_host", url(Decline::NoHost)),
            (
                "imageurl:v4:declined:non_public_host",
                url(Decline::NonPublicHost),
            ),
            ("imageurl:v4:declined:credential", url(Decline::Credential)),
            (
                "imageurl:v4:declined:invalid_query",
                url(Decline::InvalidQuery),
            ),
            (
                "imageurl:v4:declined:tracking_beacon",
                url(Decline::TrackingBeacon),
            ),
        ];
        for (written, parsed) in vectors {
            assert_eq!(parse(written), Some(parsed), "{written}");
            assert_eq!(parsed.to_string(), written);
        }
        assert_eq!(image_ref(7, "2026-10", HASH), vectors[0].0);
        assert_eq!(image_url_ref(7, "2026-10", HASH), vectors[1].0);

        let every_marker: HashSet<String> = ImageDecline::ALL
            .map(Declined::Image)
            .into_iter()
            .chain(Decline::ALL.map(Declined::Url))
            .chain([Declined::UrlUnchecked])
            .map(|declined| declined.to_string())
            .collect();
        let vector_markers: HashSet<String> = vectors
            .iter()
            .filter(|(_, parsed)| matches!(parsed, Parsed::Declined(_)))
            .map(|(written, _)| written.to_string())
            .collect();
        assert_eq!(every_marker, vector_markers);
    }

    #[test]
    fn rejects_near_misses() {
        let near_misses = [
            String::new(),
            "image:v4:".to_owned(),
            format!("image:v3:7:2026-10:{HASH}"),
            format!("Image:v4:7:2026-10:{HASH}"),
            format!("image:V4:7:2026-10:{HASH}"),
            format!("image:v4:07:2026-10:{HASH}"),
            format!("image:v4:0:2026-10:{HASH}"),
            format!("image:v4:-7:2026-10:{HASH}"),
            format!("image:v4:+7:2026-10:{HASH}"),
            format!("image:v4:9223372036854775808:2026-10:{HASH}"),
            format!("image:v4::2026-10:{HASH}"),
            format!("image:v4:7:2026-13:{HASH}"),
            format!("image:v4:7:2026-00:{HASH}"),
            format!("image:v4:7:2026-1:{HASH}"),
            format!("image:v4:7:226-10:{HASH}"),
            format!("image:v4:7:2026_10:{HASH}"),
            format!("image:v4:7:2026-10-01:{HASH}"),
            format!("image:v4:7:{HASH}"),
            format!("image:v4:7:2026-10:{}", &HASH[1..]),
            format!("image:v4:7:2026-10:{HASH}A"),
            format!("image:v4:7:2026-10:{HASH}="),
            format!("image:v4:7:2026-10:{HASH}:7"),
            "image:v4:7:2026-10:AbCdEfGhIjKlMnOpQr+/09".to_owned(),
            "image:v4:7:2026-10:AbCdEfGhIjKlMnOpQré09".to_owned(),
            format!(" image:v4:7:2026-10:{HASH}"),
            format!("image:v4:7:2026-10:{HASH}\n"),
            format!("imageurl:v4:7:2026-10:{HASH}%20"),
            "image:v4:declined".to_owned(),
            "image:v4:declined:".to_owned(),
            "image:v4:declined:AVIF".to_owned(),
            "image:v4:declined:avif ".to_owned(),
            "image:v4:declined:credential".to_owned(),
            "image:v4:declined:unchecked".to_owned(),
            "imageurl:v4:declined:avif".to_owned(),
            "imageurl:v4:declined:".to_owned(),
            "imageurl:v4:declined:Credential".to_owned(),
            "imageurl:v4:declined:credential:x".to_owned(),
            "imageurl:v4:declined:session_token".to_owned(),
            "imageurl:v3:declined:credential".to_owned(),
        ];
        for near_miss in near_misses {
            assert_eq!(parse(&near_miss), None, "{near_miss:?}");
        }
    }
}
