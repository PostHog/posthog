import { useActions, useValues } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuTrigger } from '@posthog/quill'

import { CUSTOM_OPTION_KEY } from 'lib/components/DateFilter/types'
import { dateMapping } from 'lib/utils/dateFilters'

import type { InsightLogicProps } from '~/types'

import { MenuChoiceItem } from '../MenuChoiceItem'
import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

const DATE_OPTIONS = dateMapping.filter((option) => option.key !== CUSTOM_OPTION_KEY && !option.inactive)

export function SentenceDateRange({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { seriesQuery, overriddenSlots } = useValues(insightSentenceLogic(insightProps))
    const { changeDateRange } = useActions(insightSentenceLogic(insightProps))

    const dateFrom = seriesQuery?.dateRange?.date_from ?? null
    const dateTo = seriesQuery?.dateRange?.date_to ?? null
    const selected = DATE_OPTIONS.find(
        (option) => (option.values[0] ?? null) === dateFrom && (option.values[1] ?? null) === dateTo
    )

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <EditableWord
                        color="orange"
                        overridden={overriddenSlots.includes('dateRange')}
                        data-attr="quill-insight-sentence-date-range"
                    />
                }
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuRadioGroup
                    value={selected?.key ?? ''}
                    onValueChange={(key: string) => {
                        const option = DATE_OPTIONS.find((candidate) => candidate.key === key)
                        if (option) {
                            changeDateRange(option.values[0] ?? null, option.values[1] ?? null)
                        }
                    }}
                >
                    {DATE_OPTIONS.map((option) => (
                        <MenuChoiceItem key={option.key} value={option.key}>
                            {option.key}
                        </MenuChoiceItem>
                    ))}
                </DropdownMenuRadioGroup>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
