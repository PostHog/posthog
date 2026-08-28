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
        status,
        quarantine_setting,
        quarantined_at
    FROM (
        SELECT
            if(parent = 'pytest', 'pytest', 'jest') AS runner,
            ifNull(file, '') AS file,
            ifNull(name, '') AS name,
            ifNull(status, '') AS status,
            ifNull(quarantine_setting, '') AS quarantine_setting,
            parseDateTimeBestEffort(quarantined_at) AS quarantined_at,
            replaceAll(substring(ifNull(file, ''), 1, length(ifNull(file, '')) - 3), '/', '.') AS module,
            if(parent = 'pytest' AND startsWith(ifNull(classname, ''), concat(module, '.')),
               replaceAll(substring(ifNull(classname, ''), length(module) + 2, length(ifNull(classname, ''))), '.', '::'),
               '') AS cls
        FROM {table}
    )
    WHERE file != '' AND name != '' AND quarantined_at IS NOT NULL
"""
