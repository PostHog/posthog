//! Domain model for the streaming gateway (plan §2.3).
//!
//! Small and dependency-free by design: everything the rest of the service
//! reasons about — which cache a subscriber follows, a content version, and the
//! single transition function that decides whether an observation changes
//! anything — lives here and is exhaustively unit-tested. Parse-don't-validate
//! is applied at the type boundaries so a malformed hint or a corrupt Redis
//! value can never enter the state machine.

use std::fmt;
use std::str::FromStr;

use common_types::TeamId;
use thiserror::Error;

/// Which Redis tier a cache kind is written to and read from.
///
/// A separate two-variant enum (rather than a bool) so callers name the tier
/// explicitly and the mapping from [`CacheKind`] stays the single source of
/// truth (plan §2.3).
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum RedisTier {
    /// Shared Redis tier (the general-purpose cache endpoint).
    Shared,
    /// Dedicated flags Redis tier; falls back to shared when unconfigured.
    DedicatedFlags,
}

/// Which cache snapshot a subscriber follows.
///
/// Encodes everything the rest of the service needs to know about a kind, so no
/// other module matches on it for these concerns: the HyperCache object name,
/// the Redis tier, the pub/sub ready channel, and the wire spelling all resolve
/// here (plan §2.3).
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub enum CacheKind {
    /// Mode 1: server SDK local evaluation. HyperCache value
    /// `flags_with_cohorts.json` on the shared Redis tier.
    Definitions,
    /// Mode 2: remote evaluation invalidation. HyperCache value `flags.json`
    /// on the dedicated flags Redis tier.
    RemoteEval,
}

impl CacheKind {
    /// The HyperCache object name this kind watches.
    pub fn hypercache_value(self) -> &'static str {
        match self {
            CacheKind::Definitions => "flags_with_cohorts.json",
            CacheKind::RemoteEval => "flags.json",
        }
    }

    /// The Redis tier the trigger sweep and hints read from for this kind.
    pub fn redis_tier(self) -> RedisTier {
        match self {
            CacheKind::Definitions => RedisTier::Shared,
            CacheKind::RemoteEval => RedisTier::DedicatedFlags,
        }
    }

    /// The Redis pub/sub channel the Django/Rust writers publish cache-ready
    /// signals to for this kind (plan §3.1).
    pub fn ready_channel(self) -> &'static str {
        match self {
            CacheKind::Definitions => "hypercache:ready:feature_flags:flags_with_cohorts.json",
            CacheKind::RemoteEval => "hypercache:ready:feature_flags:flags.json",
        }
    }

    /// The query-param / wire spelling of this kind. Parsing the inverse
    /// happens once, at the request boundary, via [`FromStr`].
    pub fn wire_name(self) -> &'static str {
        match self {
            CacheKind::Definitions => "definitions",
            CacheKind::RemoteEval => "remote_eval",
        }
    }
}

/// The `kind` query param was not one of the two known wire spellings.
#[derive(Debug, Error, PartialEq, Eq)]
#[error("unknown cache kind {0:?}; expected \"definitions\" or \"remote_eval\"")]
pub struct ParseCacheKindError(String);

impl FromStr for CacheKind {
    type Err = ParseCacheKindError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        match s {
            "definitions" => Ok(CacheKind::Definitions),
            "remote_eval" => Ok(CacheKind::RemoteEval),
            other => Err(ParseCacheKindError(other.to_string())),
        }
    }
}

/// A HyperCache content hash: exactly 16 lowercase-hex ascii chars
/// (sha256[:16], `posthog/storage/hypercache.py` == `common/hypercache`).
///
/// Stored as `[u8; 16]` ascii-hex so it is `Copy`, allocation-free, and
/// equality is a 16-byte compare. Deliberately **not** `Ord`: a content hash
/// has no ordering, so the state machine can never try to decide which of two
/// versions is "newer" — equality is the only comparison the protocol allows.
/// The replica-lag flap this would otherwise invite is closed in the trigger
/// layer by pinning all reads to the primary endpoint (plan §2.3, §2.7).
///
/// Constructed only via [`FromStr`] (parse-don't-validate), so a malformed hint
/// or a corrupt Redis value can never reach the state machine.
#[derive(Clone, Copy, PartialEq, Eq)]
pub struct Etag([u8; 16]);

/// An etag string was not exactly 16 lowercase-hex ascii chars.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum ParseEtagError {
    /// The input was not 16 bytes long.
    #[error("etag must be 16 chars, got {0}")]
    WrongLength(usize),
    /// The input contained a byte outside `0-9a-f` (uppercase included).
    #[error("etag must be lowercase hex, found {0:?}")]
    NotLowercaseHex(char),
}

impl FromStr for Etag {
    type Err = ParseEtagError;

    fn from_str(s: &str) -> Result<Self, Self::Err> {
        let bytes = s.as_bytes();
        if bytes.len() != 16 {
            return Err(ParseEtagError::WrongLength(bytes.len()));
        }
        for &b in bytes {
            let is_lower_hex = b.is_ascii_digit() || (b'a'..=b'f').contains(&b);
            if !is_lower_hex {
                return Err(ParseEtagError::NotLowercaseHex(b as char));
            }
        }
        let mut arr = [0u8; 16];
        arr.copy_from_slice(bytes);
        Ok(Etag(arr))
    }
}

impl fmt::Display for Etag {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        // The bytes are ascii-hex by construction (FromStr is the only ctor).
        f.write_str(std::str::from_utf8(&self.0).expect("etag is ascii-hex by construction"))
    }
}

impl fmt::Debug for Etag {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Etag({self})")
    }
}

/// One fanout topic: a team's view of one cache kind.
#[derive(Clone, Copy, PartialEq, Eq, Hash, Debug)]
pub struct Topic {
    pub team_id: TeamId,
    pub kind: CacheKind,
}

/// What a trigger source observed in Redis for a topic.
#[derive(Clone, Copy, PartialEq, Eq, Debug)]
pub enum Observation {
    /// A readable etag was present.
    Present(Etag),
    /// The key was absent or held the `__missing__` sentinel (the M4 trigger
    /// maps `get_etags_batch`'s `None` to this).
    Absent,
}

/// The value inside each topic's watch channel.
///
/// `Unknown` and `Missing` render identically on the wire (`version: null`) but
/// are kept distinct so the transition function can encode the truth table
/// exactly and metrics can tell "not yet observed" from "observed absent".
#[derive(Clone, Copy, PartialEq, Eq, Default, Debug)]
pub enum VersionState {
    /// Not yet observed since this pod started. Wire form `version: null`.
    #[default]
    Unknown,
    /// Cache absent/expired. Wire form `version: null`; clients must hold.
    Missing,
    /// A known content version. Wire form `version: <etag>`.
    Known(Etag),
}

impl VersionState {
    /// The one place that decides whether an observation changes the state.
    ///
    /// Returns `true` when the state changed, so it plugs directly into
    /// [`tokio::sync::watch::Sender::send_if_modified`] (whose closure is
    /// `FnOnce(&mut T) -> bool`) — receivers wake only on a real change. The
    /// arms are the plan §2.3 truth table verbatim. Note `Unknown + Absent`
    /// returns `true` even though the wire form is identical `null`: a harmless
    /// wake that keeps the transition total and easy to reason about.
    pub fn apply(&mut self, obs: Observation) -> bool {
        let next = match (*self, obs) {
            (VersionState::Unknown, Observation::Present(e)) => VersionState::Known(e),
            (VersionState::Unknown, Observation::Absent) => VersionState::Missing,
            // Spurious rebuilds with identical content never ping.
            (VersionState::Known(a), Observation::Present(b)) if a == b => return false,
            (VersionState::Known(_), Observation::Present(b)) => VersionState::Known(b),
            (VersionState::Known(_), Observation::Absent) => VersionState::Missing,
            (VersionState::Missing, Observation::Present(b)) => VersionState::Known(b),
            (VersionState::Missing, Observation::Absent) => return false,
        };
        *self = next;
        true
    }

    /// The etag the wire layer renders as `version`, or `None` when the beacon
    /// is `null` (`Unknown`/`Missing`).
    pub fn etag(&self) -> Option<Etag> {
        match self {
            VersionState::Known(e) => Some(*e),
            VersionState::Unknown | VersionState::Missing => None,
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use rstest::rstest;

    fn etag_a() -> Etag {
        Etag::from_str("0123456789abcdef").expect("valid etag")
    }

    fn etag_b() -> Etag {
        Etag::from_str("fedcba9876543210").expect("valid etag")
    }

    #[rstest]
    #[case(
        VersionState::Unknown,
        Observation::Present(etag_a()),
        VersionState::Known(etag_a()),
        true
    )]
    #[case(
        VersionState::Unknown,
        Observation::Absent,
        VersionState::Missing,
        true
    )]
    #[case(
        VersionState::Known(etag_a()),
        Observation::Present(etag_a()),
        VersionState::Known(etag_a()),
        false
    )]
    #[case(
        VersionState::Known(etag_a()),
        Observation::Present(etag_b()),
        VersionState::Known(etag_b()),
        true
    )]
    #[case(
        VersionState::Known(etag_a()),
        Observation::Absent,
        VersionState::Missing,
        true
    )]
    #[case(
        VersionState::Missing,
        Observation::Present(etag_b()),
        VersionState::Known(etag_b()),
        true
    )]
    #[case(
        VersionState::Missing,
        Observation::Absent,
        VersionState::Missing,
        false
    )]
    fn apply_truth_table(
        #[case] from: VersionState,
        #[case] obs: Observation,
        #[case] expected: VersionState,
        #[case] changed: bool,
    ) {
        let mut state = from;
        assert_eq!(state.apply(obs), changed, "changed flag mismatch");
        assert_eq!(state, expected, "resulting state mismatch");
    }

    #[test]
    fn default_is_unknown() {
        assert_eq!(VersionState::default(), VersionState::Unknown);
    }

    #[test]
    fn etag_helper_reflects_state() {
        assert_eq!(VersionState::Unknown.etag(), None);
        assert_eq!(VersionState::Missing.etag(), None);
        assert_eq!(VersionState::Known(etag_a()).etag(), Some(etag_a()));
    }

    #[test]
    fn etag_parses_valid_lowercase_hex() {
        let etag = Etag::from_str("0123456789abcdef").expect("valid");
        assert_eq!(etag.to_string(), "0123456789abcdef");
    }

    #[rstest]
    #[case("0123", ParseEtagError::WrongLength(4))]
    #[case("0123456789abcdef0", ParseEtagError::WrongLength(17))]
    #[case("", ParseEtagError::WrongLength(0))]
    fn etag_rejects_wrong_length(#[case] input: &str, #[case] expected: ParseEtagError) {
        assert_eq!(Etag::from_str(input), Err(expected));
    }

    #[test]
    fn etag_rejects_non_hex() {
        assert_eq!(
            Etag::from_str("0123456789abcdeg"),
            Err(ParseEtagError::NotLowercaseHex('g'))
        );
    }

    #[test]
    fn etag_rejects_uppercase() {
        assert_eq!(
            Etag::from_str("0123456789ABCDEF"),
            Err(ParseEtagError::NotLowercaseHex('A'))
        );
    }

    #[test]
    fn etag_display_round_trips() {
        for hex in ["0123456789abcdef", "fedcba9876543210", "00000000000000ff"] {
            let etag = Etag::from_str(hex).expect("valid");
            assert_eq!(etag.to_string(), hex);
        }
    }

    #[test]
    fn cache_kind_wire_round_trip() {
        for kind in [CacheKind::Definitions, CacheKind::RemoteEval] {
            assert_eq!(CacheKind::from_str(kind.wire_name()), Ok(kind));
        }
    }

    #[test]
    fn cache_kind_rejects_unknown_wire_name() {
        assert!(CacheKind::from_str("flags").is_err());
    }

    #[test]
    fn cache_kind_mapping_is_stable() {
        assert_eq!(
            CacheKind::Definitions.hypercache_value(),
            "flags_with_cohorts.json"
        );
        assert_eq!(CacheKind::RemoteEval.hypercache_value(), "flags.json");
        assert_eq!(CacheKind::Definitions.redis_tier(), RedisTier::Shared);
        assert_eq!(
            CacheKind::RemoteEval.redis_tier(),
            RedisTier::DedicatedFlags
        );
    }
}
