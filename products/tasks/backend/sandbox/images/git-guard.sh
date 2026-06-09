#!/bin/sh
# git guard.
#
# Installed first on PATH inside the cloud sandbox image. Blocks `git commit`
# and `git push` so unsigned commits cannot leave the sandbox.
# All other git subcommands (including the tool's own add/fetch/reset/
# ls-remote/update-ref) pass straight through to the real git.
#
# Escape hatch: set POSTHOG_ALLOW_UNSIGNED_GIT=1 to bypass (debugging only).

native_git=""
for candidate in /usr/bin/git /usr/local/bin/git /bin/git; do
    if [ -x "$candidate" ] && [ "$candidate" != "/opt/posthog/bin/git" ]; then
        native_git="$candidate"
        break
    fi
done
if [ -z "$native_git" ]; then
    echo "git-guard: could not locate the real git binary" >&2
    exit 127
fi

if [ "${POSTHOG_ALLOW_UNSIGNED_GIT:-}" = "1" ]; then
    exec "$native_git" "$@"
fi

# Find the subcommand, skipping git-level global options (and the ones that take
# a value), so `git -C path commit` is caught the same as `git commit`.
subcommand=""
skip_next=0
for arg in "$@"; do
    if [ "$skip_next" = "1" ]; then
        skip_next=0
        continue
    fi
    case "$arg" in
        -C|-c|--git-dir|--work-tree|--namespace|--exec-path)
            skip_next=1
            ;;
        --git-dir=*|--work-tree=*|--namespace=*|--exec-path=*|-*)
            ;;
        *)
            subcommand="$arg"
            break
            ;;
    esac
done

case "$subcommand" in
    commit|push)
        echo "git $subcommand is disabled in PostHog Code: commits must be signed." >&2
        echo "To commit: stage changes with 'git add', then call the git_signed_commit tool." >&2
        echo "To force-push after a rebase/conflict fix: call the git_signed_rewrite tool." >&2
        exit 1
        ;;
esac

exec "$native_git" "$@"
