use crate::expressions;
use anyhow::{Result, bail};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use std::collections::HashSet;
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Workflow {
    pub version: u32,
    pub id: String,
    pub title: String,
    #[serde(default)]
    pub description: String,
    pub trigger: Trigger,
    pub steps: Vec<Step>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub result: Option<Value>,
    #[serde(default = "parallelism", skip_serializing_if = "default_parallelism")]
    pub concurrency: usize,
    /// Runs in the same view/group share a freshness marker (/run/current).
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub generation: Option<String>,
}

/// How a host knows when to start this workflow.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase", deny_unknown_fields)]
pub enum Trigger {
    /// Run on explicit request.
    Manual,
    /// Run when the schedule is due.
    Schedule {
        /// The timing of scheduled runs.
        schedule: crate::schedules::Schedule,
    },
    /// Run when a topic event satisfies the optional payload filter.
    Event {
        /// The event to listen for.
        event: EventName,
        /// Required top-level payload fields and their exact JSON values.
        #[serde(default, skip_serializing_if = "Option::is_none")]
        filter: Option<serde_json::Map<String, Value>>,
    },
}

/// A topic event that can start a workflow.
#[derive(Clone, Copy, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum EventName {
    /// A message arrived in the topic inbox.
    MessageArrived,
    /// A task was added to the topic.
    TaskAdded,
    /// A task moved to a different column.
    TaskMoved,
    /// A routine run failed.
    RoutineFailed,
}

/// Returns true when the trigger names this event and every filter field is
/// present with an equal JSON value. An absent or empty filter accepts any payload.
pub fn matches(trigger: &Trigger, event_name: EventName, payload: &Value) -> bool {
    let Trigger::Event { event, filter } = trigger else {
        return false;
    };
    *event == event_name
        && filter.as_ref().is_none_or(|fields| {
            fields
                .iter()
                .all(|(key, expected)| payload.get(key) == Some(expected))
        })
}

/// A CLI action carried without its broker's permit ID or local paths.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct CliReference {
    pub action: Vec<String>,
    pub whole: bool,
    pub pattern: Vec<String>,
}

impl CliReference {
    pub fn validate(&self) -> Result<()> {
        if self.whole != self.action.is_empty() || (self.whole && !self.pattern.is_empty()) {
            bail!("Invalid CLI action for this workflow");
        }
        for word in &self.action {
            text(word, 256)?;
        }
        if !self.pattern.is_empty() {
            crate::pattern::validate_pattern(&self.action, &self.pattern)?;
        }
        Ok(())
    }

    pub fn matches(&self, action: &[String], whole: bool, pattern: &[String]) -> bool {
        self.action == action && self.whole == whole && self.pattern == pattern
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "camelCase", deny_unknown_fields)]
pub enum Step {
    Source {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        source: String,
        #[serde(
            default,
            rename = "sourceByName",
            skip_serializing_if = "std::ops::Not::not"
        )]
        source_by_name: bool,
        tool: String,
        #[serde(default)]
        arguments: Value,
    },
    Cli {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        permit: String,
        #[serde(
            default,
            rename = "cliReference",
            skip_serializing_if = "Option::is_none"
        )]
        cli_reference: Option<CliReference>,
        args: Value,
        #[serde(default)]
        options: Value,
    },
    Ai {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        options: Value,
    },
    Agent {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        options: Value,
    },
    Notify {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        options: Value,
    },
    State {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        patch: Value,
    },
    Dataset {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        table: String,
        operation: DataOperation,
        #[serde(default)]
        value: Value,
        #[serde(default)]
        options: Value,
    },
    Command {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        command: String,
        #[serde(default)]
        args: Value,
    },
    Expression {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        #[serde(default)]
        input: Value,
        code: String,
    },
    If {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        condition: Condition,
        then: Vec<Step>,
        #[serde(default, rename = "else")]
        otherwise: Vec<Step>,
    },
    Parallel {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        branches: Vec<Branch>,
    },
    Map {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        items: Value,
        #[serde(default = "parallelism")]
        concurrency: usize,
        #[serde(default = "item_limit")]
        limit: usize,
        steps: Vec<Step>,
        result: Value,
    },
    Merge {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        base: Value,
        joins: Vec<Join>,
    },
    Try {
        id: String,
        #[serde(default, skip_serializing_if = "String::is_empty")]
        title: String,
        steps: Vec<Step>,
        result: Value,
        #[serde(default)]
        fallback: Value,
        #[serde(default, rename = "catch", skip_serializing_if = "Vec::is_empty")]
        catch: Vec<Step>,
        #[serde(default, skip_serializing_if = "std::ops::Not::not")]
        rethrow: bool,
    },
}

fn parallelism() -> usize {
    3
}
fn default_parallelism(value: &usize) -> bool {
    *value == 3
}
fn item_limit() -> usize {
    256
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Branch {
    pub id: String,
    #[serde(default, skip_serializing_if = "String::is_empty")]
    pub title: String,
    pub steps: Vec<Step>,
    pub result: Value,
}
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields, rename_all = "camelCase")]
pub struct Join {
    pub from: Value,
    pub left_key: String,
    pub right_key: String,
    #[serde(rename = "as")]
    pub field: String,
    #[serde(default)]
    pub many: bool,
}
impl Step {
    pub fn id(&self) -> &str {
        match self {
            Self::Source { id, .. }
            | Self::Cli { id, .. }
            | Self::Ai { id, .. }
            | Self::Agent { id, .. }
            | Self::Notify { id, .. }
            | Self::State { id, .. }
            | Self::Dataset { id, .. }
            | Self::Command { id, .. }
            | Self::Expression { id, .. }
            | Self::If { id, .. }
            | Self::Parallel { id, .. }
            | Self::Map { id, .. }
            | Self::Merge { id, .. }
            | Self::Try { id, .. } => id,
        }
    }
    pub fn title(&self) -> &str {
        match self {
            Self::Source { title, .. }
            | Self::Cli { title, .. }
            | Self::Ai { title, .. }
            | Self::Agent { title, .. }
            | Self::Notify { title, .. }
            | Self::State { title, .. }
            | Self::Dataset { title, .. }
            | Self::Command { title, .. }
            | Self::Expression { title, .. }
            | Self::If { title, .. }
            | Self::Parallel { title, .. }
            | Self::Map { title, .. }
            | Self::Merge { title, .. }
            | Self::Try { title, .. } => title,
        }
    }
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(tag = "op", rename_all = "camelCase", deny_unknown_fields)]
pub enum Condition {
    Eq { left: Value, right: Value },
    Ne { left: Value, right: Value },
    Gt { left: Value, right: Value },
    Gte { left: Value, right: Value },
    Lt { left: Value, right: Value },
    Lte { left: Value, right: Value },
    Truthy { value: Value },
    All { conditions: Vec<Condition> },
    Any { conditions: Vec<Condition> },
    Not { condition: Box<Condition> },
}

#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub enum DataOperation {
    Set,
    Patch,
    Remove,
    Clear,
    Rows,
    Count,
    Aggregate,
}

fn name(s: &str) -> Result<()> {
    if s.is_empty()
        || s.len() > 64
        || !s
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || b == b'_' || b == b'-')
        || ["__proto__", "constructor", "prototype"].contains(&s)
    {
        bail!("Workflow and step IDs must use 1–64 letters, digits, underscores or hyphens");
    }
    Ok(())
}
fn text(s: &str, max: usize) -> Result<()> {
    if s.trim().is_empty() || s.len() > max || s.chars().any(char::is_control) {
        bail!("Workflow text must contain 1–{max} bytes without control characters");
    }
    Ok(())
}
fn object(value: &Value, field: &str) -> Result<()> {
    if !value.is_object() {
        bail!("{field} must be an object or a reference");
    }
    Ok(())
}

impl Workflow {
    /// Parses a workflow and validates its trigger, steps and references.
    pub fn parse(value: Value) -> Result<Self> {
        let version = value["version"].as_u64().unwrap_or(0);
        let max_bytes = if version == 2 { 64 * 1024 } else { 32 * 1024 };
        if serde_json::to_vec(&value)?.len() > max_bytes {
            bail!("Workflow exceeds {} KB", max_bytes / 1024);
        }
        check_values(&value, 0, version)?;
        let workflow: Self = serde_json::from_value(value)?;
        if ![1, 2].contains(&workflow.version) {
            bail!("Unsupported workflow version; use version: 1 or 2");
        }
        if !(1..=4).contains(&workflow.concurrency) {
            bail!("Workflow concurrency must be 1–4");
        }
        name(&workflow.id)?;
        if let Some(group) = &workflow.generation {
            name(group)?;
        }
        text(&workflow.title, 256)?;
        if workflow.description.len() > 4096 {
            bail!("Workflow description exceeds 4096 bytes");
        }
        if let Trigger::Schedule { schedule } = &workflow.trigger {
            // A past absolute instant is valid in an already completed
            // definition. Creating/resuming it still requires a future run.
            if !matches!(schedule, crate::schedules::Schedule::At { .. }) {
                schedule.next(chrono::Utc::now())?;
            }
        }
        let mut ids = HashSet::new();
        check_steps(&workflow.steps, &mut ids, 0, workflow.version)?;
        Ok(workflow)
    }
    /// Returns the timing of a scheduled workflow.
    pub fn schedule(&self) -> Option<crate::schedules::Schedule> {
        match &self.trigger {
            Trigger::Manual | Trigger::Event { .. } => None,
            Trigger::Schedule { schedule } => Some(schedule.clone()),
        }
    }
    pub fn sources(&self) -> Vec<&str> {
        fn collect<'a>(steps: &'a [Step], names: &mut Vec<&'a str>) {
            for step in steps {
                match step {
                    Step::Source { source, .. } => names.push(source),
                    Step::Agent { options, .. } => {
                        for tool in options["tools"].as_array().into_iter().flatten() {
                            if let Some(source) = tool["source"].as_str() {
                                names.push(source);
                            }
                        }
                    }
                    Step::If {
                        then, otherwise, ..
                    } => {
                        collect(then, names);
                        collect(otherwise, names);
                    }
                    Step::Parallel { branches, .. } => {
                        for branch in branches {
                            collect(&branch.steps, names);
                        }
                    }
                    Step::Map { steps, .. } => collect(steps, names),
                    Step::Try { steps, catch, .. } => {
                        collect(steps, names);
                        collect(catch, names);
                    }
                    _ => {}
                }
            }
        }
        let mut names = vec![];
        collect(&self.steps, &mut names);
        names
    }
}

fn check_steps(
    steps: &[Step],
    ids: &mut HashSet<String>,
    depth: usize,
    version: u32,
) -> Result<()> {
    if steps.is_empty() || depth > 8 {
        bail!("Workflows need steps and allow at most 8 nested levels");
    }
    for step in steps {
        name(step.id())?;
        if !step.title().is_empty() {
            text(step.title(), 256)?;
        }
        if !ids.insert(step.id().to_owned()) {
            bail!("Duplicate workflow step ID: {}", step.id());
        }
        if ids.len() > if version == 2 { 128 } else { 64 } {
            bail!("Too many workflow steps");
        }
        match step {
            Step::Source {
                source,
                tool,
                arguments,
                ..
            } => {
                text(source, 256)?;
                text(tool, 256)?;
                if !arguments.is_null() {
                    object(arguments, "Source arguments")?;
                }
            }
            Step::Cli {
                permit,
                cli_reference,
                args,
                options,
                ..
            } => {
                text(permit, 256)?;
                if let Some(reference) = cli_reference {
                    reference.validate()?;
                }
                if !options.is_null() {
                    object(options, "CLI options")?;
                }
                if !args.is_array() && args.get("$ref").is_none() {
                    bail!("CLI args must be an array or a reference");
                }
            }
            Step::Ai { options, .. }
            | Step::Agent { options, .. }
            | Step::Notify { options, .. } => object(options, "Step options")?,
            Step::State { patch, .. } => object(patch, "State patch")?,
            Step::Dataset { table, .. } => text(table, 128)?,
            Step::Command { command, .. } => text(command, 128)?,
            Step::Expression { code, .. } => {
                if version < 2 {
                    bail!("Native expressions require workflow version 2");
                }
                expressions::validate(code).map_err(anyhow::Error::msg)?;
            }
            Step::If {
                condition,
                then,
                otherwise,
                ..
            } => {
                check_condition(condition, 0)?;
                check_steps(then, ids, depth + 1, version)?;
                if !otherwise.is_empty() {
                    check_steps(otherwise, ids, depth + 1, version)?;
                }
            }
            Step::Parallel { branches, .. } => {
                if version < 2 {
                    bail!("Parallel, map, merge and try steps require workflow version 2");
                }
                if !(2..=8).contains(&branches.len()) {
                    bail!("Parallel needs 2–8 branches");
                }
                let mut names = HashSet::new();
                for branch in branches {
                    name(&branch.id)?;
                    if !names.insert(&branch.id) {
                        bail!("Duplicate parallel branch ID");
                    }
                    if !branch.title.is_empty() {
                        text(&branch.title, 256)?;
                    }
                    check_steps(&branch.steps, ids, depth + 1, version)?;
                }
            }
            Step::Map {
                concurrency,
                limit,
                steps,
                ..
            } => {
                if version < 2 {
                    bail!("Map steps require workflow version 2");
                }
                if !(1..=4).contains(concurrency) || !(1..=1000).contains(limit) {
                    bail!("Map concurrency must be 1–4 and limit 1–1000");
                }
                check_steps(steps, ids, depth + 1, version)?;
            }
            Step::Merge { joins, .. } => {
                if version < 2 {
                    bail!("Merge steps require workflow version 2");
                }
                if !(1..=8).contains(&joins.len()) {
                    bail!("Merge needs 1–8 data sources");
                }
                let mut fields = HashSet::new();
                for join in joins {
                    name(&join.field)?;
                    if !fields.insert(&join.field) {
                        bail!("Duplicate merge output field");
                    }
                    pointer(&join.left_key)?;
                    pointer(&join.right_key)?;
                }
            }
            Step::Try { steps, catch, .. } => {
                if version < 2 {
                    bail!("Try steps require workflow version 2");
                }
                check_steps(steps, ids, depth + 1, version)?;
                if !catch.is_empty() {
                    check_steps(catch, ids, depth + 1, version)?;
                }
            }
        }
    }
    Ok(())
}
fn pointer(path: &str) -> Result<()> {
    if !path.is_empty() && !path.starts_with('/') {
        bail!("Join keys use JSON pointers such as /id");
    }
    let mut chars = path.chars();
    while let Some(c) = chars.next() {
        if c == '~' && !matches!(chars.next(), Some('0' | '1')) {
            bail!("JSON pointer escapes must use ~0 or ~1");
        }
    }
    Ok(())
}

fn check_condition(condition: &Condition, depth: usize) -> Result<()> {
    if depth > 8 {
        bail!("Conditions allow at most 8 nested levels");
    }
    match condition {
        Condition::All { conditions } | Condition::Any { conditions } => {
            if conditions.is_empty() || conditions.len() > 64 {
                bail!("Use 1–64 conditions");
            }
            for c in conditions {
                check_condition(c, depth + 1)?;
            }
        }
        Condition::Not { condition } => check_condition(condition, depth + 1)?,
        _ => {}
    }
    Ok(())
}
fn check_values(value: &Value, depth: usize, version: u64) -> Result<()> {
    if depth > if version == 2 { 64 } else { 32 } {
        bail!("Workflow data is nested too deeply");
    }
    match value {
        Value::Array(items) => {
            for item in items {
                check_values(item, depth + 1, version)?;
            }
        }
        Value::Object(object) => {
            if let Some(reference) = object.get("$ref") {
                let path = reference.as_str().unwrap_or("");
                let roots = if version == 2 {
                    &[
                        "/input", "/state", "/steps", "/item", "/index", "/error", "/run",
                    ][..]
                } else {
                    &["/input", "/state", "/steps"][..]
                };
                if !roots
                    .iter()
                    .any(|root| path == *root || path.starts_with(&format!("{root}/")))
                    || object.keys().any(|k| k != "$ref" && k != "default")
                {
                    bail!(
                        "References use JSON pointers under /input, /state or /steps, with an optional default"
                    );
                }
                let mut chars = path.chars();
                while let Some(c) = chars.next() {
                    if c == '~' && !matches!(chars.next(), Some('0' | '1')) {
                        bail!("JSON pointer escapes must use ~0 or ~1");
                    }
                }
            }
            for (key, value) in object {
                if ["__proto__", "constructor", "prototype"].contains(&key.as_str()) {
                    bail!("Reserved workflow key: {key}");
                }
                check_values(value, depth + 1, version)?;
            }
        }
        _ => {}
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    fn workflow_with(trigger: Value) -> Result<Workflow> {
        Workflow::parse(json!({
            "version":2, "id":"triage", "title":"Triage", "trigger":trigger,
            "steps":[{"id":"save","kind":"state","patch":{"ready":true}}]
        }))
    }

    #[test]
    fn rejects_unknown_events_and_malformed_triggers() {
        for trigger in [
            json!({"kind":"event","event":"taskDeleted"}),
            json!({"kind":"event","event":"task_added"}),
            json!({"kind":"event"}),
            json!({"kind":"event","event":"taskAdded","filter":["todo"]}),
            json!({"kind":"event","event":"taskAdded","filters":{}}),
        ] {
            assert!(workflow_with(trigger.clone()).is_err(), "{trigger}");
        }
    }

    #[test]
    fn matching_requires_the_named_event_and_every_exact_field_value() -> Result<()> {
        let filter = json!({"column":"done","worker":null,"metadata":{"count":1},"tags":["pin"]});
        let raw = json!({"kind":"event","event":"taskMoved","filter":filter});
        let trigger = workflow_with(raw)?.trigger;
        let mut payload = filter.clone();
        payload["extra"] = json!(true);
        assert!(matches(&trigger, EventName::TaskMoved, &payload));
        assert!(!matches(&trigger, EventName::TaskAdded, &payload));
        for (field, other) in [
            ("column", json!("todo")),
            ("metadata", json!({"count":"1"})),
            ("tags", json!(["pin", "later"])),
            ("worker", json!("bot")),
        ] {
            let mut changed = payload.clone();
            changed[field] = other;
            assert!(
                !matches(&trigger, EventName::TaskMoved, &changed),
                "{field}"
            );
        }
        payload
            .as_object_mut()
            .expect("object fixture")
            .remove("worker");
        assert!(!matches(&trigger, EventName::TaskMoved, &payload));
        assert!(!matches(&trigger, EventName::TaskMoved, &Value::Null));
        Ok(())
    }

    #[test]
    fn an_empty_filter_accepts_any_payload_and_other_trigger_kinds_ignore_events() -> Result<()> {
        let event = EventName::TaskAdded;
        let trigger =
            workflow_with(json!({"kind":"event","event":"taskAdded","filter":{}}))?.trigger;
        assert!(matches(&trigger, event, &json!(42)));
        assert!(!matches(&Trigger::Manual, event, &json!({})));
        let schedule = workflow_with(
            json!({"kind":"schedule","schedule":{"kind":"interval","everyMs":3600000}}),
        )?;
        assert!(!matches(&schedule.trigger, event, &json!({})));
        Ok(())
    }

    #[test]
    fn rejects_unknown_versions_steps_duplicate_ids_and_bad_references() {
        let valid = json!({"version":1,"id":"sync","title":"Sync","trigger":{"kind":"manual"},"steps":[{"id":"save","kind":"state","patch":{"items":{"$ref":"/input/items"}}}]});
        assert!(Workflow::parse(valid.clone()).is_ok());
        for (pointer, replacement) in [
            ("/version", json!(3)),
            ("/steps/0/kind", json!("eval")),
            ("/steps/0/patch/items", json!({"$ref":"/input/a~2b"})),
            ("/steps/0/patch", json!(42)),
            ("/steps/0/patch/items", json!({"$ref":"/host/secret"})),
            ("/steps/0/patch", json!({"__proto__":{}})),
            (
                "/trigger",
                json!({"kind":"schedule","schedule":{"kind":"interval","everyMs":1}}),
            ),
        ] {
            let mut bad = valid.clone();
            *bad.pointer_mut(pointer).unwrap() = replacement;
            assert!(Workflow::parse(bad).is_err(), "{pointer}");
        }
        let mut bad = valid;
        let duplicate = bad["steps"][0].clone();
        bad["steps"].as_array_mut().unwrap().push(duplicate);
        assert!(Workflow::parse(bad).is_err());
    }
}
