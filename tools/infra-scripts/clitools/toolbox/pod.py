#!/usr/bin/env python3
"""Pod management functions."""

import sys
import json
import time
import subprocess
from datetime import datetime, timedelta

from toolbox.kubernetes import kubectl_cmd


class ClaimRaceError(Exception):
    """Raised when a claim attempt loses an optimistic-concurrency race.

    The Kubernetes API rejects label/annotate writes whose ``--resource-version``
    does not match the current value, returning a 409 Conflict. ``claim_pod``
    surfaces that as ``ClaimRaceError`` so the caller can retry against a
    different pod (or bail) instead of silently overwriting another writer.
    """


def _is_conflict(stderr: str) -> bool:
    """Heuristic detection of a 409 Conflict in kubectl stderr."""
    return "Conflict" in stderr or "the object has been modified" in stderr


def get_toolbox_pod(
    user: str,
    check_claimed: bool = True,
    *,
    app_label: str,
    claimed_label_key: str,
    namespace: str,
    context: str | None = None,
) -> tuple[str, bool, str]:
    """Get an available toolbox pod name and the resourceVersion observed.

    Args:
        user: Current user ARN
        check_claimed: If True, first look for pods already claimed by the user
        app_label: Value of the app.kubernetes.io/name label that identifies the pool.
        claimed_label_key: Label key the wrapper sets on a claimed pod.
        namespace: Kubernetes namespace the pool lives in.
        context: Optional kubernetes context to scope the kubectl call to.

    Returns:
        Tuple of (pod_name, is_already_claimed, resource_version). The
        resource_version reflects the pod state at observation time and is
        used by ``claim_pod`` for optimistic concurrency control.
    """
    wait_start = datetime.now()
    max_wait = timedelta(minutes=5)
    update_interval = timedelta(seconds=30)
    next_update = wait_start

    while True:
        try:
            result = subprocess.run(
                kubectl_cmd(
                    "get",
                    "pods",
                    "-n",
                    namespace,
                    "-l",
                    f"app.kubernetes.io/name={app_label}",
                    "-o",
                    "json",
                    context=context,
                ),
                capture_output=True,
                text=True,
                check=True,
            )
            pods = json.loads(result.stdout)["items"]

            if check_claimed:
                # Get user ID from ARN and sanitize it
                user_id = sanitize_label(user.split("/")[-1] if "/" in user else user)
                # First look for pods already claimed by this user
                claimed_pods = [
                    (pod["metadata"]["name"], pod["metadata"].get("resourceVersion", ""))
                    for pod in pods
                    if pod["status"]["phase"] == "Running"
                    and pod.get("metadata", {}).get("labels", {}).get(claimed_label_key) == user_id
                    and not pod.get("metadata", {}).get("deletionTimestamp")
                ]

                if claimed_pods:
                    print("⚠️  Found pod already claimed by you")  # noqa: T201
                    return claimed_pods[0][0], True, claimed_pods[0][1]
                print("No pods currently claimed by you, looking for available pods...")  # noqa: T201

            # Look for unclaimed pods
            available_pods = [
                (pod["metadata"]["name"], pod["metadata"].get("resourceVersion", ""))
                for pod in pods
                if pod["status"]["phase"] in ("Running", "Pending")
                and claimed_label_key not in pod.get("metadata", {}).get("labels", {})
                and "terminate-after" not in pod.get("metadata", {}).get("labels", {})
                and not pod.get("metadata", {}).get("deletionTimestamp")
            ]

            if available_pods:
                return available_pods[0][0], False, available_pods[0][1]

            # No pods available, check if we should wait or timeout
            current_time = datetime.now()
            if current_time - wait_start > max_wait:
                print("\n❌ No pods became available after 5 minutes.")  # noqa: T201
                print("Please reach out to #team-infrastructure for assistance.")  # noqa: T201
                sys.exit(1)

            # Check if we should print an update
            if current_time >= next_update:
                wait_time = current_time - wait_start
                print(f"⏳ Waiting for available pod... ({int(wait_time.total_seconds())}s)")  # noqa: T201
                next_update = current_time + update_interval

            # Wait before next check
            time.sleep(2)

        except subprocess.CalledProcessError as e:
            print(f"kubectl failed: {e.stderr or e}")  # noqa: T201
            sys.exit(1)
        except Exception as e:
            print(f"Unexpected error getting toolbox pod: {e}")  # noqa: T201
            sys.exit(1)


def claim_pod(
    pod_name: str,
    user_labels: dict,
    timestamp: int,
    *,
    namespace: str,
    context: str | None = None,
    resource_version: str | None = None,
):
    """Claim the pod by updating its labels.

    When ``resource_version`` is supplied, the first kubectl call that mutates
    the pod attaches ``--resource-version=<rv>`` so the API rejects the write
    if another user has already modified the pod since we observed it. On
    rejection, ``ClaimRaceError`` is raised so the caller can retry against a
    different pod. Subsequent kubectl calls in the same claim sequence do not
    pass --resource-version because the resource version advances after every
    successful write; once the first mutation has won, no other writer can
    sneak in mid-claim.

    Strips every label except app.kubernetes.io/name (which orphans the pod from
    its ReplicaSet by removing pod-template-hash), annotates karpenter to skip
    disruption, then applies user_labels + a terminate-after timestamp.
    """
    human_readable = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Claiming pod {pod_name} until {human_readable}")  # noqa: T201
    try:
        result = subprocess.run(
            kubectl_cmd("get", "pod", "-n", namespace, pod_name, "-o", "jsonpath={.metadata.labels}", context=context),
            capture_output=True,
            text=True,
            check=True,
        )

        current_labels = json.loads(result.stdout)

        labels_to_remove = [name for name in current_labels.keys() if name != "app.kubernetes.io/name"]
        # Attach the optimistic-concurrency guard to whichever kubectl invocation is the first
        # actual write; once it succeeds, the resourceVersion advances and subsequent calls
        # don't need (and can't pass) the same value.
        rv_guard_pending = bool(resource_version)

        if labels_to_remove:
            args = [f"{name}-" for name in labels_to_remove]
            if rv_guard_pending:
                args.append(f"--resource-version={resource_version}")
                rv_guard_pending = False
            try:
                subprocess.run(
                    kubectl_cmd("label", "pod", "-n", namespace, pod_name, *args, context=context),
                    check=True,
                    capture_output=True,
                    text=True,
                )
            except subprocess.CalledProcessError as e:
                if _is_conflict(e.stderr or ""):
                    raise ClaimRaceError(f"Pod {pod_name} was claimed by another writer") from e
                print(f"Error stripping labels: {e.stderr or e}")  # noqa: T201
                raise

        annotate_args = ["karpenter.sh/do-not-disrupt=true", "--overwrite=true"]
        if rv_guard_pending:
            annotate_args.append(f"--resource-version={resource_version}")
            rv_guard_pending = False
        try:
            subprocess.run(
                kubectl_cmd("annotate", "pod", "-n", namespace, pod_name, *annotate_args, context=context),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            if _is_conflict(e.stderr or ""):
                raise ClaimRaceError(f"Pod {pod_name} was claimed by another writer") from e
            print(f"Error annotating pod: {e.stderr or e}")  # noqa: T201
            raise

        label_args = [f"{key}={value}" for key, value in {**user_labels, "terminate-after": str(timestamp)}.items()]
        subprocess.run(
            kubectl_cmd("label", "pod", "-n", namespace, pod_name, *label_args, context=context),
            check=True,
        )

        print("⏳ Waiting for pod to be ready")  # noqa: T201
        try:
            subprocess.run(
                kubectl_cmd(
                    "wait",
                    "--for=condition=Ready",
                    "--timeout=5m",
                    "-n",
                    namespace,
                    "pod",
                    pod_name,
                    context=context,
                ),
                check=True,
            )
        except subprocess.CalledProcessError:
            print(f"❌ Pod {pod_name} did not become ready within 5 minutes.")  # noqa: T201
            sys.exit(1)
    except ClaimRaceError:
        raise
    except Exception as e:
        print(f"Error claiming pod: {e}")  # noqa: T201
        sys.exit(1)


def connect_to_pod(pod_name: str, *, namespace: str, context: str | None = None) -> int:
    """Connect to the specified pod using kubectl exec, returning the exec exit code.

    The caller is responsible for surfacing a non-zero return as a non-zero
    process exit so failures (RBAC denied, pod gone, network) don't get masked
    as success and trigger downstream cleanup of a session that never opened.
    """
    _safe_print(f"🚀 Connecting to pod {pod_name}...")
    result = subprocess.run(kubectl_cmd("exec", "-it", "-n", namespace, pod_name, "--", "bash", context=context))
    return result.returncode


def _safe_print(msg: str) -> None:
    """print() that swallows IOErrors raised by writing to a hung-up terminal.

    When the user closes their terminal tab, the wrapper receives SIGHUP and
    runs cleanup via atexit *after* the controlling PTY is gone. A naked
    ``print()`` in that path raises ``BrokenPipeError``/``OSError`` and aborts
    the cleanup mid-flight — leaking the very pod we're trying to delete. The
    actual cluster-side work (kubectl delete) is the load-bearing call;
    progress messages are best-effort.
    """
    try:
        print(msg)  # noqa: T201
    except (BrokenPipeError, OSError):
        pass


def delete_pod(
    pod_name: str,
    *,
    namespace: str,
    context: str | None = None,
    auto_yes: bool = False,
    expected_label_key: str | None = None,
    expected_label_value: str | None = None,
):
    """Delete the specified pod.

    With auto_yes=True, skip the [y/N] prompt and unconditionally delete.
    Uses --ignore-not-found so it is safe to call on a pod whose claim labels
    were never written or that has already been deleted.

    When ``expected_label_key`` and ``expected_label_value`` are supplied, the
    pod's current ``<key>`` label is checked first; if it does not match, the
    delete is skipped. This guards the atexit path from deleting a healthy
    unclaimed pool pod when ``claim_pod()`` failed before writing the claim
    label (e.g. a transient kubectl/get failure on the very first call). If
    the label check itself errors, the safe default is to skip the delete —
    leaving an orphan to be reaped is preferable to silently shrinking the pool.

    Robust to a closed/hung-up controlling terminal: progress prints can fail
    silently, and kubectl's own stdout/stderr are captured so they can't trip
    on the same broken FDs. The kubectl delete is the load-bearing operation
    and runs even when the user's terminal is gone.
    """
    if expected_label_key is not None and expected_label_value is not None:
        try:
            result = subprocess.run(
                kubectl_cmd(
                    "get",
                    "pod",
                    "-n",
                    namespace,
                    pod_name,
                    "-o",
                    f"jsonpath={{.metadata.labels.{expected_label_key}}}",
                    "--ignore-not-found",
                    context=context,
                ),
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as e:
            _safe_print(f"⚠️  Skipping delete of {pod_name}: could not verify claim label ({e.stderr or e})")
            return
        observed = result.stdout.strip()
        if observed != expected_label_value:
            _safe_print(
                f"⚠️  Skipping delete of {pod_name}: "
                f"{expected_label_key}='{observed}' (expected '{expected_label_value}')"
            )
            return

    if not auto_yes:
        try:
            response = input("\n❓ Would you like to delete this pod now? [y/N]: ").lower().strip()
        except (BrokenPipeError, OSError, EOFError):
            # No usable TTY — default to "don't delete" so we never delete without consent.
            _safe_print("👋 Pod will remain running until its scheduled termination time")
            return
        if response != "y":
            _safe_print("👋 Pod will remain running until its scheduled termination time")
            return

    _safe_print("🗑️  Deleting pod...")
    try:
        subprocess.run(
            kubectl_cmd(
                "delete",
                "pod",
                "-n",
                namespace,
                pod_name,
                "--ignore-not-found",
                "--wait=false",
                context=context,
            ),
            check=True,
            capture_output=True,
            text=True,
        )
        _safe_print("✅ Pod scheduled for deletion")
    except subprocess.CalledProcessError as e:
        _safe_print(f"❌ Failed to delete pod: {e.stderr or e}")


def sanitize_label(value: str) -> str:
    """Sanitize a value to be a valid kubernetes label value."""
    # Replace @ with _at_ and keep dots
    sanitized = value.replace("@", "_at_")
    # Ensure it starts and ends with alphanumeric
    sanitized = sanitized.strip("_")
    return sanitized
