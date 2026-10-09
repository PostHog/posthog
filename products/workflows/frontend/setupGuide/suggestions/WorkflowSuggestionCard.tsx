import { useActions, useValues } from 'kea'

import {
    IconBolt,
    IconClock,
    IconDecisionTree,
    IconHourglass,
    IconLetter,
    IconNotification,
    IconPercentage,
    IconSparkles,
    IconWebhooks,
} from '@posthog/icons'
import { LemonButton, LemonCard, LemonTag } from '@posthog/lemon-ui'

import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'
import { humanFriendlyNumber } from 'lib/utils/numbers'

import type { SuggestionCard, SuggestionStepKind } from './suggestionCards'
import { WorkflowDataSuggestionsSurface, workflowDataSuggestionsLogic } from './workflowDataSuggestionsLogic'

const STEP_DISPLAY: Record<SuggestionStepKind | 'trigger', { label: string; icon: JSX.Element }> = {
    trigger: { label: 'Trigger', icon: <IconBolt /> },
    email: { label: 'Email', icon: <IconLetter /> },
    delay: { label: 'Wait', icon: <IconClock /> },
    sms: { label: 'SMS', icon: <IconTwilio /> },
    push: { label: 'Push', icon: <IconNotification /> },
    slack: { label: 'Slack', icon: <IconSlack /> },
    webhook: { label: 'Webhook', icon: <IconWebhooks /> },
    wait_until: { label: 'Wait until', icon: <IconHourglass /> },
    branch: { label: 'Branch', icon: <IconDecisionTree /> },
    split: { label: 'Split', icon: <IconPercentage /> },
    action: { label: 'Action', icon: <IconBolt /> },
}

// A plan can have up to 20 steps, so the card shows the first few and a count of the rest.
const MAX_STEP_CHIPS = 6

export function WorkflowSuggestionCard({
    card,
    surface,
}: {
    card: SuggestionCard
    surface: WorkflowDataSuggestionsSurface
}): JSX.Element {
    const logic = workflowDataSuggestionsLogic({ surface })
    const { buildingKey } = useValues(logic)
    const { startSuggestion } = useActions(logic)
    const building = buildingKey === card.key

    return (
        <LemonCard hoverEffect={false} className="flex h-full flex-col gap-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
                {card.source === 'ai' && (
                    <LemonTag type="highlight" icon={<IconSparkles />}>
                        Made for your data
                    </LemonTag>
                )}
                <span className="inline-flex min-w-0 items-center gap-1 text-xs text-secondary">
                    <code className="truncate text-primary">{card.triggerEvent}</code>
                    <span translate="no">{humanFriendlyNumber(card.weeklyCount)}</span>
                    <span>this week</span>
                </span>
            </div>
            <div className="flex flex-col gap-1">
                <h4 className="mb-0 text-base font-semibold">{card.title}</h4>
                <p className="mb-0 text-sm text-secondary">{card.description}</p>
            </div>
            <ol className="m-0 flex list-none flex-wrap items-center gap-1 p-0" aria-label="Workflow steps">
                {(['trigger', ...card.steps.slice(0, MAX_STEP_CHIPS)] as const).map((step, index) => (
                    <li
                        key={`${step}-${index}`}
                        className="inline-flex items-center gap-1 rounded border bg-surface-secondary px-1.5 py-0.5 text-xs"
                    >
                        {STEP_DISPLAY[step].icon}
                        {STEP_DISPLAY[step].label}
                    </li>
                ))}
                {card.steps.length > MAX_STEP_CHIPS && (
                    <li className="text-xs text-secondary">+{card.steps.length - MAX_STEP_CHIPS} more</li>
                )}
            </ol>
            <div className="mt-auto flex">
                <LemonButton
                    type="primary"
                    size="small"
                    loading={building}
                    disabledReason={buildingKey && !building ? 'Another workflow is being built' : undefined}
                    onClick={() => startSuggestion(card)}
                    data-attr={`workflows-data-suggestion-${card.source}`}
                >
                    {building ? 'Building your workflow' : 'Start with this'}
                </LemonButton>
            </div>
        </LemonCard>
    )
}
