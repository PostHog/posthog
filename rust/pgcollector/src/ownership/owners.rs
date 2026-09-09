//! Table -> team, from the generated `table_owners.json` plus hand-written `overrides.yaml`.

use super::tables::{is_catalog, Extracted};
use crate::config::OwnershipConfig;
use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use std::collections::{BTreeMap, HashMap};

const TABLE_OWNERS_JSON: &str = include_str!("../../ownership/table_owners.json");
const OVERRIDES_YAML: &str = include_str!("../../ownership/overrides.yaml");

pub const UNOWNED: &str = "unowned";

#[derive(Deserialize)]
struct TableOwnersFile {
    tables: BTreeMap<String, TableRecord>,
}
#[derive(Deserialize)]
struct TableRecord {
    #[serde(default)]
    owners: Vec<String>,
    #[serde(default)]
    slack: Option<String>,
    #[serde(default)]
    notifications: Option<String>,
}

#[derive(Deserialize, Default)]
struct Overrides {
    #[serde(default)]
    databases: Vec<DatabaseRule>,
    #[serde(default)]
    tables: Vec<TableRule>,
    #[serde(default)]
    rotations: HashMap<String, String>,
    #[serde(default)]
    channels: HashMap<String, String>,
}
#[derive(Deserialize)]
struct DatabaseRule {
    server: Option<String>,
    datname: Option<String>,
    team: String,
}
#[derive(Deserialize)]
struct TableRule {
    #[serde(rename = "match")]
    pattern: String,
    team: Option<String>,
    #[serde(default)]
    kind: RuleKind,
}
#[derive(Deserialize, Default, Clone, Copy, PartialEq, Eq, Debug)]
#[serde(rename_all = "lowercase")]
enum RuleKind {
    #[default]
    Owner,
    Hub,
    Ignore,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct TableTeam {
    pub table: String,
    pub team: Option<String>,
    pub hub: bool,
}

#[derive(Debug, Clone, Serialize, PartialEq, Eq)]
pub struct Attribution {
    pub team: String,
    /// database | comment | table | unowned
    pub method: &'static str,
    pub primary_table: Option<String>,
    pub tables: Vec<TableTeam>,
    pub parser: &'static str,
    pub reason: String,
}

pub struct Ownership {
    tables: HashMap<String, (Option<String>, bool)>,
    globs: Vec<(glob::Pattern, Option<String>, RuleKind)>,
    databases: Vec<DatabaseRule>,
    rotations: HashMap<String, String>,
    channels: HashMap<String, String>,
    fallback_rotation: String,
}

impl Ownership {
    pub fn load(cfg: &OwnershipConfig) -> Result<Self> {
        let (json, yaml) = match cfg.dir.as_deref() {
            Some(d) => (
                std::fs::read_to_string(d.join("table_owners.json"))
                    .with_context(|| format!("reading {}", d.display()))?,
                std::fs::read_to_string(d.join("overrides.yaml")).unwrap_or_default(),
            ),
            None => (TABLE_OWNERS_JSON.to_string(), OVERRIDES_YAML.to_string()),
        };
        Self::from_sources(&json, &yaml, &cfg.fallback_rotation)
    }

    pub fn from_sources(json: &str, yaml: &str, fallback_rotation: &str) -> Result<Self> {
        let file: TableOwnersFile = serde_json::from_str(json).context("table_owners.json")?;
        let ov: Overrides = if yaml.trim().is_empty() {
            Overrides::default()
        } else {
            serde_yaml::from_str(yaml).context("overrides.yaml")?
        };
        let mut channels = ov.channels;
        let mut tables = HashMap::new();
        for (t, r) in file.tables {
            let team = r.owners.first().cloned().filter(|o| !o.starts_with('@'));
            if let (Some(team), Some(ch)) = (&team, r.notifications.or(r.slack)) {
                channels.entry(team.clone()).or_insert(ch);
            }
            tables.insert(t, (team, false));
        }
        let mut globs = Vec::new();
        for r in ov.tables {
            let p = glob::Pattern::new(&r.pattern)
                .with_context(|| format!("overrides.yaml pattern {}", r.pattern))?;
            globs.push((p, r.team, r.kind));
        }
        Ok(Self {
            tables,
            globs,
            databases: ov.databases,
            rotations: ov.rotations,
            channels,
            fallback_rotation: fallback_rotation.to_string(),
        })
    }

    pub fn table_count(&self) -> usize {
        self.tables.len()
    }

    /// (team, hub) for one table. Globs from overrides beat the generated map.
    fn lookup(&self, table: &str) -> Option<(Option<String>, bool)> {
        let mut found = self.tables.get(table).cloned();
        for (p, team, kind) in &self.globs {
            if !p.matches(table) {
                continue;
            }
            match kind {
                RuleKind::Ignore => return None,
                RuleKind::Hub => {
                    let t = team
                        .clone()
                        .or_else(|| found.as_ref().and_then(|f| f.0.clone()));
                    found = Some((t, true));
                }
                RuleKind::Owner => found = Some((team.clone(), false)),
            }
        }
        found
    }

    pub fn attribute(&self, server: &str, datname: &str, ex: &Extracted) -> Attribution {
        let tables: Vec<TableTeam> = ex
            .ranked()
            .into_iter()
            .filter(|t| !is_catalog(t))
            .filter_map(|t| {
                self.lookup(t).map(|(team, hub)| TableTeam {
                    table: t.to_string(),
                    team,
                    hub,
                })
            })
            .collect();
        let base = |team: String, method: &'static str, primary: Option<String>, reason: String| {
            Attribution {
                team,
                method,
                primary_table: primary,
                tables: tables.clone(),
                parser: ex.parser,
                reason,
            }
        };
        if let Some(r) = self.databases.iter().find(|r| {
            r.server.as_deref().is_none_or(|s| s == server)
                && r.datname.as_deref().is_none_or(|d| d == datname)
        }) {
            return base(
                r.team.clone(),
                "database",
                None,
                format!("database {datname} on {server} belongs to {}", r.team),
            );
        }
        if let Some(m) = &ex.marker {
            return base(
                m.clone(),
                "comment",
                None,
                format!("owner='{m}' marker in the query text"),
            );
        }
        // Driving table first; hubs only when nothing else names a team.
        let pick = tables
            .iter()
            .find(|t| !t.hub && t.team.is_some())
            .or_else(|| tables.iter().find(|t| t.team.is_some()));
        match pick {
            Some(t) => {
                let team = t.team.clone().unwrap_or_default();
                let why = if t.hub {
                    format!("only hub tables referenced; {} is owned by {team}", t.table)
                } else if Some(&t.table) == ex.target.as_ref() {
                    format!("writes {} (owned by {team})", t.table)
                } else {
                    format!("reads {} (owned by {team})", t.table)
                };
                base(team, "table", Some(t.table.clone()), why)
            }
            None => {
                let named: Vec<&str> = tables.iter().map(|t| t.table.as_str()).collect();
                let why = if named.is_empty() {
                    "no known table referenced".to_string()
                } else {
                    format!("no owner for {}", named.join(", "))
                };
                base(
                    UNOWNED.into(),
                    "unowned",
                    tables.first().map(|t| t.table.clone()),
                    why,
                )
            }
        }
    }

    pub fn rotation(&self, team: &str) -> String {
        if team == UNOWNED {
            return self.fallback_rotation.clone();
        }
        self.rotations
            .get(team)
            .cloned()
            .unwrap_or_else(|| team.strip_prefix("team-").unwrap_or(team).to_string())
    }

    /// Channel name without the leading `#`, as incident.io expects in `slack_channel`.
    pub fn slack_channel(&self, team: &str) -> Option<String> {
        self.channels
            .get(team)
            .map(|c| c.trim_start_matches('#').to_string())
    }
}

#[cfg(test)]
mod tests {
    use super::super::tables::extract;
    use super::*;

    const JSON: &str = r##"{"version":1,"tables":{
        "posthog_dashboard":{"owners":["team-analytics-platform"],"slack":"#team-analytics-platform","notifications":"#alerts-analytics"},
        "posthog_team":{"owners":[]},
        "posthog_person":{"owners":["team-ingestion"],"slack":"#team-ingestion"},
        "posthog_featureflag":{"owners":["team-feature-flags"],"slack":"#team-feature-flags"},
        "posthog_thing":{"owners":["@someone"]}
    }}"##;
    const YAML: &str = r#"
databases:
  - server: persons
    team: team-ingestion
tables:
  - match: posthog_team
    kind: hub
  - match: "posthog_person*"
    kind: hub
    team: team-ingestion
  - match: "personhog_*"
    team: team-ingestion
  - match: "django_*"
    kind: ignore
rotations:
  team-analytics-platform: analytics
"#;

    fn own() -> Ownership {
        Ownership::from_sources(JSON, YAML, "infra").unwrap()
    }

    #[test]
    fn driving_table_beats_joined_hub() {
        let a = own().attribute("cloud", "posthog", &extract(r#"SELECT 1 FROM "posthog_dashboard" INNER JOIN "posthog_team" ON true WHERE "posthog_dashboard"."id" = $1"#));
        assert_eq!(a.team, "team-analytics-platform");
        assert_eq!(a.method, "table");
        assert_eq!(a.primary_table.as_deref(), Some("posthog_dashboard"));
        assert_eq!(a.tables.len(), 2);
        assert!(a.tables[1].hub);
    }

    #[test]
    fn dml_target_and_hub_only_queries() {
        let a = own().attribute(
            "cloud",
            "posthog",
            &extract(
                r#"UPDATE "posthog_featureflag" SET "active" = $1 FROM "posthog_team" WHERE 1=1"#,
            ),
        );
        assert_eq!(a.team, "team-feature-flags");
        assert!(a.reason.starts_with("writes posthog_featureflag"));
        let a = own().attribute(
            "cloud",
            "posthog",
            &extract(r#"SELECT 1 FROM "posthog_team" WHERE id = $1"#),
        );
        assert_eq!(a.team, UNOWNED);
        assert_eq!(a.method, "unowned");
        let a = own().attribute(
            "cloud",
            "posthog",
            &extract(r#"SELECT 1 FROM "posthog_person" WHERE id = $1"#),
        );
        assert_eq!((a.team.as_str(), a.method), ("team-ingestion", "table"));
        assert!(a.reason.starts_with("only hub tables"));
    }

    #[test]
    fn database_rule_marker_and_globs_take_precedence() {
        let o = own();
        let a = o.attribute("persons", "d63d9", &extract("SELECT 1 FROM whatever"));
        assert_eq!((a.team.as_str(), a.method), ("team-ingestion", "database"));
        let a = o.attribute(
            "cloud",
            "posthog",
            &extract("/*owner='team-x'*/ SELECT 1 FROM posthog_dashboard"),
        );
        assert_eq!((a.team.as_str(), a.method), ("team-x", "comment"));
        let a = o.attribute(
            "cloud",
            "posthog",
            &extract("SELECT 1 FROM personhog_lease"),
        );
        assert_eq!(a.team, "team-ingestion");
        let a = o.attribute("cloud", "posthog", &extract("SELECT 1 FROM django_session"));
        assert_eq!(a.method, "unowned");
        assert!(a.tables.is_empty());
    }

    #[test]
    fn handles_are_not_teams_and_channels_come_from_the_registry() {
        let o = own();
        let a = o.attribute("cloud", "posthog", &extract("SELECT 1 FROM posthog_thing"));
        assert_eq!(a.team, UNOWNED);
        assert_eq!(
            o.slack_channel("team-analytics-platform").as_deref(),
            Some("alerts-analytics")
        );
        assert_eq!(
            o.slack_channel("team-ingestion").as_deref(),
            Some("team-ingestion")
        );
        assert_eq!(o.rotation("team-analytics-platform"), "analytics");
        assert_eq!(o.rotation("team-ingestion"), "ingestion");
        assert_eq!(o.rotation(UNOWNED), "infra");
    }

    #[test]
    fn compiled_in_files_load() {
        let o = Ownership::load(&OwnershipConfig::default()).unwrap();
        assert!(o.table_count() > 100);
        let a = o.attribute(
            "cloud",
            "posthog",
            &extract(r#"SELECT 1 FROM "posthog_person" INNER JOIN "posthog_team" ON true"#),
        );
        assert_eq!(a.team, "team-ingestion");
    }
}
