#![doc = include_str!("../README.md")]
#![deny(missing_docs)]

mod accounts;
mod address;
mod artifacts;
use address::AddressSettings;
mod account_refresh;
mod auth;
mod chat_models;
mod connector;
mod http;
mod mcp;
mod owners;
pub use owners::OwnerServices;
mod posthog;
mod queries;
mod replies;
mod scout_feed;
mod service_watch;
mod sources;
mod topic_context;
mod topic_mcp;
mod topic_work;
mod topic_workflows;
mod topic_workspace;
mod vault;
mod view_mcp;
mod views;
mod workers;

pub use auth::{Auth, DeviceTokens, FileSecrets};
pub use connector::{ConnectorFactory, Connectors};

use accounts::Accounts;
use anyhow::{Context, Result};
use chrono::{DateTime, Utc};
use meep_connections::SecretStore;
use meep_connectors::{StateStore, StoreState};
use meep_engine::{Blobs, Clock, DirBlobs, Engine, SqliteStore, Store, WorkflowSorter};
use meep_policy::Limits;
use std::{
    future::Future,
    path::{Path, PathBuf},
    sync::Arc,
};
use tokio::net::TcpListener;
use tokio_util::sync::CancellationToken;
use vault::Vault;

/// Resolve the platform's default server data directory.
pub fn data_dir() -> Result<PathBuf> {
    Ok(dirs::data_dir()
        .context("Could not locate the application data directory")?
        .join("Meep/server"))
}

struct ServiceClock;
impl Clock for ServiceClock {
    fn now(&self) -> DateTime<Utc> {
        Utc::now()
    }
    fn automatic(&self) -> bool {
        false
    }
}

/// A Topics service with replaceable persistence, account credentials and device authentication.
#[derive(Clone)]
pub struct Server {
    owner: meep_wire::OwnerId,
    factory: Option<Arc<dyn OwnerServices>>,
    base: Option<String>,
    views: Arc<views::Views>,
    provisioning: Arc<tokio::sync::Mutex<()>>,
    address_settings: Arc<parking_lot::Mutex<AddressSettings>>,
    engine: Arc<Engine>,
    accounts: Arc<Accounts>,
    auth: Arc<dyn Auth>,
}
impl Server {
    /// Open SQLite records and connector checkpoints, directory blobs and OS-specific credentials.
    pub async fn open(dir: impl AsRef<Path>) -> Result<Self> {
        let dir = dir.as_ref();
        let root = dir.to_owned();
        let auth = Arc::new(tokio::task::spawn_blocking(move || DeviceTokens::open(root)).await??);
        let factory = owners::Directories {
            root: dir.to_owned(),
            tokens: auth.clone(),
        };
        let server = Self::open_directory(dir, auth)
            .await?
            .with_owner_services(Arc::new(factory));
        if let Ok(base) = std::env::var("MEEP_PUBLIC_BASE_URL") {
            server.with_public_base(&base)
        } else {
            Ok(server)
        }
    }

    /// Supply the private storage factory for additional owners.
    pub fn with_owner_services(mut self, factory: Arc<dyn OwnerServices>) -> Self {
        self.factory = Some(factory);
        self.configure_endpoints();
        self
    }

    async fn open_directory(dir: &Path, auth: Arc<dyn Auth>) -> Result<Self> {
        let root = dir.to_owned();
        let (store, blobs, checkpoints, secrets) =
            tokio::task::spawn_blocking(move || -> Result<_> {
                let dir = &root;
                auth::private_dir(dir)?;
                #[cfg(target_os = "macos")]
                let secrets = {
                    use sha2::{Digest, Sha256};
                    Box::new(meep_connections::KeychainSecrets::new(format!(
                        "meep-server.{:x}",
                        Sha256::digest(dir.canonicalize()?.as_os_str().as_encoded_bytes())
                    )))
                };
                #[cfg(not(target_os = "macos"))]
                let secrets = Box::new(FileSecrets::open(dir.join("secrets"))?);
                let checkpoints = meep_store::Connection::open(dir.join("connectors.sqlite"))?;
                checkpoints.pragma_update(None, "journal_mode", "WAL")?;
                Ok((
                    Arc::new(SqliteStore::open(dir)?),
                    Arc::new(DirBlobs::open(dir.join("files"))?),
                    Arc::new(StoreState::new(checkpoints)?),
                    secrets,
                ))
            })
            .await??;
        let server = Self::with_storage(
            store,
            blobs,
            checkpoints,
            secrets,
            auth,
            Arc::new(Connectors),
        )
        .await?;
        let dir = dir.to_owned();
        tokio::task::spawn_blocking(move || server.with_settings_dir(&dir)).await?
    }
    /// Read and persist the host's callback address in settings.json in this directory.
    pub fn with_settings_dir(mut self, dir: &Path) -> Result<Self> {
        self.address_settings = Arc::new(parking_lot::Mutex::new(AddressSettings::open(dir)?));
        self.configure_endpoints();
        Ok(self)
    }
    /// Compose a service from host-supplied record, blob, checkpoint, secret and auth backends.
    pub async fn with_storage(
        store: Arc<dyn Store>,
        blobs: Arc<dyn Blobs>,
        checkpoints: Arc<dyn StateStore>,
        secrets: Box<dyn SecretStore + Send>,
        auth: Arc<dyn Auth>,
        factory: Arc<dyn ConnectorFactory>,
    ) -> Result<Self> {
        Self::with_sorter(
            store,
            blobs,
            checkpoints,
            secrets,
            auth,
            factory,
            Arc::new(WorkflowSorter),
        )
        .await
    }
    /// Compose a fixture host with scripted decisions for pre-workflow desktop snapshots.
    #[cfg(feature = "fixture-host")]
    pub async fn with_fixture_sorter(
        store: Arc<dyn Store>,
        blobs: Arc<dyn Blobs>,
        checkpoints: Arc<dyn StateStore>,
        secrets: Box<dyn SecretStore + Send>,
        auth: Arc<dyn Auth>,
        factory: Arc<dyn ConnectorFactory>,
        sorter: Arc<dyn meep_engine::Sorter>,
    ) -> Result<Self> {
        Self::with_sorter(store, blobs, checkpoints, secrets, auth, factory, sorter).await
    }

    async fn with_sorter(
        store: Arc<dyn Store>,
        blobs: Arc<dyn Blobs>,
        checkpoints: Arc<dyn StateStore>,
        secrets: Box<dyn SecretStore + Send>,
        auth: Arc<dyn Auth>,
        factory: Arc<dyn ConnectorFactory>,
        sorter: Arc<dyn meep_engine::Sorter>,
    ) -> Result<Self> {
        let view_store = store.clone();
        let views =
            Arc::new(tokio::task::spawn_blocking(move || views::Views::open(view_store)).await??);
        let accounts = Arc::new_cyclic(|weak| {
            Accounts::new(
                weak.clone(),
                store.clone(),
                Vault(secrets),
                factory,
                checkpoints,
            )
        });
        let engine = Engine::with_backends(
            store,
            blobs,
            vec![accounts.clone()],
            Limits {
                max_hops: 4,
                max_runs_per_hour: 60,
            },
            accounts.clone(),
            sorter,
            Arc::new(ServiceClock),
        )
        .await?;
        // Topic runs carry the meep-topic MCP, so a new topic opens its setup conversation.
        engine.enable_topic_setup();
        let engine = Arc::new(engine);
        accounts
            .engine
            .set(Arc::downgrade(&engine))
            .map_err(|_| anyhow::anyhow!("Engine already attached"))?;
        let restore = accounts.clone();
        let target = engine.clone();
        tokio::task::spawn_blocking(move || restore.restore(&target)).await??;
        let server = Self {
            owner: auth.implicit_owner(),
            factory: None,
            base: None,
            views,
            provisioning: Default::default(),
            address_settings: Default::default(),
            engine,
            accounts,
            auth,
        };
        server.resume_reply().await?;
        Ok(server)
    }
    /// Create new topics without their setup conversation, for hosts that configure topics
    /// themselves.
    pub fn without_topic_setup(self) -> Self {
        self.engine.set_topic_setup(false);
        self
    }
    /// Access the in-process engine, including trusted routine provisioning.
    pub fn engine(&self) -> &Engine {
        &self.engine
    }
    /// Serve requests and drive all workers until shutdown, closing active event streams.
    pub async fn serve(
        self,
        listener: TcpListener,
        shutdown: impl Future<Output = ()> + Send + 'static,
    ) -> Result<()> {
        let stop = CancellationToken::new();
        let guard = stop.clone().drop_guard();
        let host = owners::Host::start(self, stop.clone()).await?;
        let app = http::router(host.clone());
        let signal = stop.clone();
        let served = axum::serve(listener, app)
            .with_graceful_shutdown(async move {
                shutdown.await;
                signal.cancel();
            })
            .await;
        drop(guard);
        host.shutdown().await;
        served?;
        Ok(())
    }
}
