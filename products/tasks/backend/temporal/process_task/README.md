# Cloud Runs

## GitHub App Setup

Cloud runs require a GitHub App to interact with repositories. Create a GitHub App with these permissions:

### Required Permissions

| Permission        | Access       | Purpose                                   |
| ----------------- | ------------ | ----------------------------------------- |
| **Contents**      | Read & Write | Read files, create branches, push commits |
| **Pull requests** | Read & Write | Create and update PRs                     |
| **Metadata**      | Read         | Required for all GitHub Apps              |

### Optional Permissions

| Permission    | Access       | Purpose              |
| ------------- | ------------ | -------------------- |
| **Issues**    | Read & Write | Link tasks to issues |
| **Workflows** | Read & Write | Trigger CI workflows |

### Environment Variables

Add to your `.env`:

```bash
GITHUB_APP_CLIENT_ID=your_app_id
GITHUB_APP_SLUG=your-app-slug
GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----\n...\n-----END RSA PRIVATE KEY-----"
```

The app slug is the URL-friendly name shown in your GitHub App's URL (e.g., `github.com/apps/your-app-slug`).

The private key can include literal `\n` characters - they'll be converted to newlines.

### Creating the GitHub App

1. Go to GitHub → Settings → Developer Settings → GitHub Apps → New GitHub App
2. Set the permissions listed above
3. Generate a private key and download it
4. Install the app on the repositories you want to use

## Sandbox Providers

In production, we use **ModalSandbox** which runs on [Modal](https://modal.com) with gVisor isolation. gVisor provides kernel-level sandboxing by intercepting system calls, offering stronger isolation than standard containers.

For local development, **DockerSandbox** uses regular Docker containers. This is fine for dev/testing but doesn't provide the same isolation guarantees - containers share the host kernel and are easier to escape. DockerSandbox is blocked from running in production.

## Local Development

### Using DockerSandbox (recommended)

Add to your `.env`:

```bash
SANDBOX_PROVIDER=docker
```

Requires Docker to be running locally.

### Testing with a local agent package

To test changes to the `@posthog/agent` package before publishing, use the `LOCAL_AGENT_PACKAGE` environment variable:

```bash
# Build the agent package first
cd /path/to/array/packages/agent && pnpm build

# Run with local agent
LOCAL_AGENT_PACKAGE=/path/to/array/packages/agent \
  python products/tasks/scripts/run_agent_in_docker.py --repository org/repo
```

This uses a two-layer Docker image approach:

1. `posthog-sandbox-base` - Base image with `@posthog/agent` from npm
2. `posthog-sandbox-base-local` - Dev image that overlays your local agent package

The local image is rebuilt each time to pick up your changes. The base image is cached.

### Using ModalSandbox

Add to your `.env`:

```bash
MODAL_TOKEN_ID=your_token_id
MODAL_TOKEN_SECRET=your_token_secret
```

Get tokens from [modal.com](https://modal.com).

## Running Tests

Tests require the Array OAuth app fixture. It's created automatically via `autouse=True` in `conftest.py`.

To run tests that need Modal:

```bash
MODAL_TOKEN_ID=xxx MODAL_TOKEN_SECRET=xxx pytest products/tasks/backend/temporal/
```

Tests without Modal tokens will be skipped if they aren't provided.
