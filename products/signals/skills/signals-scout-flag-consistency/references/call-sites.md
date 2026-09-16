# Call sites and evaluation modes

Read this when you build the key index, or when Lane B needs a cause for two regimes disagreeing.

## What counts as a call site

A flag key in a tree is only a call site when code passes it to an SDK evaluation function. Everything else is a mention, and a mention never proves a repository uses a flag — nor does its absence prove the repository does not.

Count it:

- the key as an argument to an evaluation call (the shapes below), including through a named constant or enum whose value is the key;
- the key in a config or environment file the code reads and then passes to an evaluation call, when you can follow both halves.

Do not count it:

- lockfiles, vendored dependencies, generated clients, build output, `__snapshots__`, minified bundles;
- test fixtures, mocks, and flag overrides in test setup — they prove the test knows the key, not that production evaluates it;
- comments, changelogs, migrations, documentation, and commented-out code;
- a substring match inside a longer key. Search whole keys (`rg -F` with word boundaries where the key allows) — `checkout-v3` matches `checkout-v3-legacy` and the two are different flags.

When a key reaches an evaluation call only through a variable, say so in the report and cite both lines. An indirect call site is still a call site; an unverified guess that one exists is not.

## Evaluation modes

Five modes, and the disagreements in Lane B nearly always come from two of them meeting.

| Mode                     | How to recognize it                                                     | What it reads conditions from                               |
| ------------------------ | ----------------------------------------------------------------------- | ----------------------------------------------------------- |
| Client, remote           | a browser or mobile SDK call, no bootstrap config                       | the identified person's stored properties                   |
| Client, bootstrapped     | `bootstrap: { featureFlags: … }` at init, values rendered server-side   | whatever the server put in the bootstrap payload            |
| Server, remote           | a server SDK call with no personal API key configured                   | only the properties the call itself passes                  |
| Server, local evaluation | a personal API key at init; definitions polled and evaluated in process | only the properties the call itself passes                  |
| Server, local-only       | an explicit "evaluate locally only" option on the call                  | the same, and it returns the fallback when it cannot decide |

The two rows that matter most: **a server SDK resolves conditions from the properties the call passes, not from the person's stored properties.** A client call and a server call for the same flag and the same user therefore disagree whenever the flag's conditions read a property the server call does not send. That is the most common cause of a confirmed regime split, and it is invisible in either repo alone.

## Call shapes by SDK

Search for the function names, not the SDK name.

- **posthog-js / React** — `isFeatureEnabled(`, `getFeatureFlag(`, `getFeatureFlagPayload(`, `onFeatureFlags(`, `useFeatureFlagEnabled(`, `useFeatureFlagPayload(`, `useActiveFeatureFlags(`, and `bootstrap` in the init options.
- **posthog-python** — `feature_enabled(`, `get_feature_flag(`, `get_feature_flag_payload(`, `get_all_flags(`. Local evaluation is on when a personal API key is set at init; the per-call context is `person_properties=`, `groups=`, `group_properties=`, and `only_evaluate_locally=`.
- **posthog-node** — `isFeatureEnabled(`, `getFeatureFlag(`, `getAllFlags(`, with context in the options argument (`personProperties`, `groups`, `groupProperties`, `onlyEvaluateLocally`) and local evaluation on when `personalApiKey` is set.
- **Other server SDKs** (Go, Ruby, PHP, Java, Rust, Elixir) — the same two verbs in that language's casing: an "is enabled" predicate and a "get flag" accessor, each taking a distinct id and an optional context.
- **Mobile** (iOS, Android, React Native, Flutter) — an "is enabled" predicate and a "get flag" accessor on the shared SDK instance; treat these as client, remote unless the app bootstraps.

## Mapping a repository to what the stream shows

`$lib` on `$feature_flag_called` is how you tie a regime in the data to a repository in the trees. The values are the SDK, not the service, so a project with two Python services shows one `posthog-python`. Common values: `web` and `js` (posthog-js), `posthog-python`, `posthog-node`, `posthog-edge`, plus the mobile SDK names.

Two consequences:

- **Two repos on the same SDK are indistinguishable in the stream.** Lane B's query cannot separate them; the trees have to. Where two pinned repos share an SDK, confirm which one owns a call site from the code and say in the report that the stream could not attribute it.
- **Local evaluation sends no call event by default.** A repository evaluating locally can be entirely absent from `$lib` while serving flags heavily. Never read its absence from the stream as "this service does not use flags" — read the tree.
