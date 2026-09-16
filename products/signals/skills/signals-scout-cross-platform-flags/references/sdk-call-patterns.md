# Per-platform call patterns

Starting points for the code half of a run, not a rulebook. SDK method names change between major versions, so confirm a match against the version the tree actually pins (`package.json`, `Podfile.lock`, `build.gradle`, `requirements.txt`, `go.mod`) before you build a finding on it.

Skip tests, fixtures, sample apps, documentation, generated files, and vendored SDK source in every pass.

## Finding the keys

One pass per tree gives the key index. Search for the call, then read the surrounding lines for identity, properties, and load state — the call alone never tells you whether it is correct.

```sh
rg -n --no-heading -g '!**/{test,tests,spec,__tests__,examples,vendor,node_modules,dist,build}/**' \
  -e 'getFeatureFlag|isFeatureEnabled|getFeatureFlagPayload|getFeatureFlagResult|feature_enabled|featureEnabled|getAllFlags|get_all_flags' \
  <tree>
```

String literals in those calls are the keys. A key held in a constant or an enum needs a second pass over that symbol — flag keys often live in one constants file per platform, which is also where key drift hides.

## What each platform gets wrong

| Platform | SDK calls to grep | Inputs to read at the call site | The shape that breaks cross-platform |
| --- | --- | --- | --- |
| JavaScript web | `posthog.getFeatureFlag`, `isFeatureEnabled`, `getFeatureFlagResult`, `onFeatureFlags`, `posthog.init` | `bootstrap.featureFlags` at init, `identify` ordering, `setPersonPropertiesForFlags`, `reloadFeatureFlags` | Evaluation at module load or in a first-render effect, with no bootstrap and no `onFeatureFlags` wait |
| React | `useFeatureFlagEnabled`, `useFeatureFlagVariantKey`, `useFeatureFlagPayload`, `PostHogFeature` | where `identify` runs relative to the route that mounts the hook | The hook's unloaded return used directly in a branch, so the disabled path renders first |
| React Native | `useFeatureFlag`, `posthog.getFeatureFlag`, `PostHogProvider` options | `bootstrap`, `preloadFeatureFlags`, identify at launch | Evaluation during the launch frame, before the first flag response lands |
| iOS (Swift) | `PostHogSDK.shared.isFeatureEnabled`, `getFeatureFlag`, `reloadFeatureFlags`, `onFeatureFlags` | `PostHogConfig` preload setting, `identify` at launch | A launch-path read with no reload after identify, cached from the previous session |
| Android (Kotlin) | `PostHog.isFeatureEnabled`, `PostHog.getFeatureFlag`, `PostHog.reloadFeatureFlags` | `PostHogAndroidConfig` preload setting, `identify` at launch | Same launch race as iOS, usually in `Application.onCreate` or a splash activity |
| Flutter | `Posthog().isFeatureEnabled`, `getFeatureFlag`, `reloadFeatureFlags` | init options, identify ordering | Evaluation in `initState` before the first response |
| Python | `posthog.feature_enabled`, `posthog.get_feature_flag`, `posthog.get_all_flags` | `person_properties`, `group_properties`, `only_evaluate_locally`, `personal_api_key` | Local evaluation that omits a property the flag's conditions target |
| Node | `posthog.isFeatureEnabled`, `getFeatureFlag`, `getAllFlags` | `personProperties`, `groupProperties`, `onlyEvaluateLocally`, `personalApiKey` | Same omission, plus per-request evaluation of a value the request already decided |
| Go, Ruby, PHP, Java | `IsFeatureEnabled`, `GetFeatureFlag`, `isFeatureEnabled` | the properties struct or hash passed in, the personal API key | Same omission |

## Reading the unloaded value

The value a client SDK returns before flags load differs per SDK: `undefined`, `nil`, `None`, `false`, or a default the caller passed. A falsy return therefore does not mean the flag is off. These are the shapes to flag, in whatever language the tree uses:

- the result coerced to a boolean directly in a condition;
- a null-coalescing or default that turns the unloaded value into `false`;
- an equality test against a variant key, evaluated once, with no re-check after load;
- an early return taken on the unloaded value, so the loaded value never reaches the branch.

What correct looks like: the value exists before the branch runs — bootstrap at init, a value the server passed down, or an explicit wait on the SDK's flags callback with a loading state until it fires.

## Identity ordering

Read the file that initializes the SDK and the file that logs the user in. The question is whether every evaluation in the tree happens after the distinct ID is final. A tree that identifies inside the component tree, in a route effect, or after a navigation has an ordering problem even when each individual file looks right. Compare the answer per tree: mobile apps usually identify at launch, web apps after the auth route mounts, and backends always know who the user is. That difference is where the split starts.

## Local evaluation

Local evaluation decides from the properties the call passes. Read the flag's `filters` for the properties its conditions name, then read every local-evaluation call site for the properties it passes. Any property in the conditions that no call site passes is the finding, and it needs no data half: that side of the product is answering from an input it does not have.
