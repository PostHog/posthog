import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { IconEllipsis, IconStar, IconStarFilled, IconTarget, IconTrash } from '@posthog/icons'
import {
    Button,
    Dot,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    Skeleton,
    Text,
} from '@posthog/quill'

import { LinkPrimitive } from 'lib/lemon-ui/Link'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

import { InsightShortId } from '~/types'

import type { MetricGoalApi } from './generated/api.schemas'
import { GOAL_STATUS_LABEL, type GoalStatus, goalStatus, goalText } from './releaseGoals'
import { releaseLogic } from './releaseLogic'
import { ReleaseMetricGoalDialog } from './ReleaseMetricGoalDialog'
import { releaseMetricsLogic } from './releaseMetricsLogic'
import { ReleaseMetricSparkline } from './ReleaseMetricSparkline'
import { ReleaseRow } from './releaseUtils'

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
    const { loadMetrics } = useActions(releaseMetricsLogic)
    const [editingGoal, setEditingGoal] = useState(false)
    const metric = metrics[insightId]
    const ready = metric?.status === 'ready' ? metric : null
    const ids = row.metricInsightIds
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
                {ready ? (
                    <LinkPrimitive
                        to={urls.insightView(ready.shortId as InsightShortId)}
                        className="truncate text-[13px] text-muted-foreground hover:text-foreground hover:underline"
                    >
                        {ready.name}
                    </LinkPrimitive>
                ) : metric?.status === 'failed' ? (
                    <Text size="xs" variant="muted" className="flex items-center gap-1">
                        This metric could not load.
                        <Button
                            size="xs"
                            variant="link-muted"
                            onClick={() => loadMetrics([insightId])}
                            data-attr="release-metric-retry"
                        >
                            Try again
                        </Button>
                    </Text>
                ) : (
                    <Skeleton className="h-3 w-32" />
                )}
                {canEditReleases && (
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={
                                <Button
                                    size="icon-xs"
                                    variant="default"
                                    className="ml-auto shrink-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[popup-open]:opacity-100"
                                    aria-label="Metric actions"
                                    data-attr="release-metric-menu"
                                />
                            }
                        >
                            <IconEllipsis />
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="end">
                            <DropdownMenuItem onClick={() => setEditingGoal(true)} data-attr="release-metric-goal">
                                <IconTarget />
                                {goal ? 'Edit goal' : 'Set a goal'}
                            </DropdownMenuItem>
                            {!primary && (
                                <DropdownMenuItem
                                    onClick={() =>
                                        updateRelease(row.id, {
                                            metric_insight_ids: [insightId, ...ids.filter((id) => id !== insightId)],
                                        })
                                    }
                                    data-attr="release-metric-make-primary"
                                >
                                    <IconStar />
                                    Make primary
                                </DropdownMenuItem>
                            )}
                            <DropdownMenuSeparator />
                            <DropdownMenuItem
                                variant="destructive"
                                onClick={() =>
                                    updateRelease(row.id, { metric_insight_ids: ids.filter((id) => id !== insightId) })
                                }
                                data-attr="release-metric-remove"
                            >
                                <IconTrash />
                                Remove metric
                            </DropdownMenuItem>
                        </DropdownMenuContent>
                    </DropdownMenu>
                )}
            </div>
            <div className="flex min-w-0 items-baseline gap-2">
                <span className="text-[19px] leading-tight font-semibold tracking-tight tabular-nums" translate="no">
                    {ready ? (
                        ready.value === null ? (
                            '–'
                        ) : (
                            humanFriendlyNumber(ready.value)
                        )
                    ) : metric?.status === 'failed' ? (
                        '–'
                    ) : (
                        <Skeleton className="h-5 w-14" />
                    )}
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
