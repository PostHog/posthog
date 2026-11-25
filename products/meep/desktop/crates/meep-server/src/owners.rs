//! Routing and worker lifetime for the independent services on one listener.
use super::*;
use parking_lot::Mutex;
use std::{collections::BTreeMap, path::PathBuf};
use tokio::sync::OnceCell;
use tokio_util::task::TaskTracker;
use uuid::Uuid;

/// Creates isolated service backends for registered owners in a hosted deployment.
#[async_trait::async_trait]
pub trait OwnerServices: Send + Sync {
    /// Persisted owners, including those with work to resume before a device connects.
    fn owners(&self) -> Result<Vec<Uuid>>;
    /// Open the private stores for this owner. Called once per serving instance.
    async fn open(&self, owner: Uuid) -> Result<Server>;
}

pub(super) struct Directories {
    pub root: PathBuf,
    pub tokens: Arc<DeviceTokens>,
}

#[async_trait::async_trait]
impl OwnerServices for Directories {
    fn owners(&self) -> Result<Vec<Uuid>> {
        Ok(self.tokens.owners()?.into_keys().collect())
    }
    async fn open(&self, owner: Uuid) -> Result<Server> {
        let dir = self.root.join("owners").join(owner.to_string());
        Server::open_directory(&dir, self.tokens.clone()).await
    }
}

pub(super) struct Host {
    pub implicit: Server,
    pub stop: CancellationToken,
    others: Mutex<BTreeMap<Uuid, Arc<OnceCell<Server>>>>,
    workers: TaskTracker,
}
impl Host {
    pub async fn start(implicit: Server, stop: CancellationToken) -> Result<Arc<Self>> {
        let host = Arc::new(Self {
            implicit,
            stop,
            others: Mutex::new(BTreeMap::new()),
            workers: TaskTracker::new(),
        });
        if let Some(factory) = &host.implicit.factory {
            let factory = factory.clone();
            for id in tokio::task::spawn_blocking(move || factory.owners()).await?? {
                if id != host.implicit.owner {
                    host.open_owner(id).await?;
                }
            }
        }
        host.start_workers(&host.implicit);
        Ok(host)
    }

    fn start_workers(&self, service: &Server) {
        self.workers
            .spawn(workers::run(service.clone(), self.stop.clone()));
        self.workers
            .spawn(views::run(service.clone(), self.stop.clone()));
        self.workers
            .spawn(crate::scout_feed::run(service.clone(), self.stop.clone()));
    }

    pub async fn service(&self, id: Uuid) -> Result<Option<Server>> {
        if self.implicit.owner == id {
            return Ok(Some(self.implicit.clone()));
        }
        let Some(factory) = &self.implicit.factory else {
            return Ok(None);
        };
        if let Some(s) = self
            .others
            .lock()
            .get(&id)
            .and_then(|cell| cell.get())
            .cloned()
        {
            return Ok(Some(s));
        }
        let factory = factory.clone();
        if !tokio::task::spawn_blocking(move || factory.owners())
            .await??
            .contains(&id)
        {
            return Ok(None);
        }
        Ok(Some(self.open_owner(id).await?))
    }
    async fn open_owner(&self, id: Uuid) -> Result<Server> {
        let cell = self.others.lock().entry(id).or_default().clone();
        let factory = self
            .implicit
            .factory
            .as_ref()
            .context("Owner storage unavailable")?;
        let s = cell
            .get_or_try_init(|| async {
                let mut s = factory.open(id).await?;
                s.auth = self.implicit.auth.clone();
                s.owner = id;
                s.base.clone_from(&self.implicit.base);
                s.configure_endpoints();
                self.start_workers(&s);
                anyhow::Ok(s)
            })
            .await?;
        Ok(s.clone())
    }

    pub async fn shutdown(&self) {
        self.stop.cancel();
        self.workers.close();
        self.workers.wait().await;
        let services: Vec<_> = self
            .others
            .lock()
            .values()
            .filter_map(|c| c.get().cloned())
            .collect();
        for s in services.iter().chain([&self.implicit]) {
            s.engine.shutdown().await;
            s.accounts.jobs.close();
            s.accounts.jobs.wait().await;
        }
    }
}

#[cfg(test)]
mod tests;
