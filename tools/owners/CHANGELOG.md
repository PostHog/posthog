# Changelog

Notable changes to the `owners-yaml` package. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

`publish-owners.yml` reads the section matching the tagged version and uses it as
the GitHub Release body, so add the entry here before you cut the tag.

## 0.2.0

First release on PyPI, as `owners-yaml`. The package was developed in the monorepo as `posthog-owners` and never published under that name.

### Added

- `SPEC.md` defines the `owners.yaml` format, version 1, with the resolution steps, a field merge table, a flow diagram, and a worked example. `owners.schema.json` describes the file for editors.
- `SPEC.md` section 7 defines the resolver interface, and `resolution.schema.json` describes its JSON response.
- `conformance/` holds language-neutral test cases for the resolution rules, which any implementation can run.
- `publish-owners.yml` publishes the package to PyPI when an `owners-v*` tag is pushed.
- Root-only repo settings in `owners.yaml`: `github_org`, `producers`, `reserved_dirs`, `alias_files`, and `codeowners`.
- `alias_files` declares the file names, besides `owners.yaml`, that count as ownership files.
- `--repo-root` on every CLI command, and `--org` on `lint` and `codeowners`.
- A tree that is not a git worktree is read from disk, so the CLI works on an export or a scratch copy.
- `owners_yaml.github.GitHubOrg` validates team slugs and handles without any host tooling.
- An `owners-yaml` console script, so `uvx owners-yaml` works without `--from`.
- `BatchOwnershipSource`, a source that fetches a batch's ownership files together. `OwnersResolver.map()` calls its `read_all` before it reads any file.
- The top-level `owners_yaml` package exports the full public API, so consumers do not import submodules.
- `py.typed`, so type checkers read the package's annotations.

### Changed

- The GitHub organization is no longer hardcoded. `codeowners` and `lint --live` read it from `github_org` or `--org`, and fail with a clear message when neither is set.
- Producer names are no longer hardcoded. A repo that declares `producers` gets typo checks; a repo that does not accepts any name.
- The reserved `products/**/mcp/**` location moved from the code into PostHog's own `reserved_dirs`. `.github/workflows/**` stays built in.
- The CODEOWNERS projection reads its Jest spelling rules from the `codeowners` settings instead of PostHog's layout.
- Outside a git worktree and without `--repo-root`, the CLI prints an error instead of a traceback.
- `version: true` and `version: 1.0` no longer count as `version: 1`, so such a file counts as absent.
- `product.yaml` is no longer read as an ownership file unless the root `owners.yaml` lists it in `alias_files`. It was a PostHog convention baked into the code.

## 0.1.0

First version, used inside the PostHog monorepo only.
