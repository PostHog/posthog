//! How the delete saga reaches the leaders: victims grouped into one
//! batch call per partition, with single calls for any batch a leader
//! refuses.

use std::collections::{BTreeMap, HashMap};

use futures::stream::{self, StreamExt};
use tonic::{Code, Status};
use uuid::Uuid;

use personhog_common::grpc::is_semantic_refusal;
use personhog_common::partitioning::partition_for_person;
use personhog_proto::personhog::types::v1::{
    FencePersonRequest, FencePersonsRequest, FencePersonsResponse, LifecycleOpType,
    ReleaseFenceItem, ReleaseFenceRequest, ReleaseFencesRequest, ReleaseOutcome,
};

use crate::leader::LifecycleLeader;
use crate::lifecycle::engine::{OpRow, SagaError};

/// Persons per `FencePersons` or `ReleaseFences` call. Equal to the
/// leader's batch cap, which refuses larger batches outright.
pub(crate) const LIFECYCLE_BATCH_SIZE: usize = 100;

const BATCH_FALLBACKS_TOTAL: &str = "personhog_lifecycle_delete_batch_fallbacks_total";

/// How a step reaches the leaders: the client, the calls it keeps in
/// flight at once, and the partition count its batches are grouped by.
#[derive(Clone, Copy)]
pub(crate) struct LeaderCalls<'a> {
    leader: &'a dyn LifecycleLeader,
    concurrency: usize,
    num_partitions: u32,
}

impl<'a> LeaderCalls<'a> {
    pub(crate) fn new(
        leader: &'a dyn LifecycleLeader,
        concurrency: usize,
        num_partitions: u32,
    ) -> Self {
        Self {
            leader,
            concurrency,
            num_partitions,
        }
    }
}

pub(crate) enum Fenced {
    Sealed {
        person_id: i64,
        version: i64,
        created_at: i64,
    },
    Vanished(i64),
}

/// The batches one leader call may carry: one partition's victims, at
/// most [`LIFECYCLE_BATCH_SIZE`] per batch. The leader refuses a batch
/// whose members hash to different partitions.
fn partition_batches<T>(
    team_id: i64,
    items: &[T],
    num_partitions: u32,
    person_id: impl Fn(&T) -> i64,
) -> Vec<Vec<&T>> {
    let mut by_partition: BTreeMap<u32, Vec<&T>> = BTreeMap::new();
    for item in items {
        let partition = partition_for_person(team_id, person_id(item), num_partitions);
        by_partition.entry(partition).or_default().push(item);
    }
    by_partition
        .into_values()
        .flat_map(|group| {
            group
                .chunks(LIFECYCLE_BATCH_SIZE)
                .map(<[&T]>::to_vec)
                .collect::<Vec<_>>()
        })
        .collect()
}

/// Whether a failed batch is retried as single calls: an old fleet, a
/// routing mismatch from a stale partition count, or one member's semantic
/// refusal. Anything else fails the step, as a single call's failure would.
fn falls_back_to_singles(status: &Status) -> bool {
    matches!(status.code(), Code::Unimplemented | Code::InvalidArgument)
        || is_semantic_refusal(status)
}

fn record_batch_fallback(rpc: &str, status: &Status) {
    common_metrics::inc(
        BATCH_FALLBACKS_TOTAL,
        &[
            ("rpc".to_string(), rpc.to_string()),
            ("code".to_string(), format!("{:?}", status.code())),
        ],
        1,
    );
}

/// One `FencePersons` call's outcome: the victims it answered for, and the
/// victims left to single calls.
type BatchFenced<'a> = Result<(Vec<Fenced>, Vec<&'a i64>), SagaError>;

/// Fence the victims in one `FencePersons` call per partition batch, then
/// fence one call each the members of any batch a leader refused.
pub(crate) async fn fence_victims(
    calls: LeaderCalls<'_>,
    op: &OpRow,
    person_ids: &[i64],
) -> Result<Vec<Fenced>, SagaError> {
    let leader = calls.leader;
    let batch_calls: Vec<_> =
        partition_batches(op.team_id, person_ids, calls.num_partitions, |id| *id)
            .into_iter()
            .map(|batch| async move {
                let request = FencePersonsRequest {
                    team_id: op.team_id,
                    op_id: op.op_id.to_string(),
                    op_type: LifecycleOpType::Delete.into(),
                    person_ids: batch.iter().map(|id| **id).collect(),
                };
                match leader.fence_persons(request).await {
                    Ok(response) => {
                        fenced_from_batch(&batch, response).map(|fenced| (fenced, Vec::new()))
                    }
                    Err(status) if falls_back_to_singles(&status) => {
                        record_batch_fallback("FencePersons", &status);
                        Ok((Vec::new(), batch))
                    }
                    Err(status) => Err(SagaError::leader(status)),
                }
            })
            .collect();
    let batch_results: Vec<BatchFenced<'_>> = stream::iter(batch_calls)
        .buffer_unordered(calls.concurrency)
        .collect()
        .await;
    let mut fenced: Vec<Fenced> = Vec::with_capacity(person_ids.len());
    let mut singles: Vec<i64> = Vec::new();
    for result in batch_results {
        let (batch_fenced, refused) = result?;
        fenced.extend(batch_fenced);
        singles.extend(refused.into_iter().copied());
    }
    if !singles.is_empty() {
        fenced.extend(fence_each_victim(calls, op, &singles).await?);
    }
    Ok(fenced)
}

/// The batch's answer as per-victim outcomes. A person in neither list was
/// neither fenced nor found destroyed, and sealing without it would leave
/// that person unfenced through the delete.
fn fenced_from_batch(
    person_ids: &[&i64],
    response: FencePersonsResponse,
) -> Result<Vec<Fenced>, SagaError> {
    let mut by_person: HashMap<i64, Fenced> = HashMap::with_capacity(person_ids.len());
    for seal in response.sealed {
        by_person.insert(
            seal.person_id,
            Fenced::Sealed {
                person_id: seal.person_id,
                version: seal.version,
                created_at: seal.created_at,
            },
        );
    }
    for person_id in response.not_found {
        by_person.insert(person_id, Fenced::Vanished(person_id));
    }
    person_ids
        .iter()
        .map(|person_id| {
            by_person.remove(person_id).ok_or_else(|| {
                SagaError::CorruptState(format!(
                    "fence batch response carries no outcome for person {person_id}"
                ))
            })
        })
        .collect()
}

async fn fence_each_victim(
    calls: LeaderCalls<'_>,
    op: &OpRow,
    person_ids: &[i64],
) -> Result<Vec<Fenced>, SagaError> {
    let leader = calls.leader;
    let fence_calls: Vec<_> = person_ids
        .iter()
        .map(|person_id| {
            let request = FencePersonRequest {
                team_id: op.team_id,
                person_id: *person_id,
                op_id: op.op_id.to_string(),
                op_type: LifecycleOpType::Delete.into(),
            };
            let person_id = *person_id;
            async move { (person_id, leader.fence_person(request).await) }
        })
        .collect();
    let fence_results: Vec<_> = stream::iter(fence_calls)
        .buffer_unordered(calls.concurrency)
        .collect()
        .await;

    let mut fenced = Vec::with_capacity(fence_results.len());
    for (person_id, result) in fence_results {
        match result {
            Ok(response) => {
                let sealed = response.sealed.ok_or_else(|| {
                    SagaError::CorruptState(format!(
                        "fence response for person {person_id} carries no sealed state"
                    ))
                })?;
                fenced.push(Fenced::Sealed {
                    person_id,
                    version: sealed.version,
                    created_at: sealed.created_at,
                });
            }
            Err(status) if status.code() == Code::NotFound => {
                fenced.push(Fenced::Vanished(person_id));
            }
            // FencePerson mints no semantic refusal today; adding one
            // needs an abort path first (see the merge driver's).
            Err(status) => return Err(SagaError::leader(status)),
        }
    }
    Ok(fenced)
}

/// A victim whose fence must be released at completion.
pub(crate) struct FencedVictim {
    pub(crate) person_id: i64,
    pub(crate) person_uuid: Uuid,
    pub(crate) sealed_version: i64,
    pub(crate) sealed_created_at: i64,
}

impl FencedVictim {
    fn release_item(&self) -> ReleaseFenceItem {
        ReleaseFenceItem {
            person_id: self.person_id,
            person_uuid: self.person_uuid.to_string(),
            sealed_version: Some(self.sealed_version),
            created_at: self.sealed_created_at,
        }
    }

    fn release_request(&self, op: &OpRow) -> ReleaseFenceRequest {
        ReleaseFenceRequest {
            team_id: op.team_id,
            person_id: self.person_id,
            person_uuid: self.person_uuid.to_string(),
            op_id: op.op_id.to_string(),
            outcome: ReleaseOutcome::Committed.into(),
            sealed_version: Some(self.sealed_version),
            created_at: self.sealed_created_at,
        }
    }
}

/// Release the fenced victims with the committed outcome, one
/// `ReleaseFences` per partition batch, so each leader verifies the marks
/// in one query and shares one fencing window. Refused batches go single.
pub(crate) async fn release_fenced(
    calls: LeaderCalls<'_>,
    op: &OpRow,
    victims: &[FencedVictim],
) -> Result<(), SagaError> {
    let leader = calls.leader;
    let batch_calls: Vec<_> =
        partition_batches(op.team_id, victims, calls.num_partitions, |v| v.person_id)
            .into_iter()
            .map(|batch| async move {
                let request = ReleaseFencesRequest {
                    team_id: op.team_id,
                    op_id: op.op_id.to_string(),
                    outcome: ReleaseOutcome::Committed.into(),
                    persons: batch.iter().map(|v| v.release_item()).collect(),
                };
                match leader.release_fences(request).await {
                    Ok(_) => Ok(Vec::new()),
                    Err(status) if falls_back_to_singles(&status) => {
                        record_batch_fallback("ReleaseFences", &status);
                        Ok(batch)
                    }
                    Err(status) => Err(status),
                }
            })
            .collect();
    let batch_results: Vec<Result<Vec<&FencedVictim>, Status>> = stream::iter(batch_calls)
        .buffer_unordered(calls.concurrency)
        .collect()
        .await;
    let mut singles: Vec<&FencedVictim> = Vec::new();
    for result in batch_results {
        singles.extend(result.map_err(SagaError::leader)?);
    }

    let single_calls: Vec<_> = singles
        .into_iter()
        .map(|victim| {
            let request = victim.release_request(op);
            async move { leader.release_fence(request).await }
        })
        .collect();
    let single_results: Vec<_> = stream::iter(single_calls)
        .buffer_unordered(calls.concurrency)
        .collect()
        .await;
    for result in single_results {
        result.map_err(SagaError::leader)?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use personhog_common::grpc::semantic_refusal;

    #[test]
    fn partition_batches_never_mix_partitions() {
        let team_id = 7;
        let ids: Vec<i64> = (1..=50).collect();
        let batches = partition_batches(team_id, &ids, 4, |id| *id);
        let mut seen: Vec<i64> = Vec::new();
        for batch in &batches {
            let partition = partition_for_person(team_id, *batch[0], 4);
            assert!(batch
                .iter()
                .all(|id| partition_for_person(team_id, **id, 4) == partition));
            seen.extend(batch.iter().map(|id| **id));
        }
        seen.sort_unstable();
        assert_eq!(seen, ids);
    }

    #[test]
    fn partition_batches_split_a_partition_at_the_cap() {
        let ids: Vec<i64> = (1..=(2 * LIFECYCLE_BATCH_SIZE as i64 + 1)).collect();
        let sizes: Vec<usize> = partition_batches(7, &ids, 1, |id| *id)
            .iter()
            .map(Vec::len)
            .collect();
        assert_eq!(sizes, vec![LIFECYCLE_BATCH_SIZE, LIFECYCLE_BATCH_SIZE, 1]);
    }

    #[test]
    fn only_refusals_a_single_call_can_isolate_fall_back() {
        for code in [Code::Unimplemented, Code::InvalidArgument] {
            assert!(falls_back_to_singles(&Status::new(code, "")), "{code:?}");
        }
        assert!(falls_back_to_singles(&semantic_refusal(
            "no live mark",
            "release-unverified"
        )));
        for code in [
            Code::Unavailable,
            Code::DeadlineExceeded,
            Code::FailedPrecondition,
            Code::ResourceExhausted,
            Code::Internal,
        ] {
            assert!(!falls_back_to_singles(&Status::new(code, "")), "{code:?}");
        }
    }
}
