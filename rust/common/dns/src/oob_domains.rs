//! Out-of-band interaction domains, and the check the outbound guards run on a host.
//!
//! Every other host guard here is IP-based, and an out-of-band interaction domain resolves to
//! an ordinary public IP, so the lookup alone confirms the path to whoever runs the collaborator.
//! The guards log a match. Nothing is refused yet.

use std::collections::HashMap;
#[cfg(feature = "test-util")]
use std::sync::atomic::{AtomicBool, Ordering};
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

const MAX_DNS_NAME_LEN: usize = 253;

/// The listed domain this host belongs to, or None.
///
/// Pass a host that `url` parsed, never a raw url. The `url` crate applies IDNA, so an
/// internationalized name arrives in the ASCII form this list holds.
pub fn matched_oob_domain(host: &str) -> Option<&'static str> {
    if host.is_empty() || host.contains('@') || host.contains('/') {
        // A match on a raw url or a credential would put that string in the log line.
        return None;
    }
    if host.strip_suffix('.').unwrap_or(host).len() > MAX_DNS_NAME_LEN {
        // The url crate parses a name of any length, and a match keeps the host in the dedupe map.
        return None;
    }
    // The resolver treats the absolute form ("oast.live.") as the same name.
    let canonical = host.trim_end_matches('.').to_ascii_lowercase();
    OOB_DOMAINS
        .iter()
        .copied()
        .find(|domain| is_same_or_subdomain(&canonical, domain))
}

/// Same set as `is_cloud` in posthog/cloud_utils.py and `isCloud` in the node env utils.
const CLOUD_DEPLOYMENTS: &[&str] = &["EU", "US", "DEV", "E2E"];

/// A test cannot use `set_var`: it races libc environment reads from DNS lookups on other threads.
#[cfg(feature = "test-util")]
static FORCE_CLOUD: AtomicBool = AtomicBool::new(false);

/// Whether this deployment is PostHog Cloud. The python and node guards read the same variable.
///
/// Read per call rather than cached, because it is only reached once a host already matched, which
/// is rare.
fn is_cloud() -> bool {
    #[cfg(feature = "test-util")]
    if FORCE_CLOUD.load(Ordering::Relaxed) {
        return true;
    }
    is_cloud_deployment(std::env::var("CLOUD_DEPLOYMENT").ok().as_deref())
}

fn is_cloud_deployment(value: Option<&str>) -> bool {
    value.is_some_and(|value| {
        CLOUD_DEPLOYMENTS
            .iter()
            .any(|cloud| value.eq_ignore_ascii_case(cloud))
    })
}

#[cfg(feature = "test-util")]
pub fn force_cloud() {
    FORCE_CLOUD.store(true, Ordering::Relaxed);
}

/// One line per host, team and guard in this window. A resolver sees a host once per
/// connection, so an undeduped count tracks traffic rather than probing.
const DEDUPE_WINDOW: Duration = Duration::from_secs(15 * 60);
const DEDUPE_MAX_ENTRIES: usize = 10_000;

type SeenMap = HashMap<(&'static str, Option<i32>, String), Instant>;
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

fn first_sight_in_window(
    guard: &'static str,
    team_id: Option<i32>,
    host: &str,
    now: Instant,
) -> bool {
    let mut seen = seen_map();
    // The team is part of the key so that a sighting for one project does not suppress the
    // line for another.
    let key = (guard, team_id, host.to_owned());
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
///
/// A guard that knows the project passes its id. The shared resolvers and a redirect hop do not
/// have one, so they pass `None` and the line carries no `team_id`.
pub fn note_oob_domain(host: &str, guard: &'static str, team_id: Option<i32>) {
    // Match first: almost every host misses, and the miss costs a few string comparisons, which
    // keeps the environment read and the lock off the common path.
    let Some(domain) = matched_oob_domain(host) else {
        return;
    };
    if !is_cloud() {
        return;
    }
    if !first_sight_in_window(guard, team_id, host, Instant::now()) {
        return;
    }
    // `Option` records the inner value and omits the field for `None`, so a line either names a
    // team or carries no `team_id` field at all.
    info!(team_id, host, domain, guard, "security.oob_domain_seen");
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
    use super::{first_sight_in_window, is_cloud_deployment, matched_oob_domain};
    use std::time::Instant;

    #[test]
    fn only_a_cloud_deployment_value_counts_as_cloud() {
        for (value, expected) in [
            (Some("US"), true),
            (Some("EU"), true),
            (Some("DEV"), true),
            (Some("E2E"), true),
            (Some("us"), true),
            (Some("local"), false),
            (Some("TEST"), false),
            (Some(""), false),
            (None, false),
        ] {
            assert_eq!(is_cloud_deployment(value), expected, "value: {value:?}");
        }
    }

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

    #[test]
    fn a_host_longer_than_a_dns_name_never_matches() {
        let longest = format!("{}.oast.me", "a".repeat(245));
        assert_eq!(longest.len(), 253);
        assert_eq!(matched_oob_domain(&longest), Some("oast.me"));
        assert_eq!(matched_oob_domain(&format!("{longest}.")), Some("oast.me"));
        assert_eq!(matched_oob_domain(&format!("a{longest}")), None);
        assert_eq!(
            matched_oob_domain(&format!("x.oast.me{}", ".".repeat(300))),
            None
        );
    }

    #[test]
    fn one_team_does_not_dedupe_another_teams_sighting() {
        let now = Instant::now();
        let host = "one-team-does-not-dedupe.oast.me";
        assert!(first_sight_in_window("g", Some(1), host, now));
        // An actor can probe several projects with the same host, so a key without the team
        // would report the first project and hide the rest for the window.
        assert!(first_sight_in_window("g", Some(2), host, now));
        assert!(first_sight_in_window("g", None, host, now));
        assert!(!first_sight_in_window("g", Some(1), host, now));
    }
}
