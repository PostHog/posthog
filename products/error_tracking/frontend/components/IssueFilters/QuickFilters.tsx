import { useActions, useValues } from 'kea'

import { IconGear } from '@posthog/icons'

import {
    QuickFiltersModal,
    quickFiltersLogic,
    quickFiltersModalLogic,
    quickFiltersSectionLogic,
} from 'lib/components/QuickFilters'
import { Button, Tooltip, TooltipContent, TooltipTrigger } from 'lib/ui/quill'

import { QuickFilterContext } from '~/queries/schema/schema-general'
import { QuickFilter, QuickFilterOption } from '~/types'

import { ERROR_TRACKING_SCENE_LOGIC_KEY } from '../../scenes/ErrorTrackingScene/errorTrackingSceneLogic'
import { QuickFilterOptionSelect } from './QuickFilterOptionSelect'

const CONTEXT = QuickFilterContext.ErrorTrackingIssueFilters

const QuickFilterSelect = ({ filter }: { filter: QuickFilter }): JSX.Element => {
    const sectionLogic = quickFiltersSectionLogic({ context: CONTEXT, logicKey: ERROR_TRACKING_SCENE_LOGIC_KEY })
    const { selectedQuickFilters } = useValues(sectionLogic)
    const { setQuickFilterValue, clearQuickFilter } = useActions(sectionLogic)
    const selectedOptionId = selectedQuickFilters[filter.id]?.optionId ?? null
    const onChange = (option: QuickFilterOption | null): void =>
        option ? setQuickFilterValue(filter.id, filter.property_name, option) : clearQuickFilter(filter.id)

    return (
        <QuickFilterOptionSelect
            filter={filter}
            context={CONTEXT}
            selectedOptionId={selectedOptionId}
            onChange={onChange}
        />
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
