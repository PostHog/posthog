//! Chunked, concurrent deletes through the lifecycle saga.
//!
//! A production bulk delete arrives as thousands of persons and reaches
//! the service as many `DeletePersons` calls, each one saga op bounded
//! by the per-call cap. This is the harness's version of that caller: a
//! job is split into chunks, a bounded number of chunks run at once, and
//! each chunk's op id is derived from the job id so a repeated job
//! attaches to the ops it already started instead of claiming the
//! persons a second time.

use std::time::{Duration, Instant};

use anyhow::{bail, Result};
use futures::stream::{self, StreamExt};
use metrics::{counter, histogram};
use personhog_proto::personhog::lifecycle::v1::DeletePersonOutcome;
use uuid::Uuid;

use crate::client::LifecycleClient;

/// The lifecycle service's cap on person ids per `DeletePersons` call
/// (proto/personhog/lifecycle/v1/lifecycle.proto).
pub const MAX_CHUNK_SIZE: usize = 250;

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct Chunk {
    pub op_id: Uuid,
    pub person_ids: Vec<i64>,
}

/// The op id is a v5 uuid of the job id and the chunk index: the service
/// treats a repeated op id as a retry of the same op, so a job planned
/// twice must produce the same ops.
pub fn plan_chunks(job_id: Uuid, person_ids: &[i64], chunk_size: usize) -> Vec<Chunk> {
    person_ids
        .chunks(chunk_size.max(1))
        .enumerate()
        .map(|(index, ids)| Chunk {
            op_id: Uuid::new_v5(&job_id, &(index as u64).to_be_bytes()),
            person_ids: ids.to_vec(),
        })
        .collect()
}

/// `deleted` and `not_found` are the expected answers; the other two list
/// the persons by id because each one is a finding to chase.
#[derive(Debug, Default, Clone, PartialEq, Eq)]
pub struct BulkDeleteReport {
    pub deleted: usize,
    pub not_found: usize,
    pub skipped_conflict: Vec<i64>,
    pub unspecified: Vec<i64>,
    pub chunks: usize,
    pub elapsed: Duration,
}

impl BulkDeleteReport {
    fn record(&mut self, person_id: i64, outcome: DeletePersonOutcome) {
        let label = match outcome {
            DeletePersonOutcome::Deleted => {
                self.deleted += 1;
                "deleted"
            }
            DeletePersonOutcome::NotFound => {
                self.not_found += 1;
                "not_found"
            }
            DeletePersonOutcome::SkippedConflict => {
                self.skipped_conflict.push(person_id);
                "skipped_conflict"
            }
            DeletePersonOutcome::Unspecified => {
                self.unspecified.push(person_id);
                "unspecified"
            }
        };
        counter!("personhog_traffic_pool_delete_total", "outcome" => label).increment(1);
    }

    pub fn first_unsettled(&self) -> Option<i64> {
        self.skipped_conflict
            .first()
            .or(self.unspecified.first())
            .copied()
    }
}

#[derive(Clone)]
pub struct BulkDeleter {
    lifecycle: LifecycleClient,
    chunk_size: usize,
    concurrency: usize,
}

impl BulkDeleter {
    pub fn new(lifecycle: LifecycleClient, chunk_size: usize, concurrency: usize) -> Result<Self> {
        if chunk_size == 0 || chunk_size > MAX_CHUNK_SIZE {
            bail!("delete chunk size {chunk_size} must be between 1 and {MAX_CHUNK_SIZE}");
        }
        if concurrency == 0 {
            bail!("delete concurrency must be nonzero");
        }
        Ok(Self {
            lifecycle,
            chunk_size,
            concurrency,
        })
    }

    /// Every chunk is attempted before the first failure is returned, so a
    /// retry of the job finds as many ops already settled as possible.
    pub async fn delete(
        &self,
        team_id: i64,
        person_ids: &[i64],
        job_id: Uuid,
    ) -> Result<BulkDeleteReport> {
        let started = Instant::now();
        let chunks = plan_chunks(job_id, person_ids, self.chunk_size);
        let mut report = BulkDeleteReport {
            chunks: chunks.len(),
            ..Default::default()
        };

        let results: Vec<Result<Vec<(i64, DeletePersonOutcome)>>> = stream::iter(chunks)
            .map(|chunk| {
                let lifecycle = self.lifecycle.clone();
                async move {
                    let call_started = Instant::now();
                    let outcomes = lifecycle
                        .delete_persons(team_id, chunk.person_ids, &chunk.op_id)
                        .await;
                    histogram!("personhog_traffic_pool_delete_duration_ms")
                        .record(call_started.elapsed().as_secs_f64() * 1000.0);
                    outcomes
                }
            })
            .buffer_unordered(self.concurrency)
            .collect()
            .await;

        let mut first_error = None;
        for result in results {
            match result {
                Ok(outcomes) => {
                    for (person_id, outcome) in outcomes {
                        report.record(person_id, outcome);
                    }
                }
                Err(error) => {
                    first_error.get_or_insert(error);
                }
            }
        }
        report.elapsed = started.elapsed();
        histogram!("personhog_traffic_bulk_delete_job_duration_ms")
            .record(report.elapsed.as_secs_f64() * 1000.0);
        histogram!("personhog_traffic_bulk_delete_job_persons").record(person_ids.len() as f64);

        match first_error {
            Some(error) => Err(error),
            None => Ok(report),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::{plan_chunks, MAX_CHUNK_SIZE};
    use uuid::Uuid;

    #[test]
    fn a_plan_covers_every_id_once_in_order_within_the_cap() {
        let ids: Vec<i64> = (1..=601).collect();
        let chunks = plan_chunks(Uuid::new_v4(), &ids, MAX_CHUNK_SIZE);

        let sizes: Vec<usize> = chunks.iter().map(|c| c.person_ids.len()).collect();
        assert_eq!(sizes, vec![250, 250, 101]);
        let covered: Vec<i64> = chunks.iter().flat_map(|c| c.person_ids.clone()).collect();
        assert_eq!(covered, ids);
    }

    #[test]
    fn a_repeated_job_plans_the_same_ops_and_another_job_never_shares_one() {
        let ids: Vec<i64> = (1..=600).collect();
        let job = Uuid::new_v4();

        let first = plan_chunks(job, &ids, 250);
        let again = plan_chunks(job, &ids, 250);
        assert_eq!(first, again);

        let other = plan_chunks(Uuid::new_v4(), &ids, 250);
        let mut op_ids: Vec<Uuid> = first.iter().chain(other.iter()).map(|c| c.op_id).collect();
        op_ids.sort();
        op_ids.dedup();
        assert_eq!(op_ids.len(), first.len() + other.len());
    }
}
