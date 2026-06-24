#!/usr/bin/env bash
# Builds the checked-in ELF test fixtures for native symbolication tests.
#
# Requirements:
#   - zig (any recent version; used as a hermetic x86_64-linux cross C compiler/linker)
#   - rustup with the x86_64-unknown-linux-gnu target installed
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

echo "Built fixtures:"
file test_binary_nopie test_binary_pie test_binary_inline
ls -la test_rust_binary.zst
