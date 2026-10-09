<!-- Generated from backend/logic/schema.py. Do not edit. Run `hogli build:projections`. -->

| Command                    | Also      | What it does                                                                                                                                      |
| -------------------------- | --------- | ------------------------------------------------------------------------------------------------------------------------------------------------- |
| `@posthog review [--full]` |           | Start a Flash review of this pull request. Where Flash isn't available yet, the full review runs. `--full`: Run the full review instead of Flash. |
| `@posthog stamp`           | `approve` | Ask Stamphog to review this pull request. Stamphog decides whether to approve.                                                                    |
| `@posthog qa [<focus>]`    |           | Run frontend QA on this pull request in PostHog Code and post a report. `<focus>`: What to focus on. The agent gets it as your instruction.       |
| `@posthog loop <name>`     |           | Run one of your own Loops with this pull request as its input. `<name>`: The loop's name.                                                         |
| `@posthog help`            |           | List these commands.                                                                                                                              |
