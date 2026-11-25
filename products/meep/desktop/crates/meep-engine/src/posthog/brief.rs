use crate::AgentRun;
use meep_topic::{Actor, FactId};
use serde_json::{Value, json};
use std::collections::BTreeSet;

const THREAD_MESSAGES: usize = 50;

// Citations can appear in structured fields (such as action dependencies and
// thread outcomes) or as IDs in message bodies, task history and action payloads.
fn collect_ids(value: &Value, ids: &mut BTreeSet<FactId>) {
    match value {
        Value::String(text) => ids.extend(
            text.split(|c: char| !c.is_ascii_hexdigit() && c != '-')
                .filter_map(|word| word.trim_matches('-').parse::<FactId>().ok()),
        ),
        Value::Array(items) => items.iter().for_each(|item| collect_ids(item, ids)),
        Value::Object(fields) => fields.values().for_each(|item| collect_ids(item, ids)),
        _ => {}
    }
}

pub(super) fn run_context(run: &AgentRun, tools: bool) -> serde_json::Result<Value> {
    if !tools {
        return serde_json::to_value(run);
    }

    let mut cited = run.disputed_fact_ids.clone();
    let mut task = serde_json::to_value(&run.task)?;
    collect_ids(&task, &mut cited);
    let mut evidence = json!({});
    let fields = task.as_object_mut().expect("Task serializes as an object");
    let source_title = !matches!(run.task.added_by, Actor::User | Actor::Agent)
        || run
            .task
            .origin
            .as_ref()
            .is_some_and(|o| o.connection != "user");
    for key in [
        "origin", "log", "action", "result", "draft", "worker", "title",
    ] {
        if (key != "title" || source_title)
            && let Some(value) = fields.remove(key)
        {
            evidence[key] = value;
        }
    }
    task["untrusted_source_data"] = evidence;

    let mut thread = serde_json::to_value(&run.thread)?;
    collect_ids(&thread, &mut cited);
    if let Some(messages) = thread.get_mut("messages").and_then(Value::as_array_mut) {
        let omitted = messages.len().saturating_sub(THREAD_MESSAGES);
        messages.drain(..omitted);
        thread["omitted_messages"] = json!(omitted);
    }

    let mut facts = vec![];
    let mut omitted_facts = 0;
    for fact in run.facts.iter().chain(&run.historical_facts) {
        if cited.contains(&fact.id)
            || fact.provenance.thread.is_some() && fact.provenance.thread == run.task.from_thread
        {
            facts.push(fact);
        } else if fact.is_current() {
            omitted_facts += 1;
        }
    }
    let routines: Vec<_> = run
        .routines
        .iter()
        .map(|r| json!({"id":r.binding.id,"name":r.binding.name}))
        .collect();
    let mut brief = json!({
        "topic_name":run.topic_name, "mission":run.mission, "goals":run.goals,
        "task":task, "rules":run.rules, "routines":routines,
        "disputed_fact_ids":run.disputed_fact_ids, "started_at":run.started_at,
        "untrusted_source_data":{"thread":thread,"facts":facts,"context_sources":run.context_sources},
        "more":{"facts":omitted_facts,"watches":run.watches.len(),"how":"Call list_facts for current facts, get_topic for context sources and watches, and get_thread for the full source thread."}
    });
    if run.setup {
        brief["setup"] = json!(true);
    }
    Ok(brief)
}
