use anyhow::Result;
use comfy_table::{presets::UTF8_FULL_CONDENSED, ContentArrangement, Table};
use owo_colors::OwoColorize;

use crate::cli::ChaosStatusArgs;

use super::etcd::EtcdState;

pub async fn run(args: ChaosStatusArgs) -> Result<()> {
    let etcd = EtcdState::connect(&args.etcd_endpoints, &args.etcd_prefix).await?;

    let pods = etcd.list_pods().await?;
    let assignments = etcd.list_assignments().await?;
    let handoffs = etcd.list_handoffs().await?;
    let routers = etcd.list_routers().await?;
    let total = etcd.get_total_partitions().await.unwrap_or(0);

    println!();
    println!("{}", "=== personhog coordination status ===".bold());
    println!(
        "  etcd: {}  prefix: {}",
        args.etcd_endpoints, args.etcd_prefix
    );
    println!("  Partitions: {total}");
    println!();

    // Pods
    if pods.is_empty() {
        println!("  Pods: {}", "(none)".yellow());
    } else {
        let mut table = Table::new();
        table
            .load_preset(UTF8_FULL_CONDENSED)
            .set_content_arrangement(ContentArrangement::Dynamic)
            .set_header(vec!["Pod", "Status", "Registered", "Last Heartbeat"]);

        let now = now_secs();
        for pod in &pods {
            let status = format!("{:?}", pod.status);
            let registered = format_age(now, pod.registered_at);
            let heartbeat = format_age(now, pod.last_heartbeat);
            table.add_row(vec![&pod.pod_name, &status, &registered, &heartbeat]);
        }
        println!("  Pods:");
        for line in table.to_string().lines() {
            println!("    {line}");
        }
    }
    println!();

    // Assignments
    if assignments.is_empty() {
        println!("  Assignments: {}", "(none)".yellow());
    } else {
        println!("  Assignments:");
        let mut sorted = assignments.clone();
        sorted.sort_by_key(|a| a.partition);
        for chunk in sorted.chunks(4) {
            let parts: Vec<String> = chunk
                .iter()
                .map(|a| format!("{}: {}", a.partition, a.owner))
                .collect();
            println!("    {}", parts.join("  "));
        }
    }
    println!();

    // Handoffs
    if handoffs.is_empty() {
        println!("  Handoffs: {}", "(none)".green());
    } else {
        println!("  Handoffs:");
        for h in &handoffs {
            println!(
                "    partition {}: {} -> {} ({:?})",
                h.partition, h.old_owner, h.new_owner, h.phase
            );
        }
    }
    println!();

    // Routers
    if routers.is_empty() {
        println!("  Routers: {}", "(none)".yellow());
    } else {
        let now = now_secs();
        let router_info: Vec<String> = routers
            .iter()
            .map(|r| {
                format!(
                    "{} (heartbeat {})",
                    r.router_name,
                    format_age(now, r.last_heartbeat)
                )
            })
            .collect();
        println!("  Routers: {}", router_info.join(", "));
    }
    println!();

    Ok(())
}

fn now_secs() -> i64 {
    std::time::SystemTime::now()
        .duration_since(std::time::UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs() as i64
}

fn format_age(now: i64, timestamp: i64) -> String {
    let age = (now - timestamp).max(0);
    if age < 60 {
        format!("{age}s ago")
    } else if age < 3600 {
        format!("{}m ago", age / 60)
    } else {
        format!("{}h ago", age / 3600)
    }
}
