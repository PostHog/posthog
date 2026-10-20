import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { Input, Label, Tooltip, TooltipContent, TooltipTrigger } from '@posthog/quill'

import { QuillSelect } from 'lib/components/QuillSelect/QuillSelect'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import { EditorFilterProps, FunnelConversionWindowTimeUnit } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { TIME_INTERVAL_BOUNDS } from '../funnelUtils'

export function QuillFunnelConversionWindowFilter({
    insightProps,
}: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const { aggregationTargetLabel, querySource, conversionWindow, conversionWindowInterval, conversionWindowUnit } =
        useValues(funnelDataLogic(insightProps))
    const { setConversionWindowInterval, setConversionWindowUnit, commitConversionWindow } = useActions(
        funnelDataLogic(insightProps)
    )

    const hasEdited = conversionWindowInterval !== null
    const displayInterval = hasEdited ? conversionWindowInterval || undefined : conversionWindow.funnelWindowInterval
    const displayUnit = conversionWindowUnit ?? conversionWindow.funnelWindowIntervalUnit
    const intervalBounds = TIME_INTERVAL_BOUNDS[displayUnit]
    const pronoun = querySource?.aggregation_group_type_index != null ? 'that' : 'who'

    return (
        <div className="flex items-center gap-2 flex-wrap" data-attr="funnel-conversion-window-filter">
            <Label htmlFor="funnel-conversion-window-interval" className="flex items-center gap-1 whitespace-nowrap">
                Conversion window limit
                <Tooltip>
                    <TooltipTrigger render={<span className="inline-flex" tabIndex={0} aria-label="More info" />}>
                        <IconInfo className="size-4 text-muted-foreground" />
                    </TooltipTrigger>
                    <TooltipContent className="max-w-80">
                        Limit to {aggregationTargetLabel.plural} {pronoun} converted within a specific time frame.{' '}
                        {capitalizeFirstLetter(aggregationTargetLabel.plural)} {pronoun} do not convert in this time
                        frame will be considered as drop-offs.
                    </TooltipContent>
                </Tooltip>
            </Label>
            <div className="flex items-center gap-2">
                <Input
                    id="funnel-conversion-window-interval"
                    type="number"
                    className="w-20"
                    min={intervalBounds[0]}
                    max={intervalBounds[1]}
                    value={displayInterval ?? ''}
                    onChange={(e) => setConversionWindowInterval(Number(e.target.value) || 0)}
                    onBlur={commitConversionWindow}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') {
                            commitConversionWindow()
                        }
                    }}
                />
                <QuillSelect<FunnelConversionWindowTimeUnit>
                    value={displayUnit}
                    onChange={(funnelWindowIntervalUnit) => {
                        setConversionWindowUnit(funnelWindowIntervalUnit)
                        commitConversionWindow()
                    }}
                    options={Object.keys(TIME_INTERVAL_BOUNDS).map((unit) => ({
                        label: capitalizeFirstLetter(
                            pluralize(conversionWindow.funnelWindowInterval ?? 7, unit, `${unit}s`, false)
                        ),
                        value: unit as FunnelConversionWindowTimeUnit,
                    }))}
                    data-attr="funnel-conversion-window-unit"
                />
            </div>
        </div>
    )
}
