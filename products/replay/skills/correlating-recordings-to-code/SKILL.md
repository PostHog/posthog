---
name: correlating-recordings-to-code
description: >
  Goes from a moment in a session recording to the source file behind it. Use when you know when something went wrong in a recording (a Replay Vision finding, a rageclick, a crash, a timestamp a user pointed at) and you need to find the code that caused it. Turns a recording-relative offset into an absolute instant, queries the events around it, and ranks what those events carry by how reliably it maps to a file you can grep for. Covers web and mobile autocapture, exception stack traces, and what to do when no event backs the moment.
---

# Correlating a recording moment to code

The recording itself does not name code. The events captured alongside it sometimes do, and that is the whole trick: convert the moment into an absolute timestamp, pull the events in a few seconds around it, and read the fields that carry a developer-authored string. Some of those strings are in the source tree verbatim. Some are worthless. This skill says which.

## 1. Find the absolute instant

```text
anchor = recording_start_time + start_time
```

`start_time` is seconds since the recording started, not since the session started and not a wall clock. A Replay Vision signal carries both values in its `extra`: `recording_start_time` (ISO 8601) and `start_time` (whole seconds). Without one, take the recording's start time from `session-recording-get`.

Recording bounds are not session bounds. Depending on the customer's config, recording can begin well after the session did, so never substitute the session's first event for `recording_start_time`.

## 2. Query the window

Two steps, because a raw `elements_chain` runs to kilobytes of nested divs and a 10 second window holds dozens of events — pulling raw chains for all of them buries the answer.

**Step one, scan the window** on materialized columns only:

```sql
SELECT
    timestamp,
    event,
    properties.$event_type AS event_type,
    properties.$current_url AS url,
    properties.$pathname AS pathname,
    properties.$screen_name AS screen_name,
    elements_chain_ids,
    elements_chain_texts,
    elements_chain_elements,
    elements_chain_href,
    properties.$exception_types AS exception_types,
    properties.$exception_values AS exception_values,
    properties.$exception_sources AS exception_sources,
    properties.$exception_issue_id AS issue_id
FROM events
WHERE properties.$session_id = '<session_id>'
  AND timestamp >= toDateTime('<anchor>') - INTERVAL 5 SECOND
  AND timestamp <= toDateTime('<anchor>') + INTERVAL 5 SECOND
ORDER BY timestamp ASC
```

Widen `INTERVAL 5 SECOND` only if it comes back empty. Wider windows pull in unrelated interactions and you end up attributing the wrong click.

**Step two, pull the raw chain for the one row that matters**, since custom attributes (tier 2 below) appear only there. Take the interaction nearest the anchor, add `AND event = '$autocapture' AND timestamp = toDateTime64('<its timestamp>', 3)`, and select `elements_chain`. Read only its first element or two: that is the element the user touched, and everything after it is ancestors.

Both run through `execute-sql`.

## 3. Rank what came back

Work down this list and stop at the first tier that produces a candidate, because a lower tier never beats a higher one.

### Tier 1: stack traces

An `$exception` in the window is the strongest possible anchor. It names a source file outright, with no inference:

- `$exception_sources` is an **array** of the source files the stack touched, for example `["posthog/temporal/common/posthog_client.py", "products/error_tracking/backend/temporal/weekly_digest/activities.py"]`. Read all of them and take the one inside the customer's own tree: the array is not one entry per frame, and index 1 is not reliably the thrower.
- `$exception_types` and `$exception_values` are arrays too, holding the exception class and message. Their lengths do not line up with `$exception_sources`.
- `$exception_issue_id` points at the error tracking issue. Follow it with `query-error-tracking-issue-events` (`verbosity: stack`) for the full stack trace, the symbolicated frames, and captured code variables.

The singular forms (`$exception_type`, `$exception_message`) are emitted on a tiny fraction of events, so do not filter on them.

An unsymbolicated frame names the compiled artifact, not the source. Paths that look like bundle chunks or a binary mean symbolication has not run for that release, and you are back at tier 2.

### Tier 2: developer-authored element identifiers

`data-attr` (PostHog's default data attribute, configurable per team), `data-testid`, and the HTML `id` are strings a human typed into their own source, so they are greppable by construction.

Two things about how they appear that the format reference does not say. posthog-js writes captured DOM attributes with an `attr__` prefix, so you will read `attr__data-attr="capability-badge-sql"` and `attr__id="main-content"` alongside a separate un-prefixed `attr_id="main-content"` — match on the `key="value"` part and grep the repo for the **value** alone. And `elements_chain_ids` gives you the ids as an array with no parsing at all, so start there and read the raw chain only when you need a `data-*` attribute.

On mobile, autocapture carries the label the developer set on the view, and the SDKs spell it differently (React Native uses `ph-label` and falls back to `testID`; iOS uses `postHogLabel`). Whatever the SDK set lands in the chain as a `key="value"` pair, because the chain carries arbitrary attributes through unchanged, so read the chain and take the label you actually find rather than assuming a key name. Android and Flutter follow the same shape but are unverified here.

For the chain's grammar and its CSS-selector-to-regex mapping, read the `elements-chain-format.md` reference in the `exploring-autocapture-events` skill, keeping the `attr__` prefix above in mind as you read it.

### Tier 3: text and route

Weaker, but usually present.

- **Element text**, from `elements_chain_texts`. Greppable, and often the fastest hit in a small codebase. Fragile under i18n (the string in the repo is a translation key, not the rendered text) and under interpolated or dynamic content.
- **Route**, from `$current_url` / `$pathname` on web and `$screen_name` on mobile. For file-routed frameworks (Next.js app router, Nuxt, SvelteKit, Remix) the URL maps to a file almost mechanically, which makes this the most reliable fallback when there is no interaction to work from.

### Worthless: class names

Do not grep class names. Tailwind and utility-CSS class soup matches everything, and CSS modules and styled-components emit hashed names that appear nowhere in the source.

The mobile equivalent is the bare widget type. When no label was set, the chain holds `UIButton` or `UITextField`, which identifies a framework class, not the customer's code. Treat it as no anchor at all.

## 4. When the window is empty

An empty window is information, not a failure, but it is not proof that nothing happened. It usually means no interaction at that moment, which is what you would expect from a banner that rendered on load, a layout that broke on resize, or a crash mid-render. It can also mean the interaction went uncaptured (autocapture is off for the team) or that the anchor is wrong.

Fall back to tier 3 and attribute by route alone, and say the element is unknown. Do not invent one: a fabricated selector sends the next reader, or the coding agent downstream, into the wrong file with false confidence.

## 5. Take the anchor to the repo

```bash
rg -F 'checkout-submit'                  # tier 2: an id or data-attr, fixed-string
rg -F 'Payment could not be processed'   # tier 3: on-screen text
```

Then `git blame --ignore-revs-file $(git rev-parse --show-toplevel)/.git-blame-ignore-revs` the region you land on to find the commit that introduced the behavior.

Two things to hold onto:

- **A hit is a candidate, not an answer.** Confirm the file you found actually renders the element or route the events named, before reporting it.
- **Attribution quality tracks the customer's own conventions.** A codebase with `data-attr` or `postHogLabel` discipline resolves at tier 2 nearly every time; one without drops to tier 3 and is genuinely harder. Say which tier a finding rests on so the reader can weigh it.
