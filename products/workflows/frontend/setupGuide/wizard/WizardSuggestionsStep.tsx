import { useActions, useValues } from 'kea'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { workflowDataSuggestionsLogic } from '../suggestions/workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from '../suggestions/WorkflowSuggestionCard'
import { WorkflowSuggestionRow } from '../suggestions/WorkflowSuggestionRow'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

/** The first journey as suggestions from the project's events: one card to start from, the rest as rows, and a
 * way out to the templates. Without suggestions it shows `fallback`, the template list. */
export function WizardSuggestionsStep({ fallback }: { fallback: JSX.Element }): JSX.Element {
    const { cards, generating } = useValues(workflowDataSuggestionsLogic({ surface: 'onboarding_wizard' }))
    const { setTemplatesShown } = useActions(workflowsOnboardingWizardLogic)

    if (!generating && cards.length === 0) {
        return fallback
    }

    const [top, ...rest] = cards

    return (
        <div className="flex flex-col gap-4" data-attr="workflows-onboarding-wizard-suggestions">
            <span className="inline-flex items-center gap-1 text-xs text-secondary">
                {generating ? <Spinner className="size-3" /> : <IconSparkles className="size-3" />}
                {generating
                    ? 'Suggesting workflows based on the events your project sends'
                    : 'Suggested from your data'}
                <Tooltip title="AI writes these suggestions from your project's events. Check each draft before you turn it on.">
                    <LemonTag type="completion" size="small">
                        Beta
                    </LemonTag>
                </Tooltip>
            </span>
            {generating ? (
                <>
                    <LemonSkeleton className="h-44 rounded" />
                    <LemonSkeleton className="h-12 rounded" />
                    <LemonSkeleton className="h-12 rounded" />
                </>
            ) : (
                <>
                    <WorkflowSuggestionCard card={top} surface="onboarding_wizard" primary />
                    {rest.length > 0 && (
                        <div className="flex flex-col gap-2">
                            <span className="text-xs font-semibold text-secondary">More from your data</span>
                            {rest.map((card) => (
                                <WorkflowSuggestionRow key={card.key} card={card} surface="onboarding_wizard" />
                            ))}
                        </div>
                    )}
                </>
            )}
            <div className="flex flex-wrap items-center gap-1 text-sm text-secondary">
                <span>Not what you need?</span>
                <LemonButton
                    type="tertiary"
                    size="small"
                    sideIcon={<IconArrowRight />}
                    onClick={() => setTemplatesShown(true)}
                    data-attr="workflows-onboarding-wizard-show-templates"
                >
                    Start from a template or from scratch
                </LemonButton>
            </div>
        </div>
    )
}
