import { useActions, useValues } from 'kea'

import { IconInfo } from '@posthog/icons'
import { LemonInput, LemonSelect } from '@posthog/lemon-ui'

import { useQuillSurface } from 'lib/components/QuillSurface/quillSurfaceContext'
import { Tooltip } from 'lib/lemon-ui/Tooltip'
import { capitalizeFirstLetter, pluralize } from 'lib/utils/strings'

import { EditorFilterProps, FunnelConversionWindowTimeUnit } from '~/types'

import { funnelDataLogic } from '../funnelDataLogic'
import { TIME_INTERVAL_BOUNDS } from '../funnelUtils'
import { QuillFunnelConversionWindowFilter } from './QuillFunnelConversionWindowFilter'

export function FunnelConversionWindowFilter({ insightProps }: Pick<EditorFilterProps, 'insightProps'>): JSX.Element {
    const { aggregationTargetLabel, querySource, conversionWindow, conversionWindowInterval, conversionWindowUnit } =
        useValues(funnelDataLogic(insightProps))
    const { setConversionWindowInterval, setConversionWindowUnit, commitConversionWindow } = useActions(
        funnelDataLogic(insightProps)
    )
    const quillSurface = useQuillSurface()

    const hasEdited = conversionWindowInterval !== null
    const displayInterval = hasEdited ? conversionWindowInterval || undefined : conversionWindow.funnelWindowInterval

    const displayUnit = conversionWindowUnit ?? conversionWindow.funnelWindowIntervalUnit
    const intervalBounds = TIME_INTERVAL_BOUNDS[displayUnit]

    const options = Object.keys(TIME_INTERVAL_BOUNDS).map((unit) => ({
        label: capitalizeFirstLetter(pluralize(conversionWindow.funnelWindowInterval ?? 7, unit, `${unit}s`, false)),
        value: unit as FunnelConversionWindowTimeUnit,
    }))

    const relative = querySource?.aggregation_group_type_index != null ? 'that' : 'who'
    const info = `Limit to ${aggregationTargetLabel.plural} ${relative} converted within a specific time frame. ${capitalizeFirstLetter(aggregationTargetLabel.plural)} ${relative} do not convert in this time frame will be considered as drop-offs.`

    const onUnitChange = (funnelWindowIntervalUnit: FunnelConversionWindowTimeUnit | null): void => {
        if (funnelWindowIntervalUnit) {
            setConversionWindowUnit(funnelWindowIntervalUnit)
            commitConversionWindow()
        }
    }

    if (quillSurface) {
        return (
            <QuillFunnelConversionWindowFilter
                info={info}
                interval={displayInterval}
                bounds={intervalBounds}
                unit={displayUnit}
                unitOptions={options}
                onIntervalChange={setConversionWindowInterval}
                onUnitChange={onUnitChange}
                onCommit={commitConversionWindow}
            />
        )
    }

    return (
        <div className="flex items-center gap-2 flex-wrap" data-attr="funnel-conversion-window-filter">
            <span className="flex whitespace-nowrap">
                Conversion window limit
                <Tooltip title={info}>
                    <IconInfo className="w-4 info-indicator" />
                </Tooltip>
            </span>
            <div className="flex items-center gap-2">
                <LemonInput
                    type="number"
                    className="max-w-20"
                    fullWidth={false}
                    min={intervalBounds[0]}
                    max={intervalBounds[1]}
                    value={displayInterval}
                    onChange={(value) => setConversionWindowInterval(value || 0)}
                    onBlur={commitConversionWindow}
                    onPressEnter={commitConversionWindow}
                />
                <LemonSelect
                    dropdownMatchSelectWidth={false}
                    value={displayUnit}
                    onChange={onUnitChange}
                    options={options}
                    data-attr="funnel-conversion-window-unit"
                />
            </div>
        </div>
    )
}
