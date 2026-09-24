import { useActions, useValues } from 'kea'

import { IconLaptop, IconPhone, IconTabletLandscape, IconTabletPortrait } from '@posthog/icons'
import { LemonSelect } from '@posthog/lemon-ui'

import { heatmapDataLogic } from 'lib/components/heatmaps/heatmapDataLogic'

export function ViewportChooser({ lockedWidth }: { lockedWidth?: number }): JSX.Element {
    const { widthOverride } = useValues(heatmapDataLogic({ context: 'in-app' }))
    const { setWindowWidthOverride } = useActions(heatmapDataLogic({ context: 'in-app' }))
    const options = [
        { value: 320, icon: <IconPhone /> },
        { value: 375, icon: <IconPhone /> },
        { value: 425, icon: <IconPhone /> },
        { value: 768, icon: <IconTabletPortrait /> },
        { value: 1024, icon: <IconTabletLandscape /> },
        { value: 1440, icon: <IconLaptop /> },
        { value: 1920, icon: <IconLaptop /> },
    ]
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
                    </span>
                ),
            }))}
        />
    )
}
