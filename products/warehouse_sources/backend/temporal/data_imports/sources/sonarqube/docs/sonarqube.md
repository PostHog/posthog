<!--
This is the user-facing source doc. It must be moved to the posthog.com repo at
contents/docs/cdp/sources/sonarqube.md (it lives here only because this PR has no posthog.com
checkout). Once there, run `python manage.py audit_source_docs --docs-dir <posthog.com>/contents/docs/cdp/sources`.
-->
---
title: Linking SonarQube as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Sonarqube
beta: true
---

import SourceSetupIntro from "../_snippets/source-setup-intro.mdx"
import SyncModes from "../_snippets/sync-modes.mdx"
import TroubleshootingLink from "../_snippets/dw-troubleshooting-link.mdx"
import AlphaRelease from "../_snippets/alpha-release.mdx"

<AlphaRelease />

Sync code-quality data from your self-hosted [SonarQube Server](https://www.sonarsource.com/products/sonarqube/) into the PostHog data warehouse — projects, metric definitions, coding rules, issues, and users — so you can trend technical debt, reliability, and issue counts across your projects over time.

## Prerequisites

- A running SonarQube Server instance reachable from the public internet.
- A user token generated in SonarQube. The token inherits the permissions of the user who created it, so it can read the projects, issues, and rules that user can see.
- To sync the **users** table, the token's user needs the *Administer System* permission. All other tables only need normal browse access.

## Adding a data source

<SourceSetupIntro />

You'll need:

- **Server URL** — the base URL of your SonarQube instance, e.g. `https://sonarqube.yourcompany.com`.
- **User token** — create one under **My Account → Security → Generate Tokens** in your SonarQube instance. Copy it immediately; SonarQube only shows it once.

## Sync modes

<SyncModes />

**Issues** support incremental sync: after the first run, only issues created since the last sync are fetched (using the `createdAfter` filter on the issue creation date). Because SonarQube exposes no "updated since" filter for issues, status changes on existing issues (for example, an issue being resolved) are only picked up on a full refresh. Projects, metrics, rules, and users are small reference sets that sync with a full refresh each run.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **The users table fails to sync.** `/api/users/search` requires the *Administer System* permission. Either grant it to the token's user or leave the users table unselected — it's off by default.
- **Fewer issues than expected on a large project.** SonarQube caps issue search at 10,000 results per query window. PostHog automatically pages past this by re-windowing on the issue creation date, so all issues are synced; if you still see gaps, check that the token can browse the affected projects.

<TroubleshootingLink />
