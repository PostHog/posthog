import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconStarFilled } from '@posthog/icons'
import { Dot, Skeleton, Text } from '@posthog/quill'

import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { MetricGoalApi } from './generated/api.schemas'
import { GOAL_STATUS_LABEL, type GoalStatus, goalStatus, goalText } from './releaseGoals'
import { releaseLogic } from './releaseLogic'
import { ReleaseMetricGoalDialog } from './ReleaseMetricGoalDialog'
import { type ReleaseMetric, releaseMetricsLogic } from './releaseMetricsLogic'
import { ReleaseMetricSparkline } from './ReleaseMetricSparkline'
import { ReleaseMetricTileMenu } from './ReleaseMetricTileMenu'
import { ReleaseMetricTileName } from './ReleaseMetricTileName'
import { ReleaseRow } from './releaseUtils'

function valueText(metric: Extract<ReleaseMetric, { status: 'ready' }> | null): string {
    return metric?.value == null ? '–' : humanFriendlyNumber(metric.value)
}

const STATUS_DOT: Record<GoalStatus, 'success' | 'destructive' | 'default'> = {
    met: 'success',
    on_track: 'success',
    behind: 'destructive',
    no_goal: 'default',
    unmeasured: 'default',
}

export function ReleaseMetricTile({
    row,
    insightId,
    primary,
}: {
    row: ReleaseRow
    insightId: number
    primary: boolean
}): JSX.Element {
    const { metrics } = useValues(releaseMetricsLogic)
    const { canEditReleases } = useValues(releaseLogic)
    const { updateRelease } = useActions(releaseLogic)
    const [editingGoal, setEditingGoal] = useState(false)
    const metric = metrics[insightId]
    const ready = metric?.status === 'ready' ? metric : null
    const goal = row.metricGoals.find((item) => item.insight_id === insightId)
    const status = goalStatus(ready?.value ?? null, goal)
    const setGoal = (next: MetricGoalApi | null): void => {
        const others = row.metricGoals.filter((item) => item.insight_id !== insightId)
        updateRelease(row.id, { metric_goals: next ? [...others, next] : others })
        setEditingGoal(false)
    }

    return (
        <div className="group flex min-w-0 flex-col gap-0.5" data-attr="release-metric">
            <div className="flex min-w-0 items-center gap-1">
                {primary && <IconStarFilled className="size-3 shrink-0 text-muted-foreground" aria-label="Primary" />}
                <ReleaseMetricTileName insightId={insightId} metric={metric} />
                {canEditReleases && (
                    <ReleaseMetricTileMenu
                        row={row}
                        insightId={insightId}
                        primary={primary}
                        hasGoal={!!goal}
                        onEditGoal={() => setEditingGoal(true)}
                    />
                )}
            </div>
            <div className="flex min-w-0 items-baseline gap-2">
                <span className="text-[19px] leading-tight font-semibold tracking-tight tabular-nums" translate="no">
                    {metric?.status === 'loading' || !metric ? <Skeleton className="h-5 w-14" /> : valueText(ready)}
                </span>
                {goal && ready && (
                    <Text size="xs" variant="muted" className="flex min-w-0 items-center gap-1 truncate">
                        <Dot variant={STATUS_DOT[status]} />
                        {GOAL_STATUS_LABEL[status]} · {goalText(goal).toLowerCase()}
                    </Text>
                )}
            </div>
            <div className="h-10">
                {ready && ready.values.length > 1 && (
                    <ReleaseMetricSparkline
                        values={ready.values}
                        labels={ready.labels}
                        status={status}
                        target={goal?.value ?? null}
                    />
                )}
            </div>
            {editingGoal && (
                <ReleaseMetricGoalDialog
                    insightId={insightId}
                    metricName={ready?.name ?? 'this metric'}
                    goal={goal}
                    onSave={setGoal}
                    onClose={() => setEditingGoal(false)}
                />
            )}
        </div>
    )
}
