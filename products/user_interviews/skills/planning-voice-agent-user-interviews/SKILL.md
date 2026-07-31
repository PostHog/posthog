---
name: planning-voice-agent-user-interviews
description: 'Plan a round of user interviews conducted by PostHog''s AI voice agent (a "robo interviewer") — the automated voice-agent interview product. Captures a UserInterviewTopic (who to target, what to ask, framing context, question list) and calls user-interview-topics-create. ONLY trigger when the user clearly wants an AI voice agent to actually run the interview calls (e.g. "set up robo user interviews", "have the voice agent interview these users"). Do NOT trigger for ordinary user research that does not involve the voice agent — finding or shortlisting users to talk to ("who''d be a good fit to interview about Y"), planning questions for a human-run interview, or analysing feedback are audience discovery, handled with normal data queries, not this skill. Also do NOT trigger for uploading a recorded interview audio file or browsing topics with user-interview-topics-list. When intent is ambiguous, first confirm what kind of research it is and whether they want an AI voice agent to conduct it (see Step 0).'
---

# Planning voice-agent user interviews

Use this skill **only** when someone wants PostHog's AI voice agent — a "robo interviewer" — to actually conduct a round of user interview calls for them. The plan is captured as a `UserInterviewTopic` that the voice agent later runs through, calling each targeted person and working through the questions.

This is a specific product, not a generic research helper. If the user only wants to _find_ or _shortlist_ people to interview, plan questions for an interview a human will run, or analyse feedback they already have, this is **not** the right skill — handle that as ordinary audience discovery / data work (see `querying-posthog-data`) and, at most, mention that the voice-agent option exists.

## Step 0: Confirm this is the voice-agent flow

Before doing anything else, make sure the user actually wants the AI voice agent to run the interviews. Many requests that mention "interviewing users" are really about discovering _who_ to talk to, not about handing the conversation to a robot.

- If the user explicitly asked for the voice agent / robo interviews / automated calls, proceed to Step 1.
- If they only asked to find or rank users to interview (e.g. "who'd be a good fit to interview about the inbox?"), treat it as audience discovery: answer it with normal queries and **do not** create a topic. You may add a one-line offer afterwards, e.g. _"If you want, I can set these up as automated interviews run by PostHog's AI voice agent — want me to do that?"_
- If intent is ambiguous, ask first, e.g. _"Quick check on what you're after: what kind of user research is this, and do you want PostHog's AI voice agent to actually run the interviews (it calls people and works through your questions)? Or did you just want me to find the right users to talk to?"_

Only continue past this step once the user has confirmed they want the voice agent to conduct the interviews.

## What a complete topic needs

Before calling `user-interview-topics-create`, gather these:

1. **Who to interview** — at least one of:
   - `interviewee_emails` — list of email addresses
   - `interviewee_distinct_ids` — list of PostHog distinct IDs
2. **What to ask about** — `topic` (required free text)
3. **How the agent should frame the conversation** — optional `agent_context` (extra system prompt)
4. **The questions to work through** — optional ordered `questions` list

Topics snapshot their audience at create time — there is no live cohort link. If the user names a cohort, you (the agent) resolve cohort members to emails/distinct_ids before calling `user-interview-topics-create`. See Step 2 for the resolution flow and the 500-member cap UX.

The API rejects topics with no targeting, so `interviewee_emails` and/or `interviewee_distinct_ids` must end up non-empty.

## Step 1: Clarify intent

If the request is vague, ask:

- **Which feature or behavior?** "checkout" might be the button click, the page view, or the payment submission — narrow it down to one event.
- **What do you want to learn?** Why they bounced? What confused them? What alternatives they tried? The goal shapes both the audience and the questions.
- **Which kind of users?** Heavy users (what works), drop-offs (what blocks adoption), at-risk users (what breaks retention), or a mix.

Skip these questions only when the user has already answered them.

## Step 2: Pick the audience

Map what the user said to one of these paths:

- **They named a cohort** ("our power users", "trial signups last week") — use `cohorts-list` (or a `system.cohorts` SQL search) to find the cohort, confirm the match, then resolve cohort members to emails/distinct_ids (see "Resolving a cohort" below).
- **They described the kind of person but no cohort exists** — offer to either create the cohort first (`cohorts-create`), then resolve it, or fall back to finding people by behavior (see below).
- **They gave email addresses or distinct IDs** — accept them directly. Skip the cohort lookup.
- **They described a behavior, not a cohort** ("users who tried checkout but didn't finish", "people who used to use dark mode and stopped") — find them by querying their events (see below).
- **They were vague** ("a few customers", "some power users") — ask which they prefer:
  - Pick an existing cohort → `cohorts-list`
  - Look up specific persons by name or email → `persons-list` with a search query
  - Find users by behavior → see below
  - Paste a list of email addresses

Each email passes through DRF email validation (display-name format `Paul D'Ambra <paul@x.com>` is accepted alongside plain `paul@x.com`).

### Resolving a cohort

Topics snapshot their audience at create time. When the user picks a cohort, you must materialize the member list into `interviewee_emails` (and `interviewee_distinct_ids` for members without emails) before creating the topic.

1. **Count the cohort first.** Cheap query, decides the next step:

   ```sql
   SELECT count() FROM persons WHERE id IN COHORT <cohort_id>
   ```

2. **If the cohort has 500 or fewer members**, fetch their emails:

   ```sql
   SELECT properties.email AS email
   FROM persons
   WHERE id IN COHORT <cohort_id> AND properties.email IS NOT NULL
   LIMIT 500
   ```

   Put each row into `interviewee_emails`. Dedupe.

   Cohort members without an email property aren't included by default — the `persons.id` column is the person UUID, not the SDK distinct_id, so it can't be used as an `interviewee_distinct_id` without a `pdi.distinct_id` join. If you specifically need to reach members who only exist as distinct IDs, ask the user first, then do the join explicitly.

3. **If the cohort has more than 500 members**, stop and ask the user. Do not silently truncate, sample, or fall back to a different cohort — the user needs to choose. Surface:
   - The cohort name and count (e.g. "PostHog Team has 28,563 members — over the 500 cap.")
   - Why the cap exists ("we snapshot the audience at create time, and 500 is an agent-side guardrail to keep one interview campaign manageable — the backend itself does not cap the array length")
   - Their options:
     - **Narrow the cohort** — describe the subset they actually want (e.g. "engineers only", "active in the last 30 days"). You can offer to write a more specific HogQL filter or create a new, smaller cohort via `cohorts-create`.
     - **Sample randomly** — confirm a count (e.g. 200) and use `ORDER BY rand() LIMIT <n>` on the cohort query. Make the randomness explicit so they know they're not getting the "top" members.
     - **Paste a curated list** — they take over and provide emails directly.

   Pick the path with them, then re-run the resolution. Never proceed without an explicit decision.

4. **Tell the user what you resolved.** After resolution, confirm before creating: "Cohort 'X' has N members, resolved to E emails and D distinct IDs (snapshot — won't update if the cohort changes later)." This makes the snapshot semantics visible.

### Finding users by behavior

When the user describes who they want to talk to in behavioral terms, find them in the project's own data:

1. **Find the right event.** Call `read-data-schema` to list events that actually exist in the project. Don't guess event names from training data — PostHog event taxonomies are bespoke. Match the user's description to one or two candidate events; if multiple plausible matches exist, list them and ask which behavior they care about.
2. **Query for users.** Call `execute-sql` with HogQL. Filter by the chosen event over the last 60 days and group per person with `coalesce(person.properties.email, distinct_id) AS id` — this keeps both kinds of rows in a single query: people with an email group under it (directly usable as `interviewee_emails`), while emailless people fall back to their own `distinct_id` (for `interviewee_distinct_ids`) instead of collapsing into one junk `None` bucket that would sort to the top under `ORDER BY count() DESC` and eat a slot of the sample. The selected `email` column tells you which is which when routing (see below). The aggregates in each template (`event_count`, `last_seen`, `days_since_last_seen`) are what feed Step 5's per-interviewee context. Replace `<event_name>` with the chosen event:
   - **Heavy users** — `SELECT coalesce(person.properties.email, distinct_id) AS id, person.properties.email AS email, count() AS event_count, max(timestamp) AS last_seen, dateDiff('day', max(timestamp), now()) AS days_since_last_seen FROM events WHERE event = '<event_name>' AND timestamp > now() - INTERVAL 60 DAY GROUP BY id, email HAVING count() >= 5 ORDER BY count() DESC LIMIT 20`
   - **Drop-offs** (tried once or twice and never came back) — `SELECT coalesce(person.properties.email, distinct_id) AS id, person.properties.email AS email, count() AS event_count, max(timestamp) AS last_seen, dateDiff('day', max(timestamp), now()) AS days_since_last_seen FROM events WHERE event = '<event_name>' AND timestamp > now() - INTERVAL 60 DAY GROUP BY id, email HAVING count() <= 2 AND dateDiff('day', max(timestamp), now()) > 14 ORDER BY count() ASC LIMIT 20`
   - **At-risk** (was active, now dormant) — `SELECT coalesce(person.properties.email, distinct_id) AS id, person.properties.email AS email, count() AS event_count, max(timestamp) AS last_seen, dateDiff('day', max(timestamp), now()) AS days_since_last_seen FROM events WHERE event = '<event_name>' AND timestamp > now() - INTERVAL 60 DAY GROUP BY id, email HAVING count() >= 3 AND dateDiff('day', max(timestamp), now()) > 14 ORDER BY days_since_last_seen DESC LIMIT 20`
3. **Build a balanced sample.** Unless the user asked for one specific segment, mixing 5 heavy users + 3 drop-offs + 2 at-risk users yields the most actionable interviews: you learn what works, what blocks adoption, and what breaks retention. Adjust counts to match what the user actually wants.

Route each row by its `email` column: rows where `email` is non-null go into `interviewee_emails`, and rows where `email` is null (so `id` holds the `distinct_id`) go into `interviewee_distinct_ids` — both can be set on the same topic. Keep `event_count` and `days_since_last_seen` per person so Step 5 can synthesise context like "used checkout 47 times in last 60 days; last seen 2 days ago".

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
  "interviewee_emails": ["paul@acme.com", "alex@beta.com"],
  "interviewee_distinct_ids": ["distinct-id-with-no-email"],
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

Parse the CSV, then create the rows with the captured `topic_id`. For more than a couple of rows, prefer `user-interview-topics-interviewees-bulk-create` — it takes an `items` array of `(interviewee_identifier, agent_context)` and creates up to 500 rows in one request, reporting `inserted_count`, `skipped_count`, and `skipped_identifiers` for pairs that already exist. Fall back to `user-interview-topics-interviewees-create` for a single row. Skip blank lines. Quote-escape commas inside the context cell — standard CSV rules.

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
