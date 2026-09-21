# Has it deployed? The deploy ladder

Establish that the merge commit is live before you measure anything.
Strongest first; record which rung this project supports in `pattern:pr_follow_up:deploy-signal` so later runs go straight to it.

Two rules hold on every rung.
**Ordering is not proof**: a deployment or marker after the merge can come from another branch, a hotfix, or another environment, so only commit containment sets the onset, which `gh api repos/<owner>/<repo>/compare/<merge_sha>...<deploy_sha> --jq .status` confirms by reading `ahead` or `identical`.
**Only persistent production counts**: a per-PR preview, a staging environment, or an ephemeral environment named after a branch never sets the onset, whatever its status.

## Rung 1: GitHub deployments in the warehouse

`execute-sql` over `<prefix>github_deployments` joined to `<prefix>github_deployment_statuses` (table naming in `sources.md`).
The statuses table holds one row per transition, so take the **latest** status per deployment (`argMax(state, created_at)`) and keep only deployments whose latest status is `success`; a deployment that later read `failure`, `error`, or `inactive` is not live.
Candidates are those deployments created after the merge in a persistent production-named environment.
The onset is the `created_at` of the qualifying `success` status row of the earliest candidate whose `sha` contains the merge, never the deployment's own `created_at`: a queued or slow deployment is created minutes or hours before users receive it, and a window that starts at creation counts pre-release traffic as post-deploy.
When no candidate contains the merge, this rung has no answer: move down the ladder.

## Rung 2: `gh` deployments and releases

The deployments endpoint's `sha` filter matches only a deployment recorded at exactly that commit, so never filter by the merge SHA.
Enumerate instead: `gh api 'repos/<owner>/<repo>/deployments?per_page=100&page=<n>'` (add `environment=<name>` once you know the production environment), paging until `created_at` falls before the merge.
Keep persistent production environments, read each candidate's newest status from its `statuses_url` and keep `success`, then apply the containment check; the onset is the `created_at` of that success status on the earliest candidate that passes.

Releases work the same way: `gh api 'repos/<owner>/<repo>/releases?per_page=100&page=<n>'`, paging until `published_at` falls before the merge, then the earliest release published after the merge whose tag contains it (`compare/<merge_sha>...<tag>`), skipping any release with `draft` or `prerelease` set, since a beta or release candidate never reached production users; when the repository ships production from a named channel, keep only that channel's releases.
A small first page can miss the qualifying release, so page before you select.

## Rung 3: deploy annotations

`annotations-list` with `search=deploy`: a project wired to a CI deploy marker gets one `creation_type: GIT` annotation per release, usually `hidden_in_user_interface: true`, with `date_marker` the deploy time and content naming a commit and environment.
Page with `offset` until `date_marker` passes the merge time.
When the content names a commit, the onset is the first marker after the merge whose commit contains it (the same containment check).
A marker whose content names no commit cannot prove containment, so it corroborates a soak-proxy onset (rung 4) but never replaces it, and the report says the onset is estimated.

## Rung 4: soak proxy

Nothing above exists: use merge time + 24h for server-side code, + 72h or more for web client bundles and mobile apps (judge from the paths: a mobile repository, an SDK, a frontend bundle).
Say "assumed live after a 24h soak, this project has no deploy signal" in anything you file, and never call a claim failed inside the soak.

## The onset

The deploy time is your **onset**: every probe compares a post-onset window against a pre-merge window of the same length.
Use `toDateTime('<ts>', 'UTC')` for timestamp literals, since bare strings parse in the project timezone and can shift the window by hours.
