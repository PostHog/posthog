import { useActions, useValues } from 'kea'
import { Fragment } from 'react'

import { IconChevronDown } from '@posthog/icons'
import {
    Button,
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuGroup,
    DropdownMenuLabel,
    DropdownMenuRadioGroup,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
    ItemContent,
    ItemDescription,
    ItemTitle,
} from '@posthog/quill'

import type { InsightLogicProps } from '~/types'
import { ChartDisplayType } from '~/types'

import { ChartDisplayIcon } from 'products/product_analytics/frontend/insights/chartAlternatives/ChartDisplayIcon'

import { MenuChoiceItem } from '../MenuChoiceItem'
import { chartTypeStripLogic } from './chartTypeStripLogic'

export function ChartTypeMenu({
    insightProps,
    onOpenChange,
    triggerClassName,
}: {
    insightProps: InsightLogicProps
    onOpenChange?: (open: boolean) => void
    triggerClassName?: string
}): JSX.Element {
    const logic = chartTypeStripLogic(insightProps)
    const { options, currentDisplay } = useValues(logic)
    const { selectChartType } = useActions(logic)

    return (
        <DropdownMenu onOpenChange={onOpenChange}>
            <DropdownMenuTrigger
                render={
                    <Button variant="outline" className={triggerClassName} data-attr="quill-insight-chart-type-all" />
                }
            >
                All chart types
                <IconChevronDown />
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-w-80 min-w-72">
                {options.map((group, index) => (
                    <Fragment key={group.title}>
                        {index > 0 && <DropdownMenuSeparator />}
                        <DropdownMenuGroup>
                            <DropdownMenuLabel>{group.title}</DropdownMenuLabel>
                            <DropdownMenuRadioGroup
                                value={currentDisplay}
                                onValueChange={(value: ChartDisplayType) => selectChartType(value, 'all_types')}
                            >
                                {group.options.map((option) => (
                                    <MenuChoiceItem
                                        key={option.display}
                                        value={option.display}
                                        disabled={!!option.disabledReason}
                                        className={
                                            option.disabledReason
                                                ? 'h-auto items-start py-1.5 whitespace-normal [&>svg]:mt-1.5'
                                                : undefined
                                        }
                                        data-attr="quill-insight-chart-type-option"
                                    >
                                        <ChartDisplayIcon icon={option.icon} />
                                        {option.disabledReason ? (
                                            <ItemContent variant="menuItem">
                                                <ItemTitle>{option.label}</ItemTitle>
                                                <ItemDescription>{option.disabledReason}</ItemDescription>
                                            </ItemContent>
                                        ) : (
                                            <span>{option.label}</span>
                                        )}
                                    </MenuChoiceItem>
                                ))}
                            </DropdownMenuRadioGroup>
                        </DropdownMenuGroup>
                    </Fragment>
                ))}
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
