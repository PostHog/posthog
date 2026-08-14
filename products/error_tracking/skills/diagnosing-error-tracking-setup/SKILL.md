---
name: diagnosing-error-tracking-setup
description: >
  Diagnoses whether PostHog Error Tracking is configured and receiving exceptions. Use when issue searches are empty,
  a user asks whether error tracking is working, exception capture appears inactive, or an SDK sends events but no
  errors. Distinguishes observable project and ingestion state from local SDK options that PostHog cannot inspect.
---

# Diagnosing error tracking setup

An empty issue list does not prove that error tracking is disabled or broken. Check configuration and ingestion before explaining the result.

## Tools

| Tool | Purpose |
| --- | --- |
| `posthog:error-tracking-setup-status` | Read project configuration, recent ingestion, observed SDKs, and setup warnings |
| `posthog:query-error-tracking-issues-list` | Confirm whether recent exception events produced grouped issues |
| `posthog:error-tracking-recommendations-list` | Find improvements after exception ingestion is working |

## Workflow

### 1. Check observable setup state

Call `posthog:error-tracking-setup-status` first.

Treat each field as a separate signal:

- `project_autocapture_enabled` is the project setting.
- `remote_config_autocapture_enabled` is the published remote value. `null` means it could not be checked.
- `recent_event_count` shows whether the project received any events during `recent_period_days`.
- `recent_exception_count` shows whether those events included `$exception`.
- `observed_sdks` identifies SDK libraries seen on recent events.
- `has_issues` shows whether the project has grouped issues, including historical issues.
- `warnings` contains supported conclusions and next actions, identified by `warning_code`.

If `recent_data_available` is false, say that ingestion could not be checked. Do not infer that the project received no events.

### 2. Classify the result

| Evidence | Interpretation |
| --- | --- |
| No recent events | PostHog has no recent event evidence for this project. Check the SDK connection before error tracking configuration. |
| Events present, no exceptions | The SDK sends events, but PostHog has not received exception events during the period. Follow SDK-specific warnings. |
| Exceptions present, no issues | Exception ingestion works, but grouping may still be processing. Retry the issue query before calling setup broken. |
| Historical issues, no recent exceptions | Error tracking worked previously. The result does not prove whether the current application still captures exceptions. |
| Exceptions and issues present | Initial setup works. Continue with issue triage or setup recommendations. |

A difference between the project setting and published remote config is worth reporting, but neither value proves what a local SDK initialized.

### 3. Handle local SDK configuration accurately

For `posthog-node`, exception autocapture requires a local initialization option:

```ts
new PostHog(apiKey, {
    enableExceptionAutocapture: true,
})
```

PostHog can observe Node events, but it cannot inspect this local option. Say that the option is required and unverified. Never claim it is disabled solely because no exceptions arrived.

For SDKs whose `autocapture_configuration` is `unknown`, identify the observed SDK and ask the user to verify its current error tracking setup instructions.

### 4. Continue after ingestion works

When exceptions are present:

- Use `posthog:query-error-tracking-issues-list` for recent or high-impact issues.
- Use `posthog:error-tracking-recommendations-list` for alerts, rate limits, source maps, and long-running issues.
- Load `diagnosing-stacktrace-symbolication` when captured stack traces remain minified or obfuscated.
- Load `triaging-error-issues` when the user wants a prioritized review.
- Load `investigating-error-issue` when the user provides one issue.

## Response shape

State what PostHog observed, what remains unknown, and the next check. Keep the distinction explicit:

- Observed: project settings, published config, recent events, recent exceptions, issues, and SDK identifiers.
- Not observable: local SDK initialization, application exception paths, and whether an untriggered error handler would work.
