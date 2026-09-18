# Changelog

Notable changes to the `hogli` package. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[semantic versioning](https://semver.org/spec/v2.0.0.html).

`publish-hogli.yml` reads the section matching the tagged version and uses it as
the GitHub Release body, so add the entry here before you cut the tag.

## 0.2.0

### Added

- `hogli run <command>` runs a command with the environment the manifest resolves.
- `telemetry:on`, `telemetry:off`, and `telemetry:status` are now built in. They previously lived outside the package.
- `config.env.files` in `hogli.yaml` loads dotenv files before every command. Shell variables always win, and a missing file is skipped.
- `config.env.secrets` resolves secret references through whichever wrapper binary you name. 1Password is no longer built in.
- `needs_secrets: true` on a manifest entry opts a command into the secret wrapper. Commands that do not need secrets skip the extra process.
- `untracked: true` on a manifest entry keeps a command out of telemetry.
- `telemetry.add_command_properties()` attaches custom properties to the `command_completed` event.
- Events carry `hogli_version` and `is_nested`. `command_completed` carries `outcome`, which separates a signal kill from a real failure.
- Package metadata now declares support for Python 3.13.

### Changed

- Breaking: `ctx.meta["hogli.devenv"]` no longer reaches `command_completed`. Use `telemetry.add_command_properties()` instead.
- Breaking: `meta:check` now also fails on manifest entries whose `bin_script` does not exist. A manifest that passed under 0.1.0 can fail here.
- Breaking: events no longer set `$groups: {"project": "hogli"}`.
- CI detection covers GitHub Actions, Jenkins, GitLab, CircleCI, and Buildkite in addition to `CI`. Telemetry stays off in all of them, and the first-run notice no longer prints into build logs.
- `command_started` sends as soon as it is queued, so a long command that is killed still reports.

### Fixed

- hogli no longer replaces the calling process when it runs embedded as a library or under `CliRunner`. Only the `hogli` script and `python -m hogli` can exec into the secret wrapper.
- `flush()` waits on in-flight sends against a shared deadline, so one hung request cannot stall both the post-command flush and the one at exit.
- Telemetry failures no longer break commands or raise during process exit.

## 0.1.0

First release.
