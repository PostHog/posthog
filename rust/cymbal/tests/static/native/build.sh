#!/usr/bin/env bash
# Builds the checked-in ELF test fixtures for native symbolication tests.
#
# Requirements:
#   - zig (any recent version; used as a hermetic x86_64-linux cross C compiler/linker)
#   - llvm-objcopy (e.g. from an llvm toolchain)
#   - rustup with the x86_64-unknown-linux-gnu target installed
#   - a Go toolchain (for the Go fixture)
#     (rustup target add x86_64-unknown-linux-gnu)
#
# DWARF source paths are remapped to the stable prefix /cymbal_tests/native so
# the baked-in test assertions don't depend on the build machine. The binaries
# are never executed by tests — they only need valid DWARF + build ids.
#
# After rebuilding, the address constants in cymbal's native tests must be
# refreshed (they are derived from the symcache; see the comments next to the
# constants in src/langs/native.rs tests).

set -euo pipefail
cd "$(dirname "$0")"

CFLAGS=(-target x86_64-linux-gnu -g -O1 "-fdebug-prefix-map=$PWD=/cymbal_tests/native" -Wl,--build-id=sha1)

# Non-PIE (zig's default): fixed link base, exercises the non-zero
# load-address math.
zig cc "${CFLAGS[@]}" -fno-PIE -o test_binary_nopie test_binary.c

# PIE: link base 0, exercises the ASLR-slide math.
zig cc "${CFLAGS[@]}" -fPIE -pie -o test_binary_pie test_binary.c

# Inline expansion fixture (PIE).
zig cc "${CFLAGS[@]}" -fPIE -pie -o test_binary_inline test_binary_inline.c

# CLI classification fixtures: an ELF without debug info, and one with debug
# info but no GNU build id. Neither can be symbolicated; the CLI must triage
# them instead of uploading them. The strip is explicit because zig links its
# runtime objects with debug info even when -g is absent; any objcopy able to
# read ELF works (llvm-objcopy here since macOS binutils can't).
zig cc -target x86_64-linux-gnu -O1 -Wl,--build-id=sha1 -o test_binary_nodebug test_binary.c
llvm-objcopy --strip-debug test_binary_nodebug test_binary_nodebug
zig cc -target x86_64-linux-gnu -g -O1 "-fdebug-prefix-map=$PWD=/cymbal_tests/native" -Wl,--build-id=none -o test_binary_nobuildid test_binary.c

# Rust fixture: real rustc-mangled symbols for the demangling assertions.
# zig is used as the cross linker via the zigcc-x86_64-linux wrapper.
cat > .zigcc-x86_64-linux <<'WRAP'
#!/usr/bin/env bash
exec zig cc -target x86_64-linux-gnu "$@"
WRAP
chmod +x .zigcc-x86_64-linux
# rustup explicitly: dev environments often put a non-rustup rustc (without
# cross targets) first in PATH.
# line-tables-only + fat LTO keep the fixture small while matching the
# debug-info profile we recommend for production Rust builds. The binary is
# committed zstd-compressed; tests decompress it in memory.
rustup run stable rustc --target x86_64-unknown-linux-gnu \
    -C debuginfo=line-tables-only -O -C lto=fat -C codegen-units=1 -C panic=abort \
    --remap-path-prefix "$PWD=/cymbal_tests/native" \
    -C linker="$PWD/.zigcc-x86_64-linux" \
    -C link-arg=-Wl,--build-id=sha1 \
    -o test_rust_binary test_rust.rs
rm .zigcc-x86_64-linux
zstd -19 -f -q test_rust_binary
rm test_rust_binary

# Go fixture: real Go function naming and mid-stack inlining. -B gobuildid
# derives the GNU build id from the Go build ID; committed zstd-compressed.
GOOS=linux GOARCH=amd64 go build -trimpath -ldflags "-B gobuildid" -o test_go_binary test_go.go
zstd -19 -f -q test_go_binary
rm test_go_binary

echo "Built fixtures:"
file test_binary_nopie test_binary_pie test_binary_inline test_binary_nodebug test_binary_nobuildid
ls -la test_rust_binary.zst test_go_binary.zst
