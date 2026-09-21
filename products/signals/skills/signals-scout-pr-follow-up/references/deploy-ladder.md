# Has it deployed? The deploy ladder

Establish that the merge commit is live before you measure anything.
Strongest first; record which rung this project supports in `pattern:pr_follow_up:deploy-signal` so later runs go straight to it.

Two rules hold on every signal-bearing rung (rungs 1 to 3); rung 4 has no deployment to check and is the stated exception.
**Ordering is not proof**: a deployment or marker after the merge can come from another branch, a hotfix, or another environment, so only commit containment sets the onset, which `gh api repos/<owner>/<repo>/compare/<merge_sha>...<deploy_sha> --jq .status` confirms by reading `ahead` or `identical`.
**Only persistent production counts**: a per-PR preview, a staging environment, or an ephemeral environment named after a branch never sets the onset, whatever its status.

## Rung 1: GitHub deployments in the warehouse

`execute-sql` over `<prefix>github_deployments` joined to `<prefix>github_deployment_statuses` (table naming in `sources.md`).
The statuses table holds one row per transition, so keep every deployment that **ever** reached `success` (`minIf(parseDateTimeBestEffort(created_at), state = 'success')` per deployment), not only those whose latest status is `success`: GitHub marks a deployment `inactive` as soon as the next one to the same environment succeeds, so on a busy environment every past deployment reads `inactive` and a latest-status filter keeps only the newest, which need not be the one that carried the merge.
A deployment that never reached `success` (`failure`, `error`, or still `pending`) is not live.
Candidates are those deployments created after the merge in a persistent production-named environment.
Do not select them on GitHub's `production_environment` flag: a deploy workflow that never sets it leaves it false on the real production environments, and a query keyed on it returns nothing.
Filter on `transient_environment = false` plus the environment name (`production`, `prod`, `prod-<region>`, `live`), and record the names in `pattern:pr_follow_up:deploy-signal` once you know them:

```sql
SELECT d.id AS id, d.sha AS sha, d.environment AS env,
       minIf(parseDateTimeBestEffort(s.created_at), s.state = 'success') AS first_success
FROM <prefix>github_deployments AS d
LEFT JOIN <prefix>github_deployment_statuses AS s ON s.deployment_id = d.id
WHERE parseDateTimeBestEffort(d.created_at) >= toDateTime('<merge ts>', 'UTC')
  AND d.transient_environment = false
  AND d.environment IN ('<production environments>')
GROUP BY d.id, d.sha, d.environment
ORDER BY first_success ASC
LIMIT 20
```

Run the containment check from the top of that list: the first deployment created after the merge is often cut from a commit before it and reads `behind`, and the onset belongs to the first one that reads `ahead`.
A repository that ships the same SHA to several persistent production environments (one per region) has one onset per environment; take the earliest for the side-effect sweep, and name the environment that serves the project's users when you cite a fix claim.
`first_success` renders in the project timezone, so keep every comparison in UTC.
The onset is the **first** `success` status's `created_at` on the earliest candidate whose `sha` contains the merge, never the deployment's own `created_at`: a queued or slow deployment is created minutes or hours before users receive it, and a window that starts at creation counts pre-release traffic as post-deploy.
When no candidate contains the merge, this rung has no answer: move down the ladder.

## Rung 2: `gh` deployments and releases

The deployments endpoint's `sha` filter matches only a deployment recorded at exactly that commit, so never filter by the merge SHA.
Enumerate instead: `gh api 'repos/<owner>/<repo>/deployments?per_page=100&page=<n>'` (add `environment=<name>` once you know the production environment), paging until `created_at` falls before the merge.
Keep persistent production environments, read each candidate's statuses from its `statuses_url` and keep any deployment with a `success` among them (its newest status is usually `inactive` once a later deployment succeeded, and that does not mean it never shipped), then apply the containment check; the onset is the `created_at` of the first `success` status on the earliest candidate that passes.

Releases work the same way: `gh api 'repos/<owner>/<repo>/releases?per_page=100&page=<n>'`, paging until `published_at` falls before the merge, then the earliest release published after the merge whose tag contains it (`compare/<merge_sha>...<tag>`), skipping any release with `draft` or `prerelease` set, since a beta or release candidate never reached production users; when the repository ships production from a named channel, keep only that channel's releases.
A small first page can miss the qualifying release, so page before you select.

## Rung 3: deploy annotations

A project wired to a CI deploy marker gets one `creation_type: GIT` annotation per release, usually `hidden_in_user_interface: true`, with `date_marker` the deploy time and content naming a commit and environment.
`system.annotations` holds them, so one query replaces paging the API:

```sql
SELECT id, content, date_marker
FROM system.annotations
WHERE creation_type = 'GIT' AND deleted = 0
  AND content ILIKE '%<production environment>%'
  AND date_marker >= toDateTime('<merge ts>', 'UTC')
ORDER BY date_marker ASC
LIMIT 20
```

Fall back to `annotations-list` (`search=deploy`, page with `offset` until `date_marker` passes the merge time) only when that table is unavailable.
When the content names a commit, the onset is the first marker after the merge whose commit contains it (the same containment check).
A marker whose content names no commit cannot prove containment, so it corroborates a soak-proxy onset (rung 4) but never replaces it, and the report says the onset is estimated.

## Rung 4: soak proxy

Nothing above exists: use merge time + 24h for server-side code, + 72h or more for web client bundles and mobile apps (judge from the paths: a mobile repository, an SDK, a frontend bundle).
Say "assumed live after a <24h or 72h> soak, this project has no deploy signal" in anything you file, with the soak you actually applied to that surface, and never call a claim failed inside the soak.
Neither rule above applies here: there is no commit to contain and no environment to name, so the onset is always estimated, and the report says so.

## The onset

The deploy time is your **onset**: every probe compares a post-onset window against a pre-merge window of the same length.
The post-onset window closes at the next onset on the same rung (the next production deployment, release, or marker that passes the same containment check, or the next batch's proxy onset under rung 4), or at now when nothing has shipped since; movement that begins after that close belongs to the next batch, so record the close alongside the onset.
Use `toDateTime('<ts>', 'UTC')` for timestamp literals, since bare strings parse in the project timezone and can shift the window by hours.
