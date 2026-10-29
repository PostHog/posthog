import { useActions, useValues } from 'kea'
import { ReactNode } from 'react'

import { IconChevronRight } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'

export interface SuggestionsBannerProps {
    icon: ReactNode
    message: ReactNode
}

export function SuggestionsBanner({ icon, message }: SuggestionsBannerProps): JSX.Element {
    const { surfaceSuggestions } = useValues(warehouseSuggestionsLogic)
    const { openReview } = useActions(warehouseSuggestionsLogic)

    return (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-2 rounded border border-accent bg-accent-highlight-secondary px-3 py-2">
            <span className="group/colorful-product-icons colorful-product-icons-true flex shrink-0 translate-y-px text-lg">
                {icon}
            </span>
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
