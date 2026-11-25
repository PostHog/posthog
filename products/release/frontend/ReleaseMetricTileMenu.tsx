import { useActions } from 'kea'

import { IconEllipsis, IconStar, IconTarget, IconTrash } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { releaseLogic } from './releaseLogic'
import { ReleaseRow } from './releaseUtils'

export function ReleaseMetricTileMenu({
    row,
    insightId,
    primary,
    hasGoal,
    onEditGoal,
}: {
    row: ReleaseRow
    insightId: number
    primary: boolean
    hasGoal: boolean
    onEditGoal: () => void
}): JSX.Element {
    const { updateRelease } = useActions(releaseLogic)
    const others = row.metricInsightIds.filter((id) => id !== insightId)

    return (
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
                <DropdownMenuItem onClick={onEditGoal} data-attr="release-metric-goal">
                    <IconTarget />
                    {hasGoal ? 'Edit goal' : 'Set a goal'}
                </DropdownMenuItem>
                {!primary && (
                    <DropdownMenuItem
                        onClick={() => updateRelease(row.id, { metric_insight_ids: [insightId, ...others] })}
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
                        updateRelease(row.id, {
                            metric_insight_ids: others,
                            metric_goals: row.metricGoals.filter((goal) => goal.insight_id !== insightId),
                        })
                    }
                    data-attr="release-metric-remove"
                >
                    <IconTrash />
                    Remove metric
                </DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
