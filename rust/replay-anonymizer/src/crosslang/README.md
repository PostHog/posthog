# `crosslang/` — cross-language shared contract

Files in a `crosslang/` directory are a data contract that **more than one language
implementation must agree on**. Here, the default allow lists
(`default_text_words.txt`, `default_url_segments.txt`) are the single source of truth:
the Rust crate embeds them via `include_str!`, and the TypeScript ingestion pipeline's
`default-dict.ts` mirrors them, verified by `default-dict.test.ts` (which reads these
files — it does not parse the other language's source).

## The convention

Any repo path segment named `crosslang/` marks its contents as such a contract. CI path
filters match `**/crosslang/**`, so editing a file here triggers the test suites of every
consuming language — no per-file or per-crate entry to maintain as the set grows. See the
`nodejs:` filter in `.github/workflows/ci-nodejs.yml`.

Adopt this layout for any file two languages must keep in sync (e.g. the cookieless
`test_cases.json` shared between `rust/common/cookieless` and the Node ingestion tests):
move the shared file into a `crosslang/` folder and the CI trigger follows automatically.
