# cymbal-symbolication

Language-specific raw-frame resolution into Cymbal frames using the symbol catalog.

Edit this package when adding or fixing JavaScript, Apple, Java, Dart, Hermes, Go, PHP, Python, Ruby, Node, or custom frame resolution. Artifact fetching belongs in `cymbal-symbol-store`.

Validate from `rust/cymbal`:

```sh
cargo test --manifest-path ../Cargo.toml -p cymbal-symbolication
```
