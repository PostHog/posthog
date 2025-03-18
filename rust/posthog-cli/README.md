# The Posthog CLI

```bash
> posthog-cli --help
The command line interface for PostHog 🦔

Usage: posthog-cli [OPTIONS] <COMMAND>

Commands:
  login      Authenticate with PostHog, storing a personal API token locally
  query      Run a SQL query against any data you have in posthog. This is mostly for fun, and subject to change
  sourcemap  Upload a directory of bundled chunks to PostHog
  help       Print this message or the help of the given subcommand(s)

Options:
      --host <HOST>  The PostHog host to connect to [default: https://us.posthog.com]
  -h, --help         Print help
  -V, --version      Print version
```

## Releases

Releases are cut by pushing a release tag to the repository, for the `posthog-cli` app, e.g.
```
git tag "posthog-cli-v0.1.0-prerelease.1"
git push
git push tags
```

We manage publishing releases through [`cargo-dist`](https://github.com/axodotdev/cargo-dist)

We release semi-regularly, as new features are added. If a release breaks your CI or workflow, please open an issue on GitHub, and tag one or all of the crate authors
