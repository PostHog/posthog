# Twitter Referral Research

Agentic flow that finds Twitter/X users posting enthusiastic, personal endorsements of PostHog
in the last hour, so the growth team can DM them and ask for referrals to other companies that
would benefit from PostHog.

Built on the same sandbox primitive as the signals research flow (`MultiTurnSession`), but
single-turn for now: one prompt → one structured response.

## What lives here

- `research/research.py`
  Orchestrates the sandbox session via `MultiTurnSession.start(...)` then `session.end()`.
  Entry point: `run_twitter_research(context, *, api_key, since_unix_ts, hours, ...)`.
- `research/prompts.py`
  - `RelevantTweet` and `TwitterReferralCandidates` pydantic models (the structured output).
  - `build_twitter_research_prompt(...)` — the single prompt with curl instructions, enthusiasm
    criteria, and the JSON schema the agent must match.
- `management/commands/analyze_twitter_posts.py`
  Local dev CLI mirroring `analyze_report`. Reads `TWITTERAPI_IO_KEY` from the env, computes the
  `since_unix_ts` cutoff, resolves a sandbox context, runs the agent once, prints candidates.

## Mental model

`run_twitter_research()` builds a single prompt containing:

1. The exact `curl` command (with the API key inlined) the agent should run inside the sandbox
   to fetch all tweets mentioning `PostHog` since the cutoff timestamp, excluding retweets.
2. Selection criteria for "loves PostHog enough to refer" — strong positive sentiment,
   first-person voice, PostHog as the focus, active builder/founder signal. Excludes stack
   lists, tag-only replies, neutral mentions, criticism.
3. A JSON schema (`TwitterReferralCandidates`) for the structured response.

The agent shells out (`curl`, `jq`), paginates if `has_next_page` is true, judges each tweet
against the criteria, and returns a list of `{id, user, reason}` objects — empty when nothing
in the window meets the bar.

## API key handling

The Twitter API key is injected directly into the prompt at call time. The caller reads
`TWITTERAPI_IO_KEY` from its own environment (the management command does this today) and
passes it as `api_key=`. The sandbox itself does not need any env-var plumbing.

## Sandbox repo

The agent does not need the PostHog source tree — it only needs `curl` and `jq`. The local
debug command defaults to cloning `PostHog/.github` (small) to keep sandbox spin-up fast,
matching the pattern used by `select_repo.py` in the signals flow.

## Local debug command

```bash
# Default: last 1 hour, PostHog/.github sandbox clone
python manage.py analyze_twitter_posts

# Wider window for testing prompt behavior
python manage.py analyze_twitter_posts --hours 6

# Stream full raw sandbox logs
python manage.py analyze_twitter_posts --verbose
```

Requires `TWITTERAPI_IO_KEY` in the shell env and a GitHub integration set up on the first
team in the local database (same prerequisite as `analyze_report`).

## When editing this flow

- Keep this module **prompt-orchestration only**. Persistence (recording the candidates,
  marking who's already been DMed) belongs in the caller — today the management command,
  later a Temporal activity.
- If you change the output shape of `TwitterReferralCandidates`, also update the prompt's
  example/schema notes in `prompts.py` so the agent still produces matching output.
- If you broaden the search beyond "last hour" (e.g. weekly digest), add it as a parameter
  to `run_twitter_research` and the management command rather than forking the orchestrator.
- The plan is to add a Temporal cron schedule that runs this hourly. When that lands, the
  caller activity should pass `branch=None`, generate a fresh `since_unix_ts`, and persist
  the resulting candidates somewhere durable (model TBD) before DM outreach.
- **If you change any command or the flow, update this file to match.**
