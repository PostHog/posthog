import { useActions, useValues } from 'kea'

import { IconX } from '@posthog/icons'

import { Button, Skeleton, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'
import { BREAKDOWN_NULL_STRING_LABEL, isNullBreakdown } from 'scenes/insights/utils'

import { PropertyOperator } from '~/types'

import { ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY, issueFiltersLogic } from '../IssueFilters/issueFiltersLogic'
import { BreakdownsStackedBar } from './BreakdownsStackedBar'
import { BreakdownPreset } from './consts'
import { miniBreakdownsLogic } from './miniBreakdownsLogic'

interface BreakdownsTileButtonProps {
    item: BreakdownPreset
    onRemove?: () => void
}

export function BreakdownsTileButton({ item, onRemove }: BreakdownsTileButtonProps): JSX.Element {
    return <BreakdownPreview title={item.title} property={item.property} onRemove={onRemove} />
}

function BreakdownPreview({
    title,
    property,
    onRemove,
}: {
    title: string
    property: string
    onRemove?: () => void
}): JSX.Element {
    const { getBreakdownForProperty, responseLoading } = useValues(miniBreakdownsLogic)
    const { addPropertyFilter } = useActions(issueFiltersLogic({ logicKey: ERROR_TRACKING_ISSUE_SCENE_LOGIC_KEY }))
    const { properties, totalCount } = getBreakdownForProperty(property)

    const hasOnlyNullBreakdown = properties.length === 1 && properties[0].label === BREAKDOWN_NULL_STRING_LABEL

    return (
        <div className="flex min-h-8 items-center gap-2 px-2.5 py-1.5">
            <div className="flex w-[30%] min-w-0 items-center gap-1 text-xs font-semibold">
                <span className="truncate">{title}</span>
                {onRemove && (
                    <Tooltip>
                        <TooltipTrigger
                            render={
                                <Button
                                    variant="default"
                                    size="icon-xs"
                                    className="ml-auto shrink-0"
                                    aria-label={`Remove ${title} breakdown`}
                                    onClick={onRemove}
                                />
                            }
                        >
                            <IconX />
                        </TooltipTrigger>
                        <TooltipContent>Remove breakdown</TooltipContent>
                    </Tooltip>
                )}
            </div>
            <div className="w-[70%]">
                {responseLoading ? (
                    <div className="h-4 flex items-center justify-center">
                        <Skeleton className="h-2 w-full" />
                    </div>
                ) : properties.length === 0 || hasOnlyNullBreakdown ? (
                    <div className="text-muted text-xs h-4 flex items-center justify-center">No data</div>
                ) : (
                    <BreakdownsStackedBar
                        properties={properties}
                        totalCount={totalCount}
                        propertyName={property}
                        propertyLabel={title}
                        onValueClick={(item) => {
                            addPropertyFilter(
                                property,
                                isNullBreakdown(item.label) ? null : item.label,
                                isNullBreakdown(item.label) ? PropertyOperator.IsNotSet : PropertyOperator.Exact
                            )
                        }}
                    />
                )}
            </div>
        </div>
    )
}
