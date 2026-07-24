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

| Source                           | Comm method                 | Primary library                                                 | Tracked transport           |
| -------------------------------- | --------------------------- | --------------------------------------------------------------- | --------------------------- |
| adroll                           | HTTP                        | requests                                                        | ✅                          |
| agilecrm                         | HTTP                        | requests                                                        | ✅                          |
| aha                              | HTTP                        | requests                                                        | ✅                          |
| airbrake                         | HTTP                        | requests                                                        | ✅                          |
| aircall                          | HTTP                        | requests                                                        | ✅                          |
| airops                           | HTTP                        | requests                                                        | ✅                          |
| airtable                         | HTTP                        | requests                                                        | ✅                          |
| aiven                            | HTTP                        | requests                                                        | ✅                          |
| algolia                          | HTTP                        | requests                                                        | ✅                          |
| alguna                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| alpha_vantage                    | HTTP                        | requests                                                        | ✅                          |
| amazon_ads                       | HTTP                        | requests                                                        | ✅                          |
| amplitude                        | HTTP                        | requests                                                        | ✅                          |
| anthropic                        | HTTP                        | requests                                                        | ✅                          |
| apify_dataset                    | HTTP                        | requests                                                        | ✅                          |
| apollo                           | HTTP                        | requests                                                        | ✅                          |
| appdynamics                      | HTTP                        | requests                                                        | ✅                          |
| appfigures                       | HTTP                        | requests                                                        | ✅                          |
| appfollow                        | HTTP                        | requests                                                        | ✅                          |
| appsflyer                        | HTTP (CSV reports)          | requests                                                        | ✅                          |
| appsignal                        | HTTP (REST + GraphQL)       | requests                                                        | ✅                          |
| appstack                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| argocd                           | HTTP                        | requests                                                        | ✅                          |
| asana                            | HTTP                        | requests                                                        | ✅                          |
| ashby                            | HTTP                        | requests                                                        | ✅                          |
| asknicely                        | HTTP                        | requests                                                        | ✅                          |
| assemblyai                       | HTTP                        | requests                                                        | ✅                          |
| attentive                        | HTTP (webhook-first)        | requests (webhook management)                                   | ✅                          |
| attio                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| automox                          | HTTP                        | requests                                                        | ✅                          |
| autumn                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| aviationstack                    | HTTP                        | requests                                                        | ✅                          |
| aviator                          | HTTP                        | requests                                                        | ✅                          |
| awin                             | HTTP                        | requests                                                        | ✅                          |
| azure_devops                     | HTTP                        | requests                                                        | ✅                          |
| babelforce                       | HTTP                        | requests                                                        | ✅                          |
| bamboohr                         | HTTP                        | requests                                                        | ✅                          |
| baserow                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| baseten                          | HTTP                        | requests                                                        | ✅                          |
| beamer                           | HTTP                        | requests                                                        | ✅                          |
| better_stack                     | HTTP                        | requests                                                        | ✅                          |
| bettermode                       | HTTP (GraphQL)              | requests                                                        | ✅                          |
| bigmailer                        | HTTP                        | requests                                                        | ✅                          |
| bigquery                         | HTTP + gRPC                 | google-cloud-bigquery + bigquery-storage                        | ✅ (HTTP + gRPC)            |
| bing_ads                         | HTTP (vendor SDK, SOAP)     | bingads SDK                                                     | ⚠️                          |
| bitbucket                        | HTTP                        | requests                                                        | ✅                          |
| bitrise                          | HTTP                        | requests                                                        | ✅                          |
| bland_ai                         | HTTP                        | requests                                                        | ✅                          |
| blogger                          | HTTP                        | requests                                                        | ✅                          |
| bluetally                        | HTTP                        | requests                                                        | ✅                          |
| boldsign                         | HTTP                        | requests                                                        | ✅                          |
| braintree                        | HTTP (GraphQL)              | requests                                                        | ✅                          |
| braze                            | HTTP                        | requests                                                        | ✅                          |
| breezometer                      | HTTP                        | requests                                                        | ✅                          |
| brevo                            | HTTP                        | requests                                                        | ✅                          |
| brex                             | HTTP                        | requests                                                        | ✅                          |
| browser_use                      | HTTP                        | requests                                                        | ✅                          |
| browserbase                      | HTTP                        | requests                                                        | ✅                          |
| bugsnag                          | HTTP                        | requests                                                        | ✅                          |
| buildbetter                      | HTTP                        | requests                                                        | ✅                          |
| buildkite                        | HTTP                        | requests                                                        | ✅                          |
| bunny                            | HTTP                        | requests                                                        | ✅                          |
| buzzsprout                       | HTTP                        | requests                                                        | ✅                          |
| cal_com                          | HTTP                        | requests                                                        | ✅                          |
| calendly                         | HTTP                        | requests                                                        | ✅                          |
| callrail                         | HTTP                        | requests                                                        | ✅                          |
| campaign_monitor                 | HTTP                        | requests                                                        | ✅                          |
| campayn                          | HTTP                        | requests                                                        | ✅                          |
| campfire                         | HTTP                        | requests                                                        | ✅                          |
| canny                            | HTTP                        | requests                                                        | ✅                          |
| capsule_crm                      | HTTP                        | requests                                                        | ✅                          |
| care_quality_commission          | HTTP                        | requests                                                        | ✅                          |
| chameleon                        | HTTP                        | requests                                                        | ✅                          |
| chargebee                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| chargedesk                       | HTTP                        | requests                                                        | ✅                          |
| chargify                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| charthop                         | HTTP                        | requests                                                        | ✅                          |
| chatwoot                         | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| checkmarx                        | HTTP                        | requests                                                        | ✅                          |
| checkout_com                     | HTTP                        | requests                                                        | ✅                          |
| churnkey                         | HTTP                        | requests                                                        | ✅                          |
| coassemble                       | HTTP                        | requests                                                        | ✅                          |
| coda                             | HTTP                        | requests                                                        | ✅                          |
| codacy                           | HTTP                        | requests                                                        | ✅                          |
| codecov                          | HTTP                        | requests                                                        | ✅                          |
| codefresh                        | HTTP                        | requests                                                        | ✅                          |
| cody                             | HTTP (CSV reports)          | requests                                                        | ✅                          |
| cohere                           | HTTP                        | requests                                                        | ✅                          |
| coin_api                         | HTTP                        | requests                                                        | ✅                          |
| coingecko                        | HTTP                        | requests                                                        | ✅                          |
| coinmarketcap                    | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| commercetools                    | HTTP                        | requests                                                        | ✅                          |
| concord                          | HTTP                        | requests                                                        | ✅                          |
| configcat                        | HTTP                        | requests                                                        | ✅                          |
| confluence                       | HTTP                        | requests                                                        | ✅                          |
| confluent_cloud                  | HTTP                        | requests                                                        | ✅                          |
| chartmogul                       | HTTP                        | requests                                                        | ✅                          |
| circleci                         | HTTP                        | requests                                                        | ✅                          |
| circleci_insights                | HTTP                        | requests                                                        | ✅                          |
| cimis                            | HTTP                        | requests                                                        | ✅                          |
| cisco_duo                        | HTTP                        | requests (hand-rolled HMAC-SHA1 request signing)                | ✅                          |
| cloudflare                       | HTTP                        | requests                                                        | ✅                          |
| clari                            | HTTP                        | requests                                                        | ✅                          |
| clerk                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| clickhouse                       | DB protocol (HTTP-based)    | clickhouse-connect / clickhouse-driver                          | ➖                          |
| clickhouse_cloud                 | HTTP                        | requests                                                        | ✅                          |
| clickup                          | HTTP                        | requests                                                        | ✅                          |
| clockify                         | HTTP                        | requests                                                        | ✅                          |
| clockodo                         | HTTP                        | requests                                                        | ✅                          |
| close                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| cloudbeds                        | HTTP                        | requests                                                        | ✅                          |
| convertkit                       | HTTP                        | requests                                                        | ✅                          |
| convex                           | HTTP                        | requests                                                        | ✅                          |
| copper                           | HTTP                        | requests                                                        | ✅                          |
| coralogix                        | HTTP                        | requests                                                        | ✅                          |
| coupa                            | HTTP                        | requests                                                        | ✅                          |
| coveralls                        | HTTP                        | requests                                                        | ✅                          |
| crates_io                        | HTTP                        | requests                                                        | ✅                          |
| cronitor                         | HTTP                        | requests                                                        | ✅                          |
| crunchbase                       | HTTP                        | requests                                                        | ✅                          |
| culture_amp                      | HTTP                        | requests                                                        | ✅                          |
| cursor                           | HTTP                        | requests                                                        | ✅                          |
| customer_io                      | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (App API) / ➖ (webhook) |
| customerly                       | HTTP                        | requests                                                        | ✅                          |
| dagster_cloud                    | HTTP (GraphQL)              | requests                                                        | ✅                          |
| databricks                       | DB protocol                 | databricks-sql-connector                                        | ➖                          |
| datadog                          | HTTP                        | requests                                                        | ✅                          |
| dataforseo                       | HTTP                        | requests                                                        | ✅                          |
| datahub                          | HTTP                        | requests                                                        | ✅                          |
| dbt                              | HTTP                        | requests                                                        | ✅                          |
| decagon                          | HTTP                        | requests                                                        | ✅                          |
| deel                             | HTTP                        | requests                                                        | ✅                          |
| deepgram                         | HTTP                        | requests                                                        | ✅                          |
| deepsource                       | HTTP (GraphQL)              | requests                                                        | ✅                          |
| deno_deploy                      | HTTP                        | requests                                                        | ✅                          |
| devin_ai                         | HTTP                        | requests                                                        | ✅                          |
| ding_connect                     | HTTP                        | requests                                                        | ✅                          |
| digitalocean                     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| dixa                             | HTTP                        | requests                                                        | ✅                          |
| dockerhub                        | HTTP                        | requests                                                        | ✅                          |
| docuseal                         | HTTP                        | requests                                                        | ✅                          |
| doit                             | HTTP                        | requests                                                        | ✅                          |
| doppler                          | HTTP                        | requests                                                        | ✅                          |
| drata                            | HTTP                        | requests                                                        | ✅                          |
| dropbox_sign                     | HTTP                        | requests                                                        | ✅                          |
| drip                             | HTTP                        | requests                                                        | ✅                          |
| dub                              | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| dynatrace                        | HTTP                        | requests                                                        | ✅                          |
| e2b                              | HTTP                        | requests                                                        | ✅                          |
| e_conomic                        | HTTP                        | requests                                                        | ✅                          |
| easypost                         | HTTP                        | requests                                                        | ✅                          |
| easypromos                       | HTTP                        | requests                                                        | ✅                          |
| elevenlabs                       | HTTP                        | requests                                                        | ✅                          |
| freshcaller                      | HTTP                        | requests                                                        | ✅                          |
| freshchat                        | HTTP                        | requests                                                        | ✅                          |
| freshdesk                        | HTTP                        | requests                                                        | ✅                          |
| freshsales                       | HTTP                        | requests                                                        | ✅                          |
| freshservice                     | HTTP                        | requests                                                        | ✅                          |
| elasticemail                     | HTTP                        | requests                                                        | ✅                          |
| elasticsearch                    | HTTP                        | requests                                                        | ✅                          |
| emailoctopus                     | HTTP                        | requests                                                        | ✅                          |
| env0                             | HTTP                        | requests                                                        | ✅                          |
| eventbrite                       | HTTP                        | requests                                                        | ✅                          |
| eventee                          | HTTP                        | requests                                                        | ✅                          |
| eventzilla                       | HTTP                        | requests                                                        | ✅                          |
| everhour                         | HTTP                        | requests                                                        | ✅                          |
| exchange_rates_api               | HTTP                        | requests                                                        | ✅                          |
| ezofficeinventory                | HTTP                        | requests                                                        | ✅                          |
| factorial                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| fastly                           | HTTP                        | requests                                                        | ✅                          |
| featurebase                      | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| fillout                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| finage                           | HTTP                        | requests                                                        | ✅                          |
| financial_modelling              | HTTP                        | requests                                                        | ✅                          |
| finnhub                          | HTTP                        | requests                                                        | ✅                          |
| finnworlds                       | HTTP                        | requests                                                        | ✅                          |
| firecrawl                        | HTTP                        | requests                                                        | ✅                          |
| fireworks_ai                     | HTTP                        | requests                                                        | ✅                          |
| fleetio                          | HTTP                        | requests                                                        | ✅                          |
| firehydrant                      | HTTP                        | requests                                                        | ✅                          |
| flagsmith                        | HTTP                        | requests                                                        | ✅                          |
| flexmail                         | HTTP                        | requests                                                        | ✅                          |
| float_app                        | HTTP                        | requests                                                        | ✅                          |
| flowlu                           | HTTP                        | requests                                                        | ✅                          |
| fly_io                           | HTTP                        | requests                                                        | ✅                          |
| formbricks                       | HTTP                        | requests                                                        | ✅                          |
| frill                            | HTTP                        | requests                                                        | ✅                          |
| front                            | HTTP                        | requests                                                        | ✅                          |
| fulcrum                          | HTTP                        | requests                                                        | ✅                          |
| fullstory                        | HTTP                        | requests                                                        | ✅                          |
| gainsight_px                     | HTTP                        | requests                                                        | ✅                          |
| gerrit                           | HTTP                        | requests                                                        | ✅                          |
| gitbook                          | HTTP                        | requests                                                        | ✅                          |
| gitea                            | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| github                           | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| gitguardian                      | HTTP                        | requests                                                        | ✅                          |
| giphy                            | HTTP                        | requests                                                        | ✅                          |
| gitlab                           | HTTP                        | requests                                                        | ✅                          |
| gladly                           | HTTP                        | requests                                                        | ✅                          |
| glassfrog                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| gnews                            | HTTP                        | requests                                                        | ✅                          |
| gocardless                       | HTTP                        | requests                                                        | ✅                          |
| goldcast                         | HTTP                        | requests                                                        | ✅                          |
| gong                             | HTTP                        | requests                                                        | ✅                          |
| google_ads                       | gRPC                        | google-ads (googleads.client)                                   | ✅                          |
| google_analytics                 | HTTP                        | requests (`AuthorizedSession` + `TrackedHTTPAdapter`)           | ✅                          |
| google_pagespeed_insights        | HTTP                        | requests                                                        | ✅                          |
| google_sheets                    | HTTP (vendor SDK)           | gspread                                                         | ✅                          |
| google_webfonts                  | HTTP                        | requests                                                        | ✅                          |
| grafana                          | HTTP                        | requests                                                        | ✅                          |
| granola                          | HTTP                        | requests                                                        | ✅                          |
| gorgias                          | HTTP                        | requests                                                        | ✅                          |
| greenhouse                       | HTTP                        | requests                                                        | ✅                          |
| gridly                           | HTTP                        | requests                                                        | ✅                          |
| groq                             | HTTP                        | requests                                                        | ✅                          |
| guardian                         | HTTP                        | requests                                                        | ✅                          |
| guru                             | HTTP                        | requests                                                        | ✅                          |
| harvey                           | HTTP                        | requests                                                        | ✅                          |
| hatchet                          | HTTP                        | requests                                                        | ✅                          |
| healthchecks                     | HTTP                        | requests                                                        | ✅                          |
| height                           | HTTP                        | requests                                                        | ✅                          |
| helicone                         | HTTP                        | requests                                                        | ✅                          |
| hellobaton                       | HTTP                        | requests                                                        | ✅                          |
| heroku                           | HTTP                        | requests                                                        | ✅                          |
| hetzner                          | HTTP                        | requests                                                        | ✅                          |
| hex                              | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| hibob                            | HTTP                        | requests                                                        | ✅                          |
| hightouch                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| honeybadger                      | HTTP                        | requests                                                        | ✅                          |
| honeycomb                        | HTTP                        | requests                                                        | ✅                          |
| hoorayhr                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| humanitix                        | HTTP                        | requests                                                        | ✅                          |
| hubplanner                       | HTTP                        | requests                                                        | ✅                          |
| hubspot                          | HTTP                        | requests                                                        | ✅                          |
| hugging_face                     | HTTP                        | requests                                                        | ✅                          |
| huntr                            | HTTP                        | requests                                                        | ✅                          |
| hyperspell                       | HTTP                        | requests                                                        | ✅                          |
| imagga                           | HTTP                        | requests                                                        | ✅                          |
| incident_io                      | HTTP                        | requests                                                        | ✅                          |
| infisical                        | HTTP                        | requests                                                        | ✅                          |
| inflowinventory                  | HTTP                        | requests                                                        | ✅                          |
| inngest                          | HTTP                        | requests                                                        | ✅                          |
| insightly                        | HTTP                        | requests                                                        | ✅                          |
| instana                          | HTTP                        | requests                                                        | ✅                          |
| instantly                        | HTTP + Webhook              | requests + `rest_source.RESTClient` + `WebhookSourceManager`    | ✅ (pull) / ➖ (webhook)    |
| instatus                         | HTTP                        | requests                                                        | ✅                          |
| intercom                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| intruder                         | HTTP                        | requests                                                        | ✅                          |
| invoiced                         | HTTP                        | requests                                                        | ✅                          |
| invoiceninja                     | HTTP                        | requests                                                        | ✅                          |
| ip2whois                         | HTTP                        | requests                                                        | ✅                          |
| iterable                         | HTTP                        | requests                                                        | ✅                          |
| jamf_pro                         | HTTP                        | requests                                                        | ✅                          |
| jellyfish                        | HTTP                        | requests                                                        | ✅                          |
| jenkins                          | HTTP                        | requests                                                        | ✅                          |
| jfrog_artifactory                | HTTP                        | requests                                                        | ✅                          |
| jira                             | HTTP                        | requests                                                        | ✅                          |
| jobnimbus                        | HTTP                        | requests                                                        | ✅                          |
| jotform                          | HTTP                        | requests                                                        | ✅                          |
| judgeme_reviews                  | HTTP                        | requests                                                        | ✅                          |
| jumpcloud                        | HTTP                        | requests                                                        | ✅                          |
| justcall                         | HTTP                        | requests                                                        | ✅                          |
| justsift                         | HTTP                        | requests                                                        | ✅                          |
| k6_cloud                         | HTTP                        | requests                                                        | ✅                          |
| kandji                           | HTTP                        | requests (rest_source.RESTClient)                               | ✅                          |
| katana                           | HTTP                        | requests                                                        | ✅                          |
| kernel                           | HTTP                        | requests                                                        | ✅                          |
| klaus                            | HTTP                        | requests                                                        | ✅                          |
| klaviyo                          | HTTP                        | requests                                                        | ✅                          |
| knock                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| koyeb                            | HTTP                        | requests                                                        | ✅                          |
| kong_konnect                     | HTTP                        | requests                                                        | ✅                          |
| kubecost                         | HTTP                        | requests                                                        | ✅                          |
| lacework                         | HTTP                        | requests                                                        | ✅                          |
| lago                             | HTTP                        | requests                                                        | ✅                          |
| lambda_labs                      | HTTP                        | requests                                                        | ✅                          |
| langfuse                         | HTTP                        | requests                                                        | ✅                          |
| langsmith                        | HTTP                        | requests                                                        | ✅                          |
| launchdarkly                     | HTTP                        | requests                                                        | ✅                          |
| kustomer                         | HTTP                        | requests                                                        | ✅                          |
| lattice                          | HTTP                        | requests                                                        | ✅                          |
| leadfeeder                       | HTTP                        | requests                                                        | ✅                          |
| leexi                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| lemlist                          | HTTP                        | requests                                                        | ✅                          |
| lemon_squeezy                    | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| less_annoying_crm                | HTTP                        | requests                                                        | ✅                          |
| lightfield                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| lightspeed_retail                | HTTP                        | requests                                                        | ✅                          |
| linear                           | HTTP                        | requests                                                        | ✅                          |
| linearb                          | HTTP                        | requests                                                        | ✅                          |
| lever                            | HTTP                        | requests                                                        | ✅                          |
| lingo_dev                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| linkedin_ads                     | HTTP (vendor SDK, RESTli)   | linkedin-api (RestliClient)                                     | ⚠️                          |
| linkrunner                       | HTTP                        | requests                                                        | ✅                          |
| linode                           | HTTP                        | requests                                                        | ✅                          |
| llama_cloud                      | HTTP                        | requests                                                        | ✅                          |
| lob                              | HTTP                        | requests                                                        | ✅                          |
| logz_io                          | HTTP                        | requests                                                        | ✅                          |
| loops                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| luma                             | HTTP                        | requests                                                        | ✅                          |
| mailchimp                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| mem0                             | HTTP                        | requests                                                        | ✅                          |
| mailerlite                       | HTTP                        | requests                                                        | ✅                          |
| mailersend                       | HTTP                        | requests                                                        | ✅                          |
| mailgun                          | HTTP                        | requests                                                        | ✅                          |
| mailjet                          | HTTP                        | requests                                                        | ✅                          |
| mailosaur                        | HTTP                        | requests                                                        | ✅                          |
| mailtrap                         | HTTP                        | requests                                                        | ✅                          |
| marketstack                      | HTTP                        | requests                                                        | ✅                          |
| matomo                           | HTTP                        | requests                                                        | ✅                          |
| maxio                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| mention                          | HTTP                        | requests                                                        | ✅                          |
| mercury                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| meta_ads                         | HTTP                        | requests                                                        | ✅                          |
| metabase                         | HTTP                        | requests                                                        | ✅                          |
| metaplane                        | HTTP                        | requests                                                        | ✅                          |
| metorial                         | HTTP                        | requests                                                        | ✅                          |
| mistral_ai                       | HTTP                        | requests                                                        | ✅                          |
| mixmax                           | HTTP                        | requests                                                        | ✅                          |
| mixpanel                         | HTTP                        | requests                                                        | ✅                          |
| mollie                           | HTTP                        | requests                                                        | ✅                          |
| monday                           | HTTP (GraphQL)              | requests                                                        | ✅                          |
| mongodb                          | DB protocol                 | pymongo                                                         | ➖                          |
| monte_carlo                      | HTTP (GraphQL)              | requests                                                        | ✅                          |
| mssql                            | DB protocol                 | pyodbc / pymssql                                                | ➖                          |
| mux                              | HTTP                        | requests                                                        | ✅                          |
| my_hours                         | HTTP                        | requests                                                        | ✅                          |
| mysql                            | DB protocol                 | pymysql                                                         | ➖                          |
| n8n                              | HTTP                        | requests                                                        | ✅                          |
| nebius_ai                        | HTTP                        | requests                                                        | ✅                          |
| neon                             | DB protocol                 | psycopg (delegates to PostgresSource)                           | ➖                          |
| netlify                          | HTTP                        | requests                                                        | ✅                          |
| new_relic                        | HTTP (GraphQL/NerdGraph)    | requests                                                        | ✅                          |
| new_york_times                   | HTTP                        | requests                                                        | ✅                          |
| news_api                         | HTTP                        | requests                                                        | ✅                          |
| newsdata                         | HTTP                        | requests                                                        | ✅                          |
| okta                             | HTTP                        | requests                                                        | ✅                          |
| nocrm                            | HTTP                        | requests                                                        | ✅                          |
| northflank                       | HTTP                        | requests                                                        | ✅                          |
| northpass_lms                    | HTTP                        | requests                                                        | ✅                          |
| notion                           | HTTP                        | requests                                                        | ✅                          |
| nuget                            | HTTP                        | requests                                                        | ✅                          |
| omnisend                         | HTTP                        | requests                                                        | ✅                          |
| octopus_deploy                   | HTTP                        | requests                                                        | ✅                          |
| oncehub                          | HTTP                        | requests                                                        | ✅                          |
| onepagecrm                       | HTTP                        | requests                                                        | ✅                          |
| onepassword                      | HTTP (cursor pagination)    | requests                                                        | ✅                          |
| onfleet                          | HTTP (cursor pagination)    | requests                                                        | ✅                          |
| open_exchange_rates              | HTTP                        | requests                                                        | ✅                          |
| openai                           | HTTP                        | requests                                                        | ✅                          |
| openai_ads                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| opinion_stage                    | HTTP                        | requests                                                        | ✅                          |
| opuswatch                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| orb                              | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| orca_security                    | HTTP (POST query DSL)       | requests                                                        | ✅                          |
| openaq                           | HTTP                        | requests                                                        | ✅                          |
| openfda                          | HTTP                        | requests                                                        | ✅                          |
| openrouter                       | HTTP                        | requests                                                        | ✅                          |
| openweather                      | HTTP                        | requests                                                        | ✅                          |
| opsgenie                         | HTTP                        | requests                                                        | ✅                          |
| ortto                            | HTTP                        | requests                                                        | ✅                          |
| oura                             | HTTP                        | requests                                                        | ✅                          |
| outbrain                         | HTTP                        | requests                                                        | ✅                          |
| pabbly_subscriptions_billing     | HTTP                        | requests                                                        | ✅                          |
| packagist                        | HTTP                        | requests                                                        | ✅                          |
| paddle                           | HTTP                        | requests                                                        | ✅                          |
| optimizely                       | HTTP                        | requests                                                        | ✅                          |
| pagerduty                        | HTTP                        | requests                                                        | ✅                          |
| pandadoc                         | HTTP                        | requests                                                        | ✅                          |
| paperform                        | HTTP                        | requests                                                        | ✅                          |
| papersign                        | HTTP                        | requests                                                        | ✅                          |
| partnerize                       | HTTP                        | requests                                                        | ✅                          |
| partnerstack                     | HTTP                        | requests                                                        | ✅                          |
| payfit                           | HTTP                        | requests                                                        | ✅                          |
| paystack                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| pendo                            | HTTP                        | requests                                                        | ✅                          |
| perigon                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| persistiq                        | HTTP                        | requests                                                        | ✅                          |
| persona                          | HTTP                        | requests                                                        | ✅                          |
| personio                         | HTTP                        | requests                                                        | ✅                          |
| pexels                           | HTTP                        | requests                                                        | ✅                          |
| phyllo                           | HTTP                        | requests                                                        | ✅                          |
| picqer                           | HTTP                        | requests                                                        | ✅                          |
| pingdom                          | HTTP                        | requests                                                        | ✅                          |
| pinterest_ads                    | HTTP                        | requests                                                        | ✅                          |
| pipedrive                        | HTTP                        | requests                                                        | ✅                          |
| pipeliner                        | HTTP                        | requests                                                        | ✅                          |
| plain                            | HTTP                        | requests                                                        | ✅                          |
| planhat                          | HTTP                        | requests                                                        | ✅                          |
| platform_sh                      | HTTP                        | requests                                                        | ✅                          |
| plausible                        | HTTP                        | requests                                                        | ✅                          |
| plivo                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| plunk                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| polar                            | HTTP                        | requests                                                        | ✅                          |
| plaid                            | HTTP                        | requests                                                        | ✅                          |
| postgres                         | DB protocol                 | psycopg                                                         | ➖                          |
| postmark                         | HTTP                        | requests                                                        | ✅                          |
| prefect_cloud                    | HTTP                        | requests                                                        | ✅                          |
| pretix                           | HTTP                        | requests                                                        | ✅                          |
| printify                         | HTTP                        | requests                                                        | ✅                          |
| productboard                     | HTTP                        | requests                                                        | ✅                          |
| pulumi_cloud                     | HTTP                        | requests                                                        | ✅                          |
| pylon                            | HTTP                        | requests                                                        | ✅                          |
| pypi                             | HTTP                        | requests                                                        | ✅                          |
| qualaroo                         | HTTP                        | requests                                                        | ✅                          |
| qualys_vmdr                      | HTTP (XML responses)        | requests                                                        | ✅                          |
| railway                          | HTTP (GraphQL)              | requests                                                        | ✅                          |
| recurly                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| ramp                             | HTTP                        | requests                                                        | ✅                          |
| rapid7_insightvm                 | HTTP                        | requests                                                        | ✅                          |
| raygun                           | HTTP                        | requests                                                        | ✅                          |
| razorpay                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| recharge                         | HTTP                        | requests                                                        | ✅                          |
| recreation                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| recruitee                        | HTTP                        | requests                                                        | ✅                          |
| reddit_ads                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| redshift                         | DB protocol                 | psycopg (Postgres-compatible)                                   | ➖                          |
| render                           | HTTP                        | requests                                                        | ✅                          |
| rentcast                         | HTTP                        | requests                                                        | ✅                          |
| replicate                        | HTTP                        | requests                                                        | ✅                          |
| reply_io                         | HTTP                        | requests                                                        | ✅                          |
| resend                           | HTTP                        | requests                                                        | ✅                          |
| retently                         | HTTP                        | requests                                                        | ✅                          |
| revenuecat                       | HTTP + Webhook              | requests + `WebhookSourceManager`                               | ✅ (pull) / ➖ (webhook)    |
| rippling                         | HTTP                        | requests                                                        | ✅                          |
| rki_covid                        | HTTP                        | requests                                                        | ✅                          |
| roark                            | HTTP                        | requests                                                        | ✅                          |
| rocketlane                       | HTTP                        | requests                                                        | ✅                          |
| rollbar                          | HTTP                        | requests                                                        | ✅                          |
| rootly                           | HTTP                        | requests                                                        | ✅                          |
| rss                              | HTTP                        | requests                                                        | ✅                          |
| ruddr                            | HTTP                        | requests                                                        | ✅                          |
| runpod                           | HTTP                        | requests                                                        | ✅                          |
| safetyculture                    | HTTP                        | requests                                                        | ✅                          |
| sage_hr                          | HTTP                        | requests                                                        | ✅                          |
| salesforce                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| salesflare                       | HTTP                        | requests                                                        | ✅                          |
| salesloft                        | HTTP                        | requests                                                        | ✅                          |
| savvycal                         | HTTP                        | requests                                                        | ✅                          |
| scale_ai                         | HTTP                        | requests                                                        | ✅                          |
| scaleway                         | HTTP                        | requests                                                        | ✅                          |
| secoda                           | HTTP                        | requests                                                        | ✅                          |
| secureframe                      | HTTP                        | requests                                                        | ✅                          |
| segment                          | HTTP                        | requests                                                        | ✅                          |
| semgrep                          | HTTP                        | requests                                                        | ✅                          |
| sendgrid                         | HTTP                        | requests                                                        | ✅                          |
| sendowl                          | HTTP                        | requests                                                        | ✅                          |
| sentinelone                      | HTTP                        | requests                                                        | ✅                          |
| sentry                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| servicenow                       | HTTP                        | requests                                                        | ✅                          |
| shippo                           | HTTP                        | requests                                                        | ✅                          |
| shipstation                      | HTTP                        | requests                                                        | ✅                          |
| shopify                          | HTTP                        | requests                                                        | ✅                          |
| shopwired                        | HTTP                        | requests                                                        | ✅                          |
| shortcut                         | HTTP                        | requests                                                        | ✅                          |
| shortio                          | HTTP                        | requests                                                        | ✅                          |
| shutterstock                     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| signoz                           | HTTP                        | requests                                                        | ✅                          |
| simfin                           | HTTP                        | requests                                                        | ✅                          |
| simplecast                       | HTTP                        | requests                                                        | ✅                          |
| simplesat                        | HTTP                        | requests                                                        | ✅                          |
| skyvern                          | HTTP                        | requests                                                        | ✅                          |
| slack                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| smaily                           | HTTP                        | requests                                                        | ✅                          |
| smartengage                      | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| smartreach                       | HTTP                        | requests                                                        | ✅                          |
| smartsheet                       | HTTP                        | requests                                                        | ✅                          |
| smartwaiver                      | HTTP                        | requests                                                        | ✅                          |
| snapchat_ads                     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| snowflake                        | DB protocol                 | snowflake-connector-python                                      | ➖                          |
| snowplow                         | HTTP                        | requests                                                        | ✅                          |
| snyk                             | HTTP                        | requests                                                        | ✅                          |
| solarwinds_service_desk          | HTTP                        | requests                                                        | ✅                          |
| sonar_cloud                      | HTTP                        | requests                                                        | ✅                          |
| sonarqube                        | HTTP                        | requests                                                        | ✅                          |
| sonatype_nexus                   | HTTP                        | requests                                                        | ✅                          |
| sourcegraph                      | HTTP (GraphQL)              | requests                                                        | ✅                          |
| spacelift                        | HTTP (GraphQL)              | requests                                                        | ✅                          |
| sparkpost                        | HTTP                        | requests                                                        | ✅                          |
| split_io                         | HTTP                        | requests                                                        | ✅                          |
| spotlercrm                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| sprig                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| squadcast                        | HTTP                        | requests                                                        | ✅                          |
| square                           | HTTP                        | requests                                                        | ✅                          |
| squarespace                      | HTTP                        | requests                                                        | ✅                          |
| stack_overflow_for_teams         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| statuscake                       | HTTP                        | requests                                                        | ✅                          |
| statuspage                       | HTTP                        | requests                                                        | ✅                          |
| stigg                            | HTTP                        | requests                                                        | ✅                          |
| stockdata                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| streamelements                   | HTTP                        | requests                                                        | ✅                          |
| stripe                           | HTTP (vendor SDK) + Webhook | stripe (StripeClient + RequestsClient) + `WebhookSourceManager` | ✅ (pull) / ➖ (webhook)    |
| stytch                           | HTTP                        | requests                                                        | ✅                          |
| sumo_logic                       | HTTP                        | requests                                                        | ✅                          |
| supabase                         | DB protocol                 | psycopg (delegates to PostgresSource)                           | ➖                          |
| surveymonkey                     | HTTP                        | requests                                                        | ✅                          |
| surveysparrow                    | HTTP                        | requests                                                        | ✅                          |
| svix                             | HTTP                        | requests                                                        | ✅                          |
| swarmia                          | HTTP                        | requests                                                        | ✅                          |
| taboola                          | HTTP                        | requests                                                        | ✅                          |
| tailscale                        | HTTP                        | requests                                                        | ✅                          |
| tavus                            | HTTP                        | requests                                                        | ✅                          |
| tawk_to                          | HTTP                        | requests                                                        | ✅                          |
| teachable                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| teamcity                         | HTTP                        | requests                                                        | ✅                          |
| teamtailor                       | HTTP                        | requests                                                        | ✅                          |
| teamwork                         | HTTP                        | requests                                                        | ✅                          |
| tempo                            | HTTP                        | requests                                                        | ✅                          |
| temporalio                       | gRPC (vendor SDK)           | temporalio (`Client`, Rust core via `temporalio.bridge`)        | ⚠️                          |
| tenable_vulnerability_management | HTTP (async export flow)    | requests                                                        | ✅                          |
| terraform_cloud                  | HTTP                        | requests                                                        | ✅                          |
| testrail                         | HTTP                        | requests                                                        | ✅                          |
| thinkific                        | HTTP                        | requests                                                        | ✅                          |
| thinkific_courses                | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| tickettailor                     | HTTP                        | requests                                                        | ✅                          |
| tiktok_ads                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| tinyemail                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| tmdb                             | HTTP                        | requests                                                        | ✅                          |
| todoist                          | HTTP                        | requests                                                        | ✅                          |
| together_ai                      | HTTP                        | requests                                                        | ✅                          |
| torii                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| travis_ci                        | HTTP                        | requests                                                        | ✅                          |
| trello                           | HTTP                        | requests                                                        | ✅                          |
| tremendous                       | HTTP                        | requests                                                        | ✅                          |
| trigger_dev                      | HTTP                        | requests                                                        | ✅                          |
| tvmaze                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| twelve_data                      | HTTP                        | requests                                                        | ✅                          |
| twelve_labs                      | HTTP                        | requests                                                        | ✅                          |
| twilio                           | HTTP                        | requests                                                        | ✅                          |
| tyntec_sms                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| typeform                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| ubidots                          | HTTP                        | requests                                                        | ✅                          |
| unleash                          | HTTP                        | requests                                                        | ✅                          |
| unstructured                     | HTTP                        | requests                                                        | ✅                          |
| upstash                          | HTTP                        | requests                                                        | ✅                          |
| uppromote                        | HTTP + Webhook              | requests + `rest_source.RESTClient` + `WebhookSourceManager`    | ✅ (pull) / ➖ (webhook)    |
| uptimerobot                      | HTTP                        | requests                                                        | ✅                          |
| us_census                        | HTTP                        | requests                                                        | ✅                          |
| usersnap                         | HTTP                        | requests + PyJWT                                                | ✅                          |
| uservoice                        | HTTP                        | requests                                                        | ✅                          |
| vantage                          | HTTP                        | requests                                                        | ✅                          |
| vapi                             | HTTP                        | requests                                                        | ✅                          |
| vellum                           | HTTP                        | requests                                                        | ✅                          |
| veeqo                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| veracode                         | HTTP                        | requests (custom HMAC signing)                                  | ✅                          |
| vercel                           | HTTP                        | requests                                                        | ✅                          |
| vitally                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| vultr                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wasabi                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| watchmode                        | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| webflow                          | HTTP                        | requests                                                        | ✅                          |
| weights_and_biases               | HTTP (GraphQL)              | requests                                                        | ✅                          |
| wikipedia_pageviews              | HTTP                        | requests                                                        | ✅                          |
| windmill                         | HTTP                        | requests                                                        | ✅                          |
| woocommerce                      | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wordpress                        | HTTP                        | requests                                                        | ✅                          |
| workable                         | HTTP                        | requests                                                        | ✅                          |
| workos                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wrike                            | HTTP                        | requests                                                        | ✅                          |
| writesonic                       | HTTP                        | requests                                                        | ✅                          |
| wufoo                            | HTTP                        | requests                                                        | ✅                          |
| xmatters                         | HTTP                        | requests                                                        | ✅                          |
| yousign                          | HTTP + Webhook              | requests + `rest_source.RESTClient` + `WebhookSourceManager`    | ✅ (pull) / ➖ (webhook)    |
| zapier_supported_storage         | HTTP                        | requests                                                        | ✅                          |
| zapsign                          | HTTP + Webhook              | requests + `rest_source.RESTClient` + `WebhookSourceManager`    | ✅ (pull) / ➖ (webhook)    |
| zendesk                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| zendesk_sell                     | HTTP                        | requests                                                        | ✅                          |
| zendesk_sunshine                 | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| zenduty                          | HTTP                        | requests                                                        | ✅                          |
| zenloop                          | HTTP                        | requests                                                        | ✅                          |
| zep                              | HTTP                        | requests                                                        | ✅                          |
| zonka_feedback                   | HTTP                        | requests                                                        | ✅                          |
| zoom                             | HTTP                        | requests                                                        | ✅                          |
| zuora                            | HTTP                        | requests                                                        | ✅                          |

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

- [`data-imports-grpc-transport`](/.semgrep/rules/security/data-imports-grpc-transport.yaml)
- [`data-imports-http-transport`](/.semgrep/rules/security/data-imports-http-transport.yaml)
- \*\*Add
- \*\*Implement
- \*\*Migrate
- \*\*Switch
- ab_tasty
- ably
- abnormal_security
- acast
- acculynx
- actionstep
- active_campaign
- acuity_scheduling
- adapty
- adjust
- adobe_analytics
- adobe_commerce
- adp_workforce_now
- adyen
- aftership
- aha_ideas
- ahrefs
- aikido_security
- airbyte
- airops
- aiven
- akamai_reporting
- akeneo
- alation
- alegra
- allegro
- alpaca_broker_api
- amazon_ads
- amazon_cloudwatch
- amazon_eventbridge
- amazon_kinesis
- amazon_s3
- amazon_selling_partner
- amazon_sns
- amazon_sqs
- anodot_cost
- anomalo
- apaleo
- apitally
- app_store_connect
- appcues
- appdirect
- appfolio
- apple_search_ads
- apptivo
- appwrite
- arxiv
- asaas
- asknicely
- astronomer
- athenahealth
- atlan
- auth0
- autodesk_construction_cloud
- automox
- avalara
- aws_athena
- aws_batch
- aws_budgets
- aws_cloudformation
- aws_cloudtrail
- aws_compute_optimizer
- aws_config
- aws_connect
- aws_cost_and_usage_report
- aws_cost_anomaly_detection
- aws_cost_explorer
- aws_glue_data_catalog
- aws_guardduty
- aws_health
- aws_iam_access_analyzer
- aws_inspector
- aws_macie
- aws_organizations
- aws_rds_performance_insights
- aws_sagemaker
- aws_savings_plans
- aws_security_hub
- aws_ses
- aws_step_functions
- aws_support
- aws_systems_manager
- aws_trusted_advisor
- aws_waf
- aws_xray
- axiom
- azure_activity_log
- azure_advisor
- azure_api_management
- azure_application_insights
- azure_blob
- azure_cost_management
- azure_data_explorer
- azure_data_factory
- azure_log_analytics
- azure_monitor_alerts
- azure_monitor_metrics
- azure_openai_usage
- azure_policy_insights
- azure_reservations
- azure_resource_graph
- azure_resource_health
- azure_service_health
- azure_synapse
- azure_table_storage
- back_market
- backblaze
- basecamp
- beehiiv
- bigcommerce
- bigeye
- bill_com
- billomat
- bing_webmaster_tools
- bitly
- bitwarden
- blackbaud_raisers_edge_nxt
- blackboard_learn
- bling
- bloomerang
- bluesky
- bol_retailer
- boulevard
- box
- braintrust
- branch
- breezy_hr
- browse_ai
- buffer
- bugherd
- buildium
- buttondown
- buy_me_a_coffee
- cal_com
- calendarific
- calibre
- campaign_manager_360
- canvas_lms
- captain_data
- captivate
- cart_com
- cashfree
- cast_ai
- castor_edc
- catchpoint
- cdc_open_data
- census
- checkly
- chift
- chorus
- cin7
- circle_so
- cisco_meraki
- clarifai
- classy
- clazar
- cleartax
- clever
- clevertap
- cliniko
- clio
- clip
- cloudability
- cloudbeds
- cloudsmith
- cloudzero
- clover
- coassemble
- cockroachdb
- codacy
- codecov
- codemagic
- codescene
- collibra
- companycam
- conekta
- constant_contact
- conta_azul
- contentsquare
- copper
- cortex
- cosmosdb
- couchbase
- courier
- crisp
- criteo
- crossref
- crowdstrike_falcon
- cube_cloud
- curve
- d2l_brightspace
- datascope
- datorama
- dayforce
- db2
- debugbear
- deno_deploy
- deputy
- descope
- develocity
- dialpad
- discord
- discourse
- display_video_360
- docusign
- dodopayments
- dolibarr
- donorbox
- doorloop
- doppler
- dovetail
- drata
- drchrono
- dremio
- dropbox
- dubsado
- dwolla
- dynamics365
- dynamics_365_business_central
- dynamodb
- e2b
- ebay
- ecb_data_portal
- eloqua
- emarsys
- embrace
- employment_hero
- encharge
- entsoe
- eppo
- etsy
- eurostat
- expensify
- facebook_pages
- faire
- faros_ai
- fastbill
- fauna
- feishu
- fieldpulse
- fieldwire
- filevine
- finout
- fintoc
- firebase
- firebolt
- five9
- flagsmith
- flexera_cloud_cost
- flexmail
- flexport
- flowlu
- flutterwave
- fly_io
- formbricks
- fortnox
- fourthwall
- fred
- freeagent
- freightview
- freshbooks
- freshservice
- frontegg
- fulcrum
- fusionauth
- g2
- gcore
- gcp_apigee
- gcp_artifact_registry
- gcp_bigtable
- gcp_chronicle
- gcp_cloud_asset_inventory
- gcp_cloud_billing
- gcp_cloud_build
- gcp_cloud_deploy
- gcp_cloud_dns
- gcp_cloud_functions
- gcp_cloud_logging
- gcp_cloud_monitoring
- gcp_cloud_run
- gcp_cloud_spanner
- gcp_cloud_sql
- gcp_cloud_trace
- gcp_cloud_workflows
- gcp_compute_engine
- gcp_container_analysis
- gcp_dataflow
- gcp_dataplex
- gcp_dataproc
- gcp_error_reporting
- gcp_gke
- gcp_pubsub
- gcp_recaptcha_enterprise
- gcp_recommender
- gcp_security_command_center
- gdelt
- genesys_cloud
- gerrit
- getdx
- getstream
- ghost
- gitea
- givebutter
- gleif
- gmail
- gnews
- gojiberry
- goldcast
- gologin
- google_ad_manager
- google_analytics
- google_calendar
- google_chat
- google_classroom
- google_cloud_storage
- google_directory
- google_drive
- google_forms
- google_play_console
- google_tasks
- google_workspace_admin_reports
- greythr
- growthbook
- guesty
- gumloop
- gumroad
- gusto
- harness
- harness_ccm
- harness_sei
- harvest
- harvey
- healthie
- heap
- helpscout
- hetzner
- heygen
- hibob
- high_level
- hitpay
- hivebrite
- holded
- honeybadger
- honeycomb
- hostaway
- housecall_pro
- hubplanner
- humanitec
- humanitix
- ikas
- illumina_basespace
- imf_data
- impact
- imperva
- influxdb_cloud
- infor_nexus
- insightful
- instagram
- interzoid
- iyzico
- jobber
- jobtread
- judgeme_reviews
- justsift
- kafka
- kajabi
- kameleoon
- kapa_ai
- kaufland_marketplace
- keka
- kestra
- kick
- kickscale
- kinde
- kion
- kisi
- kissmetrics
- klarna
- knowbe4
- kommo
- komodor
- koyeb
- kyve
- labelbox
- lambda_labs
- lawmatics
- learnworlds
- lemon_squeezy
- lever
- lexware_office
- liana
- lightdash
- lingo_dev
- linkedin_pages
- linnworks
- llama_cloud
- lodgify
- logicmonitor
- logrocket
- lokalise
- looker
- loop_returns
- m3ter
- mailtrap
- mantle
- marketo
- mastodon
- meetup
- memberful
- mendeley
- mercado_ads
- mercado_pago
- merge
- meteostat
- metricool
- metriport
- metronome
- mews
- mezmo
- microsoft_365_usage_reports
- microsoft_advertising
- microsoft_clarity
- microsoft_dataverse
- microsoft_defender_cloud_apps
- microsoft_defender_endpoint
- microsoft_defender_for_cloud
- microsoft_entra_id
- microsoft_intune
- microsoft_lists
- microsoft_purview
- microsoft_purview_audit
- microsoft_sentinel
- microsoft_teams
- microsoft_teams_call_records
- midtrans
- mighty_networks
- mindbody
- mintlify
- mirakl
- miro
- missive
- mode
- moesif
- moneybird
- mono
- moodle
- motherduck
- mycase
- nager_date
- nasa
- navan
- neon_crm
- netsuite
- news_api
- nexhealth
- nexiopay
- ninjaone_rmm
- noaa_cdo
- nobl9
- nocrm
- nolt
- nops
- northpass_lms
- npm_registry
- nuntly
- nutshell
- nylas
- octolens
- oecd
- okendo
- omni
- onedrive
- onehundredms
- onelogin
- onesignal
- open_data_dc
- open_dental
- open_meteo
- openalex
- opencorporates
- openfec
- opn_payments
- opslevel
- oracle
- oracle_ebs
- oracle_fusion
- orbit
- otto_market
- outlook
- outreach
- oveit
- ownerrez
- pagbank
- pagerduty
- pardot
- patreon
- pax8
- paychex
- paylocity
- paymob
- paymongo
- paypal
- peec_ai
- pendo
- pennylane
- perk
- pexels
- phonepe
- phyllo
- pike13
- pinecone
- pingone
- pinterest_organic
- pipeliner
- pivotal_tracker
- piwik
- planetscale
- planning_center
- plunk
- pluralsight_flow
- pocket
- podbean
- podium
- polygon
- poplar
- postscript
- power_bi_admin
- practicepanther
- preset
- prestashop
- primetric
- printavo
- procore
- productiv
- productive
- prompting_company
- promptwatch
- proofpoint_tap
- propertyware
- pubnub
- qdrant
- qonto
- qualtrics
- quay
- quickbooks
- railz
- raken
- rapid7_insightvm
- raygun
- rb2b
- rd_station_marketing
- reddit
- redis
- redpanda_cloud
- referralhero
- rent_manager
- repairshopr
- reply_io
- retail_express
- retell_ai
- retently
- reverb
- revolut_merchant
- ringcentral
- rocket_chat
- rocket_matter
- rocketlane
- rss
- rubygems
- rudderstack
- safetyculture
- sage_intacct
- sailthru
- salesforce_marketing_cloud
- salestrics
- sanity
- sap_concur
- sap_erp
- sap_fieldglass
- sap_hana
- sap_successfactors
- savvycal
- scale_ai
- scaleway
- scalr
- search_ads_360
- sec_edgar
- secureframe
- select_star
- semantic_scholar
- semaphore
- semrush
- sendpulse
- senseforce
- serpstat
- service_fusion
- servicem8
- servicetitan
- servicetrade
- sevdesk
- sevenshifts
- sftp
- sharepoint
- sharetribe
- shippo
- shopware
- shopwired
- shortio
- sigma_computing
- signnow
- sim
- similarweb
- simplecast
- simplesat
- simpro
- sinch
- singlestore
- singular
- site24x7
- skyvern
- slash
- sleekplan
- sleuth
- smaily
- smartlook
- smartrecruiters
- smartwaiver
- smokeball
- soda_cloud
- solarwinds_service_desk
- sonar_cloud
- sonatype_nexus
- spacelift
- speedcurve
- spot_io
- spotify_ads
- sprinklr
- sprout_social
- statsig
- stockx
- strava
- streamlabs
- sumsub
- superwall
- surveymonkey
- survicate
- svix
- swonkie
- synthesia
- systeme
- tackle_io
- talkdesk
- tally
- teamup_fitness
- tebra
- telli
- telnyx
- tempo
- ternary
- terra_api
- thinkific_courses
- thoughtspot
- thousandeyes
- threads
- thrive_learning
- ticketmaster
- ticktick
- tiktok_shop
- tile38
- timely
- tiny_erp
- tinybird
- tipalti
- toast
- toggl
- track_pms
- transistor
- tremendous
- trunk_io
- trustpilot
- trustradius
- turso
- twenty
- twitch
- twitter
- twitter_ads
- two_c2p
- tyntec_sms
- uk_companies_house
- uk_ons
- un_comtrade
- uppromote
- uptick
- us_bea
- us_bls
- us_eia
- us_treasury_fiscal_data
- uservoice
- vanta
- vendr
- vespa
- virtuous
- visma_economic
- vonage
- vturb
- vwo
- waiteraid
- walmart_marketplace
- wasabi
- watchmode
- waydev
- wayfair
- whatsapp_business_management
- when_i_work
- who_gho
- whop
- wikipedia_pageviews
- wiz
- wompi
- workday
- workflowmax
- workiz
- workramp
- world_bank
- wufoo
- xendit
- xero
- xsolla
- yahoo_finance
- yandex_metrica
- ynab
- yoco
- yotpo
- younium
- youtube_analytics
- youtube_data
- zalando_zdirect
- zapsign
- zellify
- zenefits
- zenloop
- zluri
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
- zoominfo
- zylo
