# Queries

The data half of a run. All of these are noncanonical derivations for one-off investigation, not governed metrics.

**Timezone footgun:** HogQL string timestamp literals parse in the project timezone. Use `now() - INTERVAL N DAY` for every window, never a hand-written timestamp string.

**Shape check first.** Confirm `$feature_flag_called` and the properties below exist on this project with `read-data-schema` before you build on them. A project that evaluates server-side with local evaluation sends few or no call events, which makes every query here blind rather than negative.

## Platform index — response mix per key per SDK

The one orientation read. Everything else drills into a row of it.

```sql
SELECT
    properties.$feature_flag AS flag_key,
    properties.$lib AS lib,
    count() AS calls_14d,
    count(DISTINCT person_id) AS persons_14d,
    countIf(properties.$feature_flag_response = 'false') AS false_calls,
    countIf(properties.$feature_flag_bootstrapped_response IS NOT NULL) AS bootstrapped_calls
FROM events
WHERE event = '$feature_flag_called'
  AND properties.$feature_flag IS NOT NULL
  AND timestamp >= now() - INTERVAL 14 DAY
GROUP BY flag_key, lib
ORDER BY calls_14d DESC
LIMIT 200
```

Read it two ways. Across a row: one key with several `lib` values is a cross-platform key. Down a column: a `false` share far above the other platforms for the same key, or `bootstrapped_calls` at zero on a client platform, points at the unloaded-value check.

## Split brain — one person, two answers

The confirming query. Restrict it to the working set; it is the most expensive read here.

```sql
SELECT
    flag_key,
    count() AS persons_with_two_answers,
    groupUniqArray(5)(per_lib) AS examples
FROM (
    SELECT
        properties.$feature_flag AS flag_key,
        person_id,
        count(DISTINCT properties.$feature_flag_response) AS answers,
        count(DISTINCT properties.$lib) AS libs,
        groupUniqArray(6)(concat(toString(properties.$lib), '=', toString(properties.$feature_flag_response))) AS per_lib
    FROM events
    WHERE event = '$feature_flag_called'
      AND properties.$feature_flag IN ('<key-a>', '<key-b>')
      AND timestamp >= now() - INTERVAL 7 DAY
    GROUP BY flag_key, person_id
    HAVING answers > 1 AND libs > 1
)
GROUP BY flag_key
ORDER BY persons_with_two_answers DESC
```

A person who gets both answers on one platform is a load race or a rebucket, not a split brain — that is why the `libs > 1` condition is there. Before you report, check `feature-flags-activity-retrieve`: a flag edited inside the window rebuckets everyone, and the two answers are then the edit, not the platforms.

## Identity ordering — responses around identify

Per key, whether a platform's answer changes once the user is identified.

```sql
WITH identified AS (
    SELECT
        properties.$session_id AS session_id,
        min(timestamp) AS identified_at
    FROM events
    WHERE event = '$identify'
      AND timestamp >= now() - INTERVAL 7 DAY
    GROUP BY session_id
)
SELECT
    e.properties.$lib AS lib,
    countIf(e.timestamp < i.identified_at) AS calls_before,
    countIf(e.timestamp >= i.identified_at) AS calls_after,
    countIf(e.timestamp < i.identified_at AND e.properties.$feature_flag_response = 'false') AS false_before,
    countIf(e.timestamp >= i.identified_at AND e.properties.$feature_flag_response = 'false') AS false_after
FROM events AS e
INNER JOIN identified AS i ON e.properties.$session_id = i.session_id
WHERE e.event = '$feature_flag_called'
  AND e.properties.$feature_flag = '<flag-key>'
  AND e.timestamp >= now() - INTERVAL 7 DAY
GROUP BY lib
```

A `false` share that drops sharply after identify means the pre-identify evaluation hashed the anonymous ID. Compare platforms: the one that identifies late is the one to change.

## Load race — first evaluation of a session

Whether a platform's first answer of a session differs from its later answers.

```sql
SELECT
    lib,
    countIf(rank = 1 AND response = 'false') / countIf(rank = 1) AS false_share_first,
    countIf(rank > 1 AND response = 'false') / countIf(rank > 1) AS false_share_later
FROM (
    SELECT
        properties.$lib AS lib,
        toString(properties.$feature_flag_response) AS response,
        row_number() OVER (PARTITION BY properties.$session_id ORDER BY timestamp) AS rank
    FROM events
    WHERE event = '$feature_flag_called'
      AND properties.$feature_flag = '<flag-key>'
      AND timestamp >= now() - INTERVAL 7 DAY
)
GROUP BY lib
```

A first-call `false` share well above the later share on one platform, with no bootstrap on that platform, is the unloaded-value shape.

## Platform coverage of a targeted property

For the unmatchable-conditions check: whether each platform sets the property the flag targets.

```sql
SELECT
    properties.$lib AS lib,
    count() AS events_7d,
    countIf(person.properties.<targeted_property> IS NOT NULL) AS with_property
FROM events
WHERE timestamp >= now() - INTERVAL 7 DAY
GROUP BY lib
ORDER BY events_7d DESC
```

A platform with traffic and no rows carrying the property cannot match a condition on it, whatever the rollout percentage says.

## Roster side

`system.feature_flags` (`id`, `key`, `name`, `filters`, `deleted`) beats paginating the roster on a project with many flags, and joins against the key index directly. It carries no `active` column, so read state from `feature-flag-get-definition` for anything you report.
