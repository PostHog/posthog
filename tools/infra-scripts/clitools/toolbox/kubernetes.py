#!/usr/bin/env python3
"""Kubernetes context management functions."""

import sys
import subprocess


def kubectl_cmd(*args: str, context: str | None = None) -> list[str]:
    """Build a kubectl command with --context if `context` is set.

    Threading the context through every kubectl invocation lets us scope all
    operations to one cluster without ever mutating the user's global kubeconfig
    via `kubectl config use-context`. That matters because a wrapper that
    silently flips the default context can redirect later operational commands
    (kubectl delete, helm upgrade, …) to the wrong cluster.
    """
    cmd = ["kubectl"]
    if context:
        cmd.append(f"--context={context}")
    cmd.extend(args)
    return cmd


def get_available_contexts() -> list:
    """Get available kubernetes contexts."""
    try:
        result = subprocess.run(
            ["kubectl", "config", "get-contexts", "-o", "name"], capture_output=True, text=True, check=True
        )
        contexts = [context.strip() for context in result.stdout.strip().split("\n") if context.strip()]
        return contexts
    except subprocess.CalledProcessError as e:
        print(f"Error getting kubernetes contexts: {e}")  # noqa: T201
        sys.exit(1)


def get_current_context() -> str | None:
    """Get current kubernetes context."""
    try:
        result = subprocess.run(["kubectl", "config", "current-context"], capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError as e:
        print(f"Error getting current kubernetes context: {e}")  # noqa: T201
        return None


def switch_context(context: str) -> bool:
    """Switch to specified kubernetes context.

    Mutates kubeconfig globally. Prefer ``validate_context`` plus passing
    ``--context`` per invocation via ``kubectl_cmd``; this function is kept
    for callers that explicitly want a persistent switch.
    """
    try:
        subprocess.run(["kubectl", "config", "use-context", context], check=True)
        print(f"✅ Switched to context: {context}")  # noqa: T201
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error switching kubernetes context: {e}")  # noqa: T201
        return False


def validate_context(context: str) -> bool:
    """Return True if ``context`` is a known kubernetes context.

    Use this when you want to scope a single invocation to a context without
    mutating kubeconfig via ``switch_context``.
    """
    return context in get_available_contexts()


def select_context() -> str:
    """List available contexts and let the user pick one. Returns the chosen name.

    Does **not** call ``kubectl config use-context``; the caller is expected to
    pass the returned name as ``--context`` to subsequent kubectl invocations
    via ``kubectl_cmd``. Pressing Enter keeps the current context.
    """
    contexts = get_available_contexts()
    current = get_current_context()
    if current is None:
        print("❌ Could not determine current kubernetes context.")  # noqa: T201
        sys.exit(1)

    if not contexts:
        print("❌ No kubernetes contexts found.")  # noqa: T201
        sys.exit(1)

    print("\n🔍 Available kubernetes contexts:")  # noqa: T201
    for i, context in enumerate(contexts, 1):
        if context == current:
            print(f"  {i}. {context} (current)")  # noqa: T201
        else:
            print(f"  {i}. {context}")  # noqa: T201

    print(f"\nCurrently using: {current}")  # noqa: T201
    response = input("Enter context number to switch or press Enter to continue with current context: ").strip()

    if not response:
        return current

    try:
        index = int(response) - 1
    except ValueError:
        print("⚠️ Invalid input, continuing with current context.")  # noqa: T201
        return current

    if 0 <= index < len(contexts):
        return contexts[index]

    print("⚠️ Invalid selection, continuing with current context.")  # noqa: T201
    return current
