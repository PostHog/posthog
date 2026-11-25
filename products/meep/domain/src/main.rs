//! Stateless adapter for the same transitions used by the offline desktop replica.
use chrono::{DateTime, Utc};
use meep_topic::{Envelope, TopicState};
use serde::Deserialize;
use serde_json::json;
use std::io;

#[derive(Deserialize)]
struct TopicRequest {
    envelope: Envelope,
    state: Option<TopicState>,
    now: DateTime<Utc>,
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let request: serde_json::Value = serde_json::from_reader(io::stdin().lock())?;
    let response = if request["operation"] == "file" {
        let mut state: TopicState = serde_json::from_value(request["state"].clone())?;
        let now = serde_json::from_value(request["now"].clone())?;
        let file = &request["envelope"];
        let path: String = serde_json::from_value(file["path"].clone())?;
        let current = serde_json::from_value(file["current"].clone())?;
        state.deleted_files.remove(&path);
        state.refresh_file_reviews(&path, current, now);
        if let Some(candidate) = file["candidate"].as_u64() {
            let thread = serde_json::from_value(file["id"].clone())?;
            let msg = meep_topic::Message {
                id: serde_json::from_value(file["id"].clone())?,
                author: "File sync".into(),
                text: format!("Conflicting revisions {current} and {candidate} of {path}"),
                at: now,
                producer: meep_topic::Producer::System,
                origin: None,
                external_id: None,
            };
            state.receive(msg, format!("file-review/{candidate}/{path}"), thread, now)?;
            state.sort(
                thread,
                meep_topic::Decision::Ask {
                    summary: format!("Choose the current revision of {path}"),
                    reason: "Both revisions are saved.".into(),
                    suggestions: [false, true]
                        .into_iter()
                        .map(|use_candidate| meep_topic::Suggestion::ChooseFileRevision {
                            path: path.clone(),
                            current,
                            candidate,
                            use_candidate,
                        })
                        .collect(),
                },
                now,
            )?;
        }
        json!({"state": state})
    } else if request["operation"] == "board" {
        let mut state: TopicState = serde_json::from_value(request["state"].clone())?;
        let action = &request["envelope"];
        let id = serde_json::from_value(action["id"].clone())?;
        let now = serde_json::from_value(request["now"].clone())?;
        let text = action["text"].as_str().unwrap_or_default().to_owned();
        let result = match action["stage"].as_str() {
            Some("start")
                if state
                    .tasks
                    .iter()
                    .any(|t| t.id == id && t.column == meep_topic::Column::Todo) =>
            {
                state.start(id, text, now)
            }
            Some("start") => state.progress(id, text, now),
            Some("done") => state.complete(id, text, now),
            _ => state.work_needs_attention(id, text, now),
        };
        match result {
            Ok(_) => json!({"state":state}),
            Err(error) => json!({"error":error.to_string()}),
        }
    } else if request["operation"] == "publish-view" {
        let mut view: meep_views::View = serde_json::from_value(request["state"].clone())?;
        let edit = &request["envelope"];
        let source: String = serde_json::from_value(edit["source"].clone())?;
        if source.len() > 512 * 1024 {
            json!({"error":"Source exceeds 512 KiB."})
        } else if let Err(error) = meep_script::script::validate(&source, &json!({})) {
            json!({"error":error})
        } else {
            let expected = serde_json::from_value(edit["expected"].clone())?;
            let now = serde_json::from_value(request["now"].clone())?;
            match view.publish(expected, source, now) {
                Ok(()) => json!({"state":view}),
                Err(error) => json!({"error":error.to_string()}),
            }
        }
    } else if request["operation"] == "topic-rows" {
        let state = serde_json::from_value(request["state"].clone())?;
        let tool = request["envelope"]["tool"].as_str().ok_or("missing tool")?;
        json!({"state":{"rows":meep_views::topic_rows(&state,tool)?}})
    } else if request["operation"] == "import-topic" {
        json!({"state": serde_json::from_value::<TopicState>(request["state"].clone())?})
    } else if request["operation"] == "import-view" {
        json!({"state": serde_json::from_value::<meep_views::View>(request["state"].clone())?})
    } else if request["operation"] == "view" {
        let mut state = serde_json::from_value(request["state"].clone())?;
        match serde_json::from_value::<meep_views::ViewEnvelope>(request["envelope"].clone()) {
            Ok(envelope) => match envelope.apply(&mut state) {
                Ok(()) => json!({"state": state}),
                Err(err) => json!({"error": err.to_string()}),
            },
            Err(err) => json!({"error": err.to_string()}),
        }
    } else {
        match serde_json::from_value::<TopicRequest>(request) {
            Ok(req) => {
                let result = match req.state {
                    Some(mut state) => state.apply_at(&req.envelope, req.now).map(|_| state),
                    None => req.envelope.create_at(req.now).map(|(state, _)| state),
                };
                match result {
                    Ok(state) => json!({"state": state}),
                    Err(err) => json!({"error": err.to_string()}),
                }
            }
            Err(err) => json!({"error": err.to_string()}),
        }
    };
    serde_json::to_writer(io::stdout().lock(), &response)?;
    Ok(())
}
