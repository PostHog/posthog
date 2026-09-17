import { useActions, useValues } from 'kea'

import { IconSparkles } from '@posthog/icons'
import { LemonButton } from '@posthog/lemon-ui'

import { cn } from 'lib/utils/css-classes'
import { inStorybook } from 'lib/utils/dom'
import { maxGlobalLogic } from 'scenes/max/maxGlobalLogic'
import { marketingAnalyticsLogic } from 'scenes/web-analytics/tabs/marketing-analytics/frontend/logic/marketingAnalyticsLogic'

import { sidePanelStateLogic } from '~/layout/navigation-3000/sidepanel/sidePanelStateLogic'
import { SidePanelTab } from '~/types'

import { MARKETING_AI_QUESTIONS } from './marketingAiQuestions'

export function AskPostHogAi(): JSX.Element {
    const { dashboardView } = useValues(marketingAnalyticsLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    const disabledReason = dataProcessingAccepted
        ? undefined
        : (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')

    // The leading `!` sends the question on mount rather than leaving it in the composer.
    const ask = (question: string): void => openSidePanel(SidePanelTab.Max, `!${question}`)

    return (
        <div className="rounded-lg border border-dashed border-primary bg-surface-secondary p-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <IconSparkles className="size-4 shrink-0 text-ai" />
                <h4 className="m-0 text-sm font-semibold">
                    Looking for a different breakdown of this data?{' '}
                    {/* The animation is suppressed under Storybook so visual snapshots stay stable. */}
                    <span className={cn('rainbow-text', !inStorybook() && 'rainbow-text-animating')}>
                        Ask PostHog AI.
                    </span>
                </h4>
            </div>
            <div className="flex flex-wrap gap-2">
                {MARKETING_AI_QUESTIONS[dashboardView].map((question) => (
                    <LemonButton
                        key={question}
                        type="secondary"
                        size="small"
                        onClick={() => ask(question)}
                        disabledReason={disabledReason}
                        data-attr="marketing-dashboard-ask-ai"
                    >
                        {question}
                    </LemonButton>
                ))}
            </div>
        </div>
    )
}
