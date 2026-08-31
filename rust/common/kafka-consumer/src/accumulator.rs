use std::collections::HashMap;

use crate::charge::Charge;
use crate::types::{AssignmentEpoch, Offset, Partition};

/// One polled message, as the partition driver sees it: Kafka metadata plus
/// the application's raw payload. The loop never decodes `inner`.
#[derive(Debug)]
pub struct PolledMessage<M> {
    pub offset: Offset,
    /// The routing key: the message's Kafka partition key, opaque bytes.
    /// `None` owes no order at all — one free group per message.
    pub key: Option<Vec<u8>>,
    pub charge: Charge,
    pub inner: M,
}

/// One routing key's messages from one poll — or one keyless message. The
/// per-key unit that crosses the seam and comes back as a completion.
#[derive(Debug)]
pub struct Group<M> {
    /// The affinity hint: the partition the group came from.
    pub partition: Partition,
    pub epoch: AssignmentEpoch,
    /// The group's offsets, ascending; any subset of the partition's ring.
    pub offsets: Vec<Offset>,
    pub charge: Charge,
    pub key: Option<Vec<u8>>,
    pub messages: Vec<M>,
}

/// One poll's demuxed groups, in offset order per key. Obtained from the
/// factory, lent down the demux under `&mut`, released to the transport side
/// whole, by value.
#[derive(Debug)]
pub struct Accumulator<M> {
    groups: Vec<Group<M>>,
}

impl<M> Default for Accumulator<M> {
    fn default() -> Accumulator<M> {
        Accumulator { groups: Vec::new() }
    }
}

impl<M> Accumulator<M> {
    pub fn is_empty(&self) -> bool {
        self.groups.is_empty()
    }

    pub fn groups(&self) -> &[Group<M>] {
        &self.groups
    }

    pub fn into_groups(self) -> Vec<Group<M>> {
        self.groups
    }

    /// Demux one partition's slice of a poll into groups, preserving offset
    /// order within each key. Keys group in first-seen order; a null-key
    /// message becomes its own free group.
    pub(crate) fn push_demuxed(
        &mut self,
        partition: Partition,
        epoch: AssignmentEpoch,
        msgs: Vec<PolledMessage<M>>,
    ) {
        let mut by_key: HashMap<Vec<u8>, usize> = HashMap::new();
        for msg in msgs {
            let index = match &msg.key {
                None => {
                    self.groups.push(Group {
                        partition,
                        epoch,
                        offsets: Vec::with_capacity(1),
                        charge: Charge::ZERO,
                        key: None,
                        messages: Vec::with_capacity(1),
                    });
                    self.groups.len() - 1
                }
                Some(key) => *by_key.entry(key.clone()).or_insert_with(|| {
                    self.groups.push(Group {
                        partition,
                        epoch,
                        offsets: Vec::new(),
                        charge: Charge::ZERO,
                        key: msg.key.clone(),
                        messages: Vec::new(),
                    });
                    self.groups.len() - 1
                }),
            };
            let group = &mut self.groups[index];
            group.offsets.push(msg.offset);
            group.charge += msg.charge;
            group.messages.push(msg.inner);
        }
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn msg(offset: i64, key: Option<&str>) -> PolledMessage<i64> {
        PolledMessage {
            offset: Offset(offset),
            key: key.map(|k| k.as_bytes().to_vec()),
            charge: Charge {
                events: 1,
                bytes: 1,
            },
            inner: offset,
        }
    }

    #[test]
    fn keys_group_in_offset_order_and_null_keys_stay_free() {
        let mut acc = Accumulator::default();
        acc.push_demuxed(
            Partition(0),
            AssignmentEpoch(1),
            vec![
                msg(0, Some("a")),
                msg(1, None),
                msg(2, Some("b")),
                msg(3, Some("a")),
                msg(4, None),
            ],
        );

        let groups = acc.groups();
        assert_eq!(groups.len(), 4);
        assert_eq!(groups[0].key.as_deref(), Some(b"a".as_slice()));
        assert_eq!(groups[0].offsets, vec![Offset(0), Offset(3)]);
        assert_eq!(groups[1].key, None);
        assert_eq!(groups[1].offsets, vec![Offset(1)]);
        assert_eq!(groups[2].key.as_deref(), Some(b"b".as_slice()));
        assert_eq!(
            groups[3].key, None,
            "each null-key message is its own group"
        );
        assert_eq!(groups[3].offsets, vec![Offset(4)]);
    }
}
