import { useActions, useValues } from 'kea'
import { useId, useState } from 'react'

import { IconChevronDown } from '@posthog/icons'
import { Button, Popover, PopoverContent, PopoverTrigger, Text } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { ChartDisplayIcon } from 'products/product_analytics/frontend/insights/chartAlternatives/ChartDisplayIcon'

import { ChartTypeMenu } from './ChartTypeMenu'
import { chartTypeStripLogic } from './chartTypeStripLogic'
import { ChartTypeTile } from './ChartTypeTile'

export function ChartTypePopover({ insightProps }: { insightProps: InsightLogicProps }): JSX.Element | null {
    const logic = chartTypeStripLogic(insightProps)
    const { currentOption, stripState, tiles } = useValues(logic)
    const { selectChartType } = useActions(logic)
    const [open, setOpen] = useState(false)
    const [menuOpen, setMenuOpen] = useState(false)
    const labelId = useId()

    if (stripState === 'hidden') {
        return null
    }

    return (
        <Popover
            open={open}
            onOpenChange={(nextOpen) => {
                // The menu opens outside the popover, so the pointer leaves the popover to reach it.
                if (nextOpen || !menuOpen) {
                    setOpen(nextOpen)
                }
            }}
        >
            <PopoverTrigger
                openOnHover
                delay={150}
                closeDelay={150}
                render={<Button variant="outline" size="sm" data-attr="quill-insight-chart-type" />}
            >
                {currentOption && <ChartDisplayIcon icon={currentOption.icon} />}
                {currentOption?.label ?? 'Chart type'}
                <IconChevronDown />
            </PopoverTrigger>
            <PopoverContent
                align="end"
                className="w-auto gap-2"
                aria-labelledby={labelId}
                data-attr="quill-insight-chart-type-popover"
            >
                <Text id={labelId} size="xs" variant="muted">
                    Suggested ways to view this
                </Text>
                {tiles.map((tile) => (
                    <ChartTypeTile
                        key={tile.option.display}
                        tile={tile}
                        loading={stripState === 'loading'}
                        onSelect={() => selectChartType(tile.option.display, 'strip')}
                    />
                ))}
                <ChartTypeMenu
                    insightProps={insightProps}
                    onOpenChange={(nextOpen) => {
                        setMenuOpen(nextOpen)
                        if (!nextOpen) {
                            setOpen(false)
                        }
                    }}
                />
            </PopoverContent>
        </Popover>
    )
}
