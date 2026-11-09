use std::collections::HashMap;
use std::time::{Duration, Instant};

use anyhow::{Context, Result};
use envconfig::Envconfig;
use personhog_property_store::{PropertyReader, PropertyStoreConfig};
use serde_json::json;

use crate::report::ConsistencyViolation;
use crate::state::{verify_properties, ExpectedPerson};

const CATCH_UP: Duration = Duration::from_secs(60);

/// A SlateDB leader loads a person only once the writer applied it, so only `served` is expected.
pub fn load_violations(leaders: &[(String, bool, String)]) -> Vec<ConsistencyViolation> {
    let mut violations = Vec::new();
    for (name, _, page) in leaders.iter().filter(|(_, slatedb, _)| *slatedb) {
        let loads = counters_by_outcome(page, "personhog_leader_property_store_reads_total");
        let unexpected: Vec<(&str, f64)> = loads
            .iter()
            .filter(|(outcome, count)| *outcome != "served" && **count > 0.0)
            .map(|(outcome, count)| (outcome.as_str(), *count))
            .collect();
        if !unexpected.is_empty() {
            violations.push(ConsistencyViolation {
                person_id: 0,
                key: format!("property_loads:{name}"),
                expected: json!({ "outcomes": ["served"] }),
                actual: json!(unexpected),
            });
        }
    }
    violations
}

fn counters_by_outcome(page: &str, metric: &str) -> std::collections::HashMap<String, f64> {
    page.lines()
        .filter_map(|line| {
            let rest = line.strip_prefix(metric)?.strip_prefix("{")?;
            let (labels, value) = rest.split_once("} ")?;
            let outcome = labels
                .split(',')
                .find_map(|label| label.strip_prefix("outcome=\""))?
                .trim_end_matches('"');
            Some((outcome.to_string(), value.trim().parse().ok()?))
        })
        .collect()
}

pub fn store_reader() -> Result<PropertyReader> {
    let config = PropertyStoreConfig::init_from_env().context("property store config")?;
    Ok(PropertyReader::new(
        &config,
        personhog_property_store::object_store(&config)?,
    ))
}

pub async fn verify_store_against_journal(
    reader: &PropertyReader,
    team_id: i64,
    journal: &HashMap<i64, ExpectedPerson>,
) -> Result<Vec<ConsistencyViolation>> {
    let deadline = Instant::now() + CATCH_UP;
    let mut violations = Vec::new();
    for (&person_id, expected) in journal {
        let stored = loop {
            let read = reader.get(team_id, person_id).await;
            let caught_up = matches!(&read, Ok(Some(s)) if s.version >= expected.last_version);
            if caught_up || Instant::now() > deadline {
                break read.ok().flatten();
            }
            tokio::time::sleep(Duration::from_millis(100)).await;
        };
        match stored {
            Some(stored) if stored.version >= expected.last_version && !stored.deleted => {
                let properties: serde_json::Value = serde_json::from_slice(&stored.properties)
                    .context("parsing stored properties")?;
                violations.extend(verify_properties(
                    person_id,
                    &expected.written_properties,
                    &properties,
                ));
            }
            other => violations.push(ConsistencyViolation {
                person_id,
                key: "slatedb".to_string(),
                expected: json!({ "version": format!(">= {}", expected.last_version), "deleted": false }),
                actual: json!(other.map(|s| json!({ "version": s.version, "deleted": s.deleted }))),
            }),
        }
    }
    Ok(violations)
}

#[cfg(test)]
mod tests {
    use super::*;

    const PAGE: &str = "\
# TYPE personhog_leader_property_store_reads_total counter
personhog_leader_property_store_reads_total{outcome=\"served\"} 12
personhog_leader_property_store_reads_total{outcome=\"behind\"} 3
";

    #[test]
    fn only_a_slatedb_leaders_unserved_loads_are_violations() {
        for (name, slatedb, expected) in [("slatedb", true, 1), ("postgres", false, 0)] {
            let leaders = [("leader-0".to_string(), slatedb, PAGE.to_string())];
            assert_eq!(load_violations(&leaders).len(), expected, "{name}");
        }
    }
}
