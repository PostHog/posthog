# Cross-arm comparison (frozen PR 75215, clean room, same model in both seats)

| set               | arm                  | wall min | review-stage min | raw→dedup→kept | real (post-dedup) | real clusters | must/should/consider | kept real (precision) | real kept (recall) | not-real dropped | total $ | review $ | validation $ | $ per real |
| ----------------- | -------------------- | -------: | ---------------: | -------------- | ----------------- | ------------: | -------------------- | --------------------- | ------------------ | ---------------- | ------: | -------: | -----------: | ---------: |
| GC (glm-high-1bc) | GLM 5.3 Flash @ high |       83 |               46 | 46→36→13       | 9/36 (25%)        |    6 (+3 new) | 0/2/7                | 5/13 (38%)            | 5/9 (56%)          | 19/27 (70%)      |   $2.56 |    $1.15 |        $1.26 |      $0.28 |
| GB (glm-high-2)   | GLM 5.3 Flash @ high |       71 |                – | 55→35→14       | 10/35 (29%)       |    7 (+3 new) | 0/4/6                | 9/14 (64%)            | 9/10 (90%)         | 20/25 (80%)      |   $2.41 |    $1.12 |        $0.99 |      $0.24 |
| UA (luna-low-1)   | GPT 5.6 Luna @ low   |       14 |                9 | 9→9→8          | 4/9 (44%)         |    4 (+0 new) | 0/3/1                | 3/8 (38%)             | 3/4 (75%)          | 0/5 (0%)         |   $0.30 |    $0.20 |        $0.06 |      $0.07 |
| UB (luna-low-2)   | GPT 5.6 Luna @ low   |       16 |               11 | 8→8→7          | 3/8 (38%)         |    1 (+0 new) | 0/3/0                | 3/7 (43%)             | 3/3 (100%)         | 1/5 (20%)        |   $0.31 |    $0.21 |        $0.06 |      $0.10 |
| SA (sol-low-1)    | GPT 5.6 Sol @ low    |       20 |               12 | 11→9→7         | 5/9 (56%)         |    5 (+0 new) | 0/3/2                | 5/7 (71%)             | 5/5 (100%)         | 2/4 (50%)        |   $6.59 |    $4.78 |        $1.70 |      $1.32 |
| SB (sol-low-2)    | GPT 5.6 Sol @ low    |       22 |               14 | 14→10→7        | 5/10 (50%)        |    5 (+0 new) | 0/5/0                | 4/7 (57%)             | 4/5 (80%)          | 2/5 (40%)        |   $7.43 |    $5.66 |        $1.68 |      $1.49 |

## Per-arm means

| arm                  | runs | wall min | total $ | real per run | real clusters per run | must_fix per run | validator precision | validator recall | $ per real |
| -------------------- | ---: | -------: | ------: | -----------: | --------------------: | ---------------: | ------------------- | ---------------- | ---------: |
| GLM 5.3 Flash @ high |    2 |       77 |   $2.49 |          9.5 |                   6.5 |              0.0 | 14/27 (52%)         | 14/19 (74%)      |      $0.26 |
| GPT 5.6 Luna @ low   |    2 |       15 |   $0.30 |          3.5 |                   2.5 |              0.0 | 6/15 (40%)          | 6/7 (86%)        |      $0.09 |
| GPT 5.6 Sol @ low    |    2 |       21 |   $7.01 |          5.0 |                   5.0 |              0.0 | 9/14 (64%)          | 9/10 (90%)       |      $1.40 |

## Cluster consistency: fresh 3-skeptic verdicts vs the August registry

Only clusters with ≥1 fresh verdict in this experiment. `August` = n_real/n_verified in `known_clusters.json`.

| cluster | August | fresh real / fresh total | per-finding votes                                                         | issue                                                                                       |
| ------: | ------ | ------------------------ | ------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------- |
|       3 | 0/7    | 0/6                      | GC19=n(0/3), GC36=n(0/3), GB14=n(0/3), UB1=n(0/3), SA1=n(0/3), SB1=n(0/3) | self_driving_review read from context JSON with truthy bool() coercion instead of a strict  |
|       4 | 0/9    | 0/3                      | GC23=n(0/3), GB22=n(0/3), UA4=n(0/3)                                      | Engine does not gate familiarity computation/rendering on self_driving, relying on the ser  |
|       7 | 0/2    | 0/2                      | GC26=n(0/3), GB28=n(0/3)                                                  | stamphog_connected SerializerMethodField does an uncached cross-product-DB read on every s  |
|       9 | 0/5    | 0/3                      | GC30=n(0/3), GB26=n(1/3), UA5=n(0/3)                                      | process_inbox_pr_review performs a live GitHub get_pr on every receiver refire before any   |
|      11 | 0/0    | 0/1                      | GC33=n(0/3)                                                               | Webhook-leg resolver re-runs the full acting-reviewer resolution (latest suggested_reviewe  |
|      13 | 0/3    | 0/2                      | GC2=n(0/3), GB7=n(0/3)                                                    | \_parse_pr_url regex is not host-anchored, so lookalike domains/embedded github.com substri |
|      16 | 0/0    | 0/3                      | GC25=n(0/3), UB4=n(0/3), SB2=n(0/3)                                       | Exception-safety of \_start_stamphog_review's deferred facade import relative to its try/ex |
|      18 | 0/1    | 0/3                      | GC9=n(0/3), GB13=n(0/3), UA2=n(0/3)                                       | has_reviewable_repo_config omits the provider="github" filter used by sibling repo-config   |
|      22 | 0/0    | 0/1                      | GB4=n(0/3)                                                                | Self-driving identification relies solely on the deprecated Task.signal_report field witho  |
|      26 | 0/0    | 0/1                      | GC1=n(0/3)                                                                | stamphog_review_inbox_prs is PATCH-writable without a server-side stamphog_connected preco  |
|      29 | 0/0    | 1/1                      | GB10=R(3/3)                                                               | Carve-out exception retry path can block the stale-approval safety dismissal for head-chan  |
|      35 | 3/3    | 1/1                      | GC24=R(3/3)                                                               | Hard-coded 'It is a draft on purpose' provenance sentence renders even when the self-drivi  |
|      36 | 0/0    | 1/1                      | GC12=R(3/3)                                                               | Webhook leg's supersede+create path has no head-based dedupe against receiver-leg runs, do  |
|      40 | 0/1    | 0/1                      | GC22=n(0/3)                                                               | resolve_stamphog_acting_reviewer has no try/except guard despite being invoked from anothe  |
|      51 | 0/0    | 0/3                      | GC17=n(0/3), GB11=n(0/3), SA3=n(0/3)                                      | Broad except in get_stamphog_connected collapses transient circuit-breaker failures and re  |
|      53 | 0/0    | 0/1                      | GC10=n(0/3)                                                               | Opt-out dismissal message claims 'New commits were pushed' on a reopened PR where no commi  |
|      65 | 0/1    | 0/1                      | GB29=n(0/3)                                                               | Frontend loads stamphog_connected once on mount and never revalidates, so connecting Stamp  |
|      72 | 0/1    | 0/1                      | GB24=n(0/3)                                                               | AGENTS.md carve-out section never states whether StamphogRepoConfig.enabled (per-repo opt-  |
|      73 | 1/1    | 2/2                      | SA9=R(2/3), SB10=R(2/3)                                                   | find_task_run's branch fallback can bind an unrelated or stale run (whose output.pr_url na  |

Clusters where fresh verdicts disagree with each other inside this experiment: 0/19.
