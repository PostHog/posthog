# Rubric v0 for the API-quality scout (2026-09-22)

Every item is answered yes / no / unsure with one sentence of evidence. Rates, not scores.

## Hard checks (script, no judgment)

- H1 finished: run status completed, under 15 minutes.
- H2 pinned: the log shows the fetch, checkout and printed hash of the pinned commit.
- H3 scoped: files read outside the fixed page are limited to files traced from a page file (models, serializers, tests of a page endpoint).
- H4 output: at least one `scout-emit-report` call, or a close-out that states no candidate met the bar.
- H5 memory: every `scout-scratchpad-remember` key starts with the copy's own prefix; no `cursor:api-quality:` write.
- H6 cost and duration recorded from `$ai_generation`.

## Per filed report (judge, with the repo at the pinned commit)

Process items (did it do the work):
- P1 traced: the report names endpoint, file and symbol that exist at the pinned commit.
- P2 evidence: each evidence item describes code that is actually there.

Outcome items (is the result right):
- O1 real: the defect exists as described (for pagination: the ordering really is non-unique and the endpoint really paginates; for scope: the queryset really lacks the filter and no inherited manager or permission layer supplies it; for list cost: the serializer really is heavy and the queryset really lacks the prefetch).
- O2 in scope: it is a proven contract gap by the skill's own discriminator, not one of its listed noise cases (bounded single page, intentionally global resource, model without tenant data, style-only).
- O3 fix direction: the smallest fix named would resolve it.
- O4 severity: P2 vs P3 matches the skill's definitions (P2 = realistic correctness, tenant-isolation or repeatable user-impact failure; P3 = clear performance or maintainability defect needing a product decision).
- O5 not a duplicate: no inbox report and no `finding:api-quality:` memory entry already covers the same endpoint and defect.

Skeptic pass: every O1 = yes gets a second judge told to refute it; O1 stands only if the skeptic fails.

## Per run (after pooling)

- R1 recall: share of the pooled verified findings on this run's page that this run filed.
- R2 contamination: the run read another copy's memory entries (keys containing `api-quality-b<n>` for a different n).
- R3 self-agreement: for the two runs of one model on one page, did they file the same set of endpoints.
