---
name: finding-experiments
description: "Resolves experiment references from natural language to concrete experiment IDs. Handles name lookups, fuzzy descriptions ('the signup experiment', 'my latest experiment'), status filtering, and disambiguation when multiple experiments match.\nTRIGGER when: user refers to an experiment by name, description, or relative reference ('latest', 'most recent', 'the one I created yesterday') and you don't already have the experiment ID.\nDO NOT TRIGGER when: user provides an experiment ID directly, or you already resolved the experiment earlier in the conversation."
---

# Finding experiments

Users refer to experiments by name, description, or relative references — not by ID.
This skill resolves natural language references to concrete experiment IDs.

## How to find an experiment

Use the **experiment-list** tool from the Posthog-local MCP server.

IMPORTANT: Do NOT use `feature-flag-get-all` or any feature flag tool to find
experiments. Use the dedicated experiment list tool: `experiment-list`.

This tool returns experiments with their id, name, status, feature_flag_key,
start_date, end_date, and created_at. Browse the returned list to find the
experiment matching the user's reference:

- **By name**: scan the `name` field for matches
- **By recency**: results are ordered newest first by default
- **By status**: match the `status` field (draft, running, stopped)
- **By flag key**: match the `feature_flag_key` field

## After finding matches

- **Exactly one match**: Use it. Confirm with the user by name before destructive actions (delete, ship, end).
- **Multiple matches**: List them with name, status, and creation date. Ask the user to pick.
- **No matches**: Tell the user. Suggest checking archived experiments or different terms.

## Get full details if needed

After resolving to an ID, call `experiment-get` for the full object (metrics, flag details, parameters).

## Examples

```text
User: "pause my signup experiment"

Agent:
1. Calls experiment-list
2. Scans results, finds "New signup process" (ID: 1371, status: running)
3. Proceeds to pause experiment 1371
```

## When NOT to search

- You already have the experiment ID from earlier in the conversation
- The user just created the experiment — you have the ID from the create response
- The user provided the ID directly
