# Checking and applying workflow files from GitHub Actions

This job checks every workflow file on a pull request and applies them on a push to the default branch.
It needs only curl and jq, which GitHub's Ubuntu runners have, so nothing is installed.
Check errors show as annotations on the file in the pull request.

## Set it up

1. In PostHog, create a project secret API key with the workflows scope (`hog_flow:read` and `hog_flow:write`). A personal API key with the same scopes also works.
2. In the repository, add the key as the Actions secret `POSTHOG_API_KEY`.
3. Add the project id as the Actions variable `POSTHOG_PROJECT_ID`. On PostHog Cloud EU, or on your own PostHog, also add `POSTHOG_HOST`, for example `https://eu.posthog.com`.
4. Save the job below as `.github/workflows/posthog-workflows.yml`. Change `workflows/` and `main` if your files or your default branch live elsewhere.

When the secret is empty, the job prints one line and succeeds. Pull requests from forks get no secrets, so they pass this way.

To keep the write key away from pull request runs, keep a `hog_flow:read` key as the repository secret. Then run the apply as its own job in a GitHub environment that only the default branch may deploy to, and store the `hog_flow:write` key on that environment under the same name.

## The job

```yaml
name: PostHog workflows

on:
  pull_request:
    paths: ['workflows/**']
  push:
    branches: [main]
    paths: ['workflows/**']

permissions:
  contents: read

concurrency:
  group: posthog-workflows-${{ github.head_ref || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  workflows:
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Check or apply workflow files
        env:
          POSTHOG_API_KEY: ${{ secrets.POSTHOG_API_KEY }}
          POSTHOG_PROJECT_ID: ${{ vars.POSTHOG_PROJECT_ID }}
          POSTHOG_HOST: ${{ vars.POSTHOG_HOST || 'https://us.posthog.com' }}
          MODE: ${{ github.event_name == 'push' && 'apply' || 'check' }}
        run: |
          if [ -z "$POSTHOG_API_KEY" ]; then
            echo "No POSTHOG_API_KEY secret is set, so no workflow file was checked or applied."
            exit 0
          fi
          printf 'Authorization: Bearer %s\n' "$POSTHOG_API_KEY" > "$RUNNER_TEMP/posthog-auth"
          url="${POSTHOG_HOST%/}/api/projects/$POSTHOG_PROJECT_ID/hog_flows/code_$MODE/"
          failed=0
          for file in workflows/*.yaml; do
            code=$(jq -Rs '{content: .}' "$file" | curl --silent --show-error --max-time 60 \
              --header "@$RUNNER_TEMP/posthog-auth" --header 'Content-Type: application/json' \
              --data-binary @- --output "$RUNNER_TEMP/response.json" --write-out '%{http_code}' "$url") || code=000
            if [ "$code" -ge 200 ] && [ "$code" -lt 300 ]; then
              jq -r --arg file "$file" '
                (.plan.added_steps | length) as $added | (.plan.removed_steps | length) as $removed
                | "\($file): \(.result // .plan.result) \(.workflow.key // .plan.workflow.key // "a new workflow"), \($added) step(s) added, \($removed) removed",
                  ((.warnings // [])[] | "\($file): warning: \(.message)\n  fix: \(.fix)")' "$RUNNER_TEMP/response.json"
            elif jq -e '.errors | type == "array"' "$RUNNER_TEMP/response.json" > /dev/null 2>&1; then
              jq -r --arg file "$file" '.errors[]
                | "\($file):\(.line // 1):\(.column // 1): \(.status): \(.message)\n  why: \(.why)\n  fix: \(.fix)",
                  "::error file=\($file),line=\(.line // 1),col=\(.column // 1),title=\(.status)::\(.message) \(.fix)"' \
                "$RUNNER_TEMP/response.json"
              failed=1
            else
              echo "$file: PostHog answered HTTP $code: $(head -c 300 "$RUNNER_TEMP/response.json" 2> /dev/null)"
              failed=1
            fi
          done
          exit "$failed"
```

## What it does

- On a pull request it calls `code_check`, which writes nothing, and prints the plan for each file. A file with mistakes prints `file:line:column: status: message`, then `why` and `fix`, and fails the job.
- On a push to the default branch it calls `code_apply` for each file. Each file prints `created`, `updated` or `unchanged`. An apply through the API writes live, and the file's `status` sets the workflow's status.
- Warnings, such as people in a removed step, print under the file and never fail the job. Read them on the pull request before you merge.
- One concurrency group per branch keeps two applies from racing, and never cancels an apply.
- Deleting a file deletes nothing in PostHog. Archive the workflow in PostHog.

The same two calls work from any CI system:

```sh
jq -Rs '{content: .}' workflows/trial-upgrade-nudge.yaml |
  curl --fail-with-body -H "Authorization: Bearer $POSTHOG_API_KEY" -H 'Content-Type: application/json' \
    --data-binary @- "https://us.posthog.com/api/projects/$POSTHOG_PROJECT_ID/hog_flows/code_check/"
```

Replace `code_check` with `code_apply` to apply.
