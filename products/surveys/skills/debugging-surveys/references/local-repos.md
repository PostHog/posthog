# Local repo registry

Surveys spans several repos (the monorepo plus `posthog-js`, `posthog-ios`,
`posthog-android`, `posthog-flutter`, and `posthog.com`). Different maintainers keep their
clones in different places. This registry records where each maintainer's checkouts live so
a repo is found once and reused — no re-cloning every session.

GitHub stays the source of truth for _where the code lives_ (see the Repos table in
SKILL.md). The registry is purely a local cache of _where this maintainer cloned it_.

## The registry file

A JSON map of repo key → absolute local path at:

```text
~/.config/posthog-surveys/repos.json
```

Example:

```json
{
  "posthog": "/Users/me/src/posthog",
  "posthog-js": "/Users/me/src/posthog-js",
  "posthog-ios": "/Users/me/src/posthog-ios",
  "posthog-android": "/Users/me/src/posthog-android",
  "posthog-flutter": "/Users/me/src/posthog-flutter",
  "posthog.com": "/Users/me/src/posthog.com"
}
```

Repo keys match the GitHub repo names. The web and React Native SDKs both live in
`posthog-js` (`packages/browser/`, `packages/react-native/`).

## First-time setup: `init`

Run once to auto-discover and record every PostHog checkout already on the machine — no
manual typing for repos that are already cloned:

```sh
python3 scripts/repos.py init
```

It scans conventional code roots (the cwd's parents, `~/src`, `~/code`, `~/dev`,
`~/projects`, `~/repos`, `~/work`, `~/git`), matches each git checkout by its `origin`
remote (`github.com/PostHog/<repo>`), and writes the registry. It's idempotent: re-running
respects any path you chose explicitly and only fills gaps. If a repo is checked out twice,
it keeps the first and prints `set` commands so you can pick the other.

There is no global git config that lists where repos are cloned, so the filesystem + the
`origin` remote is the reliable signal — that's what discovery uses.

## Resolving a repo when you need its source

```sh
python3 scripts/repos.py ensure posthog-js          # registry -> scan -> path (add --clone to clone)
python3 scripts/repos.py get posthog-ios            # print path, or exit non-zero if unknown
python3 scripts/repos.py set posthog-android /path  # override the recorded path
python3 scripts/repos.py list                       # show the whole registry
```

`ensure` does the full resolution: recorded path → filesystem scan (recording what it
finds) → optionally clone with `--clone`. If you'd rather manage the JSON directly, follow
the same logic the script encodes:

1. **Read the registry.** If the repo is listed and the path exists, use it.
2. **Scan the code roots** above for a checkout whose `git remote get-url origin` points at
   `PostHog/<repo>` (name match as a fallback).
3. **Ask or clone.** If still not found, ask the maintainer where it is, or offer to
   `git clone https://github.com/PostHog/<repo>` into a default location (`~/src/<repo>`).
4. **Write the resolved path back** to `~/.config/posthog-surveys/repos.json` so future
   sessions skip the search/clone.

Always confirm the checkout is on a sane branch before quoting code, and grep for symbols
rather than trusting remembered line numbers — the SDKs move fast.
