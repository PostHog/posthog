---
title: Linking SonarQube as a source
sidebar: Docs
showTitle: true
availability: { free: full, selfServe: full, enterprise: full }
sourceId: Sonarqube
---

<!--
This is the user-facing source doc. It must be moved to the posthog.com repo at
contents/docs/cdp/sources/sonarqube.md (it lives here only because this PR has no posthog.com
checkout). Once there, run `python manage.py audit_source_docs --docs-dir <posthog.com>/contents/docs/cdp/sources`.
-->

import SourceSetupIntro from "../\_snippets/source-setup-intro.mdx"
import SyncModes from "../\_snippets/sync-modes.mdx"
import TroubleshootingLink from "../\_snippets/dw-troubleshooting-link.mdx"

Sync code-quality data from your self-hosted [SonarQube Server](https://www.sonarsource.com/products/sonarqube/) into the PostHog data warehouse — projects, their analyses, branches, and pull requests, metric definitions and values, metric history, quality gates and their status per project, coding rules, issues and their change history, security hotspots, and users — so you can trend technical debt, reliability, coverage, and issue counts across your projects over time.

## Prerequisites

- A running SonarQube Server instance reachable from the public internet. For SonarQube Cloud (`sonarcloud.io` or `sonarqube.us`), use the Sonar Cloud source instead.
- A user token generated in SonarQube. The token inherits the permissions of the user who created it, so it can read the projects, issues, and rules that user can see.
- To sync the **users** table, the token's user needs the _Administer System_ permission. All other tables only need normal browse access.

## Adding a data source

<SourceSetupIntro />

You'll need:

- **Server URL** — the base URL of your SonarQube instance, e.g. `https://sonarqube.yourcompany.com`.
- **User token** — create one under **My Account → Security → Generate Tokens** in your SonarQube instance. Copy it immediately; SonarQube only shows it once.

## Sync modes

<SyncModes />

**Issues** support incremental sync: after the first run, only issues created since the last sync are fetched (using the `createdAfter` filter on the issue creation date). Because SonarQube exposes no "updated since" filter for issues, status changes on existing issues (for example, an issue being resolved) are only picked up on a full refresh. **Measures history** also supports incremental sync: after the first run, only analyses from a day before the last synced analysis date onward are fetched (using the `from` filter). The overlap catches analyses that the server finished processing after the last sync. **Project analyses** sync incrementally the same way, on the analysis date. Every other table syncs with a full refresh each run.

**Component measures** holds one row per metric for every project, directory, and file, so it can grow large on big codebases. It is off by default; turn it on when you need file-level values. For project-level trends, use **measures history**.

**Issue changelog** needs one request per issue, because SonarQube returns the history of one issue at a time. On an instance with many issues, a sync takes a long time. It is off by default.

**Project pull requests** only have data on Developer Edition and above. Community Build does not analyze pull requests, so this table stays empty there.

**Hotspots** use an API that SonarQube Server 2026.4 deprecated in favor of security issues. On those versions, security findings also appear in the **issues** table.

## Configuration

<SourceParameters />

## Supported tables

<SourceTables />

## Troubleshooting

- **Setup rejects a SonarQube Cloud URL.** This source reads SonarQube Server. Cloud needs an organization key on every request, so connect it with the Sonar Cloud source instead.
- **The users table fails to sync.** `/api/users/search` requires the _Administer System_ permission. Either grant it to the token's user or leave the users table unselected — it's off by default.
- **Fewer issues than expected on a large project.** SonarQube caps issue search at 10,000 results per query window. PostHog automatically pages past this by re-windowing on the issue creation date, so all issues are synced; if you still see gaps, check that the token can browse the affected projects.

<TroubleshootingLink />
