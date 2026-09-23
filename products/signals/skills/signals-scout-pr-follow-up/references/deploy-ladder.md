# Has it deployed? The deploy ladder

Establish that the merge commit is live before you measure anything.
Strongest first; record which rung this project supports in `pattern:pr_follow_up:deploy-signal` so later runs go straight to it.

Two rules hold on every signal-bearing rung (rungs 1 to 3); rung 4 has no deployment to check and is the stated exception.
**Ordering is not proof**: a deployment or marker after the merge can come from another branch, a hotfix, or another environment, so only commit containment sets the onset, which `gh api repos/<owner>/<repo>/compare/<merge_sha>...<deploy_sha> --jq .status` confirms by reading `ahead` or `identical`.
A SHA or tag that reaches that command came from data (a deployment row, an annotation body, a release name), so check it before it touches a shell: a commit must match `^[0-9a-f]{7,40}$`, a tag must be URL-encoded and quoted, and anything else is not a candidate, because an unquoted value with shell metacharacters would run in the sandbox.
**Only persistent production counts**: a per-PR preview, a staging environment, or an ephemeral environment named after a branch never sets the onset, whatever its status.

## Rung 1: GitHub deployments in the warehouse

`execute-sql` over `<prefix>github_deployments` joined to `<prefix>github_deployment_statuses` (table naming in `sources.md`).
The statuses table holds one row per transition, so keep every deployment that **ever** reached `success` (`minOrNullIf(parseDateTimeBestEffort(created_at), state = 'success')` per deployment, kept with `HAVING first_success IS NOT NULL`), not only those whose latest status is `success`: GitHub marks a deployment `inactive` as soon as the next one to the same environment succeeds, so on a busy environment every past deployment reads `inactive` and a latest-status filter keeps only the newest, which need not be the one that carried the merge.
A deployment that never reached `success` (`failure`, `error`, or still `pending`) is not live.
Candidates are those deployments created after the merge in a persistent production-named environment.
Do not select them on GitHub's `production_environment` flag: a deploy workflow that never sets it leaves it false on the real production environments, and a query keyed on it returns nothing.
Filter on `transient_environment = false` plus the environment name (`production`, `prod`, `prod-<region>`, `live`), and record the names in `pattern:pr_follow_up:deploy-signal` once you know them:

```sql
SELECT d.id AS id, d.sha AS sha, d.environment AS env,
       minOrNullIf(parseDateTimeBestEffort(s.created_at), s.state = 'success') AS first_success
FROM `<prefix>github_deployments` AS d
LEFT JOIN `<prefix>github_deployment_statuses` AS s ON s.deployment_id = d.id
WHERE parseDateTimeBestEffort(d.created_at) >= toDateTime('<merge ts>', 'UTC')
  AND coalesce(d.transient_environment, false) = false
  AND d.environment IN ('<production environments, each escaped: backslashes doubled, then quotes doubled>')
GROUP BY d.id, d.sha, d.environment
HAVING first_success IS NOT NULL
ORDER BY first_success ASC, d.id ASC
LIMIT 20 OFFSET <page * 20>
```

`transient_environment` is nullable and a source that omits the flag leaves it NULL, so the `coalesce` keeps those persistent deployments, as the curated deployments view does.
`minIf` has no NULL: a deployment with no success row gets the epoch, sorts first, and can pass containment as a 1970 onset, which is why the `OrNull` form and the `HAVING` are not optional.
Quote both table names in backticks as shown (a flattened multi-repository name keeps hyphens), and escape each environment name before it enters the `IN` list by first replacing every `\` with `\\` and then doubling every `'`, in that order, since the names are data a repository owner typed and ClickHouse reads a backslash before a quote as an escaped quote, so doubling quotes alone leaves `\'` able to end the literal.
Run the containment check from the top of that list: the first deployment created after the merge is often cut from a commit before it and reads `behind`, and the onset belongs to the first one that reads `ahead`.
The limit is a page, not a horizon: when no row on the page reads `ahead` or `identical`, take the next page with `OFFSET` until one does or the rows run out, because a release-branch or multi-region repository can ship twenty production deployments after the merge before one contains it.
A repository that ships the same SHA to several persistent production environments (one per region) has one onset per environment; take the earliest for the side-effect sweep, close its window only at the next **different** production SHA (a later region receiving the same SHA is still this batch rolling out, not the next one), and name the environment that serves the project's users when you cite a fix claim.
`first_success` renders in the project timezone, so keep every comparison in UTC.
The onset is the **first** `success` status's `created_at` on the earliest candidate whose `sha` contains the merge, never the deployment's own `created_at`: a queued or slow deployment is created minutes or hours before users receive it, and a window that starts at creation counts pre-release traffic as post-deploy.
When no candidate contains the merge, this rung has no answer: move down the ladder.

## Rung 2: `gh` releases (and deployments, where the token allows)

The sandbox's read-only token carries read grants for repository contents, metadata, and pull requests only, and the deployments endpoint needs a `deployments: read` grant, so expect a 403 from it and go straight to releases below; the warehouse rung is where deployments are read.
Where a token does carry that grant, the deployments endpoint's `sha` filter matches only a deployment recorded at exactly that commit, so never filter by the merge SHA.
Enumerate instead: `gh api 'repos/<owner>/<repo>/deployments?per_page=100&page=<n>'`, paging until `created_at` falls before the merge, and filter the returned JSON by exact string comparison on `environment`; never put an environment name from deployment data into the command itself, because a crafted name with a quote and shell syntax would run in the sandbox that holds the read-only GitHub token and the scout's PostHog token.
Keep persistent production environments, read each candidate's statuses from its `statuses_url` and keep any deployment with a `success` among them (its newest status is usually `inactive` once a later deployment succeeded, and that does not mean it never shipped), then apply the containment check; the onset is the `created_at` of the first `success` status on the earliest candidate that passes.

Releases work the same way: `gh api 'repos/<owner>/<repo>/releases?per_page=100&page=<n>'`, which GitHub orders by **creation** date, not publication, so a draft cut before the merge and published after it sits behind older-published rows; page until a row's `created_at` falls more than 30 days before the merge (or the rows run out), because one pre-merge creation on a page does not rule out an older draft published later, then pick from everything collected the earliest release published after the merge whose tag contains it (`compare/<merge_sha>...<tag>`), skipping any release with `draft` or `prerelease` set, since a beta or release candidate never reached production users; when the repository ships production from a named channel, keep only that channel's releases.
A small first page can miss the qualifying release, so page before you select.

## Rung 3: deploy annotations

A project wired to a CI deploy marker gets one `creation_type: GIT` annotation per release, usually `hidden_in_user_interface: true`, with `date_marker` the deploy time and content naming a commit and environment.
`system.annotations` holds them, so one query replaces paging the API:

```sql
SELECT id, content, date_marker
FROM system.annotations
WHERE creation_type = 'GIT' AND deleted = 0
  AND match(content, '(^|[^a-z0-9_-])<production environment, regex-escaped>([^a-z0-9_-]|$)')
  AND date_marker >= toDateTime('<merge ts>', 'UTC')
ORDER BY date_marker ASC, id ASC
LIMIT 20 OFFSET <page * 20>
```

Page it the same way until a marker's commit contains the merge or the markers run out.
The environment name is data you discovered, so escape it before it enters the literal (regex-escape it so `.`, `+`, and the like match literally, then escape the result as a ClickHouse string literal: every `\` doubled, then every `'` doubled, in that order), and match it as a whole token, never as a substring: `production` must not match `nonproduction`, and `prod` must not match a preview label that contains it, or a preview deployment of the same SHA sets a false early onset.
Fall back to `annotations-list` only when that table is unavailable, and page it by date with `offset` and **no** `search`: a valid marker reads `production a1b2c3d` and never contains the word deploy, so filter the returned rows by `creation_type`, environment, and commit instead.
When the content names a commit, the onset is the first marker after the merge whose commit contains it (the same containment check).
A marker whose content names no commit cannot prove containment, so it corroborates a soak-proxy onset (rung 4) but never replaces it, and the report says the onset is estimated.

## Rung 4: soak proxy

Nothing above exists: use merge time + 24h for server-side code, + 72h or more for web client bundles and mobile apps (judge from the paths: a mobile repository, an SDK, a frontend bundle).
Say "assumed live after a <24h or 72h> soak, this project has no deploy signal" in anything you file, with the soak you actually applied to that surface, and never call a claim failed inside the soak.
Neither rule above applies here: there is no commit to contain and no environment to name, so the onset is always estimated, and the report says so.

## The onset

The deploy time is your **onset**: every probe compares a post-onset window against a pre-merge window of the same length.
The post-onset window closes at the next **different** production SHA on the same channel or environment, whether or not it contains the merge (a rollback to a pre-merge SHA reads `behind` and still closes the window, because the PR's code is no longer live), or at the next batch's proxy onset under rung 4, or at now when nothing has shipped since; movement that begins after that close belongs to the next batch, so record the close alongside the onset.
That close bounds attribution only: a claim probe keeps reading until it has the denominator its row needs, as the body's onset paragraph says.
Use `toDateTime('<ts>', 'UTC')` for timestamp literals, since bare strings parse in the project timezone and can shift the window by hours.
