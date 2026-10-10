import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton } from '@posthog/lemon-ui'

import { getAccessControlDisabledReason } from 'lib/utils/accessControlUtils'

import { AccessControlLevel, AccessControlResourceType } from '~/types'

import { workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from './WorkflowSuggestionCard'

export function WorkflowDataSuggestionsLane(): JSX.Element | null {
    const logic = workflowDataSuggestionsLogic({ surface: 'list' })
    const { cards, aiResultLoading, hidden } = useValues(logic)
    const { hideSuggestions, showSuggestions } = useActions(logic)
    const cannotCreate = !!getAccessControlDisabledReason(AccessControlResourceType.Workflow, AccessControlLevel.Editor)
    const loading = cards.length === 0 && aiResultLoading

    if (cannotCreate) {
        return null
    }

    if (hidden) {
        return (
            <div className="mb-3 flex justify-end">
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    icon={<IconSparkles />}
                    onClick={showSuggestions}
                    data-attr="workflows-data-suggestions-show"
                >
                    Show suggestions
                </LemonButton>
            </div>
        )
    }

    if (!loading && cards.length === 0) {
        return null
    }

    return (
        <section
            // Tints the panel with the Workflows product color, which has no ready-made background token.
            className="@container mb-4 flex flex-col gap-3 rounded-lg border p-4 bg-[color-mix(in_srgb,var(--color-product-workflows-light)_10%,transparent)]"
            data-attr="workflows-data-suggestions-lane"
        >
            <div className="flex flex-wrap items-start justify-between gap-2">
                <div className="flex items-start gap-2">
                    <IconSparkles className="mt-0.5 size-5 text-accent" />
                    <div className="flex flex-col">
                        <h3 className="mb-0 text-base font-semibold">Suggested for you</h3>
                        <span className="text-xs text-secondary">
                            Workflows built around events your project sent this week.
                        </span>
                    </div>
                </div>
                <LemonButton
                    type="tertiary"
                    size="xsmall"
                    onClick={hideSuggestions}
                    data-attr="workflows-data-suggestions-hide"
                >
                    Hide suggestions
                </LemonButton>
            </div>
            <div className="grid grid-cols-1 gap-3 @3xl:grid-cols-2 @6xl:grid-cols-3">
                {loading
                    ? [0, 1, 2].map((index) => <LemonSkeleton key={index} className="h-44 rounded" />)
                    : cards.map((card) => <WorkflowSuggestionCard key={card.key} card={card} surface="list" />)}
            </div>
        </section>
    )
}
