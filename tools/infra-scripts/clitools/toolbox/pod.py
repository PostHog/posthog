#!/usr/bin/env python3
"""Pod management functions."""

import sys
import json
import time
import subprocess
from datetime import datetime, timedelta


def get_toolbox_pod(user: str, check_claimed: bool = True) -> tuple[str, bool]:
    """Get an available toolbox pod name.

    Args:
        user: Current user ARN
        check_claimed: If True, first look for pods already claimed by the user

    Returns:
        Tuple of (pod_name, is_already_claimed)
    """
    wait_start = datetime.now()
    max_wait = timedelta(minutes=5)
    update_interval = timedelta(seconds=30)
    next_update = wait_start

    while True:
        try:
            result = subprocess.run(
                [
                    "kubectl",
                    "get",
                    "pods",
                    "-n",
                    "posthog",
                    "-l",
                    "app.kubernetes.io/name=posthog-toolbox-django",
                    "-o",
                    "json",
                ],
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
                    pod["metadata"]["name"]
                    for pod in pods
                    if pod["status"]["phase"] == "Running"
                    and pod.get("metadata", {}).get("labels", {}).get("toolbox-claimed") == user_id
                    and not pod.get("metadata", {}).get("deletionTimestamp")
                ]

                if claimed_pods:
                    print("⚠️  Found pod already claimed by you")  # noqa: T201
                    return claimed_pods[0], True
                print("No pods currently claimed by you, looking for available pods...")  # noqa: T201

            # Look for unclaimed pods
            available_pods = [
                pod["metadata"]["name"]
                for pod in pods
                if pod["status"]["phase"] in ("Running", "Pending")
                and "toolbox-claimed" not in pod.get("metadata", {}).get("labels", {})
                and "terminate-after" not in pod.get("metadata", {}).get("labels", {})
                and not pod.get("metadata", {}).get("deletionTimestamp")
            ]

            if available_pods:
                return available_pods[0], False

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


def claim_pod(pod_name: str, user_labels: dict, timestamp: int):
    """Claim the pod by updating its labels."""

    human_readable = datetime.fromtimestamp(timestamp).strftime("%Y-%m-%d %H:%M:%S %Z")
    print(f"Claiming pod {pod_name} for user {user_labels.get('toolbox-claimed', 'unknown')} until {human_readable}")  # noqa: T201
    try:
        # Get current labels
        result = subprocess.run(
            ["kubectl", "get", "pod", "-n", "posthog", pod_name, "-o", "jsonpath={.metadata.labels}"],
            capture_output=True,
            text=True,
            check=True,
        )

        current_labels = json.loads(result.stdout)

        # Remove all labels except app.kubernetes.io/name
        for label_name in current_labels.keys():
            if label_name != "app.kubernetes.io/name":
                subprocess.run(
                    ["kubectl", "label", "pod", "-n", "posthog", pod_name, f"{label_name}-"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )

        # Add karpenter.sh/do-not-disrupt annotation
        subprocess.run(
            [
                "kubectl",
                "annotate",
                "pod",
                "-n",
                "posthog",
                pod_name,
                "karpenter.sh/do-not-disrupt=true",
                "--overwrite=true",
            ],
            check=True,
        )

        # Build label arguments
        label_args = [f"{key}={value}" for key, value in {**user_labels, "terminate-after": str(timestamp)}.items()]

        # Add new labels
        subprocess.run(["kubectl", "label", "pod", "-n", "posthog", pod_name, *label_args], check=True)

        # Wait for pod to be ready
        print("⏳ Waiting for pod to be ready")  # noqa: T201
        try:
            subprocess.run(
                ["kubectl", "wait", "--for=condition=Ready", "--timeout=5m", "-n", "posthog", "pod", pod_name],
                check=True,
            )
        except subprocess.CalledProcessError:
            print(f"❌ Pod {pod_name} did not become ready within 5 minutes.")  # noqa: T201
            sys.exit(1)
    except Exception as e:
        print(f"Error claiming pod: {e}")  # noqa: T201
        sys.exit(1)


def connect_to_pod(pod_name: str):
    """Connect to the specified pod using kubectl exec.

    Args:
        pod_name: Name of the pod to connect to
    """
    print(f"🚀 Connecting to pod {pod_name}...")  # noqa: T201
    subprocess.run(["kubectl", "exec", "-it", "-n", "posthog", pod_name, "--", "bash"])


def delete_pod(pod_name: str):
    """Delete the specified pod.

    Args:
        pod_name: Name of the pod to delete
    """
    response = input("\n❓ Would you like to delete this pod now? [y/N]: ").lower().strip()
    if response == "y":
        print("🗑️  Deleting pod...")  # noqa: T201
        try:
            subprocess.run(
                [
                    "kubectl",
                    "delete",
                    "pod",
                    "-n",
                    "posthog",
                    pod_name,
                    "--wait=false",  # Don't wait for pod deletion to complete
                ],
                check=True,
            )
            print("✅ Pod scheduled for deletion")  # noqa: T201
        except subprocess.CalledProcessError as e:
            print(f"❌ Failed to delete pod: {e}")  # noqa: T201
    else:
        print("👋 Pod will remain running until its scheduled termination time")  # noqa: T201


def sanitize_label(value: str) -> str:
    """Sanitize a value to be a valid kubernetes label value."""
    # Replace @ with _at_ and keep dots
    sanitized = value.replace("@", "_at_")
    # Ensure it starts and ends with alphanumeric
    sanitized = sanitized.strip("_")
    return sanitized
