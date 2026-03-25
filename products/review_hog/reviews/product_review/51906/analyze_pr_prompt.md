You are the first step in a product review pipeline. Your job is to look at a PR's changed files and figure out what parts of the product are affected, so the next step can query PostHog for usage data.

Keep your output compact — the next steps don't need exhaustive detail, they need the right hooks to query PostHog and understand what area of the product is being touched.

## PR Metadata

```json
{
  "number": 51906,
  "title": "feat(inbox): Error tracking signal sources UI",
  "body": "## Problem\r\n\r\nInbox signal sources had no way to turn on the new Error Tracking signals of #51645 from the UI, and when those signals showed up they looked generic (raw `error_tracking / issue_created` etc.) compared to the other integrations.\r\n\r\n## Changes\r\n\r\n![CleanShot 2026-03-23 at 11 02 17](https://github.com/user-attachments/assets/06374742-e9e9-41fa-a92a-61b2b20a2a48)\r\n\r\nAdding a \"PostHog Error Tracking\" toggle that toggles all three `SignalSourceConfig` types (`issue_created`, `issue_reopened`, `issue_spiking`) so it matches what Cymbal actually checks on emit.\r\n\r\nDedicated error tracking card - fingerprint, spike baseline/current when relevant, link to the issue. Debug graph + detail panel use the same labeling. Nicer header lines for session replay / DW sources too while I was there.\r\n\r\n## How did you test this code?\r\n\r\nShould have Storybook \u2026 but not yet. Tested locally with actual error tracking \r\n\r\n## Publish to changelog?\r\n\r\nNo, not rolled out yet\r\n\r\n## Docs update\r\n\r\nskip-inkeep-docs (n/a)\r\n",
  "state": "closed",
  "draft": false,
  "created_at": "2026-03-23T10:28:29+00:00",
  "updated_at": "2026-03-26T01:04:01+00:00",
  "author": "Twixes",
  "author_association": "MEMBER",
  "base_branch": "master",
  "head_branch": "03-23-feat_inbox_error_tracking_signal_sources_and_ui",
  "mergeable_state": "unknown",
  "requested_reviewers": [],
  "assignee": null,
  "labels": [],
  "commits": 21,
  "additions": 291,
  "deletions": 33,
  "changed_files": 12
}
```

## Changed Files

```json
[
  {
    "filename": "frontend/src/lib/signals/errorTracking.ts",
    "status": "added",
    "additions": 15,
    "deletions": 0
  },
  {
    "filename": "frontend/src/lib/signals/signalCardSourceLine.ts",
    "status": "added",
    "additions": 29,
    "deletions": 0
  },
  {
    "filename": "frontend/src/queries/schema.json",
    "status": "modified",
    "additions": 16,
    "deletions": 0
  },
  {
    "filename": "frontend/src/queries/schema/schema-signals.ts",
    "status": "modified",
    "additions": 23,
    "deletions": 0
  },
  {
    "filename": "frontend/src/scenes/debug/signals/DetailPanel.tsx",
    "status": "modified",
    "additions": 20,
    "deletions": 5
  },
  {
    "filename": "frontend/src/scenes/debug/signals/SignalGraph.tsx",
    "status": "modified",
    "additions": 7,
    "deletions": 1
  },
  {
    "filename": "frontend/src/scenes/debug/signals/helpers.tsx",
    "status": "modified",
    "additions": 9,
    "deletions": 0
  },
  {
    "filename": "frontend/src/scenes/inbox/SignalCard.tsx",
    "status": "modified",
    "additions": 51,
    "deletions": 4
  },
  {
    "filename": "frontend/src/scenes/inbox/SourcesList.tsx",
    "status": "modified",
    "additions": 17,
    "deletions": 0
  },
  {
    "filename": "frontend/src/scenes/inbox/signalSourcesLogic.ts",
    "status": "modified",
    "additions": 79,
    "deletions": 8
  },
  {
    "filename": "frontend/src/scenes/inbox/types.ts",
    "status": "modified",
    "additions": 6,
    "deletions": 15
  },
  {
    "filename": "posthog/schema.py",
    "status": "modified",
    "additions": 19,
    "deletions": 0
  }
]
```

## What to do

You have a full checkout of this repository at the PR's branch. Use it to read files and trace code paths.

### 1. Figure out what routes/pages are affected

Group changed files by feature area (files sharing a parent directory). For each group, read enough code to determine:

- What route/page do these files belong to? Look at how the app defines routes — discover the pattern from the code.
- What URL pattern does this route serve?
- One-line product description of what this page does (write it for a PM, not an engineer)

### 2. Find PostHog events and feature flags

In the changed files, look for:

- **PostHog event names** — `posthog.capture()` calls, wrapper functions, action dispatchers. Just extract the event name strings.
- **Feature flag keys** — string literals passed to flag-checking functions.

Important: many codebases (including PostHog) dispatch analytics events through centralized wrappers — e.g. a shared `eventUsageLogic` or analytics utility that maps action names to `posthog.capture()` calls. If the changed files dispatch actions that resolve to capture calls in a central file, follow that one hop to extract the actual event names. Don't crawl the whole codebase, but do follow the event dispatch chain one level beyond the changed files.

## Output

Return ONLY valid JSON conforming to this schema (no markdown formatting, no explanatory text):

```json
{
  "$defs": {
    "AffectedRoute": {
      "properties": {
        "route_key": {
          "description": "Short identifier for the route (e.g., 'surveyWizard')",
          "title": "Route Key",
          "type": "string"
        },
        "description": {
          "description": "One-line product description of what this page does",
          "title": "Description",
          "type": "string"
        },
        "url_patterns": {
          "description": "URL patterns this route serves (e.g., ['/surveys/guided/:id'])",
          "items": {
            "type": "string"
          },
          "title": "Url Patterns",
          "type": "array"
        }
      },
      "required": ["route_key", "description", "url_patterns"],
      "title": "AffectedRoute",
      "type": "object"
    },
    "PRInfo": {
      "properties": {
        "number": {
          "title": "Number",
          "type": "integer"
        },
        "title": {
          "title": "Title",
          "type": "string"
        },
        "author": {
          "title": "Author",
          "type": "string"
        },
        "description": {
          "default": "",
          "title": "Description",
          "type": "string"
        }
      },
      "required": ["number", "title", "author"],
      "title": "PRInfo",
      "type": "object"
    }
  },
  "properties": {
    "pr": {
      "$ref": "#/$defs/PRInfo"
    },
    "affected_routes": {
      "items": {
        "$ref": "#/$defs/AffectedRoute"
      },
      "title": "Affected Routes",
      "type": "array"
    },
    "posthog_events": {
      "description": "PostHog event names found in changed code",
      "items": {
        "type": "string"
      },
      "title": "Posthog Events",
      "type": "array"
    },
    "feature_flag_keys": {
      "description": "Feature flag keys found in changed code",
      "items": {
        "type": "string"
      },
      "title": "Feature Flag Keys",
      "type": "array"
    }
  },
  "required": ["pr"],
  "title": "PRManifest",
  "type": "object"
}
```

Keep it lean. No per-file breakdowns, no API endpoint lists, no source_file attributions. The next step needs route URL patterns (to query pageviews), event names (to query counts), and flag keys (to check status). Everything else is noise at this stage.
