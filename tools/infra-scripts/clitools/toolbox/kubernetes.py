#!/usr/bin/env python3
"""Kubernetes context management functions."""

import sys
import subprocess


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
    """Switch to specified kubernetes context."""
    try:
        subprocess.run(["kubectl", "config", "use-context", context], check=True)
        print(f"✅ Switched to context: {context}")  # noqa: T201
        return True
    except subprocess.CalledProcessError as e:
        print(f"Error switching kubernetes context: {e}")  # noqa: T201
        return False


def select_context():
    """List available contexts and let user select one."""
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

    if response:
        try:
            index = int(response) - 1
            if 0 <= index < len(contexts):
                if switch_context(contexts[index]):
                    return contexts[index]
                else:
                    print("⚠️ Failed to switch context, continuing with current context.")  # noqa: T201
                    return current
            else:
                print("⚠️ Invalid selection, continuing with current context.")  # noqa: T201
                return current
        except ValueError:
            print("⚠️ Invalid input, continuing with current context.")  # noqa: T201
            return current

    return current
