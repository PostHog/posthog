import { JSX, useMemo, useState } from 'react'

import { LemonButton } from '@posthog/lemon-ui'

import { IconCheckCircle, IconChevronDown, IconChevronRight, IconList } from '../primitives/icons'
import { MarkdownMessage } from '../primitives/MarkdownMessage'
import { type ToolViewProps, useToolCallStatus } from '../primitives/toolCallUtils'

/**
 * Read-only render of the plan markdown in a bordered, scrollable box, mirroring
 * the upstream `PlanContent` component (which depended on react-markdown and a
 * fullscreen portal — neither is available here).
 */
function PlanContent({ plan }: { plan: string }): JSX.Element {
    return (
        <div className="relative max-h-[50vh] max-w-[750px] overflow-y-auto rounded-lg border-2 border-accent bg-accent-highlight p-4">
            <MarkdownMessage content={plan} />
        </div>
    )
}

export function PlanApprovalView({ toolCall, turnCancelled, turnComplete }: ToolViewProps): JSX.Element | null {
    const { content } = toolCall
    const { isComplete, wasCancelled } = useToolCallStatus(toolCall.status, turnCancelled, turnComplete)
    const [isPlanExpanded, setIsPlanExpanded] = useState(false)

    const planText = useMemo(() => {
        const rawPlan = (toolCall.rawInput as { plan?: string } | undefined)?.plan
        if (rawPlan) {
            return rawPlan
        }

        if (!content || content.length === 0) {
            return null
        }
        const textContent = content.find((c) => c.type === 'content')
        if (textContent && 'content' in textContent) {
            const inner = textContent.content as { type?: string; text?: string } | undefined
            if (inner?.type === 'text' && inner.text) {
                return inner.text
            }
        }
        return null
    }, [content, toolCall.rawInput])

    const showResult = isComplete || wasCancelled
    const canTogglePlan = showResult && !!planText

    if (!planText && !showResult) {
        return null
    }

    const statusContent = isComplete ? (
        <>
            <IconCheckCircle className="text-success" style={{ fontSize: 14 }} />
            <span className="text-[13px] text-success">Plan approved — proceeding with implementation</span>
        </>
    ) : wasCancelled ? (
        <span className="text-[13px] text-muted">(Plan rejected)</span>
    ) : null

    return (
        <div className="my-3">
            {!showResult && planText && (
                <div className="flex flex-col gap-2">
                    <div className="flex items-center gap-2">
                        <IconList className="text-accent" style={{ fontSize: 14 }} />
                        <span className="text-[13px] text-accent">Plan</span>
                    </div>
                    <PlanContent plan={planText} />
                    {/* Read-only transcript: approval/rejection happened upstream — these are inert. */}
                    <div className="flex items-center gap-2">
                        <LemonButton type="primary" size="small" disabledReason="Read-only transcript">
                            Approve
                        </LemonButton>
                        <LemonButton type="secondary" size="small" disabledReason="Read-only transcript">
                            Reject
                        </LemonButton>
                    </div>
                </div>
            )}

            {showResult && (
                <div>
                    {canTogglePlan ? (
                        <button
                            type="button"
                            onClick={() => setIsPlanExpanded((v) => !v)}
                            aria-expanded={isPlanExpanded}
                            className="flex items-center gap-2 rounded-sm px-1 text-left hover:bg-accent-highlight"
                        >
                            {isPlanExpanded ? (
                                <IconChevronDown className="text-muted" style={{ fontSize: 12 }} />
                            ) : (
                                <IconChevronRight className="text-muted" style={{ fontSize: 12 }} />
                            )}
                            {statusContent}
                            <span className="text-[13px] text-muted">
                                · {isPlanExpanded ? 'hide plan' : 'show plan'}
                            </span>
                        </button>
                    ) : (
                        <div className="flex items-center gap-2 px-1">{statusContent}</div>
                    )}

                    {canTogglePlan && isPlanExpanded && (
                        <div className="mt-2">
                            <PlanContent plan={planText} />
                        </div>
                    )}
                </div>
            )}
        </div>
    )
}
