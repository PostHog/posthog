#!/usr/bin/env python3
"""
Toolbox command for connecting to PostHog toolbox pods in a Kubernetes environment.
"""

import os
import sys
import atexit
import signal
import argparse
from datetime import datetime, timedelta

# Add the current directory to the path to allow importing from the toolbox package
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Import functions from the modular package
from toolbox.kubernetes import select_context, validate_context
from toolbox.pod import ClaimRaceError, claim_pod, connect_to_pod, delete_pod, get_toolbox_pod
from toolbox.user import get_current_user

POOLS = {
    "toolbox-django": {
        "app_label": "posthog-toolbox-django",
        "claimed_label_key": "toolbox-claimed",
    },
    "flags-cache-jumphost": {
        "app_label": "flags-cache-jumphost",
        "claimed_label_key": "flags-jumphost-claimed",
    },
}

# Bound the claim-race retry budget so a permanently-contended pool can't loop forever.
MAX_CLAIM_RETRIES = 3


def _exit_for_signal(signum, _frame):
    """SIGTERM/SIGHUP handler that routes through sys.exit so atexit-registered cleanup runs.

    Default Python behavior on SIGTERM/SIGHUP is to terminate without running atexit; raising
    SystemExit via sys.exit makes the registered cleanup fire.
    """
    sys.exit(128 + signum)


def main():
    """Main entry point for the toolbox command."""
    try:
        # If we're in a flox environment, exit
        if "FLOX_ENV" in os.environ:
            print("⚠️ Please exit the flox environment by typing `exit` before connecting to a toolbox.")  # noqa: T201
            sys.exit(0)

        # Set up argument parser
        parser = argparse.ArgumentParser(
            description="Connect to a toolbox pod and manage pod claims. This script will automatically connect you to your latest claimed pod.",
            epilog="Example: toolbox.py --claim-duration 24  # Claims a pod for 24 hours",
        )
        parser.add_argument(
            "--claim-duration",
            type=float,
            default=12,
            help="Duration in hours to claim the pod for (default: 12). The pod will be automatically terminated after this duration.",
        )
        parser.add_argument(
            "--update-claim",
            action="store_true",
            help="Update the termination time of your existing claimed pod instead of claiming a new one.",
        )
        parser.add_argument(
            "--pool",
            choices=sorted(POOLS.keys()),
            default="toolbox-django",
            help="Which pool to claim from. Defaults to toolbox-django (the original posthog-toolbox-django pool).",
        )
        parser.add_argument(
            "--auto-delete",
            action="store_true",
            help="Skip the [y/N] prompt on exit and unconditionally delete the claimed pod on normal exit, Ctrl-C, or terminal close.",
        )
        args = parser.parse_args()

        pool = POOLS[args.pool]
        app_label = pool["app_label"]
        claimed_label_key = pool["claimed_label_key"]
        namespace = os.environ.get("KUBE_NAMESPACE", "posthog")

        print(f"🛠️  Connecting to {args.pool} pool in namespace {namespace}...")  # noqa: T201

        # Resolve which kubernetes context to use without ever calling
        # `kubectl config use-context`. Switching kubeconfig globally would persist past
        # this script and silently redirect later operational commands.
        if kube_context := os.environ.get("KUBE_CONTEXT"):
            if not validate_context(kube_context):
                print(f"❌ KUBE_CONTEXT='{kube_context}' is not a known kubernetes context.")  # noqa: T201
                sys.exit(1)
            selected_context = kube_context
        else:
            selected_context = select_context()
        print(f"🔄 Using kubernetes context: {selected_context}")  # noqa: T201

        # Get current user labels
        user_labels = get_current_user(claimed_label_key=claimed_label_key, context=selected_context)
        print(f"👤 Current user labels: {user_labels}")  # noqa: T201

        # Get available pod
        pod_name, is_already_claimed, resource_version = get_toolbox_pod(
            user_labels[claimed_label_key],
            check_claimed=True,
            app_label=app_label,
            claimed_label_key=claimed_label_key,
            namespace=namespace,
            context=selected_context,
        )
        print(f"🎯 Found pod: {pod_name}")  # noqa: T201

        # Calculate duration
        future_time = datetime.now() + timedelta(hours=args.claim_duration)
        timestamp = int(future_time.timestamp())
        human_readable = future_time.strftime("%Y-%m-%d %H:%M:%S")

        will_claim = (not is_already_claimed) or args.update_claim

        # Arm cleanup BEFORE the claim. claim_pod() can block for up to 5 minutes
        # waiting for the pod to become Ready, so a Ctrl-C / SIGHUP / SIGTERM during
        # that wait must still clean up the pod we already labelled. Skipping
        # registration when we're just reattaching to an already-claimed pod
        # prevents this shell from deleting a pod that another shell of yours
        # may still be using.
        if args.auto_delete and will_claim:
            # expected_label_key/value gate the delete on the pod still carrying our claim
            # label, so a claim_pod() failure before any label was written (transient
            # kubectl get/RBAC error, pod gone) doesn't shrink the pool by deleting an
            # unclaimed pool pod from atexit.
            atexit.register(
                delete_pod,
                pod_name,
                namespace=namespace,
                context=selected_context,
                auto_yes=True,
                expected_label_key=claimed_label_key,
                expected_label_value=user_labels[claimed_label_key],
            )
            # SIGTERM and SIGHUP bypass atexit by default; _exit_for_signal routes them
            # through sys.exit so the registered cleanup runs. SIGHUP fires on terminal
            # close (closing iTerm, SSH disconnect, killing a tmux pane). SIGINT raises
            # KeyboardInterrupt, which the outer except handles, and atexit fires from there.
            signal.signal(signal.SIGTERM, _exit_for_signal)
            signal.signal(signal.SIGHUP, _exit_for_signal)

        if not is_already_claimed:
            # Fresh claim: protect against concurrent claimers via resourceVersion. If we
            # lose the race (409 Conflict), retry against a different pod up to
            # MAX_CLAIM_RETRIES times.
            print(f"⏰ Setting pod termination time to: {human_readable}")  # noqa: T201
            for attempt in range(1, MAX_CLAIM_RETRIES + 1):
                try:
                    claim_pod(
                        pod_name,
                        user_labels,
                        timestamp,
                        namespace=namespace,
                        context=selected_context,
                        resource_version=resource_version,
                    )
                    break
                except ClaimRaceError as race:
                    print(f"⚠️  Claim race on {pod_name} (attempt {attempt}/{MAX_CLAIM_RETRIES}): {race}")  # noqa: T201
                    if args.auto_delete and will_claim:
                        # Stale registration points at the pod we lost; remove it before
                        # picking another. atexit.unregister removes all registrations of
                        # delete_pod, which is fine because we register at most one.
                        atexit.unregister(delete_pod)
                    pod_name, is_already_claimed, resource_version = get_toolbox_pod(
                        user_labels[claimed_label_key],
                        check_claimed=True,
                        app_label=app_label,
                        claimed_label_key=claimed_label_key,
                        namespace=namespace,
                        context=selected_context,
                    )
                    if is_already_claimed:
                        # Either we won an earlier race attempt (whose ack we missed) or
                        # another shell of ours holds a claim — either way, don't auto-delete.
                        print(f"🎯 Found pod already claimed by you: {pod_name}")  # noqa: T201
                        will_claim = False
                        break
                    print(f"🎯 Trying pod: {pod_name}")  # noqa: T201
                    if args.auto_delete:
                        atexit.register(
                            delete_pod,
                            pod_name,
                            namespace=namespace,
                            context=selected_context,
                            auto_yes=True,
                            expected_label_key=claimed_label_key,
                            expected_label_value=user_labels[claimed_label_key],
                        )
            else:
                # Drop the stale registration first. The except branch above
                # registers cleanup for the *next* candidate before retrying;
                # if we exhaust retries, that candidate was never claimed by us
                # and atexit would otherwise delete a healthy unclaimed pool pod.
                if args.auto_delete:
                    atexit.unregister(delete_pod)
                print(f"❌ Could not claim a pod after {MAX_CLAIM_RETRIES} race retries.")  # noqa: T201
                sys.exit(1)
            if will_claim:
                print(f"✅ Successfully claimed pod: {pod_name}")  # noqa: T201
        elif args.update_claim:
            # Extending an existing claim of ours; no race possible because nobody
            # else is competing for a pod we already own.
            print(f"⏰ Updating pod termination time to: {human_readable}")  # noqa: T201
            claim_pod(
                pod_name,
                user_labels,
                timestamp,
                namespace=namespace,
                context=selected_context,
                resource_version=None,
            )
            print(f"✅ Successfully updated pod: {pod_name}")  # noqa: T201
        else:
            print("✅ Connecting to your existing pod (use --update-claim to extend the duration)")  # noqa: T201

        if args.auto_delete:
            rc = connect_to_pod(pod_name, namespace=namespace, context=selected_context)
        else:
            try:
                rc = connect_to_pod(pod_name, namespace=namespace, context=selected_context)
            finally:
                if will_claim:
                    delete_pod(pod_name, namespace=namespace, context=selected_context)
        sys.exit(rc)
    except KeyboardInterrupt:
        print("\n👋 Goodbye! \n \n Did something not work as expected? Ask in #team-infrastructure")  # noqa: T201
        # POSIX convention: SIGINT exits 128 + signum (130). sys.exit(0) here
        # would mask Ctrl-C as a clean success to any wrapper checking $?, and
        # is inconsistent with the SIGTERM/SIGHUP handlers which already use 128 + signum.
        sys.exit(128 + signal.SIGINT)


if __name__ == "__main__":
    main()
