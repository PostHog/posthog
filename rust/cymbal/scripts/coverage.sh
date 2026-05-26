#!/usr/bin/env bash
set -euo pipefail

usage() {
    cat <<'EOF'
Usage: scripts/coverage.sh [--summary|--html|--lcov] [cargo-llvm-cov args...]

Run Cymbal-local Rust coverage from rust/cymbal/ while delegating to the parent
rust/Cargo.toml workspace manifest.

Modes:
  --summary   Print the cargo-llvm-cov text summary. This is the default.
  --html      Write an HTML report to target/coverage/html/.
  --lcov      Write an LCOV report to target/coverage/cymbal.lcov.
  --help      Show this help.

Required tool:
  cargo install cargo-llvm-cov --locked

Examples:
  scripts/coverage.sh --summary
  scripts/coverage.sh --html
  scripts/coverage.sh --lcov -- --no-fail-fast
EOF
}

mode="--summary"
if [[ $# -gt 0 ]]; then
    case "$1" in
        --summary|--html|--lcov)
            mode="$1"
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *)
            echo "error: unknown mode '$1'" >&2
            echo >&2
            usage >&2
            exit 2
            ;;
    esac
fi

if ! command -v cargo-llvm-cov >/dev/null 2>&1; then
    cat >&2 <<'EOF'
error: cargo-llvm-cov is required to run Cymbal coverage.

Install it with:
  cargo install cargo-llvm-cov --locked

Also ensure the llvm-tools component is present:
  rustup component add llvm-tools-preview

If cargo-llvm-cov still reports "failed to find llvm-tools-preview", set
explicit paths for your toolchain:
  LLVM_COV=~/.rustup/toolchains/stable-aarch64-apple-darwin/lib/rustlib/aarch64-apple-darwin/bin/llvm-cov \\
  LLVM_PROFDATA=~/.rustup/toolchains/stable-aarch64-apple-darwin/lib/rustlib/aarch64-apple-darwin/bin/llvm-profdata \\
  scripts/coverage.sh --summary
(adjust the toolchain name to match your platform)

Then rerun:
  scripts/coverage.sh --summary
EOF
    exit 127
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cymbal_dir="$(cd "${script_dir}/.." && pwd)"
cd "${cymbal_dir}"

manifest_path="../Cargo.toml"
coverage_dir="target/coverage"
ignore_filename_regex='(^|/)(target|node/src/generated|node/dist|node/node_modules|tests/static|crates/[^/]+/tests/static)(/|$)'

packages=(
    cymbal-api
    cymbal-core
    cymbal-domain
    cymbal-fingerprinting
    cymbal-pipeline
    cymbal-repositories
    cymbal-runtime
    cymbal-rules
    cymbal-alerting
    cymbal-grouping
    cymbal-linking
    cymbal-rate-limiting
    cymbal-resolution
    cymbal-symbol-store
    cymbal-symbolication
    cymbal-server
)

package_args=()
for package in "${packages[@]}"; do
    package_args+=("-p" "${package}")
done

common_args=(
    llvm-cov
    --manifest-path "${manifest_path}"
    "${package_args[@]}"
    --ignore-filename-regex "${ignore_filename_regex}"
)

case "${mode}" in
    --summary)
        cargo "${common_args[@]}" --summary-only "$@"
        ;;
    --html)
        mkdir -p "${coverage_dir}"
        cargo "${common_args[@]}" --html --output-dir "${coverage_dir}/html" "$@"
        echo "HTML coverage report written to ${coverage_dir}/html/index.html"
        ;;
    --lcov)
        mkdir -p "${coverage_dir}"
        cargo "${common_args[@]}" --lcov --output-path "${coverage_dir}/cymbal.lcov" "$@"
        echo "LCOV coverage report written to ${coverage_dir}/cymbal.lcov"
        ;;
esac
