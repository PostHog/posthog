"""Curated view over the Trunk quarantined-tests snapshot (``TRUNK_QUARANTINED_TESTS_COLUMNS``)."""

# A QuarantinedTests table synced on the v2 API lands this column; a v1 table lands ``parent``.
V2_SHAPE_COLUMN = "parent_name"


def build_query(table: str, *, v2_shape: bool) -> str:
    """Curated SELECT over a synced Trunk quarantined-tests table: the reconstructed runner-native
    nodeid, a runner label, where the test lives, the parsed quarantine timestamp, the test's id,
    and its Trunk page when the API returned one (always null on the v1 shape, which has no URL).

    The table holds the v1 or the v2 shape, depending on the source's API version pin and whether it
    resynced since the pin changed. Both shapes carry the same values under different names: v1
    ``parent`` / ``classname`` / ``quarantined_at`` / ``test_case_id``, v2 ``parent_name`` /
    ``class_name`` / ``quarantined_since`` / ``id`` plus ``url``.

    Trunk keys a test by (file, classname, name) and overloads the parent per uploader (verified
    against a real connected source and the live v2 API): 'pytest' for pytest, the test file path
    for jest and Playwright, the story file for Storybook, and the nextest 'crate::module' id for
    Rust. Trimming the module prefix recovers the pytest class; jest and Playwright need no
    reassembly; Rust and Storybook rows carry no file, so the nodeid falls back to classname::name.
    Rows without a name or quarantine time carry nothing a consumer can attribute or age, so they
    drop here.

    The parent stays inside this view: the reading of it a consumer needs is ``source_path`` (where
    the test file sits, as its suite reported it) and ``crate`` (Rust, which reports no file).
    """
    if v2_shape:
        parent, classname, quarantined_at, test_id, url = (
            "parent_name",
            "class_name",
            "quarantined_since",
            "id",
            "url",
        )
    else:
        parent, classname, quarantined_at, test_id, url = (
            "parent",
            "classname",
            "quarantined_at",
            "test_case_id",
            "NULL",
        )
    return f"""
    SELECT
        runner,
        multiIf(
            file != '', concat(file, '::', if(cls = '', '', concat(cls, '::')), name),
            classname != '' AND classname != name, concat(classname, '::', name),
            name
        ) AS nodeid,
        file,
        any(source_path) AS source_path,
        any(crate) AS crate,
        any(status) AS status,
        any(test_case_id) AS test_case_id,
        any(url) AS trunk_url,
        -- Trunk keys a test per variant (e.g. one row per browser), so collapse to one row per
        -- test; the oldest quarantine carries the honest age.
        min(quarantined_at_parsed) AS quarantined_at
    FROM (
        SELECT
            ifNull({parent}, '') AS parent_value,
            multiIf(
                parent_value = 'pytest', 'pytest',
                parent_value LIKE '%::%', 'rust',
                parent_value LIKE 'playwright/%' OR parent_value LIKE '%.spec.ts', 'playwright',
                parent_value LIKE '%.stories.tsx', 'storybook',
                'jest'
            ) AS runner,
            if(runner = 'rust', '', if(ifNull(file, '') != '', ifNull(file, ''), parent_value)) AS source_path,
            if(runner = 'rust', splitByString('::', parent_value)[1], '') AS crate,
            ifNull(file, '') AS file,
            ifNull(name, '') AS name,
            ifNull({classname}, '') AS classname,
            lower(ifNull(status, '')) AS status,
            ifNull({test_id}, '') AS test_case_id,
            {url} AS url,
            parseDateTimeBestEffort({quarantined_at}) AS quarantined_at_parsed,
            replaceAll(substring(ifNull(file, ''), 1, length(ifNull(file, '')) - 3), '/', '.') AS module,
            if(parent_value = 'pytest' AND startsWith(classname, concat(module, '.')),
               replaceAll(substring(classname, length(module) + 2, length(classname)), '.', '::'),
               '') AS cls
        FROM {table}
    )
    WHERE name != '' AND quarantined_at_parsed IS NOT NULL
    GROUP BY runner, nodeid, file
"""
