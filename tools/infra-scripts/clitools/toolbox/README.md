# Toolbox Utility

A command line utility to connect to PostHog toolbox pods in a Kubernetes environment.

## Features

- Lists and switches between available Kubernetes contexts
- Automatically identifies the current user from Kubernetes authentication
- Finds and claims toolbox pods
- Sets expiration time for claimed pods
- Connects to claimed pods using kubectl exec
- Allows pod deletion after use

## Package Structure

The toolbox utility uses a hybrid approach with modular functions in a package but the main entry point in the top-level script:

- **Main script**:
  - `toolbox.py` - Main script with argument parsing and the core workflow

- **Support modules**:
  - `toolbox/kubernetes.py` - Functions for working with Kubernetes contexts
  - `toolbox/user.py` - User identification and ARN parsing
  - `toolbox/pod.py` - Pod management (finding, claiming, connecting, deleting)

This structure keeps the main flow in a single script for easy understanding while separating the implementation details into modular components.

## Usage

```bash
# Basic usage (claims pod for 12 hours by default)
python toolbox.py

# Claim a pod for 24 hours
python toolbox.py --claim-duration 24

# Update the termination time of an existing claimed pod
python toolbox.py --update-claim
```

Before connecting to a pod, the utility now allows you to select a Kubernetes context, making it easier to work with multiple clusters.
