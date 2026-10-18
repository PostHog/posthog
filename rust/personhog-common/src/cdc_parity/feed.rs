//! The end state a reader of one feed is left with: the highest version per
//! distinct id, as a ReplacingMergeTree keeps it, and one merge target per
//! merged person, as the cohort stream processor applies it.

use std::collections::{HashMap, HashSet};

use uuid::Uuid;

use super::decode::{DistinctIdRow, MergeEvent};

/// The version only orders rows; it is never compared across feeds.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub struct Mapping {
    pub person_uuid: Uuid,
    pub is_deleted: bool,
    pub version: i64,
}

impl From<&DistinctIdRow> for Mapping {
    fn from(row: &DistinctIdRow) -> Self {
        Self {
            person_uuid: row.person_uuid,
            is_deleted: row.is_deleted,
            version: row.version,
        }
    }
}

#[derive(Debug, Clone, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct DistinctIdKey {
    pub team_id: i64,
    pub distinct_id: String,
}

impl DistinctIdKey {
    pub fn new(team_id: i64, distinct_id: impl Into<String>) -> Self {
        Self {
            team_id,
            distinct_id: distinct_id.into(),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, PartialOrd, Ord)]
pub struct PersonKey {
    pub team_id: i64,
    pub person_uuid: Uuid,
}

impl PersonKey {
    pub fn new(team_id: i64, person_uuid: Uuid) -> Self {
        Self {
            team_id,
            person_uuid,
        }
    }
}

/// Two different rows at one version, reported once per version.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MappingConflict {
    pub key: DistinctIdKey,
    pub version: i64,
    pub first: Mapping,
    pub second: Mapping,
}

/// One person merged into two different persons.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct MergeConflict {
    pub old: PersonKey,
    pub first: Uuid,
    pub second: Uuid,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
#[error("merge events of team {} loop through {}", .person.team_id, .person.person_uuid)]
pub struct MergeLoop {
    pub person: PersonKey,
}

/// The first row sits inline because most keys only ever see one.
#[derive(Debug)]
struct MappingHistory {
    first: Mapping,
    more: Vec<Mapping>,
}

impl MappingHistory {
    fn rows(&self) -> impl Iterator<Item = &Mapping> {
        std::iter::once(&self.first).chain(self.more.iter())
    }

    /// The highest version; the first arrival among equal versions.
    fn latest(&self) -> &Mapping {
        let mut latest = &self.first;
        for row in &self.more {
            if row.version > latest.version {
                latest = row;
            }
        }
        latest
    }
}

/// How many stored rows and merge ends name one person.
#[derive(Debug, Default, Clone, Copy)]
struct Names {
    rows: u32,
    merges: u32,
}

#[derive(Debug, Default)]
pub struct FeedState {
    mappings: HashMap<DistinctIdKey, MappingHistory>,
    merged_into: HashMap<PersonKey, Uuid>,
    /// Kept exact through eviction, so naming is one lookup.
    named: HashMap<PersonKey, Names>,
}

impl FeedState {
    pub fn new() -> Self {
        Self::default()
    }

    pub fn observe_mapping(&mut self, row: &DistinctIdRow) -> Option<MappingConflict> {
        let key = DistinctIdKey::new(row.team_id, row.distinct_id.as_str());
        let mapping = Mapping::from(row);
        let person = PersonKey::new(row.team_id, row.person_uuid);
        let Some(history) = self.mappings.get_mut(&key) else {
            self.mappings.insert(
                key,
                MappingHistory {
                    first: mapping,
                    more: Vec::new(),
                },
            );
            self.named.entry(person).or_default().rows += 1;
            return None;
        };
        if history.rows().any(|seen| *seen == mapping) {
            return None;
        }
        // A second row already stored at this version was reported then.
        let conflict = {
            let mut at_version = history
                .rows()
                .filter(|seen| seen.version == mapping.version);
            match (at_version.next(), at_version.next()) {
                (Some(first), None) => Some(MappingConflict {
                    key: key.clone(),
                    version: mapping.version,
                    first: first.clone(),
                    second: mapping.clone(),
                }),
                _ => None,
            }
        };
        history.more.push(mapping);
        self.named.entry(person).or_default().rows += 1;
        conflict
    }

    /// Keeps the first target; a different second one is the conflict.
    pub fn observe_merge(&mut self, event: &MergeEvent) -> Option<MergeConflict> {
        let old = PersonKey::new(event.team_id, event.old_person_uuid);
        match self.merged_into.get(&old) {
            Some(&first) if first != event.new_person_uuid => Some(MergeConflict {
                old,
                first,
                second: event.new_person_uuid,
            }),
            Some(_) => None,
            None => {
                self.merged_into.insert(old, event.new_person_uuid);
                self.named.entry(old).or_default().merges += 1;
                self.named
                    .entry(PersonKey::new(event.team_id, event.new_person_uuid))
                    .or_default()
                    .merges += 1;
                None
            }
        }
    }

    fn unname(&mut self, person: PersonKey, update: impl FnOnce(&mut Names)) {
        if let Some(names) = self.named.get_mut(&person) {
            update(names);
            if names.rows == 0 && names.merges == 0 {
                self.named.remove(&person);
            }
        }
    }

    pub fn mapping(&self, key: &DistinctIdKey) -> Option<&Mapping> {
        self.mappings.get(key).map(MappingHistory::latest)
    }

    pub fn merged_into(&self, old: &PersonKey) -> Option<Uuid> {
        self.merged_into.get(old).copied()
    }

    pub fn survivor_of(&self, person: PersonKey) -> Result<Uuid, MergeLoop> {
        let mut visited: Vec<Uuid> = Vec::new();
        let mut current = person;
        while let Some(&next) = self.merged_into.get(&current) {
            if visited.contains(&current.person_uuid) {
                return Err(MergeLoop { person: current });
            }
            visited.push(current.person_uuid);
            current = PersonKey::new(person.team_id, next);
        }
        Ok(current.person_uuid)
    }

    /// A person only one feed named is that feed's own path to the result.
    pub fn names_person(&self, person: &PersonKey) -> bool {
        self.named.contains_key(person)
    }

    /// Whether a stored row, at any version, maps a distinct id to the
    /// person: the feed saw the person come to be, not only a merge of it.
    pub fn has_row_for(&self, person: &PersonKey) -> bool {
        self.named.get(person).is_some_and(|names| names.rows > 0)
    }

    pub fn mappings(&self) -> impl Iterator<Item = (&DistinctIdKey, &Mapping)> {
        self.mappings
            .iter()
            .map(|(key, history)| (key, history.latest()))
    }

    pub fn merges(&self) -> impl Iterator<Item = (&PersonKey, Uuid)> {
        self.merged_into.iter().map(|(old, new)| (old, *new))
    }

    pub fn named_persons(&self) -> HashSet<PersonKey> {
        self.named.keys().copied().collect()
    }

    pub fn remove_mapping(&mut self, key: &DistinctIdKey) -> Option<Mapping> {
        let history = self.mappings.remove(key)?;
        let latest = history.latest().clone();
        for row in history.rows() {
            self.unname(PersonKey::new(key.team_id, row.person_uuid), |names| {
                names.rows -= 1
            });
        }
        Some(latest)
    }

    pub fn remove_merge(&mut self, old: &PersonKey) -> Option<Uuid> {
        let new = self.merged_into.remove(old)?;
        self.unname(*old, |names| names.merges -= 1);
        self.unname(PersonKey::new(old.team_id, new), |names| names.merges -= 1);
        Some(new)
    }

    pub fn mapping_count(&self) -> usize {
        self.mappings.len()
    }

    pub fn merge_count(&self) -> usize {
        self.merged_into.len()
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn person(n: u128) -> PersonKey {
        PersonKey::new(5, uuid(n))
    }

    fn row(person: u128, version: i64, is_deleted: bool) -> DistinctIdRow {
        DistinctIdRow {
            team_id: 5,
            distinct_id: "d".to_string(),
            person_uuid: uuid(person),
            version,
            is_deleted,
        }
    }

    fn mapping(person: u128, version: i64, is_deleted: bool) -> Mapping {
        Mapping {
            person_uuid: uuid(person),
            is_deleted,
            version,
        }
    }

    fn merge(old: u128, new: u128) -> MergeEvent {
        MergeEvent {
            team_id: 5,
            old_person_uuid: uuid(old),
            new_person_uuid: uuid(new),
            merged_at_ms: 10,
        }
    }

    // A replay after a crash repeats rows in any order; only a different
    // row at an already seen version is a finding, and only once.
    #[test]
    fn rows_fold_to_the_highest_version_and_report_a_tie_once() {
        let key = DistinctIdKey::new(5, "d");
        let mut feed = FeedState::new();
        for entry in [
            row(1, 1, false),
            row(1, 2, false),
            row(1, 2, false),
            row(1, 1, false),
        ] {
            assert_eq!(feed.observe_mapping(&entry), None);
        }
        assert_eq!(feed.mapping(&key), Some(&mapping(1, 2, false)));

        assert_eq!(
            feed.observe_mapping(&row(2, 2, false)),
            Some(MappingConflict {
                key: key.clone(),
                version: 2,
                first: mapping(1, 2, false),
                second: mapping(2, 2, false),
            })
        );
        assert_eq!(feed.observe_mapping(&row(2, 2, false)), None);
        assert_eq!(feed.observe_mapping(&row(2, 2, true)), None);
        assert_eq!(feed.observe_mapping(&row(1, 3, false)), None);
        assert_eq!(feed.mapping(&key), Some(&mapping(1, 3, false)));

        // The same disagreement read after a higher version is still one.
        let mut later = FeedState::new();
        assert_eq!(later.observe_mapping(&row(1, 3, false)), None);
        assert_eq!(later.observe_mapping(&row(1, 2, false)), None);
        assert!(later.observe_mapping(&row(2, 2, false)).is_some());
        assert_eq!(later.mapping(&key), Some(&mapping(1, 3, false)));
        assert!(later.names_person(&person(2)));
        assert!(later.has_row_for(&person(2)));

        // Eviction forgets the history and the persons only it named.
        assert_eq!(later.remove_mapping(&key), Some(mapping(1, 3, false)));
        assert!(!later.names_person(&person(1)));
        assert!(!later.names_person(&person(2)));
        assert_eq!(later.observe_mapping(&row(2, 2, false)), None);
        assert_eq!(later.mapping(&key), Some(&mapping(2, 2, false)));
        assert_eq!(later.mapping_count(), 1);
    }

    #[test]
    fn merges_keep_the_first_target_and_follow_chains() {
        let mut feed = FeedState::new();
        assert_eq!(feed.observe_merge(&merge(1, 2)), None);
        assert_eq!(feed.observe_merge(&merge(1, 2)), None);
        assert_eq!(feed.observe_merge(&merge(2, 3)), None);
        assert_eq!(feed.survivor_of(person(1)), Ok(uuid(3)));
        assert_eq!(feed.survivor_of(person(3)), Ok(uuid(3)));
        assert_eq!(feed.survivor_of(person(9)), Ok(uuid(9)));

        assert_eq!(
            feed.observe_merge(&merge(1, 4)),
            Some(MergeConflict {
                old: person(1),
                first: uuid(2),
                second: uuid(4),
            })
        );
        assert_eq!(feed.merged_into(&person(1)), Some(uuid(2)));

        assert_eq!(feed.observe_merge(&merge(3, 1)), None);
        assert_eq!(
            feed.survivor_of(person(1)),
            Err(MergeLoop { person: person(1) })
        );
        assert_eq!(
            feed.named_persons(),
            HashSet::from([person(1), person(2), person(3)])
        );
        // A merge end names the person without a row for it.
        assert!(feed.names_person(&person(1)));
        assert!(!feed.has_row_for(&person(1)));

        // A person stays named while any merge still ends in it.
        assert_eq!(feed.remove_merge(&person(3)), Some(uuid(1)));
        assert_eq!(feed.survivor_of(person(1)), Ok(uuid(3)));
        assert!(feed.names_person(&person(3)));
        assert_eq!(feed.remove_merge(&person(2)), Some(uuid(3)));
        assert!(!feed.names_person(&person(3)));
        assert!(feed.names_person(&person(1)));
        assert_eq!(feed.merge_count(), 1);
    }
}
