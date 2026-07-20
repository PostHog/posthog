import { useActions, useValues } from 'kea'

import { IconWarning } from '@posthog/icons'
import { LemonTag, Spinner } from '@posthog/lemon-ui'

import { CodeSnippet, Language } from 'lib/components/CodeSnippet'

import type { MultiQuestionFormQuestion } from '~/queries/schema/schema-assistant-messages'

import { runStreamLogic } from '../logics/runStreamLogic'
import { MarkdownMessage } from '../messages/MarkdownMessage'
import { getPermissionDisplay } from '../policy/permissionDisplayUtils'
import { isPlanPermissionRequest, mapPermissionOptions, type ApprovalCardOption } from '../policy/permissionUtils'
import type { PermissionRequestRecord } from '../types/streamTypes'
import { isPlanApprovalModeOptionId, PlanApprovalSelector } from './PlanApprovalActions'
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
 * A plan approval (`ExitPlanMode`) renders `/code`'s plan-approval selector (the plan itself is the
 * document card in the thread); every other request reuses the `QuestionField` surface as sandbox
 * questions do, preserving the ACP option ids sent back to the runtime. `allow_always` stays hidden
 * unless filtering would leave no choices.
 *
 * Submitting POSTs through `runStreamLogic.respondToPermission`; the logic's
 * `respondingToPermission` drives the loading/double-submit guard and re-enables the controls when the
 * POST fails (the pending request only clears on success).
 */
export function PermissionInput({ streamKey, request }: PermissionInputProps): JSX.Element {
    const boundLogic = runStreamLogic({ streamKey })
    const { respondToPermission, cancelRun } = useActions(boundLogic)
    const { respondingToPermission } = useValues(boundLogic)

    // A plan approval keeps the product's Auto and Accept edits wire options. If neither is offered,
    // fall through to the generic card so the request stays actionable.
    const planOptions = isPlanPermissionRequest(request) ? mapPermissionOptions(request.options, true) : []
    const planApproveOptions = planOptions.filter(
        (option) => option.decision === 'approved' && isPlanApprovalModeOptionId(option.optionId)
    )
    if (planApproveOptions.length > 0) {
        return (
            <div className="p-3">
                <PlanApprovalSelector
                    approveOptions={planApproveOptions}
                    rejectOption={planOptions.find((option) => option.decision === 'declined')}
                    responding={respondingToPermission}
                    onApprove={(optionId) => respondToPermission({ requestId: request.requestId, optionId })}
                    onReject={(optionId, feedback) =>
                        respondToPermission({ requestId: request.requestId, optionId, customInput: feedback })
                    }
                    onCancel={() => cancelRun()}
                />
            </div>
        )
    }

    // A request whose every option was filtered out (e.g. only `allow_always` without a rememberable
    // preview) must still be answerable — fall back to showing everything. A plan that fell through
    // (unrecognized mode ids) keeps its unfiltered options: its approve choices are `allow_always`-kind
    // and the default filtering would leave a decline-only card.
    const defaultOptions = planOptions.length > 0 ? planOptions : mapPermissionOptions(request.options)
    const mappedOptions = defaultOptions.length > 0 ? defaultOptions : mapPermissionOptions(request.options, true)
    // Only the legacy `reject_with_feedback` kind is feedback-only — reachable solely through the
    // text field. A `reject_once` decline is a plain one-click button with no optional-feedback toggle.
    const feedbackOption = mappedOptions.find((o) => o.requiresFeedback)
    // Every option except the legacy feedback-only one renders as a one-click button.
    const buttonOptions = mappedOptions.filter((o) => !o.requiresFeedback)
    const hasOneClickDecline = buttonOptions.some((option) => option.decision === 'declined')
    const allowFeedback = !!feedbackOption && !hasOneClickDecline

    const prompt = 'Approval required'
    const display = getPermissionDisplay(request)
    const payloadLanguage = display.payload?.trim().match(/^[{[]/) ? Language.JSON : Language.Text
    // The description often just repeats the tool title — render the body only when it adds anything
    // beyond the title line.
    const requestBody = request.description ?? request.title
    const showRequestBody = !!requestBody && requestBody !== display.title

    const handleAnswer = (value: string | string[] | null): void => {
        if (respondingToPermission || value === null || Array.isArray(value)) {
            return
        }
        const selectedOption = buttonOptions.find((option) => option.label === value)
        if (selectedOption) {
            respondToPermission({ requestId: request.requestId, optionId: selectedOption.optionId })
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
            {showRequestBody && (
                <div className="max-h-60 overflow-y-auto text-sm">
                    <MarkdownMessage content={requestBody ?? ''} id={`permission-${request.requestId}`} />
                </div>
            )}

            <div className="flex items-center gap-2 text-sm">
                <IconWarning className="text-warning size-4" />
                <LemonTag size="small" type="warning">
                    Approval
                </LemonTag>
            </div>
            <div className="font-medium text-sm">{prompt}</div>
            {display.title && <div className="text-xs text-secondary">{display.title}</div>}
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
                <>
                    <QuestionField
                        question={toPermissionQuestion(prompt, buttonOptions, allowFeedback)}
                        value={undefined}
                        onAnswer={handleAnswer}
                        onChange={ignoreMultiSelectChange}
                        onSubmit={ignoreMultiSelectSubmit}
                        submitLabel="Send"
                    />
                    {allowFeedback ? (
                        <p className="text-xs text-secondary m-0">
                            Add a note when declining so the agent can adjust and continue, instead of stopping this
                            turn.
                        </p>
                    ) : hasOneClickDecline ? (
                        <p className="text-xs text-secondary m-0">
                            Declining stops this turn. Send a follow-up message to redirect the agent.
                        </p>
                    ) : null}
                </>
            )}
        </div>
    )
}
