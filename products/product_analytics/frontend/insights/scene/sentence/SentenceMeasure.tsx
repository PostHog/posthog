import { useActions, useValues } from 'kea'
import { useState } from 'react'

import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuSub,
    DropdownMenuSubContent,
    DropdownMenuSubTrigger,
    DropdownMenuTrigger,
} from '@posthog/quill'

import { TaxonomicFilterGroupType } from 'lib/components/TaxonomicFilter/types'

import type { InsightLogicProps } from '~/types'

import { MenuChoiceItem } from '../MenuChoiceItem'
import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'
import { PropertyPickerPopover } from './PropertyPickerPopover'
import type { PickedProperty } from './PropertyPickerPopover'
import { SeriesExpressionPopover } from './SeriesExpressionPopover'

const PROPERTY_GROUP_TYPES: Partial<Record<PickedProperty['type'], TaxonomicFilterGroupType>> = {
    event: TaxonomicFilterGroupType.EventProperties,
    person: TaxonomicFilterGroupType.PersonProperties,
    session: TaxonomicFilterGroupType.SessionProperties,
}

export function SentenceMeasure({
    insightProps,
    seriesIndex,
    label,
}: {
    insightProps: InsightLogicProps
    seriesIndex: number
    label: string
}): JSX.Element {
    const { measureOptions, perUserMeasureOptions, propertyMeasureOptions, seriesMathTypes, trendsQuery } = useValues(
        insightSentenceLogic(insightProps)
    )
    const { changeSeriesExpression, changeSeriesMath, changeSeriesPropertyMath, removeSeries } = useActions(
        insightSentenceLogic(insightProps)
    )
    const [expressionOpen, setExpressionOpen] = useState(false)
    // A property measure needs two picks: the calculation here, then the property in the picker it opens.
    const [pendingPropertyMath, setPendingPropertyMath] = useState<string | null>(null)
    const mathType = seriesMathTypes[seriesIndex] ?? ''

    return (
        <PropertyPickerPopover
            insightProps={insightProps}
            numericOnly
            onPick={(property) => {
                const groupType = PROPERTY_GROUP_TYPES[property.type]
                if (pendingPropertyMath && groupType) {
                    changeSeriesPropertyMath(seriesIndex, pendingPropertyMath, property.key, groupType)
                }
            }}
            trigger={(_, toggle) => (
                <span>
                    <DropdownMenu>
                        <DropdownMenuTrigger
                            render={<EditableWord color="purple" data-attr="quill-insight-sentence-measure" />}
                        >
                            {label}
                        </DropdownMenuTrigger>
                        <DropdownMenuContent align="start" className="min-w-56">
                            <DropdownMenuRadioGroup
                                value={mathType}
                                onValueChange={(value: string) => changeSeriesMath(seriesIndex, value)}
                            >
                                {measureOptions.map((option) => (
                                    <MenuChoiceItem key={option.value} value={option.value}>
                                        {option.label}
                                    </MenuChoiceItem>
                                ))}
                            </DropdownMenuRadioGroup>
                            <DropdownMenuSeparator />
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>Property value</DropdownMenuSubTrigger>
                                <DropdownMenuSubContent className="min-w-48">
                                    {propertyMeasureOptions.map((option) => (
                                        <DropdownMenuItem
                                            key={option.value}
                                            onClick={() => {
                                                setPendingPropertyMath(option.value)
                                                toggle()
                                            }}
                                        >
                                            {option.label}
                                        </DropdownMenuItem>
                                    ))}
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuSub>
                                <DropdownMenuSubTrigger>Count per user</DropdownMenuSubTrigger>
                                <DropdownMenuSubContent className="min-w-48">
                                    <DropdownMenuRadioGroup
                                        value={mathType}
                                        onValueChange={(value: string) => changeSeriesMath(seriesIndex, value)}
                                    >
                                        {perUserMeasureOptions.map((option) => (
                                            <MenuChoiceItem key={option.value} value={option.value}>
                                                {option.label}
                                            </MenuChoiceItem>
                                        ))}
                                    </DropdownMenuRadioGroup>
                                </DropdownMenuSubContent>
                            </DropdownMenuSub>
                            <DropdownMenuItem onClick={() => setExpressionOpen(true)}>SQL expression</DropdownMenuItem>
                            {seriesMathTypes.length > 1 && (
                                <>
                                    <DropdownMenuSeparator />
                                    <DropdownMenuItem variant="destructive" onClick={() => removeSeries(seriesIndex)}>
                                        Remove this event
                                    </DropdownMenuItem>
                                </>
                            )}
                        </DropdownMenuContent>
                    </DropdownMenu>
                    <SeriesExpressionPopover
                        open={expressionOpen}
                        onOpenChange={setExpressionOpen}
                        expression={trendsQuery?.series[seriesIndex]?.math_hogql ?? ''}
                        onApply={(expression) => changeSeriesExpression(seriesIndex, expression)}
                    />
                </span>
            )}
        />
    )
}
