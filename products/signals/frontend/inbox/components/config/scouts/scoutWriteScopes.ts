import type { UserBasicType } from '~/types'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

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
 * `posthog/temporal/oauth.py`. A scope the backend drops from the allowlist keeps working here as a
 * stored value the picker shows unticked, and a scope added there needs a row added here to be
 * offered. Descriptions say what the scope reaches, because each one covers update and delete of
 * every object of its kind in the project, not only the ones the scout made.
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
        description: 'Add, edit, and remove annotations on charts',
    },
    {
        scope: 'alert:write',
        group: 'Monitoring',
        label: 'Alerts',
        description: 'Create, update, delete, and test insight alerts',
    },
]

/** What every scout can write, whatever its grant. Shown so the picker is the whole picture. */
export const SCOUT_ALWAYS_GRANTED_ROWS: { label: string; description: string }[] = [
    { label: 'Notebooks', description: 'Every scout can write notebooks' },
    { label: 'Inbox and memory', description: 'Its reports, findings, and its own notes' },
]

/** Short labels for the scopes a scout holds, for the settings header and the roster row. */
export function scoutWriteScopeLabels(scopes: readonly string[] | undefined): string[] {
    return SCOUT_WRITE_SCOPE_ROWS.filter((row) => scopes?.includes(row.scope)).map((row) => row.label)
}

/**
 * Whether this viewer is known not to be allowed to change a scout's write access.
 *
 * The API accepts the change from a scout owner or a project admin, and from the person who
 * authored a scout that has no owners recorded. The last one can't be answered here, so an
 * unanswerable case stays enabled and the API gets to refuse it. Only a case we can prove is
 * disabled, which keeps the disabled state from lying.
 */
export function scoutWriteAccessDisabledReason(
    config: SignalScoutConfig,
    { isProjectAdmin, currentUserUuid }: { isProjectAdmin: boolean; currentUserUuid?: string }
): string | undefined {
    const owners = (config.owners ?? []) as UserBasicType[]
    if (isProjectAdmin || owners.length === 0) {
        return undefined
    }
    if (currentUserUuid && owners.some((owner) => owner.uuid === currentUserUuid)) {
        return undefined
    }
    const names = owners.map((owner) => owner.first_name || owner.email).join(', ')
    return `Only this scout's owners (${names}) or a project admin can change its write access`
}
