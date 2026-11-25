use anyhow::Result;
use chrono::Utc;
use meep_connectors::StoreState;
use meep_engine::{DirBlobs, SqliteStore};
use meep_server::{Connectors, DeviceTokens, FileSecrets, Server};
use meep_topic::{Command, Envelope, TopicId};
use meep_wire::{CommandBatch, CommandResults};
use reqwest::{Client, Method, RequestBuilder};
use std::{sync::Arc, time::Duration};
use tempfile::TempDir;
use tokio::{net::TcpListener, task::JoinHandle};
use tokio_util::sync::CancellationToken;
use uuid::Uuid;

pub struct Host {
    pub server: Server,
    pub client: Client,
    pub origin: String,
    pub token: String,
    pub dir: TempDir,
    stop: CancellationToken,
    task: JoinHandle<Result<()>>,
}
impl Host {
    pub async fn new() -> Result<Self> {
        Self::open(tempfile::tempdir()?).await
    }
    pub async fn open(dir: TempDir) -> Result<Self> {
        Self::open_with_base(dir, None).await
    }
    /// Open a host whose run-scoped MCP endpoints advertise `base`.
    pub async fn open_with_base(dir: TempDir, base: Option<&str>) -> Result<Self> {
        let auth = DeviceTokens::open(dir.path())?;
        let token = std::fs::read_to_string(dir.path().join("device-token"))?;
        let server = Server::with_storage(
            Arc::new(SqliteStore::open(dir.path())?),
            Arc::new(DirBlobs::open(dir.path().join("files"))?),
            Arc::new(StoreState::new(meep_store::Connection::open(
                dir.path().join("checkpoints.sqlite"),
            )?)?),
            Box::new(FileSecrets::open(dir.path().join("secrets"))?),
            Arc::new(auth),
            Arc::new(Connectors),
        )
        .await?;
        let server = server.with_settings_dir(dir.path())?;
        let server = match base {
            Some(base) => server.with_public_base(base)?,
            None => server,
        };
        let listener = TcpListener::bind("127.0.0.1:0").await?;
        let origin = format!("http://{}", listener.local_addr()?);
        let stop = CancellationToken::new();
        let task = tokio::spawn(
            server
                .clone()
                .serve(listener, stop.clone().cancelled_owned()),
        );
        Ok(Self {
            server,
            client: Client::builder().timeout(Duration::from_secs(30)).build()?,
            token,
            origin,
            dir,
            stop,
            task,
        })
    }
    pub fn request(&self, m: Method, path: &str) -> RequestBuilder {
        self.client
            .request(m, format!("{}/v1/{path}", self.origin))
            .bearer_auth(&self.token)
    }
    pub async fn commands(&self, commands: Vec<Envelope>) -> Result<CommandResults> {
        Ok(self
            .request(Method::POST, "commands")
            .json(&CommandBatch { commands })
            .send()
            .await?
            .error_for_status()?
            .json()
            .await?)
    }
    pub async fn close(self) -> Result<TempDir> {
        self.stop.cancel();
        tokio::time::timeout(Duration::from_secs(5), self.task).await???;
        Ok(self.dir)
    }
}
pub fn envelope(topic: TopicId, command: Command) -> Envelope {
    Envelope {
        id: Uuid::new_v4().into(),
        topic,
        issued_at: Utc::now(),
        command,
    }
}
pub fn create(topic: TopicId) -> Envelope {
    envelope(
        topic,
        Command::CreateTopic {
            name: "Adoption".into(),
            mission: "Track releases".into(),
        },
    )
}
