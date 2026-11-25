use crate::{Authorization, Namespace, Notification, NotificationCenter};
use anyhow::Result;
use async_trait::async_trait;
use std::{collections::BTreeMap, sync::Mutex};

/// In-memory delivery for examples and tests. Each submission replaces the same scoped ID.
pub struct MemoryNotifications {
    permission: Authorization,
    entries: Mutex<BTreeMap<String, Notification>>,
}
impl MemoryNotifications {
    pub fn new(permission: Authorization) -> Self {
        Self {
            permission,
            entries: Mutex::default(),
        }
    }
    pub fn entries(&self, scope: &Namespace) -> Vec<(String, Notification)> {
        let prefix = scope.prefix();
        self.entries
            .lock()
            .unwrap()
            .range(prefix.clone()..)
            .take_while(|(key, _)| key.starts_with(&prefix))
            .map(|(key, notice)| (key[prefix.len()..].to_owned(), notice.clone()))
            .collect()
    }
}
#[async_trait]
impl NotificationCenter for MemoryNotifications {
    async fn authorization(&self) -> Result<Authorization> {
        Ok(self.permission)
    }
    async fn request_authorization(&self) -> Result<Authorization> {
        anyhow::bail!("This fixture has no permission UI")
    }
    async fn submit(&self, key: &str, _: &Namespace, notice: &Notification) -> Result<()> {
        self.entries
            .lock()
            .unwrap()
            .insert(key.into(), notice.clone());
        Ok(())
    }
    async fn remove(&self, key: &str) -> Result<()> {
        self.entries.lock().unwrap().remove(key);
        Ok(())
    }
    async fn clear(&self, scope: &Namespace) -> Result<()> {
        let prefix = scope.prefix();
        self.entries
            .lock()
            .unwrap()
            .retain(|key, _| !key.starts_with(&prefix));
        Ok(())
    }
}
