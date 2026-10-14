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
import { LemonButton, LemonCard, LemonDialog, LemonTag, LemonTextArea } from '@posthog/lemon-ui'

import { IconSlack, IconTwilio } from 'lib/lemon-ui/icons'
import { LemonField } from 'lib/lemon-ui/LemonField'
import { humanFriendlyNumber } from 'lib/utils/numbers'
import { urls } from 'scenes/urls'

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
    primary = false,
}: {
    card: SuggestionCard
    surface: WorkflowDataSuggestionsSurface
    primary?: boolean
}): JSX.Element {
    const logic = workflowDataSuggestionsLogic({ surface })
    const { buildingKey, dismissingKey } = useValues(logic)
    const { startSuggestion, dismissSuggestion } = useActions(logic)
    const building = buildingKey === card.key

    const openDismiss = (): void => {
        LemonDialog.openForm({
            title: 'Dismiss this suggestion?',
            description: "PostHog won't suggest it again in this project.",
            initialValues: { reason: '' },
            content: (
                <LemonField name="reason" label="Why not? (optional)">
                    <LemonTextArea
                        placeholder="For example: we already send this from our own app"
                        maxLength={2000}
                        // The dialog form submits on Enter, which would dismiss before the reason is finished.
                        onKeyDown={(e) => e.key === 'Enter' && e.stopPropagation()}
                        data-attr="workflows-data-suggestion-dismiss-reason"
                    />
                </LemonField>
            ),
            primaryButtonProps: { children: 'Dismiss' },
            onSubmit: ({ reason }) => dismissSuggestion(card, reason ?? ''),
        })
    }

    return (
        <LemonCard hoverEffect={false} className="flex h-full flex-col gap-3 p-4">
            <div className="flex flex-wrap items-center gap-2">
                <LemonTag type="highlight" icon={<IconSparkles />}>
                    Made for your data
                </LemonTag>
                {card.draftWorkflowId && <LemonTag type="completion">In draft</LemonTag>}
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
            {card.draftWorkflowId ? (
                <div className="mt-auto flex">
                    <LemonButton
                        type={primary ? 'primary' : 'secondary'}
                        size="small"
                        to={urls.workflow(card.draftWorkflowId, 'workflow')}
                        // pinned: data-attr - autocapture dashboards read it
                        data-attr="workflows-data-suggestion-continue"
                    >
                        Continue setup
                    </LemonButton>
                </div>
            ) : (
                <div className="mt-auto flex flex-wrap gap-2">
                    <LemonButton
                        type={primary ? 'primary' : 'secondary'}
                        size="small"
                        loading={building}
                        disabledReason={
                            buildingKey && !building
                                ? 'Another workflow is being built'
                                : dismissingKey === card.key
                                  ? 'This suggestion is being dismissed'
                                  : undefined
                        }
                        onClick={() => startSuggestion(card)}
                        // pinned: data-attr - autocapture dashboards read it
                        data-attr="workflows-data-suggestion-ai"
                    >
                        {building ? 'Building your workflow' : 'Create workflow'}
                    </LemonButton>
                    <LemonButton
                        type="tertiary"
                        size="small"
                        loading={dismissingKey === card.key}
                        disabledReason={
                            buildingKey || (dismissingKey && dismissingKey !== card.key) ? 'Wait a moment' : undefined
                        }
                        onClick={openDismiss}
                        // pinned: data-attr - autocapture dashboards read it
                        data-attr="workflows-data-suggestion-dismiss"
                    >
                        Dismiss
                    </LemonButton>
                </div>
            )}
        </LemonCard>
    )
}
