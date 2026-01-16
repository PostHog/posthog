#!/usr/bin/env python3
"""
Feature Flags Explorer

An interactive tool for setting up feature flags and exploring the /flags endpoint.
Designed for developers working on PostHog's feature flags service.

Usage:
    ./flags_test_tool.py              # Show status and guide
    ./flags_test_tool.py setup        # Setup standard test flags
    ./flags_test_tool.py examples     # Interactive exploration
    ./flags_test_tool.py call         # Make custom API calls

No external dependencies - uses only Python standard library.
"""

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

SCRIPT_DIR = Path(__file__).parent
FLAGS_DEFINITION_FILE = SCRIPT_DIR / "standard_flags_definition.json"
ENV_FILE = SCRIPT_DIR / ".env"
ENV_EXAMPLE_FILE = SCRIPT_DIR / ".env.example"

# ANSI colors for terminal output
COLORS = {
    "red": "\033[0;31m",
    "green": "\033[0;32m",
    "yellow": "\033[1;33m",
    "blue": "\033[0;34m",
    "cyan": "\033[0;36m",
    "dim": "\033[2m",
    "bold": "\033[1m",
    "reset": "\033[0m",
}


def color(text: str, color_name: str) -> str:
    """Apply ANSI color to text if stdout is a terminal."""
    if sys.stdout.isatty():
        return f"{COLORS.get(color_name, '')}{text}{COLORS['reset']}"
    return text


def prompt_yes_no(question: str, default: bool = True) -> bool:
    """Prompt user for yes/no confirmation."""
    suffix = "[Y/n]" if default else "[y/N]"
    try:
        response = input(f"{question} {suffix} ").strip().lower()
        if not response:
            return default
        return response in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def load_env_file(env_path: Path) -> Dict[str, str]:
    """Load environment variables from a .env file."""
    env_vars: Dict[str, str] = {}
    if not env_path.exists():
        return env_vars

    with open(env_path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" in line:
                key, _, value = line.partition("=")
                key = key.strip()
                value = value.strip()
                if (value.startswith('"') and value.endswith('"')) or (
                    value.startswith("'") and value.endswith("'")
                ):
                    value = value[1:-1]
                env_vars[key] = value
    return env_vars


def http_request(
    url: str,
    method: str = "GET",
    data: Optional[Dict[str, Any]] = None,
    headers: Optional[Dict[str, str]] = None,
    timeout: int = 30,
) -> Tuple[int, Union[Dict[str, Any], str]]:
    """Make an HTTP request using only standard library."""
    headers = headers or {}
    headers.setdefault("Content-Type", "application/json")

    body = None
    if data is not None:
        body = json.dumps(data).encode("utf-8")

    req = urllib.request.Request(url, data=body, headers=headers, method=method)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            response_body = response.read().decode("utf-8")
            try:
                return response.status, json.loads(response_body)
            except json.JSONDecodeError:
                return response.status, response_body
    except urllib.error.HTTPError as e:
        response_body = e.read().decode("utf-8")
        try:
            return e.code, json.loads(response_body)
        except json.JSONDecodeError:
            return e.code, response_body
    except urllib.error.URLError as e:
        raise ConnectionError(f"Could not connect to {url}: {e.reason}")


class PostHogClient:
    """Simple client for PostHog API operations."""

    def __init__(self, host: str, personal_api_key: str, project_api_key: Optional[str] = None):
        self.host = host.rstrip("/")
        self.personal_api_key = personal_api_key
        self.project_api_key = project_api_key
        self.headers = {"Authorization": f"Bearer {personal_api_key}"}
        self._project_id: Optional[int] = None

    def _api_request(
        self, method: str, endpoint: str, data: Optional[Dict[str, Any]] = None
    ) -> Tuple[int, Any]:
        url = f"{self.host}{endpoint}"
        return http_request(url, method=method, data=data, headers=self.headers)

    def get_current_project(self) -> Dict[str, Any]:
        status, response = self._api_request("GET", "/api/projects/")
        if status != 200:
            raise RuntimeError(f"Failed to get projects: {response}")
        projects = response.get("results", [])
        if not projects:
            raise RuntimeError("No projects found. Please create a project first.")
        return projects[0]

    @property
    def project_id(self) -> int:
        if self._project_id is None:
            project = self.get_current_project()
            self._project_id = project["id"]
        return self._project_id

    def list_feature_flags(self) -> List[Dict[str, Any]]:
        status, response = self._api_request("GET", f"/api/projects/{self.project_id}/feature_flags/")
        if status != 200:
            raise RuntimeError(f"Failed to list flags: {response}")
        return response.get("results", [])

    def create_feature_flag(self, flag_data: Dict[str, Any]) -> Dict[str, Any]:
        status, response = self._api_request(
            "POST", f"/api/projects/{self.project_id}/feature_flags/", data=flag_data
        )
        if status not in (200, 201):
            raise RuntimeError(f"Failed to create flag '{flag_data.get('key')}': {response}")
        return response

    def update_feature_flag(self, flag_id: int, flag_data: Dict[str, Any]) -> Dict[str, Any]:
        status, response = self._api_request(
            "PATCH", f"/api/projects/{self.project_id}/feature_flags/{flag_id}/", data=flag_data
        )
        if status != 200:
            raise RuntimeError(f"Failed to update flag: {response}")
        return response

    def delete_feature_flag(self, flag_id: int) -> None:
        status, response = self._api_request(
            "PATCH", f"/api/projects/{self.project_id}/feature_flags/{flag_id}/", data={"deleted": True}
        )
        if status != 200:
            raise RuntimeError(f"Failed to delete flag: {response}")


def load_flags_definition() -> Dict[str, Any]:
    """Load the standard flags definition from JSON file."""
    if not FLAGS_DEFINITION_FILE.exists():
        raise FileNotFoundError(f"Flags definition file not found: {FLAGS_DEFINITION_FILE}")
    with open(FLAGS_DEFINITION_FILE) as f:
        return json.load(f)


def prepare_flag_for_api(flag_spec: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a flag specification to API-compatible format."""
    api_flag = {
        "key": flag_spec["key"],
        "name": flag_spec.get("name", flag_spec["key"]),
        "active": flag_spec.get("active", True),
        "filters": flag_spec.get("filters", {"groups": [{"properties": [], "rollout_percentage": 100}]}),
    }
    if "ensure_experience_continuity" in flag_spec:
        api_flag["ensure_experience_continuity"] = flag_spec["ensure_experience_continuity"]
    if "bucketing_identifier" in flag_spec:
        api_flag["bucketing_identifier"] = flag_spec["bucketing_identifier"]
    return api_flag


def get_standard_flag_keys() -> List[str]:
    """Get the list of standard flag keys from the definition file."""
    try:
        definition = load_flags_definition()
        return [f["key"] for f in definition.get("flags", [])]
    except Exception:
        return []


def load_config() -> Dict[str, Any]:
    """Load configuration from .env file and environment variables."""
    env_vars = load_env_file(ENV_FILE)
    return {
        "POSTHOG_HOST": os.environ.get("POSTHOG_HOST", env_vars.get("POSTHOG_HOST", "http://localhost:8010")),
        "POSTHOG_RUST_SERVICE_HOST": os.environ.get(
            "POSTHOG_RUST_SERVICE_HOST", env_vars.get("POSTHOG_RUST_SERVICE_HOST", "http://localhost:3001")
        ),
        "POSTHOG_PERSONAL_API_KEY": os.environ.get(
            "POSTHOG_PERSONAL_API_KEY", env_vars.get("POSTHOG_PERSONAL_API_KEY")
        ),
        "POSTHOG_PROJECT_API_KEY": os.environ.get(
            "POSTHOG_PROJECT_API_KEY", env_vars.get("POSTHOG_PROJECT_API_KEY")
        ),
    }


def check_standard_flags_exist(config: Dict[str, Any]) -> Tuple[int, int, List[str]]:
    """
    Check how many standard flags exist.
    Returns: (existing_count, total_count, missing_keys)
    """
    personal_api_key = config.get("POSTHOG_PERSONAL_API_KEY")
    if not personal_api_key:
        return 0, 0, []

    try:
        client = PostHogClient(config["POSTHOG_HOST"], personal_api_key)
        existing_flags = {flag["key"] for flag in client.list_feature_flags()}
        standard_keys = get_standard_flag_keys()

        if not standard_keys:
            return 0, 0, []

        missing = [k for k in standard_keys if k not in existing_flags]
        existing_count = len(standard_keys) - len(missing)
        return existing_count, len(standard_keys), missing
    except Exception:
        return 0, 0, []


def ensure_standard_flags_exist(config: Dict[str, Any], auto_setup: bool = False) -> bool:
    """
    Check if standard flags exist, and offer to create them if not.
    Returns True if flags are ready, False if user declined setup.
    """
    existing, total, missing = check_standard_flags_exist(config)

    if total == 0:
        return True  # Can't check, proceed anyway

    if existing == total:
        return True  # All flags exist

    if existing == 0:
        print(color("Standard test flags are not set up yet.", "yellow"))
    else:
        print(color(f"Some standard flags are missing ({existing}/{total} exist).", "yellow"))

    if auto_setup:
        print("Setting up standard flags...")
        return run_setup_flags(config, force=False, verbose=False) == 0

    if prompt_yes_no("Would you like to set them up now?"):
        return run_setup_flags(config, force=False, verbose=False) == 0

    print(color("Continuing without standard flags. Some features may not work as expected.", "dim"))
    return True


def run_setup_flags(config: Dict[str, Any], force: bool = False, verbose: bool = False) -> int:
    """Run the flag setup process. Returns 0 on success."""
    personal_api_key = config.get("POSTHOG_PERSONAL_API_KEY")
    if not personal_api_key:
        print(color("Error: POSTHOG_PERSONAL_API_KEY is required for setup", "red"))
        print(f"Create a personal API key at: {config['POSTHOG_HOST']}/settings/user-api-keys")
        return 1

    host = config["POSTHOG_HOST"]
    print(f"Connecting to PostHog at {host}...")

    try:
        client = PostHogClient(host, personal_api_key, config.get("POSTHOG_PROJECT_API_KEY"))
        project = client.get_current_project()
        print(f"Using project: {project.get('name', 'Unknown')} (ID: {client.project_id})")
    except ConnectionError as e:
        print(color(f"Error: {e}", "red"))
        print("Make sure PostHog is running (./bin/start)")
        return 1
    except RuntimeError as e:
        print(color(f"Error: {e}", "red"))
        return 1

    try:
        definition = load_flags_definition()
        flags_spec = definition.get("flags", [])
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(color(f"Error loading flags definition: {e}", "red"))
        return 1

    print(f"Loaded {len(flags_spec)} flag definitions")

    existing_flags = {flag["key"]: flag for flag in client.list_feature_flags()}
    results: Dict[str, List[str]] = {"created": [], "updated": [], "errors": []}

    for flag_spec in flags_spec:
        key = flag_spec["key"]
        api_flag = prepare_flag_for_api(flag_spec)

        try:
            if key in existing_flags:
                if force:
                    client.delete_feature_flag(existing_flags[key]["id"])
                    client.create_feature_flag(api_flag)
                    results["created"].append(key)
                else:
                    client.update_feature_flag(existing_flags[key]["id"], api_flag)
                    results["updated"].append(key)
            else:
                client.create_feature_flag(api_flag)
                results["created"].append(key)
        except RuntimeError as e:
            results["errors"].append(f"{key}: {e}")

    # Summary
    if results["created"]:
        print(color(f"Created {len(results['created'])} flags", "green"))
    if results["updated"]:
        print(f"Updated {len(results['updated'])} flags")
    if results["errors"]:
        print(color(f"Errors: {len(results['errors'])}", "red"))
        for error in results["errors"]:
            print(f"  - {error}")

    if not results["errors"]:
        print(color("Setup complete!", "green"))

    return 0 if not results["errors"] else 1


# =============================================================================
# Display helpers
# =============================================================================


def visible_len(text: str) -> int:
    """Calculate visible length of string (excluding ANSI codes)."""
    ansi_escape = re.compile(r'\x1b\[[0-9;]*m')
    return len(ansi_escape.sub('', text))


def pad_to_width(text: str, width: int) -> str:
    """Pad a string (possibly with ANSI codes) to a given visible width."""
    visible = visible_len(text)
    if visible >= width:
        return text
    return text + " " * (width - visible)


def format_flag_value(flag_data: Optional[Dict[str, Any]], max_width: int = 20) -> str:
    """Format a flag value for table display."""
    if flag_data is None:
        return color("—", "dim")

    if not isinstance(flag_data, dict):
        return str(flag_data)[:max_width]

    variant = flag_data.get("variant")
    enabled = flag_data.get("enabled", False)

    if variant:
        return color(str(variant)[:max_width], "green")
    elif enabled:
        return color("true", "green")
    else:
        return color("false", "red")


def format_flag_reason(flag_data: Optional[Dict[str, Any]], max_width: int = 20) -> str:
    """Format a flag reason for table display."""
    if flag_data is None:
        return color("not found", "dim")

    reason = flag_data.get("reason", {})
    code = reason.get("code", "unknown")

    short_reasons = {
        "condition_match": "match",
        "no_condition_match": "no match",
        "out_of_rollout_bound": "out of rollout",
        "no_group_type": "no group type",
        "disabled": "disabled",
    }
    display = short_reasons.get(code, code)
    return display[:max_width]


def get_flag_value_key(flag_data: Optional[Dict[str, Any]]) -> str:
    """Get a comparable key for a flag's value."""
    if flag_data is None:
        return "none"
    variant = flag_data.get("variant")
    if variant:
        return f"variant:{variant}"
    return f"enabled:{flag_data.get('enabled', False)}"


def print_flags_table(
    flags_response: Dict[str, Any],
    standard_flags: List[str],
    previous_response: Optional[Dict[str, Any]] = None,
    show_only_changed: bool = False,
    filter_category: Optional[str] = None,
) -> int:
    """Print a table showing all standard flags and their values.

    Returns the number of flags that changed from previous response.
    """
    flags = flags_response.get("flags", {})
    prev_flags = previous_response.get("flags", {}) if previous_response else {}

    # Category filters
    categories = {
        "boolean": ["simple-boolean", "rollout-percentage", "disabled-flag"],
        "string": ["string-match-exact", "string-match-contains", "string-match-regex",
                   "string-not-contains", "list-match-exact"],
        "numeric": ["numeric-greater-than", "numeric-less-than", "numeric-gte", "numeric-lte"],
        "property": ["property-is-set", "property-is-not-set"],
        "date": ["date-before", "date-after", "date-relative"],
        "multivariate": ["multivariate-simple", "multivariate-multiple", "multivariate-override"],
        "payload": ["payload-json-object", "payload-json-array", "payload-numeric",
                    "payload-boolean", "payload-string"],
        "condition": ["multiple-conditions-and", "multiple-conditions-or"],
        "advanced": ["geo-based", "group-based", "experience-continuity", "custom-bucketing"],
    }

    # Filter flags if category specified
    if filter_category and filter_category in categories:
        display_flags = [f for f in standard_flags if f in categories[filter_category]]
    else:
        display_flags = standard_flags

    col_marker = 2
    col_flag = 28
    col_value = 18
    col_reason = 14
    total_width = col_marker + col_flag + col_value + col_reason + 3

    print("─" * total_width)
    header = f"  {pad_to_width(color('Flag', 'cyan'), col_flag)} "
    header += f"{pad_to_width(color('Value', 'cyan'), col_value)} "
    header += color("Reason", "cyan")
    print(header)
    print("─" * total_width)

    changed_count = 0
    for flag_key in display_flags:
        flag_data = flags.get(flag_key)
        prev_data = prev_flags.get(flag_key)

        # Check if value changed
        current_key = get_flag_value_key(flag_data)
        prev_key = get_flag_value_key(prev_data) if prev_flags else current_key
        changed = current_key != prev_key

        if changed:
            changed_count += 1

        # Skip unchanged flags if only showing changes
        if show_only_changed and not changed:
            continue

        value_str = format_flag_value(flag_data, col_value)
        reason_str = format_flag_reason(flag_data, col_reason)

        # Marker for changed flags
        if changed and prev_flags:
            marker = color("→ ", "yellow")
        else:
            marker = "  "

        flag_col = f"{flag_key:<{col_flag}}"
        value_col = pad_to_width(value_str, col_value)
        print(f"{marker}{flag_col} {value_col} {reason_str}")

    print("─" * total_width)

    if changed_count > 0 and prev_flags:
        print(color(f"  → {changed_count} flag(s) changed from previous request", "yellow"))

    return changed_count


def print_request_header(
    title: str,
    description: str,
    distinct_id: str,
    person_properties: Optional[Dict[str, Any]] = None,
    groups: Optional[Dict[str, str]] = None,
) -> None:
    """Print a formatted request header."""
    print(f"\n{color(title, 'green')}")
    print(color(description, "dim"))
    print()

    print(color("Request:", "blue"))
    print(f"  distinct_id: {color(distinct_id, 'cyan')}")
    if person_properties:
        props_str = json.dumps(person_properties)
        if len(props_str) > 60:
            props_str = props_str[:57] + "..."
        print(f"  person_properties: {props_str}")
    if groups:
        print(f"  groups: {json.dumps(groups)}")
    print()


def call_flags_endpoint(
    host: str,
    api_key: str,
    distinct_id: str,
    person_properties: Optional[Dict[str, Any]] = None,
    groups: Optional[Dict[str, str]] = None,
    group_properties: Optional[Dict[str, Dict[str, Any]]] = None,
    flag_to_check: Optional[str] = None,
    show_table: bool = False,
    standard_flags: Optional[List[str]] = None,
    previous_response: Optional[Dict[str, Any]] = None,
    show_only_changed: bool = False,
    filter_category: Optional[str] = None,
    verbose: bool = True,
) -> Dict[str, Any]:
    """Call the /flags endpoint and display request/response."""
    url = f"{host}/flags"

    payload: Dict[str, Any] = {
        "token": api_key,
        "distinct_id": distinct_id,
    }
    if person_properties:
        payload["person_properties"] = person_properties
    if groups:
        payload["groups"] = groups
    if group_properties:
        payload["group_properties"] = group_properties

    status, response = http_request(url, method="POST", data=payload)

    if verbose and not show_table:
        display_payload = payload.copy()
        display_payload["token"] = api_key[:10] + "..." if len(api_key) > 10 else api_key
        print(color("Request:", "blue"))
        print(f"  POST {url}")
        print(f"  {json.dumps(display_payload)}")
        print(color("Response:", "blue"))

        if status != 200:
            print(color(f"  Error (status={status}): {response}", "red"))
        elif isinstance(response, dict) and "flags" in response:
            flags = response.get("flags", {})
            if flag_to_check and flag_to_check in flags:
                flag_data = flags[flag_to_check]
                value = format_flag_value(flag_data, 30)
                reason = format_flag_reason(flag_data, 30)
                print(f"  {color(flag_to_check, 'cyan')}: {value} ({reason})")
                # Show payload if present
                payload_data = flag_data.get("metadata", {}).get("payload")
                if payload_data is not None:
                    print(f"  {color('payload:', 'dim')} {json.dumps(payload_data)}")
            elif flag_to_check:
                print(f"  {color(flag_to_check, 'yellow')}: not found (inactive or doesn't exist)")
            else:
                print(f"  Returned {len(flags)} flags")
                print(color("  (use -f FLAG_KEY to see a specific flag, or -t for table view)", "dim"))
        else:
            print(f"  {response}")

    elif show_table and standard_flags:
        if status != 200:
            print(color(f"Error (status={status}): {response}", "red"))
        elif isinstance(response, dict):
            print_flags_table(
                response,
                standard_flags,
                previous_response=previous_response,
                show_only_changed=show_only_changed,
                filter_category=filter_category,
            )

    return response


# =============================================================================
# Commands
# =============================================================================


def cmd_status(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Show current status and configuration."""
    print(color("Feature Flags Explorer - Status", "bold"))
    print("─" * 50)

    # Configuration
    print(color("\nConfiguration:", "blue"))
    print(f"  PostHog host:     {config['POSTHOG_HOST']}")
    print(f"  Rust service:     {config['POSTHOG_RUST_SERVICE_HOST']}")

    has_personal_key = bool(config.get("POSTHOG_PERSONAL_API_KEY"))
    has_project_key = bool(config.get("POSTHOG_PROJECT_API_KEY"))

    key_status = color("configured", "green") if has_personal_key else color("missing", "red")
    print(f"  Personal API key: {key_status}")

    key_status = color("configured", "green") if has_project_key else color("missing", "red")
    print(f"  Project API key:  {key_status}")

    # Connection test
    print(color("\nConnectivity:", "blue"))
    for name, host in [("PostHog", config["POSTHOG_HOST"]), ("Rust service", config["POSTHOG_RUST_SERVICE_HOST"])]:
        try:
            http_request(f"{host}/flags", method="POST", data={"token": "test", "distinct_id": "test"}, timeout=5)
            print(f"  {name}: {color('reachable', 'green')}")
        except Exception:
            print(f"  {name}: {color('not reachable', 'red')}")

    # Standard flags
    print(color("\nStandard flags:", "blue"))
    existing, total, missing = check_standard_flags_exist(config)
    if total == 0:
        if not has_personal_key:
            print(f"  Cannot check (personal API key required)")
        else:
            print(f"  Cannot check")
    elif existing == total:
        print(f"  {color(f'All {total} flags are set up', 'green')}")
    elif existing == 0:
        print(f"  {color('Not set up', 'yellow')} (run: ./flags_test_tool.py setup)")
    else:
        print(f"  {color(f'{existing}/{total} flags exist', 'yellow')}")
        print(f"  Missing: {', '.join(missing[:5])}{'...' if len(missing) > 5 else ''}")

    # Next steps
    if not has_personal_key or not has_project_key:
        print(color("\nSetup required:", "yellow"))
        if not ENV_FILE.exists():
            print(f"  1. Copy .env.example to .env")
            print(f"     cp {ENV_EXAMPLE_FILE} {ENV_FILE}")
        print(f"  2. Add your API keys to .env")
        print(f"     Personal key: {config['POSTHOG_HOST']}/settings/user-api-keys")
        print(f"     Project key:  {config['POSTHOG_HOST']}/settings/project#variables")
    elif existing < total:
        print(color("\nNext step:", "green"))
        print("  ./flags_test_tool.py setup    # Set up standard flags")
    else:
        print(color("\nReady to explore:", "green"))
        print("  ./flags_test_tool.py examples")

    return 0


def cmd_setup(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Setup standard feature flags."""
    personal_api_key = config.get("POSTHOG_PERSONAL_API_KEY")
    if not personal_api_key:
        print(color("Error: POSTHOG_PERSONAL_API_KEY is required for setup", "red"))
        print(f"\nTo get started:")
        print(f"  1. Create a personal API key at: {config['POSTHOG_HOST']}/settings/user-api-keys")
        print(f"  2. Add it to your .env file: POSTHOG_PERSONAL_API_KEY=phx_your_key_here")
        return 1

    if args.check_only:
        existing, total, missing = check_standard_flags_exist(config)
        if total == 0:
            print("Could not load flag definitions")
            return 1

        print(f"Standard flags: {existing}/{total} exist")
        if missing:
            print(f"Missing: {', '.join(missing)}")
        return 0 if not missing else 1

    return run_setup_flags(config, force=args.force, verbose=args.verbose)


def get_flag_scenarios() -> Dict[str, Dict[str, Any]]:
    """Get matching and non-matching scenarios for each flag."""
    return {
        "simple-boolean": {
            "description": "Always returns true (100% rollout, no conditions)",
            "match": {"distinct_id": "any-user"},
            "match_why": "No conditions, 100% rollout - always matches",
            "no_match": None,  # Cannot fail to match
            "no_match_why": None,
        },
        "rollout-percentage": {
            "description": "50% rollout based on hash of distinct_id",
            "match": {"distinct_id": "user-in-rollout"},  # Pre-tested to be in rollout
            "match_why": "This distinct_id hashes into the 50% rollout",
            "no_match": {"distinct_id": "user-out-of-rollout-xyz"},
            "no_match_why": "This distinct_id hashes outside the 50% rollout",
        },
        "disabled-flag": {
            "description": "Inactive flag - always returns false/undefined",
            "match": None,
            "match_why": None,
            "no_match": {"distinct_id": "any-user"},
            "no_match_why": "Flag is inactive (active=false)",
        },
        "string-match-exact": {
            "description": "Exact string match: email = 'test@posthog.com'",
            "match": {"distinct_id": "user-1", "person_properties": {"email": "test@posthog.com"}},
            "match_why": "Email exactly matches 'test@posthog.com'",
            "no_match": {"distinct_id": "user-2", "person_properties": {"email": "other@posthog.com"}},
            "no_match_why": "Email doesn't exactly match (case-sensitive)",
        },
        "string-match-contains": {
            "description": "Case-insensitive contains: email icontains '@posthog.com'",
            "match": {"distinct_id": "user-1", "person_properties": {"email": "Developer@PostHog.com"}},
            "match_why": "Email contains '@posthog.com' (case-insensitive)",
            "no_match": {"distinct_id": "user-2", "person_properties": {"email": "user@gmail.com"}},
            "no_match_why": "Email doesn't contain '@posthog.com'",
        },
        "string-match-regex": {
            "description": "Regex match: email matches '^[a-z]+@posthog\\.com$'",
            "match": {"distinct_id": "user-1", "person_properties": {"email": "alice@posthog.com"}},
            "match_why": "Email matches regex (lowercase letters only before @)",
            "no_match": {"distinct_id": "user-2", "person_properties": {"email": "Alice123@posthog.com"}},
            "no_match_why": "Email has uppercase/numbers, doesn't match regex",
        },
        "string-not-contains": {
            "description": "Negation: email not_icontains 'spam'",
            "match": {"distinct_id": "user-1", "person_properties": {"email": "user@example.com"}},
            "match_why": "Email doesn't contain 'spam'",
            "no_match": {"distinct_id": "user-2", "person_properties": {"email": "spam-user@example.com"}},
            "no_match_why": "Email contains 'spam'",
        },
        "list-match-exact": {
            "description": "List match: plan in ['enterprise', 'business', 'startup']",
            "match": {"distinct_id": "user-1", "person_properties": {"plan": "enterprise"}},
            "match_why": "Plan 'enterprise' is in the allowed list",
            "no_match": {"distinct_id": "user-2", "person_properties": {"plan": "free"}},
            "no_match_why": "Plan 'free' is not in the allowed list",
        },
        "numeric-greater-than": {
            "description": "Numeric comparison: age > 18",
            "match": {"distinct_id": "user-1", "person_properties": {"age": 25}},
            "match_why": "Age 25 is greater than 18",
            "no_match": {"distinct_id": "user-2", "person_properties": {"age": 18}},
            "no_match_why": "Age 18 is NOT greater than 18 (must be >)",
        },
        "numeric-less-than": {
            "description": "Numeric comparison: age < 65",
            "match": {"distinct_id": "user-1", "person_properties": {"age": 30}},
            "match_why": "Age 30 is less than 65",
            "no_match": {"distinct_id": "user-2", "person_properties": {"age": 70}},
            "no_match_why": "Age 70 is not less than 65",
        },
        "numeric-gte": {
            "description": "Numeric comparison: usage_count >= 1000",
            "match": {"distinct_id": "user-1", "person_properties": {"usage_count": 1000}},
            "match_why": "Usage 1000 equals the threshold (>= includes equality)",
            "no_match": {"distinct_id": "user-2", "person_properties": {"usage_count": 999}},
            "no_match_why": "Usage 999 is below 1000",
        },
        "numeric-lte": {
            "description": "Numeric comparison: error_rate <= 5",
            "match": {"distinct_id": "user-1", "person_properties": {"error_rate": 3}},
            "match_why": "Error rate 3 is at or below 5",
            "no_match": {"distinct_id": "user-2", "person_properties": {"error_rate": 10}},
            "no_match_why": "Error rate 10 exceeds 5",
        },
        "property-is-set": {
            "description": "Property existence: premium_user is_set",
            "match": {"distinct_id": "user-1", "person_properties": {"premium_user": True}},
            "match_why": "Property 'premium_user' exists (value doesn't matter)",
            "no_match": {"distinct_id": "user-2", "person_properties": {"other_prop": True}},
            "no_match_why": "Property 'premium_user' is not set",
        },
        "property-is-not-set": {
            "description": "Property absence: opted_out is_not_set",
            "match": {"distinct_id": "user-1", "person_properties": {"email": "user@example.com"}},
            "match_why": "Property 'opted_out' is not present",
            "no_match": {"distinct_id": "user-2", "person_properties": {"opted_out": True}},
            "no_match_why": "Property 'opted_out' exists",
        },
        "date-before": {
            "description": "Date comparison: signup_date is_date_before '2025-01-01'",
            "match": {"distinct_id": "user-1", "person_properties": {"signup_date": "2024-06-15T00:00:00Z"}},
            "match_why": "Signup date (2024-06-15) is before 2025-01-01",
            "no_match": {"distinct_id": "user-2", "person_properties": {"signup_date": "2025-06-15T00:00:00Z"}},
            "no_match_why": "Signup date (2025-06-15) is after 2025-01-01",
        },
        "date-after": {
            "description": "Date comparison: last_active is_date_after '2024-01-01'",
            "match": {"distinct_id": "user-1", "person_properties": {"last_active": "2024-06-15T00:00:00Z"}},
            "match_why": "Last active (2024-06-15) is after 2024-01-01",
            "no_match": {"distinct_id": "user-2", "person_properties": {"last_active": "2023-06-15T00:00:00Z"}},
            "no_match_why": "Last active (2023-06-15) is before 2024-01-01",
        },
        "date-relative": {
            "description": "Relative date: last_seen is_date_after '-7d' (within last 7 days)",
            "match": {"distinct_id": "user-1", "person_properties": {"last_seen": "2026-01-14T00:00:00Z"}},
            "match_why": "Last seen is within the last 7 days from now",
            "no_match": {"distinct_id": "user-2", "person_properties": {"last_seen": "2025-01-01T00:00:00Z"}},
            "no_match_why": "Last seen is more than 7 days ago",
        },
        "multivariate-simple": {
            "description": "2 variants: 'control' (50%) and 'test' (50%)",
            "match": {"distinct_id": "user-gets-control"},
            "match_why": "Returns 'control' or 'test' based on hash - always matches one",
            "no_match": None,
            "no_match_why": None,
        },
        "multivariate-multiple": {
            "description": "4 variants: 'control', 'variant-a', 'variant-b', 'variant-c' (25% each)",
            "match": {"distinct_id": "user-abc"},
            "match_why": "Returns one of 4 variants based on hash distribution",
            "no_match": None,
            "no_match_why": None,
        },
        "multivariate-override": {
            "description": "Variant override: alpha@example.com -> 'alpha', beta@example.com -> 'beta'",
            "match": {"distinct_id": "user-1", "person_properties": {"email": "alpha@example.com"}},
            "match_why": "Email matches override condition, forces 'alpha' variant",
            "no_match": {"distinct_id": "user-2", "person_properties": {"email": "other@example.com"}},
            "no_match_why": "No override match - falls through to random variant assignment",
        },
        "payload-json-object": {
            "description": "Flag with complex JSON payload containing nested config",
            "match": {"distinct_id": "any-user"},
            "match_why": "100% rollout with JSON payload",
            "no_match": None,
            "no_match_why": None,
        },
        "payload-json-array": {
            "description": "Flag with JSON array payload",
            "match": {"distinct_id": "any-user"},
            "match_why": "100% rollout with array payload",
            "no_match": None,
            "no_match_why": None,
        },
        "payload-numeric": {
            "description": "Flag with numeric payload (42)",
            "match": {"distinct_id": "any-user"},
            "match_why": "100% rollout with numeric payload",
            "no_match": None,
            "no_match_why": None,
        },
        "payload-boolean": {
            "description": "Flag with boolean payload (true)",
            "match": {"distinct_id": "any-user"},
            "match_why": "100% rollout with boolean payload",
            "no_match": None,
            "no_match_why": None,
        },
        "payload-string": {
            "description": "Flag with string-wrapped payload",
            "match": {"distinct_id": "any-user"},
            "match_why": "100% rollout with string payload",
            "no_match": None,
            "no_match_why": None,
        },
        "multiple-conditions-and": {
            "description": "AND logic: plan in [enterprise,business] AND age >= 18 AND country = 'US'",
            "match": {"distinct_id": "user-1", "person_properties": {"plan": "enterprise", "age": 25, "country": "US"}},
            "match_why": "All three conditions match",
            "no_match": {"distinct_id": "user-2", "person_properties": {"plan": "enterprise", "age": 25, "country": "UK"}},
            "no_match_why": "Country is UK, not US - fails one AND condition",
        },
        "multiple-conditions-or": {
            "description": "OR logic: is_admin=true OR is_beta_tester=true OR email contains @posthog.com",
            "match": {"distinct_id": "user-1", "person_properties": {"is_beta_tester": "true"}},
            "match_why": "Matches the beta_tester condition (any OR branch works)",
            "no_match": {"distinct_id": "user-2", "person_properties": {"email": "user@gmail.com"}},
            "no_match_why": "Not admin, not beta tester, email not @posthog.com",
        },
        "geo-based": {
            "description": "Geo targeting: city='Sydney' (100%) OR country in [US,GB,CA] (50%)",
            "match": {"distinct_id": "user-1", "person_properties": {"$geoip_city_name": "Sydney"}},
            "match_why": "City matches Sydney - 100% rollout for that condition",
            "no_match": {"distinct_id": "user-2", "person_properties": {"$geoip_city_name": "Berlin"}},
            "no_match_why": "City is Berlin, not Sydney, and no country match",
        },
        "group-based": {
            "description": "Group targeting: company.name='PostHog' OR company.plan in [enterprise,scale]",
            "match": {
                "distinct_id": "user-1",
                "groups": {"company": "posthog-inc"},
                "group_properties": {"company": {"name": "PostHog"}}
            },
            "match_why": "Company name matches 'PostHog'",
            "no_match": {"distinct_id": "user-2"},
            "no_match_why": "No company group provided",
        },
        "experience-continuity": {
            "description": "Experience continuity - consistent variant across devices/sessions",
            "match": {"distinct_id": "user-1"},
            "match_why": "Returns consistent variant for this user across sessions",
            "no_match": None,
            "no_match_why": None,
        },
        "custom-bucketing": {
            "description": "Uses device_id (not distinct_id) for variant bucketing",
            "match": {"distinct_id": "user-1"},
            "match_why": "Variant determined by device_id property, not distinct_id",
            "no_match": None,
            "no_match_why": None,
        },
    }


def print_flag_detail(
    flag_key: str,
    scenario: Dict[str, Any],
    host: str,
    api_key: str,
) -> None:
    """Print detailed information about a flag with match/no-match scenarios."""
    print(color("═" * 70, "blue"))
    print(color(f"  {flag_key}", "bold"))
    print(color("═" * 70, "blue"))
    print(f"\n{color('Definition:', 'cyan')} {scenario['description']}\n")

    # Match scenario
    if scenario.get("match"):
        print(color("✓ MATCHING scenario:", "green"))
        req = scenario["match"]
        print(f"  distinct_id: {req['distinct_id']}")
        if req.get("person_properties"):
            print(f"  person_properties: {json.dumps(req['person_properties'])}")
        if req.get("groups"):
            print(f"  groups: {json.dumps(req['groups'])}")

        # Make the call
        response = call_flags_endpoint(
            host, api_key,
            req["distinct_id"],
            req.get("person_properties"),
            req.get("groups"),
            req.get("group_properties"),
            flag_to_check=flag_key,
            verbose=False,
        )

        flags = response.get("flags", {})
        flag_data = flags.get(flag_key, {})
        value = format_flag_value(flag_data, 30)
        reason = format_flag_reason(flag_data, 30)
        print(f"  {color('Result:', 'dim')} {value} ({reason})")

        # Show payload if present
        payload = flag_data.get("metadata", {}).get("payload") if isinstance(flag_data, dict) else None
        if payload is not None:
            payload_str = json.dumps(payload)
            if len(payload_str) > 60:
                payload_str = payload_str[:57] + "..."
            print(f"  {color('Payload:', 'dim')} {payload_str}")

        print(f"  {color('Why:', 'dim')} {scenario['match_why']}")
    else:
        print(color("✓ MATCHING scenario:", "dim") + " (flag always matches or is inactive)")

    print()

    # No-match scenario
    if scenario.get("no_match"):
        print(color("✗ NON-MATCHING scenario:", "red"))
        req = scenario["no_match"]
        print(f"  distinct_id: {req['distinct_id']}")
        if req.get("person_properties"):
            print(f"  person_properties: {json.dumps(req['person_properties'])}")
        if req.get("groups"):
            print(f"  groups: {json.dumps(req['groups'])}")

        # Make the call
        response = call_flags_endpoint(
            host, api_key,
            req["distinct_id"],
            req.get("person_properties"),
            req.get("groups"),
            req.get("group_properties"),
            flag_to_check=flag_key,
            verbose=False,
        )

        flags = response.get("flags", {})
        flag_data = flags.get(flag_key, {})
        value = format_flag_value(flag_data, 30)
        reason = format_flag_reason(flag_data, 30)
        print(f"  {color('Result:', 'dim')} {value} ({reason})")
        print(f"  {color('Why:', 'dim')} {scenario['no_match_why']}")
    else:
        print(color("✗ NON-MATCHING scenario:", "dim") + " (flag cannot fail to match)")

    print()


def cmd_examples(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Run example /flags calls to explore the service."""
    project_api_key = config.get("POSTHOG_PROJECT_API_KEY")
    if not project_api_key:
        print(color("Error: POSTHOG_PROJECT_API_KEY is required", "red"))
        print(f"Find your project API key at: {config['POSTHOG_HOST']}/settings/project#variables")
        return 1

    # Check if standard flags exist
    if not ensure_standard_flags_exist(config):
        return 1

    # Determine which service to use (Rust by default)
    if args.python:
        host = config["POSTHOG_HOST"]
        service_name = "Python"
    else:
        host = config["POSTHOG_RUST_SERVICE_HOST"]
        service_name = "Rust"

    standard_flags = get_standard_flag_keys()
    scenarios = get_flag_scenarios()

    # Check if service is reachable
    try:
        http_request(f"{host}/flags", method="POST", data={"token": project_api_key, "distinct_id": "test"})
    except ConnectionError:
        print(color(f"\nCannot connect to {service_name} service at {host}", "red"))
        print("Make sure the service is running.")
        return 1

    # Table mode - show all flags at once with request scenarios
    if args.table:
        print(color("═" * 70, "blue"))
        print(color(f"  Feature Flags Explorer - {service_name} Service (Table View)", "bold"))
        print(color(f"  Endpoint: {host}/flags", "dim"))
        print(color("═" * 70, "blue"))

        table_examples = [
            {"title": "Baseline (no properties)", "distinct_id": "anonymous-user"},
            {"title": "PostHog email", "distinct_id": "user-1", "person_properties": {"email": "dev@posthog.com"}},
            {"title": "Numeric properties", "distinct_id": "user-2", "person_properties": {"age": 25, "usage_count": 1500, "error_rate": 2}},
            {"title": "Enterprise plan + US", "distinct_id": "user-3", "person_properties": {"plan": "enterprise", "age": 30, "country": "US"}},
            {"title": "Sydney geo", "distinct_id": "user-4", "person_properties": {"$geoip_city_name": "Sydney"}},
        ]

        previous_response: Optional[Dict[str, Any]] = None
        for example in table_examples:
            print(f"\n{color(example['title'], 'green')}")
            print(f"  distinct_id: {example['distinct_id']}")
            if example.get("person_properties"):
                print(f"  properties: {json.dumps(example['person_properties'])}")
            print()

            response = call_flags_endpoint(
                host, project_api_key,
                example["distinct_id"],
                example.get("person_properties"),
                show_table=True,
                standard_flags=standard_flags,
                previous_response=previous_response,
                filter_category=args.category if hasattr(args, 'category') else None,
                verbose=False,
            )
            previous_response = response

            if not args.all:
                try:
                    input(color("\n[Press Enter for next, Ctrl+C to stop] ", "dim"))
                except KeyboardInterrupt:
                    print("\n")
                    break
        return 0

    # Detail mode - show flags one by one
    print(color("═" * 70, "blue"))
    print(color(f"  Feature Flags Explorer - {service_name} Service", "bold"))
    print(color(f"  Endpoint: {host}/flags", "dim"))
    print(color("═" * 70, "blue"))

    # Filter to specific flag if provided
    if args.flag:
        if args.flag not in scenarios:
            print(color(f"\nUnknown flag: {args.flag}", "red"))
            print(f"Available flags: {', '.join(standard_flags)}")
            return 1
        flags_to_show = [args.flag]
    elif args.category:
        categories = {
            "boolean": ["simple-boolean", "rollout-percentage", "disabled-flag"],
            "string": ["string-match-exact", "string-match-contains", "string-match-regex",
                       "string-not-contains", "list-match-exact"],
            "numeric": ["numeric-greater-than", "numeric-less-than", "numeric-gte", "numeric-lte"],
            "property": ["property-is-set", "property-is-not-set"],
            "date": ["date-before", "date-after", "date-relative"],
            "multivariate": ["multivariate-simple", "multivariate-multiple", "multivariate-override"],
            "payload": ["payload-json-object", "payload-json-array", "payload-numeric",
                        "payload-boolean", "payload-string"],
            "condition": ["multiple-conditions-and", "multiple-conditions-or"],
            "advanced": ["geo-based", "group-based", "experience-continuity", "custom-bucketing"],
        }
        flags_to_show = categories.get(args.category, [])
        print(color(f"\nShowing {args.category} flags ({len(flags_to_show)} flags)", "dim"))
    else:
        flags_to_show = standard_flags

    for i, flag_key in enumerate(flags_to_show):
        if flag_key not in scenarios:
            continue

        print_flag_detail(flag_key, scenarios[flag_key], host, project_api_key)

        if not args.all and i < len(flags_to_show) - 1:
            try:
                input(color("[Press Enter for next flag, Ctrl+C to stop] ", "dim"))
            except KeyboardInterrupt:
                print("\n")
                break

    print(color("═" * 70, "blue"))
    print(color("  Commands:", "bold"))
    print(color("═" * 70, "blue"))
    print("  ./flags_test_tool.py examples --flag string-match-regex   # Explore one flag")
    print("  ./flags_test_tool.py examples --category numeric          # Explore category")
    print("  ./flags_test_tool.py examples --table                     # Table view")
    print("  ./flags_test_tool.py call -d 'user' -f 'payload-json-object'  # Custom call")
    print()

    return 0


def cmd_call(args: argparse.Namespace, config: Dict[str, Any]) -> int:
    """Make a custom /flags call."""
    project_api_key = config.get("POSTHOG_PROJECT_API_KEY")
    if not project_api_key:
        print(color("Error: POSTHOG_PROJECT_API_KEY is required", "red"))
        print(f"Find your project API key at: {config['POSTHOG_HOST']}/settings/project#variables")
        return 1

    if args.python:
        host = config["POSTHOG_HOST"]
    else:
        host = config["POSTHOG_RUST_SERVICE_HOST"]

    person_properties = None
    if args.props:
        try:
            person_properties = json.loads(args.props)
        except json.JSONDecodeError as e:
            print(color(f"Error parsing --props JSON: {e}", "red"))
            return 1

    groups = None
    if args.groups:
        try:
            groups = json.loads(args.groups)
        except json.JSONDecodeError as e:
            print(color(f"Error parsing --groups JSON: {e}", "red"))
            return 1

    group_properties = None
    if args.group_props:
        try:
            group_properties = json.loads(args.group_props)
        except json.JSONDecodeError as e:
            print(color(f"Error parsing --group-props JSON: {e}", "red"))
            return 1

    if args.table:
        # Check if standard flags exist when using table mode
        if not ensure_standard_flags_exist(config):
            return 1

        standard_flags = get_standard_flag_keys()
        service_name = "Python" if args.python else "Rust"
        print(color(f"\nFlags from {service_name} service ({host}/flags)", "blue"))
        print(color(f"distinct_id: {args.distinct_id}", "dim"))
        if person_properties:
            print(color(f"person_properties: {json.dumps(person_properties)}", "dim"))
        if groups:
            print(color(f"groups: {json.dumps(groups)}", "dim"))
        print()

        filter_cat = args.category if hasattr(args, 'category') else None
        if filter_cat:
            print(color(f"Filtering to: {filter_cat}", "dim"))

        call_flags_endpoint(
            host,
            project_api_key,
            args.distinct_id,
            person_properties,
            groups,
            group_properties,
            show_table=True,
            standard_flags=standard_flags,
            filter_category=filter_cat,
            verbose=False,
        )
    else:
        call_flags_endpoint(
            host,
            project_api_key,
            args.distinct_id,
            person_properties,
            groups,
            group_properties,
            args.flag,
            verbose=True,
        )

    return 0


# =============================================================================
# Main
# =============================================================================


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Feature Flags Explorer - Set up test flags and explore the /flags endpoint",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                       Show status and setup guide
  %(prog)s setup                                 Set up standard test flags

  %(prog)s examples                              Detailed flag-by-flag exploration
  %(prog)s examples --flag string-match-regex    Explore a specific flag
  %(prog)s examples --category numeric           Explore all flags in a category
  %(prog)s examples --table                      Quick table view of all flags
  %(prog)s examples --python                     Use Python service instead of Rust

  %(prog)s call -d "user-123" --table            See all flags for a user
  %(prog)s call -d "user" -f "payload-json-object"   Check specific flag with payload
  %(prog)s call -d "user" -p '{"age": 25}' --table   With custom properties

Categories: boolean, string, numeric, property, date, multivariate, payload, condition, advanced

Configuration:
  Copy .env.example to .env and add your API keys.
  Get keys from your PostHog instance settings.
        """,
    )

    subparsers = parser.add_subparsers(dest="command", help="Command to run")

    # Status command (default when no command given)
    subparsers.add_parser("status", help="Show current status and configuration")

    # Setup command
    setup_parser = subparsers.add_parser("setup", help="Set up standard test flags")
    setup_parser.add_argument("--check-only", action="store_true", help="Only check flag status, don't create")
    setup_parser.add_argument("--force", action="store_true", help="Recreate all flags from scratch")
    setup_parser.add_argument("--verbose", "-v", action="store_true", help="Show detailed output")

    # Examples command
    examples_parser = subparsers.add_parser("examples", help="Interactive flag exploration")
    examples_parser.add_argument("--python", action="store_true", help="Use Python service instead of Rust")
    examples_parser.add_argument("--all", action="store_true", help="Run all without pausing")
    examples_parser.add_argument("--table", action="store_true", help="Show all flags in table view")
    examples_parser.add_argument("--flag", "-f", help="Explore a specific flag")
    examples_parser.add_argument("--category", choices=["boolean", "string", "numeric", "property", "date",
                                 "multivariate", "payload", "condition", "advanced"],
                                 help="Filter to specific flag category")

    # Call command
    call_parser = subparsers.add_parser("call", help="Make a custom /flags API call")
    call_parser.add_argument("-d", "--distinct-id", required=True, help="User's distinct ID")
    call_parser.add_argument("-f", "--flag", help="Show specific flag only (includes payload)")
    call_parser.add_argument("-t", "--table", action="store_true", help="Show all standard flags as table")
    call_parser.add_argument("-p", "--props", help="Person properties as JSON")
    call_parser.add_argument("-g", "--groups", help="Groups as JSON")
    call_parser.add_argument("--group-props", help="Group properties as JSON")
    call_parser.add_argument("--python", action="store_true", help="Use Python service instead of Rust")
    call_parser.add_argument("--category", choices=["boolean", "string", "numeric", "property", "date",
                             "multivariate", "payload", "condition", "advanced"],
                             help="Filter to specific flag category")

    args = parser.parse_args()
    config = load_config()

    # Default to status command
    if not args.command:
        args.command = "status"

    if args.command == "status":
        return cmd_status(args, config)
    elif args.command == "setup":
        return cmd_setup(args, config)
    elif args.command == "examples":
        return cmd_examples(args, config)
    elif args.command == "call":
        return cmd_call(args, config)

    return 0


if __name__ == "__main__":
    sys.exit(main())
