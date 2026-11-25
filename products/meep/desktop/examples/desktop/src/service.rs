//! Example-only source adapters. Each script receives a host for its own source.
//! Local data sources run offline. PostHog examples share an isolated loopback project.
use crate::fixture::{self, Endpoint};
use anyhow::{Context as _, Result, bail, ensure};
use meep_posthog::mcp::{Gateway, Installation};
use meep_posthog::tasks::Tasks;
use meep_posthog::workflows::{BoundWorkflow, Invocation};
use meep_workflows::catalog::ManualCatalog;

use meep_render::sdk::{HostError, ViewHost};
use meep_store::Connection;
use serde_json::{Value, json};
use std::sync::{Arc, Mutex};
use tokio::sync::OnceCell;
use uuid::Uuid;

#[derive(Clone, Copy, clap::ValueEnum)]
pub enum WorkflowBackend {
    Local,
    PosthogFixture,
}

#[derive(Clone, Copy)]
pub enum Source {
    StateOnly,
    Tasks,
    Tools,
    Storage,
    Workflows,
}

#[derive(Default)]
struct LocalProject(OnceCell<Clients>);
struct Clients {
    endpoint: Endpoint,
    tasks: Tasks,
    tools: Gateway,
    workflow: BoundWorkflow,
}
impl LocalProject {
    async fn clients(&self) -> Result<&Clients> {
        self.0
            .get_or_try_init(|| async {
                let endpoint = fixture::start().await?;
                let tasks = Tasks::new(&endpoint.origin, 1)?;
                let tools = Gateway::new(&endpoint.origin, 1)?;
                let workflow = BoundWorkflow::new(&endpoint.origin, 1, fixture::FLOW)?;
                Ok(Clients {
                    workflow,
                    endpoint,
                    tasks,
                    tools,
                })
            })
            .await
    }
}

pub struct Services {
    pub db: Arc<Mutex<Connection>>,
    workflow_backend: WorkflowBackend,
    workflow_definition: Arc<Value>,
    project: Arc<LocalProject>,
}
impl Services {
    pub fn new(db: Connection, workflow_backend: WorkflowBackend) -> Self {
        Self {
            db: Arc::new(Mutex::new(db)),
            workflow_backend,
            workflow_definition: Arc::new(
                serde_json::from_str(include_str!("../views/run-history.json"))
                    .expect("bundled workflow JSON"),
            ),
            project: Arc::default(),
        }
    }
    pub fn install_workflow(&mut self, raw: Value) -> Result<()> {
        let flow = meep_workflows::Workflow::parse(raw)?;
        ensure!(
            flow.version == 2 && matches!(flow.trigger, meep_workflows::Trigger::Manual),
            "The gallery accepts manual version 2 workflows"
        );
        self.workflow_definition = Arc::new(json!(flow));
        Ok(())
    }
    pub fn for_view(&self, source: Source) -> Arc<dyn ViewHost> {
        Arc::new(match source {
            Source::StateOnly => Host::StateOnly,
            Source::Storage => Host::Notes(self.db.clone()),
            Source::Tasks => Host::Tasks(self.project.clone()),
            Source::Tools => Host::Tools(self.project.clone()),
            Source::Workflows => Host::Workflow {
                catalog: Mutex::default(),
                definition: self.workflow_definition.clone(),
                backend: self.workflow_backend,
                project: self.project.clone(),
            },
        })
    }
}
enum Host {
    StateOnly,
    Notes(Arc<Mutex<Connection>>),
    Tasks(Arc<LocalProject>),
    Tools(Arc<LocalProject>),
    Workflow {
        catalog: Mutex<ManualCatalog>,
        definition: Arc<Value>,
        backend: WorkflowBackend,
        project: Arc<LocalProject>,
    },
}
#[async_trait::async_trait]
impl ViewHost for Host {
    async fn request(&self, method: &str, params: Value) -> Result<Value, HostError> {
        self.effect(method, &params)
            .await
            .map_err(|error| HostError::from(error.to_string()))
    }
}
impl Host {
    async fn effect(&self, method: &str, params: &Value) -> Result<Value> {
        // Script drafts last for this window. Notes and preferences have explicit saves.
        if method == "views.state" {
            return Ok(Value::Null);
        }
        if let Host::Workflow { catalog, .. } = self
            && let Some(op) = method.strip_prefix("native.workflows.")
        {
            return catalog
                .lock()
                .map_err(|_| anyhow::anyhow!("Workflow catalog unavailable"))?
                .request(op, params);
        }
        ensure!(method == "sources.call", "Unknown host method {method}");
        let source = params["source"].as_str().unwrap_or_default();
        let operation = params["tool"].as_str().unwrap_or_default();
        let args = &params["arguments"];
        match (self, source) {
            (Host::Workflow { definition, .. }, "recipes") if operation == "initial" => {
                Ok((**definition).clone())
            }
            (Host::Notes(db), "notes") => notes(db, operation, args),
            (Host::Tasks(project), "tasks") => {
                tasks(project.clients().await?, operation, args).await
            }
            (Host::Tools(project), "tools") => {
                tools(project.clients().await?, operation, args).await
            }
            (
                Host::Workflow {
                    backend, project, ..
                },
                "activity",
            ) if operation == "recent" => {
                let runs: Vec<Invocation> = match backend {
                    WorkflowBackend::Local => fixture::recent_runs(),
                    WorkflowBackend::PosthogFixture => {
                        let clients = project.clients().await?;
                        clients.workflow.recent(&clients.endpoint.token, 50).await?
                    }
                };
                Ok(runs.into_iter().map(|r| json!({"id":r.invocation_id,"status":r.status,"durationMs":r.duration_ms})).collect())
            }
            _ => bail!("Operation unavailable for this example"),
        }
    }
}

fn notes(store: &Mutex<Connection>, operation: &str, args: &Value) -> Result<Value> {
    let db = store
        .lock()
        .map_err(|_| anyhow::anyhow!("Record store unavailable"))?;
    match operation {
        "save" => {
            let text = args["text"].as_str().unwrap_or_default().trim();
            ensure!(!text.is_empty(), "Enter a note.");
            meep_store::put(&db, "notes", &Uuid::new_v4().to_string(), text)?;
        }
        "remove" => {
            let id = args["id"].as_str().context("Missing note ID")?;
            meep_store::remove(&db, "notes", id)?;
        }
        "list" => {}
        _ => bail!("Unknown notes operation"),
    }
    let rows = meep_store::list::<String>(&db, "notes")?;
    Ok(Value::Array(
        rows.into_iter()
            .map(|(id, text)| json!({"id":id,"text":text}))
            .collect(),
    ))
}
async fn tasks(clients: &Clients, operation: &str, args: &Value) -> Result<Value> {
    let api = &clients.tasks;
    let token = &clients.endpoint.token;
    let text = args["text"].as_str().unwrap_or_default();
    match operation {
        "create" => {
            let task = api.create(token, text).await?;
            Ok(json!({"id":task.id,"title":task.title}))
        }
        "reply" => {
            let id = serde_json::from_value(args["id"].clone())?;
            let message = api.comment(token, id, text).await?;
            Ok(json!({"id":message.id,"content":message.content}))
        }
        "thread" => {
            let id = serde_json::from_value(args["id"].clone())?;
            let thread = api.thread(token, id).await?;
            Ok(json!(
                thread.into_iter().map(|m| m.content).collect::<Vec<_>>()
            ))
        }
        _ => bail!("Unknown task operation"),
    }
}
async fn tools(clients: &Clients, operation: &str, args: &Value) -> Result<Value> {
    let gateway = &clients.tools;
    let token = &clients.endpoint.token;
    match operation {
        "connect" => match gateway
            .install_personal_template(token, fixture::TEMPLATE, None)
            .await?
        {
            Installation::Installed { id } => Ok(json!(id)),
            Installation::Authorize { .. } => bail!("This template needs browser authorization."),
        },
        "discover" => {
            let mut connections = Vec::new();
            for server in gateway.available(token).await? {
                let tools:Vec<_>=server.tools.into_iter().map(|tool|json!({
                    "name":tool.name,"description":tool.description,"approval":tool.approval_state,
                })).collect();
                connections
                    .push(json!({"id":server.installation_id,"name":server.name,"tools":tools}));
            }
            Ok(Value::Array(connections))
        }
        "call" => {
            let id = serde_json::from_value(args["id"].clone())?;
            let name = args["name"].as_str().context("Missing tool name")?;
            let result = gateway.call(token, id, name, &Default::default()).await?;
            ensure!(!result.is_error, "The tool returned an error");
            Ok(result
                .structured_content
                .unwrap_or_else(|| json!(result.content)))
        }
        _ => bail!("Unknown tool operation"),
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    #[tokio::test]
    async fn only_the_assigned_source_can_run_and_offline_views_need_no_server() -> Result<()> {
        let db = Connection::open_in_memory()?;
        meep_store::initialize(&db)?;
        let services = Services::new(db, WorkflowBackend::Local);
        let notes = services.for_view(Source::Storage);
        let call = |source, tool, args| json!({"source":source,"tool":tool,"arguments":args});
        let rows = notes
            .request(
                "sources.call",
                call("notes", "save", json!({"text":"Local note"})),
            )
            .await?;
        assert_eq!(rows[0]["text"], "Local note");
        assert!(
            notes
                .request("sources.call", call("tools", "connect", Value::Null))
                .await
                .is_err()
        );
        assert!(services.project.0.get().is_none());
        Ok(())
    }
}

#[cfg(test)]
mod workflow_tests {
    use super::*;

    #[tokio::test]
    async fn a_bound_posthog_workflow_deduplicates_dispatch_and_reads_status_separately()
    -> Result<()> {
        let project = fixture::start().await?;
        let flow = BoundWorkflow::new(&project.origin, 1, fixture::FLOW)?;
        let key = Uuid::new_v4();
        let vars = serde_json::Map::from_iter([("name".into(), json!("Fieldwork"))]);
        let queued = flow.start(&project.token, key, &vars).await?;
        assert_eq!(queued.status, "queued");
        let replay = flow.start(&project.token, key, &vars).await?;
        assert_eq!(queued.invocation_id, replay.invocation_id);
        let seen = flow.status(&project.token, queued.invocation_id).await?;
        assert_eq!(seen.status, "running");
        assert_eq!(seen.invocation_id, queued.invocation_id);
        let rows = flow.recent(&project.token, 1).await?;
        assert_eq!(rows.len(), 1);
        assert_eq!(rows[0].invocation_id, seen.invocation_id);
        assert!(flow.recent("invalid", 5).await.is_err());
        assert!(flow.recent(&project.token, 501).await.is_err());
        assert!(
            BoundWorkflow::new(&project.origin, 1, Uuid::new_v4())?
                .recent(&project.token, 5)
                .await
                .is_err()
        );
        Ok(())
    }
}
