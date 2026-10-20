//! Out-of-band interaction domains, and the check the outbound guards run on a host.
//!
//! Every other host guard here is IP-based, and an out-of-band interaction domain resolves to
//! an ordinary public IP, so the lookup alone confirms the path to whoever runs the collaborator.
//! The guards log a match. Nothing is refused yet.

use std::collections::HashMap;
use std::sync::{Mutex, OnceLock};
use std::time::{Duration, Instant};

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

/// Whether this deployment is PostHog Cloud. The python and node guards read the same variable.
///
/// Read per call rather than cached, because it is only reached once a host already matched, which
/// is rare, and a cached value could not be varied by a test.
fn is_cloud() -> bool {
    std::env::var("CLOUD_DEPLOYMENT")
        .map(|v| !v.trim().is_empty())
        .unwrap_or(false)
}

/// One line per host and guard in this window. A resolver sees a host once per connection, so an
/// undeduped count tracks traffic rather than probing.
const DEDUPE_WINDOW: Duration = Duration::from_secs(15 * 60);
const DEDUPE_MAX_ENTRIES: usize = 10_000;

type SeenMap = HashMap<(&'static str, String), Instant>;
static SEEN: OnceLock<Mutex<SeenMap>> = OnceLock::new();

fn seen_map() -> std::sync::MutexGuard<'static, SeenMap> {
    match SEEN.get_or_init(|| Mutex::new(HashMap::new())).lock() {
        Ok(seen) => seen,
        // A poisoned lock must not cost us the detection, and must not panic a guard either.
        Err(poisoned) => poisoned.into_inner(),
    }
}

/// Forget every recorded sighting, so one test cannot suppress the next one's log line.
#[cfg(feature = "test-util")]
pub fn reset_dedupe() {
    seen_map().clear();
}

fn first_sight_in_window(guard: &'static str, host: &str, now: Instant) -> bool {
    let mut seen = seen_map();
    let key = (guard, host.to_owned());
    if let Some(at) = seen.get(&key) {
        if now.duration_since(*at) < DEDUPE_WINDOW {
            return false;
        }
    }
    if seen.len() >= DEDUPE_MAX_ENTRIES {
        // Cheaper than an LRU, and the window makes a stale entry harmless.
        seen.retain(|_, at| now.duration_since(*at) < DEDUPE_WINDOW);
        if seen.len() >= DEDUPE_MAX_ENTRIES {
            seen.clear();
        }
    }
    seen.insert(key, now);
    true
}

/// Log that a guard holds a listed host. Detection only: the caller still proceeds.
pub fn note_oob_domain(host: &str, guard: &'static str) {
    // Match first: almost every host misses, and the miss costs a few string comparisons, which
    // keeps the environment read and the lock off the common path.
    let Some(domain) = matched_oob_domain(host) else {
        return;
    };
    if !is_cloud() {
        return;
    }
    if !first_sight_in_window(guard, host, Instant::now()) {
        return;
    }
    info!(host, domain, guard, "security.oob_domain_seen");
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
