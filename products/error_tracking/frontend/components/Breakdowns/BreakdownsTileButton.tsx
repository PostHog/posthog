import { useActions, useValues } from 'kea'

import { LemonSkeleton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { BREAKDOWN_NULL_STRING_LABEL } from 'scenes/insights/utils'

import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { BreakdownsStackedBar } from './BreakdownsStackedBar'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { BreakdownPreset } from './consts'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

interface BreakdownsTileButtonProps {
    item: BreakdownPreset
}

export function BreakdownsTileButton({ item }: BreakdownsTileButtonProps): JSX.Element {
    const { breakdownProperty } = useValues(breakdownFiltersLogic)
    const { setBreakdownProperty } = useActions(breakdownFiltersLogic)
    const { category } = useValues(errorTrackingIssueSceneLogic)
    const { setCategory } = useActions(errorTrackingIssueSceneLogic)

    const isSelected = category === 'breakdowns' && breakdownProperty === item.property

    return (
        <button
            onClick={() => {
                setBreakdownProperty(item.property)
                setCategory('breakdowns')
            }}
            className={cn(
                'w-full px-2.5 py-2 text-left border-l-[3px] cursor-pointer',
                isSelected ? 'border-l-brand-yellow' : 'border-l-transparent'
            )}
        >
            <BreakdownPreview title={item.title} property={item.property} />
        </button>
    )
}

function BreakdownPreview({ title, property }: { title: string; property: string }): JSX.Element {
    const { getBreakdownForProperty, responseLoading } = useValues(miniBreakdownsLogic)
    const { properties, totalCount } = getBreakdownForProperty(property)

    const hasOnlyNullBreakdown = properties.length === 1 && properties[0].label === BREAKDOWN_NULL_STRING_LABEL

    return (
        <div className="flex items-center gap-2">
            <div className="font-semibold text-xs w-[30%]">{title}</div>
            <div className="w-[70%]">
                {responseLoading ? (
                    <div className="h-4 flex items-center justify-center">
                        <LemonSkeleton />
                    </div>
                ) : properties.length === 0 || hasOnlyNullBreakdown ? (
                    <div className="text-muted text-xs h-4 flex items-center justify-center">No data</div>
                ) : (
                    <BreakdownsStackedBar properties={properties} totalCount={totalCount} propertyName={property} />
                )}
            </div>
        </div>
    )
}
