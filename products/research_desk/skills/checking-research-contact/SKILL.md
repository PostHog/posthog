---
name: checking-research-contact
description: >
  Checks whether PostHog already contacted a customer for research before anyone recommends reaching out for an
  interview, using the research desk MCP tools. Use when someone asks who to interview, whether a person or company
  was recently contacted, which upcoming customer research sessions they can join, or when a new interview
  recruiting workflow, survey, cohort or event turns up that the contact check does not know about yet.
---

# Checking research contact

Several PostHog teams recruit customers for interviews.
Without a check, the same customer gets asked by three teams in a month.
The research desk tools let you see prior research touches before you suggest outreach.

## Before you recommend outreach

Call `research-desk-contact-check` before you suggest that anyone contact a customer for research.
Pass the person's `emails`, the company `domain`, or both.
Pass the domain only for a company domain, not for a personal mail domain such as `gmail.com`.

Report each touch with:

- who owns it (`owner_email`), so the person can ask that colleague first
- when it happened (`occurred_at`); a cohort touch has no date and means "in an already contacted list"
- what it was (`channel` and `source_label`), such as a recruiting email, a survey, or an interview session

`recently_contacted` is a warning, not a block.
Say that the customer was contacted recently and by whom, then let the person decide.
Do not refuse to help, and do not contact the customer yourself.

When the check finds no touches, say so plainly.
It covers only registered sources, so "no touches" does not prove that nobody ever reached out.

## Finding sessions to join

Call `research-desk-sessions-list` with `start_after` set to now and `start_before` set to the end of the window the person asked about.
Skip sessions with status `cancelled`.
Offer the title, start time, organizer and meeting link, and suggest that they ask the organizer before they join.

## Registering a new recruiting source

When you find an interview recruiting workflow, survey, cohort or event that the contact check should count, check `research-desk-sources-list` first, so you do not register it twice.
If it is not there, call `research-desk-sources-create`:

- `kind`: `workflow`, `survey`, `cohort` or `event`
- `external_id`: the workflow ID, survey ID, cohort ID or event name
- `label`: a short name a colleague would recognize
- `owner_email` and `product_area` when you know them

Use only sources that recruit for research.
A marketing or onboarding workflow is not a research touch.
To stop counting a source, call `research-desk-sources-update` with `active` set to false instead of creating a new one.
