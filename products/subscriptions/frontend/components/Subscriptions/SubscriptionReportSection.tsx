import { useActions } from 'kea'
import type { ReactNode } from 'react'

import { IconGraph } from '@posthog/icons'
import { LemonInput } from '@posthog/lemon-ui'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonSegmentedButton } from 'lib/lemon-ui/LemonSegmentedButton'

import { DashboardType, SubscriptionResourceTypes } from '~/types'

import { AiPromptFields, AiPromptSubscriptionIntroduction } from './AiPromptFields'
import { InsightSelector } from './InsightSelector'
import { subscriptionLogic } from './subscriptionLogic'
import type { SubscriptionFormType, SubscriptionLogicProps } from './subscriptionLogic'

interface SubscriptionReportSectionProps {
    logicProps: SubscriptionLogicProps
    subscription: SubscriptionFormType
    dashboard?: DashboardType<any> | null
    insightName?: string
    aiContextsEnabled: boolean
    compactAnalysisWindow?: boolean
    selectionReady?: boolean
    showResourceTypeToggle?: boolean
    aiOptionDisabledReason?: string
    aiConsentMessage?: ReactNode
    aiConsentHint?: ReactNode
}

export function SubscriptionReportSection({
    logicProps,
    subscription,
    dashboard,
    insightName,
    aiContextsEnabled,
    compactAnalysisWindow = false,
    selectionReady = true,
    showResourceTypeToggle = false,
    aiOptionDisabledReason,
    aiConsentMessage,
    aiConsentHint,
}: SubscriptionReportSectionProps): JSX.Element {
    const logic = subscriptionLogic(logicProps)
    const { addContext, applyDefaultSelectedInsights, removeContext, selectAiAnalysisWindow, selectAiExamplePrompt } =
        useActions(logic)
    const isAiPrompt = subscription.resource_type === SubscriptionResourceTypes.AiPrompt

    return (
        <div className="flex min-w-0 flex-col gap-4">
            <LemonField name="title" label="Name">
                <LemonInput placeholder="e.g. Weekly activation report" />
            </LemonField>

            {showResourceTypeToggle ? (
                <LemonField name="resource_type" label="Report type">
                    {({ value, onChange }) => (
                        <LemonSegmentedButton
                            value={value}
                            onChange={onChange}
                            fullWidth
                            options={[
                                {
                                    value: SubscriptionResourceTypes.Insight,
                                    label: 'Insight or dashboard snapshot',
                                },
                                {
                                    value: SubscriptionResourceTypes.AiPrompt,
                                    label: 'Report from a prompt (beta)',
                                    disabledReason: aiOptionDisabledReason,
                                },
                            ]}
                        />
                    )}
                </LemonField>
            ) : null}

            {insightName && !isAiPrompt ? (
                <div className="flex items-center gap-2 font-semibold">
                    <IconGraph className="size-5 shrink-0 text-accent" />
                    {insightName}
                </div>
            ) : null}

            {dashboard?.tiles && selectionReady && !isAiPrompt ? (
                <LemonField name="dashboard_export_insights" label="Insights to include">
                    {({ value, onChange }) => (
                        <InsightSelector
                            tiles={dashboard.tiles}
                            selectedInsightIds={value ?? []}
                            onChange={onChange}
                            onDefaultsApplied={applyDefaultSelectedInsights}
                        />
                    )}
                </LemonField>
            ) : null}

            {aiConsentHint ? (
                <LemonBanner type="info" className="text-sm">
                    {aiConsentHint}
                </LemonBanner>
            ) : null}

            {isAiPrompt ? (
                <>
                    <AiPromptSubscriptionIntroduction />
                    <AiPromptFields
                        compactAnalysisWindow={compactAnalysisWindow}
                        contexts={subscription.contexts}
                        contextsEnabled={aiContextsEnabled}
                        prompt={subscription.prompt}
                        windowMode={subscription.ai_prompt_config?.window?.mode}
                        consentBanner={aiConsentMessage}
                        onAddContext={addContext}
                        onRemoveContext={removeContext}
                        onSelectAnalysisWindow={selectAiAnalysisWindow}
                        onSelectExample={selectAiExamplePrompt}
                    />
                </>
            ) : null}
        </div>
    )
}
