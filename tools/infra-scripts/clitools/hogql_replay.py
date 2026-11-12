#!/usr/bin/env python3
"""
Replay logged HogQL queries against a pull request's code in the hogql-replay pod pool.
"""

import os
import sys
import json
import time
import argparse
import subprocess

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from toolbox.kubernetes import ensure_context_access, get_available_contexts, kubectl_cmd
from toolbox.pod import ClaimRaceError, claim_pod, delete_pod, get_toolbox_pod
from toolbox.tailscale import ensure_tailscale_connected
from toolbox.user import get_current_user

NAMESPACE = "posthog-hogql-replay"
APP_LABEL = "posthog-hogql-replay"
CLAIMED_LABEL_KEY = "hogql-replay-claimed"
ENVIRONMENT = "prod-us"
ACCESS_SUFFIXES = ("eks", "write", "admin")
PR_IMAGE_REPOSITORY = "posthog-cloud-prs"
CLAIM_SECONDS = 2 * 60 * 60
WORK_DIR = "/tmp/hogql-replay"
CONTAINER = "posthog-hogql-replay"
VIEWER_NAMESPACE = "posthog-hogql-replay-viewer"
MAX_CLAIM_RETRIES = 3


def kubectl(context: str, *args: str) -> str:
    result = subprocess.run(kubectl_cmd(*args, context=context), check=True, capture_output=True, text=True)
    return result.stdout.strip()


def select_context() -> str:
    if context := os.environ.get("KUBE_CONTEXT"):
        return context
    available = set(get_available_contexts())
    for suffix in ACCESS_SUFFIXES:
        if f"{ENVIRONMENT}-{suffix}" in available:
            return f"{ENVIRONMENT}-{suffix}"
    sys.exit(f"No {ENVIRONMENT} kubernetes context found. Set KUBE_CONTEXT or request access.")


def pull_request(number: str | None) -> dict:
    command = ["gh", "pr", "view", *([number] if number else []), "--json", "number"]
    return json.loads(subprocess.run(command, check=True, capture_output=True, text=True).stdout)


def claim(context: str, user_labels: dict, pods: list[str]) -> str:
    for _ in range(MAX_CLAIM_RETRIES):
        pod, _, resource_version = get_toolbox_pod(
            user_labels[CLAIMED_LABEL_KEY],
            check_claimed=False,
            app_label=APP_LABEL,
            claimed_label_key=CLAIMED_LABEL_KEY,
            namespace=NAMESPACE,
            context=context,
        )
        pods.append(pod)
        try:
            claim_pod(
                pod,
                user_labels,
                int(time.time()) + CLAIM_SECONDS,
                namespace=NAMESPACE,
                context=context,
                resource_version=resource_version,
            )
            return pod
        except ClaimRaceError:
            pods.remove(pod)
    sys.exit("Could not claim a hogql-replay pod. Try again.")


def container_field(context: str, pod: str, field: str) -> str:
    path = f'{{.status.containerStatuses[?(@.name=="{CONTAINER}")].{field}}}'
    return kubectl(context, "get", "pod", "-n", NAMESPACE, pod, "-o", f"jsonpath={path}")


def pr_image(context: str, pod: str, pr_number: int) -> str:
    registry = container_field(context, pod, "image").split("/", 1)[0]
    return f"{registry}/{PR_IMAGE_REPOSITORY}:pr-{pr_number}"


def set_image(context: str, pod: str, image: str) -> None:
    if container_field(context, pod, "image") == image:
        return
    restarts = container_field(context, pod, "restartCount")
    kubectl(context, "set", "image", "-n", NAMESPACE, f"pod/{pod}", f"{CONTAINER}={image}")
    deadline = time.time() + 600
    while container_field(context, pod, "restartCount") == restarts:
        if time.time() > deadline:
            sys.exit(f"Could not start {image}. Check that Container Images CI built and pushed it for this PR.")
        time.sleep(5)
    kubectl(context, "wait", "--for=condition=Ready", "-n", NAMESPACE, f"pod/{pod}", "--timeout=600s")


def manage(context: str, pod: str, *args: str) -> None:
    print(kubectl(context, "exec", "-n", NAMESPACE, pod, "--", "python", "manage.py", "hogql_replay", *args))  # noqa: T201


def replay(context: str, base_pod: str, head_pod: str, args: argparse.Namespace, run_key: str) -> None:
    selection = [arg for query_id in args.query_id for arg in ("--query-id", query_id)]
    selection = selection or ["--sample", str(args.sample)]
    sample, base, head = f"{WORK_DIR}/sample.jsonl", f"{WORK_DIR}/base.jsonl", f"{WORK_DIR}/head.jsonl"

    for pod in (base_pod, head_pod):
        kubectl(context, "exec", "-n", NAMESPACE, pod, "--", "mkdir", "-p", WORK_DIR)
    manage(context, base_pod, "sample", "--out", sample, *selection)
    manage(context, base_pod, "upload", "--path", sample, "--key", f"{run_key}/sample.jsonl")
    manage(context, base_pod, "compile", "--sample-file", sample, "--out", base)
    manage(context, head_pod, "download", "--key", f"{run_key}/sample.jsonl", "--path", sample)
    manage(context, head_pod, "compile", "--sample-file", sample, "--out", head)
    manage(context, head_pod, "upload", "--path", head, "--key", f"{run_key}/head.jsonl")
    manage(context, base_pod, "download", "--key", f"{run_key}/head.jsonl", "--path", head)
    manage(
        context,
        base_pod,
        "run",
        *("--sample-file", sample),
        *("--base", base),
        *("--head", head),
        *("--out-dir", f"{WORK_DIR}/report"),
        *("--base-label", container_field(context, base_pod, "imageID")),
        *("--head-label", container_field(context, head_pod, "imageID")),
    )
    manage(context, base_pod, "upload", "--path", f"{WORK_DIR}/report", "--key", f"{run_key}/report")


def report_location(context: str, run_key: str) -> str:
    try:
        host = kubectl(
            context,
            *("get", "ingress", "-n", VIEWER_NAMESPACE),
            *("-o", "jsonpath={.items[0].status.loadBalancer.ingress[0].hostname}"),
        )
    except subprocess.CalledProcessError:
        host = ""
    return f"https://{host}/{run_key}/report" if host else f"{run_key}/report in the replay reports bucket"


def run(args: argparse.Namespace) -> None:
    ensure_tailscale_connected()
    context = select_context()
    if not ensure_context_access(context, NAMESPACE):
        sys.exit(1)
    pr = pull_request(args.pr)
    user_labels = get_current_user(claimed_label_key=CLAIMED_LABEL_KEY, context=context)
    run_key = f"runs/pr-{pr['number']}/{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}"
    pods: list[str] = []
    try:
        base_pod = claim(context, user_labels, pods)
        head_pod = claim(context, user_labels, pods)
        set_image(context, head_pod, args.head_image or pr_image(context, head_pod, pr["number"]))
        if args.base_image:
            set_image(context, base_pod, args.base_image)
        replay(context, base_pod, head_pod, args, run_key)
    finally:
        for pod in pods:
            delete_pod(
                pod,
                namespace=NAMESPACE,
                context=context,
                auto_yes=True,
                expected_label_key=CLAIMED_LABEL_KEY,
                expected_label_value=user_labels[CLAIMED_LABEL_KEY],
            )
    location = report_location(context, run_key)
    print(f"Report: {location}/index.html")  # noqa: T201
    print(f"Result: {location}/result.json")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", help="Pull request number. Defaults to the current branch's pull request.")
    parser.add_argument("--query-id", action="append", default=[], help="A query_log_archive query ID. Repeatable.")
    parser.add_argument(
        "--sample", type=int, default=200, help="How many recent queries to sample when no ID is given."
    )
    parser.add_argument("--head-image", help="Image for the pull request's code. Defaults to the pull request image.")
    parser.add_argument("--base-image", help="Image for the base code. Defaults to the image the pool runs.")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
