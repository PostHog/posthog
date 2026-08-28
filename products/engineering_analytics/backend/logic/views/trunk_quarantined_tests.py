"""Curated view over the Trunk quarantined-tests snapshot (``TRUNK_QUARANTINED_TESTS_COLUMNS``)."""


def build_query(table: str) -> str:
    """Curated SELECT over a synced Trunk quarantined-tests table: the reconstructed runner-native
    nodeid, a runner label, and the parsed quarantine timestamp.

    Trunk keys a test by (file, classname, name) and overloads ``parent`` per uploader (verified
    against a real connected source): 'pytest' for pytest, the test file path for jest and
    Playwright, and the nextest 'suite::test' id for Rust. Trimming the module prefix recovers the
    pytest class; jest and Playwright need no reassembly; Rust and Storybook rows carry no file, so
    the nodeid falls back to classname::name. Rows without a name or quarantine time carry nothing
    a consumer can attribute or age, so they drop here.
    """
    return f"""
    SELECT
        runner,
        multiIf(
            file != '', concat(file, '::', if(cls = '', '', concat(cls, '::')), name),
            classname != '' AND classname != name, concat(classname, '::', name),
            name
        ) AS nodeid,
        file,
        any(status) AS status,
        any(quarantine_setting) AS quarantine_setting,
        any(test_case_id) AS test_case_id,
        -- Trunk keys a test per variant (e.g. one row per browser), so collapse to one row per
        -- test; the oldest quarantine carries the honest age.
        min(quarantined_at_parsed) AS quarantined_at
    FROM (
        SELECT
            multiIf(
                parent = 'pytest', 'pytest',
                parent LIKE '%::%', 'rust',
                parent LIKE 'playwright/%' OR parent LIKE '%.spec.ts', 'playwright',
                parent LIKE '%.stories.tsx', 'storybook',
                'jest'
            ) AS runner,
            ifNull(file, '') AS file,
            ifNull(name, '') AS name,
            ifNull(classname, '') AS classname,
            ifNull(status, '') AS status,
            ifNull(quarantine_setting, '') AS quarantine_setting,
            ifNull(test_case_id, '') AS test_case_id,
            parseDateTimeBestEffort(quarantined_at) AS quarantined_at_parsed,
            replaceAll(substring(ifNull(file, ''), 1, length(ifNull(file, '')) - 3), '/', '.') AS module,
            if(parent = 'pytest' AND startsWith(ifNull(classname, ''), concat(module, '.')),
               replaceAll(substring(ifNull(classname, ''), length(module) + 2, length(ifNull(classname, ''))), '.', '::'),
               '') AS cls
        FROM {table}
    )
    WHERE name != '' AND quarantined_at_parsed IS NOT NULL
    GROUP BY runner, nodeid, file
"""
