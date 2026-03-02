import { useActions, useValues } from 'kea'

import { IconChevronLeft, IconChevronRight } from '@posthog/icons'
import { LemonButton, LemonSegmentedButton } from '@posthog/lemon-ui'

import { InsightsViewMode, errorTrackingInsightsLogic } from './errorTrackingInsightsLogic'

export function TimeRangeControls(): JSX.Element {
    const { viewMode, dateLabel, relativeDateLabel, canNavigateForward } = useValues(errorTrackingInsightsLogic)
    const { setViewMode, navigateBack, navigateForward } = useActions(errorTrackingInsightsLogic)

    return (
        <div className="flex items-center gap-2">
            <LemonSegmentedButton
                size="small"
                value={viewMode}
                onChange={(value) => setViewMode(value as InsightsViewMode)}
                options={[
                    { value: 'week', label: 'Week' },
                    { value: 'month', label: 'Month' },
                ]}
            />
            <div className="flex items-center gap-1">
                <LemonButton size="small" icon={<IconChevronLeft />} onClick={navigateBack} />
                <span className="text-sm font-medium min-w-48 text-center select-none">
                    {dateLabel}
                    <span className="text-secondary font-normal ml-1">({relativeDateLabel})</span>
                </span>
                <LemonButton
                    size="small"
                    icon={<IconChevronRight />}
                    onClick={navigateForward}
                    disabledReason={!canNavigateForward ? "You're viewing the current period" : undefined}
                />
            </div>
        </div>
    )
}
