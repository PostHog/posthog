import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutCostLineParts, scoutCostWindowLabel } from '../../../utils/scoutCosts'
import { nextRunAt, scoutGroup } from '../../../utils/scoutGroups'
import { ScoutRollup, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
import { ScoutStatusTag } from './ScoutBadges'
import { ScoutCadenceLabel } from './ScoutCadenceLabel'
import { ScoutNextRunLabel } from './ScoutNextRunLabel'
import { ScoutRunBoxes } from './ScoutRunBoxes'
import { ScoutStatusDot } from './ScoutStatusDot'

/**
 * One labelled group of the strip. The window each group describes is not the same — run counts
 * cover the last 25 runs, cost covers the last 7 days — so each carries the definition its tile
 * label used to carry, as a tooltip.
 */
function Segment({ tooltip, children }: { tooltip: string; children: React.ReactNode }): JSX.Element {
    return (
        <Tooltip title={tooltip}>
            <div className="flex min-w-0 items-center gap-1.5 border-r border-primary pr-3 last:border-r-0 last:pr-0">
                {children}
            </div>
        </Tooltip>
    )
}

/**
 * Whether a scout is worth keeping on, in one wrapping row: where it stands, how its recent runs
 * went, what it filed, what it cost, and how much steering it carries.
 *
 * This replaces a grid of equal-weight tiles plus a prose summary that restated them. The two could
 * disagree, and the failed-run count — the thing a reader opens this page for — only appeared in the
 * prose. Here it sits next to the run strip, in the same vocabulary the roster uses.
 */
export function ScoutHealthStrip({
    config,
    rollup,
    noteCount,
    learnedCount,
}: {
    config: SignalScoutConfig
    rollup: ScoutRollup | undefined
    noteCount: number
    learnedCount: number
}): JSX.Element {
    const { scoutRunCosts, scoutCostRollups, expensiveRunCostThreshold, scoutRunsLoadedOnce } =
        useValues(scoutFleetLogic)
    const { currentTeam } = useValues(teamLogic)
    const now = new Date()

    const runs = rollup?.runs ?? []
    const failed = rollup?.failedCount ?? 0
    const costRollup = scoutCostRollups.get(config.skill_name)
    // A report the scout filed and later edited counts once, as filed — adding it to both reads as
    // two reports.
    const authoredIds = rollup?.authoredReportIds ?? new Set<string>()
    const addedTo = [...(rollup?.editedReportIds ?? [])].filter((id) => !authoredIds.has(id)).length
    // Only an enabled scout has a next run; a paused one would otherwise carry an empty dash.
    const hasNextRun = nextRunAt(config, currentTeam?.timezone ?? 'UTC', now) !== null

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-secondary">
            <Segment tooltip="Where this scout stands, and when it next runs.">
                <ScoutStatusDot group={scoutGroup(config, rollup, now)} />
                <ScoutStatusTag config={config} />
                <ScoutCadenceLabel config={config} />
                {hasNextRun && (
                    <span className="tabular-nums">
                        · next run <ScoutNextRunLabel config={config} />
                    </span>
                )}
            </Segment>

            <Segment tooltip={`Runs this scout made in the ${SCOUT_RUNS_PER_SCOUT_LABEL}, quiet ones included.`}>
                {runs.length > 0 ? (
                    <>
                        <ScoutRunBoxes runs={runs} costs={scoutRunCosts} costThreshold={expensiveRunCostThreshold} />
                        <span className="whitespace-nowrap tabular-nums">{pluralize(runs.length, 'run')}</span>
                        {failed > 0 && <span className="whitespace-nowrap text-danger">· {failed} failed</span>}
                    </>
                ) : (
                    // Until the runs request has landed once, an empty rollup means "not loaded",
                    // not "never ran"; the poll retries a failed load on its own.
                    <span className="text-muted">{scoutRunsLoadedOnce ? 'No runs yet' : '…'}</span>
                )}
            </Segment>

            {(authoredIds.size > 0 || addedTo > 0) && (
                <Segment
                    tooltip={`Inbox reports this scout filed or added to in the ${SCOUT_RUNS_PER_SCOUT_LABEL}. A report it filed and later edited counts once, as filed.`}
                >
                    <span className="whitespace-nowrap tabular-nums">
                        {authoredIds.size > 0 && `${pluralize(authoredIds.size, 'report')} filed`}
                        {authoredIds.size > 0 && addedTo > 0 && ' · '}
                        {addedTo > 0 && `${addedTo} added to`}
                    </span>
                </Segment>
            )}

            {costRollup && (
                <Segment
                    tooltip={`What this scout spent on model calls in the ${scoutCostWindowLabel(costRollup.windowDays)}, and what that buys per run and per report.`}
                >
                    <span className="whitespace-nowrap tabular-nums">{scoutCostLineParts(costRollup).join(' · ')}</span>
                </Segment>
            )}

            <Segment tooltip="Notes the team has left this scout, and entries it has written for itself.">
                <span className="whitespace-nowrap tabular-nums">
                    {noteCount} told · {learnedCount} learned
                </span>
            </Segment>
        </div>
    )
}
