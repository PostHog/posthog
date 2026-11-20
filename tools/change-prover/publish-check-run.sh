#!/usr/bin/env bash
# Signs a lane's check run with this job's GitHub Actions OIDC token and posts it on the head.
#
# stamphog trusts a workflow publisher's check run only when the publishing job signed it: the token's
# audience is `stamphog-` plus the sha256 of `stamphog:v1\n<check>\n<conclusion>\n<marker JSON>`, and the
# summary carries the token after the marker. See the attestation section of the stamphog engine README.
#
# Runs in the publish job, which holds `checks: write` and `id-token: write` and installs nothing.
# Reads CHECK_NAME, CHECK_RUN (the conclude job's output, empty when that job broke), HEAD_SHA,
# WORKFLOW_SHA, IDENTIFY_PR, IDENTIFY_MERGE_BASE, REPOSITORY and GH_TOKEN, and the runner's
# ACTIONS_ID_TOKEN_REQUEST_URL and ACTIONS_ID_TOKEN_REQUEST_TOKEN.
#
# Exits 0 when it posted the decided check run, signed. Otherwise it still posts a check run, because
# stamphog waits for one on every pull request the lane covers, and exits 1.

set -euo pipefail

readonly MARKER_PREFIX='<!-- stamphog:v1 '
readonly MARKER_SUFFIX=' -->'
status=0

summary="$(jq -r '.output.summary // ""' <<< "${CHECK_RUN:-null}" 2> /dev/null || true)"
if [[ "$summary" != "$MARKER_PREFIX"*"$MARKER_SUFFIX" ]]; then
    # The conclude job broke. A neutral check that proves nothing still ends stamphog's wait, so it
    # names the pull request and head like any other result.
    pr=0
    if [[ "${IDENTIFY_PR:-}" =~ ^[0-9]+$ ]]; then
        pr="$IDENTIFY_PR"
    fi
    merge_base=""
    if [[ "${IDENTIFY_MERGE_BASE:-}" =~ ^[0-9a-f]{40}$ ]]; then
        merge_base="$IDENTIFY_MERGE_BASE"
    fi
    marker="$(jq -cn --argjson pr "$pr" --arg head_sha "$HEAD_SHA" --arg merge_base "$merge_base" \
        --arg workflow_sha "$WORKFLOW_SHA" \
        '{files: [], blobs: {}, pr: $pr, head_sha: $head_sha, merge_base: $merge_base, workflow_sha: $workflow_sha}')"
    CHECK_RUN="$(jq -cn --arg name "$CHECK_NAME" --arg head_sha "$HEAD_SHA" \
        --arg summary "$MARKER_PREFIX$marker$MARKER_SUFFIX" '{
            name: $name, head_sha: $head_sha, status: "completed", conclusion: "neutral",
            output: {title: "Not proved", summary: $summary}
        }')"
    summary="$MARKER_PREFIX$marker$MARKER_SUFFIX"
    status=1
fi

marker="${summary#"$MARKER_PREFIX"}"
marker="${marker%"$MARKER_SUFFIX"}"
check="$(jq -r '.name' <<< "$CHECK_RUN")"
conclusion="$(jq -r '.conclusion' <<< "$CHECK_RUN")"
digest="$(printf 'stamphog:v1\n%s\n%s\n%s' "$check" "$conclusion" "$marker" | sha256sum | cut -d ' ' -f 1)"

# An unsigned check run lifts nothing, and stamphog keeps waiting for a signed one, so it is still
# posted and the run fails.
if token="$(curl -fsS --retry 3 --connect-timeout 10 \
    -H "Authorization: bearer $ACTIONS_ID_TOKEN_REQUEST_TOKEN" \
    "$ACTIONS_ID_TOKEN_REQUEST_URL&audience=stamphog-$digest" | jq -r '.value // empty')" && [[ -n "$token" ]]; then
    CHECK_RUN="$(jq -c --arg token "$token" '.output.summary += "\n<!-- stamphog-oidc:v1 " + $token + " -->"' <<< "$CHECK_RUN")"
else
    echo "::error::Could not request an OIDC token, so the check run is posted unsigned"
    status=1
fi

gh api --method POST "repos/$REPOSITORY/check-runs" --input - <<< "$CHECK_RUN" > /dev/null
exit "$status"
