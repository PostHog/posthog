# cymbal-proto

Rust bindings for Cymbal internal gRPC APIs.

Proto definitions live in the top-level [`/proto/cymbal`](/proto/cymbal) directory.
The first package is `cymbal.resolution.v1`, a resolution-specific API for offloading exception-level symbol resolution from `rust/cymbal` to the planned `rust/cymbal-resolution` service.

## Building

```bash
cargo build -p cymbal-proto
```

Rust bindings regenerate automatically through `tonic-build` when the crate builds.
