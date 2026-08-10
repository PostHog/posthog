# Warehouse source endpoint coverage gaps

A backlog of endpoints and tables our **already-implemented** sources do not expose yet,
but that users plausibly want data from.

This is not a list of unimplemented sources.
Every source below already syncs data.
The gap is that the vendor's API offers objects we never wired up.

Produced 2026-07-26 by the [auditing-warehouse-source-coverage skill](/.agents/skills/auditing-warehouse-source-coverage/SKILL.md),
refreshed 2026-08-04.
Re-run that skill to refresh this file.
Tick items off as they ship rather than deleting them, so the next audit can tell "done" from "never found".

**Coverage is complete.** All 586 implemented sources have been diffed against a vendor spec or
reference.
This file carries the method, the cross-source patterns, and the highest-adoption sources in depth.
Per-source detail for the remaining 547 lives in
[COVERAGE_GAPS_APPENDIX.md](COVERAGE_GAPS_APPENDIX.md), which is generated and covers every source
with its assessment, the doc URL it was diffed against, and its gap list.

Headline numbers from the original sweep: **4,540 missing endpoints across 547 sources**, of which
1,704 are high priority.
466 sources have at least one high-priority gap.
55 sources are adequately covered.

**2026-08-04 refresh.** Eight tier 1 and 2 sources shipped their gaps between 2026-07-28 and 07-30 and
their boxes are now ticked: Stripe (16 tables to 42), GitHub (10 to 54), Sentry (37), Cloudflare (36),
Zendesk (34), Klaviyo (32), Mailchimp (32), Clerk (4 to 27).
Stripe, Sentry, Klaviyo and Mailchimp are fully closed.
Work is in flight on the remaining tier 1 and 2 sources, so treat unticked boxes there as claimed
rather than free.
Intercom was added as a tier 2 entry in the same refresh: it is more widely connected than several
sources that were hand-audited, but the original pass only swept it into the appendix.

## How sources were prioritized

Coverage alone says nothing about impact, so sources were ranked by how many production projects
actually have a connection of that type (queried from the synced `posthog_externaldatasource` replicas
in the internal dogfood project, US and EU combined), then cross-referenced against the table count each
source exposes.
Exact connection counts are internal operational data and deliberately not reproduced here.
Tiers below are relative bands, not thresholds.

- **Tier 1** — among the most-connected sources. A gap here affects a large share of warehouse users.
- **Tier 2** — widely connected. Worth doing.
- **Tier 3** — real but modest adoption. Do opportunistically.

The tiered sections below are the sources with meaningful production adoption, audited by hand.
Everything else was swept in a second pass and lives in the appendix.
Adoption should still drive scheduling: an appendix source with a high-priority gap is usually worth
less than a tier 1 source with a medium one.

SQL and file sources (Postgres, MySQL, BigQuery, Snowflake, MongoDB, Supabase, Redshift, MSSQL,
ClickHouse, Neon, Convex, Google Sheets, Custom) introspect user-defined schemas and are out of scope.

## Verification provenance

Two different confidence levels are mixed below. Treat them differently.

| Marker                 | Meaning                                                                                                                                                                          |
| ---------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **spec-verified**      | The vendor's official machine-readable spec was fetched (2026-07-26, or 2026-08-04 where a section says so) and diffed against our endpoint list. Gaps are real as of that date. |
| **needs confirmation** | Our side was read from code, but the vendor side comes from API familiarity rather than a fetched spec. Confirm against current docs before implementing.                        |

Our side was read from each source's `settings.py` / `constants.py` endpoint map for every entry,
so the "what we have today" column is accurate in all cases.

## Cross-source patterns worth fixing as a batch

These recur across many sources and are probably better tackled as themes than one source at a time.
The counts come from tagging all 4,540 swept gap items, so they are a measured prevalence rather than
an impression.
A single gap can carry more than one theme, so these do not sum to the total.

| Theme                                          | Gap items | Shape of the fix                                              |
| ---------------------------------------------- | --------: | ------------------------------------------------------------- |
| Lookup tables that resolve IDs we already sync |     1,238 | Small endpoint, one join, unblocks a category of analysis     |
| Usage, billing, and cost objects               |       429 | Often a whole missing product surface                         |
| Membership and join tables                     |       456 | Materialize a many-to-many we currently drop                  |
| State and change history                       |       424 | New table, usually cheap, enables all time-in-state questions |
| Comments, notes, and conversations             |       238 | Text content attached to records we already sync              |
| Breakdown and segmented reporting              |       210 | New report dimensions on an existing stats call               |
| Engagement events (opens, clicks, delivery)    |       161 | The fact table behind email and messaging sources             |
| Line items and order detail                    |        83 | Splits a single total into its components                     |

**Lookup tables are 27% of every gap found and are the clearest theme in the whole audit.**
The pattern is always the same: we sync a record carrying a foreign key, and never sync the table that
decodes it. Pipedrive activities carry a type key with no `activityTypes`; Discourse user badges have no
`badges`; Ably stats are scoped to app IDs with no `apps`; Mollie payments carry a `profileId` with no
`profiles`. These are the cheapest work in this document and should probably be swept as one project
rather than trickled out per source.

The five narrative patterns below were found in the hand-audited tier 1 and 2 sources and still hold.

1. **Ad platforms expose no creative metadata.**
   Meta, Reddit, TikTok, Snapchat, and Pinterest all ship campaign / ad group / ad plus a stats table,
   and none of them ship the creative (asset, copy, thumbnail) behind an ad.
   LinkedIn is the exception and does have `creatives`.
   Without creatives you can rank ad IDs but cannot say which creative won.

2. **Ad platforms expose no breakdown dimensions.**
   Google Ads has `geographic_stats`, but Meta, Reddit, TikTok, Snapchat, Pinterest, and Bing ship
   totals only.
   Age, gender, country/region, placement, platform, and device breakdowns are the most common
   reason people export ad data, and none of them are available.
   LinkedIn's member-demographic pivots (company, industry, seniority, job title) are the same gap
   and are that platform's main differentiator.

3. **Support and CRM sources return opaque foreign keys with no lookup table.**
   HubSpot deals carry `dealstage` and `pipeline` IDs with no `pipelines` table, and an owner ID with
   no `owners` table.
   Linear issues carry a state ID with no `workflow_states` table.
   These are small endpoints that unblock a whole category of analysis, so they are the highest
   value-per-line work in this document.

4. **Email tools ship campaign metadata but not per-recipient engagement.**
   Mailchimp has no `email_activity`, `open_details`, `click_details`, or `unsubscribes`.
   Klaviyo has no `flow_actions` / `flow_messages` or reporting values endpoints.
   Resend has no per-message event table.
   Postmark has no opens/clicks/stats.
   Open and click behavior is usually the entire point of connecting an email tool.

5. **State-transition history is missing almost everywhere.**
   GitHub has no `issues/events`, Linear has no `issue_history`, Salesforce has only
   `OpportunityHistory` (no `LeadHistory` / `AccountHistory`), Zendesk has no `ticket_audits`.
   Any "how long did X sit in state Y" question is unanswerable today.

## Tier 1

### Stripe — spec-verified

Diffed against [stripe/openapi](https://github.com/stripe/openapi) `spec3.json`.
Our 16 tables cover the classic payments and billing core.
The gaps cluster around the payment funnel, modern usage-based billing, and Connect.

Have: `BalanceTransaction`, `Charge`, `Coupon`, `CreditNote`, `Customer`,
`CustomerBalanceTransaction`, `CustomerPaymentMethod`, `Discount`, `Dispute`, `Invoice`,
`InvoiceItem`, `Payout`, `Price`, `Product`, `Refund`, `Subscription`.

High value:

- [x] `payment_intents` — the payment funnel and failure reasons. Charges alone miss attempts that never became a charge.
- [x] `checkout/sessions` — checkout conversion and abandonment.
- [x] `subscription_items` — per-price lines on multi-item subscriptions. Without it, MRR cannot be split by product on any subscription with more than one item.
- [x] `subscription_schedules` — phased and scheduled subscription changes.
- [x] `promotion_codes` — `Coupon` tells you the discount exists but not which redeemable code was used.
- [x] `plans` — the legacy pricing model, still widely in use.
- [x] `tax_rates` and `tax_ids`.
- [x] `quotes` — sales-led billing.
- [x] `events` — Stripe's own event log, useful as a generic change feed.
- [x] `billing/meters`, `billing/credit_grants`, `billing/credit_balance_transactions`, `billing/credit_balance_summary` — usage-based billing. Entirely absent, and this is where Stripe is actively investing.
- [x] `entitlements/features`, `entitlements/active_entitlements` — feature entitlements.
- [x] `invoice_payments` — how an invoice actually got paid.
- [x] `setup_intents`, `setup_attempts` — payment method setup funnel.
- [x] `payment_links`.
- [x] `transfers`, `application_fees`, `topups` — needed by any Connect platform.
- [x] `reviews`, `radar/early_fraud_warnings` — fraud review outcomes.
- [x] `shipping_rates`.

Lower priority: `issuing/*`, `treasury/*`, `terminal/*`, `identity/*`, `financial_connections/*`,
`climate/*`, `sigma/*`, `reporting/*`, `forwarding/*`, `files`, `file_links`, `webhook_endpoints`,
`country_specs`, `exchange_rates`, `radar/value_lists`, `billing_portal/configurations`,
`payment_method_configurations`, `payment_method_domains`, `invoice_rendering_templates`.

### Google Ads — spec-verified

Diffed against the [Google Ads API v25 field reference](https://developers.google.com/google-ads/api/fields/v25/overview)
on 2026-08-04, using each resource's attributed/segmenting resource lists and the per-field
"selectable with" lists to check every field, segment and metric combination.
40 tables and the best-covered source we have.

- [x] `campaign_budget` — budgets and budget pacing.
- [x] `age_range_view`, `gender_view` — demographic breakdowns.
- [x] `detail_placement_view`, `landing_page_view` — where ads actually ran and landed.
- [ ] `change_event` — audit of who changed what in the account. (skipped: GAQL requires a mandatory
      `LIMIT` of at most 10,000 rows and a `change_date_time` filter inside a 30-day window, neither of
      which the shared query composer or the page-token pagination loop can express)
- [x] `user_location_view` / `location_view` — distinct from the existing `geographic_stats`.
- [x] `audience`, `bidding_strategy`, `label`. (`recommendation` skipped: recommendations are ephemeral
      suggestions that vanish once applied or dismissed and have no stable ID, so a merge-only table
      would accumulate rows that no longer exist)
- [x] `product_group_view` — Shopping campaign structure beyond `shopping_performance_view`.
- [x] `asset` — asset metadata, complements `asset_group`. Per-asset performance would need
      `ad_group_ad_asset_view` or `asset_field_type_view` and is still open.
- [x] Hourly segmentation, as `campaign_hourly_stats`. (device segmentation was already there — every
      existing `*_stats` table selects `segments.device`)
- [x] Conversion stats segmented by `conversion_action`, at campaign, ad group and keyword level
      (`campaign_conversion_action_stats`, `ad_group_conversion_action_stats`,
      `keyword_conversion_action_stats`). All off by default — the per-action fan-out multiplies rows.
- [x] `customer` — account entity table (timezone, currency, auto-tagging, manager status, conversion
      tracking), distinct from the daily `customer_stats` fact table.
- [x] `ad_group_criterion`, `campaign_criterion` — every targeting criterion including negative keywords
      and other exclusions. The `keyword` table is backed by `keyword_view`, which by API design only
      returns positive, servable keywords, so negatives were previously unreachable. Both off by default.

### Meta Ads — spec-verified

Diffed against the [Marketing API reference](https://developers.facebook.com/docs/marketing-api/reference/)
and the [Insights breakdowns reference](https://developers.facebook.com/docs/marketing-api/insights/breakdowns/)
on 2026-08-04, against API version v25.0.

Have: `campaigns`, `campaign_stats`, `adsets`, `adset_stats`, `ads`, `ad_stats`, `ad_account`,
`ad_creatives`, `ad_images`, `ads_pixels`, `custom_conversions`, `campaign_stats_by_age_gender`,
`campaign_stats_by_country`, `campaign_stats_by_region`, `campaign_stats_by_platform`,
`campaign_stats_hourly`.

- [x] `adcreatives` — shipped as `ad_creatives`.
- [x] Insight breakdowns: `age`, `gender`, `country`, `region`, `publisher_platform`, `platform_position`, `impression_device`, plus hourly. Shipped as five campaign-level breakdown tables, all off by default. `device_platform` is not in Meta's valid-permutation table, so it was dropped.
- [ ] Action breakdowns: `actions`, `action_values`, `cost_per_action_type` (skipped: already synced. All three are AdsInsights fields and are in every stats table's field list today. The `action_breakdowns` parameter only adds keys inside those nested arrays, it does not produce rows.)
- [x] `ad_account` — shipped, including currency, timezone, spend caps and funding.
- [ ] Lead gen forms and `leads` (skipped: reading them needs `leads_retrieval` plus Page-level access, and our OAuth consent requests `ads_read` only, so every sync would 403.)
- [ ] `customaudiences` and saved audiences (skipped: gated behind `ads_management` and the account having accepted the Custom Audience terms of service, neither of which our consent covers.)
- [x] `adimages` — shipped as `ad_images`.
- [ ] `advideos` (skipped: AdVideo is a Page video object whose readable fields depend on video permissions we do not request, and its useful fields are short-lived URLs rather than warehouse-shaped data.)
- [x] `adspixels` and custom conversions — shipped as `ads_pixels` and `custom_conversions`.
- [ ] `adrules_library` (skipped: automated rules are configuration objects, not analytics data, and reading the rules library needs `ads_management`.)

`schemas.py` still carries a `AdsetStats = "adset_stats"  # TODO: remove this` marker. Left alone:
the table ships and has live syncs, so removing it would orphan synced data.

### GitHub — spec-verified

Re-diffed 2026-08-04 against [github/rest-api-description](https://github.com/github/rest-api-description)
`descriptions/api.github.com/api.github.com.2022-11-28.json`, the description for the API version the
source pins.
The original ten tables have grown to 54, so everything the first audit flagged now ships except
Discussions, and the remaining gaps are narrow.

Have: `issues`, `issue_comments`, `issue_events`, `issue_types`, `labels`, `milestones`,
`pull_requests`, `pull_request_comments`, `reviews`, `commits`, `commit_comments`,
`commit_statuses`, `check_runs`, `branches`, `tags`, `forks`, `stargazers`, `subscribers`,
`contributors`, `collaborators`, `teams`, `team_members`, `repository_teams`, `repository`,
`repository_activity`, `topics`, `languages`, `community_profile`, `releases`, `workflows`,
`workflow_runs`, `workflow_jobs`, `artifacts`, `runners`, `actions_caches`, `deployments`,
`deployment_statuses`, `environments`, `code_scanning_alerts`, `dependabot_alerts`,
`secret_scanning_alerts`, `security_advisories`, `dependency_sbom`, `rulesets`, `hooks`,
`traffic_views`, `traffic_clones`, `traffic_referrers`, `traffic_paths`, `contributor_stats`,
`commit_activity_stats`, `participation_stats`, `code_frequency_stats`, `punch_card_stats`.

- [x] `issues/comments` and `pulls/comments` — no comment data at all, so review latency and discussion volume are unavailable.
- [x] `issues/events` — labeled, assigned, closed, reopened transitions. Needed for time-in-state.
- [x] Repository metadata itself. There is no `repositories` table, so stars/forks/language/visibility per repo are unavailable even though the source is repo-scoped.
- [x] `branches`, `tags`.
- [x] `contributors`, `collaborators`.
- [x] `labels`, `milestones`.
- [x] `deployments`, `environments`.
- [x] `traffic/views`, `traffic/clones`, plus referrers and popular paths.
- [x] `stats/contributors`, `stats/commit_activity`, `stats/participation`, `stats/code_frequency`.
- [x] Check runs and commit statuses — CI signal at commit granularity, complementing `workflow_runs`.
- [x] `actions/workflows`, `actions/artifacts`, `actions/runners`, `actions/caches`.
- [x] `code-scanning/alerts`, `dependabot/alerts`, `secret-scanning/alerts` — security posture over time.
- [x] `forks`, `subscribers` (watchers), `topics`.
- [x] `rulesets`, `security-advisories`, `hooks`, `languages`, `community/profile`, `dependency-graph/sbom`.
- [ ] Discussions (skipped: GraphQL only. The 2026-08-04 description carries no discussion path at all — repository Discussions have never had a REST endpoint, and the old team-discussion endpoints are gone from both the spec and the REST reference. Reaching them means a second transport, a point-metered rate limit the egress limiter does not model, and a GitHub App permission every existing installation would have to re-accept.)
- [x] `repos/{repo}/activity` — pushes, force pushes, merges, branch creations and deletions. The only record that a force push or branch deletion happened, since both rewrite the history `commits` reads.
- [x] `repos/{repo}/comments` — commit comments, the third comment surface next to issue and review comments.
- [x] `repos/{repo}/issue-types` — lookup for the type an issue carries, which `issues` otherwise stores as an opaque nested object.
- [x] `repos/{repo}/teams` — the teams granted access to the repository, for ownership analysis without the org grant.
- [x] `stats/punch_card` — commit counts per weekday and hour, completing the statistics family.
- [ ] `code-quality/findings` and `pulls/stacks` (skipped: both back GitHub features that are still rolling out, and neither endpoint returns anything on an account without the feature enabled, so they would ship as tables that stay empty or error for nearly everyone. Worth revisiting once the features are generally available).
- [ ] `repos/{repo}/events` (skipped: GitHub caps this feed at 300 events over 90 days and it restates what `repository_activity`, `issues`, and `pull_requests` already carry).

### HubSpot — spec-verified 2026-08-04

Diffed against HubSpot's public spec catalog (<https://api.hubspot.com/public/api/spec/v1/specs>) and the
individual 2026-03 OpenAPI specs behind it.

Have: contacts, companies, deals, tickets, quotes, emails, meetings, leads, calls, notes, tasks,
communications, feedback_submissions, line_items, products, invoices, orders, subscriptions,
commerce_payments, pipelines, pipeline_stages, properties, owners.

- [x] `pipelines` (and pipeline stages) — deals and tickets return `dealstage` and `pipeline` as opaque IDs today, so no one can group by stage name without hardcoding a mapping. Highest value item here.
- [x] `owners` — same problem for owner IDs. Also unblocks rep-level reporting.
- [x] `line_items` and `products` — deal composition and what was actually sold.
- [x] `calls`, `notes`, `tasks`, `communications` — the rest of the engagement objects. We have `emails` and `meetings` only.
- [ ] `lists` and list memberships. (skipped: the v3 Lists API is a POST `/crm/v3/lists/search` with its own paging, and memberships are an unbounded per-list fan-out — neither fits the CRM object machinery)
- [ ] Marketing emails and marketing campaigns, with their statistics. (skipped: `/marketing/v3/*` is a separate API family needing its own scopes and paginator)
- [ ] `forms` and form submissions. (skipped: the only published Forms spec is version `2026-09-beta`, not GA)
- [ ] Custom objects. Currently impossible to sync, and most mature HubSpot portals have them. (skipped: needs schema discovery per portal rather than a fixed table)
- [x] Property definitions — needed to interpret and label custom properties.
- [ ] Associations as a first-class table. Today they ride along as a query param on contacts and companies only, so deal-to-contact links are not queryable. (skipped: needs a pair-by-pair batch read across every object type; `line_items` now carries its deal association inline)
- [x] Feedback submissions (NPS/CSAT surveys).
- [ ] Workflows. (skipped: Automation v4 is a separate API family)
- [ ] Web analytics events. `WEB_ANALYTICS_EVENTS_ENDPOINT` is already defined in `hubspot/settings.py:63` but is referenced nowhere else, so this is a half-finished thread rather than a new build. (skipped: `/events/v3/events` requires an objectId per request, so it is a per-record fan-out over the whole portal rather than a listable table)
- [x] Commerce: `invoices`, `orders`, `subscriptions`, `commerce_payments`. Not covered: `carts`, `discounts`, `fees`, `taxes`, `tax_rates`, `payment_links` — configuration-shaped objects with little query value.

### LinkedIn Ads — spec-verified

Spec: <https://learn.microsoft.com/en-us/linkedin/marketing/integrations/ads-reporting/ads-reporting> (version 202607), diffed 2026-08-04.

Have: `accounts`, `campaigns`, `campaign_groups`, `creatives`, `conversions`, `campaign_stats`, `campaign_group_stats`, `creative_stats`, `member_company_stats`, `member_company_size_stats`, `member_country_stats`, `member_industry_stats`, `member_job_title_stats`, `member_seniority_stats`. The only ad platform that ships `creatives`.

- [x] Member-demographic pivots: `MEMBER_COMPANY`, `MEMBER_INDUSTRY`, `MEMBER_SENIORITY`, `MEMBER_JOB_TITLE`, `MEMBER_COUNTRY_V2`, `MEMBER_COMPANY_SIZE`. This is the reason people advertise on LinkedIn and none of it is available.
- [ ] Lead gen forms and form responses. (skipped: the Lead Sync API needs `r_marketing_leadgen_automation`, which is not in PostHog's LinkedIn OAuth app and belongs to a separate approval program)
- [x] Conversions and conversion events. (conversion rules ship as `conversions`; the conversion-tracking reference documents no read finder for individual conversion events, so conversion counts stay available through the `externalWebsiteConversions` metric on the stats tables)
- [ ] Audiences / DMP segments. (skipped: `dmpSegments` needs `rw_dmp_segments`, part of the Audiences program and not granted with the Marketing API program)
- [ ] Budget and bid data on campaigns. (skipped: `dailyBudget`, `unitCost` and `costType` already sync on `campaigns` and `totalBudget` on `campaign_groups`; the remainder would mean adding columns to live tables)
- [ ] Video ad analytics. (skipped: `videoViews` and `videoCompletions` already sync on the stats tables; the extra quartile metrics would mean adding columns to live tables)

### Google Search Console — spec-verified

Diffed against the [Search Console API discovery document](https://searchconsole.googleapis.com/$discovery/rest?version=v1)
(revision 20260803) on 2026-08-04.

Have: `search_analytics_by_date`, `search_analytics_by_query`, `search_analytics_by_page`,
`search_analytics_by_country`, `search_analytics_by_device`, `search_analytics_by_country_device`,
`search_analytics_by_query_page`, `search_analytics_by_search_appearance`, `search_analytics_by_hour`,
`sites`, `sitemaps`, `sitemap_contents`.

- [x] `sitemaps` — submission status, errors, indexed counts. (`indexed` itself is marked deprecated
      "do not use" in the discovery document, so the per-content-type `submitted` count ships instead,
      as a `sitemap_contents` table.)
- [x] `sites` — the property list itself.
- [ ] URL inspection results (index status per URL). (skipped: `urlInspection.index.inspect` is a
      per-URL POST with no listing endpoint, and nothing in the API yields a bounded URL list —
      `sitemaps.list` returns sitemap file paths, not the URLs inside them. Combined with the
      2,000 inspections per property per day quota, there is no way to drive it as a table.)
- [x] Additional dimension combinations: country + device. (date + page + query already shipped as
      `search_analytics_by_query_page`.) Also added `search_analytics_by_hour`, the only dimension
      Google serves outside the 16-month daily window — it retains 10 days and needs
      `dataState: hourly_all`.
- [ ] Per search type (`type`: image, video, news, discover, googleNews) variants of the dimension
      bundles. (skipped: real endpoint, but the docs do not state which dimensions each type supports,
      so the table set could not be pinned down from the spec alone.)

### Clerk — spec-verified

Diffed against [clerk/openapi-specs](https://github.com/clerk/openapi-specs).
Four tables, and the two that matter most for an auth provider are missing.

- [x] `sessions` — no login/session data, so "how many people signed in" is unanswerable. Biggest gap.
- [ ] `sign_ups` — signup attempts including abandoned and failed ones. `users` only shows successes.
- [x] `organization_invitations`, `organization_domains`.
- [x] `organization_roles`, `organization_permissions` — needed to interpret membership roles.
- [x] `waitlist_entries`.
- [x] `allowlist_identifiers`, `blocklist_identifiers`.
- [x] `domains`, `saml_connections`, `enterprise_connections` — enterprise SSO configuration.
- [x] `billing` and `commerce` — Clerk's newer billing surface (shipped as `commerce_plans` and `commerce_subscription_items`)
- [x] `oauth_applications`, `api_keys`, `m2m_tokens`, `machines`.
- [ ] `clients` — retired. Clerk deprecated `GET /v1/clients` and it now answers 410, with no
      replacement listing endpoint.
- [ ] `email_addresses`, `phone_numbers` as their own tables.
- [x] `jwt_templates`, `redirect_urls`, `role_sets`, `email_templates`, `sms_templates`
- [ ] `actor_tokens`, `sign_in_tokens`, `webhooks`

### Reddit Ads, TikTok Ads, Snapchat Ads, Pinterest Ads — needs confirmation

All four ship the same six-table shape (campaigns, ad groups / ad squads, ads, plus one report each)
and all four have the same two gaps.
See patterns 1 and 2 above.

- [ ] Creative metadata for each platform.
- [ ] Breakdown dimensions (age, gender, geo, placement, device) on the report tables.
- [ ] Ad account table (currency and timezone, without which spend is ambiguous).
- [ ] Audiences and pixel / conversion event definitions.

### Snapchat Ads — spec-verified

Split out of the four-platform section above.
Diffed against the [Snapchat Marketing API v1 reference](https://developers.snap.com/api/marketing-api)
on 2026-08-04.
Have: campaigns, ad_squads, ads, campaign_stats_daily, ad_squad_stats_daily, ad_stats_daily,
ad_accounts, creatives, media, audience_segments, pixels, campaign_stats_daily_country,
campaign_stats_daily_demographics, ad_stats_daily_country, ad_stats_daily_demographics.

- [x] Creative metadata — `creatives` and `media`.
- [x] Breakdown dimensions — `report_dimension` country and age/gender tables at campaign and ad level,
      off by default because a breakdown row exists per dimension value per day.
- [x] Ad account table — `ad_accounts`, carrying the currency and timezone every spend figure is in.
- [x] Audiences — `audience_segments`.
- [x] Pixel definitions — `pixels`.
- [ ] Custom conversion definitions (skipped: `/pixels/{pixel_id}/custom_conversions` only lists per
      pixel, and this source has no parent fan-out path yet).
- [ ] Region, DMA, device make, OS, and lifestyle-category breakdowns (skipped: Snapchat documents the
      dimension names but not the column each returns, so the primary key would be a guess; region, DMA
      and make also return no conversion metrics).
- [ ] Organization-level tables — funding sources, billing centers, invoices, members (skipped: all
      scoped to an organization ID this source does not collect).

### Reddit Ads — spec-verified

Reddit Ads is done; the section above still covers TikTok.
Diffed against the Reddit Ads v3 OpenAPI spec (`https://ads-api.reddit.com/api/v3/openapi.json`) on 2026-08-04.

Have: campaigns, ad_groups, ads, campaign_report, ad_group_report, ad_report, ad_account,
custom_audiences, saved_audiences, pixels, funding_instruments, lead_gen_forms, profiles,
structured_posts, campaign_country_report, campaign_gender_report, campaign_placement_report,
campaign_community_report, campaign_os_type_report, campaign_keyword_report.

- [x] Creative metadata — `structured_posts`, fanned out over the account's profiles. Reddit hangs creatives off profiles, not off the ad account, and ad rows carry the `post_id` to join on.
- [x] Breakdown dimensions on the report tables — gender, country, placement, device (`OS_TYPE`), community and keyword, each a campaign-grain report table defaulted to `should_sync_default=False`. Reddit returns breakdowns as extra dimensions on the same `POST /reports` call, capped at three per request, so each dimension is its own table rather than a new param. Age is not shippable: `AGE` is absent from the spec's `breakdowns` enum (it appears only in a stale request example). `KEYWORD` is requested as a breakdown only: its membership of the `fields` enum was not re-checked against the spec.
- [x] Ad account table — `ad_account`, carrying `currency` and `time_zone_id`.
- [x] Audiences and pixel definitions — `custom_audiences`, `saved_audiences`, `pixels`. Conversion _events_ are write-only (`POST /pixels/{id}/conversion_events`), so there is nothing to sync.
- Also added: `funding_instruments` (per-instrument currency and credit limit), `lead_gen_forms`, `profiles`.
- Not built: `apps` (the response schema exposes only `id`); `creative_assets` (rows arrive wrapped in a per-item `result` envelope); product catalogs, feeds, sets and their imports (business-scoped, not reachable from the configured ad account); the targeting reference lists (`communities`, `interests`, `geolocations`, `languages`, `devices`, `carriers`) and `time_zones`, which are global catalogs rather than account data; `POST /ad_accounts/{id}/history` (an audit log, not warehouse-shaped); forecasting, bid suggestions and data-deletion jobs (write or estimate endpoints).

### Pinterest Ads — spec-verified

Diffed against the Pinterest API v5 OpenAPI description in
[pinterest/api-description](https://github.com/pinterest/api-description) (`v5/openapi.yaml`, spec version
5.28.0) on 2026-08-04. Supersedes the Pinterest entries in the block above.

Have: `campaigns`, `ad_groups`, `ads`, `campaign_analytics`, `ad_group_analytics`, `ad_analytics`,
`ad_accounts`, `audiences`, `conversion_tags`, `keywords`, `campaign_targeting_analytics`,
`ad_group_targeting_analytics`, `ad_targeting_analytics`.

- [ ] Creative metadata (skipped: the only creative endpoints, `GET /pins` and `GET /pins/{pin_id}`,
      need the `boards:read` and `pins:read` scopes, and the Pinterest OAuth app only requests
      `ads:read user_accounts:read`. Adding scopes forces every existing connection to reconsent, so
      it is its own piece of work. `ads.pin_id` and `ads.creative_type` already identify the creative.)
- [x] Breakdown dimensions on the report tables — `campaign_targeting_analytics`,
      `ad_group_targeting_analytics`, `ad_targeting_analytics`, broken down by age, gender, device,
      placement, country and region. Off by default.
- [x] Ad account table — `ad_accounts`, carrying currency and time zone.
- [x] Audiences and pixel / conversion event definitions — `audiences` and `conversion_tags`,
      plus `keywords` to resolve keyword targeting back to the bid term.

Verified but not built: `lead_forms`, `customer_lists`, `customer_segments`, `labels`, `order_lines`,
`promotions`, `product_group_promotions`, `templates`, `targeting_templates`, `schedules`,
`advertiser_defined_events`, `ad_accounts/{id}/analytics` (account-level totals),
`product_groups/analytics`. `billing_invoices` needs the `billing:read` scope.

### TikTok Ads — spec-verified

Supersedes the TikTok Ads entries in the section above.
Diffed on 2026-08-04 against the TikTok Marketing API v1.3 surface as expressed by the actively
maintained Airbyte `source-tiktok-marketing` manifest
(<https://github.com/airbytehq/airbyte/blob/master/airbyte-integrations/connectors/source-tiktok-marketing/manifest.yaml>),
since TikTok publishes no machine-readable spec and its docs portal renders client-side.

Have: campaigns, ad_groups, ads, campaign_report, ad_group_report, ad_report, creative_videos,
creative_images, campaign_demographic_report, campaign_country_report, campaign_platform_report,
ad_group_demographic_report, ad_group_country_report, ad_group_platform_report,
ad_demographic_report, ad_country_report, ad_platform_report.

- [x] Creative metadata — `creative_videos` (`/file/video/ad/search/`) and `creative_images` (`/file/image/ad/search/`) decode the `video_id` / `image_ids` already synced on `ads`.
- [x] Breakdown dimensions on the report tables — nine `report_type=AUDIENCE` tables covering gender + age, country, and operating system at campaign, ad group, and ad level. All default to off.
- [ ] Ad account table (skipped: `/advertiser/info/` is not readable with the scope the PostHog TikTok app holds, so the table would fail for every connection. Report tables already carry `currency`; timezone stays missing).
- [ ] Audiences (skipped: `/dmp/custom_audience/list/` needs the audience-management scope, which the app does not hold today).
- [ ] Pixel / conversion event definitions (skipped: `/pixel/list/` needs the events-manager scope, which the app does not hold today).
- [ ] Province-level breakdown (skipped: TikTok only offers `province_id` at ad level, so it does not fit the symmetric set above).
- [ ] Spark Ads posts, creative portfolios, and music assets.

### Linear — spec-verified

Verified 2026-08-04 against the root `Query` type published by `@linear/sdk` 89.0.0 (npm), which is
generated from Linear's live GraphQL schema.

Have: issues, projects, teams, users, comments, labels, cycles, resources, workflow_states,
project_milestones, initiatives, team_memberships, issue_relations, project_updates, documents.

- [x] `workflow_states` — issues carry a state ID with no way to resolve it to a name or type (backlog / started / completed). Highest value item.
- [ ] `issue_history` — state transitions over time. Without it, cycle time, lead time, and time-in-state cannot be computed. (skipped: no root `issueHistory` query — history is only reachable as `issue(id).history`, so it would need a per-issue fan-out)
- [x] `project_milestones`, [x] `initiatives`, [ ] `roadmaps` (skipped: the schema marks `roadmaps` deprecated in favour of `initiatives`)
- [x] `attachments` — links out to PRs and tickets, which is how Linear connects to GitHub. (already shipped as the `resources` table)
- [x] `issue_relations` — blocks / blocked-by / duplicates.
- [x] `project_updates`, [x] `documents`.
- [x] `team_memberships`, [ ] `organization` (skipped: a singleton object, not a paginated connection)
- [ ] Custom views, templates, reactions, triage responsibilities. (skipped: `templates` returns a plain list with no pagination, and there is no root `reactions` query; custom views and triage responsibilities are UI configuration rather than analyzable records)

## Tier 2

### Resend — needs confirmation

Five tables. `emails` exists, but delivery outcomes do not.

- [ ] Per-email delivery events as their own table (delivered, opened, clicked, bounced, complained). This is the whole analytics payload.
- [ ] Broadcast recipient-level results and stats.
- [ ] Contact suppressions.
- [ ] `api_keys`, `webhooks`.

### Sentry — spec-verified

Diffed against [getsentry/sentry-api-schema](https://github.com/getsentry/sentry-api-schema).
Fourteen tables and reasonable issue coverage.
The gaps are the newer product surfaces.

- [x] `sessions` — release health and crash-free rate. The headline Sentry metric and not available.
- [x] `releases/*/deploys` and `releases/*/commits` (plus `commitfiles`) — we have `releases` but nothing about what shipped in them or when they deployed (`commitfiles` still open)
- [x] `user-feedback` — user-submitted reports.
- [x] `replays` — session replay metadata.
- [x] `stats_v2` / `stats-summary` — event volume and quota consumption per project.
- [x] `repos` and repo commits.
- [x] `dashboards`, `discover/saved`.
- [x] `monitors/*/checkins` — we have `monitors` but not their check-in history.
- [x] `workflows`, `detectors` — the current alerting model.
- [x] Organization-level `tags` and `events` (Discover).
- [x] `trace-items` and trace metadata — tracing and spans.
- [x] Project `filters`, `ownership`, `stats`.
- [x] `integrations` and installed apps.

### Shopify — needs confirmation

Nine tables. Orders exist but nothing that explains their money or fulfillment.

- [ ] `productVariants` — SKU-level data. Products alone cannot join to order line items properly.
- [ ] `transactions` — how orders were paid, including authorizations and captures.
- [ ] `refunds` — currently no way to compute net revenue.
- [ ] `fulfillments` and `fulfillmentOrders` — shipping and delivery timelines.
- [ ] `inventoryItems`, `inventoryLevels`, `locations` — stock on hand by location.
- [ ] `returns`.
- [ ] `draftOrders`.
- [ ] `shopifyPaymentsAccount` payouts and balance transactions — payout reconciliation.
- [ ] `priceRules` (the rules behind the existing `discountCodes`).
- [ ] `customerSegments` and segment members.
- [ ] `metafields` — where most merchants keep custom data.
- [ ] `marketingEvents`, `giftCards`, `tenderTransactions`, `publications`, `sellingPlanGroups`, `companies` (B2B), `shop`.

### RevenueCat — needs confirmation

Six tables. Customer-level and catalog data exist, but not the money.

- [ ] `subscriptions` — per-subscription state and renewal dates.
- [ ] Purchases / transactions — individual purchase events at the receipt level.
- [ ] `invoices`.
- [ ] `packages` — the contents of the existing `offerings`.
- [ ] Overview metrics / charts endpoints (MRR, active subscriptions, churn as RevenueCat computes them).
- [ ] Customer aliases and attributes.
- [ ] `projects`, `paywalls`, virtual currencies, refunds.

### Attio — needs confirmation

Nine hardcoded tables for what is fundamentally a schemaless CRM.

- [ ] Arbitrary objects and their records. `ATTIO_ENDPOINTS` hardcodes companies / people / deals / users / workspaces, but Attio's core premise is user-defined objects, so any custom object is unsyncable. Biggest gap.
- [ ] `attributes` — object and list schema definitions, needed to interpret record values.
- [ ] List `entries` — we have `lists` but not their contents.
- [ ] `comments` and `threads`.
- [ ] Meetings and calls.

### Bing Ads (Microsoft Advertising) — needs confirmation

Five tables: `campaigns` plus four performance reports.
No ad group, ad, or keyword entity tables at all, which is unusual relative to our other ad sources.

- [ ] `ad_groups` and `ads` as entity tables. Today the ad group and ad performance reports reference IDs with nothing to join to.
- [x] `keyword_performance_report` — daily performance by keyword. Still missing the `keywords` entity table, so `keyword_id` has nothing to join to.
- [ ] `search_query_performance_report` — search terms, one of the main reasons to export Bing data.
- [ ] `accounts` — currency and timezone.
- [ ] `geographic_performance_report`, `user_location_performance_report`.
- [ ] `age_gender_audience_report`.
- [ ] `conversion_performance_report`, conversion goals.
- [ ] `budget_summary_report`.
- [ ] Shopping / `product_dimension_performance_report`, asset groups (Performance Max).

### Klaviyo — spec-verified

Diffed against [klaviyo/openapi](https://github.com/klaviyo/openapi) stable spec.
Eight tables. The vendor exposes 42 top-level collections.

- [x] `segments` and segment membership — Klaviyo users organize everything around segments and we expose none of them. Biggest gap. We already have the analogous `list_profiles` fan-out pattern to copy.
- [x] `flow-actions` and `flow-messages` — we have `flows` but no step-level structure, so flow performance cannot be broken down.
- [x] Campaign and flow values reporting endpoints — Klaviyo's own computed revenue and engagement metrics.
- [x] `templates`.
- [x] `catalog-items`, `catalog-variants`, `catalog-categories` — product catalog for ecommerce attribution.
- [x] `coupons` and `coupon-codes`.
- [ ] `forms` — signup form performance.
- [x] `reviews`.
- [x] `tags` and `tag-groups`.
- [x] `custom-metrics`, `data-sources`, `object-types`.
- [x] `push-tokens`, `images`, `web-feeds`, `webhooks`, `accounts`.

### Salesforce — our side code-verified, vendor side needs confirmation

`INCREMENTAL_ENDPOINTS` in `salesforce/settings.py` is a hardcoded list of 14 standard sObjects.

- [ ] Custom objects (`*__c`). Not syncable at all today. Nearly every real Salesforce org has them, so this is the biggest gap and is architectural rather than additive.
- [ ] `Case`, `CaseComment`, `CaseHistory` — the entire support side of Salesforce.
- [ ] `OpportunityLineItem` — what was actually in a deal. We have `Opportunity` and `Product2` but nothing joining them.
- [ ] `CampaignMember` — campaign attribution. `Campaign` alone cannot tell you who was in it.
- [ ] `Contract`, `Quote`, `QuoteLineItem`, `Asset`.
- [ ] `LeadHistory`, `AccountHistory`, `ContactHistory` — we have `OpportunityHistory` only.
- [ ] `OpportunityContactRole`, `AccountContactRelation`.
- [ ] `EmailMessage`, `Note`, `ContentDocument` / `Attachment`.
- [ ] `RecordType`, `Profile`, `Group` — needed to interpret the records we already sync.

### Google Analytics — needs confirmation

Ten tables, each a fixed dimension/metric bundle.

- [ ] Ecommerce dimensions and metrics (purchase revenue, items, transactions).
- [ ] Key events / conversions.
- [ ] Landing pages (distinct from the existing `pages`).
- [ ] Demographics: age, gender, interests.
- [ ] Campaign and UTM detail beyond the existing `traffic_sources`.
- [ ] Site search terms.
- [ ] Item / product performance.
- [ ] Cohorts, audiences, custom dimensions and metrics, realtime.

### Chargebee — needs confirmation

Six tables covering the transactional core but no catalog.

- [ ] `Items`, `ItemPrices`, `ItemFamilies`, `Plans` — the product catalog. Subscriptions reference prices we cannot resolve.
- [ ] `CreditNotes`.
- [ ] `Coupons` and `CouponCodes`.
- [ ] `PaymentSources`.
- [ ] `Addons`.
- [ ] `Quotes`.
- [ ] `Usages` and `UnbilledCharges` — usage-based billing.
- [ ] `SubscriptionEntitlements`.
- [ ] `PromotionalCredits`, `Gifts`, `Comments`.

### Zendesk — spec-verified

Diffed against Zendesk's published OpenAPI description.
Nine tables.

- [x] `satisfaction_ratings` — CSAT. Absent, and it is usually the first thing a support team asks for.
- [x] `ticket_metrics` — per-ticket first reply time, full resolution time, and reply counts. We ship `ticket_metric_events` (the raw event stream) but not the rolled-up per-ticket metrics that most people actually want.
- [x] `ticket_comments` / `ticket_audits` — no conversation content or change history.
- [x] `group_memberships`, `organization_memberships` — which agents are in which groups, which users in which orgs.
- [x] `macros`, `views`, `triggers`, `automations` — workflow configuration.
- [x] `custom_roles`, `user_fields`, `organization_fields`, `ticket_forms`, `custom_statuses`.
- [x] `tags`.
- [x] `custom_objects`.
- [ ] `schedules` — business hours, without which SLA math is wrong.
- [x] `audit_logs`, `activities`, `requests`, `suspended_tickets`, `deleted_tickets`, `saved_searches`, `queues`, `brand_agents`.

### Mailchimp — spec-verified

Diffed against Mailchimp's published Swagger schema.
Four tables, and the entire per-recipient engagement layer is missing.

- [x] `reports/*/email-activity` — per-member opens and clicks. The single biggest gap.
- [x] `reports/*/open-details`, `reports/*/click-details`, `reports/*/sent-to`, `reports/*/unsubscribed`, `reports/*/abuse-reports`.
- [x] `lists/*/segments` — segment definitions and membership.
- [x] `automations` and `automations/*/emails` — automated journeys, entirely absent.
- [x] `lists/*/merge-fields`, `lists/*/interest-categories` — needed to interpret contact fields.
- [x] `lists/*/growth-history`, `lists/*/activity` — list growth over time.
- [x] `templates`, `landing-pages`, `sms-campaigns`, `conversations`.
- [x] Ecommerce stores, orders, and products.
- [x] `reports/*/domain-performance`, `reports/*/locations`, `reports/*/ecommerce-product-activity`.
- [x] `campaigns/*/content`, `campaigns/*/feedback`, `campaign-folders`, `verified-domains`.

### Cloudflare — spec-verified

Diffed against [cloudflare/api-schemas](https://github.com/cloudflare/api-schemas).
Three tables (`accounts`, `zones`, `dns_records`).
This is effectively DNS and zone configuration only, and none of the telemetry people connect
Cloudflare for.

- [ ] The GraphQL Analytics API entirely (`httpRequests1dGroups`, `httpRequestsAdaptiveGroups`, `firewallEventsAdhoc`, `workersInvocationsAdaptive`, and siblings). This is the traffic data and it is the most valuable single addition. Note it is GraphQL, not REST, so it needs a different transport than the rest of the source.
- [x] `dns_analytics/report` — query volume and response codes.
- [x] `firewall/rules`, `filters`, `rulesets`, `rate_limits` — security configuration.
- [x] `logpush/jobs`, `logs/received` (`logs/received` still open)
- [x] `workers/routes` and Worker scripts.
- [x] `load_balancers`, `healthchecks`.
- [x] `page_shield/scripts`, `page_shield/connections`.
- [x] `custom_hostnames`, `ssl/certificate_packs`, `custom_certificates`.
- [x] `waiting_rooms`, `pagerules`, `snippets`, `bot_management`.
- [ ] Account `audit_logs`, `billing/usage`, `billable/usage`.
- [x] `access/*` (Zero Trust apps, policies, groups, users) — a large product surface with nothing exposed.
- [ ] R2 buckets, KV namespaces, D1 databases, Stream usage, `spectrum/apps`, `api_gateway/operations`, `security-center/insights`.

## Tier 3

### Customer.io — needs confirmation

Seventeen tables (10 API endpoints plus 7 webhook event streams) and one of our better-covered sources.

- [ ] `customers` / people. We ship `customer_events` but no table of the people themselves, so events cannot be joined to attributes.
- [ ] Activities.
- [ ] Metrics aggregates.

### Postmark — needs confirmation

Five tables. Delivery config is present, engagement is not. `bounces` also accepts pushed rows
through the Webhooks API (Bounce and SpamComplaint triggers).

- [ ] Opens and clicks per message.
- [ ] Outbound overview stats (sends, bounce rate, open rate, spam complaints).
- [ ] `servers`, `suppressions`, `domains`, inbound rules, `webhooks`.

### Brevo — needs confirmation

Eight tables, all list and campaign metadata.

- [ ] Transactional email events (delivered, opened, clicked, bounced, unsubscribed).
- [ ] SMS events.
- [ ] Aggregated campaign statistics.
- [ ] CRM deals and companies.
- [ ] Contact attribute definitions.
- [ ] Automation / workflow data, WhatsApp campaigns, ecommerce orders and products.

### WorkOS — needs confirmation

Six tables covering directory sync.

- [ ] `audit_logs` — the main reason enterprises buy WorkOS.
- [ ] The Events API — WorkOS's own change feed, and the recommended way to keep data fresh.
- [ ] SSO profiles and sessions.
- [ ] `roles`, organization domains, MFA factors, Magic Auth.

### Vercel — needs confirmation

Six tables.

- [ ] Deployment events and build logs.
- [ ] Checks and deployment status transitions.
- [ ] Usage and analytics (Web Analytics, Speed Insights).
- [ ] Environment variables, edge config, log drains, firewall, DNS records, certificates, integrations.

### Paddle — needs confirmation

Seven tables.

- [ ] Notifications / events — Paddle's change feed.
- [ ] `addresses`, `businesses` — customer hierarchy for B2B.
- [ ] Credit notes / adjustments detail beyond the existing `adjustments`.
- [ ] Payment methods, reports.

### Polar — needs confirmation

Eight tables.

- [ ] License keys.
- [ ] Discounts.
- [ ] Payments (distinct from `orders`).
- [ ] Metrics endpoints, customer sessions, files, benefit grants.

### Notion — needs confirmation

Five tables (`pages`, `databases`, `users`, `blocks`, `comments`).

- [ ] Database rows via the query endpoint. We list databases but never read their contents, which is where all the structured data lives. Biggest gap by far.
- [ ] Data sources (the newer multi-source database model).
- [ ] Page property values as columns rather than raw blocks.

### Airtable — needs confirmation

Three tables (`bases`, `tables`, `records`).

- [ ] Field / schema metadata per table, needed to type and label record columns.
- [ ] Views, comments, webhooks.

### Typeform — needs confirmation

Two tables (`forms`, `responses`).

- [ ] Form fields / questions as a table, so responses can be joined to question text rather than opaque field IDs.
- [ ] Form insights and completion-rate summaries.
- [ ] Workspaces, themes, webhooks.

### WooCommerce — needs confirmation

Ten tables, decent coverage. Products, orders, coupons and customers can also sync via webhooks
(`/webhooks`, HMAC-SHA256 signed deliveries) instead of polling.

- [ ] Product variations.
- [ ] Order refunds and order notes.
- [ ] Reports endpoints.
- [ ] Payment gateways, shipping methods. Webhooks are now managed programmatically for sync, but
      are not exposed as a table.

### Slack — needs confirmation

Two static tables (`$channels`, `$users`), but note the source also discovers per-channel message
tables dynamically at sync time, so message coverage is better than the static count suggests.

- [ ] Reactions.
- [ ] Channel membership.
- [ ] Files.
- [ ] User groups, team info, emoji.
- [ ] Admin analytics (member and channel activity).

### Intercom — spec-verified

Diffed 2026-08-04 against [Intercom's published OpenAPI description](https://github.com/intercom/Intercom-OpenAPI)
for every API version this source supports (2.13, 2.15, 2.16).
Twenty-one tables.

- [ ] `data_events` — user event stream. (skipped: `GET /events` is not listable. It requires a
      single-contact filter plus `type=user` and only serves the last 90 days, so it would fan out to
      one request per contact against a per-workspace rate limit.)
- [x] Help center collections and sections — shipped as `collections` and `help_centers`. Sections are
      nested collections (`parent_id`), so the collections table covers both.
- [x] Subscription types — shipped as `subscription_types`.
- [ ] `visitors` — (skipped: `GET /visitors` requires a `user_id` and returns a single visitor; there is
      no list endpoint.)
- [ ] Conversation ratings — (skipped: no endpoint. `conversation_rating` is a field on the conversation
      object, already synced by `conversations`.)
- [x] News items, ticket types — shipped as `news_items`, `newsfeeds`, `ticket_types` and `ticket_states`.
      Macros / saved replies skipped: `GET /macros` only exists in 2.16, so sources pinned to 2.13 or
      2.15 would 404 on it.

### Webflow, WordPress, Calendly, ActiveCampaign, Pipedrive

The first pass punted on these without a real diff. The sweep has since done one, and all five have
gaps, so that earlier "looks proportionate" read was wrong. See the appendix for each.

The two worth pulling forward, because both are higher-adoption than most appendix entries:

- **ActiveCampaign** — no `emailActivities` (per-contact opens and clicks), no e-commerce objects at all (`ecomOrders`, `ecomOrderProducts`, `ecomCustomers`), and no membership tables joining the contacts we sync to the lists and automations we also sync.
- **Pipedrive** — no deal line items (`deals/{id}/products`), so deal revenue is only readable as a single number; `/deals` excludes archived deals, so closed pipeline history is silently missing; and no `deals/{id}/flow` changelog, so stage-transition and velocity analysis is impossible. Webhook ingest now supplements the poll for the seven API v2 entity tables (activities, deals, organizations, persons, pipelines, products, stages); the remaining v1-shaped tables stay poll-only.

## Full sweep results

The remaining 547 sources were swept in a single pass, each diffed against a vendor spec or reference
fetched at audit time. Per-source detail is in [COVERAGE_GAPS_APPENDIX.md](COVERAGE_GAPS_APPENDIX.md).

| Assessment       | Sources | Meaning                                        |
| ---------------- | ------: | ---------------------------------------------- |
| `gaps`           |     411 | Specific valuable endpoints missing            |
| **thin**         |      76 | Source exposes a small fraction of a large API |
| `adequate`       |      55 | Coverage proportionate to the API              |
| could not verify |       5 | No reachable API reference found               |

### Thin sources, worst coverage first by business relevance

These 76 expose a small fraction of a large API. The ones below stand out because the product is
widely used or the missing surface is the reason people connect it at all.

`Square` (payments and orders, but not the catalog or inventory), `Segment`, `Plaid`, `GitLab`,
`Mixpanel`, `SendGrid`, `Zoom`, `Pendo`, `AppsFlyer`, `AmazonAds`, `AdRoll` (no reporting metrics at
all, which is the point of an ads connector), `Deel`, `BambooHR`, `Personio`, `HiBob`, `Factorial`,
`Matomo`, `FullStory`, `Iterable`, `Fastly`, `AzureDevOps`, `Smartsheet`, `Coupa`, `Ramp`,
`CheckoutCom`, `Cloudbeds`, `Planhat`, `Sourcegraph`, `Jumpcloud`, `Kandji`, `JamfPro`, `Veracode`,
`TenableVulnerabilityManagement`, `Kubecost`, `Scaleway`, `Telnyx`, `Plain`, `Svix`, `Ably`.

Full list of all 76 in the appendix.

### Adequately covered

55 sources need nothing. Mostly small, single-purpose APIs where we already expose everything
queryable: `PyPI`, `Packagist`, `GNews`, `NewsApi`, `Guardian`, `Firecrawl`, `Imagga`,
`GooglePageSpeedInsights`, `MicrosoftClarity`, `Mailosaur`, `Healthchecks.io`, `Coveralls`,
`OnePassword`, `LemonSqueezy`, `Granola`, and others listed in the appendix.

### Could not verify

`Decagon`, `Height`, `OPUSWatch`, `OrcaSecurity`, `Sentinelone`.
No reachable machine-readable reference was found for these during the sweep, usually because the
docs sit behind auth or a customer portal.
They are recorded so their empty gap lists are not mistaken for good coverage.
Each needs a manual pass, likely with vendor credentials.

## What this audit did not cover

- **Column-level coverage was not audited at all.** A table can exist while missing most of the vendor's fields (sparse fieldsets, `fields[...]` params, `properties` allowlists). This is the largest remaining blind spot and is probably a bigger body of work than everything in this document.
- **Incremental-sync quality was not audited.** Some tables exist but only support full refresh, which is its own class of gap and is invisible to an endpoint diff.
- **Nothing was validated against a live vendor account.** Endpoints listed here may be deprecated, gated behind a plan tier, or unavailable on the API version we pin. Confirm before building.
- **Sweep rationales are less reliable than sweep endpoints.** The endpoint names were read from fetched specs and spot-checks found them accurate, but the one-line justification beside each is the auditing agent's reasoning and occasionally over-claims (for example asserting a lookup resolves a field on a table we do not actually sync). Trust the endpoint, re-derive the rationale.
- **The five "could not verify" sources are unknowns, not clean bills of health.**
