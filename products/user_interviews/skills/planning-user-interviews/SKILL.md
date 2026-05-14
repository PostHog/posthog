---
name: planning-user-interviews
description: 'Plan a user interview topic in PostHog — pick who to target (cohort, emails, or PostHog distinct IDs), draft what to ask about, and prepare the voice-agent context plus a question list. Use when the user asks to "talk to users", "check how users feel about X", "interview some customers", "set up a user interview", "run a user-research call", "find users to ask about Y", or otherwise wants qualitative feedback through a conversation. Walks the user through targeting (cohorts-list, persons-list, or accepting emails / distinct IDs directly), captures the topic, and prompts for agent context and questions before calling user-interview-topics-create. Do NOT trigger when the user is uploading a recorded interview audio file (that''s the separate UserInterview/transcript flow) or only browsing existing topics with user-interview-topics-list.'
---

# Planning user interviews

Use this skill when someone asks to set up a user interview — to talk to customers, check sentiment, or gather qualitative feedback through a voice conversation. The plan is captured as a `UserInterviewTopic` that a voice agent will later run through.

## What a complete topic needs

Before calling `user-interview-topics-create`, gather these:

1. **Who to interview** — at least one of:
   - `interviewee_cohort` — an existing cohort ID
   - `interviewee_emails` — list of email addresses
   - `interviewee_distinct_ids` — list of PostHog distinct IDs
2. **What to ask about** — `topic` (required free text)
3. **How the agent should frame the conversation** — optional `agent_context` (extra system prompt)
4. **The questions to work through** — optional ordered `questions` list

The API rejects topics with no targeting, so at least one of the three audience fields must be set. They can be combined — a cohort plus a handful of extra emails is fine.

## Step 1: Clarify intent

If the request is vague, ask:

- **Which feature or behavior?** "checkout" might be the button click, the page view, or the payment submission — narrow it down to one event.
- **What do you want to learn?** Why they bounced? What confused them? What alternatives they tried? The goal shapes both the audience and the questions.
- **Which kind of users?** Heavy users (what works), drop-offs (what blocks adoption), at-risk users (what breaks retention), or a mix.

Skip these questions only when the user has already answered them.

## Step 2: Pick the audience

Map what the user said to one of these paths:

- **They named a cohort** ("our power users", "trial signups last week") — use `cohorts-list` filtered by name to find the cohort, confirm the match, and pass the cohort ID as `interviewee_cohort`.
- **They described the kind of person but no cohort exists** — offer to either create the cohort first (`cohorts-create`) or fall back to finding people by behavior (see below).
- **They gave email addresses or distinct IDs** — accept them directly. Skip the cohort lookup.
- **They described a behavior, not a cohort** ("users who tried checkout but didn't finish", "people who used to use dark mode and stopped") — find them by querying their events (see below).
- **They were vague** ("a few customers", "some power users") — ask which they prefer:
  - Pick an existing cohort → `cohorts-list`
  - Look up specific persons by name or email → `persons-list` with a search query
  - Find users by behavior → see below
  - Paste a list of email addresses

Each email passes through DRF email validation (display-name format `Paul D'Ambra <paul@x.com>` is accepted alongside plain `paul@x.com`).

### Finding users by behavior

When the user describes who they want to talk to in behavioral terms, find them in the project's own data:

1. **Find the right event.** Call `read-data-schema` to list events that actually exist in the project. Don't guess event names from training data — PostHog event taxonomies are bespoke. Match the user's description to one or two candidate events; if multiple plausible matches exist, list them and ask which behavior they care about.
2. **Query for users.** Call `execute-sql` with HogQL. Filter by the chosen event over the last 60 days, group by person — prefer `person.properties.email` (directly usable as `interviewee_emails`), fall back to `distinct_id` (for `interviewee_distinct_ids`). Keep both kinds of rows. The aggregates in each template (`event_count`, `last_seen`, `days_since_last_seen`) are what feed Step 5's per-interviewee context. Replace `<event_name>` with the chosen event, and `<id>` with `person.properties.email` or `distinct_id`:
   - **Heavy users** — `SELECT <id> AS id, count() AS event_count, max(timestamp) AS last_seen, dateDiff('day', max(timestamp), now()) AS days_since_last_seen FROM events WHERE event = '<event_name>' AND timestamp > now() - INTERVAL 60 DAY GROUP BY <id> HAVING count() >= 5 ORDER BY count() DESC LIMIT 20`
   - **Drop-offs** (tried once or twice and never came back) — `SELECT <id> AS id, count() AS event_count, max(timestamp) AS last_seen, dateDiff('day', max(timestamp), now()) AS days_since_last_seen FROM events WHERE event = '<event_name>' AND timestamp > now() - INTERVAL 60 DAY GROUP BY <id> HAVING count() <= 2 AND dateDiff('day', max(timestamp), now()) > 14 ORDER BY count() ASC LIMIT 20`
   - **At-risk** (was active, now dormant) — `SELECT <id> AS id, count() AS event_count, max(timestamp) AS last_seen, dateDiff('day', max(timestamp), now()) AS days_since_last_seen FROM events WHERE event = '<event_name>' AND timestamp > now() - INTERVAL 60 DAY GROUP BY <id> HAVING count() >= 3 AND dateDiff('day', max(timestamp), now()) > 14 ORDER BY days_since_last_seen DESC LIMIT 20`
3. **Build a balanced sample.** Unless the user asked for one specific segment, mixing 5 heavy users + 3 drop-offs + 2 at-risk users yields the most actionable interviews: you learn what works, what blocks adoption, and what breaks retention. Adjust counts to match what the user actually wants.

Pass the email rows as `interviewee_emails` and the distinct-ID rows as `interviewee_distinct_ids` — both can be set on the same topic. Keep `event_count` and `days_since_last_seen` per person so Step 5 can synthesise context like "used checkout 47 times in last 60 days; last seen 2 days ago".

## Step 3: Capture the topic

`topic` is one or two sentences describing what the interview is about. Infer from context where possible — don't ask the user to repeat themselves.

Example: "ask trial users why they didn't convert" → `topic: "Why trial users didn't convert in the first 14 days"`.

## Step 4: Prepare the voice agent

Two fields shape what the agent actually does on the call. **Always ask about both before creating the topic.**

### Always ask: what questions do they want to ask?

`questions` is an ordered list the agent works through. Anchors, not a script — the agent will adapt phrasing. Keep them open-ended:

- ✅ "What made you decide to try PostHog?"
- ❌ "Did you like PostHog?"

If the user already listed questions in their original request, use those and confirm. Otherwise, ask explicitly: _"What questions do you want the agent to ask?"_

If the user can't think of any, suggest 3–5 open-ended questions drawn from the `topic` and offer them for review before creating.

The field is technically optional in the API, but don't skip it silently — an interview with no questions is rarely useful.

Question templates by research goal:

- **Why users dropped off / churned**:
  - "Tell me about the last time you tried [feature] — what were you trying to do?"
  - "Walk me through what happened step-by-step."
  - "What did you expect vs what actually happened?"
  - "What made you stop or decide not to continue?"
  - "What would need to change for you to use [feature] regularly?"
- **Why heavy users love a feature**:
  - "Tell me about how you use [feature] — what problem does it solve for you?"
  - "Walk me through your typical workflow."
  - "What would you do if [feature] didn't exist?"
  - "What almost made you not use it when you first tried?"
  - "What's one thing you wish it did differently?"
- **Why someone hasn't tried a feature yet**:
  - "Have you noticed [feature] in the product?"
  - "What's stopped you from trying it?"
  - "What would have to be true for it to be worth trying?"

### Always offer: extra context to guide the interview

`agent_context` is optional, but a few sentences here make the conversation dramatically better. Always offer the user the chance to provide it, e.g.:

> _"Want to give the agent any extra context? Things like tone, what to avoid, or background on the interviewee help guide the conversation. It's optional."_

Useful kinds of context:

- **Tone**: "warm and conversational", "skip pleasantries — this is a 10-minute call"
- **Constraints**: "don't promise feature delivery", "do not discuss pricing"
- **Background the agent should know**: "the user just churned from the Scale plan; be empathetic", "this person tried PostHog 6 months ago and bounced"
- **Persona**: "you are Sam, a PostHog product researcher"

If the user declines, that's fine — leave `agent_context` empty and continue.

## Calling user-interview-topics-create

Once you have the pieces:

```json
{
  "topic": "Why trial users churned in week 2",
  "interviewee_cohort": 42,
  "interviewee_emails": ["paul@acme.com"],
  "agent_context": "Be warm. The interviewee just churned — don't pitch.",
  "questions": [
    "What were you hoping PostHog would help with?",
    "Where did you get stuck?",
    "What would have made you stay?"
  ]
}
```

After creation, capture the returned topic ID — you'll need it for Step 5 and for handing off to the voice agent.

## Step 5: Optionally attach per-interviewee context

The topic-level `agent_context` applies to every interviewee. If the user knows something specific about individual interviewees that should shape that one conversation, attach it as a per-interviewee row via `user-interview-topics-interviewees-create`. This is optional — most topics won't need it.

Each row pairs an `interviewee_identifier` (must match one of the emails or distinct IDs in the parent topic's targeting) with an `agent_context` string. At most one row per (topic, interviewee). A user can have zero rows.

Good per-interviewee context looks like:

- "uses the replay product but has never used summarization"
- "churned from Scale plan last month — be empathetic, don't pitch"
- "founder, very technical, skip basic product explanations"

After Step 4 succeeds, ask the user: _"Want to add per-interviewee context? Useful when individual people have very different backgrounds. You can either dictate the rows or paste a CSV."_

If you found the audience via behavioral query in Step 2, you already have per-person context (usage counts, dormancy windows). Use it: e.g. `"used checkout 47 times in last 60 days; last seen 2 days ago"` for heavy users, `"tried checkout once 18 days ago, never returned"` for drop-offs.

### Accepting CSV input

If the user pastes a CSV, expect two columns: `identifier,context`. Either with or without a header row. Examples:

```csv
paul@acme.com,uses replay but never summarization
steve@apple.com,founder; very technical; skip product basics
```

Or with a header:

```csv
identifier,context
abc-distinct-id-1,churned from Scale last month — be empathetic
```

Parse the CSV, then call `user-interview-topics-interviewees-create` once per row with the captured `topic_id`. Skip blank lines. Quote-escape commas inside the context cell — standard CSV rules.

If a row's identifier isn't present in the parent topic's `interviewee_emails` or `interviewee_distinct_ids`, warn the user before creating — the voice agent looks up context by exact string match, so a mismatched identifier just gets ignored at runtime.

## Edge cases

- **No users match the behavioral query.** Possible reasons: the event isn't firing, the date range is too narrow, or no users have email addresses captured as person properties. Offer to widen the date range, try a different event, or fall back to cohorts / explicit emails.
- **Users matched but few have emails.** PostHog stores whatever the SDK captures. If only a handful of matching users have email addresses on their person profile, surface the count and ask: take the smaller sample, fall back to `interviewee_distinct_ids` (the agent can still reach them via in-app delivery), or skip the behavioral query and let the user paste emails directly.
- **Ambiguous event name.** If `read-data-schema` returns multiple candidates (e.g. `checkout_started`, `checkout_completed`, `checkout_abandoned`), list them with counts and let the user pick the behavior they want to understand. Don't pick silently.
- **User asks to interview only drop-offs (or only one segment).** That works, but flag the tradeoff: interviewing only drop-offs tells you what's broken without telling you what works. Recommend including 2–3 successful users for contrast unless the user has a reason for the narrower sample.

## What this skill is not for

- **Uploading a recorded interview** — that's the separate `UserInterview` model (`user_interviews_create` with an audio file). Different flow, different model.
- **Listing existing topics** — `user-interview-topics-list` handles that directly with `search`, `limit`, and `offset`. No skill needed.
- **Analyzing transcripts after the interview** — out of scope here; that lives with the recorded `UserInterview` flow.
