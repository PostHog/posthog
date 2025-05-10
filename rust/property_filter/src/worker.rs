use std::fmt;
use std::hash::Hasher;
use std::sync::Arc;
use std::time::Duration;

use crate::app::{Context, FilterRow};

use chrono::Utc;
use fxhash::FxHasher64;
use sbbf_rs_safe::Filter;
use serde::{Deserialize, Serialize};
use sqlx::{
    postgres::{PgQueryResult, PgRow},
    FromRow,
};
use tracing::{error, info, warn};

// metrics keys
const PROPDEFS_BATCH_FETCH_ATTEMPT: &str = "propfilter_batch_fetch_attempt";
const PROPFILTER_STORE_ATTEMPT: &str = "propfilter_store_attempt";
const PROPFILTER_TEAMS_PROCESSED: &str = "propfilter_teams_processed";
const PROPFILTER_TEAMS_FAILED: &str = "propfilter_teams_failed";
const PROPFILTER_PROPS_INSERTED: &str = "propfilter_props_inserted";
const PROPFILTER_DEFS_SCANNED: &str = "propfilter_definitions_scanned";

// teams with more than this many property definitions are outliers
// and should be skipped for further property defs processing anyway.
// looking at the distribution of propdefs to teams in the database, this
// feels like a reasonable threshold, but we can make final decisions later
const TEAM_PROPDEFS_CAP: i32 = 100_000;
const _TEAM_PROPDEFS_FILTER_SIZE_CAP: usize = 8192; // TODO(eli): enforce this! 8k as initial limit

// batch size & retry params
const BATCH_FETCH_SIZE: i64 = 1_000;
const BATCH_RETRY_DELAY_MS: u64 = 100;
const MAX_BATCH_FETCH_ATTEMPTS: u64 = 5;
const MAX_PROPFILTER_STORE_ATTEMPTS: u64 = 5;

// TODO(eli): bloom filter params DO NOT CHANGE ONCE DECIDED :)
// play with the math, iterate, and measure behavior in property-defs-rs before finalizing!
const BITS_PER_KEY: usize = 64;
const NUM_KEYS: usize = 1_000_000;

#[derive(Clone, Debug, Eq, PartialEq, Hash, Serialize, Deserialize)]
pub struct PropEntry {
    property_type: char,
    group_type_index: char,
    property_name: String,
}

// property def hash key for insertion or lookup in Bloom filters.
// contains all the values needed to determine a unique property
// on the parent Team
impl PropEntry {
    pub fn new(property_name: String, property_type: char, group_type_index: char) -> Self {
        Self {
            property_type,
            group_type_index,
            property_name,
        }
    }

    pub fn from_row(row: PropertyRow) -> Self {
        let group_type_index_resolved: char = row
            .group_type_index
            .map_or('X', |gti| char::from_digit(gti as u32, 10).unwrap());

        Self::new(
            row.name,
            char::from_digit(row.r#type as u32, 10).unwrap(),
            group_type_index_resolved,
        )
    }
}

// used to build hash input for Bloom filter insertion/lookup
impl fmt::Display for PropEntry {
    fn fmt(&self, f: &mut fmt::Formatter) -> fmt::Result {
        write!(
            f,
            "{}{}{}",
            self.property_type, self.group_type_index, self.property_name
        )
    }
}

#[derive(Deserialize, FromRow, PartialEq, Eq)]
pub struct PropertyRow {
    team_id: i64,
    name: String,
    r#type: i8,
    group_type_index: Option<i8>,
}

// Builds or updates the Bloom filters for the specified FilterRow (team ID)
// which may be brand new, or fetched from posthog_propertyfilter by the
// caller. This function is will be spawned in a thread and fanned out in
// a fixed-size worker pool (Tokio runtime) to control DB R/W load.
pub async fn filter_builder(ctx: Arc<Context>, mut filter_row: FilterRow) {
    let mut offset: i64 = 0;
    let mut fwd_filter = filter_row
        .fwd_bloom
        .as_ref()
        .map_or(Filter::new(BITS_PER_KEY, NUM_KEYS), |bs| {
            Filter::from_bytes(bs).expect("failed to deserialize bloom filter")
        });
    let mut rev_filter = filter_row
        .rev_bloom
        .as_ref()
        .map_or(Filter::new(BITS_PER_KEY, NUM_KEYS), |bs| {
            Filter::from_bytes(bs).expect("failed to deserialize bloom filter")
        });

    loop {
        if filter_row.property_count >= TEAM_PROPDEFS_CAP {
            warn!(
                "Filter construction for team {} has exceeded {} properties; marking as blocked",
                filter_row.team_id, TEAM_PROPDEFS_CAP
            );

            // mark as blocked along with other partial updates before persisting
            filter_row.blocked = true;
            filter_row = update_prop_filter(filter_row, &fwd_filter, &rev_filter);

            match store_team_filter(&ctx, &filter_row).await {
                Ok(result) => {
                    metrics::counter!(PROPFILTER_TEAMS_PROCESSED, &[("result", "blocked")])
                        .increment(1);
                    info!(
                        "persisted blocked filter for team {} ({} rows affected)",
                        filter_row.team_id,
                        result.rows_affected()
                    );
                }
                Err(e) => {
                    metrics::counter!(PROPFILTER_TEAMS_FAILED, &[("reason", "store_blocked")])
                        .increment(1);
                    error!(
                        "failed to store blocked filter for team {}, got: {}",
                        filter_row.team_id, e
                    );
                    return;
                }
            }
            return;
        }

        match get_next_batch(&ctx, filter_row.team_id, offset).await {
            Ok(rows) => {
                let mut insert_count: usize = 0;
                for row in &rows {
                    let pd_row = PropertyRow::from_row(row).unwrap();

                    // build a hash for each bloom filter and insert
                    // into the corresponding filter if missing
                    let fwd_entry = PropEntry::from_row(pd_row).to_string();
                    let mut fwd_hasher = FxHasher64::default();
                    fwd_hasher.write(fwd_entry.as_bytes());
                    let fwd_hash = fwd_hasher.finish();

                    let rev_entry = fwd_entry.chars().rev().collect::<String>();
                    let mut rev_hasher = FxHasher64::default();
                    rev_hasher.write(rev_entry.as_bytes());
                    let rev_hash = rev_hasher.finish();

                    // only add the key to a filter if it's missing, and
                    // only update the prop count once for this step
                    let mut exists = true;
                    if !fwd_filter.contains_hash(fwd_hash) {
                        exists = false;
                        fwd_filter.insert_hash(fwd_hash);
                    }
                    if !rev_filter.contains_hash(rev_hash) {
                        exists = false;
                        rev_filter.insert_hash(rev_hash);
                    }
                    if !exists {
                        insert_count += 1;
                        filter_row.property_count += 1;
                    }
                }

                // if we've processed all the rows, we're done
                if rows.is_empty() {
                    filter_row = update_prop_filter(filter_row, &fwd_filter, &rev_filter);
                    match store_team_filter(&ctx, &filter_row).await {
                        Ok(result) => {
                            metrics::counter!(PROPFILTER_TEAMS_PROCESSED, &[("result", "success")])
                                .increment(1);
                            info!(
                                "persisted updated filter for team {} ({} rows affected)",
                                filter_row.team_id,
                                result.rows_affected()
                            );
                            return;
                        }
                        Err(e) => {
                            metrics::counter!(
                                PROPFILTER_TEAMS_FAILED,
                                &[("reason", "store_filter")]
                            )
                            .increment(1);
                            error!(
                                "failed to store updated filter for team {}, got: {}",
                                filter_row.team_id, e
                            );
                            return;
                        }
                    }
                }

                // report and proceed to the next batch
                offset += rows.len() as i64;
                info!(
                    "Added {} property definitions to filter from batch of {} rows for team {}",
                    insert_count,
                    rows.len(),
                    filter_row.team_id
                );
                metrics::counter!(PROPFILTER_PROPS_INSERTED).increment(insert_count as u64);
                metrics::counter!(PROPFILTER_DEFS_SCANNED).increment(rows.len() as u64);
            }

            Err(e) => {
                error!(
                    "Failed fetching posthog_propertydefinition row batch: {}",
                    e
                );
                filter_row = update_prop_filter(filter_row, &fwd_filter, &rev_filter);
                metrics::counter!(PROPFILTER_TEAMS_FAILED, &[("reason", "batch_fetch")])
                    .increment(1);
                match store_team_filter(&ctx, &filter_row).await {
                    Ok(result) => {
                        info!("persisted filter for team {} after batch fetch error ({} rows affected)",
                            filter_row.team_id, result.rows_affected());
                    }
                    Err(e) => {
                        error!(
                            "failed to store filter after batch fetch error for team {}, got: {}",
                            filter_row.team_id, e
                        );
                        return;
                    }
                }
            }
        }
    }
}

fn update_prop_filter(mut filter_row: FilterRow, fwd: &Filter, rev: &Filter) -> FilterRow {
    filter_row.fwd_bloom = Some(fwd.as_bytes().into());
    filter_row.rev_bloom = Some(rev.as_bytes().into());
    filter_row.last_updated_at = Utc::now();
    filter_row
}

async fn store_team_filter(
    ctx: &Arc<Context>,
    filter_row: &FilterRow,
) -> Result<PgQueryResult, sqlx::Error> {
    let mut attempt = 1;
    loop {
        match sqlx::query(
            r#"
            INSERT INTO posthog_propertyfilter
                (team_id, fwd_bloom, rev_bloom, property_count, blocked, last_updated_at)
                VALUES ($1, $2, $3, $4, $5, $6)
            ON CONFLICT (team_id) DO UPDATE SET
                fwd_bloom=$2, rev_bloom=$3, property_count=$4, blocked=$5, last_updated_at=$6"#,
        )
        .bind(filter_row.team_id)
        .bind(&filter_row.fwd_bloom)
        .bind(&filter_row.rev_bloom)
        .bind(filter_row.property_count)
        .bind(filter_row.blocked)
        .bind(filter_row.last_updated_at)
        .execute(&ctx.pool)
        .await
        {
            Ok(result) => {
                metrics::counter!(PROPFILTER_STORE_ATTEMPT, &[("result", "success")]).increment(1);
                return Ok(result);
            }
            Err(e) => {
                if attempt >= MAX_PROPFILTER_STORE_ATTEMPTS {
                    metrics::counter!(PROPFILTER_STORE_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    error!(
                        "failed to store filter record for team_id {} with: {:?}",
                        filter_row.team_id, e
                    );
                    return Err(e);
                }

                // within retry budget, try again
                metrics::counter!(PROPFILTER_STORE_ATTEMPT, &[("result", "retry")]).increment(1);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = attempt * BATCH_RETRY_DELAY_MS + jitter;
                tokio::time::sleep(Duration::from_millis(delay)).await;
                attempt += 1;
            }
        }
    }
}

async fn get_next_batch(
    ctx: &Arc<Context>,
    team_id: i64,
    offset: i64,
) -> Result<Vec<PgRow>, sqlx::Error> {
    let mut attempt = 1;
    // note: this query is backed by an appropriate index. I measured (EXPLAIN, example executions etc.)
    // against several outlier teams with millions of unique property defs, and if we cap our fetches
    // to 1k/batch and stop iterating at first 100k props or so, using LIMIT/OFFSET here seems acceptable
    loop {
        match sqlx::query(
            r#"
            SELECT property_type, name, type, group_type_index FROM posthog_propertydefinition
            WHERE team_id = $1
            LIMIT $2 OFFSET $3"#,
        )
        .bind(team_id)
        .bind(BATCH_FETCH_SIZE)
        .bind(offset)
        .fetch_all(&ctx.pool)
        .await
        {
            Ok(rows) => {
                metrics::counter!(PROPDEFS_BATCH_FETCH_ATTEMPT, &[("result", "success")])
                    .increment(1);
                return Ok(rows);
            }
            Err(e) => {
                if attempt >= MAX_BATCH_FETCH_ATTEMPTS {
                    metrics::counter!(PROPDEFS_BATCH_FETCH_ATTEMPT, &[("result", "failed")])
                        .increment(1);
                    error!(
                        "failed to fetch next batch for team_id {} at offset {} with: {:?}",
                        team_id, offset, e
                    );
                    return Err(e);
                }

                // within retry budget, try again
                metrics::counter!(PROPDEFS_BATCH_FETCH_ATTEMPT, &[("result", "retry")])
                    .increment(1);
                let jitter = rand::random::<u64>() % 50;
                let delay: u64 = attempt * BATCH_RETRY_DELAY_MS + jitter;
                tokio::time::sleep(Duration::from_millis(delay)).await;
                attempt += 1;
            }
        }
    }
}
