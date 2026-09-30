# Checking and applying workflow files from GitHub Actions

Two jobs: one checks every workflow file on a pull request, the other applies them on a push to the default branch.
They need only bash, curl and jq, which GitHub's Ubuntu runners have, so nothing is installed.
Check errors show as annotations on the file in the pull request.
The [posthog-workflows-action](https://github.com/Silthus/posthog-workflows-action) makes the same calls, with the same setup and the same retry and host rules.

## Set it up

1. In PostHog, create two personal API keys: one with the workflows read scope (`hog_flow:read`) for checks, one with the write scope (`hog_flow:write`) for applies. A project secret key (`phs_`) with the same scopes works once [PostHog/posthog#104202](https://github.com/PostHog/posthog/pull/104202) is deployed. Until then PostHog answers 401 to it.
2. In the repository settings, add the read key as the Actions secret `POSTHOG_API_KEY`, and the project id as the Actions variable `POSTHOG_PROJECT_ID`. On PostHog Cloud EU, or on your own PostHog, also add the variable `POSTHOG_HOST`, for example `https://eu.posthog.com`.
3. Create the environment `posthog-workflows`, limit its deployment branches to the default branch, and add the write key to it as the environment secret `POSTHOG_API_KEY`. Do this before the first push, because GitHub creates a missing environment without that limit. The limit keeps the write key away from pull request runs.
4. Save the two files below. Change `workflows/` and `main` if your files or your default branch live elsewhere.

Both secrets have the same name and hold different keys. The `apply` job names the environment, so it reads the write key. The `check` job reads the repository's read key.
If the environment has no `POSTHOG_API_KEY`, the `apply` job reads the read key and every apply fails with HTTP 403.
In a private repository, environments need GitHub Pro, Team or Enterprise. Without an environment there is no safe place for the write key, so never put it in a repository secret.

When the secret is empty, each job prints one line and succeeds, as a warning in the `apply` job. Pull requests from forks get no secrets, so they pass this way.

## `.github/scripts/posthog-workflow-files.sh`

```bash
#!/usr/bin/env bash
# Checks or applies every workflow file in workflows/: bash posthog-workflow-files.sh check|apply
set -euo pipefail
mode="$1"
if [[ -z "${POSTHOG_API_KEY:-}" ]]; then
  [[ "$mode" == apply ]] && level=warning || level=notice
  echo "::$level::No POSTHOG_API_KEY secret is set, so no workflow file was sent to PostHog."
  exit 0
fi
[[ "${POSTHOG_PROJECT_ID:-}" =~ ^[0-9]+$ ]] || { echo "Set the POSTHOG_PROJECT_ID variable to your project id."; exit 1; }
host="${POSTHOG_HOST:-https://us.posthog.com}"
[[ "$host" == https://* || "$host" =~ ^http://(localhost|127\.0\.0\.1)(:[0-9]+)?/?$ ]] ||
  { echo "POSTHOG_HOST must start with https://, so the key never travels unencrypted."; exit 1; }
url="${host%/}/api/projects/${POSTHOG_PROJECT_ID}/hog_flows/code_${mode}/"
shopt -s nullglob
files=(workflows/*.yaml workflows/*.yml)
((${#files[@]} > 0)) || { echo "No workflow files in workflows/."; exit 0; }

umask 077
work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
printf 'Authorization: Bearer %s\n' "$POSTHOG_API_KEY" > "$work/auth"
helpers='
def data: tostring | gsub("%"; "%25") | gsub("\r"; "%0D") | gsub("\n"; "%0A");
def prop: data | gsub(":"; "%3A") | gsub(","; "%2C");
def count(list): list // [] | length;
def whole: if type == "number" then floor else null end;
'

post() {
  rm -f "$work/response"
  jq -Rs '{content: .}' "$1" | curl --silent --show-error --max-time 60 --header "@$work/auth" \
    --header 'Content-Type: application/json' --data-binary @- \
    --output "$work/response" --write-out '%{http_code}' "$url" 2> "$work/curl-error" || true
}

# Readable lines go to $work/out and annotations to $work/annotations. Text from PostHog could hold a
# "##[" workflow command anywhere in a line, so the readable lines print with workflow commands stopped.
report() {
  local file="$1" code="$2"
  if [[ "$code" == 000 ]]; then
    echo "$file: could not reach $url: $(head -n 1 "$work/curl-error")"
    return 1
  fi
  if [[ "$code" == 2* ]]; then
    jq -e --arg mode "$mode" 'if $mode == "apply" then .result else .plan.result? end | strings' \
      "$work/response" > /dev/null 2>&1 || { echo "$file: PostHog answered HTTP $code without a result."; return 1; }
    jq -r --arg file "$file" "$helpers"'
      .plan as $plan
      | "\($file): \(.result // $plan.result) \(.workflow.key // $plan.workflow.key // "a new workflow"): \(count($plan.added_steps)) added, \(count($plan.changed_steps)) changed, \(count($plan.removed_steps)) removed",
        (($plan.removed_steps // [])[] | "  removes \(.name), \(if .runs == null then "people in it not counted" else "\(.runs) people in it" end)"),
        ((.warnings // [])[] | "\($file): warning: \(.message)\n  fix: \(.fix)")' "$work/response" || return 1
    return 0
  fi
  if jq -e '.errors | type == "array"' "$work/response" > /dev/null 2>&1; then
    jq -r --arg file "$file" '.errors[]
      | (if .line then ":\(.line)" + (if .column then ":\(.column)" else "" end) else "" end) as $at
      | "\($file)\($at): \(.status): \(.message)\n  why: \(.why)\n  fix: \(.fix)"' "$work/response" || return 1
    jq -r --arg file "$file" "$helpers"'.errors[]
      | (.line | whole) as $line | (.column | whole) as $column
      | "::error file=\($file | prop)\(if $line then ",line=\($line)" else "" end)\(if $line and $column then ",col=\($column)" else "" end),title=\(.status | prop)::\("\(.message)\n\(.fix)" | data)"' \
      "$work/response" >> "$work/annotations"
  else
    echo "$file: PostHog answered HTTP $code: $(head -c 300 "$work/response" 2> /dev/null | tr -s '\r\n' ' ')"
  fi
  return 1
}

failed=0
for file in "${files[@]}"; do
  : > "$work/annotations"
  code=$(post "$file")
  # One retry for no answer, a timeout, a conflict or a server error. A 429 would fail again this soon.
  if [[ "$code" =~ ^(000|408|409|5[0-9][0-9])$ ]]; then
    sleep 2
    code=$(post "$file")
  fi
  report "$file" "$code" > "$work/out" || failed=1
  token="$(od -An -N16 -tx1 /dev/urandom | tr -d ' \n')"
  echo "::stop-commands::$token"
  cat "$work/out"
  echo "::$token::"
  cat "$work/annotations"
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
  group: posthog-workflow-files-${{ github.event.pull_request.number || github.ref }}
  cancel-in-progress: ${{ github.event_name == 'pull_request' }}

jobs:
  check:
    if: github.event_name == 'pull_request'
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
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
    environment: posthog-workflows
    steps:
      - uses: actions/checkout@de0fac2e4500dabe0009e67214ff5f5447ce83dd # v6.0.2
        with:
          persist-credentials: false
      - name: Apply workflow files
        env:
          POSTHOG_API_KEY: ${{ secrets.POSTHOG_API_KEY }}
          POSTHOG_PROJECT_ID: ${{ vars.POSTHOG_PROJECT_ID }}
          POSTHOG_HOST: ${{ vars.POSTHOG_HOST }}
        run: bash .github/scripts/posthog-workflow-files.sh apply
```

Pin actions to a full commit SHA, as above, because the `apply` job holds a write key. A version tag can move.

## What it does

- On a pull request, `check` calls `code_check`, which writes nothing. Each file prints one line with the result and the steps added, changed and removed, then each removed step with the people in it. A file with mistakes prints `file:line:column: status: message`, then `why` and `fix`, and fails the job.
- On a push to the default branch, `apply` calls `code_apply` for each file. Each file prints `created`, `updated` or `unchanged`. An apply through the API writes live, and the file's `status` sets the workflow's status.
- Warnings, such as people in a removed step, print under the file and never fail the job. Read them on the pull request before you merge.
- A request that gets no answer, HTTP 408, 409 or a 5xx is sent once more after two seconds. HTTP 429 is not retried, because PostHog's rate limits last longer than that. A 2xx answer without a result fails the job.
- Text from PostHog prints with workflow commands stopped, so a message cannot run one in your job.
- A running apply is never cancelled. A queued one gives way to the newest push, which applies every file anyway.
- Deleting a file deletes nothing in PostHog. Delete the file, then archive the workflow in PostHog once the change is merged. While the file remains, check and apply refuse it if its workflow is archived.
- When `workflows/` holds no file, each job prints one line and succeeds, so deleting the last workflow file does not fail it.

The same two calls work from any CI system:

```sh
jq -Rs '{content: .}' workflows/trial-upgrade-nudge.yaml |
  curl --fail-with-body -H "Authorization: Bearer $POSTHOG_API_KEY" -H 'Content-Type: application/json' \
    --data-binary @- "https://us.posthog.com/api/projects/$POSTHOG_PROJECT_ID/hog_flows/code_check/"
```

Replace `code_check` with `code_apply` to apply.
