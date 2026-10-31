---
cargo/posthog-symbol-data: patch
---

Add `symbol_data_decompressed_size`, which also measures zstd containers that have no decompressed-size metadata.
