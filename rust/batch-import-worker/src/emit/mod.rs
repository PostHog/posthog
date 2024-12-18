use anyhow::Error;
use async_trait::async_trait;
use common_types::InternallyCapturedEvent;
use tokio::io::AsyncWriteExt;
use tracing::info;

#[async_trait]
pub trait Emitter {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error>;
}

pub struct StdoutEmitter {
    pub as_json: bool,
}

#[async_trait]
impl Emitter for StdoutEmitter {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        for event in data {
            if self.as_json {
                println!("{}", serde_json::to_string(&event)?);
            } else {
                println!("{:?}", event);
            }
        }
        Ok(())
    }
}

pub struct NoOpEmitter;

#[async_trait]
impl Emitter for NoOpEmitter {
    async fn emit(&self, _data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        Ok(())
    }
}

pub struct FileEmitter {
    pub path: String,
    pub as_json: bool,
}

impl FileEmitter {
    pub async fn new(path: String, as_json: bool, cleanup: bool) -> Result<Self, Error> {
        info!("Creating file emitter at {}", path);
        if cleanup {
            tokio::fs::remove_file(&path).await.ok();
        }
        Ok(Self { path, as_json })
    }
}

#[async_trait]
impl Emitter for FileEmitter {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        info!("Writing {} events to file {}", data.len(), self.path);
        let mut file = tokio::fs::OpenOptions::new()
            .create(true)
            .append(true)
            .open(&self.path)
            .await?;
        for event in data {
            let data = if self.as_json {
                format!("{}\n", serde_json::to_string(&event)?)
            } else {
                format!("{:?}\n", event)
            };
            file.write_all(data.as_bytes()).await?;
        }
        Ok(())
    }
}
