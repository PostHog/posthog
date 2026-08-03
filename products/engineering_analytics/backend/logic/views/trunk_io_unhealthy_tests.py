"""Curated Trunk.io unhealthy-tests query builder.

Maps the raw ``UnhealthyTests`` warehouse snapshot (Trunk.io's currently flaky/broken tests
for one repo) onto the ``(runner, nodeid)`` identity the span-derived test-health queue keys
on, so its verdicts can annotate our own evidence. This is the only place Trunk.io's JUnit
identity is translated; the table name is resolved per team (see ``logic.sources``), never
hardcoded.

The nodeid derivations mirror ``.github/scripts/report_test_timings.py`` ``test_identity()``,
which builds the span names from the same JUnit fields Trunk.io ingests:

- pytest: ``classname.replace('.', '/') + '::' + name`` (``to_pytest_nodeid``).
- jest: the JUnit file joined under ``frontend/`` (the emitter normalizes Jest's
  frontend-working-directory paths repo-relative), then ``'::' + name``. Only the single
  leading ``../`` hop is unfolded here; anything more exotic just fails to match, and an
  unmatched test degrades to "no annotation", never to a wrong one.

Rows from runners this product's queue doesn't cover (cargo, playwright, other repos' Jest
projects) keep ``runner = ''`` and are dropped.

Every column lands ``Nullable`` (see ``source_schema.py``), so reads are ``ifNull``-guarded;
``status`` is Trunk.io's ``{value, timestamp}`` object and is read through ``toString`` so the
same SQL works whether the column landed as JSON or String.
"""


def build_query(table_name: str) -> str:
    return f"""
        SELECT
            runner,
            multiIf(
                runner = 'pytest' AND classname != '', concat(replaceAll(classname, '.', '/'), '::', test_name),
                runner = 'jest' AND file_path != '', concat(
                    if(
                        startsWith(file_path, '../'),
                        substring(file_path, 4, length(file_path)),
                        concat('frontend/', file_path)
                    ),
                    '::', test_name
                ),
                test_name
            ) AS nodeid,
            trunk_status,
            trunk_quarantined,
            trunk_url
        FROM (
            SELECT
                multiIf(
                    ifNull(parent, '') = 'pytest' OR endsWith(ifNull(file_path, ''), '.py'), 'pytest',
                    endsWith(ifNull(file_path, ''), '.ts')
                        OR endsWith(ifNull(file_path, ''), '.tsx')
                        OR endsWith(ifNull(file_path, ''), '.js')
                        OR endsWith(ifNull(file_path, ''), '.jsx'), 'jest',
                    ''
                ) AS runner,
                ifNull(name, '') AS test_name,
                ifNull(classname, '') AS classname,
                ifNull(file_path, '') AS file_path,
                lower(JSONExtractString(ifNull(toString(status), '{{}}'), 'value')) AS trunk_status,
                ifNull(quarantined, false) AS trunk_quarantined,
                ifNull(html_url, '') AS trunk_url
            FROM {table_name}
        )
        WHERE runner != '' AND test_name != '' AND trunk_status IN ('flaky', 'broken')
    """
