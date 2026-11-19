//! The parity rules between the Node feed and the personhog feed: per key
//! for a streaming comparison, over whole states for a gate.

use std::collections::{BTreeSet, HashMap, HashSet};

use uuid::Uuid;

use super::feed::{DistinctIdKey, FeedState, Mapping, PersonKey};

#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum Side {
    Node,
    Personhog,
}

impl Side {
    pub fn label(self) -> &'static str {
        match self {
            Side::Node => "node",
            Side::Personhog => "personhog",
        }
    }
}

/// A person difference outranks a tombstone difference.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum MappingOutcome {
    Agree,
    PersonMismatch,
    DeletedMismatch,
    NodeOnly,
    PersonhogOnly,
}

impl MappingOutcome {
    pub fn label(self) -> &'static str {
        match self {
            MappingOutcome::Agree => "agree",
            MappingOutcome::PersonMismatch => "person_mismatch",
            MappingOutcome::DeletedMismatch => "deleted_mismatch",
            MappingOutcome::NodeOnly => "node_only",
            MappingOutcome::PersonhogOnly => "personhog_only",
        }
    }
}

pub fn compare_mapping(node: Option<&Mapping>, personhog: Option<&Mapping>) -> MappingOutcome {
    match (node, personhog) {
        (None, None) => MappingOutcome::Agree,
        (Some(_), None) => MappingOutcome::NodeOnly,
        (None, Some(_)) => MappingOutcome::PersonhogOnly,
        (Some(node), Some(personhog)) if node.person_uuid != personhog.person_uuid => {
            MappingOutcome::PersonMismatch
        }
        (Some(node), Some(personhog)) if node.is_deleted != personhog.is_deleted => {
            MappingOutcome::DeletedMismatch
        }
        (Some(_), Some(_)) => MappingOutcome::Agree,
    }
}

/// A merge only one feed holds is that feed's stub when it also holds the
/// row that created the person and the other feed never named it; any
/// other silence from the other feed is one-sided.
#[derive(Debug, Clone, Copy, PartialEq, Eq, PartialOrd, Ord, Hash)]
pub enum SurvivorOutcome {
    Agree,
    Mismatch,
    NodeOnly,
    PersonhogOnly,
    NodeStub,
    PersonhogStub,
    Loop(Side),
}

impl SurvivorOutcome {
    pub fn label(self) -> &'static str {
        match self {
            SurvivorOutcome::Agree => "agree",
            SurvivorOutcome::Mismatch => "survivor_mismatch",
            SurvivorOutcome::NodeOnly => "node_only",
            SurvivorOutcome::PersonhogOnly => "personhog_only",
            SurvivorOutcome::NodeStub => "node_stub",
            SurvivorOutcome::PersonhogStub => "personhog_stub",
            SurvivorOutcome::Loop(_) => "loop",
        }
    }
}

/// The same direct target is agreement on its own, so the verdict cannot
/// depend on whether the target's own later merge settled first. Different
/// direct targets are compared by survivor, because one feed may reach the
/// same person through a stub the other never made.
pub fn compare_survivor(
    node: &FeedState,
    personhog: &FeedState,
    old: PersonKey,
) -> SurvivorOutcome {
    match (node.merged_into(&old), personhog.merged_into(&old)) {
        (None, None) => SurvivorOutcome::Agree,
        (Some(_), None) => one_sided(
            node,
            personhog,
            &old,
            SurvivorOutcome::NodeOnly,
            SurvivorOutcome::NodeStub,
        ),
        (None, Some(_)) => one_sided(
            personhog,
            node,
            &old,
            SurvivorOutcome::PersonhogOnly,
            SurvivorOutcome::PersonhogStub,
        ),
        (Some(node_target), Some(personhog_target)) if node_target == personhog_target => {
            SurvivorOutcome::Agree
        }
        (Some(_), Some(_)) => match (node.survivor_of(old), personhog.survivor_of(old)) {
            (Err(_), _) => SurvivorOutcome::Loop(Side::Node),
            (_, Err(_)) => SurvivorOutcome::Loop(Side::Personhog),
            (Ok(node), Ok(personhog)) if node == personhog => SurvivorOutcome::Agree,
            _ => SurvivorOutcome::Mismatch,
        },
    }
}

/// A person the merging feed created in view and the other feed never saw
/// is the merging feed's stub. A person that predates the view, or that the
/// other feed named, makes the other feed's missing merge the finding.
fn one_sided(
    merging: &FeedState,
    other: &FeedState,
    old: &PersonKey,
    only: SurvivorOutcome,
    stub: SurvivorOutcome,
) -> SurvivorOutcome {
    if merging.has_row_for(old) && !other.names_person(old) {
        stub
    } else {
        only
    }
}

/// A feed that contradicts itself.
#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum AccountingViolation {
    Unaccounted {
        person: PersonKey,
        survivor: Uuid,
    },
    StaleMapping {
        key: DistinctIdKey,
        person: Uuid,
        survivor: Uuid,
    },
    Loop {
        person: PersonKey,
    },
}

/// Tombstoned rows count as holding too: a deleted person keeps its
/// tombstones under its own uuid, while a merged-away person's rows moved.
pub fn accounting_violations(feed: &FeedState) -> Vec<AccountingViolation> {
    let holders: HashSet<PersonKey> = feed
        .mappings()
        .map(|(key, mapping)| PersonKey::new(key.team_id, mapping.person_uuid))
        .collect();
    let deleted = deleted_persons(feed);
    let mut violations = Vec::new();
    for person in feed.named_persons() {
        match feed.survivor_of(person) {
            Err(_) => violations.push(AccountingViolation::Loop { person }),
            Ok(survivor) => {
                let survivor_key = PersonKey::new(person.team_id, survivor);
                if !holders.contains(&survivor_key) && !deleted.contains(&survivor_key) {
                    violations.push(AccountingViolation::Unaccounted { person, survivor });
                }
            }
        }
    }
    for (key, mapping) in feed.mappings() {
        if mapping.is_deleted {
            continue;
        }
        if let Ok(survivor) = feed.survivor_of(PersonKey::new(key.team_id, mapping.person_uuid)) {
            if survivor != mapping.person_uuid {
                violations.push(AccountingViolation::StaleMapping {
                    key: key.clone(),
                    person: mapping.person_uuid,
                    survivor,
                });
            }
        }
    }
    violations.sort();
    violations
}

/// Only a delete writes a tombstone: both feeds publish the rows a merge
/// moves as live rows under the target, so a missing merge event cannot
/// look like a delete.
fn deleted_persons(feed: &FeedState) -> HashSet<PersonKey> {
    let mut highest_rows: HashMap<(&DistinctIdKey, Uuid), &Mapping> = HashMap::new();
    for (key, row) in feed.history() {
        highest_rows
            .entry((key, row.person_uuid))
            .and_modify(|highest| {
                if row.version > highest.version {
                    *highest = row;
                }
            })
            .or_insert(row);
    }
    let mut deleted = HashSet::new();
    let mut live = HashSet::new();
    for ((key, person_uuid), row) in highest_rows {
        let person = PersonKey::new(key.team_id, person_uuid);
        if row.is_deleted {
            deleted.insert(person);
        } else {
            live.insert(person);
        }
    }
    &deleted - &live
}

#[derive(Debug, Clone, PartialEq, Eq, PartialOrd, Ord)]
pub enum Divergence {
    Mapping {
        key: DistinctIdKey,
        outcome: MappingOutcome,
        node: Option<Mapping>,
        personhog: Option<Mapping>,
    },
    Survivor {
        person: PersonKey,
        node: Uuid,
        personhog: Uuid,
    },
    Accounting {
        side: Side,
        violation: AccountingViolation,
    },
}

/// A person only one feed named is ignored, as the e2e ignores it: a stub
/// the other backend never made and then merged away. Loops surface through
/// the accounting of the feed that holds them.
pub fn compare_states(node: &FeedState, personhog: &FeedState) -> Vec<Divergence> {
    let mut divergences = Vec::new();
    let keys: BTreeSet<&DistinctIdKey> = node
        .mappings()
        .chain(personhog.mappings())
        .map(|(key, _)| key)
        .collect();
    for key in keys {
        let (node_mapping, personhog_mapping) = (node.mapping(key), personhog.mapping(key));
        let outcome = compare_mapping(node_mapping, personhog_mapping);
        if outcome != MappingOutcome::Agree {
            divergences.push(Divergence::Mapping {
                key: key.clone(),
                outcome,
                node: node_mapping.cloned(),
                personhog: personhog_mapping.cloned(),
            });
        }
    }
    let node_persons = node.named_persons();
    let personhog_persons = personhog.named_persons();
    for person in node_persons.intersection(&personhog_persons) {
        if let (Ok(node_survivor), Ok(personhog_survivor)) =
            (node.survivor_of(*person), personhog.survivor_of(*person))
        {
            if node_survivor != personhog_survivor {
                divergences.push(Divergence::Survivor {
                    person: *person,
                    node: node_survivor,
                    personhog: personhog_survivor,
                });
            }
        }
    }
    for (side, feed) in [(Side::Node, node), (Side::Personhog, personhog)] {
        for violation in accounting_violations(feed) {
            divergences.push(Divergence::Accounting { side, violation });
        }
    }
    divergences.sort();
    divergences
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::cdc_parity::decode::{DistinctIdRow, MergeEvent};

    const TEAM: i64 = 5;

    fn uuid(n: u128) -> Uuid {
        Uuid::from_u128(n)
    }

    fn mapping(person: u128, is_deleted: bool) -> Mapping {
        Mapping {
            person_uuid: uuid(person),
            is_deleted,
            version: 0,
        }
    }

    /// `rows` as (distinct id, person, version, deleted), `merges` as (old, new).
    fn feed(rows: &[(&str, u128, i64, bool)], merges: &[(u128, u128)]) -> FeedState {
        let mut feed = FeedState::new();
        for (distinct_id, person, version, is_deleted) in rows {
            feed.observe_mapping(&DistinctIdRow {
                team_id: TEAM,
                distinct_id: distinct_id.to_string(),
                person_uuid: uuid(*person),
                version: *version,
                is_deleted: *is_deleted,
            });
        }
        for (old, new) in merges {
            feed.observe_merge(&MergeEvent {
                team_id: TEAM,
                old_person_uuid: uuid(*old),
                new_person_uuid: uuid(*new),
                merged_at_ms: 10,
            });
        }
        feed
    }

    #[test]
    fn mapping_outcome_decision_table() {
        let live = |person| mapping(person, false);
        let gone = |person| mapping(person, true);
        assert_eq!(
            compare_mapping(Some(&live(1)), Some(&live(1))),
            MappingOutcome::Agree
        );
        assert_eq!(
            compare_mapping(Some(&gone(1)), Some(&gone(1))),
            MappingOutcome::Agree
        );
        assert_eq!(
            compare_mapping(Some(&live(1)), None),
            MappingOutcome::NodeOnly
        );
        assert_eq!(
            compare_mapping(None, Some(&live(1))),
            MappingOutcome::PersonhogOnly
        );
        assert_eq!(
            compare_mapping(Some(&live(1)), Some(&live(2))),
            MappingOutcome::PersonMismatch
        );
        assert_eq!(
            compare_mapping(Some(&live(1)), Some(&gone(1))),
            MappingOutcome::DeletedMismatch
        );
        assert_eq!(
            compare_mapping(Some(&live(1)), Some(&gone(2))),
            MappingOutcome::PersonMismatch
        );
        let newer = Mapping {
            version: 7,
            ..live(1)
        };
        assert_eq!(
            compare_mapping(Some(&live(1)), Some(&newer)),
            MappingOutcome::Agree
        );
    }

    #[test]
    fn survivor_outcome_decision_table() {
        let old = PersonKey::new(TEAM, uuid(1));
        let none = feed(&[], &[]);
        let knows_one = feed(&[("a", 1, 0, false)], &[]);
        let direct = feed(&[], &[(1, 2)]);
        let created_and_merged = feed(&[("a", 1, 0, false), ("a", 2, 1, false)], &[(1, 2)]);
        let chained = feed(&[], &[(1, 3), (3, 2)]);
        let downstream = feed(&[], &[(1, 2), (2, 5)]);
        let elsewhere = feed(&[], &[(1, 4)]);
        let looped_elsewhere = feed(&[], &[(1, 3), (3, 1)]);
        assert_eq!(compare_survivor(&none, &none, old), SurvivorOutcome::Agree);
        // The merging feed saw the person come to be; the other never named it.
        assert_eq!(
            compare_survivor(&created_and_merged, &none, old),
            SurvivorOutcome::NodeStub
        );
        assert_eq!(
            compare_survivor(&none, &created_and_merged, old),
            SurvivorOutcome::PersonhogStub
        );
        // The other feed named the person, or the person predates the view.
        assert_eq!(
            compare_survivor(&created_and_merged, &knows_one, old),
            SurvivorOutcome::NodeOnly
        );
        assert_eq!(
            compare_survivor(&direct, &none, old),
            SurvivorOutcome::NodeOnly
        );
        assert_eq!(
            compare_survivor(&none, &direct, old),
            SurvivorOutcome::PersonhogOnly
        );
        assert_eq!(
            compare_survivor(&direct, &chained, old),
            SurvivorOutcome::Agree
        );
        assert_eq!(
            compare_survivor(&direct, &downstream, old),
            SurvivorOutcome::Agree
        );
        assert_eq!(
            compare_survivor(&direct, &elsewhere, old),
            SurvivorOutcome::Mismatch
        );
        assert_eq!(
            compare_survivor(&looped_elsewhere, &direct, old),
            SurvivorOutcome::Loop(Side::Node)
        );
        assert_eq!(
            compare_survivor(&direct, &looped_elsewhere, old),
            SurvivorOutcome::Loop(Side::Personhog)
        );
    }

    // The shapes the Kafka parity e2e found: the same result reached by
    // different paths passes, and each way a feed can disagree is named.
    #[test]
    fn compare_states_decision_table() {
        // A birth on one backend, a create-then-merge on the other.
        let birth = feed(&[("anon", 2, 0, false), ("user", 2, 0, false)], &[]);
        let create_then_merge = feed(
            &[
                ("anon", 1, 0, false),
                ("anon", 2, 1, false),
                ("user", 2, 0, false),
            ],
            &[(1, 2)],
        );
        assert_eq!(compare_states(&birth, &create_then_merge), vec![]);
        assert_eq!(compare_states(&create_then_merge, &birth), vec![]);

        let deleted = feed(&[("d", 1, 1, true)], &[]);
        assert_eq!(compare_states(&deleted, &deleted), vec![]);
        let tombstone_left_behind = feed(&[("a", 1, 1, true), ("b", 2, 0, false)], &[(1, 2)]);
        assert_eq!(
            compare_states(&tombstone_left_behind, &tombstone_left_behind),
            vec![]
        );
        let reused_after_delete = feed(
            &[
                ("a", 1, 0, false),
                ("a", 2, 1, false),
                ("a", 2, 2, true),
                ("a", 3, 3, false),
            ],
            &[(1, 2)],
        );
        assert_eq!(
            compare_states(&reused_after_delete, &reused_after_delete),
            vec![]
        );
        let revived_then_moved = feed(
            &[
                ("a", 1, 0, false),
                ("a", 1, 1, true),
                ("a", 1, 2, false),
                ("a", 2, 3, false),
                ("b", 1, 1, true),
                ("b", 4, 2, false),
            ],
            &[],
        );
        assert_eq!(
            accounting_violations(&revived_then_moved),
            vec![AccountingViolation::Unaccounted {
                person: PersonKey::new(TEAM, uuid(1)),
                survivor: uuid(1),
            }]
        );

        let other_person = feed(&[("anon", 3, 0, false), ("user", 2, 0, false)], &[]);
        assert_eq!(
            compare_states(&birth, &other_person),
            vec![Divergence::Mapping {
                key: DistinctIdKey::new(TEAM, "anon"),
                outcome: MappingOutcome::PersonMismatch,
                node: Some(mapping(2, false)),
                personhog: Some(mapping(3, false)),
            }]
        );

        // A move without a merge event: the superseded row still names the
        // old person, which is what exposes the missing event.
        let silent_move = feed(
            &[
                ("anon", 1, 0, false),
                ("anon", 2, 1, false),
                ("user", 2, 0, false),
            ],
            &[],
        );
        assert_eq!(
            compare_states(&silent_move, &create_then_merge),
            vec![
                Divergence::Survivor {
                    person: PersonKey::new(TEAM, uuid(1)),
                    node: uuid(1),
                    personhog: uuid(2),
                },
                Divergence::Accounting {
                    side: Side::Node,
                    violation: AccountingViolation::Unaccounted {
                        person: PersonKey::new(TEAM, uuid(1)),
                        survivor: uuid(1),
                    },
                },
            ]
        );

        let into_two = feed(
            &[("a", 2, 1, false), ("b", 2, 0, false), ("c", 3, 0, false)],
            &[(1, 2)],
        );
        let into_three = feed(
            &[("a", 3, 1, false), ("b", 2, 0, false), ("c", 3, 0, false)],
            &[(1, 3)],
        );
        assert_eq!(
            compare_states(&into_two, &into_three),
            vec![
                Divergence::Mapping {
                    key: DistinctIdKey::new(TEAM, "a"),
                    outcome: MappingOutcome::PersonMismatch,
                    node: Some(Mapping {
                        version: 1,
                        ..mapping(2, false)
                    }),
                    personhog: Some(Mapping {
                        version: 1,
                        ..mapping(3, false)
                    }),
                },
                Divergence::Survivor {
                    person: PersonKey::new(TEAM, uuid(1)),
                    node: uuid(2),
                    personhog: uuid(3),
                },
            ]
        );

        // Person 1 merged away but still mapped live, and survivor 2 holds nothing.
        let stale = feed(&[("a", 1, 0, false)], &[(1, 2)]);
        assert_eq!(
            compare_states(&stale, &stale),
            vec![
                Divergence::Accounting {
                    side: Side::Node,
                    violation: AccountingViolation::Unaccounted {
                        person: PersonKey::new(TEAM, uuid(1)),
                        survivor: uuid(2),
                    },
                },
                Divergence::Accounting {
                    side: Side::Node,
                    violation: AccountingViolation::Unaccounted {
                        person: PersonKey::new(TEAM, uuid(2)),
                        survivor: uuid(2),
                    },
                },
                Divergence::Accounting {
                    side: Side::Node,
                    violation: AccountingViolation::StaleMapping {
                        key: DistinctIdKey::new(TEAM, "a"),
                        person: uuid(1),
                        survivor: uuid(2),
                    },
                },
                Divergence::Accounting {
                    side: Side::Personhog,
                    violation: AccountingViolation::Unaccounted {
                        person: PersonKey::new(TEAM, uuid(1)),
                        survivor: uuid(2),
                    },
                },
                Divergence::Accounting {
                    side: Side::Personhog,
                    violation: AccountingViolation::Unaccounted {
                        person: PersonKey::new(TEAM, uuid(2)),
                        survivor: uuid(2),
                    },
                },
                Divergence::Accounting {
                    side: Side::Personhog,
                    violation: AccountingViolation::StaleMapping {
                        key: DistinctIdKey::new(TEAM, "a"),
                        person: uuid(1),
                        survivor: uuid(2),
                    },
                },
            ]
        );

        let looped = feed(&[("a", 2, 0, false)], &[(1, 2), (2, 1)]);
        assert_eq!(
            compare_states(&looped, &birth)
                .into_iter()
                .filter(|divergence| matches!(
                    divergence,
                    Divergence::Accounting {
                        violation: AccountingViolation::Loop { .. },
                        ..
                    }
                ))
                .count(),
            2
        );
    }
}
