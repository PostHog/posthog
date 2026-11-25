//! The host selects a namespace for each caller and handles permission prompts in its UI.
use anyhow::{Result, ensure};
use async_trait::async_trait;
use std::time::Duration;

#[cfg(target_os = "macos")]
mod macos;
mod memory;
pub use memory::MemoryNotifications;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Authorization {
    NotDetermined,
    Authorized,
    Provisional,
    Denied,
    Unavailable,
}

#[derive(Clone, Debug, Default, PartialEq, Eq)]
pub struct Notification {
    pub title: String,
    pub body: String,
    pub sound: bool,
    /// A category the embedding application has registered with the OS.
    pub category: Option<String>,
    /// None delivers immediately. The OS owns the timer for delayed delivery.
    pub delay: Option<Duration>,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Namespace(String);

impl Namespace {
    pub fn new(name: impl Into<String>) -> Result<Self> {
        let name = name.into();
        ensure!(!name.is_empty(), "A notification namespace is required");
        Ok(Self(name))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }

    pub fn prefix(&self) -> String {
        format!("{}:{}:", self.0.len(), self.0)
    }

    pub fn key(&self, id: &str) -> Result<String> {
        ensure!(!id.is_empty(), "A notification ID is required");
        Ok(format!("{}{id}", self.prefix()))
    }
}

#[async_trait]
pub trait NotificationCenter: Send + Sync {
    /// Read-only. This must never display a permission prompt.
    async fn authorization(&self) -> Result<Authorization>;
    /// Call from a host UI action.
    async fn request_authorization(&self) -> Result<Authorization>;
    async fn submit(&self, key: &str, scope: &Namespace, notification: &Notification)
    -> Result<()>;
    async fn remove(&self, key: &str) -> Result<()>;
    async fn clear(&self, scope: &Namespace) -> Result<()>;
}

/// Hand this surface to a trusted tool adapter after resolving its caller's grant.
pub struct Publisher<'a> {
    center: &'a dyn NotificationCenter,
    scope: Namespace,
}

impl<'a> Publisher<'a> {
    pub fn new(center: &'a dyn NotificationCenter, scope: Namespace) -> Self {
        Self { center, scope }
    }

    pub async fn send(&self, id: &str, notification: &Notification) -> Result<()> {
        let key = self.scope.key(id)?;
        ensure!(
            !notification.title.trim().is_empty(),
            "A notification title is required"
        );
        ensure!(
            matches!(
                self.center.authorization().await?,
                Authorization::Authorized | Authorization::Provisional
            ),
            "System notifications are not authorized"
        );
        self.center.submit(&key, &self.scope, notification).await
    }

    pub async fn cancel(&self, id: &str) -> Result<()> {
        self.center.remove(&self.scope.key(id)?).await
    }

    pub async fn clear(&self) -> Result<()> {
        self.center.clear(&self.scope).await
    }
}

pub struct SystemNotifications;

#[cfg(not(target_os = "macos"))]
#[async_trait]
impl NotificationCenter for SystemNotifications {
    async fn authorization(&self) -> Result<Authorization> {
        Ok(Authorization::Unavailable)
    }
    async fn request_authorization(&self) -> Result<Authorization> {
        Ok(Authorization::Unavailable)
    }
    async fn submit(&self, _: &str, _: &Namespace, _: &Notification) -> Result<()> {
        anyhow::bail!("System notification delivery requires macOS")
    }
    async fn remove(&self, _: &str) -> Result<()> {
        anyhow::bail!("System notification delivery requires macOS")
    }
    async fn clear(&self, _: &Namespace) -> Result<()> {
        anyhow::bail!("System notification delivery requires macOS")
    }
}
