import { useActions, useValues } from 'kea'
import { RefObject, useCallback, useRef } from 'react'

import { Button, Heading, Text } from '@posthog/quill'

import { warehouseSuggestionsLogic } from '../warehouseSuggestionsLogic'
import { SavingsBannerMessage } from './SavingsBannerMessage'
import { SuggestedModelsDialogs } from './SuggestedModelsDialogs'
import { SuggestedModelsPreviewTable } from './SuggestedModelsPreviewTable'
import { useFocusFollowsRemovedRow } from './useFocusFollowsRemovedRow'

const HEADING_ID = 'models-overview-suggestions-heading'

export interface SuggestedModelsPreviewContentProps {
    emptyFocusRef: RefObject<HTMLElement>
}

export function SuggestedModelsPreviewContent({
    emptyFocusRef,
}: SuggestedModelsPreviewContentProps): JSX.Element | null {
    const { stripState, rankedSuggestions, savingsSummary } = useValues(warehouseSuggestionsLogic)
    const { openReview } = useActions(warehouseSuggestionsLogic)
    const containerRef = useRef<HTMLElement>(null)
    const focusHost = useCallback(() => emptyFocusRef.current?.focus(), [emptyFocusRef])
    useFocusFollowsRemovedRow(
        containerRef,
        rankedSuggestions.map(({ id }) => id),
        focusHost
    )

    if (stripState !== 'active' && stripState !== 'all_done') {
        return null
    }

    return (
        <>
            {rankedSuggestions.length > 0 && (
                <section ref={containerRef} aria-labelledby={HEADING_ID} className="flex flex-col gap-2">
                    <div className="flex items-center justify-between gap-4">
                        <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-0.5">
                            <Heading size="base" render={<h3 id={HEADING_ID} className="m-0" />}>
                                <span>Suggested changes</span>
                                <span translate="no" className="ml-2 font-normal text-muted-foreground">
                                    {rankedSuggestions.length}
                                </span>
                            </Heading>
                            <Text size="xs" variant="muted">
                                <SavingsBannerMessage summary={savingsSummary} />
                            </Text>
                        </div>
                        <Button
                            variant="link"
                            onClick={() => openReview()}
                            data-attr="models-overview-suggestions-review-all"
                        >
                            Review all
                        </Button>
                    </div>
                    <SuggestedModelsPreviewTable suggestions={rankedSuggestions} />
                </section>
            )}
            <SuggestedModelsDialogs />
        </>
    )
}
