#!/usr/bin/env python3
"""
Replay logged HogQL queries against a pull request's code in the hogql-replay pod pool.
"""

import os
import sys
import json
import time
import shutil
import argparse
import tempfile
import subprocess
from pathlib import Path

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


def copy(context: str, source: str, target: str) -> None:
    kubectl(context, "cp", source, target)


def replay(context: str, base_pod: str, head_pod: str, args: argparse.Namespace, local: Path) -> None:
    base_remote, head_remote = f"{NAMESPACE}/{base_pod}:{WORK_DIR}", f"{NAMESPACE}/{head_pod}:{WORK_DIR}"
    selection = [arg for query_id in args.query_id for arg in ("--query-id", query_id)]
    selection = selection or ["--sample", str(args.sample)]

    for pod in (base_pod, head_pod):
        kubectl(context, "exec", "-n", NAMESPACE, pod, "--", "mkdir", "-p", WORK_DIR)
    manage(context, base_pod, "sample", "--out", f"{WORK_DIR}/sample.jsonl", *selection)
    copy(context, f"{base_remote}/sample.jsonl", str(local / "sample.jsonl"))
    copy(context, str(local / "sample.jsonl"), f"{head_remote}/sample.jsonl")
    manage(context, base_pod, "compile", "--sample-file", f"{WORK_DIR}/sample.jsonl", "--out", f"{WORK_DIR}/base.jsonl")
    manage(context, head_pod, "compile", "--sample-file", f"{WORK_DIR}/sample.jsonl", "--out", f"{WORK_DIR}/head.jsonl")
    copy(context, f"{head_remote}/head.jsonl", str(local / "head.jsonl"))
    copy(context, str(local / "head.jsonl"), f"{base_remote}/head.jsonl")
    manage(
        context,
        base_pod,
        "run",
        *("--sample-file", f"{WORK_DIR}/sample.jsonl"),
        *("--base", f"{WORK_DIR}/base.jsonl"),
        *("--head", f"{WORK_DIR}/head.jsonl"),
        *("--out-dir", f"{WORK_DIR}/report"),
        *("--base-label", container_field(context, base_pod, "imageID")),
        *("--head-label", container_field(context, head_pod, "imageID")),
    )
    copy(context, f"{base_remote}/report", str(args.out_dir))


def publish(out_dir: Path, pr_number: int) -> None:
    if not shutil.which("hosthog"):
        print("The hosthog CLI is not installed, so the report was not published.")  # noqa: T201
        return
    subprocess.run(["hosthog", "publish", str(out_dir), "--slug", f"hogql-replay-{pr_number}"], check=True)


def run(args: argparse.Namespace) -> None:
    ensure_tailscale_connected()
    context = select_context()
    if not ensure_context_access(context, NAMESPACE):
        sys.exit(1)
    pr = pull_request(args.pr)
    user_labels = get_current_user(claimed_label_key=CLAIMED_LABEL_KEY, context=context)
    pods: list[str] = []
    try:
        base_pod = claim(context, user_labels, pods)
        head_pod = claim(context, user_labels, pods)
        set_image(context, head_pod, args.head_image or pr_image(context, head_pod, pr["number"]))
        if args.base_image:
            set_image(context, base_pod, args.base_image)
        with tempfile.TemporaryDirectory() as local:
            replay(context, base_pod, head_pod, args, Path(local))
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
    if args.publish:
        publish(args.out_dir, pr["number"])
    summary = json.loads((args.out_dir / "result.json").read_text())
    print(json.dumps({"counts": summary["counts"], "regressions": summary["regressions"]}))  # noqa: T201
    print(f"Full result: {args.out_dir / 'result.json'}")  # noqa: T201


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pr", help="Pull request number. Defaults to the current branch's pull request.")
    parser.add_argument("--query-id", action="append", default=[], help="A query_log_archive query ID. Repeatable.")
    parser.add_argument(
        "--sample", type=int, default=200, help="How many recent queries to sample when no ID is given."
    )
    parser.add_argument("--head-image", help="Image for the pull request's code. Defaults to the pull request image.")
    parser.add_argument("--base-image", help="Image for the base code. Defaults to the image the pool runs.")
    parser.add_argument("--out-dir", type=Path, default=Path("hogql-replay-report"))
    parser.add_argument("--no-publish", dest="publish", action="store_false", help="Keep the report local.")
    run(parser.parse_args())


if __name__ == "__main__":
    main()
