//! Domain layer: which rows of each event a chunk's scan may leave in ClickHouse.
//!
//! A row is evaluated only against the active conditions of its event, and a row no condition
//! matches adds nothing to any tile. So an event can be filtered only when every active condition on
//! it has a row filter.

use std::collections::{BTreeMap, BTreeSet, HashMap};

use cohort_core::filters::TeamFilters;
use cohort_core::hogvm::analysis::{EventEqualities, PropertyAlternatives};

use super::condition::EventNameSet;
use super::ids::ConditionHash;
use super::plan::ActiveConditions;

pub type ConditionConjuncts = Vec<PropertyAlternatives>;

/// Per filtered event, the conditions a row must satisfy one of. Other events are scanned whole.
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct ScanRowFilter {
    by_event: BTreeMap<String, Vec<ConditionConjuncts>>,
}

impl ScanRowFilter {
    /// A condition's filter counts for an event only when its program tests that event, because the
    /// reverse index buckets conditions by the leaf's key, not by the bytecode.
    pub fn derive(
        event_names: &EventNameSet,
        filters: &TeamFilters,
        active: &ActiveConditions,
        equalities: &HashMap<ConditionHash, EventEqualities>,
    ) -> Self {
        let mut by_event = BTreeMap::new();
        for event in event_names.iter() {
            let Some(bucket) = filters.behavioral_by_event_name.get(event) else {
                continue;
            };
            let mut conditions: Vec<ConditionConjuncts> = Vec::new();
            let mut every_condition_filtered = true;
            for candidate in &bucket.conditions {
                let Some(hash) = active.get(candidate) else {
                    continue;
                };
                match equalities
                    .get(&hash)
                    .and_then(|equalities| equalities.row_filter.as_ref())
                {
                    Some(row_filter) if row_filter.event == *event => {
                        if !conditions.contains(&row_filter.conjuncts) {
                            conditions.push(row_filter.conjuncts.clone());
                        }
                    }
                    Some(_) | None => {
                        every_condition_filtered = false;
                        break;
                    }
                }
            }
            if every_condition_filtered && !conditions.is_empty() {
                by_event.insert(event.clone(), conditions);
            }
        }
        Self { by_event }
    }

    pub fn is_empty(&self) -> bool {
        self.by_event.is_empty()
    }

    pub fn events(&self) -> impl Iterator<Item = (&str, &[ConditionConjuncts])> {
        self.by_event
            .iter()
            .map(|(event, conditions)| (event.as_str(), conditions.as_slice()))
    }

    pub fn keys(&self) -> BTreeSet<&str> {
        self.by_event
            .values()
            .flatten()
            .flatten()
            .flat_map(|alternatives| alternatives.iter().map(|(key, _)| key))
            .collect()
    }
}

#[cfg(test)]
pub(crate) mod test_catalog {
    use chrono_tz::UTC;
    use cohort_core::filters::{CohortId, TeamFilters, TeamFiltersBuilder, TeamId};
    use serde_json::{json, Value};

    use crate::domain::ConditionHash;

    pub(crate) struct Leaf {
        pub(crate) cohort: i32,
        pub(crate) key: &'static str,
        pub(crate) hash: &'static str,
        pub(crate) body: Vec<Value>,
    }

    pub(crate) fn event_is(name: &str) -> Vec<Value> {
        vec![
            json!(32),
            json!(name),
            json!(32),
            json!("event"),
            json!(1),
            json!(1),
            json!(11),
        ]
    }

    pub(crate) fn event_and_property(event: &str, key: &str, value: &str) -> Vec<Value> {
        let mut body = event_is(event);
        body.extend([
            json!(32),
            json!(value),
            json!(32),
            json!(key),
            json!(32),
            json!("properties"),
            json!(1),
            json!(2),
            json!(11),
            json!(3),
            json!(2),
        ]);
        body
    }

    pub(crate) fn catalog(leaves: &[Leaf]) -> TeamFilters {
        let mut builder = TeamFiltersBuilder::default();
        for leaf in leaves {
            let mut bytecode = vec![json!("_H"), json!(1)];
            bytecode.extend(leaf.body.iter().cloned());
            builder
                .add_cohort(
                    CohortId(leaf.cohort),
                    TeamId(2),
                    &json!({
                        "properties": { "type": "AND", "values": [{
                            "type": "behavioral",
                            "value": "performed_event",
                            "key": leaf.key,
                            "conditionHash": leaf.hash,
                            "time_value": 7,
                            "time_interval": "day",
                            "bytecode": bytecode,
                        }]}
                    }),
                )
                .unwrap();
        }
        builder.freeze(UTC)
    }

    pub(crate) fn hash(value: &str) -> ConditionHash {
        ConditionHash::parse(value).unwrap()
    }
}

#[cfg(test)]
mod tests {
    use cohort_core::filters::CohortId;

    use super::test_catalog::{catalog, event_and_property, event_is, hash, Leaf};
    use super::*;
    use crate::domain::{ConditionAnalyses, Lookback, PinnedCondition};

    const FLAG_A: &str = "aaaaaaaaaaaaaaaa";
    const FLAG_B: &str = "bbbbbbbbbbbbbbbb";
    const PAGE_URL: &str = "cccccccccccccccc";
    const PAGE_ANY: &str = "dddddddddddddddd";
    const MISFILED: &str = "eeeeeeeeeeeeeeee";

    fn leaves() -> Vec<Leaf> {
        vec![
            Leaf {
                cohort: 1,
                key: "$feature_flag_called",
                hash: FLAG_A,
                body: event_and_property("$feature_flag_called", "$feature_flag", "a"),
            },
            Leaf {
                cohort: 2,
                key: "$feature_flag_called",
                hash: FLAG_B,
                body: event_and_property("$feature_flag_called", "$feature_flag", "b"),
            },
            Leaf {
                cohort: 3,
                key: "$pageview",
                hash: PAGE_URL,
                body: event_and_property("$pageview", "$current_url", "https://example.com/"),
            },
            Leaf {
                cohort: 4,
                key: "$pageview",
                hash: PAGE_ANY,
                body: event_is("$pageview"),
            },
            // Filed under a key that differs from the event its program tests.
            Leaf {
                cohort: 5,
                key: "purchase",
                hash: MISFILED,
                body: event_and_property("refund", "currency", "EUR"),
            },
        ]
    }

    fn row_filter(active: &[&str]) -> ScanRowFilter {
        let leaves = leaves();
        let filters = catalog(&leaves);
        let conditions = leaves
            .iter()
            .map(|leaf| PinnedCondition {
                cohort_id: CohortId(leaf.cohort),
                hash: hash(leaf.hash),
                event_name: leaf.key.to_owned(),
                lookback: Lookback::SlidingDays(7),
            })
            .collect::<Vec<_>>();
        let analyses = ConditionAnalyses::build(&conditions, &filters);
        analyses.row_filter(
            &EventNameSet::new(leaves.iter().map(|leaf| leaf.key.to_owned())),
            &filters,
            &ActiveConditions::new(active.iter().map(|value| hash(value))),
        )
    }

    fn filtered_events(filter: &ScanRowFilter) -> Vec<&str> {
        filter.events().map(|(event, _)| event).collect()
    }

    #[test]
    fn an_event_is_filtered_only_when_every_active_condition_on_it_is() {
        let all = row_filter(&[FLAG_A, FLAG_B, PAGE_URL, PAGE_ANY, MISFILED]);
        assert_eq!(filtered_events(&all), vec!["$feature_flag_called"]);
        let (_, conditions) = all.events().next().unwrap();
        assert_eq!(conditions.len(), 2, "one entry per flag condition");

        let without_any = row_filter(&[FLAG_A, PAGE_URL]);
        assert_eq!(
            filtered_events(&without_any),
            vec!["$feature_flag_called", "$pageview"]
        );
        assert_eq!(
            without_any.keys(),
            BTreeSet::from(["$current_url", "$feature_flag"])
        );
    }

    #[test]
    fn a_condition_filed_under_another_event_keeps_that_event_whole() {
        assert!(row_filter(&[MISFILED]).is_empty());
    }
}
