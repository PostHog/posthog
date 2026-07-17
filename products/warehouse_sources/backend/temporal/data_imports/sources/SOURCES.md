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
| alguna                           | HTTP                        | requests                                                        | ✅                          |
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
| argocd                           | HTTP                        | requests                                                        | ✅                          |
| asana                            | HTTP                        | requests                                                        | ✅                          |
| ashby                            | HTTP                        | requests                                                        | ✅                          |
| asknicely                        | HTTP                        | requests                                                        | ✅                          |
| assemblyai                       | HTTP                        | requests                                                        | ✅                          |
| attentive                        | HTTP (webhook-first)        | requests (webhook management)                                   | ✅                          |
| attio                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| automox                          | HTTP                        | requests                                                        | ✅                          |
| aviationstack                    | HTTP                        | requests                                                        | ✅                          |
| aviator                          | HTTP                        | requests                                                        | ✅                          |
| awin                             | HTTP                        | requests                                                        | ✅                          |
| azure_devops                     | HTTP                        | requests                                                        | ✅                          |
| babelforce                       | HTTP                        | requests                                                        | ✅                          |
| bamboohr                         | HTTP                        | requests                                                        | ✅                          |
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
| datadog                          | HTTP                        | requests                                                        | ✅                          |
| datahub                          | HTTP                        | requests                                                        | ✅                          |
| dbt                              | HTTP                        | requests                                                        | ✅                          |
| decagon                          | HTTP                        | requests                                                        | ✅                          |
| deel                             | HTTP                        | requests                                                        | ✅                          |
| deepgram                         | HTTP                        | requests                                                        | ✅                          |
| deepsource                       | HTTP (GraphQL)              | requests                                                        | ✅                          |
| delighted                        | HTTP                        | requests                                                        | ✅                          |
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
| dynatrace                        | HTTP                        | requests                                                        | ✅                          |
| e2b                              | HTTP                        | requests                                                        | ✅                          |
| e_conomic                        | HTTP                        | requests                                                        | ✅                          |
| easypost                         | HTTP                        | requests                                                        | ✅                          |
| easypromos                       | HTTP                        | requests                                                        | ✅                          |
| elevenlabs                       | HTTP                        | requests                                                        | ✅                          |
| freshcaller                      | HTTP                        | requests                                                        | ✅                          |
| freshdesk                        | HTTP                        | requests                                                        | ✅                          |
| freshsales                       | HTTP                        | requests                                                        | ✅                          |
| freshservice                     | HTTP                        | requests                                                        | ✅                          |
| elasticemail                     | HTTP                        | requests                                                        | ✅                          |
| elasticsearch                    | HTTP                        | requests                                                        | ✅                          |
| emailoctopus                     | HTTP                        | requests                                                        | ✅                          |
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
| giphy                            | HTTP                        | requests                                                        | ✅                          |
| gitlab                           | HTTP                        | requests                                                        | ✅                          |
| gladly                           | HTTP                        | requests                                                        | ✅                          |
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
| hibob                            | HTTP                        | requests                                                        | ✅                          |
| honeybadger                      | HTTP                        | requests                                                        | ✅                          |
| honeycomb                        | HTTP                        | requests                                                        | ✅                          |
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
| instatus                         | HTTP                        | requests                                                        | ✅                          |
| intercom                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| intruder                         | HTTP                        | requests                                                        | ✅                          |
| invoiced                         | HTTP                        | requests                                                        | ✅                          |
| invoiceninja                     | HTTP                        | requests                                                        | ✅                          |
| ip2whois                         | HTTP                        | requests                                                        | ✅                          |
| iterable                         | HTTP                        | requests                                                        | ✅                          |
| jamf_pro                         | HTTP                        | requests                                                        | ✅                          |
| jellyfish                        | HTTP                        | requests                                                        | ✅                          |
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
| koyeb                            | HTTP                        | requests                                                        | ✅                          |
| kong_konnect                     | HTTP                        | requests                                                        | ✅                          |
| kubecost                         | HTTP                        | requests                                                        | ✅                          |
| lacework                         | HTTP                        | requests                                                        | ✅                          |
| lago                             | HTTP                        | requests                                                        | ✅                          |
| lambda_labs                      | HTTP                        | requests                                                        | ✅                          |
| langfuse                         | HTTP                        | requests                                                        | ✅                          |
| launchdarkly                     | HTTP                        | requests                                                        | ✅                          |
| kustomer                         | HTTP                        | requests                                                        | ✅                          |
| lattice                          | HTTP                        | requests                                                        | ✅                          |
| leadfeeder                       | HTTP                        | requests                                                        | ✅                          |
| lemlist                          | HTTP                        | requests                                                        | ✅                          |
| less_annoying_crm                | HTTP                        | requests                                                        | ✅                          |
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
| meta_ads                         | HTTP                        | requests                                                        | ✅                          |
| metabase                         | HTTP                        | requests                                                        | ✅                          |
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
| omnisend                         | HTTP                        | requests                                                        | ✅                          |
| oncehub                          | HTTP                        | requests                                                        | ✅                          |
| onepagecrm                       | HTTP                        | requests                                                        | ✅                          |
| onepassword                      | HTTP (cursor pagination)    | requests                                                        | ✅                          |
| onfleet                          | HTTP (cursor pagination)    | requests                                                        | ✅                          |
| open_exchange_rates              | HTTP                        | requests                                                        | ✅                          |
| openai                           | HTTP                        | requests                                                        | ✅                          |
| opinion_stage                    | HTTP                        | requests                                                        | ✅                          |
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
| recharge                         | HTTP                        | requests                                                        | ✅                          |
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
| signoz                           | HTTP                        | requests                                                        | ✅                          |
| simplecast                       | HTTP                        | requests                                                        | ✅                          |
| simplesat                        | HTTP                        | requests                                                        | ✅                          |
| skyvern                          | HTTP                        | requests                                                        | ✅                          |
| slack                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| smaily                           | HTTP                        | requests                                                        | ✅                          |
| smartreach                       | HTTP                        | requests                                                        | ✅                          |
| smartsheet                       | HTTP                        | requests                                                        | ✅                          |
| smartwaiver                      | HTTP                        | requests                                                        | ✅                          |
| snapchat_ads                     | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| snowflake                        | DB protocol                 | snowflake-connector-python                                      | ➖                          |
| snowplow                         | HTTP                        | requests                                                        | ✅                          |
| snyk                             | HTTP                        | requests                                                        | ✅                          |
| solarwinds_service_desk          | HTTP                        | requests                                                        | ✅                          |
| sonarqube                        | HTTP                        | requests                                                        | ✅                          |
| spacelift                        | HTTP (GraphQL)              | requests                                                        | ✅                          |
| sparkpost                        | HTTP                        | requests                                                        | ✅                          |
| split_io                         | HTTP                        | requests                                                        | ✅                          |
| squadcast                        | HTTP                        | requests                                                        | ✅                          |
| square                           | HTTP                        | requests                                                        | ✅                          |
| squarespace                      | HTTP                        | requests                                                        | ✅                          |
| statuspage                       | HTTP                        | requests                                                        | ✅                          |
| stigg                            | HTTP                        | requests                                                        | ✅                          |
| stripe                           | HTTP (vendor SDK) + Webhook | stripe (StripeClient + RequestsClient) + `WebhookSourceManager` | ✅ (pull) / ➖ (webhook)    |
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
| teamcity                         | HTTP                        | requests                                                        | ✅                          |
| teamtailor                       | HTTP                        | requests                                                        | ✅                          |
| teamwork                         | HTTP                        | requests                                                        | ✅                          |
| tempo                            | HTTP                        | requests                                                        | ✅                          |
| temporalio                       | gRPC (vendor SDK)           | temporalio (`Client`, Rust core via `temporalio.bridge`)        | ⚠️                          |
| tenable_vulnerability_management | HTTP (async export flow)    | requests                                                        | ✅                          |
| terraform_cloud                  | HTTP                        | requests                                                        | ✅                          |
| testrail                         | HTTP                        | requests                                                        | ✅                          |
| thinkific                        | HTTP                        | requests                                                        | ✅                          |
| tickettailor                     | HTTP                        | requests                                                        | ✅                          |
| tiktok_ads                       | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| tmdb                             | HTTP                        | requests                                                        | ✅                          |
| todoist                          | HTTP                        | requests                                                        | ✅                          |
| together_ai                      | HTTP                        | requests                                                        | ✅                          |
| travis_ci                        | HTTP                        | requests                                                        | ✅                          |
| trello                           | HTTP                        | requests                                                        | ✅                          |
| tremendous                       | HTTP                        | requests                                                        | ✅                          |
| trigger_dev                      | HTTP                        | requests                                                        | ✅                          |
| twelve_labs                      | HTTP                        | requests                                                        | ✅                          |
| twilio                           | HTTP                        | requests                                                        | ✅                          |
| typeform                         | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| ubidots                          | HTTP                        | requests                                                        | ✅                          |
| unleash                          | HTTP                        | requests                                                        | ✅                          |
| unstructured                     | HTTP                        | requests                                                        | ✅                          |
| upstash                          | HTTP                        | requests                                                        | ✅                          |
| uptimerobot                      | HTTP                        | requests                                                        | ✅                          |
| uservoice                        | HTTP                        | requests                                                        | ✅                          |
| vantage                          | HTTP                        | requests                                                        | ✅                          |
| vapi                             | HTTP                        | requests                                                        | ✅                          |
| vellum                           | HTTP                        | requests                                                        | ✅                          |
| veracode                         | HTTP                        | requests (custom HMAC signing)                                  | ✅                          |
| vercel                           | HTTP                        | requests                                                        | ✅                          |
| vitally                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| vultr                            | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| webflow                          | HTTP                        | requests                                                        | ✅                          |
| weights_and_biases               | HTTP (GraphQL)              | requests                                                        | ✅                          |
| windmill                         | HTTP                        | requests                                                        | ✅                          |
| woocommerce                      | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wordpress                        | HTTP                        | requests                                                        | ✅                          |
| workable                         | HTTP                        | requests                                                        | ✅                          |
| workos                           | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| wrike                            | HTTP                        | requests                                                        | ✅                          |
| writesonic                       | HTTP                        | requests                                                        | ✅                          |
| wufoo                            | HTTP                        | requests                                                        | ✅                          |
| xmatters                         | HTTP                        | requests                                                        | ✅                          |
| zapier_supported_storage         | HTTP                        | requests                                                        | ✅                          |
| zendesk                          | HTTP                        | requests + `rest_source.RESTClient`                             | ✅                          |
| zendesk_sell                     | HTTP                        | requests                                                        | ✅                          |
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

- \*\*Add
- \*\*Implement
- \*\*Migrate
- \*\*Switch
- [`data-imports-grpc-transport`](/.semgrep/rules/security/data-imports-grpc-transport.yaml)
- [`data-imports-http-transport`](/.semgrep/rules/security/data-imports-http-transport.yaml)
- active_campaign
- acuity_scheduling
- adapty
- adjust
- adobe_analytics
- adobe_commerce
- adp_workforce_now
- adyen
- ahrefs
- aikido_security
- airbyte
- airops
- aiven
- akeneo
- alpaca_broker_api
- amazon_ads
- amazon_cloudwatch
- amazon_eventbridge
- amazon_kinesis
- amazon_s3
- amazon_selling_partner
- amazon_sns
- amazon_sqs
- appcues
- apple_search_ads
- appstack
- apptivo
- appwrite
- asknicely
- auth0
- automox
- autumn
- aws_cloudtrail
- azure_blob
- azure_table_storage
- backblaze
- basecamp
- bigcommerce
- bitly
- box
- braintrust
- branch
- breezy_hr
- browse_ai
- cal_com
- campaign_manager_360
- campfire
- captain_data
- cart_com
- castor_edc
- chift
- chorus
- cin7
- cisco_meraki
- clarifai
- clazar
- clickhouse_cloud
- cloudbeds
- coassemble
- cockroachdb
- codacy
- codecov
- constant_contact
- copper
- cosmosdb
- couchbase
- criteo
- curve
- dagster_cloud
- databricks
- datascope
- datorama
- db2
- deno_deploy
- deputy
- display_video_360
- docusign
- dodopayments
- dolibarr
- doppler
- drata
- dremio
- dropbox
- dub
- dubsado
- dwolla
- dynamics365
- dynamodb
- e2b
- ebay
- eloqua
- employment_hero
- encharge
- env0
- expensify
- facebook_pages
- fastbill
- fauna
- feishu
- fintoc
- firebase
- firebolt
- flagsmith
- flexmail
- flexport
- flowlu
- fly_io
- formbricks
- freeagent
- freightview
- freshbooks
- freshchat
- freshservice
- fulcrum
- gerrit
- getstream
- gitea
- gitguardian
- glassfrog
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
- google_tasks
- google_workspace_admin_reports
- greythr
- growthbook
- gumloop
- gusto
- harness
- harvey
- heap
- helpscout
- hetzner
- hex
- heygen
- hibob
- high_level
- hightouch
- honeybadger
- honeycomb
- hoorayhr
- hubplanner
- humanitix
- ikas
- illumina_basespace
- impact
- infor_nexus
- insightful
- instagram
- instantly
- interzoid
- jenkins
- jobber
- judgeme_reviews
- justsift
- kafka
- kajabi
- kapa_ai
- keka
- kickscale
- kisi
- kissmetrics
- klarna
- knock
- koyeb
- kyve
- lambda_labs
- langsmith
- leexi
- lemon_squeezy
- lever
- liana
- lightfield
- lingo_dev
- linkedin_pages
- linnworks
- llama_cloud
- lokalise
- looker
- loops
- m3ter
- mailtrap
- mantle
- marketo
- mendeley
- mercado_ads
- mercury
- merge
- metaplane
- metricool
- metriport
- metronome
- microsoft_dataverse
- microsoft_entra_id
- microsoft_lists
- microsoft_teams
- mintlify
- miro
- missive
- mode
- mono
- nasa
- navan
- neon
- netsuite
- news_api
- nexiopay
- ninjaone_rmm
- nocrm
- northpass_lms
- nuget
- nutshell
- nylas
- octolens
- octopus_deploy
- onedrive
- onehundredms
- onesignal
- open_data_dc
- opuswatch
- oracle
- oracle_ebs
- oracle_fusion
- orbit
- outlook
- outreach
- oveit
- pagerduty
- pardot
- paylocity
- paypal
- peec_ai
- pendo
- pennylane
- perigon
- perk
- pexels
- phyllo
- pinecone
- pipeliner
- pivotal_tracker
- piwik
- planetscale
- plunk
- pocket
- podium
- polygon
- poplar
- prestashop
- primetric
- productive
- prompting_company
- promptwatch
- qdrant
- qonto
- qualtrics
- quickbooks
- railz
- rapid7_insightvm
- raygun
- razorpay
- rb2b
- rd_station_marketing
- recreation
- reddit
- redis
- referralhero
- repairshopr
- reply_io
- retail_express
- retell_ai
- retently
- revolut_merchant
- ringcentral
- rki_covid
- rocket_chat
- rocketlane
- rss
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
- search_ads_360
- secureframe
- semaphore
- sendpulse
- senseforce
- serpstat
- sevenshifts
- sftp
- sharepoint
- sharetribe
- shippo
- shopware
- shopwired
- shortio
- shutterstock
- sigma_computing
- signnow
- sim
- simfin
- simplecast
- simplesat
- singular
- skyvern
- slash
- smaily
- smartengage
- smartwaiver
- solarwinds_service_desk
- sonar_cloud
- sonatype_nexus
- sourcegraph
- spacelift
- spotify_ads
- spotlercrm
- statsig
- statuscake
- stockdata
- strava
- streamelements
- streamlabs
- stytch
- sumsub
- superwall
- surveymonkey
- survicate
- svix
- swonkie
- synthesia
- systeme
- teachable
- telli
- tempo
- terra_api
- thinkific_courses
- thrive_learning
- ticketmaster
- ticktick
- tile38
- timely
- tinyemail
- toggl
- track_pms
- tremendous
- trustpilot
- turso
- tvmaze
- twelve_data
- twenty
- twitter
- twitter_ads
- tyntec_sms
- uppromote
- uptick
- us_census
- usersnap
- uservoice
- veeqo
- vespa
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
- zapsign
- zellify
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
- zoominfo
