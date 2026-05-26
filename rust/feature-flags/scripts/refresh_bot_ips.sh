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
#   1. Fetches the three machine-readable provider JSONs:
#        - Googlebot   developers.google.com/search/apis/ipranges/googlebot.json
#        - Bingbot     www.bing.com/toolbox/bingbot.json
#        - Applebot    search.developer.apple.com/applebot.json
#      Each fetch lands in a tempfile, is validated with `jq empty`, then is
#      atomically moved into `rust/feature-flags/src/utils/bot_ips/<name>.json`.
#   2. Prints `git diff --stat` for the bot_ips/ directory so the operator can
#      see at a glance what changed.
#   3. Prints a Yandex reminder block. Yandex's IP list page
#      (https://yandex.com/ips/) is behind a SmartCaptcha and not machine
#      fetchable, so the script cannot refresh it. It dumps the current
#      `YANDEX_FALLBACK_CIDRS` const from `bot_detection.rs` and asks the
#      operator to compare against the browser-rendered yandex.com/ips/ page
#      and edit the const inline if it has drifted.
#   4. Runs `cargo test -p feature-flags utils::bot_detection`. The test
#      suite includes coverage (every published CIDR classifies), schema
#      (each JSON parses; entries have exactly one of ipv4Prefix/ipv6Prefix),
#      and width-floor (no entry wider than /16 v4 or /32 v6) tests, so any
#      upstream regression surfaces as a red test before the operator
#      commits.
#
# USAGE
#   From the posthog repo (or anywhere — the script resolves its own path):
#       ./rust/feature-flags/scripts/refresh_bot_ips.sh
#
#   Optional flags:
#       --skip-tests   Skip the cargo test step (useful for CI or when you
#                      just want the JSON diff and intend to test separately)
#       --no-color     Disable ANSI colors in output
#
# PREREQUISITES
#   - bash, curl, jq, git, cargo on PATH
#   - Network reachability to the three provider hosts
#
# EXIT STATUS
#   0   all three fetches succeeded, JSONs are valid, cargo test passed
#   1   one or more fetches failed (network, 4xx, malformed JSON)
#   2   `cargo test` failed — inspect the diff and the test output before
#       committing; consider rolling back via `git checkout
#       rust/feature-flags/src/utils/bot_ips/`
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

# --- fetch helper -------------------------------------------------------------
PROVIDERS=(
    "googlebot|https://developers.google.com/search/apis/ipranges/googlebot.json"
    "bingbot|https://www.bing.com/toolbox/bingbot.json"
    "applebot|https://search.developer.apple.com/applebot.json"
)

fetch_one() {
    local name="$1"
    local url="$2"
    local dest="$JSON_DIR/${name}.json"
    local tmp
    tmp="$(mktemp)"
    trap 'rm -f "$tmp"' RETURN

    echo -e "${BOLD}↳${RESET} fetching $name from $url"
    if ! curl -fsSL --max-time 30 "$url" -o "$tmp"; then
        echo -e "  ${RED}fetch failed${RESET}" >&2
        return 1
    fi
    if ! jq empty "$tmp" 2>/dev/null; then
        echo -e "  ${RED}invalid JSON${RESET} (saved to $tmp for inspection)" >&2
        # don't delete the tempfile on validation failure so the operator can debug
        trap - RETURN
        return 1
    fi
    local count
    count="$(jq '.prefixes | length' "$tmp")"
    mv "$tmp" "$dest"
    trap - RETURN
    echo -e "  ${GREEN}ok${RESET} → ${dest#"$FF_DIR/"} ($count prefixes)"
}

# --- run fetches --------------------------------------------------------------
echo -e "${BOLD}Refreshing bot IP JSONs in${RESET} $JSON_DIR"
fail=0
for entry in "${PROVIDERS[@]}"; do
    name="${entry%%|*}"
    url="${entry##*|}"
    fetch_one "$name" "$url" || fail=1
done
if [[ "$fail" -ne 0 ]]; then
    echo -e "${RED}one or more provider fetches failed; aborting${RESET}" >&2
    exit 1
fi

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
    echo -e "${RED}cargo test failed.${RESET} The refreshed JSONs have already been written."
    echo "Inspect:"
    echo "  - test output above for the failing case"
    echo "  - git diff $JSON_DIR for what changed"
    echo "If upstream published a /15 or wider, MIN_V4_PREFIX in bot_detection.rs"
    echo "rejects it — widening the floor is a deliberate policy decision."
    echo "To roll back: git checkout -- $JSON_DIR"
    exit 2
fi

echo
echo -e "${GREEN}done.${RESET} JSONs refreshed, tests green. Review the diff and commit."
