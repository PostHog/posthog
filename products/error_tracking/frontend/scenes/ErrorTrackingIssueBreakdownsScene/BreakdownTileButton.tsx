import { useActions, useValues } from 'kea'
import { useEffect, useMemo, useState } from 'react'

import { Spinner } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'

import { DataNodeLogicProps, dataNodeLogic } from '~/queries/nodes/DataNode/dataNodeLogic'
import { InsightQueryNode } from '~/queries/schema/schema-general'
import { FilterLogicalOperator } from '~/types'

import { errorTrackingIssueBreakdownQuery } from '../../queries'
import { breakdownFiltersLogic } from './breakdownFiltersLogic'
import { BreakdownPreset, errorTrackingBreakdownsSceneLogic } from './errorTrackingBreakdownsSceneLogic'

interface BreakdownTileButtonProps {
    item: BreakdownPreset
}

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
                'w-full p-2.5 text-left transition-all cursor-pointer border-l-[3px] h-[100px]',
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

// for example {label: "Chrome", count: 100}
interface BreakdownSinglePropertyStat {
    label: string
    count: number
}

function BreakdownPreview({ query, title }: BreakdownPreviewProps): JSX.Element {
    const [key] = useState(() => `BreakdownPreview.${title}.${Date.now()}`)
    const [breakdownData, setBreakdownData] = useState<BreakdownSinglePropertyStat[]>([])
    const dataNodeLogicProps: DataNodeLogicProps = {
        query: query,
        key: key,
        dataNodeCollectionId: key,
    }
    const logic = dataNodeLogic(dataNodeLogicProps)
    const { response, responseLoading } = useValues(logic)

    const topItems = useMemo(() => breakdownData.slice(0, 3), [breakdownData])
    const maxCount = useMemo(() => {
        return breakdownData.length > 0 ? breakdownData[0].count : 1
    }, [breakdownData])

    useEffect(() => {
        const breakdownDataTemp: BreakdownSinglePropertyStat[] = []

        if (response && 'results' in response && Array.isArray(response.results)) {
            response.results.forEach((series: any) => {
                if (series.data && series.label) {
                    breakdownDataTemp.push({
                        label: series.label,
                        count: series.aggregated_value,
                    })
                }
            })
        }

        setBreakdownData(breakdownDataTemp)
    }, [response])

    return (
        <div className="h-full flex flex-col gap-2">
            <div className="font-semibold text-sm">{title}</div>
            {responseLoading ? (
                <div className="flex items-center justify-center flex-1">
                    <Spinner className="text-xs" />
                </div>
            ) : breakdownData.length === 0 ? (
                <div className="text-muted text-xs flex items-center justify-center flex-1">No data</div>
            ) : (
                <div className="flex flex-col gap-1 flex-1 overflow-hidden">
                    {topItems.map((item, index) => (
                        <BreakdownPreviewLine key={index} item={item} maxCount={maxCount} />
                    ))}
                </div>
            )}
        </div>
    )
}

interface BreakdownPreviewLineProps {
    item: BreakdownSinglePropertyStat
    maxCount: number
}

function BreakdownPreviewLine({ item, maxCount }: BreakdownPreviewLineProps): JSX.Element {
    const percentage = ((item.count / maxCount) * 100).toFixed(0)

    return (
        <div className="flex items-center gap-1.5">
            <div className="flex items-center justify-between w-[60%]">
                <span className="text-xs truncate min-w-0">{item.label}</span>
                <span className="text-xs text-muted text-right flex-shrink-0 w-[5ch]">{percentage}%</span>
            </div>
            <div className="flex-1 min-w-0">
                <div className="bg-fill-secondary rounded-sm overflow-hidden h-2">
                    <div
                        className="bg-muted h-full"
                        style={{
                            width: `${percentage}%`,
                        }}
                    />
                </div>
            </div>
        </div>
    )
}
