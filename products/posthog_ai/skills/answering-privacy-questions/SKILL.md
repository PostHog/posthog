---
name: answering-privacy-questions
description: How to answer questions about PostHog privacy and compliance, data deletion, data retention, and help PostHog users with related tasks, such as generating and signing a DPA or BAA, deleting persons, events or session recordings (including GDPR and CCPA erasure requests), and opening a support ticket for what only PostHog staff can answer. Use when a user asks for a DPA or BAA, asks to delete data or handle a data subject request, or asks privacy, security, compliance, data retention, and/or data deletion questions.
---

# Answering privacy questions

The server instructions' rules hold throughout: open the latest posthog.com page before you answer (add `.md` for clean text), cite the page you opened, and never give legal advice or compliance advice beyond what PostHog's docs say, and mention that PostHog strongly suggests customers consult with their own legal counsel on such questions.

## Rules

These rules cover privacy, security, retention, deletion, data region, DPA, BAA, subprocessor, AI data and compliance (SOC 2, HIPAA, GDPR, CCPA) questions.

- Answer from the latest docs, not from memory or docs-search (docs-search includes insufficient summaries and stale cache). Docs change often: find pages with web search, open them with web fetch (add .md for clean text).
- Cite the URL you opened for every fact. Only name pages you've actually opened.
- Speak for yourself: say what you know in your own words, without saying it comes from this skill or another, and don't predict how support will reply.
- Security and compliance facts are in /docs and also https://posthog.com/handbook/company/security. Link https://trust.posthog.com only for documents gated there (e.g. SOC 2 report), naming the document, since you can't read it.
- For subprocessors, link https://posthog.com/subprocessors and mention its tabs for each processor type.
- Before mentioning an endpoint, check that all users can access it. Docs or repo code don't prove it: some are flagged for staff or a few orgs. Check docs outside /docs/api for hints, with web search and web fetch, not `docs-search`. E.g., on Nov 19, 2026, /data-deletion-requests and its UI were behind a feature flag.
- Offer and link to docs only for the self-serve path (the DPA or BAA generator, retention settings, the AI data processing toggle). For options not on all plans, say what the user's plan includes and which plans they can upgrade to.
- Link the relevant docs and say: "I can share what PostHog's docs say, but PostHog can't give legal advice on GDPR, HIPAA, CCPA or any other law. Please check with your own legal counsel."
- If the docs don't fully answer it, say what's missing. If only PostHog staff can answer it, offer to open a support ticket from the skill.
- If sources conflict, use the most recently updated unless something proves it wrong, and offer a support ticket to get clarification.

The details below say where to look and what the docs said when this skill was written (last checked Nov 19, 2026, and the deletion routes Nov 24, 2026). Docs change often, so open the page and go by it. If the page and this skill disagree, the page wins.

Lead with the self-serve path. Open a support ticket only when there is no self-serve option and the docs don't answer it, or when someone who can open one still disagrees that the docs do (section 5).

## 1. Check the user's plan first

Many options depend on the plan. Find the user's plan, then offer what it includes and name the plan(s) that would add what they asked for. Confirm each line on its page before you quote it.

| Item                          | Availability as of Nov 19, 2026                                                                                                                                                                                              | Check on                                                                                                                 |
| ----------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------ |
| DPA                           | Every PostHog Cloud plan, including free                                                                                                                                                                                     | https://posthog.com/docs/privacy (FAQ: "How do I get a signed DPA?")                                                     |
| Standard BAA                  | Boost, Scale or Enterprise platform package                                                                                                                                                                                  | https://posthog.com/docs/privacy/hipaa-compliance and https://posthog.com/baa                                            |
| Custom BAA                    | Enterprise only                                                                                                                                                                                                              | https://posthog.com/docs/privacy/hipaa-compliance                                                                        |
| Events retention              | Free: fixed at 1 year. Paid: 2 years by default, up to 3 years with Boost, 5 with Scale, 7 with Enterprise. Org admins and owners change it.                                                                                 | https://posthog.com/docs/data/events-retention and https://posthog.com/pricing                                           |
| Recording retention           | From 30 days on Free up to 5 years on Enterprise, by plan. A change applies only to new recordings.                                                                                                                          | https://posthog.com/docs/session-replay/recording-retention                                                              |
| Custom contract terms         | Standard terms for everyone. A custom MSA with custom SLAs and legal terms is Enterprise only. DPA redlines generally need a long-term contract through sales.                                                               | https://posthog.com/platform-packages, https://posthog.com/docs/support-options#terms-and-conditions and the privacy FAQ |
| Security questionnaires       | Cloud customers get PostHog's standard security assessment (docs and Trust Center). Enterprise customers can have their own questionnaire completed.                                                                         | https://posthog.com/docs/support-options#security-assessment                                                             |
| Support tickets               | Free: community support only on the pricing page; tickets are usually limited to billing issues, plus staff-run deletions for privacy or security reasons (section 5). Paid: email support, and Slack above a monthly spend. | https://posthog.com/pricing and https://posthog.com/docs/support-options                                                 |
| Person and recording deletion | Self-serve on every plan                                                                                                                                                                                                     | https://posthog.com/docs/privacy/data-storage#data-deletion                                                              |

## 2. DPA

Read https://posthog.com/docs/privacy (FAQ: "How do I get a signed DPA?") and https://posthog.com/dpa. For GDPR context, https://posthog.com/docs/privacy/gdpr-compliance.

As of the last check:

1. Any PostHog Cloud customer can get a DPA, on any plan, including free.
2. An org member opens the legal page in their PostHog app (app.posthog.com/legal), starts a new DPA and enters the company details.
3. PostHog's signature is already on it. PandaDoc emails the signer a link.
4. It takes effect the moment they sign, with no wait for PostHog.
5. The text at posthog.com/dpa is a non-binding preview. Only the copy generated in the app counts.

Related asks:

- **Redlines, an NDA, or custom terms:** quote the privacy FAQ answer on redlines and confidentiality agreements, and say custom terms come with an Enterprise contract (section 1). On a paid plan, offer a ticket if they still want to ask.
- **Which DPA applies to us, or a copy of the signed one:** the signer's PandaDoc email holds their copy. If nobody can find it, or they need an acceptance record, that's a staff lookup (section 5).
- **What a DPA clause means for their situation:** that's legal interpretation. Link the DPA section and give the legal counsel line. PostHog support can't give legal advice either.

## 3. BAA

Read https://posthog.com/docs/privacy/hipaa-compliance, https://posthog.com/baa and the privacy FAQ ("Can I use PostHog Cloud under HIPAA?").

As of the last check:

- A **standard BAA** needs Boost, Scale or Enterprise. It's generated on the same legal page as the DPA and countersigned through the app (the BAA page and the privacy FAQ agree on this).
- A **custom BAA** needs Enterprise and goes through PostHog (the HIPAA page says to contact PostHog with your requirements).
- The HIPAA page also says the generator creates a BAA "for us to countersign". The docs don't tie that wording to a plan. If the user asks how signing works, give the standard path above and offer a ticket for clarification on a paid plan.
- Say plainly what a BAA doesn't cover (the HIPAA page lists it), and that a signed BAA doesn't make a setup compliant on its own.
- Plan edge cases (trials, credits, signing before a package is active) aren't documented. On a paid plan, offer a ticket (section 5).

## 4. Deletion

Match the ask to a route, and open the pages for that route before you describe it.

| They want to                                                 | Self-serve route                                                                                                                                                                                        | Read first                                                                                                   |
| ------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------ |
| Erase a known person (GDPR or CCPA request)                  | Delete the person in the app, or call persons `bulk_delete` with `delete_events` and `delete_recordings` set. Check progress with `deletion_status`.                                                    | https://posthog.com/docs/privacy/data-storage#right-to-be-forgotten and https://posthog.com/docs/api/persons |
| Delete recordings only                                       | Session recordings delete or `bulk_delete`                                                                                                                                                              | https://posthog.com/docs/api/session-recordings                                                              |
| Remove events older than a date                              | Events retention setting (section 1). Recording retention is separate.                                                                                                                                  | https://posthog.com/docs/data/events-retention                                                               |
| Delete an account, project or organization                   | Settings                                                                                                                                                                                                | https://posthog.com/docs/privacy/data-storage#data-deletion                                                  |
| Delete all events for one distinct ID with no person profile | Give the distinct ID a person profile, then delete that person, as the page describes.                                                                                                                  | https://posthog.com/docs/privacy/data-storage#data-deletion                                                  |
| Delete events by name, time or filter                        | Off by default. Open a ticket (below). Support runs the deletion, or, for a one-off deletion that one query can select, can turn on self-serve event deletion (app and API) so they file it themselves. | https://posthog.com/docs/privacy/data-storage#deleting-specific-events                                       |
| Remove a property but keep the events                        | None, and support usually can't. They delete the events instead, so open a ticket (below) only if that is what they want.                                                                               |                                                                                                              |

Before naming any endpoint, check that every user can call it (server instructions). On the free plan, or when you can't tell the plan, don't mention self-serve event deletion: offer a ticket that asks support to run the deletion, which only an organization owner or admin can send. Self-serve event deletion (the data deletion requests endpoint and its UI) works only for organizations that support turned it on for, so whenever you mention either one, say that they can't use it until support adds their organization. On a plan you know isn't the free plan, for a one-off deletion of whole events that one query can select, tell them they can ask support to turn it on, for both the app and the API (docs: https://posthog.com/docs/privacy/data-storage#deleting-specific-events). It can't remove properties, run on a schedule, or delete persons or recordings. Support runs any other event deletion, with the query and count below. Once it's on, their project settings have a "Deletion requests" section for organization admins, owners, and members who are given access, and PostHog reviews each request before any events are deleted. Never say it's on for them, or that it will be.

When you describe a self-serve route:

- Say deletion is permanent, and name what it removes as the page states it. If they ask what deletion leaves behind and the page doesn't say, tell them it isn't documented.
- For timing, quote the asynchronous data deletion section of the data storage page, and give only the timing it states.
- API calls need a personal API key with the scope the API page names, sent to the user's own region (US or EU).
- Offer only routes from the pages you opened.

When there's no self-serve route, collect these for the ticket, so staff can act without asking again. A ticket that only asks to turn on event deletion can leave out the query and count:

- **Region and project ID**, from a project URL the user gives you. `us.posthog.com` and `app.posthog.com` are US, `eu.posthog.com` is EU. Each environment needs its own request.
- **The user's own SQL query** that selects exactly the events to delete, and **the count it returned**. You can help them write it, but they run it and confirm the count. Keep their scope exactly as they wrote it.
- **The time window, with its timezone.** A bare date in a query means the project's timezone.
- **Who's asking:** their name and role in the org, so staff can confirm they can request it. Only an organization owner or admin can send a deletion ticket, so tell a member that one of them needs to submit it.
- **Why they need it:** ask, and put their answer in the ticket. For example privacy (a data subject request) or security (PII or secrets captured in event data). On the free plan this decides whether a ticket is possible (section 5).

## 5. Opening a support ticket

Open one only when there's no self-serve option and the docs don't answer it, or the person still disagrees that they do, and only for what the user's plan supports. An organization under 3 months old, or on a trial that includes support, can open the same tickets as a paid plan.

**On a paid plan**, these need staff:

- an account-specific record, like which DPA they signed or proof of acceptance
- a deletion with no self-serve route (section 4)
- a figure or commitment the docs don't publish, needed for a review or questionnaire (Enterprise customers can have their own questionnaire completed; other plans get the standard assessment)
- contract changes such as redlines or custom BAA terms (Enterprise; on other plans, say so and name the upgrade)
- trouble getting access to a gated Trust Center document
- docs that conflict, when the user needs a firm answer

**On the free plan, or when you can't tell the plan**, tickets from here are only for billing issues, with one exception. For a deletion with no self-serve route, ask why they need it first. If the reason is privacy or security (like PII or secrets in the data), open a ticket with the section 4 details and that reason. For anything else, answer from the docs and say where they can ask. On the free plan, tell them community support is available at https://posthog.com/forum (other options are on https://posthog.com/docs/support-options), that any paid plan adds support, and which plan adds the feature they need. When you can't tell the plan, give both routes: the support panel at https://app.posthog.com/home#panel=support if their plan includes support, or the forum if it doesn't, and don't say that any paid plan adds support. The forum is public, so tell them to leave out personal data and secrets. Don't offer to write the post. The `writing-posthog-support-tickets` skill says what to do when they ask for one.

**When they can't log in**, don't open a ticket. Give them the login help from the `writing-posthog-support-tickets` skill, in your own words.

When the docs answer the question, answer and cite instead of opening a ticket. If someone on a paid plan, a trial that includes support, or in a new organization still disagrees that the docs answer it, offer a ticket that includes the answer you gave and its links. Skip the ticket when the ask is legal interpretation (give the legal counsel line). If the docs answer part of it, answer that part with a citation and open a ticket only for the rest.

How it works (paid plans, trials that include support, new organizations, and the free-plan deletions above):

1. Load the `writing-posthog-support-tickets` skill and write the ticket with it: what they asked, what the docs say (with the links you opened), what's still missing, and the details staff need (for a deletion, the section 4 list). Set `topic` to match, and use `privacy_or_security_deletion` only when they gave a privacy or security reason.
2. Show them the full draft and let them edit it. Send it only when they say yes to that version, so they don't copy or paste anything.
3. First give them the ticket number when the send returns one, and tell them to log in to PostHog and watch the support panel in the right-hand sidebar for replies, at https://app.posthog.com/home#panel=support.

If they also want to ask about something outside these topics, don't put it in the ticket. On a paid plan, on a trial that includes support, or in a new organization, they can ask in the support widget. On the free plan, point them to https://posthog.com/forum, which is public, so they should leave out personal data and secrets. When you can't tell the plan, give both.

Use only the support ticket tool for this. The `conversations-tickets-*` tools manage the user's own Conversations inbox, not PostHog support.

The `writing-posthog-support-tickets` skill and its deletion reference say what the ticket holds. Partially redact personal data (emails, names, IP addresses) everywhere else in the ticket, but never in a deletion query or an ID support needs to find the data, because support uses those exactly as written. Redact like `j***@exa***.com`, so the customer can see what you're referring to without revealing the PII. If staff need the full values, they'll ask in the ticket.

## Good habits

- Link Trust Center documents and say they're gated there. Describe only what a page you opened says about them.
- Link https://posthog.com/subprocessors for subprocessors, and mention its tabs for different types of processors.
- State only retention periods, deletion timelines and compliance claims from pages you opened.
- Describe what a BAA, DPA or setting covers, and leave the compliance judgment to the customer and their counsel.

## Sources (opened Nov 19, 2026, and data storage again Nov 24, 2026)

- https://posthog.com/docs/privacy
- https://posthog.com/dpa
- https://posthog.com/baa
- https://posthog.com/docs/privacy/hipaa-compliance
- https://posthog.com/docs/privacy/gdpr-compliance
- https://posthog.com/docs/privacy/data-storage
- https://posthog.com/docs/api/persons
- https://posthog.com/docs/api/session-recordings
- https://posthog.com/docs/data/events-retention
- https://posthog.com/docs/session-replay/recording-retention
- https://posthog.com/pricing
- https://posthog.com/platform-packages
- https://posthog.com/docs/support-options
