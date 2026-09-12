import { useValues } from 'kea'

import { Tooltip } from '@posthog/lemon-ui'

import { pluralize } from 'lib/utils/strings'
import { teamLogic } from 'scenes/teamLogic'

import type { SignalScoutConfigApi as SignalScoutConfig } from 'products/signals/frontend/generated/api.schemas'

import { scoutFleetLogic } from '../../../logics/scoutFleetLogic'
import { scoutCostLineParts, scoutCostWindowLabel } from '../../../utils/scoutCosts'
import { nextRunAt, SCOUT_GROUP_LABEL, ScoutGroupKey, scoutGroup } from '../../../utils/scoutGroups'
import { filedOrAddedLabel, ScoutRollup, SCOUT_RUNS_PER_SCOUT_LABEL } from '../../../utils/scoutRunsWindow'
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

/** The groups `ScoutStatusTag` cannot tell apart: it reads "On patrol" for each of them. */
const TAG_SILENT_GROUPS: ScoutGroupKey[] = ['working', 'watching', 'settling_in']

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
    // Shared with the run rows, so the strip cannot word the same report activity differently.
    const reportLabel = filedOrAddedLabel(rollup?.authoredReportIds ?? [], rollup?.editedReportIds ?? [])
    // Only an enabled scout has a next run; a paused one would otherwise carry an empty dash.
    const hasNextRun = nextRunAt(config, currentTeam?.timezone ?? 'UTC', now) !== null
    const group = scoutRunsLoadedOnce ? scoutGroup(config, rollup, now) : null

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 text-xs text-secondary">
            <Segment tooltip="Where this scout stands, and when it next runs.">
                {/* The dot's group is read off the run window, so an unloaded rollup would show a
                    scout that files plenty as "nothing worth filing", and it would keep saying so
                    for as long as the runs request fails. The tag beside it is config-only, so it
                    stays right either way. */}
                {group && (
                    <>
                        <ScoutStatusDot group={group} />
                        {/* Named in text, not colour alone: a reader would otherwise have to hover
                            an 8px dot to tell a producing scout from a quiet or a brand-new one.
                            The roster pairs the dot with this same label. */}
                        {TAG_SILENT_GROUPS.includes(group) && (
                            <span className="whitespace-nowrap">{SCOUT_GROUP_LABEL[group]}</span>
                        )}
                    </>
                )}
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
                        {/* The counts here and below change while the page is open, so each number
                            gets its own element — see "Rule 7" in frontend/src/AGENTS.md for what a
                            translated page does to a bare text node that has siblings. */}
                        {failed > 0 && (
                            <span className="whitespace-nowrap text-danger">
                                · <span translate="no">{failed}</span> failed
                            </span>
                        )}
                    </>
                ) : (
                    // Until the runs request has landed once, an empty rollup means "not loaded",
                    // not "never ran"; the poll retries a failed load on its own.
                    <span className="text-muted">{scoutRunsLoadedOnce ? 'No runs yet' : '…'}</span>
                )}
            </Segment>

            {reportLabel && (
                <Segment
                    tooltip={`Inbox reports this scout filed or added to in the ${SCOUT_RUNS_PER_SCOUT_LABEL}. A report it filed and later edited counts once, as filed.`}
                >
                    <span className="whitespace-nowrap tabular-nums">{reportLabel}</span>
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
                    <span translate="no">{noteCount}</span> told · <span translate="no">{learnedCount}</span> learned
                </span>
            </Segment>
        </div>
    )
}
