import { IconCheck } from '@posthog/icons'
import { LemonSwitch } from '@posthog/lemon-ui'

import { offeredScoutWriteScopes, SCOUT_ALWAYS_GRANTED_ROWS, SCOUT_WRITE_SCOPE_ROWS } from './scoutWriteScopes'

interface ScoutWriteScopesPickerProps {
    /** Scopes this scout currently holds (`write_scopes`). */
    selectedScopes: string[]
    onChange: (scopes: string[]) => void
    /** Compact rows matching the inline scout settings form; the default suits the create dialog. */
    compact?: boolean
    disabledReason?: string
}

/**
 * Per-scout picker for the write access a scout's runs carry, persisted as the config's
 * `write_scopes`. One switch per object a scout can be trusted with, grouped by the part of PostHog
 * it belongs to. Reads and the inbox are the same for every scout, so only the grant is offered.
 */
export function ScoutWriteScopesPicker({
    selectedScopes,
    onChange,
    compact,
    disabledReason,
}: ScoutWriteScopesPickerProps): JSX.Element {
    const groups = [...new Set(SCOUT_WRITE_SCOPE_ROWS.map((row) => row.group))]
    const toggleScope = (scope: string, granted: boolean): void => {
        // A stored scope with no row here would ride along into the save and get the whole update
        // rejected by the API, with no switch to clear it. The token already drops it at mint time.
        const held = offeredScoutWriteScopes(selectedScopes)
        onChange(granted ? [...held, scope] : held.filter((offered) => offered !== scope))
    }

    return (
        <div className="flex flex-col gap-2">
            <p className={compact ? 'text-[11.5px] text-muted mb-0' : 'text-xs text-secondary mb-0'}>
                Scouts can always read your project and write to the inbox. Grant write access only for the things this
                scout maintains.
            </p>
            {groups.map((group) => (
                <div key={group} className="flex flex-col gap-1">
                    <span className="text-[11px] font-medium uppercase tracking-wide text-muted">{group}</span>
                    {SCOUT_WRITE_SCOPE_ROWS.filter((row) => row.group === group).map((row) => (
                        <div key={row.scope} className="flex items-center justify-between gap-3">
                            <div className="flex min-w-0 flex-col">
                                <span className={compact ? 'text-xs text-default' : 'text-sm text-default'}>
                                    {row.label}
                                </span>
                                <span className="text-[11.5px] text-muted">{row.description}</span>
                            </div>
                            <LemonSwitch
                                size="small"
                                checked={selectedScopes.includes(row.scope)}
                                disabledReason={disabledReason}
                                onChange={(checked) => toggleScope(row.scope, checked)}
                                aria-label={`Let this scout write ${row.label.toLowerCase()}`}
                            />
                        </div>
                    ))}
                </div>
            ))}
            <div className="flex flex-col gap-1">
                <span className="text-[11px] font-medium uppercase tracking-wide text-muted">Always granted</span>
                {SCOUT_ALWAYS_GRANTED_ROWS.map((row) => (
                    <div key={row.label} className="flex items-center gap-2">
                        <IconCheck className="size-3.5 shrink-0 text-success" />
                        <span className={compact ? 'shrink-0 text-xs text-default' : 'shrink-0 text-sm text-default'}>
                            {row.label}
                        </span>
                        <span className="min-w-0 truncate text-[11.5px] text-muted">{row.description}</span>
                    </div>
                ))}
            </div>
            {selectedScopes.length > 0 && (
                <p className="text-[11.5px] text-warning mb-0">
                    Write access covers the whole project. A scout that can write dashboards can change or delete any
                    dashboard here, not only ones it created. Annotations also include organization-wide ones that other
                    projects see. Deleted dashboards, insights, and annotations can be restored. Deleted alerts cannot.
                    Changes apply from the scout's next run.
                </p>
            )}
        </div>
    )
}
