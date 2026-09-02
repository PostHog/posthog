use std::time::Duration;

use serde::{Deserialize, Serialize};

use super::ops::OpClass;

#[derive(Debug, Clone, Copy, PartialEq, PartialOrd, Serialize, Deserialize)]
#[serde(transparent)]
pub struct RatePerSecond(f64);

impl RatePerSecond {
    pub const ZERO: Self = Self(0.0);

    pub const fn new(value: f64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> f64 {
        self.0
    }

    pub fn is_active(self) -> bool {
        self.0 > 0.0
    }

    pub fn scaled(self, factor: f64) -> Self {
        Self(self.0 * factor)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ClassRates {
    pub average: RatePerSecond,
    pub five_minute_peak: RatePerSecond,
}

impl ClassRates {
    const fn new(average: f64, five_minute_peak: f64) -> Self {
        Self {
            average: RatePerSecond::new(average),
            five_minute_peak: RatePerSecond::new(five_minute_peak),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct ProdRates {
    pub person_upsert: ClassRates,
    pub distinct_id_assignment: ClassRates,
    pub merge: ClassRates,
    pub canonical_read: ClassRates,
}

pub const PROD_US_RATES: ProdRates = ProdRates {
    person_upsert: ClassRates::new(2_204.0, 5_788.0),
    distinct_id_assignment: ClassRates::new(981.0, 3_594.0),
    merge: ClassRates::new(17.2, 54.6),
    canonical_read: ClassRates::new(5_373.0, 14_474.0),
};

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum FeedMode {
    Open,
    Closed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Hook {
    Vacuum,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize, clap::ValueEnum)]
#[serde(rename_all = "snake_case")]
pub enum BenchmarkProfile {
    Smoke,
    Gate,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PhaseName {
    BaselineReads,
    SteadyMix,
    PeakMix,
    MergeStorm,
    Recovery,
    CatchUp,
}

impl PhaseName {
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::BaselineReads => "baseline_reads",
            Self::SteadyMix => "steady_mix",
            Self::PeakMix => "peak_mix",
            Self::MergeStorm => "merge_storm",
            Self::Recovery => "recovery",
            Self::CatchUp => "catch_up",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Serialize, Deserialize)]
pub struct RateSpec {
    pub class: OpClass,
    pub target: RatePerSecond,
    pub feed: FeedMode,
}

impl RateSpec {
    const fn open(class: OpClass, target: RatePerSecond) -> Self {
        Self {
            class,
            target,
            feed: FeedMode::Open,
        }
    }

    const fn closed(class: OpClass, target: RatePerSecond) -> Self {
        Self {
            class,
            target,
            feed: FeedMode::Closed,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Serialize)]
pub struct PhaseSpec {
    pub name: PhaseName,
    pub duration: Duration,
    pub rates: [RateSpec; OpClass::COUNT],
    pub pre_hooks: Vec<Hook>,
}

impl PhaseSpec {
    pub fn rate_for(&self, class: OpClass) -> &RateSpec {
        &self.rates[class.index()]
    }
}

pub fn standard_phases(
    profile: BenchmarkProfile,
    duration_override: Option<Duration>,
) -> Vec<PhaseSpec> {
    let average = rate_specs(
        PROD_US_RATES.person_upsert.average,
        PROD_US_RATES.distinct_id_assignment.average,
        PROD_US_RATES.merge.average,
        PROD_US_RATES.canonical_read.average,
        FeedMode::Open,
    );
    let peak = rate_specs(
        PROD_US_RATES.person_upsert.five_minute_peak,
        PROD_US_RATES.distinct_id_assignment.five_minute_peak,
        PROD_US_RATES.merge.five_minute_peak,
        PROD_US_RATES.canonical_read.five_minute_peak,
        FeedMode::Open,
    );
    let mut storm = average;
    storm[OpClass::Merge.index()].target = PROD_US_RATES.merge.five_minute_peak.scaled(10.0);
    let mut catch_up = peak;
    for class in OpClass::WRITE_CLASSES {
        catch_up[class.index()] = RateSpec::closed(class, catch_up[class.index()].target);
    }

    let baseline_reads = rate_specs(
        RatePerSecond::ZERO,
        RatePerSecond::ZERO,
        RatePerSecond::ZERO,
        PROD_US_RATES.canonical_read.average,
        FeedMode::Open,
    );

    [
        (PhaseName::BaselineReads, baseline_reads, Vec::new()),
        (PhaseName::SteadyMix, average, Vec::new()),
        (PhaseName::PeakMix, peak, Vec::new()),
        (PhaseName::MergeStorm, storm, Vec::new()),
        (PhaseName::Recovery, average, vec![Hook::Vacuum]),
        (PhaseName::CatchUp, catch_up, Vec::new()),
    ]
    .into_iter()
    .map(|(name, rates, pre_hooks)| PhaseSpec {
        name,
        duration: duration_override.unwrap_or_else(|| profile_duration(profile, name)),
        rates,
        pre_hooks,
    })
    .collect()
}

fn rate_specs(
    person_upsert: RatePerSecond,
    distinct_id_assignment: RatePerSecond,
    merge: RatePerSecond,
    canonical_read: RatePerSecond,
    write_feed: FeedMode,
) -> [RateSpec; OpClass::COUNT] {
    let write_spec = |class, target| match write_feed {
        FeedMode::Open => RateSpec::open(class, target),
        FeedMode::Closed => RateSpec::closed(class, target),
    };

    [
        write_spec(OpClass::PersonUpsert, person_upsert),
        write_spec(OpClass::DistinctIdAssignment, distinct_id_assignment),
        write_spec(OpClass::Merge, merge),
        RateSpec::open(OpClass::CanonicalRead, canonical_read),
    ]
}

const fn profile_duration(profile: BenchmarkProfile, phase: PhaseName) -> Duration {
    if matches!(profile, BenchmarkProfile::Smoke) {
        return Duration::from_secs(60);
    }

    match phase {
        PhaseName::BaselineReads => Duration::from_secs(5 * 60),
        PhaseName::SteadyMix => Duration::from_secs(30 * 60),
        PhaseName::PeakMix => Duration::from_secs(60 * 60),
        PhaseName::MergeStorm | PhaseName::Recovery | PhaseName::CatchUp => {
            Duration::from_secs(15 * 60)
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn standard_phases_encode_the_production_workload_and_feed_modes() {
        let phases = standard_phases(BenchmarkProfile::Gate, None);

        assert_eq!(
            phases.iter().map(|phase| phase.name).collect::<Vec<_>>(),
            vec![
                PhaseName::BaselineReads,
                PhaseName::SteadyMix,
                PhaseName::PeakMix,
                PhaseName::MergeStorm,
                PhaseName::Recovery,
                PhaseName::CatchUp,
            ]
        );

        let baseline = &phases[0];
        assert_eq!(
            baseline.rate_for(OpClass::CanonicalRead).target,
            PROD_US_RATES.canonical_read.average
        );
        for class in OpClass::WRITE_CLASSES {
            assert_eq!(baseline.rate_for(class).target, RatePerSecond::ZERO);
        }

        let steady = &phases[1];
        let peak = &phases[2];
        for (class, production) in [
            (OpClass::PersonUpsert, PROD_US_RATES.person_upsert),
            (
                OpClass::DistinctIdAssignment,
                PROD_US_RATES.distinct_id_assignment,
            ),
            (OpClass::Merge, PROD_US_RATES.merge),
            (OpClass::CanonicalRead, PROD_US_RATES.canonical_read),
        ] {
            assert_eq!(steady.rate_for(class).target, production.average);
            assert_eq!(peak.rate_for(class).target, production.five_minute_peak);
        }

        assert_eq!(
            phases[3].rate_for(OpClass::Merge).target,
            RatePerSecond::new(546.0)
        );
        assert_eq!(phases[4].pre_hooks, vec![Hook::Vacuum]);
        assert_eq!(phases[1].duration, Duration::from_secs(30 * 60));
        assert_eq!(phases[2].duration, Duration::from_secs(60 * 60));
        assert_eq!(phases[3].duration, Duration::from_secs(15 * 60));
        assert_eq!(phases[4].duration, Duration::from_secs(15 * 60));

        let catch_up = &phases[5];
        for class in OpClass::WRITE_CLASSES {
            assert_eq!(catch_up.rate_for(class).feed, FeedMode::Closed);
        }
        assert_eq!(
            catch_up.rate_for(OpClass::CanonicalRead).feed,
            FeedMode::Open
        );
    }

    #[test]
    fn smoke_and_override_durations_are_bounded_for_local_runs() {
        let smoke = standard_phases(BenchmarkProfile::Smoke, None);
        assert!(smoke
            .iter()
            .all(|phase| phase.duration == Duration::from_secs(60)));

        let override_duration = Duration::from_secs(3);
        let overridden = standard_phases(BenchmarkProfile::Gate, Some(override_duration));
        assert!(overridden
            .iter()
            .all(|phase| phase.duration == override_duration));
    }
}
