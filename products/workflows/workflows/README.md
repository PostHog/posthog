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

`repo:push` needs a personal API key with the `hog_flow:write` scope, plus the project and host:

```bash
export POSTHOG_CLI_API_KEY=phx_...
export POSTHOG_CLI_PROJECT_ID=1
export POSTHOG_CLI_HOST=https://us.posthog.com
```

Never commit the key. With none of the three set, the CLI falls back to the `~/.posthog/credentials.json` that `posthog-cli login` writes, so check the last line of the output, which names the project it pushed to.

Every push records the file's path relative to the repository root.

## Add a workflow

```bash
pnpm --filter=@posthog/workflows build
pnpm --filter=@posthog/workflows exec node dist/cli/main.js init ../../workflows/<name>.ts
```

Keep `status: 'draft'` until the workflow is reviewed and meant to run. A draft can be pushed as often as you like and sends nothing.
