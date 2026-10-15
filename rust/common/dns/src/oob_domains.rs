//! Out-of-band interaction domains, and the check the outbound guards run on a host.
//!
//! Every other host guard here is IP-based, and an out-of-band interaction domain resolves to
//! an ordinary public IP, so the lookup alone confirms the path to whoever runs the collaborator.
//! The guards log a match. Nothing is refused yet.

use tracing::info;

/// Mirror of posthog/security/crosslang/oob_domains.json. Edit that file first, then this list.
/// The parity test mirror_matches_the_shared_json fails when they differ.
pub const OOB_DOMAINS: &[&str] = &[
    "1u.ms",
    "burpcollaborator.net",
    "ceye.io",
    "dnslog.cn",
    "interact.sh",
    "oast.fun",
    "oast.live",
    "oast.me",
    "oast.online",
    "oast.pro",
    "oast.site",
    "oastify.com",
    "rbndr.us",
];

/// The listed domain this host belongs to, or None.
///
/// Pass a host that `url` parsed, never a raw url. The `url` crate applies IDNA, so an
/// internationalized name arrives in the ASCII form this list holds.
pub fn matched_oob_domain(host: &str) -> Option<&'static str> {
    if host.is_empty() || host.contains('@') || host.contains('/') {
        // A match on a raw url or a credential would put that string in the log line.
        return None;
    }
    // The resolver treats the absolute form ("oast.live.") as the same name.
    let canonical = host.trim_end_matches('.').to_ascii_lowercase();
    OOB_DOMAINS
        .iter()
        .copied()
        .find(|domain| is_same_or_subdomain(&canonical, domain))
}

/// Log that a guard holds a listed host. Detection only: the caller still proceeds.
pub fn note_oob_domain(host: &str, guard: &'static str) {
    if let Some(domain) = matched_oob_domain(host) {
        info!(host, domain, guard, "security.oob_domain_seen");
    }
}

/// Whether the host is the domain itself, or sits under it on a label boundary. A plain suffix
/// test would also match "notoast.me", which belongs to somebody else.
fn is_same_or_subdomain(host: &str, domain: &str) -> bool {
    match host.len().checked_sub(domain.len()) {
        Some(0) => host == domain,
        Some(offset) => host.ends_with(domain) && host.as_bytes()[offset - 1] == b'.',
        None => false,
    }
}

#[cfg(test)]
mod tests {
    use super::matched_oob_domain;

    #[test]
    fn matches_a_listed_domain_exactly_or_on_a_label_boundary() {
        for (host, expected) in [
            ("oast.live", Some("oast.live")),
            ("x.oast.live", Some("oast.live")),
            ("a.b.oast.pro", Some("oast.pro")),
            ("burpcollaborator.net", Some("burpcollaborator.net")),
            ("sub.oastify.com", Some("oastify.com")),
            ("OAST.ME", Some("oast.me")),
            ("oast.me.", Some("oast.me")),
            ("notoast.me", None),
            ("myoast.live", None),
            ("oast.me.evil.example", None),
            ("example.com", None),
            ("", None),
            ("1.2.3.4", None),
            ("https://oast.live/a.js", None),
            ("user:pass@oast.live", None),
        ] {
            assert_eq!(matched_oob_domain(host), expected, "host: {host}");
        }
    }
}
