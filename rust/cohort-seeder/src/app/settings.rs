//! App layer: validated orchestrator/producer tunables parsed once from [`Config`]. Depends on
//! `config`, `domain`, `store`, and its `app` siblings; this `TryFrom<&Config>` is what keeps the
//! dependency arrow pointing down (`config` no longer names an `app` type).

use std::num::{NonZeroU16, NonZeroU32, NonZeroU64, NonZeroUsize};
use std::time::Duration;

use crate::config::Config;
use crate::domain::PlanCaps;
use crate::store::runs::RunKind;
use crate::store::{LeaseDuration, LeaseDurationError, MaxAttempts, MaxAttemptsError};

use super::deliver::QUEUE_FULL_BACKOFF_CAP;
use super::orchestrator::ORCHESTRATOR_LIVENESS_DEADLINE;

/// The person seed path's tunables. `OrchestratorSettings.person` is `None` when
/// `SEEDER_PERSON_SEEDS_ENABLED` is off — the type encodes "person path off".
#[derive(Debug, Clone, Copy)]
pub struct PersonSettings {
    pub seeds_per_sec: NonZeroU32,
    pub persons_per_chunk: NonZeroU64,
    /// The person path's own slot budget: a person chunk never occupies a behavioral slot, so a
    /// long person scan cannot stall live behavioral seeding.
    pub max_concurrent_chunks: NonZeroUsize,
    pub emit_nonmatchers: bool,
}

impl PersonSettings {
    /// The pacer is shared across concurrent person chunks, so one chunk's floor wall-clock is
    /// `persons_per_chunk / (seeds_per_sec / concurrency)` — and the ClickHouse cursor stays open
    /// across the paced produce, counting client read time against `max_execution_time`. Refuse a
    /// combination that would eat more than half that budget at startup rather than at hour four.
    fn validate_scan_budget(
        &self,
        ch_max_execution_time_secs: u64,
    ) -> Result<(), OrchestratorSettingsError> {
        let projected_secs = self
            .persons_per_chunk
            .get()
            .saturating_mul(self.max_concurrent_chunks.get() as u64)
            / u64::from(self.seeds_per_sec.get());
        let budget_secs = ch_max_execution_time_secs / 2;
        if projected_secs > budget_secs {
            return Err(OrchestratorSettingsError::PersonChunkExceedsScanBudget {
                projected_secs,
                budget_secs,
            });
        }
        Ok(())
    }
}

#[derive(Debug, Clone, Copy)]
pub struct OrchestratorSettings {
    pub(super) run_poll_interval: Duration,
    pub(super) max_concurrent_chunks: NonZeroUsize,
    pub(super) chunk_lease: LeaseDuration,
    pub(super) max_chunk_attempts: MaxAttempts,
    pub(super) plan_caps: PlanCaps,
    pub(super) producer: ProducerSettings,
    pub(super) person: Option<PersonSettings>,
}

impl OrchestratorSettings {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        run_poll_interval: Duration,
        max_concurrent_chunks: usize,
        chunk_lease: Duration,
        max_chunk_attempts: u32,
        max_lookback_days: u32,
        bands_per_day: u16,
        producer: ProducerSettings,
        person: Option<PersonSettings>,
    ) -> Result<Self, OrchestratorSettingsError> {
        if run_poll_interval.is_zero() {
            return Err(OrchestratorSettingsError::ZeroPollInterval);
        }
        if run_poll_interval >= ORCHESTRATOR_LIVENESS_DEADLINE {
            return Err(OrchestratorSettingsError::PollIntervalExceedsLivenessDeadline);
        }
        let max_concurrent_chunks = NonZeroUsize::new(max_concurrent_chunks)
            .ok_or(OrchestratorSettingsError::ZeroConcurrency)?;
        let chunk_lease = LeaseDuration::new(chunk_lease).map_err(|error| match error {
            LeaseDurationError::TooShort => OrchestratorSettingsError::LeaseTooShort,
            LeaseDurationError::TooLong => OrchestratorSettingsError::LeaseTooLong,
        })?;
        let max_chunk_attempts =
            MaxAttempts::new(max_chunk_attempts).map_err(|error| match error {
                MaxAttemptsError::Zero => OrchestratorSettingsError::ZeroMaxAttempts,
                MaxAttemptsError::OutOfRange(_) => OrchestratorSettingsError::MaxAttemptsOutOfRange,
            })?;
        // The `band` column is a smallint, so the count must fit i16 for band indices to encode.
        let bands_per_day = NonZeroU16::new(bands_per_day)
            .filter(|bands| i16::try_from(bands.get()).is_ok())
            .ok_or(OrchestratorSettingsError::BandsPerDayOutOfRange)?;
        Ok(Self {
            run_poll_interval,
            max_concurrent_chunks,
            chunk_lease,
            max_chunk_attempts,
            plan_caps: PlanCaps {
                max_lookback_days,
                bands_per_day,
            },
            producer,
            person,
        })
    }

    pub fn person(&self) -> Option<&PersonSettings> {
        self.person.as_ref()
    }

    /// The backfill kinds discovery binds. With the person gate off this is `['behavioral']`, so
    /// the running binary's behavior is identical to today's.
    pub(super) fn discovery_kinds(&self) -> &'static [RunKind] {
        if self.person.is_some() {
            &[RunKind::Behavioral, RunKind::PersonProperty]
        } else {
            &[RunKind::Behavioral]
        }
    }
}

impl TryFrom<&Config> for OrchestratorSettings {
    type Error = SettingsError;

    fn try_from(config: &Config) -> Result<Self, Self::Error> {
        let producer = ProducerSettings::new(
            config.seeder_max_inflight_tiles,
            Duration::from_millis(config.seeder_queue_full_backoff_ms),
        )?;
        let person = config
            .seeder_person_seeds_enabled
            .then(|| {
                let person = PersonSettings {
                    seeds_per_sec: NonZeroU32::new(config.seeder_person_seeds_per_sec)
                        .ok_or(OrchestratorSettingsError::ZeroPersonSeedRate)?,
                    persons_per_chunk: NonZeroU64::new(config.seeder_persons_per_chunk)
                        .ok_or(OrchestratorSettingsError::ZeroPersonsPerChunk)?,
                    max_concurrent_chunks: NonZeroUsize::new(
                        config.seeder_person_max_concurrent_chunks,
                    )
                    .ok_or(OrchestratorSettingsError::ZeroPersonConcurrency)?,
                    emit_nonmatchers: config.seeder_person_emit_nonmatchers,
                };
                person.validate_scan_budget(config.seeder_ch_max_execution_time_secs)?;
                Ok::<_, OrchestratorSettingsError>(person)
            })
            .transpose()?;
        Ok(Self::new(
            Duration::from_secs(config.seeder_run_poll_secs),
            config.seeder_max_concurrent_chunks,
            Duration::from_secs(config.seeder_chunk_lease_secs),
            config.seeder_max_chunk_attempts,
            config.seeder_max_lookback_days,
            config.seeder_bands_per_day,
            producer,
            person,
        )?)
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum OrchestratorSettingsError {
    #[error("run poll interval must be greater than zero")]
    ZeroPollInterval,
    #[error("run poll interval must be shorter than the liveness deadline")]
    PollIntervalExceedsLivenessDeadline,
    #[error("maximum concurrent chunks must be greater than zero")]
    ZeroConcurrency,
    #[error("chunk lease must be at least three seconds")]
    LeaseTooShort,
    #[error("chunk lease exceeds PostgreSQL interval range")]
    LeaseTooLong,
    #[error("maximum chunk attempts must be greater than zero")]
    ZeroMaxAttempts,
    #[error("maximum chunk attempts exceeds PostgreSQL integer range")]
    MaxAttemptsOutOfRange,
    #[error("bands per day must be between 1 and 32767")]
    BandsPerDayOutOfRange,
    #[error("person seeds per second must be greater than zero")]
    ZeroPersonSeedRate,
    #[error("persons per chunk must be greater than zero")]
    ZeroPersonsPerChunk,
    #[error("person max concurrent chunks must be greater than zero")]
    ZeroPersonConcurrency,
    #[error(
        "one person chunk needs ~{projected_secs}s at the configured rate and concurrency, over \
         the {budget_secs}s scan budget (half of SEEDER_CH_MAX_EXECUTION_TIME_SECS); shrink \
         SEEDER_PERSONS_PER_CHUNK or raise SEEDER_PERSON_SEEDS_PER_SEC"
    )]
    PersonChunkExceedsScanBudget {
        projected_secs: u64,
        budget_secs: u64,
    },
}

/// The produce sequencing's tunables: the in-flight delivery bound and the queue-full backoff (capped
/// at [`QUEUE_FULL_BACKOFF_CAP`]). Consumed by `app::deliver`.
#[derive(Debug, Clone, Copy)]
pub struct ProducerSettings {
    pub(super) max_inflight: NonZeroUsize,
    pub(super) queue_full_backoff: Duration,
}

impl ProducerSettings {
    pub fn new(
        max_inflight: usize,
        queue_full_backoff: Duration,
    ) -> Result<Self, ProducerSettingsError> {
        let max_inflight =
            NonZeroUsize::new(max_inflight).ok_or(ProducerSettingsError::ZeroMaxInflight)?;
        if queue_full_backoff.is_zero() {
            return Err(ProducerSettingsError::ZeroQueueFullBackoff);
        }
        Ok(Self {
            max_inflight,
            queue_full_backoff: queue_full_backoff.min(QUEUE_FULL_BACKOFF_CAP),
        })
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum ProducerSettingsError {
    #[error("maximum in-flight tiles must be greater than zero")]
    ZeroMaxInflight,
    #[error("queue-full backoff must be greater than zero")]
    ZeroQueueFullBackoff,
}

/// Folds the producer- and orchestrator-settings validations behind one `TryFrom<&Config>` error, so
/// the seeder binary sees a single failure type when parsing its environment.
#[derive(Debug, thiserror::Error)]
pub enum SettingsError {
    #[error(transparent)]
    Producer(#[from] ProducerSettingsError),
    #[error(transparent)]
    Orchestrator(#[from] OrchestratorSettingsError),
}

#[cfg(test)]
mod tests {
    use std::collections::HashMap;

    use envconfig::Envconfig;

    use super::*;

    fn producer_settings() -> ProducerSettings {
        ProducerSettings::new(1, Duration::from_millis(1)).unwrap()
    }

    #[test]
    fn producer_settings_reject_unbounded_bounds() {
        assert_eq!(
            ProducerSettings::new(0, Duration::from_millis(1)).unwrap_err(),
            ProducerSettingsError::ZeroMaxInflight
        );
        assert_eq!(
            ProducerSettings::new(1, Duration::ZERO).unwrap_err(),
            ProducerSettingsError::ZeroQueueFullBackoff
        );
        assert_eq!(
            ProducerSettings::new(1, Duration::from_secs(60))
                .unwrap()
                .queue_full_backoff,
            QUEUE_FULL_BACKOFF_CAP
        );
    }

    #[test]
    fn settings_reject_values_that_disable_progress_or_lease_heartbeats() {
        let cases = [
            (
                OrchestratorSettings::new(
                    ORCHESTRATOR_LIVENESS_DEADLINE,
                    1,
                    Duration::from_secs(3),
                    1,
                    400,
                    1,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::PollIntervalExceedsLivenessDeadline,
            ),
            (
                OrchestratorSettings::new(
                    Duration::ZERO,
                    1,
                    Duration::from_secs(3),
                    1,
                    400,
                    1,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::ZeroPollInterval,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    0,
                    Duration::from_secs(3),
                    1,
                    400,
                    1,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::ZeroConcurrency,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    1,
                    Duration::from_secs(2),
                    1,
                    400,
                    1,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::LeaseTooShort,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    1,
                    Duration::from_secs(3),
                    0,
                    400,
                    1,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::ZeroMaxAttempts,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    1,
                    Duration::from_secs(3),
                    1,
                    400,
                    0,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::BandsPerDayOutOfRange,
            ),
            (
                OrchestratorSettings::new(
                    Duration::from_secs(1),
                    1,
                    Duration::from_secs(3),
                    1,
                    400,
                    u16::MAX,
                    producer_settings(),
                    None,
                ),
                OrchestratorSettingsError::BandsPerDayOutOfRange,
            ),
        ];
        for (result, expected) in cases {
            assert_eq!(result.unwrap_err(), expected);
        }
    }

    /// Dark-by-default: with the gate off discovery binds behavioral only; enabling it validates
    /// the person rates the way `ZeroTileRate` guards the behavioral pacer.
    #[test]
    fn person_settings_are_gated_and_validated() {
        let config = Config::init_from_hashmap(&HashMap::new()).unwrap();
        let dark = OrchestratorSettings::try_from(&config).unwrap();
        assert!(dark.person().is_none());
        assert_eq!(dark.discovery_kinds(), &[RunKind::Behavioral]);

        let mut enabled = config.clone();
        enabled.seeder_person_seeds_enabled = true;
        let lit = OrchestratorSettings::try_from(&enabled).unwrap();
        assert!(lit.person().is_some());
        assert_eq!(
            lit.discovery_kinds(),
            &[RunKind::Behavioral, RunKind::PersonProperty]
        );

        enabled.seeder_person_seeds_per_sec = 0;
        assert!(matches!(
            OrchestratorSettings::try_from(&enabled),
            Err(SettingsError::Orchestrator(
                OrchestratorSettingsError::ZeroPersonSeedRate
            ))
        ));
        enabled.seeder_person_seeds_per_sec = 2000;
        enabled.seeder_persons_per_chunk = 0;
        assert!(matches!(
            OrchestratorSettings::try_from(&enabled),
            Err(SettingsError::Orchestrator(
                OrchestratorSettingsError::ZeroPersonsPerChunk
            ))
        ));
        enabled.seeder_persons_per_chunk = 1_000_000;
        enabled.seeder_person_max_concurrent_chunks = 0;
        assert!(matches!(
            OrchestratorSettings::try_from(&enabled),
            Err(SettingsError::Orchestrator(
                OrchestratorSettingsError::ZeroPersonConcurrency
            ))
        ));
    }

    /// A chunk whose floor wall-clock (shared pacer, concurrency multiplier) would eat more than
    /// half the ClickHouse execution-time budget must refuse at startup, not at hour four.
    #[test]
    fn person_chunk_sizing_must_fit_the_clickhouse_scan_budget() {
        let mut config = Config::init_from_hashmap(&HashMap::new()).unwrap();
        config.seeder_person_seeds_enabled = true;
        assert!(OrchestratorSettings::try_from(&config).is_ok());

        // 5M persons at 2000/s across 6 concurrent chunks ⇒ 15000s > 14400/2.
        config.seeder_persons_per_chunk = 5_000_000;
        config.seeder_person_max_concurrent_chunks = 6;
        assert!(matches!(
            OrchestratorSettings::try_from(&config),
            Err(SettingsError::Orchestrator(
                OrchestratorSettingsError::PersonChunkExceedsScanBudget {
                    projected_secs: 15_000,
                    budget_secs: 7_200,
                }
            ))
        ));
    }

    #[test]
    fn try_from_config_rejects_disabled_concurrency() {
        let mut config = Config::init_from_hashmap(&HashMap::new()).unwrap();
        config.seeder_max_concurrent_chunks = 0;
        assert!(matches!(
            OrchestratorSettings::try_from(&config),
            Err(SettingsError::Orchestrator(
                OrchestratorSettingsError::ZeroConcurrency
            ))
        ));
    }
}
