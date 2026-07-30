# Warehouse source endpoint coverage gaps

A backlog of endpoints and tables our **already-implemented** sources do not expose yet,
but that users plausibly want data from.

This is not a list of unimplemented sources.
Every source below already syncs data.
The gap is that the vendor's API offers objects we never wired up.

Produced 2026-07-26 by the [auditing-warehouse-source-coverage skill](/.agents/skills/auditing-warehouse-source-coverage/SKILL.md).
Re-run that skill to refresh this file.
Tick items off as they ship rather than deleting them, so the next audit can tell "done" from "never found".

**Coverage is complete.** All 586 implemented sources have been diffed against a vendor spec or
reference.
This file carries the method, the cross-source patterns, and the highest-adoption sources in depth.
Per-source detail for the remaining 547 lives in
[COVERAGE_GAPS_APPENDIX.md](COVERAGE_GAPS_APPENDIX.md), which is generated and covers every source
with its assessment, the doc URL it was diffed against, and its gap list.

Headline numbers: **4,540 missing endpoints across 547 sources**, of which 1,704 are high priority.
466 sources have at least one high-priority gap.
55 sources are adequately covered.

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

| Marker                 | Meaning                                                                                                                                                   |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **spec-verified**      | The vendor's official machine-readable spec was fetched on 2026-07-26 and diffed against our endpoint list. Gaps are real as of that date.                |
| **needs confirmation** | Our side was read from code, but the vendor side comes from API familiarity rather than a fetched spec. Confirm against current docs before implementing. |

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

- [ ] `payment_intents` — the payment funnel and failure reasons. Charges alone miss attempts that never became a charge.
- [ ] `checkout/sessions` — checkout conversion and abandonment.
- [ ] `subscription_items` — per-price lines on multi-item subscriptions. Without it, MRR cannot be split by product on any subscription with more than one item.
- [ ] `subscription_schedules` — phased and scheduled subscription changes.
- [ ] `promotion_codes` — `Coupon` tells you the discount exists but not which redeemable code was used.
- [ ] `plans` — the legacy pricing model, still widely in use.
- [ ] `tax_rates` and `tax_ids`.
- [ ] `quotes` — sales-led billing.
- [ ] `events` — Stripe's own event log, useful as a generic change feed.
- [ ] `billing/meters`, `billing/credit_grants`, `billing/credit_balance_transactions`, `billing/credit_balance_summary` — usage-based billing. Entirely absent, and this is where Stripe is actively investing.
- [ ] `entitlements/features`, `entitlements/active_entitlements` — feature entitlements.
- [ ] `invoice_payments` — how an invoice actually got paid.
- [ ] `setup_intents`, `setup_attempts` — payment method setup funnel.
- [ ] `payment_links`.
- [ ] `transfers`, `application_fees`, `topups` — needed by any Connect platform.
- [ ] `reviews`, `radar/early_fraud_warnings` — fraud review outcomes.
- [ ] `shipping_rates`.

Lower priority: `issuing/*`, `treasury/*`, `terminal/*`, `identity/*`, `financial_connections/*`,
`climate/*`, `sigma/*`, `reporting/*`, `forwarding/*`, `files`, `file_links`, `webhook_endpoints`,
`country_specs`, `exchange_rates`, `radar/value_lists`, `billing_portal/configurations`,
`payment_method_configurations`, `payment_method_domains`, `invoice_rendering_templates`.

### Google Ads — needs confirmation

21 tables and the best-covered source we have.
Remaining gaps are mostly breakdown views and account-config resources.

- [ ] `campaign_budget` — budgets and budget pacing.
- [ ] `age_range_view`, `gender_view` — demographic breakdowns.
- [ ] `detail_placement_view`, `landing_page_view` — where ads actually ran and landed.
- [ ] `change_event` — audit of who changed what in the account.
- [ ] `user_location_view` / `location_view` — distinct from the existing `geographic_stats`.
- [ ] `audience`, `bidding_strategy`, `label`, `recommendation`.
- [ ] `product_group_view` — Shopping campaign structure beyond `shopping_performance_view`.
- [ ] `asset` — individual asset performance, complements `asset_group`.
- [ ] Device segmentation and hourly segmentation on the existing stats views.
- [ ] Conversion stats segmented by `conversion_action` (we have the actions but not their stats).

### Meta Ads — needs confirmation

Six tables: `campaigns`, `adsets`, `ads`, and one stats table each.
The thinnest coverage of any tier 1 source, and the two biggest omissions are structural.

- [ ] `adcreatives` — no creative metadata at all. You cannot tell what an ad looked like.
- [ ] Insight breakdowns: `age`, `gender`, `country`, `region`, `publisher_platform`, `platform_position`, `impression_device`. None available.
- [ ] Action breakdowns: `actions`, `action_values`, `cost_per_action_type` — conversion outcomes by type.
- [ ] `ad_account` — spend caps, currency, timezone, funding. Currency especially, since stats are meaningless without it.
- [ ] Lead gen forms and `leads` — the payload of Meta lead ads.
- [ ] `customaudiences` and saved audiences.
- [ ] `adimages`, `advideos` — creative assets.
- [ ] `adspixels` and custom conversions.
- [ ] `adrules_library` — automated rules.

`schemas.py` also carries a `AdsetStats = "adset_stats"  # TODO: remove this` marker worth resolving
while in here.

### GitHub — spec-verified

Diffed against [github/rest-api-description](https://github.com/github/rest-api-description).
Ten tables focused on code and CI.
The gaps make review-latency and issue-lifecycle analysis impossible, which is the main
engineering-analytics use case.

- [ ] `issues/comments` and `pulls/comments` — no comment data at all, so review latency and discussion volume are unavailable.
- [ ] `issues/events` — labeled, assigned, closed, reopened transitions. Needed for time-in-state.
- [ ] Repository metadata itself. There is no `repositories` table, so stars/forks/language/visibility per repo are unavailable even though the source is repo-scoped.
- [ ] `branches`, `tags`.
- [ ] `contributors`, `collaborators`.
- [ ] `labels`, `milestones`.
- [ ] `deployments`, `environments`.
- [ ] `traffic/views`, `traffic/clones`, plus referrers and popular paths.
- [ ] `stats/contributors`, `stats/commit_activity`, `stats/participation`, `stats/code_frequency`.
- [ ] Check runs and commit statuses — CI signal at commit granularity, complementing `workflow_runs`.
- [ ] `actions/workflows`, `actions/artifacts`, `actions/runners`, `actions/caches`.
- [ ] `code-scanning/alerts`, `dependabot/alerts`, `secret-scanning/alerts` — security posture over time.
- [ ] `forks`, `subscribers` (watchers), `topics`.
- [ ] `rulesets`, `security-advisories`, `hooks`, `languages`, `community/profile`, `dependency-graph/sbom`.
- [ ] Discussions.

### HubSpot — our side code-verified, vendor side needs confirmation

`ENDPOINTS` in `hubspot/settings.py` is exactly seven CRM objects.
Two small additions would unblock most real analysis.

- [ ] `pipelines` (and pipeline stages) — deals and tickets return `dealstage` and `pipeline` as opaque IDs today, so no one can group by stage name without hardcoding a mapping. Highest value item here.
- [ ] `owners` — same problem for owner IDs. Also unblocks rep-level reporting.
- [ ] `line_items` and `products` — deal composition and what was actually sold.
- [ ] `calls`, `notes`, `tasks`, `communications` — the rest of the engagement objects. We have `emails` and `meetings` only.
- [ ] `lists` and list memberships.
- [ ] Marketing emails and marketing campaigns, with their statistics.
- [ ] `forms` and form submissions.
- [ ] Custom objects. Currently impossible to sync, and most mature HubSpot portals have them.
- [ ] Property definitions — needed to interpret and label custom properties.
- [ ] Associations as a first-class table. Today they ride along as a query param on contacts and companies only, so deal-to-contact links are not queryable.
- [ ] Feedback submissions (NPS/CSAT surveys).
- [ ] Workflows.
- [ ] Web analytics events. `WEB_ANALYTICS_EVENTS_ENDPOINT` is already defined in `hubspot/settings.py:63` but is referenced nowhere else, so this is a half-finished thread rather than a new build.

### LinkedIn Ads — needs confirmation

Seven tables, and the only ad platform that already ships `creatives`.

- [ ] Member-demographic pivots: `MEMBER_COMPANY`, `MEMBER_INDUSTRY`, `MEMBER_SENIORITY`, `MEMBER_JOB_TITLE`, `MEMBER_COUNTRY_V2`, `MEMBER_COMPANY_SIZE`. This is the reason people advertise on LinkedIn and none of it is available.
- [ ] Lead gen forms and form responses.
- [ ] Conversions and conversion events.
- [ ] Audiences / DMP segments.
- [ ] Budget and bid data on campaigns.
- [ ] Video ad analytics.

### Google Search Console — needs confirmation

Seven tables, all of them `search_analytics` dimension bundles.

- [ ] `sitemaps` — submission status, errors, indexed counts.
- [ ] `sites` — the property list itself.
- [ ] URL inspection results (index status per URL).
- [ ] Additional dimension combinations, notably date + page + query together, and country + device.

### Clerk — spec-verified

Diffed against [clerk/openapi-specs](https://github.com/clerk/openapi-specs).
Four tables, and the two that matter most for an auth provider are missing.

- [ ] `sessions` — no login/session data, so "how many people signed in" is unanswerable. Biggest gap.
- [ ] `sign_ups` — signup attempts including abandoned and failed ones. `users` only shows successes.
- [ ] `organization_invitations`, `organization_domains`.
- [ ] `organization_roles`, `organization_permissions` — needed to interpret membership roles.
- [ ] `waitlist_entries`.
- [ ] `allowlist_identifiers`, `blocklist_identifiers`.
- [ ] `domains`, `saml_connections`, `enterprise_connections` — enterprise SSO configuration.
- [ ] `billing` and `commerce` — Clerk's newer billing surface.
- [ ] `oauth_applications`, `api_keys`, `m2m_tokens`, `machines`, `clients`.
- [ ] `email_addresses`, `phone_numbers` as their own tables.
- [ ] `actor_tokens`, `sign_in_tokens`, `jwt_templates`, `redirect_urls`, `role_sets`, `templates`, `webhooks`.

### Reddit Ads, TikTok Ads, Snapchat Ads, Pinterest Ads — needs confirmation

All four ship the same six-table shape (campaigns, ad groups / ad squads, ads, plus one report each)
and all four have the same two gaps.
See patterns 1 and 2 above.

- [ ] Creative metadata for each platform.
- [ ] Breakdown dimensions (age, gender, geo, placement, device) on the report tables.
- [ ] Ad account table (currency and timezone, without which spend is ambiguous).
- [ ] Audiences and pixel / conversion event definitions.

### Linear — needs confirmation

Eight tables. Two small additions unblock the cycle-time use case.

- [ ] `workflow_states` — issues carry a state ID with no way to resolve it to a name or type (backlog / started / completed). Highest value item.
- [ ] `issue_history` — state transitions over time. Without it, cycle time, lead time, and time-in-state cannot be computed.
- [ ] `project_milestones`, `initiatives`, `roadmaps`.
- [ ] `attachments` — links out to PRs and tickets, which is how Linear connects to GitHub.
- [ ] `issue_relations` — blocks / blocked-by / duplicates.
- [ ] `project_updates`, `documents`.
- [ ] `team_memberships`, `organization`.
- [ ] Custom views, templates, reactions, triage responsibilities.

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

- [ ] `sessions` — release health and crash-free rate. The headline Sentry metric and not available.
- [ ] `releases/*/deploys` and `releases/*/commits` (plus `commitfiles`) — we have `releases` but nothing about what shipped in them or when they deployed.
- [ ] `user-feedback` — user-submitted reports.
- [ ] `replays` — session replay metadata.
- [ ] `stats_v2` / `stats-summary` — event volume and quota consumption per project.
- [ ] `repos` and repo commits.
- [ ] `dashboards`, `discover/saved`.
- [ ] `monitors/*/checkins` — we have `monitors` but not their check-in history.
- [ ] `workflows`, `detectors` — the current alerting model.
- [ ] Organization-level `tags` and `events` (Discover).
- [ ] `trace-items` and trace metadata — tracing and spans.
- [ ] Project `filters`, `ownership`, `stats`.
- [ ] `integrations` and installed apps.

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

Four tables: `campaigns` plus three performance reports.
No ad group, ad, or keyword entity tables at all, which is unusual relative to our other ad sources.

- [ ] `ad_groups` and `ads` as entity tables. Today the ad group and ad performance reports reference IDs with nothing to join to.
- [ ] `keywords` and `keyword_performance_report`.
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

- [ ] `segments` and segment membership — Klaviyo users organize everything around segments and we expose none of them. Biggest gap. We already have the analogous `list_profiles` fan-out pattern to copy.
- [ ] `flow-actions` and `flow-messages` — we have `flows` but no step-level structure, so flow performance cannot be broken down.
- [ ] Campaign and flow values reporting endpoints — Klaviyo's own computed revenue and engagement metrics.
- [ ] `templates`.
- [ ] `catalog-items`, `catalog-variants`, `catalog-categories` — product catalog for ecommerce attribution.
- [ ] `coupons` and `coupon-codes`.
- [ ] `forms` — signup form performance.
- [ ] `reviews`.
- [ ] `tags` and `tag-groups`.
- [ ] `custom-metrics`, `data-sources`, `object-types`.
- [ ] `push-tokens`, `images`, `web-feeds`, `webhooks`, `accounts`.

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

- [ ] `satisfaction_ratings` — CSAT. Absent, and it is usually the first thing a support team asks for.
- [ ] `ticket_metrics` — per-ticket first reply time, full resolution time, and reply counts. We ship `ticket_metric_events` (the raw event stream) but not the rolled-up per-ticket metrics that most people actually want.
- [ ] `ticket_comments` / `ticket_audits` — no conversation content or change history.
- [ ] `group_memberships`, `organization_memberships` — which agents are in which groups, which users in which orgs.
- [ ] `macros`, `views`, `triggers`, `automations` — workflow configuration.
- [ ] `custom_roles`, `user_fields`, `organization_fields`, `ticket_forms`, `custom_statuses`.
- [ ] `tags`.
- [ ] `custom_objects`.
- [ ] `schedules` — business hours, without which SLA math is wrong.
- [ ] `audit_logs`, `activities`, `requests`, `suspended_tickets`, `deleted_tickets`, `saved_searches`, `queues`, `brand_agents`.

### Mailchimp — spec-verified

Diffed against Mailchimp's published Swagger schema.
Four tables, and the entire per-recipient engagement layer is missing.

- [ ] `reports/*/email-activity` — per-member opens and clicks. The single biggest gap.
- [ ] `reports/*/open-details`, `reports/*/click-details`, `reports/*/sent-to`, `reports/*/unsubscribed`, `reports/*/abuse-reports`.
- [ ] `lists/*/segments` — segment definitions and membership.
- [ ] `automations` and `automations/*/emails` — automated journeys, entirely absent.
- [ ] `lists/*/merge-fields`, `lists/*/interest-categories` — needed to interpret contact fields.
- [ ] `lists/*/growth-history`, `lists/*/activity` — list growth over time.
- [ ] `templates`, `landing-pages`, `sms-campaigns`, `conversations`.
- [ ] Ecommerce stores, orders, and products.
- [ ] `reports/*/domain-performance`, `reports/*/locations`, `reports/*/ecommerce-product-activity`.
- [ ] `campaigns/*/content`, `campaigns/*/feedback`, `campaign-folders`, `verified-domains`.

### Cloudflare — spec-verified

Diffed against [cloudflare/api-schemas](https://github.com/cloudflare/api-schemas).
Three tables (`accounts`, `zones`, `dns_records`).
This is effectively DNS and zone configuration only, and none of the telemetry people connect
Cloudflare for.

- [ ] The GraphQL Analytics API entirely (`httpRequests1dGroups`, `httpRequestsAdaptiveGroups`, `firewallEventsAdhoc`, `workersInvocationsAdaptive`, and siblings). This is the traffic data and it is the most valuable single addition. Note it is GraphQL, not REST, so it needs a different transport than the rest of the source.
- [ ] `dns_analytics/report` — query volume and response codes.
- [ ] `firewall/rules`, `filters`, `rulesets`, `rate_limits` — security configuration.
- [ ] `logpush/jobs`, `logs/received`.
- [ ] `workers/routes` and Worker scripts.
- [ ] `load_balancers`, `healthchecks`.
- [ ] `page_shield/scripts`, `page_shield/connections`.
- [ ] `custom_hostnames`, `ssl/certificate_packs`, `custom_certificates`.
- [ ] `waiting_rooms`, `pagerules`, `snippets`, `bot_management`.
- [ ] Account `audit_logs`, `billing/usage`, `billable/usage`.
- [ ] `access/*` (Zero Trust apps, policies, groups, users) — a large product surface with nothing exposed.
- [ ] R2 buckets, KV namespaces, D1 databases, Stream usage, `spectrum/apps`, `api_gateway/operations`, `security-center/insights`.

## Tier 3

### Customer.io — needs confirmation

Seventeen tables (10 API endpoints plus 7 webhook event streams) and one of our better-covered sources.

- [ ] `customers` / people. We ship `customer_events` but no table of the people themselves, so events cannot be joined to attributes.
- [ ] Activities.
- [ ] Metrics aggregates.

### Postmark — needs confirmation

Five tables. Delivery config is present, engagement is not.

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

Ten tables, decent coverage.

- [ ] Product variations.
- [ ] Order refunds and order notes.
- [ ] Reports endpoints.
- [ ] Payment gateways, shipping methods, webhooks.

### Slack — needs confirmation

Two static tables (`$channels`, `$users`), but note the source also discovers per-channel message
tables dynamically at sync time, so message coverage is better than the static count suggests.

- [ ] Reactions.
- [ ] Channel membership.
- [ ] Files.
- [ ] User groups, team info, emoji.
- [ ] Admin analytics (member and channel activity).

### Intercom — needs confirmation

Fourteen tables and solid coverage.

- [ ] `data_events` — user event stream.
- [ ] Help center collections and sections (we have `articles` but not their structure).
- [ ] Subscription types.
- [ ] `visitors`.
- [ ] Conversation ratings.
- [ ] News items, ticket types, macros / saved replies.

### Webflow, WordPress, Calendly, ActiveCampaign, Pipedrive

The first pass punted on these without a real diff. The sweep has since done one, and all five have
gaps, so that earlier "looks proportionate" read was wrong. See the appendix for each.

The two worth pulling forward, because both are higher-adoption than most appendix entries:

- **ActiveCampaign** — no `emailActivities` (per-contact opens and clicks), no e-commerce objects at all (`ecomOrders`, `ecomOrderProducts`, `ecomCustomers`), and no membership tables joining the contacts we sync to the lists and automations we also sync.
- **Pipedrive** — no deal line items (`deals/{id}/products`), so deal revenue is only readable as a single number; `/deals` excludes archived deals, so closed pipeline history is silently missing; and no `deals/{id}/flow` changelog, so stage-transition and velocity analysis is impossible.

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
