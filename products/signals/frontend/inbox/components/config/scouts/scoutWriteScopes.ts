/** One row in the write access picker. `scope` is the string the API stores and the token carries. */
export interface ScoutWriteScopeRow {
    scope: string
    /** Heading the row sits under. Purely a label: the API stores a flat list of scopes. */
    group: 'Analytics' | 'Monitoring'
    label: string
    description: string
}

/**
 * The scopes a person may grant one scout, mirroring `SCOUT_GRANTABLE_WRITE_SCOPES` in
 * `posthog/temporal/oauth.py`. A scope the backend drops from the allowlist may still be stored on
 * old configs: the picker shows nothing for it and drops it from the next save, since the API would
 * reject it. A scope added there needs a row added here to be offered. Descriptions say what the
 * scope reaches, because each one covers update and delete of every object of its kind in the
 * project, not only the ones the scout made.
 */
export const SCOUT_WRITE_SCOPE_ROWS: ScoutWriteScopeRow[] = [
    {
        scope: 'dashboard:write',
        group: 'Analytics',
        label: 'Dashboards',
        description: 'Create, update, and delete dashboards and their tiles',
    },
    {
        scope: 'insight:write',
        group: 'Analytics',
        label: 'Insights',
        description: 'Create, update, and delete saved insights',
    },
    {
        scope: 'annotation:write',
        group: 'Analytics',
        label: 'Annotations',
        description: 'Add, edit, and remove annotations, including organization-wide ones shared with other projects',
    },
    {
        scope: 'alert:write',
        group: 'Monitoring',
        label: 'Alerts',
        description: 'Create, update, and delete insight alerts',
    },
]

/** What every scout can write, whatever its grant. Shown so the picker is the whole picture. */
export const SCOUT_ALWAYS_GRANTED_ROWS: { label: string; description: string }[] = [
    { label: 'Notebooks', description: 'Every scout can write notebooks' },
    { label: 'Inbox and memory', description: 'Its reports, findings, and shared scout memory' },
]

/** Short labels for the scopes a scout holds, for the settings header and the roster row. */
export function scoutWriteScopeLabels(scopes: readonly string[] | undefined): string[] {
    return SCOUT_WRITE_SCOPE_ROWS.filter((row) => scopes?.includes(row.scope)).map((row) => row.label)
}

/** The scopes the picker offers a row for, in row order. Anything else stored on a config is stale. */
export function offeredScoutWriteScopes(scopes: readonly string[]): string[] {
    return SCOUT_WRITE_SCOPE_ROWS.filter((row) => scopes.includes(row.scope)).map((row) => row.scope)
}
