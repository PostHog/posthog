# Checking and applying workflow files from GitHub Actions

Two jobs: one checks every workflow file on a pull request, the other applies them on a push to the default branch.
They need only bash, curl and jq, which GitHub's Ubuntu runners have, so nothing is installed.
Check errors show as annotations on the file in the pull request.

## Set it up

1. In PostHog, create two personal API keys: one with the workflows read scope (`hog_flow:read`) for checks, one with the write scope (`hog_flow:write`) for applies. A project secret key (`phs_`) with the same scopes works once [PostHog/posthog#104202](https://github.com/PostHog/posthog/pull/104202) is deployed. Until then PostHog answers 401 to it.
2. In the repository settings, add the read key as the Actions secret `POSTHOG_API_KEY`, and the project id as the Actions variable `POSTHOG_PROJECT_ID`. On PostHog Cloud EU, or on your own PostHog, also add the variable `POSTHOG_HOST`, for example `https://eu.posthog.com`.
3. Create the environment `posthog-workflow-files`, limit its deployment branches to the default branch, and add the write key to it as the environment secret `POSTHOG_API_KEY`. Do this before the first push, because GitHub creates a missing environment without that limit. The limit keeps the write key away from pull request runs.
4. Save the two files below. Change `workflows/` and `main` if your files or your default branch live elsewhere.

When the secret is empty, each job prints one line and succeeds. Pull requests from forks get no secrets, so they pass this way.

## `.github/scripts/posthog-workflow-files.sh`

```bash
#!/usr/bin/env bash
# Checks or applies every workflow file in workflows/: bash posthog-workflow-files.sh check|apply
set -euo pipefail
mode="$1"
if [[ -z "${POSTHOG_API_KEY:-}" ]]; then
  echo "No POSTHOG_API_KEY secret is set, so no workflow file was sent to PostHog."
  exit 0
fi
[[ "${POSTHOG_PROJECT_ID:-}" =~ ^[0-9]+$ ]] || { echo "Set the POSTHOG_PROJECT_ID variable to your project id."; exit 1; }
shopt -s nullglob
files=(workflows/*.yaml workflows/*.yml)
((${#files[@]} > 0)) || { echo "No workflow files in workflows/."; exit 0; }

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf 'Authorization: Bearer %s\n' "$POSTHOG_API_KEY" > "$work/auth"
host="${POSTHOG_HOST:-https://us.posthog.com}"
[[ "$host" == https://* || "$host" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?/?$ ]] ||
  { echo "POSTHOG_HOST must start with https://, so the key never travels unencrypted."; exit 1; }
url="${host%/}/api/projects/${POSTHOG_PROJECT_ID}/hog_flows/code_${mode}/"
helpers='
def line: tostring | gsub("[\r\n]+"; " ");
def data: tostring | gsub("%"; "%25") | gsub("\r"; "%0D") | gsub("\n"; "%0A");
def prop: data | gsub(":"; "%3A") | gsub(","; "%2C");
def count(list): list // [] | length;
'

failed=0
for file in "${files[@]}"; do
  rm -f "$work/response"
  code=$(jq -Rs '{content: .}' "$file" | curl --silent --show-error --max-time 60 --header "@$work/auth" \
    --header 'Content-Type: application/json' --data-binary @- \
    --output "$work/response" --write-out '%{http_code}' "$url") || code=000
  if [[ "$code" == 000 ]]; then
    echo "$file: could not reach $url"
    failed=1
  elif [[ "$code" == 2* ]] && jq -e 'type == "object"' "$work/response" > /dev/null 2>&1; then
    jq -r --arg file "$file" "$helpers"'
      .plan as $plan
      | "\($file): \(.result // $plan.result) \(.workflow.key // $plan.workflow.key // "a new workflow"): \(count($plan.added_steps)) added, \(count($plan.changed_steps)) changed, \(count($plan.removed_steps)) removed",
        (($plan.removed_steps // [])[] | "  removes \(.name | line), \(if .runs == null then "people in it not counted" else "\(.runs) people in it" end)"),
        ((.warnings // [])[] | "\($file): warning: \(.message | line)\n  fix: \(.fix | line)")' "$work/response"
  elif jq -e '.errors | type == "array"' "$work/response" > /dev/null 2>&1; then
    jq -r --arg file "$file" "$helpers"'.errors[]
      | (if .line then ":\(.line)" + (if .column then ":\(.column)" else "" end) else "" end) as $at
      | "\($file)\($at): \(.status): \(.message | line)\n  why: \(.why | line)\n  fix: \(.fix | line)",
        "::error file=\($file | prop)\(if .line then ",line=\(.line)" else "" end)\(if .column then ",col=\(.column)" else "" end),title=\(.status | prop)::\("\(.message)\n\(.fix)" | data)"' \
      "$work/response"
    failed=1
  else
    echo "$file: PostHog answered HTTP $code: $(head -c 300 "$work/response" 2> /dev/null | tr -s '\r\n' ' ')"
    failed=1
  fi
done
exit "$failed"
```

## `.github/workflows/posthog-workflow-files.yml`

```yaml
name: PostHog workflow files

on:
  pull_request:
    paths: ['workflows/**', '.github/scripts/posthog-workflow-files.sh', '.github/workflows/posthog-workflow-files.yml']
  push:
    branches: [main]
    paths: ['workflows/**', '.github/scripts/posthog-workflow-files.sh', '.github/workflows/posthog-workflow-files.yml']

permissions:
  contents: read

concurrency:
  group: posthog-workflow-files-${{ github.head_ref || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  check:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Check workflow files
        env:
          POSTHOG_API_KEY: ${{ secrets.POSTHOG_API_KEY }}
          POSTHOG_PROJECT_ID: ${{ vars.POSTHOG_PROJECT_ID }}
          POSTHOG_HOST: ${{ vars.POSTHOG_HOST }}
        run: bash .github/scripts/posthog-workflow-files.sh check

  apply:
    if: github.event_name == 'push'
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    environment: posthog-workflow-files
    steps:
      - uses: actions/checkout@v6
        with:
          persist-credentials: false
      - name: Apply workflow files
        env:
          POSTHOG_API_KEY: ${{ secrets.POSTHOG_API_KEY }}
          POSTHOG_PROJECT_ID: ${{ vars.POSTHOG_PROJECT_ID }}
          POSTHOG_HOST: ${{ vars.POSTHOG_HOST }}
        run: bash .github/scripts/posthog-workflow-files.sh apply
```

## What it does

- On a pull request, `check` calls `code_check`, which writes nothing. Each file prints one line with the result and the steps added, changed and removed, then each removed step with the people in it. A file with mistakes prints `file:line:column: status: message`, then `why` and `fix`, and fails the job.
- On a push to the default branch, `apply` calls `code_apply` for each file. Each file prints `created`, `updated` or `unchanged`. An apply through the API writes live, and the file's `status` sets the workflow's status.
- Warnings, such as people in a removed step, print under the file and never fail the job. Read them on the pull request before you merge.
- A running apply is never cancelled. A queued one gives way to the newest push, which applies every file anyway.
- Deleting a file deletes nothing in PostHog. Delete the file, then archive the workflow in PostHog.
- When `workflows/` holds no file, each job prints one line and succeeds, so deleting the last workflow file does not fail it.

The same two calls work from any CI system:

```sh
jq -Rs '{content: .}' workflows/trial-upgrade-nudge.yaml |
  curl --fail-with-body -H "Authorization: Bearer $POSTHOG_API_KEY" -H 'Content-Type: application/json' \
    --data-binary @- "https://us.posthog.com/api/projects/$POSTHOG_PROJECT_ID/hog_flows/code_check/"
```

Replace `code_check` with `code_apply` to apply.
