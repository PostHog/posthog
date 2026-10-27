---
name: installing-posthog-from-chat
description: >-
  Set up PostHog in a user's GitHub repository from a chat, without a terminal. Wizard, PostHog's
  setup agent, runs in the cloud, adds the SDK and first events, and opens a pull request. Use only
  when you can't read or edit the user's code, which is common in web chat apps such as ChatGPT on the
  web or Claude on the web. Typical requests: install, add, or set up PostHog in their app or
  repository, or open a pull request that adds PostHog. When you're working in the user's repository, use
  installing-posthog-in-a-codebase instead. Covers connecting GitHub, picking the repository, starting
  the run, polling it, and sharing the pull request.
---

# Installing PostHog from chat

Wizard is PostHog's setup agent. With `wizard-install-start` it runs in a cloud workspace on a GitHub repository, makes the code changes, and opens a pull request. The user reviews and merges that pull request. Nothing changes on their default branch until they do.

Work through the steps in order. Skip a step when its outcome is already known from the conversation.

## 1. Connect GitHub

The run uses the project's GitHub connection, so the project needs one.

1. Call `integrations-list` and look for an integration with kind `github`.
2. When there is none, give the user this link, built from the base URL and project ID in your context: `<base URL>/integrations/connect/github/?project_id=<project id>&connect_from=mcp`. They install the PostHog GitHub App and choose which repositories it can access. Wait until they say they are done, then call `integrations-list` again.

## 2. Pick the repository

Call `integrations-github-repos-retrieve` with the GitHub integration's ID. Use `search` when the user named the repository, and page with `offset` when `has_more` is true.

- One clear match: confirm it with the user in one line.
- Several matches: list them and ask which one.
- No match: the GitHub App cannot access it. Ask the user to add the repository to the app's repository access in GitHub, then search again.

Pass the repository as `full_name` (`owner/name`).

The setup agent works at the repository root. If the user describes a monorepo where the app lives in a subdirectory, tell them the run may not find it, and offer to try anyway.

## 3. Start the run

Call `wizard-install-start` with:

- `repository`: the `owner/name` from step 2.
- `branch`: only when the user wants a branch other than the default one. The pull request targets that branch.
- `idempotency_key`: a fresh unique value for this request. Reuse the same value if you retry after a network error, so the retry returns the same run.

Errors the user can act on:

| Error code                  | What to do                                                                                               |
| --------------------------- | -------------------------------------------------------------------------------------------------------- |
| `github_not_connected`      | Go back to step 1.                                                                                       |
| `repository_not_accessible` | Ask the user to add the repository to the PostHog GitHub App, then retry with a new `idempotency_key`.   |
| `run_already_active`        | The user already has a run in progress in this project. Ask them to wait for it, or check it in PostHog. |
| HTTP 429                    | The user reached the hourly or daily limit for setup runs. Relay the message. Don't retry right away.    |

Tell the user the run started and share the `url` from the response, where they can follow it in PostHog.

## 4. Poll the run

Call `wizard-install-status` with the `run_id` about every 30 seconds while `status` is `created` or `running`. A run usually takes several minutes.

- Relay `next_step` to the user when it changes. It is written to be passed on as is.
- Mention progress from `tasks` when it helps, but don't send an update on every poll.
- Stop polling when `status` is `completed`, `failed`, or `cancelled`.

When the client cannot wait that long in one turn, tell the user the run is in progress and check again when they come back.

## 5. Share the result

- `completed` with `pull_request_url`: share the link. Say the user should review the changes and merge the pull request to finish setting up PostHog.
- `completed` without `pull_request_url`: the setup agent changed nothing, often because PostHog is already set up. Relay `next_step`.
- `failed`: relay `next_step` and `error_message`. Offer to start a new run when `next_step` suggests one.
