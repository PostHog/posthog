#!/bin/bash
# gh guard.
#
# Installed first on PATH inside the cloud sandbox image as /opt/posthog/bin/gh.
# The backend delivers the per-actor GitHub token via BASH_ENV, which only
# non-interactive `bash -c` honors — the agent runs its tool commands in an
# interactive shell, so `gh` there would otherwise have no token. This shim
# sources the same credential script the shells do, so `gh` authenticates as the
# current actor regardless of shell mode, and honors logout (an emptied file
# exports nothing, leaving gh unauthenticated rather than falling back to a stale
# token). All arguments pass straight through to the real gh.

native_gh=""
for candidate in /usr/bin/gh /usr/local/bin/gh /bin/gh; do
    if [ -x "$candidate" ] && [ "$candidate" != "/opt/posthog/bin/gh" ]; then
        native_gh="$candidate"
        break
    fi
done
if [ -z "$native_gh" ]; then
    echo "gh-guard: could not locate the real gh binary" >&2
    exit 127
fi

# Re-source the backend-managed credentials fresh on every call (the file is
# rewritten on each refresh / actor transition). The script's sourced branch
# unsets then re-exports GH_TOKEN/GITHUB_TOKEN from the env file.
if [ -f /tmp/agentsh-bash-env.sh ]; then
    # shellcheck source=/dev/null
    . /tmp/agentsh-bash-env.sh
fi

exec "$native_gh" "$@"
