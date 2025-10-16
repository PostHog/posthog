import { useActions, useValues } from 'kea'
import { useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { DataNodeLogicProps } from '~/queries/nodes/DataNode/dataNodeLogic'
import { InsightQueryNode } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { errorTrackingIssueBreakdownQuery } from '../../queries'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { BreakdownSinglePropertyStat, breakdownPreviewLogic } from './breakdownPreviewLogic'
import { BreakdownPreset, errorTrackingBreakdownsSceneLogic } from './errorTrackingBreakdownsSceneLogic'

const BREAKDOWN_COLORS = ['#3b82f6', '#22c55e', '#eab308', '#a855f7', '#ec4899', '#f97316', '#06b6d4', '#ef4444']

interface BreakdownTileButtonProps {
    item: BreakdownPreset
}

export const ERROR_TRACKING_BREAKDOWNS_DATA_COLLECTION_NODE_ID = 'error-tracking-breakdowns'

export function BreakdownTileButton({ item }: BreakdownTileButtonProps): JSX.Element {
    const { dateRange, filterTestAccounts } = useValues(breakdownFiltersLogic)
    const { selectedBreakdownPreset } = useValues(errorTrackingBreakdownsSceneLogic)
    const { setSelectedBreakdownPreset } = useActions(errorTrackingBreakdownsSceneLogic)

    const isSelected = selectedBreakdownPreset.property === item.property
    const { issueId } = useValues(errorTrackingBreakdownsSceneLogic)

    const query = errorTrackingIssueBreakdownQuery({
        breakdownProperty: item.property,
        dateRange: dateRange,
        filterTestAccounts: filterTestAccounts,
        filterGroup: { type: FilterLogicalOperator.And, values: [{ type: FilterLogicalOperator.And, values: [] }] },
        issueId,
    })

    return (
        <button
            onClick={() => setSelectedBreakdownPreset(item)}
            className={cn(
                'w-full p-2.5 text-left transition-all cursor-pointer border-l-[3px]',
                isSelected ? 'border-l-brand-yellow' : 'border-l-transparent'
            )}
        >
            <BreakdownPreview query={query.source} title={item.title} />
        </button>
    )
}

interface BreakdownPreviewProps {
    query: InsightQueryNode
    title: string
}

const LIMIT_ITEMS = 3

function BreakdownPreview({ query, title }: BreakdownPreviewProps): JSX.Element {
    const key = `BreakdownPreview.${title}`
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query,
        key: key,
        dataNodeCollectionId: ERROR_TRACKING_BREAKDOWNS_DATA_COLLECTION_NODE_ID,
    }
    const logic = breakdownPreviewLogic({ dataNodeLogicProps, limitItems: LIMIT_ITEMS })
    const { properties, totalCount, responseLoading } = useValues(logic)

    return (
        <div className="flex flex-col gap-2">
            <div className="font-semibold text-sm">{title}</div>
            {responseLoading ? (
                <div className="flex items-center justify-center h-6">
                    <Spinner className="text-xs" />
                </div>
            ) : properties.length === 0 ? (
                <div className="text-muted text-xs flex items-center justify-center h-6">No data</div>
            ) : (
                <StackedBar properties={properties} totalCount={totalCount} />
            )}
        </div>
    )
}

interface StackedBarProps {
    properties: BreakdownSinglePropertyStat[]
    totalCount: number
}

function StackedBar({ properties, totalCount }: StackedBarProps): JSX.Element {
    const [hoveredIndex, setHoveredIndex] = useState<number | null>(null)
    const [tooltipPosition, setTooltipPosition] = useState({ x: 0, y: 0 })

    const handleMouseEnter = (index: number, event: React.MouseEvent<HTMLDivElement>): void => {
        setHoveredIndex(index)
        const rect = event.currentTarget.getBoundingClientRect()
        setTooltipPosition({
            x: rect.left + rect.width / 2,
            y: rect.top,
        })
    }

    return (
        <div className="relative">
            <div className="flex w-full h-6 rounded overflow-hidden bg-fill-secondary">
                {properties.map((item, index) => {
                    const percentage = (item.count / totalCount) * 100

                    return (
                        <div
                            key={index}
                            className="h-full transition-all hover:opacity-80 cursor-pointer"
                            style={{
                                width: `${percentage}%`,
                                backgroundColor: BREAKDOWN_COLORS[index % BREAKDOWN_COLORS.length],
                            }}
                            onMouseEnter={(e) => handleMouseEnter(index, e)}
                            onMouseLeave={() => setHoveredIndex(null)}
                        />
                    )
                })}
            </div>
            {hoveredIndex !== null && (
                <div
                    className="fixed px-2 py-1 bg-bg-3000 border border-border rounded shadow-lg whitespace-nowrap z-[9999] text-xs pointer-events-none"
                    style={{
                        left: `${tooltipPosition.x}px`,
                        top: `${tooltipPosition.y - 8}px`,
                        transform: 'translate(-50%, -100%)',
                    }}
                >
                    <div className="font-semibold">{properties[hoveredIndex].label}</div>
                    <div className="text-muted">
                        {((properties[hoveredIndex].count / totalCount) * 100).toFixed(1)}%
                    </div>
                </div>
            )}
        </div>
    )
}
