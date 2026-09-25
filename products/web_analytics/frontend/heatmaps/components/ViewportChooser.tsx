import { useActions, useValues } from 'kea'

import { IconLaptop, IconPhone, IconTabletLandscape, IconTabletPortrait } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'
import { percentage } from 'lib/utils/numbers'

import { HEATMAP_PRESET_WIDTHS } from './heatmapCoverage'
import { heatmapCoverageLogic } from './heatmapCoverageLogic'

export function ViewportChooser({ lockedWidth }: { lockedWidth?: number }): JSX.Element {
    const { widthOverride } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const { widthShares } = useValues(heatmapCoverageLogic)
    const { setWindowWidthOverride } = useActions(heatmapDataLogic({ context: 'in-app' }))
    const iconForWidth = (width: number): JSX.Element =>
        width < 768 ? (
            <IconPhone />
        ) : width < 1024 ? (
            <IconTabletPortrait />
        ) : width < 1440 ? (
            <IconTabletLandscape />
        ) : (
            <IconLaptop />
        )
    const options = HEATMAP_PRESET_WIDTHS.map((value) => ({ value, icon: iconForWidth(value) }))
    const allOptions = lockedWidth ? [{ value: lockedWidth, icon: <IconLaptop /> }] : [...options]
    if (!lockedWidth && widthOverride && !options.some((option) => option.value === widthOverride)) {
        allOptions.push({ value: widthOverride, icon: <IconLaptop /> })
    }

    return (
        <LemonSelect
            size="small"
            onChange={setWindowWidthOverride}
            value={lockedWidth ?? widthOverride}
            disabledReason={lockedWidth ? 'Toolbar captures are saved at a single width' : undefined}
            data-attr="viewport-chooser"
            aria-label="Screen width"
            tooltip="Recorded screen width"
            options={allOptions.map(({ value, icon }) => ({
                value,
                label: (
                    <span className="flex items-center gap-1 whitespace-nowrap">
                        {icon}
                        <span>{`${value} px`}</span>
                        {widthShares?.[value] !== undefined ? (
                            <span className="text-muted">{percentage(widthShares[value], 0)}</span>
                        ) : null}
                    </span>
                ),
            }))}
        />
    )
}
