import { useActions, useValues } from 'kea'
import { useMemo } from 'react'

import { IconGear } from '@posthog/icons'

import {
    QuickFiltersModal,
    quickFiltersLogic,
    quickFiltersModalLogic,
    quickFiltersSectionLogic,
} from 'lib/components/QuickFilters'
import {
    Button,
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
    Tooltip,
    TooltipContent,
    TooltipTrigger,
} from 'lib/ui/quill'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../scenes/ErrorTrackingScene/errorTrackingSceneLogic'

const ANY_OPTION = '__any__'

const QuickFilterSelect = ({ filter }: { filter: QuickFilter }): JSX.Element => {
    const { selectedQuickFilters } = useValues(
        quickFiltersSectionLogic({
            context: QuickFilterContext.ErrorTrackingIssueFilters,
            logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY,
        })
    )
    const { setQuickFilterValue, clearQuickFilter } = useActions(
        quickFiltersSectionLogic({
            context: QuickFilterContext.ErrorTrackingIssueFilters,
            logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY,
        })
    )
    const selectedOptionId = selectedQuickFilters[filter.id]?.optionId ?? ANY_OPTION
    const items = useMemo(
        () => [
            { value: ANY_OPTION, label: `Any ${filter.name.toLowerCase()}` },
            ...filter.options.map((option) => ({ value: option.id, label: option.label })),
        ],
        [filter.name, filter.options]
    )

    return (
        <Select
            items={items}
            value={selectedOptionId}
            onValueChange={(selectedId) => {
                if (selectedId === ANY_OPTION) {
                    clearQuickFilter(filter.id)
                    return
                }

                const selectedOption = filter.options.find((option: QuickFilterOption) => option.id === selectedId)
                if (selectedOption) {
                    setQuickFilterValue(filter.id, filter.property_name, selectedOption)
                }
            }}
        >
            <SelectTrigger size="default">
                <SelectValue />
            </SelectTrigger>
            <SelectContent align="start" alignItemWithTrigger={false}>
                {items.map((item) => (
                    <SelectItem key={item.value} value={item.value}>
                        {item.label}
                    </SelectItem>
                ))}
            </SelectContent>
        </Select>
    )
}

export const ErrorTrackingQuickFilters = (): JSX.Element => {
    const context = QuickFilterContext.ErrorTrackingIssueFilters
    const { quickFilters } = useValues(quickFiltersLogic({ context }))
    const modalProps = { context }
    const { openModal } = useActions(quickFiltersModalLogic(modalProps))

    return (
        <>
            {quickFilters.map((filter: QuickFilter) => (
                <QuickFilterSelect key={filter.id} filter={filter} />
            ))}
            <QuickFiltersModal {...modalProps} />
            <Tooltip>
                <TooltipTrigger
                    render={
                        <Button
                            variant="outline"
                            size={quickFilters.length === 0 ? 'default' : 'icon'}
                            onClick={openModal}
                        />
                    }
                >
                    <IconGear />
                    {quickFilters.length === 0 ? 'Configure quick filters' : null}
                </TooltipTrigger>
                <TooltipContent>Configure quick filters</TooltipContent>
            </Tooltip>
        </>
    )
}
