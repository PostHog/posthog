import { useActions, useValues } from 'kea'
import { useId } from 'react'

import { IconSparkles } from '@posthog/icons'
import { LemonBanner, LemonButton, LemonLabel, LemonSelect, LemonTextArea } from '@posthog/lemon-ui'

import { AIConsentPopoverWrapper } from 'scenes/settings/organization/AIConsentPopoverWrapper'

import { InvestigationQueryAssistantProps, investigationQueryAssistantLogic } from './investigationQueryAssistantLogic'
import { InvestigationQueryProposal } from './InvestigationQueryProposal'
import { INVESTIGATION_QUERY_TASKS } from './queryAssistantHelpers'

export function InvestigationQueryComposer(props: InvestigationQueryAssistantProps): JSX.Element {
    const fieldId = useId()
    const logic = investigationQueryAssistantLogic(props)
    const { prompt, task, targetId, request, proposal, error } = useValues(logic)
    const { setPrompt, setTask, setTargetId, askAssistant, acceptProposal, dismissProposal } = useActions(logic)
    const pending = !!request && !proposal
    const ask = (): void => {
        askAssistant()
    }
    return (
        <div className="flex flex-col gap-3 border rounded p-4 mt-4" data-attr="investigation-query-assistant">
            <div className="flex items-center gap-2">
                <IconSparkles />
                <h3 className="text-base m-0">Build evidence with AI</h3>
            </div>
            <p className="text-sm text-secondary mb-0">
                Describe what you want to measure. AI can find the right events and tables, write SQL, and help refine
                it.
            </p>
            <div className="flex flex-wrap gap-2">
                <LemonSelect
                    value={task}
                    onChange={setTask}
                    options={Object.entries(INVESTIGATION_QUERY_TASKS).map(([value, { label }]) => ({
                        value: value as typeof task,
                        label,
                    }))}
                    data-attr="investigation-query-task"
                />
                <LemonSelect
                    value={targetId ?? ''}
                    onChange={(value) => setTargetId(value || null)}
                    options={[
                        { value: '', label: 'New evidence' },
                        ...props.document.evidence
                            .filter((item) => item.kind === 'query')
                            .map((item) => ({
                                value: item.id,
                                label: `E${item.reference}: ${item.title || 'Untitled evidence'}`,
                            })),
                    ]}
                    data-attr="investigation-query-target"
                />
            </div>
            <div>
                <LemonLabel htmlFor={`${fieldId}-request`}>What should the query answer?</LemonLabel>
                <LemonTextArea
                    id={`${fieldId}-request`}
                    value={prompt}
                    onChange={setPrompt}
                    maxLength={2000}
                    minRows={2}
                    placeholder="For example, compare signup-to-activation conversion this month and last month, grouped by acquisition channel."
                    data-attr="investigation-query-request"
                />
            </div>
            <div className="flex flex-wrap gap-2">
                {[
                    [
                        'compare',
                        'Compare before and after',
                        'Compare the metric before and after the change. Check that both cohorts have had the same time to convert.',
                    ],
                    [
                        'breakdown',
                        'Find affected segments',
                        'Which segments account for the change? Discover available properties and compare segment sizes and rates.',
                    ],
                    [
                        'hypothesis',
                        'Test an explanation',
                        'Which query would best distinguish the competing explanations in this investigation?',
                    ],
                ].map(([nextTask, label, nextPrompt]) => (
                    <LemonButton
                        key={nextTask}
                        type="secondary"
                        size="xsmall"
                        onClick={() => {
                            setTask(nextTask as typeof task)
                            setPrompt(nextPrompt)
                        }}
                        data-attr={`investigation-query-suggestion-${nextTask}`}
                    >
                        {label}
                    </LemonButton>
                ))}
            </div>
            <div className="flex flex-wrap items-center gap-2">
                <AIConsentPopoverWrapper onApprove={ask}>
                    <LemonButton
                        type="primary"
                        size="small"
                        icon={<IconSparkles />}
                        onClick={ask}
                        data-attr="investigation-draft-query"
                        disabledReason={
                            pending
                                ? 'Continue the current request in PostHog AI, or dismiss it to start another.'
                                : undefined
                        }
                    >
                        Ask AI
                    </LemonButton>
                </AIConsentPopoverWrapper>
                {pending && (
                    <LemonButton
                        type="tertiary"
                        size="small"
                        onClick={dismissProposal}
                        data-attr="investigation-dismiss-query-request"
                    >
                        Dismiss request
                    </LemonButton>
                )}
            </div>
            {pending && (
                <LemonBanner type="info">
                    {request.task === 'explain'
                        ? 'Continue in PostHog AI to read the explanation.'
                        : 'Continue in PostHog AI. After the assistant tests its suggested query, it appears here for review.'}
                </LemonBanner>
            )}
            {error && <LemonBanner type="error">{error}</LemonBanner>}
            {request && proposal && (
                <InvestigationQueryProposal
                    document={props.document}
                    request={request}
                    proposal={proposal}
                    onAccept={acceptProposal}
                    onDismiss={dismissProposal}
                />
            )}
        </div>
    )
}
