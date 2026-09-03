# Toolbox CLI

The primary function is to help manage and connect to PostHog toolbox pods in a Kubernetes environment.

## Installation

1. Ensure you have Python 3.x installed on your system
2. Clone this repository or download `toolbox.py`
3. Install dependencies (the PostHog SDK, used for anonymous usage telemetry):

   ```bash
   pip install -r requirements.txt
   ```

4. Make the script executable (Unix-based systems):

   ```bash
   chmod +x toolbox.py
   ```

## Requirements

- Python 3.x
- kubectl installed and configured
- the PostHog Python SDK (`pip install -r requirements.txt`) — telemetry is skipped gracefully if it's missing
- a Fleet-managed kubeconfig with the standard PostHog contexts
- Tailscale installed and connected to the PostHog tailnet — the cluster endpoints are only reachable over it.
  The CLI checks this before doing anything else and tells you how to fix it.
  Set `TOOLBOX_SKIP_TAILSCALE_CHECK=1` to skip the check on hosts that reach the cluster some other way

## Usage

Run the script using Python:

```bash
python toolbox.py [flags]
```

Or directly (Unix-based systems):

```bash
./toolbox.py [flags]
```

### What it Does

The toolbox CLI:

1. Asks whether you need `dev`, `prod-eu`, or `prod-us`
2. Selects the least-privileged usable `-eks`, `-write`, or `-admin` context
3. Guides you through requesting `k8s + toolbox access` in `#aws-access` when needed,
   waits up to 10 minutes for approval, and continues automatically
4. Finds an available PostHog toolbox pod or connects to one you've already claimed
5. Claims the pod for a specified duration (default 12 hours)
6. Provides an interactive shell session to the pod
7. Offers to delete the pod when you exit the shell

### Available Flags

| Flag                     | Description                                      | Default |
| ------------------------ | ------------------------------------------------ | ------- |
| `--claim-duration HOURS` | Number of hours to claim the pod for             | 12      |
| `--update-claim`         | Update the termination time of your existing pod | False   |

Set `KUBE_CONTEXT` to bypass environment selection for expert workflows. The context is scoped to this process and
must have the pod permissions required by the toolbox; the CLI never changes your global current context.

### Examples

1. Connect to a pod with default 12-hour claim:

```bash
python toolbox.py
```

2. Connect to a pod with a custom claim duration:

```bash
python toolbox.py --claim-duration 4
```

3. Extend the duration of your existing pod:

```bash
python toolbox.py --update-claim --claim-duration 24
```

### Notes

- If no pods are available, the script will wait up to 5 minutes for a pod to become available
- When you exit the pod shell, you'll be prompted whether to delete the pod
- If access is not approved within 10 minutes, the script exits with the profile-specific login command to use
  before retrying
- If Kubernetes rejects stale cached credentials after access is renewed, the script first logs in again with the
  selected profile. If Kubernetes still rejects it, the script resets AWS SSO, logs in again, and continues
- If something doesn't work as expected, reach out to #team-infrastructure for assistance
