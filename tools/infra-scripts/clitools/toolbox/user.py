#!/usr/bin/env python3
"""User identification and pod claiming functions."""

import re
import sys
import json
import subprocess

from toolbox.kubernetes import kubectl_cmd

# Kubernetes groups that grant write access to the cluster. The toolbox claims
# pods by patching their labels and deletes them on exit, so a read-only
# identity can't actually use it — membership in at least one of these is
# required. These mirror the EKS access-entry / aws-auth group mappings; update
# this set if the cluster's group names change.
WRITE_ACCESS_GROUPS = frozenset({"eks-developers", "eks-admins"})

# Slack channel users ping to elevate their permissions, and the runbook that
# explains how. Kept as constants so they're easy to adjust in one place.
ELEVATE_PERMISSIONS_CHANNEL = "<#C09ULM0E6SW>"
# TODO: confirm exact runbook URL
TOOLBOX_ACCESS_RUNBOOK_URL = "https://posthog.com/handbook/engineering/toolbox-access"


def _get_user_info(*, context: str | None = None) -> dict:
    """Return the ``status.userInfo`` block from ``kubectl auth whoami``.

    Centralizes the whoami call and its error handling so both identity parsing
    (``get_current_user``) and the write-access gate (``ensure_write_access``)
    share one code path. Exits the process on failure.
    """
    try:
        print("Attempting to get user identity...")  # noqa: T201
        whoami = subprocess.run(
            kubectl_cmd("auth", "whoami", "-o", "json", context=context),
            capture_output=True,
            text=True,
            check=True,
        )
        return json.loads(whoami.stdout)["status"]["userInfo"]

    except subprocess.CalledProcessError as e:
        print(f"Command failed with return code {e.returncode}")  # noqa: T201
        print(f"Output: {e.output}")  # noqa: T201
        print(f"Stderr: {e.stderr}")  # noqa: T201

        if e.returncode == 1 and "Token has expired and refresh failed" in e.stderr:
            print(  # noqa: T201
                "Token has expired and refresh failed, please reauthenticate with `aws sso login --profile=<your-profile>`"
            )

        sys.exit(1)
    except Exception as k8s_error:
        print(f"Error: Failed to get user identity: {k8s_error}")  # noqa: T201
        print(f"Error type: {type(k8s_error)}")  # noqa: T201
        sys.exit(1)


def ensure_write_access(*, context: str | None = None) -> None:
    """Exit early unless the caller belongs to a write-access kubernetes group.

    Claiming and deleting toolbox pods needs write RBAC, so a read-only identity
    would only fail later with an opaque permission error. We check group
    membership from ``kubectl auth whoami`` up front and bail out with an
    actionable message instead.
    """
    user_info = _get_user_info(context=context)
    groups = set(user_info.get("groups", []))

    if WRITE_ACCESS_GROUPS.isdisjoint(groups):
        print("\n❌ You don't have write access to this kubernetes cluster.")  # noqa: T201
        print(f"   Your groups: {sorted(groups) or '(none)'}")  # noqa: T201
        print(f"   Toolbox requires membership in one of: {sorted(WRITE_ACCESS_GROUPS)}")  # noqa: T201
        print(  # noqa: T201
            f"\n   You need to elevate your permissions with {ELEVATE_PERMISSIONS_CHANNEL} "
            "to k8s + toolbox (or admin) at least."
        )
        print(f"   Runbook: {TOOLBOX_ACCESS_RUNBOOK_URL}")  # noqa: T201
        sys.exit(1)


def get_current_user(*, claimed_label_key: str, context: str | None = None) -> dict:
    """Get user identity from kubectl auth and parse it into labels.

    Args:
        claimed_label_key: Label key under which the sanitized session name is
            placed in the returned dict. Pool-specific (e.g. ``toolbox-claimed``
            for the toolbox-django pool, ``flags-jumphost-claimed`` for the
            flags-cache-jumphost pool); see ``POOLS`` in ``toolbox.py``.
        context: Optional kubernetes context to scope the whoami call to,
            instead of relying on the default kubeconfig context.
    """
    user_info = _get_user_info(context=context)

    # First try to get the ARN from the extra info
    if "extra" in user_info and "arn" in user_info["extra"]:
        return parse_arn(user_info["extra"]["arn"][0], claimed_label_key=claimed_label_key)  # ARN is in a list

    # Fallback to sessionName if available
    if "extra" in user_info and "sessionName" in user_info["extra"]:
        return {claimed_label_key: sanitize_label(user_info["extra"]["sessionName"][0])}

    # Final fallback to username
    return {claimed_label_key: sanitize_label(f"k8s-user/{user_info['username']}")}


def parse_arn(arn: str, *, claimed_label_key: str) -> dict:
    """Parse AWS ARN into components."""
    try:
        # Handle AWS STS assumed-role ARN format
        # Format: arn:aws:sts::ACCOUNT:assumed-role/AWSReservedSSO_developers_0847e649a00cc5e7/michael.k@posthog.com
        parts = arn.split(":")
        if len(parts) != 6 or "assumed-role" not in parts[5]:
            return {claimed_label_key: sanitize_label(arn)}  # fallback for unexpected format

        # Extract role path and session name
        role_and_session = parts[5].split("/")
        if len(role_and_session) < 3:
            return {claimed_label_key: sanitize_label(arn)}

        role_path = role_and_session[1]  # The full role path (e.g. AWSReservedSSO_developers_0847e649a00cc5e7)
        session_name = role_and_session[2]  # The session name (email)

        # Extract role name from the role path (e.g. "developers" from "AWSReservedSSO_developers_0847e649a00cc5e7")
        role_parts = role_path.split("_")
        if len(role_parts) < 2:
            return {claimed_label_key: sanitize_label(arn)}  # fallback for unexpected format
        role_name = role_parts[1]  # For AWSReservedSSO_* format

        # Sanitize values for kubernetes labels
        session_name = sanitize_label(session_name)
        role_name = sanitize_label(role_name)

        print(f"Parsed ARN: session_name={session_name}, role_name={role_name}")  # noqa: T201

        return {
            claimed_label_key: session_name,  # The sanitized email address
            "role-name": role_name,  # The role name (e.g. "developers")
            "assumed-role": "true",
        }
    except Exception as e:
        print(f"Warning: Failed to parse ARN ({e}), using fallback format")  # noqa: T201
        return {claimed_label_key: sanitize_label(arn)}  # fallback for any parsing errors


def sanitize_label(value: str) -> str:
    """Sanitize a value to be a valid kubernetes label value (RFC 1123)."""
    # Replace @ with _at_ and keep dots
    sanitized = value.replace("@", "_at_")
    # Only allow alphanumeric, '-', '_', '.'
    sanitized = re.sub(r"[^A-Za-z0-9_.-]", "_", sanitized)
    # Must start and end with alphanumeric
    sanitized = re.sub(r"^[^A-Za-z0-9]+", "", sanitized)
    sanitized = re.sub(r"[^A-Za-z0-9]+$", "", sanitized)

    # If longer than 63 chars, keep the start and end parts
    if len(sanitized) > 63:
        # Keep first 31 chars and last 31 chars with a single underscore in between
        sanitized = sanitized[:31] + "_" + sanitized[-31:]

    # If after truncation it ends or starts with non-alphanumeric, strip again
    sanitized = re.sub(r"^[^A-Za-z0-9]+", "", sanitized)
    sanitized = re.sub(r"[^A-Za-z0-9]+$", "", sanitized)
    return sanitized
