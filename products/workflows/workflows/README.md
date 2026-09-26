# PostHog's own workflows

This folder holds the workflows that PostHog runs on its own project, written with [`@posthog/workflows`](../packages/workflows/README.md).
The repository runs the package from the pnpm workspace, so nothing is installed from npm.

Keep one workflow per file.
The `key` in the file is the workflow's identity in the project, and it matches the file name.

## Check and push

Run both from any directory inside the checkout. pnpm runs the script in the package directory, so the cwd does not matter.

```bash
pnpm --filter=@posthog/workflows repo:check   # print what a push would change, for every file here
pnpm --filter=@posthog/workflows repo:push    # create or update every workflow here
```

`repo:check` runs without credentials and says when it skips the comparison.

`repo:push` needs a personal API key with the `hog_flow:write` scope, plus the project and host.
It also needs the email sender described below.

```bash
export POSTHOG_CLI_API_KEY=phx_...
export POSTHOG_CLI_PROJECT_ID=1
export POSTHOG_CLI_HOST=https://us.posthog.com
```

Never commit the key. With none of the three set, the CLI falls back to the `~/.posthog/credentials.json` that `posthog-cli login` writes, so check the last line of the output, which names the project it pushed to.

Every push records the file's path relative to the repository root.

## The email sender

Email steps send from an email integration of the project you push to, and each project has its own integration ids.
So the workflows here read the sender from `POSTHOG_WORKFLOWS_EMAIL_INTEGRATION_ID` instead of naming an id:

```bash
export POSTHOG_WORKFLOWS_EMAIL_INTEGRATION_ID=12   # listed under Workflows, Channels, in the target project
```

A push, and a direct `check` of one file, stop with a message that names the variable when it is not set.
`repo:check` uses the stand-in id `1` when the variable is not set, so the check still runs offline and on a pull request from a fork.
Set the variable when you compare against a project, or the sender shows up as a change.

## Add a workflow

```bash
pnpm --filter=@posthog/workflows build
pnpm --filter=@posthog/workflows exec node dist/cli/main.js init ../../workflows/<name>.ts
```

Leave `status` out of the file. A pushed workflow starts as a draft and sends nothing, and a person turns it on in PostHog once it is reviewed. A push never changes the status of a file that does not set one.

## In CI

Frontend CI runs `pnpm --filter=@posthog/workflows test` and `repo:check` on every pull request that touches this folder or the package, offline and without credentials, so a pull request from a fork passes too.

The `Workflows as code` GitHub Actions job (`.github/workflows/workflows-as-code.yml`) runs `repo:push` on a push to `master` that changes this folder or the job's own file, and on a manual dispatch from `master`.
A change to the package alone does not push, because it can change what every file here compiles to. The next change to this folder, or a manual dispatch, pushes it.

The job runs in the `workflows-as-code` GitHub environment.
A repository admin has to create that environment with required reviewers and store the `POSTHOG_WORKFLOWS_API_KEY` secret on it, so that only a run a reviewer approves can read the key.
If nobody creates it, GitHub creates it on the first run with no reviewers and no secrets, and the job skips the push.

The job reads these settings:

- `POSTHOG_WORKFLOWS_API_KEY` (secret, required): the project's secret API key (`phs_...`) with the workflows scope enabled, once PostHog accepts one on the workflows endpoint ([Silthus/posthog#106](https://github.com/Silthus/posthog/issues/106)). Until then, use a personal API key with the `hog_flow:write` scope.
- `POSTHOG_WORKFLOWS_EMAIL_INTEGRATION_ID` (variable, required): the email integration the workflows here send from.
- `POSTHOG_WORKFLOWS_PROJECT_ID` (variable, optional): defaults to `2`, PostHog's own project on PostHog Cloud US.
- `POSTHOG_WORKFLOWS_HOST` (variable, optional): defaults to `https://us.posthog.com`.

Without the secret or the email integration variable, the job prints a warning and succeeds.

### Server support the push needs

The push depends on two server changes, so they merge and deploy before anyone sets the secret:

1. The workflow `key` ([#103849](https://github.com/PostHog/posthog/pull/103849)), which lets a push find the workflow that a file owns. A PostHog without it makes the CLI stop with `key_not_supported`, and the job prints a warning and succeeds.
2. The `managed_by` and `source_*` fields ([#103540](https://github.com/PostHog/posthog/pull/103540)), which mark a workflow as managed by code and record the file it came from. A PostHog without them ignores the fields, so the push works but PostHog does not show the workflow as managed by code.
