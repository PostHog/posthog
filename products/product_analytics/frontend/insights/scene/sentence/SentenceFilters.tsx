import { useValues } from 'kea'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { FiltersPopover } from './filters/FiltersPopover'
import { insightSentenceLogic } from './insightSentenceLogic'

export function SentenceFilters({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { overriddenSlots } = useValues(insightSentenceLogic(insightProps))

    return (
        <FiltersPopover
            insightProps={insightProps}
            trigger={(open, toggle) => (
                <EditableWord
                    color="green"
                    aria-expanded={open}
                    onClick={toggle}
                    overridden={overriddenSlots.includes('filters')}
                    data-attr="quill-insight-sentence-filters"
                >
                    {label}
                </EditableWord>
            )}
        />
    )
}
