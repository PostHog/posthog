---
title: Linking Scaleway as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Scaleway
beta: true
---

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../\_snippets/alpha-release.mdx"

<AlphaRelease />

Sync your [Scaleway](https://www.scaleway.com) organization data — billing invoices, IAM identities, projects, audit trail events, and compute instances — into PostHog to build cost, security, and infrastructure reporting alongside your product data.

## Prerequisites

Before connecting Scaleway, you need:

- A Scaleway account with an **Organization**.
- An **IAM API key** (secret key) with read permissions for the data you want to sync.
- Your **Organization ID**.

## Adding a data source

<SourceSetupIntro />

You will need the following:

- **API secret key**: create an API key from the [IAM > API keys](https://console.scaleway.com/iam/api-keys) page in the Scaleway console. The secret key is shown only once at creation, so copy it then. Scaleway API secret keys do not expire by default.
- **Organization ID**: find it under [Organization settings](https://console.scaleway.com/organization/settings).

Grant the API key the read permission sets that match the tables you want to sync. You only need the ones for the data you actually want:

- `IAMReadOnly` — users, applications, groups, policies, API keys, SSH keys
- `ProjectReadOnly` — projects
- `BillingReadOnly` — invoices
- `AuditTrailReadOnly` — audit trail events
- `InstancesReadOnly` — instance servers

Granting only a subset is fine: the source connects as long as the key is valid, and the table picker flags any table your key cannot read so you can leave it unselected.

## Sync modes

<SyncModes />

All Scaleway tables sync via full refresh. Resource inventories (IAM, projects, instances) are small, and invoices and audit events are re-pulled each sync. Audit trail events sync the most recent 90 days on each refresh.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

**"Your API key is missing the read permission set required to sync ..."**: the API key is valid but lacks the permission set for that table. Add the matching read permission (see the list above) to the key in the Scaleway console, then reconnect.

**No rows for a table**: some resources are region- or zone-scoped. Instance servers are pulled from every zone your organization can use, and audit trail events from the `fr-par` and `nl-ams` regions — a table can legitimately be empty if you have no resources there.

<TroubleshootingLink />
