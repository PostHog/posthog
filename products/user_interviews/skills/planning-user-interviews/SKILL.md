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

## Step 1: Pick the audience

Map what the user said to one of three paths:

- **They named a cohort** ("our power users", "trial signups last week") — use `cohorts-list` filtered by name to find the cohort, confirm the match, and pass the cohort ID as `interviewee_cohort`.
- **They described the kind of person but no cohort exists** — offer to either create the cohort first (`cohorts-create`) or fall back to listing specific people.
- **They gave email addresses or distinct IDs** — accept them directly. Skip the cohort lookup.
- **They were vague** ("a few customers", "some power users") — ask which they prefer:
  - Pick an existing cohort → `cohorts-list`
  - Look up specific persons by name or email → `persons-list` with a search query
  - Paste a list of email addresses

Each email passes through DRF email validation (display-name format `Paul D'Ambra <paul@x.com>` is accepted alongside plain `paul@x.com`).

## Step 2: Capture the topic

`topic` is one or two sentences describing what the interview is about. Infer from context where possible — don't ask the user to repeat themselves.

Example: "ask trial users why they didn't convert" → `topic: "Why trial users didn't convert in the first 14 days"`.

## Step 3: Prepare the voice agent

Two fields shape what the agent actually does on the call. **Always ask about both before creating the topic.**

### Always ask: what questions do they want to ask?

`questions` is an ordered list the agent works through. Anchors, not a script — the agent will adapt phrasing. Keep them open-ended:

- ✅ "What made you decide to try PostHog?"
- ❌ "Did you like PostHog?"

If the user already listed questions in their original request, use those and confirm. Otherwise, ask explicitly: _"What questions do you want the agent to ask?"_

If the user can't think of any, suggest 3–5 open-ended questions drawn from the `topic` and offer them for review before creating.

The field is technically optional in the API, but don't skip it silently — an interview with no questions is rarely useful.

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

After creation, show the new topic ID so it can be handed off to the voice agent.

## What this skill is not for

- **Uploading a recorded interview** — that's the separate `UserInterview` model (`user_interviews_create` with an audio file). Different flow, different model.
- **Listing existing topics** — `user-interview-topics-list` handles that directly with `search`, `limit`, and `offset`. No skill needed.
- **Analyzing transcripts after the interview** — out of scope here; that lives with the recorded `UserInterview` flow.
