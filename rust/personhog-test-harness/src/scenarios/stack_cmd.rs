//! `stack`: bring up the isolated personhog stack the gate uses, print where
//! it listens and which topics it publishes to, then hold it until SIGTERM
//! or Ctrl-C and tear it down. For tests in other languages, the Node
//! service e2e tests among them, which need the real stack behind a fixture
//! they can spawn and stop, without re-implementing its orchestration.

use std::path::Path;
use std::time::Duration;

use anyhow::{bail, Context, Result};
use serde_json::json;
use sqlx::postgres::PgPool;
use tokio::signal::unix::{signal, Signal, SignalKind};

use crate::cli::StackArgs;
use crate::publish;
use crate::scenarios::gate::default_bin_dir;
use crate::seed;
use crate::stack::{MonitorConfig, PublishConfig, Stack, StackConfig};

/// Prefix of the one stdout line a parent process can wait for. The logs
/// share stdout, so the marker is what makes the JSON findable.
pub const READY_MARKER: &str = "PERSONHOG_STACK_READY ";

/// A dead child must end the command instead of leaving a silent stack
/// behind a fixture that still looks up.
const LIVENESS_INTERVAL: Duration = Duration::from_secs(1);

pub async fn run(args: StackArgs) -> Result<()> {
    seed::validate_table_name(&args.pg_target_table)?;
    if args.publish && args.publishers == 0 {
        bail!("--publishers must be at least 1 with --publish");
    }
    if args.publish && args.publish_rows_per_pass <= 0 {
        bail!("--publish-rows-per-pass must be positive");
    }
    let monitor = match (
        args.monitor,
        &args.monitor_node_distinct_ids_topic,
        &args.monitor_node_merge_events_topic,
    ) {
        (false, _, _) => None,
        (true, _, _) if !args.publish => {
            bail!("--monitor needs --publish: the monitor compares the publish topics")
        }
        (true, Some(distinct_ids), Some(merge_events)) => Some(MonitorConfig {
            node_distinct_ids_topic: distinct_ids.clone(),
            node_merge_events_topic: merge_events.clone(),
        }),
        (true, _, _) => bail!(
            "--monitor needs --monitor-node-distinct-ids-topic and --monitor-node-merge-events-topic"
        ),
    };
    if let Some(path) = &args.ready_file {
        refuse_stale_ready_file(path)?;
    }
    if args.publish {
        // The publishers claim every team's rows, so a pending row from
        // anyone else would drain onto this run's topics and vanish with them.
        let outbox_table = seed::publish_outbox_table_for(&args.pg_target_table);
        let pool = PgPool::connect(&args.persons_db_url)
            .await
            .context("connecting to persons DB")?;
        let pending = publish::pending_outbox_rows(&pool, outbox_table, None).await?;
        pool.close().await;
        if pending > 0 {
            bail!(
                "{pending} pending outbox rows are already in {outbox_table} and the stack's \
                 publishers would drain them onto this run's topics; clear the table or use a \
                 dedicated persons database for --publish"
            );
        }
    }
    // Both registered before anything spawns: a SIGTERM or Ctrl-C during
    // bring-up then waits for the teardown below instead of killing the
    // harness outright, with the per-run topics left behind.
    let mut terminate =
        signal(SignalKind::terminate()).context("installing the SIGTERM handler")?;
    let mut interrupt = signal(SignalKind::interrupt()).context("installing the SIGINT handler")?;
    let bin_dir = args.bin_dir.clone().unwrap_or_else(default_bin_dir);
    let mut stack = Stack::up(StackConfig {
        bin_dir,
        leaders: args.leaders,
        routers: args.routers,
        partitions: args.partitions,
        kafka_hosts: args.kafka_hosts.clone(),
        etcd_endpoints: args.etcd_endpoints.clone(),
        persons_db_url: args.persons_db_url.clone(),
        writer_flush_interval_ms: 1000,
        pg_target_table: args.pg_target_table.clone(),
        cache_memory_capacity: 16_777_216,
        extra_leader_env: Vec::new(),
        extra_router_env: Vec::new(),
        recovery_pool_size: 16,
        leader_lease_ttl: 30,
        spawn_identity: true,
        publish: args.publish.then_some(PublishConfig {
            publishers: args.publishers,
            rows_per_pass: args.publish_rows_per_pass,
        }),
        monitor,
    })
    .await?;

    let topics = stack.publish_topics();
    // The Node clients take `host:port` and add the scheme themselves.
    let ready = json!({
        "router_addr": strip_scheme(&stack.router_url),
        "identity_addr": stack.identity_url.as_deref().map(strip_scheme),
        "pg_target_table": args.pg_target_table,
        // Every per-run topic, so a parent can clean up after a teardown
        // it had to cut short.
        "changelog_topic": stack.changelog_topic(),
        "distinct_ids_topic": topics.map(|t| t.distinct_ids.clone()),
        "merge_events_topic": topics.map(|t| t.merge_events.clone()),
        "monitor_addr": stack.monitor_url.as_deref().map(strip_scheme),
        "log_dir": stack.log_dir.display().to_string(),
    });
    println!("{READY_MARKER}{ready}");
    let announced = match &args.ready_file {
        Some(path) => write_ready_file(path, &ready.to_string()),
        None => Ok(()),
    };

    let held = match announced {
        Ok(()) => hold(&mut stack, &mut terminate, &mut interrupt).await,
        Err(e) => Err(e),
    };
    let down = stack.down().await;
    let cleared = match &args.ready_file {
        Some(path) => remove_ready_file(path),
        None => Ok(()),
    };
    held.and(down).and(cleared)
}

async fn hold(stack: &mut Stack, terminate: &mut Signal, interrupt: &mut Signal) -> Result<()> {
    let mut liveness = tokio::time::interval(LIVENESS_INTERVAL);
    loop {
        tokio::select! {
            _ = interrupt.recv() => return Ok(()),
            _ = terminate.recv() => return Ok(()),
            _ = liveness.tick() => stack.check_alive()?,
        }
    }
}

/// A file from an earlier run would satisfy a parent's existence check
/// before this stack is up, naming topics that run already deleted.
fn refuse_stale_ready_file(path: &Path) -> Result<()> {
    if path.exists() {
        bail!(
            "the ready file {} already exists; remove it, or pass a path no earlier run used",
            path.display()
        );
    }
    Ok(())
}

fn remove_ready_file(path: &Path) -> Result<()> {
    match std::fs::remove_file(path) {
        Ok(()) => Ok(()),
        Err(e) if e.kind() == std::io::ErrorKind::NotFound => Ok(()),
        Err(e) => Err(e).with_context(|| format!("removing the ready file {}", path.display())),
    }
}

/// Written whole or not at all: the reader treats the file's existence as
/// the ready signal, so it must never see a partial write.
fn write_ready_file(path: &Path, contents: &str) -> Result<()> {
    let tmp = path.with_extension("tmp");
    std::fs::write(&tmp, contents)
        .with_context(|| format!("writing the ready file {}", tmp.display()))?;
    std::fs::rename(&tmp, path)
        .with_context(|| format!("moving the ready file into place at {}", path.display()))
}

fn strip_scheme(url: &str) -> &str {
    url.split_once("://").map_or(url, |(_, rest)| rest)
}

#[cfg(test)]
mod tests {
    use super::{refuse_stale_ready_file, remove_ready_file, strip_scheme, write_ready_file};

    #[test]
    fn strip_scheme_leaves_host_and_port() {
        assert_eq!(strip_scheme("http://127.0.0.1:5000"), "127.0.0.1:5000");
        assert_eq!(strip_scheme("127.0.0.1:5000"), "127.0.0.1:5000");
    }

    #[test]
    fn a_ready_file_is_refused_while_it_exists_and_gone_after_the_run() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("ready.json");
        refuse_stale_ready_file(&path).expect("nothing written yet");
        write_ready_file(&path, "{}").unwrap();
        assert!(refuse_stale_ready_file(&path).is_err());
        remove_ready_file(&path).unwrap();
        assert!(!path.exists());
        remove_ready_file(&path).expect("a missing file is not an error");
    }
}
