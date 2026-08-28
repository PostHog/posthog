//! Pure pacing types for the seed consumer's admission gates: *why* a partition's work is held,
//! for how long, and the hysteresis that keeps the gates from flapping.
//!
//! A seed partition is paused **iff** its holdover is non-empty. The [`PauseLedger`] records
//! per-partition cause sets plus the episode start, and both the pause target and the age/count
//! metrics derive from it, so "resumed while a cause is active" is unrepresentable: the target is
//! computed, never mutated.

use std::collections::{HashMap, HashSet};
use std::time::{Duration, Instant};

/// Why a seed partition's work is held in the holdover.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PauseCause {
    /// The apply fence: the live watermark has not cleared `s_chunk + margin`.
    Fence,
    /// The partition worker's channel (or intake budget) refused the dispatch.
    ChannelFull,
    /// Live consumption is lagging; seeding yields (live-priority).
    LiveLag,
    /// The store filesystem is above the pause threshold.
    DiskPressure,
}

impl PauseCause {
    pub const ALL: [PauseCause; 4] = [
        PauseCause::Fence,
        PauseCause::ChannelFull,
        PauseCause::LiveLag,
        PauseCause::DiskPressure,
    ];

    pub fn as_str(self) -> &'static str {
        match self {
            PauseCause::Fence => "fence",
            PauseCause::ChannelFull => "channel_full",
            PauseCause::LiveLag => "live_lag",
            PauseCause::DiskPressure => "disk_pressure",
        }
    }
}

/// A payload-free set of [`PauseCause`]s.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Default)]
pub struct CauseSet {
    fence: bool,
    channel_full: bool,
    live_lag: bool,
    disk_pressure: bool,
}

impl CauseSet {
    pub fn insert(&mut self, cause: PauseCause) {
        match cause {
            PauseCause::Fence => self.fence = true,
            PauseCause::ChannelFull => self.channel_full = true,
            PauseCause::LiveLag => self.live_lag = true,
            PauseCause::DiskPressure => self.disk_pressure = true,
        }
    }

    pub fn contains(self, cause: PauseCause) -> bool {
        match cause {
            PauseCause::Fence => self.fence,
            PauseCause::ChannelFull => self.channel_full,
            PauseCause::LiveLag => self.live_lag,
            PauseCause::DiskPressure => self.disk_pressure,
        }
    }

    pub fn union(self, other: Self) -> Self {
        Self {
            fence: self.fence || other.fence,
            channel_full: self.channel_full || other.channel_full,
            live_lag: self.live_lag || other.live_lag,
            disk_pressure: self.disk_pressure || other.disk_pressure,
        }
    }

    pub fn is_empty(self) -> bool {
        self == Self::default()
    }
}

/// One continuous pause of one partition. `started` survives cause churn, so the age is the
/// continuous-pause age, not the current cause's age.
#[derive(Debug)]
struct PauseEpisode {
    started: Instant,
    causes: CauseSet,
}

/// Per-partition pause bookkeeping: cause sets plus episode start, reconciled once per cycle.
#[derive(Debug, Default)]
pub struct PauseLedger {
    episodes: HashMap<i32, PauseEpisode>,
}

impl PauseLedger {
    /// Record this cycle's causes for `partition`. An empty set ends the episode; a non-empty set
    /// starts one or updates the causes while keeping the original `started`.
    pub fn reconcile(&mut self, partition: i32, causes: CauseSet, now: Instant) {
        if causes.is_empty() {
            self.episodes.remove(&partition);
            return;
        }
        self.episodes
            .entry(partition)
            .and_modify(|episode| episode.causes = causes)
            .or_insert(PauseEpisode {
                started: now,
                causes,
            });
    }

    /// The partitions to pause — exactly those inside an episode.
    pub fn pause_target(&self) -> HashSet<i32> {
        self.episodes.keys().copied().collect()
    }

    /// Whether `partition` is currently held for `cause` — the hysteresis memory.
    pub fn has_cause(&self, partition: i32, cause: PauseCause) -> bool {
        self.episodes
            .get(&partition)
            .is_some_and(|episode| episode.causes.contains(cause))
    }

    /// How long `partition` has been continuously paused; `None` when not paused.
    pub fn age(&self, partition: i32, now: Instant) -> Option<Duration> {
        self.episodes
            .get(&partition)
            .map(|episode| now.duration_since(episode.started))
    }

    /// Paused partitions holding `cause`. A partition with several causes counts under each.
    pub fn count_with(&self, cause: PauseCause) -> usize {
        self.episodes
            .values()
            .filter(|episode| episode.causes.contains(cause))
            .count()
    }

    /// Drop episodes for partitions no longer owned, mirroring the holdover's revoke prune, so a
    /// stale episode can neither pause an unowned toppar nor keep aging its gauge.
    pub fn drop_unowned(&mut self, owned: &HashSet<i32>) {
        self.episodes
            .retain(|partition, _| owned.contains(partition));
    }
}

/// A flap-free threshold pair: engage at `engage` or above, release strictly below `release`,
/// sticky in between. Constructible only with `engage > release`, so a flapping pair is
/// unrepresentable.
#[derive(Debug, Clone, Copy)]
pub struct Hysteresis<T: PartialOrd + Copy> {
    engage: T,
    release: T,
}

/// Rejected [`Hysteresis`] thresholds: `engage <= release` would flap or never release.
#[derive(Debug, PartialEq, Eq, thiserror::Error)]
#[error("hysteresis requires engage > release")]
pub struct InvalidHysteresis;

impl<T: PartialOrd + Copy> Hysteresis<T> {
    pub fn new(engage: T, release: T) -> Result<Self, InvalidHysteresis> {
        if engage > release {
            Ok(Self { engage, release })
        } else {
            Err(InvalidHysteresis)
        }
    }

    /// The next engaged state given the previous one.
    pub fn decide(&self, engaged: bool, value: T) -> bool {
        if engaged {
            value >= self.release
        } else {
            value >= self.engage
        }
    }
}

/// A live-watermark age in ms — a unit newtype so ms and percent cannot cross at the
/// [`Hysteresis`] seam.
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
pub struct AgeMs(pub i64);

/// A filesystem used share, 0–100.
#[derive(Debug, Clone, Copy, PartialEq, PartialOrd)]
pub struct UsedPct(pub f64);

/// The seed consumer's pacing gates; `None` disables a trigger.
#[derive(Debug, Clone, Copy, Default)]
pub struct SeedPacingConfig {
    pub live_lag: Option<Hysteresis<AgeMs>>,
    pub disk: Option<Hysteresis<UsedPct>>,
}

/// The consume loop's pacing state: the ledger plus the disk gate's hysteresis memory. The disk
/// verdict is pod-wide, so its memory cannot live on any one partition's episode.
#[derive(Debug, Default)]
pub struct SeedPacing {
    pub ledger: PauseLedger,
    pub disk_engaged: bool,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn causes(list: &[PauseCause]) -> CauseSet {
        let mut set = CauseSet::default();
        for &cause in list {
            set.insert(cause);
        }
        set
    }

    #[test]
    fn cause_set_insert_contains_union_and_empty() {
        let mut set = CauseSet::default();
        assert!(set.is_empty());
        for cause in PauseCause::ALL {
            assert!(!set.contains(cause));
        }

        set.insert(PauseCause::LiveLag);
        assert!(!set.is_empty());
        assert!(set.contains(PauseCause::LiveLag));
        assert!(!set.contains(PauseCause::Fence));

        let merged = set.union(causes(&[PauseCause::Fence, PauseCause::DiskPressure]));
        assert!(merged.contains(PauseCause::LiveLag));
        assert!(merged.contains(PauseCause::Fence));
        assert!(merged.contains(PauseCause::DiskPressure));
        assert!(!merged.contains(PauseCause::ChannelFull));
    }

    /// A flapping pair (engage <= release) must be unconstructible; the decide table pins the
    /// engage-at/release-below boundary semantics.
    #[test]
    fn hysteresis_table() {
        assert!(Hysteresis::new(AgeMs(100), AgeMs(100)).is_err());
        assert!(Hysteresis::new(AgeMs(100), AgeMs(200)).is_err());

        let hysteresis = Hysteresis::new(AgeMs(100), AgeMs(50)).unwrap();
        let cases = [
            (false, 99, false, "below engage stays released"),
            (false, 100, true, "engages at the threshold"),
            (false, 101, true, "engages above the threshold"),
            (
                true,
                50,
                true,
                "at release stays engaged (releases strictly below)",
            ),
            (true, 75, true, "sticky between the thresholds"),
            (true, 49, false, "releases below the release threshold"),
            (
                false,
                75,
                false,
                "between the thresholds stays released when not engaged",
            ),
        ];
        for (engaged, value, expected, why) in cases {
            assert_eq!(hysteresis.decide(engaged, AgeMs(value)), expected, "{why}");
        }

        let pct = Hysteresis::new(UsedPct(60.0), UsedPct(55.0)).unwrap();
        assert!(pct.decide(false, UsedPct(60.0)));
        assert!(pct.decide(true, UsedPct(55.0)));
        assert!(!pct.decide(true, UsedPct(54.9)));
    }

    /// A cause change mid-episode must not reset the pause age; only a genuine resume (empty
    /// causes) starts a fresh episode.
    #[test]
    fn episode_age_survives_cause_churn_and_resets_after_resume() {
        let mut ledger = PauseLedger::default();
        let start = Instant::now();
        let later = start + Duration::from_secs(60);
        let latest = start + Duration::from_secs(120);

        ledger.reconcile(5, causes(&[PauseCause::Fence]), start);
        assert_eq!(ledger.age(5, later), Some(Duration::from_secs(60)));

        // The cause churns fence → live-lag; the episode keeps its original start.
        ledger.reconcile(5, causes(&[PauseCause::LiveLag]), later);
        assert_eq!(ledger.age(5, latest), Some(Duration::from_secs(120)));
        assert!(ledger.has_cause(5, PauseCause::LiveLag));
        assert!(!ledger.has_cause(5, PauseCause::Fence));

        // Resume, then a new pause starts a fresh episode.
        ledger.reconcile(5, CauseSet::default(), later);
        assert_eq!(ledger.age(5, latest), None);
        assert!(ledger.pause_target().is_empty());
        ledger.reconcile(5, causes(&[PauseCause::DiskPressure]), later);
        assert_eq!(ledger.age(5, latest), Some(Duration::from_secs(60)));
    }

    /// A revoked partition's episode must not keep aging its gauge or pause an unowned toppar.
    #[test]
    fn drop_unowned_prunes_episodes() {
        let mut ledger = PauseLedger::default();
        let now = Instant::now();
        ledger.reconcile(1, causes(&[PauseCause::Fence]), now);
        ledger.reconcile(2, causes(&[PauseCause::LiveLag, PauseCause::Fence]), now);

        assert_eq!(ledger.pause_target(), HashSet::from([1, 2]));
        assert_eq!(ledger.count_with(PauseCause::Fence), 2);
        assert_eq!(ledger.count_with(PauseCause::LiveLag), 1);
        assert_eq!(ledger.count_with(PauseCause::DiskPressure), 0);

        ledger.drop_unowned(&HashSet::from([2]));

        assert_eq!(ledger.pause_target(), HashSet::from([2]));
        assert_eq!(ledger.age(1, now), None);
        assert!(!ledger.has_cause(1, PauseCause::Fence));
        assert_eq!(ledger.count_with(PauseCause::Fence), 1);
    }
}
