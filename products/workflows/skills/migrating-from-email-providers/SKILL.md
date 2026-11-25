---
name: migrating-from-email-providers
description: 'Move a team from an email API provider such as Resend, Postmark, SendGrid, Mailgun or Mailchimp to PostHog: import the suppression list, unsubscribes, topics, mailing lists, templates and automations with the provider-imports tools, then walk through DNS, template review and the cutover. Use when asked to migrate, move, switch, copy or import from Resend, Postmark, SendGrid, Mailgun or Mailchimp to PostHog, "switch to PostHog", or to bring suppressions, unsubscribes or email templates from another provider. For Customer.io automations use migrating-from-customer-io.'
---

# Moving from another email provider

PostHog copies a team's data in one background import. The team then sets up DNS, reviews what the import flagged, and moves its sending one email at a time.

Call `provider-imports-providers` first. It lists the tools this project can import from, the steps of each, and the next steps to read out at the end. If the team's tool isn't listed, the import isn't turned on for this project, so stop and say so.

The sections below use Resend as the example. For Postmark, also read [Postmark](#postmark), for SendGrid, [SendGrid](#sendgrid), for Mailgun, [Mailgun](#mailgun), and for Mailchimp, [Mailchimp](#mailchimp).

## What moves

| Data                     | In PostHog                                                | What the team does                                  |
| ------------------------ | --------------------------------------------------------- | --------------------------------------------------- |
| Suppression list         | Suppression list                                          | Reads the summary                                   |
| Contacts and segments    | People, matched by email, and a static cohort per segment | Checks the people and cohorts                       |
| Unsubscribed contacts    | Opted out of all marketing email                          | Nothing                                             |
| Topics and topic choices | Marketing categories and opt-outs                         | Checks topics that only send to people who opted in |
| Templates                | Library templates, keyed by alias                         | Fixes what the notes mention, then sends a test     |
| Automations              | Draft workflows                                           | Sends trigger events to PostHog, reviews, enables   |
| Domains                  | A list only                                               | Adds each domain and publishes new DNS records      |

API keys, webhooks, send history and stats stay with the old provider. The `contacts` step fills in what the person whose email matches each contact lacks, without changing values PostHog already has, and `new_people` creates a person for each contact no one matches, with the email as the ID. Resend's `contact_properties` copies custom contact properties the same way. Each person written counts as one billable event.

## Steps

1. **Confirm the project.** Read it with `project-get`, tell the user its name and id, and ask whether the data belongs there. If not, switch with `switch-project`.
2. **Check for a running import.** `provider-imports-list`. A new start while one is active returns 409, so report on that run instead of asking for a key.
3. **Get a key.** Resend has no read-only keys, so the import needs a full access key. Ask the user to create one at https://resend.com/api-keys, just for this import. Tell them PostHog only reads from their account and deletes the key when the run ends. Treat the key as a secret: don't repeat it, log it or write it to a file. They can also run the import themselves in the app under Workflows, Opt-outs, Import from another tool.
4. **Choose the steps.** Take them all unless the user says otherwise. Before including `new_people`, tell the user how many contacts they have and that each new person counts as one event, and leave it out if they'd rather not create people. Automations also need `cohort:write` on a PostHog key with limited scopes, and `contacts`, `new_people` and `contact_properties` need `cohort:write` and `person:write`. On a refusal that names one, drop those steps or ask the user for that scope. `topic_opt_outs` and `contact_properties` read contacts one at a time, about 7,000 an hour each. On a very large list, say so and offer to skip it. The largest account an import takes, 250,000 contacts, needs about a day and a half for each of these steps, and a run can take up to four days. If a run stops early, the next import from Resend continues from where it stopped, but only with the same key, so the user keeps the key until every step has finished.
5. **Start.** `provider-imports-create` with `provider`, `steps` and `api_key`.
6. **Follow it.** Poll `provider-imports-get` every minute or so. A `running` step with a `last_error` is retrying by itself, so don't start again. Report each step's `counts`.
7. **Handle failure.** `status: failed` means the key is gone too. Read `last_error`: a rejected key needs a new key, anything else can run again. Importing again adds what's missing and doesn't duplicate anything.
8. **Report the notes.** Go through `items` with the user: each template and workflow with its link and notes. A link is a path in the PostHog app, so put the project's PostHog URL in front of it. Say plainly how many spam complaints imported, because PostHog still sends them transactional email while Resend doesn't.
9. **Walk through the switch.** See below. Once every step has finished, tell the user to delete the key in Resend.

## SendGrid

SendGrid differs from the Resend steps above in these ways.

- **Key.** SendGrid has read-only scopes, so ask for a restricted key with read access to the chosen steps. Each step's description in `provider-imports-providers` names its scopes. A key without them is refused before the run starts, with the missing scopes named. `marketing.read` is the exception: SendGrid says it also grants write access, so `single_sends` and `lists` are the steps to skip for a user who minds. Keys are created at https://app.sendgrid.com/settings/api_keys.
- **Subusers.** A key sees one account. To move subusers, run one import per subuser with its own key, one after another. PostHog finds out by itself whether a key belongs to SendGrid's EU host.

| Data                                      | In PostHog                                       | What the team does                                  |
| ----------------------------------------- | ------------------------------------------------ | --------------------------------------------------- |
| Bounces and invalid addresses             | Suppression list, blocks all email               | Reads the summary                                   |
| Spam reports                              | Suppression list, blocks marketing email only    | Reads the summary. SendGrid blocks all email.       |
| Global unsubscribes                       | Opted out of all marketing email                 | Reads the summary. SendGrid blocks all email.       |
| Unsubscribe groups and group unsubscribes | Marketing categories and opt-outs                | Passes the category when sending                    |
| Dynamic and legacy templates              | Library templates, keyed by SendGrid template ID | Fixes what the notes mention, then sends a test     |
| Design Library, Single Sends              | Library templates                                | Fixes the notes, cancels what's still scheduled     |
| Lists, verified senders, domains          | A list only                                      | Rebuilds lists as cohorts, adds senders and domains |

**Stays behind:** automations, because SendGrid's API only shares their stats, so they're rebuilt by hand as workflows. Blocks, because SendGrid doesn't keep suppressing those addresses either. Also inactive template versions, contacts as people, webhooks, API keys, stats and send history.

**Templates.** Only each template's active version comes across. Handlebars becomes Liquid and app data goes in `variables`, so `{{order.id}}` is sent the same way as before. The team has to choose a sender on each template, because SendGrid sets it per send. Say plainly how many global unsubscribes and spam reports imported, because PostHog still sends them transactional email while SendGrid doesn't.

## Importing again never undoes a change

An address someone removed from the suppression list, a person opted back in, an edited or deleted category, and an edited or deleted template all stay as they are. So a template or automation imported before does not pick up changes from Resend. To re-import one from Resend, change its alias there. Otherwise copy the change by hand.

## The switch

1. **Domains.** PostHog signs mail with its own keys, so a domain needs new records even if it already sends through Resend. Add each domain under Workflows, Channels and publish the records. Keep the Resend records, because both tools can sign for one domain. A note in `items` says when Resend already uses PostHog's default `feedback` subdomain: choose another MAIL FROM subdomain there, because two services can't share one MX record.
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

## Mailgun

Follow the same steps, with these differences.

**Region.** Ask which region the domains are in: `us`, `eu` or `both`, passed as `settings: {"region": "..."}`. Mailgun keeps data in each region apart, and PostHog only sends the key to the region chosen. If the domains step warns that a region has no domains, the user picked the wrong one.

**Key.** An account API key, created in Mailgun under Account settings, API keys. A domain sending key can't read anything. On a plan with key roles, use Support: it's the smallest role that can read suppressions, though Mailgun lets it make changes too. An Analyst key can't read bounces, complaints or unsubscribes, so the start is refused unless those steps are left out.

**Versions.** The active version imports by default. Pass `template_versions: "all"` only if the app names a version when it sends.

| Mailgun                   | In PostHog                                    | What the team does                               |
| ------------------------- | --------------------------------------------- | ------------------------------------------------ |
| Bounces, every domain     | Suppression list, blocks all email            | Reads the summary                                |
| Complaints, every domain  | Suppression list, blocks marketing email only | Knows these people still get transactional email |
| Unsubscribes for all mail | Opted out of all marketing email              | Nothing                                          |
| Unsubscribes for a tag    | Opted out of a new category named after it    | Puts the matching templates in that category     |
| Allowlists                | A list only                                   | Removes test addresses meant to bounce           |
| Mailing lists             | A category, and opt-outs for who left         | Puts the matching templates in that category     |
| List members              | People, matched by email, and cohorts         | Checks the people and cohorts                    |
| Templates                 | Library templates in Liquid                   | Fixes the notes, passes variables, sends a test  |
| Domains and DNS records   | A list only                                   | Adds each domain and publishes new records       |

**Contacts.** `contacts` and `new_people` appear only where they're turned on. Without them, list members don't become people. `contacts` needs `bounces`, `complaints`, `unsubscribes` and `mailing_lists` in the same run. Each list gets a cohort of the members subscribed to it, and one cohort per account and region, named after the account's oldest Mailgun domain, holds everyone subscribed to at least one list. A member who left every list becomes a person but joins no cohort. Importing again takes people who unsubscribed or left a list out of its cohort. A list deleted in Mailgun keeps its cohort as it was, and so does a region that has no lists left. More than 500 lists or 250,000 memberships don't fit one import.

Mailgun's API documents no automations, so nothing becomes a workflow. Routes, webhooks, tracking settings, send history and stats stay behind, and Mailjet is a separate product.

Mailgun scopes suppressions by domain and PostHog by project. An address blocked on one Mailgun domain is blocked for the whole project here. Say this plainly if the team sends unrelated brands from one account.

**Template keys.** An account template keeps its name as the key, with any character a key can't hold replaced and a short hash added. In the EU region it starts with `eu-`. A domain template starts with its domain and a short hash, and a subaccount template also carries the subaccount id. Every key except a plain account template name ends in another short hash, so no two templates share a key. Always read the key from the template when changing the app's code. Pass the values Mailgun took from `t:variables` and `recipient-variables` as `variables`.

## Mailchimp

Follow the same steps, with these differences.

**Key.** A Marketing API key, created in Mailchimp under Profile, Extras, API keys. It ends in the account's data center, such as `-us21`, and PostHog sends the key only to that data center. Every Mailchimp key can read and change the whole account, so ask the user to delete it once the import ends. Mailchimp Transactional (Mandrill) keys don't work here.

**Campaigns.** Drafts, paused and scheduled campaigns import by default. Pass `campaigns: "recent"` to add campaigns sent in the last 90 days, or `"all"` for every campaign. Each becomes a draft template, so ask before importing years of sent campaigns.

| Mailchimp                                               | In PostHog                                                    | What the team does                               |
| ------------------------------------------------------- | ------------------------------------------------------------- | ------------------------------------------------ |
| Audiences                                               | A category each, and opt-outs for who left                    | Builds the audience from its own data            |
| Unsubscribed, pending, transactional, archived contacts | Opted out of that audience's category and its groups          | Nothing                                          |
| Groups contacts can choose                              | A category each, opt-outs for who didn't choose it or left    | Puts the matching templates in that category     |
| Cleaned contacts                                        | Suppression list, blocks all email                            | Reads the summary                                |
| Abuse reports                                           | Suppression list, blocks marketing email only                 | Knows these people still get transactional email |
| Saved templates                                         | Library templates in Liquid, when Mailchimp shares their HTML | Exports the rest as HTML from Mailchimp          |
| Campaigns                                               | Library templates in Liquid                                   | Fixes the notes and sends a test                 |

`*|FNAME|*`, `*|LNAME|*` and `*|EMAIL|*` read the person properties `first_name`, `last_name` and `email`. Other merge tags read the person property of the same name, such as `*|COMPANY|*` reading `COMPANY`, so the team sends those properties to PostHog for its people. Simple `*|IF:|*` conditions convert to Liquid. Any tag PostHog can't convert stays as written and is named in the template's notes. Hidden groups, customer journeys, classic automations, segments, tags, signup forms and reports stay behind.
