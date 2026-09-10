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
from toolbox.kubernetes import TOOLBOX_ENVIRONMENTS, ensure_context_access, select_context, validate_context
from toolbox.pod import ClaimRaceError, claim_pod, connect_to_pod, delete_pod, get_toolbox_pod
from toolbox.tailscale import ensure_tailscale_connected
from toolbox.telemetry import capture_invocation, prompt_for_reason
from toolbox.user import get_current_user

# `default_namespace` is where the pool lives when KUBE_NAMESPACE isn't set.
#
# `extra_selectors_by_namespace` ANDs onto the base
# `app.kubernetes.io/name=<app_label>` selector. Keyed by namespace because the
# golden-chart deployment co-locates the toolbox release's own pgbouncer pods
# under the same `name` label, so we need `component=app` there to pick only
# the main pool pods. The legacy `posthog` namespace doesn't need a
# discriminator because its pgbouncers carry a different `name`.
POOLS = {
    "toolbox-django": {
        # Golden-chart deployment in the per-app namespace; the legacy `posthog`
        # namespace is still available via `KUBE_NAMESPACE=posthog`.
        "default_namespace": "posthog-toolbox-django",
        "app_label": "posthog-toolbox-django",
        "claimed_label_key": "toolbox-claimed",
        "extra_selectors_by_namespace": {
            "posthog-toolbox-django": "app.kubernetes.io/component=app",
        },
    },
    "flags-cache-jumphost": {
        # `namespace_by_environment` names the namespace for each environment
        # that has moved to the posthog-app golden chart; `default_namespace`
        # covers the rest, and `KUBE_NAMESPACE` overrides both. Add an entry as
        # each environment migrates, and collapse this back to a single
        # `default_namespace` once every environment is listed
        # (PostHog/charts#14843).
        "default_namespace": "posthog",
        "namespace_by_environment": {
            "dev": "flags-cache-jumphost",
            "prod-eu": "flags-cache-jumphost",
        },
        "app_label": "flags-cache-jumphost",
        "claimed_label_key": "flags-jumphost-claimed",
    },
}

# Bound the claim-race retry budget so a permanently-contended pool can't loop forever.
MAX_CLAIM_RETRIES = 3


def resolve_namespace(pool: dict, kube_context: str | None) -> str:
    """Pick the namespace a pool lives in, honouring per-environment overrides.

    `KUBE_NAMESPACE` wins outright. Otherwise a pool may map an environment to
    its own namespace, which is what a partly-finished migration looks like: one
    environment on the golden chart in a per-app namespace, the rest still in
    `posthog`. Contexts are named `<environment>-<access suffix>`, so the
    environment comes from the context when one is set.

    With no context set the caller is prompted for an environment later, so
    there is nothing to key on yet. Return the pool's own default, which is the
    unmigrated namespace, and let `KUBE_NAMESPACE` cover the rest.
    """
    if override := os.environ.get("KUBE_NAMESPACE"):
        return override

    by_environment = pool.get("namespace_by_environment") or {}
    if by_environment and kube_context:
        for environment in TOOLBOX_ENVIRONMENTS:
            if kube_context.startswith(f"{environment}-") or kube_context == environment:
                return by_environment.get(environment, pool["default_namespace"])

    return pool["default_namespace"]


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

        # The cluster endpoints are only reachable over the tailnet; without this
        # check a disconnected Tailscale surfaces as opaque kubectl timeouts.
        ensure_tailscale_connected()

        # Ask up front (before the kubectl waits) what this session is for; skipped
        # automatically on non-interactive stdin so automation never blocks.
        usage_reason = prompt_for_reason()

        pool = POOLS[args.pool]
        app_label = pool["app_label"]
        claimed_label_key = pool["claimed_label_key"]
        # Each pool advertises its own default namespace, and may override it per
        # environment while a migration is only partly done. `KUBE_NAMESPACE`
        # remains the escape hatch (e.g. to point the toolbox-django pool back
        # at the legacy `posthog` namespace during migration).
        namespace = resolve_namespace(pool, os.environ.get("KUBE_CONTEXT"))
        # Resolve which kubernetes context to use without ever calling
        # `kubectl config use-context`. Switching kubeconfig globally would persist past
        # this script and silently redirect later operational commands.
        if kube_context := os.environ.get("KUBE_CONTEXT"):
            if not validate_context(kube_context):
                print(f"❌ KUBE_CONTEXT='{kube_context}' is not a known kubernetes context.")  # noqa: T201
                sys.exit(1)
            if not ensure_context_access(kube_context, namespace):
                sys.exit(1)
            selected_context = kube_context
        else:
            selected_context = select_context(namespace)
            # The environment was only chosen inside select_context, so a pool
            # with per-environment namespaces has to be resolved again now that
            # the answer exists.
            namespace = resolve_namespace(pool, selected_context)
        print(f"🔄 Using kubernetes context: {selected_context}")  # noqa: T201

        # The base selector is `app.kubernetes.io/name=<app_label>`. Some
        # namespaces also host other workloads that share that label (e.g. the
        # golden chart deploys a per-app pgbouncer under the same name in the
        # `posthog-toolbox-django` namespace), so we may need a further
        # discriminator to pick only the main pool pods. Resolved after the
        # context, because the namespace can depend on the chosen environment.
        extra_selector = pool.get("extra_selectors_by_namespace", {}).get(namespace)

        print(f"🛠️  Connecting to {args.pool} pool in namespace {namespace}...")  # noqa: T201

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
            extra_selector=extra_selector,
        )
        print(f"🎯 Found pod: {pod_name}")  # noqa: T201

        # Best-effort usage event; counts invocations and records the environment +
        # the user's stated reason. Never raises, so it can't break connecting.
        capture_invocation(
            distinct_id=user_labels[claimed_label_key],
            properties={
                "pool": args.pool,
                "namespace": namespace,
                "kube_context": selected_context,
                "pod_name": pod_name,
                "was_already_claimed": is_already_claimed,
                "claim_duration_hours": args.claim_duration,
                "update_claim": args.update_claim,
                "auto_delete": args.auto_delete,
                "usage_reason": usage_reason,
            },
        )

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
                        extra_selector=extra_selector,
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
