//! Compares the Postgres person graph against the personhog writer's temp
//! tables for one team. One full outer join counts the per-field diffs in the
//! database and returns only the tallies. It polls until the graphs agree on a
//! drained cohort or the deadline passes.

use std::time::Duration;

use anyhow::{Context, Result};
use metrics::gauge;
use sqlx::postgres::{PgPoolOptions, PgRow};
use sqlx::{Executor, PgPool, Row};

pub const PROBE_INTERVAL: Duration = Duration::from_secs(5);
pub const COMPARE_INTERVAL: Duration = Duration::from_secs(30);
/// Caps one comparison well under the verify deadline.
const STATEMENT_TIMEOUT_MS: u64 = 120_000;

pub struct VerifyConfig {
    pub database_url: String,
    pub team_id: i64,
    pub tmp_person_table: String,
    pub tmp_pdi_table: String,
    pub deadline: Duration,
    pub probe_interval: Duration,
    pub compare_interval: Duration,
}

/// Tallies for one comparison. Field diffs count only ids present in both
/// graphs; a one-sided id is missing_shadow or extra_shadow instead.
pub struct Counts {
    pub main: i64,
    pub cohort: i64,
    pub mismatched: i64,
    pub missing_shadow: i64,
    pub extra_shadow: i64,
    pub uuid: i64,
    pub properties: i64,
    pub contested: i64,
    pub is_identified: i64,
    pub created_at: i64,
}

impl Counts {
    fn read(row: &PgRow) -> Self {
        Self {
            main: row.get("main_count"),
            cohort: row.get("cohort"),
            mismatched: row.get("mismatched"),
            missing_shadow: row.get("missing_shadow"),
            extra_shadow: row.get("extra_shadow"),
            uuid: row.get("uuid"),
            properties: row.get("properties"),
            contested: row.get("contested"),
            is_identified: row.get("is_identified"),
            created_at: row.get("created_at"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct Cohort {
    pub main: i64,
    pub shadow: i64,
}

fn is_drained(prev: Option<Cohort>, cohort: Cohort) -> bool {
    cohort.main > 0 && prev == Some(cohort)
}

fn is_pass(mismatched: i64, before: Cohort, after: Cohort, confirmed: Option<Cohort>) -> bool {
    mismatched == 0 && before.main > 0 && before == after && confirmed == Some(before)
}

/// Both legs project the fields compared for parity. created_at is truncated to
/// whole ms (the writer stores it at ms resolution), so sub-ms is not drift.
fn person_projection() -> &'static str {
    "d.distinct_id, p.uuid, p.properties, p.is_identified,
     date_trunc('milliseconds', p.created_at) AS created_at_ms"
}

pub struct Verifier {
    pool: PgPool,
    team_id: i64,
    tmp_person_table: String,
    tmp_pdi_table: String,
}

impl Verifier {
    pub async fn connect(cfg: &VerifyConfig) -> Result<Self> {
        let pool = PgPoolOptions::new()
            .max_connections(2)
            .after_connect(|conn, _meta| {
                Box::pin(async move {
                    conn.execute(
                        format!("SET statement_timeout = {STATEMENT_TIMEOUT_MS}").as_str(),
                    )
                    .await?;
                    Ok(())
                })
            })
            .connect(&cfg.database_url)
            .await
            .context("connecting to the persons database")?;
        Ok(Self::from_pool(
            pool,
            cfg.team_id,
            cfg.tmp_person_table.clone(),
            cfg.tmp_pdi_table.clone(),
        ))
    }

    pub fn from_pool(
        pool: PgPool,
        team_id: i64,
        tmp_person_table: String,
        tmp_pdi_table: String,
    ) -> Self {
        Self {
            pool,
            team_id,
            tmp_person_table,
            tmp_pdi_table,
        }
    }

    fn cohort_sql(&self) -> String {
        format!(
            "SELECT
                (SELECT count(*) FROM posthog_persondistinctid
                  WHERE team_id = $1 AND is_deleted = false) AS main_count,
                (SELECT count(*) FROM {tmp_pdi}
                  WHERE team_id = $1 AND is_deleted = false) AS shadow_count",
            tmp_pdi = self.tmp_pdi_table
        )
    }

    pub async fn probe(&self) -> Result<Cohort> {
        let row = sqlx::query(&self.cohort_sql())
            .bind(self.team_id)
            .fetch_one(&self.pool)
            .await
            .context("counting the cohort")?;
        Ok(Cohort {
            main: row.get("main_count"),
            shadow: row.get("shadow_count"),
        })
    }

    /// One full outer join of the two legs, counting differences by kind. Each
    /// leg is the team's live persons keyed by distinct id; `team_id = $1` on
    /// the `(team_id, distinct_id)` and PK indexes keeps both legs index scans
    /// over just the team's rows. Binds $1 team.
    fn comparison_sql(&self) -> String {
        let leg = |pdi: &str, person: &str| {
            format!(
                "SELECT {projection}
                   FROM {pdi} d
                   JOIN {person} p ON p.id = d.person_id AND p.team_id = d.team_id
                  WHERE d.team_id = $1 AND d.is_deleted = false AND p.is_deleted = false",
                projection = person_projection()
            )
        };
        let main = leg("posthog_persondistinctid", "posthog_person");
        let shadow = leg(&self.tmp_pdi_table, &self.tmp_person_table);
        format!(
            "WITH main AS ({main}), shadow AS ({shadow}), j AS (
                SELECT
                    m.distinct_id IS NULL AS extra_shadow,
                    s.distinct_id IS NULL AS missing_shadow,
                    m.uuid          IS DISTINCT FROM s.uuid          AS uuid_diff,
                    -- Keys every merged-in person also wrote take whichever value arrived last on
                    -- each backend, so they are checked by candidate below, not by value.
                    (m.properties - '{{loadgen_anon_seed,$creator_event_uuid}}'::text[])
                        IS DISTINCT FROM (s.properties - '{{loadgen_anon_seed,$creator_event_uuid}}'::text[]) AS properties_diff,
                    -- The seed key has a candidate set: the per-id keys of the seeds that reached the person.
                    (m.properties ? 'loadgen_anon_seed' AND NOT EXISTS (
                        SELECT 1 FROM jsonb_each_text(m.properties) kv
                        WHERE left(kv.key, 18) = 'loadgen_anon_seed_' AND kv.value = m.properties->>'loadgen_anon_seed'))
                    OR (s.properties ? 'loadgen_anon_seed' AND NOT EXISTS (
                        SELECT 1 FROM jsonb_each_text(s.properties) kv
                        WHERE left(kv.key, 18) = 'loadgen_anon_seed_' AND kv.value = s.properties->>'loadgen_anon_seed')) AS contested_diff,
                    m.is_identified IS DISTINCT FROM s.is_identified AS is_identified_diff,
                    m.created_at_ms IS DISTINCT FROM s.created_at_ms AS created_at_diff
                FROM main m FULL OUTER JOIN shadow s ON m.distinct_id = s.distinct_id
             )
             SELECT
                count(*) FILTER (WHERE NOT extra_shadow) AS main_count,
                count(*) AS cohort,
                count(*) FILTER (WHERE extra_shadow OR missing_shadow OR uuid_diff
                    OR properties_diff OR contested_diff OR is_identified_diff OR created_at_diff) AS mismatched,
                count(*) FILTER (WHERE missing_shadow) AS missing_shadow,
                count(*) FILTER (WHERE extra_shadow) AS extra_shadow,
                count(*) FILTER (WHERE uuid_diff AND NOT missing_shadow AND NOT extra_shadow) AS uuid,
                count(*) FILTER (WHERE properties_diff AND NOT missing_shadow AND NOT extra_shadow) AS properties,
                count(*) FILTER (WHERE contested_diff AND NOT missing_shadow AND NOT extra_shadow) AS contested,
                count(*) FILTER (WHERE is_identified_diff AND NOT missing_shadow AND NOT extra_shadow) AS is_identified,
                count(*) FILTER (WHERE created_at_diff AND NOT missing_shadow AND NOT extra_shadow) AS created_at
             FROM j"
        )
    }

    /// One comparison of the whole team cohort.
    pub async fn sweep(&self) -> Result<Counts> {
        let row = sqlx::query(&self.comparison_sql())
            .bind(self.team_id)
            .fetch_one(&self.pool)
            .await
            .context("comparing the cohort")?;
        Ok(Counts::read(&row))
    }

    fn export_gauges(&self, counts: &Counts) {
        gauge!("capture_loadgen_parity_cohort_size").set(counts.cohort as f64);
        gauge!("capture_loadgen_parity_authoritative_cohort").set(counts.main as f64);
        gauge!("capture_loadgen_parity_mismatched").set(counts.mismatched as f64);
        gauge!("capture_loadgen_parity_clean").set(if counts.mismatched == 0 { 1.0 } else { 0.0 });
        gauge!("capture_loadgen_parity_last_sweep_timestamp_seconds")
            .set(common_metrics::get_current_timestamp_seconds());
    }

    /// Polls until the graphs agree on a stable, drained cohort or the deadline
    /// passes. A transient query error retries; only a divergence that outlasts
    /// the deadline fails.
    pub async fn run(&self, cfg: &VerifyConfig) -> Result<bool> {
        let deadline = tokio::time::Instant::now() + cfg.deadline;
        let mut prev: Option<Cohort> = None;
        let mut confirmed: Option<Cohort> = None;
        let mut last_counts: Option<Counts> = None;
        loop {
            let before = match self.probe().await {
                Ok(cohort) => cohort,
                Err(error) => {
                    retry_or_give_up(error, deadline, "probe")?;
                    pause(deadline, cfg.probe_interval).await;
                    continue;
                }
            };
            tracing::info!(main = before.main, shadow = before.shadow, "cohort probed");
            if !is_drained(prev, before) {
                if tokio::time::Instant::now() >= deadline {
                    report_failure(cfg, last_counts.as_ref(), before);
                    return Ok(false);
                }
                prev = Some(before);
                pause(deadline, cfg.probe_interval).await;
                continue;
            }

            let counts = match self.sweep().await {
                Ok(counts) => counts,
                Err(error) => {
                    retry_or_give_up(error, deadline, "sweep")?;
                    pause(deadline, cfg.probe_interval).await;
                    continue;
                }
            };
            self.export_gauges(&counts);
            tracing::info!(
                cohort = counts.cohort,
                main_count = counts.main,
                mismatched = counts.mismatched,
                "sweep complete"
            );
            let after = match self.probe().await {
                Ok(cohort) => cohort,
                Err(error) => {
                    retry_or_give_up(error, deadline, "probe")?;
                    pause(deadline, cfg.probe_interval).await;
                    continue;
                }
            };
            if is_pass(counts.mismatched, before, after, confirmed) {
                tracing::info!(
                    cohort = counts.cohort,
                    "shadow graphs agree on a stable, drained cohort"
                );
                return Ok(true);
            }
            if tokio::time::Instant::now() >= deadline {
                report_failure(cfg, Some(&counts), after);
                return Ok(false);
            }
            let clean = counts.mismatched == 0 && before == after;
            confirmed = clean.then_some(after);
            last_counts = Some(counts);
            prev = Some(after);
            pause(
                deadline,
                if clean {
                    cfg.probe_interval
                } else {
                    cfg.compare_interval
                },
            )
            .await;
        }
    }
}

async fn pause(deadline: tokio::time::Instant, interval: Duration) {
    tokio::time::sleep_until(deadline.min(tokio::time::Instant::now() + interval)).await;
}

fn retry_or_give_up(
    error: anyhow::Error,
    deadline: tokio::time::Instant,
    what: &str,
) -> Result<()> {
    if tokio::time::Instant::now() >= deadline {
        return Err(error).context(format!("{what} failed at the deadline"));
    }
    tracing::warn!(error = format!("{error:#}"), "{} failed; retrying", what);
    Ok(())
}

fn report_failure(cfg: &VerifyConfig, counts: Option<&Counts>, cohort: Cohort) {
    let deadline_secs = cfg.deadline.as_secs();
    let Some(counts) = counts.filter(|c| c.mismatched > 0) else {
        tracing::warn!(
            main_count = cohort.main,
            shadow_count = cohort.shadow,
            deadline_secs,
            "verification expired without a divergence: the authoritative cohort never \
             stabilized at a non-zero size; ingestion is likely still draining, or nothing landed"
        );
        return;
    };
    tracing::warn!(
        cohort = counts.cohort,
        mismatched = counts.mismatched,
        missing_shadow = counts.missing_shadow,
        extra_shadow = counts.extra_shadow,
        uuid = counts.uuid,
        properties = counts.properties,
        contested = counts.contested,
        is_identified = counts.is_identified,
        created_at = counts.created_at,
        deadline_secs,
        "shadow parity verification failed; the diverging rows stay in the team until the \
         next run resets it, so query them there by team_id"
    );
}

#[cfg(test)]
mod tests {
    use super::*;

    fn cohort(main: i64, shadow: i64) -> Cohort {
        Cohort { main, shadow }
    }

    #[test]
    fn drained_needs_two_equal_probes_of_a_non_empty_cohort() {
        assert!(is_drained(Some(cohort(100, 100)), cohort(100, 100)));
        assert!(is_drained(Some(cohort(100, 90)), cohort(100, 90)));
        assert!(!is_drained(None, cohort(100, 100)));
        assert!(!is_drained(Some(cohort(90, 90)), cohort(100, 100)));
        assert!(!is_drained(Some(cohort(100, 90)), cohort(100, 100)));
        assert!(!is_drained(Some(cohort(0, 0)), cohort(0, 0)));
    }

    #[test]
    fn a_pass_needs_two_clean_comparisons_of_an_unmoved_non_empty_cohort() {
        let c = cohort(100, 100);
        assert!(is_pass(0, c, c, Some(c)));
        assert!(!is_pass(0, c, c, None));
        assert!(!is_pass(0, c, c, Some(cohort(90, 90))));
        assert!(!is_pass(1, c, c, Some(c)));
        assert!(!is_pass(0, c, cohort(110, 110), Some(c)));
        assert!(!is_pass(0, c, cohort(100, 101), Some(c)));
        assert!(!is_pass(0, cohort(0, 0), cohort(0, 0), Some(cohort(0, 0))));
    }
}
