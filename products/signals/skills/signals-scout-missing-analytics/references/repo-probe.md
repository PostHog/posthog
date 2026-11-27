# Choosing repositories and learning how they capture

How to pick the repositories worth reviewing, how to tell whether a repository sends events to this project, and what to save so no run learns the same facts twice.
Read this after the source ladder has given you a roster, and before the first review on a repository without a `repo:` entry.

## Choose the repositories that matter

An organization can connect hundreds of repositories, and most hold no product code that sends events here.
Narrow the roster on listing fields alone before you spend a `gh` call on any of them:

- Drop `archived` repositories.
- Drop repositories with no push in the last 30 days (`pushed_at`): they merge nothing for this scout to review.
- Put repositories whose `language` suggests an application (TypeScript, JavaScript, Python, Ruby, Go, Swift, Kotlin, Java, PHP, Dart, C#, Elixir) ahead of the rest; a repository of docs, infrastructure config, or data notebooks rarely ships a user action.
- Keep any repository a `config:` entry names, whatever its fields say.

Probe at most 3 repositories without a `repo:` entry per run, most recently pushed first, and move the rotation pointer in `roster:missing_analytics:repos` past them.
A large organization settles over several runs, and later runs probe only what is new or stale.

## The SDK probe

Look for a PostHog SDK in the repository's manifests first, because a manifest is one file read:

| Manifest                                                     | Dependency that names a PostHog SDK                                |
| ------------------------------------------------------------ | ------------------------------------------------------------------ |
| `package.json`                                               | `posthog-js`, `posthog-node`, `posthog-react-native`, `@posthog/*` |
| `requirements*.txt`, `pyproject.toml`, `Pipfile`, `setup.py` | `posthog`                                                          |
| `Gemfile`                                                    | `posthog-ruby`                                                     |
| `go.mod`                                                     | `github.com/posthog/posthog-go`                                    |
| `composer.json`                                              | `posthog/posthog-php`                                              |
| `Package.swift`, `Podfile`                                   | `posthog-ios`, `PostHog`                                           |
| `build.gradle*`                                              | `com.posthog`                                                      |
| `pubspec.yaml`                                               | `posthog_flutter`                                                  |
| `*.csproj`                                                   | `PostHog`                                                          |
| `mix.exs`                                                    | `posthog`                                                          |

A monorepo keeps its manifests in subdirectories: search for the file name (`gh search code 'posthog filename:package.json' --repo <owner>/<repo>`) rather than reading only the root.
Then find the initialization (`posthog.init(`, `new PostHog(`, `Posthog(`, `PostHog.setup(`, or the SDK's equivalent) and note the host it points at, when it is a literal.

A repository with no SDK can still send events: through a wrapper service, a shared internal package, a server-side HTTP call to `/capture/` or `/i/v0/e/`, or a CDP or warehouse pipeline.
When the manifest probe finds nothing, search once for `capture(` together with `posthog` before you record `sdk: none`.

## Does this repository send events to this project?

An SDK in a repository does not prove its events land in this project; the organization can run several projects.
Match on event names:

1. Collect up to 20 literal event names from capture calls in the repository (`gh search code 'capture(' --repo <owner>/<repo>`, or `git grep` on a pinned tree), skipping names built at run time.
2. Look them up in this project: `SELECT name, last_seen_at FROM system.event_definitions WHERE name IN (<escaped names>)`.
3. Several matches with a recent `last_seen_at` mean the repository sends here.
   No match means it sends elsewhere, or names its events at run time, or sends nothing yet.

Record the result as `sends-here`, `sends-elsewhere`, or `unknown`, with the evidence.
Review pull requests only in `sends-here` repositories, and in `unknown` ones that a `config:` entry names.
A repository with names built at run time or a wrapper service stays `unknown`: say so in the close-out, because a match by name cannot see it.

## Learn the capture idioms

For a `sends-here` repository, read a handful of capture calls and record:

- The SDK and the call shape (`posthog.capture('event', {...})`, `posthog.capture(distinct_id=..., event=..., properties=...)`).
- The shared helpers that wrap it (a `track()` function, an analytics service, a typed event catalog), with their file paths.
  A proposal that uses the repository's helper is a change a reviewer accepts; one that calls the SDK around the helper is not.
- The naming style: `snake_case` or `Title Case`, object-verb (`export created`) or verb-object (`created export`), past tense or present.
- Where capture calls live: UI logic, API handlers, background tasks, or a mix.
  A repository that captures server-side puts the success point in the handler, not in the UI.
- Common properties the helper adds on its own, so a proposal does not repeat them.

## The `repo:` entry

Write one entry per probed repository under the shared key `repo:<owner/repo>`, with no scout name in the key, so other scouts can read the same picture.
Keep it compact and factual, dated, and without secrets or project tokens:

> _"acme/web-app, probed 2026-06-03 by signals-scout-missing-analytics. Product web app (TypeScript). SDK posthog-js in frontend/package.json, init in frontend/src/lib/analytics.ts. Helper `track(event, props)` in frontend/src/lib/analytics.ts adds `app_version`. Naming snake_case object_verb past tense (`export_created`). Capture lives in UI logic and in api/handlers/\*. Sends here: 14 of 20 sampled names seen in the last 7 days."_

Read the entry before you trust it: another scout may have written it, and code changes.
Rewrite it when a reviewed diff contradicts it (a new SDK, a renamed helper), and re-probe a repository whose entry is older than 90 days.
For a repository that does not send here, write the entry too (`sends-elsewhere` or `sdk: none`), so the next run skips the probe.
