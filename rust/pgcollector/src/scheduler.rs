//! Drives every (collector, target) pair on its own wall-clock-aligned tick.
//!
//! Per server:
//! * a discovery loop re-lists databases every `rediscover_interval` and starts/stops
//!   database-scoped tick loops as databases appear and disappear;
//! * cluster-scoped collectors run against the writer and each `[servers.instances]`;
//! * heavy collectors (interval > 15s) are serialised per server via a semaphore, and
//!   every tick loop owns its own connection so a slow `sizes` never delays sampling.

use crate::collector::{CollectCtx, Collector, Scope, State, Target};
use crate::collectors::Registry;
use crate::config::{Config, ServerConfig};
use crate::http::{Readiness, METRICS};
use crate::pg;
use crate::sink::{Run, Sink};
use anyhow::Result;
use chrono::Utc;
use std::collections::{BTreeSet, HashMap};
use std::sync::Arc;
use std::time::{Duration, Instant};
use tokio::sync::Semaphore;
use tokio::task::JoinHandle;

pub const WRITER: &str = "writer";

pub async fn run(
    cfg: Arc<Config>,
    registry: Arc<Registry>,
    sink: Arc<dyn Sink>,
    ready: Readiness,
    once: bool,
) -> Result<()> {
    let mut handles = Vec::new();
    for server in &cfg.servers {
        let (cfg, registry, sink, server, ready) = (
            cfg.clone(),
            registry.clone(),
            sink.clone(),
            server.clone(),
            ready.clone(),
        );
        handles.push(tokio::spawn(async move {
            if let Err(e) = run_server(cfg, registry, sink, server.clone(), ready, once).await {
                tracing::error!(server = server.id, error = %format!("{e:#}"), "server loop exited");
            }
        }));
    }
    if !once {
        let sink = sink.clone();
        handles.push(tokio::spawn(async move {
            let mut t = tokio::time::interval(Duration::from_secs(3600));
            loop {
                t.tick().await;
                if let Err(e) = sink.maintain().await {
                    tracing::warn!(error = %format!("{e:#}"), "sink maintenance failed");
                }
            }
        }));
    }
    futures::future::join_all(handles).await;
    Ok(())
}

/// One endpoint we can open connections to.
#[derive(Clone)]
struct Endpoint {
    instance: String,
    url: String,
}

async fn run_server(
    cfg: Arc<Config>,
    registry: Arc<Registry>,
    sink: Arc<dyn Sink>,
    server: ServerConfig,
    ready: Readiness,
    once: bool,
) -> Result<()> {
    let timeout = cfg.defaults.statement_timeout;
    let heavy = Arc::new(Semaphore::new(1));
    let server = Arc::new(server);

    let probe = pg::connect(&server.url, timeout, None).await?;
    let version = pg::server_version(&probe).await?;
    let wanted = cfg.databases_for(&server);
    let discover = matches!(wanted.as_slice(), [w] if w == "*");
    tracing::info!(
        server = server.id,
        version,
        discover,
        instances = server.instances.len(),
        "server ready"
    );
    ready.set(true);
    {
        let caps = pg::capabilities(&probe).await.unwrap_or_default();
        let sysid: Option<i64> = probe
            .query_one("SELECT system_identifier FROM pg_control_system()", &[])
            .await
            .ok()
            .map(|r| r.get(0));
        let version_str: String = probe
            .query_one("SELECT version()", &[])
            .await
            .map(|r| r.get(0))
            .unwrap_or_default();
        let databases = if discover {
            pg::discover_databases(&probe).await.unwrap_or_default()
        } else {
            wanted.clone()
        };
        let mut instances = vec![WRITER.to_string()];
        instances.extend(server.instances.keys().cloned());
        let info = crate::sink::ServerInfo {
            server_id: server.id.clone(),
            system_identifier: sysid,
            version_num: version as i32,
            version: version_str,
            aurora_version: caps.aurora_version,
            instances,
            databases,
        };
        if let Err(e) = sink.register_server(&info).await {
            tracing::warn!(error = %format!("{e:#}"), "register_server failed");
        }
    }
    drop(probe);

    let writer = Endpoint {
        instance: WRITER.into(),
        url: server.url.clone(),
    };
    let mut cluster_endpoints = vec![writer.clone()];
    cluster_endpoints.extend(server.instances.iter().map(|(n, u)| Endpoint {
        instance: n.clone(),
        url: u.clone(),
    }));

    // Cluster-scoped loops: fixed for the life of the process.
    let mut fixed: Vec<JoinHandle<()>> = Vec::new();
    for collector in registry.iter() {
        let eff = cfg.effective(&server, collector.name(), collector.default_enabled());
        if !eff.enabled
            || collector.min_pg_version() > version
            || collector.scope() != Scope::Cluster
        {
            continue;
        }
        let interval = eff.interval.unwrap_or(collector.interval());
        let endpoints: Vec<Endpoint> = if collector.per_instance() {
            cluster_endpoints.clone()
        } else {
            vec![writer.clone()]
        };
        for ep in endpoints {
            let target = Target {
                server_id: server.id.clone(),
                instance: ep.instance.clone(),
                datname: None,
            };
            fixed.push(spawn_loop(
                collector.clone(),
                target,
                ep.url,
                interval,
                version,
                timeout,
                sink.clone(),
                heavy.clone(),
                server.clone(),
                once,
            ));
        }
    }

    // Database-scoped loops: follow discovery.
    let mut running: HashMap<String, Vec<JoinHandle<()>>> = HashMap::new();
    loop {
        let current: BTreeSet<String> = if discover {
            match pg::connect(&server.url, timeout, None).await {
                Ok(c) => match pg::discover_databases(&c).await {
                    Ok(dbs) => dbs.into_iter().collect(),
                    Err(e) => {
                        tracing::warn!(server = server.id, error = %e, "database discovery failed");
                        running.keys().cloned().collect()
                    }
                },
                Err(e) => {
                    tracing::warn!(server = server.id, error = %e, "discovery connect failed");
                    running.keys().cloned().collect()
                }
            }
        } else {
            wanted.iter().cloned().collect()
        };

        for gone in running
            .keys()
            .filter(|d| !current.contains(*d))
            .cloned()
            .collect::<Vec<_>>()
        {
            tracing::info!(
                server = server.id,
                database = gone,
                "database gone; stopping collectors"
            );
            for h in running.remove(&gone).unwrap() {
                h.abort();
            }
        }
        let new_dbs: Vec<String> = current
            .iter()
            .filter(|d| !running.contains_key(*d))
            .cloned()
            .collect();
        for db in &new_dbs {
            tracing::info!(
                server = server.id,
                database = db,
                "database found; starting collectors"
            );
            let mut hs = Vec::new();
            for collector in registry.iter() {
                let eff = cfg.effective(&server, collector.name(), collector.default_enabled());
                if !eff.enabled
                    || collector.min_pg_version() > version
                    || collector.scope() != Scope::Database
                {
                    continue;
                }
                let interval = eff.interval.unwrap_or(collector.interval());
                let endpoints: Vec<Endpoint> = if collector.per_instance() {
                    cluster_endpoints.clone()
                } else if collector.prefers_reader() && server.reader_url.is_some() {
                    // Reader-preferring database collectors (sizes, schema) read data that is
                    // identical across the cluster (shared storage / catalog); the reader is
                    // only used to shed load, so the rows are still labelled as the writer's.
                    vec![Endpoint {
                        instance: WRITER.into(),
                        url: server.reader_url.clone().unwrap(),
                    }]
                } else {
                    vec![writer.clone()]
                };
                for ep in endpoints {
                    let target = Target {
                        server_id: server.id.clone(),
                        instance: ep.instance.clone(),
                        datname: Some(db.clone()),
                    };
                    hs.push(spawn_loop(
                        collector.clone(),
                        target,
                        ep.url,
                        interval,
                        version,
                        timeout,
                        sink.clone(),
                        heavy.clone(),
                        server.clone(),
                        once,
                    ));
                }
            }
            running.insert(db.clone(), hs);
        }
        METRICS
            .targets
            .with_label_values(&[&server.id])
            .set((fixed.len() + running.values().map(Vec::len).sum::<usize>()) as i64);

        if once {
            futures::future::join_all(fixed.drain(..)).await;
            futures::future::join_all(running.drain().flat_map(|(_, hs)| hs)).await;
            return Ok(());
        }
        tokio::time::sleep(cfg.defaults.rediscover_interval).await;
    }
}

#[allow(clippy::too_many_arguments)]
fn spawn_loop(
    collector: Arc<dyn Collector>,
    target: Target,
    url: String,
    interval: Duration,
    pg_version: u32,
    timeout: Duration,
    sink: Arc<dyn Sink>,
    heavy: Arc<Semaphore>,
    server: Arc<ServerConfig>,
    once: bool,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        tick_loop(
            collector, target, url, interval, pg_version, timeout, sink, heavy, server, once,
        )
        .await
    })
}

#[allow(clippy::too_many_arguments)]
async fn tick_loop(
    collector: Arc<dyn Collector>,
    target: Target,
    url: String,
    interval: Duration,
    pg_version: u32,
    timeout: Duration,
    sink: Arc<dyn Sink>,
    heavy: Arc<Semaphore>,
    server: Arc<ServerConfig>,
    once: bool,
) {
    let mut state: Option<State> = sink
        .load_state(collector.name(), &target)
        .await
        .ok()
        .flatten();
    let is_heavy = interval > Duration::from_secs(15);
    let mut client: Option<tokio_postgres::Client> = None;
    let mut caps = crate::collector::Capabilities::default();
    let mut first = true;
    let mut unmet_logged: Option<String> = None;
    let labels = [collector.name().to_string(), target.server_id.clone()];

    loop {
        // First tick runs right away; later ticks align to wall-clock boundaries so
        // every server samples at the same instant.
        if !once && !first {
            tokio::time::sleep(until_next_boundary(interval)).await;
        }
        first = false;
        let _permit = if is_heavy {
            Some(heavy.acquire().await.unwrap())
        } else {
            None
        };

        if client.as_ref().map(|c| c.is_closed()).unwrap_or(true) {
            match pg::connect(&url, timeout, target.datname.as_deref()).await {
                Ok(c) => {
                    match pg::capabilities(&c).await {
                        Ok(cp) => caps = cp,
                        Err(e) => {
                            tracing::warn!(collector = collector.name(), error = %format!("{e:#}"), "capability probe failed")
                        }
                    }
                    client = Some(c);
                }
                Err(e) => {
                    tracing::warn!(collector = collector.name(), server = target.server_id, instance = target.instance, error = %format!("{e:#}"), "connect failed");
                    METRICS
                        .errors
                        .with_label_values(&[&labels[0], &labels[1], "connect"])
                        .inc();
                    if once {
                        return;
                    }
                    continue;
                }
            }
        }

        // Prerequisites (Aurora, extensions). Re-probed every 10 minutes so a later
        // CREATE EXTENSION is picked up without a restart.
        if let Some(reason) = collector.requires().unmet(&caps) {
            if unmet_logged.as_deref() != Some(&reason) {
                tracing::info!(
                    collector = collector.name(),
                    server = target.server_id,
                    instance = target.instance,
                    database = target.datname.as_deref().unwrap_or("-"),
                    reason,
                    "skipping: prerequisite not met"
                );
                unmet_logged = Some(reason);
            }
            if once {
                return;
            }
            drop(_permit);
            tokio::time::sleep(Duration::from_secs(600)).await;
            if let Some(c) = &client {
                if let Ok(cp) = pg::capabilities(c).await {
                    caps = cp;
                }
            }
            continue;
        }
        unmet_logged = None;

        let started = Instant::now();
        let now = Utc::now();
        let cx = CollectCtx {
            target: target.clone(),
            server: &server,
            conn: client.as_ref().unwrap(),
            pg_version,
            caps: &caps,
            now,
        };
        let result = collector.collect(&cx, state.as_ref()).await;

        let mut run = Run {
            collector: collector.name().to_string(),
            target: target.clone(),
            started_at: now,
            duration_ms: started.elapsed().as_millis() as i64,
            rows: 0,
            error: None,
        };
        METRICS
            .tick_seconds
            .with_label_values(&[&labels[0], &labels[1]])
            .observe(started.elapsed().as_secs_f64());
        match result {
            Ok((snap, next)) => {
                run.rows = snap.rows.len() as i64;
                METRICS
                    .rows
                    .with_label_values(&[&labels[0], &labels[1]])
                    .inc_by(run.rows as u64);
                if let Err(e) = sink.write(&snap).await {
                    tracing::warn!(collector = collector.name(), error = %format!("{e:#}"), "sink write failed");
                    METRICS
                        .errors
                        .with_label_values(&[&labels[0], &labels[1], "sink"])
                        .inc();
                    run.error = Some(format!("sink: {e:#}"));
                } else {
                    state = Some(next);
                }
            }
            Err(e) => {
                tracing::warn!(collector = collector.name(), server = target.server_id, instance = target.instance, error = %format!("{e:#}"), "collect failed");
                METRICS
                    .errors
                    .with_label_values(&[&labels[0], &labels[1], "collect"])
                    .inc();
                run.error = Some(format!("{e:#}"));
            }
        }
        if let Err(e) = sink.record_run(&run).await {
            tracing::debug!(error = %e, "record_run failed");
        }
        if is_heavy
            || collector.kind() == crate::collector::Kind::Snapshot
            || collector.name() == "logs"
        {
            if let Some(s) = &state {
                if let Err(e) = sink.save_state(collector.name(), &target, s).await {
                    tracing::debug!(error = %e, "save_state failed");
                }
            }
        }
        if once {
            return;
        }
    }
}

/// Sleep until the next multiple of `interval` on the wall clock.
fn until_next_boundary(interval: Duration) -> Duration {
    let now = std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap();
    let i = interval.as_millis() as u64;
    let n = now.as_millis() as u64;
    Duration::from_millis(i - (n % i))
}
