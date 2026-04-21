use anyhow::{bail, Result};
use owo_colors::OwoColorize;
use std::time::Instant;

use crate::cli::ChaosKillArgs;

use super::etcd::EtcdState;
use super::k8s;

pub async fn run(args: ChaosKillArgs) -> Result<()> {
    let start = Instant::now();

    let pod_name = match &args.pod_name {
        Some(name) => name.clone(),
        None => {
            println!("Finding a running leader pod...");
            let pods = k8s::list_leader_pods(&args.namespace, &args.label).await?;
            let ready_pod = pods.iter().find(|p| p.ready);
            match ready_pod.or(pods.first()) {
                Some(p) => {
                    println!("  Selected pod: {}", p.name.bold());
                    p.name.clone()
                }
                None => bail!("no leader pods found with label {}", args.label),
            }
        }
    };

    if args.fast {
        println!("Revoking etcd lease for pod {}...", pod_name.bold());
        let etcd = EtcdState::connect(&args.etcd_endpoints, &args.etcd_prefix).await?;
        etcd.revoke_pod_lease(&pod_name).await?;
        println!(
            "  {} lease revoked — coordinator will detect immediately",
            "OK".green(),
        );
    }

    println!("Force-deleting pod {}...", pod_name.bold());
    k8s::force_delete_pod(&args.namespace, &pod_name).await?;
    println!(
        "  {} pod deleted in {:.1}ms",
        "OK".green(),
        start.elapsed().as_secs_f64() * 1000.0
    );

    Ok(())
}
