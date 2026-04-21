use anyhow::Result;
use owo_colors::OwoColorize;
use std::time::Duration;

use crate::cli::ChaosScaleUpArgs;

use super::etcd::EtcdState;
use super::k8s;

pub async fn run(args: ChaosScaleUpArgs) -> Result<()> {
    let current = k8s::get_statefulset_replicas(&args.namespace, &args.statefulset_name).await?;
    let target = args.replicas.unwrap_or(current + 1);

    println!(
        "Scaling {} from {} to {} replicas...",
        args.statefulset_name.bold(),
        current,
        target
    );

    k8s::scale_statefulset(&args.namespace, &args.statefulset_name, target).await?;
    println!("  {} scale command issued", "OK".green());

    if target > current {
        let new_pod = format!("{}-{}", args.statefulset_name, target - 1);
        println!("  Waiting for pod {} to become Ready...", new_pod);
        match k8s::wait_for_pod_ready(&args.namespace, &new_pod, 120).await {
            Ok(()) => println!("  {} pod {} is Ready", "OK".green(), new_pod),
            Err(e) => println!("  {} pod did not become Ready: {e}", "WARN".yellow()),
        }

        println!("  Waiting for pod to register in etcd...");
        let etcd = EtcdState::connect(&args.etcd_endpoints, &args.etcd_prefix).await?;
        match etcd.wait_for_pod(&new_pod, Duration::from_secs(60)).await {
            Ok(()) => println!(
                "  {} pod {} registered — coordinator will assign partitions",
                "OK".green(),
                new_pod
            ),
            Err(e) => println!("  {} pod did not register in etcd: {e}", "WARN".yellow()),
        }
    }

    Ok(())
}
