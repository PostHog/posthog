import { useActions, useValues } from 'kea'
import posthog from 'posthog-js'

import { Tooltip as LemonTooltip } from '@posthog/lemon-ui'

import { Button, Skeleton } from 'lib/ui/quill'
import { BREAKDOWN_NULL_STRING_LABEL, isNullBreakdown } from 'scenes/insights/utils'

import { PropertyOperator } from '~/types'

import { issueFilterPreviewLogic } from '../IssueFilterPreview/issueFilterPreviewLogic'
import { BreakdownsStackedBar } from './BreakdownsStackedBar'
import { BreakdownPreset, BreakdownsEvents } from './consts'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

interface BreakdownsTileButtonProps {
    item: BreakdownPreset
}

export function BreakdownsTileButton({ item: { title, property } }: BreakdownsTileButtonProps): JSX.Element {
    const { getBreakdownForProperty, responseLoading, responseError } = useValues(miniBreakdownsLogic)
    const { loadResponse, openBreakdownDetails } = useActions(miniBreakdownsLogic)
    const { applyPropertyFilter } = useActions(issueFilterPreviewLogic)
    const { properties, totalCount } = getBreakdownForProperty(property)

    const hasOnlyNullBreakdown = properties.length === 1 && properties[0].label === BREAKDOWN_NULL_STRING_LABEL
    const hasNoData = !responseLoading && !responseError && (properties.length === 0 || hasOnlyNullBreakdown)

    return (
        <>
            <LemonTooltip title={hasNoData ? 'No data available for this property' : undefined}>
                <span className="min-w-0">
                    <Button
                        variant="default"
                        size="sm"
                        disabled={hasNoData}
                        className="h-[22px] w-full min-w-0 justify-end rounded-none border-r border-border ps-2.5 pe-2 text-right text-xs font-semibold"
                        onClick={() => {
                            openBreakdownDetails({ property, title })
                            posthog.capture(BreakdownsEvents.MiniBreakdownsPropertySelected, { property })
                        }}
                    >
                        <span className="truncate">{title}</span>
                    </Button>
                </span>
            </LemonTooltip>
            <div className="flex h-[22px] min-w-0 items-center ps-2 pe-4">
                {responseError ? (
                    <LemonTooltip title={responseError}>
                        <button
                            className="text-danger flex h-6 w-full items-center justify-center text-xs underline decoration-dotted"
                            onClick={(event) => {
                                event.stopPropagation()
                                loadResponse()
                            }}
                        >
                            Failed to load, click to retry
                        </button>
                    </LemonTooltip>
                ) : responseLoading ? (
                    <div className="flex h-3 w-full items-center justify-center">
                        <Skeleton className="h-3 w-full rounded-sm bg-border">
                            <span>Loading…</span>
                        </Skeleton>
                    </div>
                ) : hasNoData ? (
                    <div className="text-muted flex h-6 items-center justify-center text-xs">No data</div>
                ) : (
                    <BreakdownsStackedBar
                        properties={properties}
                        totalCount={totalCount}
                        propertyName={property}
                        propertyLabel={title}
                        onValueClick={(item) => {
                            applyPropertyFilter(
                                property,
                                isNullBreakdown(item.label) ? null : item.label,
                                isNullBreakdown(item.label) ? PropertyOperator.IsNotSet : PropertyOperator.Exact
                            )
                        }}
                    />
                )}
            </div>
        </>
    )
}
