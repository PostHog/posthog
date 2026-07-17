import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { MultiQuestionFormQuestion } from '~/queries/schema/schema-assistant-messages'

import { runStreamLogic } from '../logics/runStreamLogic'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { getPermissionDisplay } from '../policy/permissionDisplayUtils'
import { mapPermissionOptions, type ApprovalCardOption } from '../policy/permissionUtils'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { QuestionField } from './QuestionField'

interface PermissionInputProps {
    streamKey: string
    request: PermissionRequestRecord
}

const ignoreMultiSelectChange = (_value: string[]): void => undefined
const ignoreMultiSelectSubmit = (): void => undefined

function toPermissionQuestion(
    prompt: string,
    options: ApprovalCardOption[],
    allowCustomAnswer: boolean
): MultiQuestionFormQuestion {
    return {
        id: 'permission',
        title: 'Approval',
        question: prompt,
        type: 'select',
        options: options.map((option) => ({ value: option.label })),
        allow_custom_answer: allowCustomAnswer,
    }
}

/**
 * Self-contained input-area renderer for an ACP `permission_request` on a sandbox conversation.
 * Reuses the same `QuestionField` surface as sandbox questions while preserving the ACP option ids
 * sent back to the runtime. `allow_always` stays hidden unless filtering would leave no choices.
 *
 * Submitting POSTs through `runStreamLogic.respondToPermission`; the logic's
 * `respondingToPermission` drives the loading/double-submit guard and re-enables the controls when the
 * POST fails (the pending request only clears on success).
 */
export function PermissionInput({ streamKey, request }: PermissionInputProps): JSX.Element {
    const boundLogic = runStreamLogic({ streamKey })
    const { respondToPermission } = useActions(boundLogic)
    const { respondingToPermission, currentMode } = useValues(boundLogic)

    // A request whose every option was filtered out (e.g. only `allow_always` without a rememberable
    // preview) must still be answerable — fall back to showing everything.
    const defaultOptions = mapPermissionOptions(request.options)
    const mappedOptions = defaultOptions.length > 0 ? defaultOptions : mapPermissionOptions(request.options, true)
    // Only the legacy `reject_with_feedback` kind is feedback-only — reachable solely through the
    // text field. A `reject_once` decline is a plain one-click button with no optional-feedback toggle.
    const feedbackOption = mappedOptions.find((o) => o.requiresFeedback)
    // Every option except the legacy feedback-only one renders as a one-click button.
    const buttonOptions = mappedOptions.filter((o) => !o.requiresFeedback)
    const hasOneClickDecline = buttonOptions.some((option) => option.decision === 'declined')
    const allowFeedback = !!feedbackOption && !hasOneClickDecline

    // Plan approvals are raised while the agent is in plan mode — the mode is the grounded signal;
    // `toolCall.kind === 'plan'` covers adapters that tag the request directly.
    const isPlan = currentMode === 'plan' || request.rawToolCall.kind === 'plan'
    const prompt = isPlan ? 'Approve this plan?' : 'Approval required'
    const display = getPermissionDisplay(request)
    const payloadLanguage = display.payload?.trim().match(/^[{[]/) ? Language.JSON : Language.Text

    const respond = (optionId: string): void => {
        if (respondingToPermission) {
            return
        }
        respondToPermission({ requestId: request.requestId, optionId })
    }

    const handleAnswer = (value: string | string[] | null): void => {
        if (respondingToPermission || value === null || Array.isArray(value)) {
            return
        }
        const selectedOption = buttonOptions.find((option) => option.label === value)
        if (selectedOption) {
            respond(selectedOption.optionId)
            return
        }
        if (allowFeedback && feedbackOption) {
            respondToPermission({
                requestId: request.requestId,
                optionId: feedbackOption.optionId,
                customInput: value,
            })
        }
    }

    return (
        <div className="flex flex-col gap-2 p-3">
            <div className="flex items-center gap-2 text-sm">
                <IconWarning className="text-warning size-4" />
                <LemonTag size="small" type="warning">
                    {isPlan ? 'Plan approval' : 'Approval'}
                </LemonTag>
            </div>
            <div className="font-medium text-sm">{prompt}</div>
            {display.title && <div className="text-xs text-secondary">{display.title}</div>}
            {(request.title || request.description) && (
                <div className="max-h-60 overflow-y-auto text-sm">
                    <MarkdownMessage
                        content={request.description ?? request.title ?? ''}
                        id={`permission-${request.requestId}`}
                    />
                </div>
            )}
            {display.payload && (
                <div className="max-h-60 overflow-y-auto">
                    <CodeSnippet language={payloadLanguage} className="text-xs" compact>
                        {display.payload}
                    </CodeSnippet>
                </div>
            )}
            {respondingToPermission ? (
                <div className="flex items-center gap-2 text-muted pt-1">
                    <Spinner className="size-4" />
                    <span>Sending response…</span>
                </div>
            ) : (
                <QuestionField
                    question={toPermissionQuestion(prompt, buttonOptions, allowFeedback)}
                    value={undefined}
                    onAnswer={handleAnswer}
                    onChange={ignoreMultiSelectChange}
                    onSubmit={ignoreMultiSelectSubmit}
                    submitLabel="Send"
                />
            )}
        </div>
    )
}
