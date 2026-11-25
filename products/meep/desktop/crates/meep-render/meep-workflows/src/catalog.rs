//! The foreground workflow protocol for one mounted view. Keep a catalog per view.
//! A host with durable storage or a scheduler can implement the same SDK methods.
use crate::{Trigger, Workflow};
use anyhow::{Context, Result, bail, ensure};
use chrono::Utc;
use serde_json::{Value, json};
use std::collections::{BTreeMap, BTreeSet};

#[derive(Default)]
pub struct ManualCatalog {
    entries: BTreeMap<String, Entry>,
    sequence: u64,
}

struct Entry {
    definition: Value,
    enabled: bool,
    status: &'static str,
    active: BTreeSet<u64>,
    latest: u64,
    last_run: Option<String>,
    error: Option<String>,
    trace: Value,
}

impl Entry {
    fn snapshot(&self) -> Value {
        json!({"kind":"workflow", "id":self.definition["id"], "schedule":null, "nextRun":null,
            "enabled":self.enabled, "status":self.status, "lastRun":self.last_run,
            "lastError":self.error, "payload":{"definition":self.definition, "lastTrace":self.trace}})
    }
}

impl ManualCatalog {
    /// Accepts the operation following `native.workflows.`. Effects inside a run
    /// still go through the calling view's own host. No source grants live here.
    pub fn request(&mut self, operation: &str, params: &Value) -> Result<Value> {
        match operation {
            "register" | "update" => return self.write(operation, params),
            "list" => return Ok(self.entries.values().map(Entry::snapshot).collect()),
            "run" => {
                bail!("Background runs need a scheduler. Use workflows.execute for a mounted view.")
            }
            _ => {}
        }
        let id = params["id"].as_str().context("Missing workflow ID")?;
        let entry = self.entries.get_mut(id).context("Unknown workflow")?;
        match operation {
            "begin" => {
                ensure!(entry.enabled, "Workflow is paused");
                self.sequence += 1;
                let run = self.sequence.to_string();
                entry.latest = self.sequence;
                entry.active.insert(self.sequence);
                entry.last_run = Some(Utc::now().to_rfc3339());
                entry.error = None;
                entry.trace = Value::Null;
                entry.status = "running";
                Ok(json!({"run":run,"definition":entry.definition}))
            }
            "progress" | "trace" | "finish" => {
                let run: u64 = params["run"].as_str().context("Missing run ID")?.parse()?;
                let active = if operation == "finish" {
                    entry.active.remove(&run)
                } else {
                    entry.active.contains(&run)
                };
                if !active || run != entry.latest {
                    return Ok(json!({"recorded":false}));
                }
                if operation == "finish" {
                    entry.error = params["error"].as_str().map(str::to_owned);
                    entry.status = if entry.error.is_some() {
                        "failed"
                    } else {
                        "completed"
                    };
                } else {
                    let trace = &params["trace"];
                    ensure!(
                        trace["nodes"].is_object() && serde_json::to_vec(trace)?.len() <= 65536,
                        "Invalid workflow trace"
                    );
                    // A deferred progress snapshot can arrive after the final trace.
                    if operation == "progress"
                        && !entry.trace.is_null()
                        && entry.trace["live"] != true
                    {
                        return Ok(json!({"recorded":false}));
                    }
                    entry.trace = trace.clone();
                }
                Ok(json!({"recorded":true}))
            }
            "setEnabled" => {
                ensure!(entry.active.is_empty(), "Workflow is running");
                entry.enabled = params["enabled"]
                    .as_bool()
                    .context("Missing enabled flag")?;
                entry.status = if entry.enabled { "ready" } else { "paused" };
                Ok(entry.snapshot())
            }
            "unregister" => {
                ensure!(entry.active.is_empty(), "Workflow is running");
                self.entries.remove(id);
                Ok(json!({"cancelled":true}))
            }
            _ => bail!("Unknown workflow operation {operation}"),
        }
    }

    fn write(&mut self, op: &str, params: &Value) -> Result<Value> {
        let expected = if op == "update" {
            params.get("expected")
        } else {
            None
        };
        let raw = if expected.is_some() {
            &params["definition"]
        } else {
            params
        };
        let workflow = Workflow::parse(raw.clone())?;
        match workflow.trigger {
            Trigger::Manual => {}
            Trigger::Schedule { .. } => bail!("Scheduled workflows need a scheduler"),
            Trigger::Event { .. } => bail!("Event workflows need a host that dispatches events"),
        }
        let definition = serde_json::to_value(&workflow)?;
        if let Some(entry) = self.entries.get_mut(&workflow.id) {
            if op == "register" {
                ensure!(
                    entry.definition == definition,
                    "Workflow already exists with a different definition"
                );
            } else {
                ensure!(entry.active.is_empty(), "Workflow is running");
                if let Some(expected) = expected {
                    ensure!(
                        json!(Workflow::parse(expected.clone())?) == entry.definition,
                        "Workflow changed before update"
                    );
                }
                if entry.definition != definition {
                    entry.definition = definition;
                    entry.trace = Value::Null;
                    entry.error = None;
                    entry.last_run = None;
                    entry.status = if entry.enabled { "ready" } else { "paused" };
                }
            }
            return Ok(entry.snapshot());
        }
        ensure!(op == "register", "Unknown workflow");
        let entry = Entry {
            definition,
            enabled: true,
            status: "ready",
            active: BTreeSet::new(),
            latest: 0,
            last_run: None,
            error: None,
            trace: Value::Null,
        };
        let snapshot = entry.snapshot();
        self.entries.insert(workflow.id, entry);
        Ok(snapshot)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_manual_catalog_rejects_event_workflows() {
        let definition = json!({
            "version":2,"id":"triage","title":"Triage","trigger":{"kind":"event","event":"taskAdded"},
            "steps":[{"id":"save","kind":"state","patch":{"ready":true}}]
        });
        let mut catalog = ManualCatalog::default();
        let error = catalog
            .request("register", &definition)
            .expect_err("event needs a dispatcher");
        assert!(error.to_string().contains("dispatches events"));
        assert!(catalog.entries.is_empty());
    }

    #[test]
    fn registrations_edits_and_late_completions_are_scoped_to_the_right_run() -> Result<()> {
        let mut catalog = ManualCatalog::default();
        let original = json!({"version":2,"id":"index","title":"Index","trigger":{"kind":"manual"},"steps":[{"id":"save","kind":"state","patch":{"ready":true}}]});
        let mut changed = original.clone();
        changed["title"] = json!("Refresh");
        let id = json!({"id":"index"});
        let empty = catalog.request("register", &original)?;
        assert_eq!(catalog.request("register", &original)?, empty);
        assert!(catalog.request("register", &changed).is_err());
        let first = catalog.request("begin", &id)?["run"].clone();
        let overlapping = catalog.request("begin", &id)?["run"].clone();
        assert!(catalog.request("update", &changed).is_err());
        catalog.request("finish", &json!({"id":"index","run":overlapping}))?;
        assert!(catalog.request("update", &changed).is_err());
        catalog.request("finish", &json!({"id":"index","run":first}))?;
        catalog.request("update", &json!({"definition":changed,"expected":original}))?;
        assert!(
            catalog
                .request(
                    "update",
                    &json!({"definition":original,"expected":original})
                )
                .is_err()
        );
        let second = catalog.request("begin", &id)?["run"].clone();
        assert_ne!(first, second);
        assert_eq!(
            catalog.request(
                "finish",
                &json!({"id":"index","run":first,"error":"obsolete"})
            )?["recorded"],
            false
        );
        let trace = json!({"nodes":{}});
        catalog.request("trace", &json!({"id":"index","run":second,"trace":trace}))?;
        assert_eq!(
            catalog.request(
                "progress",
                &json!({"id":"index","run":second,"trace":{"live":true,"nodes":{}}})
            )?["recorded"],
            false
        );
        catalog.request("finish", &json!({"id":"index","run":second}))?;
        let finished = catalog.request("list", &Value::Null)?;
        assert_eq!(finished[0]["payload"]["lastTrace"], trace);
        assert_eq!(finished[0]["status"], "completed");
        catalog.request("setEnabled", &json!({"id":"index","enabled":false}))?;
        assert_eq!(catalog.request("register", &changed)?["enabled"], false);
        assert!(catalog.request("begin", &id).is_err());
        assert!(ManualCatalog::default().request("begin", &id).is_err());
        assert_eq!(catalog.request("unregister", &id)?["cancelled"], true);
        Ok(())
    }
}
