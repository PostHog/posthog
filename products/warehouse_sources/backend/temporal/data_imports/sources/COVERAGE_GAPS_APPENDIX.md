# Warehouse source coverage: full sweep appendix

Per-source detail for the complete sweep of implemented sources, generated 2026-07-26.
See [COVERAGE_GAPS.md](COVERAGE_GAPS.md) for the method, the cross-source patterns, and the
highest-adoption sources, which are covered there in more depth than here.

Every source below was diffed against a vendor spec or reference that was actually fetched during
the sweep, and the URL used is recorded with each entry.
Sources marked "could not verify" had no reachable machine-readable reference; they are listed so
the absence of findings is not mistaken for coverage.

Assessments: **thin** means the source exposes a small fraction of a large API.
`gaps` means specific valuable endpoints are missing.
`adequate` means coverage is proportionate to the API.

Priorities: `high` blocks a core use case, is the vendor's headline metric, or is a lookup table
for IDs we already sync. `medium` is commonly wanted. `low` is nice to have.

Endpoint names came from fetched specs and spot-check accurately. The one-line rationale beside
each is the auditing agent's reasoning and occasionally over-claims, so re-derive it before building.

## Ably — **thin**

Today (1): `Stats`

Diffed against: <https://raw.githubusercontent.com/ably/open-specs/main/definitions/platform-v1.yaml>

- [ ] `apps (Control API GET /accounts/{account_id}/apps)` — lookup table resolving the app IDs every Stats row is scoped to (high)
- [ ] `channels (GET /channels)` — channel enumeration with per-channel occupancy/connection/publisher counts (high)
- [ ] `channel messages history (GET /channels/{channel_id}/messages)` — the actual message event stream, not just aggregated stats (high)
- [ ] `presence (GET /channels/{channel_id}/presence)` — current members per channel for concurrency analysis (medium)
- [ ] `presence history (GET /channels/{channel_id}/presence/history)` — enter/leave transition history per channel (medium)
- [ ] `push device registrations (GET /push/deviceRegistrations)` — device inventory backing push delivery stats (medium)
- [ ] `push channel subscriptions (GET /push/channelSubscriptions)` — membership table linking devices to channels (medium)
- [ ] `namespaces (Control API GET /apps/{app_id}/namespaces)` — lookup resolving channel namespace names seen in channel data (low)

Note: Source uses a static ENDPOINTS list (products/warehouse_sources/backend/temporal/data_imports/sources/ably/source.py -> build_endpoint_schemas), so no dynamic table discovery. Ably splits its surface across two specs: platform-v1.yaml (stats/channels/presence/push) and control-v1.yaml (apps/keys/namespaces/queues/rules); most of control-v1 is config and correctly excluded, but apps is a genuine lookup. Channel-scoped endpoints require enumerating /channels first, so they'd need per-channel fan-out at sync time.

## ActiveCampaign — gaps

Today (12): `accounts`, `automations`, `campaigns`, `contacts`, `custom_fields`, `deal_groups`, `deal_stages`, `deals`, `forms`, `lists`, `segments`, `tags`

Diffed against: <https://developers.activecampaign.com/reference/overview>

- [ ] `emailActivities` — per-contact email opens/clicks/sends, the core engagement fact table (high)
- [ ] `ecomOrders` — e-commerce revenue transactions; no commerce data is synced at all today (high)
- [ ] `ecomOrderProducts` — order line items needed for product-level revenue breakdowns (high)
- [ ] `ecomCustomers` — resolves the customer IDs carried on ecom orders (high)
- [ ] `dealActivities (GET /deals/{id}/dealActivities)` — deal stage-transition and change history (high)
- [ ] `contactActivities (GET /activities)` — contact-level activity timeline across campaigns and automations (high)
- [ ] `contactLists (list memberships)` — membership table joining synced contacts to synced lists (high)
- [ ] `contactAutomations` — membership table joining synced contacts to synced automations, with entry/exit state (high)
- [ ] `accountContacts (account-contact association)` — membership table joining synced accounts to synced contacts (medium)
- [ ] `users (and groups)` — lookup resolving owner IDs on deals, tasks and notes (medium)
- [ ] `notes` — free-text CRM notes attached to contacts, deals and accounts (medium)
- [ ] `tasks (with taskTypes / taskOutcomes)` — sales activity volume plus the lookup tables that decode task type and outcome (medium)

Note: deal_groups/deal_stages already cover the pipelines and stages lookups. The reference sidebar also exposes campaign messages, campaign link stats, scores, bounce logs, custom object records, conversations, SMS broadcast metrics and the separate e-commerce GraphQL API — all plausible but lower value than the 12 above.

## AdRoll — **thin**

Today (3): `ads`, `advertisables`, `campaigns`

Diffed against: <https://apidocs.nextroll.com/crud-api/reference.html>

- [ ] `adgroups (GET /api/v1/advertisable/get_adgroups, /api/v1/campaign/get_adgroups)` — the missing middle level of the campaign -> adgroup -> ad hierarchy we already half-sync (high)
- [ ] `report/campaign, report/adgroup, report/ad, report/advertisable` — delivery and attribution metrics - impressions, clicks, spend, conversions; the whole point of an ads connector (high)
- [ ] `segments (GET /api/v1/advertisable/get_segments, /api/v1/segment/get)` — audience segments targeted by adgroups, with sizes (high)
- [ ] `organization (GET /api/v1/organization/get, get_advertisables, get_accounts)` — lookup resolving the org/account EIDs that advertisables hang off (medium)
- [ ] `pixel (GET /api/v1/advertisable/get_pixel, /api/v1/pixel/get)` — conversion tracking pixel per advertisable (medium)
- [ ] `rules (GET /api/v1/pixel/get_rules, /api/v1/rule/get)` — conversion and retargeting rule definitions that decode segment membership (medium)
- [ ] `invoice (GET /api/v1/invoice/get)` — billed spend reconciliation against reported campaign spend (medium)
- [ ] `organization users (GET /api/v1/organization/get_users)` — lookup for who owns/changed campaigns (low)
- [ ] `product_feeds/get_products` — catalog products behind dynamic creative (low)
- [ ] `marketplace_deals (GET /api/v1/marketplace_deals/get)` — programmatic deal terms for spend analysis (low)
- [ ] `contextual_categories` — lookup decoding contextual targeting categories on adgroups (low)
- [ ] `dynamic_template/get_all_for_advertisable` — creative template lookup for dynamic ads (low)

Note: NextRoll splits reporting into a separate GraphQL Reporting API (https://apidocs.nextroll.com/graphql-reporting-api/index.html) that supersedes the legacy CRUD /api/v1/report/\* endpoints - delivery and attribution metrics by advertisable, campaign, adgroup, ad, plus granular conversions. The developers.nextroll.com URL in the payload is an Angular shell with no content; the real reference is apidocs.nextroll.com.

## AgileCRM — gaps

Today (5): `companies`, `contacts`, `deals`, `events`, `tasks`

Diffed against: <https://raw.githubusercontent.com/agilecrm/rest-api/master/README.md>

- [ ] `milestone/pipelines (GET /dev/api/milestone/pipelines)` — tracks and their milestones - the lookup table decoding the milestone field on every synced deal (high)
- [ ] `tickets (GET /dev/api/tickets/filter)` — help desk tickets, an entire product area with no coverage today (high)
- [ ] `notes (GET /dev/api/notes, /dev/api/contacts/{id}/notes, /dev/api/opportunity/{id}/notes)` — free-text notes attached to synced contacts and deals (medium)
- [ ] `ticket notes/messages (GET /dev/api/tickets/notes/{ticket-id})` — the conversation thread inside each ticket (medium)
- [ ] `workflows / campaigns (GET /dev/api/workflows)` — marketing campaign definitions that contact automation activity references (medium)
- [ ] `documents (GET /dev/api/documents/contact/{contact_id}/docs)` — files attached to contacts (low)

Note: The AgileCRM README is the only reference; there is no machine-readable spec. Deal endpoints are under /dev/api/opportunity, and the pipeline lookup is under the non-obvious /dev/api/milestone/pipelines path.

## Aha — gaps

Today (8): `epics`, `features`, `goals`, `ideas`, `initiatives`, `products`, `todos`, `users`

Diffed against: <https://www.aha.io/api>

- [ ] `releases (GET /api/v1/products/{id}/releases)` — core roadmap object that every synced feature belongs to; currently unresolvable (high)
- [ ] `requirements (GET /api/v1/features/{id}/requirements)` — the child records under features, where most delivery detail lives (high)
- [ ] `workflow_status_times (GET .../workflow_status_times for features, epics, ideas, releases, requirements, initiatives, key_results)` — state transition history - time in each workflow status, needed for cycle-time analysis (high)
- [ ] `idea_votes (GET /api/v1/ideas/{id}/endorsements, /api/v1/idea_votes)` — the headline demand metric for ideas we already sync (high)
- [ ] `workflows (GET /api/v1/workflows)` — lookup table decoding the workflow_status IDs carried on features, epics, ideas and releases (high)
- [ ] `key_results (GET /api/v1/goals/{id}/key_results)` — the measurable targets under every synced goal (high)
- [ ] `comments (GET /api/v1/products/{id}/comments and per-record variants) plus idea_comments` — discussion activity across features, releases, goals and ideas (high)
- [ ] `release_phases (GET /api/v1/release_phases)` — phase/milestone breakdown inside releases for schedule analysis (medium)
- [ ] `idea_organizations (GET /api/v1/idea_organizations)` — lookup resolving which customer organization submitted or voted on an idea (medium)
- [ ] `idea_categories (GET /api/v1/products/{id}/idea_categories)` — lookup decoding the category dimension on synced ideas (medium)
- [ ] `notes (GET /api/v1/products/{id}/pages)` — product notes/pages, a first-class content object with workflow status (medium)
- [ ] `teams and team_members (GET /api/v1/teams, /api/v1/teams/{id}/team_members)` — capacity/ownership dimension for features and initiatives (medium)

Note: Aha! exposes ~65 resource families under /api/resources; the eight synced tables are a small slice. Also worth considering later: custom_fields + custom_field_options (decode custom field IDs), audits/historical_audits (record change log), time_tracking_events, schedules, capacity_investments, idea_portals, idea_users, competitors, personas, strategic_models.

## Airbrake — gaps

Today (4): `deploys`, `groups`, `notices`, `projects`

Diffed against: <https://docs.airbrake.io/docs/devops-tools/api/>

- [ ] `project activities (GET /api/v4/projects/{project_id}/activities)` — per-project activity/change log complementing the error groups already synced (medium)
- [ ] `group statistics (GET /api/v4/projects/{project_id}/groups/{group_id}/stats)` — time-bucketed occurrence counts per error group - the trend metric behind each group (medium)
- [ ] `project statistics (GET /api/v4/projects/{project_id}/stats)` — project-level error volume over time for quota and regression tracking (medium)

Note: Airbrake's readable v4 surface is small and coverage is close to complete: projects, deploys, groups and notices are all synced. The Performance Monitoring endpoints (routes-stats, routes-breakdowns, queries, queues) are PUT-only ingestion, not queryable, so they are not a warehouse gap. Source maps and iOS crash report upload are plumbing and excluded.

## Aircall — gaps

Today (6): `calls`, `contacts`, `numbers`, `tags`, `teams`, `users`

Diffed against: <https://developer.aircall.io/api-references/>

- [ ] `call transcription (GET /v1/calls/{call_id}/transcription)` — the transcript text behind every synced call; unlocks all text analysis (high)
- [ ] `call sentiments (GET /v1/calls/{call_id}/sentiments)` — Conversation Intelligence sentiment scoring per call, a headline metric (high)
- [ ] `call topics (GET /v1/calls/{call_id}/topics)` — topic breakdown dimension over calls we already sync (high)
- [ ] `call evaluations (GET /v1/calls/{call_id}/evaluations)` — QA scorecards per call - the main agent-quality metric (high)
- [ ] `call summary and custom summary result` — generated call summaries joinable to the calls table (medium)
- [ ] `predicted CSAT (GET /v1/calls/{call_id}/predicted_csat)` — per-call satisfaction prediction, a core support KPI (medium)
- [ ] `call action items` — extracted follow-ups per call for outcome tracking (medium)
- [ ] `user availabilities (GET /v1/users/availabilities)` — agent availability state, needed for staffing and utilization analysis (medium)
- [ ] `analytics report export (POST/GET /v1/analytics/report/export)` — Aircall's own aggregated analytics reports (volumes, service level) as a ready-made fact table (medium)
- [ ] `company (GET /v1/company)` — account-level lookup row giving the tenant these calls belong to (low)

Note: The Conversation Intelligence endpoints are all per-call sub-resources, so they require fanning out over the already-synced calls table rather than a top-level list call. Aircall also has Users V2 alongside V1 and a Messages/WhatsApp surface that is send-only (inbound arrives via webhooks), so there is no listable conversations table to sync.

## AirOps — **thin**

Today (2): `apps`, `executions`

Diffed against: <https://docs.airops.com/llms.txt>

- [ ] `brand_kits (POST /public_api/brand_kits/list)` — the top-level object all AI-search-visibility data hangs off; a lookup for everything below (high)
- [ ] `brand kit analytics (POST /public_api/brand_kits/{brand_kit_id}/analytics)` — AirOps' headline AI visibility/share-of-voice metrics (high)
- [ ] `citations (POST /public_api/brand_kits/{brand_kit_id}/citations/list)` — per-URL citation counts, citation share and influence score across AI answers (high)
- [ ] `answers (POST /public_api/brand_kits/{brand_kit_id}/answers/list)` — the raw LLM answers being measured - the fact table under every visibility metric (high)
- [ ] `prompts (POST /public_api/brand_kits/{brand_kit_id}/prompts/list)` — the tracked prompt set; the dimension every answer and citation is grouped by (high)
- [ ] `topics (POST /public_api/brand_kits/{brand_kit_id}/topics/list)` — lookup decoding the topic dimension on prompts and answers (medium)
- [ ] `competitors (POST /public_api/brand_kits/{brand_kit_id}/competitors/list)` — competitive share-of-voice comparison, a core reporting cut (medium)
- [ ] `web_pages (POST /public_api/brand_kits/{brand_kit_id}/web_pages/list)` — page-level performance for owned content (medium)
- [ ] `content_updates (GET/POST /public_api/brand_kits/{brand_kit_id}/content_updates/list)` — content refresh jobs and their outcomes over time (medium)
- [ ] `sentiment_theme_answers (POST /public_api/brand_kits/{brand_kit_id}/sentiment_theme_answers)` — sentiment/theme breakdown dimension over answers (medium)
- [ ] `personas (POST /public_api/brand_kits/{brand_kit_id}/personas/list)` — lookup decoding the persona dimension used when generating prompts (medium)
- [ ] `brand kit tags (POST /public_api/brand_kits/{brand_kit_id}/tags/list)` — lookup for tag labels applied to prompts and content (low)

Note: AirOps has repositioned around AI search visibility; the entire brand-kit surface (analytics, citations, answers, prompts, competitors, sentiment) is missing and is now the product's main analytical value. Note the list endpoints are POST, not GET, and are all nested under /public_api/brand_kits/{brand_kit_id}/..., so an implementation needs to enumerate brand kits first. Each doc page embeds a full OpenAPI 3.0.1 fragment in its .md version.

## Aiven — gaps

Today (9): `billing_groups`, `clouds`, `invoice_lines`, `invoices`, `organization_users`, `organizations`, `projects`, `services`, `user_groups`

Diffed against: <https://api.aiven.io/doc/openapi.json>

- [ ] `GET /project/{project}/users` — project membership join - who can access each project we already sync (high)
- [ ] `GET /organization/{organization_id}/user-groups/{user_group_id}/members` — membership rows for the user_groups table already synced (high)
- [ ] `GET /billing-group/{billing_group_id}/projects` — lookup mapping projects to billing groups, needed to attribute invoice_lines to projects (high)
- [ ] `GET /project/{project}/events` — project/service audit and state-change history (high)
- [ ] `GET /billing-group/{billing_group_id}/credits` — credit transactions that offset the invoices already synced (medium)
- [ ] `GET /project/{project}/service-types and /project/{project}/service-types/{service_type}/plans` — lookup resolving the service_type/plan identifiers carried on services (medium)
- [ ] `GET /project/{project}/service/{service_name}/tags and /project/{project}/tags` — tag dimensions used for cost and ownership attribution (medium)
- [ ] `GET /project/{project}/service/{service_name}/backups` — backup history per service for retention/RPO analysis (medium)
- [ ] `GET /project/{project}/service/{service_name}/integration` — service-to-service integration edges (metrics/log shipping topology) (medium)
- [ ] `GET /organization/{organization_id}/tickets` — support ticket volume per org/project (medium)
- [ ] `GET /project/{project}/alerts and /project/{project}/service/{service_name}/alerts` — open service alerts as an operational health table (low)
- [ ] `GET /organization/{organization_id}/emissions` — carbon emissions reporting per organization (low)

Note: Static schema list (no dynamic discovery). Coverage of the org/billing objects is decent; the gaps are the join/membership tables and the per-service operational objects.

## Algolia — gaps

Today (4): `indices`, `records`, `rules`, `synonyms`

Diffed against: <https://raw.githubusercontent.com/algolia/api-clients-automation/main/specs/bundled/analytics.yml>

- [ ] `GET /2/searches (Analytics API)` — top search terms with counts - the vendor's headline search metric (high)
- [ ] `GET /2/hits (Analytics API)` — top results per query with click and conversion counts, the record-level performance table (high)
- [ ] `GET /2/searches/noResults and /2/searches/noClicks` — zero-result and zero-click queries, the core relevance-debugging tables (high)
- [ ] `GET /2/abtests (A/B Testing API)` — A/B test definitions and per-variant results (high)
- [ ] `GET /2/conversions/conversionRate, /2/conversions/revenue, /2/conversions/addToCartRate, /2/conversions/purchaseRate` — conversion and revenue time series per index (high)
- [ ] `GET /2/clicks/clickThroughRate, /2/clicks/averageClickPosition, /2/clicks/positions` — click-through and click-position time series (medium)
- [ ] `GET /2/filters and /2/filters/{attribute}` — facet/filter usage breakdown dimension (medium)
- [ ] `GET /2/countries and /2/users/count` — geography breakdown and unique-user counts for search traffic (medium)
- [ ] `GET /1/runs and /1/runs/{runID}/events (Ingestion API)` — connector run history and per-run events for pipeline reliability reporting (medium)
- [ ] `GET /1/logs (Search API)` — raw API request log including query, timing and errors (medium)
- [ ] `GET /1/incidents, /1/latency/{clusters}, /1/indexing/{clusters} (Monitoring API)` — cluster latency, indexing time and incident history (low)
- [ ] `GET /1/logs/{indexName} (Query Suggestions API)` — query-suggestions build logs per index (low)

Note: Static schema list, no dynamic index discovery. Every synced table comes from the Search API (content objects only); the Analytics, A/B testing, Ingestion and Monitoring APIs are entirely absent, which is the part a warehouse user actually wants. Also diffed against the bundled abtesting.yml, insights.yml, monitoring.yml, ingestion.yml and search.yml specs in the same repo.

## Alguna — gaps

Today (8): `billable_metrics`, `customers`, `invoices`, `payments`, `plans`, `products`, `refunds`, `subscriptions`

Diffed against: <https://alguna.com/docs/api-reference/v2/specs/2026-04-01.json>

- [ ] `GET /subscriptions/{id}/versions (and /versions/current)` — subscription change history - the state-transition table behind MRR movement (high)
- [ ] `GET /credit-notes` — credit-note transactions that offset the invoices already synced (high)
- [ ] `GET /wallets and /wallets/{id}/balance` — prepaid wallet balances per customer (high)
- [ ] `GET /wallet-grants and /wallets/{id}/grants` — credit grant ledger - drawdown and expiry analysis (high)
- [ ] `GET /bundles` — product bundle lookup resolving bundle IDs carried on plans and subscription items (medium)
- [ ] `GET /customers/{id}/entitlements and /subscriptions/{id}/entitlements` — what each customer is currently entitled to, for feature-usage joins (medium)
- [ ] `GET /revenue-schedules (plus /customer/{id}, /subscription/{id}, /legal-entity/{id})` — revenue recognition schedule rows for rev-rec reporting (medium)
- [ ] `GET /subscriptions/{id}/revenue` — MRR/ARR/ACV per subscription - the vendor's headline metric (medium)
- [ ] `GET /customers/{id}/connected-accounts` — lookup mapping customers to payment-provider account IDs for joins to Stripe-style sources (medium)
- [ ] `GET /subscriptions/{id}/credits/balance` — monetary credit balance carried on each subscription (low)
- [ ] `GET /insights/revenue/over-time, /insights/revenue/by-customer, /insights/revenue/by-product` — prebuilt revenue breakdowns; mostly derivable from invoices but cheap to land (low)
- [ ] `GET /insights/customers and /insights/customers/over-time` — customer count/churn metrics as published by the vendor (low)

Note: Verified against the published OpenAPI spec linked from https://alguna.com/docs/llms.txt. Core billing objects are covered; the missing pieces are the credit/wallet ledger and subscription version history.

## AlphaVantage — **thin**

Today (9): `balance_sheet`, `cash_flow`, `company_overview`, `earnings`, `global_quote`, `income_statement`, `time_series_daily`, `time_series_monthly`, `time_series_weekly`

Diffed against: <https://www.alphavantage.co/documentation/>

- [ ] `LISTING_STATUS` — lookup table of every listed and delisted symbol with exchange, asset type and IPO/delisting dates - resolves the tickers already synced (high)
- [ ] `TIME_SERIES_DAILY_ADJUSTED` — split/dividend-adjusted closes, required for any correct return or backtest calculation (high)
- [ ] `DIVIDENDS` — corporate action history per symbol (high)
- [ ] `SPLITS` — split history needed to reconcile the unadjusted price series already synced (high)
- [ ] `NEWS_SENTIMENT` — news and sentiment feed - the vendor's headline alternative-data product (high)
- [ ] `EARNINGS_CALENDAR` — upcoming earnings dates to join against the earnings table already synced (medium)
- [ ] `INSIDER_TRANSACTIONS` — insider buy/sell transaction rows per symbol (medium)
- [ ] `INSTITUTIONAL_HOLDINGS` — institutional holder positions per symbol (medium)
- [ ] `SHARES_OUTSTANDING` — share count history, needed for per-share and market-cap metrics (medium)
- [ ] `EARNINGS_ESTIMATES` — analyst estimates to compare against reported earnings (medium)
- [ ] `ETF_PROFILE` — ETF holdings and sector breakdown, the ETF counterpart to company_overview (medium)
- [ ] `REAL_GDP, CPI, TREASURY_YIELD, FEDERAL_FUNDS_RATE, UNEMPLOYMENT` — macro indicator series commonly joined against equity data (medium)

Note: Single /query endpoint parameterized by `function=`; the docs page exposes ~140 anchored functions and PostHog surfaces 9. Beyond the listed gaps, TIME_SERIES_INTRADAY, TIME_SERIES_WEEKLY_ADJUSTED/MONTHLY_ADJUSTED, the FX and digital-currency series, the commodities family and ~60 technical indicators are also absent, though indicators are cheaply derivable in the warehouse.

## AmazonAds — **thin**

Today (3): `profiles`, `sp_ad_groups`, `sp_campaigns`

Diffed against: <https://d1y2lf8k3vrkfu.cloudfront.net/openapi/en-us/dest/SponsoredProducts_prod_3p.json>

- [ ] `POST /reporting/reports then GET /reporting/reports/{reportId}` — async reporting v3 - impressions, clicks, spend, sales, ACOS; without it none of the synced entities have any performance metrics (high)
- [ ] `POST /sp/productAds/list` — the ad (ASIN) level under the ad groups already synced (high)
- [ ] `POST /sp/keywords/list` — keyword-level bids and state, the main optimization object (high)
- [ ] `POST /sp/targets/list` — product and category targeting expressions with bids (high)
- [ ] `POST /portfolios/list` — lookup resolving the portfolioId carried on the campaigns already synced (high)
- [ ] `POST /sb/... campaigns, ad groups, ads and targets (AmazonAdsAPISBMerged_prod_3p.json)` — Sponsored Brands entities are entirely absent, so spend coverage is partial (high)
- [ ] `POST /sd/... campaigns, ad groups, product ads and targets (AmazonAdsAPISDMerged_prod_3p.json)` — Sponsored Display entities are entirely absent (high)
- [ ] `POST /sp/negativeKeywords/list and /sp/campaignNegativeKeywords/list` — negative keyword coverage, needed to explain traffic exclusions (medium)
- [ ] `POST /sp/negativeTargets/list and /sp/campaignNegativeTargets/list` — negative product/category targets alongside the positive targets (medium)
- [ ] `POST /history (Change History API)` — state-transition history of bids, budgets and status changes (medium)
- [ ] `POST /adsAccounts/list` — advertising account lookup above profiles, for multi-account rollups (medium)
- [ ] `GET /invoices and POST /invoiceSummaries/list (Advertising Billing API)` — billed spend reconciliation against reported spend (medium)

Note: Static schema list. The Amazon Ads docs site is a Redocly SPA; the real spec index is https://d3a0d0y2hgofx6.cloudfront.net/en-us/toc2.json, which links ~130 OpenAPI documents. I also read OfflineReport_prod_3p.json, Portfolios_prod_3p.json, AmazonAdsAPIExports_prod_3p.json, Changehistory_prod_3p.json, AdvertisingBilling_prod_3p.json and AdvertisingAccounts_prod_3p.json. Note the source code already flags reporting as a known follow-up. Nearly all list endpoints are POST /.../list rather than GET.

## Amplitude — gaps

Today (3): `annotations`, `cohorts`, `events`

Diffed against: <https://amplitude.com/docs/apis>

- [ ] `GET /api/2/taxonomy/event` — event type catalog - the lookup that names and describes the event stream already synced (high)
- [ ] `GET /api/2/taxonomy/event-property` — event property definitions and types, needed to interpret the events table (high)
- [ ] `GET /api/2/taxonomy/user-property` — user property catalog with types and descriptions (high)
- [ ] `GET /api/2/taxonomy/category` — event category lookup resolving the category IDs on event types (medium)
- [ ] `GET /api/2/taxonomy/group-property` — group property catalog for account-level analysis (medium)
- [ ] `GET /api/2/release` — release markers to join against event timestamps, the sibling of the annotations table already synced (medium)
- [ ] `GET /api/2/audit-logs/{ORG_ID}` — org-level change history for charts, cohorts and permissions (medium)
- [ ] `GET /api/3/chart/{chart_id}/query` — results of saved charts, so warehouse numbers match what teams see in Amplitude (medium)
- [ ] `GET /api/2/funnels` — funnel conversion results as Amplitude computes them (medium)
- [ ] `GET /api/2/retention` — retention curves as Amplitude computes them (medium)
- [ ] `GET /api/2/composition` — user composition breakdown by property value (low)
- [ ] `GET /api/2/revenue/ltv` — revenue LTV cohorts (low)

Note: Endpoint paths confirmed by reading https://amplitude.com/docs/apis/analytics/taxonomy, /dashboard-rest, /releases and /audit-logs. Raw events are already synced via the Export API, so the aggregate Dashboard REST endpoints are partly derivable in the warehouse - the Taxonomy lookup tables are the higher-value gap.

## Anthropic — gaps

Today (10): `api_keys`, `claude_code_analytics`, `claude_code_model_breakdown`, `cost_report`, `invites`, `service_accounts`, `usage_report`, `users`, `workspace_members`, `workspaces`

Diffed against: <https://platform.claude.com/llms.txt>

- [ ] `GET /v1/models` — model catalog - lookup resolving the model IDs already synced in usage_report, cost_report and claude_code_model_breakdown (high)
- [ ] `GET /v1/organizations/analytics/users (List User Activity)` — per-seat activity, the core seat-utilization table (high)
- [ ] `GET /v1/organizations/analytics/cost by user (Get Per-User Cost)` — cost attribution per user rather than only org-level cost_report (high)
- [ ] `GET /v1/organizations/analytics/usage by user (Get Per-User Token Usage)` — token usage per user, needed for chargeback and adoption analysis (high)
- [ ] `GET /v1/organizations/rbac_groups and .../rbac_groups/{id}/members` — group definitions plus the membership join for the users already synced (high)
- [ ] `GET /v1/organizations/rbac_roles and .../rbac_roles/{id}/permissions` — lookup resolving the role identifiers carried on users and workspace_members (medium)
- [ ] `GET /v1/organizations/analytics/summaries (Get Activity Summaries)` — rolled-up org activity as the vendor reports it (medium)
- [ ] `GET /v1/organizations/service_accounts/{id}/workspaces and /workspaces/{id}/service_accounts` — service-account-to-workspace membership join for the service_accounts already synced (medium)
- [ ] `GET /v1/organizations/analytics/connectors, /plugins, /skills` — adoption breakdown by connector, plugin and skill (medium)
- [ ] `GET /v1/messages/batches` — batch job history with request counts and status, for batch spend analysis (medium)
- [ ] `GET /v1/organizations/analytics/chat_projects and /analytics/artifacts` — Claude project and artifact usage breakdown (low)
- [ ] `GET /v1/organizations/me` — organization lookup row to anchor the org-scoped tables (low)

Note: Admin API coverage of the identity objects is good. The whole /v1/organizations/analytics/\* family (the newer per-seat Claude and Claude Code analytics) is missing except the two claude_code\_\* tables, and there is no model lookup for the model IDs already carried in usage_report/cost_report. The Compliance API (chats, projects, code artifacts, organization users) is a separate auth-gated surface for Enterprise plans and would need its own credential.

## ApifyDataset — **thin**

Today (1): `dataset_items`

Diffed against: <https://docs.apify.com/api/openapi.json>

- [ ] `GET /v2/actor-runs` — run history with status, duration and compute units - the operational and cost table for everything Apify does (high)
- [ ] `GET /v2/datasets` — dataset catalog lookup resolving the dataset IDs, item counts and owning actor for the items already synced (high)
- [ ] `GET /v2/actors` — actor lookup resolving the actId carried on runs and datasets (high)
- [ ] `GET /v2/users/me/usage/monthly` — monthly platform usage and spend breakdown (medium)
- [ ] `GET /v2/actor-tasks` — saved task definitions, the lookup between a schedule and the runs it produces (medium)
- [ ] `GET /v2/datasets/{datasetId}/statistics` — per-field statistics for the dataset being synced (medium)
- [ ] `GET /v2/actor-builds` — build history to correlate output changes with actor versions (low)
- [ ] `GET /v2/schedules and /v2/schedules/{scheduleId}/log` — schedule definitions and their invocation log (low)
- [ ] `GET /v2/request-queues and /v2/actor-runs/{runId}/request-queue/requests` — crawl request state per run for coverage and failure analysis (low)
- [ ] `GET /v2/key-value-stores/{storeId}/keys and /records` — non-dataset run outputs stored as key-value records (low)

Note: Deliberately scoped: the connector takes a single user-supplied dataset_id and syncs GET /v2/datasets/{id}/items into one user-named table, so it can cover any dataset but only one per configured source. It is not dynamic discovery - get_schemas returns the one configured endpoint. The rest of the Apify platform API (runs, actors, usage) is unreachable from this source, so the operational and cost side of Apify has no coverage at all.

## Apollo — gaps

Today (3): `accounts`, `contacts`, `opportunities`

Diffed against: <https://docs.apollo.io/reference/organization-search>

- [ ] `/opportunity_stages (list deal stages)` — lookup resolving the stage IDs already carried on the opportunities we sync (high)
- [ ] `/contact_stages` — lookup resolving contact_stage_id on synced contacts (high)
- [ ] `/account_stages` — lookup resolving account_stage_id on synced accounts (high)
- [ ] `/users/search` — lookup resolving owner/user IDs on accounts, contacts and deals (high)
- [ ] `/emailer_messages/search (outreach emails)` — per-message email send/open/reply activity, the core sequence funnel (high)
- [ ] `/phone_calls/search` — call activity records tied to contacts and accounts (high)
- [ ] `/emailer_campaigns/search (sequences)` — lookup resolving sequence IDs on email activity and contact status (medium)
- [ ] `/tasks/search` — rep task volume and completion analysis (medium)
- [ ] `/conversations/search` — conversation intelligence records joinable to calls (medium)
- [ ] `/labels (lists)` — lookup for list membership used to segment contacts and accounts (medium)
- [ ] `/notes` — note history attached to CRM records (medium)
- [ ] `/typed_custom_fields` — lookup naming the custom field IDs that appear on synced records (low)

Note: Reference index (96 slugs) read from the docs nav; each path below confirmed by re-fetching the individual reference page and reading its embedded "path" field. PostHog syncs only the three core CRM search endpoints; every lookup table and activity object is absent.

## Appdynamics — gaps

Today (6): `applications`, `business_transactions`, `health_rule_violations`, `metric_data`, `nodes`, `tiers`

Diffed against: <https://help.splunk.com/en/appdynamics-saas/extend-splunk-appdynamics/26.4.0/extend-splunk-appdynamics/splunk-appdynamics-apis>

- [ ] `/controller/rest/applications/{app}/events` — application event stream (deployments, restarts, errors, custom events) — the state-transition history behind every incident (high)
- [ ] `/controller/alerting/rest/v1/applications/{id}/health-rules` — lookup resolving the health rule IDs/names carried on the health_rule_violations we already sync (high)
- [ ] `/controller/rest/applications/{app}/request-snapshots` — individual slow/error transaction snapshots, the drill-down layer under business_transactions (high)
- [ ] `/controller/rest/applications/{app}/metrics (metric tree browse)` — lookup of available metric paths — without it metric_data has to be hand-configured (high)
- [ ] `/controller/rest/applications/{app}/backends` — lookup for remote services/databases referenced by tiers and business transactions (high)
- [ ] `/controller/anomaly/rest/api/v1/applications/{id}/anomalies` — anomaly-detection violations, the ML counterpart to health rule violations (medium)
- [ ] `/events/query (Analytics Events API, ADQL)` — transaction/log/browser analytics records not exposed by the controller REST API (medium)
- [ ] `/controller/rest/databases/servers` — database visibility inventory joinable to backends and tiers (medium)
- [ ] `/controller/rest/databases/servers/healthrule-violations` — database-side violations alongside the APM ones already synced (medium)
- [ ] `/controller/rest/applications/{app}/metric-data-v2` — v2 metric retrieval with richer rollup semantics than the v1 metric_data we sync (low)
- [ ] `/controller/ControllerAuditHistory` — who changed what in the controller, for correlating config changes to incidents (low)

Note: docs.appdynamics.com now serves an SPA shell and presents a broken TLS chain, so the canonical reference is the Splunk help portal; individual API pages (application-model, metric-and-snapshot, alert-and-respond/\*, anomaly-violation, analytics-events, database-visibility, rbac) were fetched and their /controller/... paths extracted.

## Appfigures — gaps

Today (4): `products`, `revenue_report`, `reviews`, `sales_report`

Diffed against: <https://docs.appfigures.com/api/reference/v2>

- [ ] `/ranks` — app store category rank history — the vendor's headline ASO metric (high)
- [ ] `/reports/subscriptions` — subscription metrics (new, renewals, churn) that sales/revenue reports do not break out (high)
- [ ] `/reports/ratings` — rating counts and averages over time, the current supported replacement for /ratings (high)
- [ ] `/data/stores, /data/categories, /data/countries` — lookup tables resolving the store, category and country codes on every synced report row (high)
- [ ] `/aso (keyword ranks and stats)` — tracked keyword positions, the other half of the ASO story with /ranks (high)
- [ ] `/reports/adspend` — campaign spend by network, needed for ROAS against revenue_report (medium)
- [ ] `/reports/ads` — ad publishing revenue by network, a revenue stream missing from sales_report (medium)
- [ ] `/reports/payments` — expected payouts, reconciles revenue to cash (medium)
- [ ] `/reports/usage` — in-app usage metrics (DAU, sessions, crashes) per product (medium)
- [ ] `/reports/estimates` — download/revenue estimates for competitor apps (medium)
- [ ] `/featured` — when and where apps were featured, a step-change driver for downloads (medium)
- [ ] `/events` — user-created timeline markers for annotating report series (low)

Note: The v2 reference index lists the complete resource set; each candidate below was opened and read. Note /ratings is deprecated in favour of /reports/ratings.

## Appfollow — gaps

Today (5): `app_collections`, `app_lists`, `ratings_history`, `reviews`, `users`

Diffed against: <https://docs.api.appfollow.io/reference/app_collections_list_api_v2_account_apps_get-1>

- [ ] `/api/v2/meta/rankings` — category ranking history — the headline ASO metric, complements ratings_history (high)
- [ ] `/api/v2/aso/keywords` — tracked keyword positions per app and country (high)
- [ ] `/api/v2/meta/versions` — app version release history; lookup resolving the version field on synced reviews (high)
- [ ] `/api/v2/reviews/stats` — aggregate review counts and sentiment without re-aggregating raw reviews (medium)
- [ ] `/api/v2/reviews/stats/version` — review breakdown by app version, the standard release-quality view (medium)
- [ ] `/api/v2/reviews/stats/ratings` — rating distribution over time (medium)
- [ ] `/api/v2/reviews/stats/replies, /reviews/stats/replies/count, /reviews/stats/replies/speed` — reply coverage and response-time SLA metrics for support teams (medium)
- [ ] `/api/v2/reports/aso` — packaged ASO report combining keywords, ranks and visibility (medium)
- [ ] `/api/v2/reviews/semantic` — semantic tags per review, the breakdown dimension for review analysis (medium)
- [ ] `/api/v2/charts/topcharts` — public top charts for competitive benchmarking (medium)
- [ ] `/api/v2/meta/ratings/console/gp` — Google Play Console ratings, more accurate than scraped store ratings (medium)
- [ ] `/api/v2/aso/featured` — App Store featuring events that drive install spikes (low)

Note: Full v2 endpoint list read from the docs nav (slugs encode the HTTP path). PostHog covers account management plus reviews and ratings history; the ASO and review-analytics halves of the product are unmapped.

## AppsFlyer — **thin**

Today (3): `daily_report`, `geo_report`, `partners_report`

Diffed against: <https://dev.appsflyer.com/hc/reference>

- [ ] `/api/raw-data/export/app/{app_id}/installs_report/v5` — install-level raw rows — the core AppsFlyer dataset for attribution modelling (high)
- [ ] `/api/raw-data/export/app/{app_id}/in_app_events_report/v5` — raw in-app event rows, needed to join revenue and funnel events to media source (high)
- [ ] `/api/master-agg-data/v4/app/{app_id} (Master API)` — single aggregated cross-app report with cohort KPIs, the vendor's recommended aggregate feed (high)
- [ ] `/api/raw-data/export/app/{app_id}/ad_revenue_raw/v5 (plus organic and retargeting variants)` — ad monetization revenue per user, missing entirely from the aggregate reports (high)
- [ ] `/api/raw-data/export/app/{app_id}/uninstall_events_report/v5` — uninstall events, required for retention and LTV net of churn (high)
- [ ] `/api/raw-data/export/app/{app_id}/organic_installs_report/v5 and organic_in_app_events_report/v5` — organic baseline without which paid lift cannot be computed (high)
- [ ] `/api/raw-data/export/app/{app_id}/installs_retarget/v5 and in_app_events_retarget/v5` — retargeting conversions, reported separately from UA and otherwise invisible (high)
- [ ] `/api/raw-data/export/app/{app_id}/blocked_installs_report/v5, blocked_in_app_events_report/v5, detection/v5` — Protect360 fraud rows explaining gaps between gross and attributed installs (medium)
- [ ] `SKAN aggregate performance report and SKAN raw postbacks (skan-agg-performance-report, skan-pull-cs)` — the only iOS 14+ attribution signal for a large share of traffic (medium)
- [ ] `/api/raw-data/export/app/{app_id}/postbacks/v5 (install, in-app-event and retargeting postbacks)` — partner postback delivery records for reconciling AppsFlyer against network dashboards (medium)
- [ ] `/api/raw-data/export/app/{app_id}/reinstalls/v5 and reinstalls_organic/v5` — reinstall/resurrection cohorts, a distinct lifecycle state from installs (medium)
- [ ] `/api/agg-data/export/app/{app_id}/geo_by_date_report/v5 and partners_by_date_report/v5` — daily time series of the geo and partner breakdowns we currently sync only as period totals (medium)

Note: PostHog exposes three aggregate Pull API v5 reports (daily, geo, partners). The entire raw-data pull API (install/event/uninstall level rows), ad revenue, retargeting, Protect360 fraud, SKAN and the cross-app Master API are absent — that is the bulk of what warehouse users pull from AppsFlyer. Reference index enumerated from the docs nav (~160 slugs).

## Appsignal — gaps

Today (5): `deploy_markers`, `error_samples`, `exception_incidents`, `performance_incidents`, `performance_samples`

Diffed against: <https://docs.appsignal.com/api/v2/overview>

- [ ] `organization { apps } (GraphQL app/site list)` — lookup resolving the app_id / site_id every other table is keyed by (high)
- [ ] `POST /api/v2/logs/lines` — log lines are only available here — GraphQL exposes no log field at all (high)
- [ ] `POST /api/v2/metrics/timeseries, /api/v2/metrics/list, /api/v2/metrics/names` — all custom and platform metric data plus the metric-name lookup; the GraphQL metrics API is deprecated (high)
- [ ] `POST /api/v2/tracing/traces and /api/v2/tracing/trace (spans)` — distributed trace and span data underlying the samples we already sync (high)
- [ ] `AnomalyIncident (GraphQL)` — anomaly/trigger incidents are a first-class incident type alongside exception and performance incidents we sync (high)
- [ ] `LogIncident (GraphQL)` — log-based incidents, the fourth incident type, otherwise invisible (medium)
- [ ] `POST /api/v2/deploys/stats` — throughput, mean and error_rate per revision — joins directly onto deploy_markers (medium)
- [ ] `POST /api/v2/tracing/actions and service-dependency/slow-event endpoints` — aggregated per-action performance and downstream dependency breakdown (medium)
- [ ] `POST /api/v2/kubernetes/nodes and /api/v2/kubernetes/pods` — node and pod resource metrics for correlating app incidents with infrastructure (medium)
- [ ] `uptime monitors (GraphQL)` — uptime check results, a separate monitoring signal from incidents (medium)
- [ ] `check-ins / cron (GraphQL)` — scheduled-job execution history — misses and late runs (medium)

Note: AppSignal split its API in two: GraphQL for models (apps, incidents, markers, dashboards, alerts, uptime monitors, check-ins) and a REST Public API V2 for bulk data (metrics, logs, traces, Kubernetes, deploy stats). PostHog currently uses only the legacy /api/{app_id}/\*.json endpoints plus GraphQL incidents, so the entire V2 surface is unmapped. Anomaly and log incident types confirmed from the GraphQL mutations page; V2 routes confirmed from the per-page docs.

## Appstack — adequate

Today (1): `events`

Diffed against: <https://docs.appstack.tech/api/export>

No material gaps found.

Note: Genuinely a one-endpoint API, not a thin implementation. The docs sitemap lists exactly one page under /api (the Exports API, GET https://api.appstack.tech/api/v1/export); everything else is SDK and integration documentation. PostHog's single `events` table maps to that endpoint, with offset paging and a timestamp window, so coverage is complete. No dynamic table discovery in the source.

## Argocd — gaps

Today (5): `applications`, `clusters`, `deployment_history`, `projects`, `repositories`

Diffed against: <https://raw.githubusercontent.com/argoproj/argo-cd/master/assets/swagger.json>

- [ ] `/api/v1/applications/{name}/events` — per-application Kubernetes event stream — the sync and health state-transition history behind each deployment (high)
- [ ] `/api/v1/applications/{name}/revisions/{revision}/metadata` — lookup resolving the revision SHAs in deployment_history to commit author, message and date (high)
- [ ] `/api/v1/applications/{applicationName}/managed-resources` — the resource inventory each app owns, with live vs target diff — the drift signal (high)
- [ ] `/api/v1/applications/{applicationName}/resource-tree` — live resource hierarchy and per-resource health, one level below application health (medium)
- [ ] `/api/v1/applicationsets` — lookup for the generator that produced each application in a templated setup (medium)
- [ ] `/api/v1/projects/{name}/events` — project-level change history, useful for attributing policy changes to sync behavior (medium)
- [ ] `/api/v1/applications/{name}/revisions/{revision}/chartdetails` — Helm chart version and metadata per deployed revision (low)
- [ ] `/api/v1/repositories/{repo}/refs` — branch/tag refs available per repo, for joining deployed revisions to source branches (low)

Note: Diffed against the upstream swagger spec (82 paths). PostHog's deployment_history is derived from status.history on the applications resource rather than a separate endpoint, so the revision-metadata lookup below is the natural companion. Most remaining unmapped paths are config/plumbing (certificates, gpgkeys, repocreds, notifications, session, settings, account tokens) and are excluded.

## Asana — gaps

Today (8): `custom_fields`, `projects`, `sections`, `tags`, `tasks`, `teams`, `users`, `workspaces`

Diffed against: <https://raw.githubusercontent.com/Asana/openapi/master/defs/asana_oas.yaml>

- [ ] `tasks/{task_gid}/stories` — task activity + comment stream, the only source of state-transition history (assignee/section/due-date changes) (high)
- [ ] `projects/{project_gid}/project_memberships` — who is on which project and in what role; joins users to projects we already sync (high)
- [ ] `goals (+ goals/{gid}/parentGoals)` — Asana's headline OKR object with progress/status, entirely absent today (high)
- [ ] `time_tracking_entries` — actual hours logged per task/user, the basis of any effort or capacity analysis (high)
- [ ] `projects/{project_gid}/custom_field_settings` — lookup mapping synced custom_fields to the projects/portfolios that use them (high)
- [ ] `status_updates` — project/goal/portfolio status history (color + narrative) over time (medium)
- [ ] `team_memberships` — user-to-team membership lookup joining synced users and teams (medium)
- [ ] `portfolios (+ portfolios/{gid}/items)` — program-level rollup grouping projects we already sync (medium)
- [ ] `tasks/{task_gid}/dependencies and /dependents` — task dependency graph for blocked-work and critical-path analysis (medium)
- [ ] `goal_relationships` — resolves goal hierarchy and which projects contribute to which goal (medium)
- [ ] `time_tracking_categories` — lookup resolving the category ID carried on time tracking entries (medium)
- [ ] `allocations` — resource allocation of users to projects over date ranges, for capacity reporting (low)

Note: Diffed against Asana's official OpenAPI spec (3 MB, ~120 GET paths). Also present but excluded as plumbing/low value: webhooks, attachments, jobs, organization_exports, typeahead, project/task templates, ooo_entries, audit_log_events. Note /events is a sync-token change feed rather than a table.

## Ashby — gaps

Today (16): `applications`, `archive_reasons`, `candidate_tags`, `candidates`, `custom_fields`, `departments`, `interview_schedules`, `interviews`, `job_postings`, `jobs`, `locations`, `offers`, `openings`, `projects`, `sources`, `users`

Diffed against: <https://developers.ashbyhq.com/reference/introduction>

- [ ] `applicationFeedback.list` — interview scorecards and ratings, the core quality signal for hiring analytics (high)
- [ ] `application.listHistory` — stage-transition history; without it you cannot compute time-in-stage or funnel conversion (high)
- [ ] `interviewStage.list` — lookup resolving the currentInterviewStage ID carried on every synced application (high)
- [ ] `interviewEvent.list` — actual scheduled interview occurrences with interviewers and times, distinct from the interview definitions we sync (high)
- [ ] `interviewStageGroup.list` — lookup grouping stages into funnel phases for stage-level reporting (medium)
- [ ] `applicationHiringTeamRole.list` — membership table linking users to applications by role (recruiter, hiring manager) (medium)
- [ ] `surveySubmission.list` — candidate survey responses (including DEI surveys) tied to applications (medium)
- [ ] `candidate.listNotes` — recruiter notes per candidate, commonly wanted alongside candidates (medium)
- [ ] `closeReason.list` — lookup resolving why openings/jobs were closed; pairs with the archiveReasons we already sync (medium)
- [ ] `application.listCriteriaEvaluations` — structured per-criterion scores behind feedback, for calibrated scoring analysis (medium)
- [ ] `takeHomeAssignment.list` — assignment issue/completion records, a stage most funnels drop out at (medium)
- [ ] `sourceTrackingLink.list` — resolves attribution links behind the sources table already synced (low)

Note: Ashby's readme.io OpenAPI JSON is not publicly downloadable (404), so the resource list was read from the full reference navigation on the introduction page, filtering on \*.list endpoints. Other list endpoints deliberately excluded as config: communicationTemplate, emailSender, sequenceTemplate, jobBoard, jobTemplate, brand, apiKey, webhook.

## Asknicely — gaps

Today (1): `responses`

Diffed against: <https://asknicely.asknice.ly/help/apidocs/responses>

- [ ] `GET /api/v1/stats` — daily historical time series (sent, delivered, opened, responded, promoters/passives/detractors, NPS, CSAT) - the vendor's headline metric, already tabular (high)
- [ ] `GET /api/v1/contacts/unsubscribed` — paginated opt-out list with unsubscribe timestamps; the suppression table for any send analysis (medium)
- [ ] `GET /api/v1/sentstats/{days}` — send-funnel counts for a rolling window, segmentable by custom property and question type (low)

Note: AskNicely's v1 API is genuinely small; the only other GETs are a single-contact lookup (/contact/get/{search}/{key}, not a list) and /getnps/{days} which returns one scalar derivable from responses. Source uses a static ENDPOINTS = ("responses",) tuple - no dynamic table discovery.

## AssemblyAI — adequate

Today (1): `transcripts`

Diffed against: <https://www.assemblyai.com/docs/llms.txt>

No material gaps found.

Note: The pre-recorded audio REST API has exactly one list endpoint (GET /v2/transcript). Everything else is per-transcript derived views of data already inside the transcript payload (sentences, paragraphs, subtitles, redacted audio, word search) - the transcript object itself already carries words, utterances, chapters, entities, sentiment_analysis_results and auto_highlights_result. Remaining APIs are streaming/voice-agent/LLM-gateway request endpoints and token minting, none of them queryable collections.

## Attentive — adequate

Today (8): `custom_attribute_set`, `email_message_link_click`, `email_opened`, `email_subscribed`, `email_unsubscribed`, `sms_message_link_click`, `sms_sent`, `sms_subscribed`

Diffed against: <https://docs.attentive.com/llms.txt>

No material gaps found.

Note: This is a webhook-ingestion source (the directory contains webhook_template.py), and the 8 tables map exactly 1:1 onto the 8 event types Attentive's createwebhook endpoint accepts: sms.subscribed, sms.sent, sms.message_link_click, email.subscribed, email.unsubscribed, email.message_link_click, email.opened, custom_attribute.set. Full coverage of the webhook surface. Attentive's REST/GraphQL APIs are almost entirely write/ingest (POST events, attributes, subscriptions, catalog uploads); the only GETs are single-user lookups by phone/email, webhook config, catalog upload status and /me - no analytical collections to backfill from, so historical data before webhook setup is simply unavailable from the vendor.

## Automox — gaps

Today (8): `devices`, `events`, `organizations`, `packages`, `policies`, `policy_runs`, `server_groups`, `users`

Diffed against: <https://console.automox.com/api/docs/specs/console-api.json>

- [ ] `GET /servers/{deviceID}/packages` — per-device installed/available/missing patch inventory - the core patch-compliance fact table; the synced packages table is org-level only (high)
- [ ] `GET /policystats` — per-policy compliance counts, the headline dashboard metric (high)
- [ ] `GET /orgs/{orgID}/remediations/action-sets/{actionSetID}/issues` — vulnerability findings per remediation action set; joins to devices for risk reporting (high)
- [ ] `GET /device-details/orgs/{orgUUID}/devices/{deviceUUID}/inventory` — hardware/software inventory detail per device beyond the base device record (medium)
- [ ] `GET /reports/needs-attention` — devices flagged as needing action, a ready-made operational breakdown (medium)
- [ ] `GET /reports/prepatch` — pre-patch report of pending patches per device before a run (medium)
- [ ] `GET /audit-service/v1/orgs/{orgUuid}/events` — console audit trail of who changed what, distinct from the device event stream already synced (medium)
- [ ] `GET /approvals` — patch approval decisions and their state, needed to explain why patches did or did not deploy (medium)
- [ ] `GET /cloud-worklets/executions` — worklet run history with outcomes; the automation equivalent of policy_runs (medium)
- [ ] `GET /orgs/{orgID}/remediations/action-sets` — lookup resolving the action-set IDs on remediation issues (low)
- [ ] `GET /accounts/{accountUUID}/rbac-roles` — role lookup resolving the rbac_role field on synced users (low)
- [ ] `GET /policy-windows/org/{orgUUID}/group/{groupUUID}/scheduled-windows` — maintenance windows per group, needed to interpret when policy runs could execute (low)

Note: Automox publishes six separate Scalar specs at /api/docs/specs/\*.json (console-api, server-groups, policy-report, audit-trail, webhooks, cloud-worklets-public); the gaps above span console-api, audit-trail and cloud-worklets-public. policy-report's /policy-history/\* endpoints are already covered by the synced policy_runs table.

## Autumn — adequate

Today (8): `Coupons`, `Customers`, `Entities`, `Events`, `FeatureGrants`, `Features`, `Invoices`, `Plans`

Diffed against: <https://docs.useautumn.com/llms.txt>

No material gaps found.

Note: Every list endpoint in the API reference is already synced: listCustomers, listEntities, listEvents, listFeatures, listInvoices, listPlans, and listRewards (which is the source of both the Coupons and FeatureGrants tables). Remaining endpoints are single-object gets, mutations (attach/track/check/balance ops), preview calculators, key minting, webhook payload docs, and the multi-tenant platform endpoints (list-orgs/list-users) that only apply to platform master orgs. aggregateEvents is a computed rollup over the Events table we already have.

## Aviationstack — gaps

Today (9): `aircraft_types`, `airlines`, `airplanes`, `airports`, `cities`, `countries`, `flights`, `routes`, `taxes`

Diffed against: <http://web.archive.org/web/20260411010945/https://aviationstack.com/documentation>

- [ ] `GET /v1/timetable` — live airport departure/arrival schedules with terminal, gate and delay status - the operational view flights alone does not give per-airport (high)
- [ ] `GET /v1/flightsFuture` — future scheduled flights by airport and date, needed for any forward-looking capacity or schedule analysis (medium)

Note: The live docs URL now 301s to docs.apilayer.com and lands in an auth-gated SwaggerHub login loop, so the endpoint list was read from a recent Wayback snapshot of the vendor's own documentation page and cross-checked against the api.aviationstack.com/v1/\* URLs embedded in it. The 9 synced tables cover every other documented endpoint (historical flights are the same /flights endpoint with flight_date). /v1/autocomplete is a typeahead helper, not a queryable collection. Both gap endpoints require an iata_code/airport parameter, so they would need a per-airport configuration rather than a plain full-table pull.

## Aviator — gaps

Today (5): `config_history`, `merge_queue_analytics`, `queue_stats`, `queued_pull_requests`, `repositories`

Diffed against: <https://docs.aviator.co/api/reference/json-api.md>

- [ ] `GET /api/v1/branches` — base branches with pause/active status - the lookup that resolves the base_branch carried on queued PRs and queue stats (high)
- [ ] `GET /api/v1/user_actions` — paginated action/audit history (actor, action, entity, target, timestamp) - the only transition history Aviator exposes (medium)
- [ ] `GET /api/v1/bot_pull_request` — the batch/draft PR Aviator creates in parallel mode, linking queued PRs to the batch that actually merged them (medium)
- [ ] `GET /api/v1/pull_request` — full per-PR merge state (status, blocked reason) for PRs not currently in the queued list (medium)
- [ ] `GET /api/releases/{project}/environments/{env}/deployments` — deployment history per environment from the Releases product - complements merge-queue data with what shipped (medium)
- [ ] `GET /api/v1/config` — current YAML config per repo; we sync config_history but not the current state it diffs against (low)

Note: Aviator also ships a GraphQL API for pull request data at https://app.aviator.co/graphql, but the schema is only introspectable behind auth so I could not enumerate it - it may expose richer PR/review objects than the JSON API. Runbooks and Releases have separate small REST references (docs.aviator.co/runbooks/api-reference.md, /releases-beta/api-reference.md); only the Releases deployments endpoint is a listable collection.

## Awin — gaps

Today (4): `accounts`, `programmes`, `reports_advertiser`, `transactions`

Diffed against: <https://help.awin.com/llms.txt>

- [ ] `GET publisher performance report (advertiser)` — per-publisher clicks/sales/commission breakdown - the headline advertiser metric and the counterpart to the advertiser report we already sync (high)
- [ ] `GET publishers information for advertiser` — lookup table resolving the publisherId on every transaction and performance row (high)
- [ ] `GET commission groups for an advertiser` — lookup resolving the commissionGroupId carried on transactions (high)
- [ ] `GET programme details for publisher` — commission ranges, currency and terms per programme; programmes table only carries the summary (high)
- [ ] `GET campaign performance report (publisher and advertiser)` — revenue and clicks broken down by campaign - a core reporting dimension we do not expose (medium)
- [ ] `GET creative performance report (publisher and advertiser)` — performance by creative/banner, the other main report dimension (medium)
- [ ] `GET transaction queries for a publisher` — dispute/query state on transactions - transition history for revenue we already sync (medium)
- [ ] `GET offers/promotions` — active vouchers and promotions per programme, joinable to transactions via voucher code (medium)
- [ ] `GET commission sharing rules for a publisher` — explains commission splits seen in transaction amounts (low)

Note: The wiki.awin.com URLs in the source config are dead - they now 302 to the awin.com marketing homepage. The live reference is help.awin.com/apidocs with a machine-readable index at help.awin.com/llms.txt; the doc URLs in the source should be updated.

## AzureDevOps — **thin**

Today (5): `builds`, `projects`, `pull_requests`, `repositories`, `work_item_revisions`

Diffed against: <https://github.com/MicrosoftDocs/vsts-rest-api-specs/tree/master/specification>

- [ ] `git Commits (GET /{project}/_apis/git/repositories/{repositoryId}/commits)` — commit history is the base fact table for any DORA or engineering-velocity analysis (high)
- [ ] `git Pull Request Threads + Thread Comments` — review discussion and timestamps - required for review latency and cycle time on the PRs we already sync (high)
- [ ] `git Pull Request Reviewers (and Pull Request Iteration Statuses)` — approval votes per reviewer; the membership table that turns pull_requests into review analytics (high)
- [ ] `core Teams (GET /_apis/teams, /projects/{projectId}/teams) and Team Members` — lookup resolving team ownership for projects, work items and boards (high)
- [ ] `build Definitions (GET /{project}/_apis/build/definitions)` — lookup resolving definition.id carried on every build row we already sync (high)
- [ ] `build Timeline (GET /{project}/_apis/build/builds/{buildId}/timeline/{timelineId})` — per-job/step records and durations - where build time actually goes (high)
- [ ] `release Releases + release Deployments` — deployment frequency and environment promotion history; entirely absent today (high)
- [ ] `testResults Runs + Resultsbybuild` — test pass/fail results per build - the standard quality metric alongside builds (high)
- [ ] `work Iterations (GET /{project}/{team}/_apis/work/teamsettings/iterations)` — sprint lookup resolving the iteration path on work item revisions (high)
- [ ] `wit Work Item Types + Work Item Type States (and Classification Nodes)` — lookup tables resolving type and state values on work_item_revisions, including state category (medium)
- [ ] `pipelines Pipelines + Runs (GET /{project}/_apis/pipelines, /{pipelineId}/runs)` — the current YAML pipelines model; builds alone misses pipeline-level run data (medium)
- [ ] `git Pull Request Work Items` — join table linking PRs to the work items they close - connects the two halves we already sync (medium)

Note: Azure DevOps is one of the largest APIs in this batch (47 spec areas in the official MicrosoftDocs/vsts-rest-api-specs repo); five tables is a small fraction. Diffed against the 7.1 specs for build, core, git, wit, work, release, pipelines, testResults, testPlan, policy, graph, audit and memberEntitlementManagement. Also notable but below the cut: policy Evaluations, git Pushes, graph Users/userentitlements, audit auditlog, testPlan Plans/Suites.

## Babelforce — gaps

Today (8): `agent_groups`, `agents`, `calls`, `conversations`, `numbers`, `queues`, `recordings`, `sms`

Diffed against: <https://apps.babelforce.com/developer-hub/manager/>

- [ ] `GET /api/v2/conversations/{conversationId}/events` — per-conversation event timeline - the transition history behind the conversations we already sync (high)
- [ ] `GET /api/v2/events` — workspace-wide event stream; the core analytical fact table for a contact-center source (high)
- [ ] `GET /api/v2/outbound/campaigns and /{id}/statistics` — outbound dialer campaigns plus their performance stats - a whole product area with no coverage (high)
- [ ] `GET /api/v2/outbound/lists and /{id}/leads` — dialer lists and the leads dialed, joinable to calls (medium)
- [ ] `GET /api/v2/calls/reporting/simple/{reportType}` — pre-aggregated call report dimensions the vendor exposes alongside the raw reporting feed (medium)
- [ ] `GET /api/v2/queues/{queueId}/selections` — queue-to-agent/group/tag routing membership - resolves which agents serve which queue (medium)
- [ ] `GET /api/v2/users and /api/v2/users/roles` — user and role lookup distinct from agents, resolving actor IDs on events and audit rows (medium)
- [ ] `GET /api/v2/phonebook` — contact directory resolving caller numbers on calls and sms (medium)
- [ ] `GET /api/v2/conferences` — conference sessions, a call type not represented in the calls table (medium)
- [ ] `GET /api/v2/outbound/metrics` — outbound dialer metrics for campaign performance reporting (medium)
- [ ] `GET /api/v2/audit/request` — API audit trail of who changed what (low)
- [ ] `GET /api/v2/logs` — platform logs for call-flow debugging (low)

Note: The developer hub serves a Swagger UI whose visible initializer points at the petstore default; the real spec (babelforce API 0.7.0, ~110 paths) is embedded in https://apps.babelforce.com/developer-hub/manager/swagger-ui-init.js. Excluded config surfaces: applications, routings, triggers, business-hours, calendars, prompts, integrations, settings, babeldesk dashboards/widgets, sessions.

## BambooHR — **thin**

Today (6): `employees`, `meta_fields`, `meta_lists`, `meta_users`, `time_off_requests`, `time_off_types`

Diffed against: <https://documentation.bamboohr.com/sitemap.xml>

- [ ] `GET employee table data / changed employee table data` — jobInfo, compensation and employmentStatus history tables - the state-transition history behind every HR metric (promotions, pay changes, terminations); today only current employee fields are synced (high)
- [ ] `GET time off policies + employee time off policies` — lookup resolving the policy behind time_off_requests and accrual rules (high)
- [ ] `GET time off balance` — current accrued balance per employee - the headline time-off metric, absent even though requests and types are synced (high)
- [ ] `GET timesheet entries / time tracking records` — hours worked, the core fact table for the whole time-tracking product (high)
- [ ] `GET applications, application details, job summaries, statuses (ATS)` — recruiting funnel - candidates, applications and stage; an entire product area with zero coverage (high)
- [ ] `GET company locations / list locations` — lookup resolving the location ID on employees (high)
- [ ] `GET who's out` — resolved out-of-office calendar, commonly wanted alongside time_off_requests (medium)
- [ ] `GET goals + goal comments` — performance goals and progress updates per employee (medium)
- [ ] `GET employee trainings + training types + training categories` — completion facts plus the lookup tables that name them (medium)
- [ ] `GET company benefits, employee benefits, benefit coverages, deduction types` — benefits enrollment and its lookup tables - a major HRIS reporting area (medium)
- [ ] `GET list datasets + get data from dataset (Workforce Analytics)` — the vendor's own analytics datasets, discoverable at sync time (medium)
- [ ] `GET list reports + get report by id / get company report` — saved company reports, the shape most BambooHR admins already think in (medium)

Note: documentation.bamboohr.com is a ReadMe site with no public OpenAPI download (the /reference slug in the source config 404s), but its sitemap enumerates all 312 reference pages, which is what I diffed against. Six tables against roughly 130 GET endpoints spanning employees, time off, time tracking, scheduling, benefits, goals, training, ATS, compensation benchmarks and reports. Also below the cut: employee dependents, scheduling shifts/schedules, compensation benchmarks, bank holidays, break policies.

## Baseten — gaps

Today (12): `chain_deployments`, `chains`, `deployments`, `instance_type_prices`, `instance_types`, `model_apis`, `model_environments`, `models`, `secrets`, `training_jobs`, `training_projects`, `users`

Diffed against: <https://docs.baseten.co/reference/management-api-spec.json>

- [ ] `GET /v1/billing/usage_summary` — dedicated serving, training and Model API spend by date range - the headline cost metric for a GPU-inference vendor (high)
- [ ] `GET /v1/models/{model_id}/deployments/{deployment_id}/metrics` — inference throughput, latency and replica metrics; deployments are synced but none of their performance data is (high)
- [ ] `GET /v1/audit_logs (plus /v1/models/{id}/audit_logs, /v1/chains/{id}/audit_logs)` — who deployed, promoted or deleted what and when - the deployment transition history (high)
- [ ] `GET /v1/teams` — lookup resolving the team that owns models, secrets and training projects in a multi-team workspace (high)
- [ ] `GET /v1/chains/{chain_id}/environments` — chain environments; model_environments is synced but the chain equivalent is missing, leaving chain_deployments unattributable to prod/staging (medium)
- [ ] `GET /v1/models/{model_id}/environments/{env_name}/metrics` — metrics aggregated across every deployment that served an environment, split at each promotion (medium)
- [ ] `GET /v1/training_projects/{id}/jobs/{job_id}/metrics` — training job metrics; training_jobs rows carry no loss/throughput data today (medium)
- [ ] `GET /v1/training_projects/{id}/jobs/{job_id}/checkpoints` — checkpoints produced per training job, the artifacts a job is judged by (medium)
- [ ] `GET /v1/loops/runs and /v1/loops/deployments` — training-loop runs and their deployments - a product area with no tables at all (medium)
- [ ] `GET /v1/library_listings (and /versions)` — the model library catalog that models can be forked from; lookup for source attribution (low)
- [ ] `GET /v1/training/capacity` — available training capacity, useful for queueing analysis alongside training_jobs (low)

Note: Coverage of the core object graph is good. Excluded as config/plumbing: /v1/api_keys, /v1/gateway/groups/{id}/api_keys, /v1/environment_groups (access control), /v1/blobs/credentials/\*, and the various activate/deactivate/promote/retry mutations. Log endpoints (deployment/environment/chainlet logs) were left out as unbounded text streams rather than tables.

## Beamer — adequate

Today (8): `feature_request_comments`, `feature_request_votes`, `feature_requests`, `nps`, `post_comments`, `post_reactions`, `posts`, `users`

Diffed against: <https://getbeamer-api.pages.dev/>

No material gaps found.

Note: Every listable collection in the Beamer v0 API is already synced: posts, post comments, post reactions, feature requests, feature request comments, feature request votes, NPS responses and analytics users. The remaining operations are counts (count posts/comments/votes/reactions/NPS), the feed URL helper, unread-post lookups, NPS prompt eligibility and email-survey sends, and mutation-only team management (invite/remove/update role) - there is no GET for team members and no categories endpoint, so Category only exists as an inline field on Post. Caveat on the doc URL: the vendor's own page (getbeamer.com/help/beamer-api-documentation) now 404s and redirects into help.userflow.com after the Userflow merger; getbeamer-api.pages.dev is the working rendered Swagger reference for api.getbeamer.com/v0 and is what I diffed against.

## Bettermode — **thin**

Today (6): `members`, `moderation_items`, `posts`, `replies`, `spaces`, `tags`

Diffed against: <https://api.bettermode.com/ (live GraphQL introspection of queryType fields; 159 root queries)>

- [ ] `spaceMembers` — join table linking members to spaces; without it space membership is unqueryable (high)
- [ ] `postTypes / spacePostTypes` — lookup resolving the postTypeId carried on every post we already sync (high)
- [ ] `collections` — lookup that groups the spaces we already sync (high)
- [ ] `roles` — lookup resolving roleId on members and space members (high)
- [ ] `events` — community events are a first-class content object alongside posts (high)
- [ ] `eventRegistrations / memberEventRegistrations` — attendance and RSVP records, the core event engagement metric (high)
- [ ] `activityLogs` — network-wide activity event stream for behavioral analysis (high)
- [ ] `postReactionParticipants` — per-reaction engagement records tied to posts we sync (medium)
- [ ] `tagPosts` — post-to-tag join; we sync both tags and posts but not the link (medium)
- [ ] `analytics` — vendor's aggregated community analytics reports (medium)
- [ ] `chats / messages / chatParticipants` — direct messaging is an entire engagement channel currently missing (medium)
- [ ] `memberInvitations` — invitation funnel data explaining member acquisition (medium)

## BetterStack — gaps

Today (8): `escalation_policies`, `heartbeat_groups`, `heartbeats`, `incidents`, `monitor_groups`, `monitors`, `on_calls`, `status_pages`

Diffed against: <https://betterstack.com/docs/uptime/api/getting-started-with-uptime-api/>

- [ ] `GET monitor availability summary (/api/v2/monitors/{id}/sla)` — uptime percentage and total downtime per monitor - the product's headline metric, and not derivable from the monitors table (high)
- [ ] `GET monitor response times (/api/v2/monitors/{id}/response-times)` — latency time series per monitor and region; the other core performance metric (high)
- [ ] `GET /api/v2/team-members (and /api/v2/roles)` — lookup resolving the user IDs referenced by incidents, on-call calendars and escalation policies (high)
- [ ] `GET incident comments (/api/v2/incidents/{id}/comments)` — acknowledgement and resolution commentary - the timeline behind incident MTTA/MTTR (high)
- [ ] `GET on-call calendar events and rotation` — who was actually on call and when; on_calls only carries the calendar definitions (high)
- [ ] `GET heartbeat availability summary` — the heartbeat equivalent of the monitor SLA summary (medium)
- [ ] `GET severities and severity groups (/api/v2/severities)` — call-routing severity lookup resolving the severity referenced on incidents (medium)
- [ ] `GET status page resources (/api/v2/status-pages/{id}/resources)` — join table mapping status pages to the monitors and heartbeats they display (medium)
- [ ] `GET status page reports and report status updates` — published incident reports and their update history - the customer-facing incident record (medium)
- [ ] `GET status page subscribers (/api/v2/status-pages/{id}/subscribers)` — audience reach per status page (medium)
- [ ] `GET metadata records (/api/v3/metadata)` — the catalog/metadata store used to attach ownership and context to monitors and incidents (medium)
- [ ] `GET escalation policy groups and status page groups/sections` — grouping lookups for the policies and status pages already synced (low)

Note: The docs are HTML-only with no downloadable OpenAPI; I enumerated the API reference nav across several fetched pages under /docs/uptime/api/. Excluded: the Reporting page, which is an outbound incident log drain (webhook payload schema), not a queryable resource, and the New Relic integrations endpoint (integration config).

## BigMailer — gaps

Today (13): `brands`, `bulk_campaigns`, `contacts`, `fields`, `lists`, `message_types`, `rss_campaigns`, `segments`, `senders`, `suppression_lists`, `templates`, `transactional_campaigns`, `users`

Diffed against: <https://docs.bigmailer.io/reference/listbrands (readme reference nav enumerating all 96 reference pages)>

- [ ] `listrssupdatecampaigns (/v1/brands/{brandId}/rss-update-campaigns)` — the individual sends generated by an RSS campaign; the parent rss_campaigns row alone hides per-send history (medium)
- [ ] `listbrandproperties (/v1/brands/{brandId}/brand-properties)` — lookup for brand-level custom attributes referenced across campaigns (medium)
- [ ] `listtestcampaigns (/v1/brands/{brandId}/test-campaigns)` — test sends complete the campaign inventory (low)

Note: BigMailer's public API exposes no per-recipient engagement or event endpoints (opens, clicks, bounces, deliveries) — only campaign objects. So email performance metrics are simply not fetchable, which is why coverage looks complete but shallow. 'connections' was excluded as integration plumbing.

## Bitbucket — gaps

Today (6): `commits`, `deployments`, `pipelines`, `pull_requests`, `repositories`, `workspace_members`

Diffed against: <https://api.bitbucket.org/swagger.json>

- [ ] `repositories/{workspace}/{repo}/pullrequests/{id}/activity` — approval, review and update transition history — the backbone of PR cycle-time analysis (high)
- [ ] `repositories/{workspace}/{repo}/pullrequests/{id}/comments` — code review comment volume and latency (high)
- [ ] `repositories/{workspace}/{repo}/environments` — lookup resolving the environment referenced by the deployments we already sync (high)
- [ ] `workspaces/{workspace}/projects` — lookup grouping the repositories we already sync under a project key (high)
- [ ] `repositories/{workspace}/{repo}/pipelines/{uuid}/steps` — per-step CI durations and outcomes; the pipelines row alone gives no breakdown (high)
- [ ] `repositories/{workspace}/{repo}/issues` — repo issue tracker records (medium)
- [ ] `repositories/{workspace}/{repo}/commit/{commit}/statuses` — external build/check status per commit we already sync (medium)
- [ ] `repositories/{workspace}/{repo}/refs/branches` — branch lookup resolving branch names on PRs, pipelines and deployments (medium)
- [ ] `repositories/{workspace}/{repo}/pullrequests/{id}/commits` — PR-to-commit join enabling change-size metrics (medium)
- [ ] `repositories/{workspace}/{repo}/pipelines/{uuid}/steps/{uuid}/test_reports/test_cases` — per-test-case CI results for flakiness analysis (medium)
- [ ] `repositories/{workspace}/{repo}/issues/{id}/comments` — issue discussion volume (medium)
- [ ] `repositories/{workspace}/{repo}/issues/{id}/changes` — issue state transition history (low)

## Bitrise — gaps

Today (4): `apps`, `artifacts`, `builds`, `workflows`

Diffed against: <https://api-docs.bitrise.io/docs/swagger.json>

- [ ] `/apps/{app-slug}/pipelines (and /pipelines)` — pipeline runs are Bitrise's modern CI execution unit; we sync builds and workflows but not pipeline executions (high)
- [ ] `/organizations/{org-slug}/members` — org membership records for attributing builds to people (medium)
- [ ] `/organizations` — lookup resolving the org that owns each app we already sync (medium)
- [ ] `/apps/{app-slug}/branches` — branch lookup for grouping build history (medium)
- [ ] `/apps/{app-slug}/archived-builds` — extends build history past the live builds window (medium)
- [ ] `/apps/{app-slug}/build-requests` — queued/pending build requests reveal CI backlog (low)
- [ ] `/me/activities` — account-level activity event feed (low)
- [ ] `/available-stacks` — lookup for the stack identifier carried on builds (low)

## BlandAI — **thin**

Today (3): `call_transcripts`, `calls`, `pathways`

Diffed against: <https://docs.bland.ai/llms.txt>

- [ ] `GET /v1/sms/conversations (and /v1/sms/conversations/{id})` — the entire SMS channel is missing; conversations and their messages sit alongside calls (high)
- [ ] `GET /v1/inbound` — phone number lookup resolving the numbers on every call row (high)
- [ ] `GET /v1/personas` — lookup resolving the persona that handled a call (high)
- [ ] `GET /v1/calls/{id}/event-stream` — per-call event timeline (node transitions, tool calls) — finer grained than the transcript (medium)
- [ ] `GET /v1/agents` — web agent lookup, the non-phone counterpart to pathways (medium)
- [ ] `GET /v1/pathway_versions` — pathway version history so a call can be attributed to the version that served it (medium)
- [ ] `GET /v1/voices` — lookup resolving voice IDs referenced by calls (medium)
- [ ] `GET /v1/evals/runs and /v1/evals/runs/{id}/call-results` — per-call eval scores, the quality metric for voice agents (medium)
- [ ] `GET /v1/agent-testing/runs (and /agent-testing/scenarios)` — regression test outcomes per pathway over time (medium)
- [ ] `GET /v1/widget/{id}/threads` — web widget conversation threads, another engagement channel (medium)
- [ ] `GET /v1/audit-logs` — account change history for compliance reporting (low)
- [ ] `GET /v1/knowledge` — knowledge base inventory referenced by pathways (low)

Note: Source directory has no dynamic table discovery — bland_ai.py exposes the three static tables only. Bland's API is very large (200+ documented operations), so 3 tables is a genuinely small fraction.

## Blogger — gaps

Today (4): `blogs`, `comments`, `pages`, `posts`

Diffed against: <https://blogger.googleapis.com/$discovery/rest?version=v3>

- [ ] `pageViews (v3/blogs/{blogId}/pageviews)` — blog page view counts — the only traffic metric the API exposes and the headline number for a blog (high)

Note: Discovery doc lists only 8 resources; blogs, posts, pages and comments are all covered. The remaining resources (postUserInfos, blogUserInfos, users) are per-user permission views rather than analytical collections, so coverage is essentially complete.

## Bluetally — gaps

Today (16): `accessories`, `assets`, `audits`, `categories`, `components`, `consumables`, `departments`, `depreciations`, `employees`, `licenses`, `locations`, `maintenances`, `manufacturers`, `products`, `statuses`, `suppliers`

Diffed against: <https://developer.bluetally.com/reference/list-assets (readme reference nav enumerating every list/get endpoint)>

- [ ] `list-activity (/activity)` — check-in/check-out and field-change history for assets — the state transition log behind every asset we already sync (high)
- [ ] `list-tenants-for-multi-tenant-users (/tenants)` — tenant lookup for multi-tenant accounts, needed to scope every other table (low)

Note: Coverage is otherwise complete — every list-\* endpoint in the reference maps to an existing table. The remaining operations are POST check-in/check-out actions, which are not queryable collections.

## BoldSign — gaps

Today (7): `brands`, `contacts`, `documents`, `sender_identities`, `teams`, `templates`, `users`

Diffed against: <https://api.boldsign.com/swagger/v1/swagger.json>

- [ ] `GET /v1/contactGroups/list` — lookup resolving the contact group IDs carried on the contacts we already sync (high)
- [ ] `GET /v1/customField/list` — brand-scoped custom field definitions that resolve field IDs appearing on documents and templates (medium)
- [ ] `GET /v1/document/teamlist` — documents across the whole team, broader than the API user's own document list (medium)
- [ ] `GET /v1/document/behalfList` — documents sent on behalf of others, otherwise invisible in the documents table (low)

Note: Remaining GETs are file downloads (document/template/audit-log PDFs), single-object detail lookups, or billing credit counts — none are queryable collections. /v1/plan/apiCreditsCount was excluded as billing config.

## Braintree — gaps

Today (3): `disputes`, `refunds`, `transactions`

Diffed against: <https://graphql.braintreepayments.com/reference/>

- [ ] `search.customers / Query.customers (CustomerConnection)` — lookup table resolving the customer behind every synced transaction and refund (high)
- [ ] `Query.recurringBillingSubscriptions` — recurring revenue / subscription state, unavailable from one-off transactions (high)
- [ ] `Query.report.transactionLevelFees (TransactionLevelFeeReport)` — per-transaction processing fees — the net-revenue side of transactions we already sync (high)
- [ ] `Merchant.merchantAccounts (MerchantAccountConnection)` — lookup resolving the merchantAccountId carried on every transaction (high)
- [ ] `Query.recurringBillingSubscriptionPlans` — lookup resolving the plan a subscription references (high)
- [ ] `Query.verifications (VerificationConnection)` — payment method verification attempts and decline reasons (medium)
- [ ] `search.payments (PaymentConnection)` — superset of all payment types, including ones never surfacing as card transactions (medium)
- [ ] `Query.report.paymentLevelFees (PaymentLevelFeeReport)` — fee breakdown for non-transaction payment types (medium)
- [ ] `Transaction.statusHistory / status event fields` — state transition timeline (authorized → settled → settlement declined); only the current status is synced today (medium)
- [ ] `Query.recurringBillingSubscriptionPlanAddOns and ...PlanDiscounts` — lookups for add-on and discount lines priced into subscriptions (low)

Note: Source uses the Braintree GraphQL API (payments.braintree-api.com/graphql) with a `search` root; I parsed the Search and Query root types out of the full schema reference HTML. Search exposes transactions, refunds, payments, disputes, verifications, customers, businessAccountCreationRequests, inStoreReaders, inStoreLocations, roles, recurringBillingSubscriptions; Query additionally exposes report (transactionLevelFees, paymentLevelFees) and the plan lookups. Field selections in settings.py are also deliberately narrow, so some gaps are extra fields on already-synced nodes rather than new tables.

## Braze — gaps

Today (6): `campaigns`, `canvases`, `content_blocks`, `email_templates`, `events`, `segments`

Diffed against: <https://www.braze.com/docs/sitemap.xml>

- [ ] `/campaigns/data_series` — per-campaign per-day sends, opens, clicks, conversions — Braze's headline metric (high)
- [ ] `/canvas/data_series` — per-canvas per-step time series; the canvases table is unusable analytically without it (high)
- [ ] `/events/data_series` — custom event occurrence time series for the event names already synced (high)
- [ ] `/kpi/dau/data_series, /kpi/mau/data_series, /kpi/new_users/data_series, /kpi/uninstalls/data_series` — workspace-level DAU/MAU/new users/uninstalls trends (high)
- [ ] `/segments/data_series` — segment size over time, the only way to trend audience growth (high)
- [ ] `/campaigns/details` — enriches the campaign list with message variants, channels, tags and conversion behaviors (high)
- [ ] `/canvas/details` — canvas step and variant structure needed to attribute canvas analytics (high)
- [ ] `/sends/data_series` — per-send_id analytics for API-triggered campaign sends (medium)
- [ ] `/purchases/revenue_series, /purchases/quantity_series, /purchases/product_list` — revenue and purchase counts, plus the product lookup that resolves product ids (medium)
- [ ] `/sessions/data_series` — app session counts by app and date (medium)
- [ ] `/email/unsubscribes and /email/hard_bounces` — deliverability events joinable to campaigns (medium)
- [ ] `/catalogs and /catalogs/{catalog_name}/items` — lookup tables resolving catalog item ids referenced in personalization and purchases (medium)

Note: Braze has no OpenAPI/llms.txt (llms.txt 404s), so I enumerated every /docs/api/endpoints/\* page from the docs sitemap and then opened the individual pages to read the literal REST paths (confirmed /campaigns/data_series, /canvas/data_series, /segments/data_series, /events/data_series, /sends/data_series, /kpi/dau/data_series, /sessions/data_series, /purchases/revenue_series, /email/unsubscribes, /canvas/details, /catalogs, /custom_attributes). Today the connector syncs only the six `list` endpoints — every analytics (`data\_series`) endpoint, which is what Braze users actually report on, is missing.

## Breezometer — adequate

Today (4): `air_quality_current`, `air_quality_forecast`, `air_quality_history`, `pollen_forecast`

Diffed against: <https://airquality.googleapis.com/$discovery/rest?version=v1>

No material gaps found.

Note: BreezoMeter is now Google Maps Platform: the connector calls airquality.googleapis.com and pollen.googleapis.com, not the legacy api.breezometer.com host. I pulled both official discovery documents. Air Quality v1 exposes currentConditions.lookup, history.lookup, forecast.lookup and mapTypes.heatmapTiles.lookupHeatmapTile; Pollen v1 exposes forecast.lookup and mapTypes.heatmapTiles.lookupHeatmapTile. All four JSON lookup methods are already synced; the only remaining methods return PNG heatmap tiles, which are not warehouse-shaped. Coverage is complete.

## Brex — gaps

Today (8): `budgets`, `card_transactions`, `cash_transactions`, `departments`, `expenses`, `locations`, `users`, `vendors`

Diffed against: <https://developer.brex.com/llms.txt>

- [ ] `GET /v2/cards (Team API)` — lookup resolving the card id carried on card transactions and expenses (high)
- [ ] `GET /v2/accounts/card and GET /v2/accounts/cash (Transactions API)` — lookup resolving the account ids on both transaction tables; cash accounts are already fetched internally but not exposed (high)
- [ ] `GET /v1/transfers (Payments API)` — outbound bill-pay/ACH/wire transactions, entirely absent from card and cash transactions (high)
- [ ] `GET /v2/spend_limits (Budgets API v2)` — the limit objects budgets and cards are governed by; budgets alone do not show spend controls (high)
- [ ] `GET /v3/accounting/records (Accounting API)` — the accounting ledger export — how finance teams reconcile Brex spend to the GL (high)
- [ ] `GET /v1/fields and GET /v1/fields/{field_id}/values (Fields API)` — lookup resolving the custom field ids/values tagged on expenses and transactions (medium)
- [ ] `GET /v2/titles (Team API)` — lookup resolving the title id on users, alongside the departments and locations already synced (medium)
- [ ] `GET /v1/budget_programs (Budgets API)` — lookup grouping the budgets already synced into programs (medium)
- [ ] `GET /v1/trips and GET /v1/trips/{trip_id}/bookings (Travel API)` — travel spend and per-booking line items, not derivable from card transactions (medium)
- [ ] `GET /v2/accounts/card/primary/statements and GET /v2/accounts/cash/{id}/statements` — period-end statement balances for reconciliation against transactions (medium)
- [ ] `GET /v1/linked_accounts (Payments API)` — lookup resolving the external bank accounts transfers move money to and from (medium)
- [ ] `GET /v2/legal_entities (Team API)` — lookup for multi-entity companies, needed to split spend by entity (low)

Note: developer.brex.com serves an SPA (the openapi.json URLs return HTML), but the llms.txt index plus the per-API markdown mirrors (e.g. https://developer.brex.com/openapi/team\_api.md) list every operation with its literal path. Brex ships nine APIs — Accounting, Budgets, Expenses, Fields, Onboarding, Payments, Team, Transactions, Travel — and the connector covers pieces of only four. Note the connector already calls /v2/accounts/cash internally to fan out cash transactions but never exposes it as a table.

## Browserbase — **thin**

Today (2): `projects`, `sessions`

Diffed against: <https://docs.browserbase.com/reference/api/openapi.v1.yaml>

- [ ] `GET /v1/projects/{id}/usage` — browser minutes and proxy bytes per project — the vendor's headline consumption metric and the basis for cost analysis (high)
- [ ] `GET /v1/sessions/{id}/logs` — per-session request/action log lines; the event-grain data behind every session (high)
- [ ] `GET /v1/agents/runs` — agent run outcomes, status and duration — the core analytical object of the agent platform (high)
- [ ] `GET /v1/agents` — lookup resolving the agentId referenced by every run (high)
- [ ] `GET /v1/agents/runs/{runId}/messages` — per-run message transcript, the step-level detail under a run (medium)
- [ ] `GET /v1/contexts` — lookup resolving the contextId (persistent browser profile) attached to sessions (medium)
- [ ] `GET /v1/functions and GET /v1/functions/versions/{id}/invocations` — deployed function inventory plus per-invocation records for reliability and cost analysis (medium)
- [ ] `GET /v1/downloads` — artifacts produced by sessions, joinable to the session table (medium)
- [ ] `GET /v1/sessions/{id}/replays and /v1/sessions/{id}/recording` — per-page replay metadata and timings for a session (low)
- [ ] `GET /v1/functions/builds and /v1/functions/builds/{id}/logs` — build history and failure diagnostics for deployed functions (low)
- [ ] `GET /v1/sessions/{id}/uploads` — files pushed into a session, completing the session artifact picture (low)

Note: Fetched the official OpenAPI v1 spec (124KB, 38 paths). The connector exposes only /v1/projects and /v1/sessions — two of roughly a dozen queryable resources. Browserbase has since expanded well beyond sessions into agents/runs and functions/invocations, none of which are represented.

## BrowserUse — adequate

Today (5): `browser_sessions`, `profiles`, `session_messages`, `sessions`, `workspaces`

Diffed against: <https://docs.browser-use.com/cloud/openapi/v3.json>

No material gaps found.

Note: Fetched the v3 OpenAPI spec (linked from docs.browser-use.com/llms.txt); the connector already targets api.browser-use.com/api/v3, so it is on the current API, not legacy v2. The spec's GET collections are: /sessions, /sessions/{id}/messages, /browsers, /browsers/{id}/downloads, /profiles, /workspaces, /workspaces/{id}/files, /boxes/\* and /billing/account. All five substantive collections are synced. What remains is per-session download listings and per-workspace file listings (file plumbing), the Boxes cloud-desktop control plane (no list endpoint — only GET /boxes/me plus action routes), and billing account settings. Nothing warehouse-shaped is missing.

## Bugherd — gaps

Today (4): `Organization`, `Projects`, `Tasks`, `Users`

Diffed against: <https://docs.bugherd.com/api/openapi.yaml>

- [ ] `GET /api_v2/projects/{project_id}/tasks/{task_id}/comments.json` — task discussion thread — the main activity signal on a bug, and the only per-task event grain available (high)
- [ ] `GET /api_v2/projects/{project_id}/columns.json` — lookup resolving the board column/status a task sits in (high)
- [ ] `GET /api_v2/projects/{project_id}/tasks/archive.json` — archived (closed-out) tasks live behind a separate endpoint, so completed work is entirely missing from the tasks table (high)
- [ ] `GET /api_v2/projects/{project_id}/tasks/feedback.json` — the unsorted feedback inbox — tasks not yet promoted to the board (medium)
- [ ] `GET /api_v2/projects/{project_id}/tasks/{task_id}/attachments.json` — screenshots and files attached to a task, joinable to tasks (medium)
- [ ] `GET /api_v2/users/{user_id}/projects.json` — membership join between users and projects; neither existing table carries the relationship (medium)
- [ ] `GET /api_v2/users/members.json and GET /api_v2/users/guests.json` — splits the flat users list into members vs guests, which is how BugHerd seats are licensed (medium)
- [ ] `GET /api_v2/projects/active.json` — distinguishes active from archived projects without inspecting each project (low)

Note: docs.bugherd.com/api is a Scalar shell; the real spec is at /api/openapi.yaml (70KB, 27 paths). Note that the connector's Tasks stream hits /api_v2/projects/{id}/tasks.json, which is a separate endpoint from the archived and feedback task lists — archived tasks are therefore not synced at all, not merely filtered.

## Bugsnag — gaps

Today (11): `collaborators`, `errors`, `event_fields`, `events`, `organizations`, `pivots`, `projects`, `releases`, `saved_searches`, `teams`, `trace_fields`

Diffed against: <https://bugsnagapiv2.docs.apiary.io/api-description-document>

- [ ] `GET /projects/{project_id}/stability_trend` — crash-free sessions and users over time — BugSnag's headline stability metric (high)
- [ ] `GET /projects/{project_id}/release_groups` — lookup grouping the releases already synced (e.g. by app version), plus their stability rollups (high)
- [ ] `GET /projects/{project_id}/trend and GET /projects/{project_id}/errors/{error_id}/trend` — bucketed error occurrence time series at project and error grain (high)
- [ ] `GET /projects/{project_id}/pivots/{event_field_display_id}/values and /errors/{error_id}/pivots/{display_id}/values` — the actual breakdown values behind the pivots table already synced; pivots alone list only dimension names (high)
- [ ] `GET /projects/{project_id}/span_groups` — performance monitoring aggregates — an entire product surface with no coverage today (medium)
- [ ] `GET /projects/{project_id}/span_groups/{id}/spans and /projects/{project_id}/traces/{trace_id}/spans` — individual span records, the event grain under span groups (trace_fields is already synced but has nothing to describe) (medium)
- [ ] `GET /projects/{project_id}/page_load_span_groups` — web vitals / page load performance breakdown (medium)
- [ ] `GET /organizations/{organization_id}/teams/{id}/collaborators` — membership join between the teams and collaborators tables already synced (medium)
- [ ] `GET /organizations/{organization_id}/collaborators/{collaborator_id}/project_accesses` — which projects each collaborator can access — needed to attribute errors to owners (medium)
- [ ] `GET /projects/{project_id}/errors/{error_id}/events` — events scoped to a specific error, cheaper and more targeted than the project-wide events stream (low)
- [ ] `GET /projects/{project_id}/span_groups/{id}/timeline and /distribution` — latency distribution and timeline breakdown for a span group (low)
- [ ] `GET /saved_searches/{id}/usage_summary` — usage stats for the saved searches already synced (low)

Note: Pulled the raw API Blueprint (384KB) behind the Apiary docs. It self-declares as no longer maintained, pointing to https://developer.smartbear.com/bugsnag/docs/getting-started, but the documented paths still match the api.bugsnag.com routes the connector uses. Coverage of the errors/events core is good; the gaps are the aggregate/trend endpoints and the whole performance (spans) side of the product.

## BuildBetter — gaps

Today (4): `companies`, `extractions`, `interviews`, `persons`

Diffed against: <https://docs.buildbetter.ai/pages/api/data-access.md>

- [ ] `document` — Documents are named as one of the three core data models alongside calls and signals, and are the AI-generated output most teams want to analyze (high)
- [ ] `interview.attendees (attendee/person join)` — membership table linking interviews we already sync to persons we already sync — currently no way to join calls to participants (high)
- [ ] `interview.sentences / transcript_segments (REST /recordings/{id}/transcript)` — sentence-level transcript rows with speaker and timing; the raw text behind every call (high)
- [ ] `extraction.topics (topic)` — lookup table resolving the topic IDs attached to extractions we already sync (high)
- [ ] `extraction.types / interview.type (call and signal type)` — lookup tables resolving the type IDs carried on interviews and extractions (high)
- [ ] `tag (interview tags)` — lookup for the tag references on calls, needed for any segmentation by tag (medium)
- [ ] `recordings` — REST recording resource with public UUID, duration, source, and transcript_status — the supported successor to the interview asset fields (medium)

Note: PostHog's registered api_docs_url (https://docs.buildbetter.app/) no longer resolves — DNS fails. The live docs are at https://docs.buildbetter.ai (llms.txt index at https://docs.buildbetter.ai/llms.txt). The GraphQL endpoint (api.buildbetter.app/v1/graphql) that this source uses is explicitly deprecated for customer integrations in favor of a REST API at https://api.buildbetter.app/v3/rest; unauthenticated introspection returns 'no_queries_available', so the resource list came from the docs, not the schema. Worth a follow-up to re-point the source at REST before GraphQL is retired.

## Buildkite — gaps

Today (4): `agents`, `builds`, `organizations`, `pipelines`

Diffed against: <https://buildkite.com/docs/llms.txt>

- [ ] `builds/{number}/jobs` — job-level duration, state, and retry data is the real analytical grain of CI cost and flakiness; builds alone hide it (high)
- [ ] `analytics/organizations/{org}/suites/{suite}/runs (Test Engine runs)` — test suite run history is Buildkite's headline Test Engine metric and has no equivalent in the current tables (high)
- [ ] `analytics/organizations/{org}/suites/{suite}/tests (Test Engine tests, label=flaky)` — per-test pass/fail and flaky labelling — the core use case for anyone importing CI data (high)
- [ ] `organizations/{org}/teams` — lookup table resolving team ownership of the pipelines we already sync (high)
- [ ] `organizations/{org}/teams/{team}/pipelines` — membership table joining teams to pipelines, needed to attribute build cost per team (high)
- [ ] `organizations/{org}/members` — lookup resolving the user IDs that appear as build creators and job agents (high)
- [ ] `organizations/{org}/clusters/{cluster}/queues` — lookup resolving the queue an agent or job ran on — required for agent capacity and cost analysis (medium)
- [ ] `organizations/{org}/clusters` — lookup resolving cluster IDs carried on agents and queues (medium)
- [ ] `organizations/{org}/pipelines/{pipeline}/builds/{number}/artifacts` — artifact inventory and sizes per build, useful for storage and output tracking (medium)
- [ ] `organizations/{org}/teams/{team}/members` — membership table joining users to teams (medium)
- [ ] `organizations/{org}/pipelines/{pipeline}/schedules` — explains which builds are scheduled vs triggered — a common breakdown dimension on build volume (medium)
- [ ] `organizations/{org}/pipelines/{pipeline}/builds/{number}/annotations` — build annotations carry test summaries and custom CI reporting output (low)

Note: Buildkite publishes a complete machine-readable docs index at /docs/llms.txt with one line per REST resource; every endpoint below is named there.

## Bunny — gaps

Today (4): `dns_zones`, `pull_zones`, `storage_zones`, `video_libraries`

Diffed against: <https://core-api-public-docs.b-cdn.net/docs/v3/public.json>

- [ ] `GET /statistics` — account-wide bandwidth, requests, and cache hit rate over time — Bunny's headline metric and entirely absent today (high)
- [ ] `GET /storagezone/{id}/statistics and /statistics/egress` — storage usage and egress per zone; the cost driver for the storage_zones we already sync (high)
- [ ] `GET /library/{libraryId}/videos (Stream API)` — child table of video_libraries we already sync — the individual videos, with status, size, and view counts (high)
- [ ] `GET /library/{libraryId}/statistics (Stream API)` — views, watch time, and bandwidth per video library — the core Stream analytics object (high)
- [ ] `GET /dnszone/{zoneId}/records` — lookup/child table resolving the DNS zones we already sync into individual records (high)
- [ ] `GET /dnszone/{id}/statistics` — DNS query volume per zone, the only usage metric for the DNS product (medium)
- [ ] `GET /library/{libraryId}/collections (Stream API)` — lookup resolving the collection IDs carried on videos (medium)
- [ ] `GET /v2/pullzones/{pullZoneId}/logs (CDN Logging API)` — raw edge access logs — request-level detail for traffic analysis (medium)
- [ ] `GET /billing/summary` — spend per period per service, needed to tie CDN usage to cost (medium)
- [ ] `GET /library/{libraryId}/videos/{videoId}/heatmap and /play (Stream API)` — per-video engagement/retention curve; the drop-off analysis people import video data for (medium)
- [ ] `GET /pullzone/{pullZoneId}/optimizer/statistics` — image optimizer usage per pull zone, a breakdown of the traffic we would otherwise only see in aggregate (low)
- [ ] `GET /pullzone/{pullZoneId}/safehop/statistics and /originshield/queuestatistics` — origin reliability and shield queue behavior per pull zone (low)

Note: Bunny splits its API across several specs, all fetched this run: Core (core-api-public-docs.b-cdn.net/docs/v3/public.json), Stream (video.bunnycdn.com/openapi/bunnynet-video-api.public.json), and CDN Logging (logging.bunnycdn.com/docs/all/swagger.json). PostHog syncs only the four top-level zone/library objects — every statistics and child resource in all three specs is missing, so the source currently carries configuration objects but none of the usage data that is the point of a CDN import.

## Buzzsprout — adequate

Today (2): `episodes`, `podcasts`

Diffed against: <https://github.com/Buzzsprout/buzzsprout-api/blob/master/README.md>

No material gaps found.

Note: The vendor's official API repo (github.com/Buzzsprout/buzzsprout-api) contains exactly two resource sections — sections/podcasts.md and sections/episodes.md, confirmed via the GitHub contents API. Both are already exposed. There is no publicly documented downloads/analytics endpoint; I found no spec for one and did not want to invent it.

## CalCom — gaps

Today (6): `bookings`, `event_types`, `me`, `schedules`, `teams`, `webhooks`

Diffed against: <https://cal.com/docs/api-reference/v2/openapi.json>

- [ ] `/v2/organizations/{orgId}/memberships and /v2/teams/{teamId}/memberships` — membership tables joining users to the teams we already sync — currently no way to attribute a booking to a team member (high)
- [ ] `/v2/organizations/{orgId}/users` — lookup table resolving the user/host IDs carried on bookings and event types (high)
- [ ] `/v2/bookings/{bookingUid}/attendees` — attendee-level rows for each booking — the grain needed for no-show and guest analysis (high)
- [ ] `/v2/organizations/{orgId}/routing-forms/{routingFormId}/responses` — routing form submissions, the lead-qualification data that explains which bookings came from which route (high)
- [ ] `/v2/organizations/{orgId}/routing-forms` — lookup resolving the routing form IDs on responses and routed bookings (medium)
- [ ] `/v2/organizations/{orgId}/teams` — org-level team list; the existing teams table is the personal-scope one and misses org teams (medium)
- [ ] `/v2/organizations/{orgId}/attributes and /attributes/{attributeId}/options` — lookup tables for the org attributes used to segment and route users (medium)
- [ ] `/v2/me/ooo and /v2/organizations/{orgId}/users/{userId}/ooo` — out-of-office entries, needed to interpret availability and booking gaps (medium)
- [ ] `/v2/event-types/{eventTypeId}/history` — state/transition history for event types, so config changes can be correlated with booking volume shifts (low)
- [ ] `/v2/bookings/{bookingUid}/recordings and /transcripts` — meeting artifacts per booking for content analysis (low)

Note: Full OpenAPI 3 spec for Cal.com API v2 (1.4 MB) fetched and parsed directly; api.cal.com/v2/docs-json returns the HTML docs shell, not JSON, so use the cal.com/docs path.

## Calendly — gaps

Today (5): `event_types`, `groups`, `organization_memberships`, `routing_forms`, `scheduled_events`

Diffed against: <https://stoplight.io/api/v1/projects/cHJqOjY4NTM/table-of-contents>

- [ ] `List Event Invitees (/scheduled_events/{uuid}/invitees)` — the invitee is the person, cancellation reason, no-show flag, UTM tracking, and Q&A answers — without it scheduled_events is unusable for funnel analysis (high)
- [ ] `List Routing Form Submissions (/routing_form_submissions)` — submissions for the routing_forms we already sync, including questions/answers, tracking, and which event type they routed to (high)
- [ ] `List Contacts (/contacts)` — the person lookup table Calendly resolves invitee emails against (high)
- [ ] `List Event Type Hosts (/event_types/{uuid}/hosts)` — membership table joining the event_types we sync to their hosting users (high)
- [ ] `List Group Relationships (/group_relationships)` — lookup joining the groups we already sync to users and event types (medium)
- [ ] `List activity log entries (/activity_log_entries)` — state/transition history for org and user changes; the audit trail for who changed what (medium)
- [ ] `List Recaps and Get Transcript (Notetaker)` — meeting recaps and transcripts tied to scheduled events, for content analysis of calls (medium)
- [ ] `List outgoing communications (/outgoing_communications)` — SMS and email sent per event — reminder/notification delivery data (medium)
- [ ] `List User Availability Schedules (/user_availability_schedules)` — availability rules per user, needed to compute utilization against bookable hours (medium)
- [ ] `Get Invitee No Show (/invitee_no_shows)` — no-show records; a headline meeting-quality metric (also surfaced on the invitee object) (medium)
- [ ] `List Organization Invitations (/organizations/{uuid}/invitations)` — seat onboarding funnel — who was invited, when, and whether they accepted (low)

Note: developer.calendly.com is a Gatsby shell with no fetchable spec; the real resource list is the Stoplight project it renders (project id cHJqOjY4NTM, browsable at https://calendly.stoplight.io/docs/api-docs). The table-of-contents JSON above lists every operation and model and is what I diffed against. Biggest issue: scheduled_events are synced without their invitees, so the source has meetings but no attendees.

## CallRail — gaps

Today (7): `calls`, `companies`, `form_submissions`, `tags`, `text_messages`, `trackers`, `users`

Diffed against: <https://apidocs.callrail.com/>

- [ ] `leads (/a/{account_id}/leads.json)` — the conversion object CallRail exists to produce — currently calls and form submissions are synced but not the leads derived from them (high)
- [ ] `accounts (/a.json)` — lookup resolving the account_id every other resource is scoped under; required for multi-account (agency) reporting (high)
- [ ] `page_views (/a/{account_id}/calls/{call_id}/page_views.json)` — per-call visitor page-view journey — the attribution path behind each tracked call (high)
- [ ] `lead_timelines (/a/{account_id}/leads/{id}/timeline.json)` — state/transition history for a lead across calls, texts, and forms (medium)
- [ ] `sms_threads (/a/{account_id}/sms_threads.json)` — thread-level SMS conversations, the parent grain the text_messages table hangs off (medium)
- [ ] `calls summary and timeseries (/a/{account_id}/calls/summary.json, /calls/timeseries.json)` — vendor-computed call volume breakdowns by source and period, matching what the CallRail UI reports (medium)
- [ ] `form_submissions summary (/a/{account_id}/form_submissions/summary.json)` — vendor-computed form conversion aggregates aligned with the call summary (low)
- [ ] `outbound_caller_ids (/a/{account_id}/caller_ids.json)` — lookup resolving the caller ID numbers appearing on outbound calls (low)

Note: apidocs.callrail.com serves the entire v3 reference as one ~890 KB HTML page; I parsed its heading tree for the resource list rather than using the summarizer.

## CampaignMonitor — gaps

Today (17): `active_subscribers`, `bounced_subscribers`, `campaign_bounces`, `campaign_clicks`, `campaign_opens`, `campaign_spam_complaints`, `campaign_summary`, `campaign_unsubscribes`, `campaigns`, `clients`, `draft_campaigns`, `lists`, `scheduled_campaigns`, `segments`, `suppression_list`, `templates`, `unsubscribed_subscribers`

Diffed against: <https://www.campaignmonitor.com/api/v3-3/campaigns/>

- [ ] `Campaign recipients (/campaigns/{id}/recipients)` — who a campaign was sent to; without it the opens/clicks/bounces tables have no denominator (high)
- [ ] `Getting journeys (/clients/{id}/journeys)` — the automation product is entirely unsynced; journeys is the lookup every journey metric hangs off (high)
- [ ] `Journey email recipients / opens / clicks / bounces / unsubscribes (/journeys/email/{id}/...)` — per-email engagement events for automations, mirroring the campaign\_\* tables we already expose (high)
- [ ] `Getting journey summary (/journeys/email/{id}/summary)` — vendor-computed automation performance, the journey equivalent of campaign_summary (high)
- [ ] `List custom fields (/lists/{id}/customfields)` — lookup resolving the custom field keys carried on every subscriber row (high)
- [ ] `Campaign lists and segments (/campaigns/{id}/listsandsegments)` — lookup joining campaigns we sync to the lists and segments they targeted (high)
- [ ] `Campaign email client usage (/campaigns/{id}/emailclientusage)` — breakdown dimension on opens (client/device), a standard email reporting cut (medium)
- [ ] `List stats (/lists/{id}/stats)` — per-list growth, unsubscribe, and bounce totals over time (medium)
- [ ] `Transactional statistics and Message timeline (/transactional/statistics, /transactional/messages)` — message-level transactional sends and their engagement — a whole product currently invisible (medium)
- [ ] `Unconfirmed and deleted subscribers (/lists/{id}/unconfirmed, /lists/{id}/deleted)` — completes the subscriber state coverage alongside active/bounced/unsubscribed that we already sync (medium)
- [ ] `Getting a subscriber's history (/subscribers/history)` — per-subscriber event history across campaigns, for lifecycle analysis (medium)
- [ ] `Getting tags (/clients/{id}/tags)` — lookup resolving the tags applied to campaigns and clients (low)

Note: Diffed against the v3.3 reference section index (account, campaigns, clients, journeys, lists, segments, subscribers, transactional), each page fetched and its operation headings parsed. Campaign engagement coverage is strong, but the entire Journeys (automation) product and the transactional product are absent, and campaign_recipients — the denominator for every open/click rate — is missing.

## Campayn — adequate

Today (5): `contacts`, `emails`, `forms`, `lists`, `reports`

Diffed against: <https://github.com/nebojsac/Campayn-API/blob/master/README.md>

No material gaps found.

Note: The official API docs list exactly six endpoint groups: Lists, Contacts, Forms, Emails, Reports, Signup. PostHog exposes all five readable ones (contacts, emails, forms, lists, reports); Signup is a write-only POST subscribe endpoint. Sub-resources are just nesting of the same collections (/lists/{id}/contacts, /lists/{id}/forms) and /reports/calendar.json is the only report shape the API offers. Nothing meaningful is missing.

## Campfire — gaps

Today (15): `bank_accounts`, `bank_transactions`, `bill_payments`, `bills`, `chart_of_accounts`, `chart_transactions`, `contracts`, `credit_memos`, `debit_memos`, `departments`, `invoice_payments`, `invoices`, `journal_entries`, `revenue_transactions`, `vendors`

Diffed against: <https://docs.campfire.ai/llms.txt>

- [ ] `revenue-recognition/list-contract-products` — contract line items - the revenue detail behind every contract we already sync (high)
- [ ] `revenue-recognition/list-contract-subscriptions` — subscription schedules per contract, needed for ARR/MRR and rev-rec waterfalls (high)
- [ ] `revenue-recognition/list-contract-customers` — lookup table resolving the customer IDs carried on contracts, invoices and revenue transactions (high)
- [ ] `settings/list-chart-entities` — legal entity lookup - every transaction carries an entity ID and multi-entity consolidation is unusable without it (high)
- [ ] `company-objects/list-custom-dimensions (+ list-custom-dimension-groups)` — the breakdown dimensions tagged on chart transactions and journal entries (medium)
- [ ] `revenue-recognition/list-contract-milestones` — milestone-based recognition triggers on contracts we sync (medium)
- [ ] `core-accounting/list-fixed-assets` — fixed asset register and depreciation, a whole ledger area currently absent (medium)
- [ ] `core-accounting/list-budgets (+ list-budget-accounts)` — budget vs actual reporting against chart_of_accounts we already have (medium)
- [ ] `revenue-recognition/list-prepaid-commits (+ list-prepaid-commit-consumption)` — committed spend and drawdown, core usage-based revenue analytics (medium)
- [ ] `revenue-recognition/list-contract-usage-revenue` — usage-driven revenue rows that reconcile to revenue_transactions (medium)
- [ ] `core-accounting/list-intercompany-journal-entries` — intercompany JEs are excluded from the journal_entries table today (medium)
- [ ] `financial-statements/get-trial-balance (also get-general-ledger, get-balance-sheet, get-income-statement)` — vendor-computed statement rollups users would otherwise rebuild by hand from chart_transactions (medium)

Note: Campfire has no public OpenAPI (docs.campfire.ai/openapi.json 404s) but ships a complete llms.txt index of ~330 documented operations. Note there is no bare list-products endpoint - products are only reachable via list-contract-products and list-product-bundles.

## Canny — gaps

Today (10): `boards`, `categories`, `changelog_entries`, `comments`, `companies`, `posts`, `status_changes`, `tags`, `users`, `votes`

Diffed against: <https://developers.canny.io/api-reference>

- [ ] `opportunities/list` — revenue opportunities linked to posts - the headline prioritization metric Canny sells (high)
- [ ] `insights/list` — extracted customer feedback insights tied to posts and users (high)
- [ ] `ideas/list` — the Autopilot idea objects that feed posts, a whole content type missing (medium)
- [ ] `groups/list` — lookup table resolving the group IDs attached to users and companies (medium)

Note: Roadmaps are documented as an object but Canny explicitly says roadmap data is only exposed through post data - there is no roadmaps list endpoint, so it is not a gap. Everything else on the reference (boards, categories, entries, comments, companies, posts, status changes, tags, users, votes) is already covered.

## CapsuleCRM — gaps

Today (9): `categories`, `kases`, `lost_reasons`, `milestones`, `opportunities`, `parties`, `pipelines`, `tasks`, `users`

Diffed against: <https://developer.capsulecrm.com/v2/operations/Party>

- [ ] `Entry (GET /api/v2/entries/filter or listEntriesByDate)` — the notes, emails and activity timeline on parties, opportunities and projects - the main behavioral history in Capsule (high)
- [ ] `Tag (GET /api/v2/tags, listTags tag definitions)` — lookup resolving the tag IDs embedded on parties, opportunities and kases we already sync (high)
- [ ] `Stage (GET /api/v2/stages, listStages)` — lookup for the board stage IDs carried on opportunities and projects (high)
- [ ] `Custom Field (GET /api/v2/fields/definitions, listFields)` — field-definition lookup that names the custom field values embedded in parties/opportunities (medium)
- [ ] `Board (GET /api/v2/boards, listBoards)` — lookup that groups stages, needed to interpret stage-level funnel data (medium)
- [ ] `Team (GET /api/v2/teams, listTeams)` — lookup resolving team ownership on users, tasks and opportunities (medium)
- [ ] `Goal (GET /api/v2/goals, listGoals + listGoalPeriods)` — sales targets per user/period - the denominator for quota attainment reporting (medium)
- [ ] `Track (GET /api/v2/tracks, listTrack)` — lookup for the task-sequence templates that generate the tasks we sync (medium)
- [ ] `Opportunity additional parties (GET /api/v2/opportunities/{id}/parties)` — many-to-many join between opportunities and contacts, otherwise unrecoverable (medium)
- [ ] `Project additional parties (GET /api/v2/kases/{id}/parties)` — same join for projects/cases we already sync as kases (low)
- [ ] `Party employees (GET /api/v2/parties/{id}/people, listEmployees)` — organisation-to-person hierarchy for account rollups (low)
- [ ] `listDeletedParties / listDeletedOpportunities` — tombstones needed to keep an incremental warehouse copy from drifting (low)

Note: The `kases` table PostHog already exposes is the legacy alias for Projects (the Case doc page is now just a pointer to Project), so Projects are NOT a gap. Country/currency reference lists under Internationalization were excluded as static reference data.

## CareQualityCommission — gaps

Today (2): `locations`, `providers`

Diffed against: <https://raw.githubusercontent.com/microsoft/PowerPlatformConnectors/dev/independent-publisher-connectors/Care%20Quaility%20Comission%20For%20England/CQC-Connector.swagger.json>

- [ ] `/public/v1/inspection-areas` — the global taxonomy of CQC inspection areas - the lookup table that names every inspection-area code appearing on providers and locations (high)
- [ ] `/public/v1/locations/{location_id}/inspection-areas` — per-location inspected areas and their ratings, the actual regulatory outcome data users come for (high)
- [ ] `/public/v1/providers/{provider_id}/inspection-areas` — provider-level inspected areas and ratings, the same at the parent org level (high)
- [ ] `/public/v1/locations/{location_id}/provider-inspection-areas` — provider-level areas scoped to a location, needed to join site ratings to org ratings (medium)
- [ ] `/public/v1/changes/{organisation_type}` — the delta feed of providers/locations changed in a time window - enables cheap incremental sync and change-over-time analysis (medium)

Note: CQC publishes no reachable OpenAPI of its own (api.cqc.org.uk/public/v1/swagger.json and api.service.cqc.org.uk equivalents both 404; the api-portal developer portal is JS-rendered and subscription-key gated). Verified instead against the Microsoft Power Platform independent-publisher connector swagger, which targets host api.cqc.org.uk basePath /public/v1 and enumerates 12 operations; cross-checked against the CQC connector summary page on Microsoft Learn. /reports/{id} endpoints return PDF or report text rather than tabular rows, so they were excluded.

## Census — gaps

Today (4): `destinations`, `sources`, `sync_runs`, `syncs`

Diffed against: <https://fivetran.com/docs/activations/rest-api/api-reference/workspace-apis/syncs/get-syncs>

- [ ] `workspace-apis/datasets/list-datasets` — lookup resolving the dataset/model IDs every sync points at - without it syncs reference opaque IDs (high)
- [ ] `workspace-apis/sync-runs/fetch-records` — record-level sync results including rejected rows, the detail needed to diagnose why a sync partially failed (high)
- [ ] `workspace-apis/sync-runs/fetch-records-count` — per-run record counts by status, the cheap aggregate for sync health dashboards (medium)
- [ ] `organization-apis/workspaces/list-workspaces` — lookup naming the workspaces that scope every source, destination and sync (medium)
- [ ] `workspace-apis/source-types/list-source-types` — lookup expanding the source type codes on the sources table (low)
- [ ] `workspace-apis/destination-types/list-connectors` — lookup expanding the destination connector codes on the destinations table (low)
- [ ] `workspace-apis/destinations/objects/fetch-destination-object` — destination object schemas that sync field mappings target (low)

Note: Census now lives under the Fivetran Activations docs; the docs are HTML-only (no llms.txt or OpenAPI export found at fivetran.com/docs/llms.txt). The reference sidebar is the authoritative resource list. Webhooks and source/destination connect links were excluded as plumbing.

## Chameleon — gaps

Today (8): `companies`, `event_names`, `launchers`, `profiles`, `responses`, `segments`, `surveys`, `tours`

Diffed against: <https://developers.chameleon.io/apis/overview.md>

- [ ] `GET /v3/analyze/interactions (Tour Interactions)` — per-user tour state (displayed/started/completed/exited) - the headline engagement metric and the only way to measure tour performance (high)
- [ ] `GET /v3/edit/tooltips` — a whole experience type missing alongside tours, launchers and surveys (medium)
- [ ] `GET /v3/edit/tags` — lookup resolving the tag IDs used to organize experiences (medium)
- [ ] `GET /v3/edit/properties (Data Properties)` — lookup of the property definitions sent on profiles and companies, needed to interpret their semi-arbitrary property blobs (medium)
- [ ] `GET /v3/edit/deliveries (Experience Deliveries)` — records of experiences targeted at specific users, the delivery side of the interaction funnel (medium)

Note: Chameleon's published OpenAPI at developers.chameleon.io/api-reference/openapi.json is a stub (it documents a /plants toy API), so the authoritative endpoint table is the markdown overview page. Alert groups, rate limit groups, webhooks, domains and data imports were excluded as config/plumbing. Embeddables, Product Demos and Changes have doc pages in llms.txt but do not appear in the overview endpoint table, so no list endpoint could be confirmed for them - they are not reported as gaps.

## Chargedesk — gaps

Today (4): `charges`, `customers`, `products`, `subscriptions`

Diffed against: <https://chargedesk.com/api-docs>

- [ ] `GET /v1/charges/{CHARGE_ID}/items` — charge line items - the product/quantity breakdown behind every charge we already sync (high)
- [ ] `GET /v1/log/cancellations` — subscription cancellation log with reasons and timestamps, the core churn dataset (high)
- [ ] `GET /v1/log/activity` — the account-wide activity/state-change history across charges, customers and subscriptions (high)

Note: Full endpoint list extracted from the single-page api-docs HTML. Only three additional GET-listable analytical resources exist; agents are POST/DELETE only (no list endpoint), /v1/customers/grouped is just an aggregated view of customers we already sync, and gateway/\* plus webhooks are actions and plumbing.

## Chargify — gaps

Today (8): `Components`, `Customers`, `Events`, `Invoices`, `ProductFamilies`, `Products`, `Subscriptions`, `Transactions`

Diffed against: <https://github.com/maxio-com/ab-python-sdk/tree/main/advancedbilling/controllers>

- [ ] `subscriptions/{id}/components (and site-wide list_subscription_components_for_site)` — per-subscription component price point and quantity - the line-item grain that makes Subscriptions joinable to Components (high)
- [ ] `subscriptions/{id}/components/{component_id}/usages` — metered usage records, the fact table for any usage-based billing analysis (high)
- [ ] `subscriptions/{id}/components/{component_id}/allocations` — quantity change history per component - seat expansion/contraction over time (high)
- [ ] `coupons (and coupons/{id}/usage, coupon subcodes)` — lookup resolving the coupon ids already carried on subscriptions and invoices, plus discount attribution (high)
- [ ] `reason_codes` — lookup that resolves the churn/cancellation reason codes referenced by subscription cancellations (high)
- [ ] `invoices/credit_notes` — credits and write-offs that net against Invoices; revenue is wrong without them (high)
- [ ] `insights/mrr_movements` — Maxio's headline metric - new/expansion/contraction/churn MRR movement breakdown (high)
- [ ] `insights/mrr_per_subscription` — per-subscription MRR snapshot for cohorting and ARR rollups (medium)
- [ ] `components/{id}/price_points and products/{id}/price_points (list_all_component_price_points / list_all_product_price_points)` — pricing lookup resolving the price point ids on subscriptions and components (medium)
- [ ] `subscription_groups` — resolves multi-subscription billing groups so invoices can be attributed to the paying parent (medium)
- [ ] `metafields and metadata (custom fields)` — customer/subscription custom attribute values used for segmentation (medium)
- [ ] `invoices/{uuid}/events` — invoice state transition history (issued, paid, voided, refunded) (medium)

Note: developers.maxio.com is an APIMatic SPA that returns a 121-byte shell to curl and serves no reachable OpenAPI document, so I enumerated the resource surface from Maxio's own generated SDK (maxio-com/ab-python-sdk), fetched via the GitHub tree API plus the raw controller files. The controllers are 1:1 with the Advanced Billing API spec. Source is static (settings.py enum), no dynamic table discovery.

## ChartHop — gaps

Today (8): `changes`, `group_types`, `groups`, `job_codes`, `job_levels`, `jobs`, `persons`, `time_off`

Diffed against: <https://api.charthop.com/swagger.json>

- [ ] `/v1/org/{orgId}/timeoff/policy` — lookup resolving the policy ids already carried on the synced time_off rows (high)
- [ ] `/v1/org/{orgId}/timeoff/policy/balances` — accrued vs used balance per person per policy - the number HR actually reports on (high)
- [ ] `/v1/org/{orgId}/change/compensation-history` — compensation change history per person, the analytical spine for pay-equity and raise analysis (high)
- [ ] `/v1/org/{orgId}/band` — comp band lookup that resolves the band a job/job_level sits in (high)
- [ ] `/v1/org/{orgId}/timeoff-ledger/data` — per-entry accrual/usage ledger behind the balances (medium)
- [ ] `/v1/org/{orgId}/comp-review` — compensation review cycles and their in-cycle changes (medium)
- [ ] `/v1/org/{orgId}/stockgrant` — equity grants per person - missing half of total compensation (medium)
- [ ] `/v1/org/{orgId}/goal and /goal-progress` — performance goals and their progress over time (medium)
- [ ] `/v1/org/{orgId}/assessment` — performance review cycles and calibration participants (medium)
- [ ] `/v1/org/{orgId}/form-response` — survey/form responses (engagement, onboarding, offboarding) keyed to persons (medium)
- [ ] `/v1/user` — lookup mapping ChartHop user accounts to person ids for adoption analysis (medium)
- [ ] `/v1/org/{orgId}/scenario` — headcount planning scenarios, needed to compare planned vs actual hiring (medium)

Note: Full OpenAPI 3 spec (2 MB, 541 paths) is served unauthenticated at api.charthop.com/swagger.json. PostHog covers the core org-chart entities but none of the compensation, performance, or time-off ledger surface.

## ChartMogul — gaps

Today (6): `activities`, `customers`, `data_sources`, `invoices`, `plan_groups`, `plans`

Diffed against: <https://dev.chartmogul.com/sitemap.xml>

- [ ] `/v1/customers/{customer_uuid}/subscriptions` — subscriptions are the core SaaS object and currently unreachable - plans and invoices cannot be joined into a subscription lifecycle (high)
- [ ] `/v1/subscription_events` — subscription state transition stream (started, updated, cancelled) - the movement history behind churn analysis (high)
- [ ] `/v1/metrics/all (plus /metrics/mrr, /arr, /arpa, /asp, /ltv, /customer-count, /churn-rate, /mrr-churn-rate)` — ChartMogul's headline metrics; today none of the product's actual output is syncable (high)
- [ ] `/v1/opportunities` — CRM pipeline deals with value and stage - the main revenue-forecasting object (high)
- [ ] `/v1/contacts` — person-level contacts under each customer, needed to join CRM activity to accounts (medium)
- [ ] `/v1/plan_groups/{plan_group_uuid}/plans` — lookup mapping the already-synced plans to the already-synced plan_groups (medium)
- [ ] `/v1/customers/{customer_uuid}/attributes (custom attributes and tags)` — the segmentation dimensions customers are actually sliced by (medium)
- [ ] `/v1/tasks` — CRM tasks per customer for CS workload and follow-up analysis (medium)
- [ ] `/v1/customer_notes (notes and call logs)` — logged calls and notes per customer, joinable to churn outcomes (low)

Note: No machine-readable spec is published; I enumerated the full /reference/\* resource tree from the sitemap (182 URLs) and then fetched the individual reference pages to confirm the concrete api.chartmogul.com paths (e.g. /v1/subscription_events, /v1/opportunities, /v1/customers/{uuid}/subscriptions, /v1/plan_groups/{uuid}/plans). Notably the entire ChartMogul CRM surface (opportunities, contacts, tasks, notes) and every metrics endpoint are absent.

## Chatwoot — gaps

Today (8): `agents`, `contacts`, `conversations`, `custom_attribute_definitions`, `inboxes`, `labels`, `messages`, `teams`

Diffed against: <https://raw.githubusercontent.com/chatwoot/chatwoot/develop/swagger/swagger.json>

- [ ] `/api/v1/accounts/{account_id}/reporting_events (and .../conversations/{conversation_id}/reporting_events)` — the per-conversation event stream (first_response, conversation_resolved, reply_time) that every support SLA metric is computed from (high)
- [ ] `/api/v1/accounts/{account_id}/teams/{team_id}/team_members` — lookup join table resolving which agents belong to which of the already-synced teams (high)
- [ ] `/api/v1/accounts/{account_id}/inbox_members/{inbox_id}` — lookup join table resolving agent-to-inbox assignment for routing and load analysis (high)
- [ ] `/api/v2/accounts/{account_id}/summary_reports/agent | inbox | team | channel` — vendor-computed agent/inbox/team performance rollups (resolution counts, response times) (medium)
- [ ] `/api/v2/accounts/{account_id}/reports/conversations and /reports/summary` — conversation volume and first-response-time timeseries, the product's headline dashboard numbers (medium)
- [ ] `/api/v1/accounts/{account_id}/conversations/{conversation_id}/labels and /contacts/{id}/labels` — the label-to-conversation and label-to-contact join tables; the labels table alone cannot be joined to anything (medium)
- [ ] `/api/v1/accounts/{account_id}/audit_logs` — who changed what in the account, useful for change-vs-metric correlation (low)

Note: Vendor's own swagger.json in the chatwoot/chatwoot repo, 90 paths. Coverage of the core objects is good; what's missing is the reporting/event layer and the membership join tables.

## Checkmarx — gaps

Today (5): `applications`, `projects`, `scan_results`, `scan_results_summary`, `scans`

Diffed against: <https://checkmarx.stoplight.io/docs/checkmarx-one-api-reference-guide>

- [ ] `sast-results-predicates (Retrieve SAST predicates, Retrieve predicates changelog)` — per-result triage state/severity transition history - the only way to measure remediation and time-to-triage (high)
- [ ] `Lists API (Retrieve list of states / statuses / severities)` — lookup tables that decode the state, status and severity ids already present on scan_results (high)
- [ ] `Custom States (Retrieve custom states)` — lookup for tenant-defined triage states; without it custom-state results are unreadable ids (high)
- [ ] `Applications - Retrieve list of application rules` — lookup resolving which projects roll into which application; today the applications-to-projects edge is missing (high)
- [ ] `Projects - Retrieve list of branches (and Retrieve last scan)` — branch dimension for scans; per-branch vulnerability trend is a core use case (medium)
- [ ] `SAST Metadata (Retrieve scans metadata, Retrieve scan metrics)` — LOC scanned, engine config and scan metrics - the denominators for density metrics (medium)
- [ ] `Policy Management (Retrieve all policies, policy violation details, policy violation summary)` — policy breaches per scan, the compliance-reporting object (medium)
- [ ] `Projects and Applications - Retrieve list of tags` — tag lookup used to group projects/applications by team or business unit (medium)
- [ ] `Audit Trail - Get a list of audit events` — who changed project config, presets or triage state, correlatable to result changes (medium)
- [ ] `DAST Scans and DAST Results` — an entire scanner's scans and findings are unreachable today (medium)
- [ ] `API Security Scan Results (Retrieve API Security risks, Get all api scan Metadata)` — API risk findings and the sensitive/undocumented API counts (medium)
- [ ] `Risk Orchestration (Retrieve risks, Retrieve aggregated risks)` — cross-scanner aggregated risk view used for posture reporting (low)

Note: docs.checkmarx.com now redirects the API reference to Stoplight; I pulled the full operation tree from https://checkmarx.stoplight.io/api/v1/projects/cHJqOjE5ODM2OQ==/table-of-contents (project 198369) and read every GET operation from it. The gap concentration is in triage state history and the small lookup tables that decode the ids on scan_results.

## CheckoutCom — **thin**

Today (1): `disputes`

Diffed against: <https://api-reference.checkout.com/v1/swagger.yaml>

- [ ] `POST /payments/search` — the bulk payments surface (beta, paginated) - payments are the whole point of the integration and are entirely missing (high)
- [ ] `GET /financial-actions` — the settlement ledger: captures, refunds, chargebacks and fees per payment; reconciliation is impossible without it (high)
- [ ] `GET /payments/{id}/actions` — per-payment action history (authorize, capture, void, refund) with response codes - the transition history behind decline analysis (high)
- [ ] `GET /reports and GET /reports/{id}/files/{fileId}` — the settlement and payments report files Checkout.com itself points finance teams at for reconciliation (high)
- [ ] `GET /balances/{id}` — per-currency-account balances for an entity, needed for payout and float reporting (medium)
- [ ] `GET /issuing/transactions` — card issuing transaction fact table for anyone using Issuing (medium)
- [ ] `GET /disputes/{dispute_id}/evidence (and /evidence/submitted, /schemefiles)` — evidence submitted per dispute; win-rate analysis needs it alongside the disputes already synced (medium)
- [ ] `GET /accounts/entities/{id}/payment-instruments and /accounts/entities/{entityId}/members` — platform sub-entity payout instruments and members, the dimension tables for marketplace reporting (low)
- [ ] `GET /forex/rates` — indicative FX rates for normalizing multi-currency volume (requires processing_channel_id and currency pairs) (low)

Note: Official OpenAPI 3.0.1 (2.8 MB, 173 paths) is served at api-reference.checkout.com/v1/swagger.yaml. The source implementation comments that "Checkout.com has no list-all-payments endpoint - bulk payment data only exists via report files", but the current spec does expose POST /payments/search (beta, cursor-paginated) and GET /financial-actions as real bulk surfaces, so that constraint is out of date. Only `disputes` is synced today, out of a payments API - this is a small fraction of the vendor's queryable surface.

## Churnkey — adequate

Today (1): `Sessions`

Diffed against: <https://docs.churnkey.co/data-integrations/data-api>

No material gaps found.

Note: The entire Churnkey Data API is four routes: GET /v1/data/sessions, GET /v1/data/session-aggregation, and two POST GDPR DSR endpoints (/dsr/access, /dsr/delete). session-aggregation is a pure rollup of sessions (grouped counts by month/planId/offerType/etc.) that a warehouse user can compute from the Sessions table, and the DSR endpoints are compliance plumbing that mutate/expose single-customer data. The session payload already nests customer, acceptedOffer, presentedOffers and survey response fields. Source is static, but there is genuinely nothing else to sync.

## Cimis — adequate

Today (5): `daily_data`, `hourly_data`, `spatial_zipcodes`, `station_zipcodes`, `stations`

Diffed against: <https://et.water.ca.gov/Rest/Index>

No material gaps found.

Note: The CIMIS Web API has exactly four REST services: /api/data (daily and hourly data items for stations, zip codes, coordinates or addresses), /api/station, /api/stationzipcode and /api/spatialzipcode. PostHog's five tables map 1:1 onto those - daily_data and hourly_data are the two data-item classes of /api/data. There is no other queryable resource.

## CircleCI — gaps

Today (4): `jobs`, `pipelines`, `projects`, `workflows`

Diffed against: <https://circleci.com/api/v2/openapi.json>

- [ ] `organizations/{org_id}/usage_export_job` — credit/usage export per project and job - CircleCI's headline cost metric, absent today (high)
- [ ] `deploy/environments` — deploy environment registry that resolves environment IDs on deploy markers (medium)
- [ ] `deploy/components` — deployed component inventory, the join key for deploy tracking (medium)
- [ ] `deploy/components/{component_id}/versions` — version history per component - deploy frequency and lead-time analysis (medium)
- [ ] `user/{id}` — lookup resolving the actor/trigger user IDs carried on pipelines and workflows (medium)
- [ ] `organizations/{org_id}/groups` — org user groups for grouping build activity by team (low)
- [ ] `me/collaborations` — org/slug lookup that enumerates the orgs a token can see (low)
- [ ] `projects/{project_id}/pipeline-definitions` — resolves the pipeline definition IDs attached to synced pipelines (low)

Note: The current v2 spec has no artifacts or test-metadata endpoints (those lived in v1.1), so no gap there. Insights paths exist in the same spec but belong to the separate CircleciInsights source. Source is fully static (CIRCLECI_ENDPOINTS), no dynamic discovery.

## CircleciInsights — gaps

Today (5): `flaky_tests`, `job_metrics`, `org_summary_metrics`, `workflow_metrics`, `workflow_runs`

Diffed against: <https://circleci.com/api/v2/openapi.json>

- [ ] `insights/{project-slug}/workflows/{workflow-name}/test-metrics` — per-test duration and failure metrics - the main test-health breakdown beyond flaky tests (high)
- [ ] `insights/time-series/{project-slug}/workflows/{workflow-name}/jobs` — granular job timeseries, the only source of point-in-time job trends rather than window aggregates (high)
- [ ] `insights/{project-slug}/branches` — branch dimension lookup for slicing every other insights metric (medium)
- [ ] `insights/{project-slug}/workflows/{workflow-name}/summary` — workflow summary with trend deltas, complements the raw workflow metrics (medium)
- [ ] `insights/pages/{project-slug}/summary` — project-level workflow rollup used by the Insights UI landing page (low)

Note: All five Insights tables map cleanly onto spec paths; the gaps are the remaining Insights operations in the same spec.

## CiscoDuo — gaps

Today (9): `activity_logs`, `administrator_logs`, `admins`, `authentication_logs`, `groups`, `integrations`, `phones`, `telephony_logs`, `users`

Diffed against: <https://duo.com/docs/adminapi>

- [ ] `/admin/v2/policies` — policy lookup resolving the policy keys referenced by authentication and activity logs (high)
- [ ] `/admin/v2/groups/{group_id}/users (and /admin/v1/users/{user_id}/groups)` — user-to-group membership join table - we sync users and groups but not the link between them (high)
- [ ] `/admin/v1/trust_monitor/events` — Duo Trust Monitor security events, the vendor's flagged-risk feed (high)
- [ ] `/admin/v1/endpoints` — managed endpoint/device inventory with OS, browser and plugin versions - resolves device IDs in auth logs (high)
- [ ] `/admin/v1/tokens` — hardware token inventory, the second-factor dimension missing next to phones (medium)
- [ ] `/admin/v1/webauthncredentials` — WebAuthn/security-key enrollment inventory for MFA method coverage reporting (medium)
- [ ] `/admin/v1/registered_devices` — registered and blocked device records for device-trust analysis (medium)
- [ ] `/admin/v1/bypass_codes` — bypass code issuance and usage counts - a standard security audit query (medium)
- [ ] `/admin/v1/admin_roles` — role lookup resolving role assignments on the admins table we already sync (medium)
- [ ] `/admin/v1/logs/offline_enrollment` — offline (MFA for Windows/Mac logon) enrollment event log, a log stream we do not carry (medium)
- [ ] `/admin/v1/info/authentication_attempts` — pre-aggregated auth success/failure/fraud counts for fast trend reporting (low)
- [ ] `/admin/v1/administrative_units` — administrative unit scoping that segments admins, groups and integrations (low)

Note: Static endpoint config, no dynamic table discovery. Excluded settings, branding, bulk operations, activation links and directory-sync trigger endpoints as config/plumbing.

## Clari — gaps

Today (2): `audit_events`, `forecast`

Diffed against: <https://developer.clari.com/default/documentation/external_spec>

- [ ] `/opportunity` — opportunity-level revenue records - the core analytical object behind every forecast number (high)
- [ ] `/export/activity` — rep activity export (calls, emails, meetings) driving engagement-vs-outcome analysis (high)

Note: The public Clari API v5 spec is small: forecast export, export jobs, audit events, opportunity, activity export, admin limits, plus write-only ingest endpoints. /admin/limits was excluded as quota config and /ingest/\* as write plumbing, so opportunity and activity are the only real gaps. Clari Copilot (formerly Wingman) has a separate API host not covered by this spec.

## ClickhouseCloud — gaps

Today (7): `activities`, `api_keys`, `backups`, `members`, `organizations`, `services`, `usage_cost`

Diffed against: <https://clickhouse.com/docs/cloud/manage/api/swagger>

- [ ] `/v1/organizations/{organizationId}/services/{serviceId}/clickpipes (and /clickpipes/{id}/state)` — ingestion pipeline inventory and run state, the only pipeline-health object in the API (medium)
- [ ] `/v1/organizations/{organizationId}/postgres` — managed Postgres services, a service class parallel to the services table we already sync (medium)
- [ ] `/v1/organizations/{organizationId}/postgres/{postgresId}/slowQueryPatterns` — slow query pattern statistics - genuine performance analytics rather than config (medium)
- [ ] `/v1/organizations/{organizationId}/roles` — role lookup resolving the role references on organization members (low)
- [ ] `/v1/organizations/{organizationId}/quotas` — per-quota-code limits to contextualize usage cost against ceilings (low)

Note: The remaining ~60 paths are control-plane configuration (scaling, ClickHouse settings, private endpoints, BYOC infra, ClickStack dashboards/alerts/sources, service passwords), which are excluded by the config/plumbing rule. Analytical coverage (usage_cost, activities, backups, members, services) is already close to complete. The spec is served inside the docs page rather than at api.clickhouse.cloud - /v1/swagger.json and /v1/openapi.json both 404.

## ClickUp — gaps

Today (6): `folders`, `goals`, `lists`, `spaces`, `tasks`, `workspaces`

Diffed against: <https://developer.clickup.com/sitemap.xml>

- [ ] `GET /api/v2/team/{team_id}/time_entries` — tracked time entries - the main quantitative fact table in ClickUp, entirely missing (high)
- [ ] `GET /api/v2/task/{task_id}/time_in_status (and /api/v2/task/bulk_time_in_status)` — per-task status transition history, the only way to compute cycle time from ClickUp data (high)
- [ ] `GET /api/v2/list/{list_id}/field (plus folder/space/team available fields)` — custom field definitions that resolve the custom field IDs already embedded in synced tasks (high)
- [ ] `GET /api/v2/task/{task_id}/comment` — task comment stream for collaboration and response-time analysis (medium)
- [ ] `GET /api/v2/team/{team_id}/custom_item` — custom task type lookup resolving the custom_item_id on tasks (medium)
- [ ] `GET /api/v2/space/{space_id}/tag` — space tag lookup resolving the tags attached to tasks (medium)
- [ ] `GET /api/v2/list/{list_id}/member and /api/v2/task/{task_id}/member` — list and task membership join tables for ownership and workload reporting (medium)
- [ ] `queryauditlog (audit logs)` — workspace audit event stream for admin and compliance reporting (medium)
- [ ] `GET /api/v3 chat channels and messages (getchatchannels, getchatmessages)` — in-product chat activity, a distinct engagement signal from comments (medium)
- [ ] `GET /api/v2/team/{team_id}/customroles` — custom role lookup resolving role IDs on workspace members (low)
- [ ] `GET /api/v2/team/{team_id}/timeentries/tags` — time entry tag lookup for billable/non-billable slicing once time entries land (low)
- [ ] `Docs API (searchdocspublic, getdocpagespublic)` — workspace docs and pages as a content corpus (low)

Note: Diffed against the full operation list in ClickUp's docs sitemap and confirmed the concrete paths by fetching individual reference pages (e.g. /reference/gettimeentrieswithinadaterange -> /api/v2/team/{team_Id}/time_entries). Excluded templates, webhooks, attachments, OAuth and all write operations.

## Clockify — gaps

Today (7): `clients`, `projects`, `tags`, `tasks`, `time_entries`, `users`, `workspaces`

Diffed against: <https://docs.clockify.me/>

- [ ] `GET /v1/workspaces/{workspaceId}/expenses (+ /expenses/categories)` — expense transactions and their category lookup - the cost side of project profitability (high)
- [ ] `GET /v1/workspaces/{workspaceId}/invoices (+ /items, /payments)` — invoice headers, line items and payments, the billing fact tables for revenue reporting (high)
- [ ] `GET /v1/workspaces/{workspaceId}/time-off/requests` — time off requests - required to separate absence from unlogged time in capacity analysis (high)
- [ ] `GET /v1/workspaces/{workspaceId}/projects/{projectId}/memberships` — project-to-user membership join table; today projects and users cannot be linked (high)
- [ ] `GET /v1/workspaces/{workspaceId}/custom-fields` — custom field definitions resolving the custom field IDs stored on time entries and projects (high)
- [ ] `GET /v1/workspaces/{workspaceId}/approval-requests` — timesheet approval state and history per user and period (medium)
- [ ] `GET /v1/workspaces/{workspaceId}/user-groups (+ /{userGroupId}/users)` — team grouping and its membership rows for rolling time up by team (medium)
- [ ] `GET /v1/workspaces/{workspaceId}/time-off/policies` — policy lookup that resolves the policy IDs on time off requests and balances (medium)
- [ ] `GET /v1/workspaces/{workspaceId}/time-off/balance/user/{userId}` — accrued vs used leave balances per user (medium)
- [ ] `GET /v1/workspaces/{workspaceId}/holidays` — holiday calendar needed to compute working days and utilization denominators (medium)
- [ ] `GET /v1/workspaces/{workspaceId}/scheduling/assignments/all` — planned/scheduled assignments to compare planned against tracked time (medium)
- [ ] `GET /v1/workspaces/{workspaceId}/audit-log` — workspace audit event stream for admin and compliance reporting (medium)

Note: Also present but below the cut: POST reports (detailed, summary, weekly, attendance), hourly/cost rate endpoints, and /entities/created|updated|deleted change feeds. Webhooks, addons, templates and shared reports excluded as plumbing/config.

## Clockodo — gaps

Today (8): `customers`, `entries`, `lumpsum_services`, `projects`, `services`, `surcharges`, `teams`, `users`

Diffed against: <https://www.clockodo.com/en/api/>

- [ ] `/v2/absences` — vacation, sick leave and other absences - the main non-billable time dimension (high)
- [ ] `/v2/worktimes` — clock-in/clock-out attendance records, distinct from the project time entries we sync (high)
- [ ] `/v2/userreports` — per-user yearly report (target vs actual hours, overtime, holidays) - the vendor's headline utilization metric (high)
- [ ] `/v2/targethours` — target working hours per user, the denominator for any utilization or overtime calculation (high)
- [ ] `/v2/entrygroups` — grouped/aggregated entry rollups by customer, project or service - the built-in report breakdown (medium)
- [ ] `/v2/nonbusinessdays (+ /nonbusinessgroups)` — public holiday calendars and their groups, needed for working-day normalization (medium)
- [ ] `/v2/holidaysquota and /v2/holidayscarry` — leave entitlement and carry-over balances per user and year (medium)
- [ ] `/v2/overtimecarry` — overtime carried into each year, required for correct cumulative overtime totals (medium)
- [ ] `/v2/worktimes/changerequests` — attendance correction requests and their approval state (low)
- [ ] `/v2/entriestexts` — lookup of reusable entry description texts referenced by entries (low)
- [ ] `/v2/users/access/customers-projects and /users/access/services` — per-user access scoping, useful to explain gaps in who books to what (low)

Note: Endpoint list taken from the API doc index navigation. Excluded /register, /webhooks, and /clock (ephemeral running-timer state). Source config is static, no dynamic discovery.

## Close — gaps

Today (10): `Activities`, `Contacts`, `EmailTemplates`, `LeadStatuses`, `Leads`, `Opportunities`, `OpportunityStatuses`, `Pipelines`, `Tasks`, `Users`

Diffed against: <https://api.close.com/api/openapi.json>

- [ ] `/custom_field/lead/, /custom_field/contact/, /custom_field/opportunity/, /custom_field/activity/, /custom_field/shared/ (+ /custom_field_schema/{object_type}/)` — Lookup that resolves the opaque custom.cf\_\* field IDs already embedded in the synced Leads, Contacts and Opportunities rows - without it those columns are unreadable (high)
- [ ] `/event/` — Event log: full per-object change history (field-level old/new values) for leads, opportunities and tasks; note Close caps it near 30 days of retention so it must be appended incrementally (high)
- [ ] `/sequence/ and /sequence_subscription/` — Outbound sequence definitions plus per-contact enrollment state, the core outbound-motion analysis Close users want (medium)
- [ ] `/custom_object_type/ and /custom_object/` — Custom object instances plus their type definitions - the only way to query org-specific objects modeled outside leads/opportunities (medium)
- [ ] `/outcome/` — Call outcome lookup that resolves the outcome IDs carried on call activities we already sync (medium)
- [ ] `/organization/{id}/` — Org record including memberships, resolving which users belong to which organization and with what role (medium)
- [ ] `/group/ and /role/` — User groups and permission roles - the grouping dimensions for slicing the Users table in rep-performance reporting (medium)
- [ ] `/comment/ and /comment_thread/` — Internal collaboration volume on leads and opportunities (low)
- [ ] `/form/` — Form definitions that resolve the form IDs on FormSubmission activities (low)

Note: Close ships a real OpenAPI 3 spec at https://api.close.com/api/openapi.json (135 GET paths); the source dir already documents it in close/api_inventory.md. The existing `Activities` table syncs the polymorphic /activity/ endpoint, so per-type activity endpoints (calls, emails, notes, SMS, meetings, lead/opportunity status changes) are already covered by it - I did not count them as gaps. Stage/status history is therefore available today via /activity/status_change/\*.

## Cloudbeds — **thin**

Today (6): `guests`, `hotels`, `reservations`, `room_types`, `rooms`, `transactions`

Diffed against: <https://hotels.cloudbeds.com/api/docs/index.html>

- [ ] `getRatePlans` — Rate plan lookup resolving the rate IDs carried on every reservation - required for any ADR/rate-mix analysis (high)
- [ ] `getReservationsWithRateDetails (or getReservationRoomDetails)` — Per-room, per-night rate line items behind a reservation; reservations today are header-only (high)
- [ ] `getDashboard` — Cloudbeds' headline property metrics (occupancy, ADR, RevPAR) precomputed per date (high)
- [ ] `getUsers` — Staff lookup resolving the user IDs stamped on transactions and reservation changes (high)
- [ ] `getSources` — Booking source / channel lookup that resolves the source ID on reservations - the key channel-mix dimension (medium)
- [ ] `getItems and getItemCategories` — Sellable item catalog behind transaction line items, so ancillary revenue can be categorized (medium)
- [ ] `getTaxesAndFees and getRoomsFeesAndTaxes` — Tax and fee definitions needed to split gross transaction amounts into net revenue vs tax (medium)
- [ ] `getHouseAccountList` — House accounts carry non-reservation folio activity that transactions alone cannot attribute (medium)
- [ ] `getReservationAssignments` — Which physical room a reservation occupied and when - links reservations to the rooms table over time (medium)
- [ ] `getGroups, getRoomBlocks, getAllotmentBlocks` — Group bookings and blocked inventory, a major revenue segment invisible in individual reservations (medium)
- [ ] `getGuestsByStatus` — Arrival / departure / in-house state per guest, the basis of daily operational and pace reporting (medium)
- [ ] `getPaymentMethods` — Payment method lookup resolving method codes on transactions (low)

Note: The source targets the PMS API v1.2 (base https://api.cloudbeds.com/api/v1.2, confirmed in cloudbeds/cloudbeds.py) with 6 statically declared endpoints in settings.py - no dynamic table discovery. The v1.2 surface alone exposes ~80 GET methods, so 6 tables is a small fraction. The same docs portal also hosts newer platform APIs (Folios, Fiscalization, Data Insights, Attribute Tagging) on different bases; I scoped gaps to v1.2 to match the implementation.

## Cloudzero — gaps

Today (2): `Costs`, `Dimensions`

Diffed against: <https://docs.cloudzero.com/reference/getbillingcosts>

- [ ] `/v2/optimize/recommendations (+ /v2/optimize/recommendation_types)` — Savings recommendations with estimated dollar impact - CloudZero's headline actionable output, and recommendation_types is the lookup that resolves their type IDs (high)
- [ ] `/v2/insights` — The cost insights backlog (owner, status, estimated savings) - the workflow layer users join back to costs (high)
- [ ] `/v2/budgets` — Budget definitions needed for any budget-vs-actual analysis against the Costs table already synced (high)
- [ ] `/unit-cost/v1/telemetry/{stream}/records (and the sum variant, summetrictelemetry)` — Unit metric telemetry supplies the denominators for cost-per-unit economics, the product's core promise; costs alone cannot produce a unit metric (high)
- [ ] `sumallocationtelemetry / allocation telemetry records` — Allocation drivers used to split shared cost across tenants or teams - needed to reconcile allocated costs (medium)
- [ ] `/v2/views` — Saved cost views define the grouping/filter dimensions the org actually reports on, a lookup for the Dimensions table (medium)
- [ ] `/v2/insights/{insight_id}/comments` — Discussion trail on insights, useful for measuring time-to-action on cost work (low)

Note: The ReadMe reference page embeds the full sidebar, which enumerates the v2 surface: /v2/billing/costs, /v2/billing/dimensions, /v2/budgets, /v2/insights, /v2/optimize/recommendations, /v2/optimize/recommendation_types, /v2/views, /v2/roles, plus CostFormation and AnyCost connection management. Unit-cost telemetry lives on a separate /unit-cost/v1 base, not under /v2.

## Coassemble — gaps

Today (5): `clients`, `collections`, `course_trackings`, `courses`, `users`

Diffed against: <https://developers.coassemble.com/api/tracking>

- [ ] `/collection/trackings` — Learner progress at the collection (learning path) level - the collections table is synced today with no progress data against it (high)
- [ ] `/screen/trackings` — Per-screen progress, the finest analytical grain; the only way to see where inside a course learners drop off (high)
- [ ] `/user/trackings` — Progress rows keyed by learner across all courses, the natural per-user completion table (medium)
- [ ] `/usage/clients (and /usage/client/{identifier})` — Per-client consumption (identified/anonymous recipients, narration tokens, image generations) - joins to the clients table already synced (medium)
- [ ] `/usage/allowances` — Workspace billing-period limits and current usage, giving usage rows a denominator (low)

Note: Headless API (https://api.coassemble.com/api/v1/headless). Docs sections are Courses, Generate, Collections, Identities, Tracking, Themes, Translations, Usage, Webhooks. The synced course_trackings maps to GET /trackings; the tracking section documents three sibling grains that are not synced. Themes/Translations are content config and excluded.

## Coda — gaps

Today (3): `docs`, `rows`, `tables`

Diffed against: <https://coda.io/apis/v1/openapi.json>

- [ ] `/docs/{docId}/tables/{tableIdOrName}/columns` — Column definitions (name, type, formula) that resolve the column IDs used as keys in every synced row - without it rows are unreadable (high)
- [ ] `/analytics/docs and /analytics/docs/summary` — Per-doc usage analytics (views, active users) - the headline metric for measuring doc adoption across a workspace (high)
- [ ] `/workspaces/{workspaceId}/users` — Workspace member lookup that resolves the owner/creator IDs on docs (medium)
- [ ] `/docs/{docId}/pages` — Page hierarchy per doc - the structural dimension for content inventory and for joining page analytics (medium)
- [ ] `/analytics/docs/{docId}/pages` — Page-level view analytics, one grain below doc analytics (medium)
- [ ] `/folders` — Folder lookup resolving the folder reference each doc carries (medium)
- [ ] `/docs/{docId}/acl/permissions` — Who a doc is shared with - needed for access and governance reporting over the docs table (low)
- [ ] `/workspaces/{workspaceId}/roles` — Role lookup that segments workspace users by license/role type (low)
- [ ] `/docs/{docId}/controls and /docs/{docId}/formulas` — Remaining doc object types, completing the content inventory alongside tables and pages (low)
- [ ] `/analytics/packs and /analytics/packs/summary` — Pack install and usage analytics, relevant only to workspaces that publish packs (low)

Note: Coda has been rebranded to Superhuman Docs, but the OpenAPI spec is still served at https://coda.io/apis/v1/openapi.json (v1.6.0). The synced rows table returns cells keyed by column ID, which makes the missing columns endpoint a hard blocker rather than a nicety.

## Codacy — **thin**

Today (6): `commits`, `files`, `issues`, `organizations`, `pull_requests`, `repositories`

Diffed against: <https://api.codacy.com/api/api-docs/swagger.yaml>

- [ ] `/organizations/{provider}/{org}/people` — Org member lookup resolving the author identities attached to the commits and pull requests already synced (high)
- [ ] `/tools and /tools/{toolUuid}/patterns` — Lookup that resolves the toolUuid and patternId every synced issue carries - without it issues cannot be grouped by rule or linter (high)
- [ ] `/analysis/organizations/{provider}/{org}/repositories/{repo}/commits/{commitUuid}/deltaStatistics and /commits/{srcCommitUuid}/deltaIssues` — New vs fixed issues introduced by each commit - the change-over-time signal the flat issues table cannot produce (high)
- [ ] `/organizations/{provider}/{org}/metrics/{metricName}/period, /period-grouped, /timerange` — Org-level quality metric time series (Codacy's dashboard numbers) precomputed per period (high)
- [ ] `/organizations/{provider}/{org}/security/items and /security/items/search` — Security issues (SRM) with severity and SLA state - an entire product area with no synced table (high)
- [ ] `/analysis/organizations/{provider}/{org}/repositories/{repo}/commit-statistics` — Per-repo commit statistics over time, giving repo health a trend rather than a snapshot (medium)
- [ ] `/analysis/organizations/{provider}/{org}/repositories/{repo}/category-overviews and /issues/overview` — Issue counts broken down by category and severity - the standard reporting breakdown dimensions (medium)
- [ ] `/organizations/{provider}/{org}/repositories/{repo}/branches` — Branch lookup that resolves the branch each analysed commit belongs to (medium)
- [ ] `/organizations/{provider}/{org}/sbom/dependencies/search` — Dependency inventory per org and repo, for supply-chain and license reporting (medium)
- [ ] `/coverage/organizations/{provider}/{org}/repositories/{repo}/pull-requests/{pullRequestNumber} (+ /files)` — Coverage delta per pull request - coverage is completely absent from the current table set (medium)
- [ ] `/organizations/{provider}/{org}/repositories/{repo}/files/{fileId}/coverage and /files/{fileId}/duplication` — File-level coverage and duplication metrics that enrich the files table already synced (medium)
- [ ] `/organizations/{provider}/{org}/audit` — Audit log of org and repo configuration changes, useful for correlating quality shifts with settings changes (low)

Note: Codacy API v3 swagger is served at https://api.codacy.com/api/api-docs/swagger.yaml (~250 paths). Six static endpoints in codacy/settings.py, no dynamic discovery. Whole product domains are unrepresented: security/SRM, SBOM, org metrics time series, and coverage. Excluded config surfaces (coding-standards, gate-policies, settings/\*, tokens, integrations).

## Codecov — gaps

Today (7): `branches`, `commits`, `components`, `coverage_trend`, `flags`, `pulls`, `repos`

Diffed against: <https://api.codecov.io/api/v2/schema>

- [ ] `/{service}/{owner}/repos/{repo}/totals/` — Current coverage totals per repo (lines, hits, misses, partials) - the headline number, only available as a trend today (high)
- [ ] `/{service}/{owner}/repos/{repo}/test-results/ (and /test-results/{id}/)` — Test Analytics: per-test failure rate, flake rate and runtime - Codecov's flagship non-coverage product, entirely unsynced (high)
- [ ] `/{service}/{owner}/repos/{repo}/report/ and /report/tree` — The coverage report broken down by file and directory, which turns repo-level coverage into something actionable (high)
- [ ] `/{service}/{owner}/repos/{repo}/flags/{flag_name}/coverage/` — Coverage trend per flag - the breakdown dimension for the flags table already synced (medium)
- [ ] `/{service}/{owner}/repos/{repo}/file_report/{path}/` — Line-level coverage for a specific file, needed to find persistently uncovered hot spots (medium)
- [ ] `/{service}/{owner}/repos/{repo}/commits/{commitid}/uploads/` — Which CI jobs uploaded coverage for each commit - the way to detect missing or failed uploads skewing coverage (medium)
- [ ] `/{service}/{owner}/users/` — Org member lookup resolving the author IDs on commits and pulls already synced (medium)
- [ ] `/{service}/{owner}/repos/{repo}/compare/impacted_files (also /compare/flags, /compare/components)` — Coverage delta of a pull request by file, flag and component - the review-time metric teams actually track (medium)
- [ ] `/{service}/{owner}/repos/{repo}/test-analytics/` — Aggregated test-suite health summary that pairs with the raw test results (medium)
- [ ] `/{service}/{owner}/` — Owner/org record giving repos an organization-level parent to roll up to (low)

Note: Codecov (now part of Sentry) serves a live drf-spectacular schema at https://api.codecov.io/api/v2/schema. The synced coverage_trend maps to /repos/{repo}/coverage. Core repo/commit/PR objects are covered; the gaps are the coverage detail grains and Test Analytics.

## Codefresh — gaps

Today (6): `builds`, `images`, `pipelines`, `projects`, `step_types`, `triggers`

Diffed against: <https://g.codefresh.io/api/openapi.json>

- [ ] `/builds/tree/{buildId}` — Per-build step tree with status and duration per step - without it a build is a single opaque row and slow-step analysis is impossible (high)
- [ ] `/accounts/{accountId}/users and /team` — User and team lookup that resolves the initiator/committer IDs stamped on every build (high)
- [ ] `/environments-v2 and /environments-v2/activity/{id}` — Deployment environments and their activity history - turns CI build data into deployment/DORA analysis (high)
- [ ] `/gitops/application` — Argo CD application inventory with sync and health state, the GitOps half of the product (medium)
- [ ] `/annotations (and /annotations/keys, /annotations/values/{key})` — Key/value metrics teams attach to builds and images (coverage, test counts) - the custom measures behind build reporting (medium)
- [ ] `/audit` — Account audit log of who changed pipelines and settings, for correlating pipeline changes with build outcomes (medium)
- [ ] `/analytics/reports/{reportName}` — Codefresh's own precomputed analytics reports by granularity and date range, matching its in-app dashboards (medium)
- [ ] `/hermes/events` — Trigger events that actually fired, the counterpart to the triggers table already synced (medium)
- [ ] `/images/{id}/tags` — Tags per image, resolving which build produced which deployed tag against the images table (medium)
- [ ] `/kubernetes/releases (and /k8s/releases/withoutSecrets)` — Helm releases deployed per cluster, linking pipelines to what is actually running (low)
- [ ] `/clusters` — Cluster inventory that gives releases and environments a deployment-target dimension (low)
- [ ] `/repos` — Connected git repositories, the source dimension for pipelines and builds (low)

Note: Codefresh serves its OpenAPI 3 spec unauthenticated at https://g.codefresh.io/api/openapi.json (312 paths, 180 with GET). The synced `builds` table maps to GET /workflow. Much of the remaining surface is config/admin (contexts, registries, runtime-environments, ABAC, auth keys) and correctly excluded; the real gaps are step-level build data, identity lookups, and the GitOps/deployment side.

## Codemagic — adequate

Today (2): `Applications`, `Builds`

Diffed against: <https://docs.codemagic.io/rest-api/codemagic-rest-api/>

No material gaps found.

Note: The whole public REST API is four doc pages (applications, artifacts, builds, caches), confirmed via https://docs.codemagic.io/sitemap.xml. Only two of those are queryable collections: GET /apps and GET /builds, both already synced. Artifacts is a binary download / public-url mint (GET /artifacts/:secureFilename), and caches is GET+DELETE /apps/:id/caches, i.e. build-infrastructure plumbing rather than an analytical table.

## Codescene — **thin**

Today (3): `Components`, `Files`, `Projects`

Diffed against: <https://docs.enterprise.codescene.io/latest/integrations/rest-api.html>

- [ ] `projects/{project-id}/analyses` — the analysis-run history; without it every synced table is a single 'latest' snapshot with no trend and no way to pin an analysis id (high)
- [ ] `projects/{project-id}/analyses/latest/issues` — code health issues (hotspots, brain classes) - the product's core finding table (high)
- [ ] `projects/{project-id}/analyses/latest/technical-debt` — technical debt and refactoring targets, CodeScene's headline metric (high)
- [ ] `projects/{project-id}/analyses/latest/author-statistics` — per-author contribution stats; the only way to join code health to people (high)
- [ ] `projects/{project-id}/analyses/latest/commits` — commit-level rows underpinning every aggregate CodeScene reports (medium)
- [ ] `projects/{project-id}/analyses/latest/commit-activity` — commit activity time series for delivery-rate dashboards (medium)
- [ ] `projects/{project-id}/analyses/latest/branch-statistics` — per-branch stats for branching-strategy and lead-time analysis (medium)
- [ ] `projects/{project-id}/delta-analyses` — per-PR delta analyses - the state/transition history of quality per change (medium)
- [ ] `code-coverage/projects/{project-id}/gate-results/outcomes` — coverage quality-gate pass/fail outcomes over a date range (medium)
- [ ] `code-health/projects/{project-id}/safeguards/pr/outcomes` — PR safeguard outcomes, the enforcement signal teams report on (medium)
- [ ] `active-authors` — authoritative author roster; a lookup table for the author ids appearing in analyses (medium)
- [ ] `projects/{project-id}/analyses/latest/experience/languages` — author language experience, used for knowledge-risk and bus-factor reporting (low)

Note: Static endpoint list; no dynamic table discovery in products/warehouse_sources/backend/temporal/data_imports/sources/codescene/settings.py (three hardcoded CODESCENE_ENDPOINTS). The v2 API exposes ~100 paths; PostHog covers 3, and notably syncs only the 'latest' analysis with no analysis history.

## Cody — adequate

Today (5): `credits`, `usage_by_user`, `usage_by_user_day`, `usage_by_user_day_client_language`, `usage_by_user_month`

Diffed against: <https://sourcegraph.com/docs/analytics/api.md>

No material gaps found.

Note: The Sourcegraph Analytics API has exactly two endpoints: GET /api/reports/by-user-client-date (granularity = by_user | by_user_month | by_user_day | by_user_day_client_language) and GET /api/credits. PostHog's five tables map 1:1 onto all four granularities plus credits, so coverage is complete. Note the docs page is client-rendered; the .md variant of the URL returns the full text.

## Cohere — gaps

Today (5): `connectors`, `datasets`, `embed_jobs`, `finetuned_models`, `models`

Diffed against: <https://raw.githubusercontent.com/cohere-ai/cohere-developer-experience/main/cohere-openapi.yaml>

- [ ] `GET /v2/batches (ListBatches)` — batch inference jobs with status and token counts - the only remaining job/usage table not synced (medium)
- [ ] `GET /v1/finetuning/finetuned-models/{id}/events (ListEvents)` — fine-tune job state-transition history; resolves how a synced finetuned_model reached its status (medium)
- [ ] `GET /v1/finetuning/finetuned-models/{id}/training-step-metrics (ListTrainingStepMetrics)` — per-step training loss/accuracy for evaluating fine-tunes (medium)

Note: Cohere's API is overwhelmingly POST inference (chat, embed, rerank, classify, summarize, tokenize) which is not warehouse material. Of the GET list endpoints in the spec, PostHog already syncs datasets, connectors, models, finetuned-models and embed-jobs; the three above are the genuine remainder. /v1/datasets/usage is a single-row quota reading and /v1/check-api-key is auth plumbing, both excluded.

## CoinApi — gaps

Today (6): `assets`, `exchange_rates`, `exchanges`, `ohlcv_history`, `symbols`, `trades_history`

Diffed against: <https://raw.githubusercontent.com/api-bricks/api-bricks-sdk/master/coinapi/market-data-api-rest/spec/openapi.json>

- [ ] `/v1/quotes/{symbol_id}/history` — historical bid/ask quote timeseries - the main analytical series alongside trades and OHLCV (high)
- [ ] `/v1/metrics/listing` — catalogue of every metric id CoinAPI supports; the lookup table needed to make any metrics sync interpretable (high)
- [ ] `/v1/metrics/symbol/history` — funding rate, open interest and other derivative metrics per symbol - resolves ids from the symbols table we already sync (high)
- [ ] `/v1/exchangerate/{asset_id_base}/{asset_id_quote}/history` — historical FX timeseries; today only the current-rate snapshot is synced (high)
- [ ] `/v1/orderbooks/{symbol_id}/history` — historical order book snapshots for liquidity and spread analysis (medium)
- [ ] `/v1/metrics/exchange/history` — per-exchange metric history joining to the exchanges table already synced (medium)
- [ ] `/v1/metrics/asset/history` — per-asset metric history joining to the assets table already synced (medium)
- [ ] `/v1/ohlcv/periods` — lookup of valid period_id values that the synced ohlcv_history is parameterised by (medium)
- [ ] `/v1/symbols/map/{exchange_id}` — maps CoinAPI symbol_id to each exchange's native symbol - the join key for blending in exchange-side data (medium)
- [ ] `/v1/chains` — blockchain/chain metadata lookup for assets (medium)
- [ ] `/v1/ohlcv/exchanges/{exchange_id}/history` — exchange-wide candles without enumerating every symbol (medium)
- [ ] `/v1/options/{exchange_id}/current` — options chain snapshots per exchange (low)

Note: docs.coinapi.io is behind a Cloudflare interstitial and returns 403 to curl; the machine-readable spec lives instead at api-bricks/api-bricks-sdk (the repo coinapi/coinapi-sdk now redirects to). The spec also carries a newer /v2/metrics/\* family (asset, chain, exchange listing+history) that supersedes /v1/metrics - worth preferring v2 when implementing the metrics gaps.

## CoinGecko — gaps

Today (7): `asset_platforms`, `coins_categories`, `coins_categories_list`, `coins_list`, `coins_markets`, `exchanges`, `exchanges_list`

Diffed against: <https://docs.coingecko.com/llms.txt>

- [ ] `/coins/{id}/market_chart/range` — historical price, market cap and volume timeseries - the headline series; today only a current-price snapshot is synced (high)
- [ ] `/coins/{id}/ohlc/range` — OHLC candles per coin over an arbitrary range, needed for any price analysis (high)
- [ ] `/global` — total crypto market cap, active coins and BTC dominance - CoinGecko's flagship market-wide metric (high)
- [ ] `/global/market_cap_chart` — historical global market cap and volume, the time series behind the above (high)
- [ ] `/coins/{id}/tickers` — market pairs per coin on CEX and DEX - the join that resolves coins_list against exchanges_list, which we sync but cannot currently link (high)
- [ ] `/exchanges/{id}/tickers` — trading pairs per exchange; the other half of the coin-to-exchange lookup (medium)
- [ ] `/exchanges/{id}/volume_chart/range` — historical exchange volume for ranking exchanges over time (medium)
- [ ] `/simple/supported_vs_currencies` — lookup of valid vs_currency codes that coins_markets is parameterised by (currently hardcoded to usd) (medium)
- [ ] `/coins/{id}/history` — single-day historical snapshot per coin, cheap way to build a daily fact table (medium)
- [ ] `/exchange_rates` — BTC-to-currency rates, the standard normaliser for cross-currency reporting (medium)
- [ ] `/derivatives/exchanges and /derivatives/tickers` — derivatives venues and open interest, entirely absent from current coverage (medium)
- [ ] `/nfts/markets` — NFT collections with floor price, market cap and volume - a whole product surface with no table today (medium)

Note: docs.coingecko.com/reference/\* pages are client-rendered and unparseable by curl, but llms.txt enumerates every reference page (Demo and Pro) with descriptions, and any single page can be fetched by appending .md. The onchain/GeckoTerminal family (networks, dexes, pools, token holders, pool trades) is a further ~35 endpoints with zero coverage; treated as a separate product rather than listed individually here.

## CoinMarketCap — gaps

Today (5): `categories`, `cryptocurrency_map`, `exchange_map`, `fiat_map`, `listings_latest`

Diffed against: <https://pro.coinmarketcap.com/api/documentation/pro-api-reference/cryptocurrency.md>

- [ ] `GET /v3/cryptocurrency/quotes/historical` — historical price, market cap and volume per coin - the core fact table; today only listings/latest snapshots exist (high)
- [ ] `GET /v2/cryptocurrency/ohlcv/historical` — daily OHLCV candles, required for any price or return analysis (high)
- [ ] `GET /v1/global-metrics/quotes/historical` — total market cap, BTC dominance and altcoin market cap over time - CMC's headline market metric (high)
- [ ] `GET /v2/cryptocurrency/info` — coin metadata (tags, platform, category, urls) that resolves the ids in the cryptocurrency_map we already sync (high)
- [ ] `GET /v1/exchange/listings/latest` — ranked exchanges with volume and liquidity; exchange_map alone carries no metrics (high)
- [ ] `GET /v1/exchange/info` — exchange metadata lookup resolving the ids in the synced exchange_map (medium)
- [ ] `GET /v1/cryptocurrency/listings/historical` — historical ranked snapshots, letting you reconstruct rank changes without polling listings/latest (medium)
- [ ] `GET /v2/cryptocurrency/market-pairs/latest` — per-coin market pairs and where volume actually trades (medium)
- [ ] `GET /v1/exchange/market-pairs/latest` — per-exchange market pairs; joins exchanges to cryptocurrencies (medium)
- [ ] `GET /v1/exchange/quotes/historical` — historical exchange volume for venue share analysis (medium)
- [ ] `GET /v1/cryptocurrency/category` — coin membership per category - the categories table we sync lists categories but not their constituents (medium)
- [ ] `GET /v3/fear-and-greed/historical` — CMC's proprietary sentiment index over time, a commonly requested signal (medium)

Note: coinmarketcap.com/api/documentation is a client-rendered zudoku app, but every page is served as markdown by appending .md, and pro.coinmarketcap.com/llms.txt indexes the whole reference by family (Cryptocurrency 19, Exchange 7, Global Metrics 6, DEX/Token 16, Holder 5, Derivatives 3, RWA 7, CMC Index 4...). PostHog's five tables are all lookup/snapshot endpoints; every historical family is absent. The DEX (Token/Pool/Holder/OHLCV) and Real World Assets families are also entirely uncovered but are treated as separate products rather than enumerated here.

## Commercetools — gaps

Today (8): `carts`, `categories`, `customers`, `discount_codes`, `inventory`, `orders`, `payments`, `product_projections`

Diffed against: <https://raw.githubusercontent.com/commercetools/commercetools-api-reference/main/oas/api/openapi.yaml>

- [ ] `/{projectKey}/messages` — the change-event stream (OrderStateChanged, PaymentStatusChanged, CustomerCreated...) - state and transition history for everything we already sync (high)
- [ ] `/{projectKey}/product-types` — lookup resolving the productType id carried on every synced product projection (high)
- [ ] `/{projectKey}/states` — lookup resolving the state ids on orders, payments, products and reviews; without it order state is an opaque uuid (high)
- [ ] `/{projectKey}/customer-groups` — lookup resolving customerGroup on customers, carts and orders - the standard segmentation dimension (high)
- [ ] `/{projectKey}/channels` — lookup resolving supplyChannel and distributionChannel ids on the inventory and orders we sync (high)
- [ ] `/{projectKey}/stores` — lookup resolving the store on orders and carts; required for any per-store revenue breakdown (high)
- [ ] `/{projectKey}/shipping-methods` — lookup resolving the shipping method id on orders, plus its zone and rate structure (medium)
- [ ] `/{projectKey}/products` — full product master data including staged versus current, which product-projections flattens away (medium)
- [ ] `/{projectKey}/cart-discounts` — resolves the discount ids applied to synced carts and orders; discount_codes alone does not explain the discount (medium)
- [ ] `/{projectKey}/product-discounts` — explains discounted prices appearing on product projections (medium)
- [ ] `/{projectKey}/standalone-prices` — prices held outside the product, so price analysis on product-projections alone is incomplete (medium)
- [ ] `/{projectKey}/shopping-lists` — wishlist and saved-cart behavior, a common pre-purchase funnel table (medium)

Note: The full OpenAPI (292 paths) is published at commercetools/commercetools-api-reference under oas/api/openapi.yaml; the docs site itself is navigational only. Static endpoint config in sources/commercetools/settings.py, no dynamic discovery. Also uncovered but lower value: reviews, payment-methods, business-units and associate-roles (B2B), quotes/quote-requests/staged-quotes, recurring-orders and recurrence-policies, tax-categories, zones, orders/edits. Excluded as config or plumbing: subscriptions, extensions, api-clients, types, custom-objects, product-selections.

## Concord — gaps

Today (10): `agreements`, `approvals`, `clauses`, `events`, `folders`, `groups`, `members`, `organizations`, `reports`, `tags`

Diffed against: <https://api.doc.concordnow.com/concord-openapi-bundled.yaml>

- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/members` — agreement<->user junction: who has access, their permission and signer role (high)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/summary/fields` — smart fields (contract value, renewal date, term) - the analytical dimensions of a contract (high)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/signature` — signature state and signer slots per agreement; drives time-to-signature (high)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/approval` — per-agreement approval state, joins the approvals table we already sync to its contract (high)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/activities` — per-agreement activity timeline (sent, viewed, signed) at finer grain than the org events feed (high)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/summary/clauses (and /summary/endclauses)` — clause instances per agreement - the junction to the clauses lookup table already synced (high)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/versions` — contract version history for redline/negotiation-cycle analysis (medium)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/metadata` — structured metadata fields beyond the agreement record (medium)
- [ ] `GET /organizations/{organizationId}/agreements/{agreementUid}/comments` — negotiation comment thread per agreement (medium)
- [ ] `GET /organizations/{organizationId}/folders/{folderId}/agreements` — folder->agreement membership; resolves the folders table already synced to its contents (low)

Note: Bundled OpenAPI 3.1 spec (redoc spec-url from api.doc.concordnow.com). Top-level collections are well covered; every gap is a per-agreement sub-resource, so implementing them means fanning out over the agreements table.

## ConfigCat — **thin**

Today (2): `organizations`, `products`

Diffed against: <https://api.configcat.com/docs/v1/swagger.json>

- [ ] `GET /v1/products/{productId}/configs` — config lookup table; every setting and value row is keyed by configId (high)
- [ ] `GET /v1/products/{productId}/environments` — environment lookup table; flag values are per environment (high)
- [ ] `GET /v1/configs/{configId}/settings` — the feature flag / setting catalog - the product's headline object (high)
- [ ] `GET /v2/configs/{configId}/environments/{environmentId}/values` — flag values and targeting rules per environment; what is actually rolled out where (high)
- [ ] `GET /v2/products/{productId}/auditlogs and /v2/organizations/{organizationId}/auditlogs` — change history - who flipped which flag when (high)
- [ ] `GET /v1/products/{productId}/segments` — reusable targeting segments referenced by flag rules (medium)
- [ ] `GET /v1/products/{productId}/tags (and /v1/tags/{tagId}/settings)` — tag lookup plus the tag->setting junction (medium)
- [ ] `GET /v2/organizations/{organizationId}/members and /v1/products/{productId}/members` — user membership and product access (medium)
- [ ] `GET /v1/products/{productId}/staleflags` — stale-flag report - the standard cleanup/tech-debt query (medium)
- [ ] `GET /v1/products/{productId}/permissions` — permission group lookup resolving member role ids (low)
- [ ] `GET /v1/settings/{settingId}/code-references` — where each flag is referenced in source, for removal analysis (low)
- [ ] `GET /v1/configs/{configId}/deleted-settings` — deleted flags, needed to keep historical joins from dangling (low)

Note: Source exposes 2 static endpoints (settings.py CONFIGCAT_ENDPOINTS = products, organizations) with no dynamic discovery - confirmed in products/warehouse_sources/backend/temporal/data_imports/sources/configcat/source.py. The vendor spec has ~48 GET operations. The entire config/environment/setting model - i.e. what ConfigCat actually is - is unsynced. Note: I include feature-flag 'settings' despite the generic exclusion on feature flags, because here they are the vendor's core catalog object, not incidental plumbing.

## Confluence — gaps

Today (8): `attachments`, `blogposts`, `footer_comments`, `inline_comments`, `labels`, `pages`, `spaces`, `tasks`

Diffed against: <https://dac-static.atlassian.com/cloud/confluence/openapi-v2.v3.json>

- [ ] `GET /wiki/rest/api/user, /user/bulk, /search/user (v1)` — user lookup table; pages, blogposts and comments all carry authorId/ownerId with no way to resolve them today (high)
- [ ] `GET /wiki/rest/api/analytics/content/{contentId}/views and /viewers (v1)` — page view and unique-viewer counts - the headline content metric for a wiki (high)
- [ ] `GET /pages/{id}/versions and /blogposts/{id}/versions` — edit history per page: who changed what and when, the basis of contribution analysis (high)
- [ ] `GET /wiki/rest/api/group and /group/{groupId}/membersByGroupId (v1)` — group definitions plus the group->user membership junction (medium)
- [ ] `GET /custom-content` — the fourth listable content type in v2, entirely unsynced (medium)
- [ ] `GET /spaces/{id}/permissions, /spaces/{id}/role-assignments, /space-roles` — who can do what in each space - access review and least-privilege reporting (medium)
- [ ] `GET /wiki/rest/api/audit (v1)` — admin audit record stream: permission and configuration changes over time (medium)
- [ ] `GET /pages/{id}/likes/count and /footer-comments/{id}/likes/count` — engagement counts per page and comment (low)
- [ ] `GET /whiteboards/{id}, /databases/{id}, /embeds/{id}, /folders/{id} (+ /descendants)` — the remaining v2 content types; reachable only via space/page descendant walks (low)
- [ ] `GET /classification-levels and /pages/{id}/classification-level` — data classification lookup for governance reporting (low)

Note: Diffed against the v2 spec above; the users, groups, analytics and audit gaps come from the v1 spec at https://dac-static.atlassian.com/cloud/confluence/swagger.v3.json, since v2 has no user/analytics endpoints. Content types whiteboards/databases/embeds/folders exist in v2 only as fetch-by-id plus ancestors/descendants - there is no top-level list - so they are harder than the rest.

## ConfluentCloud — gaps

Today (7): `compute_pool_metrics`, `connector_metrics`, `kafka_metrics`, `ksqldb_metrics`, `metric_descriptors`, `resource_descriptors`, `schema_registry_metrics`

Diffed against: <https://api.telemetry.confluent.cloud/v2/metrics/cloud/descriptors/resources>

- [ ] `GET /cmk/v2/clusters (Cloud API)` — Kafka cluster inventory (name, cloud, region, availability, CKU) - the lookup for kafka.id in kafka_metrics (high)
- [ ] `GET /org/v2/environments (Cloud API)` — environment lookup; every cluster, pool and connector rolls up to one (high)
- [ ] `GET /billing/v1/costs (Cloud API)` — daily cost line items per resource - the spend question metrics alone cannot answer (high)
- [ ] `GET /kafka/v3/clusters/{cluster_id}/consumer-groups (+ /lag-summary, /lags)` — consumer group inventory and per-group lag, the core operational health metric (high)
- [ ] `GET /connect/v1/environments/{env}/clusters/{cluster}/connectors (+ /status)` — connector inventory and running state - lookup for connector_metrics rows (medium)
- [ ] `Telemetry resource type flink_statement (/v2/metrics/cloud/query grouped by flink_statement.uid)` — Flink statement metrics; a declared resource type the source does not expose (medium)
- [ ] `Telemetry resource type flink_materialized_table` — Flink materialized table metrics; the other unexposed declared resource type (medium)
- [ ] `GET /fcpm/v2/compute-pools (Cloud API)` — compute pool lookup resolving compute_pool.id in compute_pool_metrics (medium)
- [ ] `GET /kafka/v3/clusters/{cluster_id}/topics (+ /partitions)` — topic inventory and partition counts for per-topic throughput and cost attribution (medium)
- [ ] `GET /sql/v1/organizations/{org}/environments/{env}/statements` — Flink statement inventory - lookup for the flink_statement metrics above (medium)
- [ ] `GET /iam/v2/service-accounts and /iam/v2/users` — principal lookup for ACL, role-binding and API-key attribution (medium)
- [ ] `GET /iam/v2/role-bindings` — principal->resource access membership table (medium)

Note: Source is deliberately scoped to the Telemetry Metrics API only (settings.py pins CONFLUENT_CLOUD_BASE_URL=api.telemetry.confluent.cloud, DATASET='cloud'); metric names are discovered from the descriptor endpoints at sync time, so per-resource metric coverage is broad. Two of the seven telemetry resource types (flink_statement, flink_materialized_table) are not wired. The larger opportunity is the Confluent Cloud management API, whose spec I also fetched at https://docs.confluent.io/cloud/current/openapi.yaml - it supplies every lookup table the metric rows reference.

## ConvertKit — gaps

Today (8): `broadcasts`, `custom_fields`, `email_templates`, `forms`, `purchases`, `sequences`, `subscribers`, `tags`

Diffed against: <https://developers.kit.com/llms.txt>

- [ ] `GET /v4/broadcasts/stats (get-stats-for-a-list-of-broadcasts) and /v4/broadcasts/{id}/stats` — opens, clicks, unsubscribes per broadcast - the headline email metric; broadcasts sync today with no performance data (high)
- [ ] `GET /v4/tags/{id}/subscribers` — tag<->subscriber junction; without it the synced tags table cannot be joined to people (high)
- [ ] `GET /v4/forms/{id}/subscribers` — form<->subscriber junction, the signup-source attribution table (high)
- [ ] `GET /v4/sequences/{id}/subscribers` — sequence membership and per-subscriber sequence state (high)
- [ ] `GET /v4/segments` — segment lookup table, entirely unsynced (high)
- [ ] `GET /v4/sequences/{id}/emails (list-sequence-emails)` — the individual emails inside each sequence - line items for the sequences already synced (medium)
- [ ] `GET /v4/broadcasts/{id}/clicks (get-link-clicks-for-a-broadcast)` — per-link click breakdown within a broadcast (medium)
- [ ] `GET /v4/subscribers/{id}/stats` — per-subscriber engagement (opens, clicks) for cohort and churn analysis (medium)
- [ ] `GET /v4/account/growth_stats` — subscriber growth, cancellations and net new over a date range (medium)
- [ ] `GET /v4/account/email_stats` — account-level send, open and click totals (medium)
- [ ] `GET /v4/posts` — published newsletter posts, the public content catalog (medium)
- [ ] `GET /v4/snippets` — reusable content snippets referenced by broadcasts and sequences (low)

Note: Kit (formerly ConvertKit) publishes a complete llms.txt index of its v4 API reference; each operation also has a .md variant. Core objects are synced but every engagement metric and every subscriber-membership junction is missing.

## Copper — gaps

Today (11): `companies`, `contact_types`, `customer_sources`, `leads`, `loss_reasons`, `opportunities`, `people`, `pipelines`, `projects`, `tasks`, `users`

Diffed against: <https://developer.copper.com/index.html>

- [ ] `POST /v1/activities/search` — the CRM interaction log (calls, emails, notes, status changes) - the main analytical event stream, entirely unsynced (high)
- [ ] `GET /v1/pipeline_stages (and /v1/pipelines/{id}/stages)` — stage lookup; opportunities carry pipeline_stage_id and pipelines is already synced, so funnel analysis is blocked on this one table (high)
- [ ] `GET /v1/lead_statuses` — status lookup; every lead row carries status_id with nothing to resolve it against (high)
- [ ] `GET /v1/activity_types (and /v1/custom_activity_types)` — lookup resolving activity_type on activity rows; also needed to separate user activity from system activity (high)
- [ ] `GET /v1/custom_field_definitions` — resolves custom_field_definition_id, which appears on companies, people, leads, opportunities and projects (high)
- [ ] `GET /v1/tags` — tag lookup for segmenting every record type (medium)
- [ ] `GET /v1/related_items (view all records related to an entity)` — cross-object relationship junction linking companies, people, opportunities and projects (medium)
- [ ] `GET /v1/{entity}/{id}/activities (see a company's / person's / lead's activities)` — per-record activity fan-out when the global activity search is too coarse (low)
- [ ] `GET /v1/field_layouts/{entity_type}` — field layout metadata for interpreting per-pipeline custom field sets (low)

Note: MkDocs site; its nav enumerates every operation one page per endpoint, which is what I diffed against. Copper already exposes most lookup tables (contact_types, customer_sources, loss_reasons, pipelines) - the notable omissions are the remaining lookups plus the activity log.

## Coralogix — gaps

Today (2): `logs`, `spans`

Diffed against: <https://coralogix.com/docs/developer-portal/apis/data-management/cases-api>

- [ ] `CasesService/ListCases` — case records with status, priority, assignee and timestamps - the incident-analytics object (high)
- [ ] `CaseEventsService/ListEvents` — case activity timeline: the state-transition history behind MTTA/MTTR (high)
- [ ] `Metrics query API (PromQL, /docs/user-guides/data-query/metrics-api)` — metrics are the third telemetry pillar; logs and spans sync today and metrics do not (high)
- [ ] `IncidentsService list/aggregate incidents` — legacy equivalent of Cases, still the only surface for accounts not migrated (high)
- [ ] `Alerts API v3 (list alert definitions)` — lookup resolving the alert ids carried on cases and incidents (medium)
- [ ] `SLO management API (list SLOs and SLO status)` — SLO targets and burn state, the standard reliability report (medium)
- [ ] `CasesNotificationService/ListNotificationDeliveries` — routing, target and outcome per case notification - paging effectiveness analysis (medium)
- [ ] `Data usage service API / metrics usage API` — ingestion volume and cost per day and per application, the TCO question (medium)
- [ ] `Insights API` — Coralogix-generated anomaly and benchmark insights over the same data (medium)

Note: The source runs DataPrime direct-archive queries and its two tables map to the two archive data sources (`source logs` / `source spans`) - confirmed in coralogix/settings.py, so it is not artificially thin on the query side. Everything below sits behind separate APIs, most of them gRPC (grpcurl against api.<domain>:443), which is a different transport than the existing HTTP archive-query client. Coralogix also states Cases is replacing Incidents, so implement Cases first and Incidents only for legacy accounts.

## Cortex — gaps

Today (7): `entities`, `entity_types`, `relationship_types`, `relationships`, `scorecard_scores`, `scorecards`, `teams`

Diffed against: <https://docs.cortex.io/llms.txt>

- [ ] `GET /api/v1/catalog/{tagOrId}/deploys` — deployment events per entity - deploy frequency and lead time, the headline Eng Intelligence metric (high)
- [ ] `GET /api/v1/users` — user lookup with profile and role assignments; resolves entity owners and team members (high)
- [ ] `GET /api/v1/catalog/{tagOrId}/custom-events` — arbitrary per-entity event stream (incidents, migrations, releases) pushed into Cortex (high)
- [ ] `GET /api/v1/initiatives` — scorecard-driven improvement campaigns and their progress - the main remediation-tracking object (high)
- [ ] `GET /api/v1/catalog/{callerTag}/dependencies` — service dependency graph edges; distinct from the entity-relationships already synced (high)
- [ ] `GET /api/v1/catalog/{tagOrId}/groups` — entity group membership junction - the tagging dimension most scorecard filters use (medium)
- [ ] `GET /api/v1/teams/relationships (team hierarchies)` — parent/child team edges; teams sync today with no hierarchy to roll up by (medium)
- [ ] `Custom metrics data points (Eng Intelligence)` — per-entity time series for custom KPIs alongside scorecard scores (medium)
- [ ] `GET /api/v1/catalog/{tagOrId}/packages` — package and library inventory per entity, for dependency and vulnerability rollups (medium)
- [ ] `Audit logs (retrieve audit logs)` — who changed catalog, scorecards and settings over time (medium)
- [ ] `GET /api/v1/catalog/{tagOrId}/custom-data` — per-entity custom key/value data - user-defined dimensions for slicing entities (medium)
- [ ] `GET /api/v1/catalog/{tagOrId}/integrations/oncall/current` — on-call ownership per entity, needed to join incidents to responders (medium)

Note: Cortex publishes an llms.txt index and every API page has a .md variant embedding the OpenAPI fragment (e.g. https://docs.cortex.io/api/readme/deploys.md); I read the operation lists from those. Catalog/scorecard coverage is good; the gaps are the per-entity event and inventory streams, which all require fanning out over the entities table by tagOrId.

## Coupa — **thin**

Today (8): `approvals`, `contracts`, `expense_reports`, `invoices`, `purchase_orders`, `requisitions`, `suppliers`, `users`

Diffed against: <https://compass.coupa.com/en-us/products/product-documentation/integration-technical-documentation/the-coupa-core-api/resources>

- [ ] `/invoices/{id}/lines (Invoice Line API, plus Invoice Charge / Tax Line)` — line-item grain for invoices already synced; without it spend cannot be broken down by item, account, or tax (high)
- [ ] `/purchase_orders/{id}/order_lines (Purchase Order Lines API)` — line items for POs already synced - the unit almost every spend analysis aggregates (high)
- [ ] `/requisitions/{id}/requisition_lines (Requisition Line API)` — line items behind requisitions already synced, needed for req-to-PO conversion analysis (high)
- [ ] `/expense_reports/{id}/expense_lines (Expense Lines API)` — per-line expense detail with category and allocation; expense_reports alone is only a header (high)
- [ ] `/accounts (plus /account_types)` — chart-of-accounts lookup that resolves the account IDs carried on every PO, invoice, and expense allocation (high)
- [ ] `/commodities` — spend category lookup referenced by requisitions, POs, and invoices; the standard breakdown dimension (high)
- [ ] `/departments` — lookup resolving the department IDs on users, requisitions, and approvals (high)
- [ ] `/receiving_transactions (Receipts API)` — goods-receipt transactions needed for three-way match and PO fulfillment analysis (high)
- [ ] `/items and /supplier_items` — catalog item lookup resolving item IDs on PO and requisition lines (medium)
- [ ] `/coupa_pay/payments and /coupa_pay/statements` — actual payment transactions closing the invoice-to-cash loop (medium)
- [ ] `Order Line Allocations and Req Line Allocation APIs` — cost-center/account splits per line - the breakdown dimension for allocated spend (medium)
- [ ] `/purchase_orders/{id}/changes (Purchase Order Change / Revisions API)` — PO amendment history for change-order and cycle-time analysis (medium)

Note: Coupa Core API is very large (several hundred documented resources across Reference, Shared, and Transactional groups). PostHog exposes 8 header-level objects and no line-level or lookup tables, so nearly all analytical grain is missing. The linked doc in the payload is the legacy Compass page; the maintained index is docs.coupa.com. A GraphQL API and flat-file (CSV) export path also exist.

## Courier — gaps

Today (5): `Audiences`, `AuditEvents`, `Brands`, `Messages`, `Tenants`

Diffed against: <https://www.courier.com/docs/llms.txt>

- [ ] `lists (GET /lists)` — core recipient grouping object; currently no way to see which lists exist (high)
- [ ] `lists/{list_id}/subscriptions` — membership table mapping users to lists - required for any audience-size or churn analysis (high)
- [ ] `notification-templates (GET /notifications)` — lookup table resolving the template IDs carried on every synced message (high)
- [ ] `messages/{id}/history` — per-message state transition history (queued, sent, delivered, opened, clicked) - the deliverability funnel (high)
- [ ] `audiences/{audience_id}/members` — membership table for audiences we already sync; audiences without members are just filter definitions (high)
- [ ] `tenants/{tenant_id}/users` — membership table joining users to the tenants we already sync (medium)
- [ ] `automations (GET /automations)` — lookup for saved automation templates that trigger sends (medium)
- [ ] `journeys (GET /journeys, plus journey versions)` — journey definitions and versions needed to attribute messages to a flow (medium)
- [ ] `digests (list digest instances)` — digest batching data explaining why messages were grouped or delayed (medium)
- [ ] `notification-templates/{id}/versions` — template version history for before/after performance comparison (low)
- [ ] `workspace-preferences (topics and sections)` — lookup for subscription topics referenced by user preference data (low)
- [ ] `user-preferences (GET /users/{id}/preferences)` — per-user subscription state for opt-out analysis (low)

Note: The payload's docs URLs (www.courier.com/docs/reference/...) now 404; the live reference lives under /docs/api-reference/ and is indexed in llms.txt. Providers and routing-strategies were excluded as configuration.

## Coveralls — adequate

Today (2): `builds`, `repositories`

Diffed against: <https://docs.coveralls.io/api-introduction>

No material gaps found.

Note: Coveralls has an unusually small read surface: only GET /api/v1/repos is a real read endpoint (/jobs is POST-only, plus two write webhooks). Everything else is 'JSON-Format Web Data' - appending .json to a web URL. PostHog's repositories + builds tables cover both listable feeds. The remaining resources (jobs/{id}.json, files/{id}.json per-line coverage arrays) have no listing endpoint and are documented as requiring a logged-in web session OAuth token rather than the API token, so they are not practically syncable. Source is static (products/warehouse_sources/backend/temporal/data_imports/sources/coveralls), no dynamic discovery, but that matches the API.

## CratesIO — gaps

Today (4): `crates`, `downloads`, `owners`, `versions`

Diffed against: <https://crates.io/api/openapi.json>

- [ ] `/api/v1/crates/{name}/{version}/dependencies` — per-version dependency edges - the dependency graph is the main analytical object crates.io exposes (high)
- [ ] `/api/v1/crates/{name}/reverse_dependencies` — who depends on your crate; the headline adoption metric for a crate owner (high)
- [ ] `/api/v1/categories (and /api/v1/category_slugs)` — lookup table resolving the category slugs carried on every crate record (medium)
- [ ] `/api/v1/keywords` — lookup table resolving the keyword IDs on crates, plus per-keyword crate counts (medium)
- [ ] `/api/v1/users/{user} and /api/v1/teams/{team}` — lookup resolving the user/team IDs returned by the owners endpoints (low)
- [ ] `/api/v1/crates/{name}/{version}/downloads` — per-version download series, finer grain than the crate-level downloads table (low)

Note: Verified against the live OpenAPI document at https://crates.io/api/openapi.json (returns 403 without a descriptive User-Agent - crates.io requires one). The payload's https://crates.io/data-access page now 404s. Source is static: the user supplies a crate list and PostHog fans out per crate.

## Cronitor — gaps

Today (3): `invocations`, `metrics`, `monitors`

Diffed against: <https://cronitor.io/docs/api.md>

- [ ] `GET /api/issues` — incidents with state, severity, and start/resolve timestamps - the core reliability object, filterable and listable (high)
- [ ] `GET /api/groups` — lookup table resolving the group each synced monitor belongs to; enables per-service rollups (high)
- [ ] `GET /api/site_errors` — RUM JavaScript errors, the analytical event stream for the Sites product (medium)
- [ ] `GET /api/sites` — lookup for RUM sites that site_errors and RUM analytics rows reference (medium)
- [ ] `RUM analytics query endpoint (aggregate/breakdown/timeseries over sites)` — pageviews, web vitals, and top-pages breakdowns - the headline RUM metrics (medium)
- [ ] `GET /api/maintenance_windows` — scheduled maintenance periods needed to exclude planned downtime from uptime and alert analysis (medium)
- [ ] `GET /api/environments` — lookup resolving the environment tag on telemetry, invocations, and monitors (low)

Note: Notifications, API keys, and status pages were excluded as configuration. Telemetry API is write-only ingestion. Source is static (three endpoints in cronitor/cronitor.py), no dynamic table discovery.

## Crunchbase — gaps

Today (7): `acquisitions`, `funding_rounds`, `funds`, `investments`, `ipos`, `organizations`, `people`

Diffed against: <https://data.crunchbase.com/llms.txt>

- [ ] `jobs (POST /searches/jobs)` — person-to-organization employment membership table joining the two entities we already sync (high)
- [ ] `categories and category_groups (and microcategories)` — lookup tables resolving the category UUIDs on every organization record (high)
- [ ] `locations` — lookup resolving the location UUIDs on organizations, people, and funding rounds (high)
- [ ] `ownerships` — parent/subsidiary relationships between organizations; needed to roll spend or funding up a corporate tree (medium)
- [ ] `key_employee_changes` — executive-change event stream, a standard signal for sales and investment triggers (medium)
- [ ] `layoffs` — layoff event stream with dates and headcount, a headline distress signal (medium)
- [ ] `press_references` — news mentions per organization, commonly used for momentum scoring (medium)
- [ ] `degrees` — education records for the people we already sync; the counterpart to jobs (medium)
- [ ] `addresses` — structured address rows referenced by organizations and events (medium)
- [ ] `events and event_appearances` — conference participation per organization/person, a common enrichment dimension (low)
- [ ] `products and product_launches` — product-level records and launch dates for organizations already synced (low)
- [ ] `principals` — unified person/org principal entity that resolves investor references on funding rounds (low)

Note: Verified from the v4 OpenAPI index in llms.txt (search endpoints per collection). Crunchbase also sells separate Insights and Predictions packages (growth_insights, funding/acquisition/ipo/layoff/closure predictions, investor_matches, org_similarities) that are entitlement-gated and were not scored as core gaps. Machine-readable spec is available at data.crunchbase.com/reference/getopenapispecjson.

## CultureAmp — adequate

Today (4): `employee_demographics`, `employees`, `manager_reviews`, `performance_cycles`

Diffed against: <https://api.cultureamp.com/spec>

No material gaps found.

Note: The OpenAPI 3 spec at https://api.cultureamp.com/spec declares exactly three top-level paths - /employees, /performance-cycles, /manager-reviews - plus the per-employee demographics sub-resource. PostHog's four tables cover all of them. The survey endpoints in the docs index (surveys, questions, responses, factors, sections) are marked 'Deprecated - No Longer Available' and redirect users to the separate Reporting API. The payload's developer.cultureamp.com URLs are dead/auth-gated; the live docs are at docs.api.cultureamp.com (llms.txt available). Future upside would come from the separate Reporting API and the GraphQL endpoint at api.cultureamp.com/graphql, neither of which is covered by this REST spec.

## Cursor — **thin**

Today (4): `daily_usage`, `members`, `spend`, `usage_events`

Diffed against: <https://cursor.com/docs/account/teams/analytics-api.md>

- [ ] `GET /analytics/ai-code/commits` — AI-authored code attribution per commit - Cursor's headline ROI metric, entirely absent today (high)
- [ ] `GET /analytics/ai-code/changes` — change-level AI vs human code accounting, the finer grain behind the commit metrics (high)
- [ ] `GET /analytics/team/models` — model usage breakdown; the dimension every cost and adoption question needs alongside spend (high)
- [ ] `GET /analytics/team/dau` — daily active users, the standard seat-utilization metric (high)
- [ ] `GET /analytics/team/agent-edits` — agent edit volume - the primary productivity measure for agent usage (high)
- [ ] `GET /analytics/team/tabs` — tab-completion acceptance metrics, the other half of core usage (high)
- [ ] `GET /analytics/by-user/{agent-edits,tabs,models,top-file-extensions}` — per-user breakdowns joining directly to the members table we already sync (high)
- [ ] `GET /teams/groups and /teams/groups/{id}/members` — billing-group lookup and membership resolving the group IDs on member and spend rows (medium)
- [ ] `GET /analytics/team/top-file-extensions` — language/file-type breakdown of AI usage (medium)
- [ ] `GET /analytics/team/bugbot and /analytics/team/bugbot-reviews` — code-review volume and per-review analytics for the Bugbot product (medium)
- [ ] `GET /analytics/team/conversation-insights` — aggregated conversation topics and outcomes (medium)
- [ ] `GET /teams/audit-logs` — admin action history for access and compliance reporting (medium)

Note: PostHog covers the four Admin API data endpoints (members, daily-usage-data, spend, filtered-usage-events) but none of the separate Analytics API (25 team- and by-user endpoints), AI Code Tracking API (4), or Cloud Agents API. Admin API endpoints verified at https://cursor.com/docs/account/teams/admin-api.md and AI code tracking at https://cursor.com/docs/account/teams/ai-code-tracking-api.md. Repo blocklists and spend-limit endpoints excluded as configuration. Note most analytics endpoints are POST-with-body query endpoints, not plain GETs.

## Customerly — gaps

Today (5): `knowledge_base_articles`, `knowledge_base_collections`, `leads`, `tags`, `users`

Diffed against: <https://documenter.gw.postman.com/api/collections/11487813/2s9Y5Wx3QG?segregateAuth=true&versionTag=latest>

- [ ] `GET /v1/knowledge/writers` — lookup table resolving the writer/author IDs carried on the knowledge_base_articles rows we already sync (medium)

Note: Pulled the raw Postman collection JSON behind the published documenter link. The entire public REST surface is 18 request paths across users, leads, tags, messages and knowledge base; every GET-able collection is already synced except /v1/knowledge/writers. Companies exist as an object (users/add-to-company, company/add-attributes) but the public API has no company list/read endpoint, so there is nothing to sync. Messages are POST-only (send), not readable, and there is no conversations export endpoint in the public API.

## DagsterCloud — gaps

Today (3): `assets`, `backfills`, `runs`

Diffed against: <https://raw.githubusercontent.com/dagster-io/dagster/master/python_modules/libraries/dagster-dg-cli/dagster_dg_cli/cli/plus/schema.graphql>

- [ ] `assetOrError(assetKey){ assetMaterializations } / assetObservations` — per-asset materialization event history with metadata — the core fact table behind the asset list we already sync (high)
- [ ] `assetNodes / assetNodeOrError` — asset definition metadata (group, owning job, description, dependencies, freshness policy) — lookup resolving the bare asset keys we sync (high)
- [ ] `schedulesOrError / sensorsOrError` — automation definitions and their status; lookup resolving the schedule/sensor tags carried on runs (high)
- [ ] `instigationStatesOrError / InstigationTick history (autoMaterializeTicks)` — schedule and sensor tick success/failure/skip history — orchestration reliability analysis (high)
- [ ] `deployments / fullDeployments / branchDeployments` — lookup resolving which Dagster+ deployment each run and asset belongs to (high)
- [ ] `reportingMetricsByJob / reportingMetricsByAsset / reportingMetricsByDeployment (Dagster+ Insights)` — Dagster+'s headline metrics — credits consumed, run duration, materialization and retry counts per job/asset/deployment (high)
- [ ] `assetCheckExecutions` — data quality check results per asset over time (medium)
- [ ] `repositoriesOrError / workspaceOrError (code locations, jobs, pipelines)` — lookup resolving repositoryOrigin and jobName already present on run rows (medium)
- [ ] `logsForRun (run event / step log)` — step-level timings, failures and retries inside runs we already sync (medium)
- [ ] `usersOrError / teamPermissions / customRoles` — org membership and role assignment for attributing runs and backfills to people (medium)
- [ ] `auditLog` — who changed deployments, code locations and automation settings (medium)
- [ ] `slasForAssets / assetSlaTimeline` — asset SLA state and breach timeline for freshness reporting (low)

Note: Diffed against the Dagster+ cloud GraphQL schema snapshot vendored in dagster-dg-cli (type CloudQuery), which is a superset of the OSS webserver schema at js_modules/ui-core/src/graphql/schema.graphql. The synced `assets` table is especially thin — the source's ASSETS_QUERY selects only id and key.path, so no asset metadata or materialization history lands at all.

## Datadog — gaps

Today (10): `audit_logs`, `dashboards`, `downtimes`, `events`, `incidents`, `logs`, `monitors`, `slos`, `synthetic_tests`, `users`

Diffed against: <https://raw.githubusercontent.com/DataDog/datadog-api-client-go/master/.generator/schemas/v2/openapi.yaml>

- [ ] `GET /api/v2/team and /api/v2/team/{team_id}/memberships` — lookup resolving the team handles attached to monitors, incidents, SLOs and services we already sync (high)
- [ ] `GET /api/v1/metrics, GET /api/v1/metrics/{metric_name}, GET /api/v1/query` — metric metadata and timeseries point query — Datadog's headline data type, entirely absent today (high)
- [ ] `GET /api/v1/usage/* (summary, billable-summary, hourly-attribution) and /api/v2/usage/hourly_usage, /estimated_cost, /cost_by_org` — billable usage and cost attribution, the most-requested Datadog warehouse use case (high)
- [ ] `GET /api/v1/slo/{slo_id}/history, /api/v1/slo/{slo_id}/corrections, GET /api/v2/slo/{slo_id}/status` — error-budget and status history for the SLOs we already sync as static definitions (high)
- [ ] `GET /api/v1/hosts and /api/v1/hosts/totals` — host inventory with tags, agent version and muting state — the join key for infrastructure metrics (medium)
- [ ] `POST /api/v2/security_monitoring/signals/search` — security signal events, the analytical output of the detection rules (medium)
- [ ] `POST /api/v2/rum/events/search` — RUM event stream for real-user performance and session analysis (medium)
- [ ] `POST /api/v2/spans/events/search` — APM span search — trace-level latency and error analysis (medium)
- [ ] `POST /api/v2/ci/pipelines/events/search and /api/v2/ci/tests/events/search` — CI Visibility pipeline and test execution events for build reliability reporting (medium)
- [ ] `GET /api/v2/cases and /api/v2/cases/projects` — Case Management records, the sibling workflow to the incidents we already sync (medium)
- [ ] `GET /api/v2/roles and /api/v2/roles/{role_id}/users` — lookup resolving role assignments for the users table we already sync (medium)
- [ ] `GET /api/v2/services/definitions and /api/v2/catalog/entity` — Software Catalog service definitions — lookup resolving the service names on monitors, incidents and spans (medium)

Note: Diffed against both machine-readable specs (v1: 1.6 MB, v2: 7.3 MB), 1062 paths total. Coverage of the core observability config objects is solid; the missing pieces are almost entirely the metric/usage/cost and event-search families plus the team and role lookup tables. Also unqueried but lower value: on-call schedules and escalation policies, DORA deployments/failures, Scorecards, notebooks, powerpacks.

## DataForSEO — **thin**

Today (5): `backlinks_summary`, `competitors_domain`, `domain_rank_overview`, `historical_rank_overview`, `ranked_keywords`

Diffed against: <https://docs.dataforseo.com/v3/wp-sitemap-posts-page-1.xml>

- [ ] `POST /v3/backlinks/backlinks/live` — the individual backlink rows behind the backlinks_summary aggregate we already sync (high)
- [ ] `POST /v3/backlinks/referring_domains/live` — referring-domain breakdown with rank and spam score — the standard link-profile dimension table (high)
- [ ] `POST /v3/dataforseo_labs/locations_and_languages and /v3/dataforseo_labs/categories` — lookup tables resolving the location_code, language_code and category codes stamped on every row we already sync (high)
- [ ] `POST /v3/dataforseo_labs/google/relevant_pages/live` — top organic landing pages per domain with traffic and keyword counts (high)
- [ ] `POST /v3/backlinks/history/live and /v3/backlinks/timeseries_summary/live` — backlink profile over time and new/lost link trend, versus the single current snapshot we sync (high)
- [ ] `POST /v3/keywords_data/google_ads/search_volume/live` — search volume, CPC and competition per keyword — the base metric for any SEO model (medium)
- [ ] `POST /v3/dataforseo_labs/google/historical_search_volume/live` — monthly search volume history for tracked keywords (medium)
- [ ] `POST /v3/backlinks/anchors/live` — anchor-text distribution for a target domain (medium)
- [ ] `POST /v3/dataforseo_labs/google/domain_intersection/live and /page_intersection/live` — keyword-gap analysis against the competitors we already sync in competitors_domain (medium)
- [ ] `POST /v3/dataforseo_labs/google/keyword_ideas/live, /keyword_suggestions/live, /related_keywords/live` — keyword expansion sets for opportunity sizing (medium)
- [ ] `POST /v3/backlinks/domain_pages_summary/live and /domain_pages/live` — per-page backlink counts, the page-level breakdown of the domain summary (medium)
- [ ] `POST /v3/serp/google/organic/live/advanced` — raw SERP snapshots per keyword, the source of rank tracking over time (medium)

Note: DataForSEO docs are a WordPress site with no OpenAPI, llms.txt or sitemap index; I enumerated all 691 endpoint doc pages from /v3/wp-sitemap-posts-page-1.xml and spot-verified the URL format on https://docs.dataforseo.com/v3/backlinks/backlinks/live/ (POST https://api.dataforseo.com/v3/backlinks/backlinks/live). The API spans SERP (157 pages), DataForSEO Labs (85), Keywords Data (69), AI Optimization (69), Business Data (58), Merchant (47), App Data (36), On-Page (33) and Backlinks (25); five synced tables is a small fraction. Whole families are absent: On-Page site audit, Business Data (Google Business Profile reviews), Merchant, App Data, Content Analysis and Domain Analytics technologies.

## Datahub — gaps

Today (14): `charts`, `containers`, `dashboards`, `data_flows`, `data_jobs`, `data_platforms`, `data_products`, `datasets`, `domains`, `glossary_nodes`, `glossary_terms`, `groups`, `tags`, `users`

Diffed against: <https://docs.datahub.com/docs/generated/metamodel/entities/chart>

- [ ] `dataProcessInstance` — individual task/pipeline run instances with status and timings — the execution fact table for the data_jobs and data_flows we already sync (high)
- [ ] `assertion (and its assertionRunEvent results)` — data quality assertions and their pass/fail run history per dataset (high)
- [ ] `schemaField` — column-level entity — lookup resolving dataset fields for column-level lineage, tags and glossary term assignment (high)
- [ ] `dataset timeseries aspects: datasetProfile, datasetUsageStatistics, operation` — row counts, null/distinct column stats, query and user usage counts, and last-modified operations for the datasets we already sync (high)
- [ ] `incident` — data incidents raised against datasets and jobs, with state transitions (medium)
- [ ] `query` — SQL queries associated with datasets, the source of column-level lineage and usage (medium)
- [ ] `mlModel, mlModelGroup, mlFeature, mlFeatureTable, mlPrimaryKey, mlModelDeployment` — ML metadata entities, entirely absent while their analytics counterparts are synced (medium)
- [ ] `dataPlatformInstance` — lookup resolving the platform-instance URNs carried on datasets, charts and dashboards (medium)
- [ ] `structuredProperty and businessAttribute` — lookup resolving custom structured property definitions applied across entities (medium)
- [ ] `dataContract` — contract definitions and their assertion bindings per dataset (medium)
- [ ] `application, service, api, semanticModel, metric` — newer catalog entity types not covered by the current fourteen (low)
- [ ] `notebook` — notebook assets and their dataset references (low)

Note: The metamodel index lists 71 entity types; the source syncs 14. I confirmed the dataset timeseries aspects (datasetProfile, datasetUsageStatistics, operation) exist on the dataset entity page. Excluded as config/plumbing: dataHubPolicy, dataHubRole, dataHubSecret, dataHubAccessToken, dataHubIngestionSource, inviteToken, globalSettings, dataHubView, form, post, dataHubUpgrade.

## Dbt — gaps

Today (6): `accounts`, `environments`, `jobs`, `projects`, `runs`, `users`

Diffed against: <https://raw.githubusercontent.com/dbt-labs/dbt-cloud-openapi-spec/master/openapi-v2.yaml>

- [ ] `Discovery API (metadata GraphQL): environment.applied models, tests, sources, snapshots, seeds, exposures, model historical runs, lineage` — model- and test-level state and run history — the resource-grain data every dbt warehouse use case needs, none of which the Admin API exposes (high)
- [ ] `GET /api/v2/accounts/{account_id}/runs/?include_related=["run_steps"] (and /api/v2/accounts/{account_id}/steps/{id}/)` — per-step timings, commands and status inside the runs we already sync — where run duration actually goes (high)
- [ ] `GET /api/v2/accounts/{account_id}/runs/{run_id}/artifacts/ and /artifacts/{remainder}` — run_results.json and manifest.json per run, giving model-level execution results and node metadata (high)
- [ ] `GET /api/v3/accounts/{account_id}/audit-logs/` — who changed jobs, environments and permissions, with timestamps (medium)
- [ ] `GET /api/v2/accounts/{account_id}/repositories/ and /api/v3/accounts/{account_id}/projects/{project_id}/repositories/` — lookup resolving the repository and branch behind each project we already sync (medium)
- [ ] `GET /api/v3/accounts/{account_id}/connections/ and /api/v3/accounts/{account_id}/projects/{project_id}/connections/` — lookup resolving the warehouse connection each environment points at (medium)
- [ ] `GET /api/v3/accounts/{account_id}/groups/ and /api/v3/accounts/{account_id}/group-permissions/{group_id}/` — group membership and permission assignment for the users we already sync (medium)
- [ ] `GET /api/v2/accounts/{account_id}/licenses/ and /api/v3/accounts/{account_id}/license-maps/` — seat type per user for license utilization reporting (low)

Note: Diffed against the vendor's own OpenAPI specs (openapi-v2.yaml, openapi-v3.yaml in dbt-labs/dbt-cloud-openapi-spec — the files the docs site renders through Stoplight). The Admin API is well covered; the real gap is the separate Discovery API, whose object list (Models, Tests, Sources, Snapshots, Seeds, Exposures, Tags, Packages, Owners, Model historical runs, Lineage, Job) I read from the schema navigation on https://docs.getdbt.com/docs/dbt-cloud-apis/discovery-schema-environment-applied-models. Excluded as config: environment variables, notifications, service tokens, IP restrictions, SCIM, OAuth configurations, webhooks, credentials, extended attributes.

## Debugbear — gaps

Today (2): `PageMetrics`, `Projects`

Diffed against: <https://www.debugbear.com/docs/api>

- [ ] `GET /api/v1/project/{projectId}/rumMetrics` — real-user Core Web Vitals aggregates — DebugBear's headline product, with nothing synced today (high)
- [ ] `GET /api/v1/project/{projectId}/rumPageViews` — page-view-grain RUM data for slicing real-user performance by page, device and country (high)
- [ ] `GET /api/v1/projects/{projectId}/pages` — lookup resolving the page IDs that every PageMetrics row is keyed on (URL, name, test settings) (high)
- [ ] `GET /api/v1/analysis/{analysisId}` — individual lab test results behind the aggregated page metrics, including test metadata and status (medium)
- [ ] `GET /api/v1/analysis/{analysisId}/requests` — request-level waterfall breakdown — which resources drive the page weight and load time (medium)
- [ ] `GET /api/v1/project/{projectId}/annotations` — timeline annotations (deploy markers) needed to attribute metric changes to releases (medium)
- [ ] `GET /api/v1/analysis/{analysisId}/lhr` — full Lighthouse report per test, including audit-level scores (low)
- [ ] `GET /api/v1/project/{projectId}/quickTests` — one-off test results run outside monitored pages (low)

Note: Enumerated all five API areas from the docs index (/docs/api) and extracted paths from each sub-page: projects-api, lab-test-api, quick-tests-api, rum-api, timeline-annotation-api. Twelve documented paths in total; the source syncs two. The RUM API being absent is the biggest miss since real-user monitoring is half the product.

## Decagon — could not verify

Today (1): `conversations`

Diffed against: <https://docs.decagon.ai/api/exporting-conversations>

No reachable API reference found during the sweep. Needs a manual pass.

Note: docs.decagon.ai is a fully client-rendered Mintlify site that returns the same 32 KB JS shell (data-current-path="/") for every path, including /sitemap.xml, /llms.txt, /llms-full.txt, /openapi.json and .md variants, with or without a browser user-agent — so no resource list could be read directly. Search snippets of the doc pages mention only two endpoints, /conversation/export (already synced, returns conversations with their messages, ratings, tags and metadata) and /chat/outbound (a write endpoint, not a table), plus a 1 req/sec global rate limit; the vendor also ships a Fivetran connector built on the same export. That is consistent with the single synced table being proportionate, but I could not confirm it from a fetched reference and have listed no gaps rather than guess.

## Deel — **thin**

Today (4): `contracts`, `invoice_adjustments`, `invoices`, `people`

Diffed against: <https://api.letsdeel.com/openapi/rest/definitions>

- [ ] `/timesheets (and /contracts/{contract_id}/timesheets)` — submitted time entries per contract — the core billable-hours fact table for contractor spend (high)
- [ ] `/payments (+ /payments/{payment_id}/breakdown)` — actual payment transactions and their per-contract breakdown; today only invoices are synced, not what was paid (high)
- [ ] `/legal-entities (+ /legal-entities/{id}/cost-centers)` — lookup that resolves the legal entity and cost center IDs carried on contracts and invoices (high)
- [ ] `/time_offs (+ /time_offs/dailies, /time_offs/time-off-events)` — absence records and transition events per worker — headline HR analytics (high)
- [ ] `/departments, /teams, /groups` — org lookup tables that resolve the department/team IDs on people rows (high)
- [ ] `/contracts/{contract_id}/adjustments` — per-contract bonuses, deductions and expenses; adjustments are only reachable one-by-one today (medium)
- [ ] `/contracts/{contract_id}/milestones` — line items for milestone-based contracts, needed to explain invoice amounts (medium)
- [ ] `/reports/payroll/cycles/{cycle_id}/gross-to-net (and /gp/legal-entities/{id}/reports)` — gross-to-net payroll report — the canonical payroll cost breakdown (medium)
- [ ] `/contracts/{contract_id}/amendments (and /eor/contracts/{id}/amendments)` — contract change history: comp changes over time rather than only current state (medium)
- [ ] `/onboarding/tracker and /offboarding/tracker` — worker lifecycle state so joiner/leaver funnels can be measured (medium)
- [ ] `/lookups/countries, /lookups/currencies, /lookups/job-titles, /lookups/seniorities, /lookups/time-off-types` — reference tables that decode the coded fields on contracts, people and time off (medium)
- [ ] `/ats/applications, /ats/candidates, /ats/job-postings` — recruiting funnel objects for orgs using Deel's ATS (low)

Note: The public spec is served from api.letsdeel.com (linked from developer.deel.com); it has 329 paths / 207 GET operations across ATS, EOR, payroll, HRIS, time tracking and IT modules, so the 4 synced tables cover a small slice.

## Deepgram — gaps

Today (6): `balances`, `invites`, `keys`, `members`, `projects`, `requests`

Diffed against: <https://developers.deepgram.com/openapi.json>

- [ ] `/v1/projects/{project_id}/usage (+ /usage/breakdown)` — the headline metric: transcription/TTS usage per project, sliced by model and feature (high)
- [ ] `/v1/projects/{project_id}/billing/breakdown` — spend broken down per project — pairs with balances to explain credit burn (high)
- [ ] `/v1/models and /v1/projects/{project_id}/models` — lookup table resolving the model IDs that appear on synced request rows (high)
- [ ] `/v1/projects/{project_id}/purchases` — credit purchase transactions behind the balance (medium)
- [ ] `/v1/projects/{project_id}/usage/fields and /billing/fields` — the set of models, methods and features seen in a period — breakdown dimensions for usage (medium)
- [ ] `/v1/projects/{project_id}/members/{member_id}/scopes` — membership permissions per project member (low)

Note: The Management API is only ~28 GET operations; the missing pieces are almost entirely the usage/billing analytics half of it. Agent configuration endpoints (/agents, /agent-variables) were excluded as config.

## Deepsource — gaps

Today (7): `analysis_runs`, `issue_occurrences`, `issues`, `metrics`, `reports`, `repositories`, `vulnerability_occurrences`

Diffed against: <https://docs.deepsource.com/docs/developers/api>

- [ ] `Check (AnalysisRun.checks, with CheckSummary occurrencesIntroduced/Resolved/Suppressed)` — per-analyzer results inside each analysis run — the level at which introduced vs resolved issues are counted (high)
- [ ] `analyzers / analyzer(shortcode)` — lookup table resolving the analyzer shortcodes carried on issues, checks and occurrences (high)
- [ ] `Repository.pullRequest / pull requests (PRSummary issuesRaised, issuesResolved, vulnerabilitiesRaised)` — PR-level quality outcomes, the main way teams measure whether DeepSource is catching things pre-merge (high)
- [ ] `Repository.targets (RepositoryTarget: ecosystem, packageManager, manifestPath)` — SCA target inventory that scopes the vulnerability occurrences already synced (medium)
- [ ] `Package / PackageVersion` — dependency inventory that resolves the packages referenced by vulnerability occurrences (medium)
- [ ] `Vulnerability (identifier, summary, severity, fixability)` — lookup definition behind vulnerability_occurrences, if occurrences only carry IDs (medium)
- [ ] `Account.suppressedIssues / IgnoreRule` — which issues are suppressed team-wide, needed to explain drops in issue counts (medium)
- [ ] `TeamMember (account team members and roles)` — resolves the users attached to runs and repositories (medium)
- [ ] `CodeCoverageReportRepository` — test coverage per repository alongside the code health metrics already synced (medium)
- [ ] `CodeFormatter / transformer runs` — auto-fix and formatter activity per repository (low)

Note: DeepSource is a Relay-style GraphQL API at https://api.deepsource.com/graphql/ with no downloadable SDL in the public docs; the resource list above was read from the docs' per-type reference pages (Check, Pull request, Analyzer, Repository, Reports, Team) and the node-query supported-types list.

## DenoDeploy — adequate

Today (5): `analytics`, `apps`, `domains`, `logs`, `revisions`

Diffed against: <https://api.deno.com/v2/openapi.json>

No material gaps found.

Note: The v2 Deploy API is tiny — 15 GET operations. Everything queryable as a collection is already exposed; the only unexposed reads are /v2/layers (+ /v2/layers/{layer}/apps), /v2/domains/{domain}/certificates, and per-revision build_logs/progress/timelines streams, all low value. Note the legacy https://api.deno.com/v1/openapi.json (Deploy Classic: projects, deployments, KV databases, org analytics) is a different, older API that this source does not target.

## Descope — gaps

Today (5): `AccessKeys`, `Audit`, `Roles`, `Tenants`, `Users`

Diffed against: <https://docs.descope.com/examples/Descope_API.yaml>

- [ ] `/v1/mgmt/permission/all` — lookup table for the permission names referenced by every synced role (high)
- [ ] `/v2/mgmt/user/history` — per-user authentication history — sign-in events, method and device, the core auth analytics fact (high)
- [ ] `/v1/mgmt/analytics/search` — Descope's own aggregated auth analytics (sign-ins, conversions) over a time range (high)
- [ ] `/v1/mgmt/group/all and /v1/mgmt/group/members (+ /v1/mgmt/group/member/all)` — tenant group membership — the user-to-group join table missing from users/tenants (medium)
- [ ] `/v1/mgmt/projects/list` — project lookup so multi-project tenants can attribute users and audit rows (medium)
- [ ] `/v1/mgmt/sso/idp/apps/load and /v1/mgmt/thirdparty/apps/load` — SSO and third-party application registry that resolves app IDs seen in audit events (medium)
- [ ] `/v1/mgmt/thirdparty/consents/search` — user consent grants per third-party app — auditable authorization state (medium)
- [ ] `/v1/mgmt/fga/relations (and /v1/mgmt/authz/re/*)` — fine-grained authorization relation tuples: who has access to what, beyond coarse roles (medium)
- [ ] `/v1/mgmt/agentic/identities/search` — agentic identity inventory for orgs using Descope's agentic hub (low)
- [ ] `/v1/mgmt/user/passkeys/list and /v1/mgmt/user/trusteddevices/list` — per-user authenticator and trusted-device inventory for MFA adoption reporting (low)
- [ ] `/v1/mgmt/descoper/list` — company-level admin users, useful for admin-action attribution in audit rows (low)

Note: The downloadable spec (Descope_API.yaml, 474 paths, 318 under /mgmt) is a POST-heavy RPC-style API, so 'endpoints' here are search/load operations rather than REST collections. Flows, themes, JWT templates, management keys, MCP servers and outbound apps were excluded as config/plumbing.

## DevinAI — **thin**

Today (4): `knowledge_notes`, `playbooks`, `secrets`, `sessions`

Diffed against: <https://docs.devin.ai/llms.txt>

- [ ] `/v3/organizations/{org_id}/members/users (and /members/{id})` — lookup table resolving the user IDs on every session; without it sessions cannot be attributed to people (high)
- [ ] `/v3/organizations/{org_id}/consumption/daily (+ /daily/users, /daily/sessions, /daily/service-users, /consumption/cycles)` — ACU consumption per day, user and session — the headline cost metric for Devin (high)
- [ ] `/v3/organizations/{org_id}/sessions/{session_id}/messages` — the conversation transcript inside a session; sessions alone carry no content (high)
- [ ] `/v3/organizations/{org_id}/sessions/insights (and /sessions/{id}/insights)` — per-session outcome and quality insights, the vendor's own success measure (high)
- [ ] `/v3/organizations/{org_id}/pr-reviews` — PR review activity and outcomes, a primary Devin use case not represented at all today (high)
- [ ] `/v3/organizations/{org_id}/audit-logs (and enterprise audit logs)` — who did what in the org — standard governance table (medium)
- [ ] `/v3/organizations/{org_id}/metrics/sessions, /metrics/prs, /metrics/usage, /metrics/dau|wau|mau, /metrics/sessions-by-category` — pre-aggregated adoption and throughput metrics that avoid recomputing them from raw sessions (medium)
- [ ] `/v3/organizations/{org_id}/repositories (+ indexed repositories and indexing status)` — repository lookup that resolves the repos sessions run against (medium)
- [ ] `/v3/organizations/{org_id}/tags (and /sessions/{id}/tags)` — tag dimension for slicing sessions by team or workstream (medium)
- [ ] `/v3/organizations` — organization lookup for enterprises with multiple orgs under one key (medium)
- [ ] `/v3/organizations/{org_id}/guardrail-violations` — policy violations raised during sessions — compliance reporting (medium)
- [ ] `/v3/organizations/{org_id}/knowledge/folders` — folder lookup that gives the synced knowledge notes their hierarchy (low)

Note: docs.devin.ai/llms.txt enumerates every v1/v2/v3 API reference page; v3 alone spans sessions, consumption, metrics, users, repositories, pr-reviews, audit-logs, code-scans, guardrails and more, so 4 synced tables (one of which, secrets, is plumbing) is a small fraction.

## DigitalOcean — gaps

Today (16): `apps`, `billing_history`, `databases`, `domains`, `droplets`, `images`, `invoices`, `kubernetes_clusters`, `load_balancers`, `projects`, `reserved_ips`, `snapshots`, `ssh_keys`, `tags`, `volumes`, `vpcs`

Diffed against: <https://api-engineering.nyc3.cdn.digitaloceanspaces.com/spec-ci/DigitalOcean-public.v2.yaml>

- [ ] `/v2/customers/my/invoices/{invoice_uuid} (invoice items) and /invoices/{invoice_uuid}/summary` — per-resource invoice line items; invoices are synced as headers only, so spend cannot be attributed to droplets or databases (high)
- [ ] `/v2/sizes` — lookup resolving the droplet size slug on every droplet into vCPU, memory, disk and hourly/monthly price (high)
- [ ] `/v2/regions` — lookup resolving the region slug carried by droplets, databases, load balancers and volumes (high)
- [ ] `/v2/projects/{project_id}/resources (and /v2/projects/default/resources)` — the join table mapping every synced resource URN to a project — projects are synced but the membership is not (high)
- [ ] `/v2/actions (and /v2/droplets/{droplet_id}/actions)` — account-wide action history: creates, resizes, power cycles with status and timing — the state-transition log for infrastructure (high)
- [ ] `/v2/apps/{app_id}/deployments (+ /v2/apps/{app_id}/events)` — App Platform deployment history and phase transitions; apps are synced but not their deploy activity (medium)
- [ ] `/v2/kubernetes/clusters/{cluster_id}/node_pools` — node pool sizing per cluster, needed to explain Kubernetes cost and capacity (medium)
- [ ] `/v2/tags/{tag_id}/resources` — resolves tags (already synced as names) to the resources they are applied to (medium)
- [ ] `/v2/domains/{domain_name}/records` — DNS records under the domains already synced (medium)
- [ ] `/v2/databases/{database_cluster_uuid}/backups and /v2/databases/{database_cluster_uuid}/events` — backup inventory and cluster event history for managed databases (medium)
- [ ] `/v2/uptime/checks (+ /checks/{check_id}/state)` — uptime check inventory and current state for availability reporting (low)
- [ ] `/v2/registry/{registry_name}/repositories (+ /tags, /digests)` — container registry repository and tag inventory with sizes (low)

Note: The public spec has 447 paths, but a large share is GenAI, monitoring metric time series, and mutation-only endpoints. Firewalls, certificates, CDN endpoints and monitoring alert policies were treated as config and excluded.

## DingConnect — gaps

Today (7): `Balance`, `Countries`, `Currencies`, `Products`, `Promotions`, `Providers`, `TransferRecords`

Diffed against: <http://web.archive.org/web/20250213144221/https://www.dingconnect.com/Api/Description>

- [ ] `api/V1/GetRegions` — lookup for the region codes that scope providers and products; the docs call out that a provider or product may only be valid for a subset of regions (high)
- [ ] `api/V1/GetErrorCodeDescriptions` — lookup decoding the ErrorCode/Context values returned on transfer records, so failed top-ups can be categorized (medium)
- [ ] `api/V1/GetProviderStatus` — per-provider availability, the dimension that explains transfer failure spikes (medium)
- [ ] `api/V1/GetProductDescriptions` — localized long-form product text keyed by LocalizationKey — resolves the descriptions deliberately split out of GetProducts (medium)
- [ ] `api/V1/GetPromotionDescriptions` — localized promotion terms keyed by LocalizationKey, the companion to the synced promotions table (low)

Note: The live docs page returns Cloudflare 403 to non-browser clients and the swagger definition (/swagger/docs/v1) is auth-gated, so this was diffed against a Wayback capture of the official API description. The full readable method set is GetBalance, GetCountries, GetCurrencies, GetProducts, GetProductDescriptions, GetPromotions, GetPromotionDescriptions, GetProviders, GetProviderStatus, GetRegions, GetErrorCodeDescriptions, ListTransferRecords; GetAccountLookup and EstimatePrices are per-request lookups rather than tables, and SendTransfer/CancelTransfers are mutations.

## Discourse — gaps

Today (6): `categories`, `groups`, `posts`, `tags`, `topics`, `users`

Diffed against: <https://docs.discourse.org/openapi.json>

- [ ] `GET /groups/{name}/members.json` — group↔user membership junction; today groups and users sync but nothing links them (high)
- [ ] `GET /admin/users.json and /admin/users/list/{flag}.json` — full user records (email, last_seen_at, trust_level, suspended state) — /directory_items.json only exposes a period-windowed public subset (high)
- [ ] `GET /user_actions.json` — per-user activity stream (likes, replies, posts) — the event table for community engagement analysis (medium)
- [ ] `GET /admin/badges.json` — lookup table resolving badge IDs on user badges (medium)
- [ ] `GET /user-badges/{username}.json` — user↔badge grants with granted_at; the gamification/engagement fact table (medium)
- [ ] `GET /tag_groups.json` — lookup that groups the tags table into categories (medium)
- [ ] `GET /t/{id}/posts.json` — authoritative topic→post ordering; the /posts.json id-walk can miss posts in long topics (low)
- [ ] `GET /notifications.json` — notification events per user (low)
- [ ] `GET /discourse-post-event/events.json` — calendar/event plugin records for communities that run events (low)

Note: The topics table is backed by /latest.json, which is a rolling recency feed rather than a full topic list — /c/{slug}/{id}.json (category topics) or /top.json would broaden historical coverage. Nothing is discovered dynamically; the endpoint set is static in settings.py.

## Dixa — gaps

Today (5): `agents`, `conversations`, `endusers`, `queues`, `tags`

Diffed against: <https://docs.dixa.io/_spec/openapi/dixa-api/@v1/v1.yaml>

- [ ] `GET /v1/conversations/{conversationId}/ratings` — CSAT ratings — Dixa's headline quality metric, absent entirely today (high)
- [ ] `GET /v1/conversations/{conversationId}/messages` — message-level fact table under each synced conversation; needed for response-time and volume analysis (high)
- [ ] `GET /v1/conversations/activitylog (and /v1/conversations/{id}/activitylog)` — state-transition history (assignment, status changes) driving handling-time metrics (high)
- [ ] `GET /v1/teams and /v1/teams/{teamId}/agents` — team lookup plus agent↔team membership; agents sync today with no team dimension (high)
- [ ] `GET /v1/custom-attributes` — lookup resolving custom attribute IDs carried on conversations (medium)
- [ ] `GET /v1/conversations/flows` — lookup resolving the flow/channel ID on each conversation (medium)
- [ ] `GET /v1/conversations/{conversationId}/notes` — internal agent notes attached to synced conversations (medium)
- [ ] `GET /v1/analytics/records/{recordId}` — Dixa's own metric record catalogue — pre-aggregated breakdown dimensions for reporting (medium)
- [ ] `GET /v1/contact-endpoints` — lookup resolving the inbound email/phone endpoint a conversation arrived on (medium)
- [ ] `GET /v1/queues/{queueId}/members` — queue↔agent membership; queues and agents both sync but are unlinked (medium)
- [ ] `GET /v1/agents/presence` — agent availability state for staffing/occupancy analysis (low)
- [ ] `GET /v1/business-hours/schedules` — schedule definitions needed to compute SLA within business hours (low)

Note: Conversations are synced via /conversation_export rather than the paged conversation endpoints, so the sub-resources above (messages, ratings, activitylog) require per-conversation fan-out.

## Dockerhub — gaps

Today (2): `repositories`, `tags`

Diffed against: <https://docs.docker.com/reference/api/hub/latest.yaml>

- [ ] `GET /v2/orgs/{org_name}/members` — org membership roster — the lookup that resolves the creator/last_updater usernames already present on repositories (high)
- [ ] `GET /v2/auditlogs/{account}` — audit log event stream (pushes, permission changes, deletions); the only event-shaped table in the Hub API (high)
- [ ] `GET /v2/orgs/{org_name}/groups/{group_name}/members` — team↔user membership junction for access analysis (medium)
- [ ] `GET /v2/orgs/{org_name}/groups` — team lookup that group membership rows point at (medium)
- [ ] `GET /v2/auditlogs/{account}/actions` — lookup enumerating audit action types for categorizing log rows (medium)
- [ ] `GET /v2/namespaces/{namespace}/pulls (DVP Data API)` — per-repo pull counts over time — the headline usage metric, but only available to Docker Verified Publishers (low)

Note: The Hub source is namespace-scoped (namespace + repositories fan-out to tags), so the two tables are proportionate for that scope; the gaps are org-scoped endpoints in the same spec. Pull analytics live in a separate spec (https://docs.docker.com/reference/api/dvp/latest.yaml) gated behind Verified Publisher status. Access-token, SCIM schema, and org-settings endpoints were excluded as plumbing.

## Docuseal — adequate

Today (3): `submissions`, `submitters`, `templates`

Diffed against: <https://www.docuseal.com/docs/api>

No material gaps found.

Note: The public DocuSeal API exposes exactly three listable resources — submissions, submitters, templates — all synced. The only other GET is /submissions/{id}/documents, which returns signed-file download URLs (excluded as file plumbing).

## Doppler — gaps

Today (8): `activity_logs`, `configs`, `environments`, `groups`, `invites`, `projects`, `service_accounts`, `workplace_users`

Diffed against: <https://docs.doppler.com/llms.txt>

- [ ] `GET /v3/configs/config/logs (config_logs)` — per-config change history — the state-transition table for who changed which secret and when (high)
- [ ] `GET /v3/projects/{project}/members (project_members)` — project↔user membership junction; projects and workplace_users sync today with nothing joining them (high)
- [ ] `GET /v3/projects/roles (project_roles)` — lookup resolving the role slug carried on every project member and invite (high)
- [ ] `GET /v3/workplace/roles (workplace_roles)` — lookup resolving the workplace role ID on synced workplace_users (medium)
- [ ] `GET /v3/workplace/groups/{slug}/members` — group↔user membership; groups sync but their members do not (medium)
- [ ] `GET /v3/change_requests` — approval-workflow records showing proposed vs applied secret changes (medium)
- [ ] `GET /v3/configs/config/secrets/names` — secret-name inventory per config (names only, no values) for sprawl and coverage audits (medium)
- [ ] `GET /v3/workplace` — single-row workplace metadata to attribute rows to a tenant (low)
- [ ] `GET /v3/workplace/roles/role/{role}/permissions` — role→permission expansion for access reviews (low)

Note: Doppler publishes no OpenAPI file; the resource list was read from the docs llms.txt index, which enumerates every reference page. Integrations, syncs, service tokens, service-account tokens/identities, webhooks, trusted IPs, and secret values were excluded as config/secret plumbing.

## Dovetail — gaps

Today (8): `Contacts`, `Data`, `DocComments`, `Docs`, `Highlights`, `Projects`, `Tags`, `Users`

Diffed against: <https://developers.dovetail.com/llms.txt>

- [ ] `GET /v1/insights` — insights are a first-class Dovetail object alongside docs and the main research output; entirely missing (high)
- [ ] `GET /v1/notes` — notes are a top-level content type parallel to docs and are not synced at all (high)
- [ ] `GET /v1/fields` — custom field definition lookup that resolves the field IDs carried on projects, data, and contacts (high)
- [ ] `GET /v1/insights/{insightId}/comments` — insight comments; DocComments already syncs the doc-side equivalent, leaving half the comment corpus behind (medium)
- [ ] `GET /v1/channels` — feedback channel lookup for channel-sourced data records (medium)
- [ ] `GET /v1/channels/{channelId}/themes` — aggregated themes per channel — the analytical breakdown dimension over feedback (medium)
- [ ] `GET /v1/folders and /v1/folders/{folderId}/contents` — folder hierarchy that organizes projects and docs (medium)
- [ ] `GET /v1/channels/{channelId}/data` — channel↔data-record junction linking feedback items to their source channel (low)
- [ ] `GET /v1/projects/templates` — project template lookup (low)

Note: The source already does per-doc fan-out for DocComments, so insight comments and channel sub-resources follow the same pattern. Dovetail publishes no OpenAPI file; the endpoint list came from the docs llms.txt reference index.

## Drata — gaps

Today (14): `assets`, `controls`, `devices`, `events`, `evidence_library`, `frameworks`, `monitoring_tests`, `personnel`, `policies`, `risk_registers`, `risks`, `users`, `vendors`, `workspaces`

Diffed against: <https://developers.drata.com/page-data/openapi/reference/v2/tag/Assets/page-data.json>

- [ ] `GET /workspaces/{workspaceId}/framework-requirements` — the requirement catalogue each synced framework is composed of — without it frameworks are opaque IDs (high)
- [ ] `GET /workspaces/{workspaceId}/controls/{controlId}/requirements` — control↔requirement mapping, the junction that makes compliance coverage queryable (high)
- [ ] `GET /workspaces/{workspaceId}/monitoring-tests/{testId}/failures` — test failure history — the headline continuous-monitoring metric; monitoring_tests today gives only current state (high)
- [ ] `GET /workspaces/{workspaceId}/tasks` — remediation tasks with owners and due dates; the core operational work queue (high)
- [ ] `GET /users/{userId}/assigned-policies` — policy acceptance per user — the compliance metric auditors ask for; policies sync but attestation does not (high)
- [ ] `GET /roles and GET /roles/{roleId}/users` — role lookup plus role↔user membership for the already-synced users table (medium)
- [ ] `GET /workspaces/{workspaceId}/audits` — audit engagements that scope frameworks and evidence (medium)
- [ ] `GET /workspaces/{workspaceId}/audits/{auditId}/requests` — auditor evidence requests and their fulfillment state (medium)
- [ ] `GET /workspaces/{workspaceId}/controls/{controlId}/owners` — control↔personnel ownership junction (medium)
- [ ] `GET /vendor-security-reviews` — vendor security review records and outcomes across all synced vendors (medium)
- [ ] `GET /vendor-types` — lookup resolving the type ID on every synced vendor (medium)
- [ ] `GET /policies/{policyId}/policy-versions` — policy version history for change tracking (low)

Note: Drata publishes no standalone spec file; the full OpenAPI document is embedded as `redocStoreStr` inside the docs portal page-data JSON (122 paths), which is what I parsed. The source already fans out by workspace ID and risk-register ID, so the workspace-scoped gaps above fit the existing pattern. Also unsynced but lower value: /groups, /custom-field-definitions, /control-library, /risk-library, control and risk notes, device apps.

## Drip — gaps

Today (6): `broadcasts`, `campaigns`, `forms`, `goals`, `subscribers`, `workflows`

Diffed against: <https://developer.drip.com/>

- [ ] `GET /v2/{account_id}/campaigns/{campaign_id}/subscribers` — campaign↔subscriber membership with subscription status; campaigns and subscribers both sync with nothing joining them (high)
- [ ] `GET /v2/{account_id}/subscribers/{id}/campaign_subscriptions` — per-subscriber campaign subscription records including started/completed state (high)
- [ ] `GET /v2/{account_id}/tags` — account tag lookup; tags drive Drip segmentation and are entirely absent (medium)
- [ ] `GET /v2/{account_id}/custom_field_identifiers` — lookup enumerating the custom field keys present on subscriber records (medium)
- [ ] `GET /v2/{account_id}/event_actions` — lookup of custom event action names used in the account (medium)
- [ ] `GET /v2/{account_id}/workflows/{workflow_id}/triggers` — trigger definitions explaining how subscribers enter each synced workflow (medium)
- [ ] `GET /v2/accounts` — account lookup to attribute rows when a token spans multiple Drip accounts (low)

Note: The synced `goals` table is Drip's /v2/{account_id}/goals endpoint, which the docs now label "Conversions" — same resource, so conversions is not a gap. Orders, refunds, and shopper-activity (cart/order/product) are write-only POST endpoints with no list counterpart, so they cannot be synced. Webhooks excluded as plumbing.

## DropboxSign — gaps

Today (4): `account`, `api_apps`, `signature_requests`, `templates`

Diffed against: <https://raw.githubusercontent.com/hellosign/hellosign-openapi/main/openapi.yaml>

- [ ] `GET /team/members/{team_id} (teamMembers)` — member roster that resolves the account IDs carried on signature_requests and templates (high)
- [ ] `GET /bulk_send_job/list + /bulk_send_job/{id} (bulkSendJobList)` — bulk send batches and their per-batch signature request status (medium)
- [ ] `GET /team and /team/info (teamGet, teamInfo)` — team/org record with seat and usage counts to join members against (medium)
- [ ] `GET /team/sub_teams/{team_id} (teamSubTeams)` — team hierarchy lookup for rolling member activity up to parent teams (low)
- [ ] `GET /team/invites (teamInvites)` — pending invites for onboarding/seat funnel analysis (low)
- [ ] `GET /fax/list (faxList)` — sent/received fax transactions for accounts using the fax product (low)
- [ ] `GET /fax_line/list (faxLineList)` — fax line lookup that resolves the line a fax was sent on (low)

Note: Spec has 36 paths; the only other GETs are file downloads, embedded URL generators and OAuth. /report/create is POST-only and emails a CSV, so it is not warehouse-queryable.

## Dub — gaps

Today (11): `click_events`, `commissions`, `customers`, `domains`, `folders`, `lead_events`, `links`, `partners`, `payouts`, `sale_events`, `tags`

Diffed against: <https://spec.speakeasy.com/dub/dub/dub-with-code-samples>

- [ ] `GET /analytics` — Dub's headline metric endpoint - clicks/leads/sales aggregated by timeseries, countries, cities, regions, continents, devices, browsers, os, referers, top_links, top_urls, trigger; none of these breakdown dimensions are reachable from the raw event tables today (high)
- [ ] `GET /partners/analytics` — per-partner clicks/leads/sales/earnings rollup, the core affiliate-program metric (medium)
- [ ] `GET /partners/applications` — pending partner applications for partner-acquisition funnel analysis (medium)
- [ ] `GET /bounties/{bountyId}/submissions` — bounty submission records and their approval state (low)
- [ ] `GET /links/count` — link counts grouped by domain/tag/folder/userId without paging all links (low)

Note: api.dub.co/openapi.json 404s; the live spec is served from spec.speakeasy.com. Coverage of the object model (links, tags, folders, domains, customers, partners, commissions, payouts, and the three event types) is essentially complete - the gap is the aggregation layer.

## Dynatrace — gaps

Today (10): `applications`, `audit_logs`, `events`, `hosts`, `metrics`, `problems`, `process_groups`, `security_problems`, `services`, `slos`

Diffed against: <https://docs.dynatrace.com/docs/dynatrace-api/environment-api/metric-v2/get-data-points>

- [ ] `GET /api/v2/metrics/query` — actual metric data points; the existing `metrics` table is descriptor metadata only (settings.py hits GET /api/v2/metrics), so no timeseries values are syncable today (high)
- [ ] `GET /api/v2/entityTypes` — lookup of every monitored entity type and its properties/relationships - needed to interpret entity IDs and to know what else is syncable (high)
- [ ] `GET /api/v2/entities with entitySelector for types beyond HOST/SERVICE/APPLICATION/PROCESS_GROUP` — DATABASE, KUBERNETES_CLUSTER/NODE, CLOUD_APPLICATION, DISK, QUEUE and custom devices are all served by the same endpoint the source already calls, just with a different type selector (high)
- [ ] `GET /api/v1/synthetic/monitors` — synthetic monitor definitions - the availability side of the product is entirely absent (high)
- [ ] `GET /api/v2/synthetic/executions` — synthetic monitor execution results, the per-run success/duration facts you would actually chart (high)
- [ ] `GET /api/v1/userSessionQueryLanguage/table` — RUM user sessions - session-level real-user data, currently only aggregate application entities are synced (medium)
- [ ] `GET /api/v2/tags` — entity tag lookup; management-zone and tag dimensions are how Dynatrace users slice everything (medium)
- [ ] `GET /api/v2/releases` — release inventory joining deployed versions to entities, for change-vs-problem correlation (medium)
- [ ] `GET /api/v2/attacks` — application-security attack events, the transactional counterpart to the security_problems already synced (medium)
- [ ] `GET /api/v2/securityProblems/{id}/remediationItems` — per-vulnerability remediation items and their tracking state (medium)
- [ ] `GET /api/v2/logs/search` — log records; high volume but the standard analytical join partner for problems and events (medium)
- [ ] `GET /api/v2/synthetic/locations` — synthetic location lookup resolving the location IDs on executions (low)

Note: Diffed against the Environment API section of docs.dynatrace.com/docs/sitemap.xml (770 URLs under /dynatrace-api/environment-api/), then confirmed individual paths on their doc pages (/api/v2/entityTypes, /api/v1/synthetic/monitors, /api/v2/synthetic/executions, /api/v2/releases, /api/v2/tags, /api/v2/attacks, /api/v2/logs/search, /api/v1/userSessionQueryLanguage/table). Important: the source's `metrics` table is descriptors, not values - verified in products/warehouse_sources/backend/temporal/data_imports/sources/dynatrace/settings.py. Entity tables are hardcoded to four types via \_entity_endpoint(); no dynamic type discovery. Config-only areas (settings objects, extensions, credential vault, tokens, network zones, ActiveGate deployment) deliberately excluded.

## E2B — gaps

Today (3): `sandboxes`, `snapshots`, `templates`

Diffed against: <https://raw.githubusercontent.com/e2b-dev/infra/main/spec/openapi.yml>

- [ ] `GET /sandboxes/metrics and GET /sandboxes/{sandboxID}/metrics` — CPU/memory/disk timeseries per sandbox - the usage metric everyone charts, and the only quantitative data E2B exposes (high)
- [ ] `GET /teams/{teamID}/metrics and /teams/{teamID}/metrics/max` — team-level concurrent-sandbox and start-rate metrics, the headline capacity/quota numbers (high)
- [ ] `GET /teams` — team lookup resolving the teamID stamped on sandboxes, templates and snapshots (medium)
- [ ] `GET /templates/{templateID} (returns the template's build list) and /templates/{templateID}/builds/{buildID}/status` — template build history - durations, statuses and failure rates for the build pipeline (medium)
- [ ] `GET /templates/{templateID}/tags` — template version/tag lookup, needed to attribute sandboxes to a template version (low)
- [ ] `GET /volumes` — persistent volume inventory and their sandbox attachments (low)
- [ ] `GET /v2/sandboxes/{sandboxID}/logs` — per-sandbox logs for failure analysis; high volume and per-ID fetch, so nice to have (low)

Note: E2B's public API is genuinely small (~20 GET-able paths, most of them template build plumbing or admin/api-key management). The source is static: E2B_ENDPOINTS in settings.py hardcodes /v2/sandboxes, /v2/templates and /snapshots with no dynamic discovery, and correctly uses the v2 sandbox listing (all states) rather than the running-only v1.

## Easypost — gaps

Today (9): `addresses`, `batches`, `events`, `insurances`, `pickups`, `refunds`, `scan_forms`, `shipments`, `trackers`

Diffed against: <https://docs.easypost.com/docs/carrier-accounts>

- [ ] `GET /v2/carrier_accounts` — lookup that resolves the carrier_account_id stamped on every shipment and rate already synced (high)
- [ ] `GET /v2/claims` — insurance claims with amount, status and resolution - transactional and completely absent (only insurances are synced) (high)
- [ ] `GET /v2/metadata/carriers` — carrier service levels, predefined packages and supported options - resolves the service/carrier codes on shipments and rates (medium)
- [ ] `GET /v2/end_shippers` — end shipper records referenced by international shipments (medium)
- [ ] `GET /v2/users/children` — child user roster for platforms that break spend and volume down by sub-account (medium)
- [ ] `GET /v2/reports/{type}` — generated shipment/payment_log/tracker/refund report objects, useful for reconciling billing (low)
- [ ] `GET /v2/carrier_types` — lookup of available carrier types and their credential fields (low)

Note: Diffed against the 45 /docs/\* pages in docs.easypost.com/sitemap.xml and read the endpoint tables on each candidate page. Orders, parcels, customs_infos and customs_items have create/retrieve only - no index endpoint - so they cannot back a warehouse table and were excluded rather than reported as gaps.

## Easypromos — gaps

Today (9): `coin_transactions`, `organizing_brands`, `participations`, `points_of_sale`, `prizes`, `promotions`, `rankings`, `stages`, `users`

Diffed against: <https://easypromos-apiref.redoc.ly/>

- [ ] `GET /prizes/{promotion_id}/users/{user_id} (GetUserPrizesByPromotion)` — prize awards linking users to the prizes they won - the winner fact table; `prizes` today is only the prize catalog (high)
- [ ] `GET /prizes/inventory/{promotion_id} (GetPrizeInventoryByPromotion)` — per-prize stock and code inventory, needed for redemption/remaining-stock reporting (medium)
- [ ] `GET /coins/{promotion_id}/users/{user_id} (GetUserBalanceVirtualCoin)` — current virtual coin balance per user; largely derivable from coin_transactions but avoids replaying the ledger (low)

Note: The spec has only 35 operations and everything is promotion-scoped (the source already fans out per promotion_id). Remaining uncovered operations are write paths (participate, register, segment assignment, coin transaction creation) or single-request helpers (autologin, login token, check_requirement, validate_code, remaining participations) - none are warehouse tables.

## EConomic — gaps

Today (18): `accounting_years`, `accounts`, `currencies`, `customer_groups`, `customers`, `departmental_distributions`, `departments`, `employees`, `invoices_booked`, `invoices_drafts`, `journals`, `payment_terms`, `product_groups`, `products`, `supplier_groups`, `suppliers`, `units`, `vat_zones`

Diffed against: <https://restdocs.e-conomic.com/>

- [ ] `GET /journals/{journalNumber}/entries` — the actual accounting entries; today only the journal headers are synced, so no transaction-level ledger exists (high)
- [ ] `GET /accounting-years/{year}/entries` — full general-ledger entry stream for a financial year - the core fact table of the whole API (high)
- [ ] `GET /accounts/{accountNumber}/accounting-years/{year}/entries` — per-account ledger entries, letting you reconcile the accounts table already synced (high)
- [ ] `GET /orders, /orders/drafts, /orders/sent, /orders/archived` — sales orders with their state slices - the pre-invoice half of the revenue pipeline is entirely missing (high)
- [ ] `GET /vat-types and GET /vat-accounts` — VAT code lookup resolving the vatZone/vatAccount references already carried on accounts, products and invoice lines (high)
- [ ] `GET /accounting-years/{year}/totals and /accounting-years/{year}/periods/{p}/totals` — account balances per year and per period - the trial-balance figures, without recomputing from entries (high)
- [ ] `GET /accounting-years/{year}/periods` — accounting-period lookup that every entry and total is bucketed by (medium)
- [ ] `GET /quotes, /quotes/drafts, /quotes/sent, /quotes/archived` — quotes and their lifecycle state, the top of the quote-to-cash funnel (medium)
- [ ] `GET /customers/{customerNumber}/contacts` — customer contact records for joining people to the customers already synced (medium)
- [ ] `GET /payment-types` — payment type lookup referenced by invoices and payment terms (medium)
- [ ] `GET /journals/{journalNumber}/vouchers` — voucher records grouping entries, with attachment metadata (medium)
- [ ] `GET /invoices/sent, /paid, /unpaid, /overdue, /not-due` — AR ageing state slices; derivable from booked invoices but these are the views finance actually asks for (medium)

Note: Resource list derived from the JSON-schema filenames embedded in restdocs.e-conomic.com (they mirror the path tree exactly, e.g. journals.journalNumber.entries.get.schema.json). Also missing but below the cut: /customers/{n}/delivery-locations, /layouts, /products/{n}/pricing/currency-specific-sales-prices, /product-groups/{n}/sales-accounts, /invoices/totals/\*. app-roles and /self are config and were excluded.

## Elasticemail — gaps

Today (7): `campaigns`, `contacts`, `events`, `lists`, `segments`, `suppressions`, `templates`

Diffed against: <https://api.elasticemail.com/public/v4/swagger>

- [ ] `/statistics/campaigns (Load Campaigns Stats)` — per-campaign delivery/engagement aggregates (sent, opened, clicked, bounced, unsubscribed) — the headline metric for the campaigns we already sync (high)
- [ ] `/lists/{listname}/contacts (Load Contacts in List)` — list membership join table linking the contacts and lists we already sync (high)
- [ ] `/statistics (Load Statistics)` — account-level delivery stats over a date range, the top-level deliverability rollup (high)
- [ ] `/statistics/channels + /statistics/channels/{name}` — per-channel send stats for attributing volume across sending channels (medium)
- [ ] `/subaccounts` — lookup resolving the sub-account that owns campaigns, events and statistics rows (medium)
- [ ] `/verifications (Get Emails Verification Results)` — email verification outcomes per address, useful for list hygiene analysis (medium)
- [ ] `/events/channels/{name} (Load Channel Events)` — channel-scoped event stream for splitting engagement events by sending channel (low)
- [ ] `/suppressions/bounces, /suppressions/complaints, /suppressions/unsubscribes` — typed suppression sub-lists; only worth adding if the generic /suppressions payload does not carry the suppression type (low)

Note: The docs page at elasticemail.com/developers/api-documentation/rest-api is a Redoc shell; the real spec it links is https://api.elasticemail.com/public/v4/swagger (Elastic Email REST API 4.0.0, 74 paths). Source uses a static endpoint list in settings.py — no dynamic table discovery.

## ElevenLabs — gaps

Today (4): `agents`, `conversations`, `history`, `voices`

Diffed against: <https://api.elevenlabs.io/openapi.json>

- [ ] `/v1/usage/character-stats` — the vendor's headline usage metric — character/credit consumption over time, broken down by voice, model and workspace user (high)
- [ ] `/v1/models` — lookup table resolving the model_id carried on history items and conversations (high)
- [ ] `/v1/workspace/members (and /v1/workspace/groups)` — lookup resolving the workspace user ids attached to history, conversations and usage rows (high)
- [ ] `/v1/convai/tools and /v1/convai/tools/{tool_id}/executions` — agent tool catalog plus per-execution records — the analytical detail behind agent conversations (medium)
- [ ] `/v1/convai/phone-numbers` — lookup resolving the phone number a Conversational AI call came in on (medium)
- [ ] `/v1/convai/batch-calling/workspace` — batch calling jobs, the campaign-level grouping over outbound conversations (medium)
- [ ] `/v1/user/subscription` — plan quota and current-period usage, needed to turn character stats into utilization (medium)
- [ ] `/v1/convai/knowledge-base (+ /summaries)` — knowledge base documents referenced by agents, resolves document ids seen in agent configs (medium)
- [ ] `/v1/convai/tags` — tag lookup for grouping agents and conversations in reporting (medium)
- [ ] `/v1/workspace/audit-logs` — state/transition history across workspace resources (medium)
- [ ] `/v1/dubbing (list dubs)` — dubbing jobs are a separate billable workload not represented by history or conversations (low)
- [ ] `/v1/convai/agent-testing and /v1/convai/test-invocations` — agent test definitions and their invocation results for quality tracking (low)

Note: Official spec is large (277 paths); the ConvAI surface is the bulk of it. Static endpoint list in settings.py, no dynamic discovery.

## EmailOctopus — gaps

Today (3): `campaigns`, `contacts`, `lists`

Diffed against: <https://emailoctopus.com/api-documentation/v2>

- [ ] `/campaigns/{campaign_id}/reports/summary` — headline campaign metrics (sent, opened, clicked, bounced, complained, unsubscribed) — currently no campaign performance data at all (high)
- [ ] `/campaigns/{campaign_id}/reports?status={sent|opened|clicked|bounced|complained|unsubscribed|not-opened|not-clicked}` — per-contact campaign engagement events, the join between campaigns and contacts (high)
- [ ] `/campaigns/{campaign_id}/reports/links` — per-link click breakdown for a campaign (medium)
- [ ] `/lists/{list_id}/tags` — tag lookup resolving the tags carried on the contacts we already sync (medium)

Note: The docs URL serves the raw OpenAPI 3.1 JSON directly. The v2 API GET surface is only lists, campaigns, contacts and the campaign reports — contacts are already synced via /lists/{list_id}/contacts, so list membership is covered. Automations are write-only (POST queue), so there is nothing to sync there.

## Env0 — gaps

Today (7): `deployments`, `environment_costs`, `environments`, `organizations`, `projects`, `teams`, `templates`

Diffed against: <https://docs.envzero.com/llms.txt>

- [ ] `cost/get-costs-for-a-project and cost/get-costs-for-an-organization` — project- and org-level cost rollups; only per-environment cost is synced today (high)
- [ ] `environments/list-deployment-resources` — the resources a deployment created or changed — the analytical detail behind each deployment row (high)
- [ ] `environments/get-a-drifted-resources-events (and find-deployment-drift-status)` — drift detection events, one of env0's headline signals and absent from the current tables (high)
- [ ] `organization/list-users` — lookup resolving the user ids stamped on deployments, environments and role assignments (high)
- [ ] `roles/get-user-role-assignments and roles/get-team-role-assignments (+ roles/get-all-roles)` — membership and permission mapping between users, teams and projects (medium)
- [ ] `deployment-logs/find-all-steps-by-deployment-id` — per-step timing and status within a deployment, needed for duration and failure-stage analysis (medium)
- [ ] `cost/get-a-projects-budget and cost/get-projects-budget-summary-of-the-current-period` — budget targets to compare actual spend against (medium)
- [ ] `audit-events/fetch-audit-logs` — state and transition history across the organization (medium)
- [ ] `modules/list-modules and modules/list-module-versions` — module registry inventory that templates and environments reference (medium)
- [ ] `cloud-compass/find-cloud-resources and cloud-compass/get-resource-events` — cloud resource inventory and change events across linked cloud accounts (medium)
- [ ] `cost/get-weekly-costs-for-projects-or-environments` — pre-bucketed weekly cost series for trend reporting (low)
- [ ] `modules/list-module-test-runs` — module test run history for module reliability tracking (low)

Note: env0 is now branded 'env zero'; docs.env0.com and docs.envzero.com serve the same llms.txt index (~300 API reference pages). Mintlify openapi.json is not exposed at the root, so the llms.txt index was used as the resource list.

## Eppo — gaps

Today (10): `Audiences`, `Bandits`, `Environments`, `Experiments`, `FeatureFlags`, `Holdouts`, `MetricCollections`, `Metrics`, `Tags`, `Teams`

Diffed against: <https://eppo.cloud/api/docs-json>

- [ ] `/api/v1/definitions/facts` — fact (metric source) definitions — the lookup that explains what each synced metric is computed from (high)
- [ ] `/api/v1/definitions/entities` — entity lookup resolving the entity ids carried on metrics, experiments and assignments (high)
- [ ] `/api/v1/definitions/dimensions` — dimension definitions, the breakdown axes available on experiment analyses (high)
- [ ] `/api/v1/experiments/{experiment_id}/property-analysis` — experiment results broken down by metric and property — the actual analysis output, currently unavailable (high)
- [ ] `/api/v1/definitions/assignments` — assignment source definitions that tie experiments to their exposure data (medium)
- [ ] `/api/v1/experiments/{id}/diagnostics` — experiment health checks (sample ratio mismatch, traffic issues) per experiment (medium)
- [ ] `/api/v1/schedules` — experiment schedules, needed to reason about analysis cadence and experiment timelines (medium)
- [ ] `/api/v1/properties/entity and /api/v1/properties/metric` — property catalogs backing the breakdown dimensions used in analyses (medium)
- [ ] `/api/v1/definitions/entry-points` — entry point definitions used to scope experiment eligibility (medium)
- [ ] `/api/v1/feature-flags/{id}/environments/{environmentId}` — per-environment flag allocations and variation splits; the flat feature flag table alone does not carry them (medium)
- [ ] `/api/v1/definitions (combined definitions listing)` — single call returning all definition objects, a cheaper alternative to syncing each definitions sub-resource (low)
- [ ] `/api/v1/protocols` — experiment protocol templates referenced by experiments (low)

Note: eppo.cloud/api/docs is a Swagger UI shell; the machine-readable spec is at /api/docs-json (also /api/docs-yaml). The entire /api/v1/definitions/\* family (facts, entities, dimensions, assignments, entry-points) is missing and is where most lookup value sits.

## Eventbrite — gaps

Today (8): `attendees`, `categories`, `events`, `formats`, `orders`, `organizations`, `ticket_classes`, `venues`

Diffed against: <https://jsapi.apiary.io/apis/eventbriteapiv3public/api-description-document>

- [ ] `/reports/sales/ (Retrieve a Sales Report)` — the vendor's headline sales metric, aggregated gross/net/fees by event and date (high)
- [ ] `/reports/attendees/ (Retrieve an Attendee Report)` — aggregated attendee report, the companion headline metric to the sales report (high)
- [ ] `/events/{event_id}/questions/ and /events/{event_id}/canned_questions/` — lookup resolving the question ids referenced by the answers embedded in attendee and order records (high)
- [ ] `/subcategories/ (List of Subcategories)` — lookup resolving subcategory_id on events; only top-level categories are synced (high)
- [ ] `/organizations/{organization_id}/discounts/ (Search Discounts by Organization)` — discount and promo code definitions plus usage counts, needed to explain order pricing (medium)
- [ ] `/organizations/{organization_id}/ticket_groups/` — ticket group lookup that groups the ticket classes already synced (medium)
- [ ] `/organizations/{organization_id}/members/ (List Members of an Organization)` — organization membership, resolving who has access to the organizations already synced (medium)
- [ ] `/events/{event_id}/inventory_tiers/ (List Inventory Tiers by Event)` — capacity/inventory tiers behind ticket classes, needed for sell-through analysis (medium)
- [ ] `/organizations/{organization_id}/roles/ (List Roles by Organization)` — role lookup that resolves the role ids on organization members (low)
- [ ] `/events/{event_id}/teams/ and /events/{event_id}/teams/{team_id}/attendees/` — event team structure and team-level attendee membership for team-based events (low)
- [ ] `/events/{event_id}/pricing/ (List Pricing)` — fee and pricing breakdown per event, complements order line items (low)
- [ ] `/series/{series_id}/ (Retrieve an Event Series)` — series lookup grouping recurring events; note the API only exposes retrieve-by-id, so it needs fan-out from events (low)

Note: eventbrite.com/platform/api is a JS shell that embeds an Apiary doc; the backing spec is the 'eventbriteapiv3public' Apiary blueprint (found in the page bundle), fetched above — 32 resource groups, last updated 2024-02-16. The older vendor SDK (github.com/eventbrite/eventbrite-sdk-python access_methods.py) corroborates the endpoint shapes but predates the organization-scoped routes.

## Eventee — adequate

Today (11): `groups`, `halls`, `lectures`, `participants`, `partners`, `pauses`, `registrations`, `reviews`, `speakers`, `tracks`, `workshops`

Diffed against: <https://jsapi.apiary.io/apis/publiceventeeapi/api-description-document>

No material gaps found.

Note: The Public Eventee API has only five GET endpoints: /content, /reviews, /groups, /participants, /registrations. /content returns a single payload containing halls, lectures, speakers, tracks, workshops, pauses and partners — exactly the tables PostHog already exposes. Everything else in the API is write-only (POST/PATCH/DELETE on hall, lecture, speaker, label, pause, partner, attendee invite/checkin). Coverage is complete. The apiary.io docs page is a JS shell; the blueprint JSON is at the jsapi.apiary.io URL above.

## Eventzilla — adequate

Today (6): `attendees`, `categories`, `events`, `tickets`, `transactions`, `users`

Diffed against: <https://developer.eventzilla.net/docs/>

No material gaps found.

Note: The Redoc page embeds the full OpenAPI document. Its entire GET surface is /events, /events/{id}, /categories, /events/{id}/attendees, /events/{id}/transactions, /events/{id}/tickets (ticket types), /attendees/{id}, /users, /users/{id}, /transactions/{identifier} — every one is already represented by the six synced tables. The remaining paths are write-only checkout and order-management flows (/checkout/\*, /events/order/\*, /events/togglesales, /attendee/checkin) plus ticket-type mutations, none of which are queryable resources. The source already fans out event-scoped child endpoints per event.

## Everhour — gaps

Today (5): `clients`, `projects`, `tasks`, `time_records`, `users`

Diffed against: <https://everhour.docs.apiary.io/api-description-document>

- [ ] `GET /invoices, GET /invoices/{id}` — client billing documents and line items; the revenue side of tracked time (high)
- [ ] `GET /expenses` — project cost records that pair with time_records for margin analysis (high)
- [ ] `GET /timecards, GET /users/{user_id}/timecards` — clock-in/clock-out attendance records, distinct from time_records (high)
- [ ] `GET /resource-planner/assignments` — scheduled/planned work per user, project and task - planned vs actual (high)
- [ ] `GET /expenses/categories` — lookup table resolving the category id carried on every expense (high)
- [ ] `GET /timesheets, GET /users/{user_id}/timesheets` — weekly timesheet approval state and transitions (medium)
- [ ] `GET /resource-planner/time-off-types` — lookup resolving time-off type ids on assignments/allocations (medium)
- [ ] `GET /allocations` — time-off and capacity allocations per user (medium)
- [ ] `GET /projects/{project_id}/sections` — lookup resolving the section id on tasks (medium)
- [ ] `GET /projects/{project_id}/fields` — custom field definitions needed to interpret task custom field values (medium)
- [ ] `GET /dashboards/projects, /dashboards/clients, /dashboards/users` — prebuilt report aggregates by project, client and member (low)

Note: Static endpoint list in get_schemas - no dynamic table discovery. Apiary blueprint is served as API Blueprint markdown, not JSON, at the /api-description-document path.

## ExchangeRatesApi — gaps

Today (3): `latest`, `symbols`, `timeseries`

Diffed against: <https://exchangeratesapi.io/documentation/>

- [ ] `GET /v1/fluctuation` — start/end rate plus absolute and percent change per currency over a window - a distinct dataset, not derivable without extra math (medium)
- [ ] `GET /v1/{YYYY-MM-DD} (historical rates)` — point-in-time rates for a single date; cheaper than a timeseries pull for date-keyed joins (low)

Note: Tiny API - the documented endpoints are symbols, latest, historical, convert, timeseries and fluctuation. `convert` is a calculator (amount in, amount out) rather than a queryable collection, so it is deliberately excluded. Coverage is close to proportionate.

## EZOfficeInventory — gaps

Today (12): `asset_stocks`, `assets`, `checked_out_assets`, `custom_fields`, `groups`, `inventories`, `labels`, `locations`, `members`, `purchase_orders`, `subgroups`, `vendors`

Diffed against: <https://ezo.io/ezofficeinventory/developers/>

- [ ] `GET /assets/{id}/history.api and /members/{id}/checkin_checkout_history.api (+ checkin_checkout_history_for_stock.api)` — check-in/check-out transition history - the utilization fact table; the source only has the point-in-time checked_out_assets snapshot (high)
- [ ] `GET /tasks.api (work orders) and /tasks/filter` — work orders with state, assignee and duration - a core analytical object with no coverage at all (high)
- [ ] `GET /services.api` — service/maintenance records per asset, the basis for downtime and maintenance-cost reporting (high)
- [ ] `GET /teams.api` — team lookup resolving the team IDs carried on members and assignments (high)
- [ ] `GET /custom_roles.api` — role lookup resolving the role reference on every member row already synced (medium)
- [ ] `GET /task_types.api` — work order type lookup, the primary breakdown dimension for work orders (medium)
- [ ] `GET /reservation_requests.api and /checkout_requests/filter.api` — reservations and booking requests - forward-looking demand against the asset pool (medium)
- [ ] `GET /baskets.api (carts)` — cart records grouping multi-item checkouts, needed to reconstruct a checkout event from its line items (medium)
- [ ] `GET /bundles.api` — asset bundle definitions and their membership, a grouping dimension for utilization (medium)
- [ ] `GET /projects.api` — projects that assets, carts and checkouts are linked to - a cost-attribution dimension (medium)
- [ ] `GET /depreciation_methods.api` — depreciation method lookup for asset valuation reporting (medium)
- [ ] `GET /retire_reasons.api` — lookup resolving the retire reason code on retired assets (low)

Note: Endpoint list extracted from the \*.api URLs on the developers page. Also missing but below the cut: /comments.api, /packages.api, /user_listings.api, /custom_attribute_history.api, /inventory_reservations.api, /reports/list_custom_reports.api, /locations/get_quantity_by_location.api.

## Factorial — **thin**

Today (17): `allowances`, `applications`, `attendance_shifts`, `candidates`, `contract_versions`, `employees`, `expenses`, `flexible_time_records`, `job_postings`, `leave_types`, `leaves`, `legal_entities`, `locations`, `payroll_supplements`, `projects`, `team_memberships`, `teams`

Diffed against: <https://apidoc.factorialhr.com/reference>

- [ ] `attendance/worked_times` — aggregated worked time per employee and day - the headline attendance metric, currently only raw shifts are synced (high)
- [ ] `project_management/time_records` — time booked against projects; projects are synced but the time booked to them is not (high)
- [ ] `contracts/compensations` — salary and compensation amounts attached to contract versions we already sync (high)
- [ ] `timeoff/allowance_stats` — consumed vs remaining balance per employee and allowance - the number leave reporting actually needs (high)
- [ ] `ats/hiring_stages and ats/application_phases` — lookup tables resolving the stage/phase id carried on every synced application (high)
- [ ] `finance/cost_centers` — lookup table for cost allocation across employees, expenses and projects (high)
- [ ] `employee_updates/terminations` — attrition events with dates and reasons; headcount churn is not derivable from the employees snapshot (high)
- [ ] `employee_updates/new_hires` — hire events for headcount growth and time-to-start reporting (medium)
- [ ] `finance/cost_center_memberships` — employee-to-cost-center membership needed to attribute cost (medium)
- [ ] `ats/candidate_sources` — lookup resolving the source id on candidates; source-of-hire is a core recruiting breakdown (medium)
- [ ] `attendance/overtime_requests` — overtime volume and approval state per employee (medium)
- [ ] `job_catalog/roles and job_catalog/levels` — lookup tables for role and level ids used in compensation banding (medium)

Note: The reference exposes roughly 140 list endpoints across ATS, attendance, contracts, finance, payroll, performance, procurement, project management, time off, trainings and work schedules; PostHog covers 17. Other notable untapped families: performance review evaluations/scores, banking transactions, finance journal entries/lines, procurement purchase orders, trainings sessions/attendances, shift management, custom field values. The docs hub is readme.io with no downloadable OpenAPI - the resource list was read off the /reference sidebar route slugs (api-2026-07-01).

## Fastly — **thin**

Today (7): `current_user`, `service_acls`, `service_backends`, `service_dictionaries`, `service_domains`, `service_versions`, `services`

Diffed against: <https://www.fastly.com/documentation/reference/api/>

- [ ] `metrics-stats/historical-stats (/stats, /stats/service/{id})` — per-service historical traffic, cache hit ratio, bandwidth and errors - Fastly's headline metric and the main reason to warehouse this data (high)
- [ ] `account/billing-usage-metrics` — usage and spend per product and service over time (high)
- [ ] `dictionaries/dictionary-item` — lookup table - the actual key/value rows inside the service_dictionaries we already sync (high)
- [ ] `acls/acl-entry` — lookup table - the IP entries inside the service_acls we already sync (high)
- [ ] `account/invoices` — billed amounts per period for cost reporting (high)
- [ ] `metrics-stats/origin-inspector` — origin-level latency, status and byte breakdowns (medium)
- [ ] `metrics-stats/domain-inspector` — per-domain request and error breakdowns, the natural dimension for service_domains (medium)
- [ ] `account/events` — account audit event log - who changed what and when (medium)
- [ ] `account/customer (and its users list)` — lookup resolving customer ids on services and users; today only current_user is synced (medium)
- [ ] `account/service-authorization` — user-to-service permission membership table (medium)
- [ ] `utils/pops` — lookup resolving POP/datacenter codes that appear in stats and inspector breakdowns (medium)

Note: Current coverage is almost entirely service configuration objects; none of the metrics-stats or account/billing families are exposed. Fastly's own OpenAPI YAML is no longer served at the old developer.fastly.com path (404) - the category tree was read from the live documentation reference index and its per-category pages. Logging endpoint types (~25 of them), TLS, purging and VCL objects are config/plumbing and deliberately excluded.

## Featurebase — **thin**

Today (10): `admins`, `boards`, `changelogs`, `comments`, `companies`, `contacts`, `custom_fields`, `post_statuses`, `post_voters`, `posts`

Diffed against: <https://developers.featurebase.app/llms.txt>

- [ ] `support/conversations (list, search)` — the entire support inbox - conversation volume, first response and resolution analysis (high)
- [ ] `support/tickets (list)` — ticket workload and lifecycle, the other half of the support product (high)
- [ ] `support/tickets/statuses` — lookup table resolving the status id on every ticket (high)
- [ ] `support/conversation_tags (list)` — lookup table for tags applied to conversations - the main support breakdown dimension (high)
- [ ] `surveys and surveys/list_responses` — survey responses are raw analytical rows (NPS/CSAT style) with no equivalent in the synced tables (high)
- [ ] `support/tickets/categories` — lookup resolving ticket category ids (medium)
- [ ] `help_center/articles (list)` — article inventory for content and deflection analysis (medium)
- [ ] `organization/teams` — lookup resolving the team an admin or conversation is assigned to (medium)
- [ ] `audit_logs (list)` — workspace change history (medium)
- [ ] `users/companies/{id}/contacts` — company-to-contact membership table joining the companies and contacts we already sync (medium)
- [ ] `support/conversations/{id}/participants` — participant membership per conversation (medium)
- [ ] `help_center/collections` — lookup grouping articles into collections (low)

Note: Featurebase has grown well past the feedback board: the reference now spans Support (conversations + tickets), Help Center, Surveys, Reports and Audit Logs. PostHog's 10 tables cover the Feedback pillar plus admins/companies/contacts only. Reports is a query API (list_datasets/query/drill_in) rather than a fixed collection, so it is not listed as a table gap. llms.txt at developers.featurebase.app gives the complete language-neutral resource tree.

## Fillout — gaps

Today (2): `forms`, `submissions`

Diffed against: <https://www.fillout.com/llms.txt>

- [ ] `GET /v1/api/forms/{formId} (form metadata)` — lookup table of every question, its id, type and choice options - without it the question ids inside submissions cannot be resolved to labels (high)

Note: Very small API. The full published reference is 8 endpoints: get forms, get form metadata, get all submissions, get submission by id, create submissions, delete submission, create webhook, remove webhook. Webhook and write endpoints are correctly out of scope, so form metadata is the only real gap. get_schemas is a static ENDPOINTS list - no dynamic discovery.

## Finage — **thin**

Today (3): `aggregates`, `last_quote`, `last_trade`

Diffed against: <https://finage.co.uk/docs/api>

- [ ] `/symbol-list/{market} (Full Symbol List API)` — lookup table of tradeable symbols per market - resolves the symbol keys every other table is built on (high)
- [ ] `/fnd/detail/stock/{symbol} (Stock Market Details)` — company profile: name, exchange, sector, industry - the dimension table for all price data (high)
- [ ] `/fnd/income-statement/{symbol}` — core fundamentals; currently no financial statement data is exposed at all (high)
- [ ] `/fnd/balance-sheet-statements/{symbol}` — core fundamentals alongside income statements (high)
- [ ] `/fnd/cash-flow-statement/{symbol}` — completes the three-statement set (high)
- [ ] `/fnd/historical-dividends/{symbol} and /fnd/dividend-calendar` — dividend events needed for total-return calculations on the aggregates already synced (high)
- [ ] `/fnd/historical-stock-splits/{symbol} and /fnd/stock-split-calendar` — split events are required to make historical aggregates comparable across time (high)
- [ ] `/fnd/financial-ratios/{symbol}` — precomputed valuation and profitability ratios (medium)
- [ ] `/agg/stock/prev-close/{symbol}` — previous close reference price for daily change calculations (medium)
- [ ] `/snapshot/stock (also /snapshot/forex, /snapshot/crypto)` — whole-market snapshot in one call rather than per-symbol quote fetches (medium)
- [ ] `/fnd/earning-calendar and /fnd/ipo-calendar` — scheduled corporate events to join against price moves (medium)
- [ ] `/last/crypto, /last/forex, /agg/crypto, /agg/forex (non-equity asset classes)` — same quote/trade/aggregate shapes for FX, crypto, ETF and index, none of which are reachable today (medium)

Note: The docs are a client-rendered playground, but the full endpoint catalog is embedded in the /docs/api HTML (126 distinct api.finage.co.uk paths, ~72 titled endpoints across US/UK/CA/IN/RU equities, forex, crypto, ETF, index, fundamentals, news and technical indicators). PostHog exposes 3 static endpoints. get_schemas uses a fixed FINAGE_ENDPOINTS map - no dynamic discovery.

## FinancialModelling — **thin**

Today (8): `balance_sheet_statements`, `cash_flow_statements`, `company_profiles`, `dividends_calendar`, `earnings_calendar`, `historical_prices`, `income_statements`, `stock_list`

Diffed against: <https://site.financialmodelingprep.com/developer/docs/stable>

- [ ] `/stable/key-metrics (and key-metrics-ttm)` — FMP's headline per-company metric set; nothing equivalent is synced today (high)
- [ ] `/stable/ratios (and ratios-ttm)` — valuation and profitability ratios derived from the statements we already sync (high)
- [ ] `/stable/dividends` — actual per-symbol dividend history; only the forward dividends_calendar is synced (high)
- [ ] `/stable/earnings` — historical actual vs estimated EPS and revenue per symbol; only the forward earnings_calendar is synced (high)
- [ ] `/stable/splits` — split history, required to make historical_prices comparable across time (high)
- [ ] `/stable/available-exchanges, /stable/available-sectors, /stable/available-industries` — lookup tables resolving the exchange, sector and industry codes carried on stock_list and company_profiles (high)
- [ ] `/stable/historical-market-capitalization (and /stable/market-capitalization)` — market cap time series, the standard size dimension for any equity analysis (medium)
- [ ] `/stable/analyst-estimates and /stable/price-target-consensus` — forward estimates and consensus targets to compare against reported results (medium)
- [ ] `/stable/quote (and batch-quote)` — current price snapshot without pulling full historical series (medium)
- [ ] `/stable/institutional-ownership/extract and /symbol-positions-summary` — 13F institutional holdings per symbol and per holder (medium)
- [ ] `/stable/insider-trading/search and /insider-trading/statistics` — insider transaction records, a widely used signal table (medium)
- [ ] `/stable/revenue-product-segmentation and /stable/revenue-geographic-segmentation` — revenue breakdown dimensions that the income statement alone cannot provide (medium)

Note: The stable docs page lists ~230 endpoints; PostHog exposes 8. Other sizeable untapped families: financial-growth and \*-growth, enterprise-values, DCF endpoints, financial-scores, grades/ratings-historical, SEC filings search, ETF and fund holdings, economic-indicators and treasury-rates, congressional trading, index constituents, news, technical indicators, and the \*-bulk endpoints that would make warehouse-scale loads far cheaper. financialmodelingprep.com/stable/openapi.json exists but returns 401 without a key, and the site 403s default curl user agents - a browser UA on the docs page returns the full endpoint list.

## Finnhub — **thin**

Today (11): `basic_financials`, `company_news`, `company_profile`, `country`, `earnings_calendar`, `earnings_surprises`, `ipo_calendar`, `market_news`, `quote`, `recommendation_trends`, `stock_symbols`

Diffed against: <https://finnhub.io/static/swagger.json>

- [ ] `/stock/financials-reported` — full as-reported income statement, balance sheet and cash flow per filing; basic_financials only gives ratios (high)
- [ ] `/stock/candle` — historical OHLCV bars, the backbone of any price time-series analysis (quote is a point-in-time snapshot only) (high)
- [ ] `/stock/filings` — SEC filing index per symbol, the join key from company to disclosure documents (high)
- [ ] `/stock/insider-transactions` — insider buy/sell transaction rows, a headline alt-data signal (high)
- [ ] `/stock/dividend` — dividend history transactions; nothing in the current table set carries payouts (high)
- [ ] `/stock/peers` — lookup table resolving each synced symbol to its comparable set for benchmarking (high)
- [ ] `/stock/price-target` — analyst price targets, a natural companion to recommendation_trends which is already synced (medium)
- [ ] `/stock/upgrade-downgrade` — individual analyst rating change events behind the aggregated recommendation trends (medium)
- [ ] `/stock/eps-estimate (plus revenue-estimate, ebitda-estimate, ebit-estimate)` — forward consensus estimates to pair with the already-synced earnings surprises (medium)
- [ ] `/stock/split` — split events needed to adjust any price or per-share series (medium)
- [ ] `/index/constituents` — lookup table mapping indices to member symbols, enabling index-level roll-ups of synced symbols (medium)
- [ ] `/calendar/economic` — macro event calendar; earnings and IPO calendars are already synced but the economic one is not (medium)

Note: Finnhub's public swagger exposes ~115 GET resources; PostHog syncs 11. Ownership (/stock/ownership, /stock/fund-ownership, /institutional/ownership), transcripts (/stock/transcripts/list), ETF/mutual-fund holdings, historical market cap and revenue breakdowns are also absent but ranked below the 12 above.

## Finnworlds — gaps

Today (11): `balance_sheets`, `bond_yields`, `cash_flows`, `company_information`, `company_ratings`, `dividends`, `financial_ratios`, `income_statements`, `sec_filings`, `stock_prices`, `stock_splits`

Diffed against: <https://finnworlds.com/documentation/>

- [ ] `Company Identification` — ticker/ISIN/CIK lookup table that resolves the company identifiers every other synced table keys on (high)
- [ ] `Historical Candlestick` — historical OHLC series; stock_prices only covers real-time quotes so there is no price history to analyze (high)
- [ ] `Insider Transactions` — insider trade rows, a core analytical fact table absent from the current set (high)
- [ ] `Market Exchanges` — lookup resolving the exchange codes carried on company and price rows (medium)
- [ ] `Stock Market Index` — index level series needed to benchmark the synced company data (medium)
- [ ] `Macroeconomic Data` — macro indicator series, one of Finnworlds' headline datasets (medium)
- [ ] `Economic Calendar` — scheduled macro releases; useful for event-study joins against price data (medium)
- [ ] `Currency Exchange Rates` — FX rates required to normalize multi-currency financial statements (medium)
- [ ] `ETF Holdings` — fund-to-holding breakdown rows linking funds to already-synced companies (medium)
- [ ] `Mutual Fund Holdings` — same fund-to-holding join for mutual funds (medium)
- [ ] `Historical Bond Yields` — bond_yields is synced but only current; the historical series is what yield-curve analysis needs (medium)
- [ ] `Commodity Prices / Historical Commodity Prices` — commodity series completing the asset-class coverage of the API (low)

Note: Finnworlds publishes no machine-readable spec; the resource list was read off the section headings of the single-page documentation. Technical Indicators, Options Chain, Available Bonds and Search Terms & Volumes are also unsynced but are lower value for a warehouse.

## Firecrawl — adequate

Today (6): `active_crawls`, `credit_usage_historical`, `monitor_checks`, `monitors`, `team_activity`, `token_usage_historical`

Diffed against: <https://docs.firecrawl.dev/llms.txt>

No material gaps found.

Note: Firecrawl's v2 API is action-oriented: nearly every endpoint is a POST job (scrape, crawl, batch-scrape, map, search, extract, parse) whose results are fetched per job ID, not a queryable collection. The listable GET collections are activity, crawl/active, credit-usage(+historical), token-usage(+historical), monitors and monitor checks - and PostHog syncs six of them. The only unsynced GETs are the current credit/token balance snapshots (the historical variants are already synced), team queue-status, threat-protection policy (config), Interact browser session listing, and per-job crawl/batch-scrape error lists, none of which justify a table.

## FireHydrant — gaps

Today (24): `alerts`, `change_events`, `changes`, `checklist_templates`, `custom_field_definitions`, `environments`, `functionalities`, `incident_roles`, `incident_tags`, `incident_types`, `incidents`, `integrations`, `post_mortem_reports`, `priorities`, `runbook_executions`, `runbooks`, `scheduled_maintenances`, `services`, `severities`, `signals_on_call`, `task_lists`, `teams`, `users`, `webhooks`

Diffed against: <https://raw.githubusercontent.com/firehydrant/firehydrant-typescript-sdk/main/openapi.yaml>

- [ ] `/v1/incidents/{incident_id}/milestones` — the incident state-transition history that every MTTx and lifecycle calculation is built from (high)
- [ ] `/v1/incidents/{incident_id}/events` — the full incident timeline; incidents alone give no in-incident activity (high)
- [ ] `/v1/incidents/{incident_id}/role_assignments` — membership table joining incidents to users and the already-synced incident_roles (high)
- [ ] `/v1/metrics/mttx` — FireHydrant's headline reliability metric (MTTA/MTTR/MTTM) with no equivalent in the current tables (high)
- [ ] `/v1/schedules` — org-wide on-call schedules; signals_on_call is synced but the schedule definitions it references are not (high)
- [ ] `/v1/teams/{team_id}/escalation_policies` — lookup resolving how alerts route per team, joining teams already synced (high)
- [ ] `/v1/incidents/{incident_id}/tasks` — task_lists is synced but not the actual tasks executed on incidents (high)
- [ ] `/v1/change_types` — lookup table resolving the change type carried on the synced changes and change_events rows (medium)
- [ ] `/v1/lifecycles/phases and /v1/lifecycles/measurement_definitions` — lookup tables that give milestones and lifecycle measurements their names and ordering (medium)
- [ ] `/v1/ticketing/tickets (plus /v1/ticketing/priorities, /v1/ticketing/ticket_tags)` — follow-up work tracked off incidents, entirely absent today (medium)
- [ ] `/v1/services/{service_id}/dependencies` — service dependency graph edges; services are synced but their relationships are not (medium)
- [ ] `/v1/metrics/incidents, /v1/metrics/milestone_funnel, /v1/metrics/retrospectives, /v1/metrics/user_involvements` — prebuilt reporting aggregates for incident volume, funnel conversion and responder load (medium)

Note: The repo already carries products/warehouse_sources/backend/temporal/data_imports/sources/firehydrant/api_inventory.md, which cites this same spec. The docs sidebar at docs.firehydrant.com additionally lists list_audit_events and list_incident_retrospectives, which do not appear in the SDK OpenAPI file, so paths for those could not be confirmed and they are omitted.

## FireworksAI — gaps

Today (10): `batch_inference_jobs`, `datasets`, `deployed_models`, `deployments`, `evaluation_jobs`, `evaluators`, `models`, `reinforcement_fine_tuning_jobs`, `supervised_fine_tuning_jobs`, `users`

Diffed against: <https://docs.fireworks.ai/llms.txt>

- [ ] `GET /v1/accounts/{account_id}/usage (Get Account Usage)` — per-model token and spend usage, the headline analytical metric for an inference platform (high)
- [ ] `GET /v1/accounts/{account_id}/dpoJobs (List dpo jobs)` — a whole fine-tuning job type missing alongside the already-synced supervised and reinforcement jobs (high)
- [ ] `List Reinforcement Fine-tuning Steps` — per-step training progression under each RFT job, the state history behind job outcomes (high)
- [ ] `List Responses` — stored inference response records - the closest thing to an event table this API offers (medium)
- [ ] `Get billing summary` — account-level cost roll-up complementing raw usage (medium)
- [ ] `List Routers` — router definitions that requests are attributed to; needed to interpret usage by route (medium)
- [ ] `List Deployment Shapes Versions` — lookup resolving the hardware shape referenced by every synced deployment row (medium)
- [ ] `List Accounts` — lookup resolving the account each synced resource is namespaced under, for multi-account orgs (low)
- [ ] `List Quotas` — quota limits to compare against observed usage (low)

Note: API keys and secrets endpoints exist but are excluded as credential plumbing. The inference endpoints (chat/completions, embeddings, rerank) are request-time, not queryable collections.

## Flagsmith — gaps

Today (8): `audit_logs`, `environments`, `feature_states`, `features`, `organisations`, `projects`, `segments`, `users`

Diffed against: <https://api.flagsmith.com/api/v1/swagger.json>

- [ ] `/api/v1/environments/{environment_api_key}/identities/` — the end users flags are evaluated against; without them feature_states cannot be attributed to anyone (high)
- [ ] `/api/v1/environments/{environment_api_key}/identities/{identity_pk}/traits/` — identity traits, the attributes segments are defined on - the core targeting dimension (high)
- [ ] `/api/v1/features/feature-segments/` — lookup/join table linking already-synced features to already-synced segments (the segment overrides) (high)
- [ ] `/api/v1/projects/{project_pk}/features/{id}/evaluation-data/` — flag evaluation counts over time, Flagsmith's headline usage metric (high)
- [ ] `/api/v1/projects/{project_pk}/segments/{id}/members/` — segment membership rows resolving which identities fall into each synced segment (high)
- [ ] `/api/v1/projects/{project_pk}/tags/` — lookup resolving the tag IDs carried on synced feature rows (high)
- [ ] `/api/v1/organisations/{organisation_pk}/usage-data/` — API request volume per organisation, needed for cost and adoption analysis (medium)
- [ ] `/api/v1/projects/{project_pk}/features/{feature_pk}/mv-options/` — multivariate variant definitions and weights behind multivariate feature states (medium)
- [ ] `/api/v1/environments/{environment_api_key}/identities/{identity_pk}/featurestates/` — per-identity flag overrides, distinct from the environment-level feature_states already synced (medium)
- [ ] `/api/v1/environments/{environment_pk}/features/{feature_pk}/versions/` — environment feature version history - the state-change trail for a flag in an environment (medium)
- [ ] `/api/v1/projects/{project_pk}/change-requests/ (and the environment list-change-requests)` — flag change approval workflow records, showing who requested and approved each change (medium)
- [ ] `/api/v1/organisations/{organisation_pk}/groups/` — user group membership lookup resolving the groups referenced on feature owners and permissions (medium)

Note: Spec is the live Flagsmith SaaS swagger (325 paths). Roles, permissions, SAML/SCIM, integrations and master API keys are excluded as access-control and plumbing config.

## Fleetio — gaps

Today (9): `contacts`, `fuel_entries`, `issues`, `meter_entries`, `parts`, `service_entries`, `vehicle_assignments`, `vehicles`, `work_orders`

Diffed against: <https://developer.fleetio.com/sitemap.xml>

- [ ] `expense_entries (and expense_entry_types)` — non-service vehicle costs; without them total cost of ownership cannot be computed from the synced tables (high)
- [ ] `service_entry_line_items (v2)` — line-item detail behind each synced service entry - labor, parts and cost breakdown (high)
- [ ] `work_order_statuses` — lookup resolving the status ID on every synced work_orders row (high)
- [ ] `vehicle_statuses` — lookup resolving the status ID on every synced vehicles row (high)
- [ ] `vehicle_types` — lookup resolving vehicle type IDs, the main breakdown dimension for fleet analysis (high)
- [ ] `service_tasks` — lookup resolving the task IDs referenced by service entries, work orders and service reminders (high)
- [ ] `vendors` — lookup resolving vendor IDs on service entries, fuel entries and purchase orders (high)
- [ ] `purchase_orders (and purchase_order_line_items)` — parts procurement transactions and their line items; parts are synced but never their purchases (medium)
- [ ] `faults` — diagnostic trouble code events streamed off vehicles - a primary reliability signal (medium)
- [ ] `location_entries` — vehicle location history, enabling utilization and route analysis (medium)
- [ ] `service_reminders` — upcoming and overdue maintenance state, the operational counterpart to the synced service entries (medium)
- [ ] `inventory_journal_entries` — parts inventory movements; parts are synced only as current stock levels (medium)

Note: No OpenAPI file is published; the resource list came from the Docusaurus sitemap, which enumerates every documented endpoint page (index/show/create/update per resource) under /docs/api/2023-03-01/. Also unsynced but lower value: equipment and equipment_assignments, submitted_inspection_forms, issue_priorities, fuel_types, groups, labels, places, tires, vehicle/contact renewal reminders and types, part_locations, comments, vmrs_reason_for_repairs.

## Flexmail — gaps

Today (7): `contacts`, `custom_fields`, `interests`, `opt_in_forms`, `preferences`, `segments`, `sources`

Diffed against: <https://api.flexmail.eu/documentation/openapi.php>

- [ ] `/contacts/{id}/interest-subscriptions` — membership table joining synced contacts to synced interests - the only way to segment by interest (high)
- [ ] `/contacts/{id}/preferences` — membership table joining contacts to the synced preferences (consent/topic opt-ins) (high)
- [ ] `/contacts/{id}/sources` — attribution rows linking each contact to the synced sources that acquired them (high)
- [ ] `/interest-labels` — lookup resolving the label IDs carried on interest rows (medium)
- [ ] `/contacts/{id}/interest-labels` — per-contact interest labels, a second targeting dimension not derivable from the synced tables (medium)
- [ ] `/account-contact-languages` — lookup resolving the language code on contact rows (low)

Note: The Flexmail public API is contact-management only - it exposes no campaigns, mailings, sends, opens or clicks - so the synced set already covers every top-level collection. The genuine gaps are all per-contact sub-resources, which need a contact-ID-driven fan-out rather than a plain list endpoint. Webhooks and webhook-events are excluded as plumbing.

## FloatApp — gaps

Today (18): `accounts`, `clients`, `deleted_logged_time`, `deleted_tasks`, `deleted_timeoffs`, `departments`, `holidays`, `logged_time`, `milestones`, `people`, `phases`, `project_tasks`, `projects`, `roles`, `status`, `tasks`, `timeoff_types`, `timeoffs`

Diffed against: <https://developer.float.com/swagger-api-v3.yaml>

- [ ] `/project-stages` — lookup table resolving the stage IDs carried on the projects we already sync (high)
- [ ] `/rate-cards` — lookup for the rate card IDs on people/projects; required to turn logged hours into billable value (high)
- [ ] `/reports/people` — Float's headline utilization/capacity report per person, pre-aggregated (high)
- [ ] `/reports/projects` — per-project scheduled vs logged vs billable breakdown (medium)
- [ ] `/project-expenses` — non-labor project cost, needed for true project margin alongside logged_time (medium)
- [ ] `/public-holidays` — region public holidays; distinct from the team /holidays table already synced, needed for correct capacity math (medium)
- [ ] `/currencies` — lookup for currency codes on rate cards and project budgets (low)

Note: Machine-readable OpenAPI at /swagger-api-v3.yaml enumerates 26 resources; PostHog covers 18. /project-templates was excluded as config.

## Flowlu — **thin**

Today (13): `accounts`, `agile_issues`, `agile_sprints`, `customer_payments`, `estimates`, `invoices`, `leads`, `pipelines`, `products`, `projects`, `tasks`, `timesheets`, `transactions`

Diffed against: <https://www.flowlu.com/api/json/openapien.json>

- [ ] `/crm/pipeline_stage/list` — lookup resolving the stage ID on every lead; we sync pipelines but not their stages (high)
- [ ] `/fin/invoice_item/list` — invoice line items - revenue by product/service instead of invoice totals only (high)
- [ ] `/timetracker/timelogs/list` — individual time log entries behind the timesheet rollups already synced (high)
- [ ] `/st/stages/list` — lookup resolving project stage IDs on the projects table (high)
- [ ] `/crm/source/list` — lookup resolving lead source IDs - core attribution dimension (high)
- [ ] `/agile/stages/list` — lookup resolving the workflow stage on agile_issues (high)
- [ ] `/task/stages/list` — lookup resolving task workflow stage IDs (medium)
- [ ] `/agile/issue_type/list` — lookup resolving issue type IDs on agile_issues (medium)
- [ ] `/fin/estimate_item/list` — estimate line items, the quoted counterpart to invoice items (medium)
- [ ] `/st/project_expense/list` — project expenses, needed for project profitability (medium)
- [ ] `/fin/organization/list` — lookup resolving the billing organization on invoices/transactions (medium)
- [ ] `/crm/loss_reason/list` — lookup resolving loss reason IDs on closed-lost leads (medium)

Note: developers.flowlu.com is the API host, not docs (returns 404/api-key errors). The real spec is the ReDoc document at https://www.flowlu.com/api/json/openapien.json: 608 paths, 124 of them `/list` collections. PostHog exposes 13, so this is a small fraction - other untouched clusters include knowledgebase/\*, businessprocess/\*, telephony/calls, im/\* (chat threads and messages), products/pricelist_item and company/absences.

## FlyIo — gaps

Today (3): `apps`, `machines`, `volumes`

Diffed against: <https://docs.machines.dev/spec/openapi3.json>

- [ ] `/apps/{app_name}/machines/{machine_id}/events` — machine state-transition history (start/stop/OOM/restart) - the only way to analyze uptime and crash patterns (high)
- [ ] `/platform/regions` — lookup resolving the region codes already carried on machines and volumes (medium)
- [ ] `/apps/{app_name}/machines/{machine_id}/versions` — per-machine config version history, gives deploy/rollout timeline (medium)
- [ ] `/apps/{app_name}/volumes/{volume_id}/snapshots` — snapshot history per volume for backup coverage reporting (medium)
- [ ] `/postgres` — managed Postgres cluster inventory (plus /postgres/{id}/databases) missing from the infra picture (low)

Note: PostHog syncs machines/volumes via the org-wide /orgs/{org_slug}/... routes; events and versions only exist per-machine, so they need a fan-out over the machines table. secrets/secretkeys, certificates and lease endpoints excluded as plumbing.

## Formbricks — gaps

Today (7): `action_classes`, `contact_attribute_keys`, `contact_attributes`, `contacts`, `responses`, `surveys`, `webhooks`

Diffed against: <https://formbricks.com/docs/api-reference/openapi.json>

- [ ] `/api/v2/organizations/{organizationId}/users` — organization members - resolves the user IDs on surveys and responses (medium)
- [ ] `/api/v2/organizations/{organizationId}/teams` — teams that own surveys/workspaces (medium)
- [ ] `/api/v2/organizations/{organizationId}/workspace-teams` — team-to-workspace membership mapping, the join table between teams and surveys (medium)
- [ ] `/api/v2/roles` — lookup resolving membership role values on org users (low)

Note: The v1 management API spec (openapi.json, 23 paths) is fully covered - every GET-listable v1 resource is already synced. The remaining gaps come from the v2 organizations API, enumerated from https://formbricks.com/docs/llms.txt (api-v2-reference/organizations-api--\* and api-v2-reference/roles/get-roles). Displays and storage have no list endpoint.

## Freshcaller — gaps

Today (4): `call_metrics`, `calls`, `teams`, `users`

Diffed against: <https://developers.freshcaller.com/api/>

- [ ] `/api/v1/user-statuses` — lookup resolving the custom agent status IDs on users and call legs (available/break/etc) (medium)

Note: Freshcaller's public API is genuinely small - calls, call_metrics (with include=life_cycle), teams, users, user-statuses, plus recording download/delete and an account export job. PostHog covers 4 of the 5 listable collections; call recordings are per-call binaries, not a queryable collection.

## Freshchat — gaps

Today (5): `accounts_configuration`, `agents`, `channels`, `groups`, `users`

Diffed against: <https://developers.freshchat.com/api/>

- [ ] `/v2/users/{user_id}/conversations` — conversations are the product's core analytical object and are entirely absent today (high)
- [ ] `/v2/conversations/{conversation_id}/messages` — message-level data for response time, volume and agent workload analysis (high)
- [ ] `/v2/roles` — lookup resolving the role IDs carried on agents (high)
- [ ] `/v2/reports/raw` — bulk raw data export - the practical way to land conversation/agent history at scale (medium)
- [ ] `/v2/outbound-messages` — outbound campaign message sends and their delivery state (medium)
- [ ] `/v2/metrics/historical` — vendor-computed historical conversation/agent metrics (medium)

Note: There is no top-level GET /v2/conversations list - conversations are only enumerable per user (/v2/users/{user_id}/conversations), so an implementation must fan out from the users table already synced, then fan out again for messages. /v2/agents/{id} status updates and business-hours/within-bh are write/check endpoints, not collections.

## Freshdesk — gaps

Today (14): `agents`, `business_hours`, `canned_response_folders`, `companies`, `contacts`, `groups`, `products`, `roles`, `satisfaction_ratings`, `skills`, `sla_policies`, `ticket_fields`, `tickets`, `time_entries`

Diffed against: <https://developers.freshdesk.com/api/>

- [ ] `/api/v2/tickets/{id}/conversations` — ticket replies and notes - the actual support conversation behind every ticket row we sync (high)
- [ ] `/api/v2/contact_fields` — lookup resolving custom contact field IDs and their dropdown choices (high)
- [ ] `/api/v2/canned_response_folders/{id}/responses` — the canned responses themselves; only their folders are synced today (high)
- [ ] `/api/v2/solutions/categories (+ /categories/{id}/folders, /folders/{id}/articles)` — knowledge base hierarchy and article stats (hits, thumbs up/down) for deflection analysis (high)
- [ ] `/api/v2/company_fields` — lookup resolving custom company field IDs and choices (medium)
- [ ] `/api/v2/custom_objects/schemas (+ /schemas/{id}/records)` — customer-defined objects linked to tickets; schemas act as the lookup for the records (medium)
- [ ] `/api/v2/customer-satisfaction/surveys/{survey_id}/responses` — new-style CSAT responses; only legacy satisfaction_ratings are synced (medium)
- [ ] `/api/v2/ticket-forms` — lookup resolving the form ID on tickets in multi-form portals (medium)
- [ ] `/api/v2/collaboration/threads (+ /collaboration/messages)` — internal discussion threads attached to tickets - collaboration effort per ticket (medium)
- [ ] `/api/v2/discussions/categories (+ /forums, /topics, /comments)` — community forum activity, another deflection surface (low)
- [ ] `/api/v2/tickets/{id}/watchers` — who is following each ticket - escalation/involvement signal (low)
- [ ] `/api/v2/channels/outbound-messages` — proactive outbound messages sent from the helpdesk (low)

Note: Ticket conversations and canned responses are per-parent sub-resources, so they need a fan-out over the tickets / canned_response_folders tables already synced. Search endpoints (/api/v2/search/\*), automations, email mailbox config and account settings excluded as plumbing.

## Freshsales — gaps

Today (9): `completed_tasks`, `contacts`, `deals`, `leads`, `open_tasks`, `past_appointments`, `sales_accounts`, `sales_activities`, `upcoming_appointments`

Diffed against: <https://developers.freshworks.com/crm/api/>

- [ ] `/api/selector/owners` — user lookup - resolves owner_id on contacts, deals, accounts, tasks and activities; there is no users table today (high)
- [ ] `/api/selector/deal_stages` — lookup resolving deal_stage_id, required for any pipeline or conversion analysis (high)
- [ ] `/api/selector/deal_pipelines` — lookup resolving deal_pipeline_id on deals (high)
- [ ] `/api/selector/lifecycle_stages` — lookup resolving lifecycle_stage_id on contacts and accounts (high)
- [ ] `/api/selector/lead_sources` — lookup resolving lead_source_id - the core attribution dimension (high)
- [ ] `/api/selector/sales_activity_types (+ /sales_activity_outcomes)` — lookups resolving type and outcome IDs on the sales_activities already synced (high)
- [ ] `/api/selector/contact_statuses` — lookup resolving contact_status_id (medium)
- [ ] `/api/selector/territories` — lookup resolving territory_id for regional breakdowns (medium)
- [ ] `/api/lists (+ /lists/{id} contacts)` — marketing lists and their contact membership (medium)
- [ ] `/api/cpq/products` — product catalog referenced by deals and quotes (medium)
- [ ] `/api/cpq/cpq_documents (+ /{id}/related_products)` — quotes/documents with their product line items - quoted vs won revenue (medium)
- [ ] `/api/contacts/{id}/activities.json` — per-contact activity timeline (notes, calls, emails) not reachable from any synced table (medium)

Note: The `/api/selector/\*` family is a set of ~18 small lookup collections (also deal_reasons, deal_types, industry_types, business_types, campaigns, currencies, designations, deal_payment_statuses) that resolve nearly every foreign key on the objects PostHog already syncs - cheap to add and the highest leverage here. `/api/settings/{module}/fields` additionally exposes custom-field metadata and dropdown choices. Notes have no list endpoint (create/read/update/delete only), so they are only reachable via the contact activities sub-resource.

## Freshservice — gaps

Today (17): `agent_groups`, `agent_roles`, `agents`, `asset_types`, `assets`, `changes`, `departments`, `locations`, `problems`, `products`, `purchase_orders`, `releases`, `requester_groups`, `requesters`, `software`, `tickets`, `vendors`

Diffed against: <https://api.freshservice.com/>

- [ ] `tickets/{id}/conversations` — the actual reply and note bodies on every ticket — required for any response-content or agent-activity analysis (high)
- [ ] `tickets/{id}/time_entries` — time tracked per ticket, the basis of effort and cost-per-ticket reporting (high)
- [ ] `contracts (+ contract_types lookup)` — asset/vendor contracts with cost and renewal dates; contract_types resolves the type ID carried on each contract (high)
- [ ] `applications/{id}/users and /installations (software users, software installations)` — membership tables joining the software we already sync to users and devices — license utilization is impossible without them (high)
- [ ] `assets/{id}/relationships (+ relationship_types lookup)` — the CMDB dependency graph plus the lookup that names each relationship type (high)
- [ ] `sla_policies` — lookup that resolves the SLA policy ID on tickets into targets and escalation rules (medium)
- [ ] `tickets/{id}/tasks (and problem/change/release tasks)` — sub-task breakdown and completion state under each ticket (medium)
- [ ] `approvals` — account-wide approval records with approver, state and timestamps — the service-request bottleneck metric (medium)
- [ ] `alerts (+ alert logs)` — alert-management records that precede incidents; logs give the state transition history (medium)
- [ ] `service_catalog/items (+ service_categories lookup)` — resolves what was actually requested in each service request, and the category lookup (medium)
- [ ] `tickets/{id}/csat_response` — satisfaction score per ticket — the headline support quality metric (medium)
- [ ] `solutions/articles (+ categories, folders)` — knowledge base content with view/hit counts for deflection analysis (low)

Note: Freshservice's single-page API reference exposes ~680 anchored operations. Static table list in the source; no dynamic discovery. Coverage is good on the top-level ITSM objects but misses every sub-resource hanging off tickets/problems/changes/releases.

## Frill — adequate

Today (8): `announcement_categories`, `announcements`, `comments`, `followers`, `ideas`, `statuses`, `topics`, `votes`

Diffed against: <https://developers.frill.co/llms.txt>

No material gaps found.

Note: Frill's llms.txt lists exactly nine reference pages: announcements, announcement-categories, ideas, comments, statuses, topics, followers, votes, plus a 'Notes' page sitting under a '--- Coming soon ---' divider. All eight shipped resources are synced; only the unreleased Notes resource is absent.

## Front — gaps

Today (9): `accounts`, `channels`, `contacts`, `conversations`, `events`, `inboxes`, `tags`, `teammates`, `teams`

Diffed against: <https://raw.githubusercontent.com/frontapp/front-api-specs/main/core-api/core-api.json>

- [ ] `conversations/{id}/messages` — the email/SMS message bodies themselves; conversations without messages is metadata only (high)
- [ ] `conversations/{id}/comments` — internal team discussion on each conversation, the collaboration signal (high)
- [ ] `company/statuses (ticket statuses)` — lookup that resolves the ticket status ID already carried on synced conversations (high)
- [ ] `conversations/{id}/followers` — membership table linking teammates to the conversations they watch (medium)
- [ ] `teammate_groups (+ /teammates, /teams, /inboxes members)` — org structure and membership joins for the teammates and teams already synced (medium)
- [ ] `contact_lists (+ contacts in list)` — customer segmentation lists and their membership rows (medium)
- [ ] `contact_groups (+ contacts in group)` — the other contact grouping dimension, needed to break conversations down by contact segment (medium)
- [ ] `custom_fields (accounts, contacts, conversations, inboxes, teammates, links)` — lookup describing the custom field definitions whose values ride on synced records (medium)
- [ ] `links (+ links/{id}/conversations)` — external resource links attached to conversations — the join to CRM/issue trackers (medium)
- [ ] `knowledge_bases/{id}/articles (+ categories)` — help center content for deflection and article-coverage analysis (medium)
- [ ] `shifts (+ shifts/{id}/teammates)` — coverage schedule and who was on it, to correlate response time with staffing (low)
- [ ] `contacts/{id}/notes` — free-text account context recorded against a contact (low)

Note: Diffed against Front's published OpenAPI 3.0 spec (128 GET operations). The top-level objects are all covered, but the sub-resources under /conversations — where the actual content lives — are entirely missing.

## Fulcrum — gaps

Today (13): `audio`, `changesets`, `choice_lists`, `classification_sets`, `forms`, `memberships`, `photos`, `projects`, `records`, `roles`, `signatures`, `videos`, `webhooks`

Diffed against: <https://docs.fulcrumapp.com/reference/records-intro>

- [ ] `records/history (records-get-all-history)` — full version history of every record — the only way to analyze edits, corrections and field-level change over time (high)
- [ ] `groups (+ group resources)` — lookup that resolves the group ID carried on the memberships and projects already synced (high)
- [ ] `audit_logs` — account-wide activity trail: who did what to which form, record or membership (medium)
- [ ] `forms/{id}/history` — form schema versions, needed to interpret older records collected under a prior form definition (medium)
- [ ] `sketches` — the one media type not synced alongside photos, audio, video and signatures — leaves media coverage inconsistent (low)
- [ ] `attachments` — arbitrary file attachments linked to records, with metadata for completeness checks (low)
- [ ] `layers` — reference data layers that records join against for spatial context (low)

Note: Fulcrum's REST reference nav lists 182 pages. PostHog covers nearly every top-level collection with a get-all; the misses are mostly history and grouping resources.

## FullStory — **thin**

Today (1): `users`

Diffed against: <https://developer.fullstory.com/server/sessions/introduction/>

- [ ] `v1 segments/{id}/export + operations (session and event export)` — the entire session and event stream — Fullstory's headline data and the reason to sync it at all; requires the async export job pattern (high)
- [ ] `v2 sessions/{uid} (list sessions per user)` — session replay URLs and session metadata joined to the users already synced; drivable by iterating the users table (high)
- [ ] `v1 segments (list segments)` — lookup naming each segment, and the handle needed to scope any export (high)
- [ ] `v2 sessions/{id}/events (get session events)` — per-session event detail for funnel and rage-click analysis (medium)
- [ ] `v2 datasets (list datasets)` — lookup describing the exportable datasets available to the account (medium)
- [ ] `v1 exports/get-user-events` — per-user event history, an alternative to the segment export for smaller pulls (medium)

Note: The source hard-codes ENDPOINTS = ("users",) in fullstory/fullstory.py with a comment that session/event data only exists behind Fullstory's async Data Export jobs — that is accurate for bulk pulls. Note the v2 /sessions list endpoint is per-user (requires uid, email or session_uid) and is not paginated, so it would have to be driven off the synced users table rather than listed directly. Bulk session and event data comes from the v1 segment-export / operations workflow, which is async but resumable.

## FusionAuth — gaps

Today (4): `AuditLogs`, `EventLogs`, `LoginRecords`, `Users`

Diffed against: <https://raw.githubusercontent.com/FusionAuth/fusionauth-openapi/main/openapi.yaml>

- [ ] `application (GET /api/application, POST /api/application/search)` — lookup that resolves the applicationId stamped on every login record, registration and audit entry (high)
- [ ] `tenant (POST /api/tenant/search)` — lookup resolving the tenantId on users and login records — the top-level isolation dimension (high)
- [ ] `group (POST /api/group/search)` — lookup naming the groups referenced by user memberships (high)
- [ ] `group/member (POST /api/group/member/search)` — the user-to-group membership table; group-level access analysis is impossible without it (high)
- [ ] `user/registration (GET /api/user/registration/{userId}/{applicationId})` — which users are registered to which applications, with roles and registration dates (medium)
- [ ] `user/consent (GET /api/user/consent, POST /api/consent/search)` — consent grants per user plus the consent definition lookup — compliance reporting (medium)
- [ ] `entity + entity/grant (POST /api/entity/search, /api/entity/grant/search)` — non-user entities and the grants linking them to users — the machine-to-machine authorization graph (medium)
- [ ] `user/action + user-action + user-action-reason` — moderation action history against users, plus the action and reason lookups that decode it (medium)
- [ ] `jwt/refresh (GET /api/jwt/refresh)` — active refresh tokens per user — session longevity and device analysis (medium)
- [ ] `report/daily-active-user and report/monthly-active-user` — FusionAuth's headline DAU/MAU metrics, precomputed by the vendor (medium)
- [ ] `identity-provider/link (GET /api/identity-provider/link)` — which users are linked to which social/SSO provider — signup source breakdown (medium)
- [ ] `user/comment (POST /api/user/comment/search)` — admin notes recorded against users during support or moderation (low)

Note: Diffed against FusionAuth's official OpenAPI 3.0.3 spec (v1.68.0, 176 paths). Many listable resources are POST /search rather than GET, so a path-only scan understates the API. Config-heavy resources (keys, lambdas, themes, email templates, connectors, IP ACLs, webhooks) are correctly left out.

## GainsightPx — gaps

Today (7): `accounts`, `articles`, `engagements`, `features`, `kc_bots`, `segments`, `users`

Diffed against: <https://jsapi.apiary.io/apis/gainsightpx.apib>

- [ ] `events/feature_match` — feature usage events — the headline Gainsight PX metric, and the join from the features table we already sync to actual usage (high)
- [ ] `events/pageView` — the core page-view event stream underpinning any adoption or navigation analysis (high)
- [ ] `events/session` — session-level events giving visit frequency, duration and stickiness (high)
- [ ] `events/engagementView` — who saw and interacted with each engagement — the only way to measure the engagements table's performance (high)
- [ ] `survey/responses` — NPS/CES/survey answers, a headline reporting object with no substitute (high)
- [ ] `events/custom` — customer-defined events captured by PX, typically the business-critical ones (high)
- [ ] `events/segment_match` — segment entry/exit events that resolve the segments table into per-user membership over time (medium)
- [ ] `events/identify` — identity resolution events tying anonymous activity to the synced users and accounts (medium)
- [ ] `events/formSubmit` — in-product form submissions, the conversion event for guides and surveys (medium)
- [ ] `events/email` — email engagement events (send/open/click) for engagements delivered by email (medium)
- [ ] `feature/adoption/{featureId}` — vendor-precomputed adoption statistics per feature — a breakdown dimension that is expensive to recompute (medium)
- [ ] `events/lead` — lead capture events from in-product forms, for acquisition attribution (low)

Note: Fetched the Swagger 2.0 spec behind the Apiary docs (api.aptrinsic.com). PostHog syncs the seven entity/config objects but none of the /v1/events/\* streams, which are the bulk of what Gainsight PX actually captures and where all the product-analytics value sits.

## Gerrit — gaps

Today (4): `accounts`, `changes`, `groups`, `projects`

Diffed against: <https://gerrit-review.googlesource.com/Documentation/rest-api-changes.html>

- [ ] `changes/{change-id}/comments` — inline review comments per change — the core code-review signal, not covered by the MESSAGES option (high)
- [ ] `groups/{group-id}/members` — join table resolving accounts to the groups we already sync (high)
- [ ] `changes/{change-id}/revisions/{revision-id}/files` — per-file insertions/deletions for code churn and review-size analysis (high)
- [ ] `projects/{project-name}/branches` — lookup resolving the branch string carried on every change (medium)
- [ ] `changes/{change-id}/reviewers` — explicit reviewer and CC list per change, including reviewers who never voted (medium)
- [ ] `projects/{project-name}/labels` — label definitions that resolve the label names appearing in change votes (medium)
- [ ] `projects/{project-name}/tags` — release tags per project for cut-to-ship analysis (medium)
- [ ] `projects/{project-name}/submit_requirements` — submit requirement definitions behind change submittability (low)
- [ ] `groups/{group-id}/groups` — included subgroups, needed to expand nested group membership (low)
- [ ] `groups/{group-id}/log.audit` — membership change history over time (low)

Note: Not dynamic — settings.py hardcodes 4 endpoints. The changes stream requests o=MESSAGES/DETAILED_LABELS/CURRENT_REVISION/DETAILED_ACCOUNTS, so review messages and label votes already ride inside the change row; inline comments and per-file stats do not. Also checked rest-api-projects.html, rest-api-accounts.html, rest-api-groups.html.

## Giphy — gaps

Today (6): `categories`, `gifs_search`, `gifs_trending`, `stickers_search`, `stickers_trending`, `trending_search_terms`

Diffed against: <https://developers.giphy.com/docs/api/endpoint/>

- [ ] `/v2/emoji` — full listable GIPHY emoji catalog — a stable, paginable table rather than a query-dependent result set (medium)
- [ ] `/v1/clips/trending` — GIPHY Clips (GIFs with sound) is a headline content type with no coverage at all (medium)
- [ ] `/v1/clips/search` — search side of the Clips corpus, mirroring the gifs/stickers search tables already synced (medium)
- [ ] `/v1/channels/search` — lookup resolving the channel/user object attached to every GIF and sticker row (medium)
- [ ] `/v1/tags/related/{term}` — related-term expansion for search-term analysis alongside trending_search_terms (low)
- [ ] `/v1/gifs/search/tags` — autocomplete tag suggestions per term (low)

Note: Read-only content-search API with an inherently small analytical surface; the APIs-guru OpenAPI copy is stale (missing categories, trending searches, channels, emoji) so the vendor endpoint reference is authoritative. Clips endpoints are access-gated by GIPHY approval.

## GitBook — gaps

Today (8): `change_requests`, `collections`, `comments`, `members`, `organizations`, `sites`, `spaces`, `teams`

Diffed against: <https://api.gitbook.com/openapi.json>

- [ ] `/spaces/{spaceId}/content/pages` — the page inventory per space — the primary documentation object, currently absent entirely (high)
- [ ] `/orgs/{organizationId}/sites/{siteId}/questions` — questions readers ask GitBook AI on published sites — the headline docs-effectiveness signal (high)
- [ ] `/orgs/{organizationId}/sites/{siteId}/answers` — the answers served for those questions, including whether the docs could answer (high)
- [ ] `/orgs/{organizationId}/teams/{teamId}/members` — join table resolving the members and teams we already sync (high)
- [ ] `/orgs/{organizationId}/sites/{siteId}/question-stats` — aggregated question volume and resolution rate per site (medium)
- [ ] `/orgs/{organizationId}/sites/{siteId}/findings` — detected content gaps per site, the actionable output of site scans (medium)
- [ ] `/orgs/{organizationId}/sites/{siteId}/insights/visitor-segments` — published-site visitor breakdown dimensions (medium)
- [ ] `/orgs/{organizationId}/sites/{siteId}/site-spaces` — lookup joining sites to the spaces they publish, both of which are already synced (medium)
- [ ] `/spaces/{spaceId}/change-requests/{changeRequestId}/reviews` — review state and reviewer per change request for docs review-cycle analysis (medium)
- [ ] `/spaces/{spaceId}/change-requests/{changeRequestId}/changes` — page-level changes inside a change request — the diff granularity of docs edits (medium)
- [ ] `/orgs/{organizationId}/sites/{siteId}/scans` — scan history behind findings, giving a time dimension to site quality (low)
- [ ] `/spaces/{spaceId}/content/files` — asset inventory per space (low)

Note: Source already does parent-child resolution (orgs -> spaces -> child resource), so nested paths are within reach of the existing transport.

## Gitea — gaps

Today (6): `commits`, `issues`, `labels`, `milestones`, `pull_requests`, `releases`

Diffed against: <https://demo.gitea.com/swagger.v1.json>

- [ ] `/repos/{owner}/{repo}/issues/comments` — repo-wide issue and PR comments in one listable call — the main discussion signal, entirely absent (high)
- [ ] `/repos/{owner}/{repo}/pulls/{index}/reviews` — PR review verdicts and reviewers, required for any review-throughput analysis (high)
- [ ] `/repos/{owner}/{repo}/actions/runs` — Gitea Actions CI runs — no CI data is synced at all today (high)
- [ ] `/repos/{owner}/{repo}/issues/{index}/timeline` — state and assignment transition history behind issue cycle time (high)
- [ ] `/repos/{owner}/{repo}/actions/jobs` — job-level CI granularity for duration and failure attribution (medium)
- [ ] `/repos/{owner}/{repo}/branches` — branch inventory with protection and last-commit metadata (medium)
- [ ] `/repos/{owner}/{repo}/tags` — git tags — releases are synced but the underlying tags are not (medium)
- [ ] `/repos/{owner}/{repo}/collaborators` — lookup resolving the user IDs appearing as authors, assignees, and reviewers (medium)
- [ ] `/repos/{owner}/{repo}/times` — tracked time entries per issue, a first-class analytical object in Gitea (medium)
- [ ] `/repos/{owner}/{repo}/pulls/{index}/files` — per-file diff stats for PR size and code churn (medium)
- [ ] `/repos/{owner}/{repo}/commits/{ref}/statuses` — commit status checks linking CI outcomes to commits (low)
- [ ] `/repos/{owner}/{repo}/issues/{index}/reactions` — reaction counts as an engagement dimension on issues (low)

Note: Source is single-repo scoped ({repository} = owner/repo) and already has webhook ingestion (webhook_template.py). Diffed against the live Gitea 1.24 swagger spec.

## Gitguardian — gaps

Today (6): `honeytokens`, `members`, `secret_incidents`, `secret_occurrences`, `sources`, `teams`

Diffed against: <https://api.gitguardian.com/v1/openapi.json>

- [ ] `/v1/secret_detectors` — lookup resolving the detector name/family stamped on every incident and occurrence we already sync (high)
- [ ] `/v1/incidents/secrets/{incident_id}/activity-logs` — incident state-transition history — remediation MTTR cannot be computed from current status alone (high)
- [ ] `/v1/honeytokens_events` — honeytoken trigger events across the org; honeytokens are synced but the events they exist to capture are not (high)
- [ ] `/v1/teams/{team_id}/team_memberships` — join table between the members and teams we already sync (high)
- [ ] `/v1/incidents/secrets/{incident_id}/notes` — analyst remediation notes attached to each incident (medium)
- [ ] `/v1/custom_tags` — lookup resolving the custom tag IDs applied to incidents (medium)
- [ ] `/v1/audit_logs` — org-wide audit trail of who changed what in GitGuardian (medium)
- [ ] `/v1/public-incidents/secrets` — publicly leaked secrets — a separate perimeter from internal incidents, with its own severity picture (medium)
- [ ] `/v1/teams/{team_id}/sources` — join table mapping the sources we sync to owning teams (medium)
- [ ] `/v1/incidents/secrets/{incident_id}/leaks` — where each secret surfaced publicly, the exposure dimension of an incident (medium)
- [ ] `/v1/public-perimeter/developers` — developers associated with public leaks, for per-developer exposure reporting (low)
- [ ] `/v1/honeytokens/{honeytoken_id}/activity-logs` — per-honeytoken activity timeline (low)

Note: Fetched the live 5 MB OpenAPI document from the vendor's own /v1/openapi.json.

## GitLab — **thin**

Today (10): `branches`, `commits`, `issues`, `labels`, `members`, `merge_requests`, `milestones`, `pipelines`, `releases`, `tags`

Diffed against: <https://docs.gitlab.com/api/api_resources/>

- [ ] `/projects/{id}/jobs` — CI job-level rows — pipelines alone cannot answer stage duration, runner cost, or failure attribution (high)
- [ ] `/projects/{id}/issues/{iid}/notes and /projects/{id}/merge_requests/{iid}/notes` — issue and merge-request comments, the main collaboration signal (high)
- [ ] `/projects/{id}/issues/{iid}/resource_state_events and /merge_requests/{iid}/resource_state_events` — open/close/reopen transition history — cycle time cannot be computed from current state alone (high)
- [ ] `/projects/{id}/dora/metrics` — GitLab's headline DevOps metric (deployment frequency, lead time, change failure rate, MTTR) (high)
- [ ] `/projects/{id}/deployments` — deployment records joining pipelines to environments, the basis of release analytics (high)
- [ ] `/projects/{id}/issues/{iid}/resource_label_events` — label add/remove history, the standard way teams track workflow stage over time (medium)
- [ ] `/projects/{id}/environments` — lookup resolving the environment IDs carried on deployments (medium)
- [ ] `/projects/{id}/merge_requests/{iid}/approvals` — who approved each MR and when — core review-governance reporting (medium)
- [ ] `/projects/{id}/events` — project activity stream covering pushes, comments, and membership changes in one table (medium)
- [ ] `/projects/{id}/issues/{iid}/resource_milestone_events` — milestone reassignment history for scope-change analysis (medium)
- [ ] `/projects/{id}/iterations` — iteration (sprint) definitions that resolve iteration IDs on issues (low)
- [ ] `/projects/{id}/vulnerabilities and /projects/{id}/vulnerability_findings` — security findings per project for posture trend reporting (low)

Note: Source is single-project scoped (every path templates {project} into /projects/{project}/...), so the missing items below are all project-scoped and reachable with the existing transport. GitLab exposes ~230 documented REST resources; 10 tables covers the obvious nouns but omits CI job granularity, comments, and all state-transition history. Individual paths confirmed against docs.gitlab.com/api/{jobs,notes,resource_state_events,dora/metrics,deployments,environments,events,merge_request_approvals}.

## Gladly — gaps

Today (4): `agents`, `conversation_items`, `customers`, `topics`

Diffed against: <https://developer.gladly.com/rest/>

- [ ] `/api/v1/customers/{customerId}/conversations` — conversation-header rows (status, channel, timestamps); only item-level rows exist today, so per-conversation handle time and volume are unanswerable (high)
- [ ] `/api/v1/teams` — lookup resolving the team IDs carried on agents and conversations (high)
- [ ] `/api/v1/inboxes` — lookup resolving the inbox IDs carried on conversation items (high)
- [ ] `/api/v1/reports/work-session-events` — agent work-session and status history — the vendor's own agent-productivity metric (high)
- [ ] `/api/v1/events` — org-wide event stream, the closest thing Gladly has to an activity log (medium)
- [ ] `/api/v1/customers/{customerId}/tasks` — customer tasks with assignment and completion state, a distinct work object from conversations (medium)
- [ ] `/api/v1/answers` — knowledge-base answer catalog, needed to analyze self-service deflection (medium)
- [ ] `/api/v1/conversation-items/{itemId}/voice-transcript` — voice transcripts for call-content analysis; the export ships item metadata only (medium)
- [ ] `/api/v1/audiences` — lookup resolving audience IDs on answers (low)
- [ ] `/api/v1/tasks/{taskId}/comments` — task discussion thread (low)

Note: Important: PostHog does not use Gladly's REST list endpoints — it ingests the file-based Export API (scheduled jobs producing JSONL, 14-day retention), and the spec confirms the export ships exactly four files: agents.jsonl, conversation_items.jsonl, customers.jsonl, topics.jsonl. So export coverage is complete; every gap below requires adding REST calls alongside the export path, and several Gladly REST resources are per-ID only with no list-all endpoint. Endpoint list extracted from the embedded Redoc spec (\_\_redoc_state) on the docs page, not from the summarized page text.

## Glassfrog — gaps

Today (8): `assignments`, `checklist_items`, `circles`, `custom_fields`, `metrics`, `people`, `projects`, `roles`

Diffed against: <https://app.glassfrog.com/api/v3/docs/spec.yaml>

- [ ] `/tensions` — tensions are the core Holacracy input object and the driver of every governance and tactical outcome (high)
- [ ] `/actions` — next-actions are the operational work items sitting alongside the projects already synced (high)
- [ ] `/proposals` — governance proposals with their responses — the transition record for how roles and circles changed (high)
- [ ] `/governance_meetings` — governance meeting records that timestamp and group structural changes (medium)
- [ ] `/tactical_meetings` — tactical meeting cadence and attendance, the operational counterpart to governance meetings (medium)
- [ ] `/agenda_items` — agenda items per meeting — the line items making meeting throughput measurable (medium)
- [ ] `/domains` — lookup resolving the domains held by the roles and circles already synced (medium)
- [ ] `/policies` — policies attached to circles and roles, part of the governance record (medium)
- [ ] `/organizations` — top-level org lookup that scopes every other table (medium)
- [ ] `/triggers` — role triggers (when-then rules) attached to roles and people (low)

Note: The docs page at /api/v3/docs is a Swagger UI shell; the real spec is at /api/v3/docs/spec.yaml, which is what was diffed. GlassFrog exposes 12 listable top-level collections and PostHog covers 8 nouns but none of the governance-process objects.

## GNews — adequate

Today (2): `articles`, `top_headlines`

Diffed against: <https://gnews.io/docs/v4>

No material gaps found.

Note: The v4 documentation states outright that GNews has "Two Powerful Endpoints" — Search and Top Headlines. Both are synced (articles, top_headlines). There is nothing else in the API.

## GoCardless — gaps

Today (7): `customers`, `events`, `mandates`, `payments`, `payouts`, `refunds`, `subscriptions`

Diffed against: <https://developer.gocardless.com/api-reference/>

- [ ] `payout_items (/payouts/{id}/items)` — line items that reconcile each payout to its underlying payments, refunds and fees - the core payout reconciliation join (high)
- [ ] `customer_bank_accounts` — lookup resolving the customer_bank_account IDs carried on every mandate and payment we already sync (high)
- [ ] `creditors` — lookup resolving the creditor ID on payments, payouts and mandates (high)
- [ ] `balances` — current available/pending funds per creditor - the headline treasury metric (medium)
- [ ] `instalment_schedules` — payment plans that group the individual payments we sync (medium)
- [ ] `billing_requests` — the modern checkout/mandate-setup funnel object, needed to measure setup conversion (medium)
- [ ] `payment_account_transactions` — transaction ledger for embedded payment accounts (medium)
- [ ] `outbound_payments` — money-out transactions, the counterpart to the payments table (medium)
- [ ] `creditor_bank_accounts` — lookup resolving the destination bank account on payouts (medium)
- [ ] `tax_rates` — lookup resolving the tax rate ID on payments and subscriptions (low)
- [ ] `scheme_identifiers` — lookup resolving the scheme identifier referenced by mandates (low)
- [ ] `customer_notifications` — notification delivery events per customer/mandate (low)

## Goldcast — gaps

Today (7): `agenda_items`, `discussion_groups`, `event_members`, `events`, `organizations`, `tracks`, `webinars`

Diffed against: <https://apidocs.goldcast.io/>

- [ ] `event/broadcasts` — the live session objects under an event - sync-time joins for attendance and agenda analysis (high)
- [ ] `event/broadcasts/{id}/polls` — in-session poll results, the main engagement measurement in a webinar tool (high)
- [ ] `event/ticket-type` — lookup resolving the ticket type carried on event_members registrations (high)
- [ ] `core/tag-library` — lookup resolving tag IDs referenced across events and members (medium)
- [ ] `event/booths` — sponsor/expo booths, the unit sponsorship ROI is measured on (medium)
- [ ] `event/{event_id}/public/v1/speakers` — speaker roster per event, a dimension for session performance breakdowns (medium)
- [ ] `event/{id}/get_recordings` — recording assets per event, needed to join on-demand viewing (medium)
- [ ] `event/resources` — downloadable content attached to an event (low)
- [ ] `event/sponsor-resources/{id}` — sponsor-supplied content assets (low)
- [ ] `event/{event_id}/public/v1/overview` — event-level summary fields not present on the base event object (low)

Note: The swagger-ui URL recorded in the source (https://customapi.goldcast.io/swagger-ui/) now 404s; the live spec is served inline as Redoc state at https://apidocs.goldcast.io/ (spec url https://customapi.goldcast.io/schema, which also 404s directly). 39 paths total, so the API is genuinely small.

## Gong — gaps

Today (5): `calls`, `calls_extensive`, `scorecards`, `users`, `workspaces`

Diffed against: <https://help.gong.io/llms.txt>

- [ ] `calls/transcript (POST /v2/calls/transcript)` — the actual conversation text - Gong's headline data and the thing most warehouse users want (high)
- [ ] `stats/activity/scorecards` — answered scorecard responses; we currently only sync scorecard definitions, not the reviews (high)
- [ ] `settings/trackers` — lookup resolving the tracker IDs that appear on calls_extensive (high)
- [ ] `stats/interaction` — talk ratio, patience, longest monologue - Gong's signature conversation metrics per user (high)
- [ ] `stats/activity/day-by-day` — daily per-rep activity fact table for coaching and adoption reporting (high)
- [ ] `call-outcomes` — lookup resolving call outcome values used to segment calls (medium)
- [ ] `stats/activity/aggregate-by-period` — pre-aggregated activity by period, cheaper than deriving from raw calls (medium)
- [ ] `coaching` — coaching metrics per manager/rep (medium)
- [ ] `logs` — audit log of access and data events, used for security and usage reporting (medium)
- [ ] `library/folders + library/folder-content` — curated call collections and their membership (medium)
- [ ] `flows + flows/prospects` — Gong Engage sequences and prospect assignments for outbound analysis (medium)
- [ ] `users/{id}/settings-history` — state-transition history of user recording settings, explains gaps in call coverage (low)

Note: Gong's OpenAPI at https://api.gong.io/v2/api-docs is auth-gated (401), and the settings/api/documentation UI requires login. The resource list above was read from Gong's own docs index at help.gong.io/llms.txt, which enumerates every API-reference page with its /v2 path.

## GooglePageSpeedInsights — adequate

Today (2): `pagespeed_desktop`, `pagespeed_mobile`

Diffed against: <https://pagespeedonline.googleapis.com/$discovery/rest?version=v5>

No material gaps found.

Note: The v5 discovery document exposes exactly one method, pagespeedapi.runPagespeed. PostHog's two tables are the desktop/mobile strategy variants of that single call, so coverage is complete at the endpoint level. Only remaining lever is the `category` request param (accessibility, seo, best-practices, pwa) - a parameter, not a missing endpoint.

## GoogleWebfonts — adequate

Today (1): `webfonts`

Diffed against: <https://webfonts.googleapis.com/$discovery/rest?version=v1>

No material gaps found.

Note: The v1 discovery document exposes exactly one method, webfonts.list. The single `webfonts` table is the whole API.

## Gorgias — gaps

Today (9): `customers`, `macros`, `messages`, `satisfaction_surveys`, `tags`, `teams`, `tickets`, `users`, `views`

Diffed against: <https://developers.gorgias.com/llms.txt>

- [ ] `events (/api/events)` — the account-wide event stream, including ticket state transitions and assignment changes - the only way to do time-in-status or SLA analysis (high)
- [ ] `ticket_tags (/api/tickets/{id}/tags)` — the ticket-to-tag join; we sync tags and tickets but not the mapping between them (high)
- [ ] `voice_calls` — phone channel fact table, entirely absent today (high)
- [ ] `custom_fields` — lookup resolving the custom field IDs used on tickets and customers (high)
- [ ] `ticket_field_values (/api/tickets/{id}/custom-fields)` — per-ticket custom field values, including system fields like AI Intent and AI Agent Outcome (high)
- [ ] `customer_field_values (/api/customers/{id}/custom-fields)` — per-customer custom field values (medium)
- [ ] `voice_call_events` — per-call state transitions (ringing, answered, transferred) for phone queue analysis (medium)
- [ ] `voice_call_recordings` — recording metadata joined to voice calls (medium)
- [ ] `statistics (/api/statistics/{slug} and metric cards)` — Gorgias' own precomputed support metrics, useful as a benchmark against derived numbers (medium)
- [ ] `view_items (/api/views/{id}/items)` — the ticket membership of each saved view; we sync views but not their contents (low)

## Grafana — gaps

Today (8): `alert_rules`, `annotations`, `dashboards`, `datasources`, `folders`, `service_accounts`, `teams`, `users`

Diffed against: <https://raw.githubusercontent.com/grafana/grafana/main/public/openapi3.json>

- [ ] `teams/{team_id}/members` — team membership join - we sync teams and users but nothing connecting them (high)
- [ ] `org/users (and orgs/{org_id}/users)` — org membership plus role, the other half of the identity model we already sync (high)
- [ ] `orgs` — lookup resolving the org_id carried on dashboards, users, teams and datasources (high)
- [ ] `dashboards/uid/{uid}/versions` — dashboard change history - who changed what and when, the main governance question (medium)
- [ ] `library-elements` — reusable panels referenced by dashboards; needed to resolve panel definitions that are not inline (medium)
- [ ] `query-history` — records of explored queries, the usage-analytics table for Explore adoption (medium)
- [ ] `access-control/roles and access-control/{resource}/{resourceID}` — RBAC role definitions and resource permissions, resolving who can see which dashboards/folders (medium)
- [ ] `folders/{folder_uid}/permissions and dashboards/uid/{uid}/permissions` — per-object permission grants for access auditing (low)
- [ ] `annotations/tags` — lookup of annotation tags for grouping the annotations we already sync (low)
- [ ] `playlists and playlists/{uid}/items` — playlist definitions and the dashboards inside them (low)
- [ ] `datasources/correlations` — correlation definitions linking datasources, useful for lineage (low)
- [ ] `admin/stats` — instance-level counts (dashboards, users, orgs, alerts) as a single summary row (low)

Note: The published openapi3.json / api-merged.json cover 207 paths but only the \*provisioning\* alerting API (/api/v1/provisioning/alert-rules), which is what the existing alert_rules table maps to. Grafana's alert instance and state-history endpoints (/api/prometheus/grafana/api/v1/rules, /api/v1/rules/history) are documented outside this spec, so I did not list them as verified gaps - worth a separate check, since alert firing history is the highest-value alerting table.

## Granola — adequate

Today (2): `folders`, `notes`

Diffed against: <https://docs.granola.ai/api-reference/openapi.json>

No material gaps found.

Note: The public OpenAPI declares only 5 paths: /v1/folders, /v1/notes, /v1/notes/{note_id}, and two webhook-endpoint management paths. PostHog's folders + notes tables cover every non-config resource in the API.

## Greenhouse — gaps

Today (13): `applications`, `candidates`, `close_reasons`, `departments`, `job_posts`, `jobs`, `offers`, `offices`, `rejection_reasons`, `scheduled_interviews`, `scorecards`, `sources`, `users`

Diffed against: <https://developers.greenhouse.io/harvest.html>

- [ ] `job_stages (GET /v1/job_stages, /v1/jobs/{id}/stages)` — lookup that resolves the current_stage / stage IDs already carried on synced applications and scorecards (high)
- [ ] `user_roles (GET /v1/user_roles)` — lookup resolving the role on the users table we already sync (high)
- [ ] `job_openings (GET /v1/jobs/{id}/openings)` — per-opening headcount, open/closed dates and close reason - required for time-to-fill and openings-filled reporting (high)
- [ ] `custom_fields + custom_field_options (GET /v1/custom_fields, /v1/custom_fields/{id}/custom_field_options)` — lookup that decodes the custom-field IDs embedded in synced jobs, candidates and applications (high)
- [ ] `activity_feed (GET /v1/candidates/{id}/activity_feed)` — candidate-level event/state history - the only source of note and email activity timestamps (medium)
- [ ] `demographic_answers (GET /v1/demographic/answers, /v1/applications/{id}/demographic/answers)` — DEI breakdown dimension joined to applications (medium)
- [ ] `demographic_questions + question_sets + answer_options (GET /v1/demographic/questions, /question_sets, /answer_options)` — lookup tables that label the demographic answer IDs (medium)
- [ ] `eeoc (GET /v1/eeoc, /v1/applications/{id}/eeoc)` — compliance reporting dimension per application (medium)
- [ ] `candidate_tags (GET /v1/tags/candidate, /v1/candidates/{id}/tags)` — segmentation dimension and lookup for tag IDs on candidates (medium)
- [ ] `prospect_pools (GET /v1/prospect_pools)` — lookup resolving prospect_pool_id / stage on prospect candidates (low)
- [ ] `approvals (GET /v1/jobs/{id}/approval_flows, /v1/users/{id}/pending_approvals)` — job approval state and cycle-time analysis (low)
- [ ] `degrees / disciplines / schools (GET /v1/degrees, /v1/disciplines, /v1/schools)` — lookup tables for the education records on candidates (low)

Note: Harvest API only; the docs page is a single static HTML reference so the full GET list is reliable. Sub-resource-only endpoints (activity_feed, openings, per-application eeoc/demographics) require iterating parent IDs we already sync.

## Gridly — gaps

Today (2): `columns`, `records`

Diffed against: <https://www.gridly.com/docs/api/>

- [ ] `views (GET /v1/views?gridId=)` — lookup for the view the synced records and columns belong to; also the only way to discover other views (high)
- [ ] `grids (GET /v1/grids?dbId=)` — lookup resolving the grid that owns each view/record set (high)
- [ ] `databases (GET /v1/databases?projectId=)` — lookup completing the project > database > grid > view hierarchy around synced records (high)
- [ ] `projects (GET /v1/projects)` — top-level lookup for project names/IDs referenced by databases (high)
- [ ] `record histories (GET /v1/views/{viewId}/records/{recordId}/histories)` — per-cell change history - who changed which localization value and when (medium)
- [ ] `dependencies (GET /v1/views/{viewId}/dependencies)` — source-to-target column mapping that explains translation status columns (medium)
- [ ] `branches (GET /v1/branches?gridId=)` — branch metadata needed to interpret records synced from a branched grid (medium)
- [ ] `automation executions (GET /v1/automations/{id}/executions)` — run history with status and timing - the analytical table for automation reliability (medium)
- [ ] `automations (GET /v1/automations)` — lookup naming the automations whose executions you would analyze (medium)
- [ ] `glossaries (GET /v1/glossaries)` — terminology lookup joined to localization records (low)
- [ ] `translation memories (GET /v1/transmems)` — TM inventory for leverage/reuse reporting (low)

Note: The connector is scoped to a single configured view (view_id is a required credential field), so records/columns are per-view content rather than a thin catalog. Columns are not a separate API call - they are read out of GET /v1/views/{viewId}. CDN publish/unpublish, tasks and shareable links were excluded as plumbing.

## Groq — gaps

Today (3): `batches`, `files`, `models`

Diffed against: <https://console.groq.com/docs/api-reference>

- [ ] `fine_tunings (GET /v1/fine_tunings, GET /v1/fine_tunings/{id})` — the only remaining listable object type - fine-tune jobs with status and base model, joinable to the models table already synced (medium)

Note: api.groq.com/openapi.json and console.groq.com/openapi.json both 404; enumerated endpoints from the rendered API reference HTML (all /openai/v1/\* and /v1/\* paths plus the operation headings). Everything else in the API is inference traffic (chat/completions, responses, embeddings, audio, reranking) or per-object content downloads, which are not warehouse tables. Coverage of batches/files/models is complete including list, retrieve and status fields.

## Guardian — adequate

Today (4): `content`, `editions`, `sections`, `tags`

Diffed against: <https://open-platform.theguardian.com/documentation/md/index.md>

No material gaps found.

Note: The Content API documents exactly five endpoints: content (/search), tags, sections, editions and single item (/{item-id}). PostHog syncs the four list endpoints; single item is an ID lookup into content, not a separate collection. Depth options (show-fields, show-tags, show-blocks) are query parameters on /search rather than distinct resources.

## Guru — gaps

Today (4): `cards`, `collections`, `groups`, `members`

Diffed against: <https://developer.getguru.com/reference/authentication>

- [ ] `team analytics (GET /v1/teams/{id}/analytics)` — the vendor's headline usage stream - card views, searches, copies per user; the main reason to warehouse Guru data (high)
- [ ] `group members (GET /v1/groups/{id}/members)` — membership table joining the groups and members we already sync (high)
- [ ] `tag categories and tags (GET /v1/teams/{id}/tagcategories, /tagcategories/tags)` — lookup resolving the tag IDs carried on synced cards (high)
- [ ] `folders (GET /v1/folders, GET /v1/folders/{id}/items)` — the board/folder hierarchy that organizes cards - lookup plus card-to-folder membership (high)
- [ ] `card comments (GET /v1/cards/{id}/comments)` — engagement and feedback events attached to synced cards (medium)
- [ ] `card verifiers (GET /v1/cards/verifiers, /v1/cards/{id}/verifiers)` — verification ownership per card - drives knowledge-freshness reporting (medium)
- [ ] `team stats (GET /v1/teams/{id}/stats)` — rolled-up workspace counters for trend dashboards (medium)
- [ ] `knowledge alerts (GET /v1/alerts/delegated, /v1/alerts/{id}/stats/summary, /stats/users)` — alert delivery and per-user read state - announcement reach analysis (medium)
- [ ] `templates (GET /v1/templates)` — lookup for the template a card was created from (medium)
- [ ] `collection access (GET /v1/collections/{id}/access, GET /v1/groups/{id}/collections)` — group-to-collection permission mapping, a membership-style join across two synced tables (low)
- [ ] `people (GET /v1/people/{id}, /v1/people/{id}/directreports)` — org chart attributes enriching members (low)
- [ ] `assistants (GET /v1/assistants)` — AI assistant inventory for answer-quality analysis (low)

Note: developer.getguru.com is a ReadMe site with no downloadable OpenAPI (openapi.json and sitemap.xml both 404, and the deep-link slug in the payload's doc list returns 404). Endpoint list was extracted from the /reference index page's operation slugs (e.g. getv1groupsgetgroupmembers, getv1teamsanalyticsgetanalytics), which are generated one-per-operation, so the inventory is complete even though field-level shapes were not read.

## Harvey — gaps

Today (5): `audit_logs`, `client_matters`, `query_history`, `usage_history`, `vault_projects`

Diffed against: <https://developers.harvey.ai/vault_api.json>

- [ ] `vault project files (GET /api/v1/vault/projects/{project_id}/files)` — the documents inside each synced vault project - per-file processing status, size and timestamps (high)
- [ ] `vault project users (GET /api/v1/vault/projects/{project_id}/users)` — membership table with access level per user, joining vault_projects to workspace users (high)
- [ ] `review table rows (GET /api/v1/vault/get_row/{review_table_id}/{file_id})` — the extracted answer grid - the actual analytical output of a Vault review (medium)
- [ ] `review table metadata (GET /api/v1/vault/review_table/{review_table_id})` — lookup naming each review table and listing the file IDs it covers (medium)
- [ ] `vault project metadata (GET /api/v1/vault/get_metadata/{project_id})` — storage limits and file counts not present on the projects list response (low)
- [ ] `recycle bin vaults (GET /api/v1/vault/workspace/recycle_bin)` — deleted-project retention view for lifecycle reporting (low)

Note: Harvey publishes six OpenAPI specs (listed in https://developers.harvey.ai/llms.txt); vault_api.json was fetched and diffed. The connector already uses the enriched v2 history endpoints (/api/v2/history/usage and /api/v2/history/query), so there is no v1-vs-v2 gap. Audit log and client matter coverage is complete - the remaining endpoints on those specs are cursor-seek helpers (earliest/latest/search) the connector already calls internally, plus write operations. Completion endpoints are inference, not warehouse tables.

## Hatchet — gaps

Today (4): `event_keys`, `events`, `tasks`, `workflow_runs`

Diffed against: <https://raw.githubusercontent.com/hatchet-dev/hatchet/main/api-contracts/openapi/openapi.yaml>

- [ ] `workflows (GET /api/v1/tenants/{tenant}/workflows, GET /api/v1/workflows/{workflow}/versions)` — lookup resolving the workflow ID and version carried on every synced workflow run and task (high)
- [ ] `task events (GET /api/v1/stable/tasks/{task}/task-events, GET /api/v1/stable/workflow-runs/{id}/task-events)` — state-transition history (queued, started, retried, failed) behind each task's final status (high)
- [ ] `workers (GET /api/v1/tenants/{tenant}/worker, GET /api/v1/workers/{worker})` — lookup identifying which worker executed a synced task, plus worker availability (high)
- [ ] `task metrics (GET /api/v1/stable/tenants/{tenant}/task-metrics, /task-point-metrics, /task-stats)` — the vendor's headline throughput and status-count series for queue health dashboards (medium)
- [ ] `queue metrics (GET /api/v1/tenants/{tenant}/queue-metrics, /step-run-queue-metrics)` — backlog depth per queue - the standard capacity-planning metric (medium)
- [ ] `scheduled runs (GET /api/v1/tenants/{tenant}/workflows/scheduled)` — upcoming and past scheduled triggers, joinable to workflow_runs (medium)
- [ ] `crons (GET /api/v1/tenants/{tenant}/workflows/crons)` — cron definitions that explain the trigger source of recurring runs (medium)
- [ ] `task timings (GET /api/v1/stable/workflow-runs/{id}/task-timings)` — per-task duration breakdown within a run - latency attribution (medium)
- [ ] `tenant members (GET /api/v1/tenants/{tenant}/members)` — membership table for the tenant whose runs are synced (medium)
- [ ] `logs (GET /api/v1/stable/tenants/{tenant}/logs, /tasks/{task}/logs)` — task log lines for failure triage alongside run rows (medium)
- [ ] `workflow run metrics (GET /api/v1/tenants/{tenant}/workflows/runs/metrics, GET /api/v1/workflows/{workflow}/metrics)` — success/failure counts per workflow without re-aggregating raw runs (low)
- [ ] `rate limits (GET /api/v1/tenants/{tenant}/rate-limits)` — current vs limit consumption per key - explains queued-but-not-running tasks (low)

Note: The connector targets the stable v1 API (/api/v1/stable/tenants/{tenant}/...), but several still-current resources (workflows, workers, crons, scheduled, members, queue-metrics) live only under the older /api/v1/tenants/{tenant}/... prefix in the same spec. Webhooks, API tokens, feature flags, SNS/Slack integrations and alerting email groups were excluded as configuration.

## Healthchecks.io — adequate

Diffed against: <https://healthchecks.io/docs/api/>

No material gaps found.

Note: The Management API v3 exposes exactly: list/get checks, list pings, get ping body, list flips, list channels, list badges and a status endpoint. PostHog syncs checks, pings, flips and channels - all four analytical collections. Badges returns per-tag SVG/JSON badge URLs (presentation plumbing) and /status is a service health probe, neither of which is a warehouse table. Remaining endpoints are writes (create/update/delete/pause/resume).

## Height — could not verify

Today (3): `field_templates`, `lists`, `users`

Diffed against: <https://height.notion.site/API-documentation-643aea5bf01742de9232ed5b8b23a91b>

No reachable API reference found during the sweep. Needs a manual pass.

Note: Could not reach any vendor-hosted doc this run: the Notion doc URL in the payload returns Cloudflare 403 to curl and an empty page to WebFetch, the Notion private API (loadPageChunk/getPublicPageData) reports publicAccessRole=none, and height.app / api.height.app / docs.height.app do not resolve at all from this host (curl exit 0 bytes), suggesting the product may be gone. Two non-vendor sources agree and both point at a large gap: Airbyte's Height connector doc (raw.githubusercontent.com/airbytehq/airbyte/master/docs/integrations/sources/height.md) lists streams workspace, lists, tasks, activities, field_templates, users, groups, search; and a third-party Redoc mirror (https://height-api.xyz/redocusaurus/default.yaml) lists /lists, /tasks, /tasks/move, /activities, /fieldTemplates, /fieldTemplates/:id/options, /taskForms/:id/answers, /users, /groups, /securityLogEvents, /workspace. PostHog exposes only field_templates, lists, users (products/warehouse_sources/backend/temporal/data_imports/sources/height/settings.py, static ENDPOINTS, no dynamic discovery) — so /tasks (the core object) and /activities (task events/messages/status changes) look like high-priority gaps, plus /groups and /fieldTemplates/:id/options as lookup tables. Not reported as gaps because the vendor spec itself could not be read.

## Helicone — gaps

Today (4): `prompts`, `requests`, `sessions`, `users`

Diffed against: <https://docs.helicone.ai/llms.txt>

- [ ] `POST /v1/evals/query` — evaluation results per request — the core quality metric Helicone users chart (high)
- [ ] `GET /v1/evals/scores` — lookup of the eval score definitions that eval results reference (high)
- [ ] `POST /v1/property/query` — custom properties attached to requests; the dimension almost every Helicone breakdown is sliced by (high)
- [ ] `POST /v1/user/metrics/query` — per-user aggregated cost/token/request metrics, complements the raw users table we sync (medium)
- [ ] `POST /v1/session/metrics/query` — per-session cost and latency rollups for the sessions we already sync (medium)
- [ ] `GET /v1/public/model-registry/models` — lookup table resolving model ids on requests to provider, context window and pricing (medium)
- [ ] `POST /v1/dashboard/scores/query` — dashboard scoring metrics over time (medium)
- [ ] `GET /v1/request/inputs` — prompt-template variable values per request — joins requests to the prompts we already sync (medium)
- [ ] `POST /v1/evals/score-distributions/query` — score distribution breakdowns for eval reporting (low)
- [ ] `GET /v1/prompt-2025/tags` — prompt tag lookup for grouping the prompts table (low)
- [ ] `GET /v1/prompt-2025/environments` — environment lookup so prompt versions can be attributed to prod/staging (low)

Note: Helicone's API is POST-query shaped rather than REST-collection shaped, so endpoints are named by their query path. Webhooks and the AI-gateway proxy endpoints (chat completions, responses, models) were excluded as plumbing.

## Hellobaton — gaps

Today (11): `activity`, `companies`, `milestones`, `phases`, `project_attachments`, `projects`, `task_attachments`, `tasks`, `templates`, `time_entries`, `users`

Diffed against: <https://app.hellobaton.com/api/swagger.json>

- [ ] `project_users` — project membership join table — who is on which project, missing entirely today (high)
- [ ] `custom_field_values` — the actual custom field data on projects and tasks; without it custom fields are invisible (high)
- [ ] `custom_fields` — lookup table naming and typing the custom field ids carried by custom_field_values (high)
- [ ] `project_phases` — per-project phase instances with dates — the state/transition history behind project progress (high)
- [ ] `comments` — collaboration events on projects and tasks, the main activity signal alongside activity (high)
- [ ] `custom_field_options` — lookup resolving picklist option ids stored in custom_field_values (medium)
- [ ] `departments` — lookup table resolving the department ids on users and projects (medium)
- [ ] `task_deliverables` — deliverable line items hanging off the tasks we already sync (medium)
- [ ] `milestone_feedback` — customer feedback tied to the milestones we already sync (medium)
- [ ] `external_tasks` — tasks mirrored from integrated systems, needed for a complete task picture (medium)
- [ ] `time_entry_aggregates` — pre-rolled time totals for utilization reporting without re-aggregating time_entries (low)
- [ ] `template_aggregates` — rollups over the templates table for template performance analysis (low)

Note: The API is read-only (GET only) and drf-yasg generated, so the swagger.json is a complete and authoritative resource list. /auth_token, download sub-resources and user-capacity-exceptions were excluded as plumbing/niche.

## Heroku — gaps

Today (11): `addons`, `apps`, `builds`, `collaborators`, `domains`, `dynos`, `formation`, `invoices`, `pipelines`, `releases`, `teams`

Diffed against: <https://api.heroku.com/schema>

- [ ] `team-member` — team membership and role — who has access to which team, no membership table today (high)
- [ ] `add-on-attachment` — lookup resolving which app each add-on is attached to; we sync add-ons but not the attachment join (high)
- [ ] `pipeline-coupling` — lookup joining apps to the pipelines we already sync, including the stage (review/staging/production) (high)
- [ ] `add-on-service` — lookup table naming the add-on service behind every add-on row we sync (high)
- [ ] `plan` — lookup giving the price and tier of each add-on plan id carried on add-ons — required for any cost analysis (high)
- [ ] `team-monthly-usage` — Heroku's headline spend/usage metric per team per month (dyno hours, add-on cost, data usage) (high)
- [ ] `team-daily-usage` — daily granularity of the same usage metric for trend analysis (medium)
- [ ] `team-app` — apps owned by each team, the org-level view the /apps personal list misses (medium)
- [ ] `team-invoice` — team-level invoices; we only sync personal /account/invoices today (medium)
- [ ] `pipeline-promotion / pipeline-promotion-target` — promotion events between pipeline stages — the deployment transition history (medium)
- [ ] `audit-trail-event` — enterprise audit log of who changed what, the main event stream in the API (medium)
- [ ] `dyno-size` — lookup resolving dyno size ids on dynos/formation to cpu, memory and cost per hour (medium)

Note: The hyper-schema at api.heroku.com/schema is the machine-readable source of truth (100 definitions). Config/plumbing resources (config-var, log-drain, telemetry-drain, oauth-\*, key, sni-endpoint, \*-webhook\*, \*-feature) were excluded. Note several high-value ones (team-monthly-usage, audit-trail-event, enterprise-account-\*) are Heroku Enterprise only.

## Hetzner — gaps

Today (17): `actions`, `certificates`, `datacenters`, `firewalls`, `floating_ips`, `images`, `isos`, `load_balancer_types`, `load_balancers`, `locations`, `networks`, `placement_groups`, `primary_ips`, `server_types`, `servers`, `ssh_keys`, `volumes`

Diffed against: <https://docs.hetzner.cloud/cloud.spec.json>

- [ ] `GET /pricing` — lookup table of hourly/monthly prices per server type, volume, load balancer and location — the only way to cost the servers we already sync (high)
- [ ] `GET /servers/{id}/metrics` — cpu, disk and network time series per server, the headline analytical data in the API (high)
- [ ] `GET /zones` — DNS zones, now part of the Cloud API and not exposed at all today (medium)
- [ ] `GET /zones/{id_or_name}/rrsets` — DNS records per zone — the actual queryable rows behind zones (medium)
- [ ] `GET /load_balancers/{id}/metrics` — connections, throughput and requests per load balancer for capacity analysis (medium)

Note: Note the payload's doc url (docs.hetzner.cloud) is an HTML docs site; the OpenAPI 3.1 spec lives at https://docs.hetzner.cloud/cloud.spec.json (docs.hetzner.cloud/spec.json 404s). Coverage of the plain list collections is essentially complete — every other GET collection in the spec is already synced.

## Hex — gaps

Today (5): `collections`, `groups`, `project_runs`, `projects`, `users`

Diffed against: <https://learn.hex.tech/docs/api-integrations/api/reference>

- [ ] `ListDataConnections` — lookup table resolving the data connection ids referenced by projects and queried tables (high)
- [ ] `GetQueriedTables` — per-project list of warehouse tables a project queries — the lineage table Hex users actually want (high)
- [ ] `ListTopics` — semantic layer topic lookup, resolves topic references on semantic projects (medium)
- [ ] `ListCells / GetCell` — the cells that make up each project we already sync, needed to analyze notebook composition (medium)
- [ ] `ListThreads / GetThreadMessages` — Hex agent threads and their messages — a genuine event stream of analyst questions (medium)
- [ ] `ListDraftGuides` — draft guides alongside the projects and collections we sync (low)

Note: learn.hex.tech renders the reference client-side from Docusaurus; the operation list above was parsed out of the page's rendered headings (operation ids), not from a raw OpenAPI file — Hex does not publish one at a guessable URL. GetProjectRuns, ListProjects, ListUsers, ListGroups and ListCollections are already covered.

## HiBob — **thin**

Today (2): `employees`, `tasks`

Diffed against: <https://apidocs.hibob.com/reference/get_tasks>

- [ ] `GET /bulk/people/lifecycle` — employee lifecycle state transitions (hire, promotion, termination) — the core HR history table (high)
- [ ] `GET /bulk/people/employment` — employment history rows per employee (contract, manager, site changes) rather than only current state (high)
- [ ] `GET /bulk/people/salaries` — compensation history, the headline HR analytics dataset (high)
- [ ] `GET /timeoff/requests/changes` — time off request event stream plus GET /timeoff/employees/{id}/balance for balances (high)
- [ ] `POST /attendance/entries/search` — clock in/out entries; also /attendance/daily-breakdown/search and /attendance/summaries/search for rollups (high)
- [ ] `GET /company/named-lists` — lookup table resolving the list-value field ids stored on every employee record (high)
- [ ] `POST /hiring/candidates/search` — recruiting pipeline entities, unreachable today (high)
- [ ] `POST /hiring/applications/search` — application rows joining candidates to job openings — the recruiting funnel fact table (high)
- [ ] `GET /job-catalog/job-roles and /job-catalog/job-families` — lookup tables resolving role and family ids carried on employee records (high)
- [ ] `GET /payroll/history` — payroll runs over time, plus POST /people/actual-payments/search (medium)
- [ ] `POST /goals/goals/search` — goals and key results with progress, including /goals/goals/key-results/search (medium)
- [ ] `GET /timeoff/policies and /timeoff/policy-types` — lookup tables resolving the policy ids on time off requests (medium)

Note: PostHog exposes only employees (POST /v1/people/search) and tasks (GET /v1/tasks) from a very large HR API — the reference nav on apidocs.hibob.com lists roughly 190 operations across people, time off, attendance, hiring, goals, job catalog, payroll, documents and workforce planning. Endpoints are static in hibob/settings.py with no dynamic table discovery. Note most read endpoints are POST /...\/search rather than GET, which the implementation will need to handle.

## Hightouch — gaps

Today (5): `destinations`, `models`, `sources`, `sync_runs`, `syncs`

Diffed against: <https://api.hightouch.io/api/swagger.json>

- [ ] `GET /decision-engine/flows` — AI Decisioning flows, Hightouch's headline product and completely absent today (medium)
- [ ] `GET /decision-engine/flow/{flowId}/messages` — the messages inside each decisioning flow — the analytical rows behind flow performance (medium)
- [ ] `GET /idr/{graphId}/runs` — identity resolution run history, the equivalent of sync_runs for identity graphs (medium)
- [ ] `GET /events/contracts` — event schema contracts, a lookup for the event streams flowing through Hightouch (low)

Note: The Redoc page at hightouch.com/docs/api-reference loads its spec from https://api.hightouch.io/api/swagger.json (found in the page's Next.js chunk). The public API is small — syncs, sync runs, models, sources and destinations are already covered, and the remaining paths are mostly single-object GETs or trigger POSTs (campaign sends, sync-sequence runs, trigger endpoints) that are not listable.

## Honeybadger — gaps

Today (5): `deploys`, `faults`, `notices`, `projects`, `sites`

Diffed against: <https://docs.honeybadger.io/api/>

- [ ] `projects/{id}/faults/{id}/occurrences (and projects/{id}/occurrences)` — error occurrence counts over time - Honeybadger's headline volume metric, and we already sync faults (high)
- [ ] `projects/{id}/sites/{id}/uptime_checks` — the actual uptime measurements behind the sites table we already sync (high)
- [ ] `projects/{id}/sites/{id}/outages` — downtime events per monitored site - the core availability fact table (high)
- [ ] `projects/{id}/faults/{id}/affected_users` — user impact per fault, needed to rank errors by blast radius (high)
- [ ] `projects/{id}/environments` — lookup table resolving the environment names carried on faults and deploys (high)
- [ ] `projects/{id}/reports/notices_per_day` — prebuilt daily error volume breakdown (medium)
- [ ] `projects/{id}/reports/notices_by_class` — error-class breakdown dimension for triage dashboards (medium)
- [ ] `projects/{id}/check_ins` — cron/heartbeat monitor state, a separate reliability signal from faults (medium)
- [ ] `projects/{id}/alarms/{id}/history` — alarm state transition history - classic state-change fact table (medium)
- [ ] `projects/{id}/faults/{id}/comments` — triage discussion attached to faults we already sync (medium)
- [ ] `teams/{id}/team_members` — membership table resolving assignee/owner references (low)
- [ ] `accounts (and accounts/{id}/users)` — account-level roster for multi-account orgs (low)

Note: Static endpoint list; source dir products/warehouse_sources/backend/temporal/data_imports/sources/honeybadger has no dynamic table discovery. Enumerated every /v2/ path across the api/faults, api/projects, api/uptime, api/check-ins, api/comments, api/alarms, api/environments, api/teams, api/accounts, api/insights, api/dashboards, api/status-pages and api/streams doc pages.

## Honeycomb — gaps

Today (9): `boards`, `burn_alerts`, `columns`, `datasets`, `derived_columns`, `markers`, `recipients`, `slos`, `triggers`

Diffed against: <https://api-docs.honeycomb.io/api/openapi-public.yaml>

- [ ] `/1/slos/{datasetSlug}/{sloId}/counts/history` — hourly SLI good/bad event counts - the data behind SLO compliance and burn, and we already sync slos (high)
- [ ] `/1/slos/{datasetSlug}/{sloId}/counts` — current SLO budget/compliance counts, Honeycomb's headline reliability metric (high)
- [ ] `/2/teams/{teamSlug}/environments` — lookup table for the environments that own the datasets we already sync (high)
- [ ] `/1/boards/{boardId}/views` — the views that make up each board we sync - board content is otherwise opaque (medium)
- [ ] `/1/dataset_definitions/{datasetSlug}` — lookup mapping dataset definition types (duration, trace id, span kind) to actual column names (medium)
- [ ] `/1/recipients/{recipientId}/triggers` — join table between recipients and triggers, both of which we already sync (medium)
- [ ] `/1/reporting/slos/historical` — weekly historical SLO breakdown across multiple SLOs in one call (medium)
- [ ] `/1/query_annotations/{datasetSlug}` — named/annotated queries used to label saved analyses (low)
- [ ] `/1/marker_settings/{datasetSlug}` — lookup resolving marker types to display settings for the markers we sync (low)

Note: Diffed against the machine-readable OpenAPI spec (api-docs.honeycomb.io/api/openapi-public.yaml). Coverage of top-level v1 resources is good; the gaps are the SLO measurement sub-resources and the v2 environments lookup.

## HoorayHR — gaps

Today (15): `availability`, `contracts`, `document_categories`, `employment_term_assignments`, `employment_terms`, `entities`, `labels`, `leave_types`, `sick_leave_dossiers`, `sick_leave_phases`, `teams_information`, `time_off`, `time_tracking`, `users`, `work_location_categories`

Diffed against: <https://api.hoorayhr.io/swagger.json>

- [ ] `/external-leave-budgets` — per-user leave balances - the core HR analytical metric next to time-off we already sync (high)
- [ ] `/attendance-report` — prebuilt attendance breakdown joining time tracking and absence (high)
- [ ] `/external-leave-types` — lookup resolving the leave type IDs carried on external leave budgets (medium)
- [ ] `/public-holidays` — holiday calendar lookup needed to interpret time-off and time-tracking days (medium)
- [ ] `/working-today` — daily who-is-working snapshot for headcount/availability reporting (low)
- [ ] `/time-zones` — static lookup for user time zone codes (low)

Note: Fetched the OpenAPI spec at https://api.hoorayhr.io/swagger.json (linked from https://api.hoorayhr.io/documentation). 15 of the 21 GET-listable resources are already covered.

## Hubplanner — gaps

Today (13): `billing_rates`, `bookings`, `clients`, `events`, `holidays`, `milestones`, `project_groups`, `project_managers`, `projects`, `resource_groups`, `resources`, `time_entries`, `vacations`

Diffed against: <https://github.com/hubplanner/API/tree/master/Sections>

- [ ] `/categories (booking categories)` — lookup resolving the category ID on every booking we already sync (high)
- [ ] `/costCategories (project cost categories)` — lookup resolving cost category IDs on projects and billing rates (high)
- [ ] `/unassigned-work` — unallocated demand alongside bookings - needed for capacity vs demand analysis (medium)
- [ ] `/project-tag` — lookup resolving project tag IDs for project segmentation (medium)
- [ ] `/resource-tag` — lookup resolving resource tag IDs (skills, roles) for resource segmentation (medium)
- [ ] `/project/customField/template` — lookup defining the project custom fields whose values ride on the projects table (medium)
- [ ] `/resource/customField/template` — lookup defining the resource custom fields whose values ride on the resources table (medium)
- [ ] `/category-groups` — parent grouping for booking categories, used to roll up booking types (low)

Note: Diffed the Sections/\*.md files in the official hubplanner/API repo against products/warehouse_sources/.../hubplanner/settings.py. The missing items are almost all lookup tables for IDs already present on bookings, projects and resources.

## HuggingFace — **thin**

Today (3): `datasets`, `models`, `spaces`

Diffed against: <https://huggingface.co/.well-known/openapi.json>

- [ ] `/api/{repoType}/{namespace}/{repo}/discussions` — discussions and pull requests per repo - the main community activity signal on repos we already sync (high)
- [ ] `/api/collections` — curated collections grouping models, datasets and spaces we already sync (high)
- [ ] `/api/models-tags-by-type and /api/datasets-tags-by-type` — lookup tables resolving the tag strings carried on every model and dataset row (high)
- [ ] `/api/trending` — Hub-wide trending repos - the headline discovery metric (medium)
- [ ] `/api/models|datasets|spaces/{namespace}/{repo}/commits/{rev}` — commit history per repo, the change/velocity fact table for repos we sync (medium)
- [ ] `/api/daily_papers and /api/papers` — papers linked to models and datasets, plus daily paper rankings (medium)
- [ ] `/api/organizations/{name}/members` — org membership roster resolving repo owners (medium)
- [ ] `/api/spaces/{namespace}/{repo}/metrics` — runtime usage metrics for spaces we already sync (medium)
- [ ] `/api/users/{username}/likes` — per-user likes, the engagement edge between users and repos (medium)
- [ ] `/api/jobs/{namespace} (and /{jobId}/metrics)` — compute job runs and their metrics for cost/usage analysis (low)
- [ ] `/api/models|datasets/{namespace}/{repo}/refs` — branches and tags per repo, needed to interpret revision-scoped data (low)
- [ ] `/api/models|datasets/{namespace}/{repo}/lfs-files` — per-file storage footprint for repo size analysis (low)

Note: PostHog exposes only 3 tables against a 252-path API. Diffed against the official machine-readable spec at https://huggingface.co/.well-known/openapi.json. Note the spec does not itself document the /api/models, /api/datasets and /api/spaces list endpoints PostHog already uses, so the spec undercounts rather than overcounts. Source dir products/warehouse_sources/.../hugging_face uses a static ENDPOINTS tuple - no dynamic discovery.

## Humanitix — **thin**

Today (2): `events`, `tags`

Diffed against: <https://api.humanitix.com/v1/documentation/json>

- [ ] `/v1/events/{eventId}/orders` — ticket orders with buyer and revenue data - the core transaction table for any ticketing analysis (high)
- [ ] `/v1/events/{eventId}/tickets` — individual issued tickets including attendee and check-in state, the line-item table under orders (high)
- [ ] `/v1/events/{eventId}/check-in-count` — attendance vs sold counts per event, the headline event-day metric (medium)
- [ ] `/v1/global/event-dates` — occurrence/date rows for recurring events, needed to attribute orders to a specific date (medium)

Note: Fetched the OpenAPI 3.0 spec directly. PostHog syncs events and tags only, so the two transactional tables the API exists to serve (orders and tickets) are entirely absent. Both are nested under /v1/events/{eventId}, so implementing them needs a per-event fan-out like other nested sources.

## Huntr — gaps

Today (8): `actions`, `activities`, `advisors`, `candidates`, `employers`, `job_posts`, `jobs`, `members`

Diffed against: <https://docs.huntr.co>

- [ ] `/org/events` — the job state transition log (JOB_CREATED, JOB_MOVED, JOB_OFFER_DATE_SET, interview dates) - the pipeline history behind jobs we already sync (high)
- [ ] `/org/activity-categories` — lookup resolving the category ID on every activity row we already sync (high)
- [ ] `/org/tags` — lookup resolving tag IDs applied across members, jobs and candidates (high)
- [ ] `/org/candidates/{id}/action-metrics` — per-candidate activity metrics - the engagement measure for candidates we already sync (high)
- [ ] `/org/goals` — goal definitions and targets that member progress is measured against (medium)
- [ ] `/org/member-groups` — cohort/group membership for the members table, the main breakdown dimension (medium)
- [ ] `/org/member-fields (and /org/members/{id}/member-fields)` — custom field definitions plus per-member values, the org's own segmentation attributes (medium)
- [ ] `/org/notes/members` — advisor notes attached to members, useful qualitative history (medium)
- [ ] `/org/board-templates` — lookup resolving board/stage template IDs referenced by jobs (low)

Note: docs.huntr.co is a single-page Slate reference; parsed every https://api.huntr.co/org/\* URL and its HTTP verb out of the rendered HTML. Verified against products/warehouse_sources/.../huntr/settings.py, which uses a static 8-endpoint map.

## Hyperspell — gaps

Today (7): `connections`, `context_documents`, `entities`, `integrations`, `memories`, `queries`, `vaults`

Diffed against: <https://docs.hyperspell.com/llms.txt>

- [ ] `GET /users` — user roster - lookup resolving the user IDs on memories, connections and queries we already sync (high)
- [ ] `GET /entities/{entity_id}/sources` — join table linking entities we sync back to the source documents they were extracted from (medium)
- [ ] `GET /connections/{connection_id}/folders` — the folder inventory per connection, needed to see what scope each connection actually indexes (medium)
- [ ] `GET /context-documents/conflicts` — detected conflicts across context documents - the quality signal for the docs we already sync (medium)
- [ ] `GET /context-documents/reviews` — document review records and their suggestions, the human-in-the-loop audit trail (medium)
- [ ] `GET /integrations/{integration_id}/channels` — lookup of available channels per integration, resolving channel IDs on memories (medium)
- [ ] `GET /context-documents/tree/{tree_id}/edits` — persisted user edits per document tree - edit history over synced context documents (low)
- [ ] `GET /emotional-state/recent` — time series of stored emotional-state observations (low)
- [ ] `GET /memories/status` — indexing progress per memory, useful for freshness/completeness checks (low)

Note: Enumerated the API reference from https://docs.hyperspell.com/llms.txt, then confirmed exact HTTP paths by fetching the individual .md pages (each embeds its Stainless OpenAPI operation line). The 7 synced tables cover the main top-level collections; the gaps are the users roster and sub-resources of things we already sync.

## Imagga — adequate

Today (2): `daily_usage`, `usage`

Diffed against: <https://docs.imagga.com/>

No material gaps found.

Note: docs.imagga.com is a JS SPA that ships no server-rendered resource list, no llms.txt, no sitemap and no OpenAPI file, so I enumerated the API surface by probing api.imagga.com/v2 unauthenticated (401 = real endpoint, 404 = not a route). Confirmed real: /tags, /categories, /categorizers, /croppings, /colors, /faces/detections, /faces/similarity, /faces/groupings, /text, /barcodes, /uploads, /usage. Every one except /usage and /categorizers is per-image inference requiring an image_url/image param — there is nothing record-oriented to list, no cursors, no collections. /v2/categorizers is a tiny static lookup of trained categorizer names, not worth a table. PostHog's `usage` + `daily\_usage` split of GET /v2/usage is the whole warehouse-queryable surface, and the source's own settings.py already documents this reasoning.

## IncidentIo — gaps

Today (12): `alerts`, `custom_fields`, `escalations`, `follow_ups`, `incident_roles`, `incident_statuses`, `incident_types`, `incident_updates`, `incidents`, `schedules`, `severities`, `users`

Diffed against: <https://api-docs.incident.io/>

- [ ] `/v2/incident_alerts` — join table linking alerts to the incidents they triggered - without it the synced `alerts` and `incidents` tables cannot be related at all (high)
- [ ] `/v1/custom_field_options` — lookup resolving the option IDs stored inside the custom field values on every incident; `custom\_fields` alone only gives definitions (high)
- [ ] `/v2/incident_timestamps` — lookup naming the timestamp IDs carried in incident timestamp_values - required to compute MTTA/MTTR from the incidents table (high)
- [ ] `/v2/escalation_paths` — lookup resolving the escalation path IDs referenced by the already-synced `escalations` rows (high)
- [ ] `/v2/alert_sources` — lookup resolving alert_source_config IDs on `alerts`, so alert volume can be attributed to Datadog/Sentry/etc (high)
- [ ] `/v2/schedule_entries` — the actual on-call shifts; `schedules` today is only the rota config, so no one can query who was on call when (high)
- [ ] `/v3/catalog_types and /v3/catalog_entries` — the service/team catalog that custom fields, alert routes and escalation paths all reference by ID - the master lookup for the whole account (high)
- [ ] `/v3/teams` — team lookup for attributing incidents, escalations and follow-ups to owning teams (medium)
- [ ] `/v2/actions` — per-incident action items during the response, complementing the already-synced follow_ups (medium)
- [ ] `/v2/incident_participants and /v2/incident_participant_workloads` — membership table of who participated in each incident plus incident.io's on-call workload metric (medium)
- [ ] `/v2/alert_attributes` — lookup resolving the attribute IDs in each alert's attribute payload (medium)
- [ ] `/v2/status_page_incidents and /v2/status_page_incident_updates` — customer-facing incident communications, separate objects from internal incidents (medium)

Note: The Mintlify docs site serves the same 537KB SPA shell for every path (including /openapi.json, /llms.txt, /docs.json), but that shell embeds the full route table plus a per-tag spec manifest (openapi/tags/\*.json, 53 tags). I diffed against that. Note the API spans three versions concurrently - v1 (severities, incident_statuses, incident_types, custom_field_options, postmortem_documents, maintenance_windows), v2 (most things) and v3 (catalog, teams, alert_routes) - and the existing PostHog source already mixes v1 and v2, so adding v3 paths is consistent. Excluded as config/plumbing: alert_routes, workflows, secrets, api_keys, ip_allowlists, heartbeat, telemetry, notification methods/rules, schedule sync rules/targets.

## Infisical — gaps

Today (5): `audit_logs`, `identities`, `organization_memberships`, `project_memberships`, `projects`

Diffed against: <https://app.infisical.com/api/docs/json>

- [ ] `/api/v1/organization/roles and /api/v2/workspace/{projectId}/roles` — lookup resolving the role IDs already carried on the synced organization_memberships and project_memberships rows (high)
- [ ] `/api/v1/groups (+ /{id}/users, /{id}/machine-identities, /{id}/projects)` — org group membership - the main way access is actually granted, invisible today (high)
- [ ] `/api/v2/workspace/{projectId}/groups` — which groups are attached to which project, the group half of project access (high)
- [ ] `/api/v2/workspace/{projectId}/identity-memberships` — machine identities scoped per project; `identities` today is org-level only, so no one can see which CI identity can read which project (high)
- [ ] `/api/v1/projects/{projectId}/environments/{envId}` — lookup resolving the environment IDs/slugs that audit_logs, folders and secrets all key on (also embedded in the project detail payload) (high)
- [ ] `/api/v2/secret-scanning/findings` — leaked-credential findings - the headline security metric of the product and the most obviously dashboardable table (high)
- [ ] `/api/v2/folders` — the secret path tree; without it secret/audit rows referencing folderId cannot be resolved to a path (medium)
- [ ] `/api/v2/secret-rotations` — rotation configs and last/next rotation timestamps - compliance reporting on stale credentials (medium)
- [ ] `/api/v1/secret-syncs` — sync destinations and their last sync status, for pipeline health reporting (medium)
- [ ] `/api/v2/secret-scanning/data-sources and /api/v2/secret-scanning/data-sources/{provider}/{dataSourceId}/scans` — scan run history that gives the findings table its denominator and coverage over time (medium)
- [ ] `/api/v1/projects/{projectId}/secret-snapshots` — point-in-time change history of a project's secrets, the audit trail complement to audit_logs (medium)
- [ ] `/api/v1/dynamic-secrets and /api/v1/dynamic-secrets/{name}/leases` — ephemeral credential leases - who checked out DB credentials and when (medium)

Note: Endpoint count is a wildly misleading measure of this API's size: of ~800 GET operations, App Connections accounts for 326, Secret Syncs 143, Secret Rotations 106 and PKI Syncs 56, almost all per-provider config variants (one path per AWS/GCP/Okta/... integration) that collapse to a handful of warehouse tables. The genuinely distinct resource families are far fewer, so 5 tables is thinner than it looks but not as thin as a raw path diff suggests. Excluded: the whole app-connections / auth-method (AWS/GCP/OIDC/LDAP/JWT auth) surface, project templates, SSO config, KMS keys, service tokens, gateways. The PKI / cert-manager area is a large separate product line - I left it out because it has no flat certificate list endpoint (certificates are only reachable per serial number, per subscriber or per profile), which makes it a poor warehouse fit without an explicit sub-resource walk.

## Inflowinventory — gaps

Today (5): `customers`, `products`, `purchase_orders`, `sales_orders`, `vendors`

Diffed against: <https://cloudapi.inflowinventory.com/docs/api/swagger.json>

- [ ] `/{companyId}/stock-adjustments` — inventory write-offs and corrections - the transaction table that explains why on-hand quantities move outside of orders (high)
- [ ] `/{companyId}/stock-transfers` — inter-location inventory movements, required for any multi-warehouse stock analysis (high)
- [ ] `/{companyId}/manufacturing-orders` — production/assembly orders - the third order type alongside the sales and purchase orders already synced (high)
- [ ] `/{companyId}/locations` — lookup resolving the locationId carried on orders, transfers and product quantities (high)
- [ ] `/{companyId}/categories` — lookup resolving product categoryId - the primary breakdown dimension for any sales or inventory report (high)
- [ ] `/{companyId}/stock-counts` — physical count cycles and their variances, for shrinkage and count-accuracy reporting (medium)
- [ ] `/{companyId}/product-cost-adjustments` — cost basis changes over time, needed for correct COGS and margin on historical orders (medium)
- [ ] `/{companyId}/product-groups (+ /{productGroupId}/quantities/{locationId})` — product grouping lookup plus per-location on-hand quantities, the current-stock view products alone does not give (medium)
- [ ] `/{companyId}/adjustment-reasons` — lookup resolving the reason code on each stock adjustment - without it adjustments cannot be categorized (medium)
- [ ] `/{companyId}/tax-codes and /{companyId}/taxing-schemes` — lookups resolving tax IDs on order lines, needed to reconcile order totals (medium)
- [ ] `/{companyId}/currencies` — lookup with exchange rates, required to normalize multi-currency order totals (medium)
- [ ] `/{companyId}/team-members` — lookup resolving the user IDs that created or own orders, for per-rep performance reporting (medium)

Note: inFlow publishes a clean ReDoc/Swagger spec and even advertises it in a static header for scrapers, so this diff is exact. Also present but lower value and omitted: payment-terms, pricing-schemes, operation-types, stockroom-users, stockroom-scans, custom-field-definitions / custom-field-dropdown-options, report-settings. Webhooks and batch-job excluded as plumbing. Every path is company-scoped ({companyId} prefix), so the source already resolves a company ID and adding tables is mechanical.

## Inngest — gaps

Today (7): `cancellations`, `environments`, `event_keys`, `events`, `function_runs`, `signing_keys`, `webhooks`

Diffed against: <https://api-docs.inngest.com/api-specs/v2.json>

- [ ] `GET /v2/apps/{appId}/functions` — lookup resolving the function IDs on every run row - today there is no way to get a function's name or app from the warehouse (high)
- [ ] `GET /v1/runs/{runID}/jobs` — per-step execution history within a run (attempts, step outputs, failures) - the grain needed to find which step fails (high)
- [ ] `GET /v2/runs and GET /v2/apps/{appId}/functions/{functionId}/runs` — direct run listings; today function_runs is walked as /v1/events/{internal_id}/runs per event, so cron- and invoke-triggered runs are never captured and the walk costs one request per event (high)
- [ ] `GET /v2/runs/{runId}/trace` — step-level span/timing tree for a run, for latency and retry analysis (medium)
- [ ] `GET /v2/experiments and GET /v2/apps/{appId}/functions/{functionId}/experiments/{experimentId}` — experiment definitions plus per-experiment aggregates, Inngest's own rollout metric (medium)
- [ ] `GET /v2/apps/{appId}` — app metadata to resolve appId on functions and runs (note: fetch-by-id only, there is no list-apps endpoint, so it needs an ID walk) (medium)
- [ ] `GET /v2/sessions, /v2/sessions/{sessionKey}, /v2/sessions/{sessionKey}/{sessionId}/runs` — AgentKit session grouping and the runs belonging to each session, for agent-workflow analysis (medium)

Note: Inngest ships two real OpenAPI specs (v1 at /api-specs/v1.json, v2 at /api-specs/v2.json) plus llms.txt / llms-full.txt; I diffed both. The existing source already mixes versions (environments and both key tables use v2, everything else v1), so pulling runs and functions from v2 fits. Excluded as config: /v2/account, /v2/partner/accounts, and the POST-only invoke/sync/rerun/scores actions. The most valuable single change here is probably switching function_runs off the per-event v1 walk onto GET /v2/runs.

## Insightly — gaps

Today (11): `Contacts`, `Emails`, `Events`, `Leads`, `Notes`, `Opportunities`, `Organisations`, `Pipelines`, `Projects`, `Tasks`, `Users`

Diffed against: <https://api.insightly.com/v3.1/swagger/docs/v3.1>

- [ ] `/PipelineStages` — lookup resolving PIPELINE_STAGE_ID on Opportunities and Projects - Pipelines is synced but its stages are not, so no funnel breakdown is possible (high)
- [ ] `/OpportunityLineItem` — line-item revenue detail behind each opportunity; the deal header alone cannot break revenue down by product (high)
- [ ] `/Opportunities/{id}/StateHistory` — won/lost/abandoned state transition history - the only source for sales-cycle and stage-velocity analysis (pair with /OpportunityStateReasons) (high)
- [ ] `/LeadSources` — lookup resolving LEAD_SOURCE_ID on Leads - the core attribution dimension (high)
- [ ] `/LeadStatuses` — lookup resolving LEAD_STATUS_ID on Leads, needed for any lead funnel (high)
- [ ] `/Ticket` — Insightly Service tickets, an entire product area with no table today (high)
- [ ] `/Quotation and /QuotationLineItem` — quotes and their line items, the pre-close revenue pipeline (medium)
- [ ] `/Product, /Pricebook, /PricebookEntry` — lookups resolving PRODUCT_ID and PRICEBOOK_ENTRY_ID on opportunity and quotation line items (medium)
- [ ] `/Milestones` — project milestones and their completion dates, the delivery-tracking grain under Projects (medium)
- [ ] `/OpportunityCategories, /ProjectCategories, /TaskCategories` — lookups resolving the CATEGORY_ID already present on the synced opportunities, projects and tasks (medium)
- [ ] `/Teams and /TeamMembers` — team membership for rolling per-rep opportunity and task metrics up to teams (medium)
- [ ] `/Prospect and /MarketingVisits` — marketing-side prospect records and site visit events, upstream of Leads (medium)

Note: https://api.insightly.com/v3.1/swagger/docs/v3 (the URL linked from the Help page) 500s; the working spec is .../swagger/docs/v3.1, which I fetched and parsed. The API is also generically extensible: /{objectName}, /{objectName}/Search and /CustomObjects expose user-defined objects, so a dynamic-table mode would be feasible here, though the current source is a fixed 11-table list. Excluded: FileAttachments/Image/ImageField (binary), Follow/Follows, Permissions, DocumentTemplates, ActivitySets, and the Community\*/Forum\*/KnowledgeArticle\* portal surface (low analytical value for most tenants).

## Instana — gaps

Today (9): `alert_configs`, `alerting_channels`, `applications`, `endpoints`, `events`, `infrastructure_snapshots`, `services`, `synthetic_tests`, `websites`

Diffed against: <https://instana.github.io/openapi/openapi.json>

- [ ] `/api/events/settings/event-specifications/built-in and /custom` — lookup resolving the eventSpecificationId carried on every row of the already-synced `events` table - without it events cannot be named or grouped (high)
- [ ] `/api/releases (+ /api/releases/{releaseId})` — release markers used to correlate deploys with events and metric regressions; the standard overlay on every Instana chart (high)
- [ ] `/api/settings/slo and /api/slo/report/{sloId}` — SLO definitions plus attainment/error-budget reports - the headline reliability metric, entirely absent today (high)
- [ ] `/api/synthetics/settings/tests/ci-cd and /api/synthetics/results/{testid}/{testresultid}` — actual synthetic test results; `synthetic\_tests` today is only the test configuration, so there is no pass/fail or latency data (high)
- [ ] `/api/synthetics/settings/locations and /api/synthetics/settings/datacenters` — lookup resolving the location IDs on synthetic tests and results - required to break results down by PoP (high)
- [ ] `POST /api/application-monitoring/metrics/{applications,services,endpoints}` — the golden-signal time series (calls, errors, latency percentiles) for the applications/services/endpoints already synced as catalogs only (high)
- [ ] `/api/settings/apdex and /api/apdex/report/{apdexId}` — Apdex configs and scores, the per-service user-satisfaction metric (medium)
- [ ] `/api/host-agent (+ /api/host-agent/{id})` — agent and host inventory with versions, for fleet coverage and upgrade tracking (medium)
- [ ] `/api/settings/users, /api/settings/rbac/teams, /api/settings/rbac/groups` — user and team membership tables for attributing alerts and ownership (medium)
- [ ] `/api/settings/auditlog and /api/settings/accesslog` — who changed which alert config or dashboard and when - the standard compliance table (medium)
- [ ] `/api/mobile-app-monitoring/config` — mobile app inventory, the exact parallel of the `websites` table already synced from website-monitoring/config (medium)
- [ ] `/api/business-monitoring/business-perspectives` — business perspective definitions that segment traces by business context, a key breakdown dimension (medium)

Note: Instana publishes a full OpenAPI 3 spec (1.9MB JSON / 1.5MB YAML, version 1.307.1417) at instana.github.io/openapi - very reliable to diff against. Two caveats for an implementer: (1) much of the analytical surface is POST-with-body (metrics, analyze/traces, analyze/beacons, analyze/entities) rather than GET, so those tables need request bodies rather than query params; (2) as the source's own settings.py notes, /api/events has no pagination and infrastructure snapshots use a `size` cap, so wide time windows must be chunked. Excluded as config: custom dashboards, API tokens, alert channel infos, maintenance windows, session settings, automation policies, sourcemap uploads, and the per-plugin catalog/tag metadata endpoints.

## Instantly — gaps

Today (10): `accounts`, `campaign_analytics`, `campaign_daily_analytics`, `campaigns`, `custom_tags`, `emails`, `lead_labels`, `lead_lists`, `leads`, `webhook_events`

Diffed against: <https://developer.instantly.ai/api-reference/openapi.json>

- [ ] `GET /api/v2/campaigns/analytics/steps` — per-sequence-step send/open/reply breakdown; the dimension that explains campaign performance (high)
- [ ] `GET /api/v2/accounts/analytics/daily` — daily per-sending-account volume and deliverability; we sync accounts but no account time series (high)
- [ ] `GET /api/v2/custom-tag-mappings` — junction resolving the custom_tags we already sync to campaigns/accounts/leads (high)
- [ ] `GET /api/v2/subsequences` — follow-up sequences attached to campaigns; missing branch of the campaign tree (medium)
- [ ] `GET /api/v2/block-lists-entries` — suppression list explaining why leads were never contacted (medium)
- [ ] `POST /api/v2/accounts/warmup-analytics` — read-shaped per-account warmup health scores (medium)
- [ ] `GET /api/v2/inbox-placement-analytics + /inbox-placement-reports` — inbox vs spam placement results per deliverability test (medium)
- [ ] `GET /api/v2/audit-logs` — workspace change history for attribution and compliance (medium)
- [ ] `GET /api/v2/campaigns/analytics/overview` — aggregate campaign KPI rollup (low)
- [ ] `GET /api/v2/workspace-members` — membership lookup for user IDs on campaigns and leads (low)
- [ ] `GET /api/v2/lead-lists/{id}/verification-stats` — email verification quality per lead list (low)

Note: Full OpenAPI 3.1 spec is public and unauthenticated. Note /leads and /leads/list are POST-only search endpoints (already used by the source); /charges-style write endpoints excluded.

## Instatus — gaps

Today (9): `audience_groups`, `components`, `incidents`, `maintenances`, `metrics`, `pages`, `subscribers`, `team`, `templates`

Diffed against: <https://instatus.com/help/api>

- [ ] `GET /v1/{page_id}/outages` — component outage history — the uptime metric a status page exists to report (high)
- [ ] `GET /v1/{page_id}/incidents/{incident_id}/incident-updates` — incident status transition history (investigating -> identified -> resolved); needed for MTTR (high)
- [ ] `GET /v1/{page_id}/maintenances/{maintenance_id}/maintenance-updates` — maintenance state transitions matching the maintenances we already sync (medium)
- [ ] `GET /v1/{page_id}/generic-notices` — banner notices posted on the status page outside the incident model (low)

Note: Existing 'team' table maps to the teammates endpoint (GET /v1/{page_id}/team) and 'pages' to GET /v2/pages, so those are covered. Metric data points are POST/DELETE only — there is no GET for metric datapoints, so metric time series is not fetchable. escalation-policies, monitors, on-call-schedules, routing-rules and monitoring-integrations doc pages expose no GET list endpoints.

## Intruder — adequate

Today (7): `fixed_occurrences`, `issues`, `occurrences`, `scan_schedules`, `scans`, `tags`, `targets`

Diffed against: <https://api.intruder.io/v1/swagger.json>

No material gaps found.

Note: Full OpenAPI 3.1.1 spec at https://api.intruder.io/v1/swagger.json (linked from the ReadMe docs). Every GET-able analytical collection is already synced: issues, issues/{id}/occurrences, occurrences/fixed, scans, scans/schedules, tags, targets. The only remaining GETs are /health/, /licenses/ (seat/billing), per-occurrence comments and scanner_output (large free-text blobs), and target authentications/api_schemas (scan configuration) — all config or plumbing.

## Invoiced — gaps

Today (9): `coupons`, `credit_notes`, `customers`, `estimates`, `invoices`, `items`, `payments`, `plans`, `subscriptions`

Diffed against: <https://developer.invoiced.com/api/coupons>

- [ ] `GET /events` — object change/audit event stream — the only way to get invoice and subscription state transitions (high)
- [ ] `GET /tax_rates` — lookup table resolving the tax rate IDs carried on invoices, items and line items we already sync (high)
- [ ] `GET /credit_balance_adjustments` — customer credit balance transactions, missing from the AR picture (medium)
- [ ] `GET /tasks` — AR collection tasks and chasing cadence per customer (medium)
- [ ] `GET /customers/{id}/contacts` — contact-level lookup for the customers we sync (billing vs technical recipients) (medium)
- [ ] `GET /customers/{id}/pending_line_items` — metered billing usage accrued but not yet invoiced (medium)
- [ ] `GET /invoices/{id}/payment_plan` — installment schedule attached to an invoice; explains partial payments (medium)
- [ ] `GET /notes` — customer and invoice notes used for collections context (low)
- [ ] `GET /customers/{id}/payment_sources` — payment method mix per customer (low)

Note: Docs are HTML only (no sitemap, no llms.txt, no OpenAPI); the resource list came from the docs nav on the coupons page and each resource page was fetched to confirm GET endpoints. Charges and refunds are POST-only (POST /charges, POST /charges/{id}/refund) with no list endpoint, so they are not syncable.

## Invoiceninja — gaps

Today (15): `clients`, `credits`, `expense_categories`, `expenses`, `invoices`, `payment_terms`, `payments`, `products`, `projects`, `purchase_orders`, `quotes`, `recurring_invoices`, `tasks`, `tax_rates`, `vendors`

Diffed against: <https://api-docs.invoicing.co/api-docs.yaml>

- [ ] `GET /api/v1/activities` — the audit/activity log — every entity state transition (invoice sent, viewed, paid, quote approved) (high)
- [ ] `GET /api/v1/statics` — master lookup payload (currencies, countries, payment types, industries, sizes, timezones, date formats) resolving the \*\_id columns on nearly every synced table (high)
- [ ] `GET /api/v1/task_statuses` — lookup resolving the status_id on the tasks we already sync (high)
- [ ] `GET /api/v1/users` — lookup resolving user_id / assigned_user_id on clients, invoices, tasks, expenses (high)
- [ ] `GET /api/v1/bank_transactions` — bank feed transactions and their match state against payments/expenses (high)
- [ ] `GET /api/v1/company_ledger` — per-client ledger entries — the running AR balance behind invoices and payments (medium)
- [ ] `GET /api/v1/subscriptions` — recurring billing plans customers are subscribed to (medium)
- [ ] `GET /api/v1/recurring_expenses` — recurring cost side; we sync recurring_invoices but not recurring_expenses (medium)
- [ ] `GET /api/v1/recurring_quotes` — recurring quote templates completing the quote lifecycle (medium)
- [ ] `GET /api/v1/company_users` — user-to-company membership and per-company permissions (medium)
- [ ] `GET /api/v1/locations` — client/company location records referenced by invoices and tax logic (medium)
- [ ] `GET /api/v1/reports/ar_detail_report, /reports/product_sales, /reports/profitloss` — prebuilt AR aging, product sales and P&L rollups if raw joins prove awkward (low)

Note: Full OpenAPI 3.0.1 spec (~1 MB) served unauthenticated at https://api-docs.invoicing.co/api-docs.yaml and mirrored in the invoiceninja/invoiceninja repo. Excluded as config/plumbing: designs, templates, tokens, webhooks, company_gateways, group_settings, schedulers, task_schedulers, bank_transaction_rules, documents, system_logs, client_gateway_tokens.

## IP2Whois — adequate

Today (1): `whois`

Diffed against: <https://www.ip2whois.com/developers-api>

No material gaps found.

Note: IP2WHOIS's Domain WHOIS product is literally one endpoint: GET https://api.ip2whois.com/v2?key=&domain=&format=. PostHog's `whois` table covers it fully (the source takes a user-configured domain list and does one lookup per domain). The vendor nav on the fetched page links a second product, 'Hosted Domains API' (/developers-domains-api, sibling of the /domains-lookup UI, returns domains sharing an IP/registrant). I could not read that page — Cloudflare returns 403 to non-browser clients on that path only — so I am not reporting it as a gap: I could not confirm its request shape or whether it shares the IP2WHOIS license key. Worth a manual look if someone wants to widen this source.

## Iterable — **thin**

Today (5): `campaigns`, `channels`, `lists`, `message_types`, `templates`

Diffed against: <https://api.iterable.com/api-docs>

- [ ] `GET /api/campaigns/metrics` — the headline campaign performance metrics (sends, opens, clicks, bounces, unsubs) — none of it is synced today (high)
- [ ] `GET /api/export/userEvents and /api/export/data.json` — the actual message events (emailSend/Open/Click/Bounce, push, SMS, purchases, custom events) and the users table — the core analytical dataset (high)
- [ ] `GET /api/lists/getUsers` — list membership junction resolving the lists we already sync to users (high)
- [ ] `GET /api/journeys` — lookup resolving workflow/journey IDs that appear on campaigns and events (medium)
- [ ] `GET /api/experiments, /api/experiments/metrics, /api/experiments/{id}/variants` — A/B test definitions and per-variant results for campaigns we sync (medium)
- [ ] `GET /api/catalogs and /api/catalogs/{catalogName}/items` — catalog item lookup used for personalization and recommendations (medium)
- [ ] `GET /api/users/getSentMessages` — per-user message history for cohort-level send analysis (medium)
- [ ] `GET /api/campaigns/recurring/{id}/childCampaigns` — lookup linking recurring parent campaigns to their child sends (medium)
- [ ] `GET /api/metadata and /api/metadata/{table}` — key-value metadata tables used as lookups in templates (low)
- [ ] `GET /api/snippets` — reusable template snippets referenced by templates we sync (low)
- [ ] `GET /api/embedded-messaging/messages` — embedded message inventory for the embedded channel (low)

Note: Swagger JSON is public and unauthenticated at https://api.iterable.com/api-docs (52 GET paths). The source's own products/warehouse_sources/backend/temporal/data_imports/sources/iterable/api_inventory.md explicitly defers the Export API (async jobId polling, NDJSON streaming, ~4 req/min limit) — that deferral is why the source is 5 config tables with zero metrics or events. EU keys need api.eu.iterable.com.

## JamfPro — **thin**

Today (9): `buildings`, `categories`, `computer_groups`, `computers`, `departments`, `mobile_devices`, `packages`, `scripts`, `sites`

Diffed against: <https://developer.jamf.com/jamf-pro/reference/get_v1-buildings>

- [ ] `GET /api/v1/users` — lookup resolving the user/owner assigned to the computers and mobile devices we sync (high)
- [ ] `GET /api/v2/computer-groups/smart-group-membership/{id} and /static-group-membership/{id}` — membership junction for the computer_groups we already sync — group rows without members are unusable (high)
- [ ] `GET /api/v2/mobile-device-groups (+ smart/static group membership)` — mobile equivalent of computer_groups plus its membership; we sync mobile_devices but no groups (high)
- [ ] `GET /api/v3/patch-software-title-configurations and /{id}/patch-report, /{id}/patch-summary` — patch compliance per software title and per device — Jamf's headline reporting surface (high)
- [ ] `GET /api/v2/mdm-commands` — MDM command history and status per device; the state-transition record for device management (high)
- [ ] `GET /api/v1/managed-software-updates/update-statuses (+ /computers/{id}, /computer-groups/{id})` — OS update enforcement status per device — core compliance metric (high)
- [ ] `GET /api/v2/patch-policies and /api/v2/patch-policies/{id}/logs` — per-device patch deployment outcomes for the packages we sync (medium)
- [ ] `GET /api/v1/computers-inventory/filevault (and /{id}/filevault)` — FileVault encryption compliance per computer (medium)
- [ ] `GET /api/v1/computer-extension-attributes and /api/v1/mobile-device-extension-attributes` — lookup resolving the custom extension-attribute IDs embedded in inventory records (medium)
- [ ] `GET /api/v1/volume-purchasing-locations/{id}/content and /api/v1/volume-purchasing-subscriptions` — VPP app license inventory and consumption (medium)
- [ ] `GET /api/v1/device-enrollments and /{id}/devices` — ADE/DEP enrollment records and their device rosters (medium)
- [ ] `GET /api/v1/{buildings,categories,departments,packages,scripts}/{id}/history` — object change history for the reference tables we already sync (low)

Note: Jamf publishes no downloadable OpenAPI on developer.jamf.com (ReadMe-hosted; /openapi.json 404s) — the resource list was extracted from the 408 get\_\* reference slugs embedded in the reference page HTML. The instance-hosted spec at https://<tenant>/api/schema requires auth. Source currently syncs /api/v1/computers-inventory and /api/v2/mobile-devices; note v4/computers-inventory and v2/mobile-devices/detail are the newest versions of those. Classic (XML) API resources such as policies and configuration profiles were not audited here.

## Jellyfish — gaps

Today (9): `allocations_by_investment_category`, `allocations_by_person`, `allocations_by_team`, `company_metrics`, `deliverables`, `engineers`, `teams`, `unlinked_pull_requests`, `work_categories`

Diffed against: <https://raw.githubusercontent.com/Jellyfish-AI/jellyfish-mcp/main/README.md>

- [ ] `metrics/person_metrics` — per-engineer engineering metrics; we sync engineers and company_metrics but nothing in between (high)
- [ ] `metrics/team_metrics` — per-team metrics for the teams we already sync — the main breakdown dimension (high)
- [ ] `allocations/details/work_category (+ by_person, by_team)` — allocation split by work category; we sync the work_categories lookup and investment-category allocations but not the work-category allocations themselves (high)
- [ ] `delivery/deliverable_scope_and_effort_history` — scope and effort change history for the deliverables we sync — the state-transition record behind delivery risk (high)
- [ ] `metrics/team_sprint_summary` — sprint-level throughput and commitment per team (medium)
- [ ] `allocations/details/investment_category_person and investment_category_team` — finer-grained investment-category breakdown than the flat allocations table we have (medium)
- [ ] `allocations/summary/investment_category and summary/work_category` — prebuilt allocation rollups for dashboards without re-aggregating detail rows (medium)
- [ ] `ai/company_adoption_analytics, company_impact_analytics, team_adoption_analytics, team_impact_analytics, person_adoption` — AI-assisted engineering adoption and impact — Jellyfish's current headline metric family, entirely unsynced (medium)
- [ ] `devex/insights_by_team` — developer experience survey insights per team (medium)
- [ ] `people/search_people` — broader people roster than list_engineers (non-engineer contributors, managers) (medium)
- [ ] `allocations/filter_fields` — dimension/filter-field lookup describing what allocations can be sliced by (low)

Note: Jellyfish publishes no public OpenAPI; the export API at https://app.jellyfish.co/endpoints/export/v0 is credential-gated. The authoritative public resource list is the official Jellyfish-AI/jellyfish-mcp README, which states each MCP tool maps 1:1 to a Jellyfish API endpoint. Gap names above are the vendor's tool/resource names — exact export paths follow the group/name shape already used by the source (e.g. delivery/work_categories, metrics/company_metrics) and should be confirmed against the MCP's api_schema tool with live credentials before implementing.

## Jenkins — gaps

Today (2): `builds`, `jobs`

Diffed against: <https://www.jenkins.io/doc/book/using/remote-access-api/>

- [ ] `/computer/api/json (nodes / agents + executors)` — lookup table resolving the builtOn field already on builds; agent online/offline and executor counts (high)
- [ ] `/queue/api/json (build queue items)` — queued items with blocked/waiting reasons - the only way to measure build wait time vs run time (high)
- [ ] `/job/{job}/{n}/testReport/api/json (JUnit test report)` — per-build suite and case pass/fail/skip and durations, the headline CI quality metric (high)
- [ ] `build changeSet / culprits (on /job/{job}/{n}/api/json)` — SCM commits and authors attached to each build, needed to join builds to code changes (high)
- [ ] `/view/{name}/api/json (views)` — lookup grouping jobs into views, referenced from the root API's views array (medium)
- [ ] `/job/{job}/{n}/wfapi/describe (pipeline stage descriptions)` — per-stage status and duration for Pipeline jobs, the breakdown dimension for build-time analysis (medium)
- [ ] `build artifacts array (on /job/{job}/{n}/api/json)` — artifacts produced per build; the connector's tree selection does not pull them (low)
- [ ] `/overallLoad/api/json` — executor and queue-length load statistics over time (low)

Note: Jenkins has no vendor OpenAPI spec and no hosted instance; the jenkins.io page describes the /api/json convention but lists no resources. I enumerated the real object list against the publicly readable instance https://jenkins.debian.net (root /api/json, /queue/api/json, /computer/api/json, /overallLoad/api/json, and a build's /api/json showing changeSet, culprits, artifacts). testReport and wfapi are plugin-provided sub-resources I could NOT confirm live (the public instances I reached had no JUnit/Pipeline builds or blocked those paths), so treat those two as lower confidence than the rest. The connector fans builds out per job, so it does scale with the job catalog, but it is genuinely only jobs + builds.

## JfrogArtifactory — gaps

Today (4): `artifacts`, `builds`, `repositories`, `storage_summary`

Diffed against: <https://docs.jfrog.com/artifactory/docs/aql-entities-fields-reference.md>

- [ ] `AQL promotion domain (build promotions)` — build state transition history - when a build moved to which repo, by whom, with what status (high)
- [ ] `AQL statistic domain (stat.downloads, stat.downloaded, stat.downloaded_by)` — artifact download counts and last-download - the headline consumption metric for a registry (high)
- [ ] `AQL artifact / module / dependency domains (build artifacts and dependencies)` — line items joining the already-synced builds to the already-synced artifacts, plus the dependency graph (high)
- [ ] `Xray Get Violations (/xray/api/v1/violations)` — security and license policy violations per artifact/build, the main security-analytics fact table (high)
- [ ] `AQL property domain (artifact properties)` — key/value metadata on artifacts used for promotion and environment labelling (medium)
- [ ] `Xray Artifact Summary / Build Summary (/xray/api/v1/summary/*)` — per-artifact and per-build vulnerability and license rollups (medium)
- [ ] `Release bundles: Get All Bundles / Get All Bundle Versions (AQL release domain)` — release-level grouping of artifacts, the unit teams actually ship (medium)
- [ ] `Xray Get Licenses` — license lookup table resolving license IDs surfaced on artifacts and violations (medium)
- [ ] `List Docker Repositories / List Docker Tags` — tag-level inventory for container registries, which AQL items alone do not resolve cleanly (low)
- [ ] `Archive Entries Search (/api/search/archive)` — class/file entries inside archives for deep dependency auditing (low)

Note: AQL is the connector's main mechanism and it already uses the items and builds domains, but the vendor's own AQL reference documents nine domains (item, build, promotion, property, statistic, artifact, module, dependency, release) - the seven unused ones are where the analytical value sits, and they are reachable through the same /api/search/aql call the connector already makes. Xray endpoints were cross-checked against https://docs.jfrog.com/security/llms.txt. I could not find a fetchable doc listing Access users/groups/permission-target endpoints, so I did not report them.

## Jira — gaps

Today (10): `dashboards`, `fields`, `filters`, `issue_types`, `issues`, `priorities`, `projects`, `resolutions`, `statuses`, `users`

Diffed against: <https://developer.atlassian.com/cloud/jira/platform/swagger-v3.v3.json>

- [ ] `/rest/api/3/issue/{id}/changelog (and /changelog/bulkfetch)` — issue field transition history - the only source for cycle time, time-in-status and reopen rate (high)
- [ ] `/rest/agile/1.0/board/{boardId}/sprint` — sprints, the unit every agile velocity and commitment metric is built on (high)
- [ ] `/rest/agile/1.0/board` — boards lookup that scopes sprints and backlogs to teams (high)
- [ ] `/rest/agile/1.0/sprint/{sprintId}/issue` — sprint-to-issue membership edges needed for velocity and scope-change analysis (high)
- [ ] `/rest/api/3/issue/{id}/comment (or /rest/api/3/comment/list)` — comment volume and response latency, the main collaboration signal on an issue (high)
- [ ] `/rest/api/3/issue/{id}/worklog (with /worklog/updated for incrementals)` — logged time per issue and user, the basis for effort and cost reporting (high)
- [ ] `/rest/api/3/project/{projectIdOrKey}/versions` — lookup resolving the fixVersions/affectedVersions IDs carried on synced issues (medium)
- [ ] `/rest/api/3/project/{projectIdOrKey}/components` — lookup resolving the component IDs carried on synced issues (medium)
- [ ] `/rest/api/3/statuscategory` — lookup rolling the already-synced statuses into To Do / In Progress / Done buckets (medium)
- [ ] `/rest/api/3/group/bulk and /rest/api/3/group/member` — group definitions plus user-to-group membership edges for team-level rollups (medium)
- [ ] `/rest/agile/1.0/board/{boardId}/epic` — epic catalog for rolling issues up to initiatives (medium)
- [ ] `/rest/api/3/issueLinkType (plus issue links)` — blocks/duplicates/relates edges between issues (low)

Note: The connector covers only the platform v3 lookup tables plus /search/jql issues. The entire Jira Software (agile) API is a separate spec at https://developer.atlassian.com/cloud/jira/software/swagger.v3.json (also fetched and diffed) and is untouched - boards and sprints are the single biggest omission for anyone doing delivery analytics. Note /rest/api/3/search is marked 'currently being removed' in the spec; the connector already uses the correct /search/jql replacement.

## JobNimbus — **thin**

Today (4): `activities`, `contacts`, `jobs`, `tasks`

Diffed against: <https://documenter.gw.postman.com/api/collections/3919598/S11PpG4x?segregateAuth=true&versionTag=latest>

- [ ] `/api1/v2/invoices` — billed revenue per job - the core financial fact table (high)
- [ ] `/api1/v2/estimates` — quoted value and win/loss analysis against jobs (high)
- [ ] `/api1/payments` — cash actually collected, needed for AR and collection-rate reporting (high)
- [ ] `/api1/account/users` — lookup resolving the sales rep / owner / assignee IDs carried on jobs, contacts and tasks (high)
- [ ] `/api1/account/settings (workflows, statuses, lead sources, custom fields)` — lookup resolving the workflow, status and lead-source IDs on jobs and contacts (high)
- [ ] `/api1/v2/products` — product catalog that estimate and invoice line items reference (medium)
- [ ] `/api1/budgets` — job budget vs actual, the input to job-level profitability (medium)
- [ ] `/api1/v2/workorders` — scheduled work per job, links crews to jobs (medium)
- [ ] `/api1/v2/materialorders` — material cost and supplier ordering per job (medium)
- [ ] `/api1/account/settings?field=groups` — team/group lookup for rolling users up to crews or offices (medium)
- [ ] `/api1/utility/uoms` — unit-of-measure lookup for product and order line items (low)

Note: The doc URL in the payload (documenter.getpostman.com/view/3919598/S11PpG7g) 404s; the live collection is S11PpG4x. The connector exposes 4 of the ~13 GET-able resources and, notably, none of the money ones (estimates, invoices, payments, budgets) - for a roofing/contracting CRM that is where nearly all the analytical value is. File upload endpoints were excluded per the rules.

## Jotform — gaps

Today (4): `forms`, `questions`, `reports`, `submissions`

Diffed against: <https://api.jotform.com/docs/>

- [ ] `GET /user/usage` — monthly submission, upload, view and payment counts - Jotform's headline account metric (high)
- [ ] `GET /user/folders` — lookup grouping forms into folders, the org dimension for form reporting (medium)
- [ ] `GET /user/history` — account activity log (form created/deleted/edited events) (medium)
- [ ] `GET /user/labels and GET /label/{id}/resources` — label lookup plus the label-to-form/submission edges that resolve tags (medium)
- [ ] `GET /user/subusers` — sub-account users, needed to attribute forms and submissions in team accounts (low)
- [ ] `GET /user` — account record (plan, limits) as the parent row for usage (low)

Note: Jotform's API is genuinely small - forms, questions, reports and submissions are the four biggest resources and are all covered. Remaining GET endpoints are mostly per-form config (/form/{id}/properties, /form/{id}/webhooks) or file uploads (/form/{id}/files), which are excluded. Endpoint list was read from the curl code samples embedded in the docs page, since the page has no machine-readable spec.

## JudgeMeReviews — adequate

Today (2): `products`, `reviews`

Diffed against: <https://judge.me/api/docs.yaml>

No material gaps found.

Note: The OpenAPI 3.0 spec (served to ReDoc from https://judge.me/api/docs.yaml) defines only: /reviews + /reviews/count + /reviews/{id}, /reviewers/{id} and /reviewers/data_request, /shops + /shops/info, /settings, /webhooks\*, write-only /replies and /private_replies, and a set of /widgets/\* endpoints that return rendered HTML fragments or scalar aggregates. There is no list endpoint for reviewers (by-ID only), so it cannot become a table, and reviewer name/email are already embedded on each review. /products is not in the spec but exists on the live API - the connector already syncs it and its own comment documents that. Coverage is proportionate; nothing analytical is missing.

## Jumpcloud — **thin**

Today (6): `applications`, `events`, `system_groups`, `systems`, `user_groups`, `users`

Diffed against: <https://docs.jumpcloud.com/api/2.0/index.yaml>

- [ ] `/api/v2/usergroups/{group_id}/members (and /membership)` — the user-to-group edges; user_groups and users are synced but the join between them is not (high)
- [ ] `/api/v2/systemgroups/{group_id}/members (and /membership)` — the system-to-group edges completing the already-synced system_groups table (high)
- [ ] `/api/v2/systems/{system_id}/users (or /api/v2/users/{user_id}/systems)` — which users can log into which devices - the central access-review fact table (high)
- [ ] `/api/v2/applications/{application_id}/users and /usergroups` — SSO application entitlements per user and group, resolving the synced applications table (high)
- [ ] `/api/v2/systeminsights/* (apps, programs, os_version, patches, disk_encryption, browser_plugins, chrome_extensions, ...)` — ~60 device inventory and compliance fact tables keyed by system_id - the richest analytical surface in the API (high)
- [ ] `/api/v2/policies, /api/v2/policyresults, /api/v2/systems/{id}/policystatuses` — policy catalog plus per-device application results - device compliance state over time (high)
- [ ] `/api/commands and /api/commandresults` — remote command execution history with exit codes and output (medium)
- [ ] `/api/v2/softwareapps and /api/v2/softwareapps/{id}/statuses` — managed software catalog and per-device install/update state (medium)
- [ ] `/api/v2/saas-management/applications, /applications/{id}/usage, /application-licenses, /applications/{id}/accounts` — SaaS app usage, license counts and per-account seats for spend and shadow-IT analysis (medium)
- [ ] `/api/v2/alerts and /api/v2/alerts/{id}/occurrences` — alert definitions plus firing history for device and identity health (medium)
- [ ] `/api/v2/identityrisk/events, /identityrisk/identities` — risk-scored identity events, a distinct signal from the Directory Insights event stream already synced (medium)
- [ ] `/api/v2/directories` — lookup of connected identity sources (AD, Google Workspace, Office 365) that users are bound to (low)

Note: Two separate specs: v1 at https://docs.jumpcloud.com/api/1.0/index.yaml (21 GET paths) and v2 at https://docs.jumpcloud.com/api/2.0/index.yaml (444 GET paths). The connector's 6 tables are all top-level object lists; every association/membership sub-resource is absent, which is the specific thing that makes a directory dataset joinable. The systeminsights family alone is ~60 device-fact endpoints. Nothing is discovered dynamically at sync time.

## JustCall — gaps

Today (6): `calls`, `contacts`, `phone_numbers`, `sales_dialer_calls`, `texts`, `users`

Diffed against: <https://developer.justcall.io/llms.txt>

- [ ] `/v2.1/sales_dialer/campaigns (List all campaigns)` — lookup resolving the campaign a sales_dialer_call belongs to - already syncing the calls without it (high)
- [ ] `/v2.1/calls/ai (List calls AI data)` — transcripts, sentiment and AI scores per call, JustCall's headline conversation-intelligence output (high)
- [ ] `/v2.1/texts/threads (List all threads)` — conversation-level grouping for the already-synced texts; per-message rows alone can't measure response time (high)
- [ ] `/v2.1/users/groups (List all user groups)` — team lookup for rolling agent-level call and text metrics up to teams (high)
- [ ] `/v2.1/sales_dialer/campaigns/{id}/contacts (List campaign contacts)` — campaign membership edges needed for dial-through and contact-rate metrics (medium)
- [ ] `/v2.1/calls/{id}/journey (Get call journey)` — per-call routing and leg history - who it rang, transfers, IVR path (medium)
- [ ] `/v2.1/texts/tags (List all tags)` — tag lookup resolving the tags applied to text threads (medium)
- [ ] `/v2.1/sales_dialer/contacts (List all contacts)` — dialer contact list, a separate population from the synced CRM contacts table (medium)
- [ ] `/v2.1/whatsapp/messages (List all messages)` — WhatsApp is a full message channel alongside texts and is entirely absent (medium)
- [ ] `/v2.1 account / agent / number analytics endpoints` — vendor-computed call metrics per account, agent and number - useful as a reconciliation baseline (medium)
- [ ] `/v2.1/meetings/ai (List meetings AI data)` — meeting-level AI summaries for teams using JustCall meetings (low)
- [ ] `/v2.1/contacts/blacklist (List blacklisted contacts)` — DNC/blacklist state that explains gaps in outbound reach (low)

Note: JustCall's docs are ReadMe-hosted with no fetchable openapi.json, but they publish a complete llms.txt indexing every reference page, which is what I diffed against. Coverage of the raw event tables (calls, texts, sales_dialer_calls) is good; what's missing is the lookup/dimension layer (campaigns, user groups, tags, threads) and the AI/conversation-intelligence tables.

## JustSift — adequate

Today (2): `fields`, `people`

Diffed against: <https://developers.justsift.com>

No material gaps found.

Note: The Sift API is tiny: the inline ReDoc OpenAPI spec (extracted from \_\_redoc_state on developers.justsift.com) exposes only 4 paths — /people/{idOrEmail}, /search/people (GET+POST), /fields/person, and /media/people/{idOrEmail}/{mediaKind}. PostHog's `people` and `fields` tables cover both queryable collections; /media is binary profile imagery and /search/people returns the same person records.

## K6Cloud — gaps

Today (5): `load_tests`, `load_zones`, `projects`, `schedules`, `test_runs`

Diffed against: <https://api.k6.io/cloud/v6/openapi>

- [ ] `test_runs/{id}/query_aggregate_k6` — aggregated metric values per test run — the headline pass/fail numbers (p95 http_req_duration, error rate) that make test_runs analyzable (high)
- [ ] `test_runs/{id}/metrics` — metric metadata per run (name, type, origin); the join key for any metric value query (high)
- [ ] `test_runs/{id}/series` — per-metric time series within a run, for trend and regression charts (medium)
- [ ] `test_runs/{id}/distribution` — breakdown of a run across load zones — the only per-zone dimension available (medium)
- [ ] `labels` — lookup table resolving the label keys/values attached to projects and load tests (medium)
- [ ] `test_runs/{id}/labels` — label dimensions present on a run's metrics (url, status, scenario, method), needed to slice metric data (medium)

Note: Two API versions in play: the resource endpoints PostHog syncs are /cloud/v6/\* (spec at https://api.k6.io/cloud/v6/openapi), but all metrics endpoints are /cloud/v5/\* and are documented only in prose at https://grafana.com/docs/grafana-cloud/testing/k6/reference/cloud-rest-api/metrics/ — not in the OpenAPI file. The v5 metrics endpoints use an unusual OData-ish call syntax, e.g. /cloud/v5/test_runs/:id/query_aggregate_k6(:parameters), and offer an /ms alias to dodge ad blockers.

## Kandji — **thin**

Today (5): `blueprints`, `device_apps`, `device_details`, `device_library_items`, `devices`

Diffed against: <https://documenter.gw.postman.com/api/collections/15284493/TzCTZkBe?segregateAuth=true&versionTag=latest>

- [ ] `prism/{category} (device_information, apps, filevault, local_users, certificates, installed_profiles, system_extensions, kernel_extensions, launch_agents_and_daemons, application_firewall, gatekeeper_and_xprotect, activation_lock, cellular, desktop_and_screensaver, startup_settings, transparency_database)` — Prism is Kandji's fleet-wide inventory dataset — 16 flat, tenant-wide tables that are the product's core analytical surface and need no per-device fan-out (high)
- [ ] `vulnerability-management/detections` — per-device CVE detections — the fact table for vulnerability posture reporting (high)
- [ ] `vulnerability-management/vulnerabilities` — CVE lookup table resolving the vulnerability IDs carried on detections (high)
- [ ] `v2/threat/threat-details` — malware/threat detections per device with quarantine status (high)
- [ ] `users` — lookup table resolving the user IDs already carried on every device record (high)
- [ ] `devices/{device_id}/status` — library-item run status per device — the compliance state behind device_library_items (high)
- [ ] `library/custom-apps, library/custom-scripts, library/custom-profiles, library/ipa-apps` — catalog lookup resolving the library item IDs we already sync in device_library_items (high)
- [ ] `v2/threat/behavioral-detections/events` — behavioral detection event stream, the time-series counterpart to threat details (medium)
- [ ] `devices/{device_id}/activity` — per-device activity/state-transition history for enrollment and drift analysis (medium)
- [ ] `audit/events` — tenant-wide audit event log — who changed what, when (medium)
- [ ] `tags` — lookup table for the tags used to segment devices (medium)
- [ ] `devices/{device_id}/commands` — MDM command history per device, for troubleshooting and success-rate reporting (medium)

Note: Docs are a published Postman collection (api-docs.kandji.io is a Postman documenter page, not OpenAPI — /openapi.json 404s); the machine-readable form is the collection JSON linked above. Product is being rebranded to 'Iru Endpoint Management' in the collection title. PostHog's 5 tables cover devices plus three per-device sub-resources and blueprints, while the collection exposes ~130 requests; the entire Prism reporting surface (the part designed for exactly this kind of export) is absent.

## Katana — gaps

Today (18): `customers`, `inventory`, `inventory_movements`, `locations`, `manufacturing_orders`, `materials`, `price_lists`, `products`, `purchase_orders`, `sales_orders`, `sales_returns`, `services`, `stock_adjustments`, `stock_transfers`, `stocktakes`, `suppliers`, `tax_rates`, `variants`

Diffed against: <https://api.katanamrp.com/v1/openapi.json>

- [ ] `sales_order_rows` — line items behind sales_orders — required for any revenue-by-product or product-mix analysis (high)
- [ ] `purchase_order_rows` — line items behind purchase_orders, with quantities and purchase prices (high)
- [ ] `bom_rows` — bill-of-materials linking products/variants to the materials they consume (high)
- [ ] `manufacturing_order_recipe_rows` — actual ingredient consumption per manufacturing order — yield and material-variance analysis (high)
- [ ] `manufacturing_order_productions` — completed production output per manufacturing order; manufacturing_orders alone only carries planned state (high)
- [ ] `sales_order_fulfillments` — shipment/fulfillment records — the transition from order to delivered (high)
- [ ] `sales_return_rows` — line items behind sales_returns, needed to attribute returns to products (medium)
- [ ] `manufacturing_order_operation_rows` — per-operation timings and assigned operators, for throughput and labor cost (medium)
- [ ] `price_list_rows` — priced items per price list; price_lists alone is only the header (medium)
- [ ] `stocktake_rows` — counted vs expected quantity per stocktake line — the actual shrinkage numbers (medium)
- [ ] `bin_locations and bin_inventory` — bin-level stock lookup and on-hand quantities below the location grain we already sync (medium)
- [ ] `operators` — lookup table resolving operator IDs referenced by manufacturing order operations (medium)

Note: The docs site (developer.katanamrp.com) is a ReadMe app, but the live gateway serves a full OpenAPI 3.0 document at https://api.katanamrp.com/v1/openapi.json — 120 paths. PostHog's 18 tables cover almost every header-level object but essentially none of the row/line-item children, which is where most manufacturing analytics lives. Also unsynced but lower value: serial_numbers, batch_stocks, additional_costs, po_additional_cost_rows, demand_forecasts, negative_stock, custom_field_definitions, customer_addresses, supplier_addresses.

## Kernel — gaps

Today (5): `apps`, `browsers`, `deployments`, `invocations`, `profiles`

Diffed against: <https://docs.onkernel.com/llms.txt>

- [ ] `audit-logs (list audit logs)` — organization-wide event history — the only cross-resource activity log the API offers (high)
- [ ] `browser-pools (list browser pools)` — lookup resolving the pool a browser session was leased from; also carries pool sizing config for utilization analysis (medium)
- [ ] `projects (list projects)` — lookup resolving the project ID carried on apps, deployments, browsers, proxies and extensions (medium)
- [ ] `browser-replays (list browser session replays)` — replay records per browser session, linking runs to recorded evidence (medium)
- [ ] `managed-auth (list auth connections)` — auth connection inventory with health state, joinable to profiles we already sync (medium)
- [ ] `managed-auth (get auth connection event timeline)` — chronological login/re-auth/health-check events per connection — state transition history (medium)
- [ ] `proxies (list proxies)` — lookup resolving proxy IDs referenced by browser sessions (medium)
- [ ] `invocations/{id}/browsers` — join table mapping invocations to the browser sessions they created (low)
- [ ] `extensions (list browser extensions)` — extension inventory per project (low)

Note: Docs expose a clean llms.txt enumerating every API-reference page. The bulk of the API is imperative browser control (filesystem, mouse/keyboard, processes, playwright exec, SSE streams) that has no warehouse value — excluded, along with api-keys and org/project limits. Note the docs' canonical host is kernel.sh/docs, while docs.onkernel.com redirects to it.

## Klaus — gaps

Today (10): `autoqa_ratings`, `autoqa_reviews`, `calibration_sessions`, `csat`, `disputes`, `quizzes`, `reviews`, `scorecards`, `users`, `workspaces`

Diffed against: <https://pub.klausapp.com/public-export-api.swagger.json>

- [ ] `/api/export/quizzes/{id}/responses` — individual quiz responses per user — quizzes alone is only the quiz definition, so pass rates and knowledge gaps are unqueryable (high)
- [ ] `/api/export/conversations/search` — the conversation records that reviews and AutoQA ratings attach to; without them scores cannot be tied back to channel, queue, or handling time (high)
- [ ] `/api/export/quizzes/{id}/overview` — per-quiz aggregate results, the vendor's own summary view (medium)
- [ ] `/api/export/quizzes/leaderboard` — agent ranking dimension across quizzes (medium)

Note: Now branded Zendesk QA. pub.klausapp.com hosts two Swagger 2.0 specs; the relevant one is public-export-api.swagger.json (18 paths) — the sibling public-import-api.swagger.json is write-only ingestion and irrelevant here. PostHog's 10 tables map 1:1 onto the workspace-scoped export endpoints; the only genuine holes are the quiz sub-resources and the POST-based conversation search (which needs a request body, so it is more work than the plain GET exports).

## Knock — gaps

Today (4): `messages`, `tenants`, `users`, `workflow_recipient_runs`

Diffed against: <https://docs.knock.app/llms.txt>

- [ ] `messages/{id}/events` — per-message state transition history (sent, delivered, opened, clicked) — the deliverability fact table behind the messages we already sync (high)
- [ ] `messages/{id}/delivery_logs` — provider-level request/response per delivery attempt; the only way to diagnose bounces and provider failures (high)
- [ ] `objects (list objects in a collection)` — non-user recipients (accounts, projects, devices) — the lookup that resolves object recipient IDs appearing on messages and subscriptions (high)
- [ ] `schedules (list schedules)` — scheduled and recurring workflow runs, the forward-looking counterpart to workflow_recipient_runs (high)
- [ ] `messages/{id}/activities` — the trigger activities (actor, recipient, data) that produced a message — links notifications back to the originating event (medium)
- [ ] `objects/{collection}/{id}/subscriptions and users/{id}/subscriptions` — membership table mapping recipients to the objects they subscribe to; drives audience sizing (medium)
- [ ] `audiences/{key}/members` — audience membership, a straightforward analytical join for targeting analysis (medium)
- [ ] `users/{id}/preferences and objects preferences` — per-recipient notification preference sets — needed to explain why recipients were skipped (medium)
- [ ] `users/{id}/feeds (list feed items)` — in-app feed items per user, for in-app channel engagement analysis (medium)
- [ ] `bulk_operations (get bulk operation)` — status of bulk identify/subscribe jobs, useful for sync auditing (low)

Note: Knock has no publicly downloadable OpenAPI file (docs.knock.app/openapi.json returns the docs SPA), but llms.txt enumerates every api-reference page and is authoritative. Caveat for whoever implements `objects`: there is no global list-all-objects endpoint — listing requires a collection key per request, so the table would need collection names as config or dynamic discovery. The message sub-resources (events, delivery_logs, activities) likewise require iterating message IDs, which is expensive but is where the deliverability data lives.

## Knowbe4 — gaps

Today (8): `group_members`, `groups`, `phishing_campaigns`, `phishing_security_test_recipients`, `phishing_security_tests`, `training_campaigns`, `training_enrollments`, `users`

Diffed against: <https://developer.knowbe4.com/elvis-swagger.yml>

- [ ] `/v1/users/{user_id}/risk_score_history` — per-user Risk Score over time — KnowBe4's headline metric, and the whole point of syncing users (high)
- [ ] `/v1/account/risk_score_history` — org-level Risk Score trend, the top-line number every KnowBe4 report opens with (high)
- [ ] `/v1/groups/{group_id}/risk_score_history` — Risk Score trend per group, the standard department-level breakdown (medium)
- [ ] `/v1/account` — account-level summary (current risk score, subscription tier, seat counts) providing denominators for coverage metrics (medium)
- [ ] `/v1/training/policies and /v1/training/policies/{policy_id}` — policy acknowledgement records — the compliance-attestation half of the training program, entirely absent today (medium)
- [ ] `/v1/phishing/campaigns/{campaign_id}/security_tests` — explicit campaign-to-test join; today the link must be inferred from phishing_security_tests (low)
- [ ] `/v1/training/store_purchases` — lookup resolving the ModStore content IDs referenced by training campaigns (low)
- [ ] `/events, /event_types, /statuses (User Events API)` — custom user risk events plus their type and status lookup tables, feeding into Risk Score (low)

Note: developer.knowbe4.com is a Vue+ReDoc SPA with no visible spec link; the specs are served as static files found in /js/app.e2f7b1e2.js — /elvis-swagger.yml is the Reporting API (what PostHog syncs, 24 paths) and /echelon-swagger.yml is the separate User Events API (different base host and API key, hence the low priority on events/event_types/statuses). PostHog's 8 tables cover the Reporting API's collection endpoints well; what is missing is almost entirely the risk_score_history sub-resources, which are per-entity fan-outs but carry the product's defining metric.

## KongKonnect — **thin**

Today (1): `api_requests`

Diffed against: <https://raw.githubusercontent.com/Kong/developer.konghq.com/main/api-specs/konnect/analytics-requests/v2/openapi.yaml>

- [ ] `/control-planes (Control Planes API v2)` — lookup that resolves the control_plane_id dimension carried on every api_requests row (high)
- [ ] `/control-planes/{id}/core-entities/services` — lookup resolving the service_id on api_requests to a named gateway service (high)
- [ ] `/control-planes/{id}/core-entities/routes` — lookup resolving route_id on api_requests to a path/method (high)
- [ ] `/control-planes/{id}/core-entities/consumers` — lookup resolving consumer_id on api_requests to a named API consumer (high)
- [ ] `/api-products (API Products v2)` — lookup for the api_product / api_product_version dimensions filterable on api_requests (high)
- [ ] `/metrics (Analytics Metrics v2)` — vendor's aggregated traffic, latency and error-rate metrics without re-aggregating raw request rows (medium)
- [ ] `/control-planes/{id}/core-entities/plugins` — which rate-limit/auth plugins were active on a service or route when traffic was served (medium)
- [ ] `/control-planes/{id}/core-entities/consumer_groups and /consumer_groups/{id}/consumers` — consumer-group membership junction for segmenting request volume by tier (medium)
- [ ] `/realms/{realmId}/consumers (Konnect Consumers v1)` — identity-realm consumer registry backing the consumer dimension (medium)
- [ ] `/catalog-services and /scorecards (Service Catalog v1)` — service inventory plus scorecard scores, the headline governance metric (medium)
- [ ] `/control-planes/{id}/core-entities/upstreams and /targets` — upstream/target topology behind each service for latency attribution (low)
- [ ] `/openmeter/meters and /openmeter/subscriptions (Metering & Billing v3)` — metered usage and subscription state for cost-per-request analysis (low)

Note: Kong publishes 25 separate Konnect OpenAPI specs under https://github.com/Kong/developer.konghq.com/tree/main/api-specs/konnect; PostHog implements one path (/api-requests) from analytics-requests/v2. Other specs diffed this run: control-planes/v2, control-planes-config/v2, analytics-metrics/v2, api-products/v2, consumers/v1, service-catalog/v1, audit-logs/v3, metering-and-billing/v3. The audit-logs v3 spec only exposes webhook/destination config, so there is no queryable audit-log table to add.

## Koyeb — gaps

Today (16): `activities`, `app_events`, `apps`, `deployment_events`, `deployments`, `domains`, `instance_events`, `instances`, `organization_members`, `regional_deployments`, `secrets`, `service_events`, `services`, `snapshots`, `usage_details`, `volumes`

Diffed against: <https://raw.githubusercontent.com/koyeb/koyeb-api-client-go/main/api/v1/koyeb/api/openapi.yaml>

- [ ] `/v1/catalog/instances` — lookup resolving the instance_type on services/deployments to vCPU, memory and price (high)
- [ ] `/v1/catalog/regions` — lookup resolving region codes carried on regional_deployments and instances (high)
- [ ] `/v1/projects` — lookup that groups apps and services; project_id is unresolvable today (high)
- [ ] `/v1/usages` — org-level usage rollup; PostHog syncs only usages/details, so totals must be re-derived (medium)
- [ ] `/v1/volume_events` — volume lifecycle history, the only event stream missing while app/service/deployment/instance events are synced (medium)
- [ ] `/v1/regional_deployment_events` — per-region deployment transition history to explain rollout failures (medium)
- [ ] `/v1/catalog/datacenters` — lookup mapping datacenter ids on regional deployments to physical locations (medium)
- [ ] `/v1/organizations` — lookup for organization_id on nearly every synced record (medium)
- [ ] `/v1/instance_snapshots` — instance snapshot inventory; PostHog syncs only volume /v1/snapshots (medium)
- [ ] `/v1/instance_snapshot_events` — snapshot lifecycle transitions (low)
- [ ] `/v1/organizations/{organization_id}/quotas and /v1/quotas/capacity` — quota headroom vs. actual instance counts (low)
- [ ] `/v1/archives` — build archive metadata linking deployments to source bundles (low)

## Kubecost — **thin**

Today (4): `allocation_by_controller`, `allocation_by_namespace`, `allocation_by_pod`, `assets`

Diffed against: <https://docs.kubecost.com/apis/apis-overview>

- [ ] `GET /model/cloudCost` — cloud provider CUR spend; the entire out-of-cluster half of Kubecost's cost model is absent (high)
- [ ] `GET /model/allocation?aggregate=cluster` — cluster is the top breakdown dimension and the only aggregation missing from namespace/controller/pod (high)
- [ ] `GET /model/allocation?aggregate=label:<name>` — label-based chargeback is the standard way teams attribute Kubernetes spend (high)
- [ ] `GET /model/allocation?aggregate=service and ?aggregate=node` — remaining first-class allocation breakdown dimensions the API documents (medium)
- [ ] `GET /model/audit/events (Cost Events Audit API)` — cluster-level change history with estimated cost impact, i.e. why spend moved (medium)
- [ ] `GET /model/savings and /model/savings/requestSizingV2` — headline savings-opportunity numbers surfaced in the Savings dashboard (medium)
- [ ] `GET /model/customCost/timeseries (External Costs API)` — third-party service costs joined into total spend (medium)
- [ ] `GET /model/allocation/trends` — period-over-period percentage change, the metric the UI's total-cost column shows (medium)
- [ ] `GET /model/savings/clusterSizingETL and /model/savings/abandonedWorkloads` — cluster right-sizing and abandoned-workload recommendations (medium)
- [ ] `GET /model/budget (Budget API)` — budget rules to join against actual allocation spend for over/under reporting (low)
- [ ] `GET /model/forecast (Forecast API)` — predicted future spend for allocation, assets and cloud cost (low)
- [ ] `GET /model/projectDisks and /model/projectAddresses` — orphaned disk and IP inventory driving waste cleanup (low)

Note: All four PostHog tables come from just two paths (/model/allocation with three aggregate values, and /model/assets) per products/warehouse_sources/backend/temporal/data_imports/sources/kubecost/settings.py. The docs are now IBM-hosted; docs.kubecost.com/apis/monitoring-apis/README.html 404s but individual API pages resolve.

## Kustomer — gaps

Today (6): `brands`, `conversations`, `customers`, `tags`, `teams`, `users`

Diffed against: <https://developer.kustomer.com/sitemap.xml>

- [ ] `GET /v1/messages (getmessages)` — the message body of every conversation; conversations without messages cannot answer response-content questions (high)
- [ ] `GET /v1/customers/{id}/events (getallcustomerevents) and GET /v1/conversations/{id}/events (getconversationevents)` — state-transition history for the conversations and customers already synced (high)
- [ ] `GET /v1/satisfaction and satisfaction responses (getsatisfaction, getsatisfactionresponse)` — CSAT is the headline support metric and is entirely absent (high)
- [ ] `GET /v1/companies (getcompanies)` — lookup resolving the company a customer belongs to for account-level support reporting (high)
- [ ] `GET /v1/substatuses (getsubstatuses)` — lookup resolving the sub-status id carried on every conversation row (high)
- [ ] `GET /v1/queues (getqueues) and queue metrics (queuemetrics)` — lookup for routing queues plus the queue-depth metric behind SLA reporting (medium)
- [ ] `GET /v1/notes (getnotesfororg)` — internal agent notes attached to conversations and customers (medium)
- [ ] `GET /v1/work-items (getworkitems) and work sessions (getworksessions)` — agent handling time and routing assignment history (medium)
- [ ] `conversation time metrics (getconversationtimesbyconversationid, getv2conversationtimesbyconversationid)` — first-response and resolution durations per conversation (medium)
- [ ] `GET /v1/kobjects and /v1/klasses (getkobjects, getklasses)` — custom objects and their schema, where Kustomer tenants put order/subscription data (medium)
- [ ] `GET /v1/routing/user-statuses (getroutinguserstatuses)` — agent availability state over time for staffing analysis (medium)
- [ ] `GET /v1/audit-logs (getauditlogs)` — configuration and permission change history (low)

Note: Kustomer's ReadMe-hosted reference blocks machine-readable spec fetches (ssr-props ships an empty sidebar); the resource list was taken from the site sitemap, which enumerates one page per operation.

## Lacework — gaps

Today (10): `agent_info`, `alerts`, `audit_logs`, `compliance_evaluations_aws`, `compliance_evaluations_azure`, `compliance_evaluations_gcp`, `compliance_evaluations_k8s`, `entities_machines`, `vulnerabilities_containers`, `vulnerabilities_hosts`

Diffed against: <https://api.lacework.net/api/v2/docs/lacework-api-v2.0.yaml>

- [ ] `GET /api/v2/Policies (and /Policies/search)` — lookup resolving the policyId carried on every synced alert and compliance evaluation (high)
- [ ] `POST /api/v2/Inventory/search` — the full cloud resource inventory that compliance evaluations are scored against (high)
- [ ] `POST /api/v2/Entities/Containers/search and /Entities/Images/search` — container and image inventory needed to join vulnerabilities_containers back to running workloads (high)
- [ ] `GET /api/v2/CloudAccounts (and /CloudAccounts/search)` — lookup resolving cloud account ids on aws/azure/gcp compliance evaluations (high)
- [ ] `POST /api/v2/CloudActivities/search` — cloud control-plane activity trail, the main behavioral dataset alongside alerts (medium)
- [ ] `POST /api/v2/Entities/Packages/search` — installed package inventory that vulnerability findings reference (medium)
- [ ] `POST /api/v2/Activities/UserLogins/search` — login activity for identity-risk analysis (medium)
- [ ] `POST /api/v2/Activities/Connections/search and /Activities/DNSs/search` — network connection and DNS telemetry per machine (medium)
- [ ] `POST /api/v2/VulnerabilityObservations/Hosts/search and /VulnerabilityObservations/Images/search` — per-observation vulnerability facts, finer grained than the summarized vulnerability tables (medium)
- [ ] `POST /api/v2/Entities/Users/search and /Entities/Applications/search` — user and application inventory to attribute machine findings (medium)
- [ ] `GET /api/v2/TeamMembers (and /TeamMembers/search)` — lookup resolving user guids on audit_logs and alert assignments (medium)
- [ ] `GET /api/v2/VulnerabilityExceptions and /Exceptions` — suppression records that explain why known findings are not counted (low)

## Lago — gaps

Today (10): `add_ons`, `applied_coupons`, `billable_metrics`, `coupons`, `credit_notes`, `customers`, `fees`, `invoices`, `plans`, `subscriptions`

Diffed against: <https://raw.githubusercontent.com/getlago/lago-openapi/main/openapi.yaml>

- [ ] `GET /wallets and GET /wallet_transactions` — prepaid credit balances and top-ups; an entire revenue mechanism is missing (high)
- [ ] `GET /payments` — actual cash collection against the invoices already synced (high)
- [ ] `GET /plans/{code}/charges (and /charges/{charge_code}/filters)` — lookup joining plans to billable metrics; without it, fees cannot be traced to pricing rules (high)
- [ ] `GET /events` — the raw usage events that every fee is derived from (high)
- [ ] `GET /taxes` — lookup resolving tax codes applied on invoices, fees and customers (medium)
- [ ] `GET /payment_requests and GET /payment_receipts` — dunning requests and receipts for collections reporting (medium)
- [ ] `GET /billing_entities` — lookup for the billing entity that owns each invoice in multi-entity setups (medium)
- [ ] `GET /analytics/mrr, /analytics/gross_revenue, /analytics/invoice_collection, /analytics/overdue_balance, /analytics/invoiced_usage` — Lago's headline pre-computed revenue metrics (medium)
- [ ] `GET /subscriptions/{external_id}/lifetime_usage` — lifetime usage per subscription for commitment and threshold tracking (medium)
- [ ] `GET /activity_logs` — state-change history across customers, subscriptions and invoices (medium)
- [ ] `GET /customers/{external_customer_id}/current_usage and /past_usage` — in-period usage before invoicing, needed for revenue forecasting (medium)
- [ ] `GET /features and /plans/{code}/entitlements` — entitlement and feature grants per plan and subscription (low)

## LambdaLabs — adequate

Today (9): `audit_events`, `filesystems`, `firewall_rulesets`, `images`, `instance_types`, `instances`, `regions`, `ssh_keys`, `tickets`

Diffed against: <https://cloud.lambda.ai/api/v1/openapi.json>

No material gaps found.

Note: The Lambda Cloud API v1.10.0 exposes 24 paths and every GET-able collection is already synced (audit-events, file-systems, firewall-rulesets, images, instance-types, instances, regions, ssh-keys, tickets). The remainder are mutations (instance-operations/launch|restart|terminate), a firewall-rules alias subsumed by firewall-rulesets, and ticket attachment upload/download plumbing.

## Langfuse — gaps

Today (8): `dataset_items`, `datasets`, `models`, `observations`, `prompts`, `scores`, `sessions`, `traces`

Diffed against: <https://cloud.langfuse.com/generated/api/openapi.yml>

- [ ] `GET /api/public/dataset-run-items` — join table linking dataset items to the trace/observation produced in each eval run - without it synced dataset_items and traces cannot be joined (high)
- [ ] `GET /api/public/datasets/{datasetName}/runs` — the eval run records that dataset-run-items and scores hang off; the unit of 'how did this prompt version do' (high)
- [ ] `GET /api/public/score-configs` — lookup that resolves the config, data type and categorical values behind the score rows already synced (high)
- [ ] `GET /api/public/experiments and GET /api/public/experiment-items` — experiment runs and their per-item results, the headline eval surface (medium)
- [ ] `GET /api/public/annotation-queues, /{queueId}/items` — human annotation queue state and per-item status for review throughput analysis (medium)
- [ ] `GET /api/public/comments` — human comments attached to traces/observations/sessions, useful for qualitative review joins (low)
- [ ] `GET /api/public/organizations/memberships and /projects/{projectId}/memberships` — org/project membership lookup resolving user ids seen on traces and annotations (org-scoped key required) (low)

Note: Endpoint map in products/warehouse_sources/backend/temporal/data_imports/sources/langfuse/settings.py is fully static - no dynamic table discovery. Some newer resources (dashboards, evaluators, evaluation-rules) sit under /api/public/unstable/ and are config-shaped, so excluded.

## LangSmith — gaps

Today (6): `annotation_queues`, `datasets`, `examples`, `feedback`, `projects`, `runs`

Diffed against: <https://api.smith.langchain.com/openapi.json>

- [ ] `POST /v2/threads/query (and /v2/threads/{thread_id}/stats)` — thread-level grouping of runs, the unit conversational agent quality is measured on (high)
- [ ] `GET /api/v1/workspaces (and /api/v1/tenants)` — lookup resolving the tenant/workspace id carried on every session, dataset and run (high)
- [ ] `GET /api/v1/annotation-queues/{queue_id}/runs` — the membership junction between annotation_queues and runs; queues are synced but their contents are not (high)
- [ ] `GET /v2/datasets/{dataset_id}/experiment-runs` — experiment results per dataset, the core evaluation output (high)
- [ ] `GET /api/v1/model-price-map` — lookup mapping model names on runs to token prices, so run cost can be recomputed (medium)
- [ ] `GET /api/v1/datasets/{dataset_id}/versions and /splits` — dataset version history and split assignment, needed to compare experiments fairly (medium)
- [ ] `GET /api/v1/orgs/current/members and /api/v1/workspaces/current/members` — membership tables resolving the user ids that appear on feedback and annotations (medium)
- [ ] `GET /api/v1/orgs/current/billing/granular-usage` — trace and token usage/spend broken down over time (medium)
- [ ] `GET /v1/platform/evaluators` — lookup resolving evaluator ids behind automated feedback scores (medium)
- [ ] `GET /api/v1/repos, /api/v1/repos/{owner}/{repo}/tags, /commits/{owner}/{repo}` — prompt hub registry with versions and commits, joinable to the prompt used by a run (medium)
- [ ] `GET /api/v1/runs/rules and /api/v1/runs/rules/{rule_id}/logs` — the automation rules that generate feedback and queue entries, plus their firing history (low)
- [ ] `GET /api/v1/audit-logs` — workspace configuration and access change history (low)

Note: The spec has 365 paths. PostHog's `projects` table maps to /api/v1/sessions and `runs` to POST /api/v1/runs/query, so the core tracing surface is covered; the gaps are mostly one level down (queue contents, dataset versions) or lookup tables.

## Lattice — gaps

Today (6): `departments`, `feedbacks`, `goals`, `review_cycles`, `updates`, `users`

Diffed against: <https://developers.lattice.com/reference>

- [ ] `GET /v1/reviewCycle/{id}/reviews (also /v1/reviewee/{id}/reviews)` — the actual performance reviews - the core analytical object of the review cycles already synced (high)
- [ ] `GET /v1/reviewCycle/{id}/reviewees` — membership table mapping users to review cycles, needed for participation and completion analysis (high)
- [ ] `GET /v1/goals/updates (and /v1/goals/{id}/updates)` — goal progress history - the state/transition trail behind the goals table; distinct from the synced 'updates' resource (high)
- [ ] `GET /v1/user/{id}/tasks` — task records tied to goals and users, commonly wanted for follow-through analysis (medium)
- [ ] `GET /v1/tags` — lookup resolving tag ids that appear on goals, users and feedback (medium)
- [ ] `GET /v1/user/{id}/customAttributes (+ /v1/customAttribute/{id}, /v1/customAttributeValue/{id})` — custom HR attributes per user plus the lookup that decodes their ids - the main segmentation dimension (medium)
- [ ] `GET /v1/question/{id} and /v1/questionRevision/{id}` — lookup resolving question ids carried on reviews and feedback (fetch-by-id only, no list endpoint) (low)
- [ ] `GET /v1/competency/{id}` — competency lookup referenced by review questions and ratings (low)

Note: developers.lattice.com is a ReadMe site with no downloadable OpenAPI file; endpoint list and exact paths were read from the embedded reference nav data and confirmed per-page (e.g. api_reviewcycle_reviews resolves to "path":"/v1/reviewCycle/{id}/reviews"). A separate Lattice Talent API exists but its spec is not publicly fetchable.

## LaunchDarkly — gaps

Today (6): `auditlog`, `environments`, `flags`, `members`, `metrics`, `projects`

Diffed against: <https://app.launchdarkly.com/api/v2/openapi.json>

- [ ] `GET /api/v2/projects/{projectKey}/environments/{environmentKey}/experiments` — experiments and their results are LaunchDarkly's headline analytical object and are entirely absent today (high)
- [ ] `GET /api/v2/segments/{projectKey}/{environmentKey}` — segments referenced by the flag targeting rules already synced - without them rule targets are unresolvable ids (high)
- [ ] `GET /api/v2/flag-statuses/{projectKey}/{environmentKey}` — per-flag status and last-requested timestamp, the basis for stale-flag and adoption reporting (high)
- [ ] `GET /api/v2/projects/{projectKey}/metric-groups` — lookup grouping the metrics already synced, and what experiments actually attach to (medium)
- [ ] `GET /api/v2/teams (+ /teams/{teamKey}/maintainers, /teams/{teamKey}/roles)` — team membership and maintainer mapping for the members table already synced (medium)
- [ ] `GET /api/v2/code-refs/statistics/{projectKey} and /api/v2/code-refs/repositories` — flag code-reference counts per repo - how you prove a flag is safe to remove (medium)
- [ ] `GET /api/v2/engineering-insights/flag-events` — flag change event stream, a real transition history to complement the audit log (medium)
- [ ] `GET /api/v2/engineering-insights/deployments` — deployment records used for lead-time and release-frequency analysis (medium)
- [ ] `GET /api/v2/approval-requests` — approval request lifecycle for flag changes - governance and change-velocity reporting (medium)
- [ ] `GET /api/v2/projects/{projectKey}/environments/{environmentKey}/holdouts` — holdout groups tied to experiment measurement (medium)
- [ ] `GET /api/v2/engineering-insights/pull-requests` — PR records feeding lead-time metrics alongside deployments (low)
- [ ] `GET /api/v2/tags and GET /api/v2/projects/{projectKey}/context-kinds` — small lookups resolving tag values and context kinds used across flags and segments (low)

Note: Static endpoint map (projects, members, auditlog, environments, metrics, flags) with a {project_key} fan-out; no dynamic table discovery. Excluded config/plumbing surfaces: tokens, webhooks, oauth clients, sdk-keys, destinations, integrations, relay configs. The /api/v2/usage/\* family is time-series metering rather than record tables, so it is a poorer warehouse fit and was left out.

## Leadfeeder — gaps

Today (3): `accounts`, `leads`, `visits`

Diffed against: <https://docs.leadfeeder.com/api/>

- [ ] `GET /accounts/{account_id}/custom_feeds (and GET /accounts/{account_id}/custom_feeds/{id}/leads)` — custom feeds are the saved lead segments; syncing them resolves feed ids and lets leads be attributed to a segment (medium)

Note: The docs page PostHog targets is explicitly labelled the legacy Leadfeeder API and points new integrations at the newer Dealfront platform API (https://docs.dealfront.com/api/public), which the page says exposes richer company/contact data, financials, signals, tags, lists and CRM relationships. That newer API is hosted on Apidog with no fetchable spec, so its resource list is unverified and not enumerated here - but the connector is built on a deprecated API and is worth a migration review. Legacy API resources are only accounts, custom feeds, leads, visits and feed exports; PostHog covers three of the four queryable ones.

## Leexi — adequate

Today (5): `call_notes`, `calls`, `meeting_events`, `teams`, `users`

Diffed against: <https://docs.public-api.leexi.ai/llms.txt>

No material gaps found.

Note: The full public API surface is users, teams, meeting events, calls and call notes - all five are already synced. Remaining endpoints are writes (create call, create/update/delete note, launch assistant), a presigned-upload helper, and webhooks, none of which are warehouse tables.

## Lemlist — gaps

Today (5): `activities`, `campaigns`, `team`, `team_senders`, `unsubscribes`

Diffed against: <https://developer.lemlist.com/api-reference/openapi/v2.json>

- [ ] `GET /campaigns/{campaignId}/leads/ (and GET /leads)` — the prospect records a campaign is actually working - the fact table the synced activities point at (high)
- [ ] `GET /contacts` — unified contact records with custom variables; the identity table for joining activities to people (high)
- [ ] `GET /campaigns/reports and GET /v2/campaigns/{campaignId}/stats` — headline campaign performance metrics (sends, opens, replies, interested) without re-aggregating raw activities (high)
- [ ] `GET /campaigns/{campaignId}/sequences` — lookup resolving the sequence and step ids carried on every activity row (high)
- [ ] `GET /campaigns/{campaignId}/statutes` — per-lead campaign state (paused, finished, interested) - the transition status behind funnel reporting (medium)
- [ ] `GET /companies (and GET /companies/{companyId}/notes)` — company records for account-level outreach reporting (medium)
- [ ] `GET /inbox and GET /inbox/{contactId}` — conversations and messages, the reply side of outreach that activities only summarize (medium)
- [ ] `GET /tasks` — manual task queue tied to leads and campaigns (medium)
- [ ] `GET /contacts/lists` — lookup resolving the contact lists that contacts are grouped into (medium)
- [ ] `GET /team/crmUsers` — lookup resolving the user ids stamped on campaigns, activities and senders (medium)
- [ ] `GET /schedules (and /campaigns/{campaignId}/schedules/)` — sending schedules attached to campaigns, useful for timing analysis (low)
- [ ] `GET /fields` — custom variable/field definitions that decode lead custom attributes (low)

Note: Only 5 of ~35 GET-able resources are exposed today; the connector's endpoint map is static. Watchlist/signal-agent endpoints (/watchlist, /watchlist/signals, /watchlist/history) are also queryable and analytical but were cut for the 12-gap cap. Excluded: hooks, lemwarm settings, enrichment jobs, email-account connect/test, audio upload.

## LemonSqueezy — adequate

Today (17): `checkouts`, `customers`, `discount_redemptions`, `discounts`, `files`, `license_key_instances`, `license_keys`, `order_items`, `orders`, `prices`, `products`, `stores`, `subscription_invoices`, `subscription_items`, `subscriptions`, `usage_records`, `variants`

Diffed against: <https://docs.lemonsqueezy.com/api/orders>

- [ ] `GET /v1/affiliates` — affiliate records and commission totals, the one remaining list resource not synced (low)

Note: Coverage is essentially complete: every list endpoint in the API nav (stores, customers, products, variants, prices, files, orders, order-items, subscriptions, subscription-invoices, subscription-items, usage-records, discounts, discount-redemptions, license-keys, license-key-instances, checkouts) is already a table. Only affiliates, webhooks (config, excluded) and the single-object /v1/users/me remain.

## LessAnnoyingCRM — gaps

Today (6): `contacts`, `events`, `notes`, `tasks`, `teams`, `users`

Diffed against: <https://account.lessannoyingcrm.com/api_docs/v2/Core_Functions/Pipeline_Items>

- [ ] `GetPipelineItems (also GetPipelineItemsAttachedToContact)` — pipeline items are the deal/opportunity records - the core revenue object and the biggest hole in coverage (high)
- [ ] `GetPipelines` — lookup resolving the pipeline ids that pipeline items and contacts carry (high)
- [ ] `GetPipelineStatuses` — lookup resolving stage/status ids on pipeline items; required for any funnel or stage-duration analysis (high)
- [ ] `GetGroups + GetContactsInGroup (GetGroupsAttachedToContact)` — group definitions plus the contact-to-group membership table used for segmentation (medium)
- [ ] `GetEmails (GetEmailsAttachedToContact)` — logged email activity per contact, the main engagement signal alongside notes and events (medium)
- [ ] `GetCustomFields` — lookup decoding the custom field ids that appear on contacts and pipeline items (medium)
- [ ] `GetRelationshipsAttachedToContacts` — contact-to-contact relationship graph (company/person links) used for account rollups (medium)
- [ ] `GetCalendars` — calendar lookup resolving the calendar ids on the events already synced (low)

Note: LACRM's v2 API is RPC-shaped (single POST endpoint with a Function name), so gaps are listed by Function name rather than path; names confirmed from the live doc pages. Endpoint map in the connector is static. Excluded: file upload/download and webhook functions.

## Lever — gaps

Today (8): `archive_reasons`, `opportunities`, `postings`, `requisitions`, `sources`, `stages`, `tags`, `users`

Diffed against: <https://hire.lever.co/developer/documentation>

- [ ] `opportunities/{id}/feedback` — interview scorecards and ratings - the core hiring-quality signal, missing entirely (high)
- [ ] `opportunities/{id}/interviews` — scheduled interview records with panel/interviewer and timing, needed for funnel and scheduling analysis (high)
- [ ] `candidates/{id}/applications (+ /applications/deleted)` — links a candidate/opportunity to a specific posting; the join table behind apply-to-hire funnels (high)
- [ ] `opportunities/{id}/offers` — offer records with salary/status - offer acceptance rate is a headline recruiting metric (high)
- [ ] `disposition_stages` — lookup resolving the disposition/stage codes carried on archived opportunities (medium)
- [ ] `audit_events` — state-transition history for candidates, postings and users; the only source of change-over-time in Lever (medium)
- [ ] `opportunities/{id}/notes` — recruiter activity volume per candidate (medium)
- [ ] `opportunities/{id}/referrals` — referral source attribution for hires (medium)
- [ ] `opportunities/{id}/panels` — interview panel composition and interviewer load (medium)
- [ ] `requisition_fields (+ /{field}/options)` — lookup resolving custom requisition field slugs and dropdown option values on requisitions we already sync (medium)
- [ ] `opportunities/{id}/forms` — profile form responses hold structured screening answers (low)
- [ ] `opportunities/{id}/resumes` — parsed resume metadata (schools, employers) for candidate-source analysis (low)

Note: Most Lever gaps are sub-resources nested under /opportunities/{id}, which PostHog already syncs, so they can be fanned out from the existing opportunities table. /v1/contacts has retrieve+update only (no list), so it is not syncable. EEO responses exist (/v1/eeo/responses) but were excluded as sensitive PII rather than analytical.

## Lightdash — gaps

Today (6): `charts`, `dashboards`, `metrics_catalog`, `org_users`, `projects`, `spaces`

Diffed against: <https://raw.githubusercontent.com/lightdash/lightdash/main/packages/backend/src/generated/swagger.json>

- [ ] `projects/{projectUuid}/explores` — lookup of every dbt model/table and its fields - resolves the field IDs embedded in the charts we already sync (high)
- [ ] `analytics/user-activity/{projectUuid}` — Lightdash's headline adoption metric: per-user views, queries and chart creation (high)
- [ ] `schedulers/{projectUuid}/list` — scheduled delivery definitions; the parent for run history below (high)
- [ ] `schedulers/{projectUuid}/runs (and /logs)` — per-run state and failure history for scheduled deliveries - the reliability table (high)
- [ ] `projects/{projectUuid}/dataCatalog/{table}/analytics (and /{field})` — which charts and dashboards use each table/field - drives model deprecation decisions (medium)
- [ ] `org/groups (+ groups/{groupUuid}/members)` — group membership table resolving access for the org users we already sync (medium)
- [ ] `v2/content` — unified listing of charts, dashboards and sql charts including spaces and last-updated, useful as a single content inventory (medium)
- [ ] `v2/projects/{projectUuid}/validate` — content validation errors per project - broken chart/dashboard tracking over time (medium)
- [ ] `saved/{chartUuid}/history (chart version history)` — change history for charts; who changed what and when (medium)
- [ ] `projects/{projectUuid}/access (and /groupAccesses)` — per-project user and group access rows; the permission join table (medium)
- [ ] `projects/{projectUuid}/tags` — lookup resolving tag IDs attached to catalog items and content (medium)
- [ ] `dashboards/{dashboardUuidOrSlug}/history` — dashboard version history alongside chart history (low)

Note: No public OpenAPI is served from docs.lightdash.com; the authoritative spec is the tsoa-generated swagger.json checked into the lightdash monorepo (268 GET paths). Many paths are AI-agent, SCIM, git-integration and SSO plumbing that were excluded.

## Lightfield — gaps

Today (9): `accounts`, `contacts`, `emails`, `lists`, `meetings`, `members`, `notes`, `opportunities`, `tasks`

Diffed against: <https://docs.lightfield.app/api/resources/object/methods/list/>

- [ ] `objects/{entitySlug} (custom object records)` — customer-defined CRM objects - the only entity type with records that PostHog does not expose at all (high)
- [ ] `{resource}/definitions (account, contact, opportunity, meeting, note, task, object)` — field/attribute definitions - the lookup that resolves the custom field slugs appearing inside the fields map on every record we already sync (medium)

Note: Lightfield's full resource list is account, contact, email, file, list, meeting, member, note, object, opportunity, task (plus auth/merge helpers), so PostHog already covers 9 of 11. Custom objects are addressed dynamically by entitySlug (GET /v1/objects/{entitySlug}), so implementing them requires discovering the slugs at sync time rather than a static table list. File endpoints were excluded as uploads/plumbing.

## LightspeedRetail — gaps

Today (8): `customers`, `inventory`, `outlets`, `products`, `registers`, `sales`, `taxes`, `users`

Diffed against: <https://x-series-api.lightspeedhq.com/reference/listcustomers>

- [ ] `consignments (GET /api/2.0/consignments)` — stock orders, transfers and stocktakes - the entire inbound inventory movement side is missing (high)
- [ ] `consignment_products (GET /api/2.0/consignments/{id}/products)` — line items of each stock order, needed for received-vs-ordered and cost analysis (high)
- [ ] `suppliers (GET /api/2.0/suppliers)` — lookup resolving the supplier_id carried on products and consignments (high)
- [ ] `payment_types (GET /api/2.0/payment_types)` — lookup resolving payment type IDs on the sale payments we already sync (high)
- [ ] `product_categories (GET /api/2.0/product_categories)` — lookup for category IDs on products - required for any category-level sales breakdown (high)
- [ ] `brands (GET /api/2.0/brands)` — lookup resolving brand_id on products (medium)
- [ ] `customer_groups (+ /customer_groups/{id}/customers)` — customer segment membership table for cohort and loyalty analysis (medium)
- [ ] `stock_adjustments (GET /api/2.0/stock_adjustments)` — inventory movement/shrinkage records that explain changes in the inventory table we sync (medium)
- [ ] `promotions (+ /promotions/{id}/products, promo codes)` — discount campaigns and their product scope; needed to attribute discounted revenue (medium)
- [ ] `gift_cards (+ gift card transactions)` — outstanding liability and gift-card redemption transactions (medium)
- [ ] `store_credits (+ transactions and balances)` — store credit liability and per-customer transaction ledger (medium)
- [ ] `shifts (GET /api/2.0/shifts)` — register shift open/close records for labor and till-reconciliation analysis (medium)

Note: The X-Series docs are a ReadMe.io site with no downloadable OpenAPI; the endpoint inventory was recovered from the 228 operation slugs embedded in the reference page payload. Also unsynced but lower value: price_books/price_book_products, product_types, product_images, serial_numbers, service_orders, quotes, fulfillments, audit log events, custom fields, variant attributes, customer_addresses, channels and retailers.

## Linearb — gaps

Today (5): `deployments`, `measurements`, `services`, `teams`, `users`

Diffed against: <https://docs.linearb.io/api-overview/>

- [ ] `incidents (GET /api/v1/incidents/search and /api/v1/incidents)` — incident records are the input to change failure rate and MTTR, two of the four DORA metrics LinearB is built around (high)

Note: LinearB's public API reference lists only measurements v2, deployments, incidents, external custom metrics, teams v1/v2, users, services, jobs and health. PostHog already covers deployments, measurements, services, teams and users. External custom metrics is write-only (report a metric), jobs is an async job-status poll and health is a liveness probe, so incidents is the only genuine readable gap.

## LingoDev — gaps

Today (1): `jobs`

Diffed against: <https://lingo.dev/en/docs/api/localization/list>

- [ ] `jobs/localization/{jobId} pipeline steps[]` — per-stage record (which pipeline stage ran, status, and cost) is only returned by the single-job GET; the list endpoint returns id/status/engineId/createdAt/targetLocale only, so cost and quality-stage analysis is impossible today (medium)

Note: Lingo.dev's public REST API is genuinely tiny: the only listable collection is GET /jobs/localization, which PostHog already syncs. The other GETs are all keyed lookups - GET /jobs/localization/{jobId}, GET /jobs/localization/groups/{groupId}, GET /engines/{id}/suggestions - and there is no engines list endpoint, so engines cannot be synced as a lookup table. Everything else is POST (localize, recognize, create jobs, provisioning) or WebSocket/webhook. The source implementation uses a static endpoint map (LINGO_DEV_ENDPOINTS), no dynamic table discovery, so the single table reflects the API rather than under-coverage.

## Linkrunner — adequate

Today (3): `attributed_users`, `campaigns`, `reporting_campaigns`

Diffed against: <https://docs.linkrunner.io/api-reference/data-apis.md>

No material gaps found.

Note: The Linkrunner server API exposes exactly three listable GET collections - /campaigns, /attributed-users and /reporting/campaigns - and PostHog syncs all three. The only other GET is /get-attribution-result, a per-device/per-user attribution lookup that requires a device_identifier or user_id and returns a single record, so it is not a syncable table. Everything else (/create-campaign, /capture-payment, /capture-event) is write-only ingestion. Caution for implementers: the openapi.json linked from docs.linkrunner.io/llms.txt is still the Mintlify 'Plant Store' placeholder, not a real spec.

## Linode — gaps

Today (9): `domains`, `events`, `invoices`, `linodes`, `lke_clusters`, `nodebalancers`, `payments`, `users`, `volumes`

Diffed against: <https://raw.githubusercontent.com/linode/linode-api-openapi/main/openapi.json>

- [ ] `account/invoices/{invoiceId}/items` — invoice line items - without them the synced invoices are just totals with no cost breakdown by service (high)
- [ ] `linode/types` — lookup resolving the plan type ID on every Linode instance we sync, plus its hourly/monthly price and specs (high)
- [ ] `regions (and regions/availability)` — lookup resolving the region ID carried on instances, volumes, nodebalancers and buckets (high)
- [ ] `account/transfer` — network transfer pool usage vs quota - the headline overage-risk metric (high)
- [ ] `linode/instances/{linodeId}/transfer/{year}/{month}` — per-instance monthly bandwidth usage, the breakdown behind account-level transfer (medium)
- [ ] `images` — custom and recovery images with size and expiry; a billed resource with no coverage today (medium)
- [ ] `databases/instances (plus databases/types)` — managed database inventory, a billed service class entirely absent from the current tables (medium)
- [ ] `lke/clusters/{clusterId}/pools` — node pool composition and autoscaling settings - the breakdown of the LKE clusters we already sync (medium)
- [ ] `nodebalancers/{nodeBalancerId}/configs (+ /nodes)` — backend node membership per nodebalancer, resolving which instances sit behind each load balancer (medium)
- [ ] `object-storage/buckets (+ object-storage/transfer, quotas usage)` — per-bucket size and object count plus transfer usage for storage cost attribution (medium)
- [ ] `support/tickets (+ /{ticketId}/replies)` — support ticket volume and response history (medium)
- [ ] `account/maintenance` — scheduled and completed host maintenance events per entity - explains reboots seen in the events table (medium)

Note: The Akamai/Linode techdocs site serves no spec directly; the authoritative OpenAPI is linode/linode-api-openapi on GitHub (openapi.json, spec version 4.229.1, 249 GET paths). Also unsynced but lower value: account/logins, tags, placement/groups, vpcs/subnets, networking/firewalls, longview, managed services and stackscripts.

## LlamaCloud — gaps

Today (10): `batches`, `classify_jobs`, `extract_jobs`, `files`, `parse_jobs`, `pipelines`, `projects`, `sheets_jobs`, `split_jobs`, `usage_metrics`

Diffed against: <https://api.cloud.llamaindex.ai/api/openapi.json>

- [ ] `GET /api/v1/extraction/extraction-agents` — lookup table resolving the extraction-agent id carried on every extract job (high)
- [ ] `GET /api/v1/extraction/runs` — run-level history (status, timings, agent) behind extraction jobs (high)
- [ ] `GET /api/v1/indexes` — top-level index objects; nothing in the current table set exposes them (medium)
- [ ] `GET /api/v1/pipelines/{pipeline_id}/documents/paginated` — per-pipeline document inventory with status, the unit of indexing work (medium)
- [ ] `GET /api/v1/pipelines/{pipeline_id}/files2` — pipeline-to-file membership join for the files table we already sync (medium)
- [ ] `GET /api/v1/beta/batch-processing/{job_id}/items` — per-item rows inside a batch; batches alone give only the job header (medium)
- [ ] `GET /api/v1/data-sources` — lookup resolving the data-source ids attached to pipelines (medium)
- [ ] `GET /api/v1/retrievers` — retriever configs referenced by retrieval activity (low)
- [ ] `GET /api/v1/chat` — chat sessions over pipelines, usable as engagement data (low)
- [ ] `GET /api/v1/organizations` — lookup resolving organization ids on projects (low)

## Lob — gaps

Today (8): `addresses`, `bank_accounts`, `campaigns`, `checks`, `letters`, `postcards`, `self_mailers`, `templates`

Diffed against: <https://raw.githubusercontent.com/lob/lob-openapi/main/lob-api-public.yml>

- [ ] `GET /qr_code_analytics` — QR scan events — the only real engagement/response metric Lob exposes for mail (high)
- [ ] `GET /creatives` — lookup resolving the creative id referenced by campaigns we already sync (high)
- [ ] `GET /billing_groups` — lookup resolving billing_group_id present on every mailpiece, needed for cost attribution (high)
- [ ] `GET /uploads and /uploads/{upl_id}/report` — campaign audience uploads plus per-upload success/failure report (high)
- [ ] `GET /snap_packs` — a first-class mailpiece type missing alongside letters/postcards/self_mailers (medium)
- [ ] `GET /booklets` — a first-class mailpiece type missing from the current set (medium)
- [ ] `GET /cards and /cards/{card_id}/orders` — card inventory plus order line items (spend and quantity) (medium)
- [ ] `GET /templates/{tmpl_id}/versions` — template version lookup resolving the version id stamped on each mailpiece (medium)
- [ ] `GET /links` — tracked link definitions that resolve click/scan attribution (medium)
- [ ] `GET /buckslips and /buckslips/{buckslip_id}/orders` — buckslip inserts and their orders, same shape as cards (low)
- [ ] `GET /informed_delivery_campaigns` — USPS Informed Delivery campaign records tied to mailpieces (low)

## LogzIO — **thin**

Today (5): `alerts`, `drop_filters`, `notification_endpoints`, `search_logs`, `triggered_alerts`

Diffed against: <https://docs.logz.io/docs/logz/logz-io-api>

- [ ] `POST /v2/security/rules/events/search (Fetch security events)` — SIEM detection events — the main analytical output of the security product (high)
- [ ] `POST /v2/security/rules/search (Retrieve security rules)` — lookup resolving the rule ids on every security event (high)
- [ ] `GET/POST audit trail (Retrieve audit trail / List account audit trails)` — who changed what in the account, a standard warehouse audit dataset (high)
- [ ] `GET /v1/user-management/users (Retrieve all users)` — lookup resolving user ids on alerts, audit rows and triggered alerts (high)
- [ ] `POST /v1/security/rules/events/logs/search (Logs that triggered a security event)` — drills a detection down to the underlying log lines (medium)
- [ ] `GET /v1/insights (Get the list of Insights)` — Cognitive Insights findings, an analytical product surface (medium)
- [ ] `POST lookup lists search + lookup list elements search` — literal lookup tables used to enrich logs and alerts (medium)
- [ ] `GET time-based sub-accounts (detailed)` — lookup resolving accountId on alerts, tokens and usage rows (medium)
- [ ] `GET /v1/account-management/log-types (Get all log types)` — lookup of log type ids used across search and drop filters (medium)
- [ ] `GET metrics accounts list` — lookup for metrics sub-accounts referenced by account settings (low)
- [ ] `GET users in all associated accounts` — cross-account user roster for multi-account orgs (low)
- [ ] `GET authentication groups` — group-to-role membership resolving user access (low)

Note: Endpoints are enumerated statically in logz_io/source.py; no dynamic table discovery. The Logz.io API is very large (~200 operations) but most of it is config/plumbing (tokens, Grafana dashboards, folders, datasources, S3/archive, silences) which is correctly excluded. Note the api-docs.logz.io sitemap still lists unified-alerts pages (search-unified-alerts, search-unified-alert-events) that now 404, so I did not report them as gaps.

## Loops — gaps

Today (10): `audience_segments`, `campaign_groups`, `campaigns`, `components`, `contact_properties`, `mailing_lists`, `themes`, `transactional_emails`, `transactional_groups`, `workflows`

Diffed against: <https://loops.so/docs/openapi.json>

- [ ] `GET /v1/event-patterns` — lookup of event definitions that workflows and campaigns trigger on (high)
- [ ] `GET /v1/contacts/suppression` — suppressed contacts, needed to reconcile deliverable audience (medium)

Note: Coverage is close to complete — the spec has ~20 listable GET collections and 10 are already exposed. Loops has no bulk contacts list endpoint (only /v1/contacts/find by email or userId), so a contacts table is not implementable against this API; /v1/email-messages/{id} is likewise single-fetch only. Remaining unexposed paths are config/plumbing (api-key, dedicated-sending-ips, uploads) or per-node workflow mutations.

## Luma — gaps

Today (4): `events`, `guests`, `people`, `person_tags`

Diffed against: <https://docs.luma.com/llms.txt>

- [ ] `GET /v1/events/ticket-types/list` — lookup resolving the ticket type ids on every guest ticket and order (high)
- [ ] `GET /v1/calendars/event-tags/list` — event tag lookup — person_tags is synced but the event-side equivalent is not (high)
- [ ] `GET /v1/organizations/calendars/list` — lookup resolving calendar ids that own events and contacts (high)
- [ ] `GET /v1/events/coupons/list` — coupon dimension behind discounted ticket orders (medium)
- [ ] `GET /v1/calendars/coupons/list` — calendar-wide coupons applying across events (medium)
- [ ] `GET /v1/memberships/tiers/list` — membership tier lookup for paid community members (medium)
- [ ] `GET /v1/calendars/admins/list` — calendar admin/host membership table (medium)
- [ ] `GET /v1/organizations/events/list` — org-wide event list spanning all calendars, broader than the single-calendar events table (medium)
- [ ] `GET /v1/calendars/get` — the calendar record itself (name, timezone, settings) as a dimension (low)
- [ ] `GET /v1/organizations/admins/list` — organization admin roster (low)

Note: Luma's docs are ReadMe-hosted with no downloadable OpenAPI; llms.txt is the vendor's own complete operation index and was used as the reference. Source is static (luma/source.py enumerates four schemas, all full-refresh because Luma has no updated-since filter).

## MailerLite — gaps

Today (10): `automations`, `campaigns`, `fields`, `forms_embedded`, `forms_popup`, `forms_promotion`, `groups`, `segments`, `subscribers`, `webhooks`

Diffed against: <https://developers.mailerlite.com/llms.txt>

- [ ] `GET /api/campaigns/{campaign_id}/reports/subscriber-activity` — per-subscriber opens, clicks and bounces — the core campaign analytics table (high)
- [ ] `GET /api/groups/{group_id}/subscribers` — group membership join table for the groups and subscribers we already sync (high)
- [ ] `GET /api/automations/{automation_id}/activity` — subscribers flowing through each automation, the automation-side event stream (high)
- [ ] `GET /api/segments/{segment_id}/subscribers` — segment membership join table (high)
- [ ] `GET /api/ecommerce/shops/{shop_id}/orders` — purchase transactions — the highest-value analytical object in the e-commerce API (high)
- [ ] `GET /api/ecommerce/shops` — lookup resolving shop ids for every e-commerce record (high)
- [ ] `GET /api/ecommerce/shops/{shop_id}/customers` — shop customers linked to subscribers, joins revenue to email (medium)
- [ ] `GET /api/ecommerce/shops/{shop_id}/products` — product catalog resolving order line items (medium)
- [ ] `GET /api/forms/{form_id}/subscribers` — signups attributable to each popup/embedded/promotion form (medium)
- [ ] `GET /api/ecommerce/shops/{shop_id}/categories` — category dimension for product and order breakdowns (medium)
- [ ] `GET /api/timezones` — lookup resolving the timezone id on subscribers and account settings (low)
- [ ] `GET /api/campaign-languages` — lookup resolving campaign language codes (low)

Note: The source ships an api_inventory.md documenting the 10 implemented paths; it only covers the core /api surface and does not mention the separate E-commerce API (shops, carts, orders, products, categories, customers), which is entirely unexposed. All schemas are static and full-refresh (MailerLite has no server-side updated_after filter).

## MailerSend — gaps

Today (5): `activity`, `domains`, `messages`, `recipients`, `templates`

Diffed against: <https://developers.mailersend.com/llms.txt>

- [ ] `GET /v1/analytics/date` — opens, clicks, bounces and deliveries bucketed by date — the vendor's headline metric endpoint (high)
- [ ] `GET /v1/suppressions/hard-bounces` — hard bounce suppression list; no suppression data is synced today (high)
- [ ] `GET /v1/suppressions/spam-complaints` — spam complaint suppression list, a core deliverability metric (high)
- [ ] `GET /v1/suppressions/unsubscribes` — unsubscribe suppression list needed to reconcile deliverable recipients (high)
- [ ] `GET /v1/analytics/country` — geographic breakdown dimension for opens and clicks (medium)
- [ ] `GET /v1/analytics/ua-name and /v1/analytics/ua-type` — client and device breakdown dimensions for engagement (medium)
- [ ] `GET /v1/suppressions/blocklist` — account blocklist entries suppressing sends (medium)
- [ ] `GET /v1/sms/messages` — SMS sends, the SMS-side equivalent of the messages table (medium)
- [ ] `GET /v1/sms/activity` — SMS delivery events, the SMS-side equivalent of activity (medium)
- [ ] `GET /v1/message-schedules` — scheduled but unsent messages, needed for a complete send pipeline view (medium)
- [ ] `GET /v1/identities (sender identities)` — lookup resolving the sender identity behind each message (medium)
- [ ] `GET /v1/dmarc-monitoring reports` — DMARC aggregate report data for domain authentication analysis (low)

Note: Suppression endpoints (/v1/suppressions/blocklist, hard-bounces, spam-complaints, unsubscribes, on-hold-list) are not listed as separate pages in the sitemap or llms.txt; I confirmed them by parsing the rendered /api/v1/email/recipients page, which links all five. Analytics sub-paths (/v1/analytics/date|country|ua-name|ua-type) were confirmed the same way from the analytics page.

## Mailgun — gaps

Today (8): `bounces`, `complaints`, `domains`, `events`, `mailing_lists`, `tags`, `templates`, `unsubscribes`

Diffed against: <https://documentation.mailgun.com/docs/mailgun/api-reference/send/mailgun/metrics/post-v1-analytics-metrics>

- [ ] `POST /v1/analytics/metrics` — the modern aggregated metrics API — Mailgun's headline deliverability numbers (high)
- [ ] `GET /v3/{domain}/stats/total and GET /v3/stats/total` — time-bucketed sent/delivered/opened/bounced counts per domain and account (high)
- [ ] `GET /v3/{domain}/tags/{tag}/stats and /stats/aggregates` — per-tag performance; tags are synced but carry no metrics without these (high)
- [ ] `GET /v3/{domain}/aggregates/devices, /providers, /countries` — device, mailbox provider and country breakdown dimensions for engagement (high)
- [ ] `GET /v3/lists/{list_address}/members` — mailing list membership join table; mailing_lists gives only the list headers (high)
- [ ] `POST /v1/analytics/logs` — the v1 log query API, richer and longer-retained than the v3 events feed already synced (high)
- [ ] `GET /v3/{domain}/whitelists (allowlist)` — allowlist entries completing the suppression picture alongside bounces/complaints/unsubscribes (medium)
- [ ] `GET /v5/accounts/subaccounts` — lookup resolving subaccount ids for multi-tenant sending (medium)
- [ ] `GET /v1/bounce-classification/domains/{domain}/events and /stats` — classified bounce reasons, far more analyzable than raw bounce rows (medium)
- [ ] `GET /v3/{domain}/templates/{name}/versions and /v4/templates/{name}/versions` — template version lookup resolving the version referenced on sends (medium)
- [ ] `POST /v1/analytics/usage-metrics` — account usage/consumption metrics for cost attribution (medium)
- [ ] `GET /v3/ip_pools and /v3/ips` — sending IP and pool lookup for deliverability-by-IP analysis (low)

Note: The URLs supplied in the payload (documentation.mailgun.com/docs/mailgun/api-reference/openapi-final/tag/...) now 404 — the reference moved to /docs/mailgun/api-reference/send/mailgun/<tag>/<operation>. I enumerated the full operation list from https://documentation.mailgun.com/sitemap.xml (414 mailgun api-reference entries) and spot-checked individual operation pages return 200.

## Mailjet — gaps

Today (10): `campaign`, `campaigndraft`, `clickstatistics`, `contact`, `contactmetadata`, `contactslist`, `listrecipient`, `message`, `openinformation`, `template`

Diffed against: <https://dev.mailjet.com/email/reference/messages/>

- [ ] `statcounters` — Mailjet's unified stats endpoint - sent/open/click/bounce counters sliced by campaign, list or sender (high)
- [ ] `messagesentstatistics` — Per-message delivery outcome metrics, the base fact table for deliverability analysis (high)
- [ ] `messagehistory` — Per-message event/state transition log (sent, opened, clicked, bounced, spam) (high)
- [ ] `bouncestatistics` — Bounce events with reason codes; we sync clicks and opens but not bounces (high)
- [ ] `campaignstatistics` — Aggregate performance per campaign, resolving the campaign rows we already sync (high)
- [ ] `contactdata` — Actual custom property values per contact - we sync contactmetadata (the schema) but not the values (high)
- [ ] `openstatistics` — Open events aggregated per message/campaign, complementing the openinformation rows we sync (medium)
- [ ] `messageinformation` — Per-message metadata linking messages to campaigns, senders and spam assassin scores (medium)
- [ ] `newsletter` — Newsletter objects that campaign and campaigndraft rows reference (medium)
- [ ] `sender` — Lookup table resolving the sender IDs carried on campaigns and messages (medium)
- [ ] `listrecipientstatistics` — Engagement metrics per list subscription, joining to the listrecipient rows we sync (medium)
- [ ] `toplinkclicked` — Link-level click breakdown per campaign (medium)

Note: The dev.mailjet.com Gatsby site 404s on most direct HTML fetches; the full REST resource nav is readable from https://dev.mailjet.com/page-data/email/reference/messages/page-data.json. Cross-checked against the vendor's official PHP wrapper resource registry (https://raw.githubusercontent.com/mailjet/mailjet-apiv3-php/master/src/Mailjet/Resources.php), which enumerates ~90 v3 resources. PostHog exposes 10 static tables; the entire statistics family is absent.

## Mailosaur — adequate

Today (3): `messages`, `servers`, `usage_transactions`

Diffed against: <https://mailosaur.com/docs/api/>

No material gaps found.

Note: The API surface is small: analysis/deliverability, devices, files, messages, servers, usage/limits, usage/transactions. PostHog covers messages, servers and usage transactions - i.e. every list-shaped analytical resource. The remainder is 2FA test devices (config), file/attachment downloads (excluded per the rules), a per-message deliverability analysis call, and usage/limits (a quota lookup).

## Mailtrap — **thin**

Today (6): `accounts`, `contact_lists`, `email_logs`, `email_templates`, `sending_domains`, `suppressions`

Diffed against: <https://github.com/mailtrap/mailtrap-openapi/tree/main/specs>

- [ ] `/api/contacts` — The core marketing audience table; contact_lists is synced but not its members (high)
- [ ] `/api/email_campaigns` — Campaign objects - currently no campaign table at all despite contact_lists being synced (high)
- [ ] `/api/stats/date` — Daily aggregated sending stats, the headline dashboard metric (high)
- [ ] `/api/contacts/{contact_identifier}/events` — Per-contact engagement event stream (opens, clicks, unsubscribes) (high)
- [ ] `/api/email_campaigns/{email_campaign_id}/stats` — Per-campaign performance metrics; resolves campaign rows into results (high)
- [ ] `/api/stats/domains` — Sending stats broken down by sending domain, joining to the sending_domains table (medium)
- [ ] `/api/contacts/fields` — Lookup table defining custom contact field IDs that contact rows reference (medium)
- [ ] `/api/sandboxes/{sandbox_id}/messages` — Sandbox test message log - the core object of the Email Sandbox product (medium)
- [ ] `/api/inbound/inboxes/{inbox_id}/messages` — Inbound message log for the inbound parsing product (medium)
- [ ] `/api/tracking_opt_outs` — Tracking opt-out records, distinct from the suppressions we already sync (medium)
- [ ] `/api/stats/email_service_providers` — Deliverability broken down by recipient ESP (Gmail, Outlook, etc.) (medium)
- [ ] `/api/sandboxes` — Lookup table resolving sandbox IDs on sandbox messages (with /api/projects as its parent) (low)

Note: Mailtrap publishes 10 OpenAPI specs covering five distinct products (email sending, sandbox, inbound, promotional/contacts, templates). PostHog exposes 6 tables and misses the contacts, email campaigns and stats surfaces entirely. Note the email-campaigns spec was fetched from specs/email-campaigns.openapi.yml and the stats paths from specs/email-sending.openapi.yml.

## Marketstack — gaps

Today (8): `currencies`, `dividends`, `eod`, `exchanges`, `intraday`, `splits`, `tickers`, `timezones`

Diffed against: <https://api.swaggerhub.com/apis/apilayer-863/MarketstackAPIv2/2.0.0/swagger.json>

- [ ] `/tickerinfo` — Company profile/fundamentals per symbol - the lookup table that resolves the tickers we already sync (high)
- [ ] `/indexlist and /indexinfo` — Market index reference and metadata; benchmarking EOD prices against indices is a core use case (medium)
- [ ] `/etfholdings` — Constituent breakdown per ETF, a genuine breakdown dimension (medium)
- [ ] `/commodities and /commoditieshistory` — Commodity price time series alongside the equity EOD series (medium)
- [ ] `/companyratings` — Analyst ratings per ticker, a common join onto price history (medium)
- [ ] `/company_facts and /submissions` — SEC filing facts and submission history keyed by CIK, for fundamentals analysis (medium)
- [ ] `/bondlist and /bond` — Bond reference and pricing data for fixed-income coverage (low)
- [ ] `/etflist` — Lookup table of ETFs that etfholdings rows reference (low)

Note: PostHog deliberately targets API v1 (MARKETSTACK_BASE_URL is pinned to /v1, with an in-code comment that v1 is free-plan-available), and coverage of v1 is complete - https://marketstack.com/documentation lists exactly the 8 endpoints already synced. All gaps below are v2-only, so acting on them means a version bump; the source's warehouse-source-new-version path exists for that.

## Matomo — **thin**

Today (5): `actions_summary`, `countries`, `referrers`, `visits`, `visits_summary`

Diffed against: <https://demo.matomo.cloud/index.php?module=API&method=API.getReportMetadata&idSite=1&period=day&date=today&format=JSON&token_auth=anonymous>

- [ ] `Actions.getPageUrls` — Page-level traffic report; actions_summary only carries site-wide totals (high)
- [ ] `Goals.get` — Goal conversions and revenue, Matomo's headline conversion metric (high)
- [ ] `Goals.getGoals` — Lookup table resolving the goal IDs that conversion reports key on (high)
- [ ] `Events.getCategory / getAction / getName` — Custom event reports - the closest analogue to PostHog's own event model (high)
- [ ] `Actions.getEntryPageUrls / getExitPageUrls` — Entry and exit page breakdowns for landing-page and drop-off analysis (medium)
- [ ] `Referrers.getReferrerType / getSearchEngines / getWebsites / getSocials` — Channel-level referrer breakdowns; referrers today is only the flat getAll roll-up (medium)
- [ ] `DevicesDetection.getType / getBrowsers / getOsFamilies` — Device, browser and OS breakdown dimensions (medium)
- [ ] `MarketingCampaignsReporting.getName / getSource / getMedium` — UTM campaign attribution reports (medium)
- [ ] `Goals.getItemsSku / getItemsName / getItemsCategory` — Ecommerce product-level line items and revenue (medium)
- [ ] `UserCountry.getRegion / getCity` — Finer geographic breakdown; only country is synced (medium)
- [ ] `Actions.getPageTitles and getSiteSearchKeywords` — Page title and on-site search reporting (low)
- [ ] `VisitFrequency.get and VisitorInterest.*` — Returning-visitor and engagement-depth metrics (low)

Note: Matomo's reference site is JS-rendered, so I read the authoritative report catalog from a live instance via API.getReportMetadata on the public demo - it returns 100 reports across 25 modules. PostHog exposes 5 static tables (Live.getLastVisitsDetails plus 4 report methods) and MATOMO_ENDPOINTS is a static dict, so there is no dynamic discovery. Goals.getGoals and SegmentEditor.getAll were separately confirmed live on the demo instance (SitesManager.getAllSites requires superuser and 401s).

## Maxio — gaps

Today (10): `components`, `coupons`, `credit_notes`, `customers`, `events`, `invoices`, `payment_profiles`, `product_families`, `products`, `subscriptions`

Diffed against: <https://github.com/maxio-com/ab-python-sdk/tree/main/doc/controllers>

- [ ] `insights: Read Mrr / List Mrr Movements / List Mrr per Subscription` — MRR and MRR movement is Maxio's headline metric and has no equivalent in the synced tables (high)
- [ ] `subscription-components: List Subscription Components for Site` — Per-subscription component allocations - the line items joining subscriptions to components (high)
- [ ] `subscription-components: List Usages` — Metered usage records, the basis of consumption billing analysis (high)
- [ ] `subscription-components: List Allocations` — Quantity change history per component, i.e. seat expansion/contraction over time (high)
- [ ] `component-price-points: List All Component Price Points` — Lookup table resolving the price_point_id carried on components and subscriptions (high)
- [ ] `product-price-points: List All Product Price Points` — Lookup table resolving the price point on every product and subscription we sync (high)
- [ ] `invoices: List Invoice Events` — Invoice state transition history (issued, paid, voided, refunded) (medium)
- [ ] `reason-codes: List Reason Codes` — Lookup table resolving cancellation/churn reason codes on subscriptions (medium)
- [ ] `subscription-groups: List Subscription Groups` — Group membership resolving parent/child subscription relationships (medium)
- [ ] `offers: List Offers` — Offer definitions that subscriptions are created from (medium)
- [ ] `subscription-invoice-account: List Prepayments / List Service Credits` — Prepayment and service credit ledger, needed to reconcile account balances (medium)
- [ ] `custom-fields: List Metafields / List Metadata` — Custom field definitions and their per-resource values on customers and subscriptions (medium)

Note: Read the vendor SDK's controller docs (32 controllers) and enumerated the list-shaped operations in each. PostHog covers 10 controllers' primary objects but misses the price-point lookups, usage/allocation history and the Insights (MRR) surface entirely.

## Mem0 — gaps

Today (3): `entities`, `events`, `memories`

Diffed against: <https://docs.mem0.ai/openapi.json>

- [ ] `GET /v1/memories/{memory_id}/history/` — Per-memory state transition history - how a memory was updated over time (high)
- [ ] `GET /v1/stats/` — Aggregate memory/search/add counts, the product's headline usage metric (medium)
- [ ] `GET /api/v1/orgs/organizations/{org_id}/projects/` — Lookup table resolving the project scope that memories and events belong to (medium)
- [ ] `GET /api/v1/orgs/organizations/{org_id}/members/` — Org membership rows for attributing memory activity to people (low)
- [ ] `GET /api/v1/orgs/organizations/` — Parent lookup for the projects and members tables (low)

Note: Mem0 publishes a real OpenAPI spec (33 paths, linked from https://docs.mem0.ai/llms.txt). Most non-covered paths are POST-only write/search operations, so the readable surface is genuinely small and the existing 3 tables cover the bulk of it.

## Mention — gaps

Today (4): `accounts`, `alert_tags`, `alerts`, `mentions`

Diffed against: <https://dev.mention.com/current/>

- [ ] `GET /accounts/{account_id}/stats` — Per-alert statistics with country, tone, weekday and influencer breakdowns - the product's headline metric (high)
- [ ] `GET /accounts/{account_id}/alerts/{alert_id}/authors` — Author/influencer breakdown per alert, with scores; a key analytical dimension over mentions (high)
- [ ] `GET /accounts/{account_id}/alerts/{alert_id}/tasks` — Task assignments on mentions - the workflow state layered over the mentions we already sync (medium)
- [ ] `GET /accounts/{account_id}/alerts/{alert_id}/mentions/{mention_id}/children` — Child/duplicate mentions, needed to deduplicate or measure syndication reach (medium)
- [ ] `GET /accounts/{account_id}/alerts/{alert_id}/shares` — Alert share membership, showing who has access to each alert (low)

Note: The reference is a static HTML tree; the full endpoint list is readable from the index page's link set. MENTION_ENDPOINTS is a static dict with no dynamic discovery, and all four tables are full-refresh.

## Mercury — gaps

Today (11): `Accounts`, `Cards`, `Categories`, `CreditAccounts`, `Customers`, `Events`, `Invoices`, `Recipients`, `Transactions`, `TreasuryAccounts`, `Users`

Diffed against: <https://docs.mercury.com/reference/getaccounts>

- [ ] `merchants (GET /api/v1/merchants)` — lookup table that resolves the merchant IDs already carried on synced Transactions (high)
- [ ] `account statements (GET /api/v1/account/{accountId}/statements)` — period-level opening/closing balances for reconciliation against Accounts (high)
- [ ] `treasury transactions (GET /api/v1/treasury/{treasuryId}/transactions)` — we sync TreasuryAccounts but none of their activity, so treasury yield/flows are unqueryable (high)
- [ ] `treasury statements (GET /api/v1/treasury/{treasuryId}/statements)` — period balances for treasury accounts (medium)
- [ ] `send money approval requests (GET /api/v1/request-send-money)` — approval state/transition history for outbound payments (medium)
- [ ] `recipient invites (GET /api/v1/recipient-invites)` — pending recipient onboarding state alongside synced Recipients (low)
- [ ] `SAFE requests (GET /api/v1/safes)` — fundraising SAFE request records (low)

Note: Endpoint inventory read from the ReadMe nav slug list embedded in the reference page, then each candidate path confirmed by fetching its individual reference page.

## Metabase — gaps

Today (6): `cards`, `collections`, `dashboards`, `databases`, `native_query_snippets`, `users`

Diffed against: <https://www.metabase.com/docs/latest/api.json>

- [ ] `table (GET /api/table, /api/table/{id}/query_metadata)` — lookup table resolving the table IDs referenced by synced cards and databases (high)
- [ ] `field (GET /api/database/{id}/fields, /api/field/{id})` — column-level metadata lookup for the databases we already sync (high)
- [ ] `permissions groups and membership (GET /api/permissions/group, /api/permissions/membership)` — membership table joining synced users to permission groups (high)
- [ ] `query execution log (GET /api/ee/logs/query_execution/{yyyy-mm})` — per-execution runtime/error history — the core usage-analytics fact table (high)
- [ ] `activity recents (GET /api/activity/recent_views, /api/activity/recents, /api/activity/popular_items)` — who viewed which card/dashboard, the main content-usage signal (medium)
- [ ] `revision (GET /api/revision, /api/revision/{entity}/{id})` — change history for cards and dashboards (medium)
- [ ] `task runs (GET /api/task, /api/task/runs)` — sync/scheduled job history for database health monitoring (medium)
- [ ] `collection items (GET /api/collection/{id}/items, /api/collection/tree)` — maps cards/dashboards to the collections we already sync (medium)
- [ ] `metric, measure and segment (GET /api/metric, /api/measure, /api/segment)` — semantic-layer definitions referenced by cards (medium)
- [ ] `alerts, pulses and notifications (GET /api/alert, /api/pulse, /api/notification)` — subscription definitions and recipients (medium)
- [ ] `timeline and timeline events (GET /api/timeline, /api/timeline/{id})` — annotation events attached to collections (low)
- [ ] `transform runs (GET /api/transform, /api/transform-job/{job-id}/runs)` — transform execution history (low)

Note: The docs page renders a Scalar spec; the machine-readable source is https://www.metabase.com/docs/latest/api.json (541 paths). Many paths are embed/public/preview variants that are not warehouse-relevant.

## Metaplane — adequate

Today (4): `connection_sync_statuses`, `connections`, `monitor_evaluations`, `monitors`

Diffed against: <https://docs.metaplane.dev/llms.txt>

No material gaps found.

Note: The public API reference lists only four read-oriented collections — connections, connection sync status, monitors, and monitor evaluation history — and PostHog exposes all four. The remaining endpoints are mutations (create/update monitor, run monitors, ingest datapoint, tag/untag). Tags look like a lookup candidate but there is no list-all-tags endpoint; the tag reads (fetchtagdefinitions, fetchtaggedobjects, fetchtaggedmonitors) all require tag names as input, so they are not syncable as a table.

## Metorial — **thin**

Today (7): `provider_deployments`, `provider_runs`, `providers`, `session_errors`, `session_messages`, `sessions`, `tool_calls`

Diffed against: <https://metorial.com/api>

- [ ] `provider-tools` — lookup table resolving the tool IDs on synced tool_calls (high)
- [ ] `session-providers` — join table linking synced sessions to the providers they used (high)
- [ ] `integration-instances` — the per-customer installed integration records that sessions run against (high)
- [ ] `provider-versions` — lookup resolving the version IDs on provider_deployments and provider_runs (high)
- [ ] `integrations` — integration catalog lookup that integration-instances point at (medium)
- [ ] `session-participants` — membership table of who/what took part in each session (medium)
- [ ] `session-connections` — per-session connection records for connectivity and failure analysis (medium)
- [ ] `session-templates` — template definitions that sessions are instantiated from (medium)
- [ ] `skills and skill-versions` — skill catalog and version history, a first-class Metorial object entirely absent today (medium)
- [ ] `integration-providers / integration-instance-providers` — join tables mapping integrations and instances to providers (medium)
- [ ] `custom-providers and custom-provider-deployments` — customer-authored providers parallel to the built-in providers we sync (medium)
- [ ] `provider-specifications` — schema/spec metadata per provider version (low)

Note: Resource list taken from the API reference navigation on metorial.com/api — 67 resources exposed versus 7 tables synced. Excluded callback/webhook, portal-\*, provider-auth-\*, and provider-config-vault resources as config/plumbing.

## MicrosoftClarity — adequate

Today (1): `project_live_insights`

Diffed against: <https://learn.microsoft.com/en-us/clarity/setup-and-installation/clarity-data-export-api>

No material gaps found.

Note: The Clarity Data Export API has exactly one endpoint: GET https://www.clarity.ms/export-data/api/v1/project-live-insights. PostHog's single project_live_insights table is full coverage. Constraints worth knowing: max 10 requests per project per day, only the last 1-3 days of data, max 3 dimension breakdowns per call, and responses capped at 1,000 unpaginated rows — so the only meaningful extension would be additional dimension-combination variants of the same endpoint, not new endpoints.

## MistralAI — gaps

Today (7): `agents`, `batch_jobs`, `conversations`, `files`, `fine_tuning_jobs`, `libraries`, `models`

Diffed against: <https://docs.mistral.ai/openapi.yaml>

- [ ] `conversation messages / history (GET /v1/conversations/{conversation_id}/messages, /history)` — the actual turns inside the conversations we already sync — without them the conversations table has no content (high)
- [ ] `organization usage (GET /v1/admin/usage)` — token spend and consumption, the headline metric for an LLM vendor (high)
- [ ] `observability traces and spans (POST /v1/observability/traces/search, /spans/search, GET /v1/observability/traces/{trace_id}/spans)` — per-request latency/cost/error telemetry for agent and workflow runs (high)
- [ ] `library documents (GET /v1/libraries/{library_id}/documents)` — the contents of the libraries we already sync, including processing status (high)
- [ ] `admin users and workspaces (GET /v1/admin/users, /v1/admin/workspaces, /v1/admin/workspaces/{uuid}/users)` — lookup and membership tables resolving the user/workspace IDs stamped on jobs and conversations (high)
- [ ] `observability chat completion events (POST /v1/observability/chat-completion-events/search)` — per-completion event log for quality and cost analysis (medium)
- [ ] `agent versions (GET /v1/agents/{agent_id}/versions)` — version history for the agents we sync, needed to attribute runs to a config (medium)
- [ ] `workflow runs and executions (GET /v1/workflows/runs, /v1/workflows/executions/{execution_id}/history)` — run-level state and transition history for workflows (medium)
- [ ] `observability datasets and dataset records (GET /v1/observability/datasets, /v1/observability/datasets/{id}/records)` — eval datasets and their records (medium)
- [ ] `admin audit logs (GET /v1/admin/audit-logs)` — org-level change and access history (medium)
- [ ] `observability campaigns and judges (GET /v1/observability/campaigns, /v1/observability/judges)` — eval campaign definitions and results (low)
- [ ] `prompts and skills with versions (GET /v2/prompts, /v2/prompts/{id}/versions, /v2/skills, /v2/skills/{id}/versions)` — managed prompt/skill registry and its version lineage (low)

Note: Spec has ~230 paths. Excluded inference endpoints (chat/embeddings/ocr/moderation), connector credential and auth paths, api-keys, and rate/spend-limit config. Also note the spec exposes /v1/fine_tuning/models/{model_id} but no /v1/fine_tuning/jobs list path, even though PostHog surfaces a fine_tuning_jobs table — worth double-checking that table's source endpoint against a newer spec revision.

## MixMax — gaps

Today (14): `appointment_links`, `code_snippets`, `file_requests`, `insights_reports`, `live_feed`, `meeting_types`, `messages`, `polls`, `rules`, `sequence_folders`, `sequences`, `snippet_tags`, `user_preferences`, `users`

Diffed against: <https://developer.mixmax.com/reference>

- [ ] `sequence recipients (GET /v1/sequences/{id}/recipients)` — the per-recipient membership and stage state for the sequences we already sync — the core sequence fact table (high)
- [ ] `sent sequences (GET /v1/sequences/sent)` — per-send records with delivery outcome, the transaction table behind sequence performance (high)
- [ ] `contacts (GET /v1/contacts)` — lookup table resolving contact IDs referenced by messages, sequences, and live feed events (high)
- [ ] `live feed events (GET /v1/livefeed/events)` — the individual open/click/reply events; the synced live_feed table is the container, not the events (high)
- [ ] `report data table (POST /v1/reports/data/table)` — Mixmax's own aggregated reporting grid — the vendor's headline metrics (high)
- [ ] `contact groups and their members (GET /v1/contactgroups, GET /v1/contactgroups/{id}/contacts)` — segment definitions plus the membership join to contacts (medium)
- [ ] `teams and team members (GET /v1/teams, GET /v1/teams/{id}/members)` — org structure lookup that resolves the user IDs we already sync (medium)
- [ ] `unsubscribes (GET /v1/unsubscribes)` — suppression list needed to interpret sequence and message outcomes (medium)
- [ ] `snippets (GET /v1/snippets)` — message snippets, a distinct resource from the code_snippets table already synced, and the target of the synced snippet_tags (medium)
- [ ] `yes/no enhancements (GET /v1/yesno)` — recipient responses to yes/no prompts embedded in emails (low)
- [ ] `Q&A enhancements (GET /v1/qa)` — recipient answers to in-email questions, parallel to the polls table (low)
- [ ] `meeting transcripts and summaries (GET /v1/meetings/transcripts/{id}, POST /v1/meetings/summaries/search)` — meeting content alongside the meeting_types we sync (low)

Note: Slug inventory from the ReadMe reference nav (155 pages); each reported path confirmed by fetching the individual reference page and reading its method/path. Excluded the /v1/salesforce\* proxy family (passthrough to Salesforce, redundant with a Salesforce source) and the /v1/integrations\* app-config family.

## Mixpanel — **thin**

Today (4): `annotations`, `cohorts`, `engage`, `export`

Diffed against: <https://developer.mixpanel.com/reference/query-api>

- [ ] `funnels query (GET /api/query/funnels — reference/funnels-query)` — funnel conversion is Mixpanel's headline metric and is entirely absent (high)
- [ ] `saved funnels list (reference/funnels-list-saved)` — lookup table of saved funnel definitions and their IDs, required to drive the funnels query (high)
- [ ] `retention query (reference/retention-query)` — cohort retention, a core Mixpanel report with no equivalent today (high)
- [ ] `segmentation query (reference/segmentation-query, plus numeric/sum/average variants)` — event counts broken down by property — the main breakdown dimension API (high)
- [ ] `insights query (reference/insights-query)` — returns the data behind saved Insights reports (high)
- [ ] `Lexicon schemas (reference/list-all-schemas-for-project, list-schemas-for-entity)` — lookup table of event and property definitions that names and types everything in the export table (high)
- [ ] `lookup tables (reference/list-lookup-tables)` — literally the project's lookup tables, used to resolve IDs on synced events and profiles (high)
- [ ] `activity stream (reference/activity-stream-query)` — per-user chronological event feed joining engage profiles to their activity (medium)
- [ ] `event taxonomy queries (reference/query-top-events, query-events-top-properties, query-events-top-property-values, query-event-properties)` — dimension/cardinality tables for event and property discovery (medium)
- [ ] `retention frequency query (reference/retention-frequency-query)` — addiction/frequency view complementing retention (medium)
- [ ] `experiments (reference/list-experiments, get-experiment)` — experiment definitions and state, needed to attribute events to variants (medium)
- [ ] `annotation tags (reference/get-annotation-tags-1)` — lookup resolving the tags on the annotations table we already sync (low)

Note: Full reference slug inventory extracted from developer.mixpanel.com; per-area OpenAPI specs are referenced on the site as openapi/query.openapi.yaml, openapi/annotations.openapi.yaml, openapi/lexicon-schemas.openapi.yaml, etc. Only 4 tables synced (annotations, cohorts, engage, export) against the whole Query API surface. Excluded feature-flags, GDPR/deletion, service-accounts, and warehouse-connector/import plumbing per the config exclusion rule.

## Mollie — gaps

Today (7): `chargebacks`, `customers`, `payment_links`, `payments`, `refunds`, `settlements`, `subscriptions`

Diffed against: <https://raw.githubusercontent.com/mollie/openapi/main/specs.yaml>

- [ ] `/v2/balances/{balanceId}/transactions` — per-transaction ledger of every movement (payment, refund, fee, payout) — the reconciliation fact table (high)
- [ ] `/v2/balances` — balance accounts that transactions and settlements roll up to; lookup for balanceId (high)
- [ ] `/v2/profiles` — lookup resolving the profileId carried on payments, payment links and methods (high)
- [ ] `/v2/customers/{customerId}/mandates` — SEPA/card mandates that subscriptions and recurring payments reference (high)
- [ ] `/v2/payouts` — bank payouts of settled funds — needed to tie settlements to money received (high)
- [ ] `/v2/payments/{paymentId}/captures` — capture events on authorized payments; without them captured vs authorized amounts can't be split (medium)
- [ ] `/v2/invoices` — Mollie's own invoices to the merchant (fees charged) for cost analysis (medium)
- [ ] `/v2/settlements/{settlementId}/payments` — join table mapping payments/refunds/captures/chargebacks to a settlement (medium)
- [ ] `/v2/methods/all` — payment-method lookup resolving the method code on every payment (medium)
- [ ] `/v2/business-accounts/accounts/{businessAccountId}/transactions` — business account ledger for merchants using Mollie banking (medium)
- [ ] `/v2/balances/{balanceId}/report` — pre-aggregated balance report grouped by transaction category (low)
- [ ] `/v2/terminals` — point-of-sale terminal lookup for in-person payments (low)

Note: Spec is the vendor's single-file OpenAPI (mollie/openapi repo, ~1.9 MB). Config-only resources (clients, client-links, permissions, capabilities, onboarding, webhooks, organizations) were deliberately excluded.

## Monday — gaps

Today (4): `boards`, `items`, `users`, `workspaces`

Diffed against: <https://raw.githubusercontent.com/mondaycom/monday-graphql-api/main/packages/api-types/generated/api-types.d.ts>

- [ ] `boards { columns { id title type settings_str } }` — lookup that resolves the column ids inside every item's column_values — today those columns are unlabeled (high)
- [ ] `boards { activity_logs }` — board change history (status transitions, moves, assignments) — the only source of state-transition data (high)
- [ ] `boards { groups { id title } }` — lookup for the group ids items belong to, including groups with no items (medium)
- [ ] `updates` — comments/updates on items — the collaboration activity stream (medium)
- [ ] `teams` — team objects plus their users — resolves team owners/subscribers on boards (medium)
- [ ] `boards { subscribers owners team_owners }` — board membership join table; boards currently sync with no ownership data (medium)
- [ ] `tags` — tag lookup resolving tag ids stored in item column values (medium)
- [ ] `folders` — workspace folder hierarchy that boards hang off via board_folder_id (medium)
- [ ] `items { subitems }` — subitems live on separate boards and are missed by the current board-items walk (medium)
- [ ] `docs` — workspace docs objects for content coverage alongside boards (low)
- [ ] `boards { views }` — board view inventory for usage analysis (low)

Note: GraphQL API pinned to version 2024-10 in monday.py. The boards query selects only scalar fields, so columns/groups/subscribers are genuinely absent even though they are nested fields rather than separate top-level queries.

## MonteCarlo — **thin**

Today (5): `alerts`, `monitors`, `tables`, `users`, `warehouses`

Diffed against: <https://apidocs.getmontecarlo.com/>

- [ ] `getIncidents` — incidents group related alerts and are the unit teams triage — the headline object above alerts (high)
- [ ] `getEvents / getEventGroups` — raw detector events (freshness, volume, schema change) underlying alerts (high)
- [ ] `getEventsForIncidents` — incident timeline / state-transition history (high)
- [ ] `getDomainsV2 + getDomainsForMcons` — domain lookup and the domain-to-asset membership join for the mcons already synced (high)
- [ ] `getFhEvents / getFhEventsByMonitor` — field-health event series per monitor — the per-field metric history behind monitor results (medium)
- [ ] `getDbtRuns / getDbtJobExecutions / getDbtTestResults` — dbt run and test outcomes tied to the same tables already synced (medium)
- [ ] `getQueryLogs / getAggregatedQueries` — warehouse query logs attributed to tables — usage and cost analysis (medium)
- [ ] `getJobExecutions / getJobSchedules` — pipeline job execution history for freshness root-causing (medium)
- [ ] `getDataProductsV2` — data product definitions that group assets for SLA reporting (medium)
- [ ] `getAccountUsage / getAssetsUsage / getBillingMonitorUsage` — monitored-asset and monitor usage counts — how consumption is tracked (medium)
- [ ] `getAuthorizationGroups + getAccountRoles` — user group/role membership lookup for the users table already synced (medium)
- [ ] `getAccountAuditLogs / getMonitorAuditLogs` — who changed which monitor and when (low)

Note: The GraphQL API exposes 661 documented queries (counted from spectaql anchors at apidocs.getmontecarlo.com); PostHog exposes 5 tables. Many of those queries are integration/config plumbing, but the core observability objects (incidents, events, domains, dbt results) are absent.

## Mux — gaps

Today (9): `assets`, `errors`, `live_streams`, `metrics_comparison`, `playback_restrictions`, `signing_keys`, `transcription_vocabularies`, `uploads`, `video_views`

Diffed against: <https://storage.googleapis.com/stainless-sdk-openapi-specs/mux/mux-d9ec974ac41da39a8bc9920a266615453f948fec82e03a1d9d4ffc0ae5f372c5.yml>

- [ ] `/data/v1/exports/views` — daily raw video-view exports — the bulk path for getting full view-level data into a warehouse (high)
- [ ] `/data/v1/metrics/{METRIC_ID}/breakdown` — Mux Data's headline output: any metric broken down by dimension (country, CDN, player) (high)
- [ ] `/data/v1/metrics/{METRIC_ID}/timeseries` — metric over time — the core QoE trend series (high)
- [ ] `/data/v1/dimensions and /data/v1/dimensions/{DIMENSION_ID}/elements` — lookup enumerating valid dimensions and their values, needed to interpret breakdowns and view rows (high)
- [ ] `/video/v1/delivery-usage` — delivery minutes per asset — the billing/usage fact table (high)
- [ ] `/data/v1/metrics/{METRIC_ID}/overall` — aggregate metric value plus total watch time and view count for a window (medium)
- [ ] `/data/v1/incidents (+ /incidents/{id}/related)` — detected delivery incidents with affected-view counts (medium)
- [ ] `/video/v1/assets/{ASSET_ID}/playback-ids (or /video/v1/playback-ids/{PLAYBACK_ID})` — lookup mapping the playback ids on video_views back to assets (medium)
- [ ] `/data/v1/annotations` — user annotations marking releases/incidents on metric timelines (medium)
- [ ] `/data/v1/filters` — legacy filter/value lookup still used to validate view query filters (low)
- [ ] `/video/v1/live-streams/{LIVE_STREAM_ID}/simulcast-targets` — restream destinations per live stream (low)
- [ ] `/video/v1/drm-configurations` — DRM configuration lookup referenced by playback ids (low)

Note: Spec URL taken from muxinc/mux-node-sdk .stats.yml (114 configured endpoints). Realtime/monitoring endpoints (/data/v1/realtime/\*, /data/v1/monitoring/\*) were skipped as they serve last-minutes data unsuited to batch sync.

## MyHours — **thin**

Today (4): `clients`, `projects`, `tags`, `users`

Diffed against: <https://documenter.gw.postman.com/api/collections/8879268/TVmV4YYU>

- [ ] `GET /api/Logs?date=&step=` — time logs are the entire point of a time tracker — the central fact table is missing, so hours cannot be queried at all (high)
- [ ] `PUT /api/Reports/activitydx` — bulk time-log report over a date range with client/project/user filters — the practical backfill path for logs (high)
- [ ] `GET /api/Projects/{projectId}/tasklist` — project task lookup resolving the task each time log is booked against (high)
- [ ] `GET /api/Projects/{projectId}/userlist` — project-to-team-member assignment join table (medium)
- [ ] `GET /api/Teams/{teamId}/teammembers` — team membership for grouping users in reporting (medium)
- [ ] `GET /api/Projects/{projectId}/overview` — project detail including budget/rate fields not on the list response (low)
- [ ] `GET /api/Reports/dashboardOptimized` — pre-aggregated dashboard totals by client/project/user (low)

Note: Doc is a Postman collection (My Hours API v1.1); parsed the raw collection JSON from documenter.gw.postman.com. Source is static (4 tables in settings.py, no dynamic discovery) and omits the time-log endpoints entirely.

## N8n — gaps

Today (6): `executions`, `projects`, `tags`, `users`, `variables`, `workflows`

Diffed against: <https://raw.githubusercontent.com/n8n-io/n8n/master/packages/cli/src/public-api/v1/openapi.yml>

- [ ] `/insights/summary` — n8n's headline metrics (total/failed executions, run time saved) over a date range, filterable by project (high)
- [ ] `/projects/{projectId}/users` — project membership join table with roles — resolves who owns which project (medium)
- [ ] `/projects/{projectId}/folders` — folder hierarchy workflows are organized into; lookup for workflow parentFolder ids (medium)
- [ ] `/workflows/{id}/test-runs (+ /test-runs/{runId}/test-cases)` — evaluation run results per workflow — pass/fail history for AI workflow testing (medium)
- [ ] `/data-tables and /data-tables/{dataTableId}/rows` — user-defined data tables and their rows, queried as ordinary warehouse tables (medium)
- [ ] `/data-tables/{dataTableId}/columns` — column metadata needed to type the data-table rows (low)
- [ ] `/community-packages` — installed community node inventory for auditing what workflows depend on (low)

Note: Spec is served from the n8n repo (docs.n8n.io/api/v1/openapi.yml 404s). Credentials, source-control, SSO/OTel/security-policy settings and log-streaming destinations were excluded as config/secret plumbing.

## NebiusAI — gaps

Today (4): `batches`, `files`, `fine_tuning_jobs`, `models`

Diffed against: <https://docs.tokenfactory.nebius.com/llms.txt>

- [ ] `GET /v1/datasets (list datasets in project)` — datasets are the training inputs fine-tuning jobs reference; also the lookup resolving dataset ids on jobs (high)
- [ ] `GET /v1/fine_tuning/jobs/{id}/events` — per-job status and training-metric updates over time — the only way to chart loss/progress (high)
- [ ] `GET /v1/fine_tuning/jobs/{id}/checkpoints` — checkpoints produced per job with their metrics, and the ids deployed models map back to (medium)
- [ ] `GET /v1/datasets operations (list/filter operations by attributes)` — dataset operation history (uploads, conversions, fine-tuning ops) with outcomes and errors (medium)
- [ ] `GET /v1/dedicated-endpoints` — inventory of deployed dedicated inference endpoints and the models behind them (medium)

Note: Nebius Token Factory (formerly AI Studio) is OpenAI-compatible for inference; the non-OpenAI surface is datasets, fine-tuning sub-resources, dedicated endpoints and sandboxes. No usage/billing API is published in the reference, so token-spend cannot be synced. Sandbox endpoints (images, instances, subprocesses) are execution plumbing, not warehouse data.

## Netlify — gaps

Today (8): `accounts`, `builds`, `deploys`, `dns_zones`, `forms`, `members`, `sites`, `submissions`

Diffed against: <https://open-api.netlify.com/swagger.json>

- [ ] `/dns_zones/{zone_id}/dns_records` — the actual records inside the zones already synced — zones alone carry almost no queryable detail (high)
- [ ] `/accounts/{account_id}/audit` — account audit log: who deployed, changed env vars, or altered site settings and when (high)
- [ ] `/sites/{site_id}/functions` — serverless/edge function inventory per site, needed to attribute build and runtime behavior (medium)
- [ ] `/sites/{site_id}/deployed-branches` — branch-to-deploy mapping for branch-deploy and preview analysis (medium)
- [ ] `/sites/{site_id}/traffic_splits` — split test definitions and branch weights — the A/B testing objects (medium)
- [ ] `/accounts/types` — lookup resolving the plan/type id on every account row (medium)
- [ ] `/sites/{site_id}/plugin_runs/latest` — build plugin run outcomes per site, complementing build status (low)
- [ ] `/sites/{site_id}/service-instances` — installed add-on instances per site (low)
- [ ] `/sites/{site_id}/ssl/certificates` — certificate state and expiry per site (low)
- [ ] `/sites/{site_id}/files` — deployed file inventory with checksums and sizes (low)
- [ ] `/agent_runners/{agent_runner_id}/sessions` — agent runner session history for accounts using Netlify agent runners (low)

Note: Official OpenAPI 2.0 spec (open-api.netlify.com/swagger.json, ~700 KB). Hooks, build_hooks, deploy_keys, env vars, snippets and billing payment methods were excluded as config/plumbing.

## NewRelic — gaps

Today (8): `alert_conditions`, `alert_policies`, `entities`, `logs`, `page_views`, `spans`, `transaction_errors`, `transactions`

Diffed against: <https://docs.newrelic.com/attribute-dictionary/>

- [ ] `NrAiIncident` — incident open/close history for the alert conditions already synced - the state-transition table that makes alert_conditions queryable (high)
- [ ] `Metric` — New Relic's dimensional metric timeslice data, the headline data type behind every APM/infra chart (high)
- [ ] `JavaScriptError` — browser error events; the error-side counterpart to page_views, same way transaction_errors pairs with transactions (high)
- [ ] `NrAiIssue` — correlated issue grouping over incidents, needed for MTTA/MTTR analysis (medium)
- [ ] `Deployment / ChangeTrackingEvent` — deployment and change markers to correlate releases with transaction/error regressions (medium)
- [ ] `MobileSession / MobileCrash / MobileRequest` — mobile monitoring events; no mobile coverage at all today (medium)
- [ ] `SyntheticCheck / SyntheticRequest` — synthetic monitor results for uptime and SLA reporting (medium)
- [ ] `SystemSample / ProcessSample / NetworkSample / StorageSample` — infrastructure host samples; no infra coverage today despite entities syncing hosts (medium)
- [ ] `NrConsumption / NrMTDConsumption / NrDailyUsage` — ingest and usage consumption events - the standard source for New Relic cost attribution (medium)
- [ ] `ServiceLevelSnapshot` — SLI/SLO attainment snapshots for service-level reporting (medium)
- [ ] `AjaxRequest / PageViewTiming / BrowserInteraction` — browser performance breakdowns that page_views alone cannot express (low)
- [ ] `NrAuditEvent` — account audit trail of who changed what (low)

Note: Source is NRQL-over-NerdGraph: each event table is just a `nrql\_table` entry in settings.py, so every gap below is a config-only addition (`SELECT \* FROM <EventType>`). The attribute dictionary enumerates 81 queryable NRQL event types; PostHog wires up 5 of them plus 3 NerdGraph config/entity tables. Incidents/issues are the notable structural gap: alert_policies and alert_conditions are synced, but nothing records what those conditions actually fired.

## NewsApi — adequate

Today (3): `everything`, `sources`, `top_headlines`

Diffed against: <https://newsapi.org/docs/endpoints>

No material gaps found.

Note: NewsAPI v2 publishes exactly three endpoints - /v2/everything, /v2/top-headlines and /v2/top-headlines/sources. All three are already exposed. There is no further nesting or sub-resource in the API.

## NewsData — gaps

Today (4): `archive`, `crypto`, `latest`, `sources`

Diffed against: <https://newsdata.io/llms.txt>

- [ ] `/api/1/market` — stock-market and financial news with ticker-symbol filtering - a distinct corpus from latest/crypto and the obvious peer of the crypto table already synced (high)
- [ ] `/api/1/count` — pre-aggregated article counts per hour/day for a query, useful for coverage/share-of-voice trends without paging every article (low)
- [ ] `/api/1/crypto/count` — same aggregation over the crypto corpus already synced (low)
- [ ] `/api/1/market/count` — same aggregation over the market corpus (low)

Note: newsdata.io/documentation is a client-rendered SPA that returns no endpoint text to curl; the vendor publishes a machine-readable llms.txt at the domain root which enumerates all 8 endpoints. PostHog covers 4 of 8. /news is documented as a legacy alias of /latest, so it is not a gap.

## NewYorkTimes — gaps

Today (5): `article_search`, `most_popular_emailed`, `most_popular_shared`, `most_popular_viewed`, `top_stories`

Diffed against: <https://github.com/nytimes/public_api_specs>

- [ ] `archive (/svc/archive/v1/{year}/{month}.json)` — full month-by-month article metadata dump back to 1851 - the natural bulk warehouse table, versus article_search's paginated 100-page cap (high)
- [ ] `timeswire (/svc/news/v3/content.json)` — continuous feed of newly published items with updated timestamps, the incremental-friendly article stream (high)
- [ ] `books best-seller list (/svc/books/v3/lists/{date}/{list}.json)` — weekly best-seller rankings, the Books API's headline dataset (medium)
- [ ] `books list names (/svc/books/v3/lists/names.json)` — lookup table resolving the list encoded names, dates and update cadence used by every other books endpoint (medium)
- [ ] `books best-sellers history (/svc/books/v3/lists/best-sellers/history.json)` — per-title ranking history across weeks, the time series behind the lists (medium)
- [ ] `community user-content (/svc/community/v3/user-content/by-date.json)` — reader comments joined to articles - the only engagement signal in the NYT APIs (medium)
- [ ] `movie reviews (/svc/movies/v2/reviews/search.json)` — critics' reviews with pick flags, a distinct content corpus from article_search (low)
- [ ] `movie critics (/svc/movies/v2/critics/{resource-type}.json)` — lookup resolving the critic bylines attached to movie reviews (low)
- [ ] `books reviews (/svc/books/v3/reviews.json)` — NYT book reviews keyed by ISBN/title, joins onto the best-seller lists (low)
- [ ] `semantic concepts (/svc/semantic/v2/concept/search.json)` — taxonomy lookup resolving the person/subject/location tags carried on articles (low)
- [ ] `times tags (/svc/suggest/v1/timestags)` — controlled-vocabulary tag dictionary for normalizing article keywords (low)

Note: Diffed against the NYT org's own OpenAPI JSON specs (archive_api, books_api, community, movie_reviews, semantic_api, times_tags, timeswire, top_stories, most_popular). PostHog covers 3 of the 9 published APIs. Also note top_stories is pinned to path /svc/topstories/v2/home.json and most_popular to the 7-day window - section and time-period are path segments in the spec, so the current tables expose one slice of each.

## NoCRM — gaps

Today (10): `activities`, `categories`, `client_folders`, `fields`, `leads`, `pipelines`, `steps`, `tags`, `teams`, `users`

Diffed against: <https://www.nocrm.io/api>

- [ ] `leads/{lead_id}/action_histories` — per-lead action and step-change history - the state-transition table needed for pipeline velocity and conversion timing (high)
- [ ] `follow_ups` — scheduled follow-up tasks/reminders on leads, the core activity object driving rep workload analysis (high)
- [ ] `leads/{lead_id}/comments` — comment thread per lead, the narrative activity stream alongside activities (medium)
- [ ] `spreadsheets` — prospecting lists - the top-of-funnel container that leads are created from, with no equivalent table today (medium)
- [ ] `spreadsheets/{spreadsheet_id}/rows` — prospect rows inside prospecting lists, plus their conversion-to-lead linkage (medium)
- [ ] `follow_ups/{follow_up_id}/tasks` — individual tasks within a follow-up sequence, the completion-level detail (medium)
- [ ] `spreadsheets/{spreadsheet_id}/comments` — comments on prospecting lists and rows, engagement history before a lead exists (low)
- [ ] `leads/{lead_id}/attachments` — attachment metadata per lead (counts/types, not file bytes) (low)

Note: The API reference is a single large HTML page; extracted all /api/v2/\* paths from it. Core CRM objects are covered (leads, activities, steps, pipelines, users, teams, clients->client_folders, predefined_tags->tags, categories, fields). The gaps are all lead sub-resources and the prospecting-list side of the product.

## Northflank — gaps

Today (5): `addons`, `jobs`, `projects`, `services`, `volumes`

Diffed against: <https://northflank.com/docs/sitemap.xml>

- [ ] `GET /v1/projects/{projectId}/services/{serviceId}/build` — build history per service (status, branch, sha, timings) - deployment frequency and build-failure analysis (high)
- [ ] `GET /v1/projects/{projectId}/jobs/{jobId}/runs` — job run history with success/failure and durations; the jobs table alone has no execution record (high)
- [ ] `GET /v1/billing/usage` — hourly resource usage entries - the basis for cost attribution per project/service (high)
- [ ] `GET /v1/plans` — lookup table resolving the plan ids carried on every service, job, addon and volume already synced (vCPU, RAM, hourly cost) (high)
- [ ] `GET /v1/projects/{projectId}/jobs/{jobId}/build` — build history for jobs, the job-side counterpart to service builds (medium)
- [ ] `GET /v1/projects/{projectId}/workflows/{workflowId}/runs` — workflow execution history, the release automation audit trail (medium)
- [ ] `GET /v1/projects/{projectId}/pipelines` — pipeline definitions that services and release flows belong to - the missing grouping dimension (medium)
- [ ] `GET /v1/projects/{projectId}/pipelines/{pipelineId}/release-flows/{id}/runs` — release flow run history: what shipped, when, and whether it succeeded (medium)
- [ ] `GET /v1/projects/{projectId}/preview-environments` — preview environment inventory and lifetimes, a major driver of ephemeral spend (medium)
- [ ] `GET /v1/tags` — lookup table resolving the tag ids attached to projects, services and addons (medium)
- [ ] `GET /v1/clusters and /v1/clusters/{id}/nodes` — BYOC cluster and node inventory - the infrastructure dimension services are scheduled onto (medium)
- [ ] `GET /v1/projects/{projectId}/services/{serviceId}/containers` — running container instances per service, the replica-level detail behind service state (low)

Note: Northflank publishes no OpenAPI document (api.northflank.com/v1/openapi.json 404s); enumerated the ~170 API reference pages from the docs sitemap and spot-verified the actual HTTP paths on list-service-builds, get-job-runs, list-plans and list-usage. PostHog syncs the five top-level resource inventories but none of the run/build/usage history that makes them analytically useful.

## NorthpassLMS — gaps

Today (8): `categories`, `course_enrollments`, `courses`, `groups`, `learning_path_enrollments`, `learning_paths`, `people`, `quizzes`

Diffed against: <https://developers.northpass.com/reference/get_v2-courses>

- [ ] `GET /v2/events` — the learner activity event stream (lesson views, completions, logins) - the fact table behind every engagement metric (high)
- [ ] `GET /v2/groups/{group_uuid}/memberships` — the people-to-groups join table; groups and people are both synced but nothing links them (high)
- [ ] `GET /v2/credentials/{credential_uuid}/achievements` — certificates/credentials actually earned by learners - the completion outcome enrollments only hint at (high)
- [ ] `GET /v2/submissions and /v2/assignments/{assignment_uuid}/submissions` — learner assignment submissions with grades/status, the assessment counterpart to quizzes (high)
- [ ] `GET /v2/courses/{course_uuid}/activities` — the lesson/activity structure inside a course - required to break enrollment progress down below course level (high)
- [ ] `GET /v2/credentials` — lookup table resolving the credential definitions that achievements reference (medium)
- [ ] `GET /v2/assignments` — assignment definitions, the lookup that submissions join back to (medium)
- [ ] `GET /v2/transcripts/{learner_id}` — per-learner transcript rolling up all course and learning-path completions (medium)
- [ ] `GET /v2/groups/{group_uuid}/courses` — course assignments per group - which cohorts were given which curriculum (medium)
- [ ] `GET /v2/communications/deliveries` — email delivery records for course invitations and reminders, for nudge-effectiveness analysis (medium)
- [ ] `GET /v2/properties/people and /v2/properties/courses` — custom properties on people and courses plus /v2/properties/property-definitions as the schema lookup - the segmentation dimensions customers configure (medium)
- [ ] `GET /v2/quiz-attempts/{quiz_attempt_uuid}/answers and /v2/question-banks` — per-question answer detail and the question bank lookup; quizzes are synced but nothing about how learners answered (low)

Note: Enumerated every /reference/get_v2-\* route from the ReadMe-hosted reference page (no public OpenAPI file is served). PostHog covers the 6 core objects plus 2 enrollment fan-outs; the learner-activity and assessment halves of the API are entirely absent.

## NpmRegistry — gaps

Today (2): `Downloads`, `Versions`

Diffed against: <https://raw.githubusercontent.com/npm/registry/master/docs/REGISTRY-API.md>

- [ ] `GET https://api.npmjs.org/versions/{package}/last-week` — per-version download counts - joins straight onto the Versions table already synced and is the only way to measure version adoption or upgrade lag (high)
- [ ] `GET /-/v1/search` — search results carry npms.io quality, popularity and maintenance scores per package, unavailable from the packument (medium)
- [ ] `GET https://api.npmjs.org/downloads/point/{period}/{pkg1},{pkg2}` — bulk point downloads for up to 128 packages in one call - same data as Downloads but far cheaper for large package lists (low)
- [ ] `GET / (registry meta)` — registry-wide doc_count and update_seq, useful only as a sync watermark (low)

Note: Also diffed against https://raw.githubusercontent.com/npm/registry/master/docs/download-counts.md. The public registry API is genuinely small (packument, version doc, search, meta) plus the downloads service (point, range, per-version). PostHog's Versions table comes from the packument and Downloads from /downloads/range, so 2 of roughly 4 useful data shapes are covered. Tables are static per source; the user supplies the package list, so breadth here is packages, not endpoints.

## Nuget — gaps

Today (3): `catalog_events`, `package_versions`, `packages`

Diffed against: <https://api.nuget.org/v3/index.json>

- [ ] `VulnerabilityInfo/6.7.0 (https://api.nuget.org/v3/vulnerabilities/index.json → vulnerability.base.json + vulnerability.update.json)` — Lookup keyed by the exact package IDs we already sync: advisory URL, severity, and affected version range — turns packages/package_versions into a security posture table (high)
- [ ] `catalogEntry.dependencyGroups (registration leaf / catalog leaf child object)` — Per-version dependency graph (target framework + dependency id/range) already present in the leaves we fetch, but never flattened into a queryable table (medium)
- [ ] `SearchQueryService/3.5.0 (query by owner/tag, not just tracked ids)` — Lets a user sync every package for an owner or tag instead of hand-listing package ids, and exposes verified/prefix-reserved and total download counts across a portfolio (low)

Note: Source is package-id-scoped: the user configures a list of package ids and packages/package_versions are built from search + registration. NuGet v3's remaining service-index resources (Autocomplete, RepositorySignatures, PackagePublish, SymbolPackagePublish, ReportAbuse, PackageBaseAddress) are plumbing or write paths and correctly excluded.

## OctopusDeploy — gaps

Today (11): `channels`, `deployments`, `environments`, `events`, `machines`, `project_groups`, `projects`, `releases`, `spaces`, `tasks`, `tenants`

Diffed against: <https://demo.octopus.app/api>

- [ ] `users (/api/users)` — Lookup that resolves the user ids already carried on events, deployments, tasks and interruptions (high)
- [ ] `teams + teammembership (/api/teams, /api/teammembership)` — Team definitions and the user→team junction — the only way to aggregate deployment activity by team (high)
- [ ] `lifecycles (/api/{space}/lifecycles)` — Lookup resolving the LifecycleId on projects/releases into ordered phases and environments, needed to judge whether a deployment progressed normally (high)
- [ ] `interruptions (/api/{space}/interruptions)` — Manual intervention and approval records with responsible-team and resolution timestamps — the wait time inside deployment lead time (high)
- [ ] `insights/reports (/api/{space}/insights/reports)` — Octopus's own DORA-style reporting objects (deployment frequency, lead time, failure rate) — the vendor's headline metric (high)
- [ ] `runbookRuns (/api/{space}/runbookRuns)` — Operational run history that sits alongside deployments; without it half of what Octopus executes is invisible (medium)
- [ ] `runbooks (/api/{space}/runbooks)` — Lookup resolving the RunbookId on runbook runs and project triggers (medium)
- [ ] `build-information (/api/{space}/build-information)` — Commits, work items and build URLs attached to packages — the join from a deployment back to source control (medium)
- [ ] `packages (/api/{space}/packages)` — Package versions consumed by releases, the other half of release-to-artifact traceability (medium)
- [ ] `artifacts (/api/{space}/artifacts)` — Files produced by deployments/tasks, joinable to the task that generated them (medium)
- [ ] `workers + workerpools (/api/{space}/workers, /api/{space}/workerpools)` — We sync machines (deployment targets) but not the worker fleet that actually executes steps, so execution capacity analysis is impossible (medium)
- [ ] `deploymentprocesses (/api/{space}/deploymentprocesses)` — Step-level definition per project, needed to break deployment duration down by step (low)

Note: Diffed against the live self-describing API root on the public demo instance, which enumerates every resource link (space-scoped links are templated as /api/Spaces-1/...). Excluded as config/plumbing: subscriptions (webhooks), gitcredentials, certificates, signingkeys, accounts, feeds, proxies, smtp/telemetry/maintenance/performance configuration, migrations and import/export. Event lookup tables (events/categories, events/groups, events/agents, events/documenttypes) exist and would enrich the events table, but are low value on their own.

## Okta — gaps

Today (6): `applications`, `group_rules`, `groups`, `logs`, `user_types`, `users`

Diffed against: <https://raw.githubusercontent.com/okta/okta-management-openapi-spec/master/dist/2026.07.2/management-minimal.yaml>

- [ ] `groups/{groupId}/users` — The user↔group membership junction; without it the groups and users tables cannot be joined at all (high)
- [ ] `apps/{appId}/users` — Application assignment per user (with scope, status and credentials profile) — the core access-review question (high)
- [ ] `apps/{appId}/groups` — Group-based application assignment, the other half of how access is actually granted (high)
- [ ] `users/{userId}/factors and users/{userId}/authenticator-enrollments` — Enrolled MFA factors per user — the standard security-posture report over an Okta sync (high)
- [ ] `policies and policies/{policyId}/rules` — Sign-on, password and authenticator policies plus their rules; explains why the logs table shows the auth outcomes it does (medium)
- [ ] `devices and devices/{deviceId}/users` — Managed device inventory plus the device↔user junction, needed for device-trust and BYOD analysis (medium)
- [ ] `iam/roles, users/{userId}/roles, groups/{groupId}/roles` — Standard and custom admin-role assignments — privileged-access reporting over users and groups we already sync (medium)
- [ ] `idps and idps/{idpId}/users` — Identity providers plus the linked external identities, resolving federated logins seen in logs (medium)
- [ ] `authenticators (and /methods)` — Lookup that resolves factor/authenticator type ids appearing in enrollments and policy rules (medium)
- [ ] `authorizationServers with /scopes, /claims and /policies` — Custom auth servers and their scopes/claims, needed to interpret OAuth token events in logs (medium)
- [ ] `users/{userId}/grants and apps/{appId}/grants` — OAuth consent grants per user and per app — who has consented to which scopes (medium)
- [ ] `zones (network zones)` — Lookup resolving zone ids referenced by policy rules and by IP conditions in the system log (low)

Note: Diffed against Okta's published management OpenAPI (485 paths). Deliberately excluded as config/plumbing: eventHooks, inlineHooks, logStreams, hook-keys, api-tokens, trustedOrigins, brands/themes/email templates, domains, email-domains/servers, captchas, push/telephony providers, rate-limit settings, features, and the credential/CSR/key sub-resources under apps and idps.

## Omni — gaps

Today (6): `Connections`, `Documents`, `Folders`, `Schedules`, `UserGroups`, `Users`

Diffed against: <https://docs.omni.co/sitemap.xml>

- [ ] `models (GET /api/v1/models — list-models, list-model-schemas)` — Lookup resolving the model id carried by documents, queries and schedules; nothing in the current tables identifies which data model content sits on (high)
- [ ] `schedule-recipients (list-schedule-recipients)` — Junction between the Schedules table we already sync and the users/groups actually receiving each delivery (high)
- [ ] `document-permissions (get-document-permissions, all-users-and-groups-with-document-access)` — Who can see which dashboard — the access-audit join across Documents, Users and UserGroups (high)
- [ ] `ai conversations (list-ai-conversations, get-conversation)` — AI query usage per user, the closest thing Omni's API offers to consumption analytics (medium)
- [ ] `labels (list-labels)` — Lookup for the labels applied to documents; without it label ids on content are unresolvable (medium)
- [ ] `user-model-roles and user-group-model-roles (retrieve endpoints)` — Per-model permission grants for users and groups — governance reporting over models (medium)
- [ ] `user-attributes (list-user-attributes)` — Lookup for the attribute keys used in row-level access controls referenced on users (medium)
- [ ] `folder-permissions (get-folder-permissions)` — Folder-level access grants, the inherited layer above document permissions on the Folders table we sync (medium)
- [ ] `document-favorites (list-document-favoriters)` — Per-document favorite counts and favoriters — an engagement signal on content (medium)
- [ ] `embed users and email-only users (list-embed-users, list-email-only-users)` — Two user populations excluded from the main Users table, so seat and delivery counts are understated (medium)
- [ ] `document drafts (list-document-drafts)` — Unpublished drafts per document, useful for content lifecycle and staleness analysis (low)
- [ ] `dbt environments and exposures (list-dbt-environments, get-dbt-exposures)` — Links Omni content to upstream dbt models for lineage (low)

Note: Diffed against every https://docs.omni.co/api/\* page in the docs sitemap (the site has no public OpenAPI JSON — /api/openapi.json 404s). Excluded as config/plumbing: api-tokens, connection-environments, model-git-configuration, content-migration import/export, uploads, images, jobs, schema-refresh-schedules, ai-credit-controls.

## Omnisend — gaps

Today (6): `campaigns`, `carts`, `categories`, `contacts`, `orders`, `products`

Diffed against: <https://api-docs.omnisend.com/llms.txt>

- [ ] `POST /analytics/statistics (Statistics)` — Aggregated delivery, engagement, revenue-attribution and audience-growth metrics grouped by event date — the vendor's headline marketing numbers, absent entirely today (high)
- [ ] `POST /analytics/reports (Reports)` — Same metric family grouped by send date with campaign/automation dimensions, so campaigns can be ranked by performance rather than just listed (high)
- [ ] `GET /segments and GET /segments/{segmentID}/statistics` — Segment definitions plus member counts — the lookup that resolves the segment ids automations and campaigns target (high)
- [ ] `GET /automations (list automation workflows)` — Automated flows are the other half of Omnisend sending volume; only one-off campaigns are synced today (high)
- [ ] `GET /brands/current` — Single-row account/brand context (currency, store connection) that makes revenue figures interpretable (low)

Note: The connector targets v3 (https://api.omnisend.com/v3). The gaps above are on the current 2026-03-15 version (header-based versioning, base https://api.omnisend.com/api/), which added Segments, Automations, Analytics, Email Templates and Images — so closing them means reaching into a newer API version, not just adding v3 paths. Events are write-only (POST /events), so there is no queryable event stream. Email templates, universal layouts, images and batches were excluded as assets/plumbing.

## Oncehub — gaps

Today (5): `booking_calendars`, `bookings`, `contacts`, `teams`, `users`

Diffed against: <https://developers.oncehub.com/booking-calendars-api.yaml>

- [ ] `GET /v2/event-types (Booking Pages API)` — Lookup resolving the meeting type referenced by bookings — duration, location and conferencing per meeting, the natural breakdown dimension for booking volume (high)
- [ ] `GET /v2/booking-pages (Booking Pages API)` — The classic-product equivalent of booking_calendars; accounts still on Booking Pages have bookings whose parent object is unresolvable today (high)
- [ ] `GET /v2/master-pages (Booking Pages API)` — Groups booking pages into a single scheduling entry point — the rollup level teams actually report on (medium)
- [ ] `GET /v2/users/{id}/scheduling-availability` — Per-user availability windows, the denominator for booked-hours-versus-available-hours utilization (low)

Note: OnceHub publishes two parallel OpenAPI specs against the same /v2 base: booking-calendars-api.yaml (synced today) and booking-pages-api.yaml (the classic surface, https://developers.oncehub.com/booking-pages-api.yaml) — the latter is where event-types, booking-pages and master-pages live, and both share /bookings, /users, /teams and /contacts. Excluded: /webhooks, /notifications/sms, /one-time-links (ephemeral), /booking-calendars/{id}/time-slots (live availability query, not a warehouse table), and the write-only lifecycle actions (cancel, reassign, no-show, request-reschedule).

## Onepagecrm — gaps

Today (10): `actions`, `calls`, `companies`, `contacts`, `deals`, `lead_sources`, `meetings`, `notes`, `statuses`, `users`

Diffed against: <https://developer.onepagecrm.com/api/reference/>

- [ ] `pipelines` — lookup that resolves the pipeline/stage IDs carried on the deals we already sync (high)
- [ ] `call_results` — lookup resolving the call outcome IDs on synced calls (high)
- [ ] `custom_fields` — field definitions needed to interpret custom field IDs on synced contacts (high)
- [ ] `deal_fields` — definitions for custom deal fields, needed to name deal custom values (medium)
- [ ] `company_fields` — definitions for custom company fields (medium)
- [ ] `action_stream` — chronological activity/state-change feed across records (medium)
- [ ] `team_stream` — team-wide activity history for rep productivity analysis (medium)
- [ ] `contacts/{contact_id}/relationships` — contact-to-contact relationship graph (medium)
- [ ] `relationship_types` — lookup resolving relationship type IDs (medium)
- [ ] `filters` — saved contact filter definitions used to segment the book of business (low)
- [ ] `countries` — country code lookup for contact/company addresses (low)
- [ ] `notifications` — notification history per user (low)

Note: Full resource list read from the docs navigation on the reference index; attachments, webhooks, bootstrap and predefined\_\* were excluded as plumbing/config.

## OnePassword — adequate

Today (3): `audit_events`, `item_usages`, `sign_in_attempts`

Diffed against: <https://i.1password.com/media/1password-events-reporting/1password-events-api_1.4.1.yaml>

No material gaps found.

Note: The Events API OpenAPI (v1.4.1) defines exactly three data endpoints — /api/v2/signinattempts, /api/v2/itemusages, /api/v2/auditevents (plus deprecated v1 twins of the same three) — and /api/v2/auth/introspect, which is a token-scope probe rather than data. All three are synced, so coverage is complete for this API. 1Password's other surfaces (SCIM Bridge for users/groups/vaults, Connect server for items/vaults, Service Accounts) are separate self-hosted deployments with their own credentials, not reachable with the Events API bearer token this source takes, so they are not a gap in this connector.

## Onfleet — gaps

Today (7): `administrators`, `hubs`, `organization`, `tasks`, `teams`, `webhooks`, `workers`

Diffed against: <https://docs.onfleet.com/reference/administrators>

- [ ] `routePlans` — route plans group tasks into driver routes - core delivery-efficiency object (high)
- [ ] `taskOrders (orders)` — order-level records that tasks are created from, with pricing/quote state (medium)
- [ ] `destinations` — lookup resolving the destination IDs referenced by synced tasks (address/geo dimension) (medium)
- [ ] `recipients` — lookup resolving recipient IDs on synced tasks (customer dimension) (medium)
- [ ] `cfGroups/task (task templates)` — lookup for task custom-field template IDs on synced tasks (medium)
- [ ] `workers/{id} schedule` — worker shift schedules, needed to compute utilization against completed tasks (medium)
- [ ] `containers/{entity}/{id}` — ordered task queues per worker/team/org - gives task sequencing state (low)

Note: Onfleet has no bulk list endpoints for recipients or destinations (only get-by-id/find), so those would need to be materialized from the task payloads, similar to how this source's peers materialize embedded sub-objects.

## OpenAI — gaps

Today (20): `admin_api_keys`, `audit_logs`, `costs`, `invites`, `project_api_keys`, `project_rate_limits`, `project_service_accounts`, `project_users`, `projects`, `usage_audio_speeches`, `usage_audio_transcriptions`, `usage_code_interpreter_sessions`, `usage_completions`, `usage_embeddings`, `usage_file_search_calls`, `usage_images`, `usage_moderations`, `usage_vector_stores`, `usage_web_search_calls`, `users`

Diffed against: <https://raw.githubusercontent.com/openai/openai-openapi/master/openapi.yaml>

- [ ] `/models` — lookup resolving the model IDs that appear in every usage\_\* and costs row (high)
- [ ] `/chat/completions (list stored completions)` — per-request log with model, tokens and metadata - the finest-grained usage fact table available (high)
- [ ] `/organization/groups and /organization/groups/{id}/users` — group membership table resolving which users belong to which group (high)
- [ ] `/organization/roles and /organization/users/{id}/roles` — role assignments for the users we already sync (medium)
- [ ] `/organization/projects/{id}/groups` — project-to-group membership, complements the project_users table we sync (medium)
- [ ] `/batches` — batch job records with request counts and completion status (medium)
- [ ] `/fine_tuning/jobs (+ /events, /checkpoints)` — training job history, cost and status over time (medium)
- [ ] `/evals, /evals/{id}/runs, /evals/{id}/runs/{id}/output_items` — eval run results - the analytical object for model quality tracking (medium)
- [ ] `/chat/completions/{id}/messages` — message-level detail behind each stored completion (low)
- [ ] `/vector_stores` — lookup resolving the vector store IDs in usage_vector_stores (low)

Note: Current coverage is exactly the Administration + Usage API surface and is complete there (only certificates, data_retention, spend_alerts/spend_limit and permission endpoints are missing, all config). The gaps listed come from the platform API, which this source does not touch at all.

## OpenAIAds — gaps

Today (7): `ad_account_insights`, `ad_group_insights`, `ad_groups`, `ad_insights`, `ads`, `campaign_insights`, `campaigns`

Diffed against: <https://developers.openai.com/ads/llms.txt>

- [ ] `GET /ad_account` — account metadata lookup - we sync ad_account_insights but not the account entity itself (medium)
- [ ] `insights with segments[]=country` — geographic breakdown dimension on the insights endpoints we already sync (medium)
- [ ] `insights with segments[]=device` — device breakdown dimension on existing insights endpoints (medium)
- [ ] `insights with segments[]=product` — product-feed breakdown, the only way to attribute spend to catalog items (medium)

Note: The Ads API is small - ad_account, campaigns, ad_groups, ads, insights, plus conversion setup and file upload (both excluded as config/plumbing). Coverage of the entity and insight levels is otherwise complete; the remaining value is in the segments[] breakdowns.

## OpenAQ — gaps

Today (12): `countries`, `instruments`, `licenses`, `locations`, `manufacturers`, `measurements`, `measurements_daily`, `measurements_hourly`, `owners`, `parameters`, `providers`, `sensors`

Diffed against: <https://api.openaq.org/openapi.json>

- [ ] `/v3/locations/{id}/latest` — most recent value per location - the headline 'current air quality' read (high)
- [ ] `/v3/sensors/{id}/flags` — data-quality flags needed to exclude bad readings from measurement aggregates (medium)
- [ ] `/v3/locations/{id}/flags` — location-level data-quality flags for the same filtering (medium)
- [ ] `/v3/parameters/{id}/latest` — latest reading per pollutant across the network (medium)
- [ ] `/v3/sensors/{id}/years` — yearly rollups, cheaper than aggregating hourly data for long-range trends (medium)
- [ ] `/v3/manufacturers/{id}/instruments` — join table linking manufacturers to instruments we already sync (low)
- [ ] `/v3/sensors/{id}/hours/hourofday and /days/dayofweek, /days/monthofyear` — seasonal/diurnal aggregations the API precomputes (low)

Note: measurements_hourly maps to /sensors/{id}/hours and measurements_daily to /sensors/{id}/days, so the main time grains are covered; sensors are already materialized from each location's embedded sensor list.

## OpenExchangeRates — gaps

Today (4): `currencies`, `historical`, `latest`, `usage`

Diffed against: <https://docs.openexchangerates.org/reference/api-introduction>

- [ ] `time-series.json` — pulls a whole date range in one call instead of day-by-day historical requests (high)
- [ ] `ohlc.json` — open/high/low/close/average per period - the vendor's analytical rate summary (medium)

Note: Small API. Remaining endpoints are convert (a single-value calculator, not a table), plus bid-ask and alternative-currencies which are request options on latest/historical rather than separate resources.

## OpenFDA — gaps

Today (9): `device_510k`, `device_enforcement`, `device_events`, `drug_enforcement`, `drug_events`, `drug_labels`, `drug_ndc`, `food_enforcement`, `food_events`

Diffed against: <https://api.fda.gov/download.json>

- [ ] `device/classification` — lookup resolving device product codes, classes and regulation numbers referenced by 510k, UDI and device events (high)
- [ ] `drug/drugsfda` — drug approvals and applications - the core regulatory fact table, absent entirely (high)
- [ ] `device/udi` — device identifier registry, the lookup that resolves devices named in adverse events and recalls (high)
- [ ] `drug/shortages` — current and resolved drug shortage records, a headline supply-chain signal (medium)
- [ ] `device/recall` — recall records distinct from the enforcement reports already synced (medium)
- [ ] `device/pma` — premarket approval submissions, the higher-risk counterpart to 510k (medium)
- [ ] `device/registrationlisting` — establishment registrations, the manufacturer lookup behind device records (medium)
- [ ] `drug/orangebook` — patent and exclusivity data joined to approved drug products (medium)
- [ ] `other/unii` — substance identifier lookup that resolves ingredient codes in drug labels and NDC (medium)
- [ ] `animalandveterinary/event` — veterinary adverse events, same shape as the drug/food event tables already synced (medium)
- [ ] `cosmetic/event` — cosmetic adverse events, completes the adverse-event family (low)
- [ ] `other/nsde` — structured product labeling index used to join labels to marketing status (low)

Note: Endpoint inventory taken from api.fda.gov/download.json, which enumerates every openFDA category and endpoint. Excluded from the list: tobacco/\*, transparency/crl, other/historicaldocument, other/substance and device/covid19serology as niche or archival.

## OpenRouter — gaps

Today (7): `activity`, `api_keys`, `credits`, `models`, `organization_members`, `providers`, `workspaces`

Diffed against: <https://openrouter.ai/docs/llms.txt>

- [ ] `model endpoints (list all endpoints for a model)` — per-provider pricing, context length and availability - the lookup that joins the models and providers tables we already sync (high)
- [ ] `/api/v1/analytics/query (+ /analytics/meta)` — metric/dimension query over usage - richer breakdowns than the 30-day activity rollup we sync (high)
- [ ] `workspace members` — membership table linking the workspaces and organization_members we already sync (high)
- [ ] `benchmarks` — model benchmark scores, a lookup for model quality comparison (medium)
- [ ] `task classifications (market share)` — per-task-category model market share, a breakdown dimension for usage analysis (medium)
- [ ] `app rankings (top apps by token usage)` — token usage leaderboard by app (medium)
- [ ] `daily rankings (daily token totals for top 50 models)` — daily model-level token time series (medium)
- [ ] `workspace budgets` — per-workspace spend limits, needed to compare spend against budget (low)

Note: No public OpenAPI JSON is reachable (openrouter.ai/docs/openapi.json 404s); the operation inventory was read from the official Go SDK reference pages linked from llms.txt. Generations endpoints were excluded because they require a known generation ID and cannot be bulk-listed. Guardrails, presets, BYOK, files and observability destinations excluded as config.

## OpenWeather — gaps

Today (4): `air_pollution`, `air_pollution_forecast`, `current_weather`, `forecast`

Diffed against: <https://openweathermap.org/api>

- [ ] `/data/2.5/air_pollution/history` — historical air quality back to Nov 2020 — the only way to trend AQI; today only current + forecast are synced (high)
- [ ] `Geocoding API (/geo/1.0/direct, /geo/1.0/reverse, /geo/1.0/zip)` — lookup table resolving city/state/country/ZIP to the lat/lon that every synced row is keyed on (high)
- [ ] `One Call API 3.0/4.0 (/data/3.0/onecall)` — unified current + minutely + hourly + daily + government weather alerts in one row set; the vendor's headline product (high)
- [ ] `Weather History API (/data/3.0/onecall/timemachine, /data/2.5/history/city)` — hourly historical observations — required for any backward-looking weather correlation (high)
- [ ] `One Call day summary (/data/3.0/onecall/day_summary)` — pre-aggregated daily weather rollup, the natural grain for joining against daily business metrics (medium)
- [ ] `Daily Forecast 16 days (/data/2.5/forecast/daily)` — extends forecast horizon past the 5-day/3-hour table already synced (medium)
- [ ] `Hourly Forecast 4 days (/data/2.5/forecast/hourly)` — finer-grained forecast than the 3-hour table (medium)
- [ ] `Climatic Forecast 30 days (/data/2.5/forecast/climate)` — long-range daily forecast for planning models (medium)
- [ ] `Statistical Weather API (/data/2.5/aggregated/*)` — climatological normals per day/month — the baseline dimension for anomaly analysis (low)
- [ ] `Accumulated Parameters (/data/2.5/aggregated/temperature, /precipitation)` — accumulated degree-days and rainfall, standard agricultural/energy analytical measures (low)
- [ ] `Solar Irradiance API (/energy/1.0/solar/data)` — GHI/DNI/DHI time series for energy-generation analysis (low)
- [ ] `Fire Weather Index API (/data/2.5/fwi)` — current + 5-day fire index per location (low)

Note: Source is location-fan-out: settings.py iterates user-configured lat/lon per endpoint and keys rows on (lat, lon, dt). Weather map tile endpoints and bulk file downloads were excluded as non-tabular.

## OpinionStage — gaps

Today (1): `items`

Diffed against: <https://api.opinionstage.com/api-docs/api/v2/openapi.yaml>

- [ ] `/api/v2/items/{itemId}/responses` — the actual respondent-level answer data — the entire point of the Public Result API; today only the widget list is synced (high)
- [ ] `/api/v2/items/{itemId}/questions` — lookup table resolving the question IDs carried on response rows (high)

Note: The vendor OpenAPI spec (title 'Public Result API') defines exactly 5 operations: list items, get item, list responses, get response, list questions. PostHog implements only list items. products/warehouse_sources/backend/temporal/data_imports/sources/opinion_stage/settings.py explicitly defers responses and questions as 'fan-out (they require an item id) and are intentionally excluded from v1' — so the gap is known and deliberate, but it is the whole analytical payload.

## Opsgenie — gaps

Today (8): `alerts`, `escalations`, `incidents`, `integrations`, `schedules`, `services`, `teams`, `users`

Diffed against: <https://docs.opsgenie.com/docs/api-overview>

- [ ] `GET /v2/alerts/{identifier}/logs` — per-alert state transition history (created, acked, escalated, closed) — the basis of MTTA/MTTR (high)
- [ ] `Team member API (GET /v2/teams/{id}/members)` — membership table joining the users and teams already synced (high)
- [ ] `Schedule rotation API (GET /v2/schedules/{id}/rotations)` — lookup resolving the rotation structure behind each synced schedule; without it schedules are opaque (high)
- [ ] `Who is on call API (GET /v2/schedules/{id}/on-calls, /v2/schedules/on-calls)` — resolves schedule + rotation into the actual on-call person, the headline operational fact (high)
- [ ] `Incident timeline API (GET /v1/incidents/{id}/timeline)` — state/transition history for the incidents table already synced (high)
- [ ] `GET /v2/alerts/{identifier}/notes` — responder commentary attached to alerts, needed for incident review analysis (medium)
- [ ] `GET /v2/alerts/{identifier}/recipients` — who was notified per alert and in what state — notification-reach analysis (medium)
- [ ] `Schedule override API (GET /v2/schedules/{id}/overrides)` — explains gaps between rotation and actual on-call coverage (medium)
- [ ] `Postmortem API (GET /v1/incidents/{id}/postmortems)` — post-incident write-ups joined to synced incidents (medium)
- [ ] `Heartbeat API (GET /v2/heartbeats)` — monitoring heartbeat state, a distinct alerting signal from alerts (medium)
- [ ] `Logs API (GET /v2/logs/list/{marker})` — account-level audit/activity log for configuration and alert changes over time (medium)
- [ ] `Maintenance API (GET /v1/maintenance)` — maintenance windows that suppress alerts — needed to exclude planned downtime (low)

Note: Alert sub-resource paths confirmed against the vendor SDK reference at https://raw.githubusercontent.com/opsgenie/opsgenie-python-sdk/master/README.md. Notification-rule, policy, forwarding-rule, integration-action, service-incident-template and custom-role endpoints were excluded as configuration.

## Optimizely — gaps

Today (6): `audiences`, `campaigns`, `events`, `experiments`, `pages`, `projects`

Diffed against: <https://api.optimizely.com/v2/swagger.json>

- [ ] `GET /experiments/{experiment_id}/results` — the experiment results payload (variation conversions, lift, significance) — the product's headline metric, entirely absent today (high)
- [ ] `GET /experiments/{experiment_id}/timeseries` — day-by-day results series, required to plot experiment progression rather than a single snapshot (high)
- [ ] `GET /campaigns/{campaign_id}/results` — same headline metric for the campaigns table already synced (high)
- [ ] `GET /attributes` — lookup resolving the visitor attribute IDs referenced by synced audiences and experiment targeting (high)
- [ ] `GET /environments` — lookup resolving the environment IDs carried on experiments and features (medium)
- [ ] `GET /features` — feature (flag) definitions are a first-class experimentation object here, not vendor plumbing — needed to join rollout results (medium)
- [ ] `GET /changes` — change history across experiments and pages — audit/transition table for who changed what and when (medium)
- [ ] `GET /groups` — mutually-exclusive experiment groups; lookup that explains traffic allocation across synced experiments (medium)
- [ ] `GET /experiments/{experiment_id}/sections` — multivariate section/variation breakdown dimension for experiment rows (low)
- [ ] `GET /list_attributes` — list-attribute definitions used in audience conditions (low)

Note: Spec fetched from the live host (api.optimizely.com/v2/swagger.json); the library.optimizely.com doc URLs in the payload now return S3 AccessDenied. Excluded: /extensions, /webhooks, /plan, /billing/usage, /export/credentials, /subject-access-requests, /custom_fields as config or plumbing.

## OPUSWatch — could not verify

Today (12): `client`, `labels`, `locations`, `registrations`, `rows`, `sessions`, `task_groups`, `tasks`, `users`, `varieties`, `worker_groups`, `workers`

No reachable API reference found during the sweep. Needs a manual pass.

Note: No public API reference found. https://api.opuswatch.nl/ext/ returns 401 on every probe (including swagger.json/openapi.json/docs), docs.opuswatch.nl does not resolve, and opuswatch.nl has no developer/API section. Search only surfaced unrelated 'Opus' products plus a third-party MCP listing derived from this same connector. The 12 tables map 1:1 to the paths in settings.py (master/client, master/locations, master/rows, master/users, master/workers, master/workergroups, master/tasks, master/taskgroups, master/labels, master/varieties, transactional/registrations, transactional/sessions), so coverage looks deliberate, but it cannot be diffed against a vendor spec without credentials.

## Orb — gaps

Today (7): `Coupons`, `CreditNotes`, `Customers`, `Invoices`, `Items`, `Plans`, `Subscriptions`

Diffed against: <https://raw.githubusercontent.com/orbcorp/orb-node/main/api.md>

- [ ] `GET /prices` — lookup resolving the price IDs carried on every synced plan, subscription and invoice line item (high)
- [ ] `GET /metrics (billable metrics)` — lookup resolving the billable-metric IDs that prices reference; without it usage-based charges are unexplainable (high)
- [ ] `GET /customers/{customer_id}/credits/ledger` — credit grant/decrement transaction log — the ledger a warehouse user needs for prepaid-balance analysis (high)
- [ ] `GET /customers/{customer_id}/balance_transactions` — customer account balance movements over time, joined to synced customers and invoices (high)
- [ ] `GET /customers/{customer_id}/costs` — per-customer cost breakdown by price/metric over a timeframe — Orb's headline revenue metric (high)
- [ ] `GET /subscriptions/{subscription_id}/usage` — usage quantities per billable metric per subscription, the raw driver of every invoice line (medium)
- [ ] `GET /subscription_changes` — state-transition history for the subscriptions table already synced (upgrades, downgrades, cancellations) (medium)
- [ ] `GET /subscriptions/{subscription_id}/schedule` — plan-over-time schedule per subscription — resolves which plan applied in which period (medium)
- [ ] `GET /customers/{customer_id}/credits` — outstanding credit block balances per customer (medium)
- [ ] `GET /subscriptions/{subscription_id}/costs` — cost breakdown at subscription grain, complementing the customer-level view (medium)
- [ ] `GET /events/volume` — ingested event volume over time — useful for reconciling usage against billing (low)
- [ ] `GET /dimensional_price_groups` — lookup for dimensional pricing groups referenced by prices (low)

Note: Diffed against the official Orb SDK API surface (orbcorp/orb-node api.md), which enumerates every REST path. Alerts, webhooks and backfill endpoints excluded as config/plumbing.

## OrcaSecurity — could not verify

Today (4): `alerts`, `assets`, `cloud_accounts`, `vulnerabilities`

Diffed against: <https://docs.orcasecurity.io/reference>

No reachable API reference found during the sweep. Needs a manual pass.

Note: Orca's API reference is auth-gated. docs.orcasecurity.io returns the same 598-byte SPA shell for every path (including /assets/\*.js, /reference, /docs/alerts, sitemap.xml, llms.txt) with and without a browser UA; orcasecurity.readme.io returns 401; api.orcasecurity.io/swagger.json returns 403 not_authenticated. Vendor guidance is that the OpenAPI spec is only available inside a logged-in tenant at Settings > API. The public orcasecurity GitHub org has a Terraform provider whose api_client package covers configuration objects (business units, compliance frameworks, custom dashboards, tag rules) but not the read/query surface, so it cannot be used to enumerate queryable resources. No gaps reported rather than guessing endpoint names.

## Ortto — adequate

Today (6): `account_custom_fields`, `accounts`, `audiences`, `people`, `person_custom_fields`, `tags`

Diffed against: <https://help.ortto.com/developer/latest/api-reference/index.html>

No material gaps found.

Note: Ortto's public REST API has only seven entities (person, organizations/accounts, audiences, tags, custom-field, activity definitions, activities) and the read operations are exactly: POST /v1/person/get, /v1/organizations/get, /v1/audiences/get, /v1/tags/get, /v1/person/custom-field/get, /v1/organization/custom-field/get. PostHog's six tables cover all of them. Everything else in the API is write-only (activities/create, activity definition create/modify/delete, audience subscribe, person merge/archive) — there is no read endpoint for activity events, campaigns, journeys or emails, so nothing further is syncable. Section list verified by probing /developer/latest/api-reference/<entity>/index.html (200 for activities, activity, audiences, custom-field, organizations, person, tags; 404 for campaigns, journeys, forms, webhooks, reports, etc.).

## Oura — gaps

Today (10): `daily_activity`, `daily_readiness`, `daily_sleep`, `daily_spo2`, `daily_stress`, `heartrate`, `personal_info`, `session`, `sleep`, `workout`

Diffed against: <https://cloud.ouraring.com/v2/static/json/openapi-1.37.json>

- [ ] `/v2/usercollection/daily_resilience` — daily resilience score — one of Oura's headline daily scores, alongside the readiness/sleep/activity scores already synced (high)
- [ ] `/v2/usercollection/daily_cardiovascular_age` — daily cardiovascular age, a headline long-term health metric with no equivalent in the current tables (medium)
- [ ] `/v2/usercollection/vO2_max` — VO2 max estimates over time, the standard cardio-fitness trend series (medium)
- [ ] `/v2/usercollection/enhanced_tag` — user-annotated events (illness, alcohol, travel) — the dimension table for segmenting every daily metric (medium)
- [ ] `/v2/usercollection/rest_mode_period` — rest-mode intervals that suppress scores; needed to exclude or explain anomalous daily rows (medium)
- [ ] `/v2/usercollection/sleep_time` — recommended bedtime windows, joins to the sleep table for adherence analysis (low)
- [ ] `/v2/usercollection/tag` — legacy tag events; superseded by enhanced_tag but still the only history for older data (low)
- [ ] `/v2/usercollection/ring_configuration` — lookup resolving the ring/device that produced each measurement (hardware, size, firmware) (low)
- [ ] `/v2/usercollection/ring_battery_level` — battery time series, useful for explaining data gaps (low)

Note: OpenAPI spec URL is not at a conventional path — it is referenced as spec-url on the Redoc page at https://cloud.ouraring.com/v2/docs (currently openapi-1.37.json). The /v2/sandbox/\* mirror of every collection was ignored as a test double, and /v2/webhook/subscription excluded as plumbing.

## Outbrain — gaps

Today (6): `budgets`, `campaign_performance`, `campaigns`, `marketer_performance_daily`, `marketers`, `promoted_links`

Diffed against: <https://jsapi.apiary.io/apis/amplifyv01/api-description-document>

- [ ] `/reports/marketers/{id}/promotedContent` — per-ad (promoted link) performance - we sync promoted_links metadata but no spend/clicks/conversions against them (high)
- [ ] `/reports/marketers/{id}/publishers` — publisher breakdown, the core Outbrain optimization dimension (high)
- [ ] `/reports/marketers/{id}/sections` — section/placement breakdown - the finest-grained supply dimension advertisers block or bid on (high)
- [ ] `/marketers/{id}/conversionEvents` — lookup table resolving the conversion event ids that appear in every report's conversion details (high)
- [ ] `/reports/marketers/{id}/campaigns/periodic` — daily per-campaign time series; campaign_performance today is only a date-range rollup (high)
- [ ] `/reports/marketers/{id}/geo` — geo breakdown with country/region granularity (medium)
- [ ] `/reports/marketers/{id}/platforms` — device/platform breakdown (medium)
- [ ] `/reports/marketers/{id}/interests` — interest-targeting breakdown (medium)
- [ ] `/marketers/{id}/segments` — audience segments lookup for segment-targeted campaigns (medium)
- [ ] `/campaigns/{campaignId}/locations` — campaign geo targeting rows, needed to interpret geo report deltas (medium)
- [ ] `/marketers/{id}/engagementMetrics` — marketer-level engagement metrics not present in the periodic report (low)
- [ ] `/campaigns/{campaignId}/promotedLinksSequences` — sequence grouping for promoted links (low)

Note: Static endpoint list in settings.py (6 paths: /marketers, /marketers/{id}/campaigns, /marketers/{id}/budgets, /campaigns/{id}/promotedLinks, /reports/marketers/{id}/periodic, /reports/marketers/{id}/campaigns) - no dynamic table discovery. The apiary HTML site 502s; the machine-readable API Blueprint JSON at the jsapi.apiary.io URL above works and was parsed for the full resource list. Outbrain's Performance Reporting group is by far the largest part of the API and PostHog currently exposes only 2 of its ~20 report endpoints.

## PabblySubscriptionsBilling — gaps

Today (13): `addon_list_category`, `addons`, `coupons`, `customers`, `invoices`, `licenses`, `multiplans`, `payment_gateways`, `payment_methods`, `products`, `refunds`, `subscriptions`, `transactions`

Diffed against: <https://apidocs.pabbly.com/pabbly/subscription-billing>

- [ ] `/plans (and /plans/{product_id})` — lookup table for the plan ids carried on every subscription and invoice - currently unresolvable (high)
- [ ] `/commissions` — affiliate commission records, the revenue-share ledger (high)
- [ ] `/mrrsubscription/` — vendor's headline MRR metric endpoint (high)
- [ ] `/revenuetransaction/` — net-revenue / ARPU report rows (high)
- [ ] `/commissions/clicks` — affiliate click events - the top of the partner funnel (medium)
- [ ] `/affiliate/links` — lookup resolving affiliate link ids on commissions and clicks (medium)
- [ ] `/scheduledchanges/{subscription_id}` — pending plan changes; needed for forward-looking churn/upgrade analysis (medium)
- [ ] `/api/v2/getdashboardstats` — account-level summary metrics (MRR, churn, active subscriptions) in one row (medium)
- [ ] `/products/{product_id}/licenses/{license_id}/codes` — individual license codes under the licenses we already sync (medium)
- [ ] `/customer/purchase-info/{customer_id}` — per-customer purchase rollup (lifetime value style fields) (low)
- [ ] `/customfields/{plan_id}` — custom field definitions for plans, to interpret subscription custom fields (low)

Note: Extracted the complete 94-endpoint method/path/title list from the embedded JSON in the docs page. The whole affiliate module and, notably, plans are entirely unexposed.

## Packagist — adequate

Today (4): `downloads`, `packages`, `security_advisories`, `versions`

Diffed against: <https://packagist.org/apidoc>

No material gaps found.

Note: Packagist's public API is small and read-only. The source takes a user-supplied package/vendor list and already covers every per-package read endpoint: packages/{vendor}/{package}.json, the p2 metadata, stats.json, and /api/security-advisories. The only unexposed read endpoints are registry-wide rather than per-package: /explore/popular.json (top packages by weekly downloads), /statistics.json (global download total), /search.json, and /metadata/changes.json (a sync change feed, not warehouse data). None of these justify a table for a user tracking their own packages.

## PagerDuty — gaps

Today (9): `escalation_policies`, `incidents`, `log_entries`, `priorities`, `schedules`, `services`, `teams`, `users`, `vendors`

Diffed against: <https://raw.githubusercontent.com/PagerDuty/api-schema/main/reference/REST/openapiv3.json>

- [ ] `/oncalls` — who was on call for which escalation policy and when - PagerDuty's headline operational dataset (high)
- [ ] `/incidents/{id}/alerts` — alert-level rows under each incident; the actual monitoring events, and where dedup/noise analysis happens (high)
- [ ] `/teams/{id}/members` — membership lookup joining users to the teams we already sync (high)
- [ ] `/change_events` — deploy/change events, the standard correlate-incidents-to-deploys join (high)
- [ ] `/analytics/raw/incidents (POST)` — precomputed per-incident MTTA/MTTR, engaged seconds, and escalation counts (high)
- [ ] `/incidents/{id}/notes` — responder notes attached to incidents, for postmortem/context analysis (medium)
- [ ] `/schedules/{id}/users` — membership lookup resolving which users belong to each schedule we already sync (medium)
- [ ] `/v3/schedules/{id}/rotations (and /overrides)` — rotation and override rows - the actual shift structure behind a schedule (medium)
- [ ] `/business_services` — business service layer plus /business_services/impacts, needed to roll incidents up to business impact (medium)
- [ ] `/maintenance_windows` — suppression windows; without them uptime and alert-volume math is wrong (medium)
- [ ] `/audit/records` — state/transition history across services, schedules, and policies (medium)
- [ ] `/notifications` — notifications actually sent to responders, for pager fatigue analysis (low)

Note: Diffed against the official PagerDuty OpenAPI 3.0.2 spec (~190 GET paths). Coverage of top-level config objects is good, but the incident sub-resources and membership/lookup tables that make incident analytics possible are missing. Note that PagerDuty's Analytics endpoints are POST-only (/analytics/raw/incidents, /analytics/metrics/incidents/\*), which is why they are easy to overlook.

## PandaDoc — gaps

Today (7): `contacts`, `document_folders`, `documents`, `forms`, `members`, `template_folders`, `templates`

Diffed against: <https://developers.pandadoc.com/llms.txt>

- [ ] `/public/v2/documents/{document_id}/audit-trail` — full state/transition history per document (sent, viewed, signed, edited) with timestamps - the core e-signature funnel dataset (high)
- [ ] `/public/v2/product-catalog/items/search` — lookup table resolving the catalog item / SKU ids referenced by quotes and pricing tables (high)
- [ ] `/public/v1/documents/{id} (detail expansion)` — recipients, tokens, and pricing table line items only appear in document details, not in the list response we sync (high)
- [ ] `/public/v1/documents/{id}/fields` — per-document field values, the structured data captured on each document (high)
- [ ] `/public/v1/documents/{id}/linked-objects` — CRM linkage (Salesforce/HubSpot object ids) - the join key back to deal data (medium)
- [ ] `/public/v1/content-library-items` — content library blocks reused across documents and templates (medium)
- [ ] `/public/v1/workspaces` — lookup resolving the workspace each document, template, and member belongs to (medium)
- [ ] `/public/v1/users` — account users, distinct from the workspace members table we already sync (medium)
- [ ] `/public/v1/documents/{id}/sections` — section composition per document (low)
- [ ] `/public/v1/documents/{id}/attachments` — attachment metadata per document (low)
- [ ] `/public/v1/notarization-requests` — notarization request status for accounts using notary workflows (low)

Note: Used the docs portal llms.txt for the full reference index, then fetched individual .md pages (which embed the OpenAPI fragment) to confirm exact paths. Current coverage is all top-level list endpoints; every document sub-resource is missing, and the list-documents response is thin compared with the document detail payload.

## Paperform — adequate

Today (7): `coupons`, `form_fields`, `forms`, `partial_submissions`, `products`, `spaces`, `submissions`

Diffed against: <https://paperform.readme.io/llms.txt>

No material gaps found.

Note: The llms.txt lists Paperform's complete public API. Every GET-able analytical resource is already exposed: forms, form fields, submissions, partial submissions, products, coupons, and spaces. The only remaining GET endpoints are /translations (form translation strings - localization config), /spaces/{id}/forms (a space-to-form mapping already derivable from the forms table), /files (signed download URLs), and the webhook CRUD endpoints - all excluded as config or plumbing.

## Papersign — adequate

Today (3): `documents`, `folders`, `spaces`

Diffed against: <https://paperform.readme.io/llms.txt>

No material gaps found.

Note: Papersign shares the Paperform API surface. Its full endpoint set is /papersign/documents, /papersign/documents/{id}, /papersign/folders, /papersign/spaces, plus mutations (send, copy, cancel, move, create-draft), signer-link generation (an ephemeral token), completed-document download URLs (file access), and folder webhooks. All three queryable collections are already synced; nothing analytical is left. Signer/participant detail exists only inside the document payload, not as a separate endpoint.

## Partnerize — gaps

Today (12): `campaigns`, `clicks`, `conversion_metrics`, `conversion_types`, `conversions`, `countries`, `currencies`, `devices`, `partnership_models`, `timezones`, `traffic_sources`, `user_contexts`

Diffed against: <https://api-docs.partnerize.com/partner/>

- [ ] `/reporting/report_publisher/publisher/{publisher_id}/payable` — payable commission per conversion - the money side of the clicks/conversions already synced (high)
- [ ] `/reporting/export/export/conversion_item.csv (conversion items)` — basket/line-item detail for conversions we already sync (high)
- [ ] `/v2/campaigns/{campaignId}/publishers/{publisherId}/commissions/active (also /default, /campaign, /voucher, /promotion, /tier)` — commission rate card that resolves the campaign IDs carried on conversions (high)
- [ ] `/v2/publishers/{publisherId}/discovery/advertisers (brands)` — advertiser/brand lookup resolving the campaign-to-brand relationship on synced campaigns (high)
- [ ] `/user/publisher/{publisher_id}/campaign/{campaign_id}/voucher` — voucher-code lookup for attributing conversions to promo codes (medium)
- [ ] `/user/publisher/{publisher_id}/selfbill` — self-billing invoices, the settlement layer over payable commission (medium)
- [ ] `/user/publisher/{publisher_id}/payment/summary` — payments summary for reconciling earnings against payouts (medium)
- [ ] `/user/publisher/{publisher_id}/available_commission` — unpaid/available commission balance (medium)
- [ ] `/v3/partner/analytics/impressions/{count,explode,filter,timeseries}` — impressions are the one funnel stage missing next to clicks and conversions (medium)
- [ ] `/v2/publishers/{publisher_id}/links (tracking links)` — resolves camref/tracking-link IDs appearing on clicks (medium)
- [ ] `/user/publisher/{publisher_id}/creative` — creative dimension for breaking down clicks and conversions (medium)
- [ ] `/v3/partner/{partnerId}/participations` — partner-to-campaign membership table (medium)

Note: The docs page embeds a full OpenAPI document (91 operationIds) which I parsed out of the HTML. PostHog implements the publisher/partner API and already covers every /reference/\* lookup table (country, currency, timezone, device, user_context, traffic_source, conversion_type, conversion_metric, partnership_model) plus campaigns/clicks/conversions via /reporting/report_publisher. The remaining surface is mostly commercial (payables, self-bills, commission rate cards) and the v3 analytics endpoints.

## PartnerStack — **thin**

Today (4): `customers`, `deals`, `leads`, `partnerships`

Diffed against: <https://docs.partnerstack.com/llms.txt>

- [ ] `GET /v2/transactions` — the commission ledger; without it partner revenue cannot be measured at all (high)
- [ ] `GET /v2/rewards` — reward records earned by partners, the payout-side counterpart to transactions (high)
- [ ] `GET /v2/payouts` — money actually paid out to partners (high)
- [ ] `GET /v2/actions` — tracked partner actions/events - the raw attribution events behind customers and deals (high)
- [ ] `GET /v2/sales-cycles/{object_type}/stages` — lookup resolving the stage ids carried on the deals and leads we already sync (high)
- [ ] `GET /v2/groups` — lookup resolving the group each partnership belongs to (high)
- [ ] `GET /v2/tiers (and /v2/tiers/collection)` — lookup resolving partnership tier ids, which drive commission rates (high)
- [ ] `GET /v2/links/{partnership_identifier}` — per-partner referral links, the attribution key between traffic and customers (medium)
- [ ] `GET /v2/products` — lookup resolving product ids on transactions and rewards (medium)
- [ ] `GET /v2/applications` — partner application funnel with decision status (medium)
- [ ] `GET /v2/product-book` — product book definitions that scope which products a partner can sell (medium)
- [ ] `GET /v2/partner-team/{team_key}` — partner team membership resolving individual members behind a partnership (medium)

Note: Only 4 of roughly 20 listable v2 collections are exposed. Everything monetary - transactions, rewards, payouts - and every lookup that resolves ids on the objects we already sync (groups, tiers, sales cycle stages, products) is missing, so the current tables cannot be joined into a partner revenue model.

## PayFit — gaps

Today (4): `absences`, `collaborators`, `contracts`, `payslips`

Diffed against: <https://developers.payfit.io/llms.txt>

- [ ] `/companies/{companyId}/contracts/time (worked time by contract)` — actual hours worked per pay period - the core time analytics table alongside absences (high)
- [ ] `/companies/{companyId}/accounting-v2` — payroll accounting entries broken down by analytical code and employee, the finance-facing dataset (high)
- [ ] `/companies/{companyId}` — company lookup resolving the company ID every other table is scoped by (medium)
- [ ] `/companies/{companyId}/payroll-status` — payroll state per pay period, needed to know which periods are final (medium)
- [ ] `/companies/{companyId}/collaborators/meal-vouchers` — per-month meal voucher entitlements per collaborator (FR) (medium)
- [ ] `/companies/{companyId}/health-insurance-contracts` — benefit contract lookup joined to employee contracts already synced (medium)
- [ ] `/companies/{companyId}/provident-fund-contracts` — provident fund contract lookup, same join as health insurance (low)
- [ ] `/companies/{companyId}/payment-files` — monthly payment file for reconciling payslips against disbursements (low)

Note: Exact paths confirmed by fetching the per-operation .md pages, which embed the OpenAPI fragment (base https://partner-api.payfit.com). Several endpoints are country-scoped (FR/UK only), which limits some of these for non-FR customers.

## Paystack — gaps

Today (13): `Customers`, `Disputes`, `PaymentPages`, `PaymentRequests`, `Plans`, `Products`, `Refunds`, `Settlements`, `Subaccounts`, `Subscriptions`, `Transactions`, `TransferRecipients`, `Transfers`

Diffed against: <https://raw.githubusercontent.com/PaystackOSS/openapi/main/dist/paystack.yaml>

- [ ] `/settlement/{id}/transactions` — maps settlements we already sync to the transactions we already sync - the payout reconciliation join (high)
- [ ] `/balance/ledger` — ledger entries behind every balance movement, the money-movement fact table (high)
- [ ] `/split (transaction splits)` — lookup resolving split codes carried on transactions and subaccounts we already sync (high)
- [ ] `/bank` — bank lookup resolving the bank codes on transfer recipients we already sync (medium)
- [ ] `/transaction/timeline/{id}` — per-transaction event/state history for funnel and failure analysis (medium)
- [ ] `/bulkcharge and /bulkcharge/{code}/charges` — batch charge runs plus their member charges (medium)
- [ ] `/dedicated_account (dedicated virtual accounts)` — virtual NUBANs assigned to customers, needed to attribute bank-transfer inflows (medium)
- [ ] `/directdebit/mandate-authorizations` — direct debit mandates underpinning recurring collections (medium)
- [ ] `/order and /order/{id}` — commerce orders with line items sitting above transactions (medium)
- [ ] `/storefront and /storefront/{id}/order` — storefront dimension for the orders above (low)
- [ ] `/transaction/totals and /paymentrequest/totals` — vendor-computed volume aggregates useful as a cross-check (low)
- [ ] `/country and /address_verification/states` — small geography lookups for customer and recipient records (low)

Note: paystack.com/docs/api is behind Cloudflare (403 to curl), so I used the vendor's own published OpenAPI repo PaystackOSS/openapi (dist/paystack.yaml, 125 paths). Coverage of the classic payments objects is good; the gaps are ledger/reconciliation and commerce.

## Pendo — **thin**

Today (5): `accounts`, `features`, `guides`, `pages`, `visitors`

Diffed against: <https://engageapi.pendo.io/api/collections/16265887/Tzm6jvKG>

- [ ] `aggregation source: events` — the raw usage event stream - Pendo's headline dataset and the basis of every engagement metric (high)
- [ ] `aggregation source: featureEvents` — feature click events joined to the features table already synced (high)
- [ ] `aggregation source: pageEvents` — page view events joined to the pages table already synced (high)
- [ ] `GET /api/v1/tracktype` — lookup resolving custom track event type IDs; also needed to interpret trackEvents (high)
- [ ] `aggregation source: trackEvents` — custom-instrumented events, the analog of product analytics custom events (high)
- [ ] `aggregation source: guideEvents (plus guidesSeen)` — guide impressions and interactions for the guides table already synced (medium)
- [ ] `aggregation source: pollEvents / pollsSeen` — poll and NPS responses, the source of Pendo's NPS reporting (medium)
- [ ] `aggregation source: surveyResponses` — survey response rows for voice-of-customer analysis (medium)
- [ ] `GET /api/v1/segment` — segment definitions, the lookup used to slice visitors and accounts already synced (medium)
- [ ] `aggregation source: groups` — page/feature group (product area) lookup used to roll up features and pages (medium)
- [ ] `GET /api/v1/report and /api/v1/report/{reportId}/results.json` — saved report definitions plus their materialized results (medium)
- [ ] `GET /api/v1/guide/{guideId}/history` — guide state/version transition history (low)

Note: engageapi.pendo.io is a Postman-published doc; I pulled the raw collection JSON from the documenter API it loads. PostHog does NOT discover tables dynamically - PENDO_ENDPOINTS in products/warehouse_sources/backend/temporal/data_imports/sources/pendo/settings.py is a fixed dict of 5. It already POSTs to /api/v1/aggregation for visitors and accounts, so every aggregation event source below is a config-level addition on machinery that already exists. Pendo's entire behavioral dataset (events, pageEvents, featureEvents, trackEvents, guideEvents, pollEvents, surveyResponses) is currently unavailable, so the source syncs only the object metadata and none of the usage.

## Perigon — gaps

Today (7): `articles`, `companies`, `journalists`, `people`, `sources`, `stories`, `topics`

Diffed against: <https://storage.googleapis.com/stainless-sdk-openapi-specs/perigon/perigon-sdk-11255e240e6346feeab8ff10dddcfb4348205d0b8f69aaedc564ec7a637b85c2.yml>

- [ ] `GET /v1/stories/history` — time-series evolution of the story clusters already synced (medium)
- [ ] `GET /v1/stories/stats` — story count statistics bucketed by hour/day/week/month for volume trending (medium)
- [ ] `GET /v1/api/sourceGroups` — named groupings of the sources already synced, useful as a source dimension (medium)
- [ ] `GET /v1/wikipedia/all` — the Wikipedia corpus, a distinct queryable dataset alongside articles (low)
- [ ] `GET /v1/api/watchlists` — org watchlists of people and companies, a lookup over entities already synced (low)

Note: docs.perigon.io is a client-rendered SPA that returns the same shell for every path (including llms.txt and sitemap.xml), so the doc URLs in the payload 404 to curl. I resolved the real spec via the vendor's official Go SDK (goperigon/perigon-go-sdk .stats.yml -> openapi_spec_url), which lists 20 paths. Coverage of the listable news/entity resources is nearly complete - all 7 synced tables map 1:1 to /v1/{articles,stories,journalists,sources,people,companies,topics}/all. Remaining endpoints are two story sub-resources, the Wikipedia corpus, and two org-owned saved-filter collections; the vector and summarize endpoints are query-time POSTs, not syncable tables.

## PersistIq — gaps

Today (3): `campaigns`, `leads`, `users`

Diffed against: <https://web.archive.org/web/20251120081157/https://apidocs.persistiq.com/>

- [ ] `GET /v1/events` — the sales activity stream (sends, opens, clicks, replies) - the only behavioral data in the API and absent today (high)
- [ ] `GET /v1/lead_statuses` — lookup resolving the status ID carried on every lead already synced (high)
- [ ] `GET /v1/lead_fields` — custom field definitions needed to interpret lead custom attributes (medium)
- [ ] `GET /v1/dnc_domains` — do-not-contact domain list for suppression analysis (low)

Note: apidocs.persistiq.com is behind a Cloudflare interstitial (403 to curl with any UA), so I read the archived copy of the same Slate single-page doc; it enumerates the full v1 API (base https://api.persistiq.com/v1). Only 4 GET-listable resources are missing, but one of them is the entire activity stream. Note /campaigns/{id}/leads is POST/DELETE only, so campaign membership is not separately syncable.

## Persona — gaps

Today (6): `accounts`, `cases`, `events`, `inquiries`, `inquiry_templates`, `transactions`

Diffed against: <https://docs.withpersona.com/2025-12-08/llms.txt>

- [ ] `GET /reports (List all Reports)` — watchlist, adverse-media and business reports - a headline Persona output missing entirely next to inquiries (high)
- [ ] `GET /inquiry-sessions` — per-attempt sessions under the inquiries already synced, needed for drop-off analysis (medium)
- [ ] `GET /workflow-runs (List all Workflow Runs)` — automation run history over inquiries and cases already synced (medium)
- [ ] `GET /devices` — device records used for fraud and repeat-signup analysis (medium)
- [ ] `GET /accounts/{account-id}/relations` — account-to-account relationship edges for the accounts already synced (medium)
- [ ] `GET /reports/{report-id}/history (List Report history)` — continuous-monitoring state history per report (low)
- [ ] `GET /lists (List all Lists)` — blocklist/allowlist definitions referenced by inquiry and verification outcomes (low)
- [ ] `GET /user-audit-logs` — reviewer action log for measuring manual review throughput (low)

Note: Persona's own repo note (products/warehouse_sources/backend/temporal/data_imports/sources/persona/api_inventory.md) documents the 6 synced endpoints. Only resources with a genuine list endpoint are reported: Verifications, Documents, Account Types, Case Templates and Transaction Types are retrieve-by-ID only in the reference, so they are not syncable as standalone tables despite being useful joins - I deliberately left them out rather than invent list routes.

## Personio — **thin**

Today (3): `absence_periods`, `attendance_periods`, `persons`

Diffed against: <https://developer.personio.de/llms.txt>

- [ ] `GET /v2/persons/{person_id}/employments` — employment records for the persons already synced - contract type, dates, job reference; the core HR fact table (high)
- [ ] `GET /v2/absence-types` — lookup resolving the absence type on every absence period already synced (high)
- [ ] `GET /v2/compensations` — salary, hourly, bonus and recurring compensation - the payroll dataset (high)
- [ ] `GET /v2/org-units` — department/team hierarchy lookup for grouping persons, absences and attendance (high)
- [ ] `GET /v2/cost-centers` — cost center lookup for allocating attendance and compensation to finance dimensions (medium)
- [ ] `GET /v2/legal-entities` — legal entity lookup for multi-entity headcount and payroll splits (medium)
- [ ] `GET /v2/jobs` — job/position catalog referenced from employments (medium)
- [ ] `GET /v2/compensations/types` — lookup resolving compensation type IDs on compensation rows (medium)
- [ ] `GET /v2/projects and /v2/projects/{id}/members` — project catalog and membership that attendance periods are booked against (medium)
- [ ] `GET /v2/recruiting/applications` — application pipeline records, the main recruiting funnel object (medium)
- [ ] `GET /v2/recruiting/applications/{id}/stage-transitions` — stage transition history - exactly the state-change data needed for time-in-stage metrics (medium)
- [ ] `GET /v2/recruiting/candidates` — candidate records joined to applications above (medium)

Note: PERSONIO_ENDPOINTS in products/warehouse_sources/backend/temporal/data_imports/sources/personio/settings.py is a static 3-entry dict (/v2/persons, /v2/absence-periods, /v2/attendance-periods) - no dynamic discovery. The v2 API exposes roughly 20 listable resources, so this is a small fraction, and notably every organizational lookup that would let you group the synced persons and time data (org units, cost centers, legal entities, jobs) is missing. Exact paths confirmed from the individual reference .md pages. Recruiting endpoints are flagged beta by the vendor.

## Pexels — gaps

Today (4): `curated_photos`, `featured_collections`, `my_collections`, `popular_videos`

Diffed against: <https://www.pexels.com/api/documentation/>

- [ ] `GET /v1/collections/{id} (collection media)` — the only way to resolve which photos/videos belong to the collections we already sync - without it featured_collections and my_collections are unjoinable ID rows (high)

Note: Pexels' whole documented surface is 9 endpoints: /v1/search, /v1/curated, /v1/photos/{id}, /videos/search, /videos/popular, /videos/videos/{id}, /v1/collections/featured, /v1/collections, /v1/collections/{id}. The source already implements search_photos and search_videos, but they are gated on a configured search query so they never appear in get_schemas - that is not a gap. www.pexels.com blocks curl with a Cloudflare 403; the page was read via the fetch tool instead.

## PgAnalyze — gaps

Today (2): `issues`, `servers`

Diffed against: <https://pganalyze.com/docs/api/queries>

- [ ] `getQueryStats` — the only performance dataset pganalyze exposes publicly (totalCalls, avgTime, avgIoTime, bufferHitRatio, pctOfTotal per normalized query) and the product's headline metric (high)

Note: pganalyze's public GraphQL API officially exposes exactly three query endpoints - getServers, getIssues, getQueryStats - so coverage is 2 of 3. getQueryStats takes a databaseId, which the current getServers query does not select, so implementing it needs a database-ID discovery step. Data is a rolling 24h window, so it must be synced incrementally or history is lost.

## Phyllo — gaps

Today (7): `accounts`, `income_payouts`, `income_transactions`, `profiles`, `social_contents`, `users`, `work_platforms`

Diffed against: <https://rapidapi.com/phyllo-phyllo-default/api/phyllo-apis-v1>

- [ ] `/v1/audience` — audience demographics and follower breakdowns - the headline output of the Identity & Audience product (high)
- [ ] `/v1/social/comments` — comment-level engagement for the contents we already sync; the Comments API is one of Phyllo's three product lines (high)
- [ ] `/v1/social/content-groups` — stories/albums/series groupings that contents belong to; needed to roll engagement up above the individual post (medium)
- [ ] `/v1/commerce/income/transactions` — commerce-platform earnings; the synced income_transactions table only covers the social income path (medium)
- [ ] `/v1/commerce/income/payouts` — commerce payout records, same coverage gap as commerce transactions (medium)
- [ ] `/v1/commerce/income/balances` — current and pending balances per connected commerce account, not derivable from payouts alone (medium)
- [ ] `/v1/media/activity/contents` — media-activity (listening/watching) items for accounts on media platforms (medium)
- [ ] `/v1/media/activity/artists` — artist lookup resolving the artist IDs carried on media activity contents (low)

Note: docs.getphyllo.com is a JS-only Stoplight SPA (no server-rendered TOC, no reachable table-of-contents API) and api.getphyllo.com/openapi.json is auth-gated, so the resource list came from Phyllo's own RapidAPI listing rather than their docs site. Phyllo now also brands as InsightIQ (docs.insightiq.ai, same Stoplight setup). Worth verifying: the source calls /v1/income/transactions and /v1/income/payouts, but the current API splits income into /v1/social/income/\* and /v1/commerce/income/\* - the unprefixed paths look like legacy aliases.

## Picqer — gaps

Today (13): `customers`, `locations`, `orders`, `picklists`, `products`, `purchaseorders`, `receipts`, `returns`, `suppliers`, `tags`, `users`, `vatgroups`, `warehouses`

Diffed against: <https://picqer.com/en/api>

- [ ] `/stockhistory` — every stock movement in and out of the warehouse with old/new levels, reason and change_type - the core inventory event stream (high)
- [ ] `/shipments (also /picklists/{idpicklist}/shipments)` — actual outbound shipments with carrier and tracking; picklists alone can't answer ship-rate or carrier-mix questions (high)
- [ ] `/warehouses/{idwarehouse}/stock and /products/{idproduct}/stock` — current stock level per product per warehouse; the products table has no per-warehouse quantities (high)
- [ ] `/return_reasons` — lookup resolving the reason ID carried on the returns we already sync (high)
- [ ] `/return_statuses` — lookup resolving the status ID on synced returns (high)
- [ ] `/backorders` — unfulfillable order lines - the standard stockout/backorder analysis (medium)
- [ ] `/picklists/batches` — batch-picking grouping over picklists; needed for picker throughput and batch efficiency (medium)
- [ ] `/webshoporders` — import status per external webshop order, including failures that never became a Picqer order (medium)
- [ ] `/comments` — cross-entity comment log (orders, picklists, returns, purchase orders) usable as an operational activity feed (medium)
- [ ] `/shippingproviders` — lookup resolving shipping provider IDs on shipments and orders (medium)
- [ ] `/pricelists` — price list definitions behind customer-specific pricing on orders (medium)
- [ ] `/productfields, /orderfields, /customerfields` — custom field definitions that name the free-field values embedded in synced products, orders and customers (medium)

Note: Full vendor resource list read from the docs navigation plus each resource page. Also present but lower value and not listed above: /tasks, /packagings, /location_types, /templates, /picking-containers, /stats, /products/{id}/pricehistory, /locations/{id}/products.

## Pingdom — gaps

Today (4): `alerts`, `checks`, `maintenance`, `probes`

Diffed against: <https://docs.pingdom.com/api/API_3.1.yaml>

- [ ] `GET /results/{checkid}` — raw per-probe check results (status, response time, probe) - the underlying monitoring data, none of which is synced today (high)
- [ ] `GET /summary.outage/{checkid}` — up/down state-transition history per check; the only way to compute uptime or incident duration (high)
- [ ] `GET /summary.performance/{checkid}` — bucketed response-time series - Pingdom's headline metric (high)
- [ ] `GET /tms/check` — transaction (synthetic scripted) checks are a separate check type entirely and are invisible in the synced checks table (high)
- [ ] `GET /summary.average/{checkid}` — average response time over a period, optionally broken down by country/probe (medium)
- [ ] `GET /tms/check/{check_id}/report/status` — status/uptime history for transaction checks (medium)
- [ ] `GET /tms/check/{check_id}/report/performance` — response-time history for transaction checks (medium)
- [ ] `GET /analysis/{checkid}` — root-cause analysis records attached to failures, for post-incident breakdowns (medium)
- [ ] `GET /alerting/contacts` — lookup resolving the user/contact IDs that appear on the alerts (/actions) rows we already sync (medium)
- [ ] `GET /maintenance.occurrences` — individual maintenance windows expanded from recurring maintenance, needed to exclude planned downtime (medium)
- [ ] `GET /alerting/teams` — team lookup for alert routing analysis (low)
- [ ] `GET /summary.hoursofday/{checkid}` — response time by hour of day for seasonality analysis (low)

Note: The synced alerts table maps to GET /actions. Every high-value gap is a per-check subresource, so implementing them needs fan-out over the synced checks plus a time-window watermark - the same shape as other fan-out sources. Spec URL is the OpenAPI file the docs SPA loads (also served at https://docs.pingdom.com/api/API\_3.1.yaml); older 2.0/2.1 specs sit alongside it.

## Pipedrive — gaps

Today (13): `activities`, `deal_fields`, `deals`, `leads`, `notes`, `organization_fields`, `organizations`, `person_fields`, `persons`, `pipelines`, `products`, `stages`, `users`

Diffed against: <https://developers.pipedrive.com/docs/api/v2/openapi.yaml>

- [ ] `GET /deals/{id}/products (v2) and /deals/products` — deal line items - product, quantity, price, discount per deal; without them revenue can only be read as a single deal-level number (high)
- [ ] `GET /deals/archived (v2)` — /deals excludes archived deals, so the synced deals table silently loses closed/archived pipeline history (high)
- [ ] `GET /activityTypes (v1)` — lookup resolving the type key on every synced activity row (high)
- [ ] `GET /deals/{id}/flow and /deals/{id}/changelog (v1)` — per-field change history including stage moves - required for stage-transition, velocity and win-rate-over-time analysis (high)
- [ ] `GET /leadLabels (v1)` — lookup resolving the label IDs carried on the leads we already sync (high)
- [ ] `GET /leadSources (v1)` — lookup resolving lead source values for attribution (medium)
- [ ] `GET /currencies (v1)` — currency lookup for multi-currency deal and product values (medium)
- [ ] `GET /pipelines/{id}/conversion_statistics and /movement_statistics (v1)` — Pipedrive's own funnel conversion and stage-movement metrics per pipeline (medium)
- [ ] `GET /callLogs (v1)` — call activity with duration and outcome, not covered by the activities table (medium)
- [ ] `GET /goals and /goals/{id}/results (v1)` — sales targets and attainment, the natural denominator for deal reporting (medium)
- [ ] `GET /mailbox/mailThreads and /mailbox/mailThreads/{id}/mailMessages (v1)` — email engagement tied to deals and persons (medium)
- [ ] `GET /projects, /projects/{id}/tasks, /projects/boards, /projects/phases (v1 and v2)` — the Projects product is entirely absent, including its board/phase lookups (medium)

Note: Diffed against both specs - v2 (https://developers.pipedrive.com/docs/api/v2/openapi.yaml) and v1 (https://developers.pipedrive.com/docs/api/v1/openapi.yaml) - because collection reads are split across them: v2 owns deals/persons/organizations/products/stages/pipelines/activities, v1 still owns activityTypes, currencies, leadLabels, leadSources, goals, callLogs, mailbox and the deal changelog/flow. Deliberately excluded as config: filters, roles, permissionSets, legacyTeams, userSettings, webhooks, files.

## Pipeliner — **thin**

Today (11): `accounts`, `appointments`, `clients`, `contacts`, `leads`, `notes`, `opportunities`, `pipelines`, `products`, `steps`, `tasks`

Diffed against: <https://pipelinercrm.eu.apidog.com/>

- [ ] `OpptyProductRelations` — product line items linking opportunities to products with quantity and price - synced opportunities and products are otherwise unjoinable (high)
- [ ] `ProcessActivityLogs and ProcessActivityLogLines` — step/stage transition history for opportunities, the basis of sales-velocity and stage-conversion analysis (high)
- [ ] `SalesUnits (and SalesUnitClientRelations)` — lookup resolving the sales unit IDs stamped on every account, contact, lead and opportunity we sync (high)
- [ ] `Currencies and CurrencyExchangeRates` — lookup for the currency IDs on opportunity and product values; without it multi-currency pipelines can't be normalized (high)
- [ ] `Processes (and ProcessTemplates)` — the sales process each Step belongs to - the parent lookup for the synced steps table (high)
- [ ] `AccountTypes, ContactTypes, LeadTypes, OpportunityTypes, TaskTypes, AppointmentTypes` — type lookups resolving the type IDs on the core records already synced (high)
- [ ] `Quotes (and QuoteProcesses, QuoteTypes)` — quoting is a first-class Pipeliner object tied to opportunities and completely absent today (medium)
- [ ] `ContactAccountRelations and ContactAccountAccountRoleRelations` — join table between the synced contacts and accounts, including the contact's role at the account (medium)
- [ ] `Forecasts and Targets/TargetRelations` — quota and forecast figures - the denominator for pipeline attainment reporting (medium)
- [ ] `Emails and EmailEvents` — email activity and open/click events tied to CRM records (medium)
- [ ] `Calls and TextMessages` — call and SMS touchpoints not represented by tasks or appointments (medium)
- [ ] `Tags and TagRelations` — tag lookup plus the polymorphic join that attaches tags to accounts, contacts and opportunities (medium)

Note: The vendor's GitBook docs site (developers.pipelinersales.com/api-docs) only carries concepts and tutorials; the actual REST entity reference it links to is the Apidog site above, which enumerates 204 /entities/{Name} resources. PostHog exposes 11 of them. Other credible-but-lower-priority entities: ProductPriceLists/ProductPriceListPrices/ProductCategories, OpptyRevenueSchedules and periods, AccountKPIs/ContactKPIs/LeadOpptyKPIs, EntityFitnesses/EntityHealths/EntityScorings, Projects/ProjectObjectives, MasterRights and SalesRoles, Memos, CloudObjects (documents), Reports. Note the product is being rebranded to Coevera in the docs.

## Plaid — **thin**

Today (2): `accounts`, `transactions`

Diffed against: <https://raw.githubusercontent.com/plaid/plaid-openapi/master/2020-09-14.yml>

- [ ] `/investments/holdings/get` — positions and cost basis per investment account - accounts alone give no portfolio detail (high)
- [ ] `/investments/transactions/get` — buys, sells, dividends and fees; the investments analogue of the transactions table we already sync (high)
- [ ] `/liabilities/get` — loan and credit-card detail (APR, minimum payment, due date, origination) that never appears in accounts or transactions (high)
- [ ] `/institutions/get_by_id (and /institutions/get)` — lookup resolving the institution_id on the item whose accounts we sync - today the bank is only an opaque ID (high)
- [ ] `/transactions/recurring/get` — Plaid-derived recurring inflow/outflow streams - the headline subscription and income-detection product (high)
- [ ] `/accounts/balance/get` — live available/current balance refresh; the balances embedded in /accounts/get are cached and can be stale (medium)
- [ ] `/identity/get` — account owner names, emails, phones and addresses, the standard join key to customer records (medium)
- [ ] `/item/get` — item metadata - institution, enabled products, consent expiry, last error - needed to explain gaps in synced data (medium)
- [ ] `/transfer/list` — money-movement records for Plaid Transfer customers, an analytical object with no equivalent today (medium)
- [ ] `/transfer/event/list` — transfer state-transition history (pending, posted, returned) for settlement and return-rate analysis (medium)
- [ ] `/statements/list` — available bank statement metadata per account for reconciliation coverage checks (low)
- [ ] `/categories/get` — legacy category taxonomy resolving the category IDs on synced transactions (low)

Note: Plaid's spec is enormous (~280 operations) but most of it is Link/onboarding plumbing, sandbox simulation, CRA/credit reporting and processor-token flows that are correctly out of scope. One PostHog source connects one Plaid Item, and which of these endpoints actually returns data depends on the products that item was linked with - investments, liabilities and transfer will 400 for items without them, so they need to fail soft. The source deliberately uses /transactions/get rather than /transactions/sync (documented in settings.py: the sync cursor can't be expressed as a row-field watermark), which means transaction updates and removals are not captured - worth revisiting separately from endpoint coverage. /categories/get is legacy; Plaid now ships personal_finance_category inline on transactions.

## Plain — **thin**

Today (3): `customers`, `threads`, `timeline_entries`

Diffed against: <https://core-api.uk.plain.com/graphql/v1/schema.graphql>

- [ ] `companies` — account-level entity that customers hang off; lookup for the company IDs already on synced customers (high)
- [ ] `users` — lookup resolving assignee and actor IDs carried on threads and timeline entries (high)
- [ ] `labelTypes` — lookup resolving the label IDs attached to synced threads (high)
- [ ] `tenants` — multi-tenant grouping dimension for customers and threads (high)
- [ ] `customerSurveys` — CSAT responses, the headline support-quality metric (high)
- [ ] `tiers` — SLA tier per company/tenant, needed to segment thread response times (medium)
- [ ] `tasks` — work items attached to threads, needed for workload analysis (medium)
- [ ] `discussions` — internal discussion threads separate from customer-facing threads (medium)
- [ ] `customerGroups` — lookup resolving group IDs on customers (medium)
- [ ] `workflowExecutions` — automation run history, for measuring deflection and routing (medium)
- [ ] `threadFieldSchemas` — lookup defining the custom thread fields whose values appear on threads (medium)
- [ ] `knowledgeGaps` — AI knowledge-gap records for content prioritization (low)

Note: Plain is GraphQL-only; I enumerated every \*Connection field on type Query from the published SDL. 62 paginated collections exist against the 3 tables PostHog exposes. Non-analytical Connections (webhookTargets, workspaceSlackIntegrations, serviceAuthorizations, savedThreadsViews, chatApps, roles, billingPlans) were deliberately excluded as config/plumbing.

## Planhat — **thin**

Today (6): `assets`, `companies`, `endusers`, `licenses`, `nps`, `users`

Diffed against: <https://docs.planhat.com/developers/api/planhat-models>

- [ ] `conversation` — customer conversation records, the core engagement signal in Planhat (high)
- [ ] `ticket` — support tickets tied to companies, needed for health scoring (high)
- [ ] `invoice` — billed revenue per company (high)
- [ ] `sale` — closed revenue transactions (high)
- [ ] `churn` — churn records, the headline customer-success metric (high)
- [ ] `metrics` — time-series usage and health metrics per company; Planhat's central analytical object (high)
- [ ] `product` — lookup resolving the product IDs carried on synced licenses and on line items (high)
- [ ] `line-item` — line-level breakdown of licenses, invoices and sales (high)
- [ ] `opportunity` — open pipeline against existing accounts (high)
- [ ] `user-activities` — enduser activity events, the raw input to adoption analysis (medium)
- [ ] `custom-field` — lookup describing the custom fields present on companies, endusers and licenses (medium)
- [ ] `task` — CSM task records for workload and playbook execution (medium)

Note: docs.planhat.com is now a Framer SPA that serves the same HTML shell for every path, so the page list is not readable by plain curl. I recovered the authoritative model list from the site's own search index (https://framerusercontent.com/sites/2dYA2Fo9WB6PMbsWedNqce/searchIndex-RF4JY9qKBv0J.json), which serializes the /developers/api/\* page titles and the full model nav on the planhat-models page. Also documented but omitted as lower value: issue, objective, project, campaign, deal, time-entry, timesheet.

## PlatformSh — gaps

Today (6): `activities`, `environments`, `members`, `organizations`, `projects`, `subscriptions`

Diffed against: <https://meta.upsun.com/openapi-spec>

- [ ] `/projects/{projectId}/environments/{environmentId}/deployments` — what is actually running per environment — services, workers, crons, resource sizes (high)
- [ ] `/organizations/{organization_id}/records/usage` — consumption records; the only way to attribute spend to projects and environments (high)
- [ ] `/organizations/{organization_id}/invoices` — billed amounts per period, the headline financial object (high)
- [ ] `/regions` — lookup resolving the region IDs already carried on synced projects and subscriptions (high)
- [ ] `/projects/{projectId}/environments/{environmentId}/backups` — backup history for recovery-posture and retention reporting (medium)
- [ ] `/projects/{projectId}/domains` — domains attached to a project, needed to map projects to sites (medium)
- [ ] `/projects/{projectId}/environments/{environmentId}/routes` — route table per environment, resolves which URL serves which app (medium)
- [ ] `/teams and /teams/{team_id}/members` — team membership lookup that complements the organization members already synced (medium)
- [ ] `/projects/{project_id}/user-access` — per-project access grants, needed for access audits alongside org members (medium)
- [ ] `/projects/{projectId}/environment-types` — lookup resolving the environment type carried on each environment (medium)
- [ ] `/organizations/{organization_id}/orders` — order history behind the subscriptions already synced (medium)
- [ ] `/organizations/{organization_id}/subscriptions/{subscription_id}/current_usage` — in-period usage per subscription for run-rate tracking (medium)

Note: api.platform.sh/docs now 301s to developer.upsun.com/api, which renders the spec at meta.upsun.com/openapi-spec. I cross-checked that this spec's paths match what the PostHog source already calls against https://api.platform.sh (/organizations, /projects/{id}/environments, /projects/{id}/activities, /organizations/{id}/members, /organizations/{id}/subscriptions), so the spec is applicable. Config/plumbing paths (variables, integrations, certificates, ssh_keys, api-tokens, provisioners, domain-claims) were excluded.

## Plausible — gaps

Today (18): `browsers`, `cities`, `countries`, `devices`, `entry_pages`, `exit_pages`, `goals`, `operating_systems`, `pages`, `referrers`, `regions`, `sources`, `timeseries`, `utm_campaigns`, `utm_contents`, `utm_mediums`, `utm_sources`, `utm_terms`

Diffed against: <https://plausible.io/docs/stats-api>

- [ ] `visit:channel` — Plausible's acquisition-channel dimension — the default breakdown in its own dashboard and not derivable from source or utm_medium (high)
- [ ] `event:props:{key}` — custom event property breakdowns; the only way to analyze custom-event dimensions such as plan or signup method (high)
- [ ] `event:hostname` — splits traffic across subdomains and multi-domain sites, which every other table silently merges (medium)
- [ ] `visit:browser_version` — browser version breakdown for compatibility analysis (low)
- [ ] `visit:os_version` — OS version breakdown for compatibility analysis (low)
- [ ] `visit:entry_page_hostname / visit:exit_page_hostname` — hostname-qualified entry and exit pages for multi-domain sites (low)

Note: Plausible's Stats API v2 is a single POST /api/v2/query endpoint; a PostHog 'table' is one breakdown dimension. Coverage is close to complete — 18 of the 24 documented dimensions are already exposed. Custom properties (event:props:\*) are open-ended per site, so implementing them would need dynamic table discovery rather than a fixed table.

## Plivo — gaps

Today (4): `applications`, `calls`, `messages`, `recordings`

Diffed against: <https://www.plivo.com/docs/numbers/phone-numbers/>

- [ ] `GET /v1/Account/{auth_id}/PhoneNumber/` — lookup resolving the rented numbers that appear as from/to on every synced message and call (high)
- [ ] `GET /v1/Account/{auth_id}/UsageSummary/` — billed usage and spend per period, the headline cost metric (high)
- [ ] `GET /v1/Account/{auth_id}/MultiPartyCall/` — conference-style calls that never appear in the flat calls table (high)
- [ ] `GET /v1/Account/{auth_id}/MultiPartyCall/name_{mpc_name}/Participant/` — per-leg participant records — join, exit and duration per member (high)
- [ ] `GET /v1/Account/{auth_id}/Subaccount/` — lookup for attributing message and call traffic to the right subaccount (medium)
- [ ] `GET /v1/Account/{auth_id}/Verify/Session/` — OTP verification sessions, needed to measure verification funnel completion (medium)
- [ ] `GET /v1/Account/{auth_id}/Zentrunk/Call/` — SIP trunking CDRs, a call stream entirely absent from the calls table (medium)
- [ ] `GET /v1/Account/{auth_id}/Endpoint/` — SIP endpoint lookup resolving endpoint IDs on calls (medium)
- [ ] `GET /v1/Account/{auth_id}/Masking/Session/` — number-masking sessions linking masked calls and messages to a session (medium)
- [ ] `GET /v1/Account/{auth_id}/Powerpack/` — lookup resolving the powerpack UUID carried on outbound messages (medium)
- [ ] `GET /v1/Account/{auth_id}/10dlc/Campaign/` — lookup resolving 10DLC campaign registration for US messaging traffic (medium)
- [ ] `GET /v1/Account/{auth_id}/10dlc/Brand/` — brand registration behind each 10DLC campaign (low)

Note: Plivo publishes no OpenAPI spec. I enumerated the API surface from https://www.plivo.com/sitemap.xml (35 /docs/\*/api/\* pages) and then fetched ten of those reference pages individually to confirm each list endpoint's exact path; every gap above was read off a real doc page in this run. Excluded as config: SIP credentials, IP ACLs, origination URIs, verified caller IDs, WhatsApp templates, toll-free verification, media uploads.

## Plunk — adequate

Today (4): `campaigns`, `contacts`, `segments`, `templates`

Diffed against: <https://docs.useplunk.com/openapi.json>

No material gaps found.

Note: The entire published Plunk API is seven operations: four listable collections (contacts, campaigns, templates, segments) plus three write-only actions (POST /v1/send, POST /v1/track, POST /v1/verify). PostHog already exposes all four listable collections, so there is nothing left to sync. Workflows and events are documented as product concepts but have no REST endpoints in the spec or in the API reference section of https://docs.useplunk.com/llms.txt.

## PrefectCloud — gaps

Today (6): `deployments`, `flow_runs`, `flows`, `task_runs`, `work_pools`, `work_queues`

Diffed against: <https://api.prefect.cloud/api/openapi.json>

- [ ] `POST /events/filter` — the workspace event feed — every state change, deployment and automation trigger; the richest analytical stream Prefect has (high)
- [ ] `POST /logs/filter` — run logs, needed to diagnose failures alongside the flow_runs already synced (high)
- [ ] `POST /artifacts/filter` — artifacts are how flows publish metrics, tables and links; the actual outputs of the runs already synced (high)
- [ ] `GET /flow_run_states/ and GET /task_run_states/` — state transition history — queue time, retry count and time-in-state cannot be derived from the terminal state on the run row (high)
- [ ] `GET /deployments/{id}/schedules` — lookup for the schedules driving each deployment, needed to measure lateness against intent (medium)
- [ ] `POST /automations/filter` — automation definitions that explain why runs were triggered or cancelled (medium)
- [ ] `POST /work_pools/{work_pool_name}/workers/filter` — worker inventory and heartbeats per pool, for capacity analysis against the pools already synced (medium)
- [ ] `POST /v2/concurrency_limits/filter` — concurrency limits that explain queueing and throttling of flow runs (medium)
- [ ] `GET /assets/ and GET /assets/materializations` — asset lineage and materialization events, Prefect's data-asset layer over runs (medium)
- [ ] `POST /slas/filter` — SLA definitions needed to judge run lateness and violations (medium)
- [ ] `POST /deployments/{id}/versions/paginate` — deployment version history, so run outcomes can be attributed to a code version (medium)
- [ ] `POST /variables/filter` — workspace variables referenced by deployment parameters (low)

Note: The PostHog source is scoped to a single configured workspace and posts to /{...}/filter paths, matching the spec exactly. Account-level tags (Bots, Invitations, Rate Limits, SSO, Billing) and block/webhook config were excluded as plumbing.

## Pretix — gaps

Today (14): `categories`, `checkin_lists`, `customers`, `events`, `gift_cards`, `invoices`, `items`, `orders`, `questions`, `quotas`, `subevents`, `tax_rules`, `vouchers`, `waiting_list_entries`

Diffed against: <https://docs.pretix.eu/dev/api/resources/index.html>

- [ ] `/organizers/{org}/transactions/` — pretix's financial ledger — the canonical per-line revenue record and the intended basis for revenue reporting (high)
- [ ] `/organizers/{org}/events/{event}/orders/{code}/payments/` — payment records with provider, amount and state; not embedded in the order JSON (high)
- [ ] `/organizers/{org}/events/{event}/orders/{code}/refunds/` — refund records, the other half of the money story and also not embedded in orders (high)
- [ ] `/organizers/{org}/events/{event}/items/{id}/variations/` — lookup resolving the variation IDs carried on order positions and quotas (high)
- [ ] `/organizers/{org}/events/{event}/checkins/` — check-in history — the attendance event stream behind the checkin_lists already synced (high)
- [ ] `/organizers/ (list)` — top-level lookup; every other table is keyed by organizer slug and there is no organizer table (high)
- [ ] `/organizers/{org}/orderpositions/` — flat ticket-level line items across all events, far cheaper to query than unnesting the positions array embedded in orders (medium)
- [ ] `/organizers/{org}/saleschannels/` — lookup resolving the sales_channel value on every order (medium)
- [ ] `/organizers/{org}/events/{event}/discounts/` — discount rules that explain the price deltas on order positions (medium)
- [ ] `/organizers/{org}/memberships/ and /organizers/{org}/membershiptypes/` — membership records plus the type lookup they reference; drives recurring-attendee analysis (medium)
- [ ] `/organizers/{org}/events/{event}/questions/{id}/options/` — lookup resolving the option IDs stored in order-position answers to the questions already synced (medium)
- [ ] `/organizers/{org}/events/{event}/seats/` — seat inventory and occupancy for seated events (medium)

Note: The PostHog source deliberately skips a dedicated order-positions stream because positions arrive embedded in each order's `positions` array (see the comment in pretix/settings.py), so that gap is a normalization convenience rather than missing data — hence medium, not high. Payments, refunds, transactions and check-in history are genuinely separate resources with no embedded equivalent. Config and plumbing resources (webhooks, devices, teams, exporters, scheduled_exports, shredders, badges, sendmail_rules, auto_checkin_rules, imported_secrets, certificates) were excluded.

## Printify — gaps

Today (7): `blueprints`, `orders`, `print_providers`, `products`, `shops`, `uploads`, `webhooks`

Diffed against: <https://developers.printify.com/>

- [ ] `catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/variants` — the variant lookup table that resolves the variant_id carried on every synced product and order line item (size/color/SKU/price) (high)
- [ ] `catalog/blueprints/{blueprint_id}/print_providers` — blueprint-to-print-provider mapping table; joins the two catalog tables already synced (medium)
- [ ] `catalog/blueprints/{blueprint_id}/print_providers/{print_provider_id}/shipping (and the v2 shipping/standard|express|priority|economy variants)` — shipping cost and handling time per variant/country, needed for order margin analysis (medium)
- [ ] `shops/{shop_id}/products/{product_id}/gpsr` — product safety/compliance attributes per product (low)

Note: Single-page reference; v1 covers catalog/shops/products/orders/uploads/webhooks, and a v2 catalog shipping family (shipping/standard, /express, /priority, /economy) exists alongside the v1 shipping endpoint. Order line items are nested inside the orders payload, so they are not a separate gap.

## Productboard — gaps

Today (14): `companies`, `components`, `features`, `initiatives`, `key_results`, `members`, `notes`, `objectives`, `products`, `release_groups`, `releases`, `subfeatures`, `teams`, `users`

Diffed against: <https://developer.productboard.com/reference/listentityfieldvalues>

- [ ] `GET /v2/entities/configurations/{type}` — defines every custom field and status for each entity type - the lookup that names the field/status IDs stored on entities (high)
- [ ] `GET /v2/entities/fields/{fieldId}/values` — actual custom-field and status values per entity (e.g. status per feature); without it the entity rows carry no field data (high)
- [ ] `GET /v2/entities/{id}/relationships` — the join table linking features to subfeatures, components, products, objectives and initiatives (high)
- [ ] `GET /v2/notes/{id}/relationships` — links each piece of customer feedback to the feature/company it belongs to - the core insight-to-feature join (high)
- [ ] `GET /v2/teams/{id}/members` — team membership join table for the teams and members already synced (high)
- [ ] `GET /v2/entities/{id}/score` — customer/user impact score per feature - a headline prioritization metric (medium)
- [ ] `GET /v2/analytics/member-activities` — per-member activity events for adoption and engagement reporting (medium)
- [ ] `GET /v2/notes/configurations` — custom field definitions for notes; resolves note field IDs (medium)
- [ ] `GET /v2/jira-integrations/{integrationId}/connections` — feature-to-Jira-issue mapping, letting roadmap data join delivery data (medium)
- [ ] `GET /v2/plugin-integrations/{integrationId}/connections` — feature-to-external-tracker mapping for non-Jira integrations (medium)

Note: The source uses the v2 API where companies/features/components/objectives etc. are all entity types on GET /v2/entities, so those 14 tables come from one endpoint. The uncovered surface is the field-value, configuration and relationship sub-resources, which is where most of the analytical detail lives.

## PulumiCloud — gaps

Today (5): `audit_logs`, `deployments`, `resources`, `stack_updates`, `stacks`

Diffed against: <https://www.pulumi.com/docs/reference/cloud-rest-api/>

- [ ] `GET /api/orgs/{orgName}/policyresults/violationsv2 (also /policyresults/issues)` — policy violations per resource/stack - the compliance dataset users report on (high)
- [ ] `GET /api/orgs/{orgName}/resources/summary` — resources under management, the org's headline usage/billing metric (high)
- [ ] `GET /api/orgs/{orgName}/members` — org membership lookup that resolves the user logins appearing on stack updates and audit logs (high)
- [ ] `GET /api/stacks/{orgName}/{projectName}/{stackName}/tags` — stack tags (environment, owner, cost centre) - the lookup that makes stack and update data groupable (high)
- [ ] `GET /api/orgs/{orgName}/teams (and /teams/{teamName})` — team lookup for ownership and access reporting on stacks (medium)
- [ ] `GET /api/orgs/{orgName}/policyresults/policies` — policy definitions lookup that names the policies referenced by violations (medium)
- [ ] `GET /api/orgs/{orgName}/policyresults/compliance` — aggregated compliance posture over time (medium)
- [ ] `GET /api/preview/insights/{orgName}/accounts and /accounts/{accountName}/scans` — Pulumi Insights cloud accounts and their scan history, the source of discovered (unmanaged) resources (medium)
- [ ] `GET /api/orgs/{orgName}/discovered-resources/summary` — unmanaged vs managed resource counts, pairs with resources/summary (medium)
- [ ] `GET /api/esc/environments (and /{orgName}/{projectName}/{envName}/versions)` — ESC environments and their version history, a first-class Pulumi Cloud object entirely unsynced (medium)
- [ ] `GET /api/orgs/{orgName}/policypacks` — policy pack inventory and versions (low)
- [ ] `GET /api/stacks/{orgName}/{projectName}/{stackName}/deployments/schedules (and /deployments/drift/schedules)` — deployment and drift schedules per stack, plus their run history (low)

Note: Pulumi publishes a machine-readable spec at https://api.pulumi.com/api/openapi/pulumi-spec.json (referenced from the 'miscellaneous' doc page) - worth using for a full diff. The existing `resources` table comes from /api/orgs/{org}/search/resources, so resource search is already covered.

## Pylon — gaps

Today (13): `accounts`, `contacts`, `custom_fields`, `issue_statuses`, `issues`, `knowledge_bases`, `macros`, `tags`, `tasks`, `teams`, `ticket_forms`, `user_roles`, `users`

Diffed against: <https://api.usepylon.com/openapi.json>

- [ ] `GET /issues/{id}/messages` — the actual conversation messages behind each issue - response times, volume, and content analysis all need this (high)
- [ ] `GET /surveys/{id}/responses` — CSAT survey responses, the headline support-quality metric (high)
- [ ] `GET /knowledge-bases/{id}/articles` — article inventory per knowledge base; the knowledge_bases table alone has no content rows (high)
- [ ] `GET /surveys` — survey definitions that give the responses their questions and scales (medium)
- [ ] `GET /accounts/{account_id}/relationships` — account hierarchy (parent/child orgs), needed to roll ticket volume up to a customer group (medium)
- [ ] `GET /issues/{id}/threads` — per-issue thread breakdown across Slack/email channels (medium)
- [ ] `GET /custom-objects/{type}` — customer-defined object records already referenced from issues and accounts (medium)
- [ ] `GET /activity-types` — lookup resolving activity type IDs used across issues and accounts (medium)
- [ ] `GET /knowledge-bases/{id}/collections` — collection grouping for knowledge base articles (medium)
- [ ] `GET /issues/{id}/followers` — who is watching each ticket - useful for internal-involvement analysis (medium)
- [ ] `GET /tasks/{id}/comments` — comment history on the tasks already synced (low)
- [ ] `GET /audit-logs` — admin/config change history (low)

Note: Pylon publishes a full OpenAPI 3 spec at https://api.usepylon.com/openapi.json (89 paths, 49 with GET) - the docs site itself is GitBook and does not serve it. Top-level coverage is good; every gap is a sub-resource or a second-tier collection.

## PyPI — adequate

Today (3): `projects`, `releases`, `vulnerabilities`

Diffed against: <https://docs.pypi.org/api/>

No material gaps found.

Note: PyPI's public API is genuinely small: the JSON API (project + release), the Index API (/simple/), a /stats/ endpoint (top-100 packages by size only) and the Integrity API (per-file provenance attestations), plus RSS feeds. The source already flattens the JSON API to one row per distribution file, so projects/releases/vulnerabilities covers the analytically useful surface. Worth knowing: download counts - the metric users actually want - are not exposed by PyPI's API at all (BigQuery public dataset or the third-party pypistats.org API), so that is a product decision rather than a missing endpoint.

## Qualaroo — gaps

Today (1): `nudges`

Diffed against: <https://help.qualaroo.com/hc/en-us/articles/201969438-The-REST-Reporting-API>

- [ ] `GET /nudges/{nudge_id}/responses.json` — the survey answers themselves - the only analytical data the Reporting API exposes; today the source syncs survey definitions with no responses (high)

Note: The REST Reporting API is essentially two endpoints (nudges list, and per-nudge responses with start_date/end_date/offset/limit paging). The source's settings define only the nudges endpoint - no dynamic table discovery - so the entire response dataset is unavailable. Adding it requires a fan-out over nudge IDs, same shape as other per-parent sources.

## QualysVmdr — gaps

Today (4): `host_list_detection`, `hosts`, `knowledge_base`, `scans`

Diffed against: <https://cdn2.qualys.com/docs/qualys-api-vmpc-user-guide.pdf>

- [ ] `GET /api/2.0/fo/asset/group/ (action=list)` — asset group lookup that resolves the group IDs/names hosts are organized by - the main grouping dimension for vulnerability reporting (high)
- [ ] `GET /api/2.0/fo/report/ (action=list, and action=fetch for a report's rows)` — the report inventory and generated report output, including scorecard and remediation reports (medium)
- [ ] `GET /api/2.0/fo/appliance/ (action=list)` — scanner appliance lookup that names the appliance referenced on each scan row (medium)
- [ ] `GET /api/2.0/fo/asset/ip/ (action=list)` — the subscription's tracked IP inventory, including IPs never yet scanned - gives coverage denominators (medium)
- [ ] `GET /api/2.0/fo/activity_log/ (action=list)` — user activity log for who ran or changed what, the audit dimension of the platform (medium)
- [ ] `GET /api/2.0/fo/schedule/scan/ (action=list)` — scheduled scan definitions that explain the cadence behind the scans table (low)
- [ ] `GET /api/2.0/fo/compliance/posture/info/ (action=list)` — per-host control pass/fail posture for Policy Compliance subscriptions (low)
- [ ] `GET /api/2.0/fo/compliance/policy/ (action=list)` — policy definitions lookup naming the policies in posture data (low)
- [ ] `GET /api/2.0/fo/asset/excluded_ip/ (action=list)` — excluded IPs, needed to explain gaps in host coverage (low)
- [ ] `GET /api/2.0/fo/qid/search_list/static/ and /dynamic/` — QID search lists that group vulnerabilities into named sets used by option profiles and reports (low)

Note: docs.qualys.com is a RoboHelp frameset that yields no endpoint list to curl; the authoritative inventory is the VM/PC API v2 user guide PDF (linked above), which enumerates every /api/2.0/fo/\* path. Credential/auth records (/api/2.0/fo/auth/\*) and option profiles are deliberately excluded as config. Asset tags live in a separate Qualys Asset Management API base (/qps/rest/2.0/search/am/tag) that this guide does not cover - not verified here, but likely the highest-value lookup after asset groups.

## Railway — gaps

Today (6): `deployments`, `environments`, `project_members`, `projects`, `services`, `volumes`

Diffed against: <https://backboard.railway.com/graphql/v2>

- [ ] `usage / projectServiceUsage / estimatedUsage` — Railway's headline metric - cost and resource usage per project/service/workspace; currently no spend data at all (high)
- [ ] `events` — Project event/activity stream - the audit-style timeline of what changed and when (high)
- [ ] `metrics` — CPU/memory/network/disk metrics per project, environment and service - core observability data (high)
- [ ] `deploymentEvents` — State-transition history for each deployment we already sync, enabling deploy-duration and failure analysis (high)
- [ ] `serviceInstance` — Lookup resolving the service x environment pair that deployments already carry IDs for (high)
- [ ] `auditLogs` — Workspace-level audit trail of who did what, for compliance and change analysis (medium)
- [ ] `httpMetrics / httpMetricsGroupedByStatus / httpDurationMetrics` — Request volume, status-code breakdown and latency percentiles per service (medium)
- [ ] `volumeInstance / volumeInstanceBackupList` — Per-environment volume instances and backups that resolve the volume IDs already synced (medium)
- [ ] `workspace` — Lookup table resolving the workspace/team that every project belongs to (medium)
- [ ] `deploymentTriggers` — Explains what caused each deployment (branch, PR, check suite) (medium)
- [ ] `httpLogs / deploymentLogs` — Request and deployment log streams for error and traffic analysis (low)
- [ ] `regions` — Small lookup resolving region codes on services and volumes (low)

Note: No published SDL file; I ran an unauthenticated GraphQL introspection query against the public API endpoint (backboard.railway.com/graphql/v2) and read the 137 root Query fields. PostHog's source issues 6 static GraphQL queries (products/warehouse_sources/.../sources/railway/) with no dynamic discovery. Railway's biggest analytical surfaces (cost/usage and metrics) are entirely absent today.

## Ramp — **thin**

Today (5): `cards`, `departments`, `reimbursements`, `transactions`, `users`

Diffed against: <https://docs.ramp.com/openapi/developer-api.json>

- [ ] `vendors (and vendors/{id}/contacts, /accounts)` — Lookup table resolving the vendor IDs carried on bills, transactions and purchase orders (high)
- [ ] `merchants` — Lookup resolving merchant IDs on every transaction - required for any spend-by-merchant analysis (high)
- [ ] `bills (and bills/drafts)` — Accounts-payable bills are a core Ramp spend object entirely missing from the warehouse (high)
- [ ] `accounting/accounts` — General-ledger account lookup that resolves the accounting codes applied to transactions (high)
- [ ] `locations` — Lookup resolving location IDs on transactions, users and cards (high)
- [ ] `entities` — Legal-entity lookup needed to split spend by entity in multi-entity orgs (high)
- [ ] `transfers` — Money movement in and out of the Ramp balance - the settlement side of card spend (medium)
- [ ] `statements` — Billing-period statements that reconcile transactions to what was actually charged (medium)
- [ ] `cashbacks` — Rewards earned per period, a headline Ramp value metric (medium)
- [ ] `accounting/fields and accounting/field-options` — Custom accounting dimensions and their allowed values - the breakdown dimensions for coded spend (medium)
- [ ] `receipts and item-receipts` — Receipt records and line-item detail attached to transactions, for compliance reporting (medium)
- [ ] `spend-programs / unified-requests` — Spend limits and the approval-request stream that explains why spend was allowed or blocked (medium)

Note: Ramp publishes a full OpenAPI spec (2.1 MB) plus llms-api.txt; the docs HTML explicitly points machine readers at /openapi/developer-api.json. The spec has ~95 GET paths across ~40 resources; PostHog exposes 5. Also note PostHog syncs the legacy /cards path, which no longer appears in the current spec (now /cards/physical and /cards/virtual) - worth confirming it still returns data.

## Rapid7 InsightVM — gaps

Diffed against: <https://help.rapid7.com/insightvm/en-us/api/insightvm-api-v4.json>

- [ ] `sites (POST /vm/v4/integration/sites)` — Lookup table resolving the site IDs carried on every asset we already sync (high)
- [ ] `scan (GET /vm/v4/integration/scan)` — Scan history - when each site was assessed, which is needed to judge how stale asset and vulnerability data is (medium)
- [ ] `scan/engine` — Lookup resolving the engine that produced each scan (low)

Note: PostHog targets the InsightVM Cloud Integrations API (/vm/v4/integration on \*.api.insight.rapid7.com), whose spec exposes only 5 resources: assets, sites, vulnerabilities, scan and scan/engine. So 2 of 5 is not as thin as it looks. The much larger on-prem console API v3 (207 paths - solutions, tags, asset_groups, policies, exploits, vulnerability_exceptions, per-asset findings) is a different product surface at help.rapid7.com/insightvm/en-us/api/api-v3.json requiring a console host and Basic auth; adding it would be a new source variant, not extra endpoints on this one. Endpoints are static (products/warehouse_sources/.../sources/rapid7_insightvm/settings.py), no dynamic discovery.

## Raygun — gaps

Today (6): `applications`, `customers`, `deployments`, `error_groups`, `pages`, `sessions`

Diffed against: <https://api.raygun.com/v3/raygun-openapi-spec.json>

- [ ] `applications/{id}/error-groups/{id}/instances` — Individual error occurrences with stack trace, environment and user context - the event-level data under the groups we already sync (high)
- [ ] `metrics/{application}/errors/time-series` — Raygun's headline error-rate metric, pre-aggregated over time (medium)
- [ ] `applications/{id}/deployments/{id}/error-groups` — Maps error groups to the deployment that introduced them, the core regression-detection join (medium)
- [ ] `metrics/{application}/pages/time-series and /pages/histogram` — Real user monitoring page-load performance over time and its distribution (medium)
- [ ] `teams` — Lookup resolving team ownership of applications (low)

Note: Spec URL is not linked from the product docs page; found it by reading the Swagger UI bootstrap at https://api.raygun.com/v3/swagger/index.js. Coverage of the top-level collections is good - the gap is one level down, at error instances and the metrics endpoints.

## Razorpay — gaps

Today (11): `Customers`, `Disputes`, `Invoices`, `Items`, `Orders`, `Payments`, `Plans`, `Refunds`, `Settlements`, `Subscriptions`, `VirtualAccounts`

Diffed against: <https://razorpay.com/docs/build/sitemap/razorpay/IN/urls.txt>

- [ ] `settlements/recon (settlement reconciliation report)` — Per-transaction settlement breakdown with fees and tax - the headline reconciliation report for finance users, not derivable from the settlement summary we sync (high)
- [ ] `payment_links` — Payment Links are a primary collection channel with their own conversion funnel and are entirely absent (high)
- [ ] `transfers and reversals (Route)` — Marketplace split-payment transfers and their reversals - the line-item breakdown of how each payment was divided (medium)
- [ ] `qr_codes` — QR code collection channel and its associated payments (medium)
- [ ] `linked_accounts (Route)` — Lookup resolving the linked-account IDs that Route transfers point at (medium)
- [ ] `payouts (RazorpayX)` — Outbound money movement; the payables counterpart to the payments already synced (medium)
- [ ] `x/transactions (RazorpayX)` — Bank account transaction ledger for balance and cash-flow reporting (medium)
- [ ] `contacts and fund_accounts (RazorpayX)` — Lookup tables resolving the payee IDs on payouts (medium)
- [ ] `subscriptions add-ons` — Line-item charges added to subscriptions we already sync, needed for correct MRR math (medium)
- [ ] `settlements/instant` — Instant settlement records with their own fee structure, separate from standard settlements (low)
- [ ] `payments/downtime` — Payment-method downtime windows that explain dips in success rate (low)
- [ ] `customers/{id}/bank_accounts and tokens` — Stored payment instrument lookups for repeat-purchase analysis (low)

Note: No OpenAPI spec is published; the docs site is a JS shell. I enumerated the API reference from Razorpay's own published sitemap URL list (450+ /docs/api/ pages) and cross-checked razorpay.com/docs/llms.txt. Coverage of the classic payments objects is genuinely good - the gaps are reconciliation, payment links, Route, and the RazorpayX banking product (which shares the same api.razorpay.com host and key).

## Recharge — gaps

Today (10): `addresses`, `charges`, `collections`, `customers`, `discounts`, `onetimes`, `orders`, `payment_methods`, `products`, `subscriptions`

Diffed against: <https://developer.rechargepayments.com/2021-11>

- [ ] `plans` — Lookup table resolving the plan IDs carried on subscriptions and onetimes (high)
- [ ] `events` — Recharge's account event log - subscription state transitions, cancellations and churn reasons over time (high)
- [ ] `credit_accounts and credit_adjustments` — Customer store-credit ledger; adjustments are the transaction-level rows behind each balance (medium)
- [ ] `bundle_selections` — Line-item contents of bundle subscriptions - without it a bundle subscription has no product breakdown (medium)
- [ ] `checkouts` — Pre-conversion checkout records, required for abandoned-checkout and funnel analysis (medium)
- [ ] `customer_entitlements` — Membership/perk entitlements per customer, a membership-program breakdown dimension (medium)
- [ ] `metafields` — Custom key-value fields attached to customers, subscriptions and addresses that often hold merchant-specific segmentation (low)
- [ ] `notifications` — Transactional notification history per customer, useful for correlating comms with churn (low)

Note: No OpenAPI spec is served (openapi.json 404s). The docs are a Nuxt SSR app; I extracted the complete 2021-11 reference nav from the embedded \_\_NUXT\_\_ payload - 24 API sections. PostHog covers 10 of them. Note the repo already carries products/warehouse_sources/.../sources/recharge/api_inventory.md, which may pre-date some of these.

## Recreation.gov — gaps

Diffed against: <https://ridb.recreation.gov/shared/swagger/ridb.yaml>

- [ ] `/reservations` — The only transactional table in RIDB - actual bookings by date; everything currently synced is static reference data (high)
- [ ] `/campsites/{id}/attributes` — Per-campsite attribute breakdown dimensions (hookups, max occupancy, site type) that make campsite data filterable (medium)
- [ ] `/permitentrances/{id}/zones` — Lookup resolving the zones under permit entrances already synced (medium)
- [ ] `/permitentrances/{id}/attributes and /tours/{id}/attributes` — Attribute breakdown dimensions for permits and tours, matching the campsite attributes pattern (low)
- [ ] `Availability API: /api/availability/camping/{facilityId} and /ticket/{facilityId}` — Site-level availability by month - the demand signal that pairs with the facility data already synced (separate spec, tiered key) (low)

Note: The documented spec path (ridb.recreation.gov/docs/ridb_swagger.json) is dead; the live OpenAPI 3.0 spec is at /shared/swagger/ridb.yaml, found by reading the docs SPA bundle. Coverage of the reference-data collections is essentially complete - every top-level RIDB collection except reservations is already synced. There is also a separate Availability API spec at /shared/swagger/availability.yaml (camping and ticket availability, per-facility per-month) behind a higher API-key tier.

## Recruitee — gaps

Today (4): `candidates`, `departments`, `offers`, `placements`

Diffed against: <https://docs.recruitee.com/reference>

- [ ] `GET /locations` — Lookup table resolving the location IDs carried on offers we already sync (high)
- [ ] `GET /timeline` — Hiring activity/event stream - the state-transition history behind candidates and placements (high)
- [ ] `GET /candidates/{id}/notes` — Recruiter notes per candidate, the qualitative record attached to candidates already synced (medium)
- [ ] `POST /analytics (job campaign analytics)` — Sourcing and job-campaign performance breakdowns - the vendor's own reporting dimensions (medium)
- [ ] `GET /candidates/{id}/reports` — Assessment and screening report results attached to candidates (low)

Note: The two URLs recorded in the source config (docs.recruitee.com/reference/candidates-index, /departments-index) both 404 - the docs were re-slugged. I enumerated the live ReadMe sidebar tree from the /reference page payload: the public ATS API documents candidates (+notes, +search), offers, locations, departments, attachments, timeline and analytics. PostHog also syncs /placements, which is not in the public reference at all, so the vendor's published surface is narrower than what the source actually reaches - treat the doc as a lower bound.

## Recurly — gaps

Today (16): `accounts`, `acquisitions`, `add_ons`, `coupons`, `credit_payments`, `dunning_campaigns`, `external_subscriptions`, `gift_cards`, `invoices`, `items`, `line_items`, `measured_units`, `plans`, `shipping_methods`, `subscriptions`, `transactions`

Diffed against: <https://raw.githubusercontent.com/recurly/recurly-client-python/master/openapi/api.yaml>

- [ ] `/accounts/{account_id}/coupon_redemptions (also /invoices/{id}/coupon_redemptions, /subscriptions/{id}/coupon_redemptions)` — the join table between coupons and accounts/invoices/subscriptions - without it synced coupons cannot be attributed to revenue (high)
- [ ] `/business_entities` — lookup resolving the business_entity_id carried on accounts, invoices and subscriptions (high)
- [ ] `/subscriptions/{subscription_id}/add_ons/{add_on_id}/usage` — usage records behind usage-based billing; the metered quantity that produces invoice line items (high)
- [ ] `/external_invoices (and /external_subscriptions/{id}/external_invoices)` — app-store revenue for the external_subscriptions already synced (high)
- [ ] `/external_products and /external_products/{id}/external_product_references` — lookup resolving the product/reference IDs on external subscriptions (medium)
- [ ] `/accounts/{account_id}/billing_infos` — payment method type, card brand and expiry per account - drives churn and decline analysis (medium)
- [ ] `/accounts/{account_id}/balance` — outstanding balance per account in each currency, the standard AR metric (medium)
- [ ] `/coupons/{coupon_id}/unique_coupon_codes` — resolves the individual redeemed code back to its bulk coupon (medium)
- [ ] `/custom_field_definitions` — lookup naming and typing the custom fields embedded on accounts, subscriptions and items (medium)
- [ ] `/general_ledger_accounts` — lookup for revenue/liability GL codes referenced by items and line items (medium)
- [ ] `/accounts/{account_id}/shipping_addresses` — geography dimension for shipping-method and tax breakdowns (medium)
- [ ] `/price_segments` — lookup for the price segment applied to plans and add-ons (low)

## Render — gaps

Today (12): `custom_domains`, `deploys`, `disks`, `env_groups`, `environments`, `events`, `jobs`, `key_value`, `owners`, `postgres`, `projects`, `services`

Diffed against: <https://api-docs.render.com/reference/introduction>

- [ ] `/services/{id}/instances (list-instances)` — per-instance rows behind each service - the unit that scaling and cost analysis is done on (high)
- [ ] `/owners/{ownerId}/members (retrieve-owner-members)` — membership table linking users to the owners/workspaces already synced (high)
- [ ] `/owners/{ownerId}/audit-logs and /organizations/{id}/audit-logs` — who changed what and when - the change history for services, env groups and members (high)
- [ ] `/metrics/* (http-requests, http-latency, cpu, memory, instance-count, bandwidth)` — the headline observability time series per service; nothing in the current tables carries runtime metrics (high)
- [ ] `/blueprints and /blueprints/{id}/syncs` — IaC definitions plus their sync history, the deploy path for most multi-service accounts (medium)
- [ ] `/snapshots (list-snapshots)` — backup/restore point history for Postgres instances already synced (medium)
- [ ] `/postgres/{id}/top-queries, /table-scans, /processes` — database performance insight rows - the reason most people query Render data at all (medium)
- [ ] `/tasks and /task-runs (listtasks, listtaskruns)` — Render Tasks execution history, analogous to the jobs table already exposed (medium)
- [ ] `/workflows and /workflows/{id}/versions` — workflow definitions and version history for the newer Workflows product (medium)
- [ ] `/redis (list-redis)` — legacy Redis instances are a separate resource from key_value and are invisible today (medium)
- [ ] `/maintenance (list-maintenance)` — scheduled maintenance windows, needed to explain downtime in deploy/event analysis (low)
- [ ] `/logs (list-logs)` — application and request logs joinable to services and deploys (low)

Note: Render's ReadMe-hosted OpenAPI file (api-docs.render.com/openapi/6140fb3daeae351056086186) now 404s; the resource list was read from the reference sidebar embedded in the introduction page.

## RentCast — gaps

Today (3): `properties`, `rental_listings`, `sale_listings`

Diffed against: <https://developers.rentcast.io/sitemap.xml>

- [ ] `/v1/markets (market statistics)` — zip-level rental and sale market aggregates plus history - the only aggregate dataset RentCast publishes and the natural join target for the listings already synced (high)

Note: The remaining uncovered endpoints - /v1/avm/value (value estimate) and /v1/avm/rent/long-term (rent estimate) - are per-address computations that require an address or lat/long on every call, so they do not map to a syncable table; they are deliberately excluded rather than overlooked. Static 3-table source, no dynamic discovery in products/warehouse_sources/backend/temporal/data_imports/sources/rentcast.

## Replicate — gaps

Today (6): `account`, `deployments`, `hardware`, `models`, `predictions`, `trainings`

Diffed against: <https://api.replicate.com/openapi.json>

- [ ] `/models/{model_owner}/{model_name}/versions` — lookup resolving the version ID stamped on every prediction and training row already synced (high)
- [ ] `/collections and /collections/{collection_slug}` — the vendor's own model taxonomy - gives a category dimension for grouping model and prediction usage (medium)
- [ ] `/files` — uploaded input/output file records with size and expiry, joinable to predictions (low)

## ReplyIo — gaps

Today (11): `account_lists`, `accounts`, `contact_lists`, `contacts`, `custom_fields`, `email_accounts`, `email_template_folders`, `email_templates`, `inbox_threads`, `sequences`, `tasks`

Diffed against: <https://docs.reply.io/llms.txt>

- [ ] `reports/list-email-activity` — per-message send/open/click/reply/bounce events - the core outreach fact table (high)
- [ ] `sequence-contacts/list-contacts-in-sequence (and list-contacts-in-sequence-with-extended-state)` — membership table joining contacts to sequences with per-sequence status; without it sequences and contacts cannot be related (high)
- [ ] `sequence-steps/list-all-sequence-steps (and list-step-variants)` — lookup resolving the step and variant IDs referenced by activity, plus A/B variant analysis (high)
- [ ] `reports/list-meetings` — booked meetings, the outcome metric outreach performance is judged on (high)
- [ ] `sequences/get-stats-for-all-sequences` — vendor-computed per-sequence delivery and reply rates (high)
- [ ] `user-account/list-team-users` — lookup resolving the owner/user IDs carried on contacts, accounts, sequences and tasks (high)
- [ ] `inbox/list-messages-in-an-inbox-thread` — message-level rows under the inbox_threads already synced (medium)
- [ ] `inbox/list-inbox-categories` — lookup for the category IDs assigned to inbox threads (medium)
- [ ] `reports/list-call-activity` — call outcomes and durations, the phone channel equivalent of email activity (medium)
- [ ] `reports/list-linkedin-activity` — LinkedIn connect/message/InMail events for multichannel sequences (medium)
- [ ] `sequence-folders/list-all-sequence-folders` — lookup grouping sequences into folders for team-level rollups (medium)
- [ ] `linkedin-accounts/list-linkedin-accounts` — sending-account dimension for LinkedIn, mirroring email_accounts which is already synced (medium)

## Retently — gaps

Today (7): `campaigns`, `companies`, `customers`, `feedback`, `outbox`, `reports`, `templates`

Diffed against: <https://www.retently.com/api/>

- [ ] `GET /api/v2/nps/score, /csat/score, /ces/score, /star/score` — the vendor's headline metric - the aggregate NPS/CSAT/CES/star score the whole product exists to report (high)
- [ ] `GET /api/v2/trends and /api/v2/trends/{groupId}` — trend groups and their trends are the topic taxonomy behind feedback; a lookup that turns free-text feedback into a breakdown dimension (high)
- [ ] `GET /api/v2/suppressions/emails and /suppressions/domains` — suppressed recipients explain gaps in outbox delivery coverage (low)

## Rippling — gaps

Today (9): `companies`, `compensations`, `departments`, `employment_types`, `levels`, `teams`, `users`, `work_locations`, `workers`

Diffed against: <https://developer.rippling.com/sitemap.xml>

- [ ] `list-time-entries (and get-time-entries)` — clock-in/clock-out records - the highest-volume fact table in Rippling and the basis of all labor analysis (high)
- [ ] `list-leave-requests` — time-off requests with status and dates, the core absence dataset (high)
- [ ] `list-worker-payroll-records` — per-worker payroll line items - actual pay, taxes and deductions, not just contracted compensation (high)
- [ ] `list-payroll-runs` — the payroll period header that payroll records roll up to (high)
- [ ] `list-worker-changes (and list-worker-change-fields)` — the transition history for workers - promotions, transfers, terminations; today only current state is synced (high)
- [ ] `list-leave-balances (and list-leave-accruals)` — accrued and remaining balance per worker per policy, the standard PTO liability metric (high)
- [ ] `list-titles` — lookup resolving the job title ID carried on workers (high)
- [ ] `list-tracks` — lookup grouping the levels table already synced into career tracks (high)
- [ ] `list-leave-types` — lookup naming the leave policy IDs on leave requests and balances (medium)
- [ ] `list-legal-entities and list-company-legal-entities` — lookup resolving the legal entity on workers and payroll, required for multi-entity reporting (medium)
- [ ] `list-job-codes and list-job-assignments` — lookup resolving the job code stamped on time entries and shift assignments (medium)
- [ ] `list-time-cards` — approved timesheet totals per period, the aggregate view of time entries (medium)

Note: Rippling exposes three distinct API surfaces (base-api, company-api, rest-api). The PostHog tables match the modern rest-api (Rippling Platform API), so the diff was taken against the ~230 rest-api reference pages in the sitemap; the base-api/company-api surfaces are older equivalents and were not counted as gaps.

## RKICovid — gaps

Today (11): `districts`, `germany`, `germany_age_groups`, `germany_history_cases`, `germany_history_deaths`, `germany_history_frozen_incidence`, `germany_history_hospitalization`, `germany_history_incidence`, `germany_history_recovered`, `states`, `testing_history`

Diffed against: <https://api.corona-zahlen.org/docs/>

- [ ] `GET /vaccinations` — national vaccination totals and quotas - an entire headline dataset with no table today (high)
- [ ] `GET /vaccinations/history/:days` — daily vaccination time series, the analytical form of the vaccination data (high)
- [ ] `GET /vaccinations/states/:state` — per-state vaccination breakdown, the standard comparison dimension (high)
- [ ] `GET /states/history/cases/:days` — per-state case time series; only Germany-level history is synced, so no state comparison over time is possible (high)
- [ ] `GET /states/history/deaths/:days` — per-state death time series to match the national germany_history_deaths table (high)
- [ ] `GET /states/history/incidence/:days` — per-state 7-day incidence, the metric the whole dataset is organized around (high)
- [ ] `GET /districts/history/cases/:days` — per-district case time series - the finest granularity the API offers and the reason to use it over aggregate sources (high)
- [ ] `GET /districts/history/incidence/:days` — per-district incidence over time, the main district-level reporting metric (high)
- [ ] `GET /germany/history/rValue/:days` — the reproduction number time series, a headline national metric with no equivalent column elsewhere (medium)
- [ ] `GET /states/age-groups` — age-group breakdown per state; the source has only the Germany-level age groups (medium)
- [ ] `GET /districts/age-groups` — age-group breakdown per district (medium)
- [ ] `GET /states/history/hospitalization/:days` — per-state hospitalization time series, matching the national hospitalization table (medium)

Note: Coverage is national-only: every history table synced is a /germany/history/\* endpoint, while the API offers the identical history families (cases, deaths, recovered, incidence, frozen-incidence, hospitalization) at /states/history/\* and /districts/history/\*, plus a whole /vaccinations tree and /maps image endpoints (not warehouse-relevant). Also missing at state/district level: history/recovered and history/frozen-incidence, omitted from the list above only to stay within 12 entries.

## Roark — gaps

Today (12): `agent`, `agent_endpoint`, `call`, `chat`, `issue`, `knowledge_base`, `metric_collection_job`, `metric_definition`, `persona`, `run_plan`, `simulation_plan_job`, `simulation_scenario`

Diffed against: <https://docs.roark.ai/llms.txt>

- [ ] `call/list-call-metrics (GET /calls/{id}/metrics)` — the scored per-call metric values - the product's headline output and the only numeric quality data (high)
- [ ] `metric-collection-job/get-metric-values-produced-by-a-metric-collection-job` — metric values per collection job, giving metric history over time rather than only the latest run (high)
- [ ] `call/list-call-evaluation-runs` — pass/fail evaluation results per call, the row grain quality dashboards are built on (high)
- [ ] `call/get-call-transcript` — turn-level transcript for the calls already synced; enables text and duration analysis (high)
- [ ] `call/list-call-sentiment-runs` — sentiment scores and key phrases per call, a standard breakdown dimension (high)
- [ ] `chat/list-chat-metrics` — the chat-channel equivalent of call metrics; chats are synced but their scores are not (medium)
- [ ] `chat/get-chat-transcript` — message-level content under the chats already synced (medium)
- [ ] `metric-policy/list-metric-policies` — lookup defining the thresholds that turn raw metric values into pass/fail (medium)

## Rocketlane — gaps

Today (5): `fields`, `projects`, `tasks`, `time_entries`, `users`

Diffed against: <https://developer.rocketlane.com/reference/get-all-projects>

- [ ] `invoices (search-invoices / get-invoice)` — billing and revenue per project, absent today (high)
- [ ] `invoices/{id}/line-items (get-invoice-line-items)` — line-item revenue breakdown against projects and tasks (high)
- [ ] `time-entry-categories (get-time-entry-categories)` — lookup table resolving the category IDs carried on time_entries we already sync (high)
- [ ] `phases (get-all-phases)` — lookup table resolving the phase IDs on tasks and projects we already sync (high)
- [ ] `resource-allocations (get-all-resource-allocations)` — planned capacity to compare against logged time entries (high)
- [ ] `invoices/{id}/payments (get-invoice-payments)` — cash collection and AR aging (medium)
- [ ] `time-offs (get-all-timeoffs)` — needed for correct utilization and availability math (medium)
- [ ] `spaces (get-all-spaces)` — lookup resolving the space grouping projects and documents belong to (medium)
- [ ] `placeholders (get-placeholders)` — unfilled roles on allocations, useful for staffing gap reporting (low)
- [ ] `space-documents (get-all-space-documents)` — document inventory per space (low)

Note: Static endpoint catalog; no dynamic table discovery. Docs are a ReadMe site with no public OpenAPI file, so the resource list was read from the reference index links.

## Rollbar — gaps

Today (4): `deploys`, `environments`, `items`, `occurrences`

Diffed against: <https://docs.rollbar.com/reference>

- [ ] `projects (list-all-projects)` — lookup table resolving the project IDs carried on items and deploys we already sync (high)
- [ ] `item occurrence counts (get-occurrence-counts)` — the per-item error-volume time series, Rollbar's headline metric (high)
- [ ] `activated item counts (get-activated-item-counts)` — new-error-rate trend over time, the standard regression signal (high)
- [ ] `users (list-all-users)` — lookup resolving assignee and resolver IDs on items (medium)
- [ ] `teams (list-all-teams)` — lookup for ownership attribution of items and projects (medium)
- [ ] `top active items (get-top-active-items)` — ranked noisiest errors per period without recomputing from occurrences (medium)
- [ ] `teams/{id}/users (list-a-teams-users)` — membership table joining users to teams for ownership rollups (medium)
- [ ] `teams/{id}/projects (list-a-teams-projects)` — membership table mapping team ownership onto projects (low)

Note: The connector authenticates with a Rollbar project access token, while projects/users/teams/counts live on the account-level API and need an account access token — implementing these likely requires an extra credential field, not just a new endpoint.

## Rootly — gaps

Today (16): `action_items`, `alerts`, `causes`, `environments`, `escalation_policies`, `functionalities`, `incident_types`, `incidents`, `post_mortems`, `pulses`, `schedules`, `services`, `severities`, `teams`, `users`, `workflows`

Diffed against: <https://docs.rootly.com/api-reference>

- [ ] `incident_events (list-incident-events)` — the incident timeline, the core state/transition history for MTTA and MTTR analysis (high)
- [ ] `statuses (list-statuses)` — lookup table resolving the status IDs on incidents we already sync (high)
- [ ] `shifts (list-shifts)` — actual on-call shift records, the basis of on-call load and fairness reporting (high)
- [ ] `alert_events (list-alert-events)` — alert lifecycle history (ack, escalate, resolve) for the alerts we already sync (high)
- [ ] `incident_roles (list-incident-roles)` — lookup resolving role assignments on incidents (commander, comms lead) (high)
- [ ] `on_calls (list-on-calls)` — who was on call for a given schedule and window (medium)
- [ ] `schedule_rotations (list-schedule-rotations)` — resolves the schedules table into rotation structure (medium)
- [ ] `schedule_rotation_users (list-schedule-rotation-users)` — membership table joining users to rotations (medium)
- [ ] `workflow_runs (list-workflow-runs)` — execution history for the workflows we already sync (medium)
- [ ] `sub_statuses (list-sub-statuses)` — lookup resolving incident sub-status IDs (medium)
- [ ] `incident_feedbacks (list-incident-feedbacks)` — post-incident satisfaction scoring (medium)
- [ ] `escalation_levels (list-escalation-levels-for-an-escalation-policy)` — resolves the escalation_policies we sync into their ordered levels and targets (medium)

Note: Rootly publishes no reachable OpenAPI file (api.rootly.com/v1/swagger.json and openapi.json both 404); the resource list was extracted from the ~550 endpoint links on the docs API-reference index. Rootly's API exposes roughly 100 resource groups, so the 16 synced tables cover core incident objects but almost none of the timeline, on-call, or lookup sub-resources.

## Rss — gaps

Today (3): `categories`, `episodes`, `podcasts`

Diffed against: <https://api.rss.com/v4/openapi.json>

- [ ] `locations (GET /v4/locations)` — lookup table resolving the location IDs carried on podcasts we already sync (high)
- [ ] `podcasts/{id}/collaborators` — membership table of who works on each podcast (high)
- [ ] `roles (GET /v4/roles)` — lookup resolving the role IDs on collaborators (medium)
- [ ] `podcasts/{id}/episodes/{id}/chapters` — per-episode chapter structure, a real sub-resource of data we already sync (medium)
- [ ] `podcasts/{id}/episodes/{id}/midrolls` — ad-insertion markers, the monetization dimension of each episode (medium)
- [ ] `podcasts/{id}/keywords` — discovery/SEO dimensions per podcast (medium)
- [ ] `podcasts/{id}/episodes/{id}/soundbites` — promo clip metadata per episode (low)
- [ ] `podcasts/{id}/episodes/{id}/transcript` — episode transcript text for content analysis (low)

Note: The v4 Core API exposes no download/listener analytics endpoint at all, so the biggest podcast metric is simply not available from this API. Static endpoint catalog, no dynamic discovery. Excluded from gaps: presigned asset uploads and the podcast TXT (DNS verification) records, which are plumbing.

## Rubygems — gaps

Today (2): `gems`, `versions`

Diffed against: <https://guides.rubygems.org/rubygems-org-api/>

- [ ] `gems/{name}/owners.json` — membership table of gem maintainers, the only ownership join available (high)
- [ ] `gems/{name}/reverse_dependencies.json` — downstream adoption of a gem, the main ecosystem-impact question (medium)
- [ ] `activity/just_updated.json and activity/latest.json` — feed of newly released and newly updated gems for ecosystem tracking (medium)
- [ ] `timeframe_versions.json` — all versions published in a time window, an ecosystem-wide release feed with a natural incremental cursor (medium)
- [ ] `owners/{handle}/gems.json` — inverse of the owners join, lists every gem for a maintainer (low)
- [ ] `profiles/{handle}.json` — lookup resolving owner handles to profile metadata (low)

Note: Per-version download counts are already included in the synced `versions` table, so the /api/v1/downloads endpoints are largely redundant. The API is small overall and the two synced tables cover the main objects; `search` was excluded as a query interface rather than a table, and web_hooks / api_key as plumbing.

## Ruddr — **thin**

Today (5): `clients`, `members`, `project_tasks`, `projects`, `time_entries`

Diffed against: <https://docs.ruddr.io/llms.txt>

- [ ] `invoices` — billing and revenue, entirely absent from the current 5 tables (high)
- [ ] `invoice-items` — line-item revenue tied back to projects and time entries (high)
- [ ] `allocations` — planned resource allocation to compare against logged time entries (high)
- [ ] `project-members` — membership table joining members to the projects we already sync (high)
- [ ] `opportunities` — the sales pipeline, a whole analytical domain currently unavailable (high)
- [ ] `opportunity-stages` — lookup table resolving the stage IDs carried on opportunities (high)
- [ ] `project-roles` — lookup resolving the role IDs on project members and time entries (high)
- [ ] `project-expenses` — cost side of project profitability (medium)
- [ ] `payments` — cash collection against invoices (medium)
- [ ] `timesheets` — submission and approval state wrapping the time entries we sync (medium)
- [ ] `project-health-reports` — periodic project status history, a natural trend series (medium)
- [ ] `practices` — lookup resolving the practice/org-unit IDs on members and projects (medium)

Note: Ruddr documents roughly 78 list endpoints; the connector exposes 5. Beyond the twelve listed, whole domains are unsynced: project budget items (service/product/other/expense, plus monthly variants), revenue recognition entries, revenue adjustments, credit notes, tax rates, cost periods, exchange rate periods, utilization target periods, contacts, companies, expense reports, holidays, skills, disciplines, job titles and member levels. Static endpoint catalog, no dynamic discovery.

## RunPod — adequate

Today (7): `billing_endpoints`, `billing_network_volumes`, `billing_pods`, `endpoints`, `network_volumes`, `pods`, `templates`

Diffed against: <https://rest.runpod.io/v1/openapi.json>

No material gaps found.

Note: The v1 REST OpenAPI spec lists only 7 GET-able collections: /pods, /endpoints, /networkvolumes, /templates, /billing/pods, /billing/endpoints, /billing/networkvolumes — all seven are already synced. The only uncovered collection is /containerregistryauth, which is credential plumbing and correctly excluded. Note RunPod also has a separate GraphQL API, but the REST spec is the documented public surface.

## SafetyCulture — gaps

Today (10): `actions`, `assets`, `groups`, `inspection_items`, `inspections`, `issues`, `schedules`, `sites`, `templates`, `users`

Diffed against: <https://developer.safetyculture.com/reference/thepubservice_feedactions>

- [ ] `feed/group_users` — membership table joining the users and groups we already sync (high)
- [ ] `feed/site_members` — membership table joining users to the sites we already sync (high)
- [ ] `feed/action_assignees` — resolves who each synced action is assigned to; actions are unattributable without it (high)
- [ ] `feed/issue_assignees` — same attribution join for the issues we already sync (high)
- [ ] `feed/schedule_occurrences` — actual scheduled occurrences, the only way to measure scheduled vs completed inspections (high)
- [ ] `feed/action_timeline_items` — state-transition history for actions, the basis of cycle-time analysis (high)
- [ ] `feed/training_course_progress` — training completion per user, a headline compliance metric (high)
- [ ] `feed/issue_timeline_items` — state-transition history for issues (medium)
- [ ] `feed/activity_log_events` — org-wide audit event stream for usage and adoption analysis (medium)
- [ ] `feed/investigations (plus investigation fields and relationships)` — incident investigation records linked to the issues and actions we sync (medium)
- [ ] `feed/assets_maintenance, feed/maintenance_plans, feed/maintenance_programs` — maintenance schedule and status for the assets we already sync (medium)
- [ ] `feed/contractor_companies and feed/contractor_company_user_memberships` — contractor org lookup plus its membership join (medium)

Note: SafetyCulture's warehouse-oriented surface is the /feed/\* family, and roughly 30 feed endpoints exist; the connector covers 10 of them (actions, assets, groups, inspection_items, inspections, issues, schedules, sites, templates, users) and none of the assignee, membership, or timeline joins. Also uncovered: feed/schedule_assignees, feed/action_fields, feed/document_types, feed/user_documents, feed/credentials, feed/credential_types, and the separate training-analytics service (lesson attempts, course statistics, survey answers). Static endpoint catalog, no dynamic discovery. feed/template_permissions was excluded as access-control plumbing.

## SageHR — gaps

Today (12): `document_categories`, `documents`, `employees`, `individual_allowances`, `leave_policies`, `leave_requests`, `offboarding_categories`, `onboarding_categories`, `positions`, `teams`, `terminated_employees`, `termination_reasons`

Diffed against: <https://jsapi.apiary.io/apis/sagehr.apib>

- [ ] `timesheets/workdays (GET /timesheets/workdays/)` — actual hours worked per employee per day — the core time-tracking fact table (high)
- [ ] `employees/{id}/compensations` — salary/compensation history per employee, needed for any pay or cost analysis (high)
- [ ] `employees/{id}/leave-management/balances` — remaining leave per employee per policy; leave_requests alone can't answer balance questions (high)
- [ ] `recruitment/positions/{id}/applicants` — hiring funnel — applicants per open role (high)
- [ ] `recruitment/positions` — open job requisitions; also the lookup that resolves position ids on applicants (medium)
- [ ] `timesheets/projects` — lookup resolving the project ids carried on workdays (medium)
- [ ] `timesheets/working_packages` — lookup resolving work package ids on timesheet entries (medium)
- [ ] `recruitment/applicants/{id}/actions` — applicant stage-transition history for time-to-hire metrics (medium)
- [ ] `performance/goals/quarterly-progress/company-goals` — company goal attainment, a headline performance metric (medium)
- [ ] `performance/goals/quarterly-progress/team-goals` — per-team goal progress, joins to the teams table already synced (medium)
- [ ] `performance/goals/quarterly-progress/individual-goals` — per-employee goal progress (medium)
- [ ] `employees/{id}/custom-fields` — customer-defined employee attributes not present on the base employee record (medium)

Note: The published Apiary host (sagehr.docs.apiary.io) 502s; the raw Swagger 2.0 blueprint is still served at https://jsapi.apiary.io/apis/sagehr.apib. Note the /vikarina/\* namespace is POST-only ingest, not queryable.

## Salesflare — gaps

Today (7): `accounts`, `contacts`, `opportunities`, `pipelines`, `tags`, `tasks`, `workflows`

Diffed against: <https://api.salesflare.com/openapi.json>

- [ ] `stages (GET /stages)` — lookup resolving the stage id on every opportunity already synced (high)
- [ ] `users (GET /users)` — lookup resolving owner/assignee ids on accounts, contacts, opportunities and tasks (high)
- [ ] `persons (GET /persons)` — the full people directory, broader than the contacts table (medium)
- [ ] `accounts/{id}/feed` — per-account activity timeline (the interaction history behind the CRM) (medium)
- [ ] `accounts/{id}/messages` — email/message log per account for engagement analysis (medium)
- [ ] `customfields/{itemClass}` — custom field definitions that resolve the custom keys stored on accounts, contacts and opportunities (medium)
- [ ] `groups (GET /groups)` — lookup for team/group membership on users (medium)
- [ ] `tags/{id}/usage` — tag-to-record counts, cheap breakdown dimension (low)
- [ ] `currencies (GET /currencies)` — lookup for currency codes on opportunity values (low)

Note: api.salesflare.com/swagger.json 404s; the live OpenAPI 3 spec is at /openapi.json. Meetings and calls are write-only (POST/PUT, no list endpoint), so they are not syncable.

## SalesLoft — gaps

Today (28): `account_stages`, `account_tiers`, `accounts`, `actions`, `cadence_memberships`, `cadences`, `call_data_records`, `call_dispositions`, `call_sentiments`, `calls`, `crm_activities`, `crm_users`, `custom_fields`, `email_template_attachments`, `email_templates`, `emails`, `groups`, `imports`, `meetings`, `notes`, `people`, `person_stages`, `phone_number_assignments`, `steps`, `successes`, `team_template_attachments`, `team_templates`, `users`

Diffed against: <https://developers.salesloft.com/docs/api/opportunities-index/>

- [ ] `opportunities` — core revenue object synced from the CRM; currently no way to tie cadence activity to pipeline (high)
- [ ] `opportunity_stages` — lookup resolving the stage id on every opportunity (high)
- [ ] `tasks` — the rep work queue — completion rates are a primary Salesloft metric (high)
- [ ] `activity_histories` — unified transition/activity timeline across people and accounts (high)
- [ ] `cadence_stats` — the vendor's headline cadence performance metric (opens, replies, conversions) (high)
- [ ] `tags` — lookup resolving tag ids attached to people, accounts and cadences (medium)
- [ ] `account_types` — lookup resolving the account_type id already carried on accounts (medium)
- [ ] `opportunity_people` — join table linking people to opportunities (medium)
- [ ] `calendar_events` — booked meetings and their outcomes beyond the meetings table (medium)
- [ ] `conversations / conversations_calls` — conversation intelligence records for call analysis (medium)
- [ ] `transcriptions` — call transcripts, the input for talk-track analysis (medium)
- [ ] `custom_roles` — lookup resolving the role assigned to each user (low)

Note: Salesloft publishes no OpenAPI file (api.salesloft.com/v2.json is auth-gated); the complete v2.0 resource list is rendered into the Docusaurus sidebar on every /docs/api/\*-index page. Excluded plumbing: webhook subscriptions, bulk jobs, external id configuration/mapping, redaction and right-to-be-forgotten, saved list views, recording settings.

## SavvyCal — adequate

Today (4): `events`, `links`, `webhooks`, `workflows`

Diffed against: <https://developers.savvycal.com/api/events>

No material gaps found.

Note: The whole REST API is six resource groups: Events, Scheduling Links, Current User, Time Zones, Webhooks, Workflows. PostHog already syncs four of them. The only remaining list endpoints are workflow rules (a sub-resource of workflows), the static IANA time-zone table, and the single-object current-user endpoint — none warrant a warehouse table.

## ScaleAI — gaps

Today (3): `batches`, `projects`, `tasks`

Diffed against: <https://api-reference.scale.com/llms.txt>

- [ ] `audits (GET /v1/audits?task_id=…)` — fixless audit records and feedback items — the input to Scale's quality scores, the platform's headline metric (medium)
- [ ] `batches/{name}/status` — per-batch task counts by state (pending/completed/error), a cheap progress breakdown (low)

Note: The v1 REST API is genuinely small: batches, projects, tasks, audits. GenAI Data Engine, GenAI Platform and Taxonomy Service are documented as guides with no listable REST collections. The audits endpoint requires a task_id or audit id, so it has to be driven off the already-synced tasks table rather than bulk-listed.

## Scaleway — **thin**

Today (10): `api_keys`, `applications`, `audit_trail_events`, `groups`, `instance_servers`, `invoices`, `policies`, `projects`, `ssh_keys`, `users`

Diffed against: <https://www.scaleway.com/en/developers/api/billing/v2beta1/schema.yml>

- [ ] `billing consumptions (GET /billing/v2beta1/consumptions)` — spend per product category per month — the headline FinOps number; invoices alone give only totals (high)
- [ ] `kubernetes clusters (GET /k8s/v1/regions/{region}/clusters)` — major compute inventory missing entirely from the resource picture (high)
- [ ] `kubernetes pools and nodes (/k8s/v1/regions/{region}/pools, /nodes)` — node-level inventory that attributes k8s cost and capacity (high)
- [ ] `managed database instances (GET /rdb/v1/regions/{region}/instances)` — managed Postgres/MySQL fleet, a large recurring cost line (high)
- [ ] `instance volumes (GET /instance/v1/zones/{zone}/volumes)` — storage attached to the servers already synced; needed to attribute storage spend (high)
- [ ] `instance images (GET /instance/v1/zones/{zone}/images)` — lookup resolving the image id carried on every synced server (medium)
- [ ] `instance snapshots (GET /instance/v1/zones/{zone}/snapshots)` — snapshot inventory, a common source of untracked storage cost (medium)
- [ ] `instance IPs (GET /instance/v1/zones/{zone}/ips)` — flexible IP inventory and attachment state, billed per unattached IP (medium)
- [ ] `billing discounts (GET /billing/v2beta1/discounts)` — discounts applied to invoices; without it invoiced totals cannot be reconciled (medium)
- [ ] `rdb backups and snapshots (/rdb/v1/regions/{region}/backups, /snapshots)` — database backup inventory and retention footprint (medium)
- [ ] `instance security groups (GET /instance/v1/zones/{zone}/security_groups)` — lookup resolving the security group referenced by each server, useful for posture reporting (low)
- [ ] `billing taxes (GET /billing/v2beta1/taxes)` — tax lines needed to reconcile gross vs net invoice amounts (low)

Note: Scaleway is a full cloud provider API — dozens of product APIs (Elastic Metal, Block/File/Object Storage, Container Registry, VPC/IPAM, Load Balancer, Serverless Functions/Containers/Jobs, Cockpit, Environmental Footprint, Secret/Key Manager, Domains, Transactional Email). The connector's 10 tables cover IAM, account projects, invoices, one compute resource and audit trail. Endpoints above were read from the per-product OpenAPI specs: /en/developers/api/billing/v2beta1/schema.yml, /instance/v1/schema.yml, /kubernetes/v1/schema.yml, /managed-database-postgre-mysql/v1/schema.yml. Note instance endpoints are zone-scoped and k8s/rdb are region-scoped, so each needs the same fan-out the existing instance_servers endpoint already does.

## Secoda — gaps

Today (6): `collections`, `columns`, `groups`, `tables`, `tags`, `users`

Diffed against: <https://docs.secoda.co/llms.txt>

- [ ] `databases (GET /api/v1/database/databases)` — top of the asset hierarchy; lookup resolving the parent of every schema and table already synced (high)
- [ ] `schemas (GET /api/v1/database/schemas)` — lookup resolving the schema id carried on every synced table (high)
- [ ] `integrations (GET /api/v1/integration/integrations)` — lookup resolving the integration id present on every resource, i.e. which source system an asset came from (high)
- [ ] `lineage (GET /api/v1/lineage/manual/)` — the dependency graph between resources — the core analytical object of a catalog (high)
- [ ] `monitors and incidents (/api/v1/monitor/monitors, /monitor/incidents)` — data-quality monitors and the incidents they raise, Secoda's headline reliability metric (high)
- [ ] `monitor measurements (GET /api/v1/monitor/measurements)` — the time series behind each monitor; required for any quality trend analysis (high)
- [ ] `queries (GET /api/v1/query/queries)` — query history driving table popularity and usage rankings (medium)
- [ ] `dashboards (GET /api/v1/dashboard/dashboards)` — BI assets, the downstream consumers in lineage (medium)
- [ ] `charts (GET /api/v1/dashboard/charts)` — chart-level assets under dashboards, needed for column-to-chart impact analysis (medium)
- [ ] `events and event properties (/api/v1/event/events, /event/event_properties, /event/category)` — the event taxonomy tracked in the catalog plus its lookup categories (medium)
- [ ] `audit logs and resource logs (/api/v1/activity_log/audit_logs/, /resource_logs/)` — who touched which asset when — governance and adoption reporting (medium)
- [ ] `custom properties (GET /api/v1/resource/all_v2/custom_properties/)` — lookup resolving customer-defined property values attached to tables and columns (medium)

Note: Each docs page embeds its own OpenAPI fragment (fetch the .md variant, e.g. /api/reference/monitors.md, to read paths). Also available but lower value: teams (/auth/teams/), documents, questions and replies, and the generic /resource/all_v2 super-list.

## Secureframe — gaps

Today (13): `cloud_resources`, `controls`, `devices`, `framework_requirements`, `frameworks`, `integration_connections`, `repositories`, `risks`, `tests`, `tprm_vendors`, `user_accounts`, `users`, `vendors`

Diffed against: <https://developer.secureframe.com/>

- [ ] `poam_items (GET /poam_items)` — Plan of Action & Milestones — the open remediation backlog with owners and due dates (high)
- [ ] `framework_asset_scopes (GET /devices/{id}/framework_asset_scopes, /cloud_resources/{id}/…, /repositories/{id}/…)` — the join that says which framework each already-synced asset is in scope for; without it assets can't be filtered by framework (high)
- [ ] `ssp_policies (GET /ssp_policies)` — the policy inventory, a compliance object with no equivalent in the current tables (medium)
- [ ] `comments (GET /comments)` — remediation discussion attached to controls, tests and risks — the activity trail (medium)
- [ ] `trust_center_requests (GET /trust_center_requests)` — inbound access requests to the trust center, a demand signal worth trending (medium)
- [ ] `ssp_report_assessment_objectives (GET /ssp_report_assessment_objectives)` — per-objective assessment results underpinning control status (medium)
- [ ] `ssp_reports (GET /ssp_reports)` — System Security Plan report headers, the parent for all ssp\_\* sections (low)
- [ ] `ssp_report_sections and ssp_report_section_blocks` — section-level SSP content for report reconstruction (low)
- [ ] `ssp_roles / ssp_duties / ssp_duty_roles` — role and duty assignment lookups referenced from SSP reports (low)
- [ ] `ssp_vendors (GET /ssp_vendors)` — vendors as recorded in the SSP, distinct from the vendors and tprm/vendors tables (low)

Note: The docs page is a Scalar viewer with the full OpenAPI YAML inlined — parse the HTML rather than fetching a separate spec file. Deliberately excluded: /user_security_settings (config), /integration_connections/{id}/archive and similar action endpoints. Note that knowledge_base_questions, knowledge_base_answers, security_questionnaires, evidences and test_exports have no GET index (create-only or fetch-by-id), so they are not syncable as tables.

## Segment — **thin**

Today (11): `audit_events`, `destinations`, `iam_groups`, `iam_users`, `labels`, `reverse_etl_models`, `sources`, `tracking_plans`, `transformations`, `warehouses`, `workspace`

Diffed against: <https://docs.segmentapis.com/ (Segment Public API OpenAPI 3.0.3, v73.0.7, extracted from the Redocly state bundle https://docs.segmentapis.com/redocly-state-bf9e006a07a5265a778ac3938ef8f8f891686c5b.js)>

- [ ] `/events/volume (Get Events Volume from Workspace)` — Segment's headline usage metric — event volume by source/day, the number every Segment customer wants in a warehouse (high)
- [ ] `/usage/mtu/daily and /usage/mtu/sources/daily` — Daily MTU usage per workspace and per source — the billing metric (high)
- [ ] `/warehouses/{warehouseId}/syncs and /warehouses/{warehouseId}/connected-sources/{sourceId}/syncs` — Warehouse sync run history/status — the state-transition history for the warehouses table already synced (high)
- [ ] `/reverse-etl-models/{modelId}/subscriptionId/{subscriptionId}/syncs` — Reverse ETL sync statuses (rows loaded, failures) for the reverse_etl_models already synced (high)
- [ ] `/destinations/{destinationId}/delivery-metrics` — Per-destination delivery success/failure counts — core deliverability analysis for the destinations table (high)
- [ ] `/catalog/destinations, /catalog/sources, /catalog/warehouses` — Lookup tables resolving the metadata IDs carried on every synced source, destination, and warehouse row (high)
- [ ] `/tracking-plans/{trackingPlanId}/rules` — The actual event/property rules inside a tracking plan — tracking_plans alone is just a header row (high)
- [ ] `/delivery-overview/successful-delivery, /failed-delivery, /failed-on-ingest, /filtered-at-source, /filtered-at-destination` — Time-series pipeline health metrics broken down by stage; the standard Delivery Overview report (medium)
- [ ] `/destinations/{destinationId}/subscriptions` — Action mappings per destination — explains which events reach which destination (medium)
- [ ] `/spaces and /spaces/{spaceId}/audiences` — Engage spaces and audience definitions plus /audiences/{id}/activations; entirely absent today (medium)
- [ ] `/usage/api-calls/daily and /usage/api-calls/sources/daily` — Daily API call volume per workspace and source for cost attribution (medium)
- [ ] `/roles (and /invites)` — Lookup resolving the role IDs referenced by iam_users and iam_groups permissions (low)

Note: Static endpoint list, no dynamic discovery. The synced 11 tables cover ~15 of the ~95 GET operations in the spec; all of Engage (spaces, audiences, computed traits, profile warehouses), all usage/volume metrics, and all sync-history sub-resources are missing.

## Semgrep — gaps

Today (5): `deployments`, `projects`, `sast_findings`, `sca_findings`, `secrets`

Diffed against: <https://semgrep.dev/api/v1/public_v1.openapi.yaml>

- [ ] `POST /api/v1/deployments/{deploymentId}/dependencies (List dependencies)` — The full SCA dependency inventory that sca_findings point at — lets you join findings to the packages actually in use (high)
- [ ] `POST /api/v1/deployments/{deploymentId}/scans/search (List scans)` — Scan run history per project — needed to trend findings over time and detect projects that stopped scanning (high)
- [ ] `POST /api/v1/deployments/{deploymentId}/dependencies/repositories (List repositories with dependencies)` — Repository-level rollup that resolves which repos carry a given dependency (medium)
- [ ] `POST /api/v1/deployments/{deploymentId}/dependencies/repositories/{repositoryId}/lockfiles` — Lockfile inventory per repo; useful for supply-chain coverage auditing (low)

Note: The dependency and scan list endpoints are POST-with-body (paginated search), not GET, so they need a POST-capable resource config. Policies and SBOM export are config/ephemeral and deliberately excluded.

## SendGrid — **thin**

Today (8): `blocks`, `bounces`, `global_unsubscribes`, `invalid_emails`, `marketing_lists`, `spam_reports`, `templates`, `unsubscribe_groups`

Diffed against: <https://github.com/twilio/sendgrid-oai/tree/main/spec/json (official Twilio SendGrid OpenAPI specs; read tsg_stats_v3.json, tsg_mc_stats_v3.json, tsg_mc_contacts_v3.json, tsg_mc_singlesends_v3.json, tsg_suppressions_v3.json, tsg_email_activity_v3.json, tsg_subusers_v3.json and others)>

- [ ] `GET /v3/stats (global email statistics)` — SendGrid's headline metric — daily requests, delivered, opens, clicks, bounces, spam reports; the whole reason to sync SendGrid (high)
- [ ] `GET /v3/marketing/stats/singlesends (+ /{id} and /{id}/links)` — Per-campaign send performance including click tracking by link (high)
- [ ] `GET /v3/marketing/singlesends` — Single Send campaign records — the lookup that resolves the singlesend IDs in the stats endpoints (high)
- [ ] `GET /v3/messages (Email Activity)` — Per-message event feed (delivered, opened, clicked, bounced) — the row-level fact table behind all aggregate stats (high)
- [ ] `GET /v3/marketing/contacts (+ /contacts/exports)` — Contact records; no recipient dimension exists today so lists and suppressions cannot be joined to people (high)
- [ ] `GET /v3/asm/groups/{group_id}/suppressions` — Membership rows linking email addresses to the unsubscribe_groups already synced — the join table is missing (high)
- [ ] `GET /v3/categories/stats (and /v3/categories/stats/sums)` — Email stats broken down by category, the main way transactional senders segment performance (medium)
- [ ] `GET /v3/categories` — Category lookup resolving the category tags used on stats and messages (medium)
- [ ] `GET /v3/marketing/stats/automations (+ /{id}/links)` — Automation (journey) performance stats (medium)
- [ ] `GET /v3/marketing/segments/2.0` — Marketing segment definitions; marketing_lists is synced but segments are not (medium)
- [ ] `GET /v3/geo/stats, /v3/mailbox_providers/stats, /v3/devices/stats, /v3/clients/stats, /v3/browsers/stats` — Breakdown dimensions on the same stats fact (country, mailbox provider, device, client, browser) (medium)
- [ ] `GET /v3/subusers and /v3/subusers/stats (+ /stats/monthly, /stats/sums, /reputations)` — Per-subuser volume and reputation — required for any agency or multi-tenant SendGrid account (medium)

Note: Current coverage is essentially only the suppression family plus templates and lists — 8 tables against a spec set of 46 OpenAPI files. Not a single statistics or activity endpoint is synced, which is the bulk of analytical value. /v3/marketing/contacts returns a sample only; the full contact set requires the async exports job (POST /v3/marketing/contacts/exports then poll and download).

## Sendowl — gaps

Today (4): `discount_codes`, `orders`, `products`, `subscriptions`

Diffed against: <https://dashboard.sendowl.com/developers/api/bundles (resource nav enumerated from https://dashboard.sendowl.com/developers/api/orders; per-resource endpoint lists read from /developers/api/{bundles,discounts,drip_items,licenses,products,subscriptions})>

- [ ] `GET /api/v1/packages (Bundles)` — Product bundles — a first-class sellable object alongside products, and the lookup that resolves bundle purchases appearing on orders (high)
- [ ] `GET /api/v1/products/{product_id}/licenses and GET /api/v1/orders/{order_id}/licenses` — Issued license keys per product and per order — the fulfillment record for license-based products (medium)

Note: SendOwl's public API is small: products, packages (bundles), orders, subscriptions, discounts, drip_items, licenses. Four of the seven are already synced. drip_items exposes no index/list endpoint (only nested POST, PUT, DELETE), so it is not syncable. Licenses are only listable nested under a product or order ID, so they need a parent-driven fan-out rather than a flat list resource.

## Sentinelone — could not verify

Today (5): `activities`, `agents`, `groups`, `sites`, `threats`

No reachable API reference found during the sweep. Needs a manual pass.

Note: SentinelOne publishes no public API reference. The console API doc (https://<tenant>.sentinelone.net/api-doc/) is an authenticated SPA — every probed spec path (/api-doc/openapi.json, /api-doc/swagger.json, /apidoc/openapi.json, /web/api/v2.1/swagger.json) returns either the JS shell or 401/404. docs.sentinelone.com does not resolve, and there is no vendor-published OpenAPI on GitHub (only third-party PowerShell/Python wrappers and Shuffle's community spec, which are not authoritative). Reporting no gaps rather than guessing endpoint names. The PostHog source is a static 5-endpoint list (activities, agents, groups, sites, threats) over /web/api/v2.1 with no dynamic discovery, so it is very likely thin against a ~300-function API — but that cannot be substantiated without an authenticated console.

## ServiceNow — gaps

Today (13): `assets`, `catalog_requests`, `catalog_tasks`, `change_requests`, `change_tasks`, `configuration_items`, `incidents`, `knowledge_articles`, `problems`, `requested_items`, `tasks`, `user_groups`, `users`

Diffed against: <https://www.servicenow.com/docs/r/zurich/it-service-management/service-level-management/r_TaskSLATable.html (plus https://www.servicenow.com/docs/r/zurich/platform-administration/c_MetricInstance.html, .../system-localization/r_ChoicesTable.html, .../it-service-management/incident-management/itsm-incident-use-case.html)>

- [ ] `task_sla (Task SLA table)` — SLA attachment, stage, breach time and elapsed percentage for every incident, change and requested item already synced — SLA attainment is the headline ITSM metric and is entirely absent (high)
- [ ] `metric_instance (Metric instance table)` — Per-field duration records (time in each state, time per assignee) generated by the metric engine — the raw data behind MTTR and state-dwell analysis (high)
- [ ] `sys_choice (Choice table)` — Lookup that translates the numeric state/priority/impact/urgency codes stored on every synced task table into labels; without it incidents.state is an unreadable integer (high)
- [ ] `service_offering (Service Offering table)` — Lookup resolving the service offering referenced by incidents and change requests, and where resolution-time commitments live (medium)
- [ ] `cmdb_ci_service_business and cmdb_ci_service_technical (Business Service / Technology Management Service)` — Service dimension referenced by incidents and changes; configuration_items (cmdb_ci) does not cover the service classes used for business-impact reporting (medium)
- [ ] `Group Members (user-to-group membership related list on sys_user_group)` — users and user_groups are both synced but the many-to-many join between them is not, so assignment-group headcount and workload-per-member cannot be computed (medium)

Note: ServiceNow's Table API is generic — /api/now/table/{table} can query any table — but the PostHog source hardcodes 13 ITSM tables in settings.py (SERVICENOW_ENDPOINTS) and get_schemas returns build_endpoint_schemas(ENDPOINTS, ...) with no dynamic table discovery. Adding a table is a one-line settings entry, so these gaps are cheap to close. ServiceNow's docs site is a JavaScript-only Fluid Topics app; the resource content above was read via its content API (https://www.servicenow.com/docs/api/khub/maps/{mapId}/topics/{topicId}/content), not the HTML pages. Field-level change history (the audit/history tables) is very likely another high-value gap but I could not confirm its exact table name in a vendor doc, so it is not listed.

## Shippo — gaps

Today (9): `addresses`, `carrier_accounts`, `customs_declarations`, `customs_items`, `orders`, `parcels`, `refunds`, `shipments`, `transactions`

Diffed against: <https://docs.goshippo.com/spec/shippoapi/public-api.yaml>

- [ ] `GET /shipments/{ShipmentId}/rates (and /rates/{CurrencyCode})` — All quoted rates per shipment, not just the purchased one — the only way to analyze rate shopping and how much was saved or overspent per label (high)
- [ ] `GET /manifests` — End-of-day carrier manifests; the batch handoff record that groups transactions and is missing entirely (medium)
- [ ] `GET /tracks/{Carrier}/{TrackingNumber}` — Delivery status and tracking-event history for the transactions already synced — turns labels into a delivery-performance fact table (medium)
- [ ] `GET /parcel-templates and GET /user-parcel-templates` — Lookup resolving the parcel template tokens referenced by parcels and shipments (low)
- [ ] `GET /shippo-accounts` — Platform sub-account lookup; needed to attribute shipments when operating Shippo on behalf of multiple merchants (low)

Note: Coverage is proportionate for the core objects: 9 of roughly 15 listable collections are synced, including all the transactional ones (transactions, shipments, orders, refunds, parcels, addresses, customs). Batches are only retrievable by ID (no list endpoint), so they are not syncable as a table. The rates sub-resource is the one materially valuable analytical gap.

## ShipStation — gaps

Today (7): `customers`, `fulfillments`, `orders`, `products`, `shipments`, `stores`, `warehouses`

Diffed against: <https://www.shipstation.com/docs/api/ (V1 API reference index; the source targets ssapi.shipstation.com, i.e. V1, not the api.shipstation.com V2 API)>

- [ ] `GET /carriers (List Carriers)` — Lookup resolving the carrierCode carried on every synced order, shipment and fulfillment row (high)
- [ ] `GET /carriers/listservices (List Services)` — Lookup resolving serviceCode on shipments and orders — required to report shipping cost by service level (high)
- [ ] `GET /accounts/listtags (List Tags)` — Lookup resolving the tagIds array on orders; without it order tags are opaque integers (high)
- [ ] `GET /users (List Users)` — Lookup resolving the userId assigned to orders and shipments, enabling per-picker/per-agent throughput analysis (high)
- [ ] `GET /carriers/listpackages (List Packages)` — Lookup resolving packageCode on shipments for packaging-mix analysis (medium)
- [ ] `GET /stores/marketplaces (List Marketplaces)` — Lookup resolving marketplaceId on the stores table, giving a clean sales-channel dimension (medium)

Note: The seven synced tables cover every V1 collection that holds transactional data (orders, shipments, fulfillments, products, customers, stores, warehouses). Everything genuinely missing is a lookup/dimension table, which is exactly the highest-leverage kind of gap here. Note the vendor also ships a separate V2 API (api.shipstation.com, OpenAPI at https://github.com/shipstation/mcp-shipstation-api/blob/master/openapi.yaml) with batches, manifests, labels, inventory and pickups — a different product surface from the V1 API this source uses, so those are not counted as gaps.

## ShopWired — **thin**

Today (8): `brands`, `categories`, `customers`, `order_statuses`, `orders`, `products`, `tags`, `vouchers`

Diffed against: <https://help.shopwired.co.uk/api>

- [ ] `transactions (GET /transactions, listtransactions)` — payment transactions per order — required to reconcile gross revenue against captured payments (high)
- [ ] `product-variations (GET /products/{id}/variations, listproductvariations)` — SKU-level rows that order line items reference; without it product-level revenue can't be split by variant (high)
- [ ] `incomplete-orders (GET /incomplete-orders, listincompleteorders)` — abandoned carts — the denominator for any checkout conversion funnel (high)
- [ ] `payouts (GET /payouts, listpayouts)` — settlement records for reconciling store revenue to money actually received (high)
- [ ] `disputes (GET /disputes, listdisputes)` — chargebacks and their outcomes, a direct revenue leak metric (medium)
- [ ] `payment-methods (GET /payment-methods, listpaymentmethods)` — lookup table resolving the payment method referenced on synced orders (medium)
- [ ] `sales (GET /sales, listsales)` — discount campaigns; lookup that explains discounted line prices on synced orders (medium)
- [ ] `product-reviews (GET /product-reviews, listproductreviews)` — ratings joined to synced products for quality vs conversion analysis (medium)
- [ ] `gift-cards (GET /gift-cards, listgiftcards)` — outstanding gift card liability and redemption against orders (medium)
- [ ] `events (GET /events, get_events)` — store activity/event log — the only transition history the API exposes (medium)
- [ ] `wishlists (GET /wishlists, get_wishlists)` — purchase-intent signal joinable to customers and products already synced (medium)
- [ ] `newsletter-subscribers (GET /newsletter-subscribers, listnewslettersubscribers)` — marketing list membership joined to customers (medium)

Note: No dynamic table discovery — products/warehouse_sources/backend/temporal/data_imports/sources/shopwired/settings.py hardcodes 8 static paths. The ShopWired ReadMe reference exposes ~45 list/collection endpoints, so PostHog covers roughly a sixth of the API. `tags` maps to /tags (product tags); the separate blog tag/category/post endpoints are unsynced too but are low-value content objects.

## Shortcut — gaps

Today (15): `categories`, `custom_fields`, `entity_templates`, `epics`, `files`, `groups`, `iterations`, `labels`, `linked_files`, `members`, `objectives`, `projects`, `repositories`, `stories`, `workflows`

Diffed against: <https://developer.shortcut.com/api/rest/v3/shortcut.swagger.json>

- [ ] `epic-workflow (GET /api/v3/epic-workflow)` — lookup that resolves epic_state_id on the epics we already sync; without it epic state is an opaque integer (high)
- [ ] `stories/{id}/history (GET)` — per-story state transition log — the only way to compute cycle time, lead time, or time-in-state (high)
- [ ] `milestones (GET /api/v3/milestones)` — lookup resolving milestone_id carried on synced epics; the objectives table does not cover legacy milestones (medium)
- [ ] `stories/{id}/comments (GET)` — collaboration volume and response latency per story (medium)
- [ ] `key-results/{id} (GET)` — resolves key_result_ids already present on synced objectives; hydrate by id since there is no list endpoint (medium)
- [ ] `documents (GET /api/v3/documents)` — docs collection with epic linkage via /documents/{id}/epics (medium)
- [ ] `epics/{id}/comments (GET)` — epic-level discussion volume (medium)
- [ ] `epics/{id}/health-history (GET)` — epic health status transitions over time (low)
- [ ] `objectives/{id}/health-history (GET)` — objective health status transitions over time (low)

Note: Coverage of the flat top-level collections is complete — every un-paginated list endpoint in the v3 spec is synced, and stories go through POST /stories/search since there is no GET /stories. The real gaps are all sub-resources and one lookup table.

## Shortio — **thin**

Today (1): `domains`

Diffed against: <https://api.short.io/openapi.json>

- [ ] `links (GET /api/links)` — the core entity; syncing domains without links leaves nothing to analyze (high)
- [ ] `statistics/domain/{domainId}/last_clicks (POST, statistics.short.io)` — raw click event stream — event-level grain everything else aggregates from (high)
- [ ] `statistics/domain/{domainId}/link_clicks (GET/POST, statistics.short.io)` — clicks per link, the headline metric of the product (high)
- [ ] `statistics/link/{linkId}/by_interval (POST, statistics.short.io)` — per-link click time series for trend analysis (high)
- [ ] `statistics/domain/{domainId}/by_interval (POST, statistics.short.io)` — domain-level click time series (medium)
- [ ] `statistics/domain/{domainId}/top (POST, statistics.short.io)` — breakdown dimensions (country, referrer, device, browser) ordered by clicks (medium)
- [ ] `statistics/link/{linkId}/top (POST, statistics.short.io)` — same breakdown dimensions scoped to a single link (medium)
- [ ] `links/folders/{domainId} (GET)` — lookup resolving the folder a link belongs to (medium)
- [ ] `tags/{domainId} (GET)` — lookup for link tags used to group campaign links (medium)
- [ ] `statistics/domain/{domainId}/paths (GET, statistics.short.io)` — most popular link paths in a time window (low)
- [ ] `links/bundle/{id}/links (GET)` — link-in-bio bundle membership (low)

Note: Only `domains` is synced (settings.py has a single endpoint, no dynamic discovery). Short.io splits its API across two hosts: the management API at api.short.io (spec fetched above) and a separate statistics API at https://statistics.short.io, documented at https://developers.short.io/reference (endpoint titles and URLs verified page by page). The click data — the whole point of a link shortener — lives entirely on the statistics host and is completely unsynced.

## Shutterstock — gaps

Today (9): `image_categories`, `image_collections`, `image_licenses`, `images_updated`, `subscriptions`, `video_categories`, `video_collections`, `video_licenses`, `videos_updated`

Diffed against: <https://api-reference.shutterstock.com/>

- [ ] `images/collections/{id}/items and videos/collections/{id}/items (GET)` — the join table for collections we already sync — without it a collection row has no members (high)
- [ ] `audio/licenses (GET /v2/audio/licenses)` — audio licensing transactions, the same analytical shape as the image and video licenses already synced (high)
- [ ] `images/licenses/{id}/downloads, videos/licenses/{id}/downloads, audio/licenses/{id}/downloads (GET)` — actual download events per license — usage grain under the license rows we sync (high)
- [ ] `editorial/licenses (GET /v2/editorial/licenses)` — editorial licensing transactions, missing from the licensing picture entirely (medium)
- [ ] `sfx/licenses (GET /v2/sfx/licenses)` — sound-effects licensing transactions (medium)
- [ ] `contributors/{contributor_id} (GET /v2/contributors)` — lookup resolving the contributor id carried on every synced asset; accepts comma-separated ids (medium)
- [ ] `audio/collections and audio/collections/{id}/items (GET)` — audio collection membership, mirroring image and video collections (medium)
- [ ] `editorial/images/updated and editorial/videos/updated (GET)` — editorial catalog deltas alongside the images_updated and videos_updated feeds already synced (medium)
- [ ] `audio/genres, audio/instruments, audio/moods (GET)` — taxonomy lookup tables for audio, equivalent to the image and video category tables (medium)
- [ ] `editorial/images/categories and editorial/videos/categories (GET)` — editorial taxonomy lookups (medium)
- [ ] `catalog/collections and catalog/collections/{collection_id}/items (GET)` — the customer's own asset catalog and its membership (medium)
- [ ] `images/collections/featured and videos/collections/featured (GET, plus /items)` — Shutterstock-curated collections and their contents (low)

Note: Coverage is solid for the images and videos verticals (categories, collections, licenses, updated feeds) but the audio, SFX, and editorial verticals are entirely absent, and collection membership is never resolved.

## SigNoz — gaps

Today (5): `alert_rules`, `dashboards`, `logs`, `notification_channels`, `traces`

Diffed against: <https://signoz.io/docs/metrics-management/query-range-api/>

- [ ] `metrics time series (POST /api/v5/query_range, signal=metrics)` — the third telemetry pillar; a warehouse user syncing an observability tool will expect metric series alongside logs and traces (medium)
- [ ] `meter metrics (POST /api/v5/query_range over signoz.meter.log.count/.size, signoz.meter.span.count/.size, signoz.meter.metric.datapoint.count)` — daily ingestion volume and cost broken down by service.name or environment — the vendor's own billing-analysis use case (medium)

Note: SigNoz's public API surface is small and PostHog covers most of it: logs and traces via POST /api/v5/query_range, plus /api/v1/rules, /api/v1/dashboards, /api/v1/channels. The metrics signal is excluded on purpose — settings.py documents that the v5 raw request type only supports logs and traces, so metrics need a per-metric aggregation query that does not map to a generic table. There is no publicly documented REST endpoint for alerts history, planned maintenance, or routing policies (those docs describe the UI only), so I did not report them. Note /api/v2/dashboards now exists alongside the v1 path in use.

## SimFin — gaps

Today (9): `balance_sheets`, `cash_flow_statements`, `common_shares_outstanding`, `companies`, `company_details`, `derived_ratios`, `income_statements`, `share_prices`, `weighted_shares_outstanding`

Diffed against: <https://simfin.readme.io/reference/1-1>

- [ ] `filings/list (GET /api/v3/filings/list) and filings/by-company (GET /api/v3/filings/by-company)` — the SEC filing index — filing dates and types are what make a statement period's data auditable and tell you when a figure became public (high)
- [ ] `companies/data-change-log (GET /api/v3/companies/data-change-log)` — restatement and revision history for figures already synced; also the natural driver for incremental refresh (medium)
- [ ] `companies/changed-companies (GET /api/v3/companies/changed-companies)` — list of companies whose data moved in a window, useful as a change-detection lookup (low)

Note: The v3 API is small (14 paths total) and PostHog covers the whole fundamentals surface: companies/list, general/compact, statements/compact (income, balance, cash flow, derived ratios), prices/compact, and both shares-outstanding endpoints. Only the filings resource and the two change-tracking endpoints are unsynced. The /verbose variants of general, prices, and statements return the same data with richer metadata, so they are not separate tables.

## SimpleCast — **thin**

Today (1): `podcasts`

Diffed against: <https://apidocs.simplecast.com/api/collections/10068189/T1DsAGJy?environment=8772875-0af62042-2b99-470c-8cdc-df8cd9c2cead&segregateAuth=true&versionTag=latest>

- [ ] `podcasts/{podcast_id}/episodes (GET)` — the core entity — a podcasts-only table has one row per show and nothing to analyze (high)
- [ ] `analytics/downloads (GET)` — downloads over time, the headline metric of the entire product (high)
- [ ] `analytics/episodes (GET, plus /average_downloads, /hours_listened, /listeners, /top_10)` — per-episode download and listening figures — the grain every podcast analysis starts from (high)
- [ ] `analytics/listeners (GET, plus /last_7 and analytics/podcasts/listeners)` — unique listener counts, the audience-size metric distinct from downloads (high)
- [ ] `podcasts/{podcast_id}/seasons (GET) and seasons/{season_id}/episodes (GET)` — lookup resolving the season an episode belongs to, needed for any season-over-season comparison (medium)
- [ ] `analytics/technology/* (GET: applications, browsers, devices, device_class, listening_methods, network_types, operating_systems, providers, web_players)` — listening-platform breakdown dimensions — which apps and devices the audience uses (medium)
- [ ] `analytics/location (GET)` — geographic breakdown of the audience (medium)
- [ ] `distribution_channels (GET) and podcasts/{podcast_id}/distribution_channels (GET)` — lookup for the platforms a show is distributed to, needed to attribute downloads by channel (medium)
- [ ] `analytics/embed/* (GET: listens, avg_completion, heatmap, locations, speeds, episodes)` — web player engagement including completion rate and drop-off heatmap (medium)
- [ ] `categories (GET) and podcasts/{podcast_id}/categories (+ /subcategories)` — lookup for show taxonomy used in benchmarking and rollups (medium)
- [ ] `analytics/campaigns/{campaign_id} (GET)` — campaign-level performance for promoted episodes (medium)
- [ ] `podcasts/{podcast_id}/keywords and episodes/{episode_id}/keywords (GET)` — keyword tags joinable to episodes for topic-level performance (low)

Note: Only `podcasts` is synced (settings.py defines one endpoint, no dynamic discovery). The published Postman collection lists 66 GET endpoints, ~30 of which are analytics. Every listening metric the product is bought for is missing. Doc URL above is the machine-readable collection JSON behind https://apidocs.simplecast.com.

## Simplesat — gaps

Today (4): `answers`, `questions`, `responses`, `surveys`

Diffed against: <https://developer.simplesat.io/api/Simplesat%20API%20(v1)%20OpenAPI.yaml>

- [ ] `customers (GET /api/v1/customers)` — lookup table resolving the customer referenced on every synced response, so CSAT/NPS can be sliced by account (high)

Note: The v1 OpenAPI defines only six resources: answers, customers, team-members, responses, surveys, questions. PostHog syncs four of them, so coverage is proportionate — only customers is a real miss. team-members exposes GET /api/v1/team-members/{team_member_id} but no list endpoint (the collection path is POST-only), so it cannot be synced as a table without hydrating ids from responses; I did not list it as a gap for that reason.

## Skyvern — gaps

Today (5): `browser_profiles`, `credentials`, `runs`, `schedules`, `workflows`

Diffed against: <https://api.skyvern.com/openapi.json>

- [ ] `GET /v1/runs/{run_id}/timeline` — per-run block/step execution timeline - the state-transition history behind every run outcome (high)
- [ ] `GET /v1/folders (and /v1/folders/{folder_id})` — lookup table resolving the folder a workflow/agent lives in (high)
- [ ] `GET /v1/agents/{workflow_permanent_id}/tags` — workflow-to-tag membership for grouping and cost attribution of synced workflows (high)
- [ ] `GET /v1/browser_sessions` — persistent browser sessions runs attach to; explains run cost and reuse (medium)
- [ ] `GET /v1/runs/{workflow_run_id}/tags` — run-to-tag membership, the standard breakdown dimension for run reporting (medium)
- [ ] `GET /v1/tag-keys and GET /v1/tag-values` — lookup tables that resolve the tag key/value ids attached to workflows and runs (medium)
- [ ] `GET /v1/agents/{workflow_permanent_id}/versions` — workflow version history, needed to attribute run results to a definition version (medium)
- [ ] `GET /v1/runs/{run_id}/artifacts` — artifact metadata produced per run (screenshots, logs, downloaded files) (medium)
- [ ] `GET /v1/browser_profiles/{profile_id}/usage` — which runs consumed which browser profile (low)
- [ ] `GET /v1/scripts (and /v1/scripts/{script_id})` — generated scripts deployed from workflows; joins to runs executed in script mode (low)
- [ ] `GET /v1/agents/{workflow_permanent_id}/tags/history` — tag change history on a workflow (low)

Note: PostHog's `workflows` table maps to /v1/agents and `runs` fans out over /v1/agents/{wpid}/runs. Config-only surfaces (custom-llms, upload_file, webhook retry, version) were excluded.

## Smaily — gaps

Today (8): `ab_tests`, `automations`, `campaign_statistics`, `campaigns`, `segment_subscribers`, `segments`, `templates`, `users`

Diffed against: <https://smaily.com/help/api/>

- [ ] `GET /api/split.php?id=… (A/B test statistics)` — the headline per-variant open/click metrics for A/B tests we already sync (high)
- [ ] `GET /api/history.php (subscriber action log)` — per-subscriber event stream (opens, clicks, opt-outs) - the core analytical fact table (high)
- [ ] `GET /api/message/action/log.php (message action log)` — per-message action events, joins campaigns/automations to subscriber behaviour (high)
- [ ] `GET /api/list.php?id=… (segment rules)` — filter_type and filter_data rules plus subscribers_count that explain each synced segment (medium)

Note: Both action logs only retain the last 30 days, so they need frequent incremental syncs keyed on since_seq_id. Smaily has no global list-all-subscribers endpoint - segment_subscribers is the only route to subscriber rows, so that is not a gap.

## SmartEngage — adequate

Today (4): `avatars`, `custom_fields`, `sequences`, `tags`

Diffed against: <http://web.archive.org/web/20240615141100/https://smartengage.com/docs/>

No material gaps found.

Note: smartengage.com/docs and docs.smartengage.com both return Cloudflare 521 right now; diffed against the archived vendor reference. The API exposes exactly four list endpoints (/avatars/list, /tags/list, /customfields/list, /sequences/list) and PostHog syncs all four. Everything else (tags/add, tags/create, tags/delete, customfields/create, customfields/update, sequences/add, sequences/remove, subscribers/add, subscribers/update) is write-only - there is no subscriber list endpoint to sync.

## Smartreach — gaps

Today (2): `campaigns`, `prospects`

Diffed against: <https://help.smartreach.io/llms.txt>

- [ ] `GET /campaigns/{campaign_id}/prospects` — campaign-to-prospect membership plus per-campaign prospect status - the join table between the two tables we already sync (high)
- [ ] `GET /campaigns/{campaign_id}/stats` — the vendor's headline campaign metrics (sends, opens, replies, bounces) (high)
- [ ] `GET /teams` — lookup table for the team id that scopes every campaign and prospect (high)
- [ ] `GET /teams/{team_id}/users` — lookup resolving the owner/user ids carried on campaigns and prospects (high)
- [ ] `GET /email_settings (and /email_settings/{id})` — sending mailbox lookup - resolves which inbox a campaign sends from (medium)
- [ ] `GET /do_not_contact` — suppression list, needed to reconcile deliverable vs excluded prospects (medium)
- [ ] `GET /campaigns/{campaign_id}/settings (channel settings)` — multichannel step configuration per campaign (low)

Note: The public smartreach.io/api_docs page only documents campaigns + prospects, which is likely why coverage stopped there. The real reference is the ReadMe site at help.smartreach.io/reference (indexed in llms.txt) and it is considerably larger. Tasks are PUT-only (no list endpoint).

## Smartsheet — **thin**

Today (6): `contacts`, `reports`, `sheets`, `templates`, `users`, `workspaces`

Diffed against: <https://developers.smartsheet.com/sitemap.xml>

- [ ] `GET /sheets/{sheetId} (rows + cells)` — the actual row/cell data inside every sheet - today only sheet metadata is synced, so no sheet content is queryable (high)
- [ ] `GET /sheets/{sheetId}/columns` — lookup resolving the column ids that every cell references, including picklist options (high)
- [ ] `GET /events (list-events, list-filtered-events)` — the org-wide activity event stream - who changed what and when (high)
- [ ] `GET /groups and group members` — group membership lookup that resolves sharing and contact ids (high)
- [ ] `GET /{assetType}/{assetId}/shares (list-asset-shares)` — who has access to each sheet/report/workspace; the access-control fact table (medium)
- [ ] `GET /sheets/{sheetId}/discussions and comments` — collaboration threads attached to sheets and rows (medium)
- [ ] `GET /sheets/{sheetId}/attachments (also row and discussion scoped)` — attachment metadata per sheet/row (medium)
- [ ] `GET /folders/{folderId}/... and /home (folder hierarchy)` — lookup resolving the folder tree that sheets, reports and dashboards hang off (medium)
- [ ] `GET /sheets/{sheetId}/rows/{rowId}/columns/{columnId}/history (cell history)` — cell-level change history - value transitions over time (medium)
- [ ] `GET /sheets/{sheetId}/updaterequests and /sentupdaterequests` — outstanding and sent update requests, a workflow-completion metric (medium)
- [ ] `GET /sights (dashboards)` — dashboard inventory alongside the sheets and reports already synced (medium)
- [ ] `GET /sheets/{sheetId}/summary/fields` — sheet summary fields - the per-sheet rollup values users report on (low)

Note: The doc URLs in the payload (smartsheet.redoc.ly) are retired - that host now serves a placeholder spec whose title is literally "(DEPRECATED site)" with a single /ping path. Live reference is developers.smartsheet.com/api/smartsheet/openapi/\*, enumerated here from the sitemap (691 operation/schema pages). Coverage is 6 top-level collections out of ~30 resource groups, and critically none of the actual sheet content.

## Smartwaiver — adequate

Today (3): `checkins`, `templates`, `waivers`

Diffed against: <https://api.smartwaiver.com/docs/v4>

No material gaps found.

Note: The v4 API's only listable analytical collections are waivers, templates and checkins - all three are synced. Remaining GETs are per-waiver binary sub-resources (/v4/waivers/{id}/signatures, /photos, /files), an async search job (/v4/search then /v4/search/{guid}/results, an alternate route to the same waiver rows), account config (/v4/info, /v4/settings, /v4/me, /v4/keys/published), webhook plumbing (/v4/webhooks/\*, /v4/webhooks/queues/\*) and write-only dynamic-waiver, SMS, prefill and group-reservation endpoints. Nothing there is worth a warehouse table.

## Snowplow — gaps

Today (7): `data_models`, `data_structures`, `failed_event_metrics`, `job_run_steps`, `job_runs`, `pipelines`, `users`

Diffed against: <https://console.snowplowanalytics.com/api/msc/v1/docs/docs.yaml>

- [ ] `GET /data-products/v2 (plus /metrics and /{dataProductId}/history)` — Data Products are the vendor's headline governance object and /metrics carries their volume numbers (high)
- [ ] `GET /event-specs/v1 (plus /metrics, /{eventSpecId}/versions, /{eventSpecId}/history)` — event specifications with observed-volume metrics and version history - the tracking-quality core (high)
- [ ] `GET /source-apps/v1` — lookup table resolving the source app ids referenced by data products and event specs (high)
- [ ] `GET /data-catalog/v1 (and /data-catalog/v1/search)` — the catalog of events and entities actually observed in the pipeline, the join key between data structures and real traffic (high)
- [ ] `GET /data-structures/v1/{schemaHash}/deployments` — which schema version is deployed to dev vs prod - deployment state history for structures we already sync (medium)
- [ ] `GET /metrics/v1/pipelines/{pipelineId}/failed-events/{errorId}` — per-error breakdown behind the failed-event totals already synced (medium)
- [ ] `GET /tracking-scenarios/v2 (plus /metrics and /{scenarioId}/history)` — tracking scenarios and their conformance metrics for orgs not yet migrated to event specs (medium)
- [ ] `GET /pipelines/v1/{pipelineId}/enrichments` — which enrichments are live per pipeline - explains enrichment-driven data quality shifts (low)
- [ ] `GET /data-products/v1/{dataProductId}/subscriptions` — who subscribes to each data product (low)
- [ ] `GET /minis/v1 (and /minis/v1/{miniId}/enrichments)` — Snowplow Mini test environments alongside the production pipelines (low)
- [ ] `GET /data-structure-drafts/v1` — in-flight schema drafts not yet promoted (low)

Note: Spec is served from the Swagger UI at /api/msc/v1/docs, whose initializer points at a relative ./docs.yaml (the obvious /swagger.json and /openapi.json paths 404). Credentials, api-keys, preferences, subscriptions (billing) and data-quality-alerts were excluded as config/plumbing.

## Snyk — gaps

Today (4): `issues`, `organizations`, `projects`, `targets`

Diffed against: <https://api.snyk.io/rest/openapi/2026-03-25>

- [ ] `GET /orgs/{org_id}/memberships` — user-to-org membership with role - the lookup that resolves who owns the projects and issues we sync (high)
- [ ] `GET /groups and GET /groups/{group_id}/orgs` — group is the parent of every org; without it multi-org rollups have no hierarchy to aggregate on (high)
- [ ] `GET /groups/{group_id}/memberships and /org_memberships` — group-level membership and role assignment across all orgs (medium)
- [ ] `GET /orgs/{org_id}/collections and /collections/{collection_id}/relationships/projects` — collection membership - the standard breakdown dimension for grouping projects in reporting (medium)
- [ ] `GET /orgs/{org_id}/policies and GET /orgs/{org_id}/policies/{policy_id}/events` — ignore/severity policies plus their event log explain why issues we sync are suppressed or re-rated (medium)
- [ ] `GET /orgs/{org_id}/container_images (and /relationships/image_target_refs)` — container image inventory joining images to the targets already synced (medium)
- [ ] `GET /orgs/{org_id}/audit_logs/search (and group-level equivalent)` — state/transition history for org and project changes (medium)
- [ ] `GET /orgs/{org_id}/inventory/assets (plus /relationships/projects and /relationships/targets)` — the AppRisk asset inventory and its mapping onto projects/targets we already sync (medium)
- [ ] `GET /orgs/{org_id}/tests/{test_id}/findings` — individual findings per test run, finer grained than the issue rollup (low)
- [ ] `GET /orgs/{org_id}/cloud/resources, /cloud/environments, /cloud/scans` — cloud posture resources and scan history for IaC customers (low)
- [ ] `GET /tenants/{tenant_id}/roles` — role lookup that resolves the role ids on membership records (low)
- [ ] `GET /orgs/{org_id}/projects/{project_id}/sbom` — per-project SBOM component listing (low)

Note: Snyk's REST API is date-versioned; /rest/openapi lists every version and 2026-03-25 is the newest (192 paths). Service accounts, invites, app installs, brokers, SSO connections, settings/\* and slack_app were excluded as config/plumbing.

## SolarwindsServiceDesk — gaps

Today (12): `catalog_items`, `changes`, `departments`, `groups`, `hardwares`, `incidents`, `other_assets`, `problems`, `releases`, `sites`, `solutions`, `users`

Diffed against: <https://apidoc.samanage.com/redoc/schema/resolved_schema.json>

- [ ] `categories` — lookup table resolving the category/subcategory IDs carried on incidents, changes and problems we already sync (high)
- [ ] `{object_type}/{id}/audits (and /audits)` — per-ticket state/field transition history - the only way to compute time-in-state, reassignment and SLA breach analytics (high)
- [ ] `{object_type}/{id}/time_tracks` — time logged per incident/change/problem; core effort and cost-per-ticket metric (high)
- [ ] `configuration_items` — CMDB configuration items that incidents and changes reference; joins tickets to affected infrastructure (high)
- [ ] `roles` — lookup resolving the role IDs on users we already sync (medium)
- [ ] `vendors` — lookup for the vendor IDs on hardwares, other_assets, contracts and purchase_orders (medium)
- [ ] `contracts` — asset contracts with cost and renewal dates; underpins spend and renewal reporting (medium)
- [ ] `purchase_orders` — procurement line items and spend against assets (medium)
- [ ] `softwares` — software asset inventory and license counts alongside the hardware assets already synced (medium)
- [ ] `mobiles` — mobile device asset class, missing from the hardware/other_assets coverage (low)
- [ ] `printers` — printer asset class, missing from the hardware/other_assets coverage (low)
- [ ] `risks` — risk records linked to changes for change-risk analysis (low)

Note: Static endpoint list (SONATYPE-style ENDPOINTS dict); no dynamic discovery. The vendor ships a full OpenAPI 3 doc at the redoc spec-url above (66 paths), so the diff is exact. change_catalogs and hardwares/{id}/warranties also exist but are low value.

## SonarCloud — gaps

Today (4): `issues`, `metrics`, `projects`, `quality_gates`

Diffed against: <https://sonarcloud.io/api/webservices/list>

- [ ] `measures/component_tree` — the actual metric values per project/directory/file - today only the metric definitions (api/metrics) are synced, so no numbers land in the warehouse (high)
- [ ] `measures/search_history` — historical metric values over time; required for any coverage/debt trend chart (high)
- [ ] `rules/search` — lookup table resolving the rule keys carried on every issue we already sync (severity, type, language, remediation effort) (high)
- [ ] `issues/changelog` — issue state/assignee/severity transition history - lets you measure time-to-fix and false-positive rates (high)
- [ ] `hotspots/search` — security hotspots are a separate finding class from issues and are entirely absent (high)
- [ ] `project_analyses/search` — per-analysis records with version and event markers; the join key for measures history and release-over-release comparison (medium)
- [ ] `project_branches/list` — branch-level quality gate status and analysis dates (medium)
- [ ] `project_pull_requests/list` — PR-level findings and gate status, the main dev-workflow surface (medium)
- [ ] `qualityprofiles/search + qualityprofiles/projects` — lookup mapping projects to the quality profile that produced their issues (medium)
- [ ] `components/search (and components/tree)` — component/file inventory that measures and issues are keyed on (medium)
- [ ] `user_groups/search + user_groups/users` — group membership table for attributing findings to teams (low)
- [ ] `languages/list` — small lookup resolving language keys on rules and measures (low)

Note: Resource list read from the instance's own machine-readable web-service catalog (33 services). Note api/metrics only returns metric \*definitions\*; the values live in api/measures, which is the single biggest omission.

## Sonarqube — gaps

Today (5): `issues`, `metrics`, `projects`, `rules`, `users`

Diffed against: <https://next.sonarqube.com/sonarqube/api/webservices/list>

- [ ] `measures/component_tree` — actual metric values per component - today only metric definitions are synced, so no measurements reach the warehouse (high)
- [ ] `measures/search_history` — metric history over time; needed for coverage, duplication and tech-debt trends (high)
- [ ] `qualitygates/list + qualitygates/project_status` — quality gate status per project is the headline pass/fail metric and is missing entirely (the SonarCloud source already has it) (high)
- [ ] `hotspots/search` — security hotspots are a distinct finding class not covered by issues (high)
- [ ] `issues/changelog` — issue transition history for time-to-remediate and reopen analysis (high)
- [ ] `project_analyses/search` — analysis records with version/event markers; join key for measures history and release comparison (medium)
- [ ] `project_branches/list` — branch-level gate status and last analysis date (medium)
- [ ] `project_pull_requests/list` — PR-level findings and gate status (medium)
- [ ] `qualityprofiles/search + qualityprofiles/projects` — lookup mapping each project to the profile that generated its issues (medium)
- [ ] `components/search + components/tree` — component/file inventory that measures and issues key on (medium)
- [ ] `user_groups/search + user_groups/users` — group membership table for team-level attribution of findings (medium)
- [ ] `languages/list` — lookup resolving language keys on rules and measures (low)

Note: Diffed against a live SonarQube instance's own web-service catalog (41 services). Same core gap as SonarCloud: api/metrics is definitions only, api/measures holds the values. views/portfolios and ce/activity also exist but are lower value.

## SonatypeNexus — gaps

Today (4): `assets`, `components`, `repositories`, `tasks`

Diffed against: <https://help.sonatype.com/en/api-reference.html>

- [ ] `security/users` — user inventory with source realm and assigned roles; the only way to attribute repository access (medium)
- [ ] `security/roles` — lookup resolving the role IDs referenced by users (medium)
- [ ] `security/privileges` — lookup resolving the privilege IDs referenced by roles (medium)
- [ ] `blobstores (list + {name}/quota-status)` — storage footprint and quota headroom per blob store - the capacity metric behind component/asset growth (medium)

Note: Source targets Nexus Repository Manager 3 only (/service/rest/v1), not IQ Server / Lifecycle. The Nexus Repository API surface is genuinely small and mostly configuration (capabilities, cleanup-policies, email, http-configuration, licensing, lifecycle, log-management, nodes, read-only, script, status, support) - components/assets/repositories/tasks already cover the bulk of queryable data, so coverage is close to proportionate.

## Sourcegraph — **thin**

Today (3): `organizations`, `repositories`, `users`

Diffed against: <https://sourcegraph.com/.api/graphql>

- [ ] `Repository.defaultBranch.target.commit.ancestors (commit history)` — commit-level history per repo - the foundational fact table for any code-activity analysis; nothing commit-shaped is synced today (high)
- [ ] `Repository.contributors` — per-repo contributor counts and last-commit dates; joins users to repositories we already sync (high)
- [ ] `telemetry.exportedEvents` — Sourcegraph's own usage event stream (Event Logging v2) - the headline adoption/usage metric (high)
- [ ] `codeHosts (and externalServices)` — lookup resolving which code host connection each synced repository came from (high)
- [ ] `Repository.gitRefs / branches / tags` — branch and tag inventory per repo; needed for release and branch-age reporting (medium)
- [ ] `preciseIndexes` — precise code-intel index records with state and failure reasons; measures code-intel coverage across repos (medium)
- [ ] `insightViews (and insightsDashboards)` — Code Insights definitions and their time series - the product's analytical output (medium)
- [ ] `roles and permissions` — RBAC lookup tables resolving role/permission assignments on the users already synced (medium)
- [ ] `savedSearches` — saved search inventory per user/org; a common usage signal (medium)
- [ ] `surveyResponses` — NPS/survey responses joined to users; standard satisfaction reporting (medium)
- [ ] `searchContexts` — search context definitions, a lookup for how teams scope their searches (low)
- [ ] `repositoryStats` — instance-wide repo counts by clone/index state; useful health rollup (low)

Note: Only 3 static tables against a GraphQL Query type with 114 root fields plus rich per-repository sub-resources; no dynamic discovery (static SOURCEGRAPH_ENDPOINTS dict). Resource list obtained by live introspection of sourcegraph.com/.api/graphql (unauthenticated introspection is allowed). Batch Changes types are not present on the public instance, so I did not list them.

## Spacelift — gaps

Today (8): `contexts`, `managed_entities`, `modules`, `policies`, `runs`, `spaces`, `stacks`, `worker_pools`

Diffed against: <https://docs.spacelift.io/integrations/api>

- [ ] `searchAuditTrailEntries` — full who-did-what-when history across stacks, runs and policies; the state-transition table for everything already synced (high)
- [ ] `run.changesV (per-run resource changes)` — add/change/delete deltas per resource for each run - the core IaC change metric; runs are synced but their change breakdown is not (high)
- [ ] `searchEvaluationRecords` — policy evaluation records per run; joins to the policies table we already sync and shows which decisions actually fired (high)
- [ ] `searchModuleVersions` — module registry version history with test results and consumers; modules are synced but their versions are not (high)
- [ ] `workerPool.workers (and busyWorkers)` — individual worker state and utilization behind the worker_pools already synced; capacity and queueing analysis (medium)
- [ ] `stack.dependsOn / isDependedOnBy` — stack dependency graph edges; needed to model blast radius and deployment ordering (medium)
- [ ] `stack.tasks` — one-off tasks executed against a stack, a run class not covered by the runs table (medium)
- [ ] `searchBlueprints` — blueprint definitions and their instantiation counts; shows stack provisioning patterns (medium)
- [ ] `searchTemplates (and template deployments/versions)` — template catalog and deployment records, the newer provisioning surface (medium)
- [ ] `stack.attachedContexts / attachedPolicies` — attachment join tables linking stacks to the contexts and policies already synced (medium)
- [ ] `users (spacelift_user)` — account users and their space/role assignments; lets runs and audit entries be attributed to people (medium)
- [ ] `terraformProvider (+ versions)` — private provider registry inventory alongside the module registry (low)

Note: Spacelift does not publish its GraphQL schema (docs only tell you to copy it from the in-app explorer), and introspection needs an account token. The resource list here was read out of the vendor's own official CLI, github.com/spacelift-io/spacectl, where the GraphQL query roots are literal struct tags (searchAuditTrailEntries, searchEvaluationRecords, searchModuleVersions, searchBlueprints, searchTemplates, searchSchedulableRuns, terraformProvider, stack.tasks, run.changesV), cross-checked against the terraform-provider-spacelift data-source docs. Endpoint names are therefore real, not guessed.

## SparkPost — gaps

Today (7): `events`, `recipient_lists`, `sending_domains`, `subaccounts`, `suppression_list`, `templates`, `webhooks`

Diffed against: <https://developers.sparkpost.com/api/metrics/>

- [ ] `metrics/deliverability/time-series` — SparkPost's headline deliverability aggregate over time; the single most-queried table for an ESP and completely absent (high)
- [ ] `metrics/deliverability/domain and /sending-domain` — deliverability broken down by recipient and sending domain - the primary reputation dimension (high)
- [ ] `metrics/deliverability/campaign and /subject-campaign` — per-campaign send/open/click/bounce rollups; core marketing reporting dimension (high)
- [ ] `metrics/deliverability/template` — per-template performance, joining directly to the templates table already synced (high)
- [ ] `metrics/deliverability/bounce-reason, /rejection-reason, /delay-reason (+ their /domain variants)` — failure-reason breakdowns; the standard deliverability troubleshooting cut (high)
- [ ] `transmissions` — the send jobs themselves with status and recipient counts; today only the resulting events are synced (high)
- [ ] `metrics/deliverability/subaccount` — per-subaccount deliverability, joining to the subaccounts table already synced (medium)
- [ ] `metrics/deliverability/mailbox-provider and /mailbox-provider-region` — inbox performance by Gmail/Outlook/Yahoo etc, a headline deliverability cut (medium)
- [ ] `metrics/deliverability/sending-ip and /ip-pool` — IP-level reputation and warmup tracking (medium)
- [ ] `ip-pools and sending-ips` — lookup tables resolving the IP pool and sending IP identifiers that appear in events and metrics (medium)
- [ ] `metrics/deliverability/link-name` — click performance per tracked link name; engagement breakdown (medium)
- [ ] `usage` — account/subaccount monthly sending volume against plan limits (low)

Note: The whole Metrics API (roughly 30 GET resources: deliverability with a dozen breakdown dimensions, plus campaigns/domains/templates/ip-pools/mailbox-providers discovery lists and benchmarks/inbox-rate) is missing. message-events is deprecated in favor of events, which is already synced, so I excluded it. ab-testing, snippets, seed-list and recipient-validation exist but are lower value.

## SplitIo — gaps

Today (10): `change_requests`, `environments`, `feature_flags`, `flag_sets`, `groups`, `rollout_statuses`, `segments`, `traffic_types`, `users`, `workspaces`

Diffed against: <https://docs.split.io/reference>

- [ ] `feature flag definitions in environment (list-feature-flag-definitions-in-environment)` — the per-environment targeting rules, treatments, default rule and rollout percentages - the actual flag configuration; today only workspace-level flag metadata is synced (high)
- [ ] `segment keys in environment (get-segment-keys-in-environment)` — segment membership rows; the membership table that turns segments into something joinable to your own users (high)
- [ ] `attributes (get-attributes)` — traffic type attribute definitions; the lookup that resolves attribute keys used in targeting rules and identities (high)
- [ ] `segments in environment (list-segments-in-environment)` — which segments are enabled per environment, plus their per-environment state (medium)
- [ ] `large segments (listlargesegments, listlargesegmentsinenvironment)` — the large-segment variant is a separate resource entirely absent from the current tables (medium)
- [ ] `rule-based segments` — rule-based segment definitions, a distinct segment class from the standard segments already synced (medium)
- [ ] `identities (save/get identity)` — per-key attribute values used for targeting; lets flag exposure be joined to customer records (medium)
- [ ] `restrictions (list-restrictions)` — governance restrictions applied to flags and environments; useful for change-control reporting (low)

Note: Resource list taken from the ReadMe-generated reference index at docs.split.io/reference (119 pages), filtered to GET operations. Split's public Admin API has no impressions or metrics export, so experimentation result data is genuinely unavailable rather than missing from the connector. API keys, events ingestion (write-only) and tag association were excluded as config/plumbing.

## SplunkObservabilityCloud — gaps

Today (12): `alert_muting_rules`, `charts`, `dashboard_groups`, `dashboards`, `detector_events`, `detectors`, `dimensions`, `incidents`, `metric_time_series`, `metrics`, `organization_members`, `teams`

Diffed against: <https://dev.splunk.com/observability/reference/>

- [ ] `slo (GET /slo/{id}, POST /slo/search)` — SLO definitions and status are the headline reliability metric; nothing SLO-related is synced today (high)
- [ ] `tests (Synthetics GET /tests)` — the whole Synthetics product is unexposed; tests is its root object (high)
- [ ] `tests/{id}/runs and runs/{id} (Synthetics runs)` — actual synthetic check results over time - the analytical fact table for uptime/latency (high)
- [ ] `locations (Synthetics GET /locations)` — lookup table resolving the location IDs stamped on every synthetic run (high)
- [ ] `event / event/find (GET /event, GET /event/find)` — org-wide custom and alert event stream; today only detector_events is synced (high)
- [ ] `tag (GET /tag, GET /tag/{name})` — metric tag lookup that resolves the breakdown labels on metrics and MTS (medium)
- [ ] `role (GET /role, GET /role/{roleId})` — role definitions and assignments complement organization_members for access analysis (medium)
- [ ] `audit events (GET /v2/audit/events)` — who changed which detector/dashboard and when (medium)
- [ ] `clients (GET /clients, /clients/metadata/values)` — agent/client inventory for fleet coverage reporting (medium)
- [ ] `navigator (GET /navigator, /navigator/{id}/dashboards)` — navigator definitions tie infrastructure categories to dashboards (low)
- [ ] `devices (Synthetics GET /devices)` — lookup resolving device profiles referenced by browser tests (low)
- [ ] `crosslink (GET /crosslink)` — data link definitions that map dimensions to external targets (low)

Note: The dev.splunk.com reference is a client-rendered SPA; the full API index (48 API groups with per-endpoint path/method/operationId) is embedded in the Next.js flight payload of https://dev.splunk.com/observability/reference/ and was parsed from there. Synthetics is a large, entirely-unexposed sub-API.

## SpotIo — gaps

Today (4): `elastigroup_costs`, `elastigroups`, `ocean_clusters`, `stateful_nodes`

Diffed against: <https://docs.spot.io/api/?version=v3>

- [ ] `GET /setup/account (List Accounts)` — lookup table resolving the accountId carried by every elastigroup, ocean cluster and cost row (high)
- [ ] `GET /ocean/aws/k8s/cluster/{oceanClusterId}/nodes (also gcp/k8s and azure/np variants)` — the per-node fact table under the ocean_clusters we already sync (high)
- [ ] `GET /ocean/aws/k8s/launchSpec (Virtual Node Groups)` — lookup resolving the launchSpec/VNG id attached to Ocean nodes (high)
- [ ] `GET /aws/ec2/group/{groupId}/events (Activity Events)` — scale-up/down and spot-interruption state transition history for groups we already sync (high)
- [ ] `GET /ocean/insights/k8s/cluster (Ocean Insights)` — Spot's headline cluster efficiency/waste metric (high)
- [ ] `GET /ocean/{oceanId}/rightSizing/namespaces/{ns}/{type}/{name}/recommendation-history` — rightsizing recommendations over time - the savings number customers report on (high)
- [ ] `GET /aws/ec2/managedInstance/{MI_ID}/costs` — stateful_nodes are synced but their cost series is not, unlike elastigroups (medium)
- [ ] `GET /aws/ec2/group/{groupId}/roll and /roll/{rollId}/status` — deployment (roll) history per elastigroup (medium)
- [ ] `GET /mcs/ecs/cluster/{clusterName}/costs` — Ocean ECS cluster cost breakdown, the ECS analogue of elastigroup_costs (medium)
- [ ] `GET /aws/ec2/group/{groupId}/status and /instanceHealthiness` — current instance membership and health per group (medium)
- [ ] `GET /azure/compute/statefulNode/cost/daily` — daily aggregated Azure stateful node cost series (medium)
- [ ] `GET /setup/access/userGroup and GET /setup/user` — user and group membership for attributing spend to owners (low)

Note: The docs page embeds a complete `globalOperations` index (450 operations across 13 sections) in its HTML; the per-section Redoc YAMLs at ./api/spot-<section>.yaml 404 to the docs shell, so the index page is the citable source. Coverage is AWS-Elastigroup-centric; Azure/GCP elastigroups and Ocean ECS/GKE/AKS are absent.

## SpotlerCRM — gaps

Today (9): `Accounts`, `Activities`, `Campaigns`, `Cases`, `Contacts`, `Documents`, `Opportunities`, `OpportunityHistories`, `OpportunityLines`

Diffed against: <https://support.reallysimplesystems.com/api-v4/>

- [ ] `campaignstages` — lookup table resolving the stage a campaign or campaign member sits in (high)
- [ ] `campaigndetails` — the per-campaign membership/detail rows linking contacts to campaigns (high)

Note: The v4 API documents exactly 11 CRUD objects; PostHog exposes 9 of them, so coverage is nearly complete. The two missing ones are both marketing-tool objects. Also available but not table-shaped: GET /datadictionary/{object} and GET /lookup/{object}/{field} for dropdown values.

## Sprig — gaps

Today (2): `Responses`, `Surveys`

Diffed against: <https://docs.sprig.com/reference/sprig-api/overview>

- [ ] `GET /v1/themes (Retrieve Themes)` — Sprig's AI-clustered themes over open-text answers - the breakdown dimension for the Responses table we already sync (high)

Note: Sprig's public read surface is genuinely tiny: GET /v1/surveys, GET /v1/responses, GET /v1/themes, plus GET /v2/users/{userId}. The users endpoint only fetches a single record by id (no list), so it is not syncable as a warehouse table; the remaining v2 endpoints are writes (Upsert a User, Purge Visitors). Two tables is therefore close to full coverage once themes is added.

## Squadcast — gaps

Today (9): `escalation_policies`, `incidents`, `postmortems`, `runbooks`, `schedules`, `services`, `slos`, `teams`, `users`

Diffed against: <https://developers.incidents.cloud.solarwinds.com/llms.txt>

- [ ] `incidents/{incidentID}/events (Get Incident Events)` — the incident timeline - acknowledge/reassign/resolve state transitions behind MTTA and MTTR (high)
- [ ] `squads` — lookup plus membership table resolving squad ids on incidents, services and escalation policies (high)
- [ ] `schedules/{scheduleID}/rotations and .../rotations/{id}/participants` — on-call rotations and who is in them; schedules are synced but are meaningless without rotations (high)
- [ ] `analytics (org-level and team-level)` — the vendor's headline MTTA/MTTR/incident-volume metrics (high)
- [ ] `incidents/tags` — incident tag values, the primary breakdown dimension for incident reporting (medium)
- [ ] `incidents/{incidentID}/notes` — responder commentary attached to incidents (medium)
- [ ] `incidents/additional-responders` — who else was pulled into an incident beyond the primary assignee (medium)
- [ ] `schedules/{scheduleID}/overrides` — on-call override history, needed for accurate coverage analysis (medium)
- [ ] `audit-logs` — configuration change history across the org (medium)
- [ ] `services/dependencies` — service dependency graph for blast-radius analysis on the services we already sync (medium)
- [ ] `status-pages/issues` — customer-facing issue records with their own lifecycle (low)
- [ ] `status-pages/maintenances` — planned maintenance windows to exclude from incident stats (low)

Note: Squadcast is now SolarWinds Incident Response; developers.incidents.cloud.solarwinds.com serves a complete llms.txt plus per-section .md files (e.g. /api-reference/incidents.md) that list every operation. Global event rules, extensions/webhooks, workflows and webforms are configuration and were excluded.

## Square — **thin**

Today (5): `catalog`, `customers`, `locations`, `payments`, `refunds`

Diffed against: <https://raw.githubusercontent.com/square/connect-api-specification/master/api.json>

- [ ] `POST /v2/orders/search (Orders)` — Square's headline commerce object with line items, discounts and taxes; payments alone cannot reconstruct what was sold (high)
- [ ] `POST /v2/inventory/counts/batch-retrieve and GET /v2/inventory/{catalog_object_id}/changes` — stock levels and the inventory change ledger for the catalog we already sync (high)
- [ ] `GET /v2/payouts and GET /v2/payouts/{payout_id}/payout-entries` — settlement/deposit reconciliation - maps payments and refunds to bank deposits (high)
- [ ] `POST /v2/invoices/search` — invoiced revenue is a separate money flow from card payments (high)
- [ ] `POST /v2/team-members/search (and GET /v2/team-members/jobs)` — lookup resolving the team_member_id stamped on payments, orders and shifts (high)
- [ ] `POST /v2/labor/shifts/search and POST /v2/labor/timecards/search` — labor hours per location, the denominator for sales-per-labor-hour (medium)
- [ ] `POST /v2/subscriptions/search and GET /v2/subscriptions/{id}/events` — recurring revenue plus subscription state transition history (medium)
- [ ] `GET /v2/disputes` — chargeback volume and outcomes against the payments we already sync (medium)
- [ ] `POST /v2/loyalty/accounts/search, /v2/loyalty/events/search, /v2/loyalty/rewards/search` — loyalty balances and point-earning events for repeat-customer analysis (medium)
- [ ] `GET /v2/gift-cards and GET /v2/gift-cards/activities` — outstanding gift card liability and the activity ledger behind it (medium)
- [ ] `GET /v2/customers/groups and GET /v2/customers/segments` — lookup tables resolving the group and segment ids on the customers we already sync (medium)
- [ ] `GET /v2/bookings and GET /v2/bookings/team-member-booking-profiles` — appointment bookings for service merchants, an entire unexposed vertical (medium)

Note: Square's OpenAPI 3.0 spec has 255 paths; PostHog exposes 5 tables and none of them is Orders, which is the object most Square analytics starts from. Many of the highest-value collections are POST search endpoints (SearchOrders, SearchInvoices, SearchSubscriptions, SearchTeamMembers) rather than GET lists, which may be why they were skipped. Also unexposed but lower value: merchants, vendors, cash drawer shifts, devices, transfer orders, terminal checkouts.

## Squarespace — gaps

Today (6): `inventory`, `orders`, `products`, `profiles`, `store_pages`, `transactions`

Diffed against: <https://developers.squarespace.com/commerce-apis/overview>

- [ ] `GET /v1/contacts (Contacts API)` — the marketing contact record, distinct from commerce profiles; holds newsletter/marketing state we have no source for (high)
- [ ] `GET /v1/commerce/discounts (Discounts API)` — lookup resolving the promo codes and discount rules applied on the orders we already sync (medium)
- [ ] `Contacts address book entries (GET under /v1/contacts/{contactId})` — shipping addresses per contact, useful for geographic breakdowns (low)
- [ ] `POST /v1/analytics/transaction-summaries` — per-contact lifetime order/donation/refund totals, though it requires supplying contactIds so it only works as a follow-on to a contacts sync (low)

Note: Squarespace's public Commerce API is small: Contacts, Analytics, Discounts, Products, Websites (store pages), Inventory, Orders, Transactions, Profiles, WebhookSubscriptions. PostHog covers 6 of the 8 data-bearing ones. Order fulfillments and inventory adjustments exist but are POST-only writes, not readable collections.

## StackOverflowForTeams — gaps

Today (6): `Answers`, `Articles`, `Collections`, `Questions`, `Tags`, `Users`

Diffed against: <https://api.stackoverflowteams.com/v3/swagger.json>

- [ ] `GET /teams/{team}/questions/{questionId}/comments` — comment volume is a core engagement signal and is entirely missing (high)
- [ ] `GET /teams/{team}/questions/{questionId}/answers/{answerId}/comments` — same engagement signal on answers, which we already sync (high)
- [ ] `GET /teams/{team}/communities` — lookup resolving the community a question/user belongs to; needed to slice knowledge activity by group (medium)
- [ ] `GET /teams/{team}/user-groups` — user group membership, the join table for per-team adoption reporting (medium)
- [ ] `GET /teams/{team}/tags/{tagId}/subject-matter-experts` — lookup mapping the tags we already sync to their designated experts (medium)
- [ ] `GET /teams/{team}/articles/{articleId}/comments` — engagement on articles, which we already sync (medium)
- [ ] `GET /teams/{team}/tags/{tagId}/tag-watchers and GET /teams/{team}/users/{userId}/watched-tags` — who follows which topic, an interest/expertise mapping (low)
- [ ] `GET /teams/{team}/questions/{questionId}/linked and /related` — question-to-question graph for duplicate and topic-cluster analysis (low)
- [ ] `GET /teams/{team}/articles/{articleId}/linked-questions` — links articles to the questions they answer (low)

Note: The swagger.json is public at https://api.stackoverflowteams.com/v3/swagger.json (the /v3/swagger/v1/swagger.json and /v3/swagger/v3/swagger.json paths 401). The readable API is small - 33 GET operations - so coverage of the six top-level collections is reasonable; the real gap is the comments sub-resources, which the vendor only exposes nested under questions/answers/articles.

## Statuscake — gaps

Today (11): `contact_groups`, `heartbeat_tests`, `maintenance_windows`, `pagespeed_history`, `pagespeed_tests`, `ssl_tests`, `uptime_alerts`, `uptime_history`, `uptime_locations`, `uptime_periods`, `uptime_tests`

Diffed against: <https://developers.statuscake.com/api/>

- [ ] `list-pagespeed-monitoring-locations (GET /pagespeed/locations)` — lookup table resolving the monitoring location codes carried on pagespeed_history rows; uptime_locations is already synced but its pagespeed twin is not (medium)

Note: Enumerated every operationId from the vendor's Redoc page (36 operations across contact-groups, heartbeat, locations, maintenance-windows, pagespeed, ssl, uptime). PostHog covers every list operation except the pagespeed locations lookup; no machine-readable spec is published (openapi.yaml / statuscake-go repo paths 404).

## Statuspage — gaps

Today (10): `component_groups`, `components`, `incident_templates`, `incidents`, `metric_providers`, `metrics`, `page_access_groups`, `page_access_users`, `pages`, `subscribers`

Diffed against: <https://developer.statuspage.io/>

- [ ] `pages/{page_id}/components/{component_id}/uptime` — per-component uptime percentage and outage duration over a range - Statuspage's headline reliability metric, not derivable from the component object (high)
- [ ] `pages/{page_id}/component-groups/{id}/uptime` — same uptime metric rolled up to the group we already sync (high)
- [ ] `pages/{page_id}/incidents/{incident_id}/postmortem` — postmortem body and publish state per incident, the write-up attached to incidents we already sync (medium)
- [ ] `organizations/{organization_id}/users` — org user roster; the only way to resolve the user IDs returned by the permissions endpoint (medium)
- [ ] `organizations/{organization_id}/permissions/{user_id}` — which pages each org user can administer - a membership table joining users to pages (medium)
- [ ] `pages/{page_id}/page_access_users/{page_access_user_id}/components` — membership table mapping restricted-audience users to the components they can see (medium)
- [ ] `pages/{page_id}/page_access_groups/{page_access_group_id}/components` — membership table mapping access groups to components; page_access_groups is synced without its contents (medium)
- [ ] `pages/{page_id}/incidents/{incident_id}/subscribers` — per-incident subscriber list, distinct from the page-level subscribers already synced (medium)
- [ ] `pages/{page_id}/subscribers/unsubscribed` — churned subscribers, excluded from the main subscribers list (low)
- [ ] `pages/{page_id}/subscribers/histogram_by_state` — subscriber counts bucketed by state for growth reporting (low)

Note: There is NO GET on pages/{page_id}/metrics/{metric_id}/data - only POST (submit) and DELETE - so historical metric datapoints are not retrievable via the API and are correctly absent. Incident updates likewise have no list GET (only PUT/PATCH); they arrive embedded in the incident object.

## Stigg — gaps

Today (7): `addons`, `coupons`, `customers`, `features`, `plans`, `products`, `subscriptions`

Diffed against: <https://app.stainless.com/api/spec/documented/stigg/openapi.documented.yml>

- [ ] `/api/v1/usage` — feature usage measurements - the metering data Stigg exists to record; nothing usage-related is synced today (high)
- [ ] `/api/v1/events` — raw metering events behind usage-based billing (high)
- [ ] `/api/v1/credits/ledger` — credit transaction ledger - grants, consumption and expiry as a time series (high)
- [ ] `/api/v1/plans/{planId}/entitlements` — lookup resolving which features each synced plan grants and at what limits (high)
- [ ] `/api/v1/customers/{id}/entitlements` — effective per-customer entitlements, the join between synced customers, plans and features (high)
- [ ] `/api/v1/plans/{id}/charges (and /overage-charges)` — price line items per plan; the plans table carries no pricing breakdown (high)
- [ ] `/api/v1/credits/grants` — credit grants per customer, the balance side of the ledger (high)
- [ ] `/api/v1/addons/{addonId}/entitlements` — feature grants attached to the addons already synced (medium)
- [ ] `/api/v1/addons/{id}/charges` — addon pricing line items (medium)
- [ ] `/api/v1/usage/{customerId}/history/{featureId}` — per-customer feature usage over time for consumption trend analysis (medium)
- [ ] `/api/v1/credits/custom-currencies` — lookup resolving currency IDs that appear on ledger and grant rows (medium)
- [ ] `/api/v1/customers/{id}/promotional-entitlements` — manually granted overrides that explain entitlement drift from the plan (medium)

Note: Spec discovered via docs.stigg.io/llms.txt, which points at the Stainless-hosted OpenAPI. The seven synced tables are exactly the seven top-level catalog collections; every sub-resource (entitlements, charges) and the whole credits/usage/events metering surface is missing, which is the analytically interesting half of the API.

## StockData — gaps

Today (6): `dividends`, `eod`, `intraday`, `news`, `quote`, `splits`

Diffed against: <https://www.stockdata.org/documentation>

- [ ] `/v1/entity/search` — ticker/entity lookup that resolves the symbols carried on every eod, intraday, quote, dividend and split row (name, exchange, industry, type) (high)
- [ ] `/v1/news/stats/aggregation` — per-entity news sentiment and volume aggregates - the headline output of StockData's news analysis (medium)
- [ ] `/v1/news/sources` — lookup resolving the source identifiers on synced news rows (medium)
- [ ] `/v1/news/stats/intraday` — intraday time series of entity news volume and sentiment (medium)
- [ ] `/v1/news/stats/trending` — trending entities by news activity over a window (medium)
- [ ] `/v1/entity/industry/list` — industry lookup for grouping tickers in breakdowns (medium)
- [ ] `/v1/data/intraday/adjusted` — split/dividend-adjusted intraday bars; the synced intraday table uses the unadjusted /data/intraday endpoint, so long-range series are discontinuous (medium)
- [ ] `/v1/entity/type/list` — entity type lookup (stock, etf, index, crypto, currency) (low)

Note: Confirmed against the PostHog source settings that the synced `intraday` table hits /data/intraday (unadjusted), so /data/intraday/adjusted is a real second dataset rather than a duplicate. The crypto/forex EOD section reuses /data/eod with a currency symbol, so it is already covered.

## StreamElements — gaps

Today (9): `activities`, `bot_commands`, `bot_timers`, `channel`, `points_alltime_leaderboard`, `points_leaderboard`, `store_items`, `store_redemptions`, `tips`

Diffed against: <https://dev.streamelements.com/api/v1/projects/cHJqOjM1MTI2/table-of-contents>

- [ ] `GET /sessions/{channel}` — live session totals (followers, subs, tips, cheers, hosts, raids for the current stream) - the headline StreamElements dashboard metric (high)
- [ ] `GET /points/{channel}/watchtime` — watchtime leaderboard; the two synced points tables cover loyalty points only, not the watchtime that earns them (high)
- [ ] `GET /stats/{channel}` — channel-level aggregate statistics, no equivalent in any synced table (high)
- [ ] `GET /contests/{channel}/history` — completed contests with entries and payouts - a transactional record of channel engagement (medium)
- [ ] `GET /giveaways/{channel}/history` — completed giveaways with winners, the same for the giveaway feature (medium)
- [ ] `GET /songrequests/{channel}/history` — song request history, an event stream of viewer-driven media requests (medium)
- [ ] `GET /chatstats/{username}/stats` — chat message and emote statistics per user, the chat-side counterpart to the activity feed (medium)
- [ ] `GET /tips/{channel}/leaderboard` — vendor-computed tip leaderboard alongside the raw tips already synced (medium)
- [ ] `GET /sessions/{channel}/top` — top contributors for the current session (top tipper, top cheerer) (medium)
- [ ] `GET /channels/{channel}/details` — richer channel profile than /channels/me, and resolves channel IDs appearing on other rows (medium)
- [ ] `GET /contests/{channel}` — currently open contests, to pair with the history table (low)
- [ ] `GET /bot/{channel}/levels` — lookup mapping usernames to bot permission levels referenced by commands (low)

Note: The Stoplight docs render entirely client-side, so the resource list had to be pulled from the vendor's own table-of-contents API (project cHJqOjM1MTI2, found via a web.archive.org CDX listing of dev.streamelements.com). The legacy developers.streamelements.com host no longer resolves. Existence of the sessions, songrequest, contests, stats and themes routes was independently confirmed by unauthenticated probes of api.streamelements.com/kappa/v2 returning 401/200 rather than 404. Config surfaces (overlays, themes, filters, modules, loyalty settings) were excluded.

## Stytch — gaps

Today (4): `members`, `organizations`, `sessions`, `users`

Diffed against: <https://stytch.com/docs/sitemap.xml>

- [ ] `b2b/api/rbac/get-policy (and consumer/api/rbac/get-rbac-policy)` — the roles, resources and scopes lookup that resolves the role IDs carried on every synced member (high)
- [ ] `b2b/api/sso/shared/get-sso-connections` — per-organization SAML/OIDC/external connections; lookup resolving the connection IDs in member.sso_registrations (medium)
- [ ] `b2b/api/connected-apps/consent-management/get-connected-apps-member` — which apps each member has authorized - a membership/consent table over users we already sync (medium)
- [ ] `b2b/api/connected-apps/consent-management/get-connected-apps-organization` — org-level view of authorized connected apps (medium)
- [ ] `consumer/api/connected-apps/consent-management/get-connected-apps-user` — same consent mapping on the consumer side (medium)
- [ ] `b2b/api/scim/connection-management/get-scim-connection + scim/scim-groups/get-scim-connection-groups` — SCIM groups and their implicit role assignments, which explain how members got their roles (medium)
- [ ] `b2b/api/connected-apps/application-management/search-connected-apps` — registry of connected apps, the lookup the consent tables point at (medium)
- [ ] `b2b/api/m2m/m2m-client/search-m2m-clients (and consumer equivalent)` — machine-to-machine client inventory with scopes; a distinct principal type from users and members (medium)
- [ ] `consumer/api/passkeys-webauthn/list-webauthn-credentials` — registered passkeys per user, for auth-method adoption analysis (low)

Note: Stytch publishes no OpenAPI spec and its Mintlify llms.txt omits the API reference, so the resource list was enumerated from the 1,637 /docs/api-reference/\* URLs in the docs sitemap and spot-checked against individual .md pages. Only search/list-shaped endpoints were considered - most of the API is action-oriented (authenticate, exchange, revoke) and not warehouse material. The Workspace Management API (pwa/api/v3: projects, environments, metrics) needs workspace-level credentials rather than a project key, and its metrics object is only a user/M2M-client count, so it was left out.

## SumoLogic — gaps

Today (13): `collector_sources`, `collectors`, `connections`, `dashboards`, `field_extraction_rules`, `health_events`, `ingest_budgets`, `logs`, `monitors`, `partitions`, `roles`, `scheduled_views`, `users`

Diffed against: <https://api.sumologic.com/docs/sumologic-api.yaml>

- [ ] `/v1/slos (and /v1/slos/sli)` — SLO definitions, SLIs and error budgets - the headline reliability objects, with no equivalent among the synced monitors (high)
- [ ] `/v1/fields (plus /v1/fields/builtin, /v1/fields/dropped)` — field metadata lookup resolving the field names that appear across logs, partitions and extraction rules (high)
- [ ] `/v1/mutingSchedules` — muting windows that explain gaps in monitor alerting - required to interpret the health_events already synced (medium)
- [ ] `/v2/content/folders (with /v2/content/{id}/path)` — content folder tree, the lookup that resolves parentId on dashboards, searches and monitors (medium)
- [ ] `/v1/otCollectors` — OpenTelemetry collector inventory; the synced collectors table comes from the legacy Collector Management API and misses these entirely (medium)
- [ ] `/v1/logSearches` — saved log searches, the reusable query definitions behind scheduled views and dashboards (medium)
- [ ] `/v2/metricsSearches` — saved metrics searches, the metrics-side counterpart (medium)
- [ ] `/v1/lookupTables` — user-maintained lookup tables used to enrich queries; genuine reference data (medium)
- [ ] `/v1/organizations/usages (and /v1/account/usage/report)` — ingest and credit consumption over time - the core cost-analysis dataset for a Sumo warehouse (medium)
- [ ] `/v1/budgets (and /v1/budgets/usage)` — capacity budgets and their consumption; distinct from the ingestBudgets already synced (medium)
- [ ] `/v1/parsers` — parser definitions that shape how log fields are extracted (low)
- [ ] `/v2/macros` — query macro definitions referenced by saved searches (low)

Note: Diffed against the vendor's own OpenAPI 3.0 spec (294 paths). The synced collectors and collector_sources tables come from the separate Collector Management API documented on help.sumologic.com and are correctly absent from this spec. Excluded config/plumbing: accessKeys, tokens, oauth clients, saml, policies, passwordPolicy, serviceAllowlist, data masking/deletion/forwarding rules, sourceTemplates. The tracing API (spanquery/tracequery) is asynchronous job-based and not a practical warehouse table.

## SurveyMonkey — gaps

Today (5): `collectors`, `survey_pages`, `survey_questions`, `survey_responses`, `surveys`

Diffed against: <https://api.surveymonkey.com/v3/docs?shell>

- [ ] `GET /v3/surveys/{id}/rollups (also /pages/{id}/rollups and /questions/{id}/rollups)` — vendor-computed answer counts per question and choice - the aggregate every survey analysis starts from, without reprocessing raw responses (high)
- [ ] `GET /v3/surveys/{id}/trends (also page- and question-level)` — response and answer trends bucketed over time, the standard breakdown dimension (high)
- [ ] `GET /v3/collectors/{id}/messages` — email invite and reminder messages sent per collector; the send side of the funnel is entirely missing today (high)
- [ ] `GET /v3/collectors/{collector_id}/messages/{message_id}/stats` — per-message delivery, open, click, bounce and response counts - the email performance metric (high)
- [ ] `GET /v3/collectors/{id}/recipients (and /messages/{id}/recipients)` — recipient-level delivery and response state, the join between contacts and responses (high)
- [ ] `GET /v3/contact_lists (and /v3/contact_lists/{id}/contacts)` — contact lists and membership, the audience definition behind each collector (medium)
- [ ] `GET /v3/contacts` — lookup resolving the contact IDs on recipients and responses (medium)
- [ ] `GET /v3/collectors/{id}/stats` — collector-level response and completion counts (medium)
- [ ] `GET /v3/survey_folders` — lookup resolving the folder_id carried on synced surveys (medium)
- [ ] `GET /v3/contact_fields` — lookup naming the custom contact fields that appear on contacts and recipients (medium)
- [ ] `GET /v3/groups/{id}/members (and /v3/groups)` — team membership table resolving the user IDs that own surveys (medium)
- [ ] `GET /v3/groups/{id}/activities` — activity log per group, useful for adoption and audit reporting (medium)

Note: Enumerated from the vendor's full single-page reference; GET availability was confirmed from the method/description pairs rather than assumed (e.g. rollups is documented as "Returns rollups for all questions in a survey"). Lower-value lookups left out of the capped list: survey_languages, survey_categories, survey_templates, team_survey_templates, question_bank/questions, benchmark_bundles, roles, workgroups and workgroup shares.

## SurveySparrow — **thin**

Today (5): `contact_lists`, `contacts`, `questions`, `responses`, `surveys`

Diffed against: <https://developers.surveysparrow.com/rest-apis>

- [ ] `GET /v3/tickets` — Support tickets raised from survey responses - a core analytical object with status, assignee and SLA fields (high)
- [ ] `GET /v3/metrics and /v3/metrics/responses` — NPS/CSAT/CES score metrics - the vendor's headline number, currently only derivable by re-aggregating raw responses (high)
- [ ] `GET /v3/users` — Lookup table resolving the user IDs already carried on surveys, tickets and responses (high)
- [ ] `GET /v3/channels` — Lookup table for the distribution channel ID on every response (email/link/SMS/embed), needed for per-channel response-rate analysis (high)
- [ ] `GET /v3/reputation_reviews` — Online review records from the Reputation Management product - a whole analytical dataset with no coverage (high)
- [ ] `GET /v3/tickets/{id}/comments` — Ticket conversation history for resolution-time and agent-activity analysis (medium)
- [ ] `GET /v3/contact_properties` — Lookup table defining the custom contact fields whose values appear on synced contacts (medium)
- [ ] `GET /v3/ticket_fields` — Lookup table decoding custom ticket field IDs (medium)
- [ ] `GET /v3/teams` — Lookup table for the team IDs on users and tickets (medium)
- [ ] `GET /v3/reports and /v3/reports/question` — Per-question aggregate report dimensions (distributions, averages) without recomputing from responses (medium)
- [ ] `GET /v3/survey_subjects, /v3/survey_subject_evaluators, /v3/survey_subject_report` — Employee 360 subject/evaluator membership and scores - the entire 360-review dataset (medium)
- [ ] `GET /v3/reputation_platforms and /v3/reputation_app_platforms` — Lookup tables resolving the platform IDs on reputation reviews (medium)

Note: Static endpoint list in products/warehouse_sources/backend/temporal/data_imports/sources/surveysparrow/settings.py (5 paths, no dynamic discovery). Full v3 GET-endpoint list enumerated from https://developers.surveysparrow.com/sitemap.xml, whose `get-v-3-\*` slugs map 1:1 to endpoints. The v3 API has ~30 resource categories; PostHog exposes 5.

## Svix — **thin**

Today (2): `applications`, `event_types`

Diffed against: <https://api.svix.com/api/v1/openapi.json>

- [ ] `GET /api/v1/app/{app_id}/msg` — The message table - every webhook payload sent, the core transactional object of the product (high)
- [ ] `GET /api/v1/app/{app_id}/attempt/msg/{msg_id} and /attempt/endpoint/{endpoint_id}` — Delivery attempts with response status, latency and retry count - the only way to analyze webhook reliability (high)
- [ ] `GET /api/v1/app/{app_id}/endpoint` — Lookup table resolving the endpoint IDs carried on every attempt, plus per-endpoint filter/rate-limit config (high)
- [ ] `GET /api/v1/app/{app_id}/endpoint/{endpoint_id}/stats` — Pre-aggregated success/pending/fail counts per endpoint (medium)
- [ ] `GET /api/v1/app/{app_id}/msg/{msg_id}/endpoint` — Message-to-endpoint fan-out membership table (medium)
- [ ] `GET /api/v1/stream and /api/v1/stream/{stream_id}/sink` — Svix Streams objects - a second product surface with zero coverage (medium)
- [ ] `GET /api/v1/stream/{stream_id}/sink/{sink_id}/events` — Stream event records, the analytical rows of the Streams product (medium)
- [ ] `GET /api/v1/app/{app_id}/integration` — Per-application integrations, a lookup for which partner owns an endpoint (medium)
- [ ] `GET /ingest/api/v1/source and /ingest/api/v1/source/{source_id}/endpoint` — Svix Ingest sources and their routing - inbound-webhook coverage (low)
- [ ] `GET /api/v1/background-task` — Async task history (recover, replay, expunge) with status transitions (low)
- [ ] `GET /api/v1/stream/event-type` — Lookup table for stream event type names, mirroring the already-synced event_types (low)

Note: Static 2-endpoint config in sources/svix/settings.py, no dynamic discovery. The spec has ~80 operations. Note the usual 'exclude webhook endpoints' rule inverts here: Svix IS a webhook platform, so its endpoints/messages/attempts are the product's transactional data, not integration plumbing. All message-level resources are nested under /app/{app_id}, so a sync must fan out over the applications table already synced.

## Swarmia — gaps

Today (6): `capex`, `capex_employees`, `dora`, `fte`, `investment`, `pull_requests`

Diffed against: <https://help.swarmia.com/settings/integrations/swarmia-apis/export-api>

- [ ] `GET /api/v0/teams` — Lookup table resolving the team names that every team-level report row is keyed on, including parent-team hierarchy and member lists (high)
- [ ] `GET /api/v1/reports/ai/adoption/users-and-licenses` — AI assistant adoption and license utilization - a headline metric with no v0 equivalent and no coverage today (high)
- [ ] `GET /api/v1/reports/custom/{id}` — Any custom report saved in the app, letting users sync breakdowns the fixed v0 endpoints cannot express (medium)
- [ ] `GET /api/v1/reports/metrics/code` — v1 successor to /pullRequests; revision 2 adds teamFte and mergedPrsByFte columns the v0 export does not return (medium)
- [ ] `GET /api/v1/reports/metrics/dora` — v1 successor to /dora on the non-deprecated API surface (low)

Note: The v0 Export API is 100% covered - all six documented endpoints (/pullRequests, /dora, /investment, /capex, /capex/employees, /fte) map to the six synced tables. The gap is that the vendor explicitly states v0 'will eventually become deprecated' in favor of the v1 Reports API (https://help.swarmia.com/settings/integrations/swarmia-apis/built-in-reports.md, which embeds an OpenAPI 3.1 doc served from https://app.swarmia.com/api/v1). The Time offs API (/api/v0/time-offs) has only create/get-by-id/update/delete, no list endpoint, so it is not syncable.

## Taboola — gaps

Today (5): `campaign_items`, `campaign_summary_by_day`, `campaigns`, `conversion_rules`, `top_campaign_content`

Diffed against: <https://developers.taboola.com/backstage-api/reference/campaign-summary-report>

- [ ] `GET /{account_id}/reports/campaign-summary/dimensions/site_breakdown` — Per-publisher-site performance, the headline breakdown for native advertising and the basis of site blocking decisions (high)
- [ ] `GET /users/current/allowed-accounts` — Lookup table of accounts and their IDs - resolves the account_id every other table is scoped by, and enumerates what can be synced (high)
- [ ] `GET /{account_id}/advertisers` — Lookup table resolving the advertiser IDs carried on synced campaigns (high)
- [ ] `GET /{account_id}/reports/campaign-summary/dimensions/country_breakdown` — Geo performance breakdown, one of the most commonly wanted report cuts (high)
- [ ] `GET /{account_id}/reports/campaign-summary/dimensions/item_breakdown` — Per-creative spend and conversion metrics, joining directly to the already-synced campaign_items (high)
- [ ] `GET /{account_id}/reports/campaign-summary/dimensions/platform_breakdown` — Desktop/mobile/tablet split, needed for device-level bid analysis (medium)
- [ ] `GET /{account_id}/reports/campaign-summary/dimensions/region_breakdown and /dma_breakdown` — Sub-national geo dimensions for US and regional targeting analysis (medium)
- [ ] `GET /{account_id}/campaigns/{campaign_id}/items/{item_id}/children/` — Child creative variants under a parent item - spend is reported at this grain for motion and multi-variant ads (medium)
- [ ] `GET /{account_id}/campaigns/{campaign_id}/targeting/audience_segments, /contextual_segments, /my_audiences, /postal_code` — Targeting configuration per campaign, required to explain why performance differs between campaigns (medium)
- [ ] `GET /{account_id}/dictionary/audience_segments/{country} and /dictionary/contextual_segments/` — Lookup tables resolving the segment IDs used in campaign targeting (medium)
- [ ] `GET /{account_id}/my_audiences and /{account_id}/combined_audiences/` — First-party and combined audience definitions with size, referenced by targeting rows (medium)
- [ ] `GET /resources/campaigns_properties/category, /operating_systems, /platforms, /resources/countries, /resources/languages` — Static lookup tables decoding the enum codes stored on campaigns and campaign_items (low)

Note: Full Backstage API path list extracted from the ReadMe reference page HTML (developers.taboola.com serves an SPA, so sitemap.xml 404s and sitemap-0.xml returns HTML). The connector pins a single dimension per report: sources/taboola/settings.py uses /reports/campaign-summary/dimensions/campaign_day_breakdown and /reports/top-campaign-content/dimensions/item_breakdown. The other campaign-summary dimensions documented on that page (site_breakdown, country_breakdown, region_breakdown, dma_breakdown, platform_breakdown, user_segment_breakdown, item_breakdown) are the same report re-cut and are unreachable today.

## Tailscale — gaps

Today (4): `configuration_audit_logs`, `devices`, `keys`, `users`

Diffed against: <https://api.tailscale.com/api/v2?outputOpenapiSchema=true>

- [ ] `GET /tailnet/{tailnet}/logging/network` — Network flow logs - per-connection traffic records, the one genuinely high-volume analytical table in the API and a direct sibling of the audit logs already synced (high)
- [ ] `GET /device/{deviceId}/routes` — Subnet routes and exit-node advertisements per device, including which are approved - the state that explains tailnet topology (medium)
- [ ] `GET /device/{deviceId}/attributes` — Device posture attributes (OS version, disk encryption, custom attributes) used in ACL posture rules, keyed to devices already synced (medium)
- [ ] `GET /tailnet/{tailnet}/services` — Tailscale Services inventory, a first-class resource with no coverage (medium)
- [ ] `GET /tailnet/{tailnet}/services/{serviceName}/devices` — Service-to-device hosting membership, joining services to the synced devices table (medium)
- [ ] `GET /tailnet/{tailnet}/user-invites` — Outstanding and accepted user invites with status - onboarding funnel data alongside the synced users table (low)
- [ ] `GET /device/{deviceId}/device-invites` — Device sharing invites and their acceptance state (low)

Note: Fetched the live OpenAPI 3.1 schema (58 paths). Static 4-endpoint config in sources/tailscale/settings.py, no dynamic discovery. Coverage of the tailnet-level list endpoints is reasonable; the notable miss is network flow logs, which sit on the same /logging prefix as the audit logs already synced and are by far the largest analytical dataset the API exposes. ACL, DNS, contacts, settings, webhooks and OAuth apps are all config and correctly out of scope.

## Tavus — gaps

Today (4): `conversations`, `personas`, `replicas`, `videos`

Diffed against: <https://docs.tavus.io/openapi.yaml>

- [ ] `GET /v2/pals` — Current replacement for personas - the lookup table resolving the agent ID carried on every conversation (high)
- [ ] `GET /v2/faces` — Current replacement for replicas - the lookup table for the face/avatar ID on conversations and videos (high)
- [ ] `GET /v2/transcriptions` — Conversation transcripts, the primary analytical output of a conversational-video product and completely uncovered (high)
- [ ] `GET /v2/conversations/{conversation_id}/canvas/interactions` — Per-conversation interaction events (clicks, inputs, component responses) - the event stream under the synced conversations table (high)
- [ ] `GET /v2/deployments` — Deployments group conversations by embed/widget surface; needed to attribute conversation volume to a channel (medium)
- [ ] `GET /v2/objectives` — Lookup table for the objectives a PAL is scored against, the basis of conversation outcome analysis (medium)
- [ ] `GET /v2/documents` — Knowledge-base documents attached to PALs, with crawl status (medium)
- [ ] `GET /v2/skills and GET /v2/pals/{pal_id}/skills` — Skill catalog plus the PAL-to-skill membership table (medium)
- [ ] `GET /v2/tools and GET /v2/pals/{pal_id}/tools` — Tool definitions and PAL-to-tool membership, needed to interpret tool-call activity (medium)
- [ ] `GET /v2/voices` — Lookup table resolving the voice ID configured on PALs and videos (medium)
- [ ] `GET /v2/lipsync` — Lipsync generation jobs with status and duration, a sibling of the synced videos table (low)
- [ ] `GET /v2/replacements` — Replacement (background swap) jobs with status (low)

Note: Important: the current spec no longer contains /v2/personas or /v2/replicas - they have been superseded by /v2/pals and /v2/faces. Two of PostHog's four synced tables therefore target endpoints absent from today's API reference and should be re-verified against a live account. Static 4-endpoint config in sources/tavus/settings.py, no dynamic discovery; the spec exposes 20 GET list endpoints.

## TawkTo — gaps

Today (4): `chats`, `members`, `properties`, `tickets`

Diffed against: <https://help.tawk.to/article/rest-api>

- [ ] `chat statistics report (by agent, tag, department, date)` — the vendor's headline aggregate for support performance; also exposes agent/tag/department as breakdown dimensions we have no table for (high)
- [ ] `knowledge base articles (list)` — lets a warehouse user join deflection and self-serve content against chats and tickets (low)

Note: tawk.to's full REST reference is access-gated (you must be approved before you get the docs link), so no public endpoint list exists. The only public vendor page enumerates capabilities in prose. PostHog's own settings.py says the same. Gaps below are quoted from that page's capability list, not from a spec — exact RPC method names (the API is POST-only RPC style, e.g. `chat.list`) cannot be confirmed without approved access, so an implementer must obtain API access first.

## Teachable — gaps

Today (5): `course_enrollments`, `courses`, `pricing_plans`, `transactions`, `users`

Diffed against: <https://docs.teachable.com/reference/listcourses>

- [ ] `courses/{course_id}/progress` — per-student completion percentage — the headline learning metric, and the only way to measure course engagement (high)
- [ ] `courses/{course_id}/lectures/{lecture_id}` — lecture lookup table resolving the lecture IDs referenced by progress and quiz data (high)
- [ ] `courses/{course_id}/lectures/{lecture_id}/quizzes/{quiz_id}/responses` — individual learner answers and scores — the assessment fact table (medium)
- [ ] `courses/{course_id}/lectures/{lecture_id}/quizzes` — quiz lookup needed to interpret quiz responses (medium)

Note: Full v1 path list read out of the embedded ReadMe OAS on the reference page: courses, enrollments, lectures, quizzes, quiz responses, progress, pricing_plans, transactions, users, webhooks. Lectures/quizzes/progress are per-course sub-resources that must be fanned out over the courses we already sync.

## Teamcity — gaps

Today (8): `agents`, `build_types`, `builds`, `changes`, `problem_occurrences`, `projects`, `test_occurrences`, `vcs_roots`

Diffed against: <https://teamcity.jetbrains.com/app/rest/swagger.json>

- [ ] `tests` — test lookup table resolving the test IDs carried by test_occurrences we already sync (high)
- [ ] `problems` — problem lookup table resolving the problem IDs carried by problem_occurrences we already sync (high)
- [ ] `users` — user lookup resolving build triggeredBy, change authors and investigation assignees (high)
- [ ] `builds/{buildLocator}/statistics` — per-build metric values (duration, queue time, artifact size, coverage) — TeamCity's headline build metrics, not present on the build object (high)
- [ ] `investigations` — who owns each failing build/test and its state — failure-ownership analysis (medium)
- [ ] `mutes` — muted tests/problems, required to compute a truthful failure rate from test_occurrences (medium)
- [ ] `agentPools` — lookup grouping agents we already sync into pools for capacity analysis (medium)
- [ ] `vcs-root-instances` — resolves the per-build-config VCS root instance and repository state that builds and changes reference (medium)
- [ ] `buildTypes/{btLocator}/branches` — branch dimension for per-branch build success/duration breakdowns (medium)
- [ ] `userGroups` — group membership lookup for user-level roll-ups (low)
- [ ] `audit` — server-side change history (config edits, permission changes) (low)
- [ ] `buildQueue` — queued builds with wait position — queue-pressure analysis, though state is ephemeral (low)

Note: Diffed against the live 2026.1 Swagger 2.0 spec served by JetBrains' own public TeamCity server (268 paths, 31 tags). Core build data is covered; what's missing is mostly lookup tables for IDs we already sync and the per-build statistics values.

## Teamtailor — gaps

Today (5): `candidates`, `departments`, `job_applications`, `jobs`, `users`

Diffed against: <https://docs.teamtailor.com/api/collections/14157246/TVzSiGxA>

- [ ] `stages` — pipeline stage lookup resolving the stage each job_application sits in — without it application data has no funnel (high)
- [ ] `movements` — candidate stage-transition history — the fact table for time-in-stage and conversion analysis (high)
- [ ] `reject-reasons` — lookup resolving the rejection reason IDs on job applications (high)
- [ ] `locations` — location lookup for the jobs we already sync; standard hiring breakdown dimension (high)
- [ ] `job-offers` — offer records with status — the bottom of the hiring funnel (medium)
- [ ] `interviews` — scheduled interview events per application, needed for interview-load and scheduling metrics (medium)
- [ ] `scorecard-scores` — per-criterion interview ratings — the structured evaluation data (medium)
- [ ] `custom-field-values` — customer-defined attributes on candidates and jobs that most reporting depends on (medium)
- [ ] `nps-responses` — candidate experience NPS, a headline recruiting metric (medium)
- [ ] `requisitions` — approved headcount requests, joins hiring demand to jobs (medium)
- [ ] `team-memberships` — membership table linking the users we sync to teams (medium)
- [ ] `stage-types` — lookup classifying stages into kinds, needed to compare funnels across differently-named pipelines (medium)

Note: docs.teamtailor.com is a published Postman collection, not an OpenAPI site — the resource list was read from the collection JSON at the URL above (~35 GET collections on https://api.teamtailor.com/v1). PostHog covers 5 of them, and every pipeline lookup table is missing.

## Teamwork — gaps

Today (9): `comments`, `companies`, `milestones`, `people`, `projects`, `tags`, `tasklists`, `tasks`, `timelogs`

Diffed against: <https://apidocs.teamwork.com/api/oas/download?slug=teamwork&api_version=v3>

- [ ] `workflows/{workflowId}/stages.json` — board stage lookup resolving the stage each task sits in — no funnel or cycle-time analysis without it (high)
- [ ] `people/utilization.json` — Teamwork's headline billable-utilization metric, not derivable from raw timelogs alone (high)
- [ ] `reporting/financial/data.json (and /totals.json)` — project profitability, cost and revenue — the core financial fact table (high)
- [ ] `projectcategories.json` — category lookup for the projects we already sync (high)
- [ ] `expenses.json (v1)` — non-time project costs, required for accurate project margin (medium)
- [ ] `invoices.json (v1)` — billed amounts per project, joins timelogs to revenue (medium)
- [ ] `timesheets.json` — submitted/approved timesheet state on top of raw timelogs (medium)
- [ ] `customfields.json (plus tasks/{id}/customfields.json, projects/{id}/customfields.json)` — customer-defined attributes most Teamwork reporting slices by (medium)
- [ ] `jobroles.json` — role lookup for the people we already sync; drives rate and utilization breakdowns (medium)
- [ ] `risks.json` — project risk register, a first-class project object with status history (medium)
- [ ] `teams.json + teams/users.json (v1)` — team membership table linking people to teams (medium)
- [ ] `latestactivity.json` — cross-object activity stream for engagement and change analysis (low)

Note: Teamwork publishes three separate specs behind the same downloader (api_version=v1 / v3 / endpoints-by-object). The documented URLs in the payload point at the 'endpoints-by-object' subset (63 paths); the real surface is 302 v3 paths plus 240 v1 paths. Some listed gaps only exist on v1 (expenses, invoices, teams).

## Telnyx — **thin**

Today (7): `AmdDetailRecords`, `ConferenceDetailRecords`, `ConferenceParticipantDetailRecords`, `MediaStorageDetailRecords`, `MessagingDetailRecords`, `VerifyDetailRecords`, `WirelessUsageDetailRecords`

Diffed against: <https://raw.githubusercontent.com/team-telnyx/openapi/master/openapi/spec3.json>

- [ ] `/phone_numbers` — lookup resolving the numbers that appear on every messaging, voice and verify detail record (high)
- [ ] `/messaging_profiles` — lookup resolving the messaging_profile_id carried by MessagingDetailRecords (high)
- [ ] `/connections (also /credential_connections, /ip_connections)` — lookup resolving the connection_id on voice/conference detail records (high)
- [ ] `/conferences` — conference metadata lookup for ConferenceDetailRecords and ConferenceParticipantDetailRecords (high)
- [ ] `/messaging_profile_metrics` — Telnyx's headline delivery/throughput metric per profile (high)
- [ ] `/charges_summary and /charges_breakdown` — account spend by product — turns usage records into cost analysis (high)
- [ ] `/verify_profiles` — lookup resolving the verify profile on VerifyDetailRecords (medium)
- [ ] `/sim_cards` — lookup resolving the SIM referenced by WirelessUsageDetailRecords (medium)
- [ ] `/invoices` — billed amounts per period for reconciliation against usage (medium)
- [ ] `/call_events` — voice call lifecycle events, finer-grained than conference detail records (medium)
- [ ] `/recordings and /recording_transcriptions` — recording inventory and transcripts tied to calls already in the detail records (medium)
- [ ] `/porting_orders and /portouts` — number-porting pipeline with state transitions (low)

Note: PostHog exposes only the seven `record\_type` variants of GET /v2/detail_records. Telnyx's public OpenAPI 2.0.0 spec has 791 paths (~230 listable collections). The usage fact tables are the right core, but every dimension table that resolves the IDs inside those records is absent, so the synced data can't be joined to anything human-readable.

## Tempo — gaps

Today (7): `accounts`, `customers`, `holiday_schemes`, `plans`, `teams`, `workload_schemes`, `worklogs`

Diffed against: <https://apidocs.tempo.io/tempo-openapi.yaml>

- [ ] `/4/work-attributes and /4/worklogs/work-attribute-values` — the customer-defined breakdown dimensions attached to the worklogs we already sync; without them worklog reporting can't be sliced (high)
- [ ] `/4/team-memberships (POST /search)` — membership table linking users to the teams we already sync (high)
- [ ] `/4/account-links` — lookup joining the accounts we sync to Jira projects/issues — the bridge between Tempo and Jira data (high)
- [ ] `/4/reports/costs-and-revenues` — Tempo's headline cost/revenue report over logged time (high)
- [ ] `/4/periods` — timesheet period boundaries, required to aggregate worklogs the way Tempo does (medium)
- [ ] `/4/timesheet-approvals/waiting and /4/timesheet-approvals/logs/search` — timesheet approval state and its transition history (medium)
- [ ] `/4/account-categories and /4/account-category-types` — category lookups classifying the accounts we already sync (medium)
- [ ] `/4/global-rates/by-role and /4/billing-rates-tables` — billing/cost rates needed to convert worklog hours into money (medium)
- [ ] `/4/user-schedule` — per-user working schedule — the denominator for utilization and capacity (medium)
- [ ] `/4/projects and /4/project-attributes` — Tempo-side project records and their attributes that plans and worklogs reference (medium)
- [ ] `/4/roles` — role lookup used by rates and plan allocations (medium)
- [ ] `/4/programs and /4/portfolios` — higher-level grouping above plans for portfolio-level roll-ups (low)

Note: apidocs.tempo.io is a Redoc page; the spec is at ./tempo-openapi.yaml (~55 collections under /4). Several Tempo collections are only listable via a POST .../search endpoint rather than GET (team-memberships, worklogs/work-attribute-values, skill-assignments, generic-resources) — an implementer must POST an empty filter body to page them.

## TemporalIO — gaps

Today (2): `workflow_histories`, `workflows`

Diffed against: <https://raw.githubusercontent.com/temporalio/api/master/openapi/openapiv3.yaml>

- [ ] `namespaces/{namespace}/schedules (ListSchedules)` — schedule definitions and their recent action results — lookup resolving which schedule spawned the workflows we already sync (high)
- [ ] `namespaces (ListNamespaces)` — namespace lookup with retention and archival config; the top-level partition of every other table (medium)
- [ ] `namespaces/{namespace}/activities (ListActivities)` — activity-level state including paused/retrying activities, without reconstructing it from raw history events (medium)
- [ ] `namespaces/{namespace}/task-queues/{task_queue.name} (DescribeTaskQueue)` — backlog depth and poller counts per task queue — the key operational health metric (medium)
- [ ] `namespaces/{namespace}/batch-operations (ListBatchOperations)` — bulk terminate/signal/reset jobs and their progress, which explain mass workflow state changes (medium)
- [ ] `namespaces/{namespace}/workers (ListWorkers)` — worker fleet inventory for attributing workflow execution to hosts/builds (medium)
- [ ] `namespaces/{namespace}/archived-workflows (ListArchivedWorkflowExecutions)` — closed executions past the visibility retention window — required for long-range historical analysis (medium)
- [ ] `namespaces/{namespace}/worker-deployments (ListWorkerDeployments)` — deployment/version records for comparing workflow outcomes across worker versions (low)
- [ ] `namespaces/{namespace}/search-attributes (ListSearchAttributes)` — lookup describing the custom search attributes that appear on synced workflows (low)

Note: Source talks gRPC via the Temporal SDK, so the OpenAPI file is the closest machine-readable list of WorkflowService operations (192 paths, duplicated under /api/v1 and legacy roots). ENDPOINTS in temporalio.py is a fixed 2-tuple — no dynamic table discovery, and namespaces are a config parameter rather than a synced table. Workflows + histories genuinely are the bulk of the data; the gaps are the surrounding operational objects.

## TenableVulnerabilityManagement — **thin**

Today (3): `assets`, `scans`, `vulnerabilities`

Diffed against: <https://developer.tenable.com/reference/exports-assets-request-export>

- [ ] `plugins (GET /plugins/plugin)` — lookup resolving the plugin_id carried on every synced vulnerability finding to name, family, CVE, CVSS and VPR (high)
- [ ] `scan history (GET /scans/{scan_id}/history)` — each individual run of a scan with status and timing; the scans table alone has no run-level history (high)
- [ ] `compliance findings export (POST /compliance/export + status/chunks)` — audit/compliance results, the second half of Tenable's findings data alongside vulnerabilities (high)
- [ ] `tag values (GET /tags/values)` — lookup table for the asset tags used to slice every asset and vulnerability report (high)
- [ ] `tag categories (GET /tags/categories)` — parent dimension for tag values, needed to group tags into category/value pairs (medium)
- [ ] `plugin families (GET /plugins/families)` — grouping dimension for plugins, standard breakdown axis in vulnerability reporting (medium)
- [ ] `networks (GET /networks)` — lookup resolving the network_id on assets and scanners (medium)
- [ ] `scanners (GET /scanners)` — lookup resolving scanner_id on scans, plus scanner fleet health (medium)
- [ ] `agents (GET /scanners/{scanner_id}/agents)` — agent inventory and last-seen, the basis of agent scan coverage analysis (medium)
- [ ] `policies / scan templates (GET /policies)` — lookup resolving the policy_id on synced scans to a named scan template (medium)
- [ ] `recast/accept rules (POST /api/v3/findings/vulnerabilities/recast/rules/search)` — severity overrides and acceptances that explain why a finding's severity differs from the plugin default (medium)
- [ ] `activity log events (GET /audit-log/v1/events)` — org-wide audit trail of who changed scans, users and tags (low)

Note: Static endpoint catalog in settings.py (assets/vulns via the bulk export API, scans via GET /scans) — no dynamic discovery. The ReadMe page embeds the entire Tenable VM API reference index (~636 operation slugs across VM, WAS, ASM, Inventory and platform settings), so 3 tables is a very small slice. Gaps below are restricted to core VM analytics; WAS/ASM/Inventory are effectively separate products and were mostly left out.

## TerraformCloud — gaps

Today (6): `organizations`, `projects`, `runs`, `state_versions`, `teams`, `workspaces`

Diffed against: <https://developer.hashicorp.com/terraform/cloud-docs/api-docs>

- [ ] `applies (/applies/{id}, run relationship)` — resource additions/changes/destructions actually applied per run — the core outcome metric for every synced run (high)
- [ ] `plans (/plans/{id}, run relationship)` — planned resource adds/changes/destroys and plan status, needed to measure drift and change volume (high)
- [ ] `workspace-resources (/workspaces/{id}/resources)` — the managed resource inventory per workspace; without it you can count runs but not what they manage (high)
- [ ] `assessment-results (/assessment-results/{id})` — health assessment / drift detection results, HCP Terraform's headline workspace-health metric (high)
- [ ] `policy-evaluations and policy-set-outcomes (/runs/{id}/policy-evaluations)` — Sentinel/OPA pass-fail per run, the governance reporting use case (medium)
- [ ] `cost-estimates (/cost-estimates/{id})` — prior and proposed monthly cost delta per run, the FinOps use case (medium)
- [ ] `state-version-outputs (/state-versions/{id}/outputs)` — outputs of the state versions already synced, the queryable payload of a state version (medium)
- [ ] `organization-memberships (/organizations/{name}/organization-memberships)` — membership join table linking users to organizations; we sync orgs and teams but not who is in them (medium)
- [ ] `configuration-versions (/workspaces/{id}/configuration-versions)` — links a run back to its VCS commit/ingress attributes, needed to attribute changes to commits and authors (medium)
- [ ] `users (/users/{id})` — lookup resolving the user ids referenced by runs, memberships and comments (medium)
- [ ] `team-members (/teams/{id}/relationships/users)` — membership join table for the teams already synced (medium)
- [ ] `audit-trails (/organization/audit-trail)` — org activity log for change attribution and compliance reporting (low)

Note: Static catalog, no dynamic discovery. Runs are synced but every artifact hanging off a run (plan, apply, policy result, cost estimate) is missing, so run outcomes cannot be quantified.

## Testrail — gaps

Today (13): `case_types`, `cases`, `milestones`, `plans`, `priorities`, `projects`, `results`, `runs`, `sections`, `statuses`, `suites`, `tests`, `users`

Diffed against: <https://support.testrail.com/api/v2/help_center/en-us/categories/7076541806228/articles.json?per_page=100>

- [ ] `get_case_fields` — lookup that decodes the custom\_\* columns on every synced case into names, types and dropdown values (high)
- [ ] `get_result_fields` — same for the custom\_\* columns on results, the largest table in a TestRail sync (high)
- [ ] `get_templates` — lookup resolving template_id on cases; without it case rows carry an unresolvable integer (high)
- [ ] `get_configs` — configuration groups/values that resolve the config ids on plan entries and runs (browser/OS matrix reporting) (medium)
- [ ] `get_history_for_case` — per-case change history, the state-transition data for tracking test case churn (medium)
- [ ] `get_case_statuses` — lookup for case approval statuses, distinct from the test result statuses already synced (medium)
- [ ] `get_labels` — labels applied to cases and tests, a standard breakdown dimension (medium)
- [ ] `get_shared_steps` — reusable step definitions referenced by cases, plus get_shared_step_history for change tracking (medium)
- [ ] `get_roles` — lookup resolving role_id on the users already synced (medium)
- [ ] `get_groups` — user group membership, needed for per-team test ownership reporting (medium)
- [ ] `get_attachments_for_run / _for_case / _for_test` — attachment metadata (counts, sizes, who attached evidence) per run and case (low)
- [ ] `get_datasets` — parameterized-test datasets referenced by BDD and data-driven cases (low)

Note: support.testrail.com HTML is behind a Cloudflare interstitial (403 to curl); the Zendesk Help Center JSON API on the same host serves the full API-reference section (id 7077185274644) and was used instead. Coverage of the main hierarchy (projects/suites/sections/cases/runs/tests/results) is good — the gaps are almost entirely the lookup tables that decode custom fields and ids already synced.

## Thinkific — gaps

Today (9): `collections`, `courses`, `enrollments`, `groups`, `instructors`, `orders`, `products`, `promotions`, `users`

Diffed against: <https://developers.thinkific.com/openapi/thinkific-admin-api-v1.yaml>

- [ ] `GET /coupons (+ /coupons/{id})` — the actual discount codes; promotions are synced but the coupons they attach to are not, so redemption analysis is impossible (high)
- [ ] `GET /courses/{id}/chapters (+ /chapters/{id})` — curriculum structure under each synced course, the lookup needed to interpret any lesson-level progress (high)
- [ ] `GET /chapters/{id}/contents (+ /contents/{id})` — lesson-level records, the finest grain of course content and the join target for completion analysis (high)
- [ ] `GET /course_reviews (+ /course_reviews/{id})` — student ratings and review text per course, a headline course-quality metric (high)
- [ ] `GET /collections/{id}/products (+ /collection_memberships/{id})` — join table linking the synced collections to the synced products (medium)
- [ ] `GET /custom_profile_field_definitions` — lookup decoding the custom profile fields carried on user records (medium)
- [ ] `GET /bundles/{id}/courses` — bundle-to-course mapping, needed to attribute bundle revenue to individual courses (medium)
- [ ] `GET /bundles/{id}/enrollments` — enrollments scoped to a bundle, distinguishing bundle-driven from direct enrollment (medium)
- [ ] `GET /products/{id}/related` — product relationship graph used for cross-sell reporting (low)
- [ ] `GET /groups/{group_id}/analysts` — who administers each synced group, a small membership lookup (low)
- [ ] `GET /product_publish_requests` — publication request state per product, useful for content-pipeline reporting (low)

Note: Machine-readable spec found at /openapi/thinkific-admin-api-v1.yaml (linked from the RSC payload of developers.thinkific.com/api/api-documentation); cross-checked against the vendor's scopes-to-endpoints article. Note /bundles has no list endpoint — only /bundles/{id} and its sub-resources — so bundle data must be fanned out from the products already synced. This source and ThinkificCourses target the same vendor API with different table sets.

## ThinkificCourses — gaps

Today (11): `collections`, `coupons`, `course_reviews`, `courses`, `enrollments`, `groups`, `instructors`, `orders`, `products`, `promotions`, `users`

Diffed against: <https://developers.thinkific.com/openapi/thinkific-admin-api-v1.yaml>

- [ ] `GET /courses/{id}/chapters (+ /chapters/{id})` — curriculum structure under each synced course; the only path to sub-course granularity (high)
- [ ] `GET /chapters/{id}/contents (+ /contents/{id})` — lesson-level records, the join target for lesson completion and drop-off analysis (high)
- [ ] `GET /collections/{id}/products (+ /collection_memberships/{id})` — join table linking the synced collections to the synced products (medium)
- [ ] `GET /custom_profile_field_definitions` — lookup decoding the custom profile fields carried on user records (medium)
- [ ] `GET /bundles/{id}/courses` — bundle-to-course mapping, needed to attribute bundle revenue to individual courses (medium)
- [ ] `GET /bundles/{id}/enrollments` — enrollments scoped to a bundle, distinguishing bundle-driven from direct enrollment (medium)
- [ ] `GET /groups/{group_id}/analysts` — who administers each synced group, a small membership lookup (low)
- [ ] `GET /products/{id}/related` — product relationship graph used for cross-sell reporting (low)
- [ ] `GET /product_publish_requests` — publication request state per product, useful for content-pipeline reporting (low)

Note: Same vendor API as the Thinkific source; this variant already covers coupons and course_reviews, so the remaining gaps are curriculum depth and the lookup tables. Worth flagging that two PostHog sources point at one Thinkific Admin API v1 with overlapping-but-unequal table sets.

## TicketTailor — gaps

Today (10): `check_ins`, `discounts`, `event_series`, `events`, `issued_memberships`, `issued_tickets`, `membership_types`, `orders`, `products`, `vouchers`

Diffed against: <https://developers.tickettailor.com/sitemap.xml>

- [ ] `GET /v1/vouchers/{id}/codes` — the individual codes issued under each synced voucher, with redemption state — the analytical grain vouchers alone lack (high)
- [ ] `GET /v1/holds` — held/reserved seats per event, required to reconcile inventory against issued tickets (medium)
- [ ] `GET /v1/stores` — lookup resolving the store a synced product belongs to, for per-store merch revenue (medium)
- [ ] `GET /v1/event_series/{id}/waitlist` — waitlist signups, the demand signal for sold-out events (medium)
- [ ] `GET /v1/checkout_forms (+ /v1/checkout_forms/{id}/elements)` — lookup that decodes the custom checkout answers stored on orders and issued tickets (medium)
- [ ] `GET /v1/event_series/{id}/overrides` — per-occurrence overrides on a recurring series, explaining why an occurrence differs from its series (low)

Note: The docs site is a Docusaurus shell that renders the OpenAPI client-side, so the sitemap was used to enumerate operations and individual pages were fetched to confirm paths. /v1/events already covers event occurrences, and ticket types/ticket groups have create/update/delete only (no list) — they come embedded in event objects, so neither is a real gap.

## Tinyemail — gaps

Today (4): `campaigns`, `contact_members`, `contacts`, `sender_details`

Diffed against: <https://docs.tinyemail.com/sitemap.xml>

- [ ] `GET /suppression (+ GET /suppression/{id})` — suppression lists and their members — the opt-out/bounce side of deliverability, entirely absent today (high)
- [ ] `POST /campaign/domain-stats` — per-campaign delivered/opens/clicks/spam/unsubscribes broken down by recipient domain, the only campaign performance data in the API (high)
- [ ] `POST /report/audience/new-subscriber-engagement` — new-subscriber engagement stats per audience; note the 7-day max window and 10-audience cap force windowed fan-out (medium)
- [ ] `GET /audiences/{id}/clean-history` — list-hygiene history per audience, explains membership drops between syncs (low)

Note: Docusaurus site; sitemap enumerated the full operation list and individual pages were fetched to confirm paths and response shapes. PostHog's `contacts` table is GET /contacts, which returns audience lists (id/name/numberOfMembers) — the same shape as GET /audiences — so audiences are effectively already covered. The Segment API has no list-all-segments endpoint (only PUT-body summary/filter calls keyed by a segment id), so segments are not syncable as a table. tinyEmail exposes no per-recipient event stream and no server-side updated-after filter on any endpoint.

## TMDb — gaps

Today (16): `countries`, `languages`, `movie_genres`, `movie_now_playing`, `movie_popular`, `movie_top_rated`, `movie_upcoming`, `person_popular`, `trending_movies`, `trending_people`, `trending_tv`, `tv_airing_today`, `tv_genres`, `tv_on_the_air`, `tv_popular`, `tv_top_rated`

Diffed against: <https://developer.themoviedb.org/reference/movie-details>

- [ ] `GET /3/discover/movie and /3/discover/tv` — The workhorse catalog query - lets a user pull arbitrary filtered slices instead of only the four curated popularity lists (high)
- [ ] `GET /3/movie/{movie_id}/credits and /3/tv/{series_id}/aggregate_credits` — Cast and crew membership joining the movies/tv and people tables we already sync - the single most-wanted relation (high)
- [ ] `GET /3/tv/{series_id}/season/{season_number} (seasons and episodes)` — Seasons and episodes are the child objects of every synced TV row; without them tv\_\* tables cannot be analyzed at episode grain (high)
- [ ] `GET /3/watch/providers/movie, /3/watch/providers/tv, /3/watch/providers/regions` — Streaming-provider lookup tables that resolve the provider IDs returned by the per-title watch/providers endpoints (high)
- [ ] `GET /3/company/{company_id}` — Lookup table resolving the production_companies IDs already embedded in synced movie and tv rows (medium)
- [ ] `GET /3/network/{network_id}` — Lookup table resolving the network IDs on synced TV series rows (medium)
- [ ] `GET /3/certification/movie/list and /3/certification/tv/list` — Lookup tables of age/content certifications per country, needed to decode release_dates and content_ratings (medium)
- [ ] `GET /3/movie/changes, /3/tv/changes, /3/person/changes` — Change feeds that would give this connector real incremental sync instead of full refresh on every run (medium)
- [ ] `GET /3/movie/{movie_id}/release_dates and /3/tv/{series_id}/content_ratings` — Per-region release date and rating breakdown dimensions (medium)
- [ ] `GET /3/movie/{movie_id}/keywords and /3/keyword/{keyword_id}` — Keyword tagging membership plus its lookup table, the standard way to segment the catalog by theme (medium)
- [ ] `GET /3/configuration/jobs` — Lookup table of departments and job titles that credits rows reference by string (low)
- [ ] `GET /3/movie/{movie_id}/reviews and /3/tv/{series_id}/reviews` — User review text and ratings per title (low)

Note: The full v3 path list (~110 operations) was extracted from the OpenAPI document embedded in the ReadMe reference page HTML; developer.themoviedb.org/sitemap.xml is only a partial index and the /openapi/<id> endpoint 404s. The connector's own products/warehouse_sources/backend/temporal/data_imports/sources/tmdb/api_inventory.md confirms it deliberately ships only the no-ID-required list endpoints; every gap below except discover/certifications/watch-providers/configuration requires fanning out over IDs from the tables already synced.

## Todoist — gaps

Today (5): `collaborators`, `labels`, `projects`, `sections`, `tasks`

Diffed against: <https://developer.todoist.com/openapi.json>

- [ ] `GET /api/v1/tasks/completed/by_completion_date` — completed tasks with completion timestamps; /tasks returns active tasks only, so throughput and completion trends are unanswerable without it (high)
- [ ] `GET /api/v1/activities` — the activity/event log (added, completed, updated, deleted per object) — the state-transition history for every synced object (high)
- [ ] `GET /api/v1/comments` — comments on tasks and projects, the collaboration content attached to the tasks already synced (medium)
- [ ] `GET /api/v1/tasks/completed/by_due_date` — completions bucketed by due date, the on-time vs late view that completion-date data cannot produce alone (medium)
- [ ] `GET /api/v1/projects/archived` — archived projects, without which tasks and activity referencing them resolve to nothing (medium)
- [ ] `GET /api/v1/workspaces/users` — workspace membership join table; collaborators are per-project only, so there is no org-level user roster (medium)
- [ ] `GET /api/v1/workspaces` — lookup resolving the workspace_id carried on projects, folders and activity (medium)
- [ ] `GET /api/v1/tasks/completed/stats` — Todoist's productivity stats (karma, streaks, daily/weekly goals) — the vendor's headline user metric (medium)
- [ ] `GET /api/v1/folders` — lookup resolving the folder that groups workspace projects (low)
- [ ] `GET /api/v1/labels/shared` — shared workspace labels, which do not appear in the personal /labels list (low)
- [ ] `GET /api/v1/reminders` — reminders attached to tasks, useful for deadline-behavior analysis (low)

Note: Full OpenAPI 3.1 spec at https://developer.todoist.com/openapi.json (note: /api/v1/openapi.json 404s). Static catalog, no dynamic discovery. The critical gap is that only active tasks are synced — completed tasks live on separate endpoints, so completion-over-time, the primary Todoist analytics question, cannot be answered today.

## TogetherAI — gaps

Today (6): `batches`, `endpoints`, `evaluations`, `files`, `fine_tunes`, `models`

Diffed against: <https://docs.together.ai/llms.txt>

- [ ] `fine-tunes/{id}/events` — per-job state/transition history for fine-tune runs, the only way to chart training progress and failure points (high)
- [ ] `fine-tunes/{id}/checkpoints` — checkpoint list resolves which artifact a deployed model came from (medium)
- [ ] `deployments (list)` — dedicated-inference deployments under each endpoint; the compute rows behind endpoint spend (medium)
- [ ] `clusters (list)` — GPU cluster inventory, the main non-inference cost driver (medium)
- [ ] `instance-types (list)` — lookup table resolving GPU/instance ids and prices carried on deployments and clusters (medium)
- [ ] `endpoints/{id}/events` — endpoint provisioning, scaling and readiness event feed (low)
- [ ] `code-interpreter sessions (list)` — session inventory for TCI usage analysis (low)

Note: No public OpenAPI JSON is served (docs.together.ai/openapi.json 404s); llms.txt is the vendor's complete machine-readable index of every reference page and was used as the endpoint list. Chat/completions/images/videos endpoints are inference calls, not queryable collections, so they are correctly absent.

## Torii — gaps

Today (4): `Apps`, `Contracts`, `Transactions`, `Users`

Diffed against: <https://developers.toriihq.com/sitemap.xml>

- [ ] `apps/{idApp}/users` — app-to-user membership/license assignment rows; the join table that makes Apps and Users analytically useful (high)
- [ ] `roles` — lookup table resolving the role ids carried on users and app owners (high)
- [ ] `apps/metadata, users/metadata, contracts/metadata, transactions/metadata` — custom-field definitions that resolve the field ids present on rows we already sync (medium)
- [ ] `workflows` — automation definitions referenced by execution logs and access requests (medium)
- [ ] `workflows/actionExecutions` — action execution log, the event stream for offboarding/provisioning automation (medium)
- [ ] `audit` — admin audit log of changes to apps, contracts and users (medium)
- [ ] `users/{idUser}/apps` — per-user app portfolio; complements the app-users join for user-centric queries (low)
- [ ] `workflows/audit` — workflow change history (low)

Note: Docs are a JS-rendered ReadMe site with no downloadable OAS, so the endpoint list came from the docs sitemap; individual reference pages were fetched to confirm titles (e.g. getappsidappusers = 'List application users', getroles = 'List roles'). SCIM v2 endpoints and app-catalog access-request policies were excluded as plumbing/config.

## TravisCI — gaps

Today (4): `branches`, `builds`, `jobs`, `repositories`

Diffed against: <https://developer.travis-ci.com/>

- [ ] `repo/{id}/requests` — build requests, including ones that never produced a build and why they were rejected (high)
- [ ] `build/{id}/stages` — stage rows that group jobs within a build; lookup for the stage a job belongs to (high)
- [ ] `owner/{login}/executions (+ executions_per_repo, executions_per_sender)` — build-minute consumption with per-repo and per-sender breakdown dimensions (high)
- [ ] `repo/{id}/crons` — scheduled build definitions that explain recurring build volume (medium)
- [ ] `orgs / users` — owner lookup tables resolving the owner ids on repositories and builds (medium)
- [ ] `scan_results` — security scan findings against build logs (medium)
- [ ] `repo/{id}/caches` — cache inventory and size per repo/branch (low)
- [ ] `build/{id}/messages` — build config validation warnings per build (low)
- [ ] `job/{id}/log` — job log text for failure-pattern analysis (low)
- [ ] `owner/{login}/allowance` — remaining credit/concurrency allowance snapshot (low)

Note: Travis serves no OpenAPI spec; the resource index on developer.travis-ci.com is the authoritative list and individual resource pages were fetched to confirm paths. Config resources (env_vars, settings, preferences, key_pair, beta_features, broadcasts, lint, custom_images) were excluded.

## Trello — gaps

Today (8): `actions`, `boards`, `cards`, `checklists`, `labels`, `lists`, `members`, `organizations`

Diffed against: <https://developer.atlassian.com/cloud/trello/swagger.v3.json>

- [ ] `boards/{id}/customFields + customFields/{id}/options` — custom field definitions and their option values; the lookup that decodes custom field ids on cards (high)
- [ ] `cards/{id}/customFieldItems` — per-card custom field values, where most teams store story points, priority and sprint (high)
- [ ] `checklists/{id}/checkItems` — the actual checklist items and their state; checklists alone are empty containers (high)
- [ ] `boards/{id}/memberships` — board membership rows with member role and status, resolving members to boards (high)
- [ ] `organizations/{id}/memberships` — workspace membership and role per member (medium)
- [ ] `cards/{id}/attachments` — attachment metadata linking cards to external artifacts (PRs, docs) (medium)
- [ ] `enterprises/{id}/members` — enterprise-wide member roster with license status (medium)
- [ ] `enterprises/{id}/auditlog` — enterprise admin audit trail (medium)
- [ ] `members/{id}/notifications` — per-member notification feed for engagement analysis (low)
- [ ] `organizations/{id}/tags` — collections/tags lookup grouping boards within a workspace (low)
- [ ] `actions/{idAction}/reactions` — emoji reactions on comment actions (low)

Note: Full Trello OpenAPI 3 spec fetched (128 GET paths). The source fans out board-scoped endpoints from /members/me/boards (see products/warehouse_sources/backend/temporal/data_imports/sources/trello/api_inventory.md), so the missing sub-resources would follow the same board/card fan-out pattern already implemented.

## Tremendous — gaps

Today (7): `campaigns`, `funding_sources`, `invoices`, `members`, `orders`, `products`, `rewards`

Diffed against: <https://raw.githubusercontent.com/tremendous-rewards/tremendous-python/HEAD/tremendous/api/tremendous_api.py>

- [ ] `balance_transactions` — the account ledger; every debit/credit behind orders and funding sources (high)
- [ ] `roles` — lookup table resolving the role ids on members (high)
- [ ] `topups` — funding top-up transactions that explain balance movements (medium)
- [ ] `fields` — custom field definitions that decode the custom_fields carried on orders and rewards (medium)
- [ ] `organizations` — org roster for multi-org accounts; resolves the organization id on orders, members and invoices (medium)
- [ ] `connected_organizations` — platform-partner child orgs, needed to attribute spend for resellers (medium)
- [ ] `connected_organization_members` — member roster per connected org (low)
- [ ] `fraud_reviews` — orders held for fraud review and their disposition (low)
- [ ] `reports` — generated report inventory (low)
- [ ] `forex` — exchange rates used to convert multi-currency reward amounts (low)

Note: developers.tremendous.com is a JS-rendered ReadMe site and the documented reference slugs now 404; the endpoint list was taken from Tremendous's own generated Python SDK (tremendous-rewards/tremendous-python), which enumerates every API path. Webhooks and organizations/create_api_key were excluded as plumbing.

## TriggerDev — gaps

Today (3): `queues`, `runs`, `schedules`

Diffed against: <https://trigger.dev/docs/llms.txt>

- [ ] `errors (list error groups)` — failed runs grouped by fingerprint with lifecycle state; the headline reliability metric (high)
- [ ] `deployments (list)` — deploy history and worker versions, the dimension that explains run behavior changes (high)
- [ ] `runs/{id}/events` — OTel span events per run; the step-level detail behind a run's duration and failure (medium)
- [ ] `waitpoints/tokens (list)` — waitpoint tokens and their completion state, showing where runs block on external systems (medium)
- [ ] `sessions (list)` — durable session records tying multiple runs to one external identity (medium)
- [ ] `bulk-actions (list)` — bulk cancel/replay operations and their processing counts (low)

Note: Trigger.dev also ships a TRQL query endpoint (management/query/execute) that exposes run data as a SQL-like surface; its schema endpoint (management/query/schema) lists every queryable table and would be the cheapest way to widen coverage. Env vars and queue concurrency controls were excluded as config.

## TrunkIo — adequate

Today (3): `FailingTests`, `QuarantinedTests`, `UnhealthyTests`

Diffed against: <https://docs.trunk.io/flaky-tests/reference/api-reference.md>

No material gaps found.

Note: The Flaky Tests REST API has exactly five endpoints: three list endpoints (distinct failed tests in a time range, unhealthy tests, quarantined tests) - all three already exposed as FailingTests, UnhealthyTests and QuarantinedTests - plus a single test-case detail lookup and a write op (link a ticket). Trunk's other API is the Merge Queue API (docs.trunk.io/merge-queue/reference/merge), a POST-based control plane (submit/cancel/restart PR, getQueue, getSubmittedPullRequest, Prometheus metrics) that requires per-branch parameters rather than exposing listable collections, so it is not a warehouse gap for this source.

## TVMaze — gaps

Today (4): `people`, `person_updates`, `show_updates`, `shows`

Diffed against: <https://www.tvmaze.com/api>

- [ ] `GET /shows/{id}/episodes` — Episodes are the primary child object of every synced show and the grain most analysis needs (high)
- [ ] `GET /shows/{id}/cast` — Cast membership joining the shows and people tables we already sync, including character records (high)
- [ ] `GET /shows/{id}/seasons` — Lookup table resolving the season IDs that episodes reference (high)
- [ ] `GET /shows/{id}/crew` — Crew membership with role type, the production-side counterpart of cast (medium)
- [ ] `GET /people/{id}/castcredits and /people/{id}/crewcredits` — Person-to-show credit history, the reverse of the cast/crew join and the natural entry point when starting from people (medium)
- [ ] `GET /schedule, /schedule/web, /schedule/full` — Airing schedule by date and country - the time-series view of what is broadcasting (medium)
- [ ] `GET /seasons/{id}/episodes` — Episode listing keyed by season, cheaper than per-show fan-out when seasons are already synced (medium)
- [ ] `GET /episodes/{id}/guestcast and /episodes/{id}/guestcrew` — Per-episode guest appearance membership not covered by show-level cast (low)
- [ ] `GET /shows/{id}/akas` — Alternative show titles per country, a lookup for cross-region matching (low)
- [ ] `GET /shows/{id}/images` — Artwork records with type and resolution metadata (low)
- [ ] `GET /shows/{id}/alternatelists and /alternatelists/{id}/alternateepisodes` — Alternate episode orderings (DVD, streaming) for shows whose broadcast order differs (low)

Note: Static 4-endpoint config in sources/tvmaze/settings.py, no dynamic discovery. TVMaze only publishes bulk index endpoints for /shows and /people (both covered) plus the two /updates feeds (covered), so the connector covers every index endpoint. Everything below is per-ID and would need a fan-out over the already-synced shows/people tables - which is exactly what makes the dataset useful, since shows without episodes or cast is close to unqueryable.

## TwelveData — **thin**

Today (11): `cryptocurrencies`, `dividends`, `earnings`, `etfs`, `exchanges`, `forex_pairs`, `indices`, `quotes`, `splits`, `stocks`, `time_series`

Diffed against: <https://twelvedata.com/docs>

- [ ] `income_statement (and income_statement/consolidated)` — core fundamentals; revenue and margin history per symbol (high)
- [ ] `balance_sheet (and balance_sheet/consolidated)` — assets, liabilities and equity history per symbol (high)
- [ ] `cash_flow (and cash_flow/consolidated)` — operating, investing and financing cash flow history (high)
- [ ] `statistics` — valuation and financial ratio snapshot; the most-queried fundamentals object (high)
- [ ] `profile` — company metadata lookup (sector, industry, country) that resolves the symbols already synced in stocks (high)
- [ ] `market_cap` — market capitalization time series, a standard breakdown dimension (medium)
- [ ] `earnings_calendar, dividends_calendar, splits_calendar, ipo_calendar` — forward-looking market-wide event feeds; the existing earnings/dividends/splits tables are per-symbol history only (medium)
- [ ] `institutional_holders, fund_holders, direct_holders` — ownership breakdown per symbol (medium)
- [ ] `insider_transactions` — insider buy/sell transaction rows, a classic analytical dataset (medium)
- [ ] `recommendations, price_target, analyst_ratings` — sell-side estimates and rating changes per symbol (medium)
- [ ] `funds (mutual funds list), bonds, commodities` — asset catalogs missing alongside the stocks/etfs/forex/crypto catalogs already synced (medium)
- [ ] `countries, instrument_type, exchange_schedule, market_state` — reference lookups resolving country, instrument type and trading-session fields on symbols and exchanges (low)

Note: No OpenAPI spec is published; the full endpoint inventory was read from the section anchors of twelvedata.com/docs. The API has roughly 150 endpoints, ~100 of which are technical indicators (computed on demand, not warehouse tables, correctly excluded). Coverage is concentrated in market data and catalogs; the entire Fundamentals, Analysis and Regulatory sections are absent, which is why this reads thin rather than merely gappy.

## TwelveLabs — gaps

Today (3): `indexes`, `tasks`, `videos`

Diffed against: <https://docs.twelvelabs.io/openapi.json>

- [ ] `assets (GET /assets)` — the current top-level media object; videos are only reachable per-index, so assets is the only account-wide inventory (high)
- [ ] `indexed-assets (GET /indexes/{index-id}/indexed-assets)` — join table linking assets to indexes and carrying per-index indexing status (high)
- [ ] `analyze tasks (GET /analyze/tasks)` — history of async analysis jobs with status/duration — the usage and cost signal (high)
- [ ] `analyze batches + results (GET /analyze/batches, /analyze/batches/{batch_id}/results)` — batch job records and their per-item outputs (medium)
- [ ] `embed tasks (GET /embed/tasks and /embed-v2/tasks)` — embedding job history, parallel to the indexing tasks already synced (medium)
- [ ] `entity-collections and their entities (GET /entity-collections, /entity-collections/{id}/entities)` — lookup tables that resolve entity ids appearing on assets (medium)
- [ ] `asset entities (GET /assets/{asset_id}/entities)` — asset-to-entity mapping for face/object analytics (medium)
- [ ] `knowledge-stores, item-collections, items (GET /knowledge-stores, .../item-collections, .../items)` — the retrieval corpus objects; items resolve ids used by search (medium)
- [ ] `connection imports (GET /connections/{connection_id}/imports)` — per-import job records for bulk ingestion runs (low)

Note: Fetched the live OpenAPI (server https://api.twelvelabs.io/v1.3 — same version the PostHog source targets). The API has grown well past indexes/tasks/videos: assets, analysis tasks/batches, embeddings, entity collections and knowledge stores are all listable.

## Twilio — gaps

Today (11): `addresses`, `applications`, `calls`, `conferences`, `incoming_phone_numbers`, `keys`, `messages`, `outgoing_caller_ids`, `queues`, `recordings`, `transcriptions`

Diffed against: <https://raw.githubusercontent.com/twilio/twilio-oai/main/spec/json/twilio_api_v2010.json>

- [ ] `Usage/Records (+ Daily/Monthly/Yearly variants)` — per-category usage and spend — the headline metric for anyone modeling Twilio cost (high)
- [ ] `Conferences/{ConferenceSid}/Participants` — per-participant rows are the only way to analyze conference attendance and talk time; conferences alone give no membership (high)
- [ ] `Accounts (subaccount list)` — lookup table resolving the AccountSid carried on every message, call and recording already synced (high)
- [ ] `Calls/{CallSid}/Events` — per-call state/transition history for debugging and funnel analysis of call flow (medium)
- [ ] `Notifications` — account-wide error and warning log, keyed to calls/messages — the standard delivery-failure diagnostic table (medium)
- [ ] `Messages/{MessageSid}/Media` — MMS media items per message; needed for attachment volume and storage analysis (medium)
- [ ] `Queues/{QueueSid}/Members` — queued-call membership with wait position/time, the analytical grain behind the queues table already synced (medium)
- [ ] `SMS/ShortCodes` — lookup resolving short-code senders on messages, complementing incoming_phone_numbers (medium)
- [ ] `Balance` — current account balance, joins with usage records for prepaid burn-down (low)
- [ ] `Recordings/{ReferenceSid}/AddOnResults (+ Payloads)` — add-on analysis output attached to recordings already synced (low)
- [ ] `Addresses/{AddressSid}/DependentPhoneNumbers` — address-to-number mapping for regulatory/compliance reporting (low)

Note: Diffed against the official twilio-oai api/2010-04-01 spec (121 paths). The source is a static endpoint map (products/warehouse_sources/backend/temporal/data_imports/sources/twilio/settings.py) hitting /2010-04-01/Accounts/{sid}/<Resource>.json, so sub-resources need explicit fan-out. Only the classic api_v2010 domain was checked; Twilio's other domains (Messaging, Conversations, Verify, TaskRouter, Voice Insights) are separate specs and out of scope for this diff.

## TyntecSMS — adequate

Today (4): `Contacts`, `MessageStatus`, `PhoneNumbers`, `PhoneRegistrations`

Diffed against: <https://raw.githubusercontent.com/tyntec/api-collection/master/sms/v1/openapi.yaml>

No material gaps found.

Note: The rendered reference at api.tyntec.com/reference/sms/current.html points at the tyntec/api-collection GitHub spec; the SMS v1 API has only five path groups (/messaging/v1/sms + message status, /incoming, /byon/phonebook/v1/numbers, /byon/contacts/v1, /byon/provisioning/v1) and PostHog's four tables cover every readable one. The sibling APIs in that repo (account, verify, voice, conversations) are separate products, and account only exposes ip-restriction and keys, which are config.

## Ubidots — gaps

Today (6): `device_groups`, `device_types`, `devices`, `events`, `values`, `variables`

Diffed against: <https://docs.ubidots.com/sitemap.xml>

- [ ] `event logs (Get all event logs / log object)` — the firing history of events/alerts — without it the synced events table is only rule config, with no occurrences to analyze (high)
- [ ] `organizations (Get all organizations)` — lookup table resolving the organization that owns devices and users already synced; also the multi-tenant grouping key (high)
- [ ] `users (Get all users)` — end users of the Ubidots app, needed to attribute devices and organization membership (medium)
- [ ] `devices of an organization (Get all devices of organization)` — device-to-organization membership join, since devices do not carry an org list (medium)
- [ ] `roles (Get all roles)` — lookup resolving the role ids on users (low)

Note: docs.ubidots.com is a ReadMe site that renders endpoints client-side, so I diffed the sitemap's /reference/\* page list (each 'Get all X' page = a list endpoint) rather than the JS-rendered bodies. Verified individual pages return 200 with GET (e.g. https://docs.ubidots.com/reference/get-event-logs, title 'Get Event Logs').

## Unleash — gaps

Today (11): `addons`, `context_fields`, `environments`, `feature_types`, `features`, `projects`, `segments`, `strategies`, `tag_types`, `tags`, `users`

Diffed against: <https://app.unleash-hosted.com/demo/docs/openapi.json>

- [ ] `events (GET /api/admin/events, /api/admin/events/{featureName}, POST /api/admin/search/events)` — the full change/audit history — who toggled which flag when; the core analytical table of a flag system (high)
- [ ] `client metrics (GET /api/admin/client-metrics/features/{name} and /raw)` — per-flag evaluation counts (yes/no) by environment — Unleash's headline usage metric, entirely absent today (high)
- [ ] `feature strategies per environment (GET /api/admin/projects/{projectId}/features/{featureName}/environments/{environment}/strategies)` — resolves which strategy and rollout is live in which environment; the synced features and strategies tables cannot be joined without it (high)
- [ ] `project features (GET /api/admin/projects/{projectId}/features)` — authoritative project-to-feature membership, including archived and stale state the flat features list omits (high)
- [ ] `applications and instances (GET /api/admin/metrics/applications, /{appName}/overview, /instances/{appName}/environment/{environment})` — registered SDK apps and connected instances — which services actually consume which flags (medium)
- [ ] `feature lifecycle (GET /api/admin/projects/{projectId}/features/{featureName}/lifecycle, /api/admin/lifecycle/count, /api/admin/insights/lifecycle)` — stage transition history powering flag-debt and cleanup reporting (medium)
- [ ] `feature tags (GET /api/admin/features/{featureName}/tags)` — feature-to-tag join table; tags and tag_types are synced but nothing links them to flags (medium)
- [ ] `project access (GET /api/admin/projects/{projectId}/access)` — user/group-to-project role memberships, the permission dimension for the synced users table (medium)
- [ ] `project insights / health report / status (GET /api/admin/projects/{projectId}/insights, /health-report, /status)` — precomputed health and flag-debt breakdowns per project (medium)
- [ ] `traffic and request metrics (GET /api/admin/metrics/traffic, /request, /connection)` — request volume per period, used for consumption and billing analysis (medium)
- [ ] `segment strategy links (GET /api/admin/segments/{id}/strategies, /api/admin/segments/strategies/{strategyId})` — join table between the synced segments and strategies (low)
- [ ] `project DORA metrics (GET /api/admin/projects/{projectId}/dora)` — lead time per flag, a ready-made delivery metric (low)

Note: Diffed against a live Unleash instance's generated OpenAPI (Unleash API 8.0.3, 100 GET operations). The docs site has no static spec; docs.getunleash.io/generated/openapi.json is a 2.8 KB stub. This is the OSS spec — an Enterprise instance additionally exposes groups, change requests and service accounts, which were not checked. Current coverage is all configuration objects; every usage/telemetry surface is missing.

## Unstructured — gaps

Today (4): `destinations`, `jobs`, `sources`, `workflows`

Diffed against: <https://docs.unstructured.io/llms.txt>

- [ ] `job failed files (GET /jobs/{id}/failed-files)` — per-file failure reasons — the only place processing errors are enumerated; jobs alone give just a status (high)
- [ ] `job details (GET /jobs/{id}/details)` — per-node processing counts and timings inside a job, the grain needed for throughput and cost analysis (high)
- [ ] `notifications (GET /notifications)` — workspace event stream (job started/failed/completed) with timestamps, an analytical log the jobs table does not reproduce (medium)
- [ ] `templates (GET /templates)` — lookup resolving the template a workflow was created from, plus its DAG metadata (medium)
- [ ] `source/destination connection checks (GET /sources/{id}/connection-check, /destinations/{id}/connection-check)` — connector health history to correlate with failed jobs (low)

Note: docs.unstructured.io serves no OpenAPI JSON (api.unstructuredapp.io/openapi.json 404s); the llms.txt index enumerates every api-reference operation and was used for the diff. The four synced tables cover the main workflow objects, so remaining gaps are the per-job detail and notification event surfaces.

## UpPromote — gaps

Today (6): `affiliates`, `coupons`, `payments_paid`, `payments_unpaid`, `programs`, `referrals`

Diffed against: <https://aff-api.uppromote.com/docs/v2/llms.txt>

- [ ] `connected customers (GET connected customer list)` — the customer-to-affiliate mapping — the lookup that lets referrals and payments be attributed back to individual customers (high)
- [ ] `program excluded products/collections` — per-program commission exclusions, needed to explain why some orders generate no referral (low)

Note: The v2 public API is small; the llms.txt index lists every operation. Coverage is otherwise complete — the only unsynced read endpoints are the connected-customer list, a program config sub-resource, an aggregate count, and webhook subscriptions (config).

## Upstash — gaps

Today (5): `audit_logs`, `redis_databases`, `redis_stats`, `teams`, `vector_indexes`

Diffed against: <https://upstash.com/docs/llms.txt>

- [ ] `GET /v2/teams/{team_id} (Get Team Members)` — membership rows resolving which users belong to each team we already sync (high)
- [ ] `GET /v2/vector/index/stats (Get Vector Stats)` — per-index query/usage metrics — the vector equivalent of redis_stats, which we do sync (high)
- [ ] `GET /v2/search (List Search Indexes)` — Upstash Search is a first-class product with no table at all today (medium)
- [ ] `GET /v2/qstash (List QStash Users)` — QStash is the third product line and is entirely unrepresented (medium)
- [ ] `GET /v2/qstash/stats/{id} (Get QStash Stats)` — daily request/bandwidth/billing time series for QStash usage analysis (medium)
- [ ] `GET /v2/redis/list-backup/{id} (List Backup)` — backup inventory per Redis database for retention/compliance reporting (low)

Note: Diffed against the Developer API inventory in the docs llms.txt; individual endpoint paths confirmed by fetching the per-endpoint .md pages (each embeds the OpenAPI operation, e.g. `get /teams/{team\_id}`, `get /vector/index/stats`, `get /search`, `get /qstash/stats/{id}`). Source already fans out redis_stats per database, so the same fan-out shape would work for vector/search stats.

## Uptimerobot — gaps

Today (6): `alert_contacts`, `maintenance_windows`, `monitor_logs`, `monitors`, `response_times`, `status_pages`

Diffed against: <https://cdn.uptimerobot.com/api/openapi.yaml>

- [ ] `GET /incidents` — the downtime incident record — the headline analytical object for uptime reporting (high)
- [ ] `GET /monitors/uptime-stats and GET /monitors/{id}/stats/uptime` — uptime percentage / SLA metric, the vendor's headline number (high)
- [ ] `GET /monitor-groups` — lookup resolving the groupId carried on monitors we already sync (high)
- [ ] `GET /tags` — lookup resolving tag ids on monitors; the main breakdown dimension (high)
- [ ] `GET /incidents/{id}/alerts` — which alert contacts were notified and when, per incident (medium)
- [ ] `GET /incidents/{id}/activity-log` — state-transition history of an incident (acknowledge, resolve, escalate) (medium)
- [ ] `GET /incidents/{id}/comments` — human annotations on incidents, useful for postmortem analysis (low)
- [ ] `GET /psps/{pspId}/announcements` — published status-page announcements tied to status_pages we already sync (low)

Note: The source is pinned to the legacy v2 API (UPTIMEROBOT_BASE_URL = https://api.uptimerobot.com/v2), and it covers essentially all of v2 (getMonitors, getAlertContacts, getMWindows, getPSPs, plus logs/response-times unpacked from getMonitors). All gaps above come from the current v3 REST API, whose OpenAPI spec is served at cdn.uptimerobot.com/api/openapi.yaml; capturing them means moving to v3 (or dual-pathing), not just adding endpoints. Excluded /integrations, /alert-contacts config CRUD and /user/me as plumbing/account settings.

## USCensus — **thin**

Today (6): `AcsDemographicsByCounty`, `AcsDemographicsByState`, `CountyBusinessPatternsByState`, `DecennialPopulationByCounty`, `DecennialPopulationByState`, `PopulationEstimatesByState`

Diffed against: <https://api.census.gov/data.json>

- [ ] `2024/acs/acs5 for=zip code tabulation area` — ZCTA-level demographics is the join key for customer postal codes — the single most requested Census cut (high)
- [ ] `2024/geoinfo` — geography lookup table (names, land/water area, centroid) that resolves the bare state/county FIPS codes every other table returns (high)
- [ ] `2023/cbp for=county` — county business patterns is only synced at state grain today; county is the useful market-sizing grain (high)
- [ ] `2021/pep/population for=county` — population estimates are state-only today, so county-level denominators are missing (high)
- [ ] `2024/acs/acs5 for=tract and for=place` — tract/place demographics for catchment and store-level analysis (medium)
- [ ] `2018/zbp (ZIP Code Business Patterns)` — establishment and payroll counts by ZIP, the business-side complement to ZCTA demographics (medium)
- [ ] `2024/acs/acs1` — 1-year estimates are a year fresher than acs5 for states and large metros (medium)
- [ ] `2024/acs/acs5/profile and /subject` — the DP/S profile tables give ready-made percentages instead of raw B-table counts (medium)
- [ ] `2020/dec/dhc` — full demographic and housing characteristics; the synced dec/pl file carries only total population and housing units (medium)
- [ ] `2024/acs/acs5 for=metropolitan statistical area/micropolitan statistical area` — MSA is the standard market grain for go-to-market analysis (medium)
- [ ] `timeseries/eits (e.g. mrts retail sales, bfs business formation)` — monthly economic indicator time series for macro overlays on revenue trends (low)
- [ ] `2023/nonemp (Nonemployer Statistics)` — sole-proprietor business counts, complements CBP for SMB market sizing (low)

Note: The Census discovery document lists 1790 datasets; the source ships 6 hand-curated queries (products/warehouse_sources/backend/temporal/data_imports/sources/us_census/settings.py) pinned to 2024/acs/acs5, 2020/dec/pl, 2023/cbp and 2021/pep/population. It does have a CustomQuery escape hatch (any dataset/variables/geography from the source config), so nothing is truly unreachable — but it only appears as a table when the user fills in the custom fields, so the canned coverage is what most users get. Gaps below are extra canned endpoints, all verified present in data.json (and the geography levels verified via https://api.census.gov/data/2024/acs/acs5/geography.json).

## Usersnap — adequate

Today (3): `feedbacks`, `project_assignees`, `projects`

Diffed against: <https://api.swaggerhub.com/apis/usersnap6/usersnap-api/0.1>

No material gaps found.

Note: The whole public Usersnap REST API is 8 operations. GET collections are: /projects, /projects/{api_key}/assignees, /projects/{project_id}/feedbacks — all three are synced. The rest are POST submit/filter variants and /feedbacks/count. The single unexposed GET is /projects/{api_key}/metrics, which returns the project's feedback field definitions ({name, help_text, metric_type}); it is a small lookup that would let you decode which fields a feedback row carries, but it is metadata rather than an analytical table, so coverage is proportionate. Spec URL discovered from the swaggerhub link on help.usersnap.com/reference/rest-api.

## Uservoice — gaps

Today (10): `comments`, `forums`, `labels`, `notes`, `nps_ratings`, `suggestion_statuses`, `suggestions`, `ticket_messages`, `tickets`, `users`

Diffed against: <https://uservoice.uservoice.com/api/v2/public/doc/api-v2-reference>

- [ ] `GET /admin/supporters` — the supporter/vote membership linking users to the suggestions we already sync (high)
- [ ] `GET /admin/features` — roadmap features that suggestions roll up to; resolves the feature_ids on suggestions (high)
- [ ] `GET /admin/categories` — lookup resolving the category id carried on every suggestion (high)
- [ ] `GET /admin/status_updates` — state-transition history of suggestions (status changes and their messages) (high)
- [ ] `GET /admin/external_accounts` — the CRM account (and its revenue/MRR fields) that feedback is attributed to (high)
- [ ] `GET /admin/external_users` — lookup joining UserVoice users to CRM contacts/accounts (high)
- [ ] `GET /admin/feedback_records` — raw captured feedback items that suggestions and impact scores are derived from (high)
- [ ] `GET /admin/segments and GET /admin/segmented_values` — the segment dimensions UserVoice reporting breaks feedback down by (medium)
- [ ] `GET /admin/importance_scores and GET /admin/importance_responses` — prioritization scoring per suggestion — the core PM ranking metric (medium)
- [ ] `GET /admin/internal_statuses and GET /admin/internal_status_updates` — internal (non-public) status plus its change history, a lookup for suggestion pipelines (medium)
- [ ] `GET /admin/product_areas` — lookup resolving product area ids on suggestions and feedback (medium)
- [ ] `GET /admin/teams` — lookup resolving owning team on suggestions/features (medium)

Note: Full Swagger 2.0 spec recovered from the ReDoc spec-url on developer.uservoice.com (the rendered page is JS-only and unusable via curl/WebFetch). The admin API exposes ~45 GET-able collections; we sync 10. Also missing but below the cut: /admin/feature_statuses, /admin/suggestion_activity_entries, /admin/supporter_messages, /admin/custom_fields, /admin/impact_reports, /admin/feedback_atoms, /admin/attachments. Note the source's `tickets` and `ticket\_messages` tables are not in this v2 admin spec, so they come from a separate/undocumented surface.

## Vantage — gaps

Today (20): `access_grants`, `anomaly_alerts`, `billing_rules`, `budgets`, `cost_alerts`, `cost_reports`, `dashboards`, `financial_commitment_reports`, `folders`, `integrations`, `kubernetes_efficiency_reports`, `network_flow_reports`, `recommendations`, `report_notifications`, `resource_reports`, `saved_filters`, `segments`, `teams`, `users`, `workspaces`

Diffed against: <https://api.vantage.sh/v2/swagger.json>

- [ ] `GET /costs` — the actual cost rows for a cost report — we sync report definitions but none of the cost data (high)
- [ ] `GET /resources` — the resource inventory returned by a resource report; today only the report definition is synced (high)
- [ ] `GET /financial_commitments` — actual RI/savings-plan commitments; we sync only financial_commitment_reports definitions (high)
- [ ] `GET /tags and GET /tags/{key}/values` — lookup for the cost-allocation tag keys/values every cost breakdown groups by (high)
- [ ] `GET /cost_providers, GET /cost_provider_accounts, GET /cost_services` — lookup tables resolving the provider, account and service ids that appear in cost data (high)
- [ ] `GET /unit_costs` — unit economics per cost report (cost per business unit), a headline FinOps metric (medium)
- [ ] `GET /business_metrics and GET /business_metrics/{token}/values` — the metric series that unit costs divide by; needed to reproduce unit-cost math (medium)
- [ ] `GET /network_flow_logs` — the aggregated flow data behind network_flow_reports, which we sync definitions of only (medium)
- [ ] `GET /cost_alerts/{cost_alert_token}/events` — firing history for the cost alerts we already sync — the state-transition table (medium)
- [ ] `GET /cost_reports/{cost_report_token}/forecasted_costs` — forecast series per report, used for budget-vs-forecast analysis (medium)
- [ ] `GET /recommendations/{recommendation_token}/resources` — the specific resources each savings recommendation targets (medium)
- [ ] `GET /virtual_tag_configs` — lookup defining the virtual tags used to group costs in reports (medium)

Note: Spec is Vantage's own OpenAPI at api.vantage.sh/v2/swagger.json (v2.0.0); vantage.readme.io/openapi.json redirects. The pattern across this source is that report \*definitions\* are synced (cost_reports, resource_reports, network_flow_reports, financial_commitment_reports) but none of the data those reports return. Below the cut: /audit_logs, /invoices (MSP only), /teams/{token}/members, /products and /products/{id}/prices, /billing_profiles, /managed_accounts, /canvases. Excluded /anomaly_notifications, /budget_alerts, /recommendation_views, /me and /ping as config/plumbing.

## Vapi — gaps

Today (9): `assistants`, `calls`, `campaigns`, `chats`, `files`, `phone_numbers`, `sessions`, `squads`, `tools`

Diffed against: <https://api.vapi.ai/api-json>

- [ ] `GET /observability/scorecard` — call quality scorecards — the analytical object for judging agent performance (high)
- [ ] `GET /eval/run` — evaluation run results per assistant; the regression signal for voice agents (high)
- [ ] `GET /eval` — eval definitions, the lookup that resolves eval ids on runs (medium)
- [ ] `GET /call/{id}/call-logs` — per-call turn/system log lines for the calls we already sync (medium)
- [ ] `POST /analytics` — Vapi's aggregate analytics query API (minutes, spend, call outcomes) — the headline metrics surface (medium)
- [ ] `GET /structured-output` — lookup for the extraction schemas whose extracted values appear on call records (low)

Note: Full OpenAPI fetched live from api.vapi.ai/api-json. Note /reporting/insight is a saved-query definition (its data only comes back via POST /reporting/insight/{id}/run), and /provider/{provider}/{resourceName} is a passthrough to Twilio/Vonage account resources — both excluded as plumbing. /v2/campaign is a newer version of the /campaign the source already uses, not a distinct resource.

## Veeqo — gaps

Today (9): `customers`, `delivery_methods`, `orders`, `products`, `purchase_orders`, `stores`, `suppliers`, `tags`, `warehouses`

Diffed against: <https://developers.veeqo.com/api/operations/list-all-customers/>

- [ ] `GET returns on order (/orders/{order_id}/returns)` — returns and refunds per order — not present in any synced table (medium)
- [ ] `GET stock entry (/sellables/{sellable_id}/warehouses/{warehouse_id}/stock_entry)` — per-warehouse inventory levels, Veeqo's core operational metric, as a flat table (medium)
- [ ] `GET view tracking events (shipments)` — delivery state transitions per shipment, the fulfillment timeline (medium)
- [ ] `GET retrieve bundle detail and GET retrieve bundle content` — bundle/kit composition — resolves which sellables make up a bundled product (low)
- [ ] `GET view properties (/products/{product_id}/product_property_specifics/{property_id})` — custom product attributes used as breakdown dimensions (low)
- [ ] `GET view company detail (/company)` — single account/company record for currency and locale context (low)

Note: Parsed the complete operation index out of the developers.veeqo.com nav (76 operations, identical on every page; the site ships no OpenAPI file — /openapi.yaml, /openapi.json and /swagger.json all 404). Every documented top-level \*list\* endpoint is already synced (orders, products, customers, purchase_orders, suppliers, warehouses, channels->stores, tags, delivery_methods). Veeqo publishes no list endpoints for allocations, shipments, returns or bundles, so all gaps above require fan-out from orders/products; the repo's own veeqo/api_inventory.md notes allocations and shipments are already embedded in the order payload. Excluded the Carrier/Rate Shopping APIs (label buying, scan forms) as operational, not analytical.

## Vellum — gaps

Today (5): `document_indexes`, `documents`, `prompt_deployments`, `workflow_deployments`, `workflow_execution_events`

Diffed against: <https://docs.vellum.ai/openapi.json>

- [ ] `GET /v1/workflow-deployments/{id}/releases` — release/version history per workflow deployment — the state-transition table for what shipped when (medium)
- [ ] `GET /v1/workflow-deployments/{id}/release-tags` — lookup mapping tags (LATEST, PRODUCTION) to workflow deployment releases (medium)
- [ ] `GET /v1/deployments/{id}/release-tags` — same lookup for the prompt deployments we already sync (medium)
- [ ] `GET /v1/folder-entities` — lookup mapping deployments, indexes and sandboxes to the folders that organize them (low)
- [ ] `GET /v1/test-suite-runs/{id}/executions` — eval results per test suite run; only reachable if run tokens are known (low)

Note: OpenAPI 3.1 spec published at docs.vellum.ai/openapi.json (linked from docs.vellum.ai/developers/client-sdk/llms.txt; the api-reference paths in the payload's doc urls now 404 and redirect to /developers/client-sdk/). Coverage is close to proportionate: most of the remaining API is execute/submit POST endpoints (execute-prompt, execute-workflow, search, submit-actuals) rather than syncable collections. Note the test-suite endpoints have no parent list endpoint (no GET /v1/test-suites and no GET /v1/test-suite-runs), so test cases and run executions cannot be enumerated without externally supplied ids.

## Veracode — **thin**

Today (4): `applications`, `findings`, `sandboxes`, `sca_findings`

Diffed against: <https://api.swaggerhub.com/apis/Veracode?limit=100>

- [ ] `GET /appsec/v2/applications/{app_guid}/summary_report` — Veracode's headline per-application result: policy compliance status, security score and flaw counts by severity (high)
- [ ] `GET /appsec/v1/cwes` — lookup table resolving the CWE id carried on every findings row we already sync (high)
- [ ] `GET /appsec/v1/categories` — lookup table resolving the finding category id on findings we already sync (high)
- [ ] `GET /appsec/v1/policies` — lookup resolving the policy GUID/name attached to each application we sync (high)
- [ ] `GET /v2/teams (Identity API)` — lookup resolving the team GUIDs on applications, enabling per-team risk rollups (high)
- [ ] `POST /appsec/v1/analytics/report + GET /appsec/v1/analytics/report/{id} (report_type SCANS)` — org-wide scan history — there is no scan/build table at all today, only findings (high)
- [ ] `POST /appsec/v1/analytics/report (report_type FINDINGS)` — bulk org-wide findings export without per-application fan-out, the vendor's designated warehouse path (medium)
- [ ] `GET /v2/business_units (Identity API)` — lookup resolving business unit on applications for org-level breakdowns (medium)
- [ ] `GET /v2/users (Identity API)` — lookup resolving user ids on annotations, mitigations and application owners (medium)
- [ ] `GET /v3/workspaces and /v3/workspaces/{id}/issues, /libraries, /projects (SCA Agent API)` — agent-based SCA issues and library inventory, a separate dataset from the appsec SCA findings we sync (medium)
- [ ] `GET /mpt/v1/scans and /mpt/v1/scans/{id}/findings` — manual penetration test scans and their findings, absent from the appsec findings feed (low)

Note: Veracode has no single spec; it publishes 16 separate OpenAPI specs on SwaggerHub under the Veracode org (applications, findings, identity, policy, summary_report, sca_agent, reporting, sandbox, annotations, etc). Diffed against all of them via the SwaggerHub API. The Annotations API is POST-only (write path) so it cannot be synced. Current coverage is the Applications + Findings + Sandbox specs only; Identity, Policy, Summary Report and Reporting are entirely unrepresented.

## Vitally — gaps

Today (10): `Accounts`, `Conversations`, `Custom_Objects`, `Messages`, `NPS_Responses`, `Notes`, `Organizations`, `Projects`, `Tasks`, `Users`

Diffed against: <https://docs.vitally.io/en/collections/10410457-rest-api>

- [ ] `GET /resources/admins` — lookup resolving the CSM/admin ids that appear on accounts, tasks, notes and conversations (high)
- [ ] `GET /resources/projectTemplates` — lookup resolving the template behind each Project we already sync (high)
- [ ] `GET /resources/meetings (and /resources/accounts/{id}/meetings)` — customer meeting activity records, a core engagement object with no equivalent today (high)
- [ ] `GET /resources/projectCategories` — lookup resolving the category grouping on project templates and projects (medium)
- [ ] `GET /resources/surveys/{surveyId}/responses` — custom survey responses — analytical feedback data distinct from the NPS responses already synced (medium)
- [ ] `GET /resources/customFields?model={model}` — custom trait definitions that give names and types to the opaque trait keys on accounts, users and custom objects (medium)

Note: The source already discovers per-custom-object instance tables dynamically at sync time (CUSTOM_OBJECT_SCHEMA_PREFIX in source.py calls /resources/customObjects/:id/instances), so the static Custom_Objects table is only the definitions and the real records are covered. Vitally has no OpenAPI spec; the resource list came from the 19-article REST API collection index, cross-checked by fetching each endpoint article for its exact path.

## Vultr — gaps

Today (10): `bare_metals`, `billing_history`, `block_storage`, `instances`, `invoices`, `kubernetes_clusters`, `load_balancers`, `managed_databases`, `snapshots`, `users`

Diffed against: <https://raw.githubusercontent.com/vultr/api-postman-collection/master/postman/schemas/schema.json>

- [ ] `GET /v2/billing/invoices/{invoice-id}/items` — invoice line items — the per-resource cost breakdown behind the invoices we already sync (high)
- [ ] `GET /v2/plans and /v2/plans-metal` — lookup resolving the plan id on every instance and bare metal, giving vCPU/RAM/price per row (high)
- [ ] `GET /v2/regions` — lookup resolving the region code carried on instances, blocks, snapshots and load balancers (high)
- [ ] `GET /v2/instances/{instance-id}/bandwidth` — daily in/out bandwidth per instance, the main usage time series for cost attribution (high)
- [ ] `GET /v2/bare-metals/{baremetal-id}/bandwidth` — same daily usage time series for bare metal servers (medium)
- [ ] `GET /v2/account` — account balance, pending charges and last payment — the headline billing figures (medium)
- [ ] `GET /v2/os` — lookup resolving os_id on instances, bare metals and snapshots (medium)
- [ ] `GET /v2/applications` — lookup resolving app_id / image_id on marketplace-deployed instances (medium)
- [ ] `GET /v2/kubernetes/clusters/{vke-id}/node-pools` — node pool sizing and node counts under the clusters we already sync (medium)
- [ ] `GET /v2/object-storage` — object storage subscription inventory, a billed resource class missing from the asset tables (medium)
- [ ] `GET /v2/backups` — automatic backup inventory, a billed add-on not covered by the snapshots table (low)
- [ ] `GET /v2/reserved-ips` — reserved IP inventory, a separately billed resource (low)

Note: Vultr's rendered API reference at www.vultr.com/api/ returns 403 to non-browser clients, so I diffed against the OpenAPI schema in Vultr's own api-postman-collection repo (109 paths). That schema looks somewhat behind the live API — it omits managed databases, VPCs, CDN, container registry and subaccounts, all of which exist in the official govultr client. So the true gap list may be slightly larger; every gap listed above is present in the fetched schema. The repo also already contains a hand-written api_inventory.md documenting the 10 synced endpoints.

## Wasabi — gaps

Today (4): `accounts`, `bucket_utilizations`, `sub_account_invoices`, `utilizations`

Diffed against: <https://docs.wasabi.com/llms.txt>

- [ ] `GET /v1/accounts/{AcctNum}/invoices/{SubInvoiceNum}/regional` — per-region cost and usage breakdown of the sub-invoices we already sync; Wasabi explicitly recommends this over the flat detail endpoint (high)
- [ ] `GET /v1/accounts/{AcctNum}/invoices/{SubInvoiceNum}` — sub-invoice line detail (unit cost, resource type); being deprecated in favor of the regional variant but still the only flat line-item view (medium)
- [ ] `GET /v1/accounts/{AcctNum}/air-jobs` — Wasabi AiR job history per sub-account, an activity table with no equivalent today (low)

Note: Coverage is close to complete for the Wasabi Account Control API (partner.wasabisys.com). I verified from the endpoint docs that /v1/utilizations and /v1/utilizations/buckets already return BOTH control and sub-account rows, so /v1/control-account/utilizations, /v1/control-account/bucket-utilizations, /v1/accounts/{acct}/utilizations and /v1/utilizations/status are all redundant with what is already synced and I deliberately excluded them. Wasabi also ships two other API families on different hosts and credentials — the WACM Connect API (api.wacm.wasabisys.com: control accounts, channel accounts, members, standalone accounts, /v1/invoices, /v1/usages) and the Stats API (/v1/standalone/utilizations) — which would be separate sources, not gaps in this one. Wasabi publishes a docs llms.txt plus per-page .md, which is the fastest way to enumerate.

## Watchmode — gaps

Today (6): `genres`, `networks`, `regions`, `releases`, `sources`, `titles`

Diffed against: <https://api.watchmode.com/openapi.json>

- [ ] `GET /v1/title/{title_id}/sources` — per-title streaming availability — Watchmode's entire reason to exist, and a fan-out of the titles we already sync (high)
- [ ] `GET /v1/title/{title_id}/details` — full title metadata (ratings, runtime, plot, network, genre ids); list-titles only returns a stub row (high)
- [ ] `GET /v1/title/{title_id}/cast-crew` — title-to-person membership table linking titles we sync to people (high)
- [ ] `GET /v1/person/{person_id}` — lookup resolving the person ids returned by cast-crew (high)
- [ ] `GET /v1/title/{title_id}/episodes` — per-episode rows for TV titles, the finest analytical grain available (medium)
- [ ] `GET /v1/title/{title_id}/seasons` — season-level rollup between titles and episodes (medium)
- [ ] `GET /v1/title-release-dates` — advanced release-date feed with source and region dimensions that the simple /releases table lacks (medium)
- [ ] `GET /v1/changes/titles_sources_changed` — change feed of streaming-availability changes, the natural incremental driver for a title_sources table (medium)
- [ ] `GET /v1/changes/new_titles` — change feed of newly added titles, enables incremental sync of the titles table (low)
- [ ] `GET /v1/changes/titles_details_changed` — change feed for title metadata updates (low)
- [ ] `GET /v1/changes/new_people` — change feed for newly added people, pairs with a person table (low)

Note: Watchmode ships a real OpenAPI 3 spec at https://api.watchmode.com/openapi.json (also /openapi.yaml, /swagger.json) even though the docs page itself is a JS-rendered Redoc shell. 23 GET operations total vs 6 synced tables. The synced 'sources' table is the streaming-service catalog (/v1/sources), not per-title availability — those are different endpoints and the per-title one is the valuable analytical join.

## Webflow — gaps

Today (7): `collections`, `forms`, `orders`, `pages`, `products`, `sites`, `users`

Diffed against: <https://developers.webflow.com/data/reference/cms/collections/list>

- [ ] `GET /v2/sites/{site_id}/form_submissions` — form submission rows — we sync form definitions but none of the submissions, which is the actual lead data (high)
- [ ] `GET /v2/sites/{site_id}/analyze/reports/traffic` — site traffic time series, Webflow's headline analytics metric, entirely absent (high)
- [ ] `GET /v2/sites/{site_id}/analyze/reports/top_pages` — per-page traffic breakdown that joins directly to the pages table we already sync (high)
- [ ] `GET /v2/sites/{site_id}/analyze/reports/top_events` — conversion and interaction event counts per site (medium)
- [ ] `GET /v2/sites/{site_id}/analyze/reports/top_dimensions` — traffic broken down by referrer, device, country and other dimensions (medium)
- [ ] `GET /v2/sites/{site_id}/analyze/reports/time_on_page` — engagement metric per page, complements top_pages (medium)
- [ ] `GET /v2/collections/{sku_collection_id}/items/{sku_id}/inventory` — stock levels per SKU for the products we already sync (medium)
- [ ] `GET /v2/sites/{site_id}/comments` — design review comment threads, an activity/collaboration table with no equivalent (medium)
- [ ] `GET /v2/sites/{site_id}/activity_logs` — site change history — who published or edited what and when (medium)
- [ ] `GET /v2/sites/{site_id}/assets` — asset inventory with sizes and folder placement (low)
- [ ] `GET /v2/sites/{site_id}/components` — component inventory for auditing design-system reuse across pages (low)

Note: The source already discovers CMS collection items dynamically: source.py/settings.py build one table per collection at sync time (COLLECTION_SCHEMA_PREFIX + /collections/{id}/items), so CMS content is covered even though 'collection items' is not in the static table list. Webflow's Fern docs have no downloadable spec URL I could find, so I enumerated the resource list from the reference navigation in the rendered docs (135 reference pages) and then fetched each candidate page to read its exact /v2/... path. Excluded as config/plumbing: webhooks, custom code, custom fonts, Google Tag Manager, robots.txt, 301 redirects, well-known files, OAuth/token introspection, workspace management.

## WeightsAndBiases — gaps

Today (5): `artifacts`, `projects`, `reports`, `runs`, `sweeps`

Diffed against: <https://api.wandb.ai/graphql>

- [ ] `Run.history / Run.sampledHistory / Run.parquetHistory` — the logged metric time series per step — W&B's core dataset; today only the final summary metrics on runs are synced (high)
- [ ] `Run.outputArtifacts and Run.inputArtifacts` — run-to-artifact lineage join table connecting the two largest tables already synced (high)
- [ ] `Entity.members / Project.teamMembers` — lookup resolving the userId carried on every run, sweep and report (high)
- [ ] `Project.artifactCollections and Project.artifactTypes` — lookup naming the collection and type each artifact version belongs to; the source already walks these to reach versions but never emits them (high)
- [ ] `Run.systemMetrics / Run.events` — GPU, CPU and memory utilization time series per run, the basis for compute-efficiency analysis (medium)
- [ ] `Run.files` — per-run output file inventory with sizes, useful for storage attribution (medium)
- [ ] `usage / usageByPeriod (Query root)` — account compute and storage consumption by period, the headline cost metric (medium)
- [ ] `entities / Entity (Query root)` — the team/entity list itself as a lookup; projects and runs are currently synced for one entity with no entity table (medium)
- [ ] `Project.computeHours and Project.storageBytes` — per-project compute and storage rollups for cost allocation across teams (medium)
- [ ] `Project.runQueues and launchAgents / QueuedRun` — Launch job queue and agent execution history, a scheduling activity table (low)
- [ ] `triggers / triggerExecutions (Automations)` — automation run history — which automation fired on which artifact or run (low)
- [ ] `Sweep.runs` — explicit sweep-to-run membership; runs carry sweepName but the ordered membership and per-sweep best-run relation are not exposed (low)

Note: W&B has no REST API for this data — the source talks straight to the GraphQL endpoint at api.wandb.ai/graphql, so I diffed by running unauthenticated introspection against that live endpoint (it answers \_\_schema and \_\_type queries without a key). Query root exposes 72 fields; Project exposes 89 fields and Run exposes 86, so the 5 synced tables are a small slice. Run.history in particular is the product's headline data and is completely absent. Note it is high-volume and would need step-level partitioning.

## WikipediaPageviews — gaps

Today (3): `article_pageviews`, `pageviews`, `top_articles`

Diffed against: <https://gitlab.wikimedia.org/repos/generated-data-platform/aqs/analytics-api/-/raw/main/reference/page-views.md>

- [ ] `GET /metrics/pageviews/top-by-country/{project}/{access}/{year}/{month}` — country breakdown of project pageviews — a geographic dimension on the headline metric that is otherwise unavailable (high)
- [ ] `GET /metrics/pageviews/top-per-country/{country}/{access}/{year}/{month}/{day}` — most-viewed articles within a single country, the geo equivalent of the top_articles table already synced (medium)
- [ ] `GET /metrics/unique-devices/{project}/{access-site}/{granularity}/{start}/{end}` — unique device counts, Wikimedia's other headline traffic metric and the closest thing to a uniques denominator for pageviews (medium)
- [ ] `GET /metrics/mediarequests/per-file/{referer}/{agent}/{file-path}/{granularity}/{start}/{end} and the aggregate variant` — media file request counts, the same traffic question for images and video (low)
- [ ] `GET /metrics/legacy/pagecounts/aggregate/{project}/{access-site}/{granularity}/{start}/{end}` — pre-2015 traffic history for long-range trend analysis; the modern pageviews series starts July 2015 (low)

Note: Confirmed the three synced tables map to /pageviews/aggregate, /pageviews/per-article and /pageviews/top. A machine-readable spec exists at https://wikimedia.org/api/rest\_v1/metrics/pageviews/api-spec.json and the docs site's source markdown on GitLab names the exact operation path for every documented endpoint, which is the reliable way to enumerate. The AQS analytics API has four sibling families beyond page views (edits, editors, devices, media files, Commons category metrics); I only listed the ones a source scoped to 'Wikipedia Pageviews' plausibly owns. Editor and edit metrics are real endpoints but arguably belong in a separate source.

## Windmill — gaps

Today (9): `apps`, `audit_logs`, `completed_jobs`, `flows`, `queued_jobs`, `resources`, `schedules`, `scripts`, `users`

Diffed against: <https://raw.githubusercontent.com/windmill-labs/windmill/main/backend/windmill-api/openapi.yaml>

- [ ] `folders/list (GET /w/{workspace}/folders/list)` — lookup that resolves the f/<folder>/ path prefix carried by every script, flow, app and resource we already sync (high)
- [ ] `groups/list + groups/get (GET /w/{workspace}/groups/list, /groups/get)` — group membership and ownership lookup for the ACLs on synced runnables (high)
- [ ] `workspaces/list (GET /workspaces/list)` — lookup resolving the workspace id every other table is scoped by (high)
- [ ] `users/list_usage + workspaces/usage` — per-user and per-workspace execution counts, the natural cost/usage metric (medium)
- [ ] `workers/list, workers/queue_counts, workers/queue_metrics` — worker capacity and queue depth telemetry to pair with queued_jobs/completed_jobs (medium)
- [ ] `scripts/history, flows/history, apps/history` — deployment version history for the runnables we already sync (medium)
- [ ] `concurrency_groups/list (GET /concurrency_groups/list)` — concurrency limits and running counts explaining job queue waits (medium)
- [ ] `assets/list (GET /w/{workspace}/assets/list)` — data assets (S3 paths, resources, DB tables) referenced by scripts and flows (low)
- [ ] `resources/type (GET /w/{workspace}/resources/type)` — lookup resolving the resource_type field on synced resources (low)
- [ ] `inputs/list (GET /w/{workspace}/inputs/list)` — saved job inputs, useful for run-parameter analysis (low)

Note: Static endpoint list, no dynamic table discovery. Deliberately excluded variables/tokens/oauth and the large \*\_triggers family (kafka, nats, mqtt, sqs, http, websocket, postgres, gcp, azure) as credential/plumbing config.

## Wordpress — gaps

Today (7): `categories`, `comments`, `media`, `pages`, `posts`, `tags`, `users`

Diffed against: <https://developer.wordpress.org/rest-api/reference/>

- [ ] `types (GET /wp/v2/types)` — lookup enumerating registered post types; also the only way to discover custom post types this source never syncs (high)
- [ ] `taxonomies (GET /wp/v2/taxonomies)` — lookup enumerating taxonomies beyond the built-in categories/tags we already sync (high)
- [ ] `post revisions (GET /wp/v2/posts/{id}/revisions)` — edit history for posts, the only source of content change-over-time (high)
- [ ] `statuses (GET /wp/v2/statuses)` — lookup resolving the status field on posts and pages (medium)
- [ ] `page revisions (GET /wp/v2/pages/{id}/revisions)` — edit history for pages (medium)
- [ ] `blocks (GET /wp/v2/blocks)` — reusable block content referenced across posts and pages (low)
- [ ] `block revisions (GET /wp/v2/blocks/{id}/revisions)` — change history for reusable blocks (low)

Note: WordPress registers a REST route per custom post type and per custom taxonomy (/wp/v2/{rest_base}), so full coverage really needs dynamic table discovery driven off /wp/v2/types and /wp/v2/taxonomies rather than a fixed table list. Excluded settings, plugins, themes, widgets, sidebars, menu-locations, application-passwords and the block-directory/pattern-directory routes as site config or plumbing.

## Workable — gaps

Today (5): `candidates`, `jobs`, `members`, `recruiters`, `stages`

Diffed against: <https://workable.readme.io/reference/jobs>

- [ ] `candidate activities (GET /candidates/{id}/activities)` — the stage-transition and action history behind every candidate; without it stages is a static snapshot (high)
- [ ] `employees (GET /employees)` — the entire Workable HR side is absent, and it is what links hires back to headcount (high)
- [ ] `departments (GET /departments)` — lookup resolving the department carried on jobs, requisitions and employees (high)
- [ ] `locations (GET /accounts/{subdomain}/locations)` — lookup resolving the location id on jobs and candidates (high)
- [ ] `time entries (GET /time-tracking/time-entries)` — time tracking fact table for employees (high)
- [ ] `job activities (GET /jobs/{shortcode}/activities)` — per-job event stream for pipeline throughput analysis (medium)
- [ ] `requisitions (GET /requisitions)` — approved headcount that jobs are opened against (medium)
- [ ] `disqualification reasons (GET /disqualification_reasons)` — lookup resolving the disqualification reason id on rejected candidates (medium)
- [ ] `custom attributes (GET /custom_attributes, GET /jobs/{shortcode}/custom_attributes)` — lookup naming the custom attribute ids stored on candidates and jobs (medium)
- [ ] `events (GET /events)` — scheduled interviews and meetings, needed for time-to-interview metrics (medium)
- [ ] `time off requests (GET /timeoff/requests)` — absence records for the employee population (medium)
- [ ] `time off balances (GET /timeoff/balances)` — remaining entitlement per employee and category (low)

Note: Coverage is limited to the recruiting core; Workable's HR module (employees, time tracking, time off, requisitions) is entirely unsynced.

## Wrike — gaps

Today (6): `contacts`, `custom_fields`, `folders`, `spaces`, `tasks`, `workflows`

Diffed against: <https://developers.wrike.com/sitemap.xml>

- [ ] `timelogs (GET /timelogs, GET /tasks/{id}/timelogs)` — the time-tracking fact table; the headline analytical object in Wrike and completely absent (high)
- [ ] `timelog_categories (GET /timelog_categories)` — lookup resolving the category id on every timelog entry (high)
- [ ] `groups (GET /groups)` — user group membership lookup for the contacts we already sync (high)
- [ ] `tasks_history (GET /tasks/{ids}/tasks_history)` — task status transition history, the only way to compute cycle time (high)
- [ ] `custom_item_types (GET /custom_item_types)` — lookup resolving customItemTypeId on tasks and folders (medium)
- [ ] `jobroles (GET /jobroles)` — lookup resolving the job role id on contacts, bookings and timelogs (medium)
- [ ] `comments (GET /comments, GET /tasks/{id}/comments)` — collaboration volume per task and folder (medium)
- [ ] `approvals (GET /approvals, GET /tasks/{id}/approvals)` — approval state and turnaround per task/folder (medium)
- [ ] `dependencies (GET /tasks/{id}/dependencies)` — the task graph edges needed for critical-path and blocker analysis (medium)
- [ ] `bookings (GET /bookings)` — resource allocations to compare planned vs logged effort (medium)
- [ ] `timesheets (GET /timesheets)` — submitted timesheet periods and their approval state (medium)
- [ ] `audit_log (GET /audit_log)` — account-level change events across all entities (medium)

Note: The reference is a ReadMe SPA; the operation list was read from developers.wrike.com/sitemap.xml (294 /reference/\* operation pages). Wrike also has a bulk BI data export (POST /data_export, GET /data_export_schema) which may be a better bulk path than per-endpoint polling for large accounts.

## Writesonic — gaps

Today (9): `content_citations`, `content_keywords`, `performance_answers`, `performance_prompts`, `performance_summary`, `platforms`, `prompts`, `topics`, `websites`

Diffed against: <https://docs.writesonic.com/reference/content_citations_v2_geo_presence_business_export_content_citations_get>

- [ ] `GET /v2/geo/presence/business/export/actionable/content-optimize/issues` — per-page content optimization issues, the actionable half of the GEO product (high)
- [ ] `GET /v2/geo/presence/business/export/actionable/content-optimize/pages` — page-level optimization scores that the issues and recommendations hang off (high)
- [ ] `GET /v2/geo/presence/business/export/actionable/content-optimize/recommendations` — recommended fixes per page, joins to pages and issues (medium)
- [ ] `GET /v2/geo/presence/business/export/actionable/content-optimize/issues-summary` — issue counts by type, the rollup dimension for reporting (medium)
- [ ] `GET /v2/geo/presence/business/export/actionable/content-optimize/scanned-urls` — crawl inventory that resolves which URLs the issue rows refer to (medium)
- [ ] `GET /v2/seo-auditor/business/export/issues/get-issues` — SEO auditor issue export, a separate product surface with no coverage at all (medium)
- [ ] `GET /v2/geo/presence/business/export/actionable/content-optimize/recommendations/all` — account-wide recommendation list rather than per-page (low)

Note: The GEO presence export family (citations, keywords, performance answers/prompts/summary, and the config lookups platforms/prompts/topics/websites) is fully covered. Everything else in the Writesonic docs is POST content-generation (article writer, ad copy, social captions) which has no queryable resource semantics and is correctly excluded.

## Wufoo — **thin**

Today (3): `forms`, `reports`, `users`

Diffed against: <https://wufoo.github.io/docs/>

- [ ] `form entries (GET /api/v3/forms/{hash}/entries.json)` — the actual form submission data; without it the source syncs metadata only (high)
- [ ] `form fields (GET /api/v3/forms/{hash}/fields.json)` — lookup mapping Field1/Field2 entry column ids to human field titles and choice values (high)
- [ ] `report entries (GET /api/v3/reports/{hash}/entries.json)` — the filtered entry set behind each report we already sync (medium)
- [ ] `report fields (GET /api/v3/reports/{hash}/fields.json)` — lookup resolving column ids on report entries (medium)
- [ ] `form entries count (GET /api/v3/forms/{hash}/entries/count.json)` — cheap submission-volume metric per form (low)
- [ ] `report widgets (GET /api/v3/reports/{hash}/widgets.json)` — the aggregate/chart definitions attached to a report (low)
- [ ] `form comments (GET /api/v3/forms/{hash}/comments.json)` — entry-level comments for review workflows (low)

Note: Not dynamic discovery — products/warehouse_sources/backend/temporal/data_imports/sources/wufoo/settings.py hardcodes three account-level endpoints and its comment explicitly defers the per-form fan-out ('require a parent form hash and are intentionally left out of this first cut'). Entries are the product's whole payload, so closing this needs per-form dynamic table generation driven off the forms list. Wufoo v3 is the API's only version and its docs now live at wufoo.github.io/docs (www.wufoo.com/docs/api/v3 redirects to a SurveyMonkey help page).

## Xmatters — gaps

Today (9): `devices`, `dynamic_teams`, `events`, `groups`, `people`, `plans`, `roles`, `sites`, `subscriptions`

Diffed against: <https://help.xmatters.com/xmapi/index.html>

- [ ] `audits (GET /api/xm/1/audits)` — the notification, response and event audit records — the main analytical fact table for alerting (high)
- [ ] `incidents (GET /api/xm/1/incidents, /incidents/{id}/timeline-entries)` — incident objects and their timeline; the headline object of xMatters incident management (high)
- [ ] `group members (GET /api/xm/1/groups/{id}/members)` — membership lookup joining the people and groups we already sync (high)
- [ ] `group shifts (GET /api/xm/1/groups/{id}/shifts)` — on-call rotation definitions; without them groups carry no schedule (high)
- [ ] `on-call (GET /api/xm/1/on-call)` — who is on call over a timeframe, the vendor's headline query (high)
- [ ] `services (GET /api/xm/1/services)` — lookup resolving the service referenced by incidents and signals (high)
- [ ] `event user deliveries (GET /api/xm/1/events/{id}/user-deliveries)` — per-recipient delivery and response outcomes for each event (medium)
- [ ] `signals (GET /api/xm/1/signals)` — the raw inbound alerts that events are created from (medium)
- [ ] `shift members (GET /api/xm/1/groups/{id}/shifts/{id}/members)` — who is rostered on each shift, with rotation order (medium)
- [ ] `on-call summary (GET /api/xm/1/on-call-summary)` — aggregated on-call load per person and group (medium)
- [ ] `forms (GET /api/xm/1/forms)` — lookup resolving the form id carried on events and scenarios (medium)
- [ ] `changes (GET /api/xm/1/changes)` — Change Intelligence records, used to correlate deploys with incidents (medium)

Note: Also unsynced but lower value: /service-dependencies, /event-suppressions, /temporary-absences, /subscriptions/{id}/subscribers, /people/{id}/group-memberships, /groups/{id}/supervisors, /device-types, /device-names, /conference-bridges. The audits and events endpoints are timeframe-based historical queries that need an explicit permission on the API user, which is worth flagging when implementing.

## YouSign — gaps

Today (7): `contacts`, `documents`, `labels`, `signature_requests`, `signers`, `users`, `workspaces`

Diffed against: <https://developers.yousign.com/reference/get-contacts-1>

- [ ] `templates (GET /templates)` — lookup resolving the template a signature request was created from (high)
- [ ] `consumptions (GET /consumptions, GET /consumptions/detail)` — the vendor's usage metering per period, the natural volume metric for a signing workload (medium)
- [ ] `consumption records (GET /consumptions/records/invited_signers, /identifications, /electronic_seals)` — line-item detail behind each consumption period (medium)
- [ ] `custom properties (GET /custom_properties)` — lookup naming the custom property ids attached to signature requests (medium)
- [ ] `identity verifications (GET /verifications/identity_documents, /companies, /bank_accounts, /proofs_of_address, /identity_videos, /watchlists)` — KYC verification outcomes per signer, an entire product surface with no coverage (medium)
- [ ] `workflow sessions (GET /workflow_sessions)` — identity/onboarding workflow runs and their state (medium)
- [ ] `workflow session applicants (GET /workflow_sessions/{id}/applicants)` — per-applicant outcome inside a workflow session (medium)
- [ ] `followers (GET /signature_requests/{signatureRequestId}/followers)` — who is CC'd on a request, alongside the signers we already sync (medium)
- [ ] `document analyses (GET /document_analyses)` — automated document checks and their verdicts (low)
- [ ] `consent requests (GET /signature_requests/{signatureRequestId}/consent_requests)` — per-signer consent steps within a request (low)
- [ ] `workflow templates (GET /workflow_templates)` — lookup resolving the template behind a workflow session (low)
- [ ] `electronic seals (GET /electronic_seals/{id})` — sealed-document records, distinct from the signature request flow (low)

Note: Yousign publishes an OAS spec (docs slug 'oas-specification'); paths above were confirmed one by one from the ReadMe reference pages. Approvers only expose a single-item GET (/signature_requests/{id}/approvers/{approverId}) with no list endpoint, so they are not listed as a gap. Audit trails are PDF downloads rather than queryable collections.

## ZapierSupportedStorage — adequate

Today (1): `records`

Diffed against: <https://help.zapier.com/api/v2/help_center/en-us/articles/8496293271053.json>

No material gaps found.

Note: Storage by Zapier is a flat key/value store scoped to one store secret - the vendor doc describes only set/get/increment/list-push operations on keys, with no additional collections. The single `records` table (one row per key) is proportionate. The source's own settings.py documents the same: one endpoint, GET /api/records, full-refresh only, no timestamps.

## ZapSign — gaps

Today (3): `documents`, `signers`, `templates`

Diffed against: <https://docs.zapsign.com.br/english/sitemap-pages.xml>

- [ ] `docs/signer-log/{doc_token} (document audit trail)` — per-document signature event history (viewed, signed, refused, timestamps) - the state-transition table behind document status (high)
- [ ] `users (GET /api/v1/users/, account users)` — lookup table resolving the created_by / account user IDs already carried on documents (medium)
- [ ] `signer-verification-details/{signer_token}` — authentication and identity-verification outcome per signer, needed to analyze signing friction and failures (medium)
- [ ] `checks/{check_id} and checks/{check_id}/details (background checks)` — background-check status and results tied to signers; no list endpoint, so it must fan out from signers (low)

Note: Docs are a GitBook site with no OpenAPI spec; the English sitemap enumerates every endpoint page and each page embeds the literal api.zapsign.com.br path, which is what I diffed against. Webhook create/delete/logs endpoints exist but were excluded as plumbing.

## ZendeskSell — gaps

Today (12): `calls`, `contacts`, `deals`, `leads`, `notes`, `orders`, `pipelines`, `products`, `stages`, `tags`, `tasks`, `users`

Diffed against: <https://developer.zendesk.com/api-reference/sales-crm/resources/introduction/>

- [ ] `associated_contacts (GET /v2/deals/{deal_id}/associated_contacts)` — the deal-to-contact junction table; without it you cannot attribute deals to the contacts involved (high)
- [ ] `line_items (GET /v2/orders/{order_id}/line_items)` — per-order product lines with quantity, price and discount - the revenue detail behind orders we already sync (high)
- [ ] `loss_reasons` — lookup table resolving the loss_reason_id already present on deals; required for any win/loss analysis (high)
- [ ] `deal_sources` — lookup table resolving deals.source_id; unlocks pipeline-by-source attribution (high)
- [ ] `lead_sources` — lookup table resolving leads.source_id; unlocks lead-source attribution (high)
- [ ] `lead_conversions` — the lead-to-contact/deal transition record - the only way to build a conversion funnel across the objects we already sync (high)
- [ ] `custom_fields` — field-definition lookup that names and types the custom_fields blobs on contacts, deals and leads (medium)
- [ ] `deal_unqualified_reasons` — lookup resolving the unqualified_reason_id on deals (medium)
- [ ] `lead_unqualified_reasons` — lookup resolving the unqualified_reason_id on leads (medium)
- [ ] `call_outcomes` — lookup resolving outcome_id on the calls table we already sync (medium)
- [ ] `text_messages` — SMS activity alongside calls and notes, completing the rep-activity picture (medium)
- [ ] `sequence_enrollments` — which contacts/leads entered which outreach sequence and their enrollment state (medium)

Note: Zendesk Sell also ships a separate Firehose (incremental sync) API covering appointments, collaborations, visits, documents and sources. Those remain uncovered but were ranked below the cut; `sequences`, `visits`, `visit\_outcomes`, `collaborations` and `documents` are the next tier.

## ZendeskSunshine — gaps

Today (6): `limits`, `object_records`, `object_type_policies`, `object_types`, `relationship_records`, `relationship_types`

Diffed against: <https://developer.zendesk.com/api-reference/custom-data/custom-objects-api/object_events/>

- [ ] `object_events (GET /api/sunshine/objects/events)` — the create/update/delete event stream for custom object records - the only source of change history for records we already sync (high)

Note: Coverage of the /api/sunshine surface is essentially complete: object_types, object_records, object_type_policies (= permissions), relationship_types, relationship_records and limits map 1:1 to the documented resources. The source also discovers object types dynamically at sync time (it pages /api/sunshine/objects/types then builds a per-type POST objects/query resource), so the static table list understates what it syncs. Remaining uncovered paths are jobs (async plumbing) and search. Separately, Zendesk has superseded Sunshine with a /api/v2/custom_objects family (custom_object_fields, custom_object_record_events, object_triggers) - a different API surface worth tracking, not a gap in this connector.

## Zenduty — gaps

Today (12): `account_members`, `escalation_policies`, `incidents`, `maintenance_windows`, `postmortems`, `roles`, `schedules`, `services`, `slas`, `tags`, `team_members`, `teams`

Diffed against: <https://apidocs.zenduty.com/openapi.json>

- [ ] `incidents/{incident_number}/alerts/` — the raw alerts that rolled up into each incident - core noise/alert-volume analysis (high)
- [ ] `account/teams/{team_id}/oncall/ (v2)` — resolved on-call shifts per team; the headline output of schedules and escalation policies we already sync (high)
- [ ] `incidents/{incident_number}/responders/ (v2)` — who was engaged on each incident - the membership table for responder load and MTTA analysis (high)
- [ ] `account/teams/{team_id}/priority/` — lookup table resolving the priority ID carried on incidents (high)
- [ ] `incidents/{incident_number}/note/` — incident timeline notes, the qualitative record alongside postmortems we already sync (medium)
- [ ] `incidents/{incident_number}/tags/` — incident-to-tag junction; we sync team tags but not which incidents carry them (medium)
- [ ] `account/teams/{team_id}/schedules/{schedule_id}/overrides/` — schedule overrides explain why actual on-call differed from the rotation (medium)
- [ ] `account/customroles/` — lookup resolving the custom role IDs on account members (medium)
- [ ] `account/teams/{team_id}/task_templates/` — incident task templates, useful for measuring runbook adoption (low)

Note: apidocs.zenduty.com is a ReDoc shell; the real spec is ./openapi.json (71 paths). Note the spec literally uses `{}` rather than a named parameter in several team-scoped list paths (e.g. /api/account/teams/{}/schedules/), so path templating there is inconsistent. Event router, integrations, transformers, per-user notification/forwarding rules and team permissions were excluded as configuration.

## Zenloop — gaps

Today (3): `properties`, `survey_groups`, `surveys`

Diffed against: <https://docs.zenloop.com/reference>

- [ ] `answers (GET, per survey)` — the actual NPS/CSAT responses with score, comment and recipient properties - the product's core dataset and currently absent entirely (high)
- [ ] `survey summary (Get Summary of Survey)` — the vendor's headline NPS score and promoter/passive/detractor breakdown per survey (high)
- [ ] `answers for survey group (Get Answers for Survey Group)` — rolled-up answers across a survey group, matching the survey_groups table we already sync (medium)
- [ ] `survey group summary (Get Summary of Survey Groups)` — group-level NPS aggregate, the comparison dimension for group reporting (medium)
- [ ] `roles (Get roles)` — lookup for user role assignments (low)

Note: docs.zenloop.com is a ReadMe.io site that aggressively rate-limits and 404s the deep-link URLs recorded in the payload (get-properties, get-survey-groups). The /reference index still serves the embedded page manifest, which lists every endpoint with its HTTP method - that is what I diffed against. Only 8 GET endpoints exist in the whole API; PostHog syncs 3 of them, and the missing `answers` endpoint is the one that carries all the response data, so this connector is effectively metadata-only today.

## Zep — **thin**

Today (3): `thread_messages`, `threads`, `users`

Diffed against: <https://help.getzep.com/sitemap.xml>

- [ ] `graph/edge/user/{user_id} and graph/edge/graph/{graph_id} (edges/facts)` — the temporal fact triples that are Zep's headline product - relationships with valid_at/invalid_at intervals (high)
- [ ] `graph/node/user/{user_id} and graph/node/graph/{graph_id} (nodes/entities)` — the extracted entities in the knowledge graph, the lookup table every edge and observation points at (high)
- [ ] `graph/episodes/user/{user_id} and graph/episodes/graph/{graph_id}` — the ingested source episodes that produced each node and edge - the provenance link back to thread messages (high)
- [ ] `graph/list-all (graphs)` — lookup enumerating non-user graphs; without it the entire graph-scoped side of the API is unreachable (high)
- [ ] `graph/observation/user/{user_id} and graph/observation/graph/{graph_id}` — per-entity observations, the granular memory records behind summarized facts (medium)
- [ ] `graph thread summaries (get-user-thread-summaries / get-graph-thread-summaries)` — generated summaries per thread, the analytical rollup of the thread_messages we already sync (medium)
- [ ] `graph/list-ontology (entity and edge type definitions)` — lookup resolving the type labels stamped on nodes and edges (medium)

Note: api.getzep.com/api/v2/openapi.json returns 401, so I diffed against the doc sitemap (which enumerates every SDK reference page) and confirmed the concrete /api/v2 paths by fetching individual pages. The connector currently covers only the thread/user memory surface; the entire graph surface - which is what Zep now leads with - is unsynced, hence 'thin'. Batch jobs, context templates, user instructions and project settings were excluded as plumbing or config.

## ZonkaFeedback — gaps

Today (3): `contacts`, `responses`, `surveys`

Diffed against: <https://apidocs.zonkafeedback.com/api/collections/2077940/TVCY7Cby>

- [ ] `workspaces` — lookup resolving the workspace ID carried on surveys and responses; required to segment reporting by workspace (high)
- [ ] `locations` — lookup resolving the location ID on responses - the standard breakdown dimension for multi-site CX programs (high)
- [ ] `distribution-logs` — survey send log; pairing it with responses gives delivery, open and response rates instead of responses alone (high)
- [ ] `users` — lookup resolving the user IDs on tasks and response assignments (medium)
- [ ] `tasks` — close-the-loop follow-up tasks raised from responses, with status and assignee (medium)
- [ ] `contactlist (contact segments)` — contact-to-segment membership, the audience dimension for response analysis (medium)
- [ ] `devices` — kiosk/device lookup resolving the device ID on offline responses (medium)
- [ ] `snapshot` — vendor-computed NPS/CSAT/CES aggregates, useful as a reconciliation baseline (medium)
- [ ] `devices/uptimestat` — device uptime history for kiosk fleet health (low)

Note: Docs are a Postman published collection, not an OpenAPI spec; I pulled the raw collection JSON (30 requests) and diffed the GET requests. Base URL is datacenter-scoped ({dc_id}.apis.zonkafeedback.com). Send-email/SMS/WhatsApp endpoints are POST-only actions and were excluded.

## Zoom — **thin**

Today (3): `meetings`, `users`, `webinars`

Diffed against: <https://developers.zoom.us/api-hub/meetings/methods/endpoints.json>

- [ ] `/report/meetings/{meetingId}/participants (and /past_meetings/{meetingId}/participants)` — per-attendee join/leave records - the core meeting-attendance fact table, and nothing in the current 3 tables carries attendance (high)
- [ ] `/report/webinars/{webinarId}/participants (and /past_webinars/{webinarId}/participants)` — webinar attendance rows; webinars are synced but have zero attendance data (high)
- [ ] `/webinars/{webinarId}/registrants` — registration records with approval status, the denominator for webinar show-up rate (high)
- [ ] `/meetings/{meetingId}/registrants` — registration records for registration-enabled meetings we already sync (high)
- [ ] `/past_meetings/{meetingId}/instances (and /past_webinars/{webinarId}/instances)` — lookup resolving each recurring meeting/webinar ID we sync to its per-occurrence UUIDs, which every report endpoint keys on (high)
- [ ] `/groups and /groups/{groupId}/members` — lookup table resolving the group IDs carried on the users rows we already sync (high)
- [ ] `/report/users` — active/inactive host report with per-user meeting counts, minutes and participant totals - Zoom's headline usage metric (high)
- [ ] `/users/{userId}/recordings` — cloud recording inventory per host, including file size and duration for storage/usage analysis (medium)
- [ ] `/report/daily` — daily rollup of new users, meetings, participants and minutes per account (medium)
- [ ] `/webinars/{webinarId}/panelists` — panelist membership per webinar, needed to separate hosts/panelists from attendees (medium)
- [ ] `/meetings/meeting_summaries and /meetings/{meetingId}/meeting_summary` — account-wide AI meeting summaries, a queryable per-meeting content table (medium)
- [ ] `/past_meetings/{meetingId}/polls, /past_webinars/{webinarId}/polls and /past_webinars/{webinarId}/qa` — poll and Q&A responses - per-respondent engagement rows tied to meetings/webinars already synced (medium)

Note: Tables are static (ZOOM_ENDPOINTS in products/warehouse_sources/backend/temporal/data_imports/sources/zoom/settings.py), no dynamic discovery. The meetings stream is pinned to params={"type": "scheduled"}, so completed/past meetings never land - which is why the /report/\* and /past_meetings/\* families are the highest-value additions. The Zoom API is split into per-product OpenAPI specs served at https://developers.zoom.us/api-hub/<product>/methods/endpoints.json; I diffed against the meetings spec (129 paths) and the users spec (https://developers.zoom.us/api-hub/users/methods/endpoints.json), and did not count the separate Phone, Team Chat, Rooms or Contact Center products, which are entirely unsynced.

## Zuora — gaps

Today (8): `accounts`, `credit_memos`, `invoices`, `orders`, `payments`, `products`, `refunds`, `subscriptions`

Diffed against: <https://developer.zuora.com/yaml/apis/zuora-openapi-full-compact.yaml>

- [ ] `object-query/invoice-items` — invoice line items - the charge-level grain behind every revenue breakdown; invoice headers alone can't be broken down by product or charge (high)
- [ ] `object-query/rate-plan-charges` — subscription charge records carrying MRR/TCV, quantity and effective dates - the driver of every recurring revenue metric (high)
- [ ] `object-query/rate-plans` — links the subscriptions already synced to their catalog rate plans; without it charges can't be rolled up per subscription (high)
- [ ] `object-query/product-rate-plans` — lookup table resolving the product IDs we already sync into named plans (high)
- [ ] `object-query/product-rate-plan-charges` — catalog charge definitions and pricing model - the lookup that gives subscription charges their product meaning (high)
- [ ] `object-query/contacts` — lookup resolving the bill-to and sold-to contact IDs carried on the accounts rows we already sync (high)
- [ ] `object-query/amendments` — subscription change history (upgrades, downgrades, cancellations) - the state-transition table for churn and expansion analysis (high)
- [ ] `object-query/debit-memos` — the missing counterpart to the credit_memos table we already sync; AR balances are wrong without it (medium)
- [ ] `object-query/credit-memo-items` — line-item grain for credit memos, needed to attribute credits to products or invoices (medium)
- [ ] `object-query/order-actions` — the individual actions inside each order we sync (create/amend/cancel/renew), giving orders analyzable structure (medium)
- [ ] `object-query/order-line-items` — non-subscription order line items with quantity and amount, missing from the order headers we sync (medium)
- [ ] `object-query/usages and object-query/processed-usages` — consumption records for usage-based charges - required to explain variable invoice amounts (medium)

Note: The connector already uses Zuora's Object Query API (/object-query/<segment>, filtered on updateddate), so every gap listed is a same-shape, same-pagination addition - the spec exposes ~50 object-query collections and the source wires up 8. Also unsynced but lower value: payment-applications, refund-applications, payment-methods, taxation-items, billing-runs, payment-runs, prepaid-balances/prepaid-balance-transactions, invoice-schedules, ramps, summarystatements. Zuora also serves the spec as zuora-openapi-for-otc.yaml (order-to-cash only); I used the full compact build, version 2026-07-24.

## Zylo — gaps

Today (12): `ActivityHistory`, `ApplicationBudgets`, `ApplicationLicenses`, `ApplicationUsers`, `Applications`, `ContractLineItems`, `Contracts`, `POLineItems`, `Payments`, `PurchaseOrders`, `SavingsEvents`, `Suppliers`

Diffed against: <https://developer.zylo.com/sitemap.xml>

- [ ] `/v2/users` — the company employee directory - lookup resolving the user IDs on the ApplicationUsers rows we already sync (high)
- [ ] `/v2/applicationStats` — per-application spend and utilization stats, Zylo's headline metric and the whole point of SaaS management (high)
- [ ] `/v2/pendingContracts` — contracts in flight/awaiting approval - the renewal pipeline, invisible from the committed Contracts table (high)
- [ ] `/v2/pendingContractLineItems` — line-item grain for pending contracts, needed to forecast renewal spend by product (medium)
- [ ] `/v2/applications/{applicationId}/functionalities` — functionality taxonomy per app - the breakdown dimension for redundant-spend analysis across the Applications we sync (medium)
- [ ] `/v2/zybrary` — Zylo's reference SaaS catalog - lookup enriching synced Applications with vendor/category benchmark data (medium)
- [ ] `/v2/customFields` — custom field definitions - lookup resolving the customer-defined field IDs that appear on applications, contracts and suppliers (medium)
- [ ] `/v2/zyloUsers` — Zylo platform users - lookup resolving owner/approver IDs referenced on applications and contracts (medium)
- [ ] `/v2/views` — application groupings (cost centers, business units) - the org breakdown dimension for spend rollups (medium)
- [ ] `/v2/applicationBudgets/stats` — budget-vs-actual aggregates alongside the raw ApplicationBudgets we already sync (medium)
- [ ] `/v2/workflows and /v2/workflows/{workflowId}/responses` — app-request and review workflow responses - per-response rows for governance reporting (low)
- [ ] `/v2/companyDocuments` — document metadata (MSAs, DPAs) linked to suppliers and contracts already synced (low)

Note: Tables are static in products/warehouse_sources/backend/temporal/data_imports/sources/zylo/settings.py (ZYLO_ENDPOINTS), no dynamic discovery. Zylo does not publish a downloadable OpenAPI file - the docs are a ReadMe.io site - so I enumerated every operation from https://developer.zylo.com/sitemap.xml and confirmed each reported path by pulling the embedded operation JSON from the individual reference pages (e.g. https://developer.zylo.com/reference/userscontroller\_getusers yields "path":"/v2/users"). Deliberately excluded as config/plumbing: /v2/alerts, /v2/integrations, /v2/automations (+executions), /v2/company, payment upload jobs, and the reporting/query job endpoints. Note /v2/purchaseOrders is already flagged in-repo as scope-gated, so some of these may 403 for keys lacking spend:read.
