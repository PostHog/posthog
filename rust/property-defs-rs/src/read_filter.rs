use std::str::FromStr;
use std::time::Duration;

use sqlx::PgPool;
use tracing::warn;

use crate::{
    batch_ingestion::{EventPropertiesBatch, PropertyDefinitionsBatch},
    metrics_consts::{READ_FILTER_ATTEMPT, READ_FILTER_ROWS_DROPPED, READ_FILTER_TIME},
    types::{PropertyValueType, Update},
    update_cache::Cache,
};

// Read-before-write: probe the batch against a Postgres reader and drop the rows
// the database already covers, so no-op upserts become cheap reader index probes
// instead of writer traffic. Every failure path fails open - the unfiltered batch
// is written exactly as it would be without this feature - so the filter can only
// remove writes the upsert would have no-oped anyway.
//
// Reader lag is safe by the same argument in the other direction: a row committed
// moments ago may look absent on the replica, so it stays in the batch and the
// writer's ON CONFLICT no-ops it.

/// Drops event-property rows that already exist. The unique index covers the
/// probe (COALESCE project key, event, property), one index descent per row.
pub async fn filter_event_properties(
    pool: &PgPool,
    batch: &mut EventPropertiesBatch,
    budget: Duration,
) {
    if batch.is_empty() {
        return;
    }
    let timer = common_metrics::timing_guard(READ_FILTER_TIME, &[]);
    let query = sqlx::query_as(
        r#"SELECT u.ord
           FROM unnest($1::bigint[], $2::text[], $3::text[]) WITH ORDINALITY AS u(pk, event, property, ord)
           JOIN posthog_eventproperty ep
             ON COALESCE(ep.project_id, ep.team_id::bigint) = u.pk
            AND ep.event = u.event
            AND ep.property = u.property"#,
    )
    .bind(&batch.project_ids)
    .bind(&batch.event_names)
    .bind(&batch.property_names)
    .fetch_all(pool);
    let found: Vec<(i64,)> = match tokio::time::timeout(budget, query).await {
        Ok(Ok(found)) => found,
        Ok(Err(e)) => {
            timer.label("table", "eventprops").fin();
            metrics::counter!(
                READ_FILTER_ATTEMPT,
                &[("table", "eventprops"), ("result", "failed")]
            )
            .increment(1);
            warn!("read filter failed for eventprops, writing unfiltered batch: {e}");
            return;
        }
        Err(_) => {
            timer.label("table", "eventprops").fin();
            metrics::counter!(
                READ_FILTER_ATTEMPT,
                &[("table", "eventprops"), ("result", "timeout")]
            )
            .increment(1);
            return;
        }
    };
    timer.label("table", "eventprops").fin();
    metrics::counter!(
        READ_FILTER_ATTEMPT,
        &[("table", "eventprops"), ("result", "success")]
    )
    .increment(1);

    let mut keep = vec![true; batch.len()];
    for (ord,) in found {
        keep[ord as usize - 1] = false;
    }
    let dropped = batch.retain_rows(&keep);
    metrics::counter!(READ_FILTER_ROWS_DROPPED, &[("table", "eventprops")])
        .increment(dropped as u64);
}

/// Drops property-definition rows the upsert could not change: the row exists
/// and either already has a type or the incoming update carries none. Rows kept
/// are new rows and NULL-to-typed upgrades, mirroring the DO UPDATE guard.
pub async fn filter_property_definitions(
    pool: &PgPool,
    cache: &Cache,
    batch: &mut PropertyDefinitionsBatch,
    budget: Duration,
) {
    if batch.is_empty() {
        return;
    }
    let timer = common_metrics::timing_guard(READ_FILTER_TIME, &[]);
    let query = sqlx::query_as(
        r#"SELECT u.ord, pd.property_type
           FROM unnest($1::bigint[], $2::text[], $3::int2[], $4::int2[]) WITH ORDINALITY
                AS u(pk, name, etype, gidx, ord)
           JOIN posthog_propertydefinition pd
             ON COALESCE(pd.project_id, pd.team_id::bigint) = u.pk
            AND pd.name = u.name
            AND pd.type = u.etype
            AND COALESCE(pd.group_type_index, -1) = COALESCE(u.gidx::int4, -1)"#,
    )
    .bind(&batch.project_ids)
    .bind(&batch.names)
    .bind(&batch.event_types)
    .bind(&batch.group_type_indices)
    .fetch_all(pool);
    let found: Vec<(i64, Option<String>)> = match tokio::time::timeout(budget, query).await {
        Ok(Ok(found)) => found,
        Ok(Err(e)) => {
            timer.label("table", "propdefs").fin();
            metrics::counter!(
                READ_FILTER_ATTEMPT,
                &[("table", "propdefs"), ("result", "failed")]
            )
            .increment(1);
            warn!("read filter failed for propdefs, writing unfiltered batch: {e}");
            return;
        }
        Err(_) => {
            timer.label("table", "propdefs").fin();
            metrics::counter!(
                READ_FILTER_ATTEMPT,
                &[("table", "propdefs"), ("result", "timeout")]
            )
            .increment(1);
            return;
        }
    };
    timer.label("table", "propdefs").fin();
    metrics::counter!(
        READ_FILTER_ATTEMPT,
        &[("table", "propdefs"), ("result", "success")]
    )
    .increment(1);

    let mut keep = vec![true; batch.len()];
    for (ord, stored_type) in found {
        let idx = ord as usize - 1;
        let upgrade = stored_type.is_none() && batch.property_types[idx].is_some();
        if upgrade {
            continue;
        }
        keep[idx] = false;
        // Refresh the dedup cache with the stored type, so future typed sightings
        // of this row hit in memory instead of re-probing the reader.
        if let Some(stored) = stored_type.and_then(|s| PropertyValueType::from_str(&s).ok()) {
            if let Update::Property(pd) = &batch.cached[idx] {
                let mut refreshed = pd.clone();
                refreshed.property_type = Some(stored);
                cache.insert(Update::Property(refreshed));
            }
        }
    }
    let dropped = batch.retain_rows(&keep);
    metrics::counter!(READ_FILTER_ROWS_DROPPED, &[("table", "propdefs")]).increment(dropped as u64);
}
