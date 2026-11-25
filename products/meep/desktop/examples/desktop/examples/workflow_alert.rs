//! A host grants one notification tool to an agent-authored workflow.
use anyhow::{Context, Result, ensure};
use meep_notifications::{Authorization, MemoryNotifications, Namespace, Notification, Publisher};
use meep_workflows::{
    HostError, Workflow,
    runner::{self, Control, Host, LocalFuture},
};
use serde_json::{Value, json};

struct AlertHost<'a> {
    granted: Option<Publisher<'a>>,
}

impl AlertHost<'_> {
    async fn notify(&self, args: Value) -> Result<Value> {
        let publisher = self
            .granted
            .as_ref()
            .context("Notification grant required")?;
        let id = args["id"].as_str().context("Notification ID required")?;
        let title = args["title"]
            .as_str()
            .context("Notification title required")?;
        publisher
            .send(
                id,
                &Notification {
                    title: title.into(),
                    ..Default::default()
                },
            )
            .await?;
        Ok(json!({"id":id}))
    }
}

impl Host for AlertHost<'_> {
    fn state(&self) -> runner::Result<Value> {
        Ok(json!({}))
    }
    fn patch(&self, _: Value) -> runner::Result<()> {
        Err("State writes unavailable".into())
    }
    fn data(&self, _: &str, _: &str, _: Value) -> runner::Result<Value> {
        Err("Datasets unavailable".into())
    }
    fn transform(&self, _: &str, _: Value) -> runner::Result<Value> {
        Err("Custom transforms unavailable".into())
    }
    fn request(&self, method: &str, args: Value) -> LocalFuture<'_, Result<Value, HostError>> {
        if method != "native.notifications.send" {
            return Box::pin(async { Err("Unknown workflow effect".into()) });
        }
        Box::pin(async move {
            self.notify(args)
                .await
                .map_err(|e| HostError::from(e.to_string()))
        })
    }
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<()> {
    let workflow = Workflow::parse(json!({
        "version":2, "id":"report-ready", "title":"Report ready", "trigger":{"kind":"manual"},
        "steps":[{"id":"announce","kind":"notify","options":{"id":"report","title":{"$ref":"/input/title"}}}]
    }))?;
    let input = json!({"title":"Weekly report ready"});
    let denied = runner::run(
        &AlertHost { granted: None },
        &workflow,
        input.clone(),
        Control::default(),
    )
    .await;
    ensure!(
        denied
            .result
            .unwrap_err()
            .contains("Notification grant required")
    );
    let center = MemoryNotifications::new(Authorization::Authorized);
    let scope = Namespace::new("reports-agent")?;
    let host = AlertHost {
        granted: Some(Publisher::new(&center, scope.clone())),
    };
    runner::run(&host, &workflow, input, Control::default())
        .await
        .result
        .map_err(anyhow::Error::msg)?;
    let entries = center.entries(&scope);
    ensure!(
        entries.len() == 1
            && entries[0].0 == "report"
            && entries[0].1.title == "Weekly report ready"
    );
    println!("{}", entries[0].1.title);
    Ok(())
}
