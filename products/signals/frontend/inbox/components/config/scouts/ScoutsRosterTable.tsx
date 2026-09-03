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
import { showsScoutOwnership } from '../../../utils/scoutOwners'
import { ScoutEnabledSwitch } from './ScoutConfigControls'
import { ScoutNameCell } from './ScoutNameCell'
import { ScoutNextRunLabel } from './ScoutNextRunLabel'
import { ScoutOwnersCell } from './ScoutOwnersCell'
import { ScoutRunBoxes } from './ScoutRunBoxes'
import { ScoutStatusDot } from './ScoutStatusDot'

/**
 * The whole troop in one alphabetical table. A scout's lifecycle is a sortable Status column rather
 * than a section heading, so finding one by name is a single scan instead of a guess at which bucket
 * the scheduler put it in.
 *
 * `compact` is the phone-width roster: Owners, Cadence, and Next run drop out and their space goes
 * to the name and the run strip. All three are detail rather than state, and the scout page states
 * them in full — at 375px they were 45px columns holding a truncated word each.
 *
 * Owners drops out at full width too when the fleet holds no custom scout, since ownership has
 * nothing to say about a canonical one.
 */
export function ScoutsRosterTable({ compact }: { compact: boolean }): JSX.Element {
    const { rosterScouts, rollups, updatingScoutIds, scoutRunsLoadedOnce } = useValues(scoutFleetLogic)
    const { updateScoutConfig } = useActions(scoutFleetLogic)

    if (rosterScouts.length === 0) {
        return <span className="px-6 py-6 text-sm text-muted">No scouts match the current filters.</span>
    }

    // Only a custom scout can carry an owner, so a fleet of canonical scouts would get a header over
    // a column of blanks. It keeps the exact column set and widths it had before owners existed.
    const showOwners = !compact && rosterScouts.some((row) => showsScoutOwnership(row.config))
    const width = compact
        ? { scout: '40%', status: '26%', cadence: '12%', nextRun: '12%', runs: '20%', enabled: '14%' }
        : showOwners
          ? { scout: '28%', status: '14%', cadence: '11%', nextRun: '11%', runs: '28%', enabled: '8%' }
          : { scout: '34%', status: '14%', cadence: '12%', nextRun: '12%', runs: '28%', enabled: '8%' }

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
                    width: width.scout,
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
                    width: width.status,
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
                    // Custom scouts only, so canonical rows stay blank and read as they did before.
                    // Narrow on purpose: faces here, and the scout page names the owner in full.
                    title: 'Owners',
                    key: 'owners',
                    width: '10%',
                    isHidden: !showOwners,
                    render: (_, row: ScoutRosterRow) => <ScoutOwnersCell config={row.config} />,
                },
                {
                    title: 'Cadence',
                    key: 'cadence',
                    width: width.cadence,
                    isHidden: compact,
                    render: (_, row: ScoutRosterRow) => (
                        <span className="text-xs text-secondary">{scoutCadenceLabel(row.config)}</span>
                    ),
                },
                {
                    title: 'Next run',
                    key: 'nextRun',
                    width: width.nextRun,
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
                    width: width.runs,
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
                    width: width.enabled,
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
