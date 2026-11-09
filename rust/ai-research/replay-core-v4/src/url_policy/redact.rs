//! A URL as the page wrote it, without what the policy reads as a credential. v4 stores pages unscrubbed, so the recorder
//! removes only these, from the URLs that it does not replace with a reference.

use std::ops::Range;
use std::sync::LazyLock;

use percent_encoding::percent_decode_str;
use url::{form_urlencoded, Url};

use super::{
    as_parsed, decoded_lowercase_path, has_credential_path, has_credential_query,
    is_credential_param, path_tokens, PathToken, MAX_URL_LEN,
};

/// The URL parser reads these with an authority, and a backslash in them as a slash. A URL with no scheme resolves
/// against a page of one of them.
const SPECIAL_SCHEMES: &[&str] = &["http", "https", "ws", "wss", "ftp", "file"];

/// A relative URL resolves against this, so that the policy reads its path and query as it reads an absolute URL's.
static RELATIVE_BASE: LazyLock<Url> =
    LazyLock::new(|| Url::parse("https://relative.invalid/").expect("a valid base"));

#[derive(Debug, Clone, PartialEq, Eq)]
pub enum Redaction {
    Clean,
    Redacted(String),
    /// The URL can hold a credential that the redaction cannot cut out: it is longer than [`MAX_URL_LEN`], the URL parser
    /// does not read it, or one reading of it takes the credential as its host.
    Unread,
}

/// `raw` without its userinfo, the credential parameters of its query and fragment, and the path segments that hold a
/// token. The rest stays as the page wrote it, apart from the tabs, line breaks and outer spaces that the URL parser
/// drops. When the policy still reads a credential after those cuts, as in a path that hides a token behind a dot
/// segment, only the URL's origin stays, and none of it when the origin holds one too.
pub fn redaction(raw: &str) -> Redaction {
    // A `data:` URI can be tens of megabytes, so its scheme is read before anything else.
    if !is_hierarchical(raw) {
        return Redaction::Clean;
    }
    let url = as_parsed(raw);
    // A text check reads a URL otherwise than the URL parser, which maps a host with IDNA, decodes it and drops dot
    // segments. So every URL within the fetcher's limit is parsed, and a longer one keeps none of its text.
    if url.len() > MAX_URL_LEN {
        return Redaction::Unread;
    }
    let read = readings(&url);
    let Some(first) = read.first() else {
        return Redaction::Unread;
    };
    if !read.iter().any(holds_credential) {
        return Redaction::Clean;
    }
    let Some(parts) = Parts::of(&url) else {
        return Redaction::Unread;
    };
    let is_clean = |text: &str| {
        let read = readings(text);
        !read.is_empty() && !read.iter().any(holds_credential)
    };
    let cut = parts.without_credentials(&url, page_host(first));
    if is_clean(&cut) {
        return Redaction::Redacted(cut);
    }
    let origin = parts.origin(&url);
    if is_clean(&origin) {
        return Redaction::Redacted(origin);
    }
    Redaction::Unread
}

pub fn needs_redaction(raw: &str) -> bool {
    redaction(raw) != Redaction::Clean
}

pub fn without_credentials(raw: &str) -> Option<String> {
    match redaction(raw) {
        Redaction::Redacted(kept) => Some(kept),
        Redaction::Clean | Redaction::Unread => None,
    }
}

/// The URLs that a browser can read `url` as. The policy parses a URL with a scheme on its own, where `https:host/a`
/// names a host, but on a page of the same scheme that URL is the path `host/a` when no two slashes follow the scheme.
fn readings(url: &str) -> Vec<Url> {
    let Ok(alone) = Url::parse(url) else {
        return RELATIVE_BASE.join(url).into_iter().collect();
    };
    let after_scheme = alone.scheme().len() + 1;
    let names_its_host = url
        .as_bytes()
        .get(after_scheme..after_scheme + 2)
        .is_some_and(|slashes| slashes.iter().all(|&byte| matches!(byte, b'/' | b'\\')));
    let reads_as_a_path =
        alone.scheme() != "file" && SPECIAL_SCHEMES.contains(&alone.scheme()) && !names_its_host;
    let on_a_page = reads_as_a_path
        .then(|| {
            let mut base = RELATIVE_BASE.clone();
            base.set_scheme(alone.scheme()).ok()?;
            base.join(url).ok()
        })
        .flatten();
    std::iter::once(alone).chain(on_a_page).collect()
}

fn holds_credential(parsed: &Url) -> bool {
    if !parsed.username().is_empty() || parsed.password().is_some() {
        return true;
    }
    if has_credential_query(parsed).unwrap_or(true) {
        return true;
    }
    match decoded_lowercase_path(parsed) {
        Ok(path) if has_credential_path(&path, page_host(parsed)) => return true,
        Ok(_) => {}
        Err(_) => return true,
    }
    // A fragment holds parameters only by convention, as an OAuth callback's `#access_token=` does.
    parsed.fragment().is_some_and(|fragment| {
        fragment.contains('=')
            && form_urlencoded::parse(fragment.as_bytes())
                .any(|(name, value)| is_credential_param(&name, &value))
    })
}

/// The host as the policy reads it, or `None` for a relative URL, whose host is the page's.
fn page_host(parsed: &Url) -> Option<&str> {
    parsed
        .host_str()
        .filter(|&host| Some(host) != RELATIVE_BASE.host_str())
        .map(|host| host.strip_suffix('.').unwrap_or(host))
}

/// A URL of a scheme such as `data:` or `mailto:` holds no path to a host. The URL parser drops tabs and line breaks
/// in a scheme too, and reads a scheme only from a letter on, so `1:a.png` is a relative path.
fn is_hierarchical(raw: &str) -> bool {
    let bytes = raw.as_bytes();
    let ignored = |byte: &u8| matches!(byte, b'\t' | b'\n' | b'\r');
    let mut scheme = Vec::new();
    let mut at = bytes
        .iter()
        .position(|&byte| byte > b' ')
        .unwrap_or(bytes.len());
    while let Some(&byte) = bytes.get(at) {
        at += 1;
        match byte {
            _ if ignored(&byte) => {}
            b':' if !scheme.is_empty() => {
                if SPECIAL_SCHEMES.contains(&String::from_utf8_lossy(&scheme).as_ref()) {
                    return true;
                }
                let mut rest = bytes[at..].iter().filter(|byte| !ignored(byte));
                return rest.next() == Some(&b'/') && rest.next() == Some(&b'/');
            }
            b'a'..=b'z' | b'A'..=b'Z' if scheme.len() < 16 => {
                scheme.push(byte.to_ascii_lowercase())
            }
            b'0'..=b'9' | b'+' | b'-' | b'.' if !scheme.is_empty() && scheme.len() < 16 => {
                scheme.push(byte)
            }
            _ => return true,
        }
    }
    true
}

/// The parts of a URL by byte offset. The query and the fragment start after their `?` and `#`.
struct Parts {
    special: bool,
    authority: Option<Range<usize>>,
    path: Range<usize>,
    query: Option<Range<usize>>,
    fragment: Option<Range<usize>>,
}

impl Parts {
    fn of(url: &str) -> Option<Self> {
        let bytes = url.as_bytes();
        let byte_at = |at: usize| bytes.get(at).copied();
        let scheme_end = bytes
            .iter()
            .position(|&byte| !(byte.is_ascii_alphanumeric() || matches!(byte, b'+' | b'-' | b'.')))
            .filter(|&end| end > 0 && bytes[0].is_ascii_alphabetic() && byte_at(end) == Some(b':'));
        let scheme = scheme_end.map_or_else(String::new, |end| url[..end].to_ascii_lowercase());
        let special = scheme.is_empty() || SPECIAL_SCHEMES.contains(&scheme.as_str());
        let is_slash = |byte: u8| byte == b'/' || (special && byte == b'\\');
        let after_scheme = scheme_end.map_or(0, |end| end + 1);
        let mut at = after_scheme;
        while byte_at(at).is_some_and(is_slash) {
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
            while byte_at(at).is_some_and(|byte| !(is_slash(byte) || byte == b'?' || byte == b'#'))
            {
                at += 1;
            }
            start..at
        });
        let path_start = at;
        while byte_at(at).is_some_and(|byte| byte != b'?' && byte != b'#') {
            at += 1;
        }
        let path = path_start..at;
        let mut query = None;
        if byte_at(at) == Some(b'?') {
            at += 1;
            let start = at;
            while byte_at(at).is_some_and(|byte| byte != b'#') {
                at += 1;
            }
            query = Some(start..at);
        }
        let fragment = (byte_at(at) == Some(b'#')).then(|| at + 1..bytes.len());
        Some(Self {
            special,
            authority,
            path,
            query,
            fragment,
        })
    }

    /// Where the host starts after any userinfo.
    fn host_start(&self, url: &str, authority: &Range<usize>) -> usize {
        url[authority.clone()]
            .rfind('@')
            .map_or(authority.start, |at| authority.start + at + 1)
    }

    /// `host` is the host as the policy reads it, which the path's tokens can depend on.
    fn without_credentials(&self, url: &str, host: Option<&str>) -> String {
        let mut out = String::with_capacity(url.len());
        match &self.authority {
            Some(authority) => {
                out.push_str(&url[..authority.start]);
                out.push_str(&url[self.host_start(url, authority)..authority.end]);
            }
            None => out.push_str(&url[..self.path.start]),
        }
        let mut copied_to = self.path.start;
        for cut in self.path_cuts(url, host) {
            out.push_str(&url[copied_to..cut.start]);
            copied_to = cut.end;
        }
        out.push_str(&url[copied_to..self.path.end]);
        for (mark, part) in [('?', &self.query), ('#', &self.fragment)] {
            let Some(part) = part.clone() else { continue };
            let holds_parameters = mark == '?' || url[part.clone()].contains('=');
            match holds_parameters
                .then(|| without_credential_params(&url[part.clone()]))
                .flatten()
            {
                Some(kept) if kept.is_empty() => {}
                Some(kept) => {
                    out.push(mark);
                    out.push_str(&kept);
                }
                None => out.push_str(&url[part.start - 1..part.end]),
            }
        }
        out
    }

    /// The scheme and host without the userinfo, or `/` for a relative URL.
    fn origin(&self, url: &str) -> String {
        match &self.authority {
            Some(authority) => format!(
                "{}{}/",
                &url[..authority.start],
                &url[self.host_start(url, authority)..authority.end]
            ),
            None if url.starts_with(['/', '\\']) => "/".to_owned(),
            None => String::new(),
        }
    }

    /// The ranges of the path to drop, in order: each segment that holds a token with the slash before it, and each
    /// `;jsessionid=` parameter.
    fn path_cuts(&self, url: &str, host: Option<&str>) -> Vec<Range<usize>> {
        let bytes = url.as_bytes();
        let is_slash = |byte: u8| byte == b'/' || (self.special && byte == b'\\');
        let mut segments = Vec::new();
        let mut start = self.path.start;
        for at in self.path.clone() {
            if is_slash(bytes[at]) {
                segments.push(start..at);
                start = at + 1;
            }
        }
        segments.push(start..self.path.end);
        let decoded: Vec<String> = segments
            .iter()
            .map(|segment| {
                percent_decode_str(&url[segment.clone()])
                    .decode_utf8_lossy()
                    .to_ascii_lowercase()
            })
            .collect();
        let decoded: Vec<&str> = decoded.iter().map(String::as_str).collect();
        let mut cuts: Vec<Range<usize>> = Vec::new();
        for token in path_tokens(&decoded, host) {
            match token {
                PathToken::Segment(index) => {
                    let segment = segments[index].clone();
                    cuts.push(segment.start.saturating_sub(1).max(self.path.start)..segment.end);
                }
                PathToken::SessionId(index) => {
                    cuts.extend(session_id_parameters(url, segments[index].clone()))
                }
            }
        }
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

/// Each `;jsessionid=` parameter of `segment` up to the next `;`, or the whole segment when the page percent-encoded
/// one.
fn session_id_parameters(url: &str, segment: Range<usize>) -> Vec<Range<usize>> {
    const NAME: &[u8] = b";jsessionid=";
    let written = &url.as_bytes()[segment.clone()];
    let mut cuts = Vec::new();
    let mut at = 0;
    while at + NAME.len() <= written.len() {
        if !written[at..at + NAME.len()].eq_ignore_ascii_case(NAME) {
            at += 1;
            continue;
        }
        let end = written[at + 1..]
            .iter()
            .position(|&byte| byte == b';')
            .map_or(written.len(), |next| at + 1 + next);
        cuts.push(segment.start + at..segment.start + end);
        at = end;
    }
    if cuts.is_empty() {
        cuts.push(segment);
    }
    cuts
}

/// The parameters of `part` that are not credentials, joined by `&`, or `None` when it holds no credential. A name
/// that does not decode is dropped as well, because the policy cannot tell what it names.
fn without_credential_params(part: &str) -> Option<String> {
    let mut dropped = false;
    let kept: Vec<&str> = part
        .split('&')
        .filter(|pair| {
            let (name, value) = pair.split_once('=').unwrap_or((pair, ""));
            let credential = match form_decoded(name) {
                Some(name) => is_credential_param(&name, &lossy_form_decoded(value)),
                None => true,
            };
            dropped |= credential;
            !credential
        })
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
                Some("//cdn.example.com/a.png?w=1"),
            ),
            ("/api/img?access_token=abc", Some("/api/img")),
            // A relative URL's host is the page's, which can be an Oracle bucket.
            (
                "/p/abc/n/ns/b/bucket/o/a.png",
                Some("/p/n/ns/b/bucket/o/a.png"),
            ),
            ("img/a.png?w=1&token=abc", Some("img/a.png?w=1")),
            ("1:a.png?token=abc", Some("1:a.png")),
            (":a.png?token=abc", Some(":a.png")),
            (
                "https://app.example.com/cb#access_token=abc&state=x",
                Some("https://app.example.com/cb#state=x"),
            ),
            (
                "https://app.example.com/a;jsessionid=abc;x=1/b.png",
                Some("https://app.example.com/a;x=1/b.png"),
            ),
            (
                "https://app.example.com/a;jsessionid=first;jsessionid=abc/b.png",
                Some("https://app.example.com/a/b.png"),
            ),
            (
                "https://res.example.com/image/upload/s--abc123--/v1/a.png",
                Some("https://res.example.com/image/upload/v1/a.png"),
            ),
            (
                "https://cdn.example.com/a.png?%ff=1&w=2",
                Some("https://cdn.example.com/a.png?w=2"),
            ),
            // The policy reads these paths decoded and without dot segments, so only the origin stays.
            (
                "https://res.example.com/v1%2Fs--abc--/a.png",
                Some("https://res.example.com/"),
            ),
            (
                "https://cdn.example.com/x/../bcdn_token=abc/a.png",
                Some("https://cdn.example.com/"),
            ),
            (
                r"https://cdn.example.com\storage\v1\object\sign\abc",
                Some("https://cdn.example.com/"),
            ),
            // IDNA maps fullwidth letters to ASCII, so this host is an Oracle bucket.
            (
                "https://objectstorage.r.ｏｒａｃｌｅｃｌｏｕｄ.com/p/abc/n/ns",
                Some("https://objectstorage.r.ｏｒａｃｌｅｃｌｏｕｄ.com/p/n/ns"),
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
    fn leaves_no_url_that_the_policy_refuses_as_a_credential() {
        for raw in [
            "https://cdn.example.com/a.png?w=10&X-Amz-Signature=abc&X-Amz-Credential=k",
            "https://user:secret@cdn.example.com/a.png",
            "https://cdn.example.com/a.png?s=0123456789abcdef0123456789abcdef",
            "https://objectstorage.us-ashburn-1.oraclecloud.com/p/secret/n/ns/b/bucket/o/a.png",
            "https://objectstorage.us-ashburn-1.oraclecloud.com./p/secret/n/ns/b/bucket/o/a.png",
            "https://%6fbjectstorage.us-ashburn-1.oraclecloud.com/p/secret/n/ns/b/bucket/o/a.png",
            "https://cdn.example.com/bcdn_token=secret&expires=1/a.png",
            "https://cdn.example.com/image/upload%2Fs--secret--%2Fv1/a.png",
            "https://cdn.example.com/a;jsessionid=first;jsessionid=secret",
            "https://cdn.example.com/x/./../bcdn_token=secret/a.png",
            "https://ＯＢＪＥＣＴＳＴＯＲＡＧＥ.r.ｏｒａｃｌｅｃｌｏｕｄ.com/p/secret/n/ns",
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

    #[test]
    fn marks_a_url_whose_credential_it_cannot_cut() {
        let long = format!(
            "https://cdn.example.com{}?token=abc",
            "/a".repeat(16 * 1024 * 1024)
        );
        assert_eq!(redaction(&long), Redaction::Unread);
        let padding = "/a".repeat(MAX_URL_LEN);
        for long in [
            format!("https://cdn.example.com/bcdn_to\tken=abc{padding}"),
            format!("/p/abc/n/ns/b/bucket/o{padding}"),
            format!("https://cdn.example.com{padding}"),
        ] {
            assert_eq!(redaction(&long), Redaction::Unread);
        }
        assert_eq!(
            redaction("https://cdn.example.com:99999/a.png?token=abc"),
            Redaction::Unread
        );
        // On a page of their scheme these are paths, so what the URL parser alone reads as a host holds the token.
        for raw in ["https:bcdn_token=abc/a.png", "https:/bcdn_token=abc/a.png"] {
            assert_eq!(redaction(raw), Redaction::Unread, "{raw}");
        }
    }

    #[test]
    fn reads_no_more_of_a_data_uri_than_its_scheme() {
        let data = format!("data:image/png;base64,{}", "A/".repeat(16 * 1024 * 1024));
        assert_eq!(without_credentials(&data), None);
    }
}
