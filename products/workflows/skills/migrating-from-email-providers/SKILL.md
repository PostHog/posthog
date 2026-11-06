---
name: migrating-from-email-providers
description: 'Move a team from an email API provider such as Resend or Postmark to PostHog: import the suppression list, unsubscribes, topics, templates and automations with the provider-imports tools, then walk through DNS, template review and the cutover. Use when asked to migrate, move, switch, copy or import from Resend or Postmark to PostHog, or to bring suppressions, unsubscribes or email templates from another provider. For Customer.io automations use migrating-from-customer-io.'
---

# Moving from another email provider

PostHog copies a team's data in one background import. The team then sets up DNS, reviews what the import flagged, and moves its sending one email at a time.

Call `provider-imports-providers` first. It lists the tools this project can import from, the steps of each, and the next steps to read out at the end. If the team's tool isn't listed, the import isn't turned on for this project, so stop and say so.

The sections below use Resend as the example. For Postmark, also read [Postmark](#postmark).

## What moves

| Data                     | In PostHog                        | What the team does                                  |
| ------------------------ | --------------------------------- | --------------------------------------------------- |
| Suppression list         | Suppression list                  | Reads the summary                                   |
| Unsubscribed contacts    | Opted out of all marketing email  | Nothing                                             |
| Topics and topic choices | Marketing categories and opt-outs | Checks topics that only send to people who opted in |
| Templates                | Library templates, keyed by alias | Fixes what the notes mention, then sends a test     |
| Automations              | Draft workflows                   | Sends trigger events to PostHog, reviews, enables   |
| Domains                  | A list only                       | Adds each domain and publishes new DNS records      |

API keys, webhooks, send history and stats stay with the old provider. Contacts never become people. Importing people has a separate list upload, and it creates billable events, so only mention it if the user asks.

## Steps

1. **Confirm the project.** Read it with `project-get`, tell the user its name and id, and ask whether the data belongs there. If not, switch with `switch-project`.
2. **Get a key.** Resend has no read-only keys, so the import needs a full access key. Ask the user to create one at https://resend.com/api-keys, just for this import. Tell them PostHog only reads from their account and deletes the key when the run ends. Treat the key as a secret: don't repeat it, log it or write it to a file. They can also run the import themselves in the app under Workflows, Opt-outs, Import from another tool.
3. **Check for a running import.** `provider-imports-list`. A new start while one is active returns 409, so report on that run instead.
4. **Choose the steps.** Take them all unless the user says otherwise. `topic_opt_outs` reads contacts one at a time, about 7,000 an hour. On a very large list, say so and offer to skip it. A run stops after 24 hours, about 150,000 contacts into that step. Importing again continues from where it stopped.
5. **Start.** `provider-imports-create` with `provider`, `steps` and `api_key`.
6. **Follow it.** Poll `provider-imports-get` every minute or so. A `running` step with a `last_error` is retrying by itself, so don't start again. Report each step's `counts`.
7. **Handle failure.** `status: failed` means the key is gone too. Read `last_error`: a rejected key needs a new key, anything else can run again. Importing again adds what's missing and doesn't duplicate anything.
8. **Report the notes.** Go through `items` with the user: each template and workflow with its link and notes. Say plainly how many spam complaints imported, because PostHog still sends them transactional email while Resend doesn't.
9. **Walk through the switch.** See below. Then tell the user to delete the key in Resend.

## Importing again never undoes a change

An address someone removed from the suppression list, a person opted back in, an edited or deleted category, and an edited or deleted template all stay as they are. So a template or automation imported before does not pick up changes from Resend. To re-import one, change its alias in Resend, or copy the change by hand.

## The switch

1. **Domains.** PostHog signs mail with its own keys, so a domain needs new records even if it already sends through Resend. Add each domain under Workflows, Channels and publish the records. Keep the Resend records, because both tools can sign for one domain. A `items` note says when Resend already uses PostHog's default `feedback` subdomain: choose another MAIL FROM subdomain there, because two services can't share one MX record.
2. **Templates.** Fix what the notes mention. Resend fills `FIRST_NAME` and other contact fields itself, and PostHog doesn't, so the app must pass them. Send a test to the user's own address.
3. **Code.** Use the `sending-transactional-emails` skill. The template key is the Resend alias, or `resend-<id>` when it has none. Move one low-risk email first. Map errors too: PostHog refuses a send to a hard-bounced address with `recipient_suppressed`, and that must not go back into a retry loop.
4. **Automations.** Each draft notes which events the app has to send to PostHog as well. Use the `building-workflows` skill to test and enable. Turn the automation off in Resend at the same moment, or people get both emails. Never enable a draft without the user's sign-off.
5. **Volume.** Mailbox providers slow down a sudden jump, so move high volume over several days. Check the project's allowance with `workflows-reputation-get` first, because new projects start with a low limit on marketing email.
6. **Clean up.** Once nothing sends through Resend, the user removes its DNS records and deletes the key.

## Postmark

Postmark has no automations and no contact list, so the steps are `streams`, `suppressions`, `templates`, `domains` and `webhooks`.

| Data                          | In PostHog                                                             | What the team does                                                |
| ----------------------------- | ---------------------------------------------------------------------- | ----------------------------------------------------------------- |
| Servers, message streams      | A list. A broadcast stream the team added becomes a marketing category | Chooses the category on marketing email that used the stream      |
| Hard bounces                  | Suppression list, blocks all email                                     | Reads the summary                                                 |
| Spam complaints               | Suppression list, blocks marketing email                               | Reads the summary                                                 |
| Added by the team or Postmark | Suppression list, blocks marketing email                               | Reads the summary                                                 |
| Unsubscribed                  | Opted out of all marketing email                                       | Nothing                                                           |
| Templates and layouts         | Library templates, each with its own copy of its layout                | Fixes what the notes mention, chooses a sender, then sends a test |
| Domains, sender signatures    | A list only                                                            | Adds each domain and sender, and publishes new DNS records        |
| Webhooks                      | A list only                                                            | Rebuilds them                                                     |

1. **Choose the token.** Postmark has no read-only tokens. A server token imports one server, and `domains` then reports that it needs the account token. The account token imports every live server and also lists domains and senders, but it can change everything in the account, so offer the choice and say that. Sandbox servers are skipped with an account token, because their suppressions aren't real. Their own server token imports them.
2. **Say what changes.** Suppressions belong to one stream in Postmark and to the whole project in PostHog. `transactional_block_lost` counts people Postmark blocks on a transactional stream for a reason other than a hard bounce. PostHog still sends them transactional email, so say the number. Someone who unsubscribed from one broadcast stream is opted out of all marketing email.
3. **Templates.** The key is the alias, with characters PostHog doesn't allow replaced by `-`, or `postmark-<id>` when there is no alias. When two servers share an alias, the later one gets `<alias>-<server id>`. Postmark's `TemplateModel` becomes `message_data` values read as `variables.<name>`. A template doesn't name a sender in Postmark, so choose one on each.
4. **Rendering.** Layouts are copied into each template. Postmark copies style-block CSS onto elements when it sends and PostHog doesn't, and PostHog prints `true` where Postmark prints `True`, so send a test and check it.
5. **Code.** Change the app's Postmark calls to PostHog's send API with the `sending-transactional-emails` skill. PostHog has no SMTP service, so an app sending over SMTP has to change to the API too.
