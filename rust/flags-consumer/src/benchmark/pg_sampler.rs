use std::time::Duration;

use anyhow::Context;
use chrono::{DateTime, Utc};
use serde::Serialize;
use sqlx::postgres::PgPoolOptions;
use sqlx::PgPool;

use super::ops::{PhaseId, PhaseMismatch};

const TABLE_STATS_SQL: &str = r#"
    WITH target(parent_name) AS (
        VALUES ('flags_person'::text), ('flags_distinct_id_map'::text)
    )
    SELECT
        target.parent_name,
        COALESCE(SUM(stats.n_tup_ins), 0)::bigint,
        COALESCE(SUM(stats.n_tup_upd), 0)::bigint,
        COALESCE(SUM(stats.n_tup_del), 0)::bigint,
        COALESCE(SUM(stats.n_tup_hot_upd), 0)::bigint,
        COALESCE(SUM(stats.n_dead_tup), 0)::bigint,
        COALESCE(SUM(stats.vacuum_count), 0)::bigint,
        COALESCE(SUM(stats.autovacuum_count), 0)::bigint,
        COALESCE(SUM(pg_relation_size(child.oid)), 0)::bigint,
        COALESCE(SUM(pg_indexes_size(child.oid)), 0)::bigint,
        COUNT(child.oid)::bigint
    FROM target
    LEFT JOIN pg_class parent
      ON parent.relname = target.parent_name
     AND parent.relnamespace = current_schema()::regnamespace
    LEFT JOIN pg_inherits inheritance ON inheritance.inhparent = parent.oid
    LEFT JOIN pg_class child
      ON child.oid = inheritance.inhrelid AND child.relkind = 'r'
    LEFT JOIN pg_stat_user_tables stats ON stats.relid = child.oid
    GROUP BY target.parent_name
    ORDER BY target.parent_name
"#;

const WAL_POSITION_SQL: &str =
    "SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), '0/0'::pg_lsn)::bigint";
const SAMPLE_QUERY_TIMEOUT: Duration = Duration::from_secs(30);

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum TableGroup {
    Person,
    DistinctIdMap,
}

impl TableGroup {
    const ALL: [Self; 2] = [Self::Person, Self::DistinctIdMap];

    const fn table_name(self) -> &'static str {
        match self {
            Self::Person => "flags_person",
            Self::DistinctIdMap => "flags_distinct_id_map",
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct TableSnapshot {
    pub group: TableGroup,
    pub inserts: u64,
    pub updates: u64,
    pub deletes: u64,
    pub hot_updates: u64,
    pub dead_tuples: u64,
    pub vacuums: u64,
    pub autovacuums: u64,
    pub heap_bytes: u64,
    pub index_bytes: u64,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum WalSnapshot {
    Available { bytes_from_origin: u64 },
    Unavailable { reason: Box<str> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PgSnapshot {
    pub phase_id: PhaseId,
    pub sampled_at: DateTime<Utc>,
    pub tables: [TableSnapshot; 2],
    pub wal: WalSnapshot,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct TableDelta {
    pub group: TableGroup,
    pub inserts: u64,
    pub updates: u64,
    pub deletes: u64,
    pub hot_updates: u64,
    pub dead_tuples: u64,
    pub vacuums: u64,
    pub autovacuums: u64,
    pub heap_bytes: u64,
    pub index_bytes: u64,
    pub stats_reset_detected: bool,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum WalDelta {
    Available { bytes: u64 },
    Unavailable { reason: Box<str> },
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct PgDeltaRecord {
    pub record_type: &'static str,
    pub phase_id: PhaseId,
    pub sampled_at: DateTime<Utc>,
    pub elapsed_millis: u64,
    pub tables: [TableDelta; 2],
    pub wal: WalDelta,
}

#[derive(Debug)]
pub struct PgSampler {
    pool: PgPool,
    phase_id: PhaseId,
    previous: Option<PgSnapshot>,
}

impl PgSampler {
    pub async fn connect(database_url: &str, phase_id: PhaseId) -> anyhow::Result<Self> {
        let pool = PgPoolOptions::new()
            .max_connections(1)
            .min_connections(1)
            .acquire_timeout(Duration::from_secs(30))
            .connect(database_url)
            .await
            .context("connect PostgreSQL sampler pool")?;
        Ok(Self {
            pool,
            phase_id,
            previous: None,
        })
    }

    pub async fn sample(&self) -> anyhow::Result<PgSnapshot> {
        let rows = tokio::time::timeout(
            SAMPLE_QUERY_TIMEOUT,
            sqlx::query_as::<_, (String, i64, i64, i64, i64, i64, i64, i64, i64, i64, i64)>(
                TABLE_STATS_SQL,
            )
            .fetch_all(&self.pool),
        )
        .await
        .context("PostgreSQL table statistics sample timed out")?
        .context("sample PostgreSQL table statistics")?;
        let mut tables = Vec::with_capacity(TableGroup::ALL.len());
        for row in rows {
            let group = table_group(&row.0)?;
            anyhow::ensure!(
                row.10 > 0,
                "PostgreSQL sampler found no leaf partitions for {}",
                row.0
            );
            tables.push(TableSnapshot {
                group,
                inserts: nonnegative(row.1),
                updates: nonnegative(row.2),
                deletes: nonnegative(row.3),
                hot_updates: nonnegative(row.4),
                dead_tuples: nonnegative(row.5),
                vacuums: nonnegative(row.6),
                autovacuums: nonnegative(row.7),
                heap_bytes: nonnegative(row.8),
                index_bytes: nonnegative(row.9),
            });
        }
        let tables = TableGroup::ALL.map(|group| {
            tables
                .iter()
                .find(|table| table.group == group)
                .copied()
                .unwrap_or(TableSnapshot {
                    group,
                    inserts: 0,
                    updates: 0,
                    deletes: 0,
                    hot_updates: 0,
                    dead_tuples: 0,
                    vacuums: 0,
                    autovacuums: 0,
                    heap_bytes: 0,
                    index_bytes: 0,
                })
        });

        let wal = match tokio::time::timeout(
            SAMPLE_QUERY_TIMEOUT,
            sqlx::query_scalar::<_, i64>(WAL_POSITION_SQL).fetch_one(&self.pool),
        )
        .await
        .context("PostgreSQL WAL sample timed out")?
        {
            Ok(bytes) => WalSnapshot::Available {
                bytes_from_origin: nonnegative(bytes),
            },
            Err(error) if is_permission_denied(&error) => WalSnapshot::Unavailable {
                reason: format!("WAL sampling unavailable: insufficient privilege ({error})")
                    .into_boxed_str(),
            },
            Err(error) => return Err(error).context("sample PostgreSQL WAL position"),
        };

        Ok(PgSnapshot {
            phase_id: self.phase_id,
            sampled_at: Utc::now(),
            tables,
            wal,
        })
    }

    pub async fn sample_delta(&mut self) -> anyhow::Result<Option<PgDeltaRecord>> {
        let current = self.sample().await?;
        let delta = self
            .previous
            .as_ref()
            .map(|previous| delta(previous, &current))
            .transpose()?;
        self.previous = Some(current);
        Ok(delta)
    }

    pub async fn close(self) {
        self.pool.close().await;
    }
}

pub fn delta(previous: &PgSnapshot, current: &PgSnapshot) -> Result<PgDeltaRecord, PgDeltaError> {
    if previous.phase_id != current.phase_id {
        return Err(PgDeltaError::PhaseMismatch(PhaseMismatch {
            expected: previous.phase_id,
            actual: current.phase_id,
        }));
    }
    let elapsed_millis = current
        .sampled_at
        .signed_duration_since(previous.sampled_at)
        .num_milliseconds()
        .max(0) as u64;
    let tables = TableGroup::ALL.map(|group| {
        let previous = snapshot_for(previous, group);
        let current = snapshot_for(current, group);
        let stats_reset_detected = [
            (previous.inserts, current.inserts),
            (previous.updates, current.updates),
            (previous.deletes, current.deletes),
            (previous.hot_updates, current.hot_updates),
            (previous.vacuums, current.vacuums),
            (previous.autovacuums, current.autovacuums),
        ]
        .into_iter()
        .any(|(before, after)| after < before);
        TableDelta {
            group,
            inserts: current.inserts.saturating_sub(previous.inserts),
            updates: current.updates.saturating_sub(previous.updates),
            deletes: current.deletes.saturating_sub(previous.deletes),
            hot_updates: current.hot_updates.saturating_sub(previous.hot_updates),
            dead_tuples: current.dead_tuples,
            vacuums: current.vacuums.saturating_sub(previous.vacuums),
            autovacuums: current.autovacuums.saturating_sub(previous.autovacuums),
            heap_bytes: current.heap_bytes,
            index_bytes: current.index_bytes,
            stats_reset_detected,
        }
    });
    let wal = match (&previous.wal, &current.wal) {
        (
            WalSnapshot::Available {
                bytes_from_origin: before,
            },
            WalSnapshot::Available {
                bytes_from_origin: after,
            },
        ) => WalDelta::Available {
            bytes: after.saturating_sub(*before),
        },
        (_, WalSnapshot::Unavailable { reason })
        | (WalSnapshot::Unavailable { reason }, WalSnapshot::Available { .. }) => {
            WalDelta::Unavailable {
                reason: reason.clone(),
            }
        }
    };
    Ok(PgDeltaRecord {
        record_type: "pg",
        phase_id: current.phase_id,
        sampled_at: current.sampled_at,
        elapsed_millis,
        tables,
        wal,
    })
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum PgDeltaError {
    PhaseMismatch(PhaseMismatch),
}

impl std::fmt::Display for PgDeltaError {
    fn fmt(&self, formatter: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::PhaseMismatch(error) => error.fmt(formatter),
        }
    }
}

impl std::error::Error for PgDeltaError {}

fn snapshot_for(snapshot: &PgSnapshot, group: TableGroup) -> TableSnapshot {
    snapshot
        .tables
        .iter()
        .find(|table| table.group == group)
        .copied()
        .unwrap_or(TableSnapshot {
            group,
            inserts: 0,
            updates: 0,
            deletes: 0,
            hot_updates: 0,
            dead_tuples: 0,
            vacuums: 0,
            autovacuums: 0,
            heap_bytes: 0,
            index_bytes: 0,
        })
}

fn table_group(table_name: &str) -> anyhow::Result<TableGroup> {
    TableGroup::ALL
        .into_iter()
        .find(|group| group.table_name() == table_name)
        .ok_or_else(|| anyhow::anyhow!("unexpected PostgreSQL sampler table {table_name}"))
}

fn nonnegative(value: i64) -> u64 {
    u64::try_from(value).unwrap_or(0)
}

fn is_permission_denied(error: &sqlx::Error) -> bool {
    matches!(
        error,
        sqlx::Error::Database(database_error)
            if database_error.code().is_some_and(|code| code.as_ref() == "42501")
    )
}

#[cfg(test)]
mod tests {
    use chrono::TimeDelta;

    use super::*;

    fn table(group: TableGroup, inserts: u64, updates: u64) -> TableSnapshot {
        TableSnapshot {
            group,
            inserts,
            updates,
            deletes: 0,
            hot_updates: updates / 2,
            dead_tuples: updates,
            vacuums: 1,
            autovacuums: 2,
            heap_bytes: 100,
            index_bytes: 50,
        }
    }

    #[test]
    fn deltas_keep_table_groups_independent_and_surface_stat_resets() {
        let sampled_at = Utc::now();
        let previous = PgSnapshot {
            phase_id: PhaseId::new(1),
            sampled_at,
            tables: [
                table(TableGroup::Person, 10, 20),
                table(TableGroup::DistinctIdMap, 100, 200),
            ],
            wal: WalSnapshot::Available {
                bytes_from_origin: 1_000,
            },
        };
        let current = PgSnapshot {
            phase_id: PhaseId::new(1),
            sampled_at: sampled_at + TimeDelta::seconds(10),
            tables: [
                table(TableGroup::Person, 2, 3),
                table(TableGroup::DistinctIdMap, 110, 240),
            ],
            wal: WalSnapshot::Available {
                bytes_from_origin: 1_500,
            },
        };

        let result = delta(&previous, &current).expect("matching phase");

        assert!(result.tables[0].stats_reset_detected);
        assert_eq!(result.tables[0].updates, 0);
        assert!(!result.tables[1].stats_reset_detected);
        assert_eq!(
            (result.tables[1].inserts, result.tables[1].updates),
            (10, 40)
        );
        assert_eq!(result.wal, WalDelta::Available { bytes: 500 });

        let mut next_phase = current;
        next_phase.phase_id = PhaseId::new(2);
        assert!(matches!(
            delta(&previous, &next_phase),
            Err(PgDeltaError::PhaseMismatch(_))
        ));
    }
}
