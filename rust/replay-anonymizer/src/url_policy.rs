//! The rules that decide whether a remote image URL may be fetched, and what its canonical forms
//! are.
//!
//! Separate from [`crate::url_collect`] on purpose. That module accumulates the URLs of one
//! message. This one holds the policy, and the policy has more than one consumer.
//!
//! The fetch lane applies the same host rule again at request time. It applies it to the resolved
//! address, and to every redirect hop, because a name that resolves publicly now can resolve
//! privately later. The fetch lane also canonicalizes what it fetched, to find its ledger entry.
//!
//! The fetch lane runs in another language. The registrable domain therefore travels with each
//! URL as data, so that lane reads the result and never repeats the rule.

use std::collections::HashSet;
use std::net::IpAddr;

use percent_encoding::percent_decode_str;
use public_suffix::{EffectiveTLDProvider, DEFAULT_PROVIDER};

use url::Url;

const VOLATILE_PARAMS: &[&str] = &["cb", "nocache", "rnd"];

const CREDENTIAL_PARAMS: &[&str] = &[
    "__cld_token__",
    "__token__",
    "access_token",
    "api_key",
    "apikey",
    "auth_token",
    "authorization",
    "awsaccesskeyid",
    "credential",
    "googleaccessid",
    "hdnea",
    "hdntl",
    "hdnts",
    "id_token",
    "ik-s",
    "jsessionid",
    "ossaccesskeyid",
    "phpsessid",
    "q-ak",
    "q-signature",
    "security-token",
    "session_token",
    "sessionid",
    "sig",
    "signature",
    "signedheaders",
    "token",
    "x-amz-credential",
    "x-amz-security-token",
    "x-amz-signature",
    "x-amz-signedheaders",
    "x-cos-security-token",
    "x-goog-credential",
    "x-goog-signature",
    "x-goog-signedheaders",
    "x-oss-credential",
    "x-oss-security-token",
    "x-oss-signature",
];

const SCOPED_VOLATILE_PARAMS: &[(&str, &[&str])] =
    &[("_nc_ohc", &["_nc_ohc", "_nc_ht", "ccb", "oe", "oh", "stp"])];

/// Longer than this and we neither collect nor fetch it. Well past what a real image URL needs,
/// and it bounds what one message can pin in memory alongside the count cap.
pub const MAX_URL_LEN: usize = 2048;

/// The politeness unit for a host: the registrable domain, or the host itself when it has none.
///
/// A rate limit protects the operator that answers the request, not a DNS label. A CDN that shards
/// over `img1..img8.cdn.example.com` would otherwise receive eight times the intended rate.
/// The fetch topic keys on this, so every URL of one operator lands on one partition and one pod
/// holds its budget without a distributed lock.
///
/// The public suffix list draws the boundary, and its private section is what makes this correct
/// for multi-tenant hosts. `d111.cloudfront.net`, `bucket.s3.amazonaws.com`, `user.github.io` and
/// `myapp.vercel.app` are each their own registrable domain, because `cloudfront.net`,
/// `s3.amazonaws.com`, `github.io` and `vercel.app` are all public suffixes. One tenant therefore
/// never shares a budget with an unrelated tenant of the same provider.
///
/// An IP literal has no registrable domain and returns unchanged, which is right: the address is
/// the operator.
pub fn politeness_key(host: &str) -> String {
    // `example.com.` and `example.com` are one operator, so two spellings must not take two
    // budgets, two breakers, and two partitions. Brackets stay, because an IPv6 literal keys in the
    // form the URL carries.
    let host = host.strip_suffix('.').unwrap_or(host);
    if host.parse::<IpAddr>().is_ok() || host.starts_with('[') {
        return host.to_string();
    }
    match DEFAULT_PROVIDER.effective_tld_plus_one(host) {
        Ok(domain) => domain.to_string(),
        // A host with no registrable domain is its own operator. `is_public_host` already declined
        // the bare names this could otherwise return.
        Err(_) => host.to_string(),
    }
}

/// The two forms of one URL. See the module docs for why both exist.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct CanonicalUrl {
    pub fetch: String,
    pub dedup: String,
    pub host: String,
    /// The registrable domain of `host`. See [`politeness_key`].
    pub domain: String,
}

fn is_volatile(name: &str, names_on_this_url: &HashSet<String>) -> bool {
    if VOLATILE_PARAMS
        .iter()
        .any(|volatile| volatile.eq_ignore_ascii_case(name))
    {
        return true;
    }
    SCOPED_VOLATILE_PARAMS.iter().any(|(marker, names)| {
        names_on_this_url.contains(*marker)
            && names
                .iter()
                .any(|volatile| volatile.eq_ignore_ascii_case(name))
    })
}

/// Whether a host is one we would ever fetch from.
///
/// A page controls the URL set, and the set exists to be handed to something that makes outbound
/// requests from inside our network. A page carrying
/// `<img src="http://169.254.169.254/...">` must not become a fetch instruction for the cloud
/// metadata endpoint.
///
/// This is not a substitute for a check at fetch time. A name that resolves publicly now can
/// resolve privately later. The fetcher therefore validates the address DNS returns, on the first
/// request and on every redirect hop.
pub fn is_public_host(host: &str) -> bool {
    let host = without_brackets_or_trailing_dot(host);
    if host.parse::<IpAddr>().is_ok() {
        return false;
    }
    is_public_domain_name(&host.to_ascii_lowercase())
}

/// `[2606:4700::1111]` becomes `2606:4700::1111`, and `localhost.` becomes `localhost`.
///
/// A trailing dot makes a name fully qualified and resolves identically, so leaving it on let
/// `localhost.` past the name check below: the label after the final dot is empty and matches
/// nothing.
fn without_brackets_or_trailing_dot(host: &str) -> &str {
    let bare = host.trim_matches(|c| c == '[' || c == ']');
    bare.strip_suffix('.').unwrap_or(bare)
}

fn is_public_domain_name(lowercase_host: &str) -> bool {
    let has_no_dot = !lowercase_host.contains('.');
    let has_empty_label = lowercase_host.split('.').any(|label| label.is_empty());
    if has_no_dot || has_empty_label {
        return false;
    }
    !matches!(
        lowercase_host.rsplit('.').next(),
        Some(
            "localhost"
                | "local"
                | "internal"
                | "intranet"
                | "lan"
                | "home"
                | "corp"
                | "test"
                | "invalid"
                | "example"
        )
    )
}

/// Why a URL was not collected. Each variant is a label on the decline counter. A lane
/// that collects less than it should then reads off a dashboard, rather than being guessed at.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub enum Decline {
    /// Longer than [`MAX_URL_LEN`], before or after normalization.
    TooLong,
    /// Not parseable as an absolute URL. A relative `src` lands here, because the recording does
    /// not carry the base it would need to resolve against.
    NotAbsolute,
    /// A scheme we do not fetch. Only `https` passes, so plain `http` lands here too.
    BadScheme,
    /// A port the scheme does not own. See the port check in [`try_canonicalize`].
    BadPort,
    /// No host at all.
    NoHost,
    /// Loopback, private, link-local or an internal-only name. See [`is_public_host`].
    NonPublicHost,
    /// A known URL credential, signature, token, signed-header list, or non-empty userinfo.
    Credential,
    /// A query parameter name could not be percent-decoded as UTF-8.
    InvalidQuery,
}

impl Decline {
    /// The metric label. Stable, because a dashboard and an alert both key on it.
    pub fn label(self) -> &'static str {
        match self {
            Decline::TooLong => "too_long",
            Decline::NotAbsolute => "not_absolute",
            Decline::BadScheme => "bad_scheme",
            Decline::BadPort => "bad_port",
            Decline::NoHost => "no_host",
            Decline::NonPublicHost => "non_public_host",
            Decline::Credential => "credential",
            Decline::InvalidQuery => "invalid_query",
        }
    }
}

/// Canonicalize a remote image URL into its fetch and dedup forms, or say why it was refused.
pub fn canonicalize(raw: &str) -> Option<CanonicalUrl> {
    try_canonicalize(raw).ok()
}

pub fn try_canonicalize(raw: &str) -> Result<CanonicalUrl, Decline> {
    if raw.len() > MAX_URL_LEN {
        return Err(Decline::TooLong);
    }
    let mut url = Url::parse(raw).map_err(|_| Decline::NotAbsolute)?;
    // The browser blocks a plain `http` image on an HTTPS page as mixed content, so it never
    // rendered for the person we recorded, and a fetch puts the request on the wire in clear text
    // from our egress addresses.
    if url.scheme() != "https" {
        return Err(Decline::BadScheme);
    }
    // A port the scheme does not own makes the fetcher a port prober: a page names any host and
    // port, the connection leaves our egress addresses, and the outcome metric shows what answered.
    // Too few images are served on other ports to be worth that.
    //
    // This check limits which service on a host we reach. `is_public_host` and the address check at
    // request time limit which hosts we reach, because DNS for a name the attacker owns can point
    // anywhere.
    if url.port().is_some() {
        return Err(Decline::BadPort);
    }
    if !url.username().is_empty() || url.password().is_some() {
        return Err(Decline::Credential);
    }
    // `example.com.` and `example.com` name the same host, and the consumer compares the two as
    // strings in more than one place. The dot comes off the URL as well as off the host, so
    // everything downstream sees one spelling.
    let host_str = url.host_str().ok_or(Decline::NoHost)?;
    let host = host_str.strip_suffix('.').unwrap_or(host_str).to_string();
    if !is_public_host(&host) {
        return Err(Decline::NonPublicHost);
    }
    if host != host_str {
        url.set_host(Some(&host)).map_err(|_| Decline::NoHost)?;
    }
    if has_credential_query(&url)? || has_credential_path(&url, &host)? {
        return Err(Decline::Credential);
    }

    let original_query = original_query(raw);
    url.set_fragment(None);
    url.set_query(None);
    let serialized_without_query = url.to_string();
    let fetch = serialize_with_query(&serialized_without_query, original_query);
    // Percent-encoding and IDNA can grow a URL, so the cap is re-checked on what we emit.
    if fetch.len() > MAX_URL_LEN {
        return Err(Decline::TooLong);
    }

    let dedup_query = remove_volatile_params(original_query)?;
    let dedup = serialize_with_query(&serialized_without_query, dedup_query.as_deref());

    Ok(CanonicalUrl {
        fetch,
        dedup,
        domain: politeness_key(&host),
        host,
    })
}

fn original_query(raw: &str) -> Option<&str> {
    let before_fragment = raw.split_once('#').map_or(raw, |(before, _)| before);
    before_fragment.split_once('?').map(|(_, query)| query)
}

fn serialize_with_query(serialized_without_query: &str, query: Option<&str>) -> String {
    let mut serialized = serialized_without_query.to_string();
    if let Some(query) = query {
        serialized.push('?');
        serialized.push_str(query);
    }
    serialized
}

fn has_credential_query(url: &Url) -> Result<bool, Decline> {
    let Some(raw_query) = url.query() else {
        return Ok(false);
    };
    for raw_pair in raw_query.split('&') {
        let raw_name = raw_pair.split_once('=').map_or(raw_pair, |(name, _)| name);
        if !has_valid_percent_encoding(raw_name) {
            return Err(Decline::InvalidQuery);
        }
        let form_name = raw_name.replace('+', " ");
        percent_decode_str(&form_name)
            .decode_utf8()
            .map_err(|_| Decline::InvalidQuery)?;
    }
    Ok(url.query_pairs().any(|(name, value)| {
        CREDENTIAL_PARAMS
            .iter()
            .any(|credential| credential.eq_ignore_ascii_case(&name))
            || (name.eq_ignore_ascii_case("s") && value.chars().count() == 32)
    }))
}

fn has_valid_percent_encoding(value: &str) -> bool {
    let bytes = value.as_bytes();
    let mut index = 0;
    while index < bytes.len() {
        if bytes[index] == b'%' {
            if index + 2 >= bytes.len()
                || !bytes[index + 1].is_ascii_hexdigit()
                || !bytes[index + 2].is_ascii_hexdigit()
            {
                return false;
            }
            index += 3;
        } else {
            index += 1;
        }
    }
    true
}

fn has_credential_path(url: &Url, host: &str) -> Result<bool, Decline> {
    if !has_valid_percent_encoding(url.path()) {
        return Err(Decline::Credential);
    }
    let path = percent_decode_str(url.path())
        .decode_utf8()
        .map_err(|_| Decline::Credential)?
        .to_ascii_lowercase();
    let segments: Vec<&str> = path.split('/').collect();
    let first_segment_has_bunny_token = segments
        .get(1)
        .and_then(|segment| segment.strip_prefix("bcdn_token="))
        .and_then(|value| value.split('&').next())
        .is_some_and(|token| !token.is_empty());
    let has_oracle_token = host.starts_with("objectstorage.")
        && host.ends_with(".oraclecloud.com")
        && host.split('.').count() == 4
        && segments.get(1) == Some(&"p")
        && segments.get(2).is_some_and(|token| !token.is_empty())
        && segments.get(3) == Some(&"n");
    let has_cloudinary_signature = segments.iter().any(|segment| {
        segment
            .strip_prefix("s--")
            .and_then(|value| value.strip_suffix("--"))
            .is_some_and(|token| !token.is_empty())
    });
    let has_supabase_signature = path.contains("/storage/v1/object/sign/")
        || path.contains("/storage/v1/render/image/sign/");
    let has_session_token = segments.iter().any(|segment| {
        segment
            .split_once(";jsessionid=")
            .and_then(|(_, value)| value.split(';').next())
            .is_some_and(|token| !token.is_empty())
    });

    Ok(first_segment_has_bunny_token
        || has_oracle_token
        || has_cloudinary_signature
        || has_supabase_signature
        || has_session_token)
}

fn remove_volatile_params(raw_query: Option<&str>) -> Result<Option<String>, Decline> {
    let Some(raw_query) = raw_query else {
        return Ok(None);
    };
    let pairs: Vec<(&str, String)> = raw_query
        .split('&')
        .map(|raw_pair| {
            let raw_name = raw_pair.split_once('=').map_or(raw_pair, |(name, _)| name);
            if !has_valid_percent_encoding(raw_name) {
                return Err(Decline::InvalidQuery);
            }
            let decoded_name = percent_decode_str(raw_name)
                .decode_utf8()
                .map_err(|_| Decline::InvalidQuery)?
                .into_owned();
            Ok((raw_pair, decoded_name))
        })
        .collect::<Result<_, _>>()?;
    let names_on_this_url: HashSet<String> = pairs
        .iter()
        .map(|(_, name)| name.to_ascii_lowercase())
        .collect();
    let kept: Vec<&str> = pairs
        .iter()
        .filter(|(_, name)| !is_volatile(name, &names_on_this_url))
        .map(|(raw_pair, _)| *raw_pair)
        .collect();

    if kept.is_empty() {
        return Ok(None);
    }
    Ok(Some(kept.join("&")))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn canonicalize_rejects_what_we_will_not_fetch() {
        for raw in [
            "ftp://example.com/a.png",
            "data:image/png;base64,aGk=",
            "/relative/a.png",
            "not a url",
            "//protocol-relative.example.com/a.png",
        ] {
            assert!(canonicalize(raw).is_none(), "{raw} should not canonicalize");
        }
        let long = format!("https://example.com/{}", "a".repeat(MAX_URL_LEN));
        assert!(canonicalize(&long).is_none());
    }

    #[test]
    fn canonicalize_normalizes_and_removes_the_fragment() {
        let c = canonicalize("HTTPS://Example.COM:443/A.png#frag").unwrap();
        assert_eq!(c.fetch, "https://example.com/A.png");
        assert_eq!(c.host, "example.com");
    }

    #[test]
    fn known_query_credentials_are_refused_case_insensitively() {
        for name in CREDENTIAL_PARAMS {
            let raw = format!(
                "https://cdn.example.com/a.png?{}=",
                name.to_ascii_uppercase()
            );
            assert_eq!(try_canonicalize(&raw), Err(Decline::Credential), "{name}");
        }
        assert_eq!(
            try_canonicalize("https://cdn.example.com/a.png?X-Amz-%53ignature=value"),
            Err(Decline::Credential)
        );
        assert_eq!(
            try_canonicalize("https://cdn.example.com/a.png?safe=1&safe=2&TOKEN="),
            Err(Decline::Credential)
        );
        assert_eq!(
            try_canonicalize("https://cdn.example.com/a.png?s=0123456789abcdef0123456789abcdef"),
            Err(Decline::Credential)
        );
        assert!(canonicalize("https://cdn.example.com/a.png?s=200").is_some());
    }

    #[test]
    fn credential_path_patterns_are_refused_case_insensitively() {
        for raw in [
            "https://cdn.example.com/BCDN_TOKEN=value/image.png",
            "https://objectstorage.region.oraclecloud.com/P/value/N/image.png",
            "https://cdn.example.com/S--value--/image.png",
            "https://cdn.example.com/STORAGE/V1/OBJECT/SIGN/value",
            "https://cdn.example.com/storage/v1/render/image/sign/value",
            "https://cdn.example.com/images;JSESSIONID=value/a.png",
        ] {
            assert_eq!(try_canonicalize(raw), Err(Decline::Credential), "{raw}");
        }
    }

    #[test]
    fn percent_encoded_credential_path_patterns_are_refused() {
        for raw in [
            "https://cdn.example.com/BCDN%5fTOKEN=value/image.png",
            "https://objectstorage.region.oraclecloud.com/%70/value/%6e/image.png",
            "https://cdn.example.com/S%2d%2dvalue%2d%2d/image.png",
            "https://cdn.example.com/storage/v1/object/s%69gn/value",
            "https://cdn.example.com/storage/v1/render/image/s%69gn/value",
            "https://cdn.example.com/images%3bJSESSIONID=value/a.png",
        ] {
            assert_eq!(try_canonicalize(raw), Err(Decline::Credential), "{raw}");
        }
    }

    #[test]
    fn userinfo_and_invalid_query_names_are_refused() {
        assert_eq!(
            try_canonicalize("https://user:pass@cdn.example.com/a.png"),
            Err(Decline::Credential)
        );
        assert_eq!(
            try_canonicalize("https://cdn.example.com/a.png?bad%FF=value"),
            Err(Decline::InvalidQuery)
        );
        assert_eq!(
            try_canonicalize("https://cdn.example.com/a.png?bad%ZZ=value"),
            Err(Decline::InvalidQuery)
        );
    }

    #[test]
    fn signing_metadata_without_a_credential_is_preserved() {
        let raw = "https://cdn.example.com/a.png?X-Amz-Algorithm=v4&X-Amz-Date=20260810T000000Z&X-Amz-Expires=60";
        let canonical = canonicalize(raw).unwrap();
        assert!(canonical.fetch.contains("X-Amz-Algorithm=v4"));
        assert!(canonical.dedup.contains("X-Amz-Algorithm=v4"));
    }

    #[test]
    fn volatile_query_fields_stay_on_the_fetch_url_and_leave_the_global_ref() {
        let canonical = canonicalize(
            "https://cdn.example.com/a.png?w=200&%63b=first&CB=second&no%63ache=third&RND=fourth",
        )
        .unwrap();

        assert_eq!(
            canonical.fetch,
            "https://cdn.example.com/a.png?w=200&%63b=first&CB=second&no%63ache=third&RND=fourth"
        );
        assert_eq!(canonical.dedup, "https://cdn.example.com/a.png?w=200");
    }

    #[test]
    fn fetch_and_retained_dedup_query_bytes_are_never_rebuilt() {
        let raw = "https://cdn.example.com/a.png?flag&empty=&plus=a+b&space=a%20b&bytes=%FF&slash=%2f&cb=drop#fragment";
        let canonical = canonicalize(raw).unwrap();

        assert_eq!(
            canonical.fetch,
            "https://cdn.example.com/a.png?flag&empty=&plus=a+b&space=a%20b&bytes=%FF&slash=%2f&cb=drop"
        );
        assert_eq!(
            canonical.dedup,
            "https://cdn.example.com/a.png?flag&empty=&plus=a+b&space=a%20b&bytes=%FF&slash=%2f"
        );
    }

    #[test]
    fn distinct_raw_nonvolatile_queries_keep_distinct_global_refs() {
        let bare = canonicalize("https://cdn.example.com/a.png?flag").unwrap();
        let empty = canonicalize("https://cdn.example.com/a.png?flag=").unwrap();
        let plus = canonicalize("https://cdn.example.com/a.png?q=a+b").unwrap();
        let encoded_space = canonicalize("https://cdn.example.com/a.png?q=a%20b").unwrap();

        assert_ne!(bare.dedup, empty.dedup);
        assert_ne!(plus.dedup, encoded_space.dedup);
    }

    #[test]
    fn meta_query_fields_are_volatile_only_with_their_marker() {
        let without_marker =
            canonicalize("https://cdn.example.com/a.png?stp=first&ccb=second").unwrap();
        assert_eq!(
            without_marker.dedup,
            "https://cdn.example.com/a.png?stp=first&ccb=second"
        );

        let with_marker = canonicalize(
            "https://cdn.example.com/a.png?keep=1&_nc_%6Fhc=a&_NC_HT=b&ccb=c&oe=d&oh=e&stp=f",
        )
        .unwrap();
        assert_eq!(with_marker.dedup, "https://cdn.example.com/a.png?keep=1");
    }

    #[test]
    fn credentials_are_refused_before_volatile_query_fields_are_removed() {
        assert_eq!(
            try_canonicalize("https://cdn.example.com/a.png?cb=first&TOKEN=secret&cb=second"),
            Err(Decline::Credential)
        );
    }

    #[test]
    fn only_https_on_its_own_port_is_collected() {
        assert_eq!(canonicalize("https://cdn.example.com:11211/a.png"), None);
        assert_eq!(canonicalize("https://cdn.example.com:8443/a.png"), None);
        assert_eq!(canonicalize("http://cdn.example.com/a.png"), None);
        assert_eq!(canonicalize("http://cdn.example.com:80/a.png"), None);
        // The parser normalizes the default port away, so `url.port()` is None and `:443` passes.
        assert!(canonicalize("https://cdn.example.com:443/a.png").is_some());
        assert!(canonicalize("https://cdn.example.com/a.png").is_some());
    }

    #[test]
    fn the_politeness_key_is_the_operator_not_the_dns_label() {
        // A CDN that shards over numbered subdomains must share one budget.
        assert_eq!(politeness_key("img1.cdn.example.com"), "example.com");
        assert_eq!(politeness_key("img8.cdn.example.com"), "example.com");
        assert_eq!(politeness_key("example.com"), "example.com");
    }

    #[test]
    fn a_multi_tenant_host_keeps_its_tenants_apart() {
        // The private section of the public suffix list is what makes this correct. Without it,
        // every CloudFront distribution on the internet would share one budget and one partition.
        assert_eq!(politeness_key("d111.cloudfront.net"), "d111.cloudfront.net");
        assert_eq!(
            politeness_key("bucket.s3.amazonaws.com"),
            "bucket.s3.amazonaws.com"
        );
        assert_eq!(politeness_key("user.github.io"), "user.github.io");
        // The app-hosting case: a tenant subdomain is its own operator for our purposes.
        assert_eq!(politeness_key("myapp.vercel.app"), "myapp.vercel.app");
        assert_eq!(politeness_key("site.netlify.app"), "site.netlify.app");
        assert_eq!(politeness_key("worker.workers.dev"), "worker.workers.dev");
    }

    #[test]
    fn a_fully_qualified_host_keys_the_same_as_the_bare_one() {
        assert_eq!(politeness_key("example.com."), "example.com");
        assert_eq!(politeness_key("img1.cdn.example.com."), "example.com");
        assert_eq!(politeness_key("user.github.io."), "user.github.io");
    }

    #[test]
    fn an_ip_literal_is_its_own_operator() {
        assert_eq!(politeness_key("203.0.113.7"), "203.0.113.7");
        assert_eq!(politeness_key("[2606:4700::1111]"), "[2606:4700::1111]");
    }

    #[test]
    fn canonicalize_carries_the_politeness_key() {
        let c = canonicalize("https://img3.cdn.example.co.uk/a.png").unwrap();
        assert_eq!(c.host, "img3.cdn.example.co.uk");
        // A multi-label public suffix, which is why this cannot be "the last two labels".
        assert_eq!(c.domain, "example.co.uk");
    }

    #[test]
    fn a_gravatar_size_is_not_stripped() {
        let big = canonicalize("https://www.gravatar.com/avatar/abc?s=200").unwrap();
        let small = canonicalize("https://www.gravatar.com/avatar/abc?s=48").unwrap();
        assert_ne!(
            big.dedup, small.dedup,
            "two avatar sizes are two images and must not share a ref"
        );
    }

    #[test]
    fn a_non_public_host_is_never_collected() {
        // The URL set comes from page content, and the fetch lane runs inside our network. Every
        // one is https, or the scheme rule would refuse it before the host rule was reached.
        for raw in [
            "https://169.254.169.254/latest/meta-data/iam/security-credentials/",
            "https://localhost/admin/export.png",
            "https://127.0.0.1/i.png",
            "https://10.0.0.5/i.png",
            "https://192.168.1.1/i.png",
            "https://172.16.0.1/i.png",
            "https://[::1]/i.png",
            "https://[fd00::1]/i.png",
            "https://metadata.internal/i.png",
            "https://buildserver/i.png",
            // A trailing dot makes a name fully qualified and resolves the same way. It used to
            // walk past the name list, because the label after the final dot is empty.
            "https://localhost./i.png",
            "https://metadata.internal./i.png",
            "https://LOCALHOST./i.png",
            // IPv6 offers several ways to write an IPv4 address. Each one used to skip the IPv4
            // rules entirely.
            "https://[::ffff:0.0.0.0]/i.png",
            "https://[::ffff:127.0.0.1]/i.png",
            "https://[::ffff:10.0.0.5]/i.png",
            "https://[::ffff:100.64.0.1]/i.png",
            "https://[::127.0.0.1]/i.png",
            "https://[2002:7f00:1::]/i.png",
            "https://[64:ff9b::7f00:1]/i.png",
            "https://[ff02::1]/i.png",
            // Ranges we would never legitimately fetch from.
            "https://224.0.0.1/i.png",
            "https://240.0.0.1/i.png",
            "https://198.18.0.1/i.png",
            "https://192.0.0.1/i.png",
            "https://0.0.0.0/i.png",
        ] {
            assert!(canonicalize(raw).is_none(), "{raw} must not be collected");
        }
        assert!(canonicalize("https://cdn.example.com/i.png").is_some());
        // A public name with a trailing dot is still public, so the fix must not over-reject.
        assert!(canonicalize("https://cdn.example.com./i.png").is_some());
        assert!(canonicalize("https://[2606:4700::1111]/i.png").is_none());
        assert!(canonicalize("https://8.8.8.8/i.png").is_none());
    }

    #[test]
    fn a_fully_qualified_host_survives_the_whole_lane() {
        let c = canonicalize("https://cdn.example.com./i.png").expect("collected");
        // The consumer compares `new URL(fetch).hostname` with `host`. A dot on one side only
        // makes every fully qualified host fail that comparison.
        assert_eq!(c.host, "cdn.example.com");
        assert_eq!(c.fetch, "https://cdn.example.com/i.png");
    }

    #[test]
    fn a_cache_buster_does_not_identify_a_distinct_resource() {
        let plain = canonicalize("https://cdn.example.com/a.png?a=hello%20world&b=2").unwrap();
        let cache_busted =
            canonicalize("https://cdn.example.com/a.png?a=hello%20world&b=2&cb=zz").unwrap();
        assert_eq!(plain.dedup, cache_busted.dedup);
    }
}
