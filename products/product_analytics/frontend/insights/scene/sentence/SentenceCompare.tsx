import { useActions } from 'kea'

import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@posthog/quill'

import type { InsightLogicProps } from '~/types'

import { EditableWord } from './EditableWord'
import { insightSentenceLogic } from './insightSentenceLogic'

export function SentenceCompare({
    insightProps,
    label,
}: {
    insightProps: InsightLogicProps
    label: string
}): JSX.Element {
    const { toggleCompare } = useActions(insightSentenceLogic(insightProps))

    return (
        <DropdownMenu>
            <DropdownMenuTrigger
                render={
                    <EditableWord
                        color="orange"
                        onRemove={toggleCompare}
                        removeLabel="Stop comparing"
                        data-attr="quill-insight-sentence-compare"
                    />
                }
            >
                {label}
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start" className="min-w-56">
                <DropdownMenuItem onClick={() => toggleCompare()}>Stop comparing</DropdownMenuItem>
            </DropdownMenuContent>
        </DropdownMenu>
    )
}
