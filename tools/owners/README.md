# owners-yaml

Code ownership in small `owners.yaml` files next to the code, with a resolver, a linter, and a CODEOWNERS export.

Each directory declares its owners in a short file.
Resolving a path takes more steps than a CODEOWNERS lookup: the nearest file wins field by field, `inherit: false` cuts off parent files, and rules override fields inside a file.
So don't read the files to find an owner. Ask the resolver: `owners who <path>` for a person, and the library, CLI, or JSON entrypoint for a tool.
GitHub's `CODEOWNERS` can stay in place for required approvals.

The format is defined in [SPEC.md](https://github.com/PostHog/posthog/blob/master/tools/owners/SPEC.md).
PostHog's monorepo uses it for about 30 teams.
The files route review requests, daily digests, flaky-test reports, and alerts.

## Quick start

```yaml
# billing/owners.yaml
version: 1
owners: [team-billing, '@alice']
```

```console
$ uvx owners-yaml who billing/api/invoices.py
path:    billing/api/invoices.py
owners:  team-billing, @alice
status:  active
slack:   #team-billing
source:  billing/owners.yaml
```

## Why use it

A single `CODEOWNERS` file works well for small repos. In a large monorepo it has these problems:

- **Line order changes the result.** The last matching line wins, so a broad pattern added at the bottom can take over the specific lines above it.
- **One busy file.** Every team edits the same file, so it gets merge conflicts and nobody feels responsible for it.
- **No lint.** Nothing reports a pattern that matches no files, a team that no longer exists, or a directory that nobody owns.
- **Nothing but owners.** You can't say that code is generated or vendored, or which Slack channel a team uses.

`owners.yaml` addresses these:

- **The nearest file wins, field by field.** A child file that only sets `owners` keeps the `status` of its parent. `inherit: false` stops inheritance.
- **Rules stay in their file.** A `rules:` pattern can only change paths below its own file, so a new rule can't take over another team's paths.
- **"Unowned" is a decision.** `owners: null` marks code that nobody owns on purpose. Everything else without an owner shows up in `owners unowned`.
- **A lifecycle status.** `status: generated`, `vendored`, or `deprecated` lets a review bot skip generated files without its own ignore list.
- **A team channel registry.** The root file maps a team to its Slack channels, with a separate channel for automation and a per-bot opt-out.
- **One resolver for every tool.** Review bots, CI jobs, and alerts all ask the same resolver, so none of them reimplements the resolution steps. It comes as a Python library, a CLI, and a JSON entrypoint that needs only PyYAML.

## Install

```bash
uv tool install owners-yaml   # or: pipx install owners-yaml
uvx owners-yaml --help        # run it once without installing
```

The package installs two identical commands, `owners` and `owners-yaml`.
In CI, pin the version (`owners-yaml==0.2.0`), because a new release can change how paths resolve.

Requirements: Python 3.10 or later, PyYAML, and click.
The commands read tracked files through `git`. Outside a git worktree, pass `--repo-root` and they read the files from disk.
`lint --live` needs the [GitHub CLI](https://cli.github.com/), signed in.

## Usage

### Write ownership files

The smallest file sets `version` and `owners`:

```yaml
version: 1
owners: team-billing
```

A file can override its own subtree with `rules:`. Within one file, the last matching rule wins:

```yaml
version: 1
owners: [team-billing, team-payments]
rules:
  - match: 'generated/**'
    status: generated
  - match: 'vendor/'
    owners: null
```

The root file can also hold repository settings:

```yaml
version: 1
owners: []
github_org: acme
producers: [review-bot]
alias_files: [package.yaml]
teams:
  team-billing:
    slack: '#billing'
    notifications:
      review-bot: '#billing-reviews'
```

`alias_files` names the other files that count as ownership files, such as a package manifest that already lists owners.
Only the `owners` field of such a file is read, and an `owners.yaml` next to it wins.
Without the setting, only `owners.yaml` decides ownership.

[SPEC.md](https://github.com/PostHog/posthog/blob/master/tools/owners/SPEC.md) lists every field and the full resolution algorithm.
For editor completion, point your YAML language server at [`owners.schema.json`](https://github.com/PostHog/posthog/blob/master/tools/owners/owners.schema.json).

### Look up owners

```console
$ owners resolve --json billing/vendor/stripe.py web/app.ts
{
  "billing/vendor/stripe.py": {
    "owners": [],
    "slack": null,
    "source": "billing/owners.yaml",
    "status": "active"
  },
  "web/app.ts": {
    "owners": [
      "team-platform"
    ],
    "slack": "#team-platform",
    "source": "owners.yaml",
    "status": "active"
  }
}
```

`resolve` also reads paths from stdin, one per line. Add `--purpose notifications` to get the channel where automation posts.

To list what nobody owns, run `owners unowned`. Paths under `owners: null` are left out.

### Lint in CI

```console
$ owners lint
⚠ coverage: 0 of 5 tracked file(s) resolve to unowned

✓ owners.yaml lint passed (1 warning(s))
```

`lint` fails on schema errors, a directory with two ownership files, and `owners.yaml` files in reserved locations.
It warns about rule patterns that match no tracked file, and it reports coverage.
`lint --live` also checks each team slug and `@handle` against the GitHub organization in `github_org`, or in `--org`.
Pass the changed ownership files as arguments to check only those.

`owners fmt` shows where files could be merged or split without changing any resolution. It never writes.

### Call it from other tools

From Python:

```python
from owners_yaml import OwnersResolver

resolution = OwnersResolver().resolve("billing/api/invoices.py")
resolution.owners  # ['team-billing', '@alice']
```

The names exported from the top-level `owners_yaml` package are the public API.
Submodules can change between minor releases.

From any language, with only PyYAML installed:

```bash
echo "billing/api/invoices.py" | PYTHONPATH=path/to/tools/owners python3 -m owners_yaml --repo-root path/to/repo
```

It prints one JSON object keyed by path, in the same shape as `owners resolve --json`.
`--repo-root` lets a tool resolve against a directory that holds only the ownership files, such as a sparse fetch.

### Resolve without a checkout

The resolver reads ownership files through a source, so it does not need a worktree.
Implement `read(path)` on anything that can return a file's text: a repository API, an unpacked archive, or a dict in tests.
`read` returns `None` when the file does not exist.

```python
from owners_yaml import OwnersResolver

files = {
    "owners.yaml": "version: 1\nowners: [team-platform]\n",
    "billing/owners.yaml": "version: 1\nowners: [team-billing]\n",
}


class DictSource:
    def read(self, path: str) -> str | None:
        return files.get(path)


resolver = OwnersResolver(source=DictSource())
for path, resolution in resolver.map(["billing/api/invoices.py", "web/app.ts"]).items():
    print(path, resolution.owners)
```

```console
billing/api/invoices.py ['team-billing']
web/app.ts ['team-platform']
```

A source that pays per read, such as one that fetches over the network, can also implement `read_all(paths)`.
`map()` calls it once with the whole batch's ownership files before it reads any of them, so the source can fetch them together.
To prefetch yourself instead, ask `ownership_file_paths(paths)` for the same list.

### Export to CODEOWNERS

Some tools read only CODEOWNERS.
`owners codeowners -o CODEOWNERS.generated` writes the owners of every test file in CODEOWNERS syntax, for test analytics that attribute a failing test to a team.
The export covers test files only and never writes `.github/CODEOWNERS`.

### Add the commands to your own CLI

Each command is a plain [click](https://click.palletsprojects.com/) command named `owners:<name>`, such as `owners_yaml.cli:cmd_lint`.
A click-based CLI can register them directly.
PostHog's `hogli` does this in its `hogli.yaml`:

```yaml
owners:
  owners:lint:
    click: owners_yaml.cli:cmd_lint
    description: Validate owners.yaml files
```

## Compared with other tools

|                        | GitHub CODEOWNERS              | Kubernetes/Prow OWNERS                  | [code_ownership](https://github.com/rubyatscale/code_ownership) | owners-yaml                        |
| ---------------------- | ------------------------------ | --------------------------------------- | --------------------------------------------------------------- | ---------------------------------- |
| Files                  | One central file               | One per directory                       | Per directory, per file annotation, or per package              | One per directory                  |
| Resolution             | Last matching line in the file | Owners of all parent files are combined | One ownership source per file                                   | Nearest file, field by field       |
| Patterns inside a file | Yes                            | Yes, regex `filters`                    | Yes, in the central config                                      | Yes, limited to the file's subtree |
| Required approvals     | Yes, GitHub enforces them      | Yes, through Prow                       | Through the CODEOWNERS file it generates                        | No, routing only                   |
| Coverage check         | No                             | No                                      | Yes                                                             | Yes                                |
| Lifecycle status       | No                             | No                                      | No                                                              | Yes                                |
| Team channel registry  | No                             | No                                      | Team config files                                               | Yes, Slack                         |
| Generates CODEOWNERS   | n/a                            | No                                      | Yes, the whole repo                                             | Test files only                    |

Other tools cover parts of this.
[codeowners-validator](https://github.com/mszostok/codeowners-validator) lints a CODEOWNERS file.
[codeowners-generator](https://github.com/gagoar/codeowners-generator) builds one from files spread across the repo.
Backstage and other service catalogs track ownership per service, not per path.

## When not to use it

- **You need GitHub to block merges on an owner's approval.** Keep that in `.github/CODEOWNERS`. `owners.yaml` routes, it doesn't block. The CODEOWNERS export covers test files only.
- **Your repo is small.** A CODEOWNERS file of a few dozen lines is easier to read than many small files.
- **You use GitLab or Bitbucket code owner approvals.** The tool reads GitHub team slugs and `@handles`, and the live lint uses the GitHub API.
- **You need a stable 1.0 API.** The package is at version 0.x. The file format is at version 1, but the Python API can still change between minor releases.

## Project

- [Changelog](https://github.com/PostHog/posthog/blob/master/tools/owners/CHANGELOG.md)
- [Specification](https://github.com/PostHog/posthog/blob/master/tools/owners/SPEC.md)
- [Issues](https://github.com/PostHog/posthog/issues)

The package lives in the [PostHog monorepo](https://github.com/PostHog/posthog/tree/master/tools/owners). It has no dependencies on the rest of the monorepo.
Run its tests with `uv run --no-project --with pyyaml --with click --with pytest pytest tools/owners/tests`.

To release, bump `version` in `pyproject.toml`, add the matching section to `CHANGELOG.md`, merge, then tag `master`:

```bash
git tag owners-v0.2.0 && git push origin owners-v0.2.0
```

The tag starts [`publish-owners.yml`](https://github.com/PostHog/posthog/blob/master/.github/workflows/publish-owners.yml).
It checks that the tag matches the version, builds and tests the wheel, and publishes to PyPI with trusted publishing.
It then creates a GitHub release from the changelog section.
To retry a failed run, dispatch the workflow on the same tag: `gh workflow run publish-owners.yml --ref owners-v0.2.0`.

MIT licensed.
