use std::collections::hash_map::Entry;
use std::collections::HashMap;

use metrics::{counter, gauge};
use personhog_proto::personhog::types::v1::Person;

/// In-memory dedup buffer keyed by (team_id, person_id).
/// Later messages for the same person overwrite earlier ones.
pub struct PersonBuffer {
    entries: HashMap<(i64, i64), Person>,
    /// Max offset seen per partition for offset commits.
    offsets: HashMap<i32, i64>,
    capacity: usize,
}

impl PersonBuffer {
    pub fn new(capacity: usize) -> Self {
        Self {
            entries: HashMap::new(),
            offsets: HashMap::new(),
            capacity,
        }
    }

    /// Insert a person into the buffer. Later messages for the same person
    /// overwrite earlier ones -- Kafka partition ordering guarantees the
    /// latest version always arrives last.
    pub fn insert(&mut self, person: Person, partition: i32, offset: i64) {
        self.offsets
            .entry(partition)
            .and_modify(|o| {
                if offset > *o {
                    *o = offset;
                }
            })
            .or_insert(offset);

        let key = (person.team_id, person.id);
        match self.entries.entry(key) {
            Entry::Occupied(mut e) => {
                e.insert(person);
                counter!("personhog_writer_messages_deduped_total").increment(1);
            }
            Entry::Vacant(e) => {
                e.insert(person);
            }
        }

        gauge!("personhog_writer_buffer_size").set(self.entries.len() as f64);
    }

    pub fn len(&self) -> usize {
        self.entries.len()
    }

    pub fn is_empty(&self) -> bool {
        self.entries.is_empty()
    }

    pub fn is_full(&self) -> bool {
        self.entries.len() >= self.capacity
    }

    /// Get the current offset for a partition, if tracked.
    pub fn partition_offset(&self, partition: i32) -> Option<i64> {
        self.offsets.get(&partition).copied()
    }

    /// Drain all entries and offsets for flushing.
    pub fn drain(&mut self) -> (Vec<Person>, HashMap<i32, i64>) {
        let persons: Vec<Person> = self.entries.drain().map(|(_, p)| p).collect();
        let offsets = std::mem::take(&mut self.offsets);
        gauge!("personhog_writer_buffer_size").set(0.0);
        (persons, offsets)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn make_person(team_id: i64, person_id: i64, version: i64) -> Person {
        Person {
            id: person_id,
            team_id,
            uuid: format!("uuid-{team_id}-{person_id}"),
            properties: vec![],
            properties_last_updated_at: vec![],
            properties_last_operation: vec![],
            created_at: 1700000000,
            version,
            is_identified: false,
            is_user_id: None,
            last_seen_at: None,
        }
    }

    #[test]
    fn insert_and_drain() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 42, 1), 0, 0);
        buf.insert(make_person(1, 43, 1), 0, 1);

        assert_eq!(buf.len(), 2);

        let (persons, offsets) = buf.drain();
        assert_eq!(persons.len(), 2);
        assert_eq!(offsets[&0], 1);
        assert_eq!(buf.len(), 0);
    }

    #[test]
    fn dedup_keeps_latest_message() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 42, 1), 0, 0);
        buf.insert(make_person(1, 42, 2), 0, 1);
        buf.insert(make_person(1, 42, 3), 0, 2);

        assert_eq!(buf.len(), 1);

        let (persons, _) = buf.drain();
        assert_eq!(persons[0].version, 3);
    }

    #[test]
    fn is_full_respects_capacity() {
        let mut buf = PersonBuffer::new(2);
        assert!(!buf.is_full());

        buf.insert(make_person(1, 1, 1), 0, 0);
        assert!(!buf.is_full());

        buf.insert(make_person(1, 2, 1), 0, 1);
        assert!(buf.is_full());
    }

    #[test]
    fn tracks_max_offset_per_partition() {
        let mut buf = PersonBuffer::new(100);
        buf.insert(make_person(1, 1, 1), 0, 10);
        buf.insert(make_person(1, 2, 1), 0, 5);
        buf.insert(make_person(1, 3, 1), 1, 3);

        assert_eq!(buf.partition_offset(0), Some(10));
        assert_eq!(buf.partition_offset(1), Some(3));
        assert_eq!(buf.partition_offset(2), None);

        let (_, offsets) = buf.drain();
        assert_eq!(offsets[&0], 10);
        assert_eq!(offsets[&1], 3);
    }
}
