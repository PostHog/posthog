import { useActions, useValues } from 'kea'

import { IconArrowRight, IconSparkles } from '@posthog/icons'
import { LemonButton, LemonSkeleton, LemonTag, Spinner, Tooltip } from '@posthog/lemon-ui'

import { workflowDataSuggestionsLogic } from '../suggestions/workflowDataSuggestionsLogic'
import { WorkflowSuggestionCard } from '../suggestions/WorkflowSuggestionCard'
import { workflowsOnboardingWizardLogic } from './workflowsOnboardingWizardLogic'

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
                    <div className="grid grid-cols-2 gap-4">
                        <LemonSkeleton className="h-44 rounded" />
                        <LemonSkeleton className="h-44 rounded" />
                    </div>
                </>
            ) : (
                <>
                    <WorkflowSuggestionCard card={top} surface="onboarding_wizard" primary />
                    {rest.length > 0 && (
                        <div className="@container">
                            <div className="grid grid-cols-1 gap-4 @xl:grid-cols-2">
                                {rest.map((card) => (
                                    <WorkflowSuggestionCard key={card.key} card={card} surface="onboarding_wizard" />
                                ))}
                            </div>
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
