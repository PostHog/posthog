use anyhow::{bail, Context, Result};
use tokio::process::Command;

#[allow(dead_code)]
pub struct LeaderPod {
    pub name: String,
    pub ready: bool,
    pub status: String,
}

/// List personhog-leader pods in the current namespace.
pub async fn list_leader_pods(namespace: &str, label: &str) -> Result<Vec<LeaderPod>> {
    let output = Command::new("kubectl")
        .args([
            "get",
            "pods",
            "-n",
            namespace,
            "-l",
            label,
            "-o",
            "jsonpath={range .items[*]}{.metadata.name},{.status.phase},{.status.containerStatuses[0].ready}\\n{end}",
        ])
        .output()
        .await
        .context("failed to run kubectl get pods")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("kubectl get pods failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    let pods = stdout
        .lines()
        .filter(|line| !line.trim().is_empty())
        .filter_map(|line| {
            let parts: Vec<&str> = line.split(',').collect();
            if parts.len() >= 3 {
                Some(LeaderPod {
                    name: parts[0].to_string(),
                    status: parts[1].to_string(),
                    ready: parts[2] == "true",
                })
            } else {
                None
            }
        })
        .collect();

    Ok(pods)
}

/// Force-delete a pod (simulates crash — no graceful shutdown).
pub async fn force_delete_pod(namespace: &str, pod_name: &str) -> Result<()> {
    let output = Command::new("kubectl")
        .args([
            "delete",
            "pod",
            pod_name,
            "-n",
            namespace,
            "--grace-period=0",
            "--force",
        ])
        .output()
        .await
        .context("failed to run kubectl delete pod")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("kubectl delete pod (force) failed: {stderr}");
    }

    Ok(())
}

/// Delete a pod with normal grace period (graceful shutdown, drain happens).
pub async fn delete_pod(namespace: &str, pod_name: &str) -> Result<()> {
    let output = Command::new("kubectl")
        .args(["delete", "pod", pod_name, "-n", namespace])
        .output()
        .await
        .context("failed to run kubectl delete pod")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("kubectl delete pod failed: {stderr}");
    }

    Ok(())
}

/// Scale a StatefulSet to the given replica count.
pub async fn scale_statefulset(
    namespace: &str,
    statefulset_name: &str,
    replicas: u32,
) -> Result<()> {
    let output = Command::new("kubectl")
        .args([
            "scale",
            "statefulset",
            statefulset_name,
            "-n",
            namespace,
            &format!("--replicas={replicas}"),
        ])
        .output()
        .await
        .context("failed to run kubectl scale")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("kubectl scale failed: {stderr}");
    }

    Ok(())
}

/// Get the current replica count of a StatefulSet.
pub async fn get_statefulset_replicas(
    namespace: &str,
    statefulset_name: &str,
) -> Result<u32> {
    let output = Command::new("kubectl")
        .args([
            "get",
            "statefulset",
            statefulset_name,
            "-n",
            namespace,
            "-o",
            "jsonpath={.spec.replicas}",
        ])
        .output()
        .await
        .context("failed to run kubectl get statefulset")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("kubectl get statefulset failed: {stderr}");
    }

    let stdout = String::from_utf8_lossy(&output.stdout);
    stdout
        .trim()
        .parse()
        .context("failed to parse replica count")
}

/// Wait for a specific pod to become Ready.
pub async fn wait_for_pod_ready(
    namespace: &str,
    pod_name: &str,
    timeout_secs: u64,
) -> Result<()> {
    let output = Command::new("kubectl")
        .args([
            "wait",
            &format!("pod/{pod_name}"),
            "-n",
            namespace,
            "--for=condition=Ready",
            &format!("--timeout={timeout_secs}s"),
        ])
        .output()
        .await
        .context("failed to run kubectl wait")?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        bail!("pod {pod_name} did not become ready: {stderr}");
    }

    Ok(())
}
