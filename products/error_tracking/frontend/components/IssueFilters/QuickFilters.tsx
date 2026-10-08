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
import { DiscoveredValuesQuickFilterSelect } from './DiscoveredValuesQuickFilterSelect'

const ANY_OPTION = '__any__'
const CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

interface QuickFilterSelectProps {
    filter: QuickFilter
    selectedOptionId: string | null
    onChange: (option: QuickFilterOption | null) => void
}

const ManualQuickFilterSelect = ({ filter, selectedOptionId, onChange }: QuickFilterSelectProps): JSX.Element => {
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
            value={selectedOptionId ?? ANY_OPTION}
            onValueChange={(selectedId) => {
                if (selectedId === ANY_OPTION) {
                    onChange(null)
                    return
                }

                const selectedOption = filter.options.find((option: QuickFilterOption) => option.id === selectedId)
                if (selectedOption) {
                    onChange(selectedOption)
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

const QuickFilterSelect = ({ filter }: { filter: QuickFilter }): JSX.Element => {
    const sectionLogic = quickFiltersSectionLogic({ context: CONTEXT, logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })
    const { selectedQuickFilters } = useValues(sectionLogic)
    const { setQuickFilterValue, clearQuickFilter } = useActions(sectionLogic)
    const selectedOptionId = selectedQuickFilters[filter.id]?.optionId ?? null
    const onChange = (option: QuickFilterOption | null): void =>
        option ? setQuickFilterValue(filter.id, filter.property_name, option) : clearQuickFilter(filter.id)

    return filter.type === 'auto-discovery' ? (
        <DiscoveredValuesQuickFilterSelect
            filter={filter}
            context={CONTEXT}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
        />
    ) : (
        <ManualQuickFilterSelect filter={filter} selectedOptionId={selectedOptionId} onChange={onChange} />
    )
}

export const ErrorTrackingQuickFilters = (): JSX.Element => {
    const context = CONTEXT
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
