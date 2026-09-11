import type { ReactElement, ReactNode } from 'react'

import { IconLineGraph, IconPulse, IconTrending, IconWarning } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonCollapse } from 'lib/lemon-ui/LemonCollapse'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonSwitch } from 'lib/lemon-ui/LemonSwitch'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { SubscriptionAIPromptMaxLength } from '~/queries/schema/schema-general'
import type { SubscriptionType } from '~/types'

import type { AIWindowConfigApi, DeliveryConfigApi } from 'products/subscriptions/frontend/generated/api.schemas'

import {
    type AiSubscriptionDisplayOption,
    getAiSubscriptionDisplayOptionState,
    getAiSubscriptionDisplaySummary,
    updateAiSubscriptionDisplayOption,
} from './utils'

export function AiPromptSubscriptionIntroduction(): JSX.Element {
    return (
        <LemonBanner type="info" className="text-sm">
            Tell us what you want to know. We'll surface the relevant information from your project data in each report.
        </LemonBanner>
    )
}

const AI_PROMPT_EXAMPLES: { icon: ReactElement; label: string; prompt: string }[] = [
    {
        icon: <IconLineGraph />,
        label: 'Top events',
        prompt: 'Top 5 events by volume, with counts and unique users for each.',
    },
    {
        icon: <IconTrending />,
        label: 'Period-over-period growth',
        prompt: 'For the top 10 events by volume, compare the current period vs the previous one and rank by growth rate. Flag any event that more than doubled or halved.',
    },
    {
        icon: <IconPulse />,
        label: 'Health check',
        prompt: 'Health check: total event volume and unique active users, and how each compares to the previous period.',
    },
    {
        icon: <IconWarning />,
        label: 'Tracking gaps',
        prompt: 'Which events we normally track received no data? List them so I can catch broken instrumentation.',
    },
]

const AI_WINDOW_MODE_OPTIONS = [
    {
        value: 'since_last_sent' as const,
        label: 'Since last report',
        labelInMenu: (
            <div className="flex flex-col">
                <span>Since last report</span>
                <span className="text-xs text-secondary">
                    Everything new since the previous scheduled report (no gaps)
                </span>
            </div>
        ),
    },
    {
        value: 'last_n_days' as const,
        label: 'Last N days',
        labelInMenu: (
            <div className="flex flex-col">
                <span>Last N days</span>
                <span className="text-xs text-secondary">A fixed trailing window, e.g. always the last 7 days</span>
            </div>
        ),
    },
    {
        value: 'days_ago_range' as const,
        label: 'Between X and Y days ago',
        labelInMenu: (
            <div className="flex flex-col">
                <span>Between X and Y days ago</span>
                <span className="text-xs text-secondary">An explicit historical range, e.g. 14 to 7 days ago</span>
            </div>
        ),
    },
]

const AI_DISPLAY_OPTIONS: { option: AiSubscriptionDisplayOption; label: string; description: string }[] = [
    {
        option: 'images',
        label: 'Chart images',
        description: 'Include chart images when the report generates them.',
    },
    {
        option: 'feedback',
        label: 'Feedback buttons',
        description: 'Ask recipients whether the report was useful.',
    },
    {
        option: 'posthog_actions',
        label: 'PostHog links and suggestions',
        description:
            'Include a link to manage the subscription. Slack reports also suggest asking @PostHog a follow-up question.',
    },
]

interface AiPromptFieldsProps {
    compactAnalysisWindow?: boolean
    prompt?: string | null
    targetType?: SubscriptionType['target_type'] | null
    windowMode?: AIWindowConfigApi['mode']
    consentBanner?: ReactNode
    onSelectAnalysisWindow: (mode: AIWindowConfigApi['mode']) => void
    onSelectExample: (prompt: string, label: string) => void
}

function shouldShowAiPromptExamples(prompt?: string | null): boolean {
    return !prompt?.trim() || AI_PROMPT_EXAMPLES.some((example) => example.prompt === prompt)
}

export function AiPromptFields({
    compactAnalysisWindow = false,
    prompt,
    targetType,
    windowMode,
    consentBanner,
    onSelectAnalysisWindow,
    onSelectExample,
}: AiPromptFieldsProps): JSX.Element {
    const showExamples = shouldShowAiPromptExamples(prompt)
    const analysisWindowClassName = compactAnalysisWindow ? 'w-80 max-w-full' : undefined

    return (
        <>
            {consentBanner ? (
                <LemonBanner type="warning" className="text-sm">
                    {consentBanner}
                </LemonBanner>
            ) : null}
            <LemonField
                name="prompt"
                label="What do you want to know?"
                help="We'll use this question to surface the right information in each report."
            >
                <LemonTextArea
                    placeholder="e.g. Which events grew the most week-over-week? Highlight any unusual spikes."
                    minRows={4}
                    maxLength={SubscriptionAIPromptMaxLength.CHARACTERS}
                />
            </LemonField>
            {showExamples ? (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-secondary">Try one of these questions:</span>
                    <div className="flex flex-wrap gap-1">
                        {AI_PROMPT_EXAMPLES.map((example) => (
                            <LemonButton
                                key={example.label}
                                size="xsmall"
                                type="secondary"
                                icon={example.icon}
                                onClick={() => onSelectExample(example.prompt, example.label)}
                            >
                                {example.label}
                            </LemonButton>
                        ))}
                    </div>
                </div>
            ) : null}
            <LemonField
                name={['ai_prompt_config', 'window', 'mode']}
                label="What time period should we look at?"
                help="This controls the project data included in each report."
            >
                {({ value }) => (
                    <LemonSelect
                        options={AI_WINDOW_MODE_OPTIONS}
                        value={value}
                        onChange={(mode) => mode && onSelectAnalysisWindow(mode)}
                        className={analysisWindowClassName}
                    />
                )}
            </LemonField>
            {windowMode === 'last_n_days' ? (
                <LemonField name={['ai_prompt_config', 'window', 'start_days_ago']} label="Number of days to analyze">
                    {({ value, onChange }) => (
                        <div className="flex items-center gap-2">
                            <LemonInput
                                type="number"
                                min={1}
                                max={365}
                                value={value ?? undefined}
                                onChange={(newValue) => onChange(newValue ?? null)}
                                className="w-24"
                            />
                            <span>days back from each run</span>
                        </div>
                    )}
                </LemonField>
            ) : null}
            {windowMode === 'days_ago_range' ? (
                <div className="flex items-start gap-2">
                    <LemonField name={['ai_prompt_config', 'window', 'start_days_ago']} label="From (days ago)">
                        {({ value, onChange }) => (
                            <LemonInput
                                type="number"
                                min={1}
                                max={365}
                                value={value ?? undefined}
                                onChange={(newValue) => onChange(newValue ?? null)}
                                className="w-24"
                            />
                        )}
                    </LemonField>
                    <LemonField name={['ai_prompt_config', 'window', 'end_days_ago']} label="To (days ago)">
                        {({ value, onChange }) => (
                            <LemonInput
                                type="number"
                                min={0}
                                max={365}
                                value={value ?? undefined}
                                onChange={(newValue) => onChange(newValue ?? null)}
                                className="w-24"
                            />
                        )}
                    </LemonField>
                </div>
            ) : null}
            <LemonField name="delivery_config">
                {({ value, onChange }) => {
                    const deliveryConfig = value as DeliveryConfigApi | undefined
                    const displaySummary = getAiSubscriptionDisplaySummary(deliveryConfig, targetType)

                    return (
                        <LemonCollapse
                            className="bg-bg-light"
                            panels={[
                                {
                                    key: 'advanced',
                                    header: {
                                        children: (
                                            <div className="flex min-w-0 w-full items-start justify-between gap-2 py-1">
                                                <div className="min-w-0">
                                                    <div className="font-semibold">Advanced delivery options</div>
                                                    <div className="text-secondary text-sm font-normal">
                                                        Choose optional content included in each delivery.
                                                    </div>
                                                </div>
                                                <div className="shrink-0 text-tertiary text-xs font-normal">
                                                    {displaySummary}
                                                </div>
                                            </div>
                                        ),
                                    },
                                    content: (
                                        <div className="flex flex-col gap-2">
                                            <p className="text-secondary text-sm mb-1">
                                                The report title and AI-written answer are always included.
                                            </p>
                                            {AI_DISPLAY_OPTIONS.map(({ option, label, description }) => {
                                                const state = getAiSubscriptionDisplayOptionState(
                                                    deliveryConfig,
                                                    option
                                                )

                                                return (
                                                    <LemonSwitch
                                                        key={option}
                                                        checked={state}
                                                        onChange={(enabled) =>
                                                            onChange(
                                                                updateAiSubscriptionDisplayOption(
                                                                    deliveryConfig,
                                                                    option,
                                                                    enabled
                                                                )
                                                            )
                                                        }
                                                        bordered
                                                        fullWidth
                                                        data-attr={`ai-subscription-display-${option.replace('_', '-')}`}
                                                        label={
                                                            <div className="flex flex-col gap-1 py-1">
                                                                <div className="leading-tight">{label}</div>
                                                                <div className="text-xs text-secondary font-normal leading-tight">
                                                                    {description}
                                                                </div>
                                                            </div>
                                                        }
                                                    />
                                                )
                                            })}
                                        </div>
                                    ),
                                },
                            ]}
                        />
                    )
                }}
            </LemonField>
        </>
    )
}
