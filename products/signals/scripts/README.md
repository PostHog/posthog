# Scout repository ranking

Run a deterministic, read-only ranking over saved repository evidence:

```sh
python products/signals/scripts/rank_repositories.py --input repositories.json --limit 5
```

The script uses the Python standard library. It does not call an API, clone repositories, or change scout settings.
The output is a candidate list for review, not a decision to clone a repository or implement a fix.

## Input

```json
{
  "context": "A web application with checkout errors and payment services.",
  "allowed_repositories": ["example/storefront", "example/payments"],
  "pinned_repositories": [],
  "ignore_terms": ["example"],
  "repositories": [
    {
      "full_name": "example/storefront",
      "description": "Web checkout application",
      "readme": "Customer storefront and checkout.",
      "archived": false,
      "fork": false,
      "template": false,
      "mirror": false,
      "project_matches": ["Source map links the checkout error to this repository."],
      "confirmed_fix_urls": ["https://github.com/example/storefront/pull/12"],
      "human_merged_prs_30d": 8,
      "last_human_activity": "2026-01-15T12:00:00Z"
    },
    {
      "full_name": "example/payments",
      "description": "Payment service"
    }
  ]
}
```

Collect `allowed_repositories` from all pages of the project's GitHub integration repository list.
Access through a person's GitHub account alone does not establish project scope.
An explicit pin never adds a repository to that scope.
Use `pinned_repositories` for this scout's pins and repositories explicitly named in its instructions, not the whole fleet's pins.

Collect names, descriptions, flags, and README text for the allowed candidates.
Mark read-only mirrors with `mirror: true`, including mirrors that GitHub does not mark as forks.
Only explicit pins can retain archived repositories, forks, templates, or mirrors.

Supply `project_matches` only for verified associations, such as a source map, deployment mapping, or service-to-repository mapping.
A shared organization homepage or an SDK documentation URL is not deployment evidence.
Supply `confirmed_fix_urls` for merged fixes linked to this project's reports, not reports that were only resolved manually.
These inputs are evidence supplied by the caller; the script does not verify them.

Use the same trailing 30-day window for every `human_merged_prs_30d` value.
Exclude bot-authored PRs. Use human activity timestamps, not GitHub's repository `pushed_at`, which includes bots.
Omit an activity field or use `null` when it is unknown. A measured zero sorts before an unknown count.

## Ranking

Each criterion breaks ties from the previous criterion:

1. Explicit pin or instruction.
2. At least one verified project association.
3. At least one confirmed fix for this project.
4. Jaccard similarity between project context tokens and repository metadata tokens.
5. Human-authored PRs merged in the trailing 30 days.
6. Most recent human activity.
7. Repository name, in alphabetical order.

Metadata includes the name, description, and first 2,000 README characters.
Token matching ignores letter case, common English words, URLs, HTML tags, image links, organization names, and `ignore_terms`.
Jaccard similarity is the size of the token intersection divided by the size of the token union.
The score is a text similarity, not a probability that a repository is relevant.

The script returns up to `--limit` candidates, plus scope and status exclusions.
It reports pins with no metadata separately instead of inventing a candidate record.
Pinned and directly associated candidates have `high` confidence; candidates with confirmed fixes have `medium` confidence; all others have `low` confidence.
`needs_project_evidence` remains true when only fix history, text, or activity supports the candidate.
Generic text overlap can promote adjacent repositories. Inspect these candidates before cloning them.
