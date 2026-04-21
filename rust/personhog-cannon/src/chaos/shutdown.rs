use anyhow::{bail, Result};
use owo_colors::OwoColorize;

use crate::cli::ChaosShutdownArgs;

use super::k8s;

pub async fn run(args: ChaosShutdownArgs) -> Result<()> {
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

    println!(
        "Gracefully deleting pod {} (drain + handoff)...",
        pod_name.bold()
    );
    k8s::delete_pod(&args.namespace, &pod_name).await?;
    println!(
        "  {} delete issued — pod will drain partitions before terminating",
        "OK".green()
    );

    Ok(())
}
