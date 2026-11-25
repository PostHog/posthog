use super::*;

impl Project {
    pub async fn workflow_details(
        &self,
        flow: Uuid,
        pause: bool,
    ) -> Result<meep_wire::WorkflowDetails> {
        let api = ProjectEndpoint::new(&self.origin, self.project, "hog_flows")?;
        if pause {
            let url = format!(
                "{}/api/projects/{}/hog_flows/{flow}/",
                self.origin.trim_end_matches('/'),
                self.project
            );
            reqwest::Client::builder()
                .redirect(reqwest::redirect::Policy::none())
                .timeout(std::time::Duration::from_secs(20))
                .build()?
                .patch(url)
                .bearer_auth(&self.token)
                .json(&serde_json::json!({"status":"draft"}))
                .send()
                .await?
                .error_for_status()?;
        }
        let definition: Value = api.get(&self.token, &format!("{flow}/")).await?;
        let status = definition["status"]
            .as_str()
            .context("Missing workflow status")?;
        let runs = meep_posthog::workflows::BoundWorkflow::new(&self.origin, self.project, flow)?
            .recent_details(&self.token, 8)
            .await
            .unwrap_or_default();
        // A step name describes an intention. Only the invocation's own output
        // or reported failure belongs in its history.
        use futures_util::{StreamExt, stream};
        #[derive(Deserialize)]
        struct Logs {
            results: Vec<Entry>,
        }
        #[derive(Deserialize)]
        struct Entry {
            message: String,
        }
        let history = stream::iter(runs)
            .map(|run| {
                let api = &api;
                async move {
                    let observed = run.invocation;
                    let result = match run.error_message.filter(|s| !s.trim().is_empty()) {
                        Some(error) => Some(error),
                        None => {
                            let path = format!(
                                "{flow}/logs/?instance_id={}&level=LOG&limit=1",
                                observed.invocation_id
                            );
                            api.get::<Logs>(&self.token, &path)
                                .await
                                .ok()
                                .and_then(|logs| logs.results.into_iter().next())
                                .map(|entry| entry.message)
                                .filter(|s| !s.trim().is_empty())
                        }
                    };
                    meep_wire::WorkflowRun {
                        at: run.started_at.or(run.scheduled_at),
                        status: observed.status,
                        duration_ms: observed.duration_ms,
                        result,
                    }
                }
            })
            .buffered(4)
            .collect::<Vec<_>>()
            .await;
        let (trigger, mut graph) = shape(&definition);
        // Per-step outcomes come from PostHog's app metrics, keyed by action id.
        // They are a garnish: a step without metrics still renders.
        let counts = stream::iter(graph.iter().map(|step| step.id.clone()).collect::<Vec<_>>())
            .map(|step| {
                let api = &api;
                async move {
                    let path = format!(
                        "{flow}/metrics/?instance_id={step}&after=-7d&interval=day&breakdown_by=kind"
                    );
                    (step, api.get::<Value>(&self.token, &path).await.ok().map(|v| series_counts(&v)))
                }
            })
            .buffered(4)
            .collect::<Vec<_>>()
            .await;
        for (step, c) in counts {
            if let Some(s) = graph.iter_mut().find(|s| s.id == step) {
                s.counts = c.filter(|c| c.succeeded + c.failed > 0);
            }
        }
        let week = api
            .get::<Value>(
                &self.token,
                &format!("{flow}/metrics/totals/?after=-7d&breakdown_by=kind"),
            )
            .await
            .ok()
            .map(|v| totals_counts(&v["totals"]));
        Ok(meep_wire::WorkflowDetails {
            manual_run_allowed: None,
            watches: vec![],
            observations: vec![],
            enabled: status == "active",
            steps: graph.iter().map(|s| s.name.clone()).collect(),
            runs: history.iter().map(|r| r.status.clone()).collect(),
            run_history: history,
            name: definition["name"]
                .as_str()
                .filter(|s| !s.is_empty())
                .map(str::to_owned),
            trigger,
            graph,
            week,
            url: Some(format!(
                "{}/project/{}/workflows/{flow}/workflow",
                self.origin.trim_end_matches('/'),
                self.project
            )),
        })
    }
}

/// Sum a metrics series response into successes and failures.
fn series_counts(v: &Value) -> meep_wire::StepCounts {
    let mut c = meep_wire::StepCounts::default();
    for series in v["series"].as_array().into_iter().flatten() {
        let total: u64 = series["values"]
            .as_array()
            .into_iter()
            .flatten()
            .filter_map(Value::as_u64)
            .sum();
        add(&mut c, series["name"].as_str().unwrap_or_default(), total);
    }
    c
}
fn totals_counts(v: &Value) -> meep_wire::StepCounts {
    let mut c = meep_wire::StepCounts::default();
    for (kind, n) in v.as_object().into_iter().flatten() {
        add(&mut c, kind, n.as_u64().unwrap_or(0));
    }
    c
}
/// PostHog app-metric kinds: `success` and `failure`; others (billing, other) are not outcomes.
fn add(c: &mut meep_wire::StepCounts, kind: &str, n: u64) {
    match kind {
        "success" => c.succeeded += n,
        "failure" => c.failed += n,
        _ => {}
    }
}

/// Read a hog flow's trigger and its steps in reading order. Branching steps
/// nest each branch one level deeper, labelled from the step's configuration.
fn shape(definition: &Value) -> (Option<String>, Vec<meep_wire::WorkflowStep>) {
    let actions: Vec<&Value> = definition["actions"]
        .as_array()
        .into_iter()
        .flatten()
        .collect();
    let edges: Vec<&Value> = definition["edges"]
        .as_array()
        .into_iter()
        .flatten()
        .collect();
    let trigger = actions
        .iter()
        .find(|a| a["type"] == "trigger")
        .map(|a| trigger_sentence(&a["config"]))
        .or_else(|| {
            definition["trigger"]
                .is_object()
                .then(|| trigger_sentence(&definition["trigger"]))
        });
    let mut out = Vec::new();
    let mut seen = std::collections::BTreeSet::new();
    let start = actions
        .iter()
        .find(|a| a["type"] == "trigger")
        .or_else(|| actions.first())
        .and_then(|a| a["id"].as_str());
    #[allow(clippy::too_many_arguments)]
    fn visit(
        id: &str,
        depth: u8,
        branch: Option<String>,
        actions: &[&Value],
        edges: &[&Value],
        trigger: &Option<String>,
        seen: &mut std::collections::BTreeSet<String>,
        out: &mut Vec<meep_wire::WorkflowStep>,
    ) {
        if !seen.insert(id.to_owned()) || depth > 6 {
            return;
        }
        let Some(a) = actions.iter().find(|a| a["id"] == id) else {
            return;
        };
        let kind = a["type"].as_str().unwrap_or("step").to_owned();
        let config = &a["config"];
        let detail = match kind.as_str() {
            "trigger" => trigger.clone(),
            other => step_detail(other, config),
        };
        let name = a["name"]
            .as_str()
            .filter(|s| !s.trim().is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| detail.clone().unwrap_or_else(|| kind.replace('_', " ")));
        out.push(meep_wire::WorkflowStep {
            id: id.to_owned(),
            kind: kind.clone(),
            name,
            detail,
            branch,
            depth,
            counts: None,
        });
        let mut outgoing: Vec<&&Value> = edges.iter().filter(|e| e["from"] == id).collect();
        outgoing.sort_by_key(|e| (e["type"] != "branch", e["index"].as_u64().unwrap_or(0)));
        let branching = outgoing.iter().any(|e| e["type"] == "branch");
        for e in outgoing {
            let Some(to) = e["to"].as_str() else { continue };
            if branching {
                let label = if e["type"] == "branch" {
                    branch_label(&kind, config, e["index"].as_u64().unwrap_or(0) as usize)
                } else {
                    "Otherwise".to_owned()
                };
                visit(
                    to,
                    depth + 1,
                    Some(label),
                    actions,
                    edges,
                    trigger,
                    seen,
                    out,
                );
            } else {
                visit(to, depth, None, actions, edges, trigger, seen, out);
            }
        }
    }
    if let Some(start) = start {
        visit(
            start, 0, None, &actions, &edges, &trigger, &mut seen, &mut out,
        );
    }
    if out.is_empty() {
        // Older or partial definitions: keep the named steps in order.
        out = actions
            .iter()
            .enumerate()
            .filter_map(|(i, a)| {
                let name = a["name"]
                    .as_str()
                    .filter(|s| !s.is_empty())
                    .or(a["type"].as_str())?;
                Some(meep_wire::WorkflowStep {
                    id: a["id"]
                        .as_str()
                        .map_or_else(|| i.to_string(), str::to_owned),
                    kind: a["type"].as_str().unwrap_or("step").to_owned(),
                    name: name.to_owned(),
                    detail: None,
                    branch: None,
                    depth: 0,
                    counts: None,
                })
            })
            .collect();
    }
    (trigger, out)
}

/// Describe event triggers by quoting each event name as written, so a name
/// like `web-nav-v2 changed` never reads as part of the sentence.
pub(crate) fn fires_sentence(names: &[impl AsRef<str>]) -> String {
    let quoted: Vec<String> = names.iter().map(|n| format!("“{}”", n.as_ref())).collect();
    format!("When {} fires", quoted.join(" or "))
}

fn trigger_sentence(t: &Value) -> String {
    match t["type"].as_str().unwrap_or_default() {
        "event" => {
            let names: Vec<&str> = t["filters"]["events"]
                .as_array()
                .into_iter()
                .flatten()
                .filter_map(|e| e["name"].as_str().or(e["id"].as_str()))
                .collect();
            if names.is_empty() {
                "When a matching event happens".into()
            } else {
                fires_sentence(&names)
            }
        }
        "webhook" => "When its webhook is called".into(),
        "manual" => "When started by hand or by the topic".into(),
        "schedule" => "On a schedule".into(),
        "batch" => "For a batch of people".into(),
        "tracking_pixel" => "When its tracking pixel loads".into(),
        _ => "When triggered".into(),
    }
}

fn duration(s: &str) -> Option<String> {
    let s = s.trim();
    let (n, unit) = s.split_at(s.find(|c: char| !c.is_ascii_digit() && c != '.')?);
    let n: f64 = n.parse().ok()?;
    let unit = match unit.trim() {
        "s" => "second",
        "m" => "minute",
        "h" => "hour",
        "d" => "day",
        "w" => "week",
        _ => return None,
    };
    Some(if n == 1. {
        format!("1 {unit}")
    } else {
        format!("{n} {unit}s")
    })
}

fn step_detail(kind: &str, config: &Value) -> Option<String> {
    Some(match kind {
        "delay" => format!("Wait {}", duration(config["delay_duration"].as_str()?)?),
        "wait_until_condition" => match config["max_wait_duration"].as_str().and_then(duration) {
            Some(max) => format!("Wait until a condition is met, up to {max}"),
            None => "Wait until a condition is met".into(),
        },
        "wait_until_time_window" => "Wait for the allowed time window".into(),
        "conditional_branch" => {
            let n = config["conditions"].as_array().map_or(0, Vec::len);
            format!("Split into {} paths by condition", n + 1)
        }
        "random_cohort_branch" => "Split people at random".into(),
        "function_email" => "Send an email".into(),
        "function_sms" => "Send a text message".into(),
        "function_push" => "Send a push notification".into(),
        "function" => {
            let template = config["template_id"]
                .as_str()?
                .trim_start_matches("template-");
            // A webhook aimed at this server's routine callback reports to the topic.
            let to_topic = config["inputs"]["url"]["value"]
                .as_str()
                .is_some_and(|url| url.contains("/v1/routines/"));
            match template {
                "webhook" if to_topic => "Report to the topic".into(),
                "webhook" => "Call a webhook".into(),
                "slack" => "Post to Slack".into(),
                other => format!("Run {}", other.replace(['-', '_'], " ")),
            }
        }
        "exit" => "End the run".into(),
        _ => return None,
    })
}

fn branch_label(kind: &str, config: &Value, index: usize) -> String {
    match kind {
        "random_cohort_branch" => config["cohorts"][index]["percentage"]
            .as_f64()
            .map(|p| format!("{p}% of people"))
            .unwrap_or_else(|| format!("Group {}", index + 1)),
        _ => config["conditions"][index]["name"]
            .as_str()
            .filter(|s| !s.is_empty())
            .map(str::to_owned)
            .unwrap_or_else(|| format!("Condition {}", index + 1)),
    }
}

#[cfg(test)]
mod shape_tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn a_branching_flow_reads_in_order_with_labelled_branches() {
        let flow = json!({
            "actions": [
                {"id": "t", "type": "trigger", "name": "", "config": {"type": "event", "filters": {"events": [{"name": "signup"}]}}},
                {"id": "w", "type": "delay", "name": "", "config": {"delay_duration": "2d"}},
                {"id": "c", "type": "conditional_branch", "name": "Activated?", "config": {"conditions": [{"name": "Has a dashboard"}]}},
                {"id": "a", "type": "function_email", "name": "Nudge", "config": {}},
                {"id": "b", "type": "function", "name": "", "config": {"template_id": "template-slack"}},
            ],
            "edges": [
                {"from": "t", "to": "w", "type": "continue"},
                {"from": "w", "to": "c", "type": "continue"},
                {"from": "c", "to": "a", "type": "branch", "index": 0},
                {"from": "c", "to": "b", "type": "continue"},
            ],
        });
        let (trigger, steps) = shape(&flow);
        assert_eq!(trigger.as_deref(), Some("When “signup” fires"));
        let names: Vec<_> = steps
            .iter()
            .map(|s| (s.name.as_str(), s.depth, s.branch.as_deref()))
            .collect();
        assert_eq!(
            names,
            [
                ("When “signup” fires", 0, None),
                ("Wait 2 days", 0, None),
                ("Activated?", 0, None),
                ("Nudge", 1, Some("Has a dashboard")),
                ("Post to Slack", 1, Some("Otherwise")),
            ]
        );
        assert_eq!(
            steps[2].detail.as_deref(),
            Some("Split into 2 paths by condition")
        );
    }

    #[test]
    fn metric_series_sum_into_successes_and_failures() {
        let v = json!({"series": [{"name": "success", "values": [2, 3]}, {"name": "failure", "values": [0, 1]}, {"name": "billing", "values": [9]}]});
        assert_eq!(
            series_counts(&v),
            meep_wire::StepCounts {
                succeeded: 5,
                failed: 1
            }
        );
    }
}
