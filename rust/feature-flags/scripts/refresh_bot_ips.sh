#!/usr/bin/env bash
#
# refresh_bot_ips.sh — refresh the bot IP JSONs embedded in the feature-flags
# binary.
#
# WHY THIS SCRIPT EXISTS
#   `rust/feature-flags/src/utils/bot_detection.rs` embeds three provider JSONs
#   at compile time via `include_str!`. The list of bot IP ranges shifts as
#   providers add or remove crawler hosts. Run this script periodically — or
#   in response to a missed-bot incident — to pull the latest published list
#   and refresh the embedded copies. It also serves as the operator-runnable
#   counterpart to the (manual) Yandex update flow.
#
# WHAT IT DOES
#   1. Fetches the three machine-readable provider JSONs into a single staging
#      tempdir:
#        - Googlebot   developers.google.com/search/apis/ipranges/googlebot.json
#        - Bingbot     www.bing.com/toolbox/bingbot.json
#        - Applebot    search.developer.apple.com/applebot.json
#      Each fetch is validated with `jq empty`. If any fetch or validation
#      fails, NOTHING in `src/utils/bot_ips/` is modified.
#   2. Backs up the current JSONs to a second tempdir, then atomically moves
#      all three staged JSONs into `src/utils/bot_ips/`.
#   3. Runs `cargo test -p feature-flags utils::bot_detection`. The test suite
#      includes coverage (every published CIDR classifies), schema (each JSON
#      parses; entries have exactly one of ipv4Prefix/ipv6Prefix), and
#      width-floor (per-provider + global) tests. If tests fail, the script
#      restores the previous JSONs from backup so the working tree is left
#      exactly as it was.
#   4. Prints `git diff --stat` for `bot_ips/` so the operator can see what
#      changed, plus a Yandex reminder block. Yandex's IP list page
#      (https://yandex.com/ips/) is behind a SmartCaptcha and not machine
#      fetchable, so the script cannot refresh it. It dumps the current
#      `YANDEX_FALLBACK_CIDRS` const from `bot_detection.rs` and asks the
#      operator to compare against the browser-rendered yandex.com/ips/ page
#      and edit the const inline if it has drifted.
#
# USAGE
#   From the posthog repo (or anywhere — the script resolves its own path):
#       ./rust/feature-flags/scripts/refresh_bot_ips.sh
#
#   Optional flags:
#       --skip-tests   Skip the cargo test step (useful for CI or when you
#                      just want the JSON diff and intend to test separately).
#                      With this flag, the stage-then-commit step still runs;
#                      only the test gate is skipped.
#       --no-color     Disable ANSI colors in output
#
# PREREQUISITES
#   - bash, curl, jq, git, cargo on PATH
#   - Network reachability to the three provider hosts
#
# EXIT STATUS
#   0   all three fetches succeeded, JSONs are valid, cargo test passed
#       (or was skipped); working tree contains the refreshed JSONs.
#   1   one or more fetches failed (network, 4xx, malformed JSON); working
#       tree is UNCHANGED.
#   2   `cargo test` failed after the refresh was staged; the previous JSONs
#       have been RESTORED from backup so the working tree is unchanged.
#       Inspect the printed test output for the failure mode.
#
# AFTER A SUCCESSFUL RUN
#   - Review `git diff rust/feature-flags/src/utils/bot_ips/` and the
#     emitted Yandex reminder.
#   - If a category of bot IP has shifted significantly (Google adds a new
#     /16 range, Apple gains an entire new octet, etc.), eyeball whether
#     the new entries match the provider's category in
#     bot_detection.rs's PROVIDERS table — the category mapping is per
#     provider, not per entry, so a single misrouted upstream entry would
#     mis-label the metric.
#   - `git add` + commit. There is no other documentation to keep in sync —
#     this script's header is the single source of truth on refresh.
#
set -euo pipefail

# --- argument parsing ---------------------------------------------------------
SKIP_TESTS=0
USE_COLOR=1
for arg in "$@"; do
    case "$arg" in
        --skip-tests) SKIP_TESTS=1 ;;
        --no-color)   USE_COLOR=0 ;;
        -h|--help)
            sed -n '1,/^set -euo/p' "$0" | sed '$d'
            exit 0
            ;;
        *) echo "unknown argument: $arg" >&2; exit 64 ;;
    esac
done

if [[ "$USE_COLOR" -eq 1 ]] && [[ -t 1 ]]; then
    BOLD='\033[1m'; GREEN='\033[32m'; YELLOW='\033[33m'; RED='\033[31m'; RESET='\033[0m'
else
    BOLD=''; GREEN=''; YELLOW=''; RED=''; RESET=''
fi

# --- locate ourselves ---------------------------------------------------------
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
FF_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
JSON_DIR="$FF_DIR/src/utils/bot_ips"
BOT_DETECTION_RS="$FF_DIR/src/utils/bot_detection.rs"

if [[ ! -d "$JSON_DIR" ]]; then
    echo -e "${RED}error:${RESET} expected $JSON_DIR to exist; run from a checkout of posthog" >&2
    exit 1
fi
if [[ ! -f "$BOT_DETECTION_RS" ]]; then
    echo -e "${RED}error:${RESET} expected $BOT_DETECTION_RS to exist" >&2
    exit 1
fi

# --- temp dirs + cleanup ------------------------------------------------------
STAGE_DIR="$(mktemp -d)"
BACKUP_DIR="$(mktemp -d)"
# Single trap cleans both temp dirs on any exit path. Set early so even
# pre-fetch failures (e.g. missing curl/jq) don't leak.
trap 'rm -rf "$STAGE_DIR" "$BACKUP_DIR"' EXIT

# --- providers + fetch helper -------------------------------------------------
PROVIDERS=(
    "googlebot|https://developers.google.com/search/apis/ipranges/googlebot.json"
    "bingbot|https://www.bing.com/toolbox/bingbot.json"
    "applebot|https://search.developer.apple.com/applebot.json"
)

# Strip CRLF line endings if present and ensure exactly one trailing newline.
# Microsoft serves bingbot.json with CRLF line endings; without this normalization
# the file would round-trip through git as a perpetual CRLF→LF diff churn.
# Apple's file ships with one trailing newline, Google's with none; the trim +
# re-append step gives all three vendored copies a byte-identical tail shape.
normalize_line_endings() {
    local file="$1"
    [[ -s "$file" ]] || return 0
    local normalized
    normalized="$(mktemp)"
    # `$(...)` captures the CR-stripped content and bash strips any trailing
    # newlines from a command-substitution. `printf '%s\n'` then puts exactly
    # one back. Files here top out at ~25KB so loading into memory is fine.
    local content
    content="$(tr -d '\r' < "$file")"
    printf '%s\n' "$content" > "$normalized"
    mv "$normalized" "$file"
}

# Fetch one provider into $STAGE_DIR/<name>.json. Validates with `jq empty`.
# Returns nonzero on any failure; nothing in $JSON_DIR is touched.
fetch_to_stage() {
    local name="$1"
    local url="$2"
    local staged="$STAGE_DIR/${name}.json"

    echo -e "${BOLD}↳${RESET} fetching $name from $url"
    if ! curl -fsSL --max-time 30 "$url" -o "$staged"; then
        echo -e "  ${RED}fetch failed${RESET}" >&2
        return 1
    fi
    if ! jq empty "$staged" 2>/dev/null; then
        echo -e "  ${RED}invalid JSON${RESET}" >&2
        return 1
    fi
    normalize_line_endings "$staged"
    local count
    count="$(jq '.prefixes | length' "$staged")"
    echo -e "  ${GREEN}ok${RESET} → staged ($count prefixes)"
}

# --- stage all three fetches --------------------------------------------------
echo -e "${BOLD}Staging bot IP JSON refresh in${RESET} $STAGE_DIR"
fail=0
for entry in "${PROVIDERS[@]}"; do
    name="${entry%%|*}"
    url="${entry##*|}"
    fetch_to_stage "$name" "$url" || fail=1
done
if [[ "$fail" -ne 0 ]]; then
    echo -e "${RED}one or more provider fetches failed; nothing on disk changed${RESET}" >&2
    exit 1
fi

# --- backup current JSONs + atomic commit -------------------------------------
# Backup must happen before we move staged files into place so we can restore
# on cargo test failure. `cp -p` preserves mtime so a restore is bit-identical.
for entry in "${PROVIDERS[@]}"; do
    name="${entry%%|*}"
    src="$JSON_DIR/${name}.json"
    if [[ -f "$src" ]]; then
        cp -p "$src" "$BACKUP_DIR/${name}.json"
    fi
done

for entry in "${PROVIDERS[@]}"; do
    name="${entry%%|*}"
    mv "$STAGE_DIR/${name}.json" "$JSON_DIR/${name}.json"
done

# --- show diff ----------------------------------------------------------------
echo
echo -e "${BOLD}Diff vs working tree:${RESET}"
if git -C "$FF_DIR" diff --stat -- "$JSON_DIR" 2>/dev/null | grep -q .; then
    git -C "$FF_DIR" diff --stat -- "$JSON_DIR"
else
    echo "  (no changes)"
fi

# --- Yandex reminder ----------------------------------------------------------
echo
echo -e "${YELLOW}${BOLD}Yandex — manual step${RESET}"
echo -e "${YELLOW}yandex.com/ips/ is behind SmartCaptcha; this script cannot refresh it.${RESET}"
echo -e "${YELLOW}Open https://yandex.com/ips/ in a browser, compare against the current${RESET}"
echo -e "${YELLOW}YANDEX_FALLBACK_CIDRS in bot_detection.rs, and edit the const inline${RESET}"
echo -e "${YELLOW}(plus its 'Last reviewed' date) if the list has drifted.${RESET}"
echo
echo "Current YANDEX_FALLBACK_CIDRS:"
# Print the const body (between the opening and closing brackets) so the
# operator can eyeball it without context-switching to the source file.
# Anchor on `^const ` so a later expression-context reference to
# YANDEX_FALLBACK_CIDRS doesn't reopen the block, and `exit` after the
# first `];` to keep the output tight.
awk '
    /^const YANDEX_FALLBACK_CIDRS/ { in_block = 1 }
    in_block { print "  " $0 }
    in_block && /^];/ { exit }
' "$BOT_DETECTION_RS"

# --- gate on cargo test -------------------------------------------------------
if [[ "$SKIP_TESTS" -eq 1 ]]; then
    echo
    echo -e "${YELLOW}--skip-tests set; skipping cargo test${RESET}"
    echo -e "${GREEN}done.${RESET} Inspect the diff above and decide whether to commit."
    exit 0
fi

echo
echo -e "${BOLD}Running cargo test -p feature-flags utils::bot_detection ...${RESET}"
if ! (cd "$FF_DIR/.." && cargo test -p feature-flags utils::bot_detection --quiet); then
    echo
    echo -e "${RED}cargo test failed.${RESET} Restoring previous JSONs from backup."
    for entry in "${PROVIDERS[@]}"; do
        name="${entry%%|*}"
        backup="$BACKUP_DIR/${name}.json"
        if [[ -f "$backup" ]]; then
            cp -p "$backup" "$JSON_DIR/${name}.json"
        fi
    done
    echo "Working tree restored to its pre-script state. Inspect the test output above."
    echo "Common causes:"
    echo "  - Upstream published a CIDR wider than a per-provider floor in"
    echo "    bot_detection.rs PROVIDERS (Apple /24, Bingbot /22, Google /23 v4 / /64 v6)."
    echo "    Widening the floor is a deliberate policy decision."
    echo "  - Upstream changed JSON shape (entry missing both ipv4Prefix and ipv6Prefix)."
    exit 2
fi

echo
echo -e "${GREEN}done.${RESET} JSONs refreshed, tests green. Review the diff and commit."
