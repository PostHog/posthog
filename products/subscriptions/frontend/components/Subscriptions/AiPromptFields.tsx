import type { ReactElement, ReactNode } from 'react'

import { IconLineGraph, IconPulse, IconTrending, IconWarning } from '@posthog/icons'

import { LemonBanner } from 'lib/lemon-ui/LemonBanner'
import { LemonButton } from 'lib/lemon-ui/LemonButton'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { LemonInput } from 'lib/lemon-ui/LemonInput'
import { LemonLabel } from 'lib/lemon-ui/LemonLabel/LemonLabel'
import { LemonSelect } from 'lib/lemon-ui/LemonSelect'
import { LemonTextArea } from 'lib/lemon-ui/LemonTextArea'

import { SubscriptionAIPromptMaxLength } from '~/queries/schema/schema-general'

import type { AIWindowConfigApi, SubscriptionContextApi } from 'products/subscriptions/frontend/generated/api.schemas'

import { SubscriptionContextPicker } from './SubscriptionContextPicker'

export function AiPromptSubscriptionIntroduction(): JSX.Element {
    return (
        <LemonBanner type="info" className="text-sm">
            Tell us what your team wants to achieve. Each report will surface relevant information from your project
            data.
        </LemonBanner>
    )
}

const AI_PROMPT_EXAMPLES: { icon: ReactElement; label: string; prompt: string }[] = [
    {
        icon: <IconTrending />,
        label: 'Improve activation',
        prompt: 'Help us improve activation by finding meaningful changes, likely causes, and the highest-leverage next steps.',
    },
    {
        icon: <IconLineGraph />,
        label: 'Grow feature adoption',
        prompt: 'Help us grow feature adoption by finding underused features, user friction, and opportunities to increase repeat use.',
    },
    {
        icon: <IconTrending />,
        label: 'Increase conversion',
        prompt: 'Help us increase conversion by finding where users drop off, explaining likely causes, and recommending what to test next.',
    },
    {
        icon: <IconPulse />,
        label: 'Improve retention',
        prompt: 'Help us improve retention by identifying behaviors linked to returning users and opportunities to reduce churn.',
    },
    {
        icon: <IconWarning />,
        label: 'Catch regressions',
        prompt: 'Help us catch product regressions early by detecting unusual changes, investigating likely causes, and recommending next steps.',
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

interface AiPromptFieldsProps {
    compactAnalysisWindow?: boolean
    contexts: SubscriptionContextApi[]
    contextsEnabled: boolean
    prompt?: string | null
    windowMode?: AIWindowConfigApi['mode']
    consentBanner?: ReactNode
    onAddContext: (context: SubscriptionContextApi) => void
    onRemoveContext: (context: SubscriptionContextApi) => void
    onSelectAnalysisWindow: (mode: AIWindowConfigApi['mode']) => void
    onSelectExample: (prompt: string, label: string) => void
}

function shouldShowAiPromptExamples(prompt?: string | null): boolean {
    return !prompt?.trim() || AI_PROMPT_EXAMPLES.some((example) => example.prompt === prompt)
}

export function AiPromptFields({
    compactAnalysisWindow = false,
    contexts,
    contextsEnabled,
    prompt,
    windowMode,
    consentBanner,
    onAddContext,
    onRemoveContext,
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
            {contextsEnabled ? (
                <div className="flex flex-col gap-1 min-w-0">
                    <LemonLabel info="Add up to three dashboards or insights to focus this report. Without context, the report chooses relevant project data based on your prompt.">
                        Context
                    </LemonLabel>
                    <SubscriptionContextPicker contexts={contexts} onAdd={onAddContext} onRemove={onRemoveContext} />
                </div>
            ) : null}
            <LemonField
                name="prompt"
                label="What goal should this report help your team achieve?"
                help="We'll use this goal to surface the right information in each report."
            >
                <LemonTextArea
                    placeholder="e.g. Help us improve activation by finding unusual changes and the events behind them."
                    minRows={4}
                    maxLength={SubscriptionAIPromptMaxLength.CHARACTERS}
                />
            </LemonField>
            {showExamples ? (
                <div className="flex flex-col gap-1">
                    <span className="text-xs text-secondary">Start with a goal:</span>
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
        </>
    )
}
