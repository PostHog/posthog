# posthog-symbol-processing

The file processing behind PostHog error tracking uploads.

PostHog stores a symbol set under a chunk ID and a content hash.
A second upload of the same chunk ID with a different hash fails with `content_hash_mismatch`.
So every tool that uploads symbol sets must write the same bytes for the same input.

This crate holds the code that decides those bytes.
Two binaries build it from this folder:

- `posthog-cli`, in `cli/`, which also publishes to crates.io and so names a version next to the path.
- `hog-worker`, in `hog/worker/`, the Rust sidecar of the `hog` CLI.

The crate reads and writes local files only.
Network calls, authentication, command line parsing and terminal output stay in the binaries.

## What is in it

| Module                     | What it decides                                                                    |
| -------------------------- | ---------------------------------------------------------------------------------- |
| `sourcemaps::constant`     | The injected snippets, the chunk ID comment and the chunk ID namespace             |
| `sourcemaps::content`      | Reading and rewriting a minified file and its sourcemap, and the Hermes container  |
| `sourcemaps::source_pairs` | Pairing a file with its map, the upload container and the event-mode content hash  |
| `sourcemaps::inject`       | Which chunk ID a pair gets in each release mode                                    |
| `sourcemaps::hermes`       | Finding the composed Hermes map and cloning the IDs into it                        |
| `debug_symbols`            | Which ELF and Mach-O files upload, under which ID, and how they are zipped         |
| `dsym`                     | The slices of a dSYM bundle and the source files packed with a binary              |
| `proguard`                 | The validity check and the container of a ProGuard or R8 mapping                   |
| `upload`                   | The symbol set payload, its default content hash and the duplicate chunk ID rule   |
| `files`                    | File wrappers and the SHA-512 content hash                                         |

## Options

The two binaries differ in a few places.
Each difference is an option or a separate function here, so neither binary carries a private copy of the code around it.
The default is always what posthog-cli does.

| Option or function                                             | posthog-cli                                    | hog-worker                                             |
| -------------------------------------------------------------- | ---------------------------------------------- | ------------------------------------------------------ |
| `AdjustmentOptions::include_content`                           | `true`                                         | `false`, the adjustment map then holds no file copy    |
| `inject_pair`, the `on_debug_id_issue` callback                | Logs `DebugIdIssue::log`                       | Returns its own wording to hog                         |
| `UploadOptions::log_debug_id_mismatch`                         | `true`                                         | `false`, hog reports the mismatch once, at injection   |
| `inject_pair_legacy`, the `new_chunk_id` callback              | Mints a UUIDv7                                 | Returns the ID hog generated                           |
| `ReadPairsOptions::skip_non_sourcemaps`, `is_sourcemap`        | `false`, any JSON object is read as a map      | `true`, a file without `mappings` is skipped           |
| `CssWhitespace`                                                | `Rust`                                         | `JavaScript`                                           |
| `SourceReadOptions::non_blocking_open`                         | `false`                                        | `true`, a FIFO is refused and does not block           |
| `collect_source_files_with`, the `on_unreadable` callback      | Logs the file and skips it                     | Returns the list to hog                                |
| `ObjectCandidate::Unparseable` from `classify_objects`         | Logs the object and skips it                   | Reports a fat slice, and fails a thin file             |
| `DsymFile::new` and `dsym::read_slices`                        | `DsymFile::new`, with `dwarfdump` and `lipo`   | `read_slices`, which needs no Xcode                    |
| `SourcePair::from_parts`                                       | Not used, `read_pairs` reads the files         | Builds a pair from files it read itself                |
| `SourceMapContent::to_hermes_container`                        | Through `TryInto`, which refuses a Metro map   | Directly, after its own `is_hermes_composed` check     |
| `proguard::is_valid_mapping`, `proguard::mapping_container`    | Through `ProguardFile`                         | Directly, to tell "not UTF-8" from "not a mapping"     |
| `SourcePair::empty_sourcemap`                                  | Uses `WRAPPER_JS_SIZE_THRESHOLD_BYTES` itself  | Picks the skip reason it returns                       |
| `SymbolSetUpload::resolved_content_hash`                       | In the upload protocol                         | When it writes the container                           |

## Change it

A change here reaches both binaries, so run both test suites:

```bash
cargo test --locked --manifest-path rust/common/symbol_processing/Cargo.toml
cargo test --locked --manifest-path cli/Cargo.toml
```

A change to what gets uploaded also changes hog's parity goldens.
`hog/test/parity/README.md` says how to record them again.

`Cargo.lock` here pins the crates that decide a written byte to the versions in `cli/Cargo.lock`.
Raise one in both files together.

See [CONTRIBUTING.md](CONTRIBUTING.md) for releases.
