use std::future::Future;
use std::sync::{Arc, OnceLock};

use personhog_common::client::{CHANGELOG_EPOCH_HEADER, PARTITION_HEADER, PERSON_ID_HEADER};
use personhog_common::partitioning::partition_for_person;
use personhog_coordination::changelog::LiveChangelog;
use personhog_leader::cache::{CachedPerson, PersonCacheKey};
use personhog_leader::follow::Follower;
use personhog_leader::service::cached_person_into_proto;
use personhog_proto::personhog::types::v1::Person;
use tonic::metadata::MetadataMap;
use tonic::Status;

use super::PersonHogReplicaService;

/// A follower and the changelog config it follows under.
pub struct Attached {
    pub follower: Arc<Follower>,
    pub changelog: LiveChangelog,
}

/// What a replica in follower mode reads people from. It is empty until the pod has read
/// the changelog config, and every read is answered from Postgres until then.
#[derive(Clone, Default)]
pub struct FollowerReads {
    attached: Arc<OnceLock<Attached>>,
}

impl FollowerReads {
    /// The follower this replica reads from, which is `attached` unless one already was.
    pub fn attach(&self, attached: impl FnOnce() -> Attached) -> &Attached {
        self.attached.get_or_init(attached)
    }

    fn attached(&self) -> Option<&Attached> {
        self.attached.get()
    }
}

impl PersonHogReplicaService {
    /// The person as a follower of their partition has them, when the router sent the
    /// request to one and it can answer. A deleted person comes back as their death
    /// document. `None` is a read for Postgres.
    pub(super) fn followed_person(
        &self,
        metadata: &MetadataMap,
        team_id: i64,
        person_id: i64,
    ) -> Option<CachedPerson> {
        if !metadata.contains_key(PARTITION_HEADER) {
            return None;
        }
        let Some(routed) = header(metadata, PARTITION_HEADER) else {
            return unanswered("unreadable_headers");
        };
        let Some(reads) = &self.follower else {
            return unanswered("not_following");
        };
        let Some(reads) = reads.attached() else {
            return unanswered("not_attached");
        };
        let (partitions, epoch) = reads.changelog.layout();
        let partition = partition_for_person(team_id, person_id, partitions);
        if metadata.contains_key(CHANGELOG_EPOCH_HEADER) {
            match header(metadata, CHANGELOG_EPOCH_HEADER) {
                Some(routed) if routed <= epoch => {}
                Some(_) => return unanswered("config_behind"),
                None => return unanswered("unreadable_headers"),
            }
        }
        if routed != u64::from(partition) {
            return unanswered("other_partition");
        }
        let key = PersonCacheKey { team_id, person_id };
        match reads.follower.read(partition, &key, epoch) {
            Ok(person) => {
                count("followed");
                Some(person)
            }
            Err(why) => unanswered(why.label()),
        }
    }

    /// The person named by the routing headers, for a read that asks by UUID. A follower
    /// holding another person under that id has no answer for the read.
    pub(super) fn followed_person_by_uuid(
        &self,
        metadata: &MetadataMap,
        team_id: i64,
        uuid: &str,
    ) -> Option<CachedPerson> {
        if !metadata.contains_key(PARTITION_HEADER) {
            return None;
        }
        let Some(person_id) =
            header(metadata, PERSON_ID_HEADER).and_then(|id| i64::try_from(id).ok())
        else {
            return unanswered("unreadable_headers");
        };
        let person = self.followed_person(metadata, team_id, person_id)?;
        if person.uuid != uuid {
            return unanswered("other_person");
        }
        Some(person)
    }
}

/// Answer with what the follower had, and read Postgres through `stored` for what it did
/// not: a person it does not hold, or one it holds only a death document for.
pub(super) async fn followed_or_stored<F, Fut>(
    followed: Option<CachedPerson>,
    stored: F,
) -> Result<Option<Person>, Status>
where
    F: FnOnce() -> Fut,
    Fut: Future<Output = Result<Option<Person>, Status>>,
{
    match followed {
        Some(person) if !person.is_deleted => Ok(Some(cached_person_into_proto(person))),
        // A live row above a death document is the person created again under the same id.
        Some(death) => Ok(stored().await?.filter(|row| row.version > death.version)),
        None => stored().await,
    }
}

fn unanswered(why: &'static str) -> Option<CachedPerson> {
    count(why);
    None
}

fn count(answer: &'static str) {
    common_metrics::inc(
        "personhog_follower_reads_total",
        &[("answer".to_string(), answer.to_string())],
        1,
    );
}

fn header(metadata: &MetadataMap, name: &'static str) -> Option<u64> {
    metadata.get(name)?.to_str().ok()?.parse().ok()
}
