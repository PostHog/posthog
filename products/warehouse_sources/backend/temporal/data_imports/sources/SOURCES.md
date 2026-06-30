# Warehouse sources — implementation status & communication methods

This file is the authoritative inventory of every source registered in [`products/warehouse_sources/backend/temporal/data_imports/sources/__init__.py`](__init__.py),
the wire protocol it uses to talk to its upstream, and whether its outbound traffic is currently routed
through the [tracked HTTP transport](common/http/) (so it shows up in our HTTP logs, metrics, and
sample-capture pipeline).

Keep this file in sync as sources are added, implemented, or migrated. The [implementing-warehouse-sources
skill](/.agents/skills/implementing-warehouse-sources/SKILL.md) instructs agents to update it as part of any
new source / vendor-SDK / migration PR.

## Status legend

| Status          | Meaning                                                                                                                   |
| --------------- | ------------------------------------------------------------------------------------------------------------------------- |
| **Implemented** | Source has working sync logic and is exposed to users (possibly behind `featureFlag=` or `releaseStatus="alpha"/"beta"`). |
| **Scaffolded**  | Source class is registered with `unreleasedSource=True` and an empty/placeholder `source.py`. No sync logic yet.          |

## Comm-method legend

| Method                    | Meaning                                                                                                                                                          |
| ------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **HTTP**                  | REST/JSON over HTTPS via the `requests` library. Routed through `make_tracked_session()` (see [common/http/](common/http/)).                                     |
| **HTTP (vendor SDK)**     | The vendor ships its own SDK that wraps HTTP. Where the SDK exposes a session/transport hook, we inject `make_tracked_session()` so the calls are still tracked. |
| **gRPC**                  | The vendor SDK uses gRPC over HTTP/2 (binary, not REST). Routed through the [tracked gRPC transport](common/grpc/) via client interceptors (see `common/grpc/`). |
| **DB protocol**           | Native database wire protocol via a driver (e.g. PostgreSQL, MySQL, Snowflake). Not HTTP.                                                                        |
| **Webhook (S3-buffered)** | Vendor pushes events to a webhook endpoint; payloads are buffered to S3 by the `WebhookSourceManager` and consumed by the pipeline.                              |

When a source uses more than one transport (e.g. BigQuery REST + Storage gRPC, or Stripe pull-API + webhooks),
the row lists both.

## Tracked-transport legend

| State         | Meaning                                                                                                                                 |
| ------------- | --------------------------------------------------------------------------------------------------------------------------------------- |
| ✅ Tracked    | Outbound calls go through `make_tracked_session()` (or the equivalent vendor-SDK injection).                                            |
| ⚠️ Vendor SDK | Vendor SDK has no session/transport hook we can use. Outbound HTTP bypasses our logging/metrics today. May need a `# nosemgrep` pragma. |
| ➖ N/A        | Source uses a native DB wire protocol (Postgres, MySQL, Snowflake, …) — neither the HTTP nor gRPC transport applies.                    |
| —             | Source is scaffolded; no transport in use yet.                                                                                          |

---

## Implemented sources

| Source              | Comm method                 | Primary library                                                 | Tracked transport           |
| ------------------- | --------------------------- | --------------------------------------------------------------- | --------------------------- |
| adroll              | HTTP                        | requests                                                        | ✅                          |
| aircall             | HTTP                        | requests                                                        | ✅                          |
| airtable            | HTTP                        | requests                                                        | ✅                          |
| algolia             | HTTP                        | requests                                                        | ✅                          |
| amazon_ads          | HTTP                        | requests                                                        | ✅                          |
| amplitude           | HTTP                        | requests                                                        | ✅                          |
| apify_dataset       | HTTP                        | requests                                                        | ✅                          |
| apollo              | HTTP                        | requests                                                        | ✅                          |
| appsflyer           | HTTP (CSV reports)          | requests                                                        | ✅                          |
| asana               | HTTP                        | requests                                                        | ✅                          |
| ashby               | HTTP                        | requests                                                        | ✅                          |
| attentive           | HTTP (webhook-first)        | requests (webhook management)                                   | ✅                          |
| attio               | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| aviationstack       | HTTP                        | requests                                                        | ✅                          |
| azure_devops        | HTTP                        | requests                                                        | ✅                          |
| bamboohr            | HTTP                        | requests                                                        | ✅                          |
| beamer              | HTTP                        | requests                                                        | ✅                          |
| bigmailer           | HTTP                        | requests                                                        | ✅                          |
| bigquery            | HTTP + gRPC                 | google-cloud-bigquery + bigquery-storage                        | ✅ (HTTP + gRPC)            |
| bing_ads            | HTTP (vendor SDK, SOAP)     | bingads SDK                                                     | ⚠️                          |
| blogger             | HTTP                        | requests                                                        | ✅                          |
| braintree           | HTTP (GraphQL)              | requests                                                        | ✅                          |
| braze               | HTTP                        | requests                                                        | ✅                          |
| breezometer         | HTTP                        | requests                                                        | ✅                          |
| brevo               | HTTP                        | requests                                                        | ✅                          |
| brex                | HTTP                        | requests                                                        | ✅                          |
| bugsnag             | HTTP                        | requests                                                        | ✅                          |
| buildbetter         | HTTP                        | requests                                                        | ✅                          |
| buildkite           | HTTP                        | requests                                                        | ✅                          |
| calendly            | HTTP                        | requests                                                        | ✅                          |
| campaign_monitor    | HTTP                        | requests                                                        | ✅                          |
| campayn             | HTTP                        | requests                                                        | ✅                          |
| canny               | HTTP                        | requests                                                        | ✅                          |
| chargebee           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| chargedesk          | HTTP                        | requests                                                        | ✅                          |
| checkout_com        | HTTP                        | requests                                                        | ✅                          |
| coda                | HTTP                        | requests                                                        | ✅                          |
| coin_api            | HTTP                        | requests                                                        | ✅                          |
| coingecko           | HTTP                        | requests                                                        | ✅                          |
| coinmarketcap       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| commercetools       | HTTP                        | requests                                                        | ✅                          |
| confluence          | HTTP                        | requests                                                        | ✅                          |
| chartmogul          | HTTP                        | requests                                                        | ✅                          |
| circleci            | HTTP                        | requests                                                        | ✅                          |
| cimis               | HTTP                        | requests                                                        | ✅                          |
| cloudflare          | HTTP                        | requests                                                        | ✅                          |
| clari               | HTTP                        | requests                                                        | ✅                          |
| clerk               | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| clickhouse          | DB protocol (HTTP-based)    | clickhouse-connect / clickhouse-driver                          | ➖                          |
| clickup             | HTTP                        | requests                                                        | ✅                          |
| clockify            | HTTP                        | requests                                                        | ✅                          |
| close               | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| convertkit          | HTTP                        | requests                                                        | ✅                          |
| convex              | HTTP                        | requests                                                        | ✅                          |
| copper              | HTTP                        | requests                                                        | ✅                          |
| coupa               | HTTP                        | requests                                                        | ✅                          |
| crunchbase          | HTTP                        | requests                                                        | ✅                          |
| culture_amp         | HTTP                        | requests                                                        | ✅                          |
| customer_io         | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (App API) / ➖ (webhook) |
| datadog             | HTTP                        | requests                                                        | ✅                          |
| deel                | HTTP                        | requests                                                        | ✅                          |
| delighted           | HTTP                        | requests                                                        | ✅                          |
| dixa                | HTTP                        | requests                                                        | ✅                          |
| docuseal            | HTTP                        | requests                                                        | ✅                          |
| doit                | HTTP                        | requests                                                        | ✅                          |
| drip                | HTTP                        | requests                                                        | ✅                          |
| e_conomic           | HTTP                        | requests                                                        | ✅                          |
| easypost            | HTTP                        | requests                                                        | ✅                          |
| easypromos          | HTTP                        | requests                                                        | ✅                          |
| freshdesk           | HTTP                        | requests                                                        | ✅                          |
| freshsales          | HTTP                        | requests                                                        | ✅                          |
| elasticemail        | HTTP                        | requests                                                        | ✅                          |
| elasticsearch       | HTTP                        | requests                                                        | ✅                          |
| emailoctopus        | HTTP                        | requests                                                        | ✅                          |
| eventbrite          | HTTP                        | requests                                                        | ✅                          |
| everhour            | HTTP                        | requests                                                        | ✅                          |
| factorial           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| fillout             | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| financial_modelling | HTTP                        | requests                                                        | ✅                          |
| finnhub             | HTTP                        | requests                                                        | ✅                          |
| finnworlds          | HTTP                        | requests                                                        | ✅                          |
| fleetio             | HTTP                        | requests                                                        | ✅                          |
| front               | HTTP                        | requests                                                        | ✅                          |
| fullstory           | HTTP                        | requests                                                        | ✅                          |
| github              | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| giphy               | HTTP                        | requests                                                        | ✅                          |
| gitlab              | HTTP                        | requests                                                        | ✅                          |
| gladly              | HTTP                        | requests                                                        | ✅                          |
| gocardless          | HTTP                        | requests                                                        | ✅                          |
| gong                | HTTP                        | requests                                                        | ✅                          |
| google_ads          | gRPC                        | google-ads (googleads.client)                                   | ✅                          |
| google_analytics    | HTTP                        | requests (`AuthorizedSession` + `TrackedHTTPAdapter`)           | ✅                          |
| google_sheets       | HTTP (vendor SDK)           | gspread                                                         | ✅                          |
| granola             | HTTP                        | requests                                                        | ✅                          |
| gorgias             | HTTP                        | requests                                                        | ✅                          |
| greenhouse          | HTTP                        | requests                                                        | ✅                          |
| guru                | HTTP                        | requests                                                        | ✅                          |
| hibob               | HTTP                        | requests                                                        | ✅                          |
| hubspot             | HTTP                        | requests                                                        | ✅                          |
| incident_io         | HTTP                        | requests                                                        | ✅                          |
| intercom            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| iterable            | HTTP                        | requests                                                        | ✅                          |
| jira                | HTTP                        | requests                                                        | ✅                          |
| jotform             | HTTP                        | requests                                                        | ✅                          |
| klaviyo             | HTTP                        | requests                                                        | ✅                          |
| lago                | HTTP                        | requests                                                        | ✅                          |
| launchdarkly        | HTTP                        | requests                                                        | ✅                          |
| kustomer            | HTTP                        | requests                                                        | ✅                          |
| lattice             | HTTP                        | requests                                                        | ✅                          |
| lemlist             | HTTP                        | requests                                                        | ✅                          |
| lightspeed_retail   | HTTP                        | requests                                                        | ✅                          |
| linear              | HTTP                        | requests                                                        | ✅                          |
| lever               | HTTP                        | requests                                                        | ✅                          |
| linkedin_ads        | HTTP (vendor SDK, RESTli)   | linkedin-api (RestliClient)                                     | ⚠️                          |
| lob                 | HTTP                        | requests                                                        | ✅                          |
| mailchimp           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| mailerlite          | HTTP                        | requests                                                        | ✅                          |
| mailersend          | HTTP                        | requests                                                        | ✅                          |
| mailgun             | HTTP                        | requests                                                        | ✅                          |
| mailjet             | HTTP                        | requests                                                        | ✅                          |
| matomo              | HTTP                        | requests                                                        | ✅                          |
| meta_ads            | HTTP                        | requests                                                        | ✅                          |
| metabase            | HTTP                        | requests                                                        | ✅                          |
| mixpanel            | HTTP                        | requests                                                        | ✅                          |
| mollie              | HTTP                        | requests                                                        | ✅                          |
| monday              | HTTP (GraphQL)              | requests                                                        | ✅                          |
| mongodb             | DB protocol                 | pymongo                                                         | ➖                          |
| mssql               | DB protocol                 | pyodbc / pymssql                                                | ➖                          |
| mux                 | HTTP                        | requests                                                        | ✅                          |
| mysql               | DB protocol                 | pymysql                                                         | ➖                          |
| okta                | HTTP                        | requests                                                        | ✅                          |
| notion              | HTTP                        | requests                                                        | ✅                          |
| omnisend            | HTTP                        | requests                                                        | ✅                          |
| orb                 | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| openweather         | HTTP                        | requests                                                        | ✅                          |
| ortto               | HTTP                        | requests                                                        | ✅                          |
| oura                | HTTP                        | requests                                                        | ✅                          |
| outbrain            | HTTP                        | requests                                                        | ✅                          |
| paddle              | HTTP                        | requests                                                        | ✅                          |
| optimizely          | HTTP                        | requests                                                        | ✅                          |
| pagerduty           | HTTP                        | requests                                                        | ✅                          |
| pandadoc            | HTTP                        | requests                                                        | ✅                          |
| paystack            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| pendo               | HTTP                        | requests                                                        | ✅                          |
| personio            | HTTP                        | requests                                                        | ✅                          |
| pingdom             | HTTP                        | requests                                                        | ✅                          |
| pinterest_ads       | HTTP                        | requests                                                        | ✅                          |
| pipedrive           | HTTP                        | requests                                                        | ✅                          |
| plain               | HTTP                        | requests                                                        | ✅                          |
| plausible           | HTTP                        | requests                                                        | ✅                          |
| polar               | HTTP                        | requests                                                        | ✅                          |
| plaid               | HTTP                        | requests                                                        | ✅                          |
| postgres            | DB protocol                 | psycopg                                                         | ➖                          |
| postmark            | HTTP                        | requests                                                        | ✅                          |
| productboard        | HTTP                        | requests                                                        | ✅                          |
| pylon               | HTTP                        | requests                                                        | ✅                          |
| recurly             | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| ramp                | HTTP                        | requests                                                        | ✅                          |
| recharge            | HTTP                        | requests                                                        | ✅                          |
| reddit_ads          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| redshift            | DB protocol                 | psycopg (Postgres-compatible)                                   | ➖                          |
| resend              | HTTP                        | requests                                                        | ✅                          |
| revenuecat          | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| rippling            | HTTP                        | requests                                                        | ✅                          |
| rollbar             | HTTP                        | requests                                                        | ✅                          |
| rootly              | HTTP                        | requests                                                        | ✅                          |
| salesforce          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| salesloft           | HTTP                        | requests                                                        | ✅                          |
| segment             | HTTP                        | requests                                                        | ✅                          |
| sendgrid            | HTTP                        | requests                                                        | ✅                          |
| sentry              | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| servicenow          | HTTP                        | requests                                                        | ✅                          |
| shipstation         | HTTP                        | requests                                                        | ✅                          |
| shopify             | HTTP                        | requests                                                        | ✅                          |
| shortcut            | HTTP                        | requests                                                        | ✅                          |
| slack               | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| smartsheet          | HTTP                        | requests                                                        | ✅                          |
| snapchat_ads        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| snowflake           | DB protocol                 | snowflake-connector-python                                      | ➖                          |
| sparkpost           | HTTP                        | requests                                                        | ✅                          |
| square              | HTTP                        | requests                                                        | ✅                          |
| squarespace         | HTTP                        | requests                                                        | ✅                          |
| statuspage          | HTTP                        | requests                                                        | ✅                          |
| stripe              | HTTP (vendor SDK) + Webhook | stripe (StripeClient + RequestsClient) + `WebhookSourceManager` | ✅ (pull) / ➖ (webhook)    |
| supabase            | DB protocol                 | psycopg (delegates to PostgresSource)                           | ➖                          |
| surveymonkey        | HTTP                        | requests                                                        | ✅                          |
| taboola             | HTTP                        | requests                                                        | ✅                          |
| teamwork            | HTTP                        | requests                                                        | ✅                          |
| temporalio          | gRPC (vendor SDK)           | temporalio (`Client`, Rust core via `temporalio.bridge`)        | ⚠️                          |
| thinkific           | HTTP                        | requests                                                        | ✅                          |
| tiktok_ads          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| tmdb                | HTTP                        | requests                                                        | ✅                          |
| todoist             | HTTP                        | requests                                                        | ✅                          |
| trello              | HTTP                        | requests                                                        | ✅                          |
| twilio              | HTTP                        | requests                                                        | ✅                          |
| typeform            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| vercel              | HTTP                        | requests                                                        | ✅                          |
| vitally             | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| webflow             | HTTP                        | requests                                                        | ✅                          |
| woocommerce         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wordpress           | HTTP                        | requests                                                        | ✅                          |
| workable            | HTTP                        | requests                                                        | ✅                          |
| workos              | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wrike               | HTTP                        | requests                                                        | ✅                          |
| zendesk             | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| zendesk_sell        | HTTP                        | requests                                                        | ✅                          |
| zoom                | HTTP                        | requests                                                        | ✅                          |
| zuora               | HTTP                        | requests                                                        | ✅                          |

### Notes on partially-tracked sources

- **bing_ads** uses Microsoft's `bingads` Python SDK, which builds its own HTTP transport via `suds-py3` for
  the SOAP API and a separate Reporting client. The SDK does not expose a session or HTTP-client injection
  hook today. Outbound traffic from this source bypasses the tracked transport.
- **linkedin_ads** uses `linkedin-api`'s `RestliClient`, which constructs its own internal `requests.Session`.
  We don't yet have a session-injection seam on it, so outbound calls bypass the tracked transport. (The file
  imports `requests` only for exception types — those references are expected and don't need a pragma.)
- **temporalio** talks gRPC, but the Python `temporalio` SDK runs its entire gRPC stack in a Rust core
  (`temporalio.bridge`, a PyO3 module) — service RPCs dispatch through `ServiceClient._rpc_call` into the
  bridge, so there is no Python `grpc.Channel` or client-interceptor seam for the tracked gRPC transport to
  wrap. (`Client.connect(interceptors=...)` accepts high-level `temporalio.client.Interceptor`s, a different
  abstraction that wouldn't feed the gRPC observer/metrics.) Outbound traffic bypasses the tracked transport.
- **bigquery** uses two transports: the metadata/management traffic via the BigQuery REST API is HTTP,
  tracked via `AuthorizedSession` + a mounted `TrackedHTTPAdapter`; the Storage Read API uses gRPC,
  tracked via `BigQueryReadGrpcTransport(channel=make_tracked_channel(...))` so `create_read_session` and
  `read_rows` ride the tracked gRPC interceptors.
- **google_ads** is pure gRPC. Every `GoogleAdsClient.get_service(...)` call passes
  `interceptors=tracked_interceptors(host)` so its unary calls (`search`, `search_google_ads_fields`) are
  logged, metered, and eligible for sample capture.

---

## Scaffolded sources

These are registered in `__init__.py` with `unreleasedSource=True` and a stub `source.py`. They have no
sync logic yet — picking up any of them means following the [implementing-warehouse-sources skill](/.agents/skills/implementing-warehouse-sources/SKILL.md).

One source per line (kept alphabetical) so adding or removing a source only touches its own line and
doesn't conflict with concurrent PRs.

- active_campaign
- acuity_scheduling
- adapty
- adjust
- adobe_analytics
- adobe_commerce
- adp_workforce_now
- adyen
- agilecrm
- aha
- ahrefs
- airbyte
- akeneo
- alpaca_broker_api
- alpha_vantage
- amazon_ads
- amazon_cloudwatch
- amazon_eventbridge
- amazon_kinesis
- amazon_s3
- amazon_selling_partner
- amazon_sns
- amazon_sqs
- appcues
- appfigures
- appfollow
- apple_search_ads
- appstack
- apptivo
- assemblyai
- auth0
- awin
- aws_cloudtrail
- azure_blob
- azure_table_storage
- babelforce
- basecamp
- bigcommerce
- bitly
- bluetally
- boldsign
- box
- braintrust
- branch
- breezy_hr
- bunny
- buzzsprout
- cal_com
- callrail
- campaign_manager_360
- capsule_crm
- captain_data
- care_quality_commission
- cart_com
- castor_edc
- chameleon
- chargify
- chatwoot
- chift
- chorus
- churnkey
- cin7
- cisco_meraki
- clarifai
- clazar
- clockodo
- cloudbeds
- coassemble
- cockroachdb
- codefresh
- concord
- configcat
- constant_contact
- copper
- cosmosdb
- couchbase
- criteo
- curve
- customerly
- databricks
- datascope
- datorama
- db2
- dbt
- deputy
- devin_ai
- ding_connect
- display_video_360
- dockerhub
- docusign
- dolibarr
- dremio
- dropbox
- dropbox_sign
- dwolla
- dynamics365
- dynamodb
- ebay
- eloqua
- employment_hero
- encharge
- eventee
- eventzilla
- exchange_rates_api
- expensify
- ezofficeinventory
- facebook_pages
- fastbill
- fastly
- fauna
- feishu
- finage
- firebase
- firebolt
- firehydrant
- flexmail
- flexport
- float_app
- flowlu
- formbricks
- freeagent
- freightview
- freshbooks
- freshcaller
- freshchat
- freshservice
- fulcrum
- gainsight_px
- gitbook
- glassfrog
- gmail
- gnews
- goldcast
- gologin
- google_ad_manager
- google_analytics
- google_calendar
- google_classroom
- google_cloud_storage
- google_directory
- google_drive
- google_forms
- google_pagespeed_insights
- google_tasks
- google_webfonts
- google_workspace_admin_reports
- grafana
- greythr
- gridly
- guardian
- gusto
- harness
- heap
- height
- hellobaton
- helpscout
- hibob
- high_level
- hightouch
- hoorayhr
- hubplanner
- hugging_face
- humanitix
- huntr
- ikas
- illumina_basespace
- imagga
- incident_io
- inflowinventory
- infor_nexus
- insightful
- insightly
- instagram
- instatus
- interzoid
- intruder
- invoiced
- invoiceninja
- ip2whois
- jamf_pro
- jobber
- jobnimbus
- judgeme_reviews
- justcall
- justsift
- k6_cloud
- kafka
- katana
- keka
- kisi
- kissmetrics
- klarna
- klaus
- knock
- kyve
- leadfeeder
- leexi
- lemon_squeezy
- less_annoying_crm
- lever
- liana
- lightfield
- linkedin_pages
- linkrunner
- linnworks
- lokalise
- looker
- luma
- mailosaur
- mailtrap
- mantle
- marketo
- marketstack
- mendeley
- mention
- mercado_ads
- merge
- metricool
- metronome
- microsoft_dataverse
- microsoft_entra_id
- microsoft_lists
- microsoft_teams
- miro
- missive
- mixmax
- mode
- my_hours
- n8n
- nasa
- navan
- nebius_ai
- neon
- netsuite
- new_relic
- new_york_times
- news_api
- newsdata
- nexiopay
- ninjaone_rmm
- nocrm
- northpass_lms
- nutshell
- nylas
- oncehub
- onedrive
- onehundredms
- onepagecrm
- onesignal
- onfleet
- open_data_dc
- open_exchange_rates
- openaq
- openfda
- opinion_stage
- opsgenie
- opuswatch
- oracle
- oracle_ebs
- oracle_fusion
- orbit
- outlook
- outreach
- oveit
- pabbly_subscriptions_billing
- pagerduty
- paperform
- papersign
- pardot
- partnerize
- partnerstack
- payfit
- paylocity
- paypal
- pendo
- pennylane
- perigon
- perk
- persistiq
- persona
- pexels
- phyllo
- picqer
- pipeliner
- pivotal_tracker
- piwik
- planetscale
- planhat
- pocket
- polygon
- poplar
- prestashop
- pretix
- primetric
- printify
- productive
- pypi
- qonto
- qualaroo
- qualtrics
- quickbooks
- railz
- razorpay
- rb2b
- rd_station_marketing
- recreation
- recruitee
- reddit
- referralhero
- rentcast
- repairshopr
- reply_io
- retail_express
- retently
- revolut_merchant
- ringcentral
- rki_covid
- rocket_chat
- rocketlane
- rss
- ruddr
- safetyculture
- sage_hr
- sage_intacct
- sailthru
- salesflare
- salesforce_marketing_cloud
- sanity
- sap_concur
- sap_erp
- sap_fieldglass
- sap_hana
- sap_successfactors
- savvycal
- search_ads_360
- secoda
- sendowl
- sendpulse
- senseforce
- serpstat
- sevenshifts
- sftp
- sharepoint
- sharetribe
- shippo
- shopwired
- shortio
- shutterstock
- sigma_computing
- signnow
- simfin
- simplecast
- simplesat
- smaily
- smartengage
- smartreach
- smartwaiver
- solarwinds_service_desk
- sonar_cloud
- split_io
- spotify_ads
- spotlercrm
- statsig
- stigg
- stockdata
- strava
- streamelements
- streamlabs
- superwall
- surveymonkey
- surveysparrow
- survicate
- svix
- systeme
- tavus
- tawk_to
- teamtailor
- tempo
- testrail
- thinkific_courses
- thrive_learning
- ticketmaster
- tickettailor
- ticktick
- tile38
- timely
- tinyemail
- toggl
- track_pms
- tremendous
- trustpilot
- tvmaze
- twelve_data
- twitter
- twitter_ads
- tyntec_sms
- ubidots
- unleash
- uppromote
- uptick
- us_census
- uservoice
- vantage
- veeqo
- visma_economic
- vwo
- waiteraid
- wasabi
- watchmode
- when_i_work
- wikipedia_pageviews
- workday
- workflowmax
- workramp
- wufoo
- xero
- xsolla
- yahoo_finance
- yandex_metrica
- ynab
- yotpo
- younium
- yousign
- youtube_analytics
- youtube_data
- zapier_supported_storage
- zapsign
- zendesk_sunshine
- zenefits
- zenloop
- zoho_analytics
- zoho_bigin
- zoho_billing
- zoho_books
- zoho_campaign
- zoho_crm
- zoho_desk
- zoho_expense
- zoho_inventory
- zoho_invoice
- zonka_feedback
- zoominfo

---

## When to update this file

Update SOURCES.md whenever you:

- **Add a new source** (move it from the scaffolded list into the implemented table once it actually syncs).
- **Implement an existing scaffolded source** (move it into the implemented table; record the comm method
  and tracked-transport state).
- **Migrate a vendor SDK** to use `make_tracked_session()` (flip the source from ⚠️ to ✅).
- **Switch a source's protocol** (e.g. swap a REST client for a gRPC SDK, or add webhook support
  alongside the pull API).

Two semgrep rules enforce the tracked transports inside `sources/`:

- [`data-imports-http-transport`](/.semgrep/rules/data-imports-http-transport.yaml) bans direct
  `requests.<verb>` / `requests.Session()` / `httpx.*` — route through `make_tracked_session()`.
- [`data-imports-grpc-transport`](/.semgrep/rules/data-imports-grpc-transport.yaml) bans raw
  `grpc.*_channel(...)` and direct `BigQueryReadClient(...)` / `GoogleAdsClient(...)` construction —
  route through `make_tracked_channel(...)` (for `channel=`/`transport=` SDKs) or
  `tracked_interceptors(host)` (for `interceptors=` SDKs).

Vendor SDKs that genuinely cannot be intercepted should both:

1. Carry a `# nosemgrep: data-imports-...-transport-...` pragma at the call site, with a one-line reason.
2. Be listed here under "Notes on partially-tracked sources" with the `⚠️ Vendor SDK` row state.
