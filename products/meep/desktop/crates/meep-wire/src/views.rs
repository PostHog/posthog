//! Workspace-wide script views and the commands projected by both replicas.
use anyhow::{Context, Result, ensure};
use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

/// A saved script generation. Restoring copies the source into a new generation.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Revision {
    /// Sequential generation starting at one.
    pub number: u64,
    /// Time of publication.
    pub at: DateTime<Utc>,
    /// Validated JavaScript.
    pub source: String,
}

/// Lifecycle of an authoring turn.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub enum Stage {
    /// Waiting for server dispatch.
    Queued,
    /// Dispatch was reserved before contacting Tasks.
    Starting,
    /// Confirmed run, with its most recent progress.
    Working(String),
    /// Final response or failure detail.
    Finished(String),
}
impl Stage {
    /// Whether another turn can follow this one.
    pub fn finished(&self) -> bool {
        matches!(self, Self::Finished(_))
    }
}

/// How a request runs: the PostHog Tasks model and effort, and files the person
/// attached. Files are uploaded to the view first and named here.
#[derive(Clone, Debug, Default, PartialEq, Serialize, Deserialize)]
pub struct TurnOptions {
    /// PostHog Tasks model ID; `None` uses the service default.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
    /// Reasoning effort the model advertises.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub effort: Option<String>,
    /// Names of files uploaded to this view for the request.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub files: Vec<String>,
}

/// One user request in a conversation.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct Turn {
    /// Command that created this turn.
    pub id: Uuid,
    /// Conversation identity shared by resumed turns.
    pub session: Uuid,
    /// Original request.
    pub prompt: String,
    /// Latest agent observation.
    pub stage: Stage,
    /// Assistant messages and tool activity decoded from the provider session.
    #[serde(default)]
    pub messages: Vec<meep_protocol::sessions::AgentMessage>,
    /// When the person submitted the prompt.
    pub at: DateTime<Utc>,
    /// Model, effort and files the request runs with.
    #[serde(default)]
    pub options: TurnOptions,
    /// The person asked to stop this turn; the server cancels its run.
    #[serde(default)]
    pub stop: bool,
}

/// Replicated view, independent of any topic.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct View {
    /// Stable workspace identity.
    pub id: Uuid,
    /// Sidebar label.
    pub title: String,
    /// Sidebar emoji.
    pub icon: String,
    /// Shell tile palette.
    pub color: String,
    /// Published source generations in ascending order.
    pub revisions: Vec<Revision>,
    /// Chronological authoring conversations.
    pub turns: Vec<Turn>,
    /// Tombstone preventing resurrection on replay.
    pub deleted: bool,
}
impl View {
    /// The next authoring turn, in command arrival order.
    pub fn pending(&self) -> Option<&Turn> {
        self.turns.iter().find(|t| !t.stage.finished())
    }
    /// Current source generation, or zero before the initial build.
    pub fn generation(&self) -> u64 {
        self.revisions.last().map_or(0, |r| r.number)
    }
    /// Publish source against the generation its editor actually read.
    pub fn publish(&mut self, expected: u64, source: String, at: DateTime<Utc>) -> Result<()> {
        ensure!(
            !self.deleted && self.generation() == expected,
            "View changed. Read its source again."
        );
        self.revisions.push(Revision {
            number: expected
                .checked_add(1)
                .context("The view has reached its revision limit")?,
            source,
            at,
        });
        Ok(())
    }
}

/// A device command. Publication is restricted to the authenticated agent endpoint.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ViewCommand {
    /// Create a view and start its first conversation.
    Create {
        /// First request.
        prompt: String,
        /// Model, effort and attached files.
        #[serde(default)]
        options: TurnOptions,
    },
    /// Start or continue a session.
    Ask {
        /// Session to continue, or a new UUID.
        session: Uuid,
        /// User request.
        prompt: String,
        /// Model, effort and attached files.
        #[serde(default)]
        options: TurnOptions,
    },
    /// Stop a queued or running turn.
    Stop {
        /// The turn to stop.
        turn: Uuid,
    },
    /// Update the name and tile together.
    Settings {
        /// Sidebar label.
        title: String,
        /// Emoji.
        icon: String,
        /// Tile color.
        color: String,
    },
    /// Restore an older checkpoint.
    Restore {
        /// Old generation to copy.
        number: u64,
        /// Generation displayed in settings.
        expected: u64,
    },
    /// Remove from the workspace and revoke authoring access.
    Delete,
}

/// Retryable outbox entry for a workspace view.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
pub struct ViewEnvelope {
    /// Stable command and turn identity.
    pub id: Uuid,
    /// Destination view.
    pub view: Uuid,
    /// Device time.
    pub at: DateTime<Utc>,
    /// Requested operation.
    pub command: ViewCommand,
}

impl ViewEnvelope {
    /// Apply a user edit atomically to a projected snapshot.
    pub fn apply(&self, state: &mut Option<View>) -> Result<()> {
        let turn = |session, prompt: &str, options: &TurnOptions| -> Result<Turn> {
            ensure!(
                !prompt.trim().is_empty() && prompt.len() <= 32000,
                "Enter a request of up to 32,000 bytes."
            );
            ensure!(
                options.files.len() <= 10
                    && options
                        .files
                        .iter()
                        .all(|f| !f.is_empty() && f.len() <= 255 && !f.contains(['/', '\\'])),
                "Attach up to 10 files with plain names."
            );
            Ok(Turn {
                id: self.id,
                session,
                prompt: prompt.trim().into(),
                at: self.at,
                stage: Stage::Queued,
                messages: Vec::new(),
                options: options.clone(),
                stop: false,
            })
        };
        if let ViewCommand::Create { prompt, options } = &self.command {
            ensure!(state.is_none(), "View already exists");
            *state = Some(View {
                id: self.view,
                title: "Untitled view".into(),
                icon: "✨".into(),
                color: "ink".into(),
                turns: vec![turn(self.id, prompt, options)?],
                revisions: vec![],
                deleted: false,
            });
            return Ok(());
        }
        let v = state
            .as_mut()
            .filter(|v| !v.deleted && v.id == self.view)
            .context("View no longer exists")?;
        match &self.command {
            ViewCommand::Create { .. } => unreachable!(),
            ViewCommand::Ask {
                session,
                prompt,
                options,
            } => {
                ensure!(
                    !v.turns.iter().any(|t| t.id == self.id),
                    "Turn already queued"
                );
                v.turns.push(turn(*session, prompt, options)?);
            }
            ViewCommand::Stop { turn } => {
                let t = v
                    .turns
                    .iter_mut()
                    .find(|t| t.id == *turn)
                    .context("Unknown turn")?;
                // A turn that never reached PostHog stops here; a running one is
                // cancelled by the server, which then finishes it.
                match t.stage {
                    Stage::Queued => t.stage = Stage::Finished("Stopped.".into()),
                    Stage::Finished(_) => {}
                    _ => t.stop = true,
                }
            }
            ViewCommand::Settings { title, icon, color } => {
                ensure!(
                    !title.trim().is_empty()
                        && title.len() <= 256
                        && !icon.trim().is_empty()
                        && icon.len() <= 64
                        && color.len() <= 32,
                    "Invalid view name or tile"
                );
                v.title = title.trim().into();
                v.icon = icon.clone();
                v.color = color.clone();
            }
            ViewCommand::Restore { number, expected } => {
                let r = v
                    .revisions
                    .iter()
                    .find(|r| r.number == *number)
                    .context("Unknown checkpoint")?;
                v.publish(*expected, r.source.clone(), self.at)?;
            }
            ViewCommand::Delete => v.deleted = true,
        }
        Ok(())
    }
}

/// Read a topic collection using the same script contract on server and replica.
pub fn topic_rows(state: &meep_topic::TopicState, tool: &str) -> Result<serde_json::Value> {
    Ok(match tool {
        "tasks" => state
            .tasks
            .iter()
            .map(|task| {
                let mut row = serde_json::to_value(task)?;
                // Existing generated views commonly render `status`; retain `column`
                // for board logic and give display code a human-readable value.
                row["status"] = serde_json::json!(match task.column {
                    meep_topic::Column::Todo => "To do",
                    meep_topic::Column::InProgress => "In progress",
                    meep_topic::Column::NeedsYou => "Needs you",
                    meep_topic::Column::Done => "Done",
                });
                Ok(row)
            })
            .collect::<Result<Vec<_>>>()?
            .into(),
        "threads" => serde_json::to_value(&state.threads)?,
        "facts" => serde_json::to_value(
            state
                .topic
                .facts
                .iter()
                .filter(|f| f.is_current())
                .collect::<Vec<_>>(),
        )?,
        _ => anyhow::bail!("Unknown topic collection"),
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use meep_topic::{Column, Command, Envelope, Topic, TopicState};

    #[test]
    fn task_view_rows_expose_board_column_and_readable_status() -> Result<()> {
        let now = Utc::now();
        let topic = Uuid::from_u128(1).into();
        let mut state = TopicState::new(Topic::new(topic, "Fixture", now));
        for (i, (column, status)) in [
            (Column::Todo, "To do"),
            (Column::InProgress, "In progress"),
            (Column::NeedsYou, "Needs you"),
            (Column::Done, "Done"),
        ]
        .into_iter()
        .enumerate()
        {
            state.apply(&Envelope {
                id: Uuid::from_u128(10 + i as u128).into(),
                topic,
                issued_at: now,
                command: Command::AddTask {
                    id: Uuid::from_u128(20 + i as u128).into(),
                    title: status.into(),
                },
            })?;
            state.tasks.last_mut().unwrap().column = column;
        }
        let rows = topic_rows(&state, "tasks")?;
        for (row, (column, status)) in rows.as_array().unwrap().iter().zip([
            ("Todo", "To do"),
            ("InProgress", "In progress"),
            ("NeedsYou", "Needs you"),
            ("Done", "Done"),
        ]) {
            assert_eq!(row["column"], column);
            assert_eq!(row["status"], status);
            assert_eq!(row["title"], status);
        }
        Ok(())
    }
}
