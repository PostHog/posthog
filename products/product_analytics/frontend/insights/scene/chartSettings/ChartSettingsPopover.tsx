import { useValues } from 'kea'

import { IconGear } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { ChartSettings } from './ChartSettings'
import { chartSettingsLogic } from './chartSettingsLogic'

/** A button that opens the chart's display settings. Shows nothing for a chart with no settings. */
export function ChartSettingsPopover({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const { groups, goalLinesSupported } = useValues(chartSettingsLogic(insightProps))

    if (!groups.length && !goalLinesSupported) {
        return null
    }

    return (
        <Popover>
            <PopoverTrigger
                render={
                    <Button
                        variant="outline"
                        size="icon-sm"
                        aria-label="Chart settings"
                        data-attr="quill-insight-chart-settings-button"
                    />
                }
            >
                <IconGear />
            </PopoverTrigger>
            <PopoverContent
                align="end"
                aria-label="Chart settings"
                className="max-h-(--available-height) w-80 max-w-(--available-width) overflow-y-auto"
                data-attr="quill-insight-chart-settings-popover"
            >
                <ChartSettings insightProps={insightProps} />
            </PopoverContent>
        </Popover>
    )
}
