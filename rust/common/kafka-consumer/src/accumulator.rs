use std::collections::HashMap;
use std::hash::Hash;

use crate::types::{Offset, Partition};

/// One polled message as the demux sees it. The crate never reads `inner`.
#[derive(Debug)]
pub struct PolledMessage<K, M> {
    pub offset: Offset,
    /// The routing key. `None` owes no order to any other message and forms
    /// a group of its own.
    pub key: Option<K>,
    pub inner: M,
}

/// One message in a group, paired with its offset so the two cannot diverge.
#[derive(Debug)]
pub struct GroupMessage<M> {
    pub offset: Offset,
    pub message: M,
}

/// One key's messages from one poll on one partition, or one keyless message
/// on its own. Messages keep submission order; ordering by offset is the
/// caller's contract, not the accumulator's.
#[derive(Debug)]
pub struct Group<K, M> {
    pub partition: Partition,
    pub key: Option<K>,
    pub messages: Vec<GroupMessage<M>>,
}

impl<K, M> Group<K, M> {
    pub fn len(&self) -> usize {
        self.messages.len()
    }

    pub fn is_empty(&self) -> bool {
        self.messages.is_empty()
    }
}

/// Demuxes one poll into groups. Push messages in delivery order: a keyed
/// message joins its partition's group for that key, a keyless message opens
/// a group of its own. Groups come out in first-seen order, and each group
/// keeps its messages in submission order.
#[derive(Debug)]
pub struct Accumulator<K, M> {
    groups: Vec<Group<K, M>>,
    /// Nested rather than keyed by `(Partition, K)`, so a lookup borrows the
    /// key instead of cloning it per message.
    group_index_by_key: HashMap<Partition, HashMap<K, usize>>,
    message_count: usize,
}

impl<K, M> Default for Accumulator<K, M> {
    fn default() -> Self {
        Self {
            groups: Vec::new(),
            group_index_by_key: HashMap::new(),
            message_count: 0,
        }
    }
}

impl<K: Hash + Eq + Clone, M> Accumulator<K, M> {
    pub fn push(&mut self, partition: Partition, message: PolledMessage<K, M>) {
        let PolledMessage { offset, key, inner } = message;
        let index = match key {
            None => {
                self.groups.push(Group {
                    partition,
                    key: None,
                    messages: Vec::with_capacity(1),
                });
                self.groups.len() - 1
            }
            Some(key) => {
                let group_index_by_key = self.group_index_by_key.entry(partition).or_default();
                match group_index_by_key.get(&key) {
                    Some(&index) => index,
                    None => {
                        let index = self.groups.len();
                        self.groups.push(Group {
                            partition,
                            key: Some(key.clone()),
                            messages: Vec::new(),
                        });
                        group_index_by_key.insert(key, index);
                        index
                    }
                }
            }
        };
        self.groups[index].messages.push(GroupMessage {
            offset,
            message: inner,
        });
        self.message_count += 1;
    }

    pub fn message_count(&self) -> usize {
        self.message_count
    }

    pub fn into_groups(self) -> Vec<Group<K, M>> {
        self.groups
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn push(
        acc: &mut Accumulator<&'static str, i64>,
        partition: i32,
        offset: i64,
        key: Option<&'static str>,
    ) {
        acc.push(
            Partition(partition),
            PolledMessage {
                offset: Offset(offset),
                key,
                inner: offset,
            },
        );
    }

    fn offsets<K>(group: &Group<K, i64>) -> Vec<Offset> {
        group.messages.iter().map(|m| m.offset).collect()
    }

    #[test]
    fn keyed_messages_group_per_partition_and_key_in_submission_order() {
        let mut acc = Accumulator::default();
        push(&mut acc, 0, 0, Some("a"));
        push(&mut acc, 0, 1, Some("b"));
        push(&mut acc, 1, 5, Some("a"));
        push(&mut acc, 0, 2, Some("a"));

        assert_eq!(acc.message_count(), 4);
        let groups = acc.into_groups();
        let shapes: Vec<(Partition, Option<&str>, Vec<Offset>)> = groups
            .iter()
            .map(|g| (g.partition, g.key, offsets(g)))
            .collect();
        assert_eq!(
            shapes,
            vec![
                (Partition(0), Some("a"), vec![Offset(0), Offset(2)]),
                (Partition(0), Some("b"), vec![Offset(1)]),
                (Partition(1), Some("a"), vec![Offset(5)]),
            ]
        );
        let bodies: Vec<i64> = groups[0].messages.iter().map(|m| m.message).collect();
        assert_eq!(bodies, vec![0, 2]);
    }

    #[test]
    fn keyless_messages_each_form_their_own_group() {
        let mut acc = Accumulator::default();
        push(&mut acc, 0, 0, None);
        push(&mut acc, 0, 1, Some("a"));
        push(&mut acc, 0, 2, None);

        let groups = acc.into_groups();
        assert_eq!(groups.len(), 3);
        assert_eq!(groups[0].key, None);
        assert_eq!(offsets(&groups[0]), vec![Offset(0)]);
        assert_eq!(groups[2].key, None);
        assert_eq!(offsets(&groups[2]), vec![Offset(2)]);
    }
}
