use std::time::Duration;

use anyhow::Error;
use async_trait::async_trait;
use common_types::InternallyCapturedEvent;
use tokio::io::AsyncWriteExt;
use tracing::info;

pub mod capture;
pub mod kafka;

#[async_trait]
pub trait Emitter: Send + Sync {
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error>;
}

#[async_trait]
pub trait Transaction<'a>: Send + Sync {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error>;

    // Commits return a delay to wait before the next commit start
    async fn commit_write(self: Box<Self>) -> Result<Duration, Error> {
        Ok(Duration::from_secs(0))
    }
}

pub struct StdoutEmitter {
    pub as_json: bool,
}

#[async_trait]
impl Emitter for StdoutEmitter {
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error> {
        let to_store: &'a Self = self;
        Ok(Box::new(to_store))
    }
}

#[async_trait]
impl<'a> Transaction<'a> for &'a StdoutEmitter {
    async fn emit(&self, data: &[InternallyCapturedEvent]) -> Result<(), Error> {
        for event in data {
            if self.as_json {
                println!("{}", serde_json::to_string(&event)?);
            } else {
                println!("{event:?}");
            }
        }
        Ok(())
    }
}

pub struct NoOpEmitter;

#[async_trait]
impl Emitter for NoOpEmitter {
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error> {
        let to_store: &'a Self = self;
        Ok(Box::new(to_store))
    }
}

#[async_trait]
impl<'a> Transaction<'a> for &'a NoOpEmitter {
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
    async fn begin_write<'a>(&'a mut self) -> Result<Box<dyn Transaction<'a> + 'a>, Error> {
        let to_store: &'a Self = self;
        Ok(Box::new(to_store))
    }
}

#[async_trait]
impl<'a> Transaction<'a> for &'a FileEmitter {
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
                format!("{event:?}\n")
            };
            file.write_all(data.as_bytes()).await?;
        }
        Ok(())
    }
}

/// Why a sink refused a chunk, in the terms a user can act on.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SinkFailureReason {
    Quota,
    BadRequest,
    ServerError,
    RateLimited,
    Unauthorized,
    Transport,
    Serialization,
    Other,
}

impl SinkFailureReason {
    /// Bounded label for metrics. This is a contract read by dashboards and alerts.
    pub fn metric_label(self) -> &'static str {
        match self {
            Self::Quota => "quota",
            Self::BadRequest => "bad_request",
            Self::ServerError => "server_error",
            Self::RateLimited => "rate_limited",
            Self::Unauthorized => "unauthorized",
            Self::Transport => "transport",
            Self::Serialization => "serialization",
            Self::Other => "other",
        }
    }

    /// What the user sees on the paused job. `None` means the reason has no action the
    /// user can take, so the caller keeps its generic message.
    pub fn user_message(self) -> Option<&'static str> {
        match self {
            Self::Quota => Some(
                "Your organization is over a usage limit, so the events are being rejected. Raise the limit on the billing page, then resume this migration.",
            ),
            Self::RateLimited => Some(
                "Events are arriving faster than we can accept them. Wait a few minutes, then resume this migration.",
            ),
            Self::Unauthorized => Some(
                "We could not authenticate this migration with our own event API. Contact support, then resume this migration.",
            ),
            Self::BadRequest => Some(
                "A batch of events was rejected because we could not read it, or because it was too large. Check the source data, then resume this migration.",
            ),
            Self::ServerError | Self::Transport | Self::Serialization | Self::Other => None,
        }
    }
}

/// A sink refusal that carries its classification. The job layer downcasts to it to count
/// the pause under the reason the sink client saw.
#[derive(Debug, thiserror::Error)]
#[error("{message}")]
pub struct SinkFailure {
    pub reason: SinkFailureReason,
    pub message: String,
}
