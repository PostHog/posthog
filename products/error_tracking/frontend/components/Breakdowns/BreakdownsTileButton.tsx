import { useActions, useValues } from 'kea'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { InsightQueryNode } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { errorTrackingIssueBreakdownQuery } from '../../queries'
import { errorTrackingIssueSceneLogic } from '../../scenes/ErrorTrackingIssueScene/errorTrackingIssueSceneLogic'
import { BreakdownsStackedBar } from './BreakdownsStackedBar'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { breakdownPreviewLogic } from './breakdownPreviewLogic'
import {
    BreakdownPreset,
    ERROR_TRACKING_BREAKDOWNS_DATA_COLLECTION_NODE_ID,
    POSTHOG_BREAKDOWN_NULL_VALUE,
} from './consts'
import { errorTrackingBreakdownsLogic } from './errorTrackingBreakdownsLogic'

interface BreakdownsTileButtonProps {
    item: BreakdownPreset
}

export function BreakdownsTileButton({ item }: BreakdownsTileButtonProps): JSX.Element {
    const { dateRange, filterTestAccounts } = useValues(breakdownFiltersLogic)
    const { breakdownProperty, issueId } = useValues(errorTrackingBreakdownsLogic)
    const { setBreakdownProperty } = useActions(errorTrackingBreakdownsLogic)
    const { category } = useValues(errorTrackingIssueSceneLogic)
    const { setCategory } = useActions(errorTrackingIssueSceneLogic)

    const isSelected = category === 'breakdowns' && breakdownProperty === item.property

    const query = errorTrackingIssueBreakdownQuery({
        breakdownProperty: item.property,
        dateRange: dateRange,
        filterTestAccounts: filterTestAccounts,
        filterGroup: { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: [] }] },
        issueId,
    })

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
            <BreakdownPreview query={query.source} title={item.title} property={item.property} />
        </button>
    )
}

function BreakdownPreview({
    query,
    title,
    property,
}: {
    query: InsightQueryNode
    title: string
    property: string
}): JSX.Element {
    const key = `BreakdownPreview.${title}`
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query,
        key: key,
        dataNodeCollectionId: ERROR_TRACKING_BREAKDOWNS_DATA_COLLECTION_NODE_ID,
    }
    const logic = breakdownPreviewLogic({ dataNodeLogicProps })
    const { properties, totalCount, responseLoading } = useValues(logic)

    const hasOnlyNullBreakdown = properties.length === 1 && properties[0].label === POSTHOG_BREAKDOWN_NULL_VALUE

    return (
        <div className="flex items-center gap-2">
            <div className="font-semibold text-xs w-[30%]">{title}</div>
            <div className="w-[70%]">
                {responseLoading ? (
                    <div className="h-4 flex items-center justify-center">
                        <Spinner className="text-xs" />
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
