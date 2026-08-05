# Integration platform comparison

How our source catalog compares to the two integration platforms people most often suggest we adopt: [Composio](https://composio.dev) and [Nango](https://nango.dev).

The question this file answers is narrow and specific: **would adopting one of these platforms meaningfully extend what PostHog can integrate with?**

Short answer: not for reading data.
Our catalog is already larger than either of theirs, and the vendors they have that we lack are mostly not data sources.
What they have that we don't is the _other direction_ — writing back into third-party systems.
See [Where the real gap is](#where-the-real-gap-is).

This file compares _catalogs_.
For whether a source is implemented, see [SOURCES.md](SOURCES.md).
For endpoints an implemented source is missing, see [COVERAGE_GAPS.md](COVERAGE_GAPS.md).

## Method

Counts come from three catalogs, normalized to a comparable key by lowercasing and stripping non-alphanumerics (`adobe_analytics` → `adobeanalytics`):

| Catalog      | Source of truth                                                                           |
| ------------ | ----------------------------------------------------------------------------------------- |
| **PostHog**  | Every directory under this one that registers a source. Split on `unreleasedSource=True`. |
| **Composio** | The toolkit enum in the public `composio` Python client.                                  |
| **Nango**    | The provider keys in Nango's public `providers.yaml`.                                     |

Nango keys are per-_auth-mode_, not per-vendor: `jira`, `jirabasic`, `jiradatacenter`, and `jiradatacenterapikey` are four keys for one vendor.
Raw key counts overstate its catalog by about 20%, so keys are collapsed to a vendor stem by stripping known auth suffixes (`basic`, `apikey`, `oauth2cc`, `sandbox`, `scim`, `pat`, and so on) before matching.

Matching is automated and therefore imperfect in both directions.
It is a name match, not a capability match: it says a vendor appears in both catalogs, not that the two integrations expose the same objects.
Known false positives (a platform's `adobe` against our `adobe_analytics` + `adobe_commerce`, their `googlebigquery` against our `bigquery`) are filtered by hand where they'd distort a headline number, and the filtered list is small enough to re-check by eye.

## Catalog size

| Catalog                                 |   Vendors |
| --------------------------------------- | --------: |
| **PostHog** — registered                | **1,276** |
| **PostHog** — implemented, syncing data |   **636** |
| **PostHog** — scaffolded, no sync logic |       640 |
| Nango — distinct vendors                |       759 |
| Nango — raw provider keys               |       934 |
| Composio — toolkits                     |       298 |

Our implemented count alone (636) is more than twice Composio's entire catalog and within striking distance of Nango's whole distinct-vendor set.
Counting scaffolds, we register more vendors than both platforms combined have distinct.

## Overlap

How much of each platform's catalog we already cover:

| Platform | Vendors | We cover | Share | Of those, already implemented |
| -------- | ------: | -------: | ----: | ----------------------------: |
| Composio |     298 |      142 |   48% |                            88 |
| Nango    |     759 |      333 |   44% |                           179 |

The reverse direction is the more telling number: **956 of our 1,276 registered vendors appear in neither platform.**
The catalogs are not nested.
Ours is broader and pointed somewhere else.

## What they have that we don't

Only **30 vendors** are carried by _both_ Composio and Nango while being absent from our catalog entirely.
Two independent platforms both bothering to build an integration is a decent proxy for real demand, which makes this the highest-signal gap list available without our own adoption data:

```text
accelo          affinity        battlenet       canva           contentful
epicgames       exa             exist           figma           fireflies
fitbit          googledocs      googlemaps      googlemeet      hackerrankwork
keap            klipfolio       lastpass        linkhut         mural
peopledatalabs  recallai        rocketreach     smugmug         stackexchange
typefully       wakatime        waveaccounting  webex           zohomail
```

Read that list as a category, not as a backlog.
Figma, Canva, Google Docs, Google Meet, Google Maps, Webex, Mural, Fitbit, LastPass, SmugMug, Wakatime, Typefully, Battle.net, Epic Games: these are productivity and consumer apps.
They are things an agent _does something in_.
They are not systems anyone wants to bulk-sync into a warehouse and run funnels over.

The handful with genuine warehouse value — Accelo, Affinity, Contentful, Keap, Wave Accounting, RocketReach, People Data Labs — are ordinary source requests.
They are worth scaffolding on their own merits, and none of them needs a platform dependency to build.

## Where the real gap is

The catalogs differ in **direction**, not size.

- Our 636 implemented sources are **read-only bulk sync**.
  Pull the vendor's objects on a schedule, land them in the warehouse, let people query them.
  This is what [SOURCES.md](SOURCES.md) and [COVERAGE_GAPS.md](COVERAGE_GAPS.md) are about, and we are further along at it than either platform.
- Composio is **write actions for agents**.
  Create the Linear issue, send the Slack message, update the Salesforce opportunity.
  Its catalog is small because each toolkit is a hand-built set of actions, not a schema dump.
- Nango sits between the two: managed OAuth plus sync _and_ write, with the auth layer as the real product.
  That's why its catalog is per-auth-mode rather than per-vendor.

Against that framing, the interesting number is not the 30 vendors we're missing.
It's the **88 vendors we already read from where the write side does not exist**:

```text
ably              close             gong              mem0              salesforce
activecampaign    cloudflare        google_ads        meta_ads          sendgrid
airtable          coda              google_analytics  microsoft_clarity sentry
amplitude         confluence        google_sheets     mixpanel          servicenow
anthropic         customerio        gorgias           monday            shopify
apollo            datadog           gumroad           neon              shortcut
appsflyer         deel              guru              notion            simplesat
asana             docusign          harvest           oncehub           slack
ashby             dropbox_sign      hubspot           pagerduty         snowflake
attio             elevenlabs        intercom          pandadoc          square
bamboohr          eventbrite        jira              pipedrive         stripe
baserow           factorial         klaviyo           productboard      supabase
bitbucket         finage            kommo             qualaroo          surveymonkey
boldsign          firecrawl         launchdarkly      rippling          todoist
braintree         freshdesk         lever             rocketlane        trello
brevo             front             linear                              webflow
brex              github            mailchimp                           wrike
calendly                            mailerlite                          zendesk
clickup                                                                 zoom
```

For every one of these we have already done the hard parts: credentials storage, OAuth where the vendor requires it, rate-limit handling, and a tested client against the vendor's API.
What we don't have is a way for an agent to write back through that same connection.

This matters more than it used to.
MCP tool call volume on our own MCP server has grown sharply over the last few months, on both calls and distinct callers, and the tools people reach for are increasingly ones that would act on a system rather than describe one.
The read-side catalog is a genuine asset here, and it's underused: an agent that can query a customer's Stripe data but can't open the Linear issue about it is doing half a job.

## Recommendation

**Don't adopt either platform for catalog breadth.**
The premise doesn't survive the numbers.
We cover under half of each of their catalogs and they cover a quarter of ours, and the vendors we're missing are overwhelmingly outside the category we serve.
Buying breadth we already exceed, and taking a runtime dependency on a third party's auth layer to get it, is a bad trade.

**Do treat the write direction as a real product gap.**
The 88-vendor list above is the place to start, because the marginal cost per vendor is low: the connection already exists.
Whether that gets built in-house or on top of Composio is a separate question, and one worth asking properly, but it should be argued on write-action coverage rather than on catalog size.

**Scaffold the seven warehouse-relevant misses** (Accelo, Affinity, Contentful, Keap, Wave Accounting, RocketReach, People Data Labs) through the normal [implementing-warehouse-sources](/.agents/skills/implementing-warehouse-sources/SKILL.md) path.
They are ordinary source work and don't depend on anything above.

## Refreshing this file

Both platforms publish their catalogs, so this comparison is reproducible without credentials:

- Composio: the toolkit enum in the public `composio` Python client on PyPI.
  Pin a version; the enum churns between releases.
- Nango: `providers.yaml` in Nango's public repo.
  Collapse auth-mode suffixes before counting.

Our side comes from this directory: a source is scaffolded if its `source.py` sets `unreleasedSource=True`, implemented otherwise.
Regenerate both sides before trusting any number here, and update the date below.

Produced 2026-08-05.
