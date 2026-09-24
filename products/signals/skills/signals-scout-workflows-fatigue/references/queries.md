# Queries for the workflows audience fatigue scout

Every query runs through `execute-sql`.
Replace `<ids>` with the ids you collected in an earlier step, and keep the time windows as written unless a guardrail says otherwise.
Two facts about the tables shape every query here.
`system.cohorts.count` is a cached number that can be far off, so always count members from the membership tables.
The JSON columns on `system.hog_flows` are nullable, so wrap them in `ifNull(toString(...), '[]')` before `JSONExtractArrayRaw`; the bare column fails with "Nested type Array(String) cannot be inside Nullable type".

## Query 1: inventory of active marketing email workflows

One row per active workflow that has at least one `function_email` step whose category is not `transactional`, with its trigger type and the cohort ids in its audience.
A batch workflow's audience is `trigger.filters.properties`; cohort filters carry `type: "cohort"` and the cohort id in `value`.
Person-property filters have no cohort id and show up as an empty array.

```sql
SELECT
  id,
  name,
  trigger.type AS trigger_type,
  arrayMap(x -> JSONExtractInt(x, 'value'),
    arrayFilter(x -> JSONExtractString(x, 'type') = 'cohort',
      JSONExtractArrayRaw(ifNull(toString(trigger.filters.properties), '[]')))) AS cohort_ids
FROM system.hog_flows
WHERE status = 'active'
  AND arrayExists(
    a -> JSONExtractString(a, 'type') = 'function_email'
      AND JSONExtractString(a, 'config', 'message_category_type') != 'transactional',
    JSONExtractArrayRaw(ifNull(toString(actions), '[]')))
ORDER BY trigger_type, name
LIMIT 500
```

For pattern 2, group the same rows by cohort:

```sql
SELECT cohort_id, count() AS workflows, groupArray(name) AS workflow_names
FROM (
  SELECT id, name,
    arrayJoin(arrayMap(x -> JSONExtractInt(x, 'value'),
      arrayFilter(x -> JSONExtractString(x, 'type') = 'cohort',
        JSONExtractArrayRaw(ifNull(toString(trigger.filters.properties), '[]'))))) AS cohort_id
  FROM system.hog_flows
  WHERE status = 'active' AND trigger.type = 'batch'
)
GROUP BY cohort_id
HAVING workflows >= 2
ORDER BY workflows DESC
LIMIT 50
```

## Query 2: pairwise cohort overlap and true sizes

Static cohorts live in `static_cohort_people`, property-based cohorts in `cohort_people`; `system.cohorts.is_static` says which table to read.
Run the overlap once per table, then the sizes.
Containment is `overlap / min(members_a, members_b)`.

```sql
SELECT a.cohort_id AS c1, b.cohort_id AS c2, count(DISTINCT a.person_id) AS overlap
FROM static_cohort_people AS a
JOIN static_cohort_people AS b ON a.person_id = b.person_id
WHERE a.cohort_id IN (<ids>) AND b.cohort_id IN (<ids>) AND a.cohort_id < b.cohort_id
GROUP BY c1, c2
ORDER BY overlap DESC
LIMIT 50
```

```sql
SELECT cohort_id, uniq(person_id) AS members
FROM static_cohort_people
WHERE cohort_id IN (<ids>)
GROUP BY cohort_id
```

```sql
SELECT id, name, is_static
FROM system.cohorts
WHERE id IN (<ids>)
```

## Query 3: sends per person, last 7 days

Needs `$workflows_email_sent`, which a project captures only when it turned engagement events on.
Confirm the event exists before running this, and treat the result as the baseline to store under `pattern:workflows-fatigue:baseline`.

```sql
SELECT count() AS people,
       countIf(sends >= 2) AS ge2_sends,
       countIf(sends >= 3) AS ge3_sends,
       countIf(sends >= 5) AS ge5_sends,
       countIf(workflows >= 2) AS from_2plus_workflows,
       countIf(workflows >= 3) AS from_3plus_workflows,
       max(sends) AS max_sends
FROM (
  SELECT person_id, count() AS sends, uniq(properties.$workflow_id) AS workflows
  FROM events
  WHERE event = '$workflows_email_sent' AND timestamp >= now() - INTERVAL 7 DAY
  GROUP BY person_id
)
```

## Query 4: workflow pairs sharing recipients, last 14 days

The pre-aggregated subqueries keep the join small: one row per person and workflow.

```sql
SELECT a.wf AS wf_a, b.wf AS wf_b, count() AS shared_people
FROM (SELECT person_id, properties.$workflow_id AS wf FROM events
      WHERE event = '$workflows_email_sent' AND timestamp >= now() - INTERVAL 14 DAY
      GROUP BY person_id, wf) AS a
JOIN (SELECT person_id, properties.$workflow_id AS wf FROM events
      WHERE event = '$workflows_email_sent' AND timestamp >= now() - INTERVAL 14 DAY
      GROUP BY person_id, wf) AS b ON a.person_id = b.person_id
WHERE a.wf < b.wf
GROUP BY wf_a, wf_b
ORDER BY shared_people DESC
LIMIT 20
```

## Query 5: names and trigger types for workflow ids

```sql
SELECT id, name, status, trigger.type AS trigger_type, version
FROM system.hog_flows
WHERE id IN (<ids>)
```

## Query 6: consequence check

Unsubscribe and complaint share among people mailed by two or more workflows, against people mailed by one, over 14 days.
An unsubscribe click can land on a different person than the send when the click happens in a fresh anonymous session, so read a zero here as "no evidence", never as "no fatigue".

```sql
SELECT multi, count() AS people, countIf(unsubs > 0) AS unsubscribed, countIf(blocked > 0) AS complained
FROM (
  SELECT person_id,
         uniqIf(properties.$workflow_id, event = '$workflows_email_sent') >= 2 AS multi,
         countIf(event = '$workflows_email_unsubscribed') AS unsubs,
         countIf(event = '$workflows_email_blocked') AS blocked
  FROM events
  WHERE event IN ('$workflows_email_sent', '$workflows_email_unsubscribed', '$workflows_email_blocked')
    AND timestamp >= now() - INTERVAL 14 DAY
  GROUP BY person_id
)
GROUP BY multi
ORDER BY multi
```
