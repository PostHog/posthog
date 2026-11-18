use std::sync::Arc;

use personhog_common::partitioning::partition_for_person;
use personhog_coordination::changelog::LiveChangelog;
use personhog_leader::cache::PersonCacheKey;
use personhog_leader::follow::{Follower, ReadRefusal};
use personhog_leader::pg::load_person_from_pg;
use personhog_leader::service::cached_person_into_proto;
use personhog_proto::personhog::types::v1::Person;
use tonic::metadata::MetadataMap;
use tonic::Status;

use super::PersonHogReplicaService;

/// The partition the router sent the request to.
pub const PARTITION_HEADER: &str = "x-partition";
/// The changelog config epoch the router chose that partition under.
pub const EPOCH_HEADER: &str = "x-changelog-epoch";
/// The person a caller routed the request by.
pub const PERSON_ID_HEADER: &str = "x-person-id";

/// What a replica needs to serve people from the changelog.
#[derive(Clone)]
pub struct FollowerReads {
    pub follower: Arc<Follower>,
    pub changelog: LiveChangelog,
    /// Where a person with no unapplied writes is loaded from: a read replica, and the
    /// table the writer maintains. An unmarked person is current only in that table.
    pub pool: sqlx::PgPool,
    pub table: String,
}

impl PersonHogReplicaService {
    /// Whether the router sent this request to a follower of the person's partition. A
    /// request it did not is answered from Postgres.
    pub(super) fn routed_to_a_follower(metadata: &MetadataMap) -> bool {
        metadata.contains_key(PARTITION_HEADER)
    }

    /// The person the request was routed by, checked against the UUID it asks for.
    pub(super) async fn followed_person_by_uuid(
        &self,
        metadata: &MetadataMap,
        team_id: i64,
        uuid: &str,
    ) -> Result<Option<Person>, Status> {
        let person_id = header(metadata, PERSON_ID_HEADER)?
            .and_then(|id| i64::try_from(id).ok())
            .ok_or_else(|| Status::invalid_argument(format!("missing {PERSON_ID_HEADER}")))?;
        let person = self.followed_person(metadata, team_id, person_id).await?;
        if person.as_ref().is_some_and(|person| person.uuid != uuid) {
            return Err(Status::invalid_argument(format!(
                "{PERSON_ID_HEADER} names another person than the requested UUID"
            )));
        }
        Ok(person)
    }

    /// The person as the changelog has them. Every refusal is retryable against another
    /// follower of the partition: this one is behind, or has not seen the caller's config.
    pub(super) async fn followed_person(
        &self,
        metadata: &MetadataMap,
        team_id: i64,
        person_id: i64,
    ) -> Result<Option<Person>, Status> {
        let routed = header(metadata, PARTITION_HEADER)?;
        let Some(reads) = &self.follower else {
            refused("not_following", None);
            return Err(Status::failed_precondition(
                "this replica does not follow the changelog",
            ));
        };
        let (partitions, epoch) = reads.changelog.layout();
        let partition = partition_for_person(team_id, person_id, partitions);
        if header(metadata, EPOCH_HEADER)?.is_some_and(|routed| routed > epoch) {
            refused("config_behind", Some(partition));
            return Err(Status::unavailable(
                "this follower has not seen the changelog config the request was routed under",
            ));
        }
        if routed.is_some_and(|routed| routed != partition as u64) {
            refused("other_partition", Some(partition));
            return Err(Status::failed_precondition(format!(
                "the request was routed to another partition than {partition}"
            )));
        }
        let key = PersonCacheKey { team_id, person_id };
        let read = reads
            .follower
            .read(partition, &key, epoch, || async {
                load_person_from_pg(&reads.pool, &reads.table, &key)
                    .await
                    .map_err(|e| e.to_string())
            })
            .await;
        match read {
            Ok(person) => Ok(person.map(cached_person_into_proto)),
            Err(ReadRefusal::NotCurrent) => {
                refused("not_current", Some(partition));
                Err(Status::unavailable(
                    "this follower is not current for the partition",
                ))
            }
            Err(ReadRefusal::Recovery(reason)) => {
                refused("recovery", Some(partition));
                Err(Status::unavailable(reason))
            }
            Err(ReadRefusal::Load(reason)) => {
                refused("load", Some(partition));
                Err(Status::unavailable(reason))
            }
        }
    }
}

/// `partition` is the one this pod computed for the person, never a value a caller sent,
/// so the label stays within the partition count.
fn refused(reason: &'static str, partition: Option<u32>) {
    let partition = partition.map_or_else(|| "none".to_string(), |partition| partition.to_string());
    common_metrics::inc(
        "personhog_follower_read_refusals_total",
        &[
            ("reason".to_string(), reason.to_string()),
            ("partition".to_string(), partition),
        ],
        1,
    );
}

#[allow(clippy::result_large_err)]
fn header(metadata: &MetadataMap, name: &'static str) -> Result<Option<u64>, Status> {
    let Some(value) = metadata.get(name) else {
        return Ok(None);
    };
    value
        .to_str()
        .ok()
        .and_then(|value| value.parse().ok())
        .map(Some)
        .ok_or_else(|| Status::invalid_argument(format!("{name} is not a number")))
}
