"""Curated view over the Trunk quarantined-tests snapshot (``TRUNK_QUARANTINED_TESTS_COLUMNS``)."""


def build_query(table: str) -> str:
    """Curated SELECT over a synced Trunk quarantined-tests table: the reconstructed runner-native
    nodeid, the runner, and the parsed quarantine timestamp.

    Trunk keys a test by (file, classname, name) rather than one id, and the two runners split the
    name differently: pytest hides the class inside ``classname`` (the file's module plus the
    class), while jest puts the whole title in ``name``. Trimming the module prefix recovers the
    pytest class; jest needs no reassembly. ``parent`` carries the runner for pytest and the file
    path for jest. Rows without a file, name, or quarantine time carry nothing a consumer can
    attribute or age, so they drop here.
    """
    return f"""
    SELECT
        runner,
        concat(file, '::', if(cls = '', '', concat(cls, '::')), name) AS nodeid,
        file,
        any(status) AS status,
        any(quarantine_setting) AS quarantine_setting,
        any(test_case_id) AS test_case_id,
        -- Trunk keys a test per variant (e.g. one row per browser), so collapse to one row per
        -- test; the oldest quarantine carries the honest age.
        min(quarantined_at_parsed) AS quarantined_at
    FROM (
        SELECT
            if(parent = 'pytest', 'pytest', 'jest') AS runner,
            ifNull(file, '') AS file,
            ifNull(name, '') AS name,
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
    WHERE file != '' AND name != '' AND quarantined_at_parsed IS NOT NULL
    GROUP BY runner, nodeid, file
"""
