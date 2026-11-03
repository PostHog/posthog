//! A URL as the page wrote it, without what the policy reads as a credential. v4 stores pages unscrubbed, so the recorder
//! removes only these, from the URLs that it does not replace with a reference.

use std::ops::Range;

use percent_encoding::percent_decode_str;

use super::{is_credential_param, path_tokens, PathToken};

/// The URL parser reads these with an authority, and a backslash in them as a slash. A URL with no scheme resolves
/// against a page of one of them.
const SPECIAL_SCHEMES: &[&str] = &["http", "https", "ws", "wss", "ftp", "file"];

/// `raw` without its userinfo, the credential parameters of its query and fragment, and the path segments that hold a
/// token. The rest stays as the page wrote it. `None` when `raw` holds none of them.
pub fn without_credentials(raw: &str) -> Option<String> {
    // The URL parser drops tabs and line breaks anywhere, so the parts are found without them and keep them in place.
    let all: Vec<(usize, char)> = raw
        .char_indices()
        .filter(|&(_, ch)| !matches!(ch, '\t' | '\n' | '\r'))
        .collect();
    let first = all.iter().position(|&(_, ch)| ch > ' ')?;
    let last = all.iter().rposition(|&(_, ch)| ch > ' ')?;
    let end_byte = all[last].0 + all[last].1.len_utf8();
    let chars = &all[first..=last];
    let url = Parts::of(chars)?;
    let byte = |at: usize| chars.get(at).map_or(end_byte, |&(byte, _)| byte);
    let text = |range: Range<usize>| &raw[byte(range.start)..byte(range.end)];

    let mut changed = false;
    let mut out = String::with_capacity(raw.len());
    out.push_str(&raw[..byte(0)]);
    let head_end = url.authority.as_ref().map_or(url.path.start, |a| a.start);
    out.push_str(text(0..head_end));
    let mut host = String::new();
    if let Some(authority) = url.authority.clone() {
        let userinfo_end = chars[authority.clone()]
            .iter()
            .rposition(|&(_, ch)| ch == '@')
            .map_or(authority.start, |at| authority.start + at + 1);
        changed |= userinfo_end > authority.start + 1;
        let kept = if userinfo_end > authority.start + 1 {
            userinfo_end
        } else {
            authority.start
        };
        out.push_str(text(kept..authority.end));
        host = chars[userinfo_end..authority.end]
            .iter()
            .map(|&(_, ch)| ch.to_ascii_lowercase())
            .take_while(|&ch| ch != ':')
            .collect();
    }
    let cuts = url.path_cuts(chars, &host);
    changed |= !cuts.is_empty();
    let mut copied_to = url.path.start;
    for cut in cuts {
        out.push_str(text(copied_to..cut.start));
        copied_to = cut.end;
    }
    out.push_str(text(copied_to..url.path.end));
    for (mark, part) in [('?', url.query), ('#', url.fragment)] {
        let Some(part) = part else { continue };
        // A fragment holds parameters only by convention, as an OAuth callback's `#access_token=` does.
        let holds_parameters = mark == '?' || chars[part.clone()].iter().any(|&(_, ch)| ch == '=');
        match holds_parameters
            .then(|| without_credential_params(chars, part.clone(), &text))
            .flatten()
        {
            Some(kept) => {
                changed = true;
                if !kept.is_empty() {
                    out.push(mark);
                    out.push_str(&kept);
                }
            }
            None => out.push_str(text(part.start - 1..part.end)),
        }
    }
    out.push_str(&raw[end_byte..]);
    changed.then_some(out)
}

/// The parts of a URL, by index in its characters without tabs and line breaks. The query and the fragment start after
/// their `?` and `#`.
struct Parts {
    special: bool,
    authority: Option<Range<usize>>,
    path: Range<usize>,
    query: Option<Range<usize>>,
    fragment: Option<Range<usize>>,
}

impl Parts {
    /// `None` for a URL of a scheme such as `data:` or `mailto:`, which holds no path to a host.
    fn of(chars: &[(usize, char)]) -> Option<Self> {
        let char_at = |at: usize| chars.get(at).map(|&(_, ch)| ch);
        let scheme_end = chars
            .iter()
            .position(|&(_, ch)| !(ch.is_ascii_alphanumeric() || matches!(ch, '+' | '-' | '.')))
            .filter(|&end| {
                end > 0 && chars[0].1.is_ascii_alphabetic() && char_at(end) == Some(':')
            });
        let scheme: String = scheme_end.map_or_else(String::new, |end| {
            chars[..end]
                .iter()
                .map(|&(_, ch)| ch.to_ascii_lowercase())
                .collect()
        });
        let special = scheme.is_empty() || SPECIAL_SCHEMES.contains(&scheme.as_str());
        let is_slash = |ch: char| ch == '/' || (special && ch == '\\');
        let after_scheme = scheme_end.map_or(0, |end| end + 1);
        let mut at = after_scheme;
        while char_at(at).is_some_and(is_slash) {
            at += 1;
        }
        let has_authority = (special && !scheme.is_empty()) || at - after_scheme >= 2;
        if !has_authority {
            if !special {
                return None;
            }
            at = after_scheme;
        }
        let authority = has_authority.then(|| {
            let start = at;
            while char_at(at).is_some_and(|ch| !(is_slash(ch) || ch == '?' || ch == '#')) {
                at += 1;
            }
            start..at
        });
        let path_start = at;
        while char_at(at).is_some_and(|ch| ch != '?' && ch != '#') {
            at += 1;
        }
        let path = path_start..at;
        let mut query = None;
        if char_at(at) == Some('?') {
            at += 1;
            let start = at;
            while char_at(at).is_some_and(|ch| ch != '#') {
                at += 1;
            }
            query = Some(start..at);
        }
        let fragment = (char_at(at) == Some('#')).then(|| at + 1..chars.len());
        Some(Self {
            special,
            authority,
            path,
            query,
            fragment,
        })
    }

    /// The ranges of the path to drop, in order: each segment that holds a token with the slash before it, and each
    /// `;jsessionid=` parameter.
    fn path_cuts(&self, chars: &[(usize, char)], host: &str) -> Vec<Range<usize>> {
        let is_slash = |ch: char| ch == '/' || (self.special && ch == '\\');
        let mut segments = Vec::new();
        let mut start = self.path.start;
        for at in self.path.clone() {
            if is_slash(chars[at].1) {
                segments.push(start..at);
                start = at + 1;
            }
        }
        segments.push(start..self.path.end);
        let decoded: Vec<String> = segments
            .iter()
            .map(|segment| {
                let written: String = chars[segment.clone()].iter().map(|&(_, ch)| ch).collect();
                percent_decode_str(&written)
                    .decode_utf8_lossy()
                    .to_ascii_lowercase()
            })
            .collect();
        let decoded: Vec<&str> = decoded.iter().map(String::as_str).collect();
        let mut cuts: Vec<Range<usize>> = path_tokens(&decoded, host)
            .into_iter()
            .map(|token| match token {
                PathToken::Segment(index) => {
                    let segment = segments[index].clone();
                    segment.start.saturating_sub(1).max(self.path.start)..segment.end
                }
                PathToken::SessionId(index) => {
                    let segment = segments[index].clone();
                    session_id_parameter(chars, segment)
                }
            })
            .collect();
        cuts.sort_by_key(|cut| cut.start);
        cuts.dedup_by(|later, earlier| {
            let overlaps = later.start < earlier.end;
            if overlaps {
                earlier.end = earlier.end.max(later.end);
            }
            overlaps
        });
        cuts
    }
}

/// The `;jsessionid=` parameter of `segment` up to the next `;`, or the whole segment when the page percent-encoded it.
fn session_id_parameter(chars: &[(usize, char)], segment: Range<usize>) -> Range<usize> {
    const NAME: &str = ";jsessionid=";
    let written: Vec<char> = chars[segment.clone()].iter().map(|&(_, ch)| ch).collect();
    let Some(at) = (0..written.len()).find(|&at| {
        written.len() - at >= NAME.len()
            && written[at..at + NAME.len()]
                .iter()
                .zip(NAME.chars())
                .all(|(ch, name)| ch.eq_ignore_ascii_case(&name))
    }) else {
        return segment;
    };
    let end = (at + 1..written.len())
        .find(|&end| written[end] == ';')
        .unwrap_or(written.len());
    segment.start + at..segment.start + end
}

/// The parameters of `part` that are not credentials, joined by `&`, or `None` when it holds no credential. A name
/// that does not decode is dropped as well, because the policy cannot tell what it names.
fn without_credential_params<'r>(
    chars: &[(usize, char)],
    part: Range<usize>,
    text: &impl Fn(Range<usize>) -> &'r str,
) -> Option<String> {
    let mut pairs = Vec::new();
    let mut start = part.start;
    for at in part.clone() {
        if chars[at].1 == '&' {
            pairs.push(start..at);
            start = at + 1;
        }
    }
    pairs.push(start..part.end);
    let mut dropped = false;
    let kept: Vec<&str> = pairs
        .into_iter()
        .filter(|pair| {
            let written: String = chars[pair.clone()].iter().map(|&(_, ch)| ch).collect();
            let (name, value) = written.split_once('=').unwrap_or((&written, ""));
            let credential = match form_decoded(name) {
                Some(name) => is_credential_param(&name, &lossy_form_decoded(value)),
                None => true,
            };
            dropped |= credential;
            !credential
        })
        .map(text)
        .collect();
    dropped.then(|| kept.join("&"))
}

fn form_decoded(text: &str) -> Option<String> {
    let text = text.replace('+', " ");
    let bytes = text.as_bytes();
    let valid = bytes.iter().enumerate().all(|(at, &byte)| {
        byte != b'%'
            || (bytes.get(at + 1).is_some_and(u8::is_ascii_hexdigit)
                && bytes.get(at + 2).is_some_and(u8::is_ascii_hexdigit))
    });
    if !valid {
        return None;
    }
    percent_decode_str(&text)
        .decode_utf8()
        .ok()
        .map(|decoded| decoded.into_owned())
}

fn lossy_form_decoded(text: &str) -> String {
    percent_decode_str(&text.replace('+', " "))
        .decode_utf8_lossy()
        .into_owned()
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::url_policy::checked_url;
    use crate::url_policy::Decline;

    #[test]
    fn drops_only_the_credentials_of_a_url() {
        for (raw, kept) in [
            (
                "https://cdn.example.com/a.png?w=10&X-Amz-Signature=abc&h=20#top",
                Some("https://cdn.example.com/a.png?w=10&h=20#top"),
            ),
            (
                "https://cdn.example.com/a.png?token=abc",
                Some("https://cdn.example.com/a.png"),
            ),
            (
                "https://user:secret@cdn.example.com/a.png",
                Some("https://cdn.example.com/a.png"),
            ),
            (
                r"HTTPS:\\user:secret@CDN.example.com\a.png?Sig=abc",
                Some(r"HTTPS:\\CDN.example.com\a.png"),
            ),
            (
                " //cdn.example.com/a.png?to\tken=abc&w=1 ",
                Some(" //cdn.example.com/a.png?w=1 "),
            ),
            ("/api/img?access_token=abc", Some("/api/img")),
            ("img/a.png?w=1&token=abc", Some("img/a.png?w=1")),
            (
                "https://app.example.com/cb#access_token=abc&state=x",
                Some("https://app.example.com/cb#state=x"),
            ),
            (
                "https://app.example.com/a;jsessionid=abc;x=1/b.png",
                Some("https://app.example.com/a;x=1/b.png"),
            ),
            (
                "https://res.example.com/image/upload/s--abc123--/v1/a.png",
                Some("https://res.example.com/image/upload/v1/a.png"),
            ),
            (
                "https://cdn.example.com/a.png?%ff=1&w=2",
                Some("https://cdn.example.com/a.png?w=2"),
            ),
            ("https://cdn.example.com/a.png?w=10", None),
            ("https://cdn.example.com/a.png#token", None),
            ("data:image/png;base64,abc?token=x", None),
            ("mailto:a@example.com?token=x", None),
        ] {
            assert_eq!(without_credentials(raw).as_deref(), kept, "{raw}");
        }
    }

    #[test]
    fn leaves_a_url_the_policy_does_not_refuse_as_a_credential() {
        for raw in [
            "https://cdn.example.com/a.png?w=10&X-Amz-Signature=abc&X-Amz-Credential=k",
            "https://user:secret@cdn.example.com/a.png",
            "https://cdn.example.com/a.png?s=0123456789abcdef0123456789abcdef",
            "https://objectstorage.us-ashburn-1.oraclecloud.com/p/secret/n/ns/b/bucket/o/a.png",
            "https://cdn.example.com/bcdn_token=secret&expires=1/a.png",
        ] {
            assert_eq!(checked_url(raw).err(), Some(Decline::Credential), "{raw}");
            let kept = without_credentials(raw).unwrap();
            assert_ne!(
                checked_url(&kept).err(),
                Some(Decline::Credential),
                "{kept}"
            );
            assert!(!kept.contains("secret") && !kept.contains("abc"), "{kept}");
        }
    }
}
