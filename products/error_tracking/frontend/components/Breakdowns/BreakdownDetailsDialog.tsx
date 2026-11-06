import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { PieChart } from '@posthog/quill-charts'
import type { PieChartConfig, Series } from '@posthog/quill-charts'

import { useChartTheme } from 'lib/charts/hooks'
import { Button, Dialog, DialogBody, DialogContent, DialogHeader, DialogTitle, Skeleton, Text } from 'lib/ui/quill'
import { humanFriendlyLargeNumber } from 'lib/utils/numbers'
import { BREAKDOWN_NULL_DISPLAY, BREAKDOWN_OTHER_DISPLAY, isNullBreakdown } from 'scenes/insights/utils'

import { PropertyOperator } from '~/types'

import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import {
    BreakdownSinglePropertyStat,
    getBreakdownForPropertyFromResponse,
    miniBreakdownsLogic,
} from './miniBreakdownsLogic'

const PIE_CONFIG: PieChartConfig = {
    innerRadiusRatio: 0.55,
    showLabelOnSlice: false,
    showValueOnSlice: false,
}

export function BreakdownDetailsDialog(): JSX.Element {
    const theme = useChartTheme()
    const { selectedBreakdownProperty, breakdownDetails, breakdownDetailsLoading, breakdownDetailsError } =
        useValues(miniBreakdownsLogic)
    const { closeBreakdownDetails, loadBreakdownDetails } = useActions(miniBreakdownsLogic)
    const { applyPropertyFilter } = useActions(issueFilterPreviewLogic)
    const { properties, totalCount } = getBreakdownForPropertyFromResponse(
        breakdownDetails,
        selectedBreakdownProperty?.property ?? ''
    )
    const selectBreakdownValue = (item: BreakdownSinglePropertyStat): void => {
        // "Other" is a synthetic bucket for values beyond the query limit, not a real property
        // value, so filtering exactly on its label would match no exceptions.
        if (!selectedBreakdownProperty || item.label === BREAKDOWN_OTHER_DISPLAY) {
            return
        }
        applyPropertyFilter(
            selectedBreakdownProperty.property,
            isNullBreakdown(item.label) ? null : item.label,
            isNullBreakdown(item.label) ? PropertyOperator.IsNotSet : PropertyOperator.Exact
        )
        closeBreakdownDetails()
    }
    const series = useMemo<Series<BreakdownSinglePropertyStat>[]>(
        () =>
            properties.map((item, index) => ({
                key: `${item.label}:${index}`,
                label: isNullBreakdown(item.label) ? BREAKDOWN_NULL_DISPLAY : item.label,
                data: [item.count],
                meta: item,
            })),
        [properties]
    )

    return (
        <Dialog open={selectedBreakdownProperty !== null} onOpenChange={(open) => !open && closeBreakdownDetails()}>
            <DialogContent size="wide" className="max-w-3xl">
                <DialogHeader>
                    <DialogTitle>Property breakdown</DialogTitle>
                </DialogHeader>
                <DialogBody>
                    {breakdownDetailsError ? (
                        <div className="flex min-h-64 flex-col items-center justify-center gap-2">
                            <Text variant="destructive">Couldn’t load the breakdown values.</Text>
                            <Button
                                variant="outline"
                                loading={breakdownDetailsLoading}
                                onClick={() => {
                                    if (selectedBreakdownProperty) {
                                        loadBreakdownDetails({ property: selectedBreakdownProperty.property })
                                    }
                                }}
                            >
                                Try again
                            </Button>
                        </div>
                    ) : breakdownDetailsLoading ? (
                        <div className="grid min-h-80 grid-cols-1 gap-4 md:grid-cols-[20rem_minmax(0,1fr)]">
                            <div className="mx-auto flex aspect-square w-full max-w-80 items-center justify-center">
                                <Skeleton className="aspect-square w-4/5 rounded-full bg-border" />
                            </div>
                            <div className="flex min-w-0 flex-col gap-2 border-t border-primary pt-4 md:border-l md:border-t-0 md:py-1 md:pl-4">
                                <Skeleton className="h-5 w-32 bg-border" />
                                {Array.from({ length: 7 }, (_, index) => (
                                    <Skeleton key={index} className="h-8 w-full bg-border" />
                                ))}
                            </div>
                        </div>
                    ) : properties.length === 0 ? (
                        <div className="flex min-h-64 items-center justify-center">
                            <Text variant="muted">No values found.</Text>
                        </div>
                    ) : (
                        <div className="grid min-h-80 grid-cols-1 gap-4 md:grid-cols-[20rem_minmax(0,1fr)]">
                            <div className="mx-auto flex aspect-square w-full max-w-80 min-w-0 flex-col">
                                <PieChart
                                    series={series}
                                    theme={theme}
                                    config={PIE_CONFIG}
                                    onSliceClick={({ series: clickedSeries }) => {
                                        if (clickedSeries.meta) {
                                            selectBreakdownValue(clickedSeries.meta)
                                        }
                                    }}
                                    centerLabel={
                                        <div className="text-center">
                                            <div className="text-xl font-semibold tabular-nums">
                                                {humanFriendlyLargeNumber(totalCount)}
                                            </div>
                                            <Text size="xs" variant="muted">
                                                occurrences
                                            </Text>
                                        </div>
                                    }
                                />
                            </div>
                            <div className="min-w-0 border-t border-primary pt-4 md:border-l md:border-t-0 md:pl-4 md:pt-0">
                                <Text size="sm" weight="semibold" className="pb-2">
                                    {selectedBreakdownProperty?.title ?? 'Property'}
                                </Text>
                                <div className="max-h-72 overflow-y-auto">
                                    {properties.map((item, index) => (
                                        <button
                                            key={`${item.label}:${index}`}
                                            type="button"
                                            disabled={item.label === BREAKDOWN_OTHER_DISPLAY}
                                            className={`flex h-8 w-full items-center justify-between gap-3 border-b border-primary px-1 text-left ${
                                                item.label === BREAKDOWN_OTHER_DISPLAY
                                                    ? 'cursor-default'
                                                    : 'hover:bg-fill-button-tertiary-hover focus-visible:ring-2 focus-visible:ring-primary'
                                            }`}
                                            onClick={() => selectBreakdownValue(item)}
                                        >
                                            <Text size="xs" className="min-w-0 truncate" title={item.label}>
                                                {isNullBreakdown(item.label) ? BREAKDOWN_NULL_DISPLAY : item.label}
                                            </Text>
                                            <div className="shrink-0 text-right">
                                                <Text
                                                    size="xs"
                                                    weight="medium"
                                                    render={<span />}
                                                    className="tabular-nums"
                                                >
                                                    {humanFriendlyLargeNumber(item.count)}
                                                </Text>
                                                <Text
                                                    size="xxs"
                                                    variant="muted"
                                                    render={<span />}
                                                    className="ms-1 tabular-nums"
                                                >
                                                    {totalCount > 0
                                                        ? `${((item.count / totalCount) * 100).toFixed(1)}%`
                                                        : '0%'}
                                                </Text>
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            </div>
                        </div>
                    )}
                </DialogBody>
            </DialogContent>
        </Dialog>
    )
}
