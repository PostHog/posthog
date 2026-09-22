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

The `Workflows as code` GitHub Actions job (`.github/workflows/workflows-as-code.yml`) runs `repo:check` on every pull request that touches this folder or the package, offline and without credentials, so a pull request from a fork passes too.
On a push to `master` it runs `repo:push` when the repository secret `POSTHOG_WORKFLOWS_API_KEY` is set.
The secret holds the project's secret API key (`phs_...`), which needs the workflows scope enabled on the project, once PostHog accepts one on the workflows endpoint ([Silthus/posthog#106](https://github.com/Silthus/posthog/issues/106)). A personal API key with the `hog_flow:write` scope works today and keeps working.
The push goes to project `2`, PostHog's own project on PostHog Cloud US, unless the repository variable `POSTHOG_WORKFLOWS_PROJECT_ID` names another one.
The variable `POSTHOG_WORKFLOWS_HOST` is optional too and defaults to `https://us.posthog.com`.
Without the secret, the job prints one line and succeeds.
