import { useActions, useValues } from 'kea'
import { router } from 'kea-router'

import { LemonTable } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { urls } from 'scenes/urls'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import {
    compareScoutsByName,
    SCOUT_GROUP_LABEL,
    SCOUT_GROUP_ORDER,
    scoutCadenceLabel,
    ScoutRosterRow,
} from '../../../utils/scoutGroups'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutNameCell } from './ScoutNameCell'
import { ScoutNextRunLabel } from './ScoutNextRunLabel'
import { ScoutRunBoxes } from './ScoutRunBoxes'
import { ScoutStatusDot } from './ScoutStatusDot'

/**
 * The whole troop in one alphabetical table. A scout's lifecycle is a sortable Status column rather
 * than a section heading, so finding one by name is a single scan instead of a guess at which bucket
 * the scheduler put it in.
 *
 * `compact` is the phone-width roster: Cadence and Next run drop out and their space goes to the
 * name and the run strip. Both are schedule detail rather than state, and the scout page states
 * them in full — at 375px they were 45px columns holding a truncated word each.
 */
export function ScoutsRosterTable({ compact }: { compact: boolean }): JSX.Element {
    const { rosterScouts, rollups, updatingScoutIds, scoutRunsLoadedOnce } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)

    if (rosterScouts.length === 0) {
        return <span className="px-6 py-6 text-sm text-muted">No scouts match the current filters.</span>
    }

    return (
        <LemonTable
            embedded
            size="small"
            // Compact has no room to spare, and an auto layout sizes columns to their content — the
            // run strip's fixed-width boxes alone push the table wider than a phone and the toggle
            // off the right edge. Fixed makes the percentages below binding and lets cells clip.
            tableLayout={compact ? 'fixed' : 'auto'}
            rowKey={(row: ScoutRosterRow) => row.config.id}
            dataSource={rosterScouts}
            rowClassName={(row: ScoutRosterRow) => cn('cursor-pointer', !row.config.enabled && 'opacity-65')}
            onRow={(row: ScoutRosterRow) => ({
                // The row is one big target for the scout page, but a link or button inside it
                // (a run box, the name) already navigates itself: a second push here would
                // override the run box's task URL.
                onClick: (event) => {
                    if ((event.target as HTMLElement).closest('a, button')) {
                        return
                    }
                    router.actions.push(urls.inboxScout(row.config.skill_name))
                },
            })}
            columns={[
                {
                    title: 'Scout',
                    key: 'scout',
                    width: compact ? '40%' : '34%',
                    sorter: (a: ScoutRosterRow, b: ScoutRosterRow) => compareScoutsByName(a.config, b.config),
                    render: (_, row: ScoutRosterRow) => (
                        <ScoutNameCell
                            config={row.config}
                            group={row.group}
                            rollup={rollups.get(row.config.skill_name)}
                        />
                    ),
                },
                {
                    title: 'Status',
                    key: 'status',
                    width: compact ? '26%' : '14%',
                    sorter: (a: ScoutRosterRow, b: ScoutRosterRow) =>
                        SCOUT_GROUP_ORDER.indexOf(a.group) - SCOUT_GROUP_ORDER.indexOf(b.group),
                    render: (_, row: ScoutRosterRow) => (
                        <span className="flex items-center gap-2 text-xs text-secondary">
                            <ScoutStatusDot group={row.group} />
                            {SCOUT_GROUP_LABEL[row.group]}
                        </span>
                    ),
                },
                {
                    title: 'Cadence',
                    key: 'cadence',
                    width: '12%',
                    isHidden: compact,
                    render: (_, row: ScoutRosterRow) => (
                        <span className="text-xs text-secondary">{scoutCadenceLabel(row.config)}</span>
                    ),
                },
                {
                    title: 'Next run',
                    key: 'nextRun',
                    width: '12%',
                    isHidden: compact,
                    render: (_, row: ScoutRosterRow) => (
                        <span className="text-xs text-secondary tabular-nums">
                            <ScoutNextRunLabel config={row.config} />
                        </span>
                    ),
                },
                {
                    // "Recent runs" doesn't fit the compact column, and a right-aligned header clips
                    // from its left — it would read as "ent runs".
                    title: compact ? 'Runs' : 'Recent runs',
                    key: 'runs',
                    width: compact ? '20%' : '28%',
                    // The strip is a timeline ending at "now", anchored right so every row's
                    // newest run shares one vertical line; the header follows its content.
                    align: 'right',
                    render: (_, row: ScoutRosterRow) => {
                        const runs = rollups.get(row.config.skill_name)?.runs ?? []
                        if (runs.length) {
                            return <ScoutRunBoxes runs={runs} />
                        }
                        // Until the runs request has landed once, an empty rollup means "not
                        // loaded", not "never ran"; the poll retries a failed load on its own.
                        return scoutRunsLoadedOnce ? (
                            <span className="text-xs text-muted">No runs yet</span>
                        ) : (
                            <span className="text-xs text-muted">…</span>
                        )
                    },
                },
                {
                    title: '',
                    key: 'enabled',
                    width: compact ? '14%' : '8%',
                    render: (_, row: ScoutRosterRow) => (
                        // Stop the row's navigation: flipping a scout off is not a request to
                        // open it, and landing on its page afterwards hides the row you just changed.
                        <div
                            className="flex justify-end"
                            onClick={(event) => event.stopPropagation()}
                            onKeyDown={(event) => event.stopPropagation()}
                            role="presentation"
                        >
                            <ScoutEnabledSwitch
                                config={row.config}
                                onUpdate={updateScoutConfig}
                                updating={updatingScoutIds.includes(row.config.id)}
                            />
                        </div>
                    ),
                },
            ]}
        />
    )
}
