//! The get-or-create pipeline: batch-resolve distinct ids on the primary,
//! create person stubs for misses in one multi-row transaction, then apply
//! initial properties through the leader with bounded concurrency.
//!
//! `created = true` in a result means the stub row is committed in Postgres
//! AND the initial properties (when provided) are durable in the leader's
//! changelog — the single ack covers both planes.

use std::collections::{HashMap, HashSet};

use chrono::{DateTime, Utc};
use futures::stream::{self, StreamExt};
use tonic::{Code, Status};

use personhog_proto::personhog::types::v1::{
    GetOrCreatePersonEntry, Person as ProtoPerson, UpdatePersonPropertiesRequest,
};

use crate::service::error::log_and_convert_error;
use crate::service::validation::validate_entry;
use crate::service::PersonHogIdentityService;
use crate::storage::{Person, PersonStub, StubOutcome};

/// Bound on concurrent leader-routed property writes within one batch.
const MAX_CONCURRENT_PROPERTY_WRITES: usize = 8;

const GET_OR_CREATE_TOTAL: &str = "personhog_identity_get_or_create_total";

fn count_outcome(outcome: &str) {
    common_metrics::inc(
        GET_OR_CREATE_TOTAL,
        &[("outcome".to_string(), outcome.to_string())],
        1,
    );
}

/// Empty bytes and an empty JSON object both mean "no properties to apply".
fn has_properties(raw: &[u8]) -> bool {
    !raw.is_empty() && raw.trim_ascii() != b"{}"
}

fn entry_created_at(entry: &GetOrCreatePersonEntry) -> DateTime<Utc> {
    if entry.created_at > 0 {
        DateTime::from_timestamp_millis(entry.created_at).unwrap_or_else(Utc::now)
    } else {
        Utc::now()
    }
}

/// How each entry proceeds after the resolve phase.
enum Plan {
    /// Terminal before stub creation: invalid entry, or the key resolved.
    Done(Result<(ProtoPerson, bool), Status>),
    /// First entry for a missing key; owns the stub at this index.
    Owner(usize),
    /// Duplicate of a missing key earlier in the batch; shares its outcome
    /// but never reports created = true (exactly one entry creates).
    Follower(usize),
}

impl PersonHogIdentityService {
    /// Runs the get-or-create pipeline for a set of entries: one batched
    /// resolve, one multi-row stub-create transaction for the misses, one
    /// batched re-resolve for lost races, then the leader property fan-out.
    /// Per-key conflicts and failures never affect other keys. Results are in
    /// entry order.
    pub(crate) async fn get_or_create_entries(
        &self,
        entries: Vec<GetOrCreatePersonEntry>,
    ) -> Result<Vec<Result<(ProtoPerson, bool), Status>>, Status> {
        let keys: Vec<(i64, String)> = entries
            .iter()
            .filter(|entry| validate_entry(&self.limits, entry).is_ok())
            .map(|entry| (entry.team_id, entry.distinct_id.clone()))
            .collect();
        let resolved = self
            .storage
            .resolve_distinct_ids(&keys)
            .await
            .map_err(|e| log_and_convert_error(e, "resolve_distinct_ids"))?;

        // Plan each entry and collect one stub per missing key.
        let mut stubs: Vec<PersonStub> = Vec::new();
        let mut stub_index: HashMap<(i64, String), usize> = HashMap::new();
        let plans: Vec<Plan> = entries
            .iter()
            .map(|entry| {
                if let Err(status) = validate_entry(&self.limits, entry) {
                    return Plan::Done(Err(status));
                }
                let key = (entry.team_id, entry.distinct_id.clone());
                if let Some(person) = resolved.get(&key) {
                    count_outcome("exists");
                    return Plan::Done(Ok((person.clone().into(), false)));
                }
                if let Some(&index) = stub_index.get(&key) {
                    return Plan::Follower(index);
                }
                stub_index.insert(key, stubs.len());
                stubs.push(build_stub(entry));
                Plan::Owner(stubs.len() - 1)
            })
            .collect();

        let outcomes = if stubs.is_empty() {
            Vec::new()
        } else {
            self.storage
                .create_person_stubs(&stubs)
                .await
                .map_err(|e| log_and_convert_error(e, "create_person_stubs"))?
        };

        // Lost races re-resolve in one batch: the winner's mapping committed,
        // so a fresh resolve finds it.
        let lost_keys: Vec<(i64, String)> = stub_index
            .iter()
            .filter(|(_, &index)| matches!(outcomes[index], StubOutcome::LostRace))
            .map(|(key, _)| key.clone())
            .collect();
        let lost_resolved = if lost_keys.is_empty() {
            HashMap::new()
        } else {
            self.storage
                .resolve_distinct_ids(&lost_keys)
                .await
                .map_err(|e| log_and_convert_error(e, "resolve_after_lost_race"))?
        };

        // Assemble results; created owners go through the leader fan-out.
        let lost_race_result = |i: usize| {
            let key = (entries[i].team_id, entries[i].distinct_id.clone());
            match lost_resolved.get(&key) {
                Some(person) => {
                    count_outcome("lost_race_resolved");
                    Ok((person.clone().into(), false))
                }
                None => {
                    count_outcome("lost_race_unresolved");
                    Err(Status::aborted(
                        "concurrent identity operation on distinct id; retry",
                    ))
                }
            }
        };
        let mut results: Vec<Option<Result<(ProtoPerson, bool), Status>>> = Vec::new();
        let mut property_writes: Vec<(usize, Person)> = Vec::new();
        for (i, plan) in plans.into_iter().enumerate() {
            let result = match plan {
                Plan::Done(result) => Some(result),
                Plan::Owner(index) => match &outcomes[index] {
                    StubOutcome::Committed {
                        person,
                        created: true,
                    } => {
                        property_writes.push((i, person.clone()));
                        None
                    }
                    StubOutcome::Committed {
                        person,
                        created: false,
                    } => {
                        count_outcome("exists");
                        Some(Ok((person.clone().into(), false)))
                    }
                    StubOutcome::LostRace => Some(lost_race_result(i)),
                },
                Plan::Follower(index) => match &outcomes[index] {
                    StubOutcome::Committed { person, .. } => {
                        count_outcome("exists");
                        Some(Ok((person.clone().into(), false)))
                    }
                    StubOutcome::LostRace => Some(lost_race_result(i)),
                },
            };
            results.push(result);
        }

        let applied: Vec<(usize, Result<ProtoPerson, Status>)> =
            stream::iter(property_writes.into_iter().map(|(i, person)| {
                let entry = &entries[i];
                async move { (i, self.apply_initial_properties(entry, person).await) }
            }))
            .buffered(MAX_CONCURRENT_PROPERTY_WRITES)
            .collect()
            .await;
        for (i, result) in applied {
            let result = result.map(|person| (person, true));
            if result.is_ok() {
                count_outcome("created");
            }
            results[i] = Some(result);
        }

        Ok(results
            .into_iter()
            .map(|result| result.expect("every entry has a result"))
            .collect())
    }

    /// Applies the entry's $set/$set_once to a freshly created stub through
    /// the leader (via the router). Success means the properties are durable
    /// in the changelog — only then may the RPC report created = true.
    async fn apply_initial_properties(
        &self,
        entry: &GetOrCreatePersonEntry,
        person: Person,
    ) -> Result<ProtoPerson, Status> {
        if !has_properties(&entry.set_properties) && !has_properties(&entry.set_once_properties) {
            return Ok(person.into());
        }

        let request = UpdatePersonPropertiesRequest {
            team_id: person.team_id,
            person_id: person.id,
            event_name: entry.event_name.clone(),
            set_properties: entry.set_properties.clone(),
            set_once_properties: entry.set_once_properties.clone(),
            unset_properties: Vec::new(),
        };

        match self
            .property_writer
            .update_person_properties(request.clone())
            .await
        {
            Ok(response) => Ok(response.person.unwrap_or_else(|| person.into())),
            Err(status) if status.code() == Code::NotFound => {
                // The stub was destroyed (merged or deleted) between commit and
                // the property write. Re-resolve and apply to the person the
                // distinct id now maps to.
                let key = (entry.team_id, entry.distinct_id.clone());
                let mut resolved = self
                    .storage
                    .resolve_distinct_ids(std::slice::from_ref(&key))
                    .await
                    .map_err(|e| log_and_convert_error(e, "resolve_after_leader_not_found"))?;
                let Some(current) = resolved.remove(&key) else {
                    return Err(status);
                };
                if current.id == person.id {
                    return Err(status);
                }
                let retry = UpdatePersonPropertiesRequest {
                    team_id: current.team_id,
                    person_id: current.id,
                    ..request
                };
                let response = self.property_writer.update_person_properties(retry).await?;
                Ok(response.person.unwrap_or_else(|| current.into()))
            }
            Err(status) => Err(status),
        }
    }
}

/// Builds the storage stub for an entry, deduping extras and dropping the
/// primary from them — the storage layer requires unique distinct ids.
fn build_stub(entry: &GetOrCreatePersonEntry) -> PersonStub {
    let mut seen: HashSet<&str> = HashSet::from([entry.distinct_id.as_str()]);
    let extra_distinct_ids: Vec<String> = entry
        .extra_distinct_ids
        .iter()
        .filter(|d| seen.insert(d.as_str()))
        .cloned()
        .collect();
    PersonStub {
        team_id: entry.team_id,
        distinct_id: entry.distinct_id.clone(),
        extra_distinct_ids,
        created_at: entry_created_at(entry),
        is_identified: entry.is_identified,
    }
}
