import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconBolt, IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface SuggestionsBannerProps {
    message: ReactNode
}

export function SuggestionsBanner({ message }: SuggestionsBannerProps): JSX.Element {
    const { surfaceSuggestions } = useValues(warehouseSuggestionsLogic)
    const { openReview } = useActions(warehouseSuggestionsLogic)

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded border border-accent bg-accent-highlight-secondary px-3 py-2">
            <IconBolt className="shrink-0 text-lg text-accent" />
            <span className="min-w-0 flex-1 text-sm">{message}</span>
            <LemonButton
                size="small"
                type="primary"
                sideIcon={<IconChevronRight />}
                onClick={() => openReview()}
                data-attr="warehouse-suggestions-review"
            >
                {`Review ${surfaceSuggestions.length}`}
            </LemonButton>
        </div>
    )
}
