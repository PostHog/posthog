#!/usr/bin/env python3
"""Kubernetes context discovery and access management for the toolbox CLI."""

import sys
import json
import time
import subprocess

TOOLBOX_ENVIRONMENTS = ("dev", "prod-eu", "prod-us")
ACCESS_SUFFIXES = ("eks", "write", "admin")
ACCESS_WAIT_SECONDS = 10 * 60
ACCESS_POLL_SECONDS = 5
COMMAND_TIMEOUT_SECONDS = 15
AWS_ACCESS_CHANNEL = "https://posthog.slack.com/archives/C09ULM0E6SW"


def kubectl_cmd(*args: str, context: str | None = None) -> list[str]:
    """Build a kubectl command scoped to a context without changing kubeconfig."""
    cmd = ["kubectl"]
    if context:
        cmd.append(f"--context={context}")
    cmd.extend(args)
    return cmd


def get_available_contexts() -> list[str]:
    """Return the context names in the user's active kubeconfig."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "get-contexts", "-o", "name"],
            capture_output=True,
            text=True,
            check=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        print("❌ kubectl is not installed or is not on PATH.")  # noqa: T201
        sys.exit(1)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
        print(f"❌ Could not read kubernetes contexts: {error}")  # noqa: T201
        sys.exit(1)
    return [context.strip() for context in result.stdout.splitlines() if context.strip()]


def get_current_context() -> str | None:
    """Return the current context, retained for backwards-compatible callers."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "current-context"],
            capture_output=True,
            text=True,
            check=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        return result.stdout.strip()
    except (FileNotFoundError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None


def switch_context(context: str) -> bool:
    """Persistently switch context for legacy callers; the toolbox never uses this."""
    try:
        subprocess.run(["kubectl", "config", "use-context", context], check=True)
        print(f"✅ Switched to context: {context}")  # noqa: T201
        return True
    except subprocess.CalledProcessError as error:
        print(f"Error switching kubernetes context: {error}")  # noqa: T201
        return False


def validate_context(context: str) -> bool:
    """Return whether a context exists in the active kubeconfig."""
    return context in get_available_contexts()


def select_environment() -> str:
    """Prompt for one of the environments that actually hosts toolbox pools."""
    print("\n🌍 Choose an environment:")  # noqa: T201
    for index, environment in enumerate(TOOLBOX_ENVIRONMENTS, 1):
        print(f"  {index}. {environment}")  # noqa: T201

    while True:
        response = input("Environment number: ").strip()
        try:
            choice = int(response)
            if 1 <= choice <= len(TOOLBOX_ENVIRONMENTS):
                return TOOLBOX_ENVIRONMENTS[choice - 1]
        except ValueError:
            pass
        print(f"⚠️ Please enter a number from 1 to {len(TOOLBOX_ENVIRONMENTS)}.")  # noqa: T201


def check_context_access(context: str, _namespace: str) -> tuple[bool, str]:
    """Return whether a context can authenticate to its Kubernetes cluster."""
    try:
        result = subprocess.run(
            kubectl_cmd("auth", "whoami", "-o", "json", context=context),
            capture_output=True,
            text=True,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        return False, "kubectl is not installed or is not on PATH"
    except subprocess.TimeoutExpired:
        return False, "kubectl authentication check timed out (check that Tailscale is connected)"

    diagnostic = "\n".join(part for part in (result.stdout.strip(), result.stderr.strip()) if part)
    if result.returncode == 0:
        return True, ""
    return False, diagnostic


def get_context_profile(context: str) -> str:
    """Derive the AWS profile from a context's local kubeconfig user entry."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "view", "-o", "json"],
            capture_output=True,
            text=True,
            check=True,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
        config = json.loads(result.stdout)
        context_entry = next(item for item in config.get("contexts", []) if item.get("name") == context)
        user_name = context_entry["context"]["user"]
        user_entry = next(item for item in config.get("users", []) if item.get("name") == user_name)
        env = user_entry.get("user", {}).get("exec", {}).get("env", [])
        profile = next(item["value"] for item in env if item.get("name") == "AWS_PROFILE")
        if not profile:
            raise ValueError("empty AWS_PROFILE")
        return profile
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        KeyError,
        StopIteration,
        ValueError,
    ) as error:
        raise RuntimeError(f"could not derive an AWS profile for context '{context}'") from error


def _needs_sso_login(diagnostic: str) -> bool:
    diagnostic = diagnostic.lower()
    return any(
        marker in diagnostic
        for marker in (
            "token has expired",
            "sso session",
            "sso token",
            "unauthorizedssotokenerror",
            "error loading sso",
        )
    )


def _needs_sso_reset(diagnostic: str) -> bool:
    """Return whether Kubernetes rejected credentials from an otherwise active SSO grant."""
    diagnostic = diagnostic.lower()
    return any(
        marker in diagnostic
        for marker in (
            "the server has asked for the client to provide credentials",
            "you must be logged in to the server (unauthorized)",
        )
    )


# Transport-level fragments in kubectl output. They only count as cluster
# unreachability (which for the tailnet-gated clusters almost always means
# Tailscale is down) on lines about the API server connection; the same
# fragments coming from the AWS credential exec plugin must keep their own
# diagnostic instead of a misleading Tailscale hint.
_NETWORK_FAILURE_MARKERS = (
    "no such host",
    "no route to host",
    "i/o timeout",
    "network is unreachable",
    "connection refused",
    "dial tcp",
    "tls handshake timeout",
)
# kubectl's own dialer produces these; the AWS CLI phrases its errors differently.
_CLUSTER_CONNECTION_CONTEXTS = ("unable to connect to the server", "dial tcp")
_CREDENTIAL_PLUGIN_FRAGMENTS = ("getting credentials", "executable aws")


def _looks_like_network_failure(diagnostic: str) -> bool:
    for line in diagnostic.lower().splitlines():
        if any(fragment in line for fragment in _CREDENTIAL_PLUGIN_FRAGMENTS):
            continue
        if not any(marker in line for marker in _NETWORK_FAILURE_MARKERS):
            continue
        if any(context in line for context in _CLUSTER_CONNECTION_CONTEXTS):
            return True
    return False


def summarize_diagnostic(diagnostic: str) -> str:
    """Extract a concise, useful reason from noisy kubectl/AWS output."""
    lines = [line.strip() for line in diagnostic.splitlines() if line.strip()]
    for line in lines:
        if "No access" in line:
            return "AWS reports that this profile currently has no access"
        if _needs_sso_reset(line):
            return "Kubernetes rejected the cached AWS SSO credentials"
    if _looks_like_network_failure(diagnostic):
        return "cannot reach the cluster endpoint (check that Tailscale is connected)"
    for line in reversed(lines):
        if not line.startswith(("E", "Unable to connect to the server")):
            return line
    return lines[-1] if lines else "authentication failed"


def login_to_sso(profile: str, *, timeout: float) -> bool:
    """Run the AWS CLI's interactive SSO login for a kubeconfig-derived profile."""
    print(f"🔐 Your AWS SSO session needs refreshing. Logging in with profile '{profile}'...")  # noqa: T201
    try:
        return (
            subprocess.run(
                ["aws", "sso", "login", "--profile", profile],
                check=False,
                timeout=max(1, timeout),
            ).returncode
            == 0
        )
    except FileNotFoundError:
        print("❌ aws is not installed or is not on PATH.")  # noqa: T201
        return False
    except subprocess.TimeoutExpired:
        print("❌ AWS SSO login did not finish before the access wait timed out.")  # noqa: T201
        return False


def reset_sso(profile: str, *, deadline: float) -> bool:
    """Clear stale AWS SSO credentials and log back in with the selected profile."""
    print("🔄 Kubernetes rejected the refreshed credentials. Resetting AWS SSO and logging in again...")  # noqa: T201
    try:
        logout = subprocess.run(
            ["aws", "sso", "logout"],
            check=False,
            timeout=max(1, deadline - time.monotonic()),
        )
    except FileNotFoundError:
        print("❌ aws is not installed or is not on PATH.")  # noqa: T201
        return False
    except subprocess.TimeoutExpired:
        print("❌ AWS SSO logout did not finish before the access wait timed out.")  # noqa: T201
        return False
    if logout.returncode != 0:
        print("❌ AWS SSO logout failed.")  # noqa: T201
        return False
    return login_to_sso(profile, timeout=deadline - time.monotonic())


def wait_for_context_access(context: str, namespace: str, *, initial_diagnostic: str = "") -> bool:
    """Wait up to ten minutes for an AWS Access grant to become usable."""
    deadline = time.monotonic() + ACCESS_WAIT_SECONDS
    try:
        profile = get_context_profile(context)
    except RuntimeError as error:
        print(f"❌ {error}.")  # noqa: T201
        return False

    sso_login_attempted = False
    sso_reset_attempted = False
    if _needs_sso_reset(initial_diagnostic):
        sso_login_attempted = True
        if not login_to_sso(profile, timeout=deadline - time.monotonic()):
            return False
    elif _needs_sso_login(initial_diagnostic):
        sso_login_attempted = True
        if not login_to_sso(profile, timeout=deadline - time.monotonic()):
            print(  # noqa: T201
                f"❌ AWS SSO login failed. Try `aws sso login --profile {profile}` and rerun the toolbox."
            )
            return False

    print("\n🔒 No active toolbox-capable access was found.")  # noqa: T201
    print(f"Request `k8s + toolbox access` (eks-developer) in #aws-access: {AWS_ACCESS_CHANNEL}")  # noqa: T201
    print("⏳ Waiting up to 10 minutes for access. Press Ctrl-C to stop.")  # noqa: T201

    next_status = 0.0
    last_reason = ""
    while time.monotonic() < deadline:
        print(f"   Checking whether '{context}' can authenticate...")  # noqa: T201
        usable, diagnostic = check_context_access(context, namespace)
        if usable:
            print("✅ Access is active. Continuing...")  # noqa: T201
            return True
        if _needs_sso_reset(diagnostic):
            if not sso_login_attempted:
                sso_login_attempted = True
                if not login_to_sso(profile, timeout=deadline - time.monotonic()):
                    return False
            elif not sso_reset_attempted:
                sso_reset_attempted = True
                if not reset_sso(profile, deadline=deadline):
                    return False
        elif _needs_sso_login(diagnostic) and not sso_login_attempted:
            sso_login_attempted = True
            if not login_to_sso(profile, timeout=deadline - time.monotonic()):
                return False
        reason = summarize_diagnostic(diagnostic)
        if reason != last_reason:
            print(f"   Not ready: {reason}.")  # noqa: T201
            last_reason = reason
        now = time.monotonic()
        if now >= next_status:
            remaining = max(0, int((deadline - now) / 60) + 1)
            print(f"   Still waiting for access ({remaining} min remaining)...")  # noqa: T201
            next_status = now + 30
        time.sleep(ACCESS_POLL_SECONDS)

    print(  # noqa: T201
        "❌ Access was not available after 10 minutes. "
        f"After approval, rerun or use `aws sso login --profile {profile}`."
    )
    return False


def select_context(namespace: str) -> str:
    """Select the least-privileged usable managed context for a toolbox environment."""
    environment = select_environment()
    available = set(get_available_contexts())
    candidates = [f"{environment}-{suffix}" for suffix in ACCESS_SUFFIXES]
    configured = [context for context in candidates if context in available]
    if not configured:
        print(f"❌ No managed toolbox contexts were found for '{environment}'.")  # noqa: T201
        print("Your managed kubeconfig may be missing or out of date; contact #team-infrastructure.")  # noqa: T201
        sys.exit(1)

    diagnostics: dict[str, str] = {}
    for context in configured:
        print(f"🔎 Checking kubernetes access with '{context}'...")  # noqa: T201
        usable, diagnostic = check_context_access(context, namespace)
        diagnostics[context] = diagnostic
        if usable:
            return context

    least_privileged = f"{environment}-eks"
    if least_privileged not in available:
        print(f"❌ Expected managed context '{least_privileged}' is missing from kubeconfig.")  # noqa: T201
        sys.exit(1)
    if wait_for_context_access(
        least_privileged,
        namespace,
        initial_diagnostic=diagnostics.get(least_privileged, ""),
    ):
        return least_privileged
    sys.exit(1)


def ensure_context_access(context: str, namespace: str) -> bool:
    """Validate an explicit expert override and explain failures."""
    usable, diagnostic = check_context_access(context, namespace)
    if usable:
        return True
    print(f"❌ KUBE_CONTEXT='{context}' cannot perform the toolbox pod operations.")  # noqa: T201
    if diagnostic:
        print(diagnostic)  # noqa: T201
    return False
