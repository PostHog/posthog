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
    const { dashboardBreakdown, dashboardView, dateFilter, draftConversionGoal } = useValues(marketingAnalyticsLogic)
    const { openSidePanel } = useActions(sidePanelStateLogic)
    const { dataProcessingAccepted, dataProcessingApprovalDisabledReason } = useValues(maxGlobalLogic)

    const disabledReason = dataProcessingAccepted
        ? undefined
        : (dataProcessingApprovalDisabledReason ?? 'Approve AI data processing to use PostHog AI')

    const ask = (question: string): void => {
        const context = [
            `Dashboard section: ${dashboardView}`,
            `Date range: ${dateFilter.dateFrom ?? 'all time'} to ${dateFilter.dateTo ?? 'today'}`,
            `Breakdown: ${dashboardBreakdown}`,
            draftConversionGoal ? `Conversion goal: ${draftConversionGoal.conversion_goal_name}` : null,
        ].filter(Boolean)

        openSidePanel(
            SidePanelTab.Max,
            `!${question}\n\nUse this Marketing Analytics dashboard context:\n${context.join('\n')}`
        )
    }

    return (
        <div className="rounded-lg border border-dashed border-primary bg-surface-secondary p-4 flex flex-col gap-3">
            <div className="flex items-center gap-2">
                <IconSparkles className="size-4 shrink-0 text-ai" />
                <h4 className="m-0 text-sm font-semibold">
                    Need another view of this data?{' '}
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
